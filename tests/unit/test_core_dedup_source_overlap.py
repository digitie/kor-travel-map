"""#1468 원천 겹침 규칙 — 반경 blocking·이름 일치 판정·선형 겹침 후보(``core.dedup``)."""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from decimal import Decimal

import pytest

from kortravelmap.core.dedup import (
    DedupPoint,
    find_dedup_candidates,
    route_overlap_candidate,
)
from kortravelmap.core.scoring import DedupDecision, haversine_meters
from kortravelmap.dto.coordinate import Coordinate

pytestmark = pytest.mark.unit

_CAMP = "03060000"
_FOREST = "03030000"
_ARBORETUM = "01030000"
_BASE_LAT = 37.5
_BASE_LON = 127.0


@dataclass(frozen=True)
class _Stub:
    feature_id: str
    name: str
    coord: Coordinate | None
    category: str
    kind: str = "place"
    detail: object = None


def _at(north_m: float, east_m: float = 0.0) -> Coordinate:
    """기준점에서 북쪽·동쪽으로 미터만큼 떨어진 좌표."""
    lat = _BASE_LAT + north_m / 111_320.0
    lon = _BASE_LON + east_m / (111_320.0 * math.cos(math.radians(_BASE_LAT)))
    return Coordinate(lon=Decimal(f"{lon:.7f}"), lat=Decimal(f"{lat:.7f}"))


# ── 반경 blocking ────────────────────────────────────────────────────────────


def test_same_category_same_name_far_apart_is_cut_by_radius() -> None:
    # 같은 범주·같은 이름이면 거리와 무관하게 0.45 + 0.20 = 0.65가 된다 — 전국 동명 캠핑장이
    # 모두 쌍이 되던 이유. 반경을 주면 그 쌍은 끊긴다.
    left = [_Stub("mois", "솔밭캠핑장", _at(0), _CAMP)]
    right = [_Stub("mcst", "솔밭캠핑장", _at(500), _CAMP)]
    assert len(find_dedup_candidates(left, right)) == 1  # 반경 없는 기존 동작
    assert find_dedup_candidates(left, right, max_distance_m=300) == []


def test_radius_keeps_pairs_inside_and_matches_unblocked_result() -> None:
    left = [_Stub("mois", "하소담캠핑장", _at(0), _CAMP)]
    right = [_Stub("mcst", "하소담캠핑장", _at(23), _CAMP)]
    blocked = find_dedup_candidates(left, right, max_distance_m=300)
    assert blocked == find_dedup_candidates(left, right)
    assert [c.feature_id_b for c in blocked] == ["mcst"]


def test_grid_blocking_equals_brute_force_within_radius() -> None:
    # 격자 3×3 이웃 칸 조회가 반경 안 쌍을 하나도 빠뜨리지 않는다(칸 경계·고위도 쪽 포함).
    rng = random.Random(1468)
    radius = 250.0

    def _rand(prefix: str, i: int) -> _Stub:
        return _Stub(
            f"{prefix}{i}", "같은캠핑장", _at(rng.uniform(-900, 900), rng.uniform(-900, 900)), _CAMP
        )

    left = [_rand("l", i) for i in range(60)]
    right = [_rand("r", i) for i in range(60)]
    got = {
        (c.feature_id_a, c.feature_id_b)
        for c in find_dedup_candidates(left, right, max_distance_m=radius)
    }
    expected = {
        (a.feature_id, b.feature_id)
        for a in left
        for b in right
        if a.coord is not None
        and b.coord is not None
        and haversine_meters(a.coord, b.coord) <= radius
    }
    assert expected  # 시드가 반경 안 쌍을 실제로 만든다
    assert got == expected


def test_radius_skips_features_without_coord() -> None:
    left = [_Stub("a", "같은곳", None, _CAMP)]
    right = [_Stub("b", "같은곳", None, _CAMP)]
    assert find_dedup_candidates(left, right, max_distance_m=300) == []


