"""``test_enrichment_review_repo`` — ops.enrichment_review_queue (ADR-042, T-RV-52c).

``infra/enrichment_review_repo.py``의 enqueue / pending / decide를 실 PostGIS
(migrated_session, alembic head)에서 검증한다:

- review-band 후보 insert + 점수 0~100 변환 + status='pending'.
- 재스캔 시 pending 행 갱신(updated), 검토 완료 행 보존(skipped).
- ``pending_enrichment_reviews`` name_score 내림차순 + float 변환.
- accept → ENRICHMENT ``SourceLink`` 적재(1차 feature에 source만 추가) + status 갱신.
- reject/ignore는 상태만 갱신, 이미 검토된 행은 changed=False.
- FK — 존재하지 않는 target feature 참조 시 IntegrityError.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from krtour.map.infra.enrichment_review_repo import (
    EnrichmentQueueResult,
    EnrichmentReviewInput,
    decide_enrichment_review,
    enqueue_review_candidate,
    enqueue_review_candidates,
    pending_enrichment_reviews,
)
from krtour.map.infra.models import FeatureRow
from krtour.map.providers.visitkorea import (
    FestivalCandidate,
    FestivalReviewCandidate,
    ScoringFestivalMatcher,
    festival_to_review_candidates,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration

KST = timezone(timedelta(hours=9))
_FESTIVAL_CAT = "01010100"  # event/festival 카테고리(임의 유효값)
_TARGET_ID = "f_1100000000_e_springfest0000000000"


def _festival_feature(feature_id: str = _TARGET_ID, name: str = "서울 봄꽃 축제") -> FeatureRow:
    """datagokr 1차 축제 event feature (enrichment FK 대상)."""
    return FeatureRow(
        feature_id=feature_id,
        kind="event",
        name=name,
        category=_FESTIVAL_CAT,
        detail={},
    )


class _Item:
    """``VisitKoreaFestivalItem`` Protocol 만족 최소 객체."""

    def __init__(self, content_id: str, title: str) -> None:
        self.content_id = content_id
        self.title = title
        self.overview = None
        self.first_image = None
        self.first_image2 = None
        self.addr1 = "서울특별시 영등포구"
        self.area_code = "1"
        self.sigungu_code = "19"
        self.event_start_date = "20260405"
        self.event_end_date = "20260412"
        self.tel = None
        self.homepage = None
        self.modified_time = "20260301120000"


def _now() -> datetime:
    return datetime(2026, 5, 28, 10, 0, tzinfo=KST)


def _review_candidate(
    title: str, *, target: str = _TARGET_ID, target_name: str = "서울 봄꽃 축제"
) -> FestivalReviewCandidate:
    """review-band 후보 1건 생성(점수 밴드를 넓혀 강제로 review로 보냄)."""
    matcher = ScoringFestivalMatcher(
        [FestivalCandidate(feature_id=target, name=target_name)]
    )
    plan = festival_to_review_candidates(
        [_Item("c-" + title, title)],
        matcher=matcher,
        fetched_at=_now(),
        accept_threshold=0.999,
        review_floor=0.3,
    )
    assert len(plan.review) == 1
    return plan.review[0]


def _as_input(candidate: FestivalReviewCandidate) -> EnrichmentReviewInput:
    return EnrichmentReviewInput(
        target_feature_id=candidate.target_feature_id,
        target_name=candidate.target_name,
        source_name=candidate.source_name,
        name_score=candidate.name_score,
        source_record=candidate.enrichment.source_record,
    )


async def test_enqueue_inserts_pending(migrated_session: AsyncSession) -> None:
    migrated_session.add(_festival_feature())
    await migrated_session.flush()

    result = await enqueue_review_candidates(
        migrated_session, [_as_input(_review_candidate("서울 봄꽃"))]
    )
    assert result == EnrichmentQueueResult(
        candidates_total=1, inserted=1, updated=0, skipped=0
    )

    row = (
        await migrated_session.execute(
            text(
                "SELECT target_feature_id, source_provider, source_name, "
                "name_score, status FROM ops.enrichment_review_queue"
            )
        )
    ).one()
    assert row.target_feature_id == _TARGET_ID
    assert row.source_provider == "python-visitkorea-api"
    assert row.source_name == "서울 봄꽃"
    assert 30.0 <= float(row.name_score) < 99.9
    assert row.status == "pending"


async def test_reenqueue_updates_then_preserves_reviewed(
    migrated_session: AsyncSession,
) -> None:
    migrated_session.add(_festival_feature())
    await migrated_session.flush()
    candidate = _as_input(_review_candidate("서울 봄꽃"))

    first = await enqueue_review_candidate(migrated_session, candidate)
    second = await enqueue_review_candidate(migrated_session, candidate)
    assert first == "inserted"
    assert second == "updated"

    # 운영자 검토 완료로 표시 → 재스캔 시 보존(skipped).
    await migrated_session.execute(
        text(
            "UPDATE ops.enrichment_review_queue SET status = 'rejected' "
            "WHERE target_feature_id = :t"
        ),
        {"t": _TARGET_ID},
    )
    third = await enqueue_review_candidate(migrated_session, candidate)
    assert third == "skipped"


async def test_pending_sorted_desc_and_float(
    migrated_session: AsyncSession,
) -> None:
    migrated_session.add(_festival_feature("f_a_evt", "가나다 축제"))
    migrated_session.add(_festival_feature("f_b_evt", "서울 봄꽃 축제"))
    await migrated_session.flush()

    high = _as_input(
        _review_candidate("서울 봄꽃 축", target="f_b_evt", target_name="서울 봄꽃 축제")
    )
    low = _as_input(
        _review_candidate("가나", target="f_a_evt", target_name="가나다 축제")
    )
    await enqueue_review_candidates(migrated_session, [low, high])

    rows = await pending_enrichment_reviews(migrated_session, limit=10)
    assert len(rows) == 2
    assert rows[0]["name_score"] >= rows[1]["name_score"]
    assert isinstance(rows[0]["name_score"], float)
    assert rows[0]["status"] == "pending"


async def test_accept_applies_enrichment_link(
    migrated_session: AsyncSession,
) -> None:
    migrated_session.add(_festival_feature())
    await migrated_session.flush()
    await enqueue_review_candidate(
        migrated_session, _as_input(_review_candidate("서울 봄꽃"))
    )
    review_key = (
        await migrated_session.execute(
            text("SELECT review_key FROM ops.enrichment_review_queue LIMIT 1")
        )
    ).scalar_one()

    decision = await decide_enrichment_review(
        migrated_session, review_key, "accepted", reviewed_by="tester"
    )
    assert decision.changed is True
    assert decision.applied is True
    assert decision.load is not None
    assert decision.load.source_links_inserted == 1

    # ENRICHMENT source_link이 1차 feature에 적재됐는지.
    link_role = (
        await migrated_session.execute(
            text(
                "SELECT source_role FROM provider_sync.source_links "
                "WHERE feature_id = :t"
            ),
            {"t": _TARGET_ID},
        )
    ).scalar_one()
    assert link_role == "enrichment"

    status = (
        await migrated_session.execute(
            text(
                "SELECT status FROM ops.enrichment_review_queue "
                "WHERE review_key = :k"
            ),
            {"k": review_key},
        )
    ).scalar_one()
    assert status == "accepted"


async def test_decide_idempotent_after_review(
    migrated_session: AsyncSession,
) -> None:
    migrated_session.add(_festival_feature())
    await migrated_session.flush()
    await enqueue_review_candidate(
        migrated_session, _as_input(_review_candidate("서울 봄꽃"))
    )
    review_key = (
        await migrated_session.execute(
            text("SELECT review_key FROM ops.enrichment_review_queue LIMIT 1")
        )
    ).scalar_one()

    first = await decide_enrichment_review(migrated_session, review_key, "rejected")
    assert first.changed is True
    assert first.applied is False

    # 이미 검토됨 → 두 번째 결정은 무효(changed=False).
    second = await decide_enrichment_review(migrated_session, review_key, "accepted")
    assert second.changed is False
    assert second.applied is False


async def test_decide_rejects_invalid_decision(
    migrated_session: AsyncSession,
) -> None:
    with pytest.raises(ValueError, match="decision"):
        await decide_enrichment_review(migrated_session, "no-such-key", "bogus")


async def test_fk_requires_existing_target_feature(
    migrated_session: AsyncSession,
) -> None:
    candidate = _as_input(_review_candidate("서울 봄꽃", target="ghost_evt"))
    with pytest.raises(IntegrityError):  # noqa: PT012 — savepoint 격리 필요
        async with migrated_session.begin_nested():
            await enqueue_review_candidate(migrated_session, candidate)
