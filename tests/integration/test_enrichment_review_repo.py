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

import asyncio
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

import pytest
from geoalchemy2.elements import WKTElement
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession as _AsyncSession

from kortravelmap.infra.admin_feature_repo import (
    get_enrichment_review_detail,
    list_enrichment_reviews,
)
from kortravelmap.infra.enrichment_review_repo import (
    EnrichmentQueueResult,
    EnrichmentReviewInput,
    decide_enrichment_review,
    enqueue_review_candidate,
    enqueue_review_candidates,
    pending_enrichment_reviews,
)
from kortravelmap.infra.models import FeatureRow
from kortravelmap.providers.visitkorea import (
    FestivalCandidate,
    FestivalReviewCandidate,
    ScoringFestivalMatcher,
    festival_to_review_candidates,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

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
        coord=WKTElement("POINT(126.9244 37.5261)", srid=4326),
        coord_precision_digits=6,
        detail={
            "starts_on": "2026-04-05",
            "ends_on": "2026-04-12",
        },
    )


class _Item:
    """``VisitKoreaFestivalItem`` Protocol 만족 최소 객체."""

    def __init__(
        self,
        content_id: str,
        title: str,
        *,
        map_x: float = 126.9245,
        map_y: float = 37.526,
    ) -> None:
        self.content_id = content_id
        self.title = title
        self.overview = None
        self.first_image = None
        self.first_image2 = None
        self.addr1 = "서울특별시 영등포구"
        self.area_code = "1"
        self.sigungu_code = "19"
        self.map_x = map_x
        self.map_y = map_y
        self.event_start_date = "20260405"
        self.event_end_date = "20260412"
        self.tel = None
        self.homepage = None
        self.modified_time = "20260301120000"


def _now() -> datetime:
    return datetime(2026, 5, 28, 10, 0, tzinfo=KST)


