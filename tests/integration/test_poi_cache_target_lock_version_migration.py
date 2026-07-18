"""0058 POI cache target lock_version migration 회귀."""

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

_PRE_REVISION = "0057_import_job_event_scope"
_TARGET_REVISION = "0058_poi_target_lock_version"


def _run_alembic(dsn: str, revision: str, *, downgrade: bool = False) -> None:
    root = Path(__file__).resolve().parents[2]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    config.set_main_option("sqlalchemy.url", dsn)
    if downgrade:
        command.downgrade(config, revision)
    else:
        command.upgrade(config, revision)


async def test_lock_version_backfill_trigger_and_downgrade(pg_container: Any) -> None:
    admin_dsn = normalize_async_dsn(pg_container.get_connection_url())
    database = f"poi_target_lock_version_{uuid4().hex}"
    target_dsn = make_url(admin_dsn).set(database=database).render_as_string(
        hide_password=False
    )
    admin_engine = make_async_engine(admin_dsn)
    async with admin_engine.connect() as connection:
        autocommit = await connection.execution_options(isolation_level="AUTOCOMMIT")
        await autocommit.execute(text(f'CREATE DATABASE "{database}"'))

    target_engine = make_async_engine(target_dsn)
    try:
        await asyncio.to_thread(_run_alembic, target_dsn, _PRE_REVISION)
        async with target_engine.begin() as connection:
            await connection.execute(
                text(
                    """
                    INSERT INTO ops.poi_cache_targets (
                      external_system, target_key, lon, lat, coord, coord_key, radius_km
                    ) VALUES (
                      'migration-test', 'legacy', 126.978, 37.5665,
                      x_extension.ST_SetSRID(
                        x_extension.ST_MakePoint(126.978, 37.5665), 4326
                      ),
                      '126.978000:37.566500:p6', 5
                    )
                    """
                )
            )

        await target_engine.dispose()
        await asyncio.to_thread(_run_alembic, target_dsn, _TARGET_REVISION)
        target_engine = make_async_engine(target_dsn)
        async with target_engine.begin() as connection:
            initial = await connection.scalar(
                text(
                    "SELECT lock_version FROM ops.poi_cache_targets "
                    "WHERE external_system = 'migration-test'"
                )
            )
            forced = await connection.scalar(
                text(
                    "UPDATE ops.poi_cache_targets SET lock_version = 900, name = 'updated' "
                    "WHERE external_system = 'migration-test' RETURNING lock_version"
                )
            )
            trigger = await connection.scalar(
                text(
                    "SELECT tgname FROM pg_trigger "
                    "WHERE tgrelid = 'ops.poi_cache_targets'::regclass "
                    "AND tgname = 'trg_poi_cache_targets_lock_version' "
                    "AND NOT tgisinternal"
                )
            )
            constraint = await connection.scalar(
                text(
                    "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                    "WHERE conrelid = 'ops.poi_cache_targets'::regclass "
                    "AND contype = 'c' "
                    "AND pg_get_constraintdef(oid) LIKE '%lock_version >= 1%'"
                )
            )
        assert initial == 1
        assert forced == 2
        assert trigger == "trg_poi_cache_targets_lock_version"
        assert constraint is not None
        assert "lock_version >= 1" in constraint

        await target_engine.dispose()
        await asyncio.to_thread(
            _run_alembic,
            target_dsn,
            _PRE_REVISION,
            downgrade=True,
        )
        target_engine = make_async_engine(target_dsn)
        async with target_engine.connect() as connection:
            column = await connection.scalar(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = 'ops' AND table_name = 'poi_cache_targets' "
                    "AND column_name = 'lock_version'"
                )
            )
            trigger = await connection.scalar(
                text(
                    "SELECT to_regprocedure("
                    "'ops.force_poi_cache_target_lock_version()')"
                )
            )
        assert column is None
        assert trigger is None
    finally:
        await target_engine.dispose()
        async with admin_engine.connect() as connection:
            autocommit = await connection.execution_options(
                isolation_level="AUTOCOMMIT"
            )
            await autocommit.execute(
                text(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)')
            )
        await admin_engine.dispose()
