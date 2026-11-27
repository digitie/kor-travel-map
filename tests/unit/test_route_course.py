"""``core.route_course`` — 원천 구간을 방향 있는 등산 코스로 조립 (ADR-128)."""

from __future__ import annotations

import pytest
from shapely import wkt

from kortravelmap.core.route_course import (
    CourseSegmentGeometry,
    assemble_course,
    connected_segment_groups,
    geometry_contradicts_source,
)


def _seg(
    segment_id: str, serial: int, text: str, length: float | None = None
) -> CourseSegmentGeometry:
    return CourseSegmentGeometry(
        segment_id=segment_id, order_key=(serial, segment_id), wkt=text, source_length_m=length
    )


# 127.00 → 127.02 동쪽으로 이어지는 세 구간. 가운데 구간은 거꾸로 디지타이징됐고, 이음매에
# 약 5 m(0.00005도) 틈이 있다.
_A = _seg("a", 1, "LINESTRING (127.000 37.5, 127.010 37.5)")
_B = _seg("b", 2, "LINESTRING (127.020 37.5, 127.01005 37.5)")
_C = _seg("c", 3, "LINESTRING (127.020 37.5, 127.030 37.5)")
_FAR = _seg("far", 4, "LINESTRING (127.200 37.6, 127.210 37.6)")


@pytest.mark.unit
def test_groups_touching_segments_within_tolerance() -> None:
    groups = connected_segment_groups([_FAR, _C, _A, _B])
    assert [[segment.segment_id for segment in group] for group in groups] == [
        ["a", "b", "c"],
        ["far"],
    ]


@pytest.mark.unit
def test_assembles_reversed_and_gapped_segments_into_one_path() -> None:
    course = assemble_course([_C, _B, _A])
    assert course is not None
    assert course.shape == "path"
    assert course.part_count == 1
    # 출발 힌트가 없으면 가장 작은 원천 순번 구간(a)의 첫 점 쪽에서 출발한다.
    assert course.start == pytest.approx((127.000, 37.5))
    assert course.end == pytest.approx((127.030, 37.5))
    assert 2600 < course.length_m < 2700  # 위도 37.5에서 경도 0.03도 ≈ 2.65 km
    line = wkt.loads(course.wkt)
    assert line.geom_type == "LineString"
    assert line.coords[0] == pytest.approx((127.000, 37.5))


@pytest.mark.unit
def test_start_far_from_picks_terminal_away_from_reference() -> None:
    course = assemble_course([_A, _B, _C], start_far_from=(127.000, 37.5))
    assert course is not None
    assert course.start == pytest.approx((127.030, 37.5))
    assert course.end == pytest.approx((127.000, 37.5))


@pytest.mark.unit
def test_start_near_candidates_choose_matching_terminal() -> None:
    # 후보 하나는 어느 말단과도 멀고(지선 끝이었던 점), 다른 하나가 동쪽 끝과 맞는다.
    course = assemble_course([_A, _B, _C], start_near=[(127.5, 37.9), (127.030, 37.5)])
    assert course is not None
    assert course.start == pytest.approx((127.030, 37.5))


@pytest.mark.unit
def test_short_dead_end_spur_is_pruned_but_long_branch_is_kept() -> None:
    spur = _seg("spur", 9, "LINESTRING (127.010 37.5, 127.010 37.5002)")  # ≈ 22 m
    course = assemble_course([_A, _B, _C, spur])
    assert course is not None
    assert course.shape == "path"

    branch = _seg("branch", 9, "LINESTRING (127.010 37.5, 127.010 37.51)")  # ≈ 1.1 km
    network = assemble_course([_A, _B, _C, branch])
    assert network is not None
    assert network.shape == "network"
    assert network.part_count == 2
    # 본선은 출발 말단에서 가장 먼 말단까지 — 서쪽 끝 → 동쪽 끝(2.65 km)이 북쪽 샛길(1.1 km
    # 갈래)보다 멀다.
    assert network.start == pytest.approx((127.000, 37.5))
    assert network.end == pytest.approx((127.030, 37.5))
    assert network.main_length_m < network.length_m


