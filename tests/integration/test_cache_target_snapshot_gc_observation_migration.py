"""0078 GC 관측 이력의 app rollback 및 명시적 downgrade/forward 경로."""

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

_PRE_REVISION = "0077_cache_target_snapshot_gc"
_TARGET_REVISION = "0078_cache_target_gc_observe"


def _run_alembic(dsn: str, revision: str, *, downgrade: bool = False) -> None:
    root = Path(__file__).resolve().parents[2]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    config.set_main_option("sqlalchemy.url", dsn)
    if downgrade:
        command.downgrade(config, revision)
    else:
        command.upgrade(config, revision)


async def test_0078_app_rollback_preserves_data_and_schema_cycle_recovers(
    pg_container: Any,
) -> None:
    admin_dsn = normalize_async_dsn(pg_container.get_connection_url())
    database = f"cache_target_gc_0078_{uuid4().hex}"
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
        await asyncio.to_thread(_run_alembic, target_dsn, _TARGET_REVISION)
        target_engine = make_async_engine(target_dsn)
        async with target_engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO ops.poi_cache_target_snapshot_gc_observations "
                    "(dagster_run_id, referenced_items, referenced_headers, "
                    "growth_baseline_eligible, growth_min_interval_seconds) "
                    "VALUES ('app-rollback-preserved', 10, 1, true, 300)"
                )
            )
        # 앱만 이전 버전으로 되돌리는 정상 rollback은 DB migration을 실행하지 않는다.
        async with target_engine.connect() as connection:
            preserved = await connection.scalar(
                text(
                    "SELECT referenced_items FROM "
                    "ops.poi_cache_target_snapshot_gc_observations "
                    "WHERE dagster_run_id = 'app-rollback-preserved'"
                )
            )
        assert preserved == 10

        await target_engine.dispose()
        await asyncio.to_thread(
            _run_alembic, target_dsn, _PRE_REVISION, downgrade=True
        )
        target_engine = make_async_engine(target_dsn)
        async with target_engine.connect() as connection:
            dropped = await connection.scalar(
                text(
                    "SELECT to_regclass("
                    "'ops.poi_cache_target_snapshot_gc_observations')"
                )
            )
        assert dropped is None

        await target_engine.dispose()
        await asyncio.to_thread(_run_alembic, target_dsn, _TARGET_REVISION)
        target_engine = make_async_engine(target_dsn)
        async with target_engine.connect() as connection:
            restored = await connection.scalar(
                text(
                    "SELECT to_regclass("
                    "'ops.poi_cache_target_snapshot_gc_observations')"
                )
            )
            row_count = await connection.scalar(
                text(
                    "SELECT count(*) FROM "
                    "ops.poi_cache_target_snapshot_gc_observations"
                )
            )
            revision = await connection.scalar(
                text("SELECT version_num FROM alembic_version")
            )
        assert str(restored) == "ops.poi_cache_target_snapshot_gc_observations"
        assert row_count == 0
        assert revision == _TARGET_REVISION
    finally:
        await target_engine.dispose()
        async with admin_engine.connect() as connection:
            autocommit = await connection.execution_options(isolation_level="AUTOCOMMIT")
            await autocommit.execute(
                text(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)')
            )
        await admin_engine.dispose()
