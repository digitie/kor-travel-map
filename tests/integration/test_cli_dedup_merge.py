"""``test_cli_dedup_merge`` — ``ktmctl dedup-merge`` round-trip (Sprint 4a).

검토 큐 후보 1쌍 적재 → CLI ``dedup-merge <review_id>``(자체 engine, ``--dsn``) →
병합 + 큐 ``merged`` 전이를 검증. + advisory lock 점유 시 skip(exit 3) + 미존재
review_id(exit 2).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.cli import dedup_merge_lock_key
from kortravelmap.cli.main import build_parser
from kortravelmap.infra.advisory_lock import advisory_lock
from kortravelmap.infra.models import (
    DedupReviewQueueRow,
    FeatureRow,
    SourceLinkRow,
    SourceRecordRow,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = pytest.mark.integration

_CAT = "01070100"
_FETCHED = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
_TRUNCATE_SQL = (
    "TRUNCATE feature.features, provider_sync.source_records, "
    "provider_sync.source_links, ops.dedup_review_queue, "
    "ops.feature_merge_history RESTART IDENTITY CASCADE"
)


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


async def _seed_pair(engine: AsyncEngine) -> str:
    async with AsyncSession(engine) as session, session.begin():
        session.add(_feature("f_master", with_coord=True))
        session.add(_feature("f_loser", with_coord=False))
        session.add(
            SourceRecordRow(
                source_record_key="SR1",
                provider="python-mois-api",
                dataset_key="d",
                source_entity_type="t",
                source_entity_id="SR1",
                raw_payload_hash="h",
                raw_data={},
                fetched_at=_FETCHED,
            )
        )
        await session.flush()
        session.add(
            SourceLinkRow(
                feature_id="f_loser",
                source_record_key="SR1",
                source_role="primary",
                match_method="natural_key",
                confidence=100,
                is_primary_source=True,
            )
        )
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
        return str(row.review_id)


@pytest.fixture
async def container_dsn(
    pg_container: object, migrated_engine: AsyncEngine
) -> AsyncIterator[str]:
    from kortravelmap.infra.db import normalize_async_dsn

    dsn = normalize_async_dsn(pg_container.get_connection_url())  # type: ignore[attr-defined]
    yield dsn
    async with AsyncSession(migrated_engine) as session, session.begin():
        await session.execute(text(_TRUNCATE_SQL))


async def _queue_status(engine: AsyncEngine, review_id: str) -> str:
    async with AsyncSession(engine) as session:
        return str(
            (
                await session.execute(
                    text(
                        "SELECT status FROM ops.dedup_review_queue "
                        "WHERE review_id = :k"
                    ),
                    {"k": review_id},
                )
            ).scalar_one()
        )


async def test_cli_dedup_merge_round_trip(
    container_dsn: str, migrated_engine: AsyncEngine
) -> None:
    review_id = await _seed_pair(migrated_engine)
    args = build_parser().parse_args(
        ["--dsn", container_dsn, "dedup-merge", review_id, "--merged-by", "op-1"]
    )
    rc = await args.func(args)  # type: ignore[attr-defined]
    assert rc == 0
    assert await _queue_status(migrated_engine, review_id) == "merged"


async def test_cli_dedup_merge_skips_when_locked(
    container_dsn: str, migrated_engine: AsyncEngine
) -> None:
    review_id = await _seed_pair(migrated_engine)
    args = build_parser().parse_args(
        ["--dsn", container_dsn, "dedup-merge", review_id]
    )
    key = dedup_merge_lock_key(review_id)
    async with (
        AsyncSession(migrated_engine) as holder,
        advisory_lock(holder, key),
    ):
        rc = await args.func(args)  # type: ignore[attr-defined]
    assert rc == 3  # _EXIT_LOCK_SKIPPED
    # 잠겨서 미수행 — 큐는 그대로 pending.
    assert await _queue_status(migrated_engine, review_id) == "pending"


async def test_cli_dedup_merge_unknown_key_exit2(
    container_dsn: str, migrated_engine: AsyncEngine
) -> None:
    # 큐 비어 있어도 fixture가 teardown TRUNCATE하므로 안전.
    args = build_parser().parse_args(
        ["--dsn", container_dsn, "dedup-merge",
         "00000000-0000-0000-0000-000000000000"]
    )
    rc = await args.func(args)  # type: ignore[attr-defined]
    assert rc == 2  # _EXIT_INVALID
