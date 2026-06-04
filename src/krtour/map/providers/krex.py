"""``krtour.map.providers.krex`` — 휴게소 → multi-kind 변환 (Sprint 2 §2.4).

본 모듈은 `python-krex-api` provider 라이브러리의 typed model을 4 kind으로
정규화한다 — **multi-kind 통합 검증** (place + price + weather + notice).

지원 dataset:

| 함수 | dataset_key | Feature.kind | DTO |
|------|-------------|--------------|-----|
| ``rest_areas_to_bundles`` | ``krex_rest_areas`` | place | FeatureBundle |
| ``rest_area_prices_to_values`` | ``krex_rest_area_prices`` | (시계열) | PriceValue |
| ``rest_area_weather_to_values`` | ``krex_rest_area_weather`` | (시계열) | WeatherValue |
| ``traffic_notices_to_bundles`` | ``krex_traffic_notices`` | notice | FeatureBundle |

ADR 참조
--------
- ADR-006 — provider wrapper 금지 (Protocol input shape만)
- ADR-009 — make_feature_id/source_record_key/payload_hash
- ADR-010 — WeatherValue 두 축 (forecast_style=observed, timeline=ultra_short)
- ADR-013/014 — bulk insert + BRIN
- ADR-018 — Feature.detail은 PlaceDetail/NoticeDetail instance
- ADR-024 — canonical provider name `python-krex-api`
- ADR-027 — NOTICE_TYPES (traffic/road_closure/roadwork/safety...) +
  normalize_notice_type alias
- ADR-041 — address utility 활용

설계 메모
--------
- rest_area Feature의 `uni_id`(휴게소 식별자) → `feature_id` 매핑은 본 함수가
  결정. 호출자는 prices/weather 변환 시 동일 `feature_id`를 전달
  (`KrexRestAreaCatalog` 같은 캐시 책임).
- 가격은 `REST_AREA_FOOD`(식음료) 또는 `REST_AREA_FUEL`(주유) — 입력 row의
  category 필드로 분기.
- 교통 공지는 휴게소가 아닌 도로 구간 단위 — `feature_id`는 notice 자체에
  결정적으로 생성 (`source_natural_key = notice_id`).
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from decimal import Decimal
from typing import Any, Final, Literal, Protocol, runtime_checkable

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
    ForecastStyle,
    NoticeDetail,
    PlaceDetail,
    PriceDomain,
    PriceValue,
    SourceLink,
    SourceRecord,
    SourceRole,
    TimelineBucket,
    WeatherDomain,
    WeatherValue,
)
from krtour.map.geocoding import (
    AddressResolver,
    ReverseGeocoder,
    cached_address_resolver,
    cached_reverse_geocoder,
)

__all__ = [
    # Protocols
    "KrexRestAreaItem",
    "KrexRestAreaPriceItem",
    "KrexRestAreaWeatherItem",
    "KrexTrafficNoticeItem",
    # 변환 함수
    "rest_areas_to_bundles",
    "rest_area_prices_to_values",
    "rest_area_weather_to_values",
    "traffic_notices_to_bundles",
    # 메타
    "KREX_PROVIDER_NAME",
    "REST_AREA_DATASET_KEY",
    "REST_AREA_PRICES_DATASET_KEY",
    "REST_AREA_WEATHER_DATASET_KEY",
    "TRAFFIC_NOTICES_DATASET_KEY",
    "REST_AREA_CATEGORY",
    "TRAFFIC_NOTICE_CATEGORY",
    "REST_AREA_MARKER_ICON",
    "REST_AREA_MARKER_COLOR",
    "TRAFFIC_NOTICE_MARKER_ICON",
    "TRAFFIC_NOTICE_MARKER_COLOR",
]


# -- 상수 --------------------------------------------------------------

KREX_PROVIDER_NAME: Final[str] = "python-krex-api"
"""canonical provider name (ADR-024)."""

REST_AREA_DATASET_KEY: Final[str] = "krex_rest_areas"
REST_AREA_PRICES_DATASET_KEY: Final[str] = "krex_rest_area_prices"
REST_AREA_WEATHER_DATASET_KEY: Final[str] = "krex_rest_area_weather"
TRAFFIC_NOTICES_DATASET_KEY: Final[str] = "krex_traffic_notices"

_REST_AREA_ENTITY_TYPE: Final[str] = "rest_area"
_TRAFFIC_NOTICE_ENTITY_TYPE: Final[str] = "traffic_notice"

REST_AREA_CATEGORY: Final[str] = "06040101"
"""`PlaceCategoryCode.TRANSPORT_REST_AREA_HIGHWAY_EX` — 고속도로 휴게소."""

# notice kind의 ``Feature.category``는 ADR-023 강제로 8자리 숫자. notice는
# `NoticeDetail.notice_type`가 진짜 분류 — category는 부차적이므로 PlaceCategory
# Code에 notice 도메인이 등록될 때까지 placeholder ``"99000000"`` 사용. 도메인
# 구분은 `NoticeDetail.payload['domain']='highway'`로.
TRAFFIC_NOTICE_CATEGORY: Final[str] = "99000000"

REST_AREA_MARKER_ICON: Final[str] = "fast-food"
REST_AREA_MARKER_COLOR: Final[str] = "P-06"

TRAFFIC_NOTICE_MARKER_ICON: Final[str] = "roadblock"
TRAFFIC_NOTICE_MARKER_COLOR: Final[str] = "P-13"


# -- Protocols ---------------------------------------------------------


@runtime_checkable
class KrexRestAreaItem(Protocol):
    """krex 휴게소 정보 row shape (place Feature 생성용)."""

    uni_id: str
    """휴게소 자연키 (provider 내 unique)."""

    name: str
    """휴게소명. Feature.name."""

    direction: str | None
    """방향 (예: '서울방향'/'부산방향')."""

    highway_name: str | None
    """고속도로 노선명 (예: '경부고속도로')."""

    address: str | None
    """전체 주소."""

    longitude: Decimal | None
    """경도 WGS84."""

    latitude: Decimal | None
    """위도 WGS84."""

    tel: str | None
    """대표 전화번호."""


@runtime_checkable
class KrexRestAreaPriceItem(Protocol):
    """krex 휴게소 가격 시계열 row shape (식음료 또는 주유)."""

    uni_id: str
    """휴게소 자연키."""

    category: Literal["food", "fuel"]
    """``food`` (식음료) 또는 ``fuel`` (주유) — PriceDomain 분기."""

    product_key: str
    """제품/메뉴 코드 (예: 'gasoline'/'diesel' 또는 'menu_001')."""

    product_name: str | None
    """제품/메뉴 한글 이름."""

    price: str | Decimal | int | float
    """가격 (KRW). food는 KRW/item, fuel은 KRW/L."""

    observed_at: datetime
    """관측 시각 (KST aware)."""


@runtime_checkable
class KrexRestAreaWeatherItem(Protocol):
    """krex 휴게소 관측 기상 row shape."""

    uni_id: str
    """휴게소 자연키."""

    metric_key: str
    """KMA 표준 호환 metric (T1H/REH/WSD/PTY 등)."""

    value: str | Decimal | int | float
    """관측값 (숫자 또는 코드 문자열)."""

    observed_at: datetime
    """관측 시각 (KST aware)."""

    unit: str | None
    """단위 override (없으면 metric_key로 KMA_METRIC_UNITS 참조)."""


@runtime_checkable
class KrexTrafficNoticeItem(Protocol):
    """krex 교통 공지 row shape (notice Feature 생성용)."""

    notice_id: str
    """공지 자연키 (provider 내 unique)."""

    title: str
    """공지 제목. Feature.name."""

    notice_type: str
    """공지 종류 (한/영 alias 가능 — `normalize_notice_type`이 정규화)."""

    description: str | None
    """공지 본문."""

    longitude: Decimal | None
    """발생 지점 경도 (있으면)."""

    latitude: Decimal | None
    """발생 지점 위도."""

    valid_from: datetime | None
    """효력 시작 (KST aware)."""

    valid_until: datetime | None
    """효력 종료 (KST aware)."""

    severity: int | None
    """0~5 등급 (NoticeDetail.severity)."""

    source_agency: str | None
    """발령 기관 (예: '한국도로공사')."""


# -- helpers -----------------------------------------------------------


def _coord_or_none(
    lat: Decimal | None, lon: Decimal | None
) -> Coordinate | None:
    if lat is None or lon is None:
        return None
    return Coordinate(lon=lon, lat=lat)


def _parse_numeric(raw: str | Decimal | int | float | None) -> Decimal | None:
    """가격/관측값 입력을 Decimal로 정규화 (천 단위 ',' 흡수, None pass-through)."""
    if raw is None:
        return None
    if isinstance(raw, Decimal):
        return raw
    if isinstance(raw, int | float):
        return Decimal(str(raw))
    cleaned = str(raw).replace(",", "").strip()
    if not cleaned:
        return None
    try:
        return Decimal(cleaned)
    except (ValueError, ArithmeticError):
        return None


async def _reverse_geocode(
    coord: Coordinate | None, geocoder: ReverseGeocoder | None
) -> tuple[str | None, str | None, str | None, str | None]:
    """reverse geocoding 결과 → (bjd_code, sigungu_code, sido_code, admin)."""
    if coord is None or geocoder is None:
        return (None, None, None, None)
    geo = await geocoder(coord)
    if geo is None:
        return (None, None, None, None)
    bjd = geo.bjd_code  # geocoding이 이미 정규화·검증
    sigungu = geo.sigungu_code or extract_sigungu_code(bjd)
    sido = geo.sido_code or extract_sido_code(bjd)
    return (bjd, sigungu, sido, geo.admin)


# -- rest_areas → place FeatureBundle ----------------------------------


async def _rest_area_item_to_bundle(
    item: KrexRestAreaItem,
    *,
    fetched_at: datetime,
    reverse_geocoder: ReverseGeocoder | None,
    address_resolver: AddressResolver | None,
) -> FeatureBundle:
    coord = _coord_or_none(item.latitude, item.longitude)
    bjd_code, sigungu, sido, admin = await _reverse_geocode(coord, reverse_geocoder)
    road_text = normalize_korean_text(item.address)
    road_name_code: str | None = None
    if bjd_code is None and address_resolver is not None:
        resolved = await address_resolver(Address(road=road_text))
        if resolved is not None and resolved.bjd_code is not None:
            bjd_code = resolved.bjd_code
            sigungu = resolved.sigungu_code or extract_sigungu_code(bjd_code)
            sido = resolved.sido_code or extract_sido_code(bjd_code)
            admin = resolved.admin
            road_name_code = resolved.road_name_code

    address = Address(
        road=road_text,
        admin=admin,
        bjd_code=bjd_code,
        sigungu_code=sigungu,
        sido_code=sido,
        road_name_code=road_name_code,
    )

    raw_data: dict[str, Any] = {
        "uni_id": item.uni_id,
        "name": item.name,
        "direction": item.direction,
        "highway_name": item.highway_name,
        "address": item.address,
        "longitude": str(item.longitude) if item.longitude is not None else None,
        "latitude": str(item.latitude) if item.latitude is not None else None,
        "tel": item.tel,
    }
    payload_hash = make_payload_hash(raw_data)
    source_record_key = make_source_record_key(
        provider=KREX_PROVIDER_NAME,
        dataset_key=REST_AREA_DATASET_KEY,
        source_entity_type=_REST_AREA_ENTITY_TYPE,
        source_entity_id=item.uni_id,
        raw_payload_hash=payload_hash,
    )
    feature_id = make_feature_id(
        bjd_code=bjd_code,
        kind=FeatureKind.PLACE.value,
        category=REST_AREA_CATEGORY,
        source_type=f"{KREX_PROVIDER_NAME}:{REST_AREA_DATASET_KEY}",
        source_natural_key=item.uni_id,
    )

    name_normalized = normalize_korean_text(item.name) or item.name
    phones: list[str] = []
    if item.tel:
        normalized_tel = normalize_phone_number(item.tel)
        if normalized_tel:
            phones.append(normalized_tel)

    feature = Feature(
        feature_id=feature_id,
        kind=FeatureKind.PLACE,
        name=name_normalized,
        coord=coord,
        address=address,
        category=REST_AREA_CATEGORY,
        marker_icon=REST_AREA_MARKER_ICON,
        marker_color=REST_AREA_MARKER_COLOR,
        detail=PlaceDetail(
            feature_id=feature_id,
            place_kind="rest_area",
            phones=phones,
            facility_info={
                "direction": item.direction,
                "highway_name": item.highway_name,
            },
        ),
    )

    source_record = SourceRecord(
        provider=normalize_provider_name(KREX_PROVIDER_NAME),
        dataset_key=REST_AREA_DATASET_KEY,
        source_entity_type=_REST_AREA_ENTITY_TYPE,
        source_entity_id=item.uni_id,
        raw_payload_hash=payload_hash,
        raw_name=item.name,
        raw_address=item.address,
        raw_longitude=item.longitude,
        raw_latitude=item.latitude,
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
        is_primary_source=True,
    )
    return FeatureBundle(
        feature=feature, source_record=source_record, source_link=source_link
    )


async def rest_areas_to_bundles(
    items: Iterable[KrexRestAreaItem],
    *,
    fetched_at: datetime,
    reverse_geocoder: ReverseGeocoder | None = None,
    address_resolver: AddressResolver | None = None,
) -> list[FeatureBundle]:
    """krex 휴게소 items → ``list[FeatureBundle]`` (place kind, 1차 source).

    호출자는 결과 bundle의 `feature_id`를 캐시(uni_id → feature_id)로 두고
    `rest_area_prices_to_values`/`rest_area_weather_to_values` 호출 시 동일
    `feature_id`를 전달.

    Notes
    -----
    휴게소명(`name`) 또는 `uni_id`가 빈 레코드는 유효 `Feature`(name 1자 이상,
    source key 필요)를 구성할 수 없어 **skip**한다. EX OpenAPI
    ``serviceAreaRoute``가 간혹 모든 표시 필드가 ``null``인 placeholder 행을
    반환하므로(실측, ADR-044) 방어적으로 거른다.
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
    bundles: list[FeatureBundle] = []
    for item in items:
        if not (item.name or "").strip() or not (item.uni_id or "").strip():
            continue
        bundles.append(
            await _rest_area_item_to_bundle(
                item,
                fetched_at=fetched_at,
                reverse_geocoder=geocoder,
                address_resolver=resolver,
            )
        )
    return bundles


