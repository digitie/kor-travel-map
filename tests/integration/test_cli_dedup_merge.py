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
    SourceEntityHeadRow,
    SourceEntityRow,
    SourceLinkRow,
    SourceRecordRow,
)
from tests.integration._db_cleanup import truncate_committed_test_rows

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = pytest.mark.integration

_CAT = "01070100"
_FETCHED = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
# T-VN-33: entity가 더는 record를 참조하지 않으므로 source_records TRUNCATE가
# source_entities까지 cascade하지 않는다 — entity를 직접 비워야 재실행이 안전하다
# (head는 entity/record 양쪽에서 cascade된다).
_TRUNCATE_SQL = (
    "TRUNCATE feature.features, provider_sync.source_entities, "
    "provider_sync.source_records, "
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
    )


async def _seed_pair(engine: AsyncEngine) -> str:
    async with AsyncSession(engine) as session, session.begin():
        # T-VN-33: entity identity의 dataset 소유는 provider_dataset_id 하나뿐이다.
        provider_dataset_id = int(
            (
                await session.execute(
                    text(
                        "SELECT provider_dataset_id "
                        "FROM provider_sync.provider_datasets "
                        "WHERE provider = 'python-mois-api' "
                        "  AND dataset_key = 'mois_license_features_bulk'"
                    )
                )
            ).scalar_one()
        )
        session.add(_feature("f_master", with_coord=True))
        session.add(_feature("f_loser", with_coord=False))
        session.add(
            SourceEntityRow(
                source_entity_key="SE1",
                provider_dataset_id=provider_dataset_id,
                source_entity_type="t",
                source_entity_id="SR1",
                first_seen_at=_FETCHED,
                last_seen_at=_FETCHED,
            )
        )
        await session.flush()
        session.add(
            SourceRecordRow(
                source_record_key="SR1",
                source_entity_key="SE1",
                # raw_payload_hash는 ^[0-9a-f]{1,64}$ 를 만족해야 한다.
                raw_payload_hash="5d41402abc4b2a76b9719d911017c592",
                raw_data={},
                fetched_at=_FETCHED,
                imported_at=_FETCHED,
            )
        )
        await session.flush()
        # 현재 record 포인터는 entity가 아니라 head가 소유한다.
        session.add(
            SourceEntityHeadRow(
                source_entity_key="SE1",
                current_source_record_key="SR1",
                observed_at=_FETCHED,
            )
        )
        await session.flush()
        session.add(
            SourceLinkRow(
                feature_id="f_loser",
                source_entity_key="SE1",
                source_role="primary",
                match_method="natural_key",
                confidence=100,
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
        await truncate_committed_test_rows(session, _TRUNCATE_SQL)


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
