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
- rest_area dataset(`tn_pubr_public_rest_area_api`)에는 안정 식별자가 없어
  (ADR-044 실측) 자연키를 krtour 측에서 `name`+`route_name`+`direction`으로
  파생한다(`_rest_area_natural_key`). 이 파생키 → `feature_id` 매핑은 본 함수가
  결정. 호출자는 prices/weather 변환 시 동일 `feature_id`를 전달
  (`KrexRestAreaCatalog` 같은 캐시 책임). prices/weather row의 `uni_id`는 별도
  dataset의 자연키로 본 reconciliation 범위 밖이다.
- 가격은 `REST_AREA_FOOD`(식음료) 또는 `REST_AREA_FUEL`(주유) — 입력 row의
  category 필드로 분기.
- 교통 공지(traffic notice)는 provider ``krex.models.Incident``를 mirror한다
  (ADR-044 실측 — provider PR#9에서 실시간 돌발 API ``openapi/burstInfo/
  realTimeSms``(apiId 0611)로 repoint, #378). Incident가 노출하는 건
  occurred_date/occurred_time/incident_type(+code)/direction/message/point_name/
  route_no/route_name/process_status(+code)/latitude/longitude/congestion_length/
  series_no/raw이며, notice Feature에 필요한 나머지 파생값(자연키·제목·
  notice_type·효력기간·source_agency)은 krtour 변환부
  (`_traffic_notice_item_to_bundle`)가 생성한다.
- Incident에는 안정 식별자가 없어 자연키를 krtour 측에서 파생한다
  (`_traffic_notice_natural_key`): occurred_date + occurred_time + route_no +
  raw payload hash. 좌표(latitude/longitude)는 일부 row에만 있다(실측 36/99) —
  좌표가 있으면 Coordinate + reverse geocoding, 없으면 **coordless**
  (bjd_code 미상 → global feature_id, 노선/지점/방향이 위치 단서).
- **transient 주의**: EX 돌발(incident) feed는 해소된 사건이 사라지는 휘발성
  피드다. notice Feature로 적재하면 재실행마다 현재 활성 집합으로 refresh된다.
  realTimeSms에는 종료 시각 컬럼이 없어 `valid_until`은 None — 만료는 feed
  refresh(사라짐) + `process_status`(payload 보존)가 표현한다. 실행 사이 stale
  Feature가 남는 건 정상 동작이다.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime, time, timedelta, timezone
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
    normalize_notice_type,
)
from krtour.map.geocoding import (
    AddressResolver,
    ReverseGeocoder,
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

_KST: Final[timezone] = timezone(timedelta(hours=9))
"""ADR-019 — naive하게 파싱된 incident datetime에 부착할 KST tzinfo."""

_TRAFFIC_NOTICE_SOURCE_AGENCY: Final[str] = "한국도로공사"
"""krex EX = 한국도로공사(Korea Expressway Corp) — Incident에 기관 컬럼이 없어
변환부가 고정 부여한다 (ADR-044)."""

_TRAFFIC_NOTICE_DEFAULT_TYPE: Final[str] = "traffic"
"""Incident.incident_type이 NOTICE_TYPES/alias에 매핑되지 않을 때의 fallback
notice_type (ADR-027 generic). EX incidentType 원문은 payload/title에 보존."""


# -- Protocols ---------------------------------------------------------


@runtime_checkable
class KrexRestAreaItem(Protocol):
    """krex 휴게소 정보 row shape (place Feature 생성용).

    provider model ``krex.models.RestArea`` 정합 (ADR-024/044). 이 dataset
    (``tn_pubr_public_rest_area_api``, ``KrexClient.restarea.list_all``)은
    **안정 식별자(uni_id)도 주소 컬럼도 없다**. 따라서 자연키는 krtour 측에서
    ``name``+``route_name``+``direction`` 조합으로 파생한다
    (``_rest_area_natural_key``).

    파생 자연키 tradeoff (사용자 승인, ADR-009/016)
    - **충돌**: 같은 name+route_name+direction을 가진 서로 다른 휴게소는 동일
      키로 묶여 dedup된다.
    - **rename 단절**: 휴게소명/노선/방향 표기가 바뀌면 키가 달라져 기존
      Feature와의 dedup이 끊긴다(신규 Feature로 적재).
    """

    name: str
    """휴게소명. Feature.name. (provider ``RestArea.name``)"""

    route_name: str | None
    """고속도로 노선명 (예: '경부고속도로'). (provider ``RestArea.route_name``)"""

    direction: str | None
    """방향 (예: '서울방향'/'부산방향'). (provider ``RestArea.direction``)"""

    lon: float | Decimal | None
    """경도 WGS84. provider는 ``float`` — 변환부에서 ``Decimal(str(...))`` 강제."""

    lat: float | Decimal | None
    """위도 WGS84. provider는 ``float`` — 변환부에서 ``Decimal(str(...))`` 강제."""

    phone_number: str | None
    """대표 전화번호. (provider ``RestArea.phone_number``)"""


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
    """krex 교통 공지(돌발) row shape — provider ``krex.models.Incident`` 정합.

    ADR-044 실측 (provider PR#9, ``openapi/burstInfo/realTimeSms`` repoint, #378):
    notice Feature가 필요로 하는 식별자/제목/notice_type/효력기간/severity/기관은
    **provider에 없으므로** krtour 변환부(`_traffic_notice_item_to_bundle`)가
    전부 파생한다. 좌표(latitude/longitude)는 일부 row에만 있다(실측 36/99).

    파생 자연키 tradeoff (사용자 승인, ADR-009/044)
    - Incident에 안정 id가 없어 occurred_date+occurred_time+route_no+raw payload
      hash로 자연키를 파생한다(`_traffic_notice_natural_key`). raw가 byte 단위로
      바뀌면(예: smsText 수정, accProcessCode 진행→완료 전이) 자연키가 달라져
      새 Feature로 적재될 수 있다.
    - EX 돌발 feed는 휘발성(transient) — 해소된 사건은 사라진다. 재실행마다
      활성 집합으로 refresh. realTimeSms에는 종료 시각 컬럼이 없어
      `valid_until`은 None(모듈 docstring 참조).
    """

    occurred_date: str | None
    """발생 일자 (예: '2023.09.27'). (provider ``Incident.occurred_date`` ←
    원천 ``accDate``) 방어적 파싱 — `_parse_krex_occurrence`."""

    occurred_time: str | None
    """발생 시각 (예: '09:11:24'). (provider ``Incident.occurred_time`` ←
    원천 ``accHour``)"""

    incident_type: str | None
    """돌발유형명 (예: '이벤트/홍보'). (provider ``Incident.incident_type`` ←
    원천 ``accType``) 변환부가 `normalize_notice_type`로 정규화, 실패 시
    ``traffic`` fallback."""

    incident_type_code: str | None
    """돌발유형 코드 (예: '15'). (provider ``Incident.incident_type_code`` ←
    원천 ``accTypeCode``)"""

    direction: str | None
    """방향 한글 텍스트 (예: '대구방향'). (provider ``Incident.direction`` ←
    원천 ``startEndTypeCode``)"""

    message: str | None
    """돌발 문자 본문. (provider ``Incident.message`` ← 원천 ``smsText``)
    Feature.name/description 파생."""

    point_name: str | None
    """돌발지점명. (provider ``Incident.point_name`` ← 원천 ``accPointNM``,
    whitespace-only는 provider가 None 처리)"""

    route_no: str | None
    """노선 번호 (예: '0552'). (provider ``Incident.route_no`` ← 원천 ``nosunNM``)"""

    route_name: str | None
    """노선명 (예: '대구부산선'). (provider ``Incident.route_name`` ← 원천 ``roadNM``)"""

    process_status: str | None
    """처리 상태명 (예: '진행'). (provider ``Incident.process_status`` ←
    원천 ``accProcessNM``)"""

    process_status_code: str | None
    """처리 상태 코드 (예: '1'). (provider ``Incident.process_status_code`` ←
    원천 ``accProcessCode``)"""

    latitude: float | Decimal | None
    """위도 WGS84 (일부 row만). provider는 ``float`` — 변환부에서
    ``Decimal(str(...))`` 강제. (provider ``Incident.latitude``)"""

    longitude: float | Decimal | None
    """경도 WGS84 (일부 row만). **원천 키는 ``altitude``** — provider가 경도로
    매핑한다(포털 명세 '돌발시작이정경도'). (provider ``Incident.longitude``)"""

    congestion_length: float | None
    """정체 길이 km. (provider ``Incident.congestion_length`` ← 원천 ``lateLength``)"""

    series_no: int | None
    """연번. (provider ``Incident.series_no`` ← 원천 ``seriesNM``)"""

    raw: dict[str, Any]
    """provider 원본 row. 자연키 hash + payload 보존에 사용. (provider ``Incident.raw``)"""


# -- helpers -----------------------------------------------------------


def _coord_or_none(
    lat: Decimal | None, lon: Decimal | None
) -> Coordinate | None:
    if lat is None or lon is None:
        return None
    return Coordinate(lon=lon, lat=lat)


def _to_decimal_or_none(value: float | Decimal | None) -> Decimal | None:
    """provider 좌표(``float``)를 deterministic하게 ``Decimal``로 강제.

    ``Decimal(str(...))``로 float repr의 이진 잡음 없이 변환한다(ADR-044 —
    provider ``RestArea.lat/lon``은 ``float``).
    """
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _rest_area_natural_key(item: KrexRestAreaItem) -> str:
    """krtour 측 파생 자연키 — ``name``+``route_name``+``direction``.

    source(``tn_pubr_public_rest_area_api``)에 안정 식별자가 없어
    (option 2, 사용자 결정) 세 필드를 normalize(strip→lower)해 ``::``로 잇는다
    (None은 ``""``). 구분자는 mois(``{slug}::{mng_no}``)와 동일 ``::`` — ID 시스템이
    예약한 ``|``를 피한다(ADR-009 `_validate_component`). 충돌·rename 단절 tradeoff는
    ``KrexRestAreaItem`` docstring 참조(ADR-009/016).
    """
    parts = (
        (item.name or "").strip().lower(),
        (item.route_name or "").strip().lower(),
        (item.direction or "").strip().lower(),
    )
    return "::".join(parts)


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
) -> FeatureBundle:
    lon = _to_decimal_or_none(item.lon)
    lat = _to_decimal_or_none(item.lat)
    coord = _coord_or_none(lat, lon)
    bjd_code, sigungu, sido, admin = await _reverse_geocode(coord, reverse_geocoder)
    # source(tn_pubr_public_rest_area_api)에 주소 컬럼이 없어 road는 항상 None
    # (좌표 reverse geocoding만으로 행정구역을 채운다). address_resolver fallback은
    # 입력 주소가 없으므로 적용 불가 — 좌표가 없으면 bjd_code 미상으로 남는다.
    road_name_code: str | None = None

    address = Address(
        road=None,
        admin=admin,
        bjd_code=bjd_code,
        sigungu_code=sigungu,
        sido_code=sido,
        road_name_code=road_name_code,
    )

    natural_key = _rest_area_natural_key(item)
    raw_data: dict[str, Any] = {
        "natural_key": natural_key,
        "name": item.name,
        "route_name": item.route_name,
        "direction": item.direction,
        "lon": str(lon) if lon is not None else None,
        "lat": str(lat) if lat is not None else None,
        "phone_number": item.phone_number,
    }
    payload_hash = make_payload_hash(raw_data)
    source_record_key = make_source_record_key(
        provider=KREX_PROVIDER_NAME,
        dataset_key=REST_AREA_DATASET_KEY,
        source_entity_type=_REST_AREA_ENTITY_TYPE,
        source_entity_id=natural_key,
        raw_payload_hash=payload_hash,
    )
    feature_id = make_feature_id(
        bjd_code=bjd_code,
        kind=FeatureKind.PLACE.value,
        category=REST_AREA_CATEGORY,
        source_type=f"{KREX_PROVIDER_NAME}:{REST_AREA_DATASET_KEY}",
        source_natural_key=natural_key,
    )

    name_normalized = normalize_korean_text(item.name) or item.name
    phones: list[str] = []
    if item.phone_number:
        normalized_tel = normalize_phone_number(item.phone_number)
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
                # 출력 키 "highway_name"은 PlaceDetail 계약 유지 — 값은 provider
                # ``RestArea.route_name``에서 읽는다(입력 reconciliation, ADR-044).
                "direction": item.direction,
                "highway_name": item.route_name,
            },
        ),
    )

    source_record = SourceRecord(
        provider=normalize_provider_name(KREX_PROVIDER_NAME),
        dataset_key=REST_AREA_DATASET_KEY,
        source_entity_type=_REST_AREA_ENTITY_TYPE,
        source_entity_id=natural_key,
        raw_payload_hash=payload_hash,
        raw_name=item.name,
        raw_address=None,
        raw_longitude=lon,
        raw_latitude=lat,
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

    호출자는 결과 bundle의 `feature_id`를 캐시(파생 자연키 → feature_id)로 두고
    `rest_area_prices_to_values`/`rest_area_weather_to_values` 호출 시 동일
    `feature_id`를 전달.

    `address_resolver`는 다른 provider와의 호출 시그니처 호환을 위해 받지만,
    이 dataset에는 주소 컬럼이 없어(ADR-044) **사용되지 않는다** — 행정구역은
    `reverse_geocoder`(좌표 기반)로만 채운다.

    Notes
    -----
    휴게소명(`name`)이 빈 레코드는 유효 `Feature`(name 1자 이상)도 의미 있는
    파생 자연키도 만들 수 없어 **skip**한다. data.go.kr
    ``tn_pubr_public_rest_area_api``가 간혹 표시 필드가 ``null``인 placeholder
    행을 반환하므로(실측, ADR-044) 방어적으로 거른다.
    """
    _ = address_resolver  # 호환용 — 본 dataset은 주소가 없어 미사용 (위 docstring).
    geocoder = (
        cached_reverse_geocoder(reverse_geocoder)
        if reverse_geocoder is not None
        else None
    )
    bundles: list[FeatureBundle] = []
    for item in items:
        if not (item.name or "").strip():
            continue
        bundles.append(
            await _rest_area_item_to_bundle(
                item,
                fetched_at=fetched_at,
                reverse_geocoder=geocoder,
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

_KREX_OCCURRED_DATE_FORMATS: Final[tuple[str, ...]] = (
    "%Y.%m.%d",
    "%Y-%m-%d",
    "%Y%m%d",
)
"""``_parse_krex_occurrence``가 차례로 시도할 발생 일자 strptime 포맷
(실측 정본은 ``"2023.09.27"`` — 나머지는 방어적 fallback)."""

_KREX_OCCURRED_TIME_FORMATS: Final[tuple[str, ...]] = (
    "%H:%M:%S",
    "%H:%M",
    "%H%M%S",
)
"""``_parse_krex_occurrence``가 차례로 시도할 발생 시각 strptime 포맷
(실측 정본은 ``"09:11:24"``)."""


def _parse_krex_occurrence(
    occurred_date: str | None, occurred_time: str | None
) -> datetime | None:
    """EX incident의 occurred_date+occurred_time을 KST aware datetime으로 방어적 파싱.

    realTimeSms는 발생 시각을 ``accDate``("2023.09.27") + ``accHour``("09:11:24")
    두 컬럼으로 쪼개 내려준다(ADR-044 실측, #378). 일자 파싱 실패 시 None,
    시각 파싱 실패/부재 시 해당 일자의 자정으로 강등한다(일자만이라도 보존).
    naive 결과엔 KST tzinfo를 부착한다(ADR-019).
    """
    date_text = (occurred_date or "").strip()
    if not date_text:
        return None
    parsed_date: date | None = None
    for fmt in _KREX_OCCURRED_DATE_FORMATS:
        try:
            parsed_date = datetime.strptime(date_text, fmt).date()
            break
        except ValueError:
            continue
    if parsed_date is None:
        return None
    parsed_time = time(0, 0)
    time_text = (occurred_time or "").strip()
    if time_text:
        for fmt in _KREX_OCCURRED_TIME_FORMATS:
            try:
                parsed_time = datetime.strptime(time_text, fmt).time()
                break
            except ValueError:
                continue
    return datetime.combine(parsed_date, parsed_time, tzinfo=_KST)


def _traffic_notice_natural_key(item: KrexTrafficNoticeItem) -> str:
    """krtour 측 파생 자연키 — ``occurred_date::occurred_time::route_no::raw_hash``.

    provider ``Incident``에 안정 식별자가 없어(ADR-044) 네 성분을 normalize
    (strip→lower) 후 ``::``로 잇는다 — ID 시스템이 예약한 ``|``를 피한다
    (mois/rest_areas와 동일 구분자, ADR-009 `_validate_component`). raw payload
    hash로 동일 노선/발생시각이라도 본문이 다른 사건을 구분한다.

    tradeoff (#378): raw에는 ``accProcessCode``(처리 상태)·``smsText``가 포함되어
    상태 전이(진행→완료)나 문구 수정만으로도 raw hash가 바뀌어 새 Feature로
    적재된다 — transient feed라 재실행 refresh가 전제이므로 수용(구 scheme의
    started_at 성분을 occurred_date+occurred_time으로 대체, 나머지 성질 동일).
    충돌·재적재 tradeoff는 ``KrexTrafficNoticeItem`` docstring 참조.
    """
    parts = (
        (item.occurred_date or "").strip().lower(),
        (item.occurred_time or "").strip().lower(),
        (item.route_no or "").strip().lower(),
        make_payload_hash(item.raw),
    )
    return "::".join(parts)


def _safe_notice_type(incident_type: str | None) -> str:
    """incident_type → canonical notice_type, 매핑 실패 시 generic fallback.

    EX incidentType 원문(코드/한글)은 NOTICE_TYPES/alias에 없을 수 있어
    (`normalize_notice_type` ValueError) ``traffic``으로 강등한다(ADR-027). 원문은
    title/payload에 보존된다.
    """
    if incident_type is None or not incident_type.strip():
        return _TRAFFIC_NOTICE_DEFAULT_TYPE
    try:
        return normalize_notice_type(incident_type.strip())
    except ValueError:
        return _TRAFFIC_NOTICE_DEFAULT_TYPE


def _synthesize_notice_title(item: KrexTrafficNoticeItem) -> str:
    """Incident → 비어있지 않은 ``Feature.name`` 합성.

    ``[{route_name|route_no|'고속도로'}] {incident_type|'교통정보'}`` 형태. route와
    type가 모두 비면 point_name(돌발지점명) → message 순으로 80자 truncate해
    쓰고, 그것도 비면 최종 기본 문구를 반환한다(Feature.name은 1자 이상).
    """
    route = (item.route_name or item.route_no or "").strip()
    itype = (item.incident_type or "").strip()
    if route or itype:
        return f"[{route or '고속도로'}] {itype or '교통정보'}".strip()
    point = (item.point_name or "").strip()
    if point:
        return point[:80]
    message = (item.message or "").strip()
    if message:
        return message[:80]
    return "고속도로 교통정보"


async def _traffic_notice_item_to_bundle(
    item: KrexTrafficNoticeItem,
    *,
    fetched_at: datetime,
    reverse_geocoder: ReverseGeocoder | None,
) -> FeatureBundle:
    # realTimeSms는 일부 row에만 좌표가 있다(실측 36/99, #378). 좌표가 있으면
    # reverse geocoding으로 행정구역을 채우고, 없으면 bjd_code 미상 →
    # global feature_id.
    lon = _to_decimal_or_none(item.longitude)
    lat = _to_decimal_or_none(item.latitude)
    coord = _coord_or_none(lat, lon)
    bjd_code, sigungu, sido, admin = await _reverse_geocode(coord, reverse_geocoder)

    address = Address(
        admin=admin,
        bjd_code=bjd_code,
        sigungu_code=sigungu,
        sido_code=sido,
    )

    natural_key = _traffic_notice_natural_key(item)
    notice_type = _safe_notice_type(item.incident_type)
    title = _synthesize_notice_title(item)
    valid_from = _parse_krex_occurrence(item.occurred_date, item.occurred_time)
    # realTimeSms에는 종료 시각 컬럼이 없다(#378) — transient feed 만료는 refresh
    # (사라짐) + process_status(payload 보존)가 표현한다(모듈 docstring).
    valid_until: datetime | None = None
    # coordless row는 좌표·주소 둘 다 없으면 주소 검증이 ``missing_address``
    # error로 막으므로(validation.py), 노선명/번호·돌발지점명·방향을 위치 단서
    # (raw_address)로 채워 coordless notice도 적재되게 한다(ADR-044).
    location_clue = (
        " ".join(
            part
            for part in (
                (item.route_name or item.route_no or "").strip(),
                (item.point_name or "").strip(),
                (item.direction or "").strip(),
            )
            if part
        )
        or None
    )

    raw_data: dict[str, Any] = {
        "natural_key": natural_key,
        "occurred_date": item.occurred_date,
        "occurred_time": item.occurred_time,
        "incident_type": item.incident_type,
        "incident_type_code": item.incident_type_code,
        "direction": item.direction,
        "message": item.message,
        "point_name": item.point_name,
        "route_no": item.route_no,
        "route_name": item.route_name,
        "process_status": item.process_status,
        "process_status_code": item.process_status_code,
        "latitude": str(lat) if lat is not None else None,
        "longitude": str(lon) if lon is not None else None,
        "congestion_length": item.congestion_length,
        "series_no": item.series_no,
    }
    payload_hash = make_payload_hash(raw_data)
    source_record_key = make_source_record_key(
        provider=KREX_PROVIDER_NAME,
        dataset_key=TRAFFIC_NOTICES_DATASET_KEY,
        source_entity_type=_TRAFFIC_NOTICE_ENTITY_TYPE,
        source_entity_id=natural_key,
        raw_payload_hash=payload_hash,
    )
    feature_id = make_feature_id(
        bjd_code=bjd_code,
        kind=FeatureKind.NOTICE.value,
        category=TRAFFIC_NOTICE_CATEGORY,
        source_type=f"{KREX_PROVIDER_NAME}:{TRAFFIC_NOTICES_DATASET_KEY}",
        source_natural_key=natural_key,
    )

    title_normalized = normalize_korean_text(title) or title

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
            notice_type=notice_type,  # NoticeDetail validator가 다시 정규화(이미 canonical)
            severity=None,  # Incident에 등급 컬럼 없음(ADR-044).
            valid_start_time=valid_from,
            valid_end_time=valid_until,
            source_agency=_TRAFFIC_NOTICE_SOURCE_AGENCY,
            payload={
                "domain": "highway",
                "description": normalize_korean_text(item.message),
                "route_no": item.route_no,
                "route_name": item.route_name,
                "incident_type": item.incident_type,
                "incident_type_code": item.incident_type_code,
                "point_name": item.point_name,
                "direction": item.direction,
                "process_status": item.process_status,
                "process_status_code": item.process_status_code,
            },
        ),
    )

    source_record = SourceRecord(
        provider=normalize_provider_name(KREX_PROVIDER_NAME),
        dataset_key=TRAFFIC_NOTICES_DATASET_KEY,
        source_entity_type=_TRAFFIC_NOTICE_ENTITY_TYPE,
        source_entity_id=natural_key,
        raw_payload_hash=payload_hash,
        raw_name=title,
        raw_address=location_clue,
        raw_longitude=lon,
        raw_latitude=lat,
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
    """krex 교통 공지(돌발) items → ``list[FeatureBundle]`` (notice kind).

    입력은 provider ``krex.models.Incident``(realTimeSms, #378 — 또는 동일 shape)
    이며, notice Feature에 필요한 모든 파생값은 본 변환부가 생성한다(ADR-044
    reconciliation): 자연키(`_traffic_notice_natural_key`), 제목
    (`_synthesize_notice_title`), notice_type(`_safe_notice_type` — 매핑 실패 시
    ``traffic``), 발생 시각(`_parse_krex_occurrence` → valid_start_time;
    종료 컬럼이 없어 valid_end_time은 None), source_agency(``한국도로공사`` 고정).
    좌표가 있는 row(실측 36/99)는 Coordinate + reverse geocoding, 없는 row는
    coordless(global feature_id, 노선/지점/방향이 raw_address 위치 단서)다.

    **transient feed**: 해소된 incident는 사라지므로 재실행마다 활성 집합으로
    refresh되고, 실행 사이 stale Feature가 남는 건 정상이다(모듈 docstring).
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