# -- rest_area_prices → PriceValue 시계열 ------------------------------


def _price_domain_for(category: str) -> PriceDomain:
    if category == "fuel":
        return PriceDomain.REST_AREA_FUEL
    if category == "food":
        return PriceDomain.REST_AREA_FOOD
    raise ValueError(
        f"krex rest_area price category는 'food' or 'fuel' (got {category!r})."
    )


def _price_unit_for(category: str) -> str:
    return "KRW/L" if category == "fuel" else "KRW"


def _rest_area_price_item_to_value(
    item: KrexRestAreaPriceItem,
    *,
    feature_id: str,
    source_record_key: str | None,
) -> PriceValue:
    value_number = _parse_numeric(item.price)
    if value_number is None:
        raise ValueError(
            f"krex rest_area price.price이 numeric이 아님 — uni_id={item.uni_id!r}, "
            f"product_key={item.product_key!r}, raw={item.price!r}."
        )

    payload: dict[str, Any] = {
        "uni_id": item.uni_id,
        "category": item.category,
        "product_key": item.product_key,
        "product_name": item.product_name,
        "price": str(item.price),
        "observed_at": item.observed_at.isoformat(),
    }

    return PriceValue(
        feature_id=feature_id,
        provider=normalize_provider_name(KREX_PROVIDER_NAME),
        price_domain=_price_domain_for(item.category),
        product_key=item.product_key,
        product_name=normalize_korean_text(item.product_name),
        observed_at=item.observed_at,
        value_number=value_number,
        unit=_price_unit_for(item.category),
        normalization_version="krex-v1.0",
        payload=payload,
        source_record_key=source_record_key,
    )


