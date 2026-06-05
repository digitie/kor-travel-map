"""``test_merge_repo`` — dedup 수동 병합 1차 함수 (ADR-016, Sprint 4a).

``merge_from_review``/``apply_feature_merge``가 실 PostGIS에서:
① loser source_link를 master로 재지정(+ 충돌 link drop) ② loser feature soft-delete
③ ``feature_merge_history`` 기록 ④ ``dedup_review_queue`` ``merged`` 전이 하는지 검증.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from krtour.map.infra.merge_repo import (
    MergeConflictError,
    MergeNotFoundError,
    apply_feature_merge,
    merge_from_review,
)
from krtour.map.infra.models import (
    DedupReviewQueueRow,
    FeatureRow,
    SourceLinkRow,
    SourceRecordRow,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = pytest.mark.integration

_CAT = "01070100"
_FETCHED = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)


def _feature(feature_id: str, *, with_coord: bool) -> FeatureRow:
    from geoalchemy2 import WKTElement

    return FeatureRow(
        feature_id=feature_id,
        kind="place",
        name="불국사",
        category=_CAT,
        coord=WKTElement("POINT(129.3320 35.7900)", srid=4326)
        if with_coord
        else None,
        detail={"summary": "temple"},
    )


def _source_record(key: str, provider: str) -> SourceRecordRow:
    return SourceRecordRow(
        source_record_key=key,
        provider=provider,
        dataset_key="d",
        source_entity_type="t",
        source_entity_id=key,
        raw_payload_hash="h",
        raw_data={},
        fetched_at=_FETCHED,
    )


def _link(feature_id: str, key: str, *, primary: bool = True) -> SourceLinkRow:
    return SourceLinkRow(
        feature_id=feature_id,
        source_record_key=key,
        source_role="primary" if primary else "enrichment",
        match_method="natural_key",
        confidence=100,
        is_primary_source=primary,
    )


async def _seed_pair(engine: AsyncEngine) -> str:
    """master(좌표 O) + loser(좌표 X) + source_links(충돌 SR 포함) + 큐 1행 적재.

    반환: 생성된 ``review_key``. SR1은 양쪽 모두 링크(충돌), SR2는 loser 전용.
    """
    async with AsyncSession(engine) as session, session.begin():
        session.add(_feature("f_master", with_coord=True))
        session.add(_feature("f_loser", with_coord=False))
        session.add(_source_record("SR1", "python-mois-api"))
        session.add(_source_record("SR2", "python-visitkorea-api"))
        await session.flush()
        session.add(_link("f_master", "SR1"))
        session.add(_link("f_loser", "SR1", primary=False))  # 충돌 — master 보유
        session.add(_link("f_loser", "SR2"))  # loser 전용 — 이동 대상
        row = DedupReviewQueueRow(
            feature_id_a="f_loser",
            feature_id_b="f_master",
            total_score=90,
            name_score=95,
            spatial_score=88,
            category_score=80,
        )
        session.add(row)
        await session.flush()
        return str(row.review_key)


async def _links_of(engine: AsyncEngine, feature_id: str) -> set[str]:
    async with AsyncSession(engine) as session:
        result = await session.execute(
            select(SourceLinkRow.source_record_key).where(
                SourceLinkRow.feature_id == feature_id
            )
        )
        return {r[0] for r in result}


async def _feature_status(engine: AsyncEngine, feature_id: str) -> tuple[str, bool]:
    async with AsyncSession(engine) as session:
        row = (
            await session.execute(
                select(FeatureRow.status, FeatureRow.deleted_at).where(
                    FeatureRow.feature_id == feature_id
                )
            )
        ).one()
        return (row[0], row[1] is not None)


async def _merge_from_review_with_short_lock_timeout(
    session: AsyncSession, review_key: str
) -> None:
    await session.execute(text("SET LOCAL lock_timeout = '100ms'"))
    await merge_from_review(session, review_key)


@pytest.fixture
async def seeded(
    pg_container: object, migrated_engine: AsyncEngine
) -> object:
    """병합 대상 1쌍 적재 + teardown TRUNCATE. 반환: review_key."""
    review_key = await _seed_pair(migrated_engine)
    yield review_key
    async with AsyncSession(migrated_engine) as session, session.begin():
        await session.execute(
            text(
                "TRUNCATE feature.features, provider_sync.source_records, "
                "provider_sync.source_links, ops.dedup_review_queue, "
                "ops.feature_merge_history RESTART IDENTITY CASCADE"
            )
        )


async def test_merge_from_review_full_flow(
    seeded: str, migrated_engine: AsyncEngine
) -> None:
    review_key = seeded
    async with AsyncSession(migrated_engine) as session, session.begin():
        outcome = await merge_from_review(
            session, review_key, merged_by="op-1", reason="dup"
        )

    # 좌표 보유 master 선정 (ADR-016 1순위).
    assert outcome.master_feature_id == "f_master"
    assert outcome.loser_feature_id == "f_loser"
    # SR2 이동(1), 충돌 SR1 drop(1).
    assert outcome.source_links_moved == 1
    assert outcome.source_links_dropped == 1
    assert outcome.queue_updated is True

    # master는 SR1+SR2 보유, loser는 링크 없음.
    assert await _links_of(migrated_engine, "f_master") == {"SR1", "SR2"}
    assert await _links_of(migrated_engine, "f_loser") == set()
    # loser soft-delete.
    assert await _feature_status(migrated_engine, "f_loser") == ("deleted", True)
    # master는 그대로 active.
    status, _ = await _feature_status(migrated_engine, "f_master")
    assert status == "active"

    # feature_merge_history 1행 + 큐 merged.
    async with AsyncSession(migrated_engine) as session:
        hist = (
            await session.execute(
                text(
                    "SELECT master_feature_id, loser_feature_id, score, "
                    "merged_by, review_key FROM ops.feature_merge_history"
                )
            )
        ).one()
        assert hist[0] == "f_master"
        assert hist[1] == "f_loser"
        assert float(hist[2]) == 90.0
        assert hist[3] == "op-1"
        assert str(hist[4]) == review_key
        qstatus = (
            await session.execute(
                text(
                    "SELECT status, reviewed_by FROM ops.dedup_review_queue "
                    "WHERE review_key = :k"
                ),
                {"k": review_key},
            )
        ).one()
        assert qstatus[0] == "merged"
        assert qstatus[1] == "op-1"


async def test_merge_from_review_unknown_key_raises(
    seeded: str, migrated_engine: AsyncEngine
) -> None:
    async with AsyncSession(migrated_engine) as session, session.begin():
        with pytest.raises(MergeNotFoundError, match="review_key 없음"):
            await merge_from_review(
                session, "00000000-0000-0000-0000-000000000000"
            )


async def test_merge_from_review_already_merged_raises(
    seeded: str, migrated_engine: AsyncEngine
) -> None:
    review_key = seeded
    async with AsyncSession(migrated_engine) as session, session.begin():
        await merge_from_review(session, review_key)
    # 두 번째 시도 — 이미 merged.
    async with AsyncSession(migrated_engine) as session, session.begin():
        with pytest.raises(MergeConflictError, match="이미 검토"):
            await merge_from_review(session, review_key)


async def test_merge_from_review_locks_review_row(
    seeded: str, migrated_engine: AsyncEngine
) -> None:
    review_key = seeded
    async with AsyncSession(migrated_engine) as holder, holder.begin():
        await holder.execute(
            text(
                "SELECT review_key FROM ops.dedup_review_queue "
                "WHERE review_key = :review_key FOR UPDATE"
            ),
            {"review_key": review_key},
        )

        async with AsyncSession(migrated_engine) as contender:
            with pytest.raises(DBAPIError):
                await _merge_from_review_with_short_lock_timeout(
                    contender, review_key
                )


async def test_apply_feature_merge_distinct_guard(
    seeded: str, migrated_engine: AsyncEngine
) -> None:
    async with AsyncSession(migrated_engine) as session, session.begin():
        with pytest.raises(MergeConflictError, match="master와 loser가 같음"):
            await apply_feature_merge(
                session, master_id="f_master", loser_id="f_master"
            )


async def test_merge_history_count_after_merge(
    seeded: str, migrated_engine: AsyncEngine
) -> None:
    review_key = seeded
    async with AsyncSession(migrated_engine) as session, session.begin():
        await merge_from_review(session, review_key)
    async with AsyncSession(migrated_engine) as session:
        count = (
            await session.execute(
                select(func.count()).select_from(
                    text("ops.feature_merge_history")
                )
            )
        ).scalar_one()
    assert count == 1
