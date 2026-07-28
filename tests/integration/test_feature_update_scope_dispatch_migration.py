"""0053 canonical sync scope/dispatch intent migration 회귀 검증."""

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

_PRE_REVISION = "0052_pipeline_projection_access"
_TARGET_REVISION = "0053_update_scope_dispatch"


def _run_alembic(dsn: str, revision: str, *, downgrade: bool = False) -> None:
    root = Path(__file__).resolve().parents[2]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    config.set_main_option("sqlalchemy.url", dsn)
    if downgrade:
        command.downgrade(config, revision)
    else:
        command.upgrade(config, revision)


async def _create_database(pg_container: Any, prefix: str) -> tuple[str, AsyncEngine]:
    admin_dsn = normalize_async_dsn(pg_container.get_connection_url())
    database = f"{prefix}_{uuid4().hex}"
    target_dsn = make_url(admin_dsn).set(database=database).render_as_string(hide_password=False)
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


async def test_0053_backfills_scope_dispatch_and_installs_typed_invariants(
    pg_container: Any,
) -> None:
    dsn, engine = await _create_database(pg_container, "scope_dispatch")
    try:
        await asyncio.to_thread(_run_alembic, dsn, _PRE_REVISION)
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    """
                    INSERT INTO ops.import_jobs (
                      job_id, kind, payload, status, provider, dataset_key,
                      trigger_kind, dagster_run_id
                    ) VALUES
                    ('53000000-0000-4000-8000-000000000001',
                     'feature_update_request', '{}'::jsonb, 'done',
                     'provider-a', 'dataset-a', 'update_request', NULL),
                    ('53000000-0000-4000-8000-000000000002',
                     'feature_update_request', '{}'::jsonb, 'queued',
                     'provider-b', 'dataset-b', 'update_request', NULL),
                    ('53000000-0000-4000-8000-000000000003',
                     'feature_update_request', '{}'::jsonb, 'done',
                     NULL, NULL, 'update_request', NULL),
                    ('53000000-0000-4000-8000-000000000004',
                     'feature_update_request', '{}'::jsonb, 'done',
                     'python-kma-api', 'kma_short_forecast', 'update_request', NULL),
                    ('53000000-0000-4000-8000-000000000005',
                     'feature_update_request', '{}'::jsonb, 'done',
                     'python-kma-api', 'kma_ultra_short_nowcast', 'update_request', NULL),
                    ('53000000-0000-4000-8000-000000000006',
                     'feature_update_request', '{}'::jsonb, 'done',
                     'python-kma-api', 'kma_ultra_short_forecast', 'update_request', NULL)
                    """
                )
            )
            await connection.execute(
                text(
                    """
                    INSERT INTO ops.feature_update_requests (
                      request_id, scope_type, scope, run_mode, job_id, created_at
                    ) VALUES
                    ('53000000-0000-4000-8000-000000000011',
                     'provider_dataset',
                     '{"type":"provider_dataset","provider":"provider-a",'
                     '"dataset_key":"dataset-a","sync_scope":"scope-a"}'::jsonb,
                     'queued', '53000000-0000-4000-8000-000000000001',
                     '2026-07-17T00:00:00+00'::timestamptz),
                    ('53000000-0000-4000-8000-000000000012',
                     'provider_dataset',
                     '{"type":"provider_dataset","provider":"provider-b",'
                     '"dataset_key":"dataset-b"}'::jsonb,
                     'now', '53000000-0000-4000-8000-000000000002',
                     '2026-07-17T00:01:00+00'::timestamptz),
                    ('53000000-0000-4000-8000-000000000013',
                     'feature_ids',
                     '{"type":"feature_ids","feature_ids":[]}'::jsonb,
                     'now', '53000000-0000-4000-8000-000000000003',
                     '2026-07-17T00:02:00+00'::timestamptz),
                    ('53000000-0000-4000-8000-000000000014',
                     'provider_dataset',
                     '{"type":"provider_dataset","provider":"python-kma-api",'
                     '"dataset_key":"kma_short_forecast",'
                     '"sync_scope":"legacy-grid-alias"}'::jsonb,
                     'queued', '53000000-0000-4000-8000-000000000004',
                     '2026-07-17T00:03:00+00'::timestamptz),
                    ('53000000-0000-4000-8000-000000000015',
                     'provider_dataset',
                     '{"type":"provider_dataset","provider":"python-kma-api",'
                     '"dataset_key":"kma_ultra_short_nowcast"}'::jsonb,
                     'queued', '53000000-0000-4000-8000-000000000005',
                     '2026-07-17T00:04:00+00'::timestamptz),
                    ('53000000-0000-4000-8000-000000000016',
                     'provider_dataset',
                     '{"type":"provider_dataset","provider":"python-kma-api",'
                     '"dataset_key":"kma_ultra_short_forecast",'
                     '"sync_scope":"dataset_wide"}'::jsonb,
                     'queued', '53000000-0000-4000-8000-000000000006',
                     '2026-07-17T00:05:00+00'::timestamptz)
                    """
                )
            )

        await engine.dispose()
        await asyncio.to_thread(_run_alembic, dsn, _TARGET_REVISION)
        engine = make_async_engine(dsn)
        async with engine.begin() as connection:
            rows = {
                str(row.job_id): row
                for row in await connection.execute(
                    text(
                        "SELECT job_id, sync_scope, dispatch_requested_at "
                        "FROM ops.import_jobs ORDER BY job_id"
                    )
                )
            }
            index_definition = (
                await connection.execute(
                    text(
                        "SELECT indexdef FROM pg_indexes WHERE schemaname = 'ops' "
                        "AND indexname = 'uq_import_jobs_active_feature_update_scope'"
                    )
                )
            ).scalar_one()
            revision = (
                await connection.execute(text("SELECT version_num FROM alembic_version"))
            ).scalar_one()

            assert rows["53000000-0000-4000-8000-000000000001"].sync_scope == "dataset_wide"
            assert rows["53000000-0000-4000-8000-000000000001"].dispatch_requested_at is None
            assert rows["53000000-0000-4000-8000-000000000002"].sync_scope == "dataset_wide"
            assert (
                rows["53000000-0000-4000-8000-000000000002"].dispatch_requested_at.isoformat()
                == "2026-07-17T00:01:00+00:00"
            )
            assert rows["53000000-0000-4000-8000-000000000003"].sync_scope is None
            assert (
                rows["53000000-0000-4000-8000-000000000003"]
                .dispatch_requested_at.isoformat()
                == "2026-07-17T00:02:00+00:00"
            )
            assert rows["53000000-0000-4000-8000-000000000004"].sync_scope == "target_grids"
            assert rows["53000000-0000-4000-8000-000000000005"].sync_scope == "target_grids"
            assert rows["53000000-0000-4000-8000-000000000006"].sync_scope == "target_grids"
            raw_requested_scope = (
                await connection.execute(
                    text(
                        "SELECT scope->>'sync_scope' FROM ops.feature_update_requests "
                        "WHERE request_id = '53000000-0000-4000-8000-000000000014'"
                    )
                )
            ).scalar_one()
            assert raw_requested_scope == "legacy-grid-alias"
            assert "provider, dataset_key, sync_scope" in index_definition
            assert "status = ANY" in index_definition or "status IN" in index_definition
            assert revision == _TARGET_REVISION

            poi_insert = text(
                """
                INSERT INTO ops.poi_cache_targets (
                  external_system, target_key, lon, lat, coord, coord_key, radius_km
                ) VALUES (
                  :external_system, :target_key, 126.978, 37.5665,
                  x_extension.ST_SetSRID(
                    x_extension.ST_MakePoint(126.978, 37.5665), 4326
                  ),
                  '126.978000:37.566500:p6', 5.0
                )
                """
            )
            await connection.execute(
                poi_insert,
                {"external_system": "x" * 112, "target_key": "valid-max"},
            )
            for invalid_system, target_key in (
                (" invalid", "leading-space"),
                ("invalid\t", "trailing-tab"),
                ("\u00a0invalid", "leading-nbsp"),
                ("invalid\u2007", "trailing-figure-space"),
                ("x" * 113, "too-long"),
            ):
                with pytest.raises(IntegrityError):
                    async with connection.begin_nested():
                        await connection.execute(
                            poi_insert,
                            {
                                "external_system": invalid_system,
                                "target_key": target_key,
                            },
                        )

            with pytest.raises(IntegrityError):  # noqa: PT012 - 두 insert를 함께 rollback
                async with connection.begin_nested():
                    await connection.execute(
                        text(
                            """
                            INSERT INTO ops.import_jobs (
                              job_id, kind, payload, status, trigger_kind
                            ) VALUES (
                              '53000000-0000-4000-8000-000000000096',
                              'feature_update_request', '{}'::jsonb, 'done',
                              'update_request'
                            )
                            """
                        )
                    )

                    await connection.execute(
                        text(
                            """
                            INSERT INTO ops.feature_update_requests (
                              request_id, scope_type, scope, run_mode, job_id
                            ) VALUES (
                              '53000000-0000-4000-8000-000000000096',
                              'cache_target_keys',
                              jsonb_build_object(
                                'type', 'cache_target_keys',
                                'external_system', repeat('x', 113),
                                'target_keys', jsonb_build_array('target-1'),
                                'scope_mode', 'center_radius'
                              ),
                              'queued',
                              '53000000-0000-4000-8000-000000000096'
                            )
                            """
                        )
                    )

            with pytest.raises(IntegrityError):
                async with connection.begin_nested():
                    await connection.execute(
                        text(
                            """
                            INSERT INTO ops.import_jobs (
                              job_id, kind, payload, status, provider, dataset_key,
                              sync_scope, trigger_kind
                            ) VALUES (
                              '53000000-0000-4000-8000-000000000095',
                              'feature_update_request', '{}'::jsonb, 'done',
                              'provider-unicode', 'dataset-unicode',
                              'external_system:' || chr(160) || 'invalid',
                              'update_request'
                            )
                            """
                        )
                    )

            with pytest.raises(IntegrityError):
                async with connection.begin_nested():
                    await connection.execute(
                        text(
                            "UPDATE ops.import_jobs SET sync_scope = 'changed' "
                            "WHERE job_id = '53000000-0000-4000-8000-000000000002'"
                        )
                    )

            with pytest.raises(IntegrityError):  # noqa: PT012 - job/request pair 원자 검증
                async with connection.begin_nested():
                    await connection.execute(
                        text(
                            """
                            INSERT INTO ops.import_jobs (
                              job_id, kind, payload, status, provider, dataset_key,
                              sync_scope, trigger_kind
                            ) VALUES (
                              '53000000-0000-4000-8000-000000000097',
                              'feature_update_request', '{}'::jsonb, 'done',
                              'provider-explicit', 'dataset-explicit',
                              'target_grids', 'update_request'
                            )
                            """
                        )
                    )
                    await connection.execute(
                        text(
                            """
                            INSERT INTO ops.feature_update_requests (
                              request_id, scope_type, scope, run_mode, job_id
                            ) VALUES (
                              '53000000-0000-4000-8000-000000000097',
                              'provider_dataset',
                              '{"type":"provider_dataset",'
                              '"provider":"provider-explicit",'
                              '"dataset_key":"dataset-explicit",'
                              '"sync_scope":"dataset_wide"}'::jsonb,
                              'queued',
                              '53000000-0000-4000-8000-000000000097'
                            )
                            """
                        )
                    )

            with pytest.raises(IntegrityError):
                async with connection.begin_nested():
                    await connection.execute(
                        text(
                            """
                            INSERT INTO ops.import_jobs (
                              job_id, kind, payload, status, provider, dataset_key,
                              sync_scope, trigger_kind
                            ) VALUES (
                              '53000000-0000-4000-8000-000000000098',
                              'feature_update_request', '{}'::jsonb, 'done',
                              'provider-z', 'dataset-z', 'legacy-alias', 'update_request'
                            )
                            """
                        )
                    )

            with pytest.raises(IntegrityError):
                async with connection.begin_nested():
                    await connection.execute(
                        text(
                            """
                            INSERT INTO ops.import_jobs (
                              job_id, kind, payload, status, provider, dataset_key,
                              sync_scope, trigger_kind
                            ) VALUES (
                              '53000000-0000-4000-8000-000000000099',
                              'feature_update_request', '{}'::jsonb, 'queued',
                              'provider-b', 'dataset-b', 'dataset_wide', 'update_request'
                            )
                            """
                        )
                    )

        await engine.dispose()
        await asyncio.to_thread(_run_alembic, dsn, _PRE_REVISION, downgrade=True)
        engine = make_async_engine(dsn)
        async with engine.connect() as connection:
            remaining_columns = (
                await connection.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_schema = 'ops' AND table_name = 'import_jobs' "
                        "AND column_name IN ('sync_scope','dispatch_requested_at')"
                    )
                )
            ).all()
        assert remaining_columns == []
    finally:
        await engine.dispose()
        await _drop_database(pg_container, dsn)


