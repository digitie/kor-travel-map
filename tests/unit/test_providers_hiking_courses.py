"""산림청 등산로·KNPS 탐방로 구간 → 등산 코스 route (ADR-128)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import pytest

from kortravelmap.dto import Address, Coordinate, FeatureKind, RouteDetail
from kortravelmap.providers.knps import (
    KNPS_TRAIL_COURSE_ENTITY_TYPE,
    knps_trail_courses_to_bundles,
)
from kortravelmap.providers.krforest import (
    DATASET_KEY_MOUNTAIN_TRAILS,
    MOUNTAIN_TRAIL_COURSE_ENTITY_TYPE,
    forest_trails_to_bundles,
    mountain_trail_courses_to_bundles,
)

KST = timezone(timedelta(hours=9))
_NOW = datetime(2026, 11, 27, 12, 0, tzinfo=KST)


@dataclass(frozen=True)
class _Trail:
    name: str | None
    source_id: str | None
    source_file: str | None
    layer_name: str | None
    geometry_type: str | None
    geometry: dict[str, Any] | None
    bbox: tuple[float, float, float, float] | None
    raw: Any = field(default_factory=dict)


def _forest(
    serial: int,
    coords: list[tuple[float, float]],
    *,
    segment_name: str | None = "부암동구간",
    length_km: float = 0.88,
    ascent: Any = 16,
    descent: Any = 11,
    difficulty: str | None = "쉬움",
    mountain: tuple[str, str] = ("111100101", "북악산"),
) -> _Trail:
    raw: dict[str, Any] = {
        "MNTN_CODE": mountain[0],
        "MNTN_NM": mountain[1],
        "PMNTN_SN": serial,
        "PMNTN_LT": length_km,
        "PMNTN_UPPL": ascent,
        "PMNTN_GODN": descent,
        "DATA_STDR_": "2016-12-31",
    }
    if segment_name is not None:
        raw["PMNTN_NM"] = segment_name
    if difficulty is not None:
        raw["PMNTN_DFFL"] = difficulty
    xs = [c[0] for c in coords]
    ys = [c[1] for c in coords]
    return _Trail(
        name=f"{mountain[1]} {segment_name}" if segment_name else mountain[1],
        source_id=f"mountain/x.zip/PMNTN_{mountain[1]}.shp:keys:{serial}",
        source_file="mountain/x.zip/PMNTN.shp",
        layer_name="PMNTN",
        geometry_type="LineString",
        geometry={"type": "LineString", "coordinates": [list(c) for c in coords]},
        bbox=(min(xs), min(ys), max(xs), max(ys)),
        raw=raw,
    )


# 서→동으로 이어지는 두 구간(정상부는 동쪽 다른 노선 쪽) + 같은 산 다른 노선 하나.
_W1 = _forest(1, [(127.000, 37.5), (127.010, 37.5)], difficulty="쉬움", ascent=16)
_W2 = _forest(2, [(127.010, 37.5), (127.020, 37.5)], difficulty="중간", ascent="20.0")
_SUMMIT = _forest(
    3, [(127.020, 37.5), (127.040, 37.5), (127.060, 37.5)], segment_name="정상구간", ascent=30,
    length_km=3.53,
)
_ISOLATED = _forest(4, [(127.500, 37.7), (127.510, 37.7)], ascent=12)


def _courses(items: list[_Trail], **kwargs: Any) -> list[Any]:
    return asyncio.run(mountain_trail_courses_to_bundles(items, fetched_at=_NOW, **kwargs))


@pytest.mark.unit
def test_mountain_trail_segments_become_named_courses_with_source_fields() -> None:
    bundles = _courses([_SUMMIT, _W2, _W1, _ISOLATED])
    by_name = {bundle.feature.name: bundle for bundle in bundles}
    # 같은 노선명(부암동구간)이 서로 떨어진 두 성분이면 이름 뒤에 순번이 붙는다.
    assert sorted(by_name) == ["북악산 부암동구간 1", "북악산 부암동구간 2", "북악산 정상구간"]

    course = by_name["북악산 부암동구간 1"]
    detail = course.feature.detail
    assert isinstance(detail, RouteDetail)
    assert course.feature.kind == FeatureKind.ROUTE
    assert detail.route_type == "hiking_course"
    assert detail.geometry_status == "assembled"
    # 원천 상행시간 합(16 + "20.0"), 가장 어려운 구간 등급.
    assert detail.expected_duration_minutes == 36
    assert detail.difficulty == "moderate"
    assert detail.payload["duration_basis"] == "source"
    assert detail.payload["descent_minutes"] == 22
    assert detail.payload["source_distance_m"] == pytest.approx(1760.0)
    assert detail.payload["segment_count"] == 2
    assert detail.payload["difficulty_breakdown_m"]["moderate"] == pytest.approx(880.0)
    assert detail.total_distance_meters is not None
    assert Decimal("1700") < detail.total_distance_meters < Decimal("1800")
    # 출발점 = 산 구간망 중심에서 가장 먼 말단(서쪽 끝) = Feature.coord.
    assert course.feature.coord is not None
    assert float(course.feature.coord.lon) == pytest.approx(127.000)
    assert course.feature.geom is not None
    assert course.feature.geom.startswith("LINESTRING (127 ")
    assert course.source_record.source_entity_type == MOUNTAIN_TRAIL_COURSE_ENTITY_TYPE
    assert course.source_record.dataset_key == DATASET_KEY_MOUNTAIN_TRAILS
    assert [seg["PMNTN_SN"] for seg in course.source_record.raw_data["segments"]] == [1, 2]


@pytest.mark.unit
def test_missing_source_duration_falls_back_to_labelled_estimate() -> None:
    no_time = _forest(1, [(127.000, 37.5), (127.010, 37.5)], ascent=None)
    (bundle,) = _courses([no_time])
    detail = bundle.feature.detail
    assert isinstance(detail, RouteDetail)
    assert detail.payload["duration_basis"] == "estimated"
    # 880 m × 18분/km ≈ 15.9 → 16분
    assert detail.expected_duration_minutes == 16


@pytest.mark.unit
def test_course_identity_is_deterministic_and_ignores_geocoder() -> None:
    async def _rg(coord: Coordinate) -> Address | None:
        return Address(bjd_code="1111010100", sigungu_code="11110", sido_code="11")

    first = _courses([_W1, _W2])
    second = _courses([_W2, _W1], reverse_geocoder=_rg)
    assert [b.feature.feature_id for b in first] == [b.feature.feature_id for b in second]
    assert [b.source_record.source_record_key for b in first] == [
        b.source_record.source_record_key for b in second
    ]
    assert second[0].feature.address.bjd_code == "1111010100"


@pytest.mark.unit
def test_mountain_trail_segment_route_carries_source_fields() -> None:
    (bundle,) = asyncio.run(
        forest_trails_to_bundles(
            [_W2], dataset_key=DATASET_KEY_MOUNTAIN_TRAILS, fetched_at=_NOW
        )
    )
    detail = bundle.feature.detail
    assert isinstance(detail, RouteDetail)
    assert detail.total_distance_meters == Decimal("880.0")
    assert detail.expected_duration_minutes == 20
    assert detail.difficulty == "moderate"
    assert detail.payload["descent_minutes"] == 11


@dataclass(frozen=True)
class _KnpsRecord:
    source_id: str
    name: str | None
    geom_wkt: str
    raw: dict[str, Any]


def _knps(
    serial: int, start: str, end: str, wkt: str, *, distance: str, go: str, course: str
) -> _KnpsRecord:
    return _KnpsRecord(
        source_id=f"knps:{serial}",
        name=course,
        geom_wkt=wkt,
        raw={
            "공원사무소코드": "101",
            "탐방코스(한글)": course,
            "일련번호": str(serial),
            "시작점_ID": start,
            "종점_ID": end,
            "지리정보시스템 상 거리(m)": distance,
            "가는시간(분)": go,
            "오는시간(분)": go,
            "난이도": "2.15",
            "탐방로 통제여부": "0",
            "상세구간": "",
        },
    )


@pytest.mark.unit
def test_knps_course_follows_source_node_graph_and_names() -> None:
    course = "노고단고개 ~ 천왕봉"
    records = [
        # 원천 순번이 작은 구간이 코스 한가운데(동쪽)에 있어도 출발은 노드 그래프의 시작이다.
        _knps(12, "2", "3", "LINESTRING (127.02 35.3, 127.03 35.3)", distance="906", go="30",
              course=course),
        _knps(113, "1", "2", "LINESTRING (127.00 35.3, 127.02 35.3)", distance="1815", go="60",
              course=course),
        # 지선 토막(약 9 m)은 출발 후보지만 조립에서 떨어진다.
        _knps(80, "9", "2", "LINESTRING (127.0200 35.3001, 127.02 35.3)", distance="11",
              go="1", course=course),
        # 원천 거리와 모순되는 지그재그 선 — 선에서 빠지고 계보에 표시된다.
        _knps(1, "7", "8", "LINESTRING (127.5 35.3, 127.9 35.3)", distance="400", go="10",
              course=course),
    ]
    (bundle,) = asyncio.run(knps_trail_courses_to_bundles(records, fetched_at=_NOW))
    detail = bundle.feature.detail
    assert isinstance(detail, RouteDetail)
    assert bundle.feature.name == course
    assert detail.route_type == "hiking_course"
    assert detail.begin_name == "노고단고개"
    assert detail.end_name == "천왕봉"
    assert bundle.feature.coord is not None
    assert float(bundle.feature.coord.lon) == pytest.approx(127.00)
    assert detail.payload["excluded_segment_ids"] == ["knps:1"]
    assert detail.expected_duration_minutes == 91  # 30 + 60 + 1 (모순 구간 10분 제외)
    assert detail.difficulty is None  # 원천 척도 미상 — 원값만 보존
    assert detail.payload["source_difficulty_max"] == pytest.approx(2.15)
    assert bundle.source_record.source_entity_type == KNPS_TRAIL_COURSE_ENTITY_TYPE
    assert bundle.source_record.source_entity_id == f"course::101::{course}"


@pytest.mark.unit
def test_course_address_falls_back_to_line_when_start_has_no_legal_dong() -> None:
    calls: list[tuple[float, float]] = []

    async def _rg(coord: Coordinate) -> Address | None:
        calls.append((float(coord.lon), float(coord.lat)))
        if (float(coord.lon), float(coord.lat)) == (127.0, 37.5):
            return Address()  # 들머리가 경계 밖 — 법정동 없음
        return Address(bjd_code="1111010100", sigungu_code="11110", sido_code="11")

    # 동쪽 정상구간이 산 구간망 중심을 동쪽으로 당긴다 → 부암동구간의 출발은 서쪽 끝.
    bundle = next(
        b for b in _courses([_W1, _SUMMIT], reverse_geocoder=_rg) if "부암동" in b.feature.name
    )
    assert calls[0] == pytest.approx((127.000, 37.5))
    assert bundle.feature.address.bjd_code == "1111010100"
    # 좌표는 그대로 출발점이다 — 주소만 선 위 대표점에서 얻는다.
    assert bundle.feature.coord is not None
    assert float(bundle.feature.coord.lon) == pytest.approx(127.000)


@pytest.mark.unit
def test_knps_names_are_dropped_when_start_is_not_source_anchored() -> None:
    course = "백운대 ~ 우이동"
    # 들어오는 구간이 없는 노드가 없다(원형으로 이어진 노드 id) — 출발을 원천 근거로 못 정한다.
    records = [
        _knps(1, "1", "2", "LINESTRING (127.00 37.6, 127.01 37.6)", distance="880", go="20",
              course=course),
        _knps(2, "2", "1", "LINESTRING (127.01 37.6, 127.02 37.6)", distance="880", go="20",
              course=course),
    ]
    (bundle,) = asyncio.run(knps_trail_courses_to_bundles(records, fetched_at=_NOW))
    detail = bundle.feature.detail
    assert isinstance(detail, RouteDetail)
    assert detail.begin_name is None
    assert detail.end_name is None
