"""``krtour.map.providers.knps`` — 국립공원공단(KNPS) file dataset → Feature 변환.

`python-knps-api`(`digitie/python-knps-api`, ADR-028 + amendment 2026-05-25)가
제공하는 14건 keyless file dataset을 본 라이브러리 ``Feature`` 계약으로 정규화한다.
ADR-006(provider wrapper 금지) — knps-api의 public client/catalog를 직접 쓰고,
본 모듈은 **순수 변환 함수**만 둔다 (ADR-002).

knps-api는 raw bytes(`client.files...`)와 `FileArtifact` preview 외에, **SHP/CSV를
파싱한 typed record(좌표·geometry WKT 포함)를 노출하는 것이 책임**이다 (ADR-044 —
데이터 정합성·파싱의 1차 책임은 provider 라이브러리). 따라서 SHP(ZIP) →
geometry, CP949/euc-kr 디코딩, EPSG:5179→4326 좌표 변환은 **knps-api 측**에서
수행하고(필요 시 upstream PR), 본 모듈은 그 결과(WKT/좌표)를 `Feature` 계약으로
정규화한다.

입력 계약: 본 모듈은 raw bytes를 직접 파싱하지 않고, **이미 행 단위로 파싱된**
record Protocol을 받는다 — Point는 ``KnpsPointRecord``(좌표+이름+raw),
route/area는 ``KnpsGeometryRecord``(geometry WKT 4326+이름+raw). provider 변환
함수는 category·DTO 조립·centroid에 집중 (테스트 용이, knps-api와 책임 분계).

ADR 참조
--------
- ADR-002 — 순수 변환 함수 (wrapper class 금지)
- ADR-006 — knps-api public 직접 사용
- ADR-009 — ``make_feature_id`` 결정적 생성
- ADR-012 — ``Coordinate``는 WGS84 (4326); coord_5179는 DB generated
- ADR-027 — forest 카테고리 확장 (mountain_shelter 등)
- ADR-028 — `python-knps-api` provider 등록 (+ amendment keyless/file-only)
- ADR-034 — provider 구현 순서 (KNPS는 7단계)
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from decimal import Decimal
from typing import Any, Final, Protocol, runtime_checkable

from krtour.map.category import get_category, is_known_category_code
from krtour.map.core.address import normalize_korean_text
from krtour.map.core.geometry import (
    AREA_GEOMETRY_TYPES,
    ROUTE_GEOMETRY_TYPES,
    GeometryError,
    normalize_geometry,
)
from krtour.map.core.ids import (
    make_feature_id,
    make_payload_hash,
    make_source_record_key,
)
from krtour.map.core.providers import normalize_provider_name
from krtour.map.dto import (
    AreaDetail,
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

__all__ = [
    "KnpsPointRecord",
    "KnpsGeometryRecord",
    "KnpsPlaceDatasetSpec",
    "KnpsGeometryDatasetSpec",
    "KNPS_PLACE_DATASETS",
    "KNPS_POINT_DATASET_KEYS",
    "KNPS_GEOMETRY_DATASETS",
    "KNPS_GEOMETRY_DATASET_KEYS",
    "knps_point_records_to_bundles",
    "knps_geometry_records_to_bundles",
    "resolve_cultural_resource_category",
    "PROVIDER_NAME",
]


PROVIDER_NAME: Final[str] = "python-knps-api"
"""canonical provider name (ADR-024/028 ``CANONICAL_PROVIDER_NAMES``)."""

# 좌표계 — knps file dataset은 EPSG:4326(WGS84) 좌표 컬럼을 제공(검증 dataset
# 기준). 다른 좌표계 dataset은 호출 측 parser가 4326으로 변환해 넘긴다.
_DEFAULT_MARKER_COLOR: Final[str] = "P-06"
"""KNPS place 기본 marker color (자연/공원 계열). dataset spec에서 override."""


@runtime_checkable
class KnpsPointRecord(Protocol):
    """파싱된 KNPS point dataset 한 행의 입력 shape.

    knps-api raw CSV를 호출자/파서가 행 단위로 푼 결과. provider 변환 함수는 본
    Protocol만 의존 — 실제 model(dataclass/dict wrapper)이 이 shape를 만족하면 된다.
    """

    @property
    def source_id(self) -> str:
        """provider 원천 식별자 (관리번호/일련번호 등). dedup/결정적 ID용."""
        ...

    @property
    def name(self) -> str:
        """시설 이름 (한글)."""
        ...

    @property
    def longitude(self) -> Decimal | float | None:
        """경도 (WGS84). ``None``이면 좌표 없는 feature."""
        ...

    @property
    def latitude(self) -> Decimal | float | None:
        """위도 (WGS84)."""
        ...

    @property
    def raw(self) -> dict[str, Any]:
        """원천 row 전체 (raw_data JSONB 보존 + subtype 분기용)."""
        ...


class KnpsPlaceDatasetSpec:
    """KNPS place(Point) dataset 1건의 변환 사양 (category/place_kind/marker).

    ``docs/knps-feature-etl.md §2.1/§4`` 검증표 그대로. cultural_resources는
    category가 row subtype에 따라 갈리므로 ``category=None`` + 동적 resolver.
    """

    __slots__ = ("dataset_key", "category", "place_kind", "marker_color", "dynamic")

    def __init__(
        self,
        dataset_key: str,
        *,
        category: str | None,
        place_kind: str,
        marker_color: str = _DEFAULT_MARKER_COLOR,
        dynamic: bool = False,
    ) -> None:
        self.dataset_key = dataset_key
        self.category = category
        self.place_kind = place_kind
        self.marker_color = marker_color
        # True면 row별로 category/place_kind를 resolver가 결정 (cultural_resources).
        self.dynamic = dynamic


# 검증된 Point/place dataset 5건 (knps.file_datasets() geometry_type='Point',
# feature_kind='place'). docs/knps-feature-etl.md §4 표 기준.
KNPS_PLACE_DATASETS: Final[dict[str, KnpsPlaceDatasetSpec]] = {
    "knps_visitor_centers": KnpsPlaceDatasetSpec(
        "knps_visitor_centers",
        category="01060101",  # TOURISM_INFORMATION_CENTER_PUBLIC
        place_kind="visitor_center",
        marker_color="P-06",
    ),
    "knps_restrooms": KnpsPlaceDatasetSpec(
        "knps_restrooms",
        category="05060000",  # CONVENIENCE_TOILET
        place_kind="restroom_national_park",
        marker_color="P-13",
    ),
    "knps_campgrounds": KnpsPlaceDatasetSpec(
        "knps_campgrounds",
        category="03060100",  # LODGING_CAMPGROUND_AUTO
        place_kind="campground",
        marker_color="P-06",
    ),
    "knps_shelters": KnpsPlaceDatasetSpec(
        "knps_shelters",
        category="03080100",  # LODGING_MOUNTAIN_SHELTER_KNPS (ADR-027)
        place_kind="mountain_shelter",
        marker_color="P-06",
    ),
    "knps_cultural_resources": KnpsPlaceDatasetSpec(
        "knps_cultural_resources",
        category=None,  # row subtype별 동적 (resolve_cultural_resource_category)
        place_kind="cultural_resource",
        marker_color="P-08",
        dynamic=True,
    ),
}

# Point feature_kind='place' dataset key 집합 (편의).
KNPS_POINT_DATASET_KEYS: Final[frozenset[str]] = frozenset(KNPS_PLACE_DATASETS)

_SOURCE_ENTITY_TYPE: Final[str] = "knps_facility"


def resolve_cultural_resource_category(raw: dict[str, Any]) -> tuple[str, str]:
    """cultural_resources row의 ``RESOURCE_TYPE``에 따라 (category, place_kind).

    ``docs/knps-feature-etl.md §2.3`` 분기표. 키 이름은 대소문자/한영 변형을 폭넓게
    탐색하고, 못 찾으면 일반 유산 코드로 fallback.
    """
    # RESOURCE_TYPE 후보 키 (knps CSV 컬럼 변형 대비).
    rtype = ""
    for key in ("RESOURCE_TYPE", "resource_type", "자원유형", "구분", "유형"):
        val = raw.get(key)
        if val:
            rtype = str(val)
            break

    if "사찰" in rtype:
        return "01070100", "temple"  # TOURISM_HERITAGE_TEMPLE
    if any(tok in rtype for tok in ("유적", "사적", "기념물")):
        return "01070300", "historic_site"  # TOURISM_HERITAGE_HISTORIC_SITE
    return "01070000", "cultural_resource"  # TOURISM_HERITAGE (기타)


def _coord(record: KnpsPointRecord) -> Coordinate | None:
    """record 좌표 → ``Coordinate`` (없거나 0/범위밖이면 ``None``)."""
    lon, lat = record.longitude, record.latitude
    if lon is None or lat is None:
        return None
    try:
        return Coordinate(lon=Decimal(str(lon)), lat=Decimal(str(lat)))
    except (ValueError, ArithmeticError):
        # 한국 경계 밖/파싱 실패 → 좌표 없는 feature로 (Coordinate validator raise).
        return None


def _maki_for(category: str) -> str:
    """category 코드의 maki icon (없으면 fallback 'marker')."""
    if is_known_category_code(category):
        return get_category(category).mapbox_maki_icon or "marker"
    return "marker"


def _point_record_to_bundle(
    record: KnpsPointRecord,
    spec: KnpsPlaceDatasetSpec,
    *,
    fetched_at: datetime,
) -> FeatureBundle:
    """KNPS point record 1건 → place ``FeatureBundle``."""
    if spec.dynamic:
        category, place_kind = resolve_cultural_resource_category(record.raw)
    else:
        assert spec.category is not None  # 비-dynamic spec은 category 필수
        category, place_kind = spec.category, spec.place_kind

    raw_data = dict(record.raw)
    payload_hash = make_payload_hash(raw_data)
    source_record_key = make_source_record_key(
        provider=PROVIDER_NAME,
        dataset_key=spec.dataset_key,
        source_entity_type=_SOURCE_ENTITY_TYPE,
        source_entity_id=record.source_id,
        raw_payload_hash=payload_hash,
    )
    feature_id = make_feature_id(
        bjd_code=None,  # KNPS file dataset에 법정동코드 없음 — reverse geocode 후속
        kind=FeatureKind.PLACE.value,
        category=category,
        source_type=f"{PROVIDER_NAME}:{spec.dataset_key}",
        source_natural_key=record.source_id,
    )

    coord = _coord(record)
    normalized_name = normalize_korean_text(record.name) or record.name

    feature = Feature(
        feature_id=feature_id,
        kind=FeatureKind.PLACE,
        name=normalized_name,
        coord=coord,
        category=category,
        marker_icon=_maki_for(category),
        marker_color=spec.marker_color,
        detail=PlaceDetail(
            feature_id=feature_id,
            place_kind=place_kind,
            payload={"knps_dataset": spec.dataset_key},
        ),
    )
    source_record = SourceRecord(
        provider=normalize_provider_name(PROVIDER_NAME),
        dataset_key=spec.dataset_key,
        source_entity_type=_SOURCE_ENTITY_TYPE,
        source_entity_id=record.source_id,
        raw_payload_hash=payload_hash,
        raw_name=record.name,
        raw_longitude=Decimal(str(record.longitude))
        if record.longitude is not None
        else None,
        raw_latitude=Decimal(str(record.latitude))
        if record.latitude is not None
        else None,
        raw_data=raw_data,
        fetched_at=fetched_at,
        source_record_key=source_record_key,
    )
    source_link = SourceLink(
        feature_id=feature_id,
        source_record_key=source_record_key,
        source_role=SourceRole.PRIMARY,  # KNPS는 해당 시설의 1차 source
        match_method="natural_key",
        confidence=100,
        is_primary_source=True,
    )
    return FeatureBundle(
        feature=feature, source_record=source_record, source_link=source_link
    )


def knps_point_records_to_bundles(
    records: Iterable[KnpsPointRecord],
    *,
    dataset_key: str,
    fetched_at: datetime,
) -> list[FeatureBundle]:
    """KNPS Point/place dataset의 파싱된 행들 → ``list[FeatureBundle]``.

    Parameters
    ----------
    records
        ``KnpsPointRecord`` Protocol을 만족하는 파싱된 행 iterable (CSV 디코딩/컬럼
        추출은 호출자/파서 책임).
    dataset_key
        ``KNPS_PLACE_DATASETS`` 키 중 하나 (visitor_centers / restrooms /
        campgrounds / shelters / cultural_resources).
    fetched_at
        provider 호출 시각 (KST aware, ADR-019). batch 단위 1회 결정.

    Returns
    -------
    list[FeatureBundle]
        입력 순서 유지. 결정적 ID (ADR-009).

    Raises
    ------
    KeyError
        ``dataset_key``가 Point/place dataset이 아님 (SHP/route/area는 후속 PR).
    """
    try:
        spec = KNPS_PLACE_DATASETS[dataset_key]
    except KeyError as exc:
        raise KeyError(
            f"KNPS Point/place dataset 아님: {dataset_key!r}. "
            f"지원: {sorted(KNPS_PLACE_DATASETS)}. SHP(area)/route는 후속 PR "
            "(docs/knps-feature-etl.md §5)."
        ) from exc

    return [
        _point_record_to_bundle(record, spec, fetched_at=fetched_at)
        for record in records
    ]


# =====================================================================
# geometry datasets (route LINESTRING / area POLYGON) — Sprint 3 후속
# =====================================================================


@runtime_checkable
class KnpsGeometryRecord(Protocol):
    """파싱된 KNPS geometry(route/area) dataset 한 행의 입력 shape.

    knps-api raw(CSV/SHP)를 호출자/파서가 행 단위로 풀고 geometry를 **WKT(4326)**
    문자열로 추출한 결과. SHP/CSV 디코딩·좌표계 변환(EPSG:5179→4326 등)은 호출자
    책임 — 본 변환 함수는 WKT 검증·centroid·DTO 조립에 집중 (테스트 용이, ADR-002).
    """

    @property
    def source_id(self) -> str:
        """provider 원천 식별자 (결정적 ID/dedup용)."""
        ...

    @property
    def name(self) -> str:
        """탐방로/구역 이름 (한글)."""
        ...

    @property
    def geom_wkt(self) -> str:
        """geometry WKT (EPSG:4326). route는 LINESTRING/MULTILINESTRING,
        area는 POLYGON/MULTIPOLYGON."""
        ...

    @property
    def raw(self) -> dict[str, Any]:
        """원천 row 전체 (raw_data JSONB 보존 + payload 분기용)."""
        ...


class KnpsGeometryDatasetSpec:
    """KNPS route/area dataset 1건의 변환 사양.

    route는 ``RouteDetail.route_type``, area는 ``AreaDetail.area_kind``로 분기.
    category는 탐방로/시설도로(route)·국립공원 경계(area)는 실제 관광 category를
    갖고(upstream ``docs/knps-feature-etl.md §4``), 위험지역/보호지역은 category가
    없어 ``category=None`` → sentinel ``00000000``. marker_icon은 spec에 명시
    (upstream §4 표: route/공원 ``park``, 위험/보호 ``barrier``).
    """

    __slots__ = (
        "dataset_key", "feature_kind", "category", "detail_kind",
        "allowed_geom_types", "marker_icon", "marker_color",
    )

    def __init__(
        self,
        dataset_key: str,
        *,
        feature_kind: FeatureKind,
        detail_kind: str,
        allowed_geom_types: frozenset[str],
        category: str | None = None,
        marker_icon: str = "marker",
        marker_color: str = _DEFAULT_MARKER_COLOR,
    ) -> None:
        self.dataset_key = dataset_key
        self.feature_kind = feature_kind
        self.category = category
        # route → route_type 값, area → area_kind 값.
        self.detail_kind = detail_kind
        self.allowed_geom_types = allowed_geom_types
        self.marker_icon = marker_icon
        self.marker_color = marker_color


# 일부 area(hazard/protected)는 관광 category 없음 → sentinel (Feature.category는
# 8자리 숫자 형식 강제, ADR-023). area_kind로만 식별. 단, 국립공원 경계는 실제
# 관광 category가 있음 (upstream knps-feature-etl.md §4).
_SENTINEL_CATEGORY: Final[str] = "00000000"
# 국립공원 경계 (TOURISM_NATURAL_LANDSCAPE_MOUNTAIN_VALLEY_NATIONAL_PARK).
_NATIONAL_PARK_CATEGORY: Final[str] = "01020101"
# 탐방로/시설도로 (TOURISM_NATURAL_LANDSCAPE_MOUNTAIN_VALLEY_FOREST_TRAIL).
_TRAIL_CATEGORY: Final[str] = "01020103"
# route/national_park maki — upstream knps-feature-etl.md §4 표 ("park").
_PARK_MAKI: Final[str] = "park"


KNPS_GEOMETRY_DATASETS: Final[dict[str, KnpsGeometryDatasetSpec]] = {
    "knps_trails": KnpsGeometryDatasetSpec(
        "knps_trails",
        feature_kind=FeatureKind.ROUTE,
        detail_kind="hiking_trail",
        allowed_geom_types=ROUTE_GEOMETRY_TYPES,
        category=_TRAIL_CATEGORY,
        marker_icon=_PARK_MAKI,
        marker_color="P-06",
    ),
    "knps_linear_facilities": KnpsGeometryDatasetSpec(
        "knps_linear_facilities",
        feature_kind=FeatureKind.ROUTE,
        detail_kind="facility_road",
        allowed_geom_types=ROUTE_GEOMETRY_TYPES,
        category=_TRAIL_CATEGORY,
        marker_icon=_PARK_MAKI,
        marker_color="P-06",
    ),
    "knps_park_boundaries": KnpsGeometryDatasetSpec(
        "knps_park_boundaries",
        feature_kind=FeatureKind.AREA,
        detail_kind="national_park",
        allowed_geom_types=AREA_GEOMETRY_TYPES,
        category=_NATIONAL_PARK_CATEGORY,  # upstream §4 — 경계도 관광 category 보유
        marker_icon=_PARK_MAKI,
        marker_color="P-06",
    ),
    "knps_hazard_zones": KnpsGeometryDatasetSpec(
        "knps_hazard_zones",
        feature_kind=FeatureKind.AREA,
        detail_kind="hazard_zone",
        allowed_geom_types=AREA_GEOMETRY_TYPES,
        category=None,  # 위험지역은 관광 category 없음 (upstream §3/§4)
        marker_icon="barrier",
        marker_color="P-13",
    ),
    "knps_protected_areas": KnpsGeometryDatasetSpec(
        "knps_protected_areas",
        feature_kind=FeatureKind.AREA,
        detail_kind="protected_area",
        allowed_geom_types=AREA_GEOMETRY_TYPES,
        category=None,  # 보호지역도 관광 category 없음 (upstream §2 layer)
        marker_icon="barrier",
        marker_color="P-13",
    ),
}

KNPS_GEOMETRY_DATASET_KEYS: Final[frozenset[str]] = frozenset(KNPS_GEOMETRY_DATASETS)


def _geometry_detail(
    spec: KnpsGeometryDatasetSpec, feature_id: str, raw: dict[str, Any]
) -> RouteDetail | AreaDetail:
    """spec.feature_kind에 맞는 detail 생성 (route/area)."""
    if spec.feature_kind is FeatureKind.ROUTE:
        return RouteDetail(
            feature_id=feature_id,
            route_type=spec.detail_kind,
            geometry_source="knps",
            geometry_status="provided",
            payload={"knps_dataset": spec.dataset_key},
        )
    return AreaDetail(
        feature_id=feature_id,
        area_kind=spec.detail_kind,  # Literal 값 검증은 AreaDetail validator
        boundary_source="knps",
        payload={"knps_dataset": spec.dataset_key},
    )


def _geometry_record_to_bundle(
    record: KnpsGeometryRecord,
    spec: KnpsGeometryDatasetSpec,
    *,
    fetched_at: datetime,
) -> FeatureBundle | None:
    """KNPS geometry record 1건 → route/area ``FeatureBundle``.

    geometry 파싱 실패/경계 밖 centroid는 ``None`` 반환 (호출자가 skip/집계).
    """
    try:
        canonical_wkt, centroid = normalize_geometry(
            record.geom_wkt, allowed_types=spec.allowed_geom_types
        )
    except GeometryError:
        return None

    category = spec.category if spec.category is not None else _SENTINEL_CATEGORY
    raw_data = dict(record.raw)
    payload_hash = make_payload_hash(raw_data)
    source_record_key = make_source_record_key(
        provider=PROVIDER_NAME,
        dataset_key=spec.dataset_key,
        source_entity_type=_SOURCE_ENTITY_TYPE,
        source_entity_id=record.source_id,
        raw_payload_hash=payload_hash,
    )
    feature_id = make_feature_id(
        bjd_code=None,
        kind=spec.feature_kind.value,
        category=category,
        source_type=f"{PROVIDER_NAME}:{spec.dataset_key}",
        source_natural_key=record.source_id,
    )
    normalized_name = normalize_korean_text(record.name) or record.name

    feature = Feature(
        feature_id=feature_id,
        kind=spec.feature_kind,
        name=normalized_name,
        coord=centroid,  # 선/면 대표 좌표 = centroid (ADR-012, 지도 마커용)
        geom=canonical_wkt,
        category=category,
        marker_icon=spec.marker_icon,
        marker_color=spec.marker_color,
        detail=_geometry_detail(spec, feature_id, raw_data),
    )
    source_record = SourceRecord(
        provider=normalize_provider_name(PROVIDER_NAME),
        dataset_key=spec.dataset_key,
        source_entity_type=_SOURCE_ENTITY_TYPE,
        source_entity_id=record.source_id,
        raw_payload_hash=payload_hash,
        raw_name=record.name,
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


def knps_geometry_records_to_bundles(
    records: Iterable[KnpsGeometryRecord],
    *,
    dataset_key: str,
    fetched_at: datetime,
) -> list[FeatureBundle]:
    """KNPS route/area dataset의 파싱된 행들(WKT geometry) → ``list[FeatureBundle]``.

    geometry 파싱 실패/한국 경계 밖 centroid 행은 **건너뛴다**(결과에서 제외).
    SHP/CSV 디코딩·좌표계 변환은 호출자 책임 — 본 함수는 WKT(4326) 입력만 받는다.

    Parameters
    ----------
    records
        ``KnpsGeometryRecord`` Protocol 만족 (``geom_wkt``는 EPSG:4326 WKT).
    dataset_key
        ``KNPS_GEOMETRY_DATASETS`` 키 (trails / linear_facilities /
        park_boundaries / hazard_zones / protected_areas).
    fetched_at
        provider 호출 시각 (KST aware, ADR-019).

    Raises
    ------
    KeyError
        ``dataset_key``가 route/area geometry dataset이 아님.
    """
    try:
        spec = KNPS_GEOMETRY_DATASETS[dataset_key]
    except KeyError as exc:
        raise KeyError(
            f"KNPS route/area geometry dataset 아님: {dataset_key!r}. "
            f"지원: {sorted(KNPS_GEOMETRY_DATASETS)}. Point/place는 "
            "knps_point_records_to_bundles."
        ) from exc

    bundles: list[FeatureBundle] = []
    for record in records:
        bundle = _geometry_record_to_bundle(record, spec, fetched_at=fetched_at)
        if bundle is not None:
            bundles.append(bundle)
    return bundles
