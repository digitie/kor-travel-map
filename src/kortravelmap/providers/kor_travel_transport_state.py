"""``kortravelmap.providers.kor_travel_transport_state`` — transport export → Valkey 상태 값 (ADR-114).

``providers.kor_travel_transport``가 엄격히 파싱한 transport export 행을 ``dto.transport_state`` 값과
:class:`~kortravelmap.infra.valkey_state.StateItem`으로 바꾼다. HTTP는 Dagster fetcher가, 저장은
``infra.valkey_state``가 한다 — 이 모듈은 변환과 데이터셋 정의(이름·교체 거부 기준·신선도 상한)만 갖는다.

**식별자는 PG 변환과 같은 규칙이다**(ADR-114 D1). kind·category·``source_type``·자연키는
``providers.opinet``·``krex``·``krairport``와 같고, ``bjd_code``만 ``None``으로 고정한다 — transport
export에 VWorld 행정 블록(ADR-114 결정 6)이 실려도 id가 바뀌지 않게 하려는 것이다. 자연키·제목 규칙은
``krex``의 공개 함수를 그대로 부른다(복제하지 않는다).

이 모듈은 geo를 부르지 않는다. 행정 코드는 export가 실어 줄 때까지 비어 있다.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from typing import Final

from pydantic import BaseModel

from kortravelmap.category import mapbox_maki_icon_or_none
from kortravelmap.core.address import normalize_korean_text, normalize_phone_number
from kortravelmap.core.ids import make_feature_id
from kortravelmap.dto import FeatureKind
from kortravelmap.dto.transport_state import (
    AirportState,
    FuelPriceState,
    FuelStationState,
    HighwayIncidentState,
    RestAreaFuelPriceState,
    RestAreaState,
    StateAddress,
    StateCoordinate,
)
from kortravelmap.infra.valkey_state import ShrinkGuard, StateItem
from kortravelmap.providers.kor_travel_transport import (
    DATASET_KEY_AIRPORTS,
    DATASET_KEY_FUEL_STATIONS,
    DATASET_KEY_HIGHWAY_INCIDENTS,
    DATASET_KEY_REST_AREA_FUEL_PRICES,
    DATASET_KEY_REST_AREAS,
    INCIDENT_SET_MAX_AGE,
    KOR_TRAVEL_TRANSPORT_PROVIDER_NAME,
    TransportAirport,
    TransportExportContractError,
    TransportFuelStation,
    TransportHighwayIncident,
    TransportRestArea,
    TransportRestAreaFuelPrice,
)
from kortravelmap.providers.krairport import AIRPORT_CATEGORY, AIRPORT_MARKER_COLOR
from kortravelmap.providers.krex import (
    REST_AREA_CATEGORY,
    REST_AREA_MARKER_COLOR,
    REST_AREA_MARKER_ICON,
    TRAFFIC_NOTICE_CATEGORY,
    TRAFFIC_NOTICE_MARKER_COLOR,
    TRAFFIC_NOTICE_MARKER_ICON,
    fuel_price_match_key,
    parse_krex_occurrence,
    rest_area_natural_key,
    safe_notice_type,
    synthesize_notice_title,
    traffic_notice_natural_key,
)
from kortravelmap.providers.opinet import (
    OPINET_PRODUCT_KEY_MAP,
    OPINET_PRODUCT_NAME_KO,
    OPINET_STATION_CATEGORY,
    OPINET_STATION_MARKER_COLOR,
    OPINET_STATION_MARKER_ICON,
)

__all__ = [
    "AIRPORT_MARKER_ICON",
    "DATASET_AIRPORTS",
    "DATASET_FUEL_STATIONS",
    "DATASET_HIGHWAY_INCIDENTS",
    "DATASET_REST_AREAS",
    "DATASET_REST_AREA_FUEL_PRICES",
    "KOREA_LAT_RANGE",
    "KOREA_LON_RANGE",
    "TRANSPORT_STATE_DATASETS",
    "TransportStateDataset",
    "airport_state",
    "fuel_station_state",
    "highway_incident_state",
    "rest_area_fuel_price_state",
    "rest_area_state",
    "state_coordinate",
    "to_state_item",
]

AIRPORT_MARKER_ICON: Final[str] = mapbox_maki_icon_or_none(AIRPORT_CATEGORY) or "airport"
"""공항 maki icon. PG 경로(``krairport``)와 같은 계산이다."""

KOREA_LON_RANGE: Final[tuple[float, float]] = (120.0, 135.0)
KOREA_LAT_RANGE: Final[tuple[float, float]] = (30.0, 45.0)
"""좌표로 받아들이는 범위(ADR-114 D1). 밖이거나 (0, 0)이면 좌표 없음으로 둔다."""


@dataclass(frozen=True, slots=True)
class TransportStateDataset:
    """Valkey 상태 데이터셋 하나의 정의(ADR-114 D1·D4·D5)."""

    name: str
    """Valkey 키의 ``{ds}``."""
    guard: ShrinkGuard
    max_age: timedelta
    """이보다 오래된 세대는 응답에 ``stale=true``."""


DATASET_FUEL_STATIONS: Final[TransportStateDataset] = TransportStateDataset(
    name="transport.fuel_stations",
    guard=ShrinkGuard(min_ratio=0.9, baseline_min=100, min_count=10_000),
    max_age=timedelta(hours=48),
)
DATASET_REST_AREAS: Final[TransportStateDataset] = TransportStateDataset(
    name="transport.rest_areas",
    guard=ShrinkGuard(min_ratio=0.9, baseline_min=20, min_count=100),
    max_age=timedelta(days=8),
)
DATASET_REST_AREA_FUEL_PRICES: Final[TransportStateDataset] = TransportStateDataset(
    name="transport.rest_area_fuel_prices",
    guard=ShrinkGuard(min_ratio=0.8, baseline_min=20, min_count=80),
    max_age=timedelta(hours=48),
)
DATASET_HIGHWAY_INCIDENTS: Final[TransportStateDataset] = TransportStateDataset(
    name="transport.highway_incidents",
    guard=ShrinkGuard(min_ratio=0.25, baseline_min=20, allow_empty_below_baseline=True),
    max_age=INCIDENT_SET_MAX_AGE,
)
DATASET_AIRPORTS: Final[TransportStateDataset] = TransportStateDataset(
    name="transport.airports",
    guard=ShrinkGuard(min_ratio=0.8, baseline_min=5, min_count=10),
    max_age=timedelta(days=8),
)

TRANSPORT_STATE_DATASETS: Final[tuple[TransportStateDataset, ...]] = (
    DATASET_FUEL_STATIONS,
    DATASET_REST_AREAS,
    DATASET_REST_AREA_FUEL_PRICES,
    DATASET_HIGHWAY_INCIDENTS,
    DATASET_AIRPORTS,
)


def _source_type(dataset_key: str) -> str:
    return f"{KOR_TRAVEL_TRANSPORT_PROVIDER_NAME}:{dataset_key}"


def state_coordinate(lon: float | None, lat: float | None) -> StateCoordinate | None:
    """한국 주변 범위 안의 좌표만 받는다. 밖이거나 (0, 0)·NaN이면 ``None``."""
    if lon is None or lat is None:
        return None
    if not (KOREA_LON_RANGE[0] <= lon <= KOREA_LON_RANGE[1]):
        return None
    if not (KOREA_LAT_RANGE[0] <= lat <= KOREA_LAT_RANGE[1]):
        return None
    return StateCoordinate(lon=lon, lat=lat)


def _price_float(value: Decimal | None) -> float | None:
    return float(value) if value is not None else None


def _phone(value: str | None) -> str | None:
    return normalize_phone_number(value) if value else None


def fuel_station_state(station: TransportFuelStation) -> FuelStationState:
    """주유소 + 유종별 최신가. id는 PG의 주유소 **place** feature와 같은 입력(``bjd_code=None``)."""
    feature_id = make_feature_id(
        bjd_code=None,
        kind=FeatureKind.PLACE.value,
        category=OPINET_STATION_CATEGORY,
        source_type=_source_type(DATASET_KEY_FUEL_STATIONS),
        source_natural_key=station.uni_id,
    )
    prices = [
        FuelPriceState(
            product_key=OPINET_PRODUCT_KEY_MAP.get(
                price.product_code.strip(), price.product_code.strip().lower()
            ),
            product_code=price.product_code.strip(),
            product_name=OPINET_PRODUCT_NAME_KO.get(
                OPINET_PRODUCT_KEY_MAP.get(price.product_code.strip(), "")
            ),
            price=_price_float(price.price),
            provider_updated_at=price.provider_updated_at,
            collected_at=price.collected_at,
        )
        for price in station.prices
    ]
    road = normalize_korean_text(station.address_road)
    jibun = normalize_korean_text(station.address_jibun)
    return FuelStationState(
        feature_id=feature_id,
        category=OPINET_STATION_CATEGORY,
        marker_icon=OPINET_STATION_MARKER_ICON,
        marker_color=OPINET_STATION_MARKER_COLOR,
        name=normalize_korean_text(station.name) or station.name,
        natural_key=station.uni_id,
        coord=state_coordinate(station.lon, station.lat),
        address=StateAddress(road=road or jibun, jibun=jibun),
        phone=_phone(station.tel),
        brand_code=station.brand,
        brand_name=station.brand_name,
        is_self=station.is_self,
        is_24h=station.is_24h,
        has_carwash=station.has_carwash,
        has_maintenance=station.has_maintenance,
        has_cvs=station.has_cvs,
        lpg_available=station.lpg_yn,
        prices=prices,
        source_last_seen_at=station.last_seen_at,
    )


def rest_area_state(area: TransportRestArea) -> RestAreaState:
    """휴게소. transport 자연키가 Map 규칙과 다르면 계약 위반이다(PG 경로와 같은 검사)."""
    natural_key = rest_area_natural_key(area)
    if area.natural_key != natural_key:
        raise TransportExportContractError(
            f"rest-areas.item.natural_key: 휴게소 자연키 불일치 "
            f"(transport={area.natural_key!r}, map={natural_key!r})."
        )
    feature_id = make_feature_id(
        bjd_code=None,
        kind=FeatureKind.PLACE.value,
        category=REST_AREA_CATEGORY,
        source_type=_source_type(DATASET_KEY_REST_AREAS),
        source_natural_key=natural_key,
    )
    return RestAreaState(
        feature_id=feature_id,
        category=REST_AREA_CATEGORY,
        marker_icon=REST_AREA_MARKER_ICON,
        marker_color=REST_AREA_MARKER_COLOR,
        name=normalize_korean_text(area.name) or area.name,
        natural_key=natural_key,
        route_name=area.route_name,
        direction=area.direction,
        coord=state_coordinate(area.lon, area.lat),
        address=StateAddress(),
        phone=_phone(area.phone_number),
        has_gas_station=area.has_gas_station,
        has_lpg_station=area.has_lpg_station,
        has_ev_charger=area.has_ev_charger,
    )


def rest_area_fuel_price_state(record: TransportRestAreaFuelPrice) -> RestAreaFuelPriceState:
    """휴게소 주유소 최신가. id는 PG의 휴게소 유가 price feature와 같은 입력이다."""
    service_area_code = record.service_area_code.strip()
    if not service_area_code:
        raise TransportExportContractError(
            "rest-area-fuel-prices.item.service_area_code: 비어 있다."
        )
    feature_id = make_feature_id(
        bjd_code=None,
        kind=FeatureKind.PRICE.value,
        category=REST_AREA_CATEGORY,
        source_type=_source_type(DATASET_KEY_REST_AREA_FUEL_PRICES),
        source_natural_key=service_area_code,
    )
    return RestAreaFuelPriceState(
        feature_id=feature_id,
        service_area_code=service_area_code,
        service_area_name=normalize_korean_text(record.service_area_name)
        or record.service_area_name,
        match_key=fuel_price_match_key(record),
        route_name=record.route_name,
        direction=record.direction,
        oil_company=record.oil_company,
        phone=_phone(record.phone_number),
        address=normalize_korean_text(record.address),
        gasoline_price=record.gasoline_price,
        diesel_price=record.diesel_price,
        lpg_price=record.lpg_price,
        observed_at=record.observed_at,
    )


def highway_incident_state(incident: TransportHighwayIncident) -> HighwayIncidentState:
    """활성 돌발. 자연키·제목·유형은 PG 변환(``krex``)과 같은 함수로 만든다."""
    natural_key = traffic_notice_natural_key(incident)
    feature_id = make_feature_id(
        bjd_code=None,
        kind=FeatureKind.NOTICE.value,
        category=TRAFFIC_NOTICE_CATEGORY,
        source_type=_source_type(DATASET_KEY_HIGHWAY_INCIDENTS),
        source_natural_key=natural_key,
    )
    title = synthesize_notice_title(incident)
    return HighwayIncidentState(
        feature_id=feature_id,
        category=TRAFFIC_NOTICE_CATEGORY,
        marker_icon=TRAFFIC_NOTICE_MARKER_ICON,
        marker_color=TRAFFIC_NOTICE_MARKER_COLOR,
        title=normalize_korean_text(title) or title,
        notice_type=safe_notice_type(incident.incident_type),
        natural_key=natural_key,
        occurred_at=parse_krex_occurrence(incident.occurred_date, incident.occurred_time),
        incident_type=incident.incident_type,
        incident_type_code=incident.incident_type_code,
        process_status=incident.process_status,
        process_status_code=incident.process_status_code,
        route_no=incident.route_no,
        route_name=incident.route_name,
        direction=incident.direction,
        point_name=incident.point_name,
        message=normalize_korean_text(incident.message),
        congestion_length=incident.congestion_length,
        coord=state_coordinate(incident.longitude, incident.latitude),
    )


def airport_state(airport: TransportAirport) -> AirportState:
    """공항. 자연키는 IATA 코드(``parse_airport``가 대문자로 맞춘다)."""
    feature_id = make_feature_id(
        bjd_code=None,
        kind=FeatureKind.PLACE.value,
        category=AIRPORT_CATEGORY,
        source_type=_source_type(DATASET_KEY_AIRPORTS),
        source_natural_key=airport.code,
    )
    coordinate = airport.coordinate
    return AirportState(
        feature_id=feature_id,
        category=AIRPORT_CATEGORY,
        marker_icon=AIRPORT_MARKER_ICON,
        marker_color=AIRPORT_MARKER_COLOR,
        name=normalize_korean_text(airport.name_korean) or airport.name_english or airport.code,
        name_english=airport.name_english,
        iata_code=airport.code,
        icao_code=airport.icao_code,
        municipality=normalize_korean_text(airport.municipality),
        coord=(
            state_coordinate(coordinate.lon, coordinate.lat) if coordinate is not None else None
        ),
        address=StateAddress(),
    )


def to_state_item(value: BaseModel, *, lookup_keys: tuple[str, ...] = ()) -> StateItem:
    """값 모델 → :class:`StateItem`. ``feature_id``·``coord``(있으면)를 모델에서 읽는다."""
    fields: Mapping[str, object] = value.__dict__
    feature_id = fields.get("feature_id")
    if not isinstance(feature_id, str) or not feature_id:
        raise ValueError(f"{type(value).__name__}에 feature_id가 없다.")
    coord = fields.get("coord")
    return StateItem(
        id=feature_id,
        value=value.model_dump_json(),
        coord=(coord.lon, coord.lat) if isinstance(coord, StateCoordinate) else None,
        lookup_keys=lookup_keys,
    )
