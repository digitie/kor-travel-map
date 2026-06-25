"""``test_providers_knps`` — KNPS Point/place dataset 변환 (ADR-028/034 7단계).

본 PR 테스트 범위:
- 5건 Point/place dataset(visitor_centers/restrooms/campgrounds/shelters/
  cultural_resources) happy path + category/place_kind/maki 정합.
- cultural_resources subtype 분기 (사찰/유적/기타).
- 좌표 없는 record는 ``Feature.coord=None``.
- 결정성 — 같은 입력은 같은 ``feature_id`` / ``source_record_key``.
- ``FeatureBundle`` FK consistency + SourceRole.PRIMARY.
- 미지원 dataset_key는 ``KeyError`` (SHP/route/area는 후속 PR).
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import pytest

from kortravelmap.dto import FeatureBundle, FeatureKind, SourceRole
from kortravelmap.providers.knps import (
    KNPS_GEOMETRY_DATASET_KEYS,
    KNPS_GEOMETRY_DATASETS,
    KNPS_PLACE_DATASETS,
    KNPS_POINT_DATASET_KEYS,
    PROVIDER_NAME,
    KnpsGeometryColumnMap,
    KnpsPointColumnMap,
    resolve_cultural_resource_category,
)
from kortravelmap.providers.knps import (
    knps_csv_preview_to_geometry_bundles as _csv_geometry_async,
)
from kortravelmap.providers.knps import (
    knps_csv_preview_to_point_bundles as _csv_point_async,
)
from kortravelmap.providers.knps import (
    knps_geometry_records_to_bundles as _geometry_async,
)
from kortravelmap.providers.knps import (
    knps_point_records_to_bundles as _point_async,
)
from kortravelmap.providers.knps_name_translations import (
    KNPS_PROTECTED_AREA_KOREAN_NAMES,
)


# sync 테스트 ergonomics — 실제 async 변환을 asyncio.run으로 구동.
def knps_point_records_to_bundles(
    records: Iterable[Any], **kwargs: Any
) -> list[FeatureBundle]:
    return asyncio.run(_point_async(records, **kwargs))


def knps_geometry_records_to_bundles(
    records: Iterable[Any], **kwargs: Any
) -> list[FeatureBundle]:
    return asyncio.run(_geometry_async(records, **kwargs))


def knps_csv_preview_to_point_bundles(preview: Any, **kwargs: Any) -> list[FeatureBundle]:
    return asyncio.run(_csv_point_async(preview, **kwargs))


def knps_csv_preview_to_geometry_bundles(
    preview: Any, **kwargs: Any
) -> list[FeatureBundle]:
    return asyncio.run(_csv_geometry_async(preview, **kwargs))

_KST = timezone(timedelta(hours=9))
_FETCHED = datetime(2026, 5, 29, 12, 0, tzinfo=_KST)


@dataclass(frozen=True)
class _Rec:
    """`KnpsPointRecord` Protocol 만족."""

    source_id: str
    name: str | None
    longitude: Decimal | None
    latitude: Decimal | None
    raw: dict[str, Any]


def _one(dataset_key: str, **over: Any):
    rec = _Rec(
        source_id=over.get("source_id", "KN-001"),
        name=over.get("name", "북한산 시설"),
        longitude=over.get("longitude", Decimal("126.9876")),
        latitude=over.get("latitude", Decimal("37.6584")),
        raw=over.get("raw", {"MNG_NO": "KN-001"}),
    )
    return knps_point_records_to_bundles(
        [rec], dataset_key=dataset_key, fetched_at=_FETCHED
    )[0]


def test_visitor_center_mapping() -> None:
    b = _one("knps_visitor_centers")
    assert b.feature.kind is FeatureKind.PLACE
    assert b.feature.category == "01060101"
    assert b.feature.detail.place_kind == "visitor_center"
    assert b.feature.marker_icon == "information"
    assert b.feature.coord is not None
    assert float(b.feature.coord.lon) == pytest.approx(126.9876)


def test_shelter_uses_adr027_category() -> None:
    b = _one("knps_shelters", name="대피소")
    assert b.feature.category == "03080100"  # LODGING_MOUNTAIN_SHELTER_KNPS
    assert b.feature.detail.place_kind == "mountain_shelter"
    assert b.feature.marker_icon == "shelter"


def test_restroom_and_campground_categories() -> None:
    assert _one("knps_restrooms").feature.category == "05060000"
    assert _one("knps_campgrounds").feature.category == "03060100"


@pytest.mark.parametrize(
    ("dataset_key", "maki"),
    [
        # upstream knps-feature-etl.md §4 표와 1:1 (category 카탈로그 drift 방지)
        ("knps_visitor_centers", "information"),
        ("knps_restrooms", "toilet"),
        ("knps_campgrounds", "campsite"),
        ("knps_shelters", "shelter"),
    ],
)
def test_place_maki_matches_upstream_table(dataset_key: str, maki: str) -> None:
    assert _one(dataset_key).feature.marker_icon == maki


@pytest.mark.parametrize(
    ("rtype", "category", "place_kind"),
    [
        ("사찰", "01070100", "temple"),
        ("유적", "01070300", "historic_site"),
        ("사적지", "01070300", "historic_site"),
        ("기념물", "01070300", "historic_site"),
        ("전망대", "01070000", "cultural_resource"),
        ("", "01070000", "cultural_resource"),
    ],
)
def test_cultural_resource_subtype_branching(
    rtype: str, category: str, place_kind: str
) -> None:
    cat, kind = resolve_cultural_resource_category({"RESOURCE_TYPE": rtype})
    assert (cat, kind) == (category, place_kind)


def test_cultural_resource_bundle_dynamic_category() -> None:
    b = _one(
        "knps_cultural_resources",
        name="화엄사",
        raw={"RESOURCE_TYPE": "사찰", "MNG_NO": "CR-1"},
    )
    assert b.feature.category == "01070100"
    assert b.feature.detail.place_kind == "temple"
    assert b.feature.marker_icon == "religious-buddhist"


def test_missing_coord_yields_none() -> None:
    b = _one("knps_restrooms", longitude=None, latitude=None)
    assert b.feature.coord is None
    assert b.source_record.raw_longitude is None


def test_out_of_korea_coord_is_dropped() -> None:
    # 한국 경계 밖 좌표는 Coordinate validator가 reject → coord=None.
    b = _one("knps_restrooms", longitude=Decimal("0.0"), latitude=Decimal("0.0"))
    assert b.feature.coord is None


def test_nameless_point_record_is_skipped() -> None:
    # knps-api 실모델 name은 str | None — 이름 없는 행은 skip (배치는 계속).
    recs = [
        _Rec("K-1", None, Decimal("127.0"), Decimal("37.5"), {}),
        _Rec("K-2", "  ", Decimal("127.0"), Decimal("37.5"), {}),
        _Rec("K-3", "탐방로입구 화장실", Decimal("127.0"), Decimal("37.5"), {}),
    ]
    bundles = knps_point_records_to_bundles(
        recs, dataset_key="knps_restrooms", fetched_at=_FETCHED
    )
    assert [b.feature.name for b in bundles] == ["탐방로입구 화장실"]


def test_primary_source_and_provider_name() -> None:
    b = _one("knps_visitor_centers")
    assert b.source_link.source_role is SourceRole.PRIMARY
    assert b.source_link.is_primary_source is True
    assert b.source_link.confidence == 100
    assert b.source_record.provider == PROVIDER_NAME


def test_deterministic_ids() -> None:
    b1 = _one("knps_shelters")
    b2 = _one("knps_shelters")
    assert b1.feature.feature_id == b2.feature.feature_id
    assert b1.source_record.source_record_key == b2.source_record.source_record_key


def test_bundle_fk_consistency() -> None:
    # FeatureBundle model_validator: source_link FK가 feature/source_record와 일치.
    b = _one("knps_campgrounds")
    assert b.source_link.feature_id == b.feature.feature_id
    assert b.source_link.source_record_key == b.source_record.source_record_key


def test_unsupported_dataset_key_raises() -> None:
    with pytest.raises(KeyError, match="Point/place dataset 아님"):
        knps_point_records_to_bundles(
            [], dataset_key="knps_park_boundaries", fetched_at=_FETCHED
        )


def test_point_dataset_keys_match_registry() -> None:
    assert frozenset(KNPS_PLACE_DATASETS) == KNPS_POINT_DATASET_KEYS
    assert "knps_visitor_centers" in KNPS_POINT_DATASET_KEYS


def test_preserves_input_order() -> None:
    recs = [
        _Rec(f"K-{i}", f"시설{i}", Decimal("127.0"), Decimal("37.5"), {"i": i})
        for i in range(3)
    ]
    bundles = knps_point_records_to_bundles(
        recs, dataset_key="knps_restrooms", fetched_at=_FETCHED
    )
    assert [b.source_record.source_entity_id for b in bundles] == ["K-0", "K-1", "K-2"]


# ── geometry datasets (route/area) ───────────────────────────────────────

_LINE = "LINESTRING(126.98 37.65, 126.99 37.66, 127.0 37.67)"
_POLY = "POLYGON((126.9 37.6, 127.0 37.6, 127.0 37.7, 126.9 37.7, 126.9 37.6))"


@dataclass(frozen=True)
class _GRec:
    """`KnpsGeometryRecord` Protocol 만족."""

    source_id: str
    name: str | None
    geom_wkt: str
    raw: dict[str, Any]


def _geo_one(dataset_key: str, geom_wkt: str, **over: Any):
    rec = _GRec(
        source_id=over.get("source_id", "G-001"),
        name=over.get("name", "북한산 둘레길"),
        geom_wkt=geom_wkt,
        raw=over.get("raw", {"NO": "G-001"}),
    )
    return knps_geometry_records_to_bundles(
        [rec], dataset_key=dataset_key, fetched_at=_FETCHED
    )


def test_trail_route_mapping() -> None:
    b = _geo_one("knps_trails", _LINE)[0]
    assert b.feature.kind is FeatureKind.ROUTE
    assert b.feature.category == "01020103"
    assert b.feature.marker_icon == "park"  # upstream §4 — route는 park
    assert b.feature.detail.route_type == "hiking_trail"
    assert b.feature.detail.geometry_source == "knps"
    assert b.feature.geom is not None
    assert "LINESTRING" in b.feature.geom
    # centroid가 coord로
    assert b.feature.coord is not None
    assert float(b.feature.coord.lon) == pytest.approx(126.99)


def test_linear_facility_route_type() -> None:
    b = _geo_one("knps_linear_facilities", _LINE)[0]
    assert b.feature.detail.route_type == "facility_road"
    assert b.feature.category == "01020103"
    assert b.feature.marker_icon == "park"


def test_park_boundary_area_mapping() -> None:
    b = _geo_one("knps_park_boundaries", _POLY, name="북한산국립공원")[0]
    assert b.feature.kind is FeatureKind.AREA
    # 국립공원 경계는 실제 관광 category 보유 (upstream §4, sentinel 아님)
    assert b.feature.category == "01020101"
    assert b.feature.marker_icon == "park"
    assert b.feature.detail.area_kind == "national_park"
    assert b.feature.detail.boundary_source == "knps"
    assert b.feature.geom is not None
    assert b.feature.geom.startswith("POLYGON")


def test_park_boundary_area_name_falls_back_to_raw_park_name() -> None:
    b = _geo_one(
        "knps_park_boundaries",
        _POLY,
        name=None,
        raw={"NPK_NM": "가야산", "NO": "PARK-1"},
    )[0]
    assert b.feature.kind is FeatureKind.AREA
    assert b.feature.name == "가야산 국립공원"
    assert b.source_record.raw_name == "가야산 국립공원"


def test_protected_area_translates_raw_english_name() -> None:
    b = _geo_one(
        "knps_protected_areas",
        _POLY,
        name=None,
        raw={"NAME": "Jeju Island", "MNUM": "PROTECTED-1"},
    )[0]
    assert b.feature.kind is FeatureKind.AREA
    assert b.feature.name == "제주도"
    assert b.source_record.raw_name == "제주도"


def test_protected_area_prefers_recoverable_raw_korean_name() -> None:
    b = _geo_one(
        "knps_protected_areas",
        _POLY,
        name="Bongpyeong",
        raw={"ORIG_NAME": "遊됲룊", "NAME": "Bongpyeong", "MNUM": "PROTECTED-1"},
    )[0]
    assert b.feature.name == "봉평"
    assert b.source_record.raw_name == "봉평"


def test_protected_area_ignores_lossy_mojibake_korean_name() -> None:
    b = _geo_one(
        "knps_protected_areas",
        _POLY,
        name="Jeonbuk Jeongeup Shinseongdong",
        raw={
            "ORIG_NAME": "�쟾遺� �젙�쓭�떆 �떊�젙�룞",
            "NAME": "Jeonbuk Jeongeup Shinseongdong",
            "MNUM": "PROTECTED-1",
        },
    )[0]
    assert b.feature.name == "전북 정읍 신성동 야생동물보호구역"


def test_protected_area_ignores_unrecoverable_cjk_mojibake_name() -> None:
    b = _geo_one(
        "knps_protected_areas",
        _POLY,
        name="Cheokchi",
        raw={"ORIG_NAME": "泥숈튂", "NAME": "Cheokchi", "MNUM": "PROTECTED-1"},
    )[0]
    assert b.feature.name == "척치 상수원보호구역"


def test_protected_area_ignores_latin_mixed_mojibake_name() -> None:
    b = _geo_one(
        "knps_protected_areas",
        _POLY,
        name="횓le volcanique et tunnels de lave de Jeju",
        raw={
            "ORIG_NAME": "횓le volcanique et tunnels de lave de Jeju",
            "NAME": "Jeju Volcanic Island and Lava Tubes",
            "MNUM": "PROTECTED-1",
        },
    )[0]
    assert b.feature.name == "제주 화산섬과 용암동굴"


def test_protected_area_translation_table_has_no_latin_letters() -> None:
    assert len(KNPS_PROTECTED_AREA_KOREAN_NAMES) == 1431
    assert all(
        re.search(r"[A-Za-z]", translated_name) is None
        for translated_name in KNPS_PROTECTED_AREA_KOREAN_NAMES.values()
    )


def test_hazard_and_protected_area_kinds() -> None:
    # 위험/보호지역은 관광 category 없음 → sentinel + barrier (upstream §3/§4)
    hazard = _geo_one("knps_hazard_zones", _POLY)[0]
    assert hazard.feature.detail.area_kind == "hazard_zone"
    assert hazard.feature.category == "00000000"
    assert hazard.feature.marker_icon == "barrier"
    protected = _geo_one("knps_protected_areas", _POLY)[0]
    assert protected.feature.detail.area_kind == "protected_area"
    assert protected.feature.category == "00000000"


def test_invalid_wkt_is_skipped() -> None:
    assert _geo_one("knps_trails", "NOT WKT") == []


def test_wrong_geometry_type_is_skipped() -> None:
    # trails(route)에 polygon → 허용 type 위반 → skip.
    assert _geo_one("knps_trails", _POLY) == []
    # park_boundaries(area)에 linestring → skip.
    assert _geo_one("knps_park_boundaries", _LINE) == []


def test_out_of_korea_geometry_is_skipped() -> None:
    assert _geo_one("knps_trails", "LINESTRING(0 0, 1 1)") == []


def test_nameless_geometry_record_is_skipped() -> None:
    # live trails에 이름 없는 코스 존재 (#407) — 그 행만 skip, 배치는 계속.
    assert _geo_one("knps_trails", _LINE, name=None) == []
    assert _geo_one("knps_trails", _LINE, name="  ") == []
    recs = [
        _GRec(source_id="G-1", name=None, geom_wkt=_LINE, raw={}),
        _GRec(source_id="G-2", name="북한산 둘레길", geom_wkt=_LINE, raw={}),
    ]
    bundles = knps_geometry_records_to_bundles(
        recs, dataset_key="knps_trails", fetched_at=_FETCHED
    )
    assert [b.feature.name for b in bundles] == ["북한산 둘레길"]


def test_geometry_deterministic_and_primary() -> None:
    b1 = _geo_one("knps_trails", _LINE)[0]
    b2 = _geo_one("knps_trails", _LINE)[0]
    assert b1.feature.feature_id == b2.feature.feature_id
    assert b1.source_link.source_role is SourceRole.PRIMARY
    assert b1.source_link.feature_id == b1.feature.feature_id


def test_geometry_unsupported_dataset_key_raises() -> None:
    with pytest.raises(KeyError, match="route/area geometry dataset 아님"):
        knps_geometry_records_to_bundles(
            [], dataset_key="knps_visitor_centers", fetched_at=_FETCHED
        )


def test_geometry_dataset_keys_registry() -> None:
    assert frozenset(KNPS_GEOMETRY_DATASETS) == KNPS_GEOMETRY_DATASET_KEYS
    assert "knps_trails" in KNPS_GEOMETRY_DATASET_KEYS
    # Point/geometry dataset 집합은 서로 disjoint.
    assert KNPS_GEOMETRY_DATASET_KEYS.isdisjoint(KNPS_POINT_DATASET_KEYS)


# ── knps-api CsvPreview → FeatureBundle 브리지 ────────────────────────────


@dataclass(frozen=True)
class _Row:
    """knps-api ``CsvPreviewRow`` structural stub."""

    mapping: dict[str, str | None]

    @property
    def as_dict(self) -> dict[str, str | None]:
        return self.mapping


@dataclass(frozen=True)
class _Preview:
    """knps-api ``CsvPreview`` structural stub."""

    rows: tuple[_Row, ...]


def _preview(*dicts: dict[str, str | None]) -> _Preview:
    return _Preview(rows=tuple(_Row(d) for d in dicts))


def test_csv_preview_point_default_columns() -> None:
    prev = _preview(
        {"관리번호": "VC-1", "명칭": "북한산 탐방안내소", "경도": "126.9876", "위도": "37.6584"},
    )
    b = knps_csv_preview_to_point_bundles(
        prev, dataset_key="knps_visitor_centers", fetched_at=_FETCHED
    )[0]
    assert b.feature.name == "북한산 탐방안내소"
    assert b.feature.category == "01060101"
    assert b.feature.coord is not None
    assert float(b.feature.coord.lon) == pytest.approx(126.9876)
    assert b.source_record.source_entity_id == "VC-1"


def test_csv_preview_point_missing_coord_is_none() -> None:
    prev = _preview({"관리번호": "VC-2", "명칭": "좌표없음", "경도": "", "위도": ""})
    b = knps_csv_preview_to_point_bundles(
        prev, dataset_key="knps_restrooms", fetched_at=_FETCHED
    )[0]
    assert b.feature.coord is None


def test_csv_preview_point_id_hash_fallback() -> None:
    # source_id 컬럼 없음 → 행 해시 기반 결정적 fallback.
    prev = _preview({"명칭": "무명소", "경도": "127.0", "위도": "37.5"})
    b = knps_csv_preview_to_point_bundles(
        prev, dataset_key="knps_restrooms", fetched_at=_FETCHED
    )[0]
    assert b.source_record.source_entity_id.startswith("row-")
    # 결정적: 같은 행은 같은 id
    b2 = knps_csv_preview_to_point_bundles(
        prev, dataset_key="knps_restrooms", fetched_at=_FETCHED
    )[0]
    assert b.source_record.source_entity_id == b2.source_record.source_entity_id


def test_csv_preview_point_column_map_override() -> None:
    cm = KnpsPointColumnMap(
        source_id=("ID",), name=("NAME",), longitude=("LON",), latitude=("LAT",)
    )
    prev = _preview({"ID": "x1", "NAME": "영문헤더", "LON": "127.1", "LAT": "37.4"})
    b = knps_csv_preview_to_point_bundles(
        prev, dataset_key="knps_campgrounds", fetched_at=_FETCHED, column_map=cm
    )[0]
    assert b.feature.name == "영문헤더"
    assert float(b.feature.coord.lon) == pytest.approx(127.1)


def test_csv_preview_point_cultural_subtype_from_raw() -> None:
    prev = _preview(
        {
            "관리번호": "c1",
            "명칭": "화엄사",
            "경도": "127.3",
            "위도": "35.3",
            "RESOURCE_TYPE": "사찰",
        },
    )
    b = knps_csv_preview_to_point_bundles(
        prev, dataset_key="knps_cultural_resources", fetched_at=_FETCHED
    )[0]
    assert b.feature.category == "01070100"
    assert b.feature.detail.place_kind == "temple"


def test_csv_preview_point_unsupported_key_raises() -> None:
    with pytest.raises(KeyError, match="Point/place dataset 아님"):
        knps_csv_preview_to_point_bundles(
            _preview(), dataset_key="knps_trails", fetched_at=_FETCHED
        )


def test_csv_preview_geometry_wkt_column() -> None:
    prev = _preview(
        {"관리번호": "t1", "노선명": "둘레길", "WKT": "LINESTRING(127 37.5, 127.1 37.6)"},
        {"관리번호": "t2", "노선명": "WKT없음"},  # geometry 없음 → skip
    )
    bundles = knps_csv_preview_to_geometry_bundles(
        prev, dataset_key="knps_trails", fetched_at=_FETCHED
    )
    assert len(bundles) == 1
    assert bundles[0].feature.kind is FeatureKind.ROUTE
    assert bundles[0].feature.geom is not None


def test_csv_preview_geometry_column_map_override() -> None:
    cm = KnpsGeometryColumnMap(source_id=("ID",), name=("NM",), geom_wkt=("SHAPE",))
    prev = _preview(
        {
            "ID": "p1",
            "NM": "북한산",
            "SHAPE": "POLYGON((126.9 37.6,127 37.6,127 37.7,126.9 37.7,126.9 37.6))",
        }
    )
    b = knps_csv_preview_to_geometry_bundles(
        prev, dataset_key="knps_park_boundaries", fetched_at=_FETCHED, column_map=cm
    )[0]
    assert b.feature.kind is FeatureKind.AREA
    assert b.feature.category == "01020101"


def test_csv_preview_geometry_unsupported_key_raises() -> None:
    with pytest.raises(KeyError, match="route/area geometry dataset 아님"):
        knps_csv_preview_to_geometry_bundles(
            _preview(), dataset_key="knps_restrooms", fetched_at=_FETCHED
        )
