"""Alembic 0051 canonical provider operation schema/backfill/down 회귀."""

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

_PRE_REVISION = "0050_pipeline_cancellations"
_TARGET_REVISION = "0051_canonical_provider_ops"


def _run_alembic(dsn: str, revision: str, *, downgrade: bool = False) -> None:
    root = Path(__file__).resolve().parents[2]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    # 아카이브 체인 전용 그래프 — alembic/legacy_versions/README.md 참조.
    config.set_main_option("version_locations", str(root / "alembic" / "legacy_versions"))
    config.set_main_option("sqlalchemy.url", dsn)
    if downgrade:
        command.downgrade(config, revision)
    else:
        command.upgrade(config, revision)


async def test_0051_exact_event_pair_and_cancellation_snapshot_backfill(
    pg_container: Any,
) -> None:
    admin_dsn = normalize_async_dsn(pg_container.get_connection_url())
    database = f"canonical_provider_ops_{uuid4().hex}"
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
                    INSERT INTO ops.import_jobs (
                      job_id, kind, payload, status, dagster_run_id
                    ) VALUES
                    ('11111111-1111-4111-8111-111111111111', 'legacy_exact',
                     '{}'::jsonb, 'done', NULL),
                    ('22222222-2222-4222-8222-222222222222', 'legacy_multi',
                     '{}'::jsonb, 'done', NULL),
                    ('33333333-3333-4333-8333-333333333333', 'legacy_running',
                     '{}'::jsonb, 'running', 'legacy-run'),
                    ('55555555-5555-4555-8555-555555555555', 'request_ambiguous',
                     '{}'::jsonb, 'done', NULL),
                    ('66666666-6666-4666-8666-666666666666', 'request_exact',
                     '{}'::jsonb, 'done', NULL),
                    ('77777777-7777-4777-8777-777777777777', 'request_blank',
                     '{}'::jsonb, 'done', NULL),
                    ('88888888-8888-4888-8888-888888888888', 'request_partial',
                     '{}'::jsonb, 'done', NULL),
                    ('99999999-9999-4999-8999-999999999999', 'request_mixed_scope',
                     '{}'::jsonb, 'done', NULL),
                    ('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', 'request_non_string',
                     '{}'::jsonb, 'done', NULL),
                    ('bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb', 'request_duplicate',
                     '{}'::jsonb, 'done', NULL),
                    ('cccccccc-cccc-4ccc-8ccc-cccccccccccc', 'non_pair_request',
                     '{}'::jsonb, 'done', NULL),
                    ('eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee',
                     'legacy_generic_queued', '{}'::jsonb, 'queued',
                     'legacy-generic-run'),
                    ('ffffffff-ffff-4fff-8fff-ffffffffffff', 'event_partial',
                     '{}'::jsonb, 'done', NULL)
                    """
                )
            )
            await connection.execute(
                text(
                    """
                    INSERT INTO ops.import_job_events (
                      job_id, provider, dataset_key, level, message
                    ) VALUES
                    ('11111111-1111-4111-8111-111111111111',
                     'provider-a', 'dataset-a', 'info', 'exact'),
                    ('22222222-2222-4222-8222-222222222222',
                     'provider-a', 'dataset-a', 'info', 'first'),
                    ('22222222-2222-4222-8222-222222222222',
                     'provider-b', 'dataset-b', 'info', 'second'),
                    ('ffffffff-ffff-4fff-8fff-ffffffffffff',
                     'event-provider', 'event-dataset', 'info', 'exact'),
                    ('ffffffff-ffff-4fff-8fff-ffffffffffff',
                     'event-provider', NULL, 'info', 'partial')
                    """
                )
            )
            await connection.execute(
                text(
                    """
                    INSERT INTO ops.feature_update_requests (
                      request_id, scope_type, scope, run_mode, job_id
                    ) VALUES
                    ('55555555-0001-4000-8000-000000000001',
                     'provider_dataset',
                     '{"provider":"provider-a","dataset_key":"dataset-a"}'::jsonb,
                     'queued', '55555555-5555-4555-8555-555555555555'),
                    ('55555555-0002-4000-8000-000000000002',
                     'provider_dataset',
                     '{"provider":"provider-b","dataset_key":"dataset-b"}'::jsonb,
                     'queued', '55555555-5555-4555-8555-555555555555'),
                    ('66666666-0001-4000-8000-000000000001',
                     'provider_dataset',
                     '{"provider":"request-provider","dataset_key":"request-dataset"}'::jsonb,
                     'queued', '66666666-6666-4666-8666-666666666666'),
                    ('77777777-0001-4000-8000-000000000001',
                     'provider_dataset',
                     '{"provider":" ","dataset_key":"dataset"}'::jsonb,
                     'queued', '77777777-7777-4777-8777-777777777777'),
                    ('88888888-0001-4000-8000-000000000001',
                     'provider_dataset',
                     '{"provider":"request-provider","dataset_key":"request-dataset"}'::jsonb,
                     'queued', '88888888-8888-4888-8888-888888888888'),
                    ('88888888-0002-4000-8000-000000000002',
                     'provider_dataset',
                     '{"provider":"request-provider"}'::jsonb,
                     'queued', '88888888-8888-4888-8888-888888888888'),
                    ('99999999-0001-4000-8000-000000000001',
                     'provider_dataset',
                     '{"provider":"request-provider","dataset_key":"request-dataset"}'::jsonb,
                     'queued', '99999999-9999-4999-8999-999999999999'),
                    ('99999999-0002-4000-8000-000000000002',
                     'bbox', '{"west": 126,"south": 37,"east": 127,"north": 38}'::jsonb,
                     'queued', '99999999-9999-4999-8999-999999999999'),
                    ('aaaaaaaa-0001-4000-8000-000000000001',
                     'provider_dataset',
                     '{"provider": 123,"dataset_key":["dataset"]}'::jsonb,
                     'queued', 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'),
                    ('bbbbbbbb-0001-4000-8000-000000000001',
                     'provider_dataset',
                     '{"provider":"request-provider","dataset_key":"request-dataset"}'::jsonb,
                     'queued', 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb'),
                    ('bbbbbbbb-0002-4000-8000-000000000002',
                     'provider_dataset',
                     '{"provider":"request-provider","dataset_key":"request-dataset"}'::jsonb,
                     'queued', 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb'),
                    ('cccccccc-0001-4000-8000-000000000001',
                     'bbox', '{"west": 126,"south": 37,"east": 127,"north": 38}'::jsonb,
                     'queued', 'cccccccc-cccc-4ccc-8ccc-cccccccccccc')
                    """
                )
            )
            await connection.execute(
                text(
                    """
                    INSERT INTO ops.import_job_events (
                      job_id, provider, dataset_key, level, message
                    ) VALUES
                    (
                      '66666666-6666-4666-8666-666666666666',
                      'event-provider', 'event-dataset', 'info', 'lower priority'
                    ),
                    (
                      '55555555-5555-4555-8555-555555555555',
                      'provider-a', 'dataset-a', 'info', 'ambiguous request fallback denied'
                    ),
                    (
                      '77777777-7777-4777-8777-777777777777',
                      'event-provider', 'event-dataset', 'info', 'invalid request fallback denied'
                    ),
                    (
                      '88888888-8888-4888-8888-888888888888',
                      'event-provider', 'event-dataset', 'info', 'partial request fallback denied'
                    ),
                    (
                      '99999999-9999-4999-8999-999999999999',
                      'event-provider', 'event-dataset', 'info', 'mixed scope fallback denied'
                    ),
                    (
                      'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
                      'event-provider', 'event-dataset', 'info', 'non-string fallback denied'
                    ),
                    (
                      'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
                      'event-provider', 'event-dataset', 'info', 'duplicate fallback denied'
                    ),
                    (
                      'cccccccc-cccc-4ccc-8ccc-cccccccccccc',
                      'event-provider', 'event-dataset', 'info', 'linked request fallback denied'
                    )
                    """
                )
            )
            await connection.execute(
                text(
                    """
                    INSERT INTO ops.pipeline_cancellations (
                      cancellation_id, root_kind, root_id, requested_by
                    ) VALUES (
                      '44444444-4444-4444-8444-444444444444', 'import_job',
                      '33333333-3333-4333-8333-333333333333', 'admin:test'
                    )
                    """
                )
            )
            await connection.execute(
                text(
                    """
                    INSERT INTO ops.pipeline_cancellation_runs (
                      cancellation_id, dagster_run_id, result
                    ) VALUES
                    (
                      '44444444-4444-4444-8444-444444444444', 'legacy-run', 'pending'
                    ),
                    (
                      '44444444-4444-4444-8444-444444444444',
                      'legacy-generic-run', 'pending'
                    )
                    """
                )
            )
            await connection.execute(
                text(
                    """
                    INSERT INTO ops.pipeline_cancellation_members (
                      cancellation_id, member_kind, member_id, dagster_run_id,
                      initial_status, result
                    ) VALUES
                    (
                      '44444444-4444-4444-8444-444444444444', 'import_job',
                      '33333333-3333-4333-8333-333333333333', 'legacy-run',
                      'running', 'pending'
                    ),
                    (
                      '44444444-4444-4444-8444-444444444444', 'import_job',
                      'eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee',
                      'legacy-generic-run', 'queued', 'pending'
                    )
                    """
                )
            )

        await target_engine.dispose()
        await asyncio.to_thread(_run_alembic, target_dsn, _TARGET_REVISION)
        target_engine = make_async_engine(target_dsn)
        async with target_engine.connect() as connection:
            jobs = {
                str(row.job_id): (row.provider, row.dataset_key)
                for row in await connection.execute(
                    text(
                        "SELECT job_id, provider, dataset_key FROM ops.import_jobs "
                        "ORDER BY job_id"
                    )
                )
            }
            members = {
                str(row.member_id): (
                    str(row.operation_kind) if row.operation_kind is not None else None,
                    bool(row.requires_run_termination),
                )
                for row in await connection.execute(
                    text(
                        """
                        SELECT member_id, operation_kind, requires_run_termination
                        FROM ops.pipeline_cancellation_members
                        WHERE cancellation_id =
                          '44444444-4444-4444-8444-444444444444'::uuid
                        """
                    )
                )
            }
            indexes = {
                str(row.indexname)
                for row in await connection.execute(
                    text(
                        """
                        SELECT indexname FROM pg_indexes
                        WHERE schemaname = 'ops' AND tablename = 'import_jobs'
                        """
                    )
                )
            }
            run_columns = {
                str(row.column_name)
                for row in await connection.execute(
                    text(
                        """
                        SELECT column_name FROM information_schema.columns
                        WHERE table_schema = 'ops'
                          AND table_name = 'pipeline_cancellation_runs'
                        """
                    )
                )
            }
            member_columns = {
                str(row.column_name)
                for row in await connection.execute(
                    text(
                        """
                        SELECT column_name FROM information_schema.columns
                        WHERE table_schema = 'ops'
                          AND table_name = 'pipeline_cancellation_members'
                        """
                    )
                )
            }
            checks = {
                (str(row.table_name), str(row.definition))
                for row in await connection.execute(
                    text(
                        """
                        SELECT
                          conrelid::regclass::text AS table_name,
                          pg_get_constraintdef(oid) AS definition
                        FROM pg_constraint
                        WHERE connamespace = 'ops'::regnamespace
                          AND contype = 'c'
                        """
                    )
                )
            }
        assert jobs["11111111-1111-4111-8111-111111111111"] == (
            "provider-a",
            "dataset-a",
        )
        assert jobs["22222222-2222-4222-8222-222222222222"] == (None, None)
        assert jobs["55555555-5555-4555-8555-555555555555"] == (None, None)
        assert jobs["66666666-6666-4666-8666-666666666666"] == (
            "request-provider",
            "request-dataset",
        )
        assert jobs["77777777-7777-4777-8777-777777777777"] == (None, None)
        assert jobs["88888888-8888-4888-8888-888888888888"] == (None, None)
        assert jobs["99999999-9999-4999-8999-999999999999"] == (None, None)
        assert jobs["aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"] == (None, None)
        assert jobs["bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"] == (None, None)
        assert jobs["cccccccc-cccc-4ccc-8ccc-cccccccccccc"] == (None, None)
        assert jobs["ffffffff-ffff-4fff-8fff-ffffffffffff"] == (None, None)
        assert members["33333333-3333-4333-8333-333333333333"] == (
            "legacy_running",
            True,
        )
        assert members["eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"] == (
            "legacy_generic_queued",
            False,
        )
        assert {"engine_started_at", "engine_finished_at"} <= run_columns
        assert {"operation_kind", "requires_run_termination"} <= member_columns
        assert any(
            table_name == "ops.pipeline_cancellation_runs"
            and "engine_started_at" in definition
            and "engine_finished_at" in definition
            and "already_terminal" in definition
            for table_name, definition in checks
        )
        assert any(
            table_name == "ops.pipeline_cancellation_members"
            and "operation_kind" in definition
            and "btrim(operation_kind)" in definition
            and "member_kind" in definition
            for table_name, definition in checks
        )
        assert any(
            table_name == "ops.pipeline_cancellation_members"
            and "requires_run_termination" in definition
            and "provider_feature_load_run" in definition
            and "initial_status" in definition
            for table_name, definition in checks
        )
        assert {
            "uq_import_jobs_feature_run",
            "uq_import_jobs_feature_run_pair",
            "idx_import_jobs_provider_dataset_created",
            "idx_import_jobs_provider_created",
            "idx_import_jobs_dataset_created",
        } <= indexes

        await target_engine.dispose()
        with pytest.raises(RuntimeError, match="active feature operation/cancellation"):
            await asyncio.to_thread(
                _run_alembic, target_dsn, _PRE_REVISION, downgrade=True
            )
        target_engine = make_async_engine(target_dsn)

        async with target_engine.begin() as connection:
            await connection.execute(
                text(
                    """
                    UPDATE ops.pipeline_cancellations
                    SET status = 'completed', finished_at = now()
                    WHERE cancellation_id =
                      '44444444-4444-4444-8444-444444444444'::uuid
                    """
                )
            )
            await connection.execute(
                text(
                    """
                    UPDATE ops.pipeline_cancellation_runs
                    SET result = 'already_terminal',
                        engine_started_at = now() - interval '1 second',
                        engine_finished_at = now()
                    WHERE cancellation_id =
                      '44444444-4444-4444-8444-444444444444'::uuid
                    """
                )
            )
            await connection.execute(
                text(
                    """
                    UPDATE ops.pipeline_cancellation_members
                    SET initial_status = 'queued',
                        operation_kind = 'provider_feature_load',
                        requires_run_termination = true,
                        result = 'cancel_failed', terminal_status = NULL,
                        error = jsonb_build_object(
                          'code', 'DAGSTER_RECONCILE_FAILED',
                          'message', 'test',
                          'details', '{}'::jsonb
                        )
                    WHERE cancellation_id =
                      '44444444-4444-4444-8444-444444444444'::uuid
                      AND member_id =
                        '33333333-3333-4333-8333-333333333333'::uuid
                    """
                )
            )
            await connection.execute(
                text(
                    """
                    UPDATE ops.import_jobs
                    SET status = 'done', finished_at = now()
                    WHERE job_id IN (
                      '33333333-3333-4333-8333-333333333333'::uuid,
                      'eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee'::uuid
                    )
                    """
                )
            )
        await target_engine.dispose()
        with pytest.raises(
            RuntimeError,
            match=(
                "incompatible queued run-backed cancel_failed history count=1; "
                "sample cancellation_id/member_id="
            ),
        ):
            await asyncio.to_thread(
                _run_alembic, target_dsn, _PRE_REVISION, downgrade=True
            )
        target_engine = make_async_engine(target_dsn)
        async with target_engine.begin() as connection:
            persisted_times = (
                await connection.execute(
                    text(
                        """
                        SELECT engine_started_at, engine_finished_at
                        FROM ops.pipeline_cancellation_runs
                        WHERE cancellation_id =
                          '44444444-4444-4444-8444-444444444444'::uuid
                          AND dagster_run_id = 'legacy-run'
                        """
                    )
                )
            ).one()
            assert persisted_times.engine_started_at is not None
            assert persisted_times.engine_finished_at is not None
            assert (
                persisted_times.engine_started_at
                <= persisted_times.engine_finished_at
            )
            await connection.execute(
                text(
                    """
                    UPDATE ops.pipeline_cancellation_members
                    SET operation_kind = CASE
                          WHEN member_id =
                            '33333333-3333-4333-8333-333333333333'::uuid
                          THEN 'legacy_running'
                          ELSE operation_kind
                        END,
                        requires_run_termination = false,
                        result = 'already_terminal', terminal_status = 'done',
                        error = NULL
                    WHERE cancellation_id =
                      '44444444-4444-4444-8444-444444444444'::uuid
                    """
                )
            )
        await target_engine.dispose()
        await asyncio.to_thread(
            _run_alembic, target_dsn, _PRE_REVISION, downgrade=True
        )
        target_engine = make_async_engine(target_dsn)
        async with target_engine.connect() as connection:
            remaining_columns = {
                (str(row.table_name), str(row.column_name))
                for row in await connection.execute(
                    text(
                        """
                        SELECT table_name, column_name
                        FROM information_schema.columns
                        WHERE table_schema = 'ops'
                          AND (
                            (table_name = 'import_jobs' AND column_name = 'provider')
                            OR (table_name = 'pipeline_cancellation_runs'
                                AND column_name IN (
                                  'engine_started_at', 'engine_finished_at'
                                ))
                            OR (table_name = 'pipeline_cancellation_members'
                                AND column_name IN (
                                  'operation_kind', 'requires_run_termination'
                                ))
                          )
                        """
                    )
                )
            }
            remaining_checks = {
                str(row.conname)
                for row in await connection.execute(
                    text(
                        """
                        SELECT conname FROM pg_constraint
                        WHERE connamespace = 'ops'::regnamespace
                          AND conname IN (
                            'ck_pipeline_cancellation_runs_engine_times',
                            'ck_pipeline_cancellation_members_operation_kind',
                            'ck_pipeline_cancellation_members_run_termination'
                          )
                        """
                    )
                )
            }
        assert remaining_columns == set()
        assert remaining_checks == set()
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
