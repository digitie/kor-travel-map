"""``kortravelmap.providers.krforest`` — 산림청 휴양림/수목원 → FeatureBundle.

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

import math
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Final, Protocol, runtime_checkable

from shapely.geometry import shape as shape_geometry

from kortravelmap.category import (
    PlaceCategoryCode,
    mapbox_maki_icon_or_none,
)
from kortravelmap.core.address import (
    extract_sido_code,
    extract_sigungu_code,
    normalize_korean_text,
    normalize_phone_number,
)
from kortravelmap.core.geometry import (
    ROUTE_GEOMETRY_TYPES,
    GeometryError,
    normalize_geometry,
)
from kortravelmap.core.ids import (
    make_feature_id,
    make_payload_hash,
    make_source_record_key,
)
from kortravelmap.core.providers import normalize_provider_name
from kortravelmap.core.route_course import (
    CourseSegmentGeometry,
    assemble_course,
    connected_segment_groups,
)
from kortravelmap.dto import (
    Address,
    AdminClaimKind,
    AdminEvidence,
    Coordinate,
    Feature,
    FeatureBundle,
    FeatureKind,
    PlaceDetail,
    RouteDetail,
    SourceLink,
    SourceRecord,
    SourceRole,
)
from kortravelmap.dto.route import ROUTE_TYPE_HIKING_TRAIL, ROUTE_TYPE_TREKKING
from kortravelmap.geocoding import (
    AddressResolver,
    ReverseGeocoder,
    cached_address_resolver,
    cached_reverse_geocoder,
)
from kortravelmap.providers._route_course import (
    CourseAggregate,
    build_course_bundle,
    sorted_unique_texts,
)

__all__ = [
    "ForestSpatialItem",
    "ForestTrailItem",
    "RecreationForestItem",
    "arboretums_to_bundles",
    "dulle_trails_to_bundles",
    "forest_trails_to_bundles",
    "mountain_trail_courses_to_bundles",
    "mountain_trails_to_bundles",
    "recreation_forests_to_bundles",
    # 상수
    "ARBORETUM_CATEGORY",
    "DATASET_KEY_ARBORETUMS",
    "DATASET_KEY_DULLE_TRAILS",
    "DATASET_KEY_MOUNTAIN_TRAILS",
    "MOUNTAIN_TRAIL_COURSE_ENTITY_TYPE",
    "MOUNTAIN_TRAIL_SEGMENT_ENTITY_TYPE",
    "DATASET_KEY_RECREATION_FORESTS",
    "FOREST_ROUTE_CATEGORY",
    "FOREST_ROUTE_MARKER_COLOR",
    "KRFOREST_MARKER_COLOR",
    "KRFOREST_PROVIDER_NAME",
    "RECREATION_FOREST_CATEGORY",
]


# -- 상수 -----------------------------------------------------------------

KRFOREST_PROVIDER_NAME: Final[str] = "python-krforest-api"
"""canonical provider name (ADR-024 ``CANONICAL_PROVIDER_NAMES``)."""

DATASET_KEY_RECREATION_FORESTS: Final[str] = "krforest_recreation_forests"
DATASET_KEY_ARBORETUMS: Final[str] = "krforest_arboretums"
DATASET_KEY_MOUNTAIN_TRAILS: Final[str] = "krforest_mountain_trails"
DATASET_KEY_DULLE_TRAILS: Final[str] = "krforest_dulle_trails"

_RECREATION_FOREST_ENTITY_TYPE: Final[str] = "recreation_forest"
_ARBORETUM_ENTITY_TYPE: Final[str] = "arboretum"
MOUNTAIN_TRAIL_SEGMENT_ENTITY_TYPE: Final[str] = "mountain_trail_segment"
MOUNTAIN_TRAIL_COURSE_ENTITY_TYPE: Final[str] = "mountain_trail_course"
"""구간을 이어 만든 등산 코스의 source entity type (ADR-128)."""
_MOUNTAIN_TRAIL_ENTITY_TYPE: Final[str] = MOUNTAIN_TRAIL_SEGMENT_ENTITY_TYPE
_DULLE_TRAIL_ENTITY_TYPE: Final[str] = "dulle_trail_segment"

RECREATION_FOREST_CATEGORY: Final[str] = PlaceCategoryCode.LODGING_RECREATION_FOREST.value
"""``Feature.category`` — 휴양림 03030000."""

ARBORETUM_CATEGORY: Final[str] = PlaceCategoryCode.TOURISM_BOTANICAL.value
"""``Feature.category`` — 수목원·식물원 01030000."""

FOREST_ROUTE_CATEGORY: Final[str] = PlaceCategoryCode.TOURISM_ACTIVITY_TREKKING.value
"""등산로·둘레길 route의 보조 category 01080500."""

RECREATION_FOREST_PLACE_KIND: Final[str] = "recreation_forest"
ARBORETUM_PLACE_KIND: Final[str] = "arboretum"

KRFOREST_MARKER_COLOR: Final[str] = "P-05"
"""산림 계열 marker color (녹색 계열 팔레트, ADR-029 P-01~P-16 범위)."""

FOREST_ROUTE_MARKER_COLOR: Final[str] = "P-06"
"""등산로·둘레길 route marker color."""

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


@runtime_checkable
class ForestTrailItem(Protocol):
    """산림청 SHP/GeoJSON/GPX route 1건 입력 shape.

    `python-krforest-api`의 `ForestSpatialFeature`가 이 Protocol을 만족한다.
    공간 파일 파싱·좌표계 변환은 provider 책임이며, map은 WGS84 GeoJSON과
    source natural key를 그대로 받아 `FeatureBundle`로 정규화한다.
    """

    name: str | None
    source_file: str | None
    layer_name: str | None
    geometry_type: str | None
    geometry: Mapping[str, Any] | None
    bbox: tuple[float, float, float, float] | None
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


_CLAIM_KIND_BY_LENGTH: Final[dict[int, AdminClaimKind]] = {
    10: "bjd",
    8: "emd",
    5: "sigungu",
    2: "sido",
}


def _claim_from_region_code(value: str | None) -> tuple[str, AdminClaimKind] | None:
    """provider payload의 ``region_code``를 ``AdminEvidence`` claim 축으로 바꾼다.

    원천 `python-krforest-api`는 ``_REGION_CODE_KEYS``(``region_code``/``EMD_CD``/
    ``EMNDN_CD``/``STD_SGGCD``/``법정동코드``)를 **우선순위만으로** 읽고 길이·숫자 검증을
    전혀 하지 않는다(`parser.py`의 ``str(value).strip()``). 즉 DBF가 수치 필드면
    ``"4173025000.0"`` 같은 값도 올 수 있고, 자릿수 체계도 데이터셋마다 다를 수 있다.

    `AdminEvidence`의 필드 validator는 그런 값에 **ValueError를 던지므로**, 여기서
    거르지 않으면 asset 전체가 죽는다. 지원 길이(10/8/5/2)와 숫자만 통과시키고 나머지는
    조용히 ``None``으로 떨어뜨린다 — 무장은 관측을 늘리는 일이지 적재를 막는 일이 아니다.

    실측(2026-08-03 prod): arboretum 205건 전량이 8자리 숫자 = ``emd``다.
    """
    if value is None:
        return None
    text = value.strip()
    if not text.isdigit():
        return None
    kind = _CLAIM_KIND_BY_LENGTH.get(len(text))
    if kind is None:
        return None
    return text, kind


async def _resolve_address(
    *,
    coord: Coordinate | None,
    road_text: str | None,
    reverse_geocoder: ReverseGeocoder | None,
    address_resolver: AddressResolver | None,
) -> tuple[Address, Address | None, bool]:
    """좌표 reverse + 주소 geocode로 행정코드를 보강한 ``Address``를 만든다.

    반환: ``(address, reverse_geo, reverse_attempted)``.

    ``reverse_geo``를 **따로** 돌려주는 이유는 `AdminEvidence`의 obs 축이 오직 좌표
    reverse 결과여야 하기 때문이다. 아래 ``geo``는 `address_resolver`(provider 주소
    문자열의 정지오코딩)로도 채워지므로, 그대로 obs로 쓰면 claim_text와 출처가 같아져
    **자기 자신과 비교**하게 된다(`mois.py`가 같은 이유로 분리한다).
    """
    geo: Address | None = None
    reverse_geo: Address | None = None
    reverse_attempted = False
    if coord is not None and reverse_geocoder is not None:
        reverse_attempted = True
        geo = await reverse_geocoder(coord)
        reverse_geo = geo
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
    address = Address(
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
    return address, reverse_geo, reverse_attempted


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
    admin_evidence: AdminEvidence | None = None,
) -> FeatureBundle:
    """공통 place ``FeatureBundle`` 조립(휴양림/수목원 공용).

    ``admin_evidence``는 수목원(arboretums)에서만 채워진다 — 휴양림 payload에는 행정코드
    필드 자체가 없다(원천 ``StandardRecreationForest``의 유일한 코드는 제공기관코드다).
    """
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
        provider_natural_key=natural_key,
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
    return FeatureBundle(
        feature=feature,
        source_record=source_record,
        source_link=source_link,
        admin_evidence=admin_evidence,
    )


# -- route 변환 -----------------------------------------------------------

_FOREST_ROUTE_SPECS: Final[dict[str, tuple[str, str]]] = {
    DATASET_KEY_MOUNTAIN_TRAILS: (
        ROUTE_TYPE_HIKING_TRAIL,
        _MOUNTAIN_TRAIL_ENTITY_TYPE,
    ),
    DATASET_KEY_DULLE_TRAILS: (ROUTE_TYPE_TREKKING, _DULLE_TRAIL_ENTITY_TYPE),
}


def _forest_route_spec(dataset_key: str) -> tuple[str, str]:
    try:
        return _FOREST_ROUTE_SPECS[dataset_key]
    except KeyError as exc:
        raise KeyError(
            f"krforest route dataset_key가 아님: {dataset_key!r}. "
            f"지원: {sorted(_FOREST_ROUTE_SPECS)}"
        ) from exc


def _forest_route_source_id(
    item: ForestTrailItem,
    *,
    name: str,
    canonical_wkt: str,
) -> str:
    """provider source_id를 우선하고, 구 provider에는 deterministic fallback을 쓴다."""

    # C05A adds `source_id` to the provider model.  The fallback keeps this
    # converter safe while older pins are still used by local preview jobs.
    source_id = getattr(item, "source_id", None)
    if isinstance(source_id, str):
        normalized_source_id = normalize_korean_text(source_id)
        if normalized_source_id is not None:
            return normalized_source_id

    source_file = item.source_file or "unknown-file"
    layer_name = item.layer_name or "unknown-layer"
    geometry_hash = make_payload_hash(
        {"name": name, "source_file": source_file, "layer_name": layer_name, "wkt": canonical_wkt}
    )
    return _derived_key(name, source_file, layer_name, geometry_hash)


def _forest_route_geometry(
    item: ForestTrailItem,
) -> tuple[str, Coordinate, str] | None:
    """provider GeoJSON geometry를 canonical WKT·centroid·type으로 변환한다."""

    geometry = item.geometry
    if not isinstance(geometry, Mapping):
        return None
    try:
        source_geometry = shape_geometry(dict(geometry))
        canonical_wkt, centroid = normalize_geometry(
            source_geometry.wkt,
            allowed_types=ROUTE_GEOMETRY_TYPES,
        )
    except (AttributeError, GeometryError, KeyError, TypeError, ValueError):
        return None
    return canonical_wkt, centroid, source_geometry.geom_type


async def _forest_route_to_bundle(
    item: ForestTrailItem,
    *,
    dataset_key: str,
    route_type: str,
    source_entity_type: str,
    fetched_at: datetime,
    reverse_geocoder: ReverseGeocoder | None,
) -> FeatureBundle | None:
    name = normalize_korean_text(item.name)
    if name is None:
        return None

    geometry_result = _forest_route_geometry(item)
    if geometry_result is None:
        return None
    canonical_wkt, coord, geometry_type = geometry_result
    source_id = _forest_route_source_id(item, name=name, canonical_wkt=canonical_wkt)
    address = await reverse_geocoder(coord) if reverse_geocoder is not None else None
    spatial_payload = {
        "source_file": item.source_file,
        "layer_name": item.layer_name,
        "source_id": source_id,
        "geometry_type": geometry_type,
        "geometry_wkt": canonical_wkt,
        "bbox": list(item.bbox) if item.bbox is not None else None,
    }
    raw_data = dict(item.raw) if isinstance(item.raw, Mapping) else {}
    # provider raw에는 geometry가 별도 model field로 있으므로 payload hash에도
    # geometry snapshot을 포함해 선형 geometry 변경을 새 source record로 남긴다.
    raw_data["_kortravelmap_spatial"] = spatial_payload
    payload_hash = make_payload_hash(raw_data)
    source_record_key = make_source_record_key(
        provider=KRFOREST_PROVIDER_NAME,
        dataset_key=dataset_key,
        source_entity_type=source_entity_type,
        source_entity_id=source_id,
        raw_payload_hash=payload_hash,
    )
    feature_id = make_feature_id(
        # route identity is provider source-native.  Reverse-geocoder output may
        # change when the route centroid or geocoder version changes, so it must
        # remain display metadata rather than split the same source entity.
        bjd_code=None,
        kind=FeatureKind.ROUTE.value,
        category=FOREST_ROUTE_CATEGORY,
        source_type=f"{KRFOREST_PROVIDER_NAME}:{dataset_key}",
        source_natural_key=source_id,
    )
    # 산림청 등산로 DBF의 거리·상하행 시간·난이도(``PMNTN_*``)는 원천에 있는데도 예전
    # 변환이 버렸다(ADR-128). 구간 route에도 같은 정규 열로 싣는다.
    fields = (
        _mountain_trail_source_fields(raw_data)
        if dataset_key == DATASET_KEY_MOUNTAIN_TRAILS
        else None
    )
    feature = Feature(
        feature_id=feature_id,
        provider_natural_key=source_id,
        kind=FeatureKind.ROUTE,
        name=name,
        coord=coord,
        address=address or Address(),
        geom=canonical_wkt,
        category=FOREST_ROUTE_CATEGORY,
        marker_icon=_maki_for(FOREST_ROUTE_CATEGORY),
        marker_color=FOREST_ROUTE_MARKER_COLOR,
        detail=RouteDetail(
            feature_id=feature_id,
            route_type=route_type,
            geometry_source="krforest",
            geometry_status="provided",
            total_distance_meters=(
                Decimal(str(round(fields.distance_m, 1)))
                if fields is not None and fields.distance_m
                else None
            ),
            expected_duration_minutes=(
                fields.ascent_minutes
                if fields is not None and fields.ascent_minutes
                else None
            ),
            difficulty=fields.difficulty if fields is not None else None,
            payload={
                "dataset_key": dataset_key,
                "source_file": item.source_file,
                "layer_name": item.layer_name,
                "source_id": source_id,
                "geometry_type": geometry_type,
                "availability_status_source": "not_available",
                **(
                    {"descent_minutes": fields.descent_minutes}
                    if fields is not None and fields.descent_minutes is not None
                    else {}
                ),
                **(
                    {"duration_basis": "source"}
                    if fields is not None and fields.ascent_minutes
                    else {}
                ),
            },
        ),
    )
    source_record = SourceRecord(
        provider=normalize_provider_name(KRFOREST_PROVIDER_NAME),
        dataset_key=dataset_key,
        source_entity_type=source_entity_type,
        source_entity_id=source_id,
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
    return FeatureBundle(
        feature=feature,
        source_record=source_record,
        source_link=source_link,
    )


async def forest_trails_to_bundles(
    items: Iterable[ForestTrailItem],
    *,
    dataset_key: str,
    fetched_at: datetime,
    reverse_geocoder: ReverseGeocoder | None = None,
) -> list[FeatureBundle]:
    """산림청 route 공간 피처를 `FeatureBundle`로 정규화한다.

    LineString/MultiLineString만 route로 승격하며 이름 없음·빈/불량 geometry·중복
    source natural key는 결과에서 제외한다. forest.go.kr 파일은 폐쇄·통행 가능
    상태의 실시간 source가 아니므로 운영 상태를 추정하지 않는다.
    """

    route_type, source_entity_type = _forest_route_spec(dataset_key)
    geocoder = (
        cached_reverse_geocoder(reverse_geocoder)
        if reverse_geocoder is not None
        else None
    )
    bundles: list[FeatureBundle] = []
    seen_source_ids: set[str] = set()
    for item in items:
        bundle = await _forest_route_to_bundle(
            item,
            dataset_key=dataset_key,
            route_type=route_type,
            source_entity_type=source_entity_type,
            fetched_at=fetched_at,
            reverse_geocoder=geocoder,
        )
        if bundle is None:
            continue
        source_id = bundle.source_record.source_entity_id
        if source_id in seen_source_ids:
            continue
        seen_source_ids.add(source_id)
        bundles.append(bundle)
    return bundles


async def mountain_trails_to_bundles(
    items: Iterable[ForestTrailItem],
    *,
    fetched_at: datetime,
    reverse_geocoder: ReverseGeocoder | None = None,
) -> list[FeatureBundle]:
    """산림청 등산로(`PBD0000041`) route를 변환한다."""

    return await forest_trails_to_bundles(
        items,
        dataset_key=DATASET_KEY_MOUNTAIN_TRAILS,
        fetched_at=fetched_at,
        reverse_geocoder=reverse_geocoder,
    )


async def dulle_trails_to_bundles(
    items: Iterable[ForestTrailItem],
    *,
    fetched_at: datetime,
    reverse_geocoder: ReverseGeocoder | None = None,
) -> list[FeatureBundle]:
    """산림청 둘레길(`PBD0000031`) route를 변환한다."""

    return await forest_trails_to_bundles(
        items,
        dataset_key=DATASET_KEY_DULLE_TRAILS,
        fetched_at=fetched_at,
        reverse_geocoder=reverse_geocoder,
    )


# -- 등산 코스 (ADR-128) -------------------------------------------------

_FOREST_DIFFICULTY: Final[dict[str, str]] = {
    "쉬움": "easy",
    "중간": "moderate",
    "어려움": "hard",
}
"""산림청 ``PMNTN_DFFL`` → ``RouteDetail.difficulty``. 원천 실측 값은 이 셋뿐이다
(2026-11 prod 57,047구간: 쉬움 56,107 / 중간 844 / 어려움 21 / 빈 값 75)."""

_DIFFICULTY_RANK: Final[dict[str, int]] = {"easy": 0, "moderate": 1, "hard": 2}


def _raw_number(raw: Mapping[str, Any], key: str) -> float | None:
    """DBF 수치 필드를 float로 읽는다. 문자열("57020.0")·빈 값·음수는 걸러낸다."""
    value = raw.get(key)
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(str(value).strip())
    except ValueError:
        return None
    if not math.isfinite(number) or number < 0:
        return None
    return number


def _raw_minutes(raw: Mapping[str, Any], key: str) -> int | None:
    number = _raw_number(raw, key)
    return None if number is None else round(number)


def _raw_label(raw: Mapping[str, Any], key: str) -> str | None:
    value = raw.get(key)
    return None if value is None else normalize_korean_text(str(value))


@dataclass(frozen=True, slots=True)
class _MountainTrailSourceFields:
    """산림청 등산로 DBF 한 행에서 읽은 원천 속성(``PMNTN_*``)."""

    distance_m: float | None
    """``PMNTN_LT``(km) × 1000. geometry 길이와 중앙 비율 1.000으로 일치한다(실측)."""
    ascent_minutes: int | None
    """``PMNTN_UPPL`` — 상행 소요시간(분). 중앙 17.8분/km."""
    descent_minutes: int | None
    """``PMNTN_GODN`` — 하행 소요시간(분)."""
    difficulty: str | None


def _mountain_trail_source_fields(raw: Mapping[str, Any]) -> _MountainTrailSourceFields:
    length_km = _raw_number(raw, "PMNTN_LT")
    label = _raw_label(raw, "PMNTN_DFFL")
    return _MountainTrailSourceFields(
        distance_m=None if length_km is None else length_km * 1000.0,
        ascent_minutes=_raw_minutes(raw, "PMNTN_UPPL"),
        descent_minutes=_raw_minutes(raw, "PMNTN_GODN"),
        difficulty=_FOREST_DIFFICULTY.get(label) if label is not None else None,
    )


@dataclass(frozen=True, slots=True)
class _MountainTrailSegment:
    source_id: str
    serial: int
    mountain_code: str
    mountain_name: str
    segment_name: str | None
    wkt: str
    bbox_center: tuple[float, float]
    fields: _MountainTrailSourceFields
    raw: dict[str, Any]


def _mountain_trail_segments(items: Iterable[ForestTrailItem]) -> list[_MountainTrailSegment]:
    """산림청 등산로 item을 코스 조립 입력으로 푼다. 산 코드·geometry 없는 행은 버린다."""
    segments: list[_MountainTrailSegment] = []
    seen: set[str] = set()
    for item in items:
        raw = dict(item.raw) if isinstance(item.raw, Mapping) else {}
        mountain_code = _raw_label(raw, "MNTN_CODE")
        mountain_name = _raw_label(raw, "MNTN_NM")
        name = normalize_korean_text(item.name)
        if mountain_code is None or (mountain_name is None and name is None):
            continue
        geometry_result = _forest_route_geometry(item)
        if geometry_result is None:
            continue
        canonical_wkt, _centroid, _geometry_type = geometry_result
        source_id = _forest_route_source_id(
            item, name=name or mountain_name or mountain_code, canonical_wkt=canonical_wkt
        )
        if source_id in seen:
            continue
        seen.add(source_id)
        serial_value = _raw_number(raw, "PMNTN_SN")
        min_x, min_y, max_x, max_y = shape_geometry(dict(item.geometry or {})).bounds
        segments.append(
            _MountainTrailSegment(
                source_id=source_id,
                serial=int(serial_value) if serial_value is not None else 0,
                mountain_code=mountain_code,
                mountain_name=mountain_name or name or mountain_code,
                segment_name=_raw_label(raw, "PMNTN_NM"),
                wkt=canonical_wkt,
                bbox_center=((min_x + max_x) / 2, (min_y + max_y) / 2),
                fields=_mountain_trail_source_fields(raw),
                raw={"source_id": source_id, **raw},
            )
        )
    return segments


def _hardest(difficulties: Sequence[str | None]) -> str | None:
    known = [value for value in difficulties if value is not None]
    if not known:
        return None
    return max(known, key=lambda value: _DIFFICULTY_RANK[value])


def _group_by_mountain(
    segments: Sequence[_MountainTrailSegment],
) -> dict[str, list[_MountainTrailSegment]]:
    grouped: dict[str, list[_MountainTrailSegment]] = defaultdict(list)
    for segment in segments:
        grouped[segment.mountain_code].append(segment)
    return grouped


def _most_common_name(names: Sequence[str]) -> str:
    """산 코드 하나의 표기가 갈릴 때 최빈 표기(같으면 사전순 앞) — 행 순서와 무관하다."""
    counts: dict[str, int] = {}
    for name in names:
        counts[name] = counts.get(name, 0) + 1
    return min(counts, key=lambda name: (-counts[name], name))


def _mountain_course_aggregate(
    *,
    natural_key: str,
    name: str,
    mountain_name: str,
    members: Sequence[_MountainTrailSegment],
    excluded: frozenset[str],
    start_rule: str,
) -> CourseAggregate:
    included = [segment for segment in members if segment.source_id not in excluded]
    distances = [segment.fields.distance_m for segment in included]
    ascents = [segment.fields.ascent_minutes for segment in included]
    descents = [segment.fields.descent_minutes for segment in included]
    breakdown: dict[str, float] = {"easy": 0.0, "moderate": 0.0, "hard": 0.0, "unknown": 0.0}
    for segment in included:
        breakdown[segment.fields.difficulty or "unknown"] += segment.fields.distance_m or 0.0
    known_distances = [value for value in distances if value is not None]
    first = members[0]
    return CourseAggregate(
        natural_key=natural_key,
        name=name,
        segment_source_ids=tuple(segment.source_id for segment in members),
        segment_raws=tuple(segment.raw for segment in members),
        source_distance_m=sum(known_distances) if known_distances else None,
        # 상행 시간이 코스 소요시간이다 — 원천은 구간마다 오르막 방향 시간을 적는다.
        # 하나라도 비면 합이 틀리므로 거리 기반 추정으로 내려간다.
        source_duration_minutes=(
            sum(value for value in ascents if value is not None)
            if included and all(value is not None for value in ascents)
            else None
        ),
        difficulty=_hardest([segment.fields.difficulty for segment in included]),
        payload={
            "mountain_code": first.mountain_code,
            "mountain_name": mountain_name,
            "segment_name": first.segment_name,
            "start_rule": start_rule,
            "duration_method": "sum_of_ascent_minutes",
            "descent_minutes": (
                sum(value for value in descents if value is not None)
                if included and all(value is not None for value in descents)
                else None
            ),
            "difficulty_basis": "hardest_segment",
            "difficulty_breakdown_m": {key: round(value, 1) for key, value in breakdown.items()},
            "surfaces": sorted_unique_texts(
                [_raw_label(segment.raw, "PMNTN_MTRQ") for segment in included]
            ),
            "risks": sorted_unique_texts(
                [_raw_label(segment.raw, "PMNTN_RISK") for segment in included]
            ),
            "main_points": sorted_unique_texts(
                [_raw_label(segment.raw, "PMNTN_MAIN") for segment in included]
            ),
            "data_reference_date": max(
                (value for segment in members if (value := _raw_label(segment.raw, "DATA_STDR_"))),
                default=None,
            ),
        },
    )


async def mountain_trail_courses_to_bundles(
    items: Iterable[ForestTrailItem],
    *,
    fetched_at: datetime,
    reverse_geocoder: ReverseGeocoder | None = None,
) -> list[FeatureBundle]:
    """산림청 등산로(``PBD0000041``) 구간을 등산 코스 route로 묶는다(ADR-128).

    코스 = 같은 산(``MNTN_CODE``)·같은 노선명(``PMNTN_NM``, 없으면 이름 없는 묶음)의 구간 중
    약 10 m 안에서 서로 닿는 연결 성분. 출발점은 산 전체 구간망의 중심(정상부 대용점)에서
    가장 먼 말단이다(들머리 추정 — 원천에 시종점·고도가 없다). 거리·상행시간·난이도는
    원천 ``PMNTN_LT``/``PMNTN_UPPL``/``PMNTN_DFFL``을 합산·집계한다.
    """
    geocoder = (
        cached_reverse_geocoder(reverse_geocoder) if reverse_geocoder is not None else None
    )
    segments = _mountain_trail_segments(items)
    groups: dict[tuple[str, str | None], list[_MountainTrailSegment]] = defaultdict(list)
    mountain_points: dict[str, list[tuple[float, float]]] = defaultdict(list)
    # 입력 행 순서와 무관하게 같은 결과가 나오도록 원천 순번 순으로 다룬다.
    for segment in sorted(segments, key=lambda item: (item.serial, item.source_id)):
        groups[(segment.mountain_code, segment.segment_name)].append(segment)
        mountain_points[segment.mountain_code].append(segment.bbox_center)
    mountain_names = {
        code: _most_common_name([segment.mountain_name for segment in members])
        for code, members in _group_by_mountain(segments).items()
    }
    bundles: list[FeatureBundle] = []
    seen_keys: set[str] = set()
    for group_key in sorted(groups, key=lambda key: (key[0], key[1] or "")):
        mountain_code, segment_name = group_key
        members = groups[group_key]
        points = mountain_points[mountain_code]
        centroid = (
            math.fsum(point[0] for point in points) / len(points),
            math.fsum(point[1] for point in points) / len(points),
        )
        by_id = {segment.source_id: segment for segment in members}
        components = connected_segment_groups(
            [
                CourseSegmentGeometry(
                    segment_id=segment.source_id,
                    order_key=(segment.serial, segment.source_id),
                    wkt=segment.wkt,
                    source_length_m=segment.fields.distance_m,
                )
                for segment in members
            ]
        )
        mountain_name = mountain_names[mountain_code]
        base_name = (
            f"{mountain_name} {segment_name}"
            if segment_name is not None and segment_name != mountain_name
            else f"{mountain_name} 등산로"
        )
        for ordinal, component in enumerate(components, start=1):
            course = assemble_course(component, start_far_from=centroid)
            if course is None:
                continue
            component_members = [by_id[geometry.segment_id] for geometry in component]
            natural_key = (
                f"course::{mountain_code}::{segment_name or '-'}::{component_members[0].serial}"
            )
            if natural_key in seen_keys:
                natural_key = f"{natural_key}::{component_members[0].source_id}"
            seen_keys.add(natural_key)
            aggregate = _mountain_course_aggregate(
                natural_key=natural_key,
                name=base_name if len(components) == 1 else f"{base_name} {ordinal}",
                mountain_name=mountain_name,
                members=component_members,
                excluded=frozenset(course.excluded_segment_ids),
                start_rule="far_from_mountain_network_centroid",
            )
            bundles.append(
                await build_course_bundle(
                    provider=KRFOREST_PROVIDER_NAME,
                    dataset_key=DATASET_KEY_MOUNTAIN_TRAILS,
                    source_entity_type=MOUNTAIN_TRAIL_COURSE_ENTITY_TYPE,
                    category=FOREST_ROUTE_CATEGORY,
                    marker_icon=_maki_for(FOREST_ROUTE_CATEGORY),
                    marker_color=FOREST_ROUTE_MARKER_COLOR,
                    geometry_source="krforest",
                    course=course,
                    aggregate=aggregate,
                    fetched_at=fetched_at,
                    reverse_geocoder=geocoder,
                )
            )
    return bundles


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
    address, _reverse_geo, _reverse_attempted = await _resolve_address(
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
    address, reverse_geo, reverse_attempted = await _resolve_address(
        coord=coord,
        road_text=road_text,
        reverse_geocoder=reverse_geocoder,
        address_resolver=address_resolver,
    )
    # T-VN-H30C: MOIS와 달리 위 reverse는 payload 코드 유무와 무관하게 호출되므로
    # obs(좌표 reverse)와 claim(payload region_code)이 **동시에** 성립한다 → grade="dual".
    # 즉 MOIS에서 구조적으로 불가능했던 staleness 대조가 여기서는 실제로 발화한다.
    claim = _claim_from_region_code(item.region_code)
    admin_evidence = AdminEvidence(
        # obs 축은 **좌표 reverse** 결과만이다. `address`는 address_resolver(주소 문자열
        # 정지오코딩)로도 채워질 수 있어 그대로 쓰면 claim_text와 출처가 같아진다.
        obs_code=reverse_geo.bjd_code if reverse_geo is not None else None,
        reverse_attempted=reverse_attempted,
        claim_code=claim[0] if claim is not None else None,
        claim_kind=claim[1] if claim is not None else None,
        claim_text=item.address or None,
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
        admin_evidence=admin_evidence,
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
