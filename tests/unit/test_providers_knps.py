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

from kortravelmap.category import is_known_category_code
from kortravelmap.dto import Address, Coordinate, FeatureBundle, FeatureKind, SourceRole
from kortravelmap.providers.knps import (
    KNPS_GEOMETRY_DATASET_KEYS,
    KNPS_GEOMETRY_DATASETS,
    KNPS_LOADABLE_GEOMETRY_DATASET_KEYS,
    KNPS_NATIONAL_PARK_PROMOTIONS,
    KNPS_PLACE_DATASETS,
    KNPS_POINT_DATASET_KEYS,
    KNPS_PROTECTED_AREA_DESIGNATION_CATEGORIES,
    PROVIDER_NAME,
    KnpsGeometryColumnMap,
    KnpsPointColumnMap,
    knps_geometry_snapshot_retires_absent,
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
    name = over.get("name", "북한산 시설")
    rec = _Rec(
        source_id=over.get("source_id", "KN-001"),
        name=name,
        longitude=over.get("longitude", Decimal("126.9876")),
        latitude=over.get("latitude", Decimal("37.6584")),
        # 실제 record처럼 이름은 원천 행의 한 값이다.
        raw=over.get("raw", {"MNG_NO": "KN-001", "KOR_NM": name}),
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
    assert b.source_record.raw_data == {"MNG_NO": "KN-001", "KOR_NM": "북한산 시설"}


def test_provider_corrected_name_enters_raw_hash_only_when_it_differs_from_source() -> None:
    """knps-api a472a37: 現… 표식을 걷은 이름은 원천 값과 다르다 — 해시에 넣어 재적재가 고친다."""
    plain = _one("knps_shelters", name="노고단대피소", raw={"시설물": "노고단대피소"})
    fixed = _one("knps_shelters", name="노고단대피소", raw={"시설물": "現노고단대피소"})
    assert plain.source_record.raw_data == {"시설물": "노고단대피소"}
    assert fixed.source_record.raw_data == {
        "시설물": "現노고단대피소",
        "__map_display_name__": "노고단대피소",
    }
    assert fixed.source_record.raw_payload_hash != _one(
        "knps_shelters", name="現노고단대피소", raw={"시설물": "現노고단대피소"}
    ).source_record.raw_payload_hash


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


def test_linear_facility_is_left_unloaded() -> None:
    """선형시설 671행은 이름이 `탐방로`·`탐방로12` 같은 일반명뿐이다(#1450).

    이름을 지어내지 않는다.
    """
    assert KNPS_GEOMETRY_DATASETS["knps_linear_facilities"].unloaded_reason
    assert _geo_one("knps_linear_facilities", _LINE, name="북한산 순환도로") == []
    assert "knps_linear_facilities" not in KNPS_LOADABLE_GEOMETRY_DATASET_KEYS


def test_park_boundary_buffer_dataset_is_left_unloaded_and_retires_old_rows() -> None:
    """15017313은 공원경계 3 km 버퍼다(원본 메타 `Buffer "3 Kilometers"`, 북한산 240.7 km² vs 76.9).

    싣지 않고, 돌리면 빈 snapshot으로 예전에 실은 버퍼 면을 은퇴시킨다.
    """
    spec = KNPS_GEOMETRY_DATASETS["knps_park_boundaries"]
    assert spec.unloaded_reason is not None
    assert "3 km 버퍼" in spec.unloaded_reason
    assert _geo_one("knps_park_boundaries", _POLY, name="북한산국립공원") == []
    assert "knps_park_boundaries" not in KNPS_LOADABLE_GEOMETRY_DATASET_KEYS
    assert knps_geometry_snapshot_retires_absent(spec)


def test_area_datasets_retire_absent_but_trails_do_not() -> None:
    assert knps_geometry_snapshot_retires_absent(KNPS_GEOMETRY_DATASETS["knps_protected_areas"])
    assert not knps_geometry_snapshot_retires_absent(KNPS_GEOMETRY_DATASETS["knps_trails"])


def _national_park(**over: Any) -> list[FeatureBundle]:
    raw = {
        "WDPAID": "10932.0",
        "WDPA_PID": "10932.0",
        "NAME": "Bukhansan",
        "ORIG_NAME": "북한산",
        "DESIG_ENG": "National Park",
        "MARINE": "0",
    }
    raw.update(over.pop("raw", {}))
    return _geo_one(
        "knps_protected_areas",
        _POLY,
        source_id=over.pop("source_id", "10932"),
        name=over.pop("name", "북한산"),
        raw=raw,
    )


def test_national_park_row_of_protected_areas_becomes_national_park_area() -> None:
    """국립공원 경계의 정본은 한국보호지역의 `National Park` 행이다(버퍼가 아닌 실제 경계)."""
    b = _national_park()[0]
    assert b.feature.kind is FeatureKind.AREA
    assert b.feature.detail.area_kind == "national_park"
    assert b.feature.category == "01020101"
    assert b.feature.name == "북한산 국립공원"
    assert b.feature.marker_icon == "park"
    assert b.feature.detail.payload == {"knps_dataset": "knps_protected_areas"}
    assert b.source_record.dataset_key == "knps_protected_areas"
    assert b.feature.provider_natural_key == "10932"


def test_promoted_provincial_park_row_becomes_national_park() -> None:
    """팔공산은 2023-12-31 승격 — 2016 스냅샷엔 `Provincial Park` 행이다."""
    assert KNPS_NATIONAL_PARK_PROMOTIONS == {"555571373": "2023-12-31"}
    b = _national_park(
        source_id="555571373",
        name="팔공산",
        raw={
            "WDPAID": "555571373.0",
            "WDPA_PID": "555571373.0",
            "ORIG_NAME": "팔공산",
            "DESIG_ENG": "Provincial Park",
        },
    )[0]
    assert b.feature.detail.area_kind == "national_park"
    assert b.feature.category == "01020101"
    assert b.feature.name == "팔공산 국립공원"


def test_promotion_also_matches_raw_wdpa_id_under_legacy_row_hash_source_id() -> None:
    """knps-api가 source_id를 행 hash로 주던 시절의 record도 raw WDPA id로 승격을 알아본다."""
    b = _national_park(
        source_id="row:0123456789abcdef",
        raw={"WDPA_PID": "555571373.0", "ORIG_NAME": "팔공산", "DESIG_ENG": "Provincial Park"},
    )[0]
    assert b.feature.detail.area_kind == "national_park"


def test_other_provincial_park_stays_protected_area() -> None:
    b = _protected("Provincial Park", WDPA_PID="555571374.0")[0]
    assert b.feature.detail.area_kind == "protected_area"
    assert b.feature.category == "01020102"


def _national_park_record(source_id: str, name: str) -> _GRec:
    return _GRec(
        source_id=source_id,
        name=name,
        geom_wkt=_POLY,
        raw={"WDPA_PID": f"{source_id}.0", "ORIG_NAME": name, "DESIG_ENG": "National Park"},
    )


def test_national_park_geocodes_first_anchor_with_a_bjd_code() -> None:
    """해상 국립공원은 centroid가 바다라 빈 답이다 — 면 위 후보점에서 첫 법정동을 쓴다.

    대표점(coord)은 그 주소가 나온 점이다(주소·좌표 일치).
    """
    seen: list[Coordinate] = []

    async def reverse(coord: Coordinate) -> Address | None:
        seen.append(coord)
        if len(seen) < 3:  # centroid·전체 representative_point는 바다
            return None
        return Address(bjd_code="4482533000", sigungu_code="44825", sido_code="44")

    bundles = asyncio.run(
        _geometry_async(
            [_national_park_record("4735", "태안해안")],
            dataset_key="knps_protected_areas",
            fetched_at=_FETCHED,
            reverse_geocoder=reverse,
        )
    )
    feature = bundles[0].feature
    assert feature.address.bjd_code == "4482533000"
    assert feature.coord == seen[2]
    assert len(seen) == 3


def test_national_park_centroid_answer_keeps_centroid_and_one_call() -> None:
    calls: list[Coordinate] = []

    async def reverse(coord: Coordinate) -> Address | None:
        calls.append(coord)
        return Address(bjd_code="1130510400", sigungu_code="11305", sido_code="11")

    feature = asyncio.run(
        _geometry_async(
            [_national_park_record("10932", "북한산")],
            dataset_key="knps_protected_areas",
            fetched_at=_FETCHED,
            reverse_geocoder=reverse,
        )
    )[0].feature
    assert len(calls) == 1
    assert feature.coord is not None
    assert float(feature.coord.lon) == pytest.approx(126.95)
    assert float(feature.coord.lat) == pytest.approx(37.65)


def test_protected_area_does_not_walk_anchor_candidates() -> None:
    """일반 보호지역은 centroid 한 번만 묻는다 — 해상 보호구역 134건이 빈 답 가드를 넘지 않게."""
    calls: list[Coordinate] = []

    async def reverse(coord: Coordinate) -> Address | None:
        calls.append(coord)
        return None

    rec = _GRec(
        source_id="1",
        name="가상 보호지역",
        geom_wkt=_POLY,
        raw={"WDPAID": "1", "DESIG_ENG": "Provincial Park", "MARINE": "0"},
    )
    asyncio.run(
        _geometry_async(
            [rec],
            dataset_key="knps_protected_areas",
            fetched_at=_FETCHED,
            reverse_geocoder=reverse,
        )
    )
    assert len(calls) == 1


def test_self_intersecting_protected_area_is_repaired_before_storage() -> None:
    """prod 한국보호지역 14건이 `Ring Self-intersection`이었다 — 저장 전에 valid로 고친다."""
    from shapely import wkt as shapely_wkt

    bowtie = "POLYGON((126.9 37.6, 127.0 37.7, 127.0 37.6, 126.9 37.7, 126.9 37.6))"
    repaired = _geo_one(
        "knps_protected_areas",
        bowtie,
        name="가상 보호지역",
        raw={"WDPAID": "1", "DESIG_ENG": "Provincial Park", "MARINE": "0"},
    )[0]
    assert repaired.feature.geom is not None
    geom = shapely_wkt.loads(repaired.feature.geom)
    assert geom.is_valid
    assert geom.geom_type == "MultiPolygon"
    assert geom.area == pytest.approx(0.005)


def test_protected_area_translates_raw_english_name() -> None:
    b = _geo_one(
        "knps_protected_areas",
        _POLY,
        name=None,
        raw={"NAME": "Jeju Island", "MNUM": "PROTECTED-1", "DESIG_ENG": "Provincial Park"},
    )[0]
    assert b.feature.kind is FeatureKind.AREA
    assert b.feature.name == "제주도"
    assert b.source_record.raw_data["NAME"] == "Jeju Island"


def test_protected_area_prefers_recoverable_raw_korean_name() -> None:
    b = _geo_one(
        "knps_protected_areas",
        _POLY,
        name="Bongpyeong",
        raw={
            "ORIG_NAME": "遊됲룊",
            "NAME": "Bongpyeong",
            "MNUM": "PROTECTED-1",
            "DESIG_ENG": "Provincial Park",
        },
    )[0]
    assert b.feature.name == "봉평"
    assert b.source_record.raw_data["NAME"] == "Bongpyeong"


def test_protected_area_ignores_lossy_mojibake_korean_name() -> None:
    b = _geo_one(
        "knps_protected_areas",
        _POLY,
        name="Jeonbuk Jeongeup Shinseongdong",
        raw={
            "ORIG_NAME": "�쟾遺� �젙�쓭�떆 �떊�젙�룞",
            "NAME": "Jeonbuk Jeongeup Shinseongdong",
            "MNUM": "PROTECTED-1",
            # 이름 해석 검사다 — 지정 종류는 적재 대상으로 둔다(#1450 allowlist).
            "DESIG_ENG": "Provincial Park",
        },
    )[0]
    assert b.feature.name == "전북 정읍 신성동 야생동물보호구역"


def test_protected_area_ignores_unrecoverable_cjk_mojibake_name() -> None:
    b = _geo_one(
        "knps_protected_areas",
        _POLY,
        name="Cheokchi",
        raw={
            "ORIG_NAME": "泥숈튂",
            "NAME": "Cheokchi",
            "MNUM": "PROTECTED-1",
            "DESIG_ENG": "Provincial Park",
        },
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
            "DESIG_ENG": "Provincial Park",
        },
    )[0]
    assert b.feature.name == "제주 화산섬과 용암동굴"


def test_protected_area_translation_table_has_no_latin_letters() -> None:
    assert len(KNPS_PROTECTED_AREA_KOREAN_NAMES) == 1431
    assert all(
        re.search(r"[A-Za-z]", translated_name) is None
        for translated_name in KNPS_PROTECTED_AREA_KOREAN_NAMES.values()
    )


def test_geometry_raw_payload_is_verbatim_not_normalized() -> None:
    # raw payload는 normalized Feature.name과 별개로 provider 값을 원형 보존한다.
    # (a) record.name이 있으면 raw mapping 자체는 변경하지 않는다.
    trail = _geo_one("knps_trails", _LINE, name="  북한산 둘레길  ")[0]
    assert trail.feature.name == "북한산 둘레길"  # normalized
    assert trail.source_record.raw_data == {"NO": "G-001"}
    # (b) 이름을 raw column에서 복구해도 원 mapping을 그대로 둔다.
    park = _national_park(name="   ")[0]
    assert park.feature.name == "북한산 국립공원"  # 합성된 normalized
    assert park.source_record.raw_data["ORIG_NAME"] == "북한산"


def test_hazard_zones_are_left_unloaded() -> None:
    """원천 83행이 전부 POINT다(#1450). area로 싣지 않고, 지정 기간 없는 2018 스냅샷이라
    notice도 아니며, 가는 곳이 아니라 place도 아니다 — 싣지 않는다."""
    assert KNPS_GEOMETRY_DATASETS["knps_hazard_zones"].unloaded_reason
    assert _geo_one("knps_hazard_zones", _POLY) == []
    assert _geo_one("knps_hazard_zones", "POINT(127.64 35.32)") == []
    assert "knps_hazard_zones" not in KNPS_LOADABLE_GEOMETRY_DATASET_KEYS
    assert "knps_protected_areas" in KNPS_LOADABLE_GEOMETRY_DATASET_KEYS


def _protected(desig_eng: str | None, *, marine: str = "0", **raw: Any):
    return _geo_one(
        "knps_protected_areas",
        _POLY,
        name="가상 보호지역",
        raw={"WDPAID": "1", "DESIG_ENG": desig_eng, "MARINE": marine, **raw},
    )


@pytest.mark.parametrize(
    ("desig_eng", "marine", "category"),
    [
        ("Provincial Park", "0", "01020102"),
        ("County Park", "1", "01020102"),
        ("Scenic Site", "0", "01070300"),
        ("Natural Monument", "2", "01020400"),
        ("Wetland Protected Area", "0", "01020200"),
        ("Wetland Protected Area - Tidal Flat", "2", "01020300"),
        ("Ramsar Site, Wetland of International Importance", "0", "01020200"),
        ("Ramsar Site, Wetland of International Importance", "1", "01020300"),
        ("Ecosystem and Landscape Conservation Area", "0", "01020000"),
        ("  scenic site ", "0", "01070300"),
    ],
)
def test_protected_area_keeps_travel_designations_with_real_category(
    desig_eng: str, marine: str, category: str
) -> None:
    bundles = _protected(desig_eng, marine=marine)
    assert len(bundles) == 1
    feature = bundles[0].feature
    assert feature.kind is FeatureKind.AREA
    assert feature.detail.area_kind == "protected_area"
    assert feature.category == category
    assert feature.category != "00000000"
    assert feature.marker_icon == "park"


@pytest.mark.parametrize(
    "desig_eng",
    [
        "Wildlife Protection Area",
        "Water Source Protection Area",
        "Special Island",
        "Forest Genetic Resources Reserve",
        "MARINE Protected Area",
        "Urban Natural Park Areas",
        None,
        "",
    ],
)
def test_protected_area_drops_non_travel_designations(desig_eng: str | None) -> None:
    assert _protected(desig_eng) == []


def test_protected_area_designation_table_uses_known_categories() -> None:
    for categories in KNPS_PROTECTED_AREA_DESIGNATION_CATEGORIES.values():
        for code in categories:
            assert is_known_category_code(code), code


def test_protected_area_reverse_geocode_failure_drops_row_not_run() -> None:
    """바다 한가운데 centroid는 역지오코딩이 법정동을 못 준다 — 그 행만 버린다(#1450)."""
    assert KNPS_GEOMETRY_DATASETS["knps_protected_areas"].address_failure_mode == "drop"
    assert KNPS_GEOMETRY_DATASETS["knps_park_boundaries"].address_failure_mode == "strict"


def test_invalid_wkt_is_skipped() -> None:
    assert _geo_one("knps_trails", "NOT WKT") == []


def test_wrong_geometry_type_is_skipped() -> None:
    # trails(route)에 polygon → 허용 type 위반 → skip.
    assert _geo_one("knps_trails", _POLY) == []
    # protected_areas(area)에 linestring → skip.
    assert _geo_one(
        "knps_protected_areas", _LINE, raw={"WDPAID": "1", "DESIG_ENG": "Provincial Park"}
    ) == []


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


def test_unmatched_trail_course_is_skipped() -> None:
    # live KNPS trails의 "비매칭코스"(영문 Nonmatching Course)는 공식 코스명이
    # 아니라 코스 매칭 실패 placeholder다. 하나의 거대 route로 적재하지 않는다.
    assert (
        _geo_one(
            "knps_trails",
            _LINE,
            source_id="15000000000",
            name="비매칭코스",
            raw={
                "국립공원관리번호": "15000000000",
                "코스ID": "0",
                "탐방코스(한글)": "비매칭코스",
                "탐방코스(영문)": "Nonmatching Course",
            },
        )
        == []
    )

    recs = [
        _GRec(
            source_id="G-unmatched",
            name="Nonmatching Course",
            geom_wkt=_LINE,
            raw={"탐방코스(영문)": "Nonmatching Course"},
        ),
        _GRec(source_id="G-valid", name="북한산 둘레길", geom_wkt=_LINE, raw={}),
    ]
    bundles = knps_geometry_records_to_bundles(
        recs, dataset_key="knps_trails", fetched_at=_FETCHED
    )
    assert [b.feature.name for b in bundles] == ["북한산 둘레길"]


def test_unmatched_trail_course_variant_is_skipped() -> None:
    assert (
        _geo_one(
            "knps_trails",
            _LINE,
            source_id="G-unmatched-variant",
            name="북한산 둘레길",
            raw={
                "COURSE_NM": "비매칭 코스",
                "MATCH_YN": "N",
            },
        )
        == []
    )

    bundles = knps_geometry_records_to_bundles(
        [
            _GRec(
                source_id="G-valid",
                name="북한산 둘레길",
                geom_wkt=_LINE,
                raw={"비고": "비매칭 후보 검토 메모"},
            )
        ],
        dataset_key="knps_trails",
        fetched_at=_FETCHED,
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
    row: dict[str, str | None] = {
        "ID": "p1",
        "NM": "북한산",
        "SHAPE": "POLYGON((126.9 37.6,127 37.6,127 37.7,126.9 37.7,126.9 37.6))",
    }
    prev = _preview(row)
    # 공원경계(3 km 버퍼)는 싣지 않는다 — column_map이 맞아도 빈 결과다.
    assert (
        knps_csv_preview_to_geometry_bundles(
            prev, dataset_key="knps_park_boundaries", fetched_at=_FETCHED, column_map=cm
        )
        == []
    )
    b = knps_csv_preview_to_geometry_bundles(
        _preview({**row, "DESIG_ENG": "National Park"}),
        dataset_key="knps_protected_areas",
        fetched_at=_FETCHED,
        column_map=cm,
    )[0]
    assert b.feature.kind is FeatureKind.AREA
    assert b.feature.category == "01020101"


def test_csv_preview_geometry_unsupported_key_raises() -> None:
    with pytest.raises(KeyError, match="route/area geometry dataset 아님"):
        knps_csv_preview_to_geometry_bundles(
            _preview(), dataset_key="knps_restrooms", fetched_at=_FETCHED
        )
