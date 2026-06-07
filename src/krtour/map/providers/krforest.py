"""``krtour.map.providers.krforest`` — 산림청 휴양림/수목원 → FeatureBundle.

본 모듈은 ``python-krforest-api``(``import krforest``)의 typed model을 본 라이브러리의
``FeatureBundle``(place)로 정규화한다. provider client + model은 별도 라이브러리가
제공(ADR-006 wrapper 금지: 본 모듈은 변환 순수 함수, client 호출은 호출자가 직접).

지원 dataset (ADR-034 8단계 — MOIS-sibling):

- ``krforest_recreation_forests`` (place) — ``recreation_forests_to_bundles``,
  provider ``travel.standard_recreation_forests()``.
- ``krforest_arboretums`` (place) — ``arboretums_to_bundles``,
  provider ``travel.recreation_forest_arboretums()`` (SHP file).

- 휴양림(recreation forest) → category ``LODGING_RECREATION_FOREST``(03030000),
  place_kind ``recreation_forest``. MOIS ``condo_resorts``/``tourist_accommodations``와
  dedup sibling(ADR-034).
- 수목원/식물원(arboretum) → category ``TOURISM_BOTANICAL``(01030000), place_kind
  ``arboretum``. MOIS ``botanical_gardens``와 dedup sibling.

provider 좌표는 WGS84 ``float``(``latitude``/``longitude``)이며, 본 라이브러리는
WGS84만 받는다(ADR-012). ``Coordinate``는 ``Decimal``이므로 ``Decimal(str(x))``로 변환
한다. ``standard_data`` 패턴과 동일하게 변환 함수는 **async**(feature_id가 bjd_code에
의존, ADR-009)이고 좌표 reverse / 주소 geocode로 행정코드를 보강한다.

ADR 참조
--------
- ADR-006 / ADR-009 / ADR-012 / ADR-016 / ADR-019 / ADR-024 / ADR-034
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from decimal import Decimal
from typing import Any, Final, Protocol, runtime_checkable

from krtour.map.category import (
    PlaceCategoryCode,
    mapbox_maki_icon_or_none,
)
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
    "ForestSpatialItem",
    "RecreationForestItem",
    "arboretums_to_bundles",
    "recreation_forests_to_bundles",
    # 상수
    "DATASET_KEY_ARBORETUMS",
    "DATASET_KEY_RECREATION_FORESTS",
    "KRFOREST_MARKER_COLOR",
    "RECREATION_FOREST_CATEGORY",
    "ARBORETUM_CATEGORY",
]


# -- 상수 -----------------------------------------------------------------

KRFOREST_PROVIDER_NAME: Final[str] = "python-krforest-api"
"""canonical provider name (ADR-024 ``CANONICAL_PROVIDER_NAMES``)."""

DATASET_KEY_RECREATION_FORESTS: Final[str] = "krforest_recreation_forests"
DATASET_KEY_ARBORETUMS: Final[str] = "krforest_arboretums"

_RECREATION_FOREST_ENTITY_TYPE: Final[str] = "recreation_forest"
_ARBORETUM_ENTITY_TYPE: Final[str] = "arboretum"

RECREATION_FOREST_CATEGORY: Final[str] = PlaceCategoryCode.LODGING_RECREATION_FOREST.value
"""``Feature.category`` — 휴양림 03030000."""

ARBORETUM_CATEGORY: Final[str] = PlaceCategoryCode.TOURISM_BOTANICAL.value
"""``Feature.category`` — 수목원·식물원 01030000."""

RECREATION_FOREST_PLACE_KIND: Final[str] = "recreation_forest"
ARBORETUM_PLACE_KIND: Final[str] = "arboretum"

KRFOREST_MARKER_COLOR: Final[str] = "P-05"
"""산림 계열 marker color (녹색 계열 팔레트, ADR-029 P-01~P-16 범위)."""

_DEFAULT_MARKER_ICON: Final[str] = "park"
"""category maki 매핑이 없을 때의 fallback Maki icon."""


def _maki_for(category: str) -> str:
    """category → Maki icon. 미매핑이면 fallback(``park``)."""
    return mapbox_maki_icon_or_none(category) or _DEFAULT_MARKER_ICON


# -- 입력 Protocol --------------------------------------------------------


@runtime_checkable
class RecreationForestItem(Protocol):
    """전국자연휴양림표준데이터 1 row 입력 shape (``StandardRecreationForest``).

    ``python-krforest-api``의 ``travel.standard_recreation_forests()`` 결과 model이
    본 Protocol을 만족한다(필드명 동일). 좌표는 WGS84 ``float``.
    """

    name: str | None
    """휴양림명 (``Feature.name``)."""

    sido_name: str | None
    """시도명 (자연키 파생 보조)."""

    forest_type: str | None
    """휴양림 구분(국립/공립/사립 등) — ``facility_info``에 보존."""

    address: str | None
    """소재지 주소 (``Feature.address.road``)."""

    phone_number: str | None
    """전화번호 (``PlaceDetail.phones``)."""

    homepage_url: str | None
    """홈페이지 (``PlaceDetail.facility_info``)."""

    latitude: float | None
    """위도 (WGS84)."""

    longitude: float | None
    """경도 (WGS84)."""

    institution_code: str | None
    """제공기관코드 — 안정 식별자(``source_entity_id``). 없으면 name::sido 파생."""

    raw: Any
    """provider 원천 dict (``SourceRecord.raw_data``의 ``provider_raw``로 보존)."""


@runtime_checkable
class ForestSpatialItem(Protocol):
    """수목원/식물원 등 산림 공간 point 1건 입력 shape (``ForestSpatialPoint``).

    ``python-krforest-api``의 ``travel.recreation_forest_arboretums()``(SHP) 결과
    model이 본 Protocol을 만족한다.
    """

    name: str | None
    """명칭 (``Feature.name``)."""

    category: str | None
    """provider 분류(``facility_info``에 보존)."""

    address: str | None
    """주소 (``Feature.address.road``)."""

    phone_number: str | None
    homepage_url: str | None
    latitude: float | None
    longitude: float | None

    region_code: str | None
    """행정구역 코드(자연키 파생 보조)."""

    region_name: str | None
    """행정구역명(자연키 파생 보조)."""

    raw: Any


# -- 헬퍼 -----------------------------------------------------------------


def _coord_of(lat: float | None, lon: float | None) -> Coordinate | None:
    """WGS84 ``float`` 좌표 → ``Coordinate``(Decimal). 한 쪽이라도 None이면 None."""
    if lat is None or lon is None:
        return None
    return Coordinate(lon=Decimal(str(lon)), lat=Decimal(str(lat)))


def _derived_key(name: str | None, *parts: str | None) -> str:
    """안정 식별자가 없을 때 name + 보조 part로 자연키 파생(ADR-009 ``::``).

    ``|``는 ADR-009 예약 문자이므로 ``::``를 separator로 쓴다(krex와 동일).
    """
    chunks = [normalize_korean_text(name) or (name or "")]
    chunks.extend((part or "") for part in parts)
    return "::".join(chunks)


async def _resolve_address(
    *,
    coord: Coordinate | None,
    road_text: str | None,
    reverse_geocoder: ReverseGeocoder | None,
    address_resolver: AddressResolver | None,
) -> Address:
    """좌표 reverse + 주소 geocode로 행정코드를 보강한 ``Address``를 만든다."""
    geo: Address | None = None
    if coord is not None and reverse_geocoder is not None:
        geo = await reverse_geocoder(coord)
    if (geo is None or geo.bjd_code is None) and address_resolver is not None:
        resolved = await address_resolver(Address(road=road_text))
        if resolved is not None and resolved.bjd_code is not None:
            geo = resolved
    bjd_code = geo.bjd_code if geo is not None else None
    sigungu_code = (
        (geo.sigungu_code if geo is not None else None)
        or extract_sigungu_code(bjd_code)
    )
    sido_code = (
        (geo.sido_code if geo is not None else None) or extract_sido_code(bjd_code)
    )
    return Address(
        road=road_text,
        admin=geo.admin if geo is not None else None,
        bjd_code=bjd_code,
        admin_dong_code=geo.admin_dong_code if geo is not None else None,
        sigungu_code=sigungu_code,
        sido_code=sido_code,
        road_name_code=geo.road_name_code if geo is not None else None,
        zipcode=geo.zipcode if geo is not None else None,
        sido_name=geo.sido_name if geo is not None else None,
        sigungu_name=geo.sigungu_name if geo is not None else None,
    )


def _build_place_bundle(
    *,
    name: str,
    natural_key: str,
    dataset_key: str,
    source_entity_type: str,
    category: str,
    place_kind: str,
    coord: Coordinate | None,
    address: Address,
    phone: str | None,
    facility_info: dict[str, Any],
    raw_data: dict[str, Any],
    raw_address: str | None,
    fetched_at: datetime,
) -> FeatureBundle:
    """공통 place ``FeatureBundle`` 조립(휴양림/수목원 공용)."""
    payload_hash = make_payload_hash(raw_data)
    source_record_key = make_source_record_key(
        provider=KRFOREST_PROVIDER_NAME,
        dataset_key=dataset_key,
        source_entity_type=source_entity_type,
        source_entity_id=natural_key,
        raw_payload_hash=payload_hash,
    )
    feature_id = make_feature_id(
        bjd_code=address.bjd_code,
        kind=FeatureKind.PLACE.value,
        category=category,
        source_type=f"{KRFOREST_PROVIDER_NAME}:{dataset_key}",
        source_natural_key=natural_key,
    )
    normalized_name = normalize_korean_text(name) or name
    phones = [normalize_phone_number(phone)] if normalize_phone_number(phone) else []
    feature = Feature(
        feature_id=feature_id,
        kind=FeatureKind.PLACE,
        name=normalized_name,
        coord=coord,
        address=address,
        category=category,
        marker_icon=_maki_for(category),
        marker_color=KRFOREST_MARKER_COLOR,
        detail=PlaceDetail(
            feature_id=feature_id,
            place_kind=place_kind,
            phones=phones,
            facility_info={k: v for k, v in facility_info.items() if v is not None},
        ),
    )
    source_record = SourceRecord(
        provider=normalize_provider_name(KRFOREST_PROVIDER_NAME),
        dataset_key=dataset_key,
        source_entity_type=source_entity_type,
        source_entity_id=natural_key,
        raw_payload_hash=payload_hash,
        source_version=None,
        raw_name=name,
        raw_address=raw_address,
        raw_longitude=coord.lon if coord is not None else None,
        raw_latitude=coord.lat if coord is not None else None,
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
        feature=feature,
        source_record=source_record,
        source_link=source_link,
    )


# -- 단일 변환 ------------------------------------------------------------


async def _recreation_forest_to_bundle(
    item: RecreationForestItem,
    *,
    fetched_at: datetime,
    reverse_geocoder: ReverseGeocoder | None,
    address_resolver: AddressResolver | None,
) -> FeatureBundle:
    name = item.name or ""
    coord = _coord_of(item.latitude, item.longitude)
    road_text = normalize_korean_text(item.address)
    address = await _resolve_address(
        coord=coord,
        road_text=road_text,
        reverse_geocoder=reverse_geocoder,
        address_resolver=address_resolver,
    )
    natural_key = item.institution_code or _derived_key(name, item.sido_name)
    raw_data: dict[str, Any] = {
        "name": item.name,
        "sido_name": item.sido_name,
        "forest_type": item.forest_type,
        "address": item.address,
        "phone_number": item.phone_number,
        "homepage_url": item.homepage_url,
        "latitude": str(item.latitude) if item.latitude is not None else None,
        "longitude": str(item.longitude) if item.longitude is not None else None,
        "institution_code": item.institution_code,
    }
    facility_info: dict[str, Any] = {
        "forest_type": normalize_korean_text(item.forest_type),
        "homepage_url": item.homepage_url,
    }
    return _build_place_bundle(
        name=name,
        natural_key=natural_key,
        dataset_key=DATASET_KEY_RECREATION_FORESTS,
        source_entity_type=_RECREATION_FOREST_ENTITY_TYPE,
        category=RECREATION_FOREST_CATEGORY,
        place_kind=RECREATION_FOREST_PLACE_KIND,
        coord=coord,
        address=address,
        phone=item.phone_number,
        facility_info=facility_info,
        raw_data=raw_data,
        raw_address=item.address,
        fetched_at=fetched_at,
    )


async def _arboretum_to_bundle(
    item: ForestSpatialItem,
    *,
    fetched_at: datetime,
    reverse_geocoder: ReverseGeocoder | None,
    address_resolver: AddressResolver | None,
) -> FeatureBundle:
    name = item.name or ""
    coord = _coord_of(item.latitude, item.longitude)
    road_text = normalize_korean_text(item.address)
    address = await _resolve_address(
        coord=coord,
        road_text=road_text,
        reverse_geocoder=reverse_geocoder,
        address_resolver=address_resolver,
    )
    natural_key = _derived_key(name, item.region_code or item.region_name)
    raw_data: dict[str, Any] = {
        "name": item.name,
        "category": item.category,
        "address": item.address,
        "phone_number": item.phone_number,
        "homepage_url": item.homepage_url,
        "latitude": str(item.latitude) if item.latitude is not None else None,
        "longitude": str(item.longitude) if item.longitude is not None else None,
        "region_code": item.region_code,
        "region_name": item.region_name,
    }
    facility_info: dict[str, Any] = {
        "provider_category": normalize_korean_text(item.category),
        "homepage_url": item.homepage_url,
        "region_name": normalize_korean_text(item.region_name),
    }
    return _build_place_bundle(
        name=name,
        natural_key=natural_key,
        dataset_key=DATASET_KEY_ARBORETUMS,
        source_entity_type=_ARBORETUM_ENTITY_TYPE,
        category=ARBORETUM_CATEGORY,
        place_kind=ARBORETUM_PLACE_KIND,
        coord=coord,
        address=address,
        phone=item.phone_number,
        facility_info=facility_info,
        raw_data=raw_data,
        raw_address=item.address,
        fetched_at=fetched_at,
    )


# -- 공개 API -----------------------------------------------------------


async def recreation_forests_to_bundles(
    items: Iterable[RecreationForestItem],
    *,
    fetched_at: datetime,
    reverse_geocoder: ReverseGeocoder | None = None,
    address_resolver: AddressResolver | None = None,
) -> list[FeatureBundle]:
    """전국자연휴양림표준데이터 items → ``list[FeatureBundle]`` (place, ADR-034 8단계).

    각 bundle은 휴양림 place Feature(category 03030000) + SourceRecord + PRIMARY
    SourceLink. ``feature_id``/``source_record_key``는 결정적(ADR-009). 안정키
    ``institution_code``가 없으면 ``name::sido`` 파생키를 쓴다.
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
        await _recreation_forest_to_bundle(
            item,
            fetched_at=fetched_at,
            reverse_geocoder=geocoder,
            address_resolver=resolver,
        )
        for item in items
    ]


async def arboretums_to_bundles(
    items: Iterable[ForestSpatialItem],
    *,
    fetched_at: datetime,
    reverse_geocoder: ReverseGeocoder | None = None,
    address_resolver: AddressResolver | None = None,
) -> list[FeatureBundle]:
    """수목원/식물원 산림 point items → ``list[FeatureBundle]`` (place, category 01030000).

    provider SHP dataset(``recreation_forest_arboretums``)의 point record를 place
    Feature로 정규화한다. 안정 식별자가 없어 ``name::region`` 파생키를 쓴다.
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
        await _arboretum_to_bundle(
            item,
            fetched_at=fetched_at,
            reverse_geocoder=geocoder,
            address_resolver=resolver,
        )
        for item in items
    ]