def rest_area_prices_to_values(
    items: Iterable[KrexRestAreaPriceItem],
    *,
    feature_id: str,
    source_record_key: str | None = None,
) -> list[PriceValue]:
    """krex 휴게소 가격 시계열 → ``list[PriceValue]``.

    `feature_id`는 호출자가 `rest_areas_to_bundles` 결과의 feature_id를 전달.
    """
    return [
        _rest_area_price_item_to_value(
            item,
            feature_id=feature_id,
            source_record_key=source_record_key,
        )
        for item in items
    ]


# -- rest_area_weather → WeatherValue (observed) -----------------------


def _rest_area_weather_item_to_value(
    item: KrexRestAreaWeatherItem,
    *,
    feature_id: str,
    source_record_key: str | None,
) -> WeatherValue:
    value_number = _parse_numeric(item.value)
    value_text = (
        None
        if value_number is not None
        else (str(item.value).strip() or None)
    )

    payload: dict[str, Any] = {
        "uni_id": item.uni_id,
        "metric_key": item.metric_key,
        "value": str(item.value),
        "observed_at": item.observed_at.isoformat(),
        "unit": item.unit,
    }

    return WeatherValue(
        feature_id=feature_id,
        provider=normalize_provider_name(KREX_PROVIDER_NAME),
        weather_domain=WeatherDomain.REST_AREA_WEATHER,
        forecast_style=ForecastStyle.OBSERVED,
        timeline_bucket=TimelineBucket.ULTRA_SHORT,
        metric_key=item.metric_key,
        source_metric_key=item.metric_key,
        unit=item.unit,
        observed_at=item.observed_at,
        value_number=value_number,
        value_text=value_text,
        normalization_version="krex-v1.0",
        payload=payload,
        source_record_key=source_record_key,
    )


