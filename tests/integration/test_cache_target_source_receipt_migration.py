"""0076 cache target immutable source receipt migration 회귀."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from alembic.config import Config
from sqlalchemy import BigInteger, CheckConstraint, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError, IntegrityError

from alembic import command
from kortravelmap.infra.db import make_async_engine, normalize_async_dsn
from kortravelmap.infra.models import PoiCacheTargetSourceEventRow

pytestmark = pytest.mark.integration

_PRE_REVISION = "0075_cache_target_outbox"
_TARGET_REVISION = "0076_cache_target_receipt"
_ACTIVE_TARGET_ID = "10000000-0000-4000-8000-000000000001"
_DELETED_TARGET_ID = "10000000-0000-4000-8000-000000000002"
_ACTIVE_EVENT_ID = "20000000-0000-4000-8000-000000000001"
_DELETED_EVENT_ID = "20000000-0000-4000-8000-000000000002"


def _run_alembic(dsn: str, revision: str, *, downgrade: bool = False) -> None:
    root = Path(__file__).resolve().parents[2]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    config.set_main_option("sqlalchemy.url", dsn)
    if downgrade:
        command.downgrade(config, revision)
    else:
        command.upgrade(config, revision)


async def _seed_0075_receipts(connection: Any) -> None:
    params = {
        "active_target_id": _ACTIVE_TARGET_ID,
        "deleted_target_id": _DELETED_TARGET_ID,
        "active_event_id": _ACTIVE_EVENT_ID,
        "deleted_event_id": _DELETED_EVENT_ID,
        "active_entity_tag": f'"{_ACTIVE_TARGET_ID}:5"',
    }
    statements = (
        """
            INSERT INTO ops.poi_cache_target_streams (
              external_system, consumer_id, restore_epoch
            ) VALUES ('receipt-test', 'pinvi-consumer', 1)
        """,
        """
            INSERT INTO ops.poi_cache_targets (
              target_id, lock_version, external_system, target_key,
              lon, lat, coord, coord_key, radius_km,
              update_enabled, updated_at, deleted_at
            ) VALUES
            (
              CAST(:active_target_id AS uuid), 7, 'receipt-test', 'active',
              126.978, 37.5665,
              x_extension.ST_SetSRID(
                x_extension.ST_MakePoint(126.978, 37.5665), 4326
              ),
              '126.978000:37.566500:p6', 5, true,
              '2026-08-01 11:59:00+00', NULL
            ),
            (
              CAST(:deleted_target_id AS uuid), 9, 'receipt-test', 'deleted',
              126.979, 37.5666,
              x_extension.ST_SetSRID(
                x_extension.ST_MakePoint(126.979, 37.5666), 4326
              ),
              '126.979000:37.566600:p6', 5, false,
              '2026-08-01 12:00:00+00', '2026-08-01 12:00:00+00'
            )
        """,
        """
            INSERT INTO ops.poi_cache_target_source_heads (
              external_system, target_key, target_id, state, restore_epoch,
              source_generation, source_payload_fingerprint
            ) VALUES
            (
              'receipt-test', 'active', CAST(:active_target_id AS uuid),
              'active', 1, 1, repeat('a', 64)
            ),
            (
              'receipt-test', 'deleted', NULL,
              'deleted', 1, 1, repeat('b', 64)
            )
        """,
        """
            INSERT INTO ops.poi_cache_target_source_events (
              event_id, external_system, target_key, idempotency_key, operation,
              restore_epoch, source_generation, request_fingerprint,
              source_payload_fingerprint, outcome, target_id,
              occurred_at, recorded_at
            ) VALUES
            (
              CAST(:active_event_id AS uuid), 'receipt-test', 'active',
              '30000000-0000-4000-8000-000000000001', 'upsert',
              1, 1, repeat('c', 64), repeat('a', 64), 'applied',
              CAST(:active_target_id AS uuid),
              '2026-08-01 11:58:00+00', '2026-08-01 11:58:00+00'
            ),
            (
              CAST(:deleted_event_id AS uuid), 'receipt-test', 'deleted',
              '30000000-0000-4000-8000-000000000002', 'delete',
              1, 1, repeat('d', 64), repeat('b', 64), 'applied',
              CAST(:deleted_target_id AS uuid),
              '2026-08-01 12:00:00+00', '2026-08-01 12:00:00+00'
            )
        """,
        """
            INSERT INTO ops.poi_cache_target_outbox_events (
              event_id, event_type, event_scope, external_system, target_key,
              target_id, restore_epoch, source_generation, target_sequence,
              source_payload_fingerprint, payload_fingerprint, payload,
              source_event_id
            ) VALUES
            (
              '40000000-0000-4000-8000-000000000001',
              'cache_target.state_applied', 'target', 'receipt-test', 'active',
              CAST(:active_target_id AS uuid), 1, 1, 1,
              repeat('a', 64), repeat('e', 64),
              jsonb_build_object(
                'version', 'cache-target-event-v1',
                'state', 'active',
                'source_event_id', CAST(:active_event_id AS text),
                'target', jsonb_build_object(
                  'target_id', CAST(:active_target_id AS text),
                  'entity_tag', CAST(:active_entity_tag AS text)
                )
              ),
              CAST(:active_event_id AS uuid)
            ),
            (
              '40000000-0000-4000-8000-000000000002',
              'cache_target.state_applied', 'target', 'receipt-test', 'deleted',
              CAST(:deleted_target_id AS uuid), 1, 1, 1,
              repeat('b', 64), repeat('f', 64),
              jsonb_build_object(
                'version', 'cache-target-event-v1',
                'state', 'deleted',
                'source_event_id', CAST(:deleted_event_id AS text),
                'target', NULL
              ),
              CAST(:deleted_event_id AS uuid)
            )
        """,
    )
    for statement in statements:
        await connection.execute(text(statement), params)


async def test_0076_receipt_backfill_drift_guard_and_downgrade(
    pg_container: Any,
) -> None:
    admin_dsn = normalize_async_dsn(pg_container.get_connection_url())
    database = f"cache_target_0076_{uuid4().hex}"
    target_dsn = make_url(admin_dsn).set(database=database).render_as_string(
        hide_password=False
    )
    admin_engine = make_async_engine(admin_dsn)
    async with admin_engine.connect() as connection:
        autocommit = await connection.execution_options(isolation_level="AUTOCOMMIT")
        await autocommit.execute(text(f'CREATE DATABASE "{database}"'))

    target_engine = make_async_engine(target_dsn)
    try:
        await target_engine.dispose()
        await asyncio.to_thread(_run_alembic, target_dsn, _PRE_REVISION)
        target_engine = make_async_engine(target_dsn)
        async with target_engine.begin() as connection:
            await _seed_0075_receipts(connection)

        await target_engine.dispose()
        await asyncio.to_thread(_run_alembic, target_dsn, _TARGET_REVISION)
        target_engine = make_async_engine(target_dsn)
        async with target_engine.connect() as connection:
            receipt_rows = (
                await connection.execute(
                    text(
                        "SELECT event_id::text, target_lock_version "
                        "FROM ops.poi_cache_target_source_events"
                    )
                )
            ).tuples().all()
            receipts = {str(event_id): int(version) for event_id, version in receipt_rows}
            constraints = set(
                (
                    await connection.execute(
                        text(
                            "SELECT conname FROM pg_constraint "
                            "WHERE conrelid = "
                            "'ops.poi_cache_target_source_events'::regclass "
                            "AND conname IN ("
                            "'ck_cache_target_source_events_target_lock_version',"
                            "'ck_cache_target_source_events_applied_target_receipt')"
                        )
                    )
                ).scalars()
            )
            trigger = await connection.scalar(
                text(
                    "SELECT tgname FROM pg_trigger "
                    "WHERE tgrelid = "
                    "'ops.poi_cache_target_source_events'::regclass "
                    "AND tgname = "
                    "'trg_poi_cache_target_source_events_append_only' "
                    "AND NOT tgisinternal"
                )
            )
        assert receipts == {_ACTIVE_EVENT_ID: 5, _DELETED_EVENT_ID: 9}
        assert constraints == {
            "ck_cache_target_source_events_target_lock_version",
            "ck_cache_target_source_events_applied_target_receipt",
        }
        assert trigger == "trg_poi_cache_target_source_events_append_only"

        column = PoiCacheTargetSourceEventRow.__table__.c.target_lock_version
        assert isinstance(column.type, BigInteger)
        assert column.nullable
        assert any(
            isinstance(constraint, CheckConstraint)
            and "target_lock_version > 0" in str(constraint.sqltext)
            for constraint in PoiCacheTargetSourceEventRow.__table__.constraints
        )

        async with target_engine.begin() as connection:
            with pytest.raises(DBAPIError, match="append-only"):
                async with connection.begin_nested():
                    await connection.execute(
                        text(
                            "UPDATE ops.poi_cache_target_source_events "
                            "SET target_lock_version = 10 "
                            "WHERE event_id = CAST(:event_id AS uuid)"
                        ),
                        {"event_id": _DELETED_EVENT_ID},
                    )

        await target_engine.dispose()
        await asyncio.to_thread(
            _run_alembic,
            target_dsn,
            _PRE_REVISION,
            downgrade=True,
        )
        target_engine = make_async_engine(target_dsn)
        async with target_engine.begin() as connection:
            column_after_downgrade = await connection.scalar(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = 'ops' "
                    "AND table_name = 'poi_cache_target_source_events' "
                    "AND column_name = 'target_lock_version'"
                )
            )
            await connection.execute(
                text(
                    "UPDATE ops.poi_cache_targets "
                    "SET name = 'drifted', updated_at = updated_at + interval '1 second' "
                    "WHERE target_id = CAST(:target_id AS uuid)"
                ),
                {"target_id": _DELETED_TARGET_ID},
            )
        assert column_after_downgrade is None

        await target_engine.dispose()
        with pytest.raises(IntegrityError, match="source receipt backfill drift"):
            await asyncio.to_thread(_run_alembic, target_dsn, _TARGET_REVISION)
    finally:
        await target_engine.dispose()
        async with admin_engine.connect() as connection:
            autocommit = await connection.execution_options(isolation_level="AUTOCOMMIT")
            await autocommit.execute(
                text(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)')
            )
        await admin_engine.dispose()