async def test_0053_reconciles_queued_scope_duplicates_deterministically(
    pg_container: Any,
) -> None:
    dsn, engine = await _create_database(pg_container, "scope_dispatch_reconcile")
    try:
        await asyncio.to_thread(_run_alembic, dsn, _PRE_REVISION)
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    """
                    INSERT INTO ops.import_jobs (
                      job_id, kind, payload, status, provider, dataset_key,
                      trigger_kind, dagster_run_id, error_message
                    ) VALUES
                    ('53000000-1000-4000-8000-000000000001',
                     'feature_update_request', '{}'::jsonb, 'queued',
                     'provider-a', 'dataset-a', 'update_request', NULL,
                     'prior retry context'),
                    ('53000000-1000-4000-8000-000000000002',
                     'feature_update_request', '{}'::jsonb, 'queued',
                     'provider-a', 'dataset-a', 'update_request', NULL, NULL),
                    ('53000000-1000-4000-8000-000000000003',
                     'feature_update_request', '{}'::jsonb, 'queued',
                     'provider-a', 'dataset-a', 'update_request', NULL, NULL),
                    ('53000000-1000-4000-8000-000000000004',
                     'feature_update_request', '{}'::jsonb, 'running',
                     'provider-b', 'dataset-b', 'update_request', 'run-b', NULL),
                    ('53000000-1000-4000-8000-000000000005',
                     'feature_update_request', '{}'::jsonb, 'queued',
                     'provider-b', 'dataset-b', 'update_request', NULL, NULL)
                    """
                )
            )
            await connection.execute(
                text(
                    """
                    INSERT INTO ops.feature_update_requests (
                      request_id, scope_type, scope, run_mode, priority, job_id,
                      created_at
                    ) VALUES
                    ('53000000-1000-4000-8000-000000000011',
                     'provider_dataset',
                     '{"type":"provider_dataset","provider":"provider-a",'
                     '"dataset_key":"dataset-a","sync_scope":"foo"}'::jsonb,
                     'queued', 75, '53000000-1000-4000-8000-000000000001',
                     '2026-07-17T00:00:00+00'::timestamptz),
                    ('53000000-1000-4000-8000-000000000012',
                     'provider_dataset',
                     '{"type":"provider_dataset","provider":"provider-a",'
                     '"dataset_key":"dataset-a","sync_scope":"bar"}'::jsonb,
                     'now', 75, '53000000-1000-4000-8000-000000000002',
                     '2026-07-17T00:01:00+00'::timestamptz),
                    ('53000000-1000-4000-8000-000000000013',
                     'provider_dataset',
                     '{"type":"provider_dataset","provider":"provider-a",'
                     '"dataset_key":"dataset-a","sync_scope":"baz"}'::jsonb,
                     'now', 75, '53000000-1000-4000-8000-000000000003',
                     '2026-07-17T00:02:00+00'::timestamptz),
                    ('53000000-1000-4000-8000-000000000014',
                     'provider_dataset',
                     '{"type":"provider_dataset","provider":"provider-b",'
                     '"dataset_key":"dataset-b"}'::jsonb,
                     'queued', 0, '53000000-1000-4000-8000-000000000004',
                     '2026-07-17T00:03:00+00'::timestamptz),
                    ('53000000-1000-4000-8000-000000000015',
                     'provider_dataset',
                     '{"type":"provider_dataset","provider":"provider-b",'
                     '"dataset_key":"dataset-b"}'::jsonb,
                     'now', 100, '53000000-1000-4000-8000-000000000005',
                     '2026-07-17T00:04:00+00'::timestamptz)
                    """
                )
            )

        await engine.dispose()
        await asyncio.to_thread(_run_alembic, dsn, _TARGET_REVISION)

        engine = make_async_engine(dsn)
        async with engine.connect() as connection:
            rows = {
                str(row.job_id): row
                for row in await connection.execute(
                    text(
                        "SELECT job_id, status, finished_at, error_message, sync_scope "
                        "FROM ops.import_jobs ORDER BY job_id"
                    )
                )
            }
            revision = (
                await connection.execute(text("SELECT version_num FROM alembic_version"))
            ).scalar_one()

        queued_winner = rows["53000000-1000-4000-8000-000000000002"]
        assert queued_winner.status == "queued"
        assert queued_winner.finished_at is None
        assert queued_winner.error_message is None
        assert queued_winner.sync_scope == "dataset_wide"

        first_loser = rows["53000000-1000-4000-8000-000000000001"]
        assert first_loser.status == "cancelled"
        assert first_loser.finished_at is not None
        assert first_loser.error_message == (
            "prior retry context; migration 0053 superseded duplicate active scope; "
            "winner_job_id=53000000-1000-4000-8000-000000000002"
        )
        later_loser = rows["53000000-1000-4000-8000-000000000003"]
        assert later_loser.status == "cancelled"
        assert later_loser.finished_at is not None
        assert later_loser.error_message == (
            "migration 0053 superseded duplicate active scope; "
            "winner_job_id=53000000-1000-4000-8000-000000000002"
        )

        running_winner = rows["53000000-1000-4000-8000-000000000004"]
        assert running_winner.status == "running"
        mixed_loser = rows["53000000-1000-4000-8000-000000000005"]
        assert mixed_loser.status == "cancelled"
        assert mixed_loser.finished_at is not None
        assert mixed_loser.error_message == (
            "migration 0053 superseded duplicate active scope; "
            "winner_job_id=53000000-1000-4000-8000-000000000004"
        )
        assert revision == _TARGET_REVISION

        await engine.dispose()
        await asyncio.to_thread(_run_alembic, dsn, _PRE_REVISION, downgrade=True)
        await asyncio.to_thread(_run_alembic, dsn, _TARGET_REVISION)
        engine = make_async_engine(dsn)
        async with engine.connect() as connection:
            roundtrip_rows = {
                str(row.job_id): row
                for row in await connection.execute(
                    text(
                        "SELECT job_id, status, error_message "
                        "FROM ops.import_jobs ORDER BY job_id"
                    )
                )
            }
            roundtrip_revision = (
                await connection.execute(text("SELECT version_num FROM alembic_version"))
            ).scalar_one()
        assert (
            roundtrip_rows["53000000-1000-4000-8000-000000000002"].status
            == "queued"
        )
        assert (
            roundtrip_rows["53000000-1000-4000-8000-000000000001"].error_message
            == first_loser.error_message
        )
        assert (
            roundtrip_rows["53000000-1000-4000-8000-000000000003"].error_message
            == later_loser.error_message
        )
        assert roundtrip_revision == _TARGET_REVISION
    finally:
        await engine.dispose()
        await _drop_database(pg_container, dsn)