@pytest.mark.unit
def test_loop_starts_at_vertex_nearest_hint() -> None:
    ring = _seg("ring", 1, "LINESTRING (127 37.5, 127.01 37.5, 127.01 37.51, 127 37.51, 127 37.5)")
    course = assemble_course([ring], start_near=[(127.01, 37.51)])
    assert course is not None
    assert course.shape == "loop"
    assert course.start == pytest.approx((127.01, 37.51))
    assert course.end == course.start


@pytest.mark.unit
def test_segment_contradicting_source_length_is_excluded() -> None:
    # 원천 거리 100 m인데 geometry는 약 8.8 km — KNPS 원천의 지그재그 선 결함.
    junk = _seg("junk", 0, "LINESTRING (127.0 37.5, 127.1 37.5)", length=100.0)
    course = assemble_course([junk, _A, _B, _C])
    assert course is not None
    assert course.excluded_segment_ids == ("junk",)
    assert course.length_m < 3000
    assert assemble_course([junk]) is None


@pytest.mark.unit
def test_geometry_contradicts_source_thresholds() -> None:
    assert not geometry_contradicts_source(1200.0, None)
    assert not geometry_contradicts_source(250.0, 50.0)  # 5배지만 +500 m 안
    assert geometry_contradicts_source(2000.0, 100.0)
    assert not geometry_contradicts_source(2900.0, 1000.0)


@pytest.mark.unit
def test_assembly_is_deterministic_under_input_order() -> None:
    first = assemble_course([_A, _B, _C])
    second = assemble_course([_C, _A, _B])
    assert first == second


@pytest.mark.unit
def test_t_junction_gap_is_joined_into_the_main_line() -> None:
    # 샛길 끝이 본선 한가운데 약 4 m 앞에서 멈췄다(적대 리뷰 재현 사례).
    main = _seg("main", 1, "LINESTRING (127.00 37.0, 127.02 37.0)")
    branch = _seg("branch", 2, "LINESTRING (127.01 37.00004, 127.01 37.03)")
    course = assemble_course([main, branch], start_near=[(127.00, 37.0)])
    assert course is not None
    assert course.shape == "network"
    assert course.start == pytest.approx((127.00, 37.0))
    # 본선은 출발점에서 망을 따라 가장 먼 말단(샛길 끝 북쪽 3 km)까지 이어진다.
    assert course.end == pytest.approx((127.01, 37.03))
    assert course.main_length_m > 3_000
    assert course.start_matches_hint is True


@pytest.mark.unit
def test_ranked_hint_beats_a_longer_branch_end_candidate() -> None:
    main = _seg("main", 1, "LINESTRING (127.00 37.0, 127.01 37.0, 127.03 37.0)")
    branch = _seg("branch", 2, "LINESTRING (126.995 37.01, 127.01 37.0)")
    # 1순위 후보가 서쪽 끝, 2순위가 샛길 끝 — 경도 사전순이 아니라 순위가 이긴다.
    course = assemble_course([main, branch], start_near=[(127.00, 37.0), (126.995, 37.01)])
    assert course is not None
    assert course.start == pytest.approx((127.00, 37.0))
    flipped = assemble_course([main, branch], start_near=[(126.995, 37.01), (127.00, 37.0)])
    assert flipped is not None
    assert flipped.start == pytest.approx((126.995, 37.01))


@pytest.mark.unit
def test_unmatched_hint_is_reported() -> None:
    course = assemble_course([_A, _B, _C], start_near=[(127.5, 37.9)])
    assert course is not None
    assert course.start_matches_hint is False
    assert assemble_course([_A, _B, _C]).start_matches_hint is None  # type: ignore[union-attr]