def rest_area_weather_to_values(
    items: Iterable[KrexRestAreaWeatherItem],
    *,
    feature_id: str,
    source_record_key: str | None = None,
) -> list[WeatherValue]:
    """krex 휴게소 관측 기상 → ``list[WeatherValue]`` (forecast_style=observed)."""
    return [
        _rest_area_weather_item_to_value(
            item,
            feature_id=feature_id,
            source_record_key=source_record_key,
        )
        for item in items
    ]


# -- traffic_notices → notice FeatureBundle ----------------------------


async def _traffic_notice_item_to_bundle(
    item: KrexTrafficNoticeItem,
    *,
    fetched_at: datetime,
    reverse_geocoder: ReverseGeocoder | None,
) -> FeatureBundle:
    coord = _coord_or_none(item.latitude, item.longitude)
    bjd_code, sigungu, sido, admin = await _reverse_geocode(coord, reverse_geocoder)

    address = Address(
        admin=admin,
        bjd_code=bjd_code,
        sigungu_code=sigungu,
        sido_code=sido,
    )

    raw_data: dict[str, Any] = {
        "notice_id": item.notice_id,
        "title": item.title,
        "notice_type": item.notice_type,
        "description": item.description,
        "longitude": str(item.longitude) if item.longitude is not None else None,
        "latitude": str(item.latitude) if item.latitude is not None else None,
        "valid_from": item.valid_from.isoformat() if item.valid_from else None,
        "valid_until": item.valid_until.isoformat() if item.valid_until else None,
        "severity": item.severity,
        "source_agency": item.source_agency,
    }
    payload_hash = make_payload_hash(raw_data)
    source_record_key = make_source_record_key(
        provider=KREX_PROVIDER_NAME,
        dataset_key=TRAFFIC_NOTICES_DATASET_KEY,
        source_entity_type=_TRAFFIC_NOTICE_ENTITY_TYPE,
        source_entity_id=item.notice_id,
        raw_payload_hash=payload_hash,
    )
    feature_id = make_feature_id(
        bjd_code=bjd_code,
        kind=FeatureKind.NOTICE.value,
        category=TRAFFIC_NOTICE_CATEGORY,
        source_type=f"{KREX_PROVIDER_NAME}:{TRAFFIC_NOTICES_DATASET_KEY}",
        source_natural_key=item.notice_id,
    )

    title_normalized = normalize_korean_text(item.title) or item.title

    feature = Feature(
        feature_id=feature_id,
        kind=FeatureKind.NOTICE,
        name=title_normalized,
        coord=coord,
        address=address,
        category=TRAFFIC_NOTICE_CATEGORY,
        marker_icon=TRAFFIC_NOTICE_MARKER_ICON,
        marker_color=TRAFFIC_NOTICE_MARKER_COLOR,
        detail=NoticeDetail(
            feature_id=feature_id,
            notice_type=item.notice_type,  # normalize_notice_type가 validator에서 정규화
            severity=item.severity,
            valid_start_time=item.valid_from,
            valid_end_time=item.valid_until,
            source_agency=normalize_korean_text(item.source_agency),
            payload={
                "domain": "highway",
                "description": normalize_korean_text(item.description),
            },
        ),
    )

    source_record = SourceRecord(
        provider=normalize_provider_name(KREX_PROVIDER_NAME),
        dataset_key=TRAFFIC_NOTICES_DATASET_KEY,
        source_entity_type=_TRAFFIC_NOTICE_ENTITY_TYPE,
        source_entity_id=item.notice_id,
        raw_payload_hash=payload_hash,
        raw_name=item.title,
        raw_longitude=item.longitude,
        raw_latitude=item.latitude,
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
        is_primary_source=True,
    )
    return FeatureBundle(
        feature=feature, source_record=source_record, source_link=source_link
    )


async def traffic_notices_to_bundles(
    items: Iterable[KrexTrafficNoticeItem],
    *,
    fetched_at: datetime,
    reverse_geocoder: ReverseGeocoder | None = None,
) -> list[FeatureBundle]:
    """krex 교통 공지 items → ``list[FeatureBundle]`` (notice kind).

    `Feature(kind=notice)` + `NoticeDetail`. notice_type은 한/영 alias 입력 가능
    (NoticeDetail validator의 ``normalize_notice_type``이 canonical 변환).
    """
    geocoder = (
        cached_reverse_geocoder(reverse_geocoder)
        if reverse_geocoder is not None
        else None
    )
    return [
        await _traffic_notice_item_to_bundle(
            item, fetched_at=fetched_at, reverse_geocoder=geocoder
        )
        for item in items
    ]
