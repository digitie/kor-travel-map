"""``test_core_dedup`` — cross-provider dedup 후보 (ADR-016, SPRINT-3 §2.5).

knps 사찰 ↔ krheritage temple 시나리오로 ``find_dedup_candidates`` 검증.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

import pytest

from krtour.map.core.dedup import DedupCandidate, find_dedup_candidates
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
