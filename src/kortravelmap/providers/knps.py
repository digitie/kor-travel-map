"""``kortravelmap.providers.knps`` — 국립공원공단(KNPS) file dataset → Feature 변환.

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

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Final, Protocol, runtime_checkable

from kortravelmap.category import get_category, is_known_category_code
from kortravelmap.core.address import normalize_korean_text
from kortravelmap.core.geometry import (
    AREA_GEOMETRY_TYPES,
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
from kortravelmap.dto import (
    Address,
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
from kortravelmap.geocoding import ReverseGeocoder, cached_reverse_geocoder

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
    # knps-api CsvPreview → FeatureBundle 브리지
    "KnpsCsvRow",
    "KnpsCsvPreview",
    "KnpsPointColumnMap",
    "KnpsGeometryColumnMap",
    "KNPS_DEFAULT_POINT_COLUMN_MAP",
    "KNPS_DEFAULT_GEOMETRY_COLUMN_MAP",
    "knps_csv_preview_to_point_bundles",
    "knps_csv_preview_to_geometry_bundles",
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
    def name(self) -> str | None:
        """시설 이름 (한글). knps-api ``KnpsPlaceRecord.name``은 ``str | None``
        (ADR-044 — provider 실모델 기준). 없으면 행 skip."""
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

    ``docs/etl/knps-feature-etl.md §2.1/§4`` 검증표 그대로. cultural_resources는
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
# feature_kind='place'). docs/etl/knps-feature-etl.md §4 표 기준.
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

    ``docs/etl/knps-feature-etl.md §2.3`` 분기표. 키 이름은 대소문자/한영 변형을 폭넓게
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


async def _point_record_to_bundle(
    record: KnpsPointRecord,
    spec: KnpsPlaceDatasetSpec,
    *,
    fetched_at: datetime,
    reverse_geocoder: ReverseGeocoder | None,
) -> FeatureBundle | None:
    """KNPS point record 1건 → place ``FeatureBundle``.

    이름 없는 record는 ``None`` 반환 — ``Feature.name`` 필수에 표시/검색 단서가
    없다 (mcst/datagokr file-data와 동일 규칙, 호출자가 skip).
    """
    normalized_name = normalize_korean_text(record.name)
    if normalized_name is None:  # None/빈/공백-only 이름 모두 skip
        return None

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

    # KNPS file dataset엔 법정동코드가 없다. 좌표가 있고 reverse_geocoder가 주입되면
    # feature_id 계산 전에 await해 bjd_code를 채운다 (ADR-009 — feature_id는 bjd 의존).
    coord = _coord(record)
    address: Address | None = None
    if coord is not None and reverse_geocoder is not None:
        address = await reverse_geocoder(coord)
    bjd_code = address.bjd_code if address is not None else None

    feature_id = make_feature_id(
        bjd_code=bjd_code,  # 없으면 make_feature_id 내부에서 'global'
        kind=FeatureKind.PLACE.value,
        category=category,
        source_type=f"{PROVIDER_NAME}:{spec.dataset_key}",
        source_natural_key=record.source_id,
    )

    feature = Feature(
        feature_id=feature_id,
        kind=FeatureKind.PLACE,
        name=normalized_name,
        coord=coord,
        address=address or Address(),
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


async def knps_point_records_to_bundles(
    records: Iterable[KnpsPointRecord],
    *,
    dataset_key: str,
    fetched_at: datetime,
    reverse_geocoder: ReverseGeocoder | None = None,
) -> list[FeatureBundle]:
    """KNPS Point/place dataset의 파싱된 행들 → ``list[FeatureBundle]``.

    이름 없는 행은 **건너뛴다** — ``Feature.name`` 필수에 표시/검색 단서가 없다
    (mcst/datagokr file-data와 동일 규칙).

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
    reverse_geocoder
        좌표 → ``Address`` async 역지오코더 (``kortravelmap.geocoding.
        ReverseGeocoder``). KNPS file dataset엔 법정동코드가 없으므로, 주입하면
        좌표로 bjd_code를 채워 feature_id가 'global' bucket을 벗어난다 (ADR-009).
        중복 좌표는 ``cached_reverse_geocoder``로 1회만 호출.

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
            "(docs/etl/knps-feature-etl.md §5)."
        ) from exc

    geocoder = (
        cached_reverse_geocoder(reverse_geocoder)
        if reverse_geocoder is not None
        else None
    )
    bundles: list[FeatureBundle] = []
    for record in records:
        bundle = await _point_record_to_bundle(
            record, spec, fetched_at=fetched_at, reverse_geocoder=geocoder
        )
        if bundle is not None:
            bundles.append(bundle)
    return bundles


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
    def name(self) -> str | None:
        """탐방로/구역 이름 (한글). knps-api ``KnpsGeoRecord.name``은
        ``str | None`` (ADR-044 — provider 실모델 기준). 없으면 행 skip."""
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
    갖고(upstream ``docs/etl/knps-feature-etl.md §4``), 위험지역/보호지역은 category가
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