async def test_0053_fails_closed_on_multiple_running_scope_ambiguity(
    pg_container: Any,
) -> None:
    dsn, engine = await _create_database(pg_container, "scope_dispatch_conflict")
    try:
        await asyncio.to_thread(_run_alembic, dsn, _PRE_REVISION)
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    """
                    INSERT INTO ops.import_jobs (
                      job_id, kind, payload, status, provider, dataset_key,
                      trigger_kind, dagster_run_id
                    ) VALUES
                    ('53000000-2000-4000-8000-000000000001',
                     'feature_update_request', '{}'::jsonb, 'running',
                     'provider-a', 'dataset-a', 'update_request', 'run-a'),
                    ('53000000-2000-4000-8000-000000000002',
                     'feature_update_request', '{}'::jsonb, 'running',
                     'provider-a', 'dataset-a', 'update_request', 'run-b')
                    """
                )
            )
            await connection.execute(
                text(
                    """
                    INSERT INTO ops.feature_update_requests (
                      request_id, scope_type, scope, run_mode, job_id
                    ) VALUES
                    ('53000000-2000-4000-8000-000000000011',
                     'provider_dataset',
                     '{"type":"provider_dataset","provider":"provider-a",'
                     '"dataset_key":"dataset-a"}'::jsonb,
                     'queued', '53000000-2000-4000-8000-000000000001'),
                    ('53000000-2000-4000-8000-000000000012',
                     'provider_dataset',
                     '{"type":"provider_dataset","provider":"provider-a",'
                     '"dataset_key":"dataset-a"}'::jsonb,
                     'queued', '53000000-2000-4000-8000-000000000002')
                    """
                )
            )

        await engine.dispose()
        with pytest.raises(RuntimeError, match="multiple running"):
            await asyncio.to_thread(_run_alembic, dsn, _TARGET_REVISION)

        engine = make_async_engine(dsn)
        async with engine.connect() as connection:
            revision = (
                await connection.execute(text("SELECT version_num FROM alembic_version"))
            ).scalar_one()
            scope_column = (
                await connection.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_schema = 'ops' AND table_name = 'import_jobs' "
                        "AND column_name = 'sync_scope'"
                    )
                )
            ).one_or_none()
        assert revision == _PRE_REVISION
        assert scope_column is None
    finally:
        await engine.dispose()
        await _drop_database(pg_container, dsn)


