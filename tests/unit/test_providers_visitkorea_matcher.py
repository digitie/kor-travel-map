"""``test_providers_visitkorea_matcher`` — ScoringFestivalMatcher (T-RV-52b1).

이름 Jaro-Winkler 유사도(ADR-016)로 visitkorea 축제를 적재된 datagokr 축제 후보에
매칭하는 기본 matcher 검증.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from kortravelmap.providers.visitkorea import (
    FestivalCandidate,
    ScoringFestivalMatcher,
)


@dataclass
class _Item:
    """matcher가 쓰는 ``.title``만 가진 최소 입력(Protocol 일부)."""

    title: str | None


_CANDIDATES = [
    FestivalCandidate(feature_id="f_seoul", name="서울 봄꽃 축제"),
    FestivalCandidate(feature_id="f_busan", name="부산 바다 축제"),
    FestivalCandidate(feature_id="f_jeju", name="제주 유채꽃 축제"),
]


@pytest.mark.unit
def test_exact_name_match_high_confidence() -> None:
    matcher = ScoringFestivalMatcher(_CANDIDATES)
    result = matcher.match(_Item(title="서울 봄꽃 축제"))
    assert result is not None
    assert result.feature_id == "f_seoul"
    assert result.confidence == 100
    assert result.match_method == "name_match"


@pytest.mark.unit
def test_no_candidate_above_threshold_returns_none() -> None:
    matcher = ScoringFestivalMatcher(_CANDIDATES, name_threshold=0.95)
    assert matcher.match(_Item(title="완전히 다른 이름의 행사")) is None


@pytest.mark.unit
def test_empty_or_none_title_returns_none() -> None:
    matcher = ScoringFestivalMatcher(_CANDIDATES)
    assert matcher.match(_Item(title="")) is None
    assert matcher.match(_Item(title="   ")) is None
    assert matcher.match(_Item(title=None)) is None


@pytest.mark.unit
def test_picks_best_scoring_candidate() -> None:
    candidates = [
        FestivalCandidate(feature_id="f_cherry", name="서울 벚꽃 축제"),
        FestivalCandidate(feature_id="f_spring", name="서울 봄꽃 축제"),
    ]
    matcher = ScoringFestivalMatcher(candidates, name_threshold=0.8)
    result = matcher.match(_Item(title="서울 봄꽃 축제"))
    assert result is not None
    # 완전 일치하는 후보가 최고점.
    assert result.feature_id == "f_spring"


@pytest.mark.unit
def test_blank_named_candidates_ignored() -> None:
    matcher = ScoringFestivalMatcher(
        [FestivalCandidate(feature_id="f_blank", name="   ")]
    )
    assert matcher.match(_Item(title="서울 봄꽃 축제")) is None


@pytest.mark.unit
@pytest.mark.parametrize("bad", [-0.1, 1.1, 2.0])
def test_invalid_threshold_rejected(bad: float) -> None:
    with pytest.raises(ValueError, match="name_threshold"):
        ScoringFestivalMatcher(_CANDIDATES, name_threshold=bad)