def _raw_text(raw: Mapping[str, Any], *keys: str) -> str | None:
    """raw dict에서 첫 번째 비어 있지 않은 문자열 값을 꺼낸다."""
    for key in keys:
        value = raw.get(key)
        if value is None:
            continue
        text = normalize_korean_text(str(value))
        if text is not None:
            return text
    return None


def _geometry_record_name(
    record: KnpsGeometryRecord, spec: KnpsGeometryDatasetSpec
) -> str | None:
    """KNPS geometry 이름을 provider normalized field 또는 raw column에서 결정한다."""
    normalized_name = normalize_korean_text(record.name)
    if normalized_name is not None:
        return normalized_name

    raw = record.raw
    if spec.dataset_key == "knps_park_boundaries":
        park_name = _raw_text(raw, "NPK_NM", "국립공원명", "PARK_NM", "name", "NAME")
        if park_name is None:
            return None
        return park_name if "국립공원" in park_name else f"{park_name} 국립공원"
    if spec.dataset_key == "knps_protected_areas":
        return _raw_text(raw, "NAME", "ORIG_NAME", "DESIG_ENG", "DESIG")
    return None


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


async def _geometry_record_to_bundle(
    record: KnpsGeometryRecord,
    spec: KnpsGeometryDatasetSpec,
    *,
    fetched_at: datetime,
    reverse_geocoder: ReverseGeocoder | None,
) -> FeatureBundle | None:
    """KNPS geometry record 1건 → route/area ``FeatureBundle``.

    route는 이름 없는 record를 건너뛰고, area dataset은 raw 속성에서 이름을
    복구한다. geometry 파싱 실패/경계 밖 centroid는 ``None`` 반환(호출자가 skip/집계).
    """
    normalized_name = _geometry_record_name(record, spec)
    if normalized_name is None:  # None/빈/공백-only 이름 모두 skip
        return None

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

    # route/area도 법정동코드가 없다. centroid를 역지오코딩해 feature_id 계산 전에
    # bjd_code/주소를 채운다 (ADR-009).
    address: Address | None = None
    if reverse_geocoder is not None:
        address = await reverse_geocoder(centroid)
    bjd_code = address.bjd_code if address is not None else None

    feature_id = make_feature_id(
        bjd_code=bjd_code,
        kind=spec.feature_kind.value,
        category=category,
        source_type=f"{PROVIDER_NAME}:{spec.dataset_key}",
        source_natural_key=record.source_id,
    )
    feature = Feature(
        feature_id=feature_id,
        kind=spec.feature_kind,
        name=normalized_name,
        coord=centroid,  # 선/면 대표 좌표 = centroid (ADR-012, 지도 마커용)
        address=address or Address(),
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
        raw_name=record.name or normalized_name,
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


async def knps_geometry_records_to_bundles(
    records: Iterable[KnpsGeometryRecord],
    *,
    dataset_key: str,
    fetched_at: datetime,
    reverse_geocoder: ReverseGeocoder | None = None,
) -> list[FeatureBundle]:
    """KNPS route/area dataset의 파싱된 행들(WKT geometry) → ``list[FeatureBundle]``.

    이름 없는 행/geometry 파싱 실패/한국 경계 밖 centroid 행은 **건너뛴다**
    (결과에서 제외). SHP/CSV 디코딩·좌표계 변환은 호출자 책임 — 본 함수는
    WKT(4326) 입력만 받는다.

    Parameters
    ----------
    records
        ``KnpsGeometryRecord`` Protocol 만족 (``geom_wkt``는 EPSG:4326 WKT).
    dataset_key
        ``KNPS_GEOMETRY_DATASETS`` 키 (trails / linear_facilities /
        park_boundaries / hazard_zones / protected_areas).
    fetched_at
        provider 호출 시각 (KST aware, ADR-019).
    reverse_geocoder
        좌표 → ``Address`` async 역지오코더. 주입하면 centroid를 역지오코딩해
        bjd_code를 채워 feature_id가 'global' bucket을 벗어난다 (ADR-009).

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

    geocoder = (
        cached_reverse_geocoder(reverse_geocoder)
        if reverse_geocoder is not None
        else None
    )
    bundles: list[FeatureBundle] = []
    for record in records:
        bundle = await _geometry_record_to_bundle(
            record, spec, fetched_at=fetched_at, reverse_geocoder=geocoder
        )
        if bundle is not None:
            bundles.append(bundle)
    return bundles


# =====================================================================
# knps-api CsvPreview → FeatureBundle 브리지
# =====================================================================
#
# knps-api는 raw bytes를 `client.files.download_artifact(key, preview_rows=N)`로
# 파싱해 `FileArtifact.csv_previews[*]`(헤더 + 행)를 돌려준다 (preview_rows를 크게
# 주면 전 행 획득). 본 브리지는 그 `CsvPreview`(structural Protocol)를 직접 소비해
# place/route/area bundle로 잇는다 — knps를 import하지 않고 구조만 의존(ADR-006).
#
# ⚠️ 실제 CSV 컬럼명은 knps-api(소스/테스트/문서)에 없고 live(data.go.kr) 확인이
# 필요하다. 아래 DEFAULT 컬럼 후보는 data.go.kr 한국어 관례 기반 **best-guess**다.
# 적재 전 `CsvPreview.headers`로 검증하고 필요 시 `column_map`으로 override할 것.
# (geometry는 knps-api parser가 WGS84 WKT를 노출하면 그 컬럼을 가리키게 한다.)


@runtime_checkable
class KnpsCsvRow(Protocol):
    """knps-api ``CsvPreviewRow``의 structural 입력 shape."""

    @property
    def as_dict(self) -> dict[str, str | None]:
        """header→value dict (knps-api ``CsvPreviewRow.as_dict``)."""
        ...


@runtime_checkable
class KnpsCsvPreview(Protocol):
    """knps-api ``CsvPreview``의 structural 입력 shape."""

    @property
    def rows(self) -> tuple[KnpsCsvRow, ...]:
        """파싱된 데이터 행들 (knps-api ``CsvPreview.rows``)."""
        ...


@dataclass(frozen=True)
class KnpsPointColumnMap:
    """Point(place) CSV의 필드별 컬럼명 후보 (첫 매칭 우선).

    각 필드는 후보 헤더명 tuple — 행 dict에서 처음 매칭되는 비어있지 않은 값 사용.
    ⚠️ best-guess. live ``CsvPreview.headers``로 검증 후 확정/확장.
    """

    source_id: tuple[str, ...]
    name: tuple[str, ...]
    longitude: tuple[str, ...]
    latitude: tuple[str, ...]


@dataclass(frozen=True)
class KnpsGeometryColumnMap:
    """route/area CSV의 필드별 컬럼명 후보 (geometry는 WKT 컬럼)."""

    source_id: tuple[str, ...]
    name: tuple[str, ...]
    geom_wkt: tuple[str, ...]


# best-guess 기본 컬럼 후보 (VERIFY against live headers).
KNPS_DEFAULT_POINT_COLUMN_MAP: Final[KnpsPointColumnMap] = KnpsPointColumnMap(
    source_id=("관리번호", "고유번호", "일련번호", "번호", "NO", "no", "id"),
    name=("명칭", "시설명", "관리소명", "이름", "name"),
    longitude=("경도", "경도(WGS84)", "X좌표", "x좌표", "longitude", "lon", "lng", "x"),
    latitude=("위도", "위도(WGS84)", "Y좌표", "y좌표", "latitude", "lat", "y"),
)

KNPS_DEFAULT_GEOMETRY_COLUMN_MAP: Final[KnpsGeometryColumnMap] = KnpsGeometryColumnMap(
    source_id=("관리번호", "고유번호", "일련번호", "번호", "NO", "no", "id"),
    name=("명칭", "노선명", "구간명", "구역명", "이름", "name"),
    # knps-api parser가 노출할 WGS84 WKT 컬럼 후보 (현재 미확정).
    geom_wkt=("WKT", "wkt", "the_geom", "geom", "공간정보", "도형", "geometry"),
)


@dataclass(frozen=True)
class _CsvPointRecord:
    """``KnpsPointRecord`` Protocol을 만족하는 내부 record (CsvPreview 행 기반)."""

    source_id: str
    name: str
    longitude: Decimal | None
    latitude: Decimal | None
    raw: dict[str, Any]


@dataclass(frozen=True)
class _CsvGeometryRecord:
    """``KnpsGeometryRecord`` Protocol을 만족하는 내부 record."""

    source_id: str
    name: str
    geom_wkt: str
    raw: dict[str, Any]


def _pick(row: dict[str, str | None], candidates: tuple[str, ...]) -> str | None:
    """행 dict에서 후보 헤더 중 처음 매칭되는 비어있지 않은 값 (strip)."""
    for col in candidates:
        val = row.get(col)
        if val is not None:
            text = str(val).strip()
            if text:
                return text
    return None


def _to_decimal(text: str | None) -> Decimal | None:
    """좌표 문자열 → Decimal (빈값/파싱 실패는 None)."""
    if text is None:
        return None
    try:
        return Decimal(text)
    except (ArithmeticError, ValueError):
        return None


def _row_natural_key(row: dict[str, Any], picked_id: str | None) -> str:
    """source_id 컬럼이 없으면 행 내용 해시로 결정적 fallback."""
    return picked_id if picked_id is not None else f"row-{make_payload_hash(row)[:16]}"


async def knps_csv_preview_to_point_bundles(
    preview: KnpsCsvPreview,
    *,
    dataset_key: str,
    fetched_at: datetime,
    column_map: KnpsPointColumnMap | None = None,
    reverse_geocoder: ReverseGeocoder | None = None,
) -> list[FeatureBundle]:
    """knps-api ``CsvPreview`` → place ``FeatureBundle`` (Point dataset).

    ``column_map``이 ``None``이면 ``KNPS_DEFAULT_POINT_COLUMN_MAP``(best-guess)
    사용. 좌표 컬럼이 없거나 한국 경계 밖이면 ``Feature.coord=None``로 적재된다.

    Parameters
    ----------
    preview
        knps-api ``FileArtifact.csv_previews[*]`` 한 건 (structural Protocol).
    dataset_key
        ``KNPS_PLACE_DATASETS`` 키.
    fetched_at
        provider 호출 시각 (KST aware, ADR-019).
    column_map
        컬럼명 매핑 override (live ``CsvPreview.headers`` 확인 후 권장).
    reverse_geocoder
        좌표 → ``Address`` async 역지오코더 (bjd_code 보강, ADR-009).

    Raises
    ------
    KeyError
        ``dataset_key``가 Point/place dataset이 아님.
    """
    if dataset_key not in KNPS_PLACE_DATASETS:
        raise KeyError(
            f"KNPS Point/place dataset 아님: {dataset_key!r}. "
            f"지원: {sorted(KNPS_PLACE_DATASETS)}."
        )
    cmap = column_map or KNPS_DEFAULT_POINT_COLUMN_MAP
    records: list[_CsvPointRecord] = []
    for row in preview.rows:
        data = dict(row.as_dict)
        sid = _row_natural_key(data, _pick(data, cmap.source_id))
        name = _pick(data, cmap.name) or sid
        records.append(
            _CsvPointRecord(
                source_id=sid,
                name=name,
                longitude=_to_decimal(_pick(data, cmap.longitude)),
                latitude=_to_decimal(_pick(data, cmap.latitude)),
                raw=data,
            )
        )
    return await knps_point_records_to_bundles(
        records,
        dataset_key=dataset_key,
        fetched_at=fetched_at,
        reverse_geocoder=reverse_geocoder,
    )


async def knps_csv_preview_to_geometry_bundles(
    preview: KnpsCsvPreview,
    *,
    dataset_key: str,
    fetched_at: datetime,
    column_map: KnpsGeometryColumnMap | None = None,
    reverse_geocoder: ReverseGeocoder | None = None,
) -> list[FeatureBundle]:
    """knps-api ``CsvPreview`` → route/area ``FeatureBundle`` (geometry dataset).

    geometry WKT 컬럼이 없는 행은 건너뛴다. ⚠️ CSV의 geometry 표현(WKT 컬럼 vs
    좌표 컬럼)은 knps-api parser 확정 후 ``column_map``으로 맞춘다. SHP(ZIP)
    dataset(``knps_park_boundaries``)은 knps-api가 geometry를 노출한 뒤 본
    함수 대신 ``knps_geometry_records_to_bundles``로 직접 잇는다.

    Raises
    ------
    KeyError
        ``dataset_key``가 route/area geometry dataset이 아님.
    """
    if dataset_key not in KNPS_GEOMETRY_DATASETS:
        raise KeyError(
            f"KNPS route/area geometry dataset 아님: {dataset_key!r}. "
            f"지원: {sorted(KNPS_GEOMETRY_DATASETS)}."
        )
    cmap = column_map or KNPS_DEFAULT_GEOMETRY_COLUMN_MAP
    records: list[_CsvGeometryRecord] = []
    for row in preview.rows:
        data = dict(row.as_dict)
        wkt = _pick(data, cmap.geom_wkt)
        if wkt is None:
            continue  # geometry 없는 행은 skip (route/area는 geometry 필수)
        sid = _row_natural_key(data, _pick(data, cmap.source_id))
        name = _pick(data, cmap.name) or sid
        records.append(
            _CsvGeometryRecord(source_id=sid, name=name, geom_wkt=wkt, raw=data)
        )
    return await knps_geometry_records_to_bundles(
        records,
        dataset_key=dataset_key,
        fetched_at=fetched_at,
        reverse_geocoder=reverse_geocoder,
    )
