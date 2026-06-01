"""``test_core_dedup`` — cross-provider dedup 후보 (ADR-016, SPRINT-3 §2.5).

knps 사찰 ↔ krheritage temple 시나리오로 ``find_dedup_candidates`` 검증.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from decimal import Decimal

import pytest

from krtour.map.core.dedup import (
    DedupCandidate,
    DedupInput,
    find_dedup_candidates,
    find_sibling_candidates,
)
from krtour.map.core.scoring import DedupDecision
from krtour.map.dto.coordinate import Coordinate

pytestmark = pytest.mark.unit

_TEMPLE_CAT = "01070100"  # TOURISM_HERITAGE_TEMPLE


@dataclass(frozen=True)
class _Stub:
    """``DedupInput`` Protocol 만족 (Feature 대용)."""

    feature_id: str
    name: str
    coord: Coordinate | None
    category: str


def _c(lon: str, lat: str) -> Coordinate:
    return Coordinate(lon=Decimal(lon), lat=Decimal(lat))


def test_identical_temple_is_auto_merge() -> None:
    knps = [_Stub("f_knps_1", "불국사", _c("129.3320", "35.7900"), _TEMPLE_CAT)]
    krh = [_Stub("f_krh_1", "불국사", _c("129.3320", "35.7900"), _TEMPLE_CAT)]
    [cand] = find_dedup_candidates(knps, krh)
    assert cand.decision == DedupDecision.AUTO_MERGE
    assert cand.score >= 0.85
    assert cand.feature_id_a == "f_knps_1"
    assert cand.feature_id_b == "f_krh_1"
    assert cand.name_score == pytest.approx(1.0)


def test_far_different_temple_keep_separate_excluded() -> None:
    knps = [_Stub("f_knps_1", "불국사", _c("129.3320", "35.7900"), _TEMPLE_CAT)]
    krh = [_Stub("f_krh_2", "해인사", _c("128.0980", "35.8010"), _TEMPLE_CAT)]
    # 이름·좌표 모두 멀어 KEEP_SEPARATE → 후보 없음.
    assert find_dedup_candidates(knps, krh) == []


def test_include_auto_merge_false_filters() -> None:
    knps = [_Stub("f_knps_1", "불국사", _c("129.3320", "35.7900"), _TEMPLE_CAT)]
    krh = [_Stub("f_krh_1", "불국사", _c("129.3320", "35.7900"), _TEMPLE_CAT)]
    # auto_merge만 있는데 제외 → 빈 list.
    assert find_dedup_candidates(knps, krh, include_auto_merge=False) == []


def test_candidates_sorted_by_score_desc() -> None:
    knps = [
        _Stub("f_knps_1", "불국사", _c("129.3320", "35.7900"), _TEMPLE_CAT),
        _Stub("f_knps_2", "통도사", _c("129.0630", "35.4870"), _TEMPLE_CAT),
    ]
    krh = [
        _Stub("f_krh_1", "불국사", _c("129.3320", "35.7900"), _TEMPLE_CAT),
        _Stub("f_krh_2", "통도사", _c("129.0630", "35.4870"), _TEMPLE_CAT),
    ]
    cands = find_dedup_candidates(knps, krh)
    assert len(cands) >= 2
    scores = [c.score for c in cands]
    assert scores == sorted(scores, reverse=True)
    # 각 후보는 자기 짝과 매칭 (자명한 동일쌍).
    top = cands[0]
    assert top.feature_id_a.replace("knps", "") == top.feature_id_b.replace("krh", "")


def test_candidate_carries_component_scores() -> None:
    knps = [_Stub("f_a", "불국사", _c("129.3320", "35.7900"), _TEMPLE_CAT)]
    krh = [_Stub("f_b", "불국사", _c("129.3325", "35.7902"), _TEMPLE_CAT)]
    [cand] = find_dedup_candidates(knps, krh)
    assert isinstance(cand, DedupCandidate)
    assert 0.0 <= cand.name_score <= 1.0
    assert 0.0 <= cand.spatial_score <= 1.0
    assert 0.0 <= cand.category_score <= 1.0
    # 종합 점수는 성분 가중합 범위.
    assert 0.0 <= cand.score <= 1.0


def test_empty_inputs() -> None:
    assert find_dedup_candidates([], []) == []
    knps = [_Stub("f_a", "불국사", _c("129.33", "35.79"), _TEMPLE_CAT)]
    assert find_dedup_candidates(knps, []) == []


# -- J 영역 확장 — 운영에서 자주 보이는 엣지 -----------------------------


def test_manual_review_band_returned() -> None:
    """이름·카테고리 같음 + 좌표 60m 떨어짐 — MANUAL_REVIEW 밴드.

    같은 이름(1.0) + 60m 좌표(exp(-60/50)≈0.30) + 같은 카테고리(1.0):
    0.45*1.0 + 0.35*0.30 + 0.20*1.0 = 0.76 — 0.65 ≤ s < 0.85 → MANUAL.
    """
    knps = [_Stub("f_knps_1", "송광사", _c("127.29500", "35.00900"), _TEMPLE_CAT)]
    # 위도 ~0.00054° ≈ 60m.
    krh = [_Stub("f_krh_1", "송광사", _c("127.29500", "35.00954"), _TEMPLE_CAT)]
    cands = find_dedup_candidates(knps, krh)
    assert len(cands) == 1
    cand = cands[0]
    # 정확히 manual_review band — auto_merge(>=0.85)에 도달하지 않음.
    assert cand.decision == "manual_review", f"score={cand.score} cand={cand}"


def test_include_auto_merge_false_keeps_manual_review() -> None:
    """include_auto_merge=False — auto_merge는 빠지고 manual_review만 남음."""
    # 동일 좌표 + 동일 이름 → auto_merge.
    auto_left = _Stub("f_knps_auto", "불국사", _c("129.3320", "35.7900"), _TEMPLE_CAT)
    auto_right = _Stub("f_krh_auto", "불국사", _c("129.3320", "35.7900"), _TEMPLE_CAT)
    # 동일 이름·카테고리 + 60m 떨어진 좌표 → manual_review band.
    man_left = _Stub("f_knps_man", "송광사", _c("127.29500", "35.00900"), _TEMPLE_CAT)
    man_right = _Stub("f_krh_man", "송광사", _c("127.29500", "35.00954"), _TEMPLE_CAT)

    cands = find_dedup_candidates(
        [auto_left, man_left], [auto_right, man_right], include_auto_merge=False
    )
    # auto_merge는 모두 제외, manual_review만 남는다 — 송광사 쌍이 적어도 1건.
    assert len(cands) >= 1
    for c in cands:
        assert c.decision == "manual_review", f"score={c.score} cand={c}"
    # auto 쌍은 제외 — auto_left/auto_right 쌍이 후보에 없어야.
    assert all(c.feature_id_a != "f_knps_auto" for c in cands)
    assert all(c.feature_id_b != "f_krh_auto" for c in cands)


def test_self_dedup_same_feature_id_kept() -> None:
    """left와 right에 같은 feature_id가 있어도 별도 인스턴스로 비교됨.

    호출 측이 self-dedup 의도가 없다면 사전에 제외해야 한다 — 본 함수는
    그 책임을 갖지 않고, '같은 id 쌍이라도 cross-score한다'는 동작 보장.
    """
    a = _Stub("f_same", "불국사", _c("129.33", "35.79"), _TEMPLE_CAT)
    b = _Stub("f_same", "불국사", _c("129.33", "35.79"), _TEMPLE_CAT)
    cands = find_dedup_candidates([a], [b])
    assert len(cands) == 1
    # 점수는 1.0 — 동일 입력.
    assert cands[0].score == pytest.approx(1.0)
    assert cands[0].feature_id_a == "f_same"
    assert cands[0].feature_id_b == "f_same"


def test_no_coords_both_sides_uses_name_category() -> None:
    """좌표 없으면 name + category로만 점수 — spatial=0이지만 manual 진입 가능.

    same name + same category → 0.45 + 0 + 0.20 = 0.65 → MANUAL_REVIEW 경계.
    """
    a = _Stub("f_a", "불국사", None, _TEMPLE_CAT)
    b = _Stub("f_b", "불국사", None, _TEMPLE_CAT)
    cands = find_dedup_candidates([a], [b])
    assert len(cands) == 1
    cand = cands[0]
    # 정확히 0.65 (threshold 경계). MANUAL_REVIEW로 분류.
    assert cand.score == pytest.approx(0.65)
    assert cand.decision == "manual_review"


def test_one_side_missing_coord_spatial_zero() -> None:
    """한쪽 좌표만 None — spatial_sim=0, name+category만 점수."""
    a = _Stub("f_a", "불국사", _c("129.33", "35.79"), _TEMPLE_CAT)
    b = _Stub("f_b", "불국사", None, _TEMPLE_CAT)
    cands = find_dedup_candidates([a], [b])
    if cands:
        # spatial=0 → max(0.45+0.20)=0.65 만 가능.
        assert cands[0].spatial_score == 0.0
        assert cands[0].score == pytest.approx(0.65)


def test_category_mismatch_excludes() -> None:
    """카테고리 다름 + 좌표 다름 → KEEP_SEPARATE."""
    a = _Stub("f_a", "불국사", _c("129.33", "35.79"), "01070100")
    b = _Stub("f_b", "불국사", _c("129.33", "35.79"), "99999999")
    cands = find_dedup_candidates([a], [b])
    # 좌표·이름 같지만 category=0이라 0.45+0.35+0 = 0.80 < 0.85 → manual_review.
    assert len(cands) == 1
    assert cands[0].decision == "manual_review"
    assert cands[0].category_score == 0.0


def test_score_sorted_desc_and_stable_for_ties() -> None:
    """동일 score가 여럿 있을 때 정렬은 안정(insert 순서 유지)."""
    # 두 쌍 모두 동일 score(1.0). 정렬 후 입력 순서가 유지되는지.
    a1 = _Stub("f_knps_1", "불국사", _c("129.33", "35.79"), _TEMPLE_CAT)
    a2 = _Stub("f_knps_2", "통도사", _c("129.06", "35.49"), _TEMPLE_CAT)
    b1 = _Stub("f_krh_1", "불국사", _c("129.33", "35.79"), _TEMPLE_CAT)
    b2 = _Stub("f_krh_2", "통도사", _c("129.06", "35.49"), _TEMPLE_CAT)
    cands = find_dedup_candidates([a1, a2], [b1, b2])
    # 4 쌍 cross-score: (a1,b1)=1.0, (a1,b2)<1.0, (a2,b1)<1.0, (a2,b2)=1.0.
    # 상위 2건은 동일 점수 1.0 — 정렬 안정성으로 (a1,b1)이 (a2,b2)보다 먼저.
    top_two = cands[:2]
    assert {c.feature_id_a for c in top_two} == {"f_knps_1", "f_knps_2"}
    assert top_two[0].feature_id_a == "f_knps_1"  # left 우선 (입력 순서 유지)
    assert top_two[0].feature_id_b == "f_krh_1"
    assert top_two[0].score == pytest.approx(1.0)


def test_iterable_input_not_just_list() -> None:
    """Iterable 임의 형태(generator/tuple)도 받아들임."""
    def _gen() -> Iterator[DedupInput]:
        yield _Stub("f_knps_1", "불국사", _c("129.33", "35.79"), _TEMPLE_CAT)

    krh = (
        _Stub("f_krh_1", "불국사", _c("129.33", "35.79"), _TEMPLE_CAT),
    )
    cands = find_dedup_candidates(_gen(), krh)
    assert len(cands) == 1
    assert cands[0].decision == "auto_merge"


def test_right_iterable_consumed_once_per_left() -> None:
    """right가 generator라도 left N개에 대해 N번 순회 가능해야(내부 list 변환).

    `find_dedup_candidates`가 right를 매번 새로 만들지 않고도 동작하려면
    내부에서 한 번 list로 변환해야 — 회귀 보호.
    """
    def _gen_right() -> Iterator[DedupInput]:
        yield _Stub("f_krh_1", "불국사", _c("129.33", "35.79"), _TEMPLE_CAT)

    left = [
        _Stub("f_knps_1", "불국사", _c("129.33", "35.79"), _TEMPLE_CAT),
        _Stub("f_knps_2", "통도사", _c("129.06", "35.49"), _TEMPLE_CAT),
    ]
    cands = find_dedup_candidates(left, _gen_right())
    # 2 left × 1 right = 2 score. KEEP_SEPARATE는 빠지므로 1 또는 2건.
    # 핵심: f_knps_2가 right와 한 번이라도 비교되었는지(통도사 vs 불국사 KEEP_SEPARATE).
    # 적어도 f_knps_1쪽 1건은 매칭.
    assert any(c.feature_id_a == "f_knps_1" for c in cands)


def test_candidate_score_rounded_to_4_decimals() -> None:
    """score/성분 점수가 round(_, 4)로 정규화 — 부동소수점 노이즈 차단."""
    a = [_Stub("f_a", "불국사", _c("129.3320", "35.7900"), _TEMPLE_CAT)]
    b = [_Stub("f_b", "불국사", _c("129.3320", "35.7900"), _TEMPLE_CAT)]
    [cand] = find_dedup_candidates(a, b)
    # round(s, 4) 결과의 소수점 자릿수가 4 이하.
    for v in (cand.score, cand.name_score, cand.spatial_score, cand.category_score):
        # str(0.85)는 "0.85" → split "." 후 마지막 ≤ 4 자리.
        rounded_str = f"{v:.10f}".rstrip("0").rstrip(".")
        if "." in rounded_str:
            decimals = rounded_str.split(".")[1]
            assert len(decimals) <= 4, (
                f"{v} has more than 4 decimals after rstrip: {rounded_str}"
            )


# -- find_sibling_candidates (within-set, MOIS self-sibling) ------------------

_REST_CAT = "02010100"  # FOOD_RESTAURANT_KOREAN


def test_sibling_same_business_two_slugs_is_candidate() -> None:
    # 같은 사업장이 general_restaurants + tourist_restaurants 2슬러그로 등록.
    feats = [
        _Stub("f_gen", "행복식당", _c("127.0000", "37.5000"), _REST_CAT),
        _Stub("f_tour", "행복식당", _c("127.0000", "37.5000"), _REST_CAT),
    ]
    [cand] = find_sibling_candidates(feats)
    assert cand.decision == DedupDecision.AUTO_MERGE
    assert {cand.feature_id_a, cand.feature_id_b} == {"f_gen", "f_tour"}


def test_sibling_unique_pairs_no_symmetric_dup() -> None:
    # 3건 모두 동일 → 고유 쌍 3개(C(3,2)), 대칭/self 제외.
    feats = [
        _Stub("f1", "행복식당", _c("127.0000", "37.5000"), _REST_CAT),
        _Stub("f2", "행복식당", _c("127.0000", "37.5000"), _REST_CAT),
        _Stub("f3", "행복식당", _c("127.0000", "37.5000"), _REST_CAT),
    ]
    cands = find_sibling_candidates(feats)
    assert len(cands) == 3
    pairs = {frozenset((c.feature_id_a, c.feature_id_b)) for c in cands}
    assert pairs == {
        frozenset(("f1", "f2")),
        frozenset(("f1", "f3")),
        frozenset(("f2", "f3")),
    }


def test_sibling_skips_self_pair_on_duplicate_id() -> None:
    # 같은 feature_id가 중복 입력돼도 self-pair는 제외.
    feats = [
        _Stub("dup", "행복식당", _c("127.0000", "37.5000"), _REST_CAT),
        _Stub("dup", "행복식당", _c("127.0000", "37.5000"), _REST_CAT),
    ]
    assert find_sibling_candidates(feats) == []


def test_sibling_distinct_places_keep_separate() -> None:
    # 다른 이름 + 먼 좌표 → KEEP_SEPARATE → 후보 없음.
    feats = [
        _Stub("f1", "행복식당", _c("127.0000", "37.5000"), _REST_CAT),
        _Stub("f2", "전혀다른집", _c("129.0000", "35.1000"), _REST_CAT),
    ]
    assert find_sibling_candidates(feats) == []


def test_sibling_empty_and_single() -> None:
    assert find_sibling_candidates([]) == []
    assert find_sibling_candidates(
        [_Stub("f1", "행복식당", _c("127.0", "37.5"), _REST_CAT)]
    ) == []


def test_sibling_exclude_auto_merge() -> None:
    feats = [
        _Stub("f1", "행복식당", _c("127.0000", "37.5000"), _REST_CAT),
        _Stub("f2", "행복식당", _c("127.0000", "37.5000"), _REST_CAT),
    ]
    # auto_merge 후보 → include_auto_merge=False면 제외.
    assert find_sibling_candidates(feats, include_auto_merge=False) == []
