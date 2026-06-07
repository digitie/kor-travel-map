"""``krtour.map.providers.opinet`` — OpiNet 유가 → ``PriceValue``.

본 모듈은 `python-opinet-api` provider 라이브러리의 typed model을 본 라이브러리
``PriceValue`` DTO로 정규화한다. 주유소 자체(`Feature`)는 별도 PR 예정 —
본 PR(#42)은 **시계열 가격 변환만**.

OpiNet은 한국석유공사 운영. 주유소 ID(uni_id) + 제품코드(prodcd) + 관측시각이
unique. 본 lib는 `feature_id`를 호출자가 미리 결정한 후 전달받는다 (격자→
feature 매핑 같은 책임은 본 모듈 X).

OpiNet product code(KMA `category` 위치):

| OpiNet `prodcd` | 본 lib `product_key` | 한글 |
|----------------|---------------------|------|
| `B027` | `gasoline` | 휘발유 |
| `D047` | `diesel` | 경유 |
| `B034` | `premium_gasoline` | 고급휘발유 |
| `C004` | `kerosene` | 등유 |
| `K015` | `lpg` | LPG |

ADR 참조
--------
- ADR-006 — provider wrapper 금지
- ADR-009 — `make_price_value_key`
- ADR-013/014 — bulk insert + BRIN(observed_at) 시계열
- ADR-019 — datetime aware
- ADR-024 — canonical provider name `python-opinet-api`
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from decimal import Decimal
from typing import Any, Final, Protocol, runtime_checkable

from krtour.map.core.address import (
    extract_sido_code,
    extract_sigungu_code,
    normalize_korean_text,
    normalize_phone_number,
)
from krtour.map.core.ids import (
    make_feature_id,
    make_payload_hash,
    make_source_record_key,
)
from krtour.map.core.providers import normalize_provider_name
from krtour.map.dto import (
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
from krtour.map.geocoding import (
    AddressResolver,
    ReverseGeocoder,
    cached_address_resolver,
    cached_reverse_geocoder,
)

__all__ = [
    "OpinetPriceItem",
    "OpinetStationItem",
    "prices_to_values",
    "stations_to_bundles",
    # 메타
    "OPINET_PROVIDER_NAME",
    "OPINET_PRODUCT_KEY_MAP",
    "OPINET_PRODUCT_NAME_KO",
    "OPINET_STATION_CATEGORY",
    "OPINET_STATION_MARKER_ICON",
    "OPINET_STATION_MARKER_COLOR",
    "OPINET_STATION_DATASET_KEY",
]


# -- 상수 -----------------------------------------------------------------

OPINET_PROVIDER_NAME: Final[str] = "python-opinet-api"
"""canonical provider name (ADR-024)."""

OPINET_STATION_DATASET_KEY: Final[str] = "opinet_fuel_station_details"
"""``provider_sync.source_records.dataset_key`` — 주유소 station detail."""

_OPINET_STATION_ENTITY_TYPE: Final[str] = "fuel_station"
"""``source_records.source_entity_type`` — provider 내 entity 종류."""

OPINET_STATION_CATEGORY: Final[str] = "06020000"
"""``Feature.category`` — `PlaceCategoryCode.TRANSPORT_FUEL` 8자리."""

OPINET_STATION_MARKER_ICON: Final[str] = "fuel"
"""Maki icon name — 주유소."""

OPINET_STATION_MARKER_COLOR: Final[str] = "P-08"
"""주유소 marker color palette (주황 계열)."""


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
    """OpiNet 주유소 row 1건의 입력 shape (place Feature 생성용, ADR-044 정렬).

    ``python-opinet-api``의 ``Station``(``iter_stations_in_bbox``/``search_stations_
    around`` 반환) typed model 필드명에 정렬한다. ``Station``은 좌표를 KATEC에서
    WGS84(``lon``/``lat`` float)로 이미 변환해 노출한다(본 lib는 WGS84만, ADR-012).

    Notes
    -----
    - ``tel``/``lpg_yn``은 ``Station``엔 **없고** ``StationDetail``(단건 상세)에만
      있다. 변환은 ``getattr``로 있을 때만 보강(N+1 detail 호출은 후속) — Protocol
      필수에서 제외해 ``Station``이 그대로 만족하게 한다.
    - ``brand``는 provider ``BrandCode`` enum(또는 None) — 변환에서 코드 문자열로
      정규화해 보존.
    """

    uni_id: str
    """OpiNet 주유소 자연키 (예: ``"A0019186"``). source_entity_id 매핑."""

    name: str
    """주유소 상호명. Feature.name 매핑."""

    brand: Any
    """브랜드 (provider ``BrandCode`` enum | None). 코드 문자열로 정규화 보존."""

    address_road: str | None
    """도로명 주소 (우선)."""

    address_jibun: str | None
    """지번 주소 (도로명 없을 때 fallback)."""

    lon: float
    """경도 (WGS84, provider가 KATEC에서 변환)."""

    lat: float
    """위도 (WGS84)."""


@runtime_checkable
class OpinetPriceItem(Protocol):
    """OpiNet 주유소 가격 시계열 row 1건의 입력 shape.

    `python-opinet-api`의 typed model이 본 Protocol을 만족해야 한다. OpiNet
    원천 컬럼명을 영문 snake_case로 정규화된 형태 가정.
    """

    uni_id: str
    """OpiNet 주유소 자연키 (provider 내 unique). source_entity_id로 매핑."""

    prodcd: str
    """제품 코드 (B027/D047/B034/K015/C004). source_product_key로 보존."""

    price: str | Decimal | int | float
    """판매가 (KRW/L). 원천 string일 수도 있으나 numeric 변환 후 적재."""

    trade_dt: datetime
    """관측 시각 (KST aware). observed_at에 매핑."""


# -- 헬퍼 ---------------------------------------------------------------


def _parse_price_value(raw: str | Decimal | int | float) -> Decimal:
    """가격을 `Decimal`로 변환. ``"1,820"`` (천 단위 구분자) 흡수."""
    if isinstance(raw, Decimal):
        return raw
    if isinstance(raw, int | float):
        return Decimal(str(raw))
    # str — 천 단위 구분자 / 공백 흡수.
    cleaned = str(raw).replace(",", "").strip()
    return Decimal(cleaned)


# -- 단일 row → PriceValue -----------------------------------------------


def _item_to_price_value(
    item: OpinetPriceItem,
    *,
    feature_id: str,
    source_record_key: str | None,
) -> PriceValue:
    """OpiNet 가격 row 한 건 → ``PriceValue``."""
    product_key = OPINET_PRODUCT_KEY_MAP.get(item.prodcd, item.prodcd.lower())
    product_name = OPINET_PRODUCT_NAME_KO.get(product_key)
    value = _parse_price_value(item.price)

    payload: dict[str, Any] = {
        "uni_id": item.uni_id,
        "prodcd": item.prodcd,
        "price": str(item.price),
        "trade_dt": item.trade_dt.isoformat(),
    }

    return PriceValue(
        feature_id=feature_id,
        provider=normalize_provider_name(OPINET_PROVIDER_NAME),
        price_domain=PriceDomain.OPINET_GAS_STATION,
        product_key=product_key,
        product_name=product_name,
        source_product_key=item.prodcd,
        observed_at=item.trade_dt,
        value_number=value,
        unit="KRW/L",
        normalization_version="opinet-v1.0",
        payload=payload,
        source_record_key=source_record_key,
    )


# -- 공개 API -----------------------------------------------------------


def prices_to_values(
    items: Iterable[OpinetPriceItem],
    *,
    feature_id: str,
    source_record_key: str | None = None,
) -> list[PriceValue]:
    """OpiNet 가격 items → ``list[PriceValue]``.

    Parameters
    ----------
    items
        `python-opinet-api`의 가격 시계열 typed model iterable. 본 Protocol을
        만족해야 한다.
    feature_id
        주유소 ``Feature``의 ID (`make_feature_id` 결과, kind=place). 호출자가
        OpiNet uni_id → feature_id 매핑을 사전 결정해서 명시 전달.
    source_record_key
        provider raw payload 추적용. 운영상 권장 — 누락 시 trace 불가.

    Returns
    -------
    list[PriceValue]
        입력 순서 유지. `price_domain=opinet_gas_station`,
        `unit="KRW/L"`, `observed_at=trade_dt`.

    Raises
    ------
    pydantic.ValidationError
        observed_at naive 또는 value_number 음수 (ADR-019 / PriceValue
        validator).

    Examples
    --------
    호출자 측 사용 예시 (TripMate Dagster asset):

    >>> # client = AsyncOpiNetClient(...)
    >>> # async for page in client.aiter_prices(area="11", ...):
    >>> #     values = prices_to_values(
    >>> #         page.items,
    >>> #         feature_id=station_feature_id,
    >>> #         source_record_key=sr_key,
    >>> #     )
    >>> #     await krtour_client.load_price_values(values)

    Notes
    -----
    - OpiNet uni_id → feature_id 매핑은 별도 catalog (`OpinetStationCatalog`
      등) 책임. 본 함수는 매핑 X.
    - 가격 시계열은 시간 단위로 들어옴 — BRIN(observed_at) 인덱스 적재 권장
      (ADR-014). 호출자가 bulk insert 시 안전 마진 30k (ADR-013).
    - PR#43+: gas station feature (`stations_to_bundles`) — `Feature(kind=
      place, category="06020000" TRANSPORT_FUEL)` + SourceRecord + SourceLink.
    """
    return [
        _item_to_price_value(
            item,
            feature_id=feature_id,
            source_record_key=source_record_key,
        )
        for item in items
    ]


# -- stations_to_bundles (PR#43) -----------------------------------------


async def _station_item_to_bundle(
    item: OpinetStationItem,
    *,
    fetched_at: datetime,
    reverse_geocoder: ReverseGeocoder | None,
    address_resolver: AddressResolver | None,
) -> FeatureBundle:
    """OpiNet 주유소 row 한 건 → 한 ``FeatureBundle`` (place kind).

    PR#34 datagokr `cultural_festivals_to_bundles`의 9-step 패턴과 동일.
    """

    # 0) provider 필드 정규화 — 주소(도로명 우선), 브랜드 코드, tel/lpg(Detail 한정).
    road_address = normalize_korean_text(item.address_road)
    jibun_address = normalize_korean_text(item.address_jibun)
    display_address = road_address or jibun_address
    brand_code = _brand_code(item.brand)
    tel = getattr(item, "tel", None)
    lpg_yn = getattr(item, "lpg_yn", None)

    # 1) Coordinate — Station은 lon/lat(WGS84 float)을 항상 노출.
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
    raw_data: dict[str, Any] = {
        "uni_id": item.uni_id,
        "name": item.name,
        "brand": brand_code,
        "address_road": item.address_road,
        "address_jibun": item.address_jibun,
        "lon": str(item.lon) if item.lon is not None else None,
        "lat": str(item.lat) if item.lat is not None else None,
        "tel": tel,
        "lpg_yn": _coerce_bool_str(lpg_yn),
    }
    payload_hash = make_payload_hash(raw_data)

    # 5) source_record_key (ADR-009).
    source_record_key = make_source_record_key(
        provider=OPINET_PROVIDER_NAME,
        dataset_key=OPINET_STATION_DATASET_KEY,
        source_entity_type=_OPINET_STATION_ENTITY_TYPE,
        source_entity_id=item.uni_id,
        raw_payload_hash=payload_hash,
    )

    # 6) feature_id (ADR-009).
    feature_id = make_feature_id(
        bjd_code=bjd_code,
        kind=FeatureKind.PLACE.value,
        category=OPINET_STATION_CATEGORY,
        source_type=f"{OPINET_PROVIDER_NAME}:{OPINET_STATION_DATASET_KEY}",
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
            },
        ),
    )

    # 8) SourceRecord.
    source_record = SourceRecord(
        provider=normalize_provider_name(OPINET_PROVIDER_NAME),
        dataset_key=OPINET_STATION_DATASET_KEY,
        source_entity_type=_OPINET_STATION_ENTITY_TYPE,
        source_entity_id=item.uni_id,
        raw_payload_hash=payload_hash,
        source_version=None,
        raw_name=item.name,
        raw_address=display_address,
        raw_longitude=coord.lon if coord is not None else None,
        raw_latitude=coord.lat if coord is not None else None,
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
        is_primary_source=True,
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
        `python-opinet-api`의 주유소 typed model iterable.
        ``OpinetStationItem`` Protocol을 만족해야 한다.
    fetched_at
        provider 호출 시각 (KST aware). 모든 bundle 공통.
    reverse_geocoder
        좌표 → ``Address`` async 역지오코더 (있으면). feature_id가 bjd_code에
        의존하므로(ADR-009) feature_id 계산 전에 await해 보강. 중복 좌표는
        ``cached_reverse_geocoder``로 1회만 호출.
    address_resolver
        주소 → ``Address`` async 보강 geocoder. 좌표 reverse 결과에 bjd_code가 없을
        때 주소 문자열로 kraddr-geo ``/v2/geocode``를 호출한다.

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
    - 가격 시계열은 `prices_to_values`와 별도로 호출자가 적재 (uni_id로 join).
    - PriceValue의 `feature_id`는 본 함수가 만든 `feature_id`와 같아야 — 호출자
      `OpinetStationCatalog`가 ``uni_id -> feature_id`` 매핑을 유지.
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
