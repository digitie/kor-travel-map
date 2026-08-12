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
                            'pipeline_cancellation_members',
                            'import_jobs',
                            'feature_update_requests'
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
            "idx_pipeline_cancellations_previous",
            "idx_pipeline_cancellation_members_member",
            "idx_pipeline_cancellation_members_run",
            "idx_import_jobs_cancellation_id",
            "idx_feature_update_requests_cancellation_id",
        } <= indexes
        assert revision == _TARGET_REVISION

        # downgrade가 active 검사 전에 관련 테이블을 강하게 잠근다. 아직 commit되지
        # 않은 marker writer가 끝나기 전에는 검사/DDL이 진행되지 않아야 하며, commit
        # 뒤에는 그 active 상태를 반드시 보고 거부해야 한다.
        writer = await target_engine.connect()
        writer_tx = await writer.begin()
        await writer.execute(
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
        await writer.execute(
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
        downgrade_task = asyncio.create_task(
            asyncio.to_thread(
                _run_alembic,
                target_dsn,
                _PRE_REVISION,
                downgrade=True,
            )
        )
        # Alembic process bootstrap itself can take longer than one second on a
        # contended CI worker.  This is a synchronization gate, not a
        # performance assertion: wait for the actual blocked lock with a
        # bounded deadline before releasing the writer transaction.
        downgrade_is_waiting = False
        wait_deadline = asyncio.get_running_loop().time() + 5.0
        async with target_engine.connect() as probe:
            while asyncio.get_running_loop().time() < wait_deadline:
                downgrade_is_waiting = bool(
                    await probe.scalar(
                        text(
                            """
                            SELECT EXISTS (
                                SELECT 1
                                FROM pg_locks AS lock
                                JOIN pg_class AS relation
                                  ON relation.oid = lock.relation
                                JOIN pg_namespace AS namespace
                                  ON namespace.oid = relation.relnamespace
                                WHERE namespace.nspname = 'ops'
                                  AND relation.relname = 'pipeline_cancellations'
                                  AND lock.mode = 'AccessExclusiveLock'
                                  AND NOT lock.granted
                            )
                            """
                        )
                    )
                )
                if downgrade_is_waiting:
                    break
                await asyncio.sleep(0.01)
        assert downgrade_is_waiting is True
        assert downgrade_task.done() is False
        await writer_tx.commit()
        await writer.close()
        with pytest.raises(RuntimeError, match="active pipeline cancellation"):
            await downgrade_task

        await target_engine.dispose()
        target_engine = make_async_engine(target_dsn)
        async with target_engine.begin() as connection:
            await connection.execute(
                text(
                    """
                    UPDATE ops.pipeline_cancellations
                    SET status = 'retryable',
                        error = '{"code":"DAGSTER_UNAVAILABLE","message":"retry"}'::jsonb,
                        finished_at = now(), updated_at = now()
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
                    SET status = 'completed', error = NULL, updated_at = now()
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
