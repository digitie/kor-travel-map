"""``kortravelmap.providers.opinet`` — OpiNet 주유소/유가 정규화 (원천: kor-travel-transport).

OpiNet(한국석유공사) 주유소·유가 데이터를 ``FeatureBundle``/``PriceValue`` DTO로 정규화한다.
Map은 OpiNet을 직접 부르지 않는다 — kor-travel-transport가 전국 주유소를 수집해
``/v1/service/exports/fuel-stations``로 내고(ADR-106), 그 응답을
``providers.kor_travel_transport.parse_fuel_station``이 이 모듈의 입력 shape로 바꾼다.
provider 정체성은 ``kor-travel-transport``이고 자연키는 오피넷 주유소 ID(uni_id)다.

주유소 자체는 ``kind=place`` feature로, 유가는 주유소별 ``kind=price`` anchor feature와
``feature.feature_price_values`` row로 적재한다. 한 주유소의 유종들은 같은 price feature에
모인다 — ADR-098 identity ``(dataset, kind, natural_key=uni_id)``.

OpiNet product code:

| OpiNet `prodcd` | 본 lib `product_key` | 한글 |
|----------------|---------------------|------|
| `B027` | `gasoline` | 휘발유 |
| `D047` | `diesel` | 경유 |
| `B034` | `premium_gasoline` | 고급휘발유 |
| `C004` | `kerosene` | 등유 |
| `K015` | `lpg` | LPG |

ADR 참조: ADR-009 / ADR-013/014 / ADR-019 / ADR-098 / ADR-106
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime
from decimal import Decimal
from typing import Any, Final, Protocol, runtime_checkable

from kortravelmap.core.address import (
    extract_sido_code,
    extract_sigungu_code,
    normalize_korean_text,
    normalize_phone_number,
)
from kortravelmap.core.ids import (
    make_feature_id,
    make_payload_hash,
    make_source_record_key,
)
from kortravelmap.core.providers import normalize_provider_name
from kortravelmap.dto import (
    Address,
    Coordinate,
    Feature,
    FeatureBundle,
    FeatureKind,
    PlaceDetail,
    PriceDomain,
    PriceValue,
    SourceLink,
    SourceRecord,
    SourceRole,
)
from kortravelmap.geocoding import (
    AddressResolver,
    ReverseGeocoder,
    cached_address_resolver,
    cached_reverse_geocoder,
)
from kortravelmap.providers.kor_travel_transport import (
    DATASET_KEY_FUEL_PRICES,
    DATASET_KEY_FUEL_STATIONS,
    KOR_TRAVEL_TRANSPORT_PROVIDER_NAME,
)

__all__ = [
    "OPINET_STATION_SOURCE_ENTITY_TYPE",
    "FuelStationPlaceLocator",
    "OpinetStationItem",
    "OpinetStationPriceRow",
    "OpinetStationWithPrices",
    "fuel_station_place_locator_from_rows",
    "station_prices_to_features_and_values",
    "stations_to_bundles",
    # 메타
    "OPINET_PRODUCT_KEY_MAP",
    "OPINET_PRODUCT_NAME_KO",
    "OPINET_STATION_CATEGORY",
    "OPINET_STATION_MARKER_ICON",
    "OPINET_STATION_MARKER_COLOR",
]


# -- 상수 -----------------------------------------------------------------

_OPINET_STATION_ENTITY_TYPE: Final[str] = "fuel_station"
"""``source_records.source_entity_type`` — 주유소."""

OPINET_STATION_SOURCE_ENTITY_TYPE: Final[str] = _OPINET_STATION_ENTITY_TYPE
"""가격 적재가 주유소 place locator를 조회할 때 쓰는 ``source_entity_type``."""

_OPINET_PRICE_ENTITY_TYPE: Final[str] = "fuel_station_price"
"""``source_records.source_entity_type`` — 주유소 유종별 최신 가격 묶음."""

OPINET_STATION_CATEGORY: Final[str] = "06020000"
"""``Feature.category`` — `PlaceCategoryCode.TRANSPORT_FUEL` 8자리."""

OPINET_STATION_MARKER_ICON: Final[str] = "fuel"
"""Maki icon name — 주유소."""

OPINET_STATION_MARKER_COLOR: Final[str] = "P-08"
"""주유소 marker color palette (주황 계열)."""

_FACILITY_FLAGS: Final[tuple[str, ...]] = (
    "is_self",
    "is_24h",
    "has_carwash",
    "has_maintenance",
    "has_cvs",
)
"""transport가 넘기는 오피넷 편의시설 플래그. 값이 있을 때만 ``facility_info``에 싣는다."""


# OpiNet 원천 product code → 본 lib 표준 product_key 매핑.
OPINET_PRODUCT_KEY_MAP: Final[dict[str, str]] = {
    "B027": "gasoline",
    "D047": "diesel",
    "B034": "premium_gasoline",
    "C004": "kerosene",
    "K015": "lpg",
}

# 표준 product_key → 한글 이름.
OPINET_PRODUCT_NAME_KO: Final[dict[str, str]] = {
    "gasoline": "휘발유",
    "diesel": "경유",
    "premium_gasoline": "고급휘발유",
    "kerosene": "등유",
    "lpg": "LPG",
}


# -- 입력 Protocol --------------------------------------------------------


@runtime_checkable
class OpinetStationItem(Protocol):
    """OpiNet 주유소 row 1건의 입력 shape (place Feature 생성용).

    ``providers.kor_travel_transport.TransportFuelStation``이 만족한다. ``tel``/``lpg_yn``과
    편의시설 플래그는 있을 때만 ``getattr``로 보강한다.
    """

    uni_id: str
    """OpiNet 주유소 자연키 (예: ``"A0019186"``)."""

    name: str
    """주유소 상호명."""

    brand: Any
    """브랜드 코드(문자열) 또는 None."""

    address_road: str | None
    """도로명 주소 (우선)."""

    address_jibun: str | None
    """지번 주소 (도로명 없을 때 fallback)."""

    lon: float | None
    """경도 (WGS84)."""

    lat: float | None
    """위도 (WGS84)."""


@runtime_checkable
class OpinetStationPriceRow(Protocol):
    """주유소 유종 하나의 최신 가격. ``price=None``은 현재 판매하지 않음이다."""

    product_code: str
    price: Decimal | None
    observed_at: datetime
    collected_at: datetime
    """transport가 이 가격을 현재가로 마지막으로 확인한 시각 — ``PriceValue.observed_at``."""
    raw: Mapping[str, Any]


@runtime_checkable
class OpinetStationWithPrices(OpinetStationItem, Protocol):
    """주유소 + 유종별 최신 가격."""

    prices: Iterable[OpinetStationPriceRow]


# -- 헬퍼 ---------------------------------------------------------------


def _jsonable_raw(value: Any) -> Any:
    """Mapping/tuple/enum/datetime을 JSONB 가능 값으로 정규화."""
    enum_value = getattr(value, "value", None)
    if isinstance(enum_value, str):
        return enum_value
    if isinstance(value, Mapping):
        return {str(k): _jsonable_raw(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable_raw(item) for item in value]
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return value


def _source_raw_or_fallback(
    value: object,
    fallback: dict[str, Any],
) -> dict[str, Any]:
    """원천 행이 있으면 그것만 보존하고, 없으면 정규화 필드로 재구성한다."""
    if isinstance(value, Mapping) and value:
        result = _jsonable_raw(value)
        assert isinstance(result, dict)
        return result
    return fallback


# -- 주유소 + 유종별 가격 → price Feature + PriceValue --------------------


FuelStationPlaceLocator = Mapping[str, str]
"""주유소 자연키(uni_id) → 이미 적재된 주유소 place ``feature_id``."""


def fuel_station_place_locator_from_rows(
    rows: Iterable[tuple[str, str, float, float]],
) -> dict[str, str]:
    """``AsyncKorTravelMapClient.list_primary_place_locator`` 행 → ``uni_id → place feature_id``.

    가격 적재는 주유소 place를 다시 만들지 않는다(역지오코딩은 place job의 몫, ADR-106 리뷰 M5).
    이미 적재된 place의 ``feature_id``만 ``parent_feature_id``로 쓴다. 같은 자연키 중복은 첫 행.
    """
    locator: dict[str, str] = {}
    for source_entity_id, feature_id, _lon, _lat in rows:
        key = (source_entity_id or "").strip()
        if key and key not in locator:
            locator[key] = feature_id
    return locator


def _station_prices_to_bundle_and_values(
    station: OpinetStationWithPrices,
    *,
    fetched_at: datetime,
    place_locator: FuelStationPlaceLocator,
) -> tuple[FeatureBundle, list[PriceValue]] | None:
    rows = list(station.prices)
    priced = [row for row in rows if row.price is not None]
    if not priced:
        return None

    raw_data: dict[str, Any] = {
        "uni_id": station.uni_id,
        "prices": [_jsonable_raw(row.raw) for row in rows],
    }
    payload_hash = make_payload_hash(raw_data)
    source_record_key = make_source_record_key(
        provider=KOR_TRAVEL_TRANSPORT_PROVIDER_NAME,
        dataset_key=DATASET_KEY_FUEL_PRICES,
        source_entity_type=_OPINET_PRICE_ENTITY_TYPE,
        source_entity_id=station.uni_id,
        raw_payload_hash=payload_hash,
    )
    feature_id = make_feature_id(
        bjd_code=None,
        kind=FeatureKind.PRICE.value,
        category=OPINET_STATION_CATEGORY,
        source_type=f"{KOR_TRAVEL_TRANSPORT_PROVIDER_NAME}:{DATASET_KEY_FUEL_PRICES}",
        source_natural_key=station.uni_id,
    )
    provider = normalize_provider_name(KOR_TRAVEL_TRANSPORT_PROVIDER_NAME)
    values: list[PriceValue] = []
    for row in priced:
        assert row.price is not None
        prodcd = row.product_code.strip()
        product_key = OPINET_PRODUCT_KEY_MAP.get(prodcd, prodcd.lower())
        provider_updated_at = getattr(row, "provider_updated_at", None)
        values.append(
            PriceValue(
                feature_id=feature_id,
                provider=provider,
                price_domain=PriceDomain.OPINET_GAS_STATION,
                product_key=product_key,
                product_name=OPINET_PRODUCT_NAME_KO.get(product_key),
                source_product_key=prodcd,
                # 관측 시각 = transport가 이 값을 오피넷 현재가로 마지막으로 확인한 수집 시각.
                # 오피넷 갱신시각(``*_DT``)은 그 유종 가격을 **바꾼** 때라 며칠씩 묵는다 — 그것을
                # 관측 시각으로 쓰면 가격을 유지 중인 주유소가 현재가 지평선(4일) 밖으로 사라진다.
                # 갱신시각은 payload ``provider_updated_at``으로 보존한다(ADR-106).
                observed_at=row.collected_at,
                value_number=row.price,
                unit="KRW/L",
                normalization_version="opinet-v1.1",
                payload={
                    "uni_id": station.uni_id,
                    "station_name": station.name,
                    "prodcd": prodcd,
                    "product_key": product_key,
                    "price": str(row.price),
                    "observed_at": row.collected_at.isoformat(),
                    "provider_updated_at": (
                        provider_updated_at.isoformat()
                        if isinstance(provider_updated_at, datetime)
                        else None
                    ),
                },
                source_record_key=source_record_key,
            )
        )

    coord: Coordinate | None = None
    if station.lon is not None and station.lat is not None:
        coord = Coordinate(lon=Decimal(str(station.lon)), lat=Decimal(str(station.lat)))
    road_address = normalize_korean_text(station.address_road)
    jibun_address = normalize_korean_text(station.address_jibun)
    name_normalized = normalize_korean_text(station.name) or station.name
    feature = Feature(
        feature_id=feature_id,
        provider_natural_key=station.uni_id,
        kind=FeatureKind.PRICE,
        name=f"{name_normalized} 유가",
        coord=coord,
        address=Address(road=road_address or jibun_address),
        category=OPINET_STATION_CATEGORY,
        marker_icon=OPINET_STATION_MARKER_ICON,
        marker_color=OPINET_STATION_MARKER_COLOR,
        # place가 아직 없으면(새 주유소, 주간 place job 전) 부모 없이 적재하고 다음 실행에서 붙는다.
        parent_feature_id=place_locator.get(station.uni_id),
        detail=None,
    )
    source_record = SourceRecord(
        provider=provider,
        dataset_key=DATASET_KEY_FUEL_PRICES,
        source_entity_type=_OPINET_PRICE_ENTITY_TYPE,
        source_entity_id=station.uni_id,
        raw_payload_hash=payload_hash,
        raw_data=raw_data,
        fetched_at=fetched_at,
        source_record_key=source_record_key,
    )
    source_link = SourceLink(
        feature_id=feature_id,
        source_record_key=source_record_key,
        source_role=SourceRole.PRIMARY,
        match_method="natural_key",
        confidence=100,
    )
    return (
        FeatureBundle(feature=feature, source_record=source_record, source_link=source_link),
        values,
    )


def station_prices_to_features_and_values(
    items: Iterable[OpinetStationWithPrices],
    *,
    fetched_at: datetime,
    place_locator: FuelStationPlaceLocator,
) -> tuple[list[FeatureBundle], list[PriceValue]]:
    """주유소 + 유종별 최신 가격 → (price Feature bundle, PriceValue).

    역지오코딩·주소 보강을 하지 않는다 — 좌표는 transport가 넘긴 WGS84 그대로, 부모는
    ``place_locator``(이미 적재된 주유소 place)에서 찾는다. 주유소 place 적재·주소 보강은
    place job(``feature_place_transport_fuel_stations``, geo-heavy pool)만 한다(ADR-106 리뷰 M5).
    판매가가 하나도 없는 주유소는 가격 feature를 만들지 않는다.
    """
    bundles: list[FeatureBundle] = []
    values: list[PriceValue] = []
    for item in items:
        converted = _station_prices_to_bundle_and_values(
            item, fetched_at=fetched_at, place_locator=place_locator
        )
        if converted is None:
            continue
        bundle, item_values = converted
        bundles.append(bundle)
        values.extend(item_values)
    return bundles, values


# -- 주유소 place ------------------------------------------------------------


async def _station_item_to_bundle(
    item: OpinetStationItem,
    *,
    fetched_at: datetime,
    reverse_geocoder: ReverseGeocoder | None,
    address_resolver: AddressResolver | None,
) -> FeatureBundle:
    """OpiNet 주유소 row 한 건 → 한 ``FeatureBundle`` (place kind)."""

    # 0) 필드 정규화 — 주소(도로명 우선), 브랜드 코드, tel/lpg.
    road_address = normalize_korean_text(item.address_road)
    jibun_address = normalize_korean_text(item.address_jibun)
    display_address = road_address or jibun_address
    brand_code = _brand_code(item.brand)
    tel = getattr(item, "tel", None)
    lpg_yn = getattr(item, "lpg_yn", None)

    # 1) Coordinate — transport가 KATEC을 WGS84 lon/lat으로 변환해 넘긴다.
    coord: Coordinate | None
    if item.lon is not None and item.lat is not None:
        coord = Coordinate(lon=Decimal(str(item.lon)), lat=Decimal(str(item.lat)))
    else:
        coord = None

    # 2) Geocoding 보강. 좌표 reverse가 우선이고, bjd_code가 없으면 주소 geocode를 쓴다.
    bjd_code: str | None = None
    sigungu_code: str | None = None
    sido_code: str | None = None
    admin_address: str | None = None
    road_name_code: str | None = None
    if coord is not None and reverse_geocoder is not None:
        geo = await reverse_geocoder(coord)
        if geo is not None:
            bjd_code = geo.bjd_code
            sigungu_code = geo.sigungu_code or extract_sigungu_code(bjd_code)
            sido_code = geo.sido_code or extract_sido_code(bjd_code)
            admin_address = geo.admin
            road_name_code = geo.road_name_code
    if bjd_code is None and address_resolver is not None:
        resolved = await address_resolver(Address(road=display_address))
        if resolved is not None and resolved.bjd_code is not None:
            bjd_code = resolved.bjd_code
            sigungu_code = resolved.sigungu_code or extract_sigungu_code(bjd_code)
            sido_code = resolved.sido_code or extract_sido_code(bjd_code)
            admin_address = resolved.admin
            road_name_code = resolved.road_name_code

    # 3) Address — 도로명 주소를 road 슬롯에 둠.
    #    legal은 reverse_geocoder가 제공하지 않으면 None.
    address = Address(
        road=road_address or jibun_address,
        admin=admin_address,
        bjd_code=bjd_code,
        sigungu_code=sigungu_code,
        sido_code=sido_code,
        road_name_code=road_name_code,
    )

    # 4) Raw payload (canonical JSON 직렬화 가능).
    raw_data = _source_raw_or_fallback(
        getattr(item, "raw", None),
        {
            "uni_id": item.uni_id,
            "name": item.name,
            "brand": brand_code,
            "address_road": item.address_road,
            "address_jibun": item.address_jibun,
            "lon": str(item.lon) if item.lon is not None else None,
            "lat": str(item.lat) if item.lat is not None else None,
            "tel": tel,
            "lpg_yn": _coerce_bool_str(lpg_yn),
        },
    )
    payload_hash = make_payload_hash(raw_data)

    # 5) source_record_key (ADR-009).
    source_record_key = make_source_record_key(
        provider=KOR_TRAVEL_TRANSPORT_PROVIDER_NAME,
        dataset_key=DATASET_KEY_FUEL_STATIONS,
        source_entity_type=_OPINET_STATION_ENTITY_TYPE,
        source_entity_id=item.uni_id,
        raw_payload_hash=payload_hash,
    )

    # 6) feature_id (ADR-009).
    feature_id = make_feature_id(
        bjd_code=bjd_code,
        kind=FeatureKind.PLACE.value,
        category=OPINET_STATION_CATEGORY,
        source_type=f"{KOR_TRAVEL_TRANSPORT_PROVIDER_NAME}:{DATASET_KEY_FUEL_STATIONS}",
        source_natural_key=item.uni_id,
    )

    # 7) Feature 본체 + PlaceDetail.
    normalized_name = normalize_korean_text(item.name) or item.name
    phones: list[str] = []
    if tel:
        normalized_tel = normalize_phone_number(tel)
        if normalized_tel:
            phones.append(normalized_tel)

    feature = Feature(
        feature_id=feature_id,
        provider_natural_key=item.uni_id,
        kind=FeatureKind.PLACE,
        name=normalized_name,
        coord=coord,
        address=address,
        category=OPINET_STATION_CATEGORY,
        marker_icon=OPINET_STATION_MARKER_ICON,
        marker_color=OPINET_STATION_MARKER_COLOR,
        detail=PlaceDetail(
            feature_id=feature_id,
            place_kind="gas_station",
            phones=phones,
            facility_info={
                "brand_code": brand_code,
                "lpg_yn": _coerce_bool_str(lpg_yn),
                **{
                    flag: value
                    for flag in _FACILITY_FLAGS
                    if (value := getattr(item, flag, None)) is not None
                },
            },
        ),
    )

    # 8) SourceRecord.
    source_record = SourceRecord(
        provider=normalize_provider_name(KOR_TRAVEL_TRANSPORT_PROVIDER_NAME),
        dataset_key=DATASET_KEY_FUEL_STATIONS,
        source_entity_type=_OPINET_STATION_ENTITY_TYPE,
        source_entity_id=item.uni_id,
        raw_payload_hash=payload_hash,
        raw_data=raw_data,
        fetched_at=fetched_at,
        source_record_key=source_record_key,
    )

    # 9) SourceLink — primary.
    source_link = SourceLink(
        feature_id=feature_id,
        source_record_key=source_record_key,
        source_role=SourceRole.PRIMARY,
        match_method="natural_key",
        confidence=100,
    )

    return FeatureBundle(
        feature=feature,
        source_record=source_record,
        source_link=source_link,
    )


def _brand_code(brand: Any) -> str | None:
    """provider ``BrandCode`` enum(또는 str/None)을 코드 문자열로 정규화.

    ``BrandCode``는 StrEnum이라 ``.value``가 코드(예: ``"SKE"``). 이미 str이면 그대로.
    """
    if brand is None:
        return None
    value = getattr(brand, "value", None)
    if isinstance(value, str):
        return value
    text = str(brand).strip()
    return text or None


def _coerce_bool_str(value: str | bool | None) -> bool | None:
    """OpiNet의 ``"Y"``/``"N"``/``bool``/``None`` 입력을 ``bool | None``로 정규화."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    upper = str(value).strip().upper()
    if upper in {"Y", "TRUE", "1"}:
        return True
    if upper in {"N", "FALSE", "0", ""}:
        return False
    return None


