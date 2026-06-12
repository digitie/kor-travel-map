"""``test_providers_visitkorea_review_band`` — festival_to_review_candidates (T-RV-52c).

이름 유사도 점수 밴드로 visitkorea 축제 매칭을 자동(≥accept) / 검토(review-band) /
제외(<floor)로 분류하는 로직 검증. ``ScoringFestivalMatcher.best_match``(임계 비의존)
공유.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pytest

from kortravelmap.dto import SourceRole
from kortravelmap.providers.visitkorea import (
    DATASET_KEY_FESTIVAL_EVENTS,
    VISITKOREA_PROVIDER_NAME,
    FestivalCandidate,
    ScoringFestivalMatcher,
    festival_to_review_candidates,
)

KST = timezone(timedelta(hours=9))


@dataclass(frozen=True)
class _Item:
    """``VisitKoreaFestivalItem`` Protocol 만족 최소 dataclass."""

    content_id: str
    title: str | None
    overview: str | None = None
    first_image: str | None = None
    first_image2: str | None = None
    addr1: str | None = None
    area_code: str | None = None
    sigungu_code: str | None = None
    event_start_date: str | None = None
    event_end_date: str | None = None
    tel: str | None = None
    homepage: str | None = None
    modified_time: str | None = None


_CANDIDATES = [
    FestivalCandidate(feature_id="f_spring", name="서울 봄꽃 축제"),
    FestivalCandidate(feature_id="f_busan", name="부산 바다 축제"),
]


def _now() -> datetime:
    return datetime(2026, 5, 28, 10, 0, tzinfo=KST)


@pytest.mark.unit
def test_exact_match_goes_to_auto() -> None:
    matcher = ScoringFestivalMatcher(_CANDIDATES)
    item = _Item(content_id="1", title="서울 봄꽃 축제")
    plan = festival_to_review_candidates([item], matcher=matcher, fetched_at=_now())
    assert len(plan.auto) == 1
    assert plan.review == []
    assert plan.auto[0].source_link.feature_id == "f_spring"
    assert plan.auto[0].source_link.source_role is SourceRole.ENRICHMENT


@pytest.mark.unit
def test_ambiguous_match_goes_to_review() -> None:
    # 부분 일치 → review-band(0.70~0.90)에 들도록 floor/accept를 넓게 잡는다.
    matcher = ScoringFestivalMatcher(_CANDIDATES)
    item = _Item(content_id="2", title="서울 봄꽃")
    plan = festival_to_review_candidates(
        [item],
        matcher=matcher,
        fetched_at=_now(),
        accept_threshold=0.99,
        review_floor=0.5,
    )
    assert plan.auto == []
    assert len(plan.review) == 1
    candidate = plan.review[0]
    assert candidate.target_feature_id == "f_spring"
    assert candidate.target_name == "서울 봄꽃 축제"
    assert candidate.source_name == "서울 봄꽃"
    assert 0.5 <= candidate.name_score < 0.99
    # accept 시 적재할 enrichment가 준비돼 있어야 한다.
    enr = candidate.enrichment
    assert enr.source_record.provider == VISITKOREA_PROVIDER_NAME
    assert enr.source_record.dataset_key == DATASET_KEY_FESTIVAL_EVENTS
    assert enr.source_link.feature_id == "f_spring"


@pytest.mark.unit
def test_low_score_dropped() -> None:
    matcher = ScoringFestivalMatcher(_CANDIDATES)
    item = _Item(content_id="3", title="전혀 관련 없는 박람회")
    plan = festival_to_review_candidates(
        [item],
        matcher=matcher,
        fetched_at=_now(),
        accept_threshold=0.90,
        review_floor=0.70,
    )
    assert plan.auto == []
    assert plan.review == []


@pytest.mark.unit
def test_empty_title_and_no_candidates_skipped() -> None:
    matcher = ScoringFestivalMatcher(_CANDIDATES)
    blank = _Item(content_id="4", title="   ")
    plan = festival_to_review_candidates([blank], matcher=matcher, fetched_at=_now())
    assert plan.auto == []
    assert plan.review == []

    empty_matcher = ScoringFestivalMatcher([])
    plan2 = festival_to_review_candidates(
        [_Item(content_id="5", title="서울 봄꽃 축제")],
        matcher=empty_matcher,
        fetched_at=_now(),
    )
    assert plan2.auto == []
    assert plan2.review == []


@pytest.mark.unit
@pytest.mark.parametrize(
    ("accept", "floor"),
    [(0.9, 0.95), (1.1, 0.5), (0.9, -0.1)],
)
def test_invalid_band_bounds_rejected(accept: float, floor: float) -> None:
    matcher = ScoringFestivalMatcher(_CANDIDATES)
    with pytest.raises(ValueError, match="review_floor"):
        festival_to_review_candidates(
            [_Item(content_id="6", title="서울 봄꽃 축제")],
            matcher=matcher,
            fetched_at=_now(),
            accept_threshold=accept,
            review_floor=floor,
        )


@pytest.mark.unit
def test_best_match_returns_score_regardless_of_threshold() -> None:
    matcher = ScoringFestivalMatcher(_CANDIDATES, name_threshold=0.99)
    found = matcher.best_match(_Item(content_id="7", title="서울 봄꽃 축제"))
    assert found is not None
    candidate, score = found
    assert candidate.feature_id == "f_spring"
    assert score == pytest.approx(1.0)
    # match()는 임계 0.99 미만이면 None이지만 best_match는 점수를 돌려준다.
    assert matcher.best_match(_Item(content_id="8", title="없는 축제")) is not None
