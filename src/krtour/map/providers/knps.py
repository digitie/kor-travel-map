"""``krtour.map.providers.knps`` — 국립공원공단(KNPS) file dataset → Feature 변환.

`python-knps-api`(`digitie/python-knps-api`, ADR-028 + amendment 2026-05-25)가
제공하는 14건 keyless file dataset을 본 라이브러리 ``Feature`` 계약으로 정규화한다.
ADR-006(provider wrapper 금지) — knps-api의 public client/catalog를 직접 쓰고,
본 모듈은 **순수 변환 함수**만 둔다 (ADR-002).

knps-api는 raw bytes(`client.files...`)와 `FileArtifact` preview만 제공한다.
**SHP/CSV 파싱은 본 라이브러리 책임** (`docs/knps-feature-etl.md §5`). 본 PR은
**Point CSV → place** 경로(검증된 5 dataset: visitor_centers/restrooms/
cultural_resources/campgrounds/shelters)를 구현한다. SHP(area)/LineString(route)/
Polygon(area)은 `pyshp`+`shapely` 파서가 필요해 후속 PR (stub로 표시).

입력 계약: 본 모듈은 raw bytes를 직접 파싱하지 않고, **이미 행 단위로 파싱된**
``KnpsPointRecord`` Protocol(좌표 + 이름 + dataset_key + raw dict)을 받는다.
CSV 디코딩(CP949 등)/컬럼 추출은 호출자(Dagster asset) 또는 후속 parser helper가
수행 — provider 변환 함수는 좌표계·category·DTO 조립에 집중 (테스트 용이).

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
from krtour.map.core.ids import (
    make_feature_id,
    make_payload_hash,
    make_source_record_key,
)
from krtour.map.core.providers import normalize_provider_name
from krtour.map.dto import (
    Coordinate,
    Feature,
    FeatureBundle,
    FeatureKind,
    PlaceDetail,
    SourceLink,
    SourceRecord,
    SourceRole,
)

__all__ = [
    "KnpsPointRecord",
    "KnpsPlaceDatasetSpec",
    "KNPS_PLACE_DATASETS",
    "KNPS_POINT_DATASET_KEYS",
    "knps_point_records_to_bundles",
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
