"""0057 canonical import-job event scope migration 회귀 검증."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import uuid4

import pytest
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError

from alembic import command
from kortravelmap.infra.db import make_async_engine, normalize_async_dsn

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = pytest.mark.integration

_PRE_REVISION = "0056_refresh_policy_revision"
_TARGET_REVISION = "0057_import_job_event_scope"


def _run_alembic(dsn: str, revision: str, *, downgrade: bool = False) -> None:
    root = Path(__file__).resolve().parents[2]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    # 아카이브 체인 전용 그래프 — `alembic/legacy_versions/README.md`. `versions/`와 함께 담으면 revision이 중복된다.
    config.set_main_option("version_locations", str(root / "alembic" / "legacy_versions"))
    config.set_main_option("sqlalchemy.url", dsn)
    if downgrade:
        command.downgrade(config, revision)
    else:
        command.upgrade(config, revision)


async def _create_database(pg_container: Any, prefix: str) -> tuple[str, AsyncEngine]:
    admin_dsn = normalize_async_dsn(pg_container.get_connection_url())
    database = f"{prefix}_{uuid4().hex}"
    target_dsn = (
        make_url(admin_dsn)
        .set(database=database)
        .render_as_string(hide_password=False)
    )
    admin_engine = make_async_engine(admin_dsn)
    async with admin_engine.connect() as connection:
        autocommit = await connection.execution_options(isolation_level="AUTOCOMMIT")
        await autocommit.execute(text(f'CREATE DATABASE "{database}"'))
    await admin_engine.dispose()
    return target_dsn, make_async_engine(target_dsn)


async def _drop_database(pg_container: Any, dsn: str) -> None:
    admin_dsn = normalize_async_dsn(pg_container.get_connection_url())
    database = make_url(dsn).database
    admin_engine = make_async_engine(admin_dsn)
    try:
        async with admin_engine.connect() as connection:
            autocommit = await connection.execution_options(isolation_level="AUTOCOMMIT")
            await autocommit.execute(text(f'DROP DATABASE IF EXISTS "{database}"'))
    finally:
        await admin_engine.dispose()


async def _seed_pre_0057_rows(engine: AsyncEngine) -> None:
    async with engine.begin() as connection:
        await connection.execute(
            text(
                """
                INSERT INTO ops.import_jobs (
                  job_id, kind, payload, status, provider, dataset_key,
                  sync_scope, trigger_kind
                ) VALUES
                ('57000000-0000-4000-8000-000000000001',
                 'feature_update_request', '{}'::jsonb, 'done',
                 'provider-a', 'dataset-a', 'external_system:alpha',
                 'update_request'),
                ('57000000-0000-4000-8000-000000000002',
                 'manual_provider_load', '{}'::jsonb, 'done',
                 'provider-a', 'dataset-a', NULL, 'manual')
                """
            )
        )
        await connection.execute(
            text(
                """
                INSERT INTO ops.feature_update_requests (
                  request_id, scope_type, scope, run_mode, job_id
                ) VALUES (
                  '57000000-0000-4000-8000-000000000011',
                  'provider_dataset',
                  '{"type":"provider_dataset","provider":"provider-a",'
                  '"dataset_key":"dataset-a",'
                  '"sync_scope":"external_system:alpha"}'::jsonb,
                  'queued', '57000000-0000-4000-8000-000000000001'
                )
                """
            )
        )
        await connection.execute(
            text(
                """
                INSERT INTO ops.import_job_events (
                  event_id, job_id, provider, dataset_key, level, message
                ) VALUES
                ('57000000-0000-4000-8000-000000000021',
                 '57000000-0000-4000-8000-000000000001',
                 NULL, NULL, 'info', '0052-style canonical event'),
                ('57000000-0000-4000-8000-000000000022',
                 '57000000-0000-4000-8000-000000000002',
                 'provider-a', 'dataset-a', 'info', 'general event')
                """
            )
        )


async def test_0057_fresh_upgrade_has_single_head_and_typed_scope_schema(
    pg_container: Any,
) -> None:
    dsn, engine = await _create_database(pg_container, "event_scope_fresh")
    try:
        await engine.dispose()
        await asyncio.to_thread(_run_alembic, dsn, _TARGET_REVISION)
        engine = make_async_engine(dsn)
        async with engine.connect() as connection:
            revision = (
                await connection.execute(text("SELECT version_num FROM alembic_version"))
            ).scalar_one()
            column_exists = (
                await connection.execute(
                    text(
                        "SELECT EXISTS (SELECT 1 FROM information_schema.columns "
                        "WHERE table_schema='ops' "
                        "AND table_name='import_job_events' "
                        "AND column_name='sync_scope')"
                    )
                )
            ).scalar_one()
            index_definition = (
                await connection.execute(
                    text(
                        "SELECT indexdef FROM pg_indexes WHERE schemaname='ops' "
                        "AND indexname="
                        "'idx_import_job_events_provider_dataset_scope_time'"
                    )
                )
            ).scalar_one()
            dataset_only_index_exists = (
                await connection.execute(
                    text(
                        "SELECT EXISTS (SELECT 1 FROM pg_indexes "
                        "WHERE schemaname='ops' AND indexname="
                        "'idx_import_job_events_dataset_time')"
                    )
                )
            ).scalar_one()
            assert revision == _TARGET_REVISION
            assert column_exists is True
            assert (
                "provider, dataset_key, sync_scope, occurred_at DESC, event_id DESC"
                in index_definition
            )
            assert "sync_scope IS NOT NULL" in index_definition
            assert "provider IS NOT NULL" in index_definition
            assert "dataset_key IS NOT NULL" in index_definition
            assert "quarantined_at IS NULL" in index_definition
            assert dataset_only_index_exists is False
    finally:
        await engine.dispose()
        await _drop_database(pg_container, dsn)


async def test_0057_backfill_trigger_constraints_and_downgrade(
    pg_container: Any,
) -> None:
    dsn, engine = await _create_database(pg_container, "event_scope_upgrade")
    try:
        await asyncio.to_thread(_run_alembic, dsn, _PRE_REVISION)
        await _seed_pre_0057_rows(engine)
        await engine.dispose()
        await asyncio.to_thread(_run_alembic, dsn, _TARGET_REVISION)
        engine = make_async_engine(dsn)
        async with engine.begin() as connection:
            identities = {
                str(row.event_id): (row.provider, row.dataset_key, row.sync_scope)
                for row in await connection.execute(
                    text(
                        "SELECT event_id, provider, dataset_key, sync_scope "
                        "FROM ops.import_job_events "
                        "ORDER BY event_id"
                    )
                )
            }
            assert identities == {
                "57000000-0000-4000-8000-000000000021": (
                    "provider-a",
                    "dataset-a",
                    "external_system:alpha",
                ),
                "57000000-0000-4000-8000-000000000022": (
                    "provider-a",
                    "dataset-a",
                    None,
                ),
            }

            inserted = (
                await connection.execute(
                    text(
                        """
                        INSERT INTO ops.import_job_events (
                          event_id, job_id, level, message
                        ) VALUES (
                          '57000000-0000-4000-8000-000000000023',
                          '57000000-0000-4000-8000-000000000001',
                          'info', 'trigger copied identity'
                        )
                        RETURNING provider, dataset_key, sync_scope
                        """
                    )
                )
            ).one()
            assert inserted.provider == "provider-a"
            assert inserted.dataset_key == "dataset-a"
            assert inserted.sync_scope == "external_system:alpha"

            with pytest.raises(IntegrityError):
                async with connection.begin_nested():
                    await connection.execute(
                        text(
                            """
                            INSERT INTO ops.import_job_events (
                              job_id, provider, dataset_key, level, message
                            ) VALUES (
                              '57000000-0000-4000-8000-000000000001',
                              'provider-b', 'dataset-a', 'info', 'wrong pair'
                            )
                            """
                        )
                    )
            with pytest.raises(IntegrityError):
                async with connection.begin_nested():
                    await connection.execute(
                        text(
                            """
                            INSERT INTO ops.import_job_events (
                              job_id, sync_scope, level, message
                            ) VALUES (
                              '57000000-0000-4000-8000-000000000001',
                              'target_grids', 'info', 'wrong scope'
                            )
                            """
                        )
                    )
            with pytest.raises(IntegrityError):
                async with connection.begin_nested():
                    await connection.execute(
                        text(
                            """
                            INSERT INTO ops.import_job_events (
                              job_id, sync_scope, level, message
                            ) VALUES (
                              '57000000-0000-4000-8000-000000000002',
                              'dataset_wide', 'info', 'general job scope'
                            )
                            """
                        )
                    )
            with pytest.raises(IntegrityError):
                async with connection.begin_nested():
                    await connection.execute(
                        text(
                            "UPDATE ops.import_job_events "
                            "SET sync_scope='target_grids' "
                            "WHERE event_id="
                            "'57000000-0000-4000-8000-000000000021'"
                        )
                    )

        await engine.dispose()
        await asyncio.to_thread(
            _run_alembic,
            dsn,
            _PRE_REVISION,
            downgrade=True,
        )
        engine = make_async_engine(dsn)
        async with engine.connect() as connection:
            column_exists = (
                await connection.execute(
                    text(
                        "SELECT EXISTS (SELECT 1 FROM information_schema.columns "
                        "WHERE table_schema='ops' "
                        "AND table_name='import_job_events' "
                        "AND column_name='sync_scope')"
                    )
                )
            ).scalar_one()
            dataset_only_index_definition = (
                await connection.execute(
                    text(
                        "SELECT indexdef FROM pg_indexes "
                        "WHERE schemaname='ops' AND indexname="
                        "'idx_import_job_events_dataset_time'"
                    )
                )
            ).scalar_one()
            assert column_exists is False
            assert (
                "(dataset_key, occurred_at DESC, event_id DESC)"
                in dataset_only_index_definition
            )
            assert "dataset_key IS NOT NULL" in dataset_only_index_definition
            assert "quarantined_at IS NULL" in dataset_only_index_definition
    finally:
        await engine.dispose()
        await _drop_database(pg_container, dsn)


async def test_0057_rejects_legacy_event_pair_drift(pg_container: Any) -> None:
    dsn, engine = await _create_database(pg_container, "event_scope_drift")
    try:
        await asyncio.to_thread(_run_alembic, dsn, _PRE_REVISION)
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    """
                    INSERT INTO ops.import_jobs (
                      job_id, kind, payload, status, provider, dataset_key
                    ) VALUES (
                      '57000000-0000-4000-8000-000000000091',
                      'manual_provider_load', '{}'::jsonb, 'done',
                      'provider-a', 'dataset-a'
                    )
                    """
                )
            )
            await connection.execute(
                text(
                    """
                    INSERT INTO ops.import_job_events (
                      event_id, job_id, provider, dataset_key, level, message
                    ) VALUES (
                      '57000000-0000-4000-8000-000000000092',
                      '57000000-0000-4000-8000-000000000091',
                      'provider-b', 'dataset-b', 'info', 'drifted event'
                    )
                    """
                )
            )
        await engine.dispose()
        with pytest.raises(RuntimeError, match="typed pair differs"):
            await asyncio.to_thread(_run_alembic, dsn, _TARGET_REVISION)
        engine = make_async_engine(dsn)
        async with engine.connect() as connection:
            revision = (
                await connection.execute(text("SELECT version_num FROM alembic_version"))
            ).scalar_one()
            assert revision == _PRE_REVISION
    finally:
        await engine.dispose()
        await _drop_database(pg_container, dsn)