def _review_candidate(
    title: str,
    *,
    map_x: float = 126.9245,
    map_y: float = 37.526,
    target: str = _TARGET_ID,
    target_name: str = "서울 봄꽃 축제",
) -> FestivalReviewCandidate:
    """review-band 후보 1건 생성(점수 밴드를 넓혀 강제로 review로 보냄)."""
    matcher = ScoringFestivalMatcher(
        [FestivalCandidate(feature_id=target, name=target_name)]
    )
    plan = festival_to_review_candidates(
        [_Item("c-" + title, title, map_x=map_x, map_y=map_y)],
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
    review_id = (
        await migrated_session.execute(
            text("SELECT review_id FROM ops.enrichment_review_queue LIMIT 1")
        )
    ).scalar_one()

    decision = await decide_enrichment_review(
        migrated_session, review_id, "accepted", reviewed_by="tester"
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
                "WHERE review_id = :k"
            ),
            {"k": review_id},
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
    review_id = (
        await migrated_session.execute(
            text("SELECT review_id FROM ops.enrichment_review_queue LIMIT 1")
        )
    ).scalar_one()

    first = await decide_enrichment_review(migrated_session, review_id, "rejected")
    assert first.changed is True
    assert first.applied is False

    # 이미 검토됨 → 두 번째 결정은 무효(changed=False).
    second = await decide_enrichment_review(migrated_session, review_id, "accepted")
    assert second.changed is False
    assert second.applied is False


async def test_decide_rejects_invalid_decision(
    migrated_session: AsyncSession,
) -> None:
    with pytest.raises(ValueError, match="decision"):
        await decide_enrichment_review(migrated_session, "no-such-key", "bogus")


async def test_list_enrichment_reviews_admin_query(
    migrated_session: AsyncSession,
) -> None:
    migrated_session.add(_festival_feature("f_a_evt", "가나다 축제"))
    migrated_session.add(_festival_feature("f_b_evt", "서울 봄꽃 축제"))
    await migrated_session.flush()
    await enqueue_review_candidates(
        migrated_session,
        [
            _as_input(
                _review_candidate("가나", target="f_a_evt", target_name="가나다 축제")
            ),
            _as_input(
                _review_candidate(
                    "서울 봄꽃 축", target="f_b_evt", target_name="서울 봄꽃 축제"
                )
            ),
        ],
    )

    page = await list_enrichment_reviews(migrated_session, statuses=("pending",))
    assert len(page.items) == 2
    assert page.total_count == 2
    # name_score 내림차순.
    assert page.items[0].name_score >= page.items[1].name_score
    top = page.items[0]
    # 1차 feature를 join해 kind/category를 채운다.
    assert top.target_kind == "event"
    assert top.target_category == _FESTIVAL_CAT
    assert top.target_lon == pytest.approx(126.9244)
    assert top.target_lat == pytest.approx(37.5261)
    assert top.target_start_date == "2026-04-05"
    assert top.target_end_date == "2026-04-12"
    assert top.source_provider == "python-visitkorea-api"
    assert top.source_lon == pytest.approx(126.9245)
    assert top.source_lat == pytest.approx(37.526)
    assert top.source_start_date == "20260405"
    assert top.source_end_date == "20260412"
    assert top.distance_m is not None
    assert 0 < top.distance_m < 20
    assert top.spatial_score is not None
    assert 60 < top.spatial_score <= 100

    page_2 = await list_enrichment_reviews(
        migrated_session,
        statuses=("pending",),
        page_size=1,
        page=2,
    )
    assert len(page_2.items) == 1
    assert page_2.total_count == 2

    # provider 필터.
    filtered = await list_enrichment_reviews(
        migrated_session, providers=("python-visitkorea-api",)
    )
    assert len(filtered.items) == 2
    assert filtered.total_count == 2
    none_match = await list_enrichment_reviews(
        migrated_session, providers=("python-knps-api",)
    )
    assert none_match.items == ()
    assert none_match.total_count == 0


async def test_list_enrichment_reviews_far_distance_does_not_underflow(
    migrated_session: AsyncSession,
) -> None:
    migrated_session.add(_festival_feature("f_far_evt", "서울 봄꽃 축제"))
    await migrated_session.flush()
    await enqueue_review_candidates(
        migrated_session,
        [
            _as_input(
                _review_candidate(
                    "서울 봄꽃 축",
                    map_x=0.0,
                    map_y=0.0,
                    target="f_far_evt",
                    target_name="서울 봄꽃 축제",
                )
            ),
        ],
    )

    page = await list_enrichment_reviews(migrated_session, statuses=("pending",))

    assert len(page.items) == 1
    item = page.items[0]
    assert item.distance_m is not None
    assert item.distance_m > 1_000_000
    assert item.spatial_score == 0.0

    detail = await get_enrichment_review_detail(migrated_session, item.review_id)
    assert detail is not None
    assert detail.distance_m is not None
    assert detail.distance_m > 1_000_000
    assert detail.spatial_score == 0.0


async def test_fk_requires_existing_target_feature(
    migrated_session: AsyncSession,
) -> None:
    candidate = _as_input(_review_candidate("서울 봄꽃", target="ghost_evt"))
    with pytest.raises(IntegrityError):  # noqa: PT012 — savepoint 격리 필요
        async with migrated_session.begin_nested():
            await enqueue_review_candidate(migrated_session, candidate)


_RACE_TRUNCATE = (
    "TRUNCATE feature.features, provider_sync.source_records, "
    "provider_sync.source_links, ops.enrichment_review_queue "
    "RESTART IDENTITY CASCADE"
)


async def test_concurrent_decide_no_accepted_link_leak(
    migrated_engine: AsyncEngine,
) -> None:
    """동시 accept/reject 결정 시 FOR UPDATE 직렬화로 link 누수가 없어야 한다(#297).

    같은 pending 행에 accept와 reject를 동시 실행하면 정확히 하나만 점유(changed=True)
    하고, 최종 ENRICHMENT link 존재 여부가 최종 status와 정합해야 한다(reject가
    이기면 link 0, accept가 이기면 link 1). 버그(점유 전 side-effect)면 reject가
    status를 잡아도 accept가 link를 새겨 link=1·status=rejected 불일치가 난다.
    """
    try:
        # 1) feature + pending 후보를 commit 적재.
        async with _AsyncSession(migrated_engine) as session, session.begin():
            session.add(_festival_feature())
            await session.flush()
            await enqueue_review_candidate(
                session, _as_input(_review_candidate("서울 봄꽃"))
            )
        async with _AsyncSession(migrated_engine) as session:
            review_id = (
                await session.execute(
                    text("SELECT review_id FROM ops.enrichment_review_queue LIMIT 1")
                )
            ).scalar_one()

        # 2) accept / reject 동시 결정 (각 자기 transaction).
        async def _decide(decision: str) -> object:
            async with _AsyncSession(migrated_engine) as session, session.begin():
                return await decide_enrichment_review(session, review_id, decision)

        results = await asyncio.gather(
            _decide("accepted"), _decide("rejected")
        )
        changed = [r for r in results if r.changed]
        assert len(changed) == 1  # 정확히 하나만 점유.

        # 3) 최종 status ↔ ENRICHMENT link 정합.
        async with _AsyncSession(migrated_engine) as session:
            status = (
                await session.execute(
                    text(
                        "SELECT status FROM ops.enrichment_review_queue "
                        "WHERE review_id = :k"
                    ),
                    {"k": review_id},
                )
            ).scalar_one()
            link_count = (
                await session.execute(
                    text(
                        "SELECT count(*) FROM provider_sync.source_links "
                        "WHERE source_role = 'enrichment'"
                    )
                )
            ).scalar_one()
        assert (link_count == 1) == (status == "accepted")
    finally:
        async with _AsyncSession(migrated_engine) as session, session.begin():
            await session.execute(text(_RACE_TRUNCATE))
