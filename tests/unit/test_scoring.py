"""``test_scoring`` — Record Linkage scoring (ADR-016, PR#29)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from krtour.map.core.scoring import (
    SPATIAL_DECAY_METERS,
    THRESHOLD_AUTO,
    THRESHOLD_MANUAL,
    WEIGHT_CATEGORY,
    WEIGHT_NAME,
    WEIGHT_SPATIAL,
    DedupDecision,
    category_similarity,
    classify_decision,
    haversine_meters,
    name_similarity,
    normalize_kr_place_name,
    score_pair,
    spatial_similarity,
)
from krtour.map.dto import Coordinate

# -- ADR-016 가중치 정합 ----------------------------------------------------


@pytest.mark.unit
def test_weights_sum_to_one() -> None:
    """ADR-016 — 가중치 합은 정확히 1.0."""
    assert abs((WEIGHT_NAME + WEIGHT_SPATIAL + WEIGHT_CATEGORY) - 1.0) < 1e-9


@pytest.mark.unit
def test_thresholds_ordered() -> None:
    """AUTO > MANUAL > 0."""
    assert THRESHOLD_AUTO > THRESHOLD_MANUAL > 0


@pytest.mark.unit
def test_adr_016_values() -> None:
    """ADR-016 SPEC V8 D-14 명세 값 확인 — 변경 시 ADR 동기 필요."""
    assert WEIGHT_NAME == 0.45
    assert WEIGHT_SPATIAL == 0.35
    assert WEIGHT_CATEGORY == 0.20
    assert THRESHOLD_AUTO == 0.85
    assert THRESHOLD_MANUAL == 0.65
    assert SPATIAL_DECAY_METERS == 50.0


# -- normalize_kr_place_name ----------------------------------------------


@pytest.mark.unit
def test_normalize_lowercase() -> None:
    """ASCII는 소문자 + 공백 제거 (한국어 일관)."""
    assert normalize_kr_place_name("Seoul Station") == "seoulstation"


@pytest.mark.unit
def test_normalize_strips_all_whitespace() -> None:
    """한국어 장소명은 공백 변형 흡수 위해 모든 공백 제거."""
    assert normalize_kr_place_name("  서울  시청  ") == "서울시청"
    assert normalize_kr_place_name("서울 특별 시청") == "서울특별시청"


@pytest.mark.unit
def test_normalize_strips_parentheses() -> None:
    """괄호 내용 제거."""
    assert normalize_kr_place_name("서울시청(본관)") == "서울시청"
    assert normalize_kr_place_name("장소[분점]") == "장소"


@pytest.mark.unit
def test_normalize_empty() -> None:
    """빈 문자열은 그대로."""
    assert normalize_kr_place_name("") == ""


# -- name_similarity ------------------------------------------------------


@pytest.mark.unit
def test_name_sim_identical() -> None:
    """같은 이름은 1.0."""
    assert name_similarity("서울시청", "서울시청") == 1.0


@pytest.mark.unit
def test_name_sim_similar_korean() -> None:
    """띄어쓰기 차이는 정규화 후 동일 → 1.0."""
    assert name_similarity("서울 시청", "서울시청") == 1.0


@pytest.mark.unit
def test_name_sim_different() -> None:
    """완전히 다른 이름은 낮은 점수."""
    sim = name_similarity("서울시청", "부산해운대")
    assert 0.0 <= sim <= 0.6  # jaro_winkler는 0이 아닐 수 있음


@pytest.mark.unit
def test_name_sim_empty_returns_zero() -> None:
    """빈 입력은 0.0."""
    assert name_similarity("", "서울시청") == 0.0
    assert name_similarity("서울시청", "") == 0.0


# -- spatial_similarity ---------------------------------------------------


def _coord(lon: str, lat: str) -> Coordinate:
    return Coordinate(lon=Decimal(lon), lat=Decimal(lat))


@pytest.mark.unit
def test_spatial_sim_same_point() -> None:
    """동일 좌표는 1.0."""
    c = _coord("126.97", "37.57")
    assert spatial_similarity(c, c) == 1.0


@pytest.mark.unit
def test_spatial_sim_decays_with_distance() -> None:
    """거리 증가 시 점수 감소 (exp decay)."""
    c1 = _coord("126.97", "37.57")
    c_near = _coord("126.9701", "37.5701")  # ~10m
    c_far = _coord("126.9800", "37.5800")  # ~1km

    sim_near = spatial_similarity(c1, c_near)
    sim_far = spatial_similarity(c1, c_far)
    assert sim_near > sim_far
    # 1km는 사실상 0 (exp(-1000/50) ≈ 2e-9).
    assert sim_far < 0.01


@pytest.mark.unit
def test_spatial_sim_50m_decay_check() -> None:
    """50m에서 sim ≈ 1/e ≈ 0.37 (ADR-016 정의 검증)."""
    c1 = _coord("126.97000", "37.57000")
    # 위도 1° ≈ 111km, 경도 1° ≈ 88km (37.5°N)
    # 50m ≈ 0.00045° (위도)
    c_50m = _coord("126.97000", "37.57045")
    sim = spatial_similarity(c1, c_50m)
    # exp(-1) ≈ 0.368. 위도 변환 오차 감안 ±0.05.
    assert 0.30 < sim < 0.45


@pytest.mark.unit
def test_spatial_sim_none_returns_zero() -> None:
    """None 좌표는 0."""
    c = _coord("126.97", "37.57")
    assert spatial_similarity(None, c) == 0.0
    assert spatial_similarity(c, None) == 0.0
    assert spatial_similarity(None, None) == 0.0


# -- haversine_meters -----------------------------------------------------


@pytest.mark.unit
def test_haversine_seoul_busan() -> None:
    """서울-부산 직선 ≈ 325km (UTM-K 측정과 동일 범위)."""
    seoul = _coord("126.9784", "37.5666")
    busan = _coord("129.0756", "35.1796")
    d_m = haversine_meters(seoul, busan)
    # 320~335km 범위 (test_crs와 동일 기준).
    assert 320_000 < d_m < 335_000


@pytest.mark.unit
def test_haversine_zero_for_same_point() -> None:
    c = _coord("126.97", "37.57")
    assert haversine_meters(c, c) == 0.0


# -- category_similarity --------------------------------------------------


@pytest.mark.unit
def test_category_sim_identical() -> None:
    assert category_similarity({"01020101"}, {"01020101"}) == 1.0


@pytest.mark.unit
def test_category_sim_jaccard() -> None:
    """Jaccard = |A∩B| / |A∪B|."""
    # |∩|=1, |∪|=2 → 0.5
    assert category_similarity({"a", "b"}, {"a"}) == 0.5
    # |∩|=1, |∪|=3 → 1/3
    assert category_similarity({"a", "b"}, {"a", "c"}) == pytest.approx(1 / 3)


@pytest.mark.unit
def test_category_sim_empty_returns_zero() -> None:
    assert category_similarity(set(), {"a"}) == 0.0
    assert category_similarity({"a"}, set()) == 0.0
    assert category_similarity(None, {"a"}) == 0.0


# -- score_pair (종합) ----------------------------------------------------


@pytest.mark.unit
def test_score_pair_identical_is_one() -> None:
    """모든 차원 완전 일치 → 1.0."""
    c = _coord("126.97", "37.57")
    s = score_pair(
        name_a="서울시청", name_b="서울시청",
        coord_a=c, coord_b=c,
        cat_a={"01020101"}, cat_b={"01020101"},
    )
    assert s == 1.0


@pytest.mark.unit
def test_score_pair_completely_different_is_low() -> None:
    """모든 차원 불일치 + 먼 좌표 → 낮은 점수."""
    c1 = _coord("126.97", "37.57")  # 서울
    c2 = _coord("129.08", "35.18")  # 부산
    s = score_pair(
        name_a="서울시청", name_b="부산해운대",
        coord_a=c1, coord_b=c2,
        cat_a={"01020101"}, cat_b={"02020101"},
    )
    assert s < THRESHOLD_MANUAL


@pytest.mark.unit
def test_score_pair_no_coords_only_name_category() -> None:
    """좌표 없으면 name + category로만 계산 (spatial=0)."""
    s = score_pair(
        name_a="서울시청", name_b="서울시청",
        coord_a=None, coord_b=None,
        cat_a={"01020101"}, cat_b={"01020101"},
    )
    # 1.0 * 0.45 + 0 * 0.35 + 1.0 * 0.20 = 0.65
    assert s == pytest.approx(0.65)


# -- classify_decision ----------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    ("score", "expected"),
    [
        (1.00, DedupDecision.AUTO_MERGE),
        (0.85, DedupDecision.AUTO_MERGE),  # 경계는 AUTO
        (0.84, DedupDecision.MANUAL_REVIEW),
        (0.70, DedupDecision.MANUAL_REVIEW),
        (0.65, DedupDecision.MANUAL_REVIEW),  # 경계는 MANUAL
        (0.64, DedupDecision.KEEP_SEPARATE),
        (0.30, DedupDecision.KEEP_SEPARATE),
        (0.00, DedupDecision.KEEP_SEPARATE),
    ],
)
def test_classify_decision_thresholds(score: float, expected: str) -> None:
    assert classify_decision(score) == expected


@pytest.mark.unit
def test_decision_constants_unique() -> None:
    """DedupDecision 3 상수가 서로 다른 값."""
    assert len({
        DedupDecision.AUTO_MERGE,
        DedupDecision.MANUAL_REVIEW,
        DedupDecision.KEEP_SEPARATE,
    }) == 3