@pytest.mark.parametrize("radius", [0, -1.0])
def test_radius_must_be_positive(radius: float) -> None:
    with pytest.raises(ValueError, match="max_distance_m"):
        find_dedup_candidates([], [], max_distance_m=radius)


# ── 이름 일치 판정 ───────────────────────────────────────────────────────────


def test_same_name_mode_lifts_pair_below_score_threshold() -> None:
    # 같은 이름의 휴양림·수목원 — 범주가 달라 점수 상한 0.80이고, 28 m 밖이면 0.65 미만이다.
    forest = [_Stub("forest", "옥화자연휴양림", _at(0), _FOREST)]
    arboretum = [_Stub("arbo", "옥화 자연휴양림", _at(400), _ARBORETUM)]
    assert find_dedup_candidates(forest, arboretum, max_distance_m=1000) == []
    [cand] = find_dedup_candidates(forest, arboretum, max_distance_m=1000, match="same_name")
    assert cand.decision == DedupDecision.MANUAL_REVIEW
    assert cand.score < 0.65
    assert cand.reason == "manual_review:same_name"


def test_same_name_mode_rejects_similar_but_different_names() -> None:
    # 같은 단지의 휴양림과 수목원은 다른 시설이다 — 점수가 넘어도 이름이 다르면 올리지 않는다.
    forest = [_Stub("forest", "옥화자연휴양림", _at(0), _FOREST)]
    arboretum = [_Stub("arbo", "옥화자연휴양림 수목원", _at(0), _ARBORETUM)]
    assert find_dedup_candidates(forest, arboretum, max_distance_m=1000) != []
    assert (
        find_dedup_candidates(forest, arboretum, max_distance_m=1000, match="same_name") == []
    )


def test_score_or_same_name_keeps_both_kinds() -> None:
    left = [_Stub("knps", "백무동야영장", _at(0), "03060100")]
    right = [
        _Stub("near_scored", "백무동 자동차야영장", _at(5), _CAMP),
        _Stub("same_far", "백무동야영장", _at(200), _CAMP),
        _Stub("other", "뱀사골야영장", _at(200), _CAMP),
    ]
    got = {
        c.feature_id_b: c
        for c in find_dedup_candidates(
            left, right, max_distance_m=300, match="score_or_same_name"
        )
    }
    assert set(got) == {"near_scored", "same_far"}
    assert got["near_scored"].reason is None  # 점수로 올라온 쌍은 판정 그대로
    assert got["same_far"].reason == "manual_review:same_name"


def test_name_match_modes_require_radius() -> None:
    with pytest.raises(ValueError, match="max_distance_m"):
        find_dedup_candidates([], [], match="same_name")


def test_unknown_match_mode_rejected() -> None:
    with pytest.raises(ValueError, match="match"):
        find_dedup_candidates([], [], max_distance_m=100, match="fuzzy")  # type: ignore[arg-type]


# ── 선형 겹침 후보 ───────────────────────────────────────────────────────────


def test_route_overlap_candidate_is_manual_review_with_ratio_reason() -> None:
    mountain = DedupPoint("trail", "설악산 1구간", _at(0), "01080500", "route")
    knps = DedupPoint("knps", "설악동~비선대", _at(30), "01020103", "route")
    cand = route_overlap_candidate(mountain, knps, overlap_ratio=0.873)
    assert cand.decision == DedupDecision.MANUAL_REVIEW
    assert cand.reason == "manual_review:route_overlap=0.87"
    assert (cand.feature_id_a, cand.feature_id_b) == ("trail", "knps")
    # total은 점 후보와 같은 식이다 — F7 회귀 감시가 같은 식으로 다시 계산한다.
    assert 0.0 <= cand.score <= 1.0
    assert cand.category_score == 0.0


@pytest.mark.parametrize("ratio", [-0.1, 1.1])
def test_route_overlap_ratio_bounds(ratio: float) -> None:
    point = DedupPoint("a", "x", None, "01080500", "route")
    with pytest.raises(ValueError, match="overlap_ratio"):
        route_overlap_candidate(point, point, overlap_ratio=ratio)
