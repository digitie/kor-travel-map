"""Alembic 0050 pipeline cancellation schema와 strict downgrade 검증."""

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

_PRE_REVISION = "0049_refresh_stale_after"
_TARGET_REVISION = "0050_pipeline_cancellations"


def _run_alembic(dsn: str, revision: str, *, downgrade: bool = False) -> None:
    root = Path(__file__).resolve().parents[2]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    config.set_main_option("sqlalchemy.url", dsn)
    if downgrade:
        command.downgrade(config, revision)
    else:
        command.upgrade(config, revision)


async def test_pipeline_cancellation_upgrade_and_strict_downgrade(
    pg_container: Any,
) -> None:
    admin_dsn = normalize_async_dsn(pg_container.get_connection_url())
    database = f"pipeline_cancellation_migration_{uuid4().hex}"
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
        async with target_engine.connect() as connection:
            marker_before = (
                await connection.execute(
                    text(
                        """
                        SELECT column_name
                        FROM information_schema.columns
                        WHERE table_schema = 'ops'
                          AND table_name = 'import_jobs'
                          AND column_name = 'cancellation_id'
                        """
                    )
                )
            ).one_or_none()
        assert marker_before is None

        await target_engine.dispose()
        await asyncio.to_thread(_run_alembic, target_dsn, _TARGET_REVISION)
        target_engine = make_async_engine(target_dsn)
        cancellation_id = "11111111-1111-4111-8111-111111111111"
        job_id = "22222222-2222-4222-8222-222222222222"
        async with target_engine.begin() as connection:
            tables = {
                str(row.table_name)
                for row in await connection.execute(
                    text(
                        """
                        SELECT table_name
                        FROM information_schema.tables
                        WHERE table_schema = 'ops'
                          AND table_name LIKE 'pipeline_cancellation%'
                        """
                    )
                )
            }
            marker_columns = {
                str(row.column_name)
                for row in await connection.execute(
                    text(
                        """
                        SELECT column_name
                        FROM information_schema.columns
                        WHERE table_schema = 'ops'
                          AND table_name = 'feature_update_requests'
                          AND column_name LIKE 'cancellation%'
                        """
                    )
                )
            }
            indexes = {
                str(row.indexname)
                for row in await connection.execute(
                    text(
                        """
                        SELECT indexname
                        FROM pg_indexes
                        WHERE schemaname = 'ops'
                          AND tablename IN (
                            'pipeline_cancellations',
                            'pipeline_cancellation_members'
                          )
                        """
                    )
                )
            }
            revision = (
                await connection.execute(
                    text("SELECT version_num FROM alembic_version")
                )
            ).scalar_one()
            await connection.execute(
                text(
                    """
                    INSERT INTO ops.pipeline_cancellations (
                        cancellation_id, root_kind, root_id, requested_by
                    ) VALUES (
                        CAST(:cancellation_id AS uuid), 'import_job',
                        CAST(:job_id AS uuid), 'admin:test'
                    )
                    """
                ),
                {"cancellation_id": cancellation_id, "job_id": job_id},
            )
            await connection.execute(
                text(
                    """
                    INSERT INTO ops.import_jobs (
                        job_id, kind, payload, cancellation_id,
                        cancellation_requested_at, cancellation_requested_by
                    ) VALUES (
                        CAST(:job_id AS uuid), 'provider_load', '{}'::jsonb,
                        CAST(:cancellation_id AS uuid), now(), 'admin:test'
                    )
                    """
                ),
                {"cancellation_id": cancellation_id, "job_id": job_id},
            )

        assert tables == {
            "pipeline_cancellations",
            "pipeline_cancellation_members",
            "pipeline_cancellation_runs",
        }
        assert marker_columns == {
            "cancellation_id",
            "cancellation_reason",
            "cancellation_requested_at",
            "cancellation_requested_by",
        }
        assert {
            "uq_pipeline_cancellations_active_root",
            "idx_pipeline_cancellations_root_history",
            "idx_pipeline_cancellation_members_member",
        } <= indexes
        assert revision == _TARGET_REVISION

        await target_engine.dispose()
        with pytest.raises(RuntimeError, match="active pipeline cancellation"):
            await asyncio.to_thread(
                _run_alembic,
                target_dsn,
                _PRE_REVISION,
                downgrade=True,
            )

        target_engine = make_async_engine(target_dsn)
        async with target_engine.begin() as connection:
            await connection.execute(
                text(
                    """
                    UPDATE ops.pipeline_cancellations
                    SET status = 'retryable', finished_at = now(), updated_at = now()
                    WHERE cancellation_id = CAST(:cancellation_id AS uuid)
                    """
                ),
                {"cancellation_id": cancellation_id},
            )
        await target_engine.dispose()
        with pytest.raises(RuntimeError, match="active pipeline cancellation"):
            await asyncio.to_thread(
                _run_alembic,
                target_dsn,
                _PRE_REVISION,
                downgrade=True,
            )

        target_engine = make_async_engine(target_dsn)
        async with target_engine.begin() as connection:
            await connection.execute(
                text(
                    """
                    UPDATE ops.import_jobs
                    SET status = 'done', finished_at = now()
                    WHERE job_id = CAST(:job_id AS uuid)
                    """
                ),
                {"job_id": job_id},
            )
            await connection.execute(
                text(
                    """
                    UPDATE ops.pipeline_cancellations
                    SET status = 'completed', updated_at = now()
                    WHERE cancellation_id = CAST(:cancellation_id AS uuid)
                    """
                ),
                {"cancellation_id": cancellation_id},
            )
        await target_engine.dispose()
        await asyncio.to_thread(
            _run_alembic,
            target_dsn,
            _PRE_REVISION,
            downgrade=True,
        )

        target_engine = make_async_engine(target_dsn)
        async with target_engine.connect() as connection:
            tables_after = (
                await connection.execute(
                    text(
                        """
                        SELECT table_name
                        FROM information_schema.tables
                        WHERE table_schema = 'ops'
                          AND table_name LIKE 'pipeline_cancellation%'
                        """
                    )
                )
            ).all()
            marker_after = (
                await connection.execute(
                    text(
                        """
                        SELECT column_name
                        FROM information_schema.columns
                        WHERE table_schema = 'ops'
                          AND table_name = 'import_jobs'
                          AND column_name = 'cancellation_id'
                        """
                    )
                )
            ).one_or_none()
        assert tables_after == []
        assert marker_after is None
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
