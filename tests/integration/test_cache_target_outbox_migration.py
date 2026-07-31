"""0073 cache target outbox migration 회귀."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import make_url

from alembic import command
from kortravelmap.infra.db import make_async_engine, normalize_async_dsn

pytestmark = pytest.mark.integration

_PRE_REVISION = "0072_curation_provenance"
_TARGET_REVISION = "0073_cache_target_outbox"


def _run_alembic(dsn: str, revision: str, *, downgrade: bool = False) -> None:
    root = Path(__file__).resolve().parents[2]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    config.set_main_option("sqlalchemy.url", dsn)
    if downgrade:
        command.downgrade(config, revision)
    else:
        command.upgrade(config, revision)


async def test_0073_phase_schema_and_downgrade(pg_container: Any) -> None:
    admin_dsn = normalize_async_dsn(pg_container.get_connection_url())
    database = f"cache_target_0073_{uuid4().hex}"
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
        await asyncio.to_thread(_run_alembic, target_dsn, _TARGET_REVISION)
        target_engine = make_async_engine(target_dsn)
        async with target_engine.connect() as connection:
            revision = await connection.scalar(text("SELECT version_num FROM alembic_version"))
            phase_column = await connection.scalar(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = 'ops' "
                    "AND table_name = 'poi_cache_target_reconciliation_requests' "
                    "AND column_name = 'phase_version'"
                )
            )
            status_constraint = await connection.scalar(
                text(
                    "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                    "WHERE conrelid = "
                    "'ops.poi_cache_target_reconciliation_requests'::regclass "
                    "AND conname = "
                    "'ck_cache_target_reconciliation_requests_status'"
                )
            )
            lifecycle_constraint = await connection.scalar(
                text(
                    "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                    "WHERE conrelid = "
                    "'ops.poi_cache_target_reconciliation_requests'::regclass "
                    "AND conname = "
                    "'ck_cache_target_reconciliation_requests_lifecycle'"
                )
            )
            snapshot_item_table = await connection.scalar(
                text("SELECT to_regclass('ops.poi_cache_target_snapshot_items')")
            )
            append_only_function = await connection.scalar(
                text("SELECT to_regprocedure('ops.reject_cache_target_history_mutation()')")
            )
        assert revision == _TARGET_REVISION
        assert phase_column == "phase_version"
        assert status_constraint is not None
        assert "preparing" in status_constraint
        assert "running" in status_constraint
        assert lifecycle_constraint is not None
        assert "snapshot_id IS NULL" in lifecycle_constraint
        assert "snapshot_id IS NOT NULL" in lifecycle_constraint
        assert str(snapshot_item_table) == "ops.poi_cache_target_snapshot_items"
        assert str(append_only_function) == "ops.reject_cache_target_history_mutation()"

        await target_engine.dispose()
        await asyncio.to_thread(
            _run_alembic,
            target_dsn,
            _PRE_REVISION,
            downgrade=True,
        )
        target_engine = make_async_engine(target_dsn)
        async with target_engine.connect() as connection:
            request_table = await connection.scalar(
                text("SELECT to_regclass('ops.poi_cache_target_reconciliation_requests')")
            )
            append_only_function = await connection.scalar(
                text("SELECT to_regprocedure('ops.reject_cache_target_history_mutation()')")
            )
            revision = await connection.scalar(text("SELECT version_num FROM alembic_version"))
        assert request_table is None
        assert append_only_function is None
        assert revision == _PRE_REVISION
    finally:
        await target_engine.dispose()
        async with admin_engine.connect() as connection:
            autocommit = await connection.execution_options(isolation_level="AUTOCOMMIT")
            await autocommit.execute(
                text(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)')
            )
        await admin_engine.dispose()