async def test_0053_fails_closed_on_cancellation_marked_scope_duplicate(
    pg_container: Any,
) -> None:
    dsn, engine = await _create_database(pg_container, "scope_dispatch_cancelling")
    try:
        await asyncio.to_thread(_run_alembic, dsn, _PRE_REVISION)
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    """
                    INSERT INTO ops.import_jobs (
                      job_id, kind, payload, status, provider, dataset_key,
                      trigger_kind, dagster_run_id
                    ) VALUES
                    ('53000000-3000-4000-8000-000000000001',
                     'feature_update_request', '{}'::jsonb, 'queued',
                     'provider-c', 'dataset-c', 'update_request', NULL),
                    ('53000000-3000-4000-8000-000000000002',
                     'feature_update_request', '{}'::jsonb, 'queued',
                     'provider-c', 'dataset-c', 'update_request', NULL)
                    """
                )
            )
            await connection.execute(
                text(
                    """
                    INSERT INTO ops.feature_update_requests (
                      request_id, scope_type, scope, run_mode, priority, job_id,
                      created_at
                    ) VALUES
                    ('53000000-3000-4000-8000-000000000011',
                     'provider_dataset',
                     '{"type":"provider_dataset","provider":"provider-c",'
                     '"dataset_key":"dataset-c"}'::jsonb,
                     'now', 100, '53000000-3000-4000-8000-000000000001',
                     '2026-07-17T00:00:00+00'::timestamptz),
                    ('53000000-3000-4000-8000-000000000012',
                     'provider_dataset',
                     '{"type":"provider_dataset","provider":"provider-c",'
                     '"dataset_key":"dataset-c"}'::jsonb,
                     'queued', 50, '53000000-3000-4000-8000-000000000002',
                     '2026-07-17T00:01:00+00'::timestamptz)
                    """
                )
            )
            await connection.execute(
                text(
                    """
                    INSERT INTO ops.pipeline_cancellations (
                      cancellation_id, root_kind, root_id, status, requested_by
                    ) VALUES (
                      '53000000-3000-4000-8000-000000000021',
                      'import_job',
                      '53000000-3000-4000-8000-000000000001',
                      'in_progress',
                      'migration-test'
                    )
                    """
                )
            )
            await connection.execute(
                text(
                    """
                    INSERT INTO ops.pipeline_cancellation_members (
                      cancellation_id, job_id, operation_kind, initial_status,
                      requires_run_termination
                    ) VALUES (
                      '53000000-3000-4000-8000-000000000021',
                      '53000000-3000-4000-8000-000000000001',
                      'feature_update_request',
                      'queued',
                      false
                    )
                    """
                )
            )
            await connection.execute(
                text(
                    """
                    UPDATE ops.import_jobs
                       SET cancellation_id = '53000000-3000-4000-8000-000000000021',
                           cancellation_requested_at = now(),
                           cancellation_requested_by = 'migration-test'
                     WHERE job_id = '53000000-3000-4000-8000-000000000001'
                    """
                )
            )

        await engine.dispose()
        with pytest.raises(RuntimeError, match="cancellation-marked"):
            await asyncio.to_thread(_run_alembic, dsn, _TARGET_REVISION)

        engine = make_async_engine(dsn)
        async with engine.connect() as connection:
            revision = (
                await connection.execute(text("SELECT version_num FROM alembic_version"))
            ).scalar_one()
            statuses = (
                await connection.execute(
                    text(
                        "SELECT status FROM ops.import_jobs "
                        "WHERE job_id IN ("
                        "'53000000-3000-4000-8000-000000000001',"
                        "'53000000-3000-4000-8000-000000000002'"
                        ") ORDER BY job_id"
                    )
                )
            ).scalars().all()
            member_result = (
                await connection.execute(
                    text(
                        "SELECT result FROM ops.pipeline_cancellation_members "
                        "WHERE cancellation_id = "
                        "'53000000-3000-4000-8000-000000000021'"
                    )
                )
            ).scalar_one()
            attempt_status = (
                await connection.execute(
                    text(
                        "SELECT status FROM ops.pipeline_cancellations "
                        "WHERE cancellation_id = "
                        "'53000000-3000-4000-8000-000000000021'"
                    )
                )
            ).scalar_one()
            scope_column = (
                await connection.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_schema = 'ops' AND table_name = 'import_jobs' "
                        "AND column_name = 'sync_scope'"
                    )
                )
            ).one_or_none()
        assert revision == _PRE_REVISION
        assert statuses == ["queued", "queued"]
        assert member_result == "pending"
        assert attempt_status == "in_progress"
        assert scope_column is None
    finally:
        await engine.dispose()
        await _drop_database(pg_container, dsn)


