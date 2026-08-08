"""T-VN-33 source lineage writer의 immutable record/head cutover 검증."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text

from kortravelmap.dto import SourceRecord
from kortravelmap.infra.feature_repo import (
    _make_source_entity_key,
    upsert_source_record,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


pytestmark = pytest.mark.integration

_PROVIDER = "writer-test"
_DATASET = "immutable-head"
_ENTITY_TYPE = "record"
_ENTITY_ID = "one"
_BASE = datetime(2026, 8, 7, 1, 0, tzinfo=UTC)


async def _seed_dataset(session: AsyncSession) -> None:
    await session.execute(
        text(
            """
            INSERT INTO provider_sync.provider_datasets (
                provider, dataset_key, display_name, source_kind
            ) VALUES (
                :provider, :dataset_key, 'writer test', 'manual'
            )
            """
        ),
        {"provider": _PROVIDER, "dataset_key": _DATASET},
    )


def _record(
    *,
    key: str,
    payload_hash: str,
    observed_at: datetime,
    raw_data: dict[str, str],
) -> SourceRecord:
    return SourceRecord(
        provider=_PROVIDER,
        dataset_key=_DATASET,
        source_entity_type=_ENTITY_TYPE,
        source_entity_id=_ENTITY_ID,
        raw_payload_hash=payload_hash,
        raw_data=raw_data,
        fetched_at=_BASE,
        imported_at=observed_at,
        source_record_key=key,
    )


async def test_source_record_writer_keeps_raw_snapshot_immutable_and_advances_head(
    migrated_session: AsyncSession,
) -> None:
    """재관측은 raw row가 아니라 current head만 바꾼다."""

    await _seed_dataset(migrated_session)
    entity_key = _make_source_entity_key(
        provider=_PROVIDER,
        dataset_key=_DATASET,
        source_entity_type=_ENTITY_TYPE,
        source_entity_id=_ENTITY_ID,
    )
    first = _record(
        key="source-record-a",
        payload_hash="a1",
        observed_at=_BASE,
        raw_data={"edition": "a"},
    )
    assert await upsert_source_record(migrated_session, first) is True

    repeated_at = _BASE + timedelta(minutes=5)
    repeated = _record(
        key="source-record-a",
        payload_hash="a1",
        observed_at=repeated_at,
        raw_data={"edition": "a"},
    )
    assert await upsert_source_record(migrated_session, repeated) is False

    second_at = repeated_at + timedelta(minutes=5)
    second = _record(
        key="source-record-b",
        payload_hash="b2",
        observed_at=second_at,
        raw_data={"edition": "b"},
    )
    assert await upsert_source_record(migrated_session, second) is True

    # stale 재관측은 current pointer와 만료 상태를 되돌릴 수 없다.
    stale = _record(
        key="source-record-a",
        payload_hash="a1",
        observed_at=_BASE + timedelta(minutes=1),
        raw_data={"edition": "a"},
    )
    assert await upsert_source_record(migrated_session, stale) is False
    await migrated_session.flush()

    stored = (
        await migrated_session.execute(
            text(
                """
                SELECT
                    head.current_source_record_key,
                    head.observed_at,
                    first_record.raw_data,
                    first_record.imported_at,
                    entity.first_seen_at,
                    entity.last_seen_at
                FROM provider_sync.source_entities AS entity
                JOIN provider_sync.source_entity_heads AS head
                  ON head.source_entity_key = entity.source_entity_key
                JOIN provider_sync.source_records AS first_record
                  ON first_record.source_record_key = 'source-record-a'
                WHERE entity.source_entity_key = :entity_key
                """
            ),
            {"entity_key": entity_key},
        )
    ).mappings().one()

    assert stored["current_source_record_key"] == "source-record-b"
    assert stored["observed_at"] == second_at
    assert stored["raw_data"] == {"edition": "a"}
    assert stored["imported_at"] == _BASE
    assert stored["first_seen_at"] == _BASE
    assert stored["last_seen_at"] == second_at