async def stations_to_bundles(
    items: Iterable[OpinetStationItem],
    *,
    fetched_at: datetime,
    reverse_geocoder: ReverseGeocoder | None = None,
    address_resolver: AddressResolver | None = None,
) -> list[FeatureBundle]:
    """OpiNet 주유소 items → ``list[FeatureBundle]`` (place kind, 1차 source).

    Parameters
    ----------
    items
        transport export를 파싱한 주유소(``OpinetStationItem`` Protocol).
    fetched_at
        export 조회 시각 (aware). 모든 bundle 공통.
    reverse_geocoder
        좌표 → ``Address`` async 역지오코더 (있으면). feature_id가 bjd_code에
        의존하므로(ADR-009) feature_id 계산 전에 await해 보강. 중복 좌표는
        ``cached_reverse_geocoder``로 1회만 호출.
    address_resolver
        주소 → ``Address`` async 보강 geocoder. 좌표 reverse 결과에 bjd_code가 없을
        때 주소 문자열로 kor-travel-geo ``/v2/geocode``를 호출한다.

    Returns
    -------
    list[FeatureBundle]
        입력 순서 유지. `Feature(kind=place, category="06020000" TRANSPORT_
        FUEL)` + `PlaceDetail(place_kind="gas_station")` + `SourceRecord` +
        `SourceLink(role=primary)`.

    Notes
    -----
    - 좌표 nullable 가능. 좌표 없으면 ``Feature.coord=None``으로 적재되고
      `features_in_bounds` 쿼리에서 자연 제외 (ADR-012).
    - 가격은 `station_prices_to_features_and_values`가 별도 `kind=price` anchor
      feature로 적재한다.
    """
    geocoder = (
        cached_reverse_geocoder(reverse_geocoder)
        if reverse_geocoder is not None
        else None
    )
    resolver = (
        cached_address_resolver(address_resolver)
        if address_resolver is not None
        else None
    )
    return [
        await _station_item_to_bundle(
            item,
            fetched_at=fetched_at,
            reverse_geocoder=geocoder,
            address_resolver=resolver,
        )
        for item in items
    ]