async def test_0053_fails_closed_on_noncanonical_poi_external_system(
    pg_container: Any,
) -> None:
    dsn, engine = await _create_database(pg_container, "scope_dispatch_invalid_poi")
    try:
        await asyncio.to_thread(_run_alembic, dsn, _PRE_REVISION)
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    """
                    INSERT INTO ops.poi_cache_targets (
                      external_system, target_key, lon, lat, coord, coord_key, radius_km
                    ) VALUES (
                      chr(160) || 'legacy-system', 'poi-1', 126.978, 37.5665,
                      x_extension.ST_SetSRID(
                        x_extension.ST_MakePoint(126.978, 37.5665), 4326
                      ),
                      '126.978000:37.566500:p6', 5.0
                    )
                    """
                )
            )

        await engine.dispose()
        with pytest.raises(RuntimeError, match="canonical external_system identity"):
            await asyncio.to_thread(_run_alembic, dsn, _TARGET_REVISION)

        engine = make_async_engine(dsn)
        async with engine.connect() as connection:
            revision = (
                await connection.execute(text("SELECT version_num FROM alembic_version"))
            ).scalar_one()
            constraint = (
                await connection.execute(
                    text(
                        "SELECT conname FROM pg_constraint "
                        "WHERE conname = 'ck_poi_cache_targets_external_system_identity'"
                    )
                )
            ).one_or_none()
        assert revision == _PRE_REVISION
        assert constraint is None
    finally:
        await engine.dispose()
        await _drop_database(pg_container, dsn)
