"""0048 ``import_jobs.dagster_run_id`` 실컬럼 + 백필 migration 검증 (ADR-064)."""

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

_PRE_REVISION = "0047_notice_reconcile_stats"
_TARGET_REVISION = "0048_import_jobs_dagster_run_id"


def _run_alembic(dsn: str, revision: str, *, downgrade: bool = False) -> None:
    root = Path(__file__).resolve().parents[2]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    config.set_main_option("sqlalchemy.url", dsn)
    if downgrade:
        command.downgrade(config, revision)
    else:
        command.upgrade(config, revision)


def _alembic_heads() -> list[str]:
    from alembic.script import ScriptDirectory

    root = Path(__file__).resolve().parents[2]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    return list(ScriptDirectory.from_config(config).get_heads())


async def test_dagster_run_id_backfill_upgrade_and_downgrade(
    pg_container: Any,
) -> None:
    admin_dsn = normalize_async_dsn(pg_container.get_connection_url())
    database = f"dagster_run_id_migration_{uuid4().hex}"
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
            column_before = (
                await connection.execute(
                    text(
                        """
                        SELECT column_name FROM information_schema.columns
                        WHERE table_schema = 'ops'
                          AND table_name = 'import_jobs'
                          AND column_name = 'dagster_run_id'
                        """
                    )
                )
            ).one_or_none()
            assert column_before is None
            # 레거시 행 4종: 신규 키 / 레거시 run_id 키 / 빈 문자열 / 키 없음.
            await connection.execute(
                text(
                    """
                    INSERT INTO ops.import_jobs (job_id, kind, payload) VALUES
                    ('aaaaaaaa-0000-4000-8000-000000000001', 'k',
                     '{"dagster_run_id": "run-new"}'::jsonb),
                    ('aaaaaaaa-0000-4000-8000-000000000002', 'k',
                     '{"run_id": "run-legacy"}'::jsonb),
                    ('aaaaaaaa-0000-4000-8000-000000000003', 'k',
                     '{"dagster_run_id": ""}'::jsonb),
                    ('aaaaaaaa-0000-4000-8000-000000000004', 'k',
                     '{"provider": "python-kma-api"}'::jsonb)
                    """
                )
            )

        await target_engine.dispose()
        await asyncio.to_thread(_run_alembic, target_dsn, _TARGET_REVISION)
        target_engine = make_async_engine(target_dsn)
        async with target_engine.begin() as connection:
            backfilled = {
                str(row.job_id): row.dagster_run_id
                for row in await connection.execute(
                    text(
                        "SELECT job_id, dagster_run_id FROM ops.import_jobs "
                        "ORDER BY job_id"
                    )
                )
            }
            index_definition = (
                await connection.execute(
                    text(
                        """
                        SELECT indexdef FROM pg_indexes
                        WHERE schemaname = 'ops'
                          AND tablename = 'import_jobs'
                          AND indexname = 'idx_import_jobs_dagster_run_id'
                        """
                    )
                )
            ).scalar_one()
            revision = (
                await connection.execute(
                    text("SELECT version_num FROM alembic_version")
                )
            ).scalar_one()

        assert backfilled == {
            "aaaaaaaa-0000-4000-8000-000000000001": "run-new",
            "aaaaaaaa-0000-4000-8000-000000000002": "run-legacy",
            "aaaaaaaa-0000-4000-8000-000000000003": None,
            "aaaaaaaa-0000-4000-8000-000000000004": None,
        }
        assert "WHERE (dagster_run_id IS NOT NULL)" in index_definition
        assert revision == _TARGET_REVISION

        # 단일 head — 0048이 0047 위의 유일한 head여야 한다.
        assert _alembic_heads() == [_TARGET_REVISION]

        await target_engine.dispose()
        await asyncio.to_thread(
            _run_alembic, target_dsn, _PRE_REVISION, downgrade=True
        )
        target_engine = make_async_engine(target_dsn)
        async with target_engine.connect() as connection:
            column_after = (
                await connection.execute(
                    text(
                        """
                        SELECT column_name FROM information_schema.columns
                        WHERE table_schema = 'ops'
                          AND table_name = 'import_jobs'
                          AND column_name = 'dagster_run_id'
                        """
                    )
                )
            ).one_or_none()
            surviving_rows = (
                await connection.execute(
                    text("SELECT count(*) FROM ops.import_jobs")
                )
            ).scalar_one()
        assert column_after is None
        assert surviving_rows == 4
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
