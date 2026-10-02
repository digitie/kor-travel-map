"""``kortravelmap.providers.kor_travel_transport`` — kor-travel-transport export 계약 (ADR-106).

Map은 OpiNet 주유소·유가, 한국도로공사(KREX) 휴게소·휴게소 유가·고속도로 돌발,
공항 메타데이터를 provider 라이브러리로 직접 받지 않는다. kor-travel-transport가 수집·저장한 값을
``GET /v1/service/exports/*``(transport ADR-012)로 읽는다. 이 모듈은 그 계약의 Map 쪽 정본이다.

- **provider 정체성**: 모든 dataset의 provider는 ``kor-travel-transport``
  (``source_kind=internal``)다. 자연키는 원천의 것을 그대로 쓴다(주유소 uni_id,
  휴게소 ``name::route::direction``, 휴게소 코드, 돌발 사건 단서, IATA 코드) — ADR-098
  identity ``(dataset, kind, natural_key)``의 세 번째 성분이다.
- **이 모듈은 REST client wrapper가 아니다**(ADR-006은 공개 provider client에 대한 규칙이다).
  HTTP는 Dagster fetcher가 한다. 여기서는 이미 받은 JSON을 **엄격히** 검사해 변환 함수
  (``providers.opinet``/``providers.krex``/``providers.krairport``)가 받는 입력 shape로 바꾼다.
  계약이 어긋나면 :class:`TransportExportContractError`로 실패한다 — 조용히 건너뛰면 적재가
  "성공"으로 기록되고 누락이 숨는다.
- 계약 기계 정본은 vendoring한 ``contracts/kor-travel-transport/openapi.json``이다
  (``contracts/kor-travel-transport/PIN.json``의 SHA-256과 transport revision에 결박).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Final

__all__ = [
    "DATASET_KEY_AIRPORTS",
    "DATASET_KEY_FUEL_PRICES",
    "DATASET_KEY_FUEL_STATIONS",
    "DATASET_KEY_HIGHWAY_INCIDENTS",
    "DATASET_KEY_REST_AREAS",
    "DATASET_KEY_REST_AREA_FUEL_PRICES",
    "EXPORT_PATH_AIRPORTS",
    "EXPORT_PATH_FUEL_STATIONS",
    "EXPORT_PATH_HIGHWAY_INCIDENTS_ACTIVE",
    "EXPORT_PATH_REST_AREAS",
    "EXPORT_PATH_REST_AREA_FUEL_PRICES",
    "KOR_TRAVEL_TRANSPORT_PROVIDER_NAME",
    "SERVICE_TOKEN_HEADER",
    "TransportAirport",
    "TransportCoordinate",
    "TransportExportContractError",
    "TransportExportPage",
    "TransportFuelPrice",
    "TransportFuelStation",
    "TransportHighwayIncident",
    "TransportIncidentActiveSet",
    "TransportRestArea",
    "TransportRestAreaFuelPrice",
    "parse_active_incident_set",
    "parse_airport",
    "parse_airports",
    "parse_export_page",
    "parse_fuel_station",
    "parse_rest_area",
    "parse_rest_area_fuel_price",
]

KOR_TRAVEL_TRANSPORT_PROVIDER_NAME: Final[str] = "kor-travel-transport"
"""provider canonical name. transport 저장소·배포 식별자와 같다(transport ADR-010)."""

DATASET_KEY_FUEL_STATIONS: Final[str] = "transport_fuel_stations"
"""오피넷 주유소 place Feature."""
DATASET_KEY_FUEL_PRICES: Final[str] = "transport_fuel_prices"
"""오피넷 주유소 유종별 가격 price Feature + PriceValue."""
DATASET_KEY_REST_AREAS: Final[str] = "transport_rest_areas"
"""고속도로 휴게소 place Feature."""
DATASET_KEY_REST_AREA_FUEL_PRICES: Final[str] = "transport_rest_area_fuel_prices"
"""휴게소 주유소 유가 price Feature + PriceValue."""
DATASET_KEY_HIGHWAY_INCIDENTS: Final[str] = "transport_highway_incidents"
"""고속도로 돌발·통제 notice Feature(활성 집합 reconcile)."""
DATASET_KEY_AIRPORTS: Final[str] = "transport_airports"
"""국내 운영 공항 place Feature."""

SERVICE_TOKEN_HEADER: Final[str] = "X-Kor-Travel-Transport-Service-Token"
"""transport export 토큰 header(transport ADR-012)."""

EXPORT_PATH_FUEL_STATIONS: Final[str] = "/v1/service/exports/fuel-stations"
EXPORT_PATH_REST_AREAS: Final[str] = "/v1/service/exports/rest-areas"
EXPORT_PATH_REST_AREA_FUEL_PRICES: Final[str] = "/v1/service/exports/rest-area-fuel-prices"
EXPORT_PATH_HIGHWAY_INCIDENTS_ACTIVE: Final[str] = "/v1/service/exports/highway-incidents/active"
EXPORT_PATH_AIRPORTS: Final[str] = "/v1/service/exports/airports"


class TransportExportContractError(ValueError):
    """transport export 응답이 vendored 계약과 어긋난다."""


# -- 입력 shape ---------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TransportCoordinate:
    lat: float
    lon: float


@dataclass(frozen=True, slots=True)
class TransportFuelPrice:
    """주유소 유종 하나의 최신 가격. ``price=None``은 "현재 판매하지 않음"이다."""

    product_code: str
    price: Decimal | None
    provider_updated_at: datetime | None
    observed_at: datetime
    raw: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class TransportFuelStation:
    """오피넷 주유소 1건(``providers.opinet.OpinetStationItem`` 입력 shape)."""

    uni_id: str
    name: str
    brand: str | None
    brand_name: str | None
    address_road: str | None
    address_jibun: str | None
    lon: float | None
    lat: float | None
    tel: str | None
    lpg_yn: bool | None
    is_self: bool | None
    is_24h: bool | None
    has_carwash: bool | None
    has_maintenance: bool | None
    has_cvs: bool | None
    last_seen_at: datetime
    prices: tuple[TransportFuelPrice, ...]
    raw: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class TransportRestArea:
    """휴게소 1건(``providers.krex.KrexRestAreaItem`` 입력 shape)."""

    natural_key: str
    name: str
    route_name: str | None
    direction: str | None
    lon: float | None
    lat: float | None
    phone_number: str | None
    has_gas_station: bool | None
    has_lpg_station: bool | None
    has_ev_charger: bool | None
    raw: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class TransportRestAreaFuelPrice:
    """휴게소 주유소 현재 유가(``providers.krex.KrexRestAreaFuelPriceRecord`` 입력 shape)."""

    service_area_code: str
    route_name: str | None
    direction: str | None
    oil_company: str | None
    service_area_name: str | None
    phone_number: str | None
    address: str | None
    gasoline_price: int | None
    diesel_price: int | None
    lpg_price: int | None
    observed_at: datetime
    raw: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class TransportHighwayIncident:
    """고속도로 돌발 1건(``providers.krex.KrexTrafficNoticeItem`` 입력 shape)."""

    occurred_date: str | None
    occurred_time: str | None
    incident_type: str | None
    incident_type_code: str | None
    direction: str | None
    message: str | None
    point_name: str | None
    route_no: str | None
    route_name: str | None
    process_status: str | None
    process_status_code: str | None
    latitude: float | None
    longitude: float | None
    congestion_length: float | None
    series_no: int | None
    raw: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class TransportAirport:
    """국내 운영 공항 1건(``providers.krairport.AirportMetadataItem`` 입력 shape)."""

    code: str
    name_korean: str | None
    name_english: str
    icao_code: str | None
    municipality: str | None
    coordinate: TransportCoordinate | None
    raw: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class TransportExportPage:
    """``{items, next_cursor, has_more, collection}`` 페이지."""

    items: tuple[Mapping[str, Any], ...]
    next_cursor: str | None
    has_more: bool
    collection: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class TransportIncidentActiveSet:
    """마지막 성공 돌발 수집의 활성 사건 전체. 여기 없는 사건은 해소된 것이다."""

    collected_at: datetime
    items: tuple[TransportHighwayIncident, ...]


# -- 엄격 파싱 ------------------------------------------------------------------


def _mapping(value: Any, where: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TransportExportContractError(f"{where}: JSON object가 아니다.")
    return value


def _required_text(item: Mapping[str, Any], key: str, where: str) -> str:
    value = item.get(key)
    if not isinstance(value, str) or not value.strip():
        raise TransportExportContractError(f"{where}.{key}: 비어 있지 않은 문자열이어야 한다.")
    return value


def _text(item: Mapping[str, Any], key: str, where: str) -> str | None:
    value = item.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise TransportExportContractError(f"{where}.{key}: 문자열 또는 null이어야 한다.")
    return value


def _bool(item: Mapping[str, Any], key: str, where: str) -> bool | None:
    value = item.get(key)
    if value is None or isinstance(value, bool):
        return value
    raise TransportExportContractError(f"{where}.{key}: boolean 또는 null이어야 한다.")


def _number(item: Mapping[str, Any], key: str, where: str) -> float | None:
    value = item.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TransportExportContractError(f"{where}.{key}: 숫자 또는 null이어야 한다.")
    return float(value)


def _integer(item: Mapping[str, Any], key: str, where: str) -> int | None:
    value = item.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise TransportExportContractError(f"{where}.{key}: 정수 또는 null이어야 한다.")
    return value


def _decimal(item: Mapping[str, Any], key: str, where: str) -> Decimal | None:
    value = item.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        raise TransportExportContractError(f"{where}.{key}: 숫자 또는 null이어야 한다.")
    try:
        return Decimal(str(value))
    except InvalidOperation as exc:
        raise TransportExportContractError(f"{where}.{key}: 숫자로 읽을 수 없다.") from exc


def _datetime(item: Mapping[str, Any], key: str, where: str, *, required: bool) -> datetime | None:
    value = item.get(key)
    if value is None:
        if required:
            raise TransportExportContractError(f"{where}.{key}: 필수 시각이 없다.")
        return None
    if not isinstance(value, str):
        raise TransportExportContractError(f"{where}.{key}: ISO-8601 문자열이어야 한다.")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise TransportExportContractError(f"{where}.{key}: ISO-8601 시각이 아니다.") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise TransportExportContractError(f"{where}.{key}: timezone이 없는 시각이다.")
    return parsed


def _required_datetime(item: Mapping[str, Any], key: str, where: str) -> datetime:
    parsed = _datetime(item, key, where, required=True)
    assert parsed is not None
    return parsed


def _raw(item: Mapping[str, Any], where: str) -> Mapping[str, Any]:
    value = item.get("raw")
    if value is None:
        return {}
    return _mapping(value, f"{where}.raw")


def parse_export_page(payload: Any, *, where: str) -> TransportExportPage:
    """페이지 envelope을 검사한다. ``has_more=true``면 새 ``next_cursor``가 있어야 한다."""
    page = _mapping(payload, where)
    items = page.get("items")
    if not isinstance(items, list):
        raise TransportExportContractError(f"{where}.items: 배열이어야 한다.")
    has_more = page.get("has_more")
    if not isinstance(has_more, bool):
        raise TransportExportContractError(f"{where}.has_more: boolean이어야 한다.")
    next_cursor = page.get("next_cursor")
    if has_more and (not isinstance(next_cursor, str) or not next_cursor):
        raise TransportExportContractError(f"{where}: has_more=true인데 next_cursor가 없다.")
    return TransportExportPage(
        items=tuple(_mapping(item, f"{where}.items[]") for item in items),
        next_cursor=next_cursor if isinstance(next_cursor, str) else None,
        has_more=has_more,
        collection=_mapping(page.get("collection"), f"{where}.collection"),
    )


def parse_fuel_station(item: Mapping[str, Any]) -> TransportFuelStation:
    where = "fuel-stations.item"
    prices_value = item.get("prices")
    if not isinstance(prices_value, list):
        raise TransportExportContractError(f"{where}.prices: 배열이어야 한다.")
    prices: list[TransportFuelPrice] = []
    for raw_price in prices_value:
        price = _mapping(raw_price, f"{where}.prices[]")
        prices.append(TransportFuelPrice(
            product_code=_required_text(price, "product_code", f"{where}.prices[]"),
            price=_decimal(price, "price", f"{where}.prices[]"),
            provider_updated_at=_datetime(
                price, "provider_updated_at", f"{where}.prices[]", required=False
            ),
            observed_at=_required_datetime(price, "observed_at", f"{where}.prices[]"),
            raw=dict(price),
        ))
    lpg = next((price for price in prices if price.product_code == "K015"), None)
    return TransportFuelStation(
        uni_id=_required_text(item, "natural_key", where).strip(),
        name=_required_text(item, "name", where),
        brand=_text(item, "brand_code", where),
        brand_name=_text(item, "brand_name", where),
        address_road=_text(item, "address", where),
        address_jibun=None,
        lon=_number(item, "longitude", where),
        lat=_number(item, "latitude", where),
        tel=_text(item, "phone", where),
        # 오피넷 브라우저 원천에는 LPG 여부 컬럼이 없다.
        # LPG(K015) 가격 행이 판매가를 가지면 판매로 본다.
        lpg_yn=None if lpg is None else lpg.price is not None,
        is_self=_bool(item, "is_self", where),
        is_24h=_bool(item, "is_24h", where),
        has_carwash=_bool(item, "has_carwash", where),
        has_maintenance=_bool(item, "has_maintenance", where),
        has_cvs=_bool(item, "has_cvs", where),
        last_seen_at=_required_datetime(item, "last_seen_at", where),
        prices=tuple(prices),
        raw=_raw(item, where),
    )


def parse_rest_area(item: Mapping[str, Any]) -> TransportRestArea:
    where = "rest-areas.item"
    return TransportRestArea(
        natural_key=_required_text(item, "natural_key", where),
        name=_required_text(item, "name", where),
        route_name=_text(item, "route_name", where),
        direction=_text(item, "direction", where),
        lon=_number(item, "longitude", where),
        lat=_number(item, "latitude", where),
        phone_number=_text(item, "phone_number", where),
        has_gas_station=_bool(item, "has_gas_station", where),
        has_lpg_station=_bool(item, "has_lpg_station", where),
        has_ev_charger=_bool(item, "has_ev_charger", where),
        raw=_raw(item, where),
    )


def parse_rest_area_fuel_price(item: Mapping[str, Any]) -> TransportRestAreaFuelPrice:
    where = "rest-area-fuel-prices.item"
    return TransportRestAreaFuelPrice(
        service_area_code=_required_text(item, "service_area_code", where).strip(),
        route_name=_text(item, "route_name", where),
        direction=_text(item, "direction", where),
        oil_company=_text(item, "oil_company", where),
        service_area_name=_text(item, "service_area_name", where),
        phone_number=_text(item, "phone_number", where),
        address=_text(item, "address", where),
        gasoline_price=_integer(item, "gasoline_price", where),
        diesel_price=_integer(item, "diesel_price", where),
        lpg_price=_integer(item, "lpg_price", where),
        observed_at=_required_datetime(item, "observed_at", where),
        raw=_raw(item, where),
    )


def _parse_incident(item: Mapping[str, Any]) -> TransportHighwayIncident:
    where = "highway-incidents.item"
    return TransportHighwayIncident(
        occurred_date=_text(item, "occurred_date", where),
        occurred_time=_text(item, "occurred_time", where),
        incident_type=_text(item, "incident_type", where),
        incident_type_code=_text(item, "incident_type_code", where),
        direction=_text(item, "direction", where),
        message=_text(item, "message", where),
        point_name=_text(item, "point_name", where),
        route_no=_text(item, "route_no", where),
        route_name=_text(item, "route_name", where),
        process_status=_text(item, "process_status", where),
        process_status_code=_text(item, "process_status_code", where),
        latitude=_number(item, "latitude", where),
        longitude=_number(item, "longitude", where),
        congestion_length=_number(item, "congestion_length", where),
        series_no=_integer(item, "series_no", where),
        raw=_raw(item, where),
    )


def parse_active_incident_set(payload: Any) -> TransportIncidentActiveSet:
    """활성 돌발 집합을 검사한다. 원본 provider 행(``raw``)이 없는 사건은 계약 위반이다."""
    where = "highway-incidents/active"
    body = _mapping(payload, where)
    items = body.get("items")
    if not isinstance(items, list):
        raise TransportExportContractError(f"{where}.items: 배열이어야 한다.")
    parsed = tuple(_parse_incident(_mapping(item, f"{where}.items[]")) for item in items)
    if any(not incident.raw for incident in parsed):
        raise TransportExportContractError(f"{where}: 원본 행(raw)이 없는 사건이 있다.")
    return TransportIncidentActiveSet(
        collected_at=_required_datetime(body, "collected_at", where),
        items=parsed,
    )


def parse_airport(item: Mapping[str, Any]) -> TransportAirport:
    where = "airports.item"
    lat = _number(item, "latitude", where)
    lon = _number(item, "longitude", where)
    return TransportAirport(
        code=_required_text(item, "code", where).strip().upper(),
        name_korean=_text(item, "name_korean", where),
        name_english=_required_text(item, "name_english", where),
        icao_code=_text(item, "icao_code", where),
        municipality=_text(item, "municipality", where),
        coordinate=(
            TransportCoordinate(lat=lat, lon=lon) if lat is not None and lon is not None else None
        ),
        raw=dict(item),
    )


def parse_airports(payload: Any) -> tuple[TransportAirport, ...]:
    body = _mapping(payload, "airports")
    items = body.get("items")
    if not isinstance(items, list) or not items:
        raise TransportExportContractError("airports.items: 비어 있지 않은 배열이어야 한다.")
    return tuple(parse_airport(_mapping(item, "airports.items[]")) for item in items)

