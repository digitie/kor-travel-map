"""0052 pipeline projection identity/index migration 검증."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta
from pathlib import Path
from threading import Event as ThreadEvent
from typing import Any
from uuid import uuid4

import pytest
from alembic.config import Config
from kortravelmap.api.routers.ops_live import (
    _import_job_events_snapshot,
    _import_jobs_snapshot,
    collect_live_topic_snapshots,
)
from sqlalchemy import event, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from alembic import command
from kortravelmap.infra.db import make_async_engine, normalize_async_dsn

pytestmark = pytest.mark.integration

_PRE_REVISION = "0051_canonical_provider_ops"
_TARGET_REVISION = "0052_pipeline_projection_access"
_PRE_REVISION_EVENT_INDEX_NAMES = {
    "idx_import_job_events_job_time",
    "idx_import_job_events_provider_time",
    "idx_import_job_events_level_time",
}
_EXPECTED_INDEX_NAMES = _PRE_REVISION_EVENT_INDEX_NAMES | {
    "idx_import_job_events_time",
    "idx_import_job_events_dataset_time",
    "idx_import_job_events_provider_dataset_time",
    "idx_feature_update_providers_gin",
    "idx_feature_update_dataset_keys_gin",
    "idx_feature_update_priority",
    "idx_feature_update_created",
    "idx_import_jobs_feature_update_queue",
    "idx_import_jobs_quarantined",
}
_REMOVED_DIRECT_INDEX_NAMES = {
    "idx_feature_update_direct_provider_dataset",
    "idx_feature_update_direct_dataset",
}
_INDEX_NAMES = _EXPECTED_INDEX_NAMES | _REMOVED_DIRECT_INDEX_NAMES
_PRE_REVISION_INDEX_NAMES = {
    "idx_feature_update_created",
    *_PRE_REVISION_EVENT_INDEX_NAMES,
}
_REQUEST_LIFECYCLE_COLUMNS = {
    "status",
    "dagster_run_id",
    "cancellation_id",
    "cancellation_requested_at",
    "cancellation_requested_by",
    "cancellation_reason",
    "error_message",
    "started_at",
    "finished_at",
    "updated_at",
}

_JOBLESS_DIRECT_REQUEST = "10000000-0000-4000-8000-000000000001"
_JOBLESS_NON_DIRECT_REQUEST = "20000000-0000-4000-8000-000000000002"
_MISMATCHED_DIRECT_REQUEST = "30000000-0000-4000-8000-000000000003"
_PAIRED_NON_DIRECT_REQUEST = "40000000-0000-4000-8000-000000000004"
_MISMATCHED_DIRECT_SOURCE_JOB = "30000000-0000-4000-9000-000000000003"
_PAIRED_NON_DIRECT_SOURCE_JOB = "40000000-0000-4000-9000-000000000004"
_SHAPE_CHECK_SOURCE_JOB = "50000000-0000-4000-9000-000000000005"
_SHAPE_CHECK_REQUEST = "50000000-0000-4000-8000-000000000005"
_RESERVED_DIRECT_REQUEST = "60000000-0000-4000-8000-000000000006"
_RESERVED_NON_DIRECT_REQUEST = "70000000-0000-4000-8000-000000000007"
_RESERVED_DIRECT_ROOT_JOB = "60000000-0000-4000-9000-000000000006"
_RESERVED_DIRECT_SOURCE_JOB = "61000000-0000-4000-9000-000000000006"
_RESERVED_NON_DIRECT_SOURCE_JOB = "70000000-0000-4000-9000-000000000007"
_SHARED_OWNER_REQUEST = "81000000-0000-4000-8000-000000000008"
_SHARED_LOSER_REQUEST = "82000000-0000-4000-8000-000000000009"
_SHARED_SOURCE_JOB = "81000000-0000-4000-9000-000000000008"
_VALID_ORPHAN_JOB = "83000000-0000-4000-9000-000000000010"
_QUARANTINE_PARENT_JOB = "83100000-0000-4000-9000-000000000010"
_QUARANTINE_CHILD_JOB = "83200000-0000-4000-9000-000000000010"
_QUARANTINE_PROVIDER = "quarantine-provider"
_QUARANTINE_DATASET = "quarantine-dataset"
_QUARANTINE_EVENT_ID = "83300000-0000-4000-9000-000000000010"
_QUARANTINE_CANCELLATION_ID = "83400000-0000-4000-9000-000000000010"
_RUNNING_OWNER_REQUEST = "84000000-0000-4000-8000-000000000011"
_RUNNING_OWNER_JOB = "84000000-0000-4000-9000-000000000011"
_RUNNING_OWNER_RUN_ID = "legacy-running-owner"
_EXPECTED_IDENTITY_LOCK_SQL = (
    "lock table ops.pipeline_cancellations, "
    "ops.pipeline_cancellation_members, "
    "ops.pipeline_cancellation_runs, "
    "ops.feature_update_requests, ops.import_jobs, "
    "ops.import_job_events in access exclusive mode nowait"
)
_EXPECTED_IDENTITY_LOCK_SQL_WITH_CLOCK = _EXPECTED_IDENTITY_LOCK_SQL.replace(
    " in access exclusive",
    ", ops.import_job_event_clock in access exclusive",
)


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


async def _index_definitions(connection: Any) -> dict[str, str]:
    rows = await connection.execute(
        text(
            """
            SELECT indexname, indexdef
            FROM pg_indexes
            WHERE schemaname = 'ops'
              AND indexname = ANY(CAST(:index_names AS text[]))
            """
        ),
        {"index_names": sorted(_INDEX_NAMES)},
    )
    return {str(row.indexname): str(row.indexdef) for row in rows}


def _assert_pre_revision_index_definitions(definitions: dict[str, str]) -> None:
    assert set(definitions) == _PRE_REVISION_INDEX_NAMES
    created = definitions["idx_feature_update_created"]
    assert "(created_at DESC)" in created
    assert "request_id" not in created
    assert "(job_id, occurred_at DESC, event_id DESC)" in definitions[
        "idx_import_job_events_job_time"
    ]
    provider = definitions["idx_import_job_events_provider_time"]
    assert "(provider, occurred_at DESC, event_id DESC)" in provider
    assert "provider IS NOT NULL" in provider
    assert "(level, occurred_at DESC, event_id DESC)" in definitions[
        "idx_import_job_events_level_time"
    ]
    for index_name in _PRE_REVISION_EVENT_INDEX_NAMES:
        assert "quarantined_at" not in definitions[index_name]


async def _feature_update_job_index_definition(
    connection: Any,
    *,
    index_name: str = "idx_feature_update_job",
) -> str:
    definition = (
        await connection.execute(
            text(
                """
                SELECT indexdef
                FROM pg_indexes
                WHERE schemaname = 'ops'
                  AND tablename = 'feature_update_requests'
                  AND indexname = :index_name
                """
            ),
            {"index_name": index_name},
        )
    ).scalar_one()
    return str(definition)


async def _dry_run_column_contract(
    connection: Any,
) -> tuple[str, str | None] | None:
    row = (
        await connection.execute(
            text(
                """
                SELECT is_nullable, column_default
                FROM information_schema.columns
                WHERE table_schema = 'ops'
                  AND table_name = 'feature_update_requests'
                  AND column_name = 'dry_run'
                """
            )
        )
    ).one_or_none()
    if row is None:
        return None
    return str(row.is_nullable), (
        str(row.column_default) if row.column_default is not None else None
    )


async def _request_job_contract(connection: Any) -> tuple[str, str]:
    row = (
        await connection.execute(
            text(
                """
                SELECT request_column.is_nullable, reference.delete_rule
                FROM information_schema.columns AS request_column
                JOIN information_schema.referential_constraints AS reference
                  ON reference.constraint_schema = request_column.table_schema
                 AND reference.constraint_name =
                       'fk_feature_update_requests_job_id_import_jobs'
                WHERE request_column.table_schema = 'ops'
                  AND request_column.table_name = 'feature_update_requests'
                  AND request_column.column_name = 'job_id'
                """
            )
        )
    ).one()
    return str(row.is_nullable), str(row.delete_rule)


async def _request_columns(connection: Any) -> set[str]:
    return set(
        await connection.scalars(
            text(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'ops'
                  AND table_name = 'feature_update_requests'
                """
            )
        )
    )


async def _import_job_columns(connection: Any) -> set[str]:
    return set(
        await connection.scalars(
            text(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'ops'
                  AND table_name = 'import_jobs'
                """
            )
        )
    )


async def _import_job_event_columns(connection: Any) -> set[str]:
    return set(
        await connection.scalars(
            text(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'ops'
                  AND table_name = 'import_job_events'
                """
            )
        )
    )


async def _import_job_event_clock_row(
    connection: Any,
) -> tuple[bool, int, Any] | None:
    if not bool(
        await connection.scalar(
            text("SELECT to_regclass('ops.import_job_event_clock') IS NOT NULL")
        )
    ):
        return None
    row = (
        await connection.execute(
            text(
                """
                SELECT clock_id, revision, updated_at
                FROM ops.import_job_event_clock
                """
            )
        )
    ).one()
    return bool(row.clock_id), int(row.revision), row.updated_at


async def _import_job_event_clock_constraints(connection: Any) -> dict[str, str]:
    rows = await connection.execute(
        text(
            """
            SELECT conname, pg_get_constraintdef(oid) AS definition
            FROM pg_constraint
            WHERE connamespace = 'ops'::regnamespace
              AND conrelid = to_regclass('ops.import_job_event_clock')
            """
        )
    )
    return {str(row.conname): str(row.definition) for row in rows}


async def _identity_constraints(connection: Any) -> dict[str, str]:
    rows = await connection.execute(
        text(
            """
            SELECT conname, pg_get_constraintdef(oid) AS definition
            FROM pg_constraint
            WHERE connamespace = 'ops'::regnamespace
              AND conname IN (
                'ck_feature_update_requests_scope_shape',
                'ck_feature_update_requests_providers_shape',
                'ck_feature_update_requests_dataset_keys_shape',
                'ck_feature_update_requests_update_policy_shape',
                'ck_feature_update_requests_direct_filters_empty',
                'ck_feature_update_requests_priority_range',
                'ck_feature_update_requests_generation_positive',
                'ck_feature_update_requests_matched_scope_object',
                'ck_feature_update_requests_reason_shape',
                'ck_import_jobs_update_request_shape',
                'ck_import_jobs_quarantine_shape'
              )
            """
        )
    )
    return {str(row.conname): str(row.definition) for row in rows}


async def _cancellation_member_identity_columns(connection: Any) -> set[str]:
    return set(
        await connection.scalars(
            text(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'ops'
                  AND table_name = 'pipeline_cancellation_members'
                  AND column_name IN ('member_kind', 'member_id', 'job_id')
                """
            )
        )
    )


async def _cancellation_member_contract(
    connection: Any,
) -> tuple[set[str], dict[str, str], str]:
    columns = await _cancellation_member_identity_columns(connection)
    rows = await connection.execute(
        text(
            """
            SELECT conname, pg_get_constraintdef(oid) AS definition
            FROM pg_constraint
            WHERE connamespace = 'ops'::regnamespace
              AND conrelid = 'ops.pipeline_cancellation_members'::regclass
              AND conname IN (
                'pk_pipeline_cancellation_members',
                'fk_pipeline_cancellation_members_job',
                'ck_pipeline_cancellation_members_operation_kind'
              )
            """
        )
    )
    index_definition = (
        await connection.execute(
            text(
                """
                SELECT indexdef
                FROM pg_indexes
                WHERE schemaname = 'ops'
                  AND tablename = 'pipeline_cancellation_members'
                  AND indexname = 'idx_pipeline_cancellation_members_job'
                """
            )
        )
    ).scalar_one()
    return (
        columns,
        {str(row.conname): str(row.definition) for row in rows},
        str(index_definition),
    )


async def _legacy_cancellation_member_contract(
    connection: Any,
) -> tuple[dict[str, str], str]:
    rows = await connection.execute(
        text(
            """
            SELECT conname, pg_get_constraintdef(oid) AS definition
            FROM pg_constraint
            WHERE connamespace = 'ops'::regnamespace
              AND conrelid = 'ops.pipeline_cancellation_members'::regclass
              AND conname IN (
                'pk_pipeline_cancellation_members',
                'ck_pipeline_cancellation_members_kind',
                'ck_pipeline_cancellation_members_operation_kind'
              )
            """
        )
    )
    index_definition = (
        await connection.execute(
            text(
                """
                SELECT indexdef
                FROM pg_indexes
                WHERE schemaname = 'ops'
                  AND tablename = 'pipeline_cancellation_members'
                  AND indexname = 'idx_pipeline_cancellation_members_member'
                """
            )
        )
    ).scalar_one()
    return (
        {str(row.conname): str(row.definition) for row in rows},
        str(index_definition),
    )


async def _identity_triggers(connection: Any) -> set[str]:
    rows = await connection.execute(
        text(
            """
            SELECT trigger_row.tgname
            FROM pg_trigger AS trigger_row
            WHERE NOT trigger_row.tgisinternal
              AND trigger_row.tgname IN (
                'trg_import_jobs_identity_immutable',
                'trg_feature_update_requests_job_identity',
                'trg_import_jobs_feature_update_pair',
                'trg_feature_update_requests_mutation_guard',
                'trg_import_jobs_feature_update_append_only',
                'trg_import_jobs_quarantine_immutable',
                'trg_import_job_events_quarantine_immutable',
                'trg_import_job_events_clock',
                'trg_import_job_event_clock_mutation_guard',
                'trg_import_job_event_clock_truncate_guard',
                'trg_pipeline_cancellation_members_reject_quarantine'
              )
            """
        )
    )
    return {str(row.tgname) for row in rows}


async def _cancellation_quarantine_guard_function_exists(connection: Any) -> bool:
    return bool(
        (
            await connection.execute(
                text(
                    "SELECT to_regprocedure("
                    "'ops.reject_quarantined_cancellation_member()'"
                    ") IS NOT NULL"
                )
            )
        ).scalar_one()
    )


async def _scope_validator_exists(connection: Any) -> bool:
    return bool(
        (
            await connection.execute(
                text(
                    "SELECT to_regprocedure("
                    "'ops.is_valid_feature_update_scope(text,jsonb)'"
                    ") IS NOT NULL"
                )
            )
        ).scalar_one()
    )


async def _scope_validator_result(connection: Any, scope_type: str, scope: Any) -> bool:
    return bool(
        (
            await connection.execute(
                text(
                    "SELECT ops.is_valid_feature_update_scope(:scope_type, CAST(:scope AS jsonb))"
                ),
                {"scope_type": scope_type, "scope": json.dumps(scope)},
            )
        ).scalar_one()
    )


async def _filter_validator_exists(connection: Any) -> bool:
    return bool(
        (
            await connection.execute(
                text(
                    "SELECT to_regprocedure("
                    "'ops.is_valid_feature_update_filter_array(text[],integer)'"
                    ") IS NOT NULL"
                )
            )
        ).scalar_one()
    )


async def _policy_validator_exists(connection: Any) -> bool:
    return bool(
        (
            await connection.execute(
                text(
                    "SELECT to_regprocedure("
                    "'ops.is_valid_feature_update_policy(jsonb)'"
                    ") IS NOT NULL"
                )
            )
        ).scalar_one()
    )


async def _policy_validator_result(connection: Any, policy: Any) -> bool:
    return bool(
        (
            await connection.execute(
                text(
                    "SELECT ops.is_valid_feature_update_policy("
                    "CAST(:policy AS jsonb))"
                ),
                {"policy": json.dumps(policy)},
            )
        ).scalar_one()
    )


async def _temporary_filter_functions_exist(connection: Any) -> bool:
    return bool(
        (
            await connection.execute(
                text(
                    "SELECT "
                    "to_regprocedure("
                    "'ops.is_valid_feature_update_filter_jsonb(jsonb,integer)'"
                    ") IS NOT NULL OR "
                    "to_regprocedure("
                    "'ops.feature_update_filter_jsonb_to_array(jsonb)'"
                    ") IS NOT NULL"
                )
            )
        ).scalar_one()
    )


async def _filter_validator_result(
    connection: Any,
    values: list[str] | None,
    max_items: int,
) -> bool:
    return bool(
        (
            await connection.execute(
                text(
                    "SELECT ops.is_valid_feature_update_filter_array("
                    "CAST(:values AS text[]), :max_items)"
                ),
                {"values": values, "max_items": max_items},
            )
        ).scalar_one()
    )


async def _filter_column_contract(connection: Any) -> dict[str, tuple[str, str, str | None]]:
    rows = await connection.execute(
        text(
            """
            SELECT column_name, data_type, udt_name, column_default
            FROM information_schema.columns
            WHERE table_schema = 'ops'
              AND table_name = 'feature_update_requests'
              AND column_name IN ('providers', 'dataset_keys')
            """
        )
    )
    return {
        str(row.column_name): (
            str(row.data_type),
            str(row.udt_name),
            str(row.column_default) if row.column_default is not None else None,
        )
        for row in rows
    }


async def test_pipeline_projection_access_paths_upgrade_and_downgrade(
    pg_container: Any,
) -> None:
    admin_dsn = normalize_async_dsn(pg_container.get_connection_url())
    database = f"pipeline_projection_indexes_{uuid4().hex}"
    target_dsn = make_url(admin_dsn).set(database=database).render_as_string(hide_password=False)
    admin_engine = make_async_engine(admin_dsn)
    async with admin_engine.connect() as connection:
        autocommit = await connection.execution_options(isolation_level="AUTOCOMMIT")
        await autocommit.execute(text(f'CREATE DATABASE "{database}"'))

    target_engine = make_async_engine(target_dsn)
    try:
        await asyncio.to_thread(_run_alembic, target_dsn, _PRE_REVISION)
        async with target_engine.begin() as connection:
            _assert_pre_revision_index_definitions(
                await _index_definitions(connection)
            )
            assert await _request_job_contract(connection) == ("YES", "SET NULL")
            assert "WHERE (job_id IS NOT NULL)" in (
                await _feature_update_job_index_definition(connection)
            )
            assert await _dry_run_column_contract(connection) == ("NO", "false")
            assert await _filter_column_contract(connection) == {
                "providers": ("jsonb", "jsonb", "'[]'::jsonb"),
                "dataset_keys": ("jsonb", "jsonb", "'[]'::jsonb"),
            }
            assert await _import_job_event_clock_row(connection) is None
            await connection.execute(
                text(
                    """
                    INSERT INTO ops.import_jobs (
                      job_id, kind, parent_job_id, payload, status, provider, dataset_key,
                      dagster_run_id, trigger_kind, operation_registry_version,
                      dagster_run_status
                    ) VALUES
                    (
                      :mismatched_job, 'legacy_mismatched_direct', NULL, '{}'::jsonb,
                      'done', 'old-provider', 'old-dataset', NULL, NULL, NULL, NULL
                    ),
                    (
                      :paired_non_direct_job, 'legacy_paired_non_direct', NULL, '{}'::jsonb,
                      'done', 'paired-provider', 'paired-dataset', NULL, NULL, NULL, NULL
                    ),
                    (
                      :shape_check_job, 'feature_update_request', NULL, '{}'::jsonb,
                      'done', '123', '456', NULL, NULL, NULL, NULL
                    ),
                    (
                      :reserved_direct_root, 'provider_feature_load_run', NULL,
                      '{}'::jsonb, 'done', NULL, NULL,
                      'reserved-direct-run', 'manual', 'registry-v1', 'SUCCESS'
                    ),
                    (
                      :reserved_direct_job, 'provider_feature_load', :reserved_direct_root,
                      '{}'::jsonb, 'done', 'reserved-provider', 'reserved-dataset',
                      'reserved-direct-run', NULL, NULL, NULL
                    ),
                    (
                      :reserved_non_direct_job, 'provider_feature_load_run', NULL,
                      '{}'::jsonb, 'done', NULL, NULL,
                      'reserved-non-direct-run', 'manual', 'registry-v1', 'SUCCESS'
                    ),
                    (
                      :shared_source_job, 'feature_update_request', NULL,
                      jsonb_build_object(
                        'request_id', CAST(:shared_loser AS text)
                      ), 'done', NULL, NULL,
                      NULL, 'update_request', NULL, NULL
                    ),
                    (
                      :quarantine_parent_job, 'quarantine_component_parent', NULL,
                      '{"component":"parent"}'::jsonb, 'done',
                      :quarantine_provider, :quarantine_dataset,
                      NULL, NULL, NULL, NULL
                    ),
                    (
                      :valid_orphan_job, 'feature_update_request', :quarantine_parent_job,
                      '{"component":"canonical"}'::jsonb, 'done', NULL, NULL,
                      NULL, 'update_request', NULL, NULL
                    ),
                    (
                      :quarantine_child_job, 'quarantine_component_child',
                      :valid_orphan_job, '{"component":"child"}'::jsonb, 'done',
                      :quarantine_provider, :quarantine_dataset,
                      NULL, NULL, NULL, NULL
                    ),
                    (
                      :running_owner_job, 'feature_update_request', NULL,
                      '{}'::jsonb, 'running', NULL, NULL,
                      :running_owner_run_id, 'update_request', NULL, NULL
                    )
                    """
                ),
                {
                    "mismatched_job": _MISMATCHED_DIRECT_SOURCE_JOB,
                    "paired_non_direct_job": _PAIRED_NON_DIRECT_SOURCE_JOB,
                    "shape_check_job": _SHAPE_CHECK_SOURCE_JOB,
                    "reserved_direct_root": _RESERVED_DIRECT_ROOT_JOB,
                    "reserved_direct_job": _RESERVED_DIRECT_SOURCE_JOB,
                    "reserved_non_direct_job": _RESERVED_NON_DIRECT_SOURCE_JOB,
                    "shared_source_job": _SHARED_SOURCE_JOB,
                    "shared_loser": _SHARED_LOSER_REQUEST,
                    "valid_orphan_job": _VALID_ORPHAN_JOB,
                    "quarantine_parent_job": _QUARANTINE_PARENT_JOB,
                    "quarantine_child_job": _QUARANTINE_CHILD_JOB,
                    "quarantine_provider": _QUARANTINE_PROVIDER,
                    "quarantine_dataset": _QUARANTINE_DATASET,
                    "running_owner_job": _RUNNING_OWNER_JOB,
                    "running_owner_run_id": _RUNNING_OWNER_RUN_ID,
                },
            )
            await connection.execute(
                text(
                    """
                    INSERT INTO ops.import_job_events (
                      event_id, job_id, level, code, message, payload,
                      occurred_at
                    ) VALUES (
                      :event_id, :job_id, 'info', 'legacy.component.audit',
                      'quarantine component audit',
                      jsonb_build_object('preserved', true),
                      TIMESTAMPTZ '2099-01-01 00:00:00+00'
                    )
                    """
                ),
                {"event_id": _QUARANTINE_EVENT_ID, "job_id": _VALID_ORPHAN_JOB},
            )
            await connection.execute(
                text(
                    """
                    INSERT INTO ops.feature_update_requests (
                      request_id, scope_type, scope, run_mode, status,
                      dagster_run_id, job_id
                    ) VALUES (
                      :request_id, 'feature_ids',
                      '{"type":"feature_ids","feature_ids":[]}'::jsonb,
                      'queued', 'running', :dagster_run_id, :job_id
                    )
                    """
                ),
                {
                    "request_id": _RUNNING_OWNER_REQUEST,
                    "dagster_run_id": _RUNNING_OWNER_RUN_ID,
                    "job_id": _RUNNING_OWNER_JOB,
                },
            )
            await connection.execute(
                text(
                    """
                    INSERT INTO ops.feature_update_requests (
                      request_id, scope_type, scope, providers, dataset_keys,
                      run_mode, status, job_id
                    ) VALUES
                    (
                      :jobless_direct, 'provider_dataset',
                      jsonb_build_object(
                        'type', 'provider_dataset',
                        'provider', 'direct-provider',
                        'dataset_key', 'direct-dataset'
                      ),
                      jsonb_build_array('direct-provider'),
                      jsonb_build_array('direct-dataset'),
                      'queued', 'queued', NULL
                    ),
                    (
                      :jobless_non_direct, 'bbox',
                      jsonb_build_object(
                        'type', 'bbox', 'min_lon', 126, 'min_lat', 37,
                        'max_lon', 127, 'max_lat', 38
                      ),
                      '[]'::jsonb, '[]'::jsonb,
                      'queued', 'done', NULL
                    ),
                    (
                      :mismatched_direct, 'provider_dataset',
                      jsonb_build_object(
                        'type', 'provider_dataset',
                        'provider', 'canonical-provider',
                        'dataset_key', 'canonical-dataset'
                      ),
                      '[]'::jsonb, '[]'::jsonb,
                      'queued', 'queued', :mismatched_job
                    ),
                    (
                      :paired_non_direct, 'bbox',
                      jsonb_build_object(
                        'type', 'bbox', 'min_lon', 128, 'min_lat', 35,
                        'max_lon', 129, 'max_lat', 36
                      ),
                      '[]'::jsonb, '[]'::jsonb,
                      'queued', 'queued', :paired_non_direct_job
                    ),
                    (
                      :shape_check_request, 'feature_ids',
                      jsonb_build_object('type', 'feature_ids', 'feature_ids', '[]'::jsonb),
                      '[]'::jsonb, '[]'::jsonb,
                      'queued', 'done', :shape_check_job
                    ),
                    (
                      :reserved_direct, 'provider_dataset',
                      jsonb_build_object(
                        'type', 'provider_dataset',
                        'provider', 'reserved-provider',
                        'dataset_key', 'reserved-dataset'
                      ),
                      '[]'::jsonb, '[]'::jsonb,
                      'queued', 'done', :reserved_direct_job
                    ),
                    (
                      :reserved_non_direct, 'bbox',
                      jsonb_build_object(
                        'type', 'bbox', 'min_lon', 126, 'min_lat', 37,
                        'max_lon', 127, 'max_lat', 38
                      ),
                      '[]'::jsonb, '[]'::jsonb,
                      'queued', 'done', :reserved_non_direct_job
                    ),
                    (
                      :shared_owner, 'feature_ids',
                      jsonb_build_object('type', 'feature_ids', 'feature_ids', '[]'::jsonb),
                      '[]'::jsonb, '[]'::jsonb,
                      'queued', 'done', :shared_source_job
                    ),
                    (
                      :shared_loser, 'feature_ids',
                      jsonb_build_object('type', 'feature_ids', 'feature_ids', '[]'::jsonb),
                      '[]'::jsonb, '[]'::jsonb,
                      'queued', 'done', :shared_source_job
                    )
                    """
                ),
                {
                    "jobless_direct": _JOBLESS_DIRECT_REQUEST,
                    "jobless_non_direct": _JOBLESS_NON_DIRECT_REQUEST,
                    "mismatched_direct": _MISMATCHED_DIRECT_REQUEST,
                    "paired_non_direct": _PAIRED_NON_DIRECT_REQUEST,
                    "shape_check_request": _SHAPE_CHECK_REQUEST,
                    "shape_check_job": _SHAPE_CHECK_SOURCE_JOB,
                    "reserved_direct": _RESERVED_DIRECT_REQUEST,
                    "reserved_non_direct": _RESERVED_NON_DIRECT_REQUEST,
                    "mismatched_job": _MISMATCHED_DIRECT_SOURCE_JOB,
                    "paired_non_direct_job": _PAIRED_NON_DIRECT_SOURCE_JOB,
                    "reserved_direct_job": _RESERVED_DIRECT_SOURCE_JOB,
                    "reserved_non_direct_job": _RESERVED_NON_DIRECT_SOURCE_JOB,
                    "shared_owner": _SHARED_OWNER_REQUEST,
                    "shared_loser": _SHARED_LOSER_REQUEST,
                    "shared_source_job": _SHARED_SOURCE_JOB,
                },
            )
            await connection.execute(
                text(
                    """
                    UPDATE ops.feature_update_requests
                       SET update_policy = jsonb_build_object(
                         'mode', 'refresh_existing',
                         'include_inactive', true,
                         'force_provider_call', false,
                         'dedup_after_load', true,
                         'consistency_check_after_load', false,
                         'prevent_provider_reactivation', true
                       )
                     WHERE request_id = :request_id
                    """
                ),
                {"request_id": _JOBLESS_DIRECT_REQUEST},
            )

        await target_engine.dispose()
        await asyncio.to_thread(_run_alembic, target_dsn, _TARGET_REVISION)
        target_engine = make_async_engine(target_dsn)
        async with target_engine.begin() as connection:
            definitions = await _index_definitions(connection)
            revision = (
                await connection.execute(text("SELECT version_num FROM alembic_version"))
            ).scalar_one()
            request_rows = {
                str(row.request_id): row
                for row in await connection.execute(
                    text(
                        """
                        SELECT
                          request.request_id,
                          request.job_id,
                          request.generation,
                          request.providers,
                          request.dataset_keys,
                          request.update_policy,
                          job.kind,
                          job.payload,
                          job.status AS job_status,
                          job.progress,
                          job.provider,
                          job.dataset_key,
                          job.trigger_kind,
                          job.dagster_run_id
                        FROM ops.feature_update_requests AS request
                        JOIN ops.import_jobs AS job ON job.job_id = request.job_id
                        WHERE request.request_id = ANY(CAST(:request_ids AS uuid[]))
                        ORDER BY request.request_id
                        """
                    ),
                    {
                        "request_ids": [
                            _JOBLESS_DIRECT_REQUEST,
                            _JOBLESS_NON_DIRECT_REQUEST,
                            _MISMATCHED_DIRECT_REQUEST,
                            _PAIRED_NON_DIRECT_REQUEST,
                            _SHAPE_CHECK_REQUEST,
                            _RESERVED_DIRECT_REQUEST,
                            _RESERVED_NON_DIRECT_REQUEST,
                            _SHARED_OWNER_REQUEST,
                            _SHARED_LOSER_REQUEST,
                            _RUNNING_OWNER_REQUEST,
                        ]
                    },
                )
            }
            request_contract = await _request_job_contract(connection)
            constraints = await _identity_constraints(connection)
            (
                member_columns,
                member_constraints,
                member_index,
            ) = await _cancellation_member_contract(connection)
            triggers = await _identity_triggers(connection)
            job_index = await _feature_update_job_index_definition(
                connection,
                index_name="uq_feature_update_requests_job_id",
            )

            assert set(definitions) == _EXPECTED_INDEX_NAMES
            assert _REMOVED_DIRECT_INDEX_NAMES.isdisjoint(definitions)
            assert "(occurred_at DESC, event_id DESC)" in definitions["idx_import_job_events_time"]
            job_audit = definitions["idx_import_job_events_job_time"]
            assert "(job_id, occurred_at DESC, event_id DESC)" in job_audit
            provider_audit = definitions["idx_import_job_events_provider_time"]
            assert "(provider, occurred_at DESC, event_id DESC)" in provider_audit
            assert "provider IS NOT NULL" in provider_audit
            dataset_audit = definitions["idx_import_job_events_dataset_time"]
            assert "(dataset_key, occurred_at DESC, event_id DESC)" in dataset_audit
            assert "dataset_key IS NOT NULL" in dataset_audit
            pair_audit = definitions["idx_import_job_events_provider_dataset_time"]
            assert "(provider, dataset_key, occurred_at DESC, event_id DESC)" in pair_audit
            assert "provider IS NOT NULL" in pair_audit
            assert "dataset_key IS NOT NULL" in pair_audit
            level_audit = definitions["idx_import_job_events_level_time"]
            assert "(level, occurred_at DESC, event_id DESC)" in level_audit
            for index_name in (
                "idx_import_job_events_time",
                "idx_import_job_events_job_time",
                "idx_import_job_events_provider_time",
                "idx_import_job_events_dataset_time",
                "idx_import_job_events_provider_dataset_time",
                "idx_import_job_events_level_time",
            ):
                assert "quarantined_at IS NULL" in definitions[index_name]
            assert (
                "USING gin (providers)"
                in definitions["idx_feature_update_providers_gin"]
            )
            assert (
                "USING gin (dataset_keys)"
                in definitions["idx_feature_update_dataset_keys_gin"]
            )
            assert "(priority DESC, created_at, request_id)" in definitions[
                "idx_feature_update_priority"
            ]
            assert "(created_at DESC, request_id DESC)" in definitions[
                "idx_feature_update_created"
            ]
            queue_index = definitions["idx_import_jobs_feature_update_queue"]
            assert "(job_id)" in queue_index
            assert "kind = 'feature_update_request'" in queue_index
            assert "status = 'queued'" in queue_index
            assert "cancellation_id IS NULL" in queue_index
            quarantine_index = definitions["idx_import_jobs_quarantined"]
            assert "(quarantined_at DESC, job_id DESC)" in quarantine_index
            assert "quarantined_at IS NOT NULL" in quarantine_index
            assert revision == _TARGET_REVISION
            assert request_contract == ("NO", "RESTRICT")
            request_columns = await _request_columns(connection)
            assert {"generation", "matched_scope", "job_id"} <= request_columns
            assert _REQUEST_LIFECYCLE_COLUMNS.isdisjoint(request_columns)
            assert "dry_run" not in request_columns
            assert {"quarantined_at", "quarantine_reason"} <= (
                await _import_job_columns(connection)
            )
            assert "quarantined_at" in await _import_job_event_columns(connection)
            assert member_columns == {"job_id"}
            assert "PRIMARY KEY (cancellation_id, job_id)" in member_constraints[
                "pk_pipeline_cancellation_members"
            ]
            assert "FOREIGN KEY (job_id)" in member_constraints[
                "fk_pipeline_cancellation_members_job"
            ]
            assert "ON DELETE RESTRICT" in member_constraints[
                "fk_pipeline_cancellation_members_job"
            ]
            assert "operation_kind IS NULL" in member_constraints[
                "ck_pipeline_cancellation_members_operation_kind"
            ]
            assert "(job_id, updated_at DESC, cancellation_id DESC)" in member_index
            assert "UNIQUE INDEX" in job_index
            duplicate_job_index = (
                await connection.execute(
                    text(
                        """
                        SELECT count(*)
                        FROM pg_indexes
                        WHERE schemaname = 'ops'
                          AND tablename = 'feature_update_requests'
                          AND indexname = 'idx_feature_update_job'
                        """
                    )
                )
            ).scalar_one()
            assert duplicate_job_index == 0
            assert await _dry_run_column_contract(connection) is None
            assert triggers == {
                "trg_import_jobs_identity_immutable",
                "trg_feature_update_requests_job_identity",
                "trg_import_jobs_feature_update_pair",
                "trg_feature_update_requests_mutation_guard",
                "trg_import_jobs_feature_update_append_only",
                "trg_import_jobs_quarantine_immutable",
                "trg_import_job_events_quarantine_immutable",
                "trg_import_job_events_clock",
                "trg_import_job_event_clock_mutation_guard",
                "trg_import_job_event_clock_truncate_guard",
                "trg_pipeline_cancellation_members_reject_quarantine",
            }
            event_clock_before = await _import_job_event_clock_row(connection)
            assert event_clock_before is not None
            assert event_clock_before[:2] == (True, 0)
            event_clock_constraints = await _import_job_event_clock_constraints(connection)
            assert "PRIMARY KEY (clock_id)" in event_clock_constraints[
                "pk_import_job_event_clock"
            ]
            assert "CHECK (clock_id)" in event_clock_constraints[
                "ck_import_job_event_clock_singleton"
            ]
            assert "revision >= 0" in event_clock_constraints[
                "ck_import_job_event_clock_revision_nonnegative"
            ]
            assert await _cancellation_quarantine_guard_function_exists(connection)
            assert await _scope_validator_exists(connection)
            assert await _filter_validator_exists(connection)
            assert await _policy_validator_exists(connection)
            assert not await _temporary_filter_functions_exist(connection)
            assert await _filter_column_contract(connection) == {
                "providers": ("ARRAY", "_text", "'{}'::text[]"),
                "dataset_keys": ("ARRAY", "_text", "'{}'::text[]"),
            }
            scope_shape_check = constraints["ck_feature_update_requests_scope_shape"]
            assert "is_valid_feature_update_scope" in scope_shape_check
            assert "scope_type" in scope_shape_check
            assert "is_valid_feature_update_filter_array" in constraints[
                "ck_feature_update_requests_providers_shape"
            ]
            assert "32" in constraints["ck_feature_update_requests_providers_shape"]
            assert "is_valid_feature_update_filter_array" in constraints[
                "ck_feature_update_requests_dataset_keys_shape"
            ]
            assert "64" in constraints["ck_feature_update_requests_dataset_keys_shape"]
            assert "is_valid_feature_update_policy" in constraints[
                "ck_feature_update_requests_update_policy_shape"
            ]
            assert "cardinality(providers) = 0" in constraints[
                "ck_feature_update_requests_direct_filters_empty"
            ]
            assert "priority >= 0" in constraints[
                "ck_feature_update_requests_priority_range"
            ]
            assert "priority <= 1000" in constraints[
                "ck_feature_update_requests_priority_range"
            ]
            assert "generation > 0" in constraints[
                "ck_feature_update_requests_generation_positive"
            ]
            assert "jsonb_typeof(matched_scope) = 'object'" in constraints[
                "ck_feature_update_requests_matched_scope_object"
            ]
            assert "char_length(reason) <= 500" in constraints[
                "ck_feature_update_requests_reason_shape"
            ]
            update_request_shape = constraints["ck_import_jobs_update_request_shape"]
            assert "quarantined_at IS NOT NULL" in update_request_shape
            assert "parent_job_id IS NULL" in update_request_shape
            assert "load_batch_id IS NULL" in update_request_shape
            assert "trigger_kind = 'update_request'" in update_request_shape
            assert "operation_registry_version IS NULL" in update_request_shape
            assert "dagster_run_status IS NULL" in update_request_shape
            assert "payload = '{}'::jsonb" in update_request_shape
            assert "dagster_run_id = btrim(dagster_run_id)" in update_request_shape
            assert "dagster_run_id <> ''" in update_request_shape
            assert "status <> 'queued'" in update_request_shape
            assert "dagster_run_id IS NULL" in update_request_shape
            assert "status <> 'running'" in update_request_shape
            assert "dagster_run_id IS NOT NULL" in update_request_shape
            quarantine_shape = constraints["ck_import_jobs_quarantine_shape"]
            assert "quarantined_at IS NULL" in quarantine_shape
            assert "quarantine_reason IS NULL" in quarantine_shape
            assert "quarantined_at IS NOT NULL" in quarantine_shape
            assert "unlinked_feature_update_component" in quarantine_shape

            valid_scopes = (
                ("feature_ids", {"type": "feature_ids", "feature_ids": []}),
                (
                    "center_radius",
                    {
                        "type": "center_radius",
                        "center": {"lon": 127, "lat": 37},
                        "radius_km": 500,
                    },
                ),
                (
                    "sigungu_by_radius",
                    {
                        "type": "sigungu_by_radius",
                        "center": {"lon": 127, "lat": 37},
                        "radius_km": 1,
                        "match": "intersects",
                    },
                ),
                (
                    "bbox",
                    {
                        "type": "bbox",
                        "min_lon": -180,
                        "min_lat": -90,
                        "max_lon": 180,
                        "max_lat": 90,
                    },
                ),
                (
                    "provider_dataset",
                    {
                        "type": "provider_dataset",
                        "provider": "provider",
                        "dataset_key": "dataset",
                        "sync_scope": "sigungu:11",
                    },
                ),
                (
                    "cache_target_keys",
                    {
                        "type": "cache_target_keys",
                        "external_system": "pinvi",
                        "target_keys": [],
                        "scope_mode": "center_radius",
                    },
                ),
            )
            for scope_type, scope in valid_scopes:
                assert await _scope_validator_result(connection, scope_type, scope)

            invalid_scopes = (
                ("feature_ids", {"type": "feature_ids", "feature_ids": ["\t"]}),
                (
                    "center_radius",
                    {
                        "type": "center_radius",
                        "center": {"lon": 181, "lat": 37},
                        "radius_km": 1,
                    },
                ),
                (
                    "sigungu_by_radius",
                    {
                        "type": "sigungu_by_radius",
                        "center": {"lon": 127, "lat": 37},
                        "radius_km": 1,
                        "match": "contains_center",
                    },
                ),
                (
                    "bbox",
                    {
                        "type": "bbox",
                        "min_lon": 128,
                        "min_lat": 37,
                        "max_lon": 127,
                        "max_lat": 38,
                    },
                ),
                (
                    "provider_dataset",
                    {
                        "type": "provider_dataset",
                        "provider": "\n",
                        "dataset_key": "dataset",
                    },
                ),
                (
                    "cache_target_keys",
                    {
                        "type": "cache_target_keys",
                        "external_system": "pinvi",
                        "target_keys": [],
                        "scope_mode": "center_radius",
                        "radius_km": 501,
                    },
                ),
            )
            for scope_type, scope in invalid_scopes:
                assert not await _scope_validator_result(connection, scope_type, scope)

            for values, max_items in (
                ([], 32),
                (["provider-a", "provider-b"], 32),
                (["dataset-a"], 64),
                (["x" * 128], 32),
                ([f"provider-{index}" for index in range(32)], 32),
                ([f"dataset-{index}" for index in range(64)], 64),
            ):
                assert await _filter_validator_result(connection, values, max_items)
            for values, max_items in (
                (None, 32),
                ([" padded"], 32),
                ([""], 32),
                (["duplicate", "duplicate"], 32),
                (["x" * 129], 32),
                ([f"provider-{index}" for index in range(33)], 32),
                ([f"dataset-{index}" for index in range(65)], 64),
                ([], -1),
            ):
                assert not await _filter_validator_result(connection, values, max_items)
            noncanonical_lower_bound = (
                await connection.execute(
                    text(
                        "SELECT ops.is_valid_feature_update_filter_array("
                        "CAST('[0:1]={provider-a,provider-b}' AS text[]), 32)"
                    )
                )
            ).scalar_one()
            assert not noncanonical_lower_bound

            for policy in (
                {},
                {"mode": "refresh_existing"},
                {
                    "mode": "refresh_existing",
                    "include_inactive": True,
                    "force_provider_call": False,
                    "dedup_after_load": True,
                    "consistency_check_after_load": False,
                    "prevent_provider_reactivation": True,
                },
            ):
                assert await _policy_validator_result(connection, policy)
            for policy in (
                None,
                [],
                {"unknown": True},
                {"mode": "replace_all"},
                {"include_inactive": "true"},
                {"force_provider_call": []},
                {"prevent_provider_reactivation": None},
            ):
                assert not await _policy_validator_result(connection, policy)

            assert set(request_rows) == {
                _JOBLESS_DIRECT_REQUEST,
                _JOBLESS_NON_DIRECT_REQUEST,
                _MISMATCHED_DIRECT_REQUEST,
                _PAIRED_NON_DIRECT_REQUEST,
                _SHAPE_CHECK_REQUEST,
                _RESERVED_DIRECT_REQUEST,
                _RESERVED_NON_DIRECT_REQUEST,
                _SHARED_OWNER_REQUEST,
                _SHARED_LOSER_REQUEST,
                _RUNNING_OWNER_REQUEST,
            }
            assert len({str(row.job_id) for row in request_rows.values()}) == 10
            assert str(request_rows[_SHARED_OWNER_REQUEST].job_id) == _SHARED_SOURCE_JOB
            assert str(request_rows[_SHARED_LOSER_REQUEST].job_id) != _SHARED_SOURCE_JOB
            assert str(request_rows[_RUNNING_OWNER_REQUEST].job_id) == _RUNNING_OWNER_JOB
            assert (
                request_rows[_RUNNING_OWNER_REQUEST].dagster_run_id
                == _RUNNING_OWNER_RUN_ID
            )
            assert request_rows[_RUNNING_OWNER_REQUEST].job_status == "running"
            assert request_rows[_SHARED_OWNER_REQUEST].dagster_run_id is None
            assert request_rows[_SHARED_OWNER_REQUEST].job_status == "done"
            assert str(request_rows[_MISMATCHED_DIRECT_REQUEST].job_id) != (
                _MISMATCHED_DIRECT_SOURCE_JOB
            )
            assert str(request_rows[_PAIRED_NON_DIRECT_REQUEST].job_id) != (
                _PAIRED_NON_DIRECT_SOURCE_JOB
            )
            assert str(request_rows[_SHAPE_CHECK_REQUEST].job_id) != _SHAPE_CHECK_SOURCE_JOB
            assert str(request_rows[_RESERVED_DIRECT_REQUEST].job_id) != (
                _RESERVED_DIRECT_SOURCE_JOB
            )
            assert str(request_rows[_RESERVED_NON_DIRECT_REQUEST].job_id) != (
                _RESERVED_NON_DIRECT_SOURCE_JOB
            )
            assert (
                request_rows[_JOBLESS_DIRECT_REQUEST].provider,
                request_rows[_JOBLESS_DIRECT_REQUEST].dataset_key,
            ) == ("direct-provider", "direct-dataset")
            assert request_rows[_JOBLESS_DIRECT_REQUEST].providers == []
            assert request_rows[_JOBLESS_DIRECT_REQUEST].dataset_keys == []
            assert request_rows[_JOBLESS_DIRECT_REQUEST].update_policy == {
                "mode": "refresh_existing",
                "include_inactive": True,
                "force_provider_call": False,
                "dedup_after_load": True,
                "consistency_check_after_load": False,
                "prevent_provider_reactivation": True,
            }
            assert (
                request_rows[_MISMATCHED_DIRECT_REQUEST].provider,
                request_rows[_MISMATCHED_DIRECT_REQUEST].dataset_key,
            ) == ("canonical-provider", "canonical-dataset")
            assert (
                request_rows[_JOBLESS_NON_DIRECT_REQUEST].provider,
                request_rows[_JOBLESS_NON_DIRECT_REQUEST].dataset_key,
            ) == (None, None)
            assert (
                request_rows[_PAIRED_NON_DIRECT_REQUEST].provider,
                request_rows[_PAIRED_NON_DIRECT_REQUEST].dataset_key,
            ) == (None, None)
            assert (
                request_rows[_RESERVED_DIRECT_REQUEST].provider,
                request_rows[_RESERVED_DIRECT_REQUEST].dataset_key,
            ) == ("reserved-provider", "reserved-dataset")
            assert (
                request_rows[_RESERVED_NON_DIRECT_REQUEST].provider,
                request_rows[_RESERVED_NON_DIRECT_REQUEST].dataset_key,
            ) == (None, None)
            for request_id, row in request_rows.items():
                assert row.kind == "feature_update_request"
                assert row.payload == {}
                assert row.generation == 1
                expected_progress = (
                    0
                    if request_id == _SHARED_OWNER_REQUEST
                    else 100
                    if row.job_status == "done"
                    else 0
                )
                assert row.progress == expected_progress
                assert row.trigger_kind == "update_request"

            migration_audit = {
                str(row.request_id): (str(row.code), row.payload)
                for row in await connection.execute(
                    text(
                        """
                        SELECT request.request_id, event.code, event.payload
                        FROM ops.feature_update_requests AS request
                        JOIN ops.import_job_events AS event
                          ON event.job_id = request.job_id
                        WHERE request.request_id = ANY(CAST(:request_ids AS uuid[]))
                          AND event.code = 'migration.feature_update_request_relinked'
                        ORDER BY request.request_id
                        """
                    ),
                    {"request_ids": list(request_rows)},
                )
            }
            expected_audit_payloads = {
                _JOBLESS_DIRECT_REQUEST: {},
                _JOBLESS_NON_DIRECT_REQUEST: {},
                _MISMATCHED_DIRECT_REQUEST: {
                    "source_job_id": _MISMATCHED_DIRECT_SOURCE_JOB
                },
                _PAIRED_NON_DIRECT_REQUEST: {
                    "source_job_id": _PAIRED_NON_DIRECT_SOURCE_JOB
                },
                _SHAPE_CHECK_REQUEST: {"source_job_id": _SHAPE_CHECK_SOURCE_JOB},
                _RESERVED_DIRECT_REQUEST: {
                    "source_job_id": _RESERVED_DIRECT_SOURCE_JOB
                },
                _RESERVED_NON_DIRECT_REQUEST: {
                    "source_job_id": _RESERVED_NON_DIRECT_SOURCE_JOB
                },
                _SHARED_LOSER_REQUEST: {"source_job_id": _SHARED_SOURCE_JOB},
            }
            assert migration_audit == {
                request_id: (
                    "migration.feature_update_request_relinked",
                    payload,
                )
                for request_id, payload in expected_audit_payloads.items()
            }

            component_ids = {
                _QUARANTINE_PARENT_JOB,
                _VALID_ORPHAN_JOB,
                _QUARANTINE_CHILD_JOB,
            }
            quarantined_component = {
                str(row.job_id): row
                for row in await connection.execute(
                    text(
                        """
                        SELECT
                          job_id, kind, payload, parent_job_id, provider, dataset_key,
                          quarantined_at, quarantine_reason
                        FROM ops.import_jobs
                        WHERE job_id = ANY(CAST(:job_ids AS uuid[]))
                        ORDER BY job_id
                        """
                    ),
                    {"job_ids": sorted(component_ids)},
                )
            }
            assert set(quarantined_component) == component_ids
            assert {
                job_id: (
                    row.kind,
                    row.payload,
                    str(row.parent_job_id) if row.parent_job_id is not None else None,
                    row.provider,
                    row.dataset_key,
                )
                for job_id, row in quarantined_component.items()
            } == {
                _QUARANTINE_PARENT_JOB: (
                    "quarantine_component_parent",
                    {"component": "parent"},
                    None,
                    _QUARANTINE_PROVIDER,
                    _QUARANTINE_DATASET,
                ),
                _VALID_ORPHAN_JOB: (
                    "feature_update_request",
                    {"component": "canonical"},
                    _QUARANTINE_PARENT_JOB,
                    None,
                    None,
                ),
                _QUARANTINE_CHILD_JOB: (
                    "quarantine_component_child",
                    {"component": "child"},
                    _VALID_ORPHAN_JOB,
                    _QUARANTINE_PROVIDER,
                    _QUARANTINE_DATASET,
                ),
            }
            assert {
                row.quarantine_reason for row in quarantined_component.values()
            } == {"unlinked_feature_update_component"}
            assert all(
                row.quarantined_at is not None
                for row in quarantined_component.values()
            )
            assert len(
                {row.quarantined_at for row in quarantined_component.values()}
            ) == 1

            replaced_source = (
                await connection.execute(
                    text(
                        """
                        SELECT kind, payload, quarantined_at, quarantine_reason
                        FROM ops.import_jobs
                        WHERE job_id = :job_id
                        """
                    ),
                    {"job_id": _SHAPE_CHECK_SOURCE_JOB},
                )
            ).one()
            assert replaced_source.kind == "feature_update_request"
            assert replaced_source.payload == {}
            assert replaced_source.quarantined_at is not None
            assert (
                replaced_source.quarantine_reason
                == "unlinked_feature_update_component"
            )

            visible_job_ids = {
                str(row.job_id)
                for row in await connection.execute(
                    text(
                        "SELECT job_id FROM ops.import_jobs "
                        "WHERE quarantined_at IS NULL"
                    )
                )
            }
            assert component_ids.isdisjoint(visible_job_ids)

            async with AsyncSession(target_engine) as session:
                # 이 테스트는 0052 단독 schema를 검증한다. 최신 repository의
                # 0053 typed sync_scope 계약을 과거 revision에 역이식하지 않고,
                # 0052가 소유한 quarantine visibility만 직접 확인한다.
                visible_event_ids = {
                    str(row.event_id)
                    for row in await session.execute(
                        text(
                            """
                            SELECT event.event_id
                            FROM ops.import_job_events AS event
                            JOIN ops.import_jobs AS job ON job.job_id = event.job_id
                            WHERE event.quarantined_at IS NULL
                              AND job.quarantined_at IS NULL
                            """
                        )
                    )
                }
                assert _QUARANTINE_EVENT_ID not in visible_event_ids
                quarantined_job_event_count = await session.scalar(
                    text(
                        """
                        SELECT count(*)
                        FROM ops.import_job_events AS event
                        JOIN ops.import_jobs AS job ON job.job_id = event.job_id
                        WHERE event.job_id = CAST(:job_id AS uuid)
                          AND event.quarantined_at IS NULL
                          AND job.quarantined_at IS NULL
                        """
                    ),
                    {"job_id": _VALID_ORPHAN_JOB},
                )
                assert quarantined_job_event_count == 0
                live_snapshot = await _import_jobs_snapshot(session)
                assert live_snapshot["event_clock_revision"] == 0
                assert live_snapshot["latest_event_id"] != _QUARANTINE_EVENT_ID

            cancellation_linked_ids = {
                str(row.job_id)
                for row in await connection.execute(
                    text(
                        """
                        SELECT cancellation.root_id AS job_id
                        FROM ops.pipeline_cancellations AS cancellation
                        WHERE cancellation.root_kind = 'import_job'
                          AND cancellation.root_id = ANY(CAST(:job_ids AS uuid[]))
                        UNION
                        SELECT member.job_id
                        FROM ops.pipeline_cancellation_members AS member
                        WHERE member.job_id = ANY(CAST(:job_ids AS uuid[]))
                        """
                    ),
                    {"job_ids": sorted(component_ids)},
                )
            }
            assert cancellation_linked_ids == set()

            quarantined_job_before = (
                await connection.execute(
                    text(
                        """
                        SELECT kind, payload, status, parent_job_id,
                               quarantined_at, quarantine_reason
                        FROM ops.import_jobs
                        WHERE job_id = :job_id
                        """
                    ),
                    {"job_id": _VALID_ORPHAN_JOB},
                )
            ).one()
            preserved_event_before = (
                await connection.execute(
                    text(
                        """
                        SELECT event_id, job_id, code, message, payload,
                               quarantined_at, occurred_at
                        FROM ops.import_job_events
                        WHERE event_id = :event_id
                        """
                    ),
                    {"event_id": _QUARANTINE_EVENT_ID},
                )
            ).one()
            assert preserved_event_before.quarantined_at == (
                quarantined_job_before.quarantined_at
            )

            with pytest.raises(IntegrityError):
                async with connection.begin_nested():
                    await connection.execute(
                        text(
                            """
                            INSERT INTO ops.import_jobs (
                              job_id, kind, payload, status,
                              quarantined_at, quarantine_reason
                            ) VALUES (
                              'b1000000-0000-4000-9000-000000000001',
                              'runtime-quarantine-forbidden', '{}'::jsonb, 'done',
                              now(), 'unlinked_feature_update_component'
                            )
                            """
                        )
                    )
            with pytest.raises(IntegrityError):
                async with connection.begin_nested():
                    await connection.execute(
                        text(
                            """
                            UPDATE ops.import_jobs
                               SET quarantined_at = now(),
                                   quarantine_reason =
                                     'unlinked_feature_update_component'
                             WHERE job_id = :job_id
                            """
                        ),
                        {"job_id": _SHARED_SOURCE_JOB},
                    )

            quarantined_updates = (
                "UPDATE ops.import_jobs "
                "SET payload = payload || jsonb_build_object('tampered', true) "
                "WHERE job_id = :job_id",
                "UPDATE ops.import_jobs SET status = 'failed' WHERE job_id = :job_id",
                "UPDATE ops.import_jobs SET parent_job_id = :parent_job_id "
                "WHERE job_id = :job_id",
            )
            for statement in quarantined_updates:
                with pytest.raises(IntegrityError):
                    async with connection.begin_nested():
                        await connection.execute(
                            text(statement),
                            {
                                "job_id": _VALID_ORPHAN_JOB,
                                "parent_job_id": _RESERVED_DIRECT_ROOT_JOB,
                            },
                        )
            with pytest.raises(IntegrityError):
                async with connection.begin_nested():
                    await connection.execute(
                        text("DELETE FROM ops.import_jobs WHERE job_id = :job_id"),
                        {"job_id": _VALID_ORPHAN_JOB},
                    )

            with pytest.raises(IntegrityError):
                async with connection.begin_nested():
                    await connection.execute(
                        text(
                            """
                            INSERT INTO ops.import_job_events (
                              event_id, job_id, level, code, message, payload
                            ) VALUES (
                              'b2000000-0000-4000-9000-000000000002',
                              :job_id, 'warning', 'quarantine.append.forbidden',
                              'must fail', '{}'::jsonb
                            )
                            """
                        ),
                        {"job_id": _VALID_ORPHAN_JOB},
                    )
            with pytest.raises(IntegrityError):
                async with connection.begin_nested():
                    await connection.execute(
                        text(
                            """
                            INSERT INTO ops.import_job_events (
                              event_id, job_id, level, message, quarantined_at
                            ) VALUES (
                              'b2100000-0000-4000-9000-000000000010',
                              :job_id, 'info', 'runtime marker must fail', now()
                            )
                            """
                        ),
                        {"job_id": _RESERVED_DIRECT_ROOT_JOB},
                    )
            active_event_id = "b2200000-0000-4000-9000-000000000011"
            await connection.execute(
                text(
                    """
                    INSERT INTO ops.import_job_events (
                      event_id, job_id, level, message
                    ) VALUES (
                      :event_id, :job_id, 'info', 'active event marker guard'
                    )
                    """
                ),
                {
                    "event_id": active_event_id,
                    "job_id": _RESERVED_DIRECT_ROOT_JOB,
                },
            )
            event_clock_after_insert = await _import_job_event_clock_row(connection)
            assert event_clock_after_insert is not None
            assert event_clock_after_insert[1] == event_clock_before[1] + 1
            assert event_clock_after_insert[2] >= event_clock_before[2]
            with pytest.raises(IntegrityError):
                async with connection.begin_nested():
                    await connection.execute(
                        text("DELETE FROM ops.import_job_event_clock WHERE clock_id")
                    )
            for statement in (
                "UPDATE ops.import_job_event_clock "
                "SET revision = revision + 1 WHERE clock_id",
                "TRUNCATE TABLE ops.import_job_event_clock",
            ):
                with pytest.raises(IntegrityError):
                    async with connection.begin_nested():
                        await connection.execute(text(statement))
            async def truncate_events_and_force_rollback() -> None:
                async with connection.begin_nested():
                    clock_before_truncate = await _import_job_event_clock_row(connection)
                    await connection.execute(text("TRUNCATE TABLE ops.import_job_events"))
                    clock_after_truncate = await _import_job_event_clock_row(connection)
                    assert clock_before_truncate is not None
                    assert clock_after_truncate is not None
                    assert clock_after_truncate[1] == clock_before_truncate[1] + 1
                    raise RuntimeError("force event truncate rollback")

            with pytest.raises(RuntimeError, match="force event truncate rollback"):
                await truncate_events_and_force_rollback()
            assert await _import_job_event_clock_row(connection) == event_clock_after_insert
            rollback_event_id = "b2300000-0000-4000-9000-000000000012"

            async def insert_event_and_force_rollback() -> None:
                async with connection.begin_nested():
                    await connection.execute(
                        text(
                            """
                            INSERT INTO ops.import_job_events (
                              event_id, job_id, level, message
                            ) VALUES (
                              :event_id, :job_id, 'info', 'rollback event clock'
                            )
                            """
                        ),
                        {
                            "event_id": rollback_event_id,
                            "job_id": _RESERVED_DIRECT_ROOT_JOB,
                        },
                    )
                    raise RuntimeError("force event rollback")

            with pytest.raises(RuntimeError, match="force event rollback"):
                await insert_event_and_force_rollback()
            assert await _import_job_event_clock_row(connection) == event_clock_after_insert
            assert not bool(
                await connection.scalar(
                    text(
                        "SELECT EXISTS ("
                        "SELECT 1 FROM ops.import_job_events WHERE event_id = :event_id"
                        ")"
                    ),
                    {"event_id": rollback_event_id},
                )
            )
            await connection.execute(
                text(
                    "UPDATE ops.import_job_events "
                    "SET message = 'active event clock update' "
                    "WHERE event_id = :event_id"
                ),
                {"event_id": active_event_id},
            )
            event_clock_after_update = await _import_job_event_clock_row(connection)
            assert event_clock_after_update is not None
            assert event_clock_after_update[1] == event_clock_after_insert[1] + 1
            with pytest.raises(IntegrityError):
                async with connection.begin_nested():
                    await connection.execute(
                        text(
                            "UPDATE ops.import_job_events "
                            "SET quarantined_at = now() "
                            "WHERE event_id = :event_id"
                        ),
                        {"event_id": active_event_id},
                    )
            for statement in (
                "UPDATE ops.import_job_events SET message = 'tampered' "
                "WHERE event_id = :event_id",
                "DELETE FROM ops.import_job_events WHERE event_id = :event_id",
            ):
                with pytest.raises(IntegrityError):
                    async with connection.begin_nested():
                        await connection.execute(
                            text(statement),
                            {"event_id": _QUARANTINE_EVENT_ID},
                        )
            with pytest.raises(IntegrityError):
                async with connection.begin_nested():
                    await connection.execute(
                        text(
                            """
                            INSERT INTO ops.import_jobs (
                              job_id, kind, payload, status, parent_job_id
                            ) VALUES (
                              'b3000000-0000-4000-9000-000000000003',
                              'quarantine-child-forbidden', '{}'::jsonb, 'done',
                              :parent_job_id
                            )
                            """
                        ),
                        {"parent_job_id": _VALID_ORPHAN_JOB},
                    )
            attach_candidate_id = "b4000000-0000-4000-9000-000000000004"
            await connection.execute(
                text(
                    """
                    INSERT INTO ops.import_jobs (job_id, kind, payload, status)
                    VALUES (:job_id, 'attach-candidate', '{}'::jsonb, 'done')
                    """
                ),
                {"job_id": attach_candidate_id},
            )
            with pytest.raises(IntegrityError):
                async with connection.begin_nested():
                    await connection.execute(
                        text(
                            """
                            UPDATE ops.import_jobs
                               SET parent_job_id = :parent_job_id
                             WHERE job_id = :job_id
                            """
                        ),
                        {
                            "job_id": attach_candidate_id,
                            "parent_job_id": _VALID_ORPHAN_JOB,
                        },
                    )
            assert (
                await connection.scalar(
                    text(
                        "SELECT parent_job_id FROM ops.import_jobs "
                        "WHERE job_id = :job_id"
                    ),
                    {"job_id": attach_candidate_id},
                )
                is None
            )
            with pytest.raises(IntegrityError):
                async with connection.begin_nested():
                    await connection.execute(
                        text(
                            """
                            INSERT INTO ops.feature_update_requests (
                              request_id, scope_type, scope, run_mode, job_id
                            ) VALUES (
                              'b5000000-0000-4000-8000-000000000005',
                              'feature_ids',
                              '{"type":"feature_ids","feature_ids":[]}'::jsonb,
                              'queued', :job_id
                            )
                            """
                        ),
                        {"job_id": _VALID_ORPHAN_JOB},
                    )

            await connection.execute(
                text(
                    """
                    INSERT INTO ops.pipeline_cancellations (
                      cancellation_id, root_kind, root_id, status,
                      requested_by, finished_at
                    ) VALUES (
                      :cancellation_id, 'import_job', :root_id, 'completed',
                      'migration-test', now()
                    )
                    """
                ),
                {
                    "cancellation_id": _QUARANTINE_CANCELLATION_ID,
                    "root_id": _RESERVED_DIRECT_ROOT_JOB,
                },
            )
            with pytest.raises(IntegrityError):
                async with connection.begin_nested():
                    await connection.execute(
                        text(
                            """
                            INSERT INTO ops.pipeline_cancellation_members (
                              cancellation_id, job_id, initial_status,
                              result, terminal_status
                            ) VALUES (
                              :cancellation_id, :job_id, 'done',
                              'already_terminal', 'done'
                            )
                            """
                        ),
                        {
                            "cancellation_id": _QUARANTINE_CANCELLATION_ID,
                            "job_id": _VALID_ORPHAN_JOB,
                        },
                    )
            await connection.execute(
                text(
                    """
                    INSERT INTO ops.pipeline_cancellation_members (
                      cancellation_id, job_id, initial_status,
                      result, terminal_status
                    ) VALUES (
                      :cancellation_id, :job_id, 'done',
                      'already_terminal', 'done'
                    )
                    """
                ),
                {
                    "cancellation_id": _QUARANTINE_CANCELLATION_ID,
                    "job_id": _RESERVED_DIRECT_ROOT_JOB,
                },
            )
            with pytest.raises(IntegrityError):
                async with connection.begin_nested():
                    await connection.execute(
                        text(
                            """
                            UPDATE ops.pipeline_cancellation_members
                               SET job_id = :quarantined_job_id
                             WHERE cancellation_id = :cancellation_id
                               AND job_id = :current_job_id
                            """
                        ),
                        {
                            "cancellation_id": _QUARANTINE_CANCELLATION_ID,
                            "current_job_id": _RESERVED_DIRECT_ROOT_JOB,
                            "quarantined_job_id": _VALID_ORPHAN_JOB,
                        },
                    )
            assert str(
                (
                    await connection.execute(
                        text(
                            """
                            SELECT job_id
                            FROM ops.pipeline_cancellation_members
                            WHERE cancellation_id = :cancellation_id
                            """
                        ),
                        {"cancellation_id": _QUARANTINE_CANCELLATION_ID},
                    )
                ).scalar_one()
            ) == _RESERVED_DIRECT_ROOT_JOB

            quarantined_job_after = (
                await connection.execute(
                    text(
                        """
                        SELECT kind, payload, status, parent_job_id,
                               quarantined_at, quarantine_reason
                        FROM ops.import_jobs
                        WHERE job_id = :job_id
                        """
                    ),
                    {"job_id": _VALID_ORPHAN_JOB},
                )
            ).one()
            preserved_event_after = (
                await connection.execute(
                    text(
                        """
                        SELECT event_id, job_id, code, message, payload,
                               quarantined_at, occurred_at
                        FROM ops.import_job_events
                        WHERE event_id = :event_id
                        """
                    ),
                    {"event_id": _QUARANTINE_EVENT_ID},
                )
            ).one()
            assert quarantined_job_after == quarantined_job_before
            assert preserved_event_after == preserved_event_before

            with pytest.raises(IntegrityError):
                async with connection.begin_nested():
                    await connection.execute(
                        text(
                            """
                            UPDATE ops.import_jobs
                               SET dagster_run_id = 'queued-owner-is-invalid'
                             WHERE job_id = :job_id
                            """
                        ),
                        {"job_id": str(request_rows[_JOBLESS_DIRECT_REQUEST].job_id)},
                    )
            with pytest.raises(IntegrityError):
                async with connection.begin_nested():
                    await connection.execute(
                        text(
                            """
                            UPDATE ops.import_jobs
                               SET status = 'running'
                             WHERE job_id = :job_id
                            """
                        ),
                        {"job_id": str(request_rows[_JOBLESS_DIRECT_REQUEST].job_id)},
                    )
            with pytest.raises(IntegrityError):
                async with connection.begin_nested():
                    await connection.execute(
                        text(
                            """
                            UPDATE ops.import_jobs
                               SET dagster_run_id = ' padded-owner '
                             WHERE job_id = :job_id
                            """
                        ),
                        {"job_id": _SHARED_SOURCE_JOB},
                    )

            mutable_request_id = _JOBLESS_DIRECT_REQUEST
            await connection.execute(
                text(
                    """
                    UPDATE ops.feature_update_requests
                       SET matched_scope = jsonb_build_object('feature_count', 3),
                           generation = generation + 1
                     WHERE request_id = :request_id
                    """
                ),
                {"request_id": mutable_request_id},
            )
            mutable_state = (
                await connection.execute(
                    text(
                        """
                        SELECT matched_scope, generation
                        FROM ops.feature_update_requests
                        WHERE request_id = :request_id
                        """
                    ),
                    {"request_id": mutable_request_id},
                )
            ).one()
            assert mutable_state.matched_scope == {"feature_count": 3}
            assert mutable_state.generation == 2
            with pytest.raises(IntegrityError):
                async with connection.begin_nested():
                    await connection.execute(
                        text(
                            """
                            UPDATE ops.feature_update_requests
                               SET generation = generation + 2
                             WHERE request_id = :request_id
                            """
                        ),
                        {"request_id": mutable_request_id},
                    )
            with pytest.raises(IntegrityError):
                async with connection.begin_nested():
                    await connection.execute(
                        text(
                            """
                            UPDATE ops.feature_update_requests
                               SET matched_scope = '[]'::jsonb
                             WHERE request_id = :request_id
                            """
                        ),
                        {"request_id": mutable_request_id},
                    )
            with pytest.raises(IntegrityError):
                async with connection.begin_nested():
                    await connection.execute(
                        text(
                            """
                            UPDATE ops.feature_update_requests
                               SET priority = 51
                             WHERE request_id = :request_id
                            """
                        ),
                        {"request_id": mutable_request_id},
                    )
            with pytest.raises(IntegrityError):
                async with connection.begin_nested():
                    await connection.execute(
                        text(
                            "DELETE FROM ops.feature_update_requests "
                            "WHERE request_id = :request_id"
                        ),
                        {"request_id": mutable_request_id},
                    )
            with pytest.raises(IntegrityError):
                async with connection.begin_nested():
                    await connection.execute(
                        text(
                            """
                            UPDATE ops.import_jobs
                               SET payload = jsonb_build_object(
                                 'request_id', CAST(:request_id AS text)
                               )
                             WHERE job_id = :job_id
                            """
                        ),
                        {
                            "request_id": mutable_request_id,
                            "job_id": str(request_rows[mutable_request_id].job_id),
                        },
                    )

            with pytest.raises(IntegrityError):
                async with connection.begin_nested():
                    await connection.execute(
                        text(
                            """
                            INSERT INTO ops.feature_update_requests (
                              request_id, scope_type, scope, run_mode, job_id
                            ) VALUES (
                              '50000000-0000-4000-8000-000000000005',
                              'bbox', '{"type":"bbox"}'::jsonb, 'queued', NULL
                            )
                            """
                        )
                    )
            with pytest.raises(IntegrityError):
                async with connection.begin_nested():
                    await connection.execute(
                        text(
                            """
                            INSERT INTO ops.feature_update_requests (
                              request_id, scope_type, scope, run_mode, job_id
                            ) VALUES (
                              '81000000-0000-4000-8000-000000000001',
                              'provider_dataset',
                              jsonb_build_object(
                                'type', 'provider_dataset',
                                'provider', 'other-provider',
                                'dataset_key', 'other-dataset'
                              ),
                              'queued', :job_id
                            )
                            """
                        ),
                        {"job_id": _MISMATCHED_DIRECT_SOURCE_JOB},
                    )
            with pytest.raises(IntegrityError):
                async with connection.begin_nested():
                    await connection.execute(
                        text(
                            """
                            INSERT INTO ops.feature_update_requests (
                              request_id, scope_type, scope, run_mode, job_id
                            ) VALUES (
                              '82000000-0000-4000-8000-000000000002',
                              'bbox', '{"type":"bbox"}'::jsonb,
                              'queued', :job_id
                            )
                            """
                        ),
                        {"job_id": _PAIRED_NON_DIRECT_SOURCE_JOB},
                    )
            with pytest.raises(IntegrityError):
                async with connection.begin_nested():
                    await connection.execute(
                        text(
                            """
                            INSERT INTO ops.feature_update_requests (
                              request_id, scope_type, scope, run_mode, job_id
                            ) VALUES (
                              '83000000-0000-4000-8000-000000000003',
                              'bbox', '{"type":"center_radius"}'::jsonb,
                              'queued', :job_id
                            )
                            """
                        ),
                        {"job_id": str(request_rows[_JOBLESS_NON_DIRECT_REQUEST].job_id)},
                    )
            with pytest.raises(IntegrityError):
                async with connection.begin_nested():
                    await connection.execute(
                        text(
                            """
                            UPDATE ops.feature_update_requests
                               SET update_policy = jsonb_build_object(
                                 'include_inactive', NULL
                               )
                             WHERE request_id = :request_id
                            """
                        ),
                        {"request_id": _JOBLESS_DIRECT_REQUEST},
                    )
            with pytest.raises(IntegrityError):
                async with connection.begin_nested():
                    await connection.execute(
                        text(
                            """
                            UPDATE ops.feature_update_requests
                               SET providers = ARRAY['other-provider']::text[]
                             WHERE request_id = :request_id
                            """
                        ),
                        {"request_id": _JOBLESS_DIRECT_REQUEST},
                    )
            with pytest.raises(IntegrityError):
                async with connection.begin_nested():
                    await connection.execute(
                        text(
                            """
                            UPDATE ops.feature_update_requests
                               SET priority = 1001
                             WHERE request_id = :request_id
                            """
                        ),
                        {"request_id": _JOBLESS_DIRECT_REQUEST},
                    )
            with pytest.raises(IntegrityError):
                async with connection.begin_nested():
                    await connection.execute(
                        text(
                            """
                            UPDATE ops.feature_update_requests
                               SET scope_type = 'feature_ids',
                                   scope = jsonb_build_object(
                                     'type', 'feature_ids',
                                     'feature_ids', jsonb_build_array(
                                       'feature-1', 'feature-1'
                                     )
                                   )
                             WHERE request_id = :request_id
                            """
                        ),
                        {"request_id": _JOBLESS_NON_DIRECT_REQUEST},
                    )
            with pytest.raises(IntegrityError):
                async with connection.begin_nested():
                    await connection.execute(
                        text(
                            """
                            INSERT INTO ops.feature_update_requests (
                              request_id, scope_type, scope, providers,
                              run_mode, job_id
                            ) VALUES (
                              '86500000-0000-4000-8000-000000000006',
                              'bbox',
                              jsonb_build_object(
                                'type', 'bbox', 'min_lon', 126, 'min_lat', 37,
                                'max_lon', 127, 'max_lat', 38
                              ),
                              ARRAY[['provider-a', 'provider-b']]::text[],
                              'queued', :job_id
                            )
                            """
                        ),
                        {"job_id": str(request_rows[_JOBLESS_NON_DIRECT_REQUEST].job_id)},
                    )
            with pytest.raises(IntegrityError):
                async with connection.begin_nested():
                    await connection.execute(
                        text(
                            """
                            INSERT INTO ops.feature_update_requests (
                              request_id, scope_type, scope, run_mode, job_id
                            ) VALUES (
                              '84000000-0000-4000-8000-000000000004',
                              'bbox', '[]'::jsonb, 'queued', :job_id
                            )
                            """
                        ),
                        {"job_id": str(request_rows[_JOBLESS_NON_DIRECT_REQUEST].job_id)},
                    )
            with pytest.raises(IntegrityError):
                async with connection.begin_nested():
                    await connection.execute(
                        text(
                            """
                            INSERT INTO ops.feature_update_requests (
                              request_id, scope_type, scope, run_mode, job_id
                            ) VALUES (
                              '85000000-0000-4000-8000-000000000005',
                              'provider_dataset',
                              jsonb_build_object(
                                'type', 'provider_dataset',
                                'provider', 123,
                                'dataset_key', 456,
                                'sync_scope', 'scope-123'
                              ),
                              'queued', :job_id
                            )
                            """
                        ),
                        {"job_id": _SHAPE_CHECK_SOURCE_JOB},
                    )
            with pytest.raises(IntegrityError):
                async with connection.begin_nested():
                    await connection.execute(
                        text(
                            """
                            INSERT INTO ops.feature_update_requests (
                              request_id, scope_type, scope, providers,
                              run_mode, job_id
                            ) VALUES (
                              '86000000-0000-4000-8000-000000000006',
                              'bbox',
                              jsonb_build_object(
                                'type', 'bbox', 'min_lon', 126, 'min_lat', 37,
                                'max_lon', 127, 'max_lat', 38
                              ),
                              ARRAY[NULL]::text[], 'queued', :job_id
                            )
                            """
                        ),
                        {"job_id": str(request_rows[_JOBLESS_NON_DIRECT_REQUEST].job_id)},
                    )
            with pytest.raises(IntegrityError):
                async with connection.begin_nested():
                    await connection.execute(
                        text(
                            """
                            INSERT INTO ops.feature_update_requests (
                              request_id, scope_type, scope, dataset_keys,
                              run_mode, job_id
                            ) VALUES (
                              '87000000-0000-4000-8000-000000000007',
                              'bbox',
                              jsonb_build_object(
                                'type', 'bbox', 'min_lon', 126, 'min_lat', 37,
                                'max_lon', 127, 'max_lat', 38
                              ),
                              ARRAY[' padded']::text[], 'queued', :job_id
                            )
                            """
                        ),
                        {"job_id": str(request_rows[_JOBLESS_NON_DIRECT_REQUEST].job_id)},
                    )
            with pytest.raises(IntegrityError):
                async with connection.begin_nested():
                    await connection.execute(
                        text(
                            """
                            INSERT INTO ops.feature_update_requests (
                              request_id, scope_type, scope, run_mode, job_id
                            ) VALUES (
                              '88000000-0000-4000-8000-000000000008',
                              'bbox',
                              jsonb_build_object(
                                'type', 'bbox', 'min_lon', 126, 'min_lat', 37,
                                'max_lon', 127, 'max_lat', 38
                              ),
                              'queued', :job_id
                            )
                            """
                        ),
                        {"job_id": _RESERVED_NON_DIRECT_SOURCE_JOB},
                    )
            with pytest.raises(IntegrityError):
                async with connection.begin_nested():
                    await connection.execute(
                        text(
                            """
                            UPDATE ops.feature_update_requests
                               SET job_id = :reserved_job_id
                             WHERE request_id = :request_id
                            """
                        ),
                        {
                            "reserved_job_id": _RESERVED_DIRECT_SOURCE_JOB,
                            "request_id": _RESERVED_DIRECT_REQUEST,
                        },
                    )
            with pytest.raises(IntegrityError):
                async with connection.begin_nested():
                    await connection.execute(
                        text(
                            """
                            UPDATE ops.import_jobs
                               SET kind = 'provider_feature_load'
                             WHERE job_id = :job_id
                            """
                        ),
                        {"job_id": str(request_rows[_RESERVED_DIRECT_REQUEST].job_id)},
                    )
            with pytest.raises(IntegrityError):
                async with connection.begin_nested():
                    await connection.execute(
                        text(
                            """
                            UPDATE ops.import_jobs
                               SET provider = 'mutated-provider',
                                   dataset_key = 'mutated-dataset'
                             WHERE job_id = :job_id
                            """
                        ),
                        {"job_id": _MISMATCHED_DIRECT_SOURCE_JOB},
                    )
            with pytest.raises(IntegrityError):
                async with connection.begin_nested():
                    await connection.execute(
                        text("DELETE FROM ops.import_jobs WHERE job_id = :job_id"),
                        {"job_id": str(request_rows[_JOBLESS_DIRECT_REQUEST].job_id)},
                    )

        direct_canonical_job_id = str(request_rows[_JOBLESS_DIRECT_REQUEST].job_id)
        await target_engine.dispose()
        await asyncio.to_thread(_run_alembic, target_dsn, _PRE_REVISION, downgrade=True)
        target_engine = make_async_engine(target_dsn)
        async with target_engine.begin() as connection:
            _assert_pre_revision_index_definitions(
                await _index_definitions(connection)
            )
            revision = (
                await connection.execute(text("SELECT version_num FROM alembic_version"))
            ).scalar_one()
            assert revision == _PRE_REVISION
            assert await _request_job_contract(connection) == ("YES", "SET NULL")
            assert await _identity_constraints(connection) == {}
            assert await _identity_triggers(connection) == set()
            assert not await _cancellation_quarantine_guard_function_exists(connection)
            assert await _cancellation_member_identity_columns(connection) == {
                "member_kind",
                "member_id",
            }
            legacy_member_constraints, legacy_member_index = (
                await _legacy_cancellation_member_contract(connection)
            )
            assert (
                "PRIMARY KEY (cancellation_id, member_kind, member_id)"
                in legacy_member_constraints["pk_pipeline_cancellation_members"]
            )
            assert "member_kind = ANY" in legacy_member_constraints[
                "ck_pipeline_cancellation_members_kind"
            ]
            assert "member_kind = 'import_job'" in legacy_member_constraints[
                "ck_pipeline_cancellation_members_operation_kind"
            ]
            assert (
                "(member_kind, member_id, updated_at DESC, cancellation_id DESC)"
                in legacy_member_index
            )
            restored_request_columns = await _request_columns(connection)
            assert restored_request_columns >= _REQUEST_LIFECYCLE_COLUMNS
            assert "generation" not in restored_request_columns
            assert {"quarantined_at", "quarantine_reason"}.isdisjoint(
                await _import_job_columns(connection)
            )
            assert "quarantined_at" not in await _import_job_event_columns(connection)
            assert await _import_job_event_clock_row(connection) is None
            assert not await _scope_validator_exists(connection)
            assert not await _filter_validator_exists(connection)
            assert not await _policy_validator_exists(connection)
            assert await _filter_column_contract(connection) == {
                "providers": ("jsonb", "jsonb", "'[]'::jsonb"),
                "dataset_keys": ("jsonb", "jsonb", "'[]'::jsonb"),
            }
            restored_filters = (
                await connection.execute(
                    text(
                        """
                        SELECT
                          providers,
                          dataset_keys,
                          jsonb_typeof(providers) AS providers_type,
                          jsonb_typeof(dataset_keys) AS dataset_keys_type
                        FROM ops.feature_update_requests
                        WHERE request_id = :request_id
                        """
                    ),
                    {"request_id": _JOBLESS_DIRECT_REQUEST},
                )
            ).one()
            assert restored_filters.providers == []
            assert restored_filters.dataset_keys == []
            assert restored_filters.providers_type == "array"
            assert restored_filters.dataset_keys_type == "array"
            assert "WHERE (job_id IS NOT NULL)" in (
                await _feature_update_job_index_definition(connection)
            )
            assert await _dry_run_column_contract(connection) == ("NO", "false")

            downgraded_component = {
                str(row.job_id): (
                    row.kind,
                    row.payload,
                    str(row.parent_job_id) if row.parent_job_id is not None else None,
                )
                for row in await connection.execute(
                    text(
                        """
                        SELECT job_id, kind, payload, parent_job_id
                        FROM ops.import_jobs
                        WHERE job_id = ANY(CAST(:job_ids AS uuid[]))
                        ORDER BY job_id
                        """
                    ),
                    {"job_ids": sorted(component_ids)},
                )
            }
            assert downgraded_component == {
                _QUARANTINE_PARENT_JOB: (
                    "quarantine_component_parent",
                    {"component": "parent"},
                    None,
                ),
                _VALID_ORPHAN_JOB: (
                    "feature_update_request",
                    {"component": "canonical"},
                    _QUARANTINE_PARENT_JOB,
                ),
                _QUARANTINE_CHILD_JOB: (
                    "quarantine_component_child",
                    {"component": "child"},
                    _VALID_ORPHAN_JOB,
                ),
            }
            downgraded_event = (
                await connection.execute(
                    text(
                        """
                        SELECT code, message, payload
                        FROM ops.import_job_events
                        WHERE event_id = :event_id
                        """
                    ),
                    {"event_id": _QUARANTINE_EVENT_ID},
                )
            ).one()
            assert downgraded_event.code == "legacy.component.audit"
            assert downgraded_event.message == "quarantine component audit"
            assert downgraded_event.payload == {"preserved": True}

            await connection.execute(
                text(
                    """
                    INSERT INTO ops.pipeline_cancellation_members (
                      cancellation_id, member_kind, member_id, initial_status,
                      result, terminal_status
                    ) VALUES (
                      :cancellation_id, 'import_job', :member_id, 'done',
                      'already_terminal', 'done'
                    )
                    """
                ),
                {
                    "cancellation_id": _QUARANTINE_CANCELLATION_ID,
                    "member_id": _VALID_ORPHAN_JOB,
                },
            )
            downgraded_member_ids = {
                str(member_id)
                for member_id in await connection.scalars(
                    text(
                        """
                        SELECT member_id
                        FROM ops.pipeline_cancellation_members
                        WHERE cancellation_id = :cancellation_id
                          AND member_kind = 'import_job'
                        """
                    ),
                    {"cancellation_id": _QUARANTINE_CANCELLATION_ID},
                )
            }
            assert downgraded_member_ids == {
                _RESERVED_DIRECT_ROOT_JOB,
                _VALID_ORPHAN_JOB,
            }

            await connection.execute(
                text("DELETE FROM ops.import_jobs WHERE job_id = :job_id"),
                {"job_id": direct_canonical_job_id},
            )
            nulled_job_id = (
                await connection.execute(
                    text(
                        """
                        SELECT job_id
                        FROM ops.feature_update_requests
                        WHERE request_id = :request_id
                        """
                    ),
                    {"request_id": _JOBLESS_DIRECT_REQUEST},
                )
            ).scalar_one()
            assert nulled_job_id is None

            await connection.execute(
                text(
                    """
                    UPDATE ops.import_jobs
                       SET provider = 'downgraded-provider',
                           dataset_key = 'downgraded-dataset'
                     WHERE job_id = :job_id
                    """
                ),
                {"job_id": _MISMATCHED_DIRECT_SOURCE_JOB},
            )
            await connection.execute(
                text(
                    """
                    INSERT INTO ops.feature_update_requests (
                      request_id, scope_type, scope, run_mode, status,
                      dagster_run_id, job_id
                    ) VALUES (
                      '80000000-0000-4000-8000-000000000008',
                      'provider_dataset',
                      '{"provider":" padded ","dataset_key":""}'::jsonb,
                      'queued', 'queued', NULL, :job_id
                    )
                    """
                ),
                {"job_id": _MISMATCHED_DIRECT_SOURCE_JOB},
            )
            restored_dry_run = (
                await connection.execute(
                    text(
                        """
                        SELECT dry_run
                        FROM ops.feature_update_requests
                        WHERE request_id =
                          '80000000-0000-4000-8000-000000000008'::uuid
                        """
                    )
                )
            ).scalar_one()
            assert restored_dry_run is False
    finally:
        await target_engine.dispose()
        async with admin_engine.connect() as connection:
            autocommit = await connection.execution_options(isolation_level="AUTOCOMMIT")
            await autocommit.execute(text(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)'))
        await admin_engine.dispose()


async def test_pipeline_projection_access_paths_rejects_malformed_direct_scope(
    pg_container: Any,
) -> None:
    admin_dsn = normalize_async_dsn(pg_container.get_connection_url())
    database = f"pipeline_projection_malformed_{uuid4().hex}"
    target_dsn = make_url(admin_dsn).set(database=database).render_as_string(hide_password=False)
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
                    INSERT INTO ops.feature_update_requests (
                      request_id, scope_type, scope, run_mode, dry_run, job_id
                    ) VALUES (
                      '90000000-0000-4000-8000-000000000009',
                      'provider_dataset',
                      jsonb_build_object(
                        'type', 'provider_dataset',
                        'provider', 'provider',
                        'dataset_key', 'dataset'
                      ),
                      'queued', true, NULL
                    )
                    """
                )
            )

        await target_engine.dispose()
        with pytest.raises(RuntimeError) as dry_run_failure:
            await asyncio.to_thread(_run_alembic, target_dsn, _TARGET_REVISION)
        assert "dry-run" in str(dry_run_failure.value)

        target_engine = make_async_engine(target_dsn)
        async with target_engine.begin() as connection:
            revision, dry_run = (
                await connection.execute(
                    text(
                        """
                        SELECT version.version_num, request.dry_run
                        FROM alembic_version AS version
                        CROSS JOIN ops.feature_update_requests AS request
                        WHERE request.request_id =
                          '90000000-0000-4000-8000-000000000009'::uuid
                        """
                    )
                )
            ).one()
            assert revision == _PRE_REVISION
            assert dry_run is True
            assert await _dry_run_column_contract(connection) == ("NO", "false")
            await connection.execute(
                text(
                    """
                    UPDATE ops.feature_update_requests
                       SET dry_run = false
                     WHERE request_id =
                       '90000000-0000-4000-8000-000000000009'::uuid
                    """
                )
            )

        malformed_scopes: tuple[tuple[str, str, Any], ...] = (
            ("not_object", "provider_dataset", ["provider_dataset"]),
            (
                "missing_type",
                "provider_dataset",
                {"provider": "provider", "dataset_key": "dataset"},
            ),
            (
                "wrong_type",
                "provider_dataset",
                {
                    "type": "bbox",
                    "provider": "provider",
                    "dataset_key": "dataset",
                },
            ),
            ("feature_ids_item_type", "feature_ids", {"type": "feature_ids", "feature_ids": [123]}),
            (
                "feature_ids_duplicate",
                "feature_ids",
                {"type": "feature_ids", "feature_ids": ["feature-1", "feature-1"]},
            ),
            (
                "center_radius_missing_radius",
                "center_radius",
                {"type": "center_radius", "center": {"lon": 127, "lat": 37}},
            ),
            (
                "sigungu_invalid_match",
                "sigungu_by_radius",
                {
                    "type": "sigungu_by_radius",
                    "center": {"lon": 127, "lat": 37},
                    "radius_km": 5,
                    "match": "invalid",
                },
            ),
            (
                "sigungu_unsupported_legacy_match",
                "sigungu_by_radius",
                {
                    "type": "sigungu_by_radius",
                    "center": {"lon": 127, "lat": 37},
                    "radius_km": 5,
                    "match": "contains_center",
                },
            ),
            (
                "bbox_legacy_keys",
                "bbox",
                {
                    "type": "bbox",
                    "west": 126,
                    "south": 37,
                    "east": 127,
                    "north": 38,
                },
            ),
            (
                "cache_target_blank_key",
                "cache_target_keys",
                {
                    "type": "cache_target_keys",
                    "external_system": "pinvi",
                    "target_keys": [""],
                    "scope_mode": "center_radius",
                },
            ),
            (
                "cache_target_duplicate",
                "cache_target_keys",
                {
                    "type": "cache_target_keys",
                    "external_system": "pinvi",
                    "target_keys": ["poi-1", "poi-1"],
                    "scope_mode": "center_radius",
                },
            ),
            (
                "non_string_provider",
                "provider_dataset",
                {
                    "type": "provider_dataset",
                    "provider": 123,
                    "dataset_key": "dataset",
                },
            ),
            (
                "whitespace_provider",
                "provider_dataset",
                {
                    "type": "provider_dataset",
                    "provider": "\t",
                    "dataset_key": "dataset",
                },
            ),
            (
                "padded_provider",
                "provider_dataset",
                {
                    "type": "provider_dataset",
                    "provider": " padded-provider ",
                    "dataset_key": "dataset",
                },
            ),
            (
                "blank_dataset",
                "provider_dataset",
                {
                    "type": "provider_dataset",
                    "provider": "provider",
                    "dataset_key": "",
                },
            ),
            (
                "non_string_sync_scope",
                "provider_dataset",
                {
                    "type": "provider_dataset",
                    "provider": "provider",
                    "dataset_key": "dataset",
                    "sync_scope": 123,
                },
            ),
            (
                "blank_sync_scope",
                "provider_dataset",
                {
                    "type": "provider_dataset",
                    "provider": "provider",
                    "dataset_key": "dataset",
                    "sync_scope": "",
                },
            ),
            (
                "padded_sync_scope",
                "provider_dataset",
                {
                    "type": "provider_dataset",
                    "provider": "provider",
                    "dataset_key": "dataset",
                    "sync_scope": " padded-scope ",
                },
            ),
            (
                "null_sync_scope",
                "provider_dataset",
                {
                    "type": "provider_dataset",
                    "provider": "provider",
                    "dataset_key": "dataset",
                    "sync_scope": None,
                },
            ),
        )
        for case_name, scope_type, malformed_scope in malformed_scopes:
            async with target_engine.begin() as connection:
                await connection.execute(
                    text(
                        """
                        UPDATE ops.feature_update_requests
                           SET scope_type = :scope_type,
                               scope = CAST(:scope AS jsonb)
                         WHERE request_id =
                           '90000000-0000-4000-8000-000000000009'::uuid
                        """
                    ),
                    {
                        "scope_type": scope_type,
                        "scope": json.dumps(malformed_scope),
                    },
                )

            await target_engine.dispose()
            with pytest.raises(
                RuntimeError,
                match="cannot repair malformed feature update request scope",
            ) as raised:
                await asyncio.to_thread(_run_alembic, target_dsn, _TARGET_REVISION)
            assert "90000000-0000-4000-8000-000000000009" in str(raised.value), case_name

            target_engine = make_async_engine(target_dsn)
            async with target_engine.connect() as connection:
                revision = (
                    await connection.execute(text("SELECT version_num FROM alembic_version"))
                ).scalar_one()
                persisted_scope = (
                    await connection.execute(
                        text(
                            """
                            SELECT scope
                            FROM ops.feature_update_requests
                            WHERE request_id =
                              '90000000-0000-4000-8000-000000000009'::uuid
                            """
                        )
                    )
                ).scalar_one()
                assert revision == _PRE_REVISION
                _assert_pre_revision_index_definitions(
                    await _index_definitions(connection)
                )
                assert await _request_job_contract(connection) == (
                    "YES",
                    "SET NULL",
                )
                assert "WHERE (job_id IS NOT NULL)" in (
                    await _feature_update_job_index_definition(connection)
                )
                assert await _dry_run_column_contract(connection) == (
                    "NO",
                    "false",
                )
                assert persisted_scope == malformed_scope

        malformed_filters: tuple[tuple[str, Any, Any], ...] = (
            ("providers_object", {}, []),
            ("providers_null", None, []),
            ("providers_item_type", [123], []),
            ("providers_item_null", [None], []),
            ("providers_empty", [""], []),
            ("providers_padded", [" padded-provider"], []),
            ("providers_too_long", ["x" * 129], []),
            ("providers_duplicate", ["provider", "provider"], []),
            ("providers_too_many", [f"provider-{index}" for index in range(33)], []),
            ("dataset_keys_object", [], {}),
            ("dataset_keys_too_many", [], [f"dataset-{index}" for index in range(65)]),
        )
        for case_name, malformed_providers, malformed_dataset_keys in malformed_filters:
            async with target_engine.begin() as connection:
                await connection.execute(
                    text(
                        """
                        UPDATE ops.feature_update_requests
                           SET scope_type = 'provider_dataset',
                               scope = jsonb_build_object(
                                 'type', 'provider_dataset',
                                 'provider', 'provider',
                                 'dataset_key', 'dataset'
                               ),
                               providers = CAST(:providers AS jsonb),
                               dataset_keys = CAST(:dataset_keys AS jsonb)
                         WHERE request_id =
                           '90000000-0000-4000-8000-000000000009'::uuid
                        """
                    ),
                    {
                        "providers": json.dumps(malformed_providers),
                        "dataset_keys": json.dumps(malformed_dataset_keys),
                    },
                )

            await target_engine.dispose()
            with pytest.raises(
                RuntimeError,
                match="cannot repair malformed feature update request filters",
            ) as raised:
                await asyncio.to_thread(_run_alembic, target_dsn, _TARGET_REVISION)
            assert "90000000-0000-4000-8000-000000000009" in str(raised.value), case_name

            target_engine = make_async_engine(target_dsn)
            async with target_engine.connect() as connection:
                revision, persisted_providers, persisted_dataset_keys = (
                    await connection.execute(
                        text(
                            """
                            SELECT version.version_num,
                                   request.providers,
                                   request.dataset_keys
                            FROM alembic_version AS version
                            CROSS JOIN ops.feature_update_requests AS request
                            WHERE request.request_id =
                              '90000000-0000-4000-8000-000000000009'::uuid
                            """
                        )
                    )
                ).one()
                assert revision == _PRE_REVISION
                assert persisted_providers == malformed_providers, case_name
                assert persisted_dataset_keys == malformed_dataset_keys, case_name

        async with target_engine.begin() as connection:
            await connection.execute(
                text(
                    """
                    UPDATE ops.feature_update_requests
                       SET scope_type = 'provider_dataset',
                           scope = jsonb_build_object(
                             'type', 'provider_dataset',
                             'provider', 'provider',
                             'dataset_key', 'dataset'
                           ),
                           providers = '["other-provider"]'::jsonb,
                           dataset_keys = '[]'::jsonb
                     WHERE request_id =
                       '90000000-0000-4000-8000-000000000009'::uuid
                    """
                )
            )
        await target_engine.dispose()
        with pytest.raises(
            RuntimeError,
            match="provider_dataset requests with conflicting filters",
        ):
            await asyncio.to_thread(_run_alembic, target_dsn, _TARGET_REVISION)

        target_engine = make_async_engine(target_dsn)
        async with target_engine.begin() as connection:
            revision = (
                await connection.execute(text("SELECT version_num FROM alembic_version"))
            ).scalar_one()
            assert revision == _PRE_REVISION
            await connection.execute(
                text(
                    """
                    UPDATE ops.feature_update_requests
                       SET providers = '[]'::jsonb,
                           priority = -1
                     WHERE request_id =
                       '90000000-0000-4000-8000-000000000009'::uuid
                    """
                )
            )
        await target_engine.dispose()
        with pytest.raises(RuntimeError, match="invalid priority"):
            await asyncio.to_thread(_run_alembic, target_dsn, _TARGET_REVISION)

        target_engine = make_async_engine(target_dsn)
        async with target_engine.begin() as connection:
            revision = (
                await connection.execute(text("SELECT version_num FROM alembic_version"))
            ).scalar_one()
            assert revision == _PRE_REVISION
            await connection.execute(
                text(
                    """
                    UPDATE ops.feature_update_requests
                       SET priority = 50
                     WHERE request_id =
                       '90000000-0000-4000-8000-000000000009'::uuid
                    """
                )
            )

        malformed_policies: tuple[tuple[str, Any], ...] = (
            ("policy_null", None),
            ("policy_array", []),
            ("policy_unknown", {"unknown": True}),
            ("policy_wrong_mode", {"mode": "replace_all"}),
            ("policy_wrong_boolean", {"include_inactive": "true"}),
            ("policy_boolean_array", {"force_provider_call": []}),
            ("policy_field_null", {"prevent_provider_reactivation": None}),
        )
        for case_name, malformed_policy in malformed_policies:
            async with target_engine.begin() as connection:
                await connection.execute(
                    text(
                        """
                        UPDATE ops.feature_update_requests
                           SET scope_type = 'provider_dataset',
                               scope = jsonb_build_object(
                                 'type', 'provider_dataset',
                                 'provider', 'provider',
                                 'dataset_key', 'dataset'
                               ),
                               providers = '[]'::jsonb,
                               dataset_keys = '[]'::jsonb,
                               update_policy = CAST(:update_policy AS jsonb)
                         WHERE request_id =
                           '90000000-0000-4000-8000-000000000009'::uuid
                        """
                    ),
                    {"update_policy": json.dumps(malformed_policy)},
                )

            await target_engine.dispose()
            with pytest.raises(RuntimeError) as raised:
                await asyncio.to_thread(_run_alembic, target_dsn, _TARGET_REVISION)
            assert "policy" in str(raised.value).lower(), case_name
            assert "90000000-0000-4000-8000-000000000009" in str(raised.value), case_name

            target_engine = make_async_engine(target_dsn)
            async with target_engine.connect() as connection:
                revision, persisted_policy = (
                    await connection.execute(
                        text(
                            """
                            SELECT version.version_num, request.update_policy
                            FROM alembic_version AS version
                            CROSS JOIN ops.feature_update_requests AS request
                            WHERE request.request_id =
                              '90000000-0000-4000-8000-000000000009'::uuid
                            """
                        )
                    )
                ).one()
                assert revision == _PRE_REVISION, case_name
                assert persisted_policy == malformed_policy, case_name
                assert await _identity_constraints(connection) == {}

        async with target_engine.begin() as connection:
            await connection.execute(
                text(
                    """
                    UPDATE ops.feature_update_requests
                       SET scope_type = 'provider_dataset',
                           scope = jsonb_build_object(
                         'type', 'provider_dataset',
                         'provider', 'missing-sync-provider',
                         'dataset_key', 'missing-sync-dataset'
                       ),
                           providers = jsonb_build_array('missing-sync-provider'),
                           dataset_keys = jsonb_build_array('missing-sync-dataset'),
                           update_policy = jsonb_build_object(
                             'mode', 'refresh_existing',
                             'include_inactive', true
                           )
                     WHERE request_id =
                       '90000000-0000-4000-8000-000000000009'::uuid
                    """
                )
            )
            await connection.execute(
                text(
                    """
                    INSERT INTO ops.feature_update_requests (
                      request_id, scope_type, scope, run_mode, status,
                      dagster_run_id, job_id
                    ) VALUES (
                      '92000000-0000-4000-8000-000000000009',
                      'provider_dataset',
                      jsonb_build_object(
                        'type', 'provider_dataset',
                        'provider', 'string-sync-provider',
                        'dataset_key', 'string-sync-dataset',
                        'sync_scope', 'sigungu:11'
                      ),
                      'queued', 'done', 'canonical-run', NULL
                    )
                    """
                )
            )

        await target_engine.dispose()
        await asyncio.to_thread(_run_alembic, target_dsn, _TARGET_REVISION)
        target_engine = make_async_engine(target_dsn)
        async with target_engine.connect() as connection:
            valid_rows = {
                str(row.request_id): (
                    str(row.job_id),
                    bool(row.has_sync_scope),
                    row.sync_scope_type,
                    row.provider,
                    row.dataset_key,
                    int(row.provider_count),
                    int(row.dataset_key_count),
                )
                for row in await connection.execute(
                    text(
                        """
                        SELECT
                          request.request_id,
                          request.job_id,
                          request.scope ? 'sync_scope' AS has_sync_scope,
                          jsonb_typeof(request.scope->'sync_scope')
                            AS sync_scope_type,
                          job.provider,
                          job.dataset_key,
                          cardinality(request.providers) AS provider_count,
                          cardinality(request.dataset_keys) AS dataset_key_count
                        FROM ops.feature_update_requests AS request
                        JOIN ops.import_jobs AS job ON job.job_id = request.job_id
                        WHERE request.request_id IN (
                          '90000000-0000-4000-8000-000000000009'::uuid,
                          '92000000-0000-4000-8000-000000000009'::uuid
                        )
                        """
                    )
                )
            }
            assert all(job_id != "None" for job_id, *_ in valid_rows.values())
            assert len({row[0] for row in valid_rows.values()}) == 2
            assert {request_id: row[1:] for request_id, row in valid_rows.items()} == {
                "90000000-0000-4000-8000-000000000009": (
                    False,
                    None,
                    "missing-sync-provider",
                    "missing-sync-dataset",
                    0,
                    0,
                ),
                "92000000-0000-4000-8000-000000000009": (
                    True,
                    "string",
                    "string-sync-provider",
                    "string-sync-dataset",
                    0,
                    0,
                ),
            }
            assert " WHERE " not in (
                await _feature_update_job_index_definition(
                    connection,
                    index_name="uq_feature_update_requests_job_id",
                )
            )
            assert await _dry_run_column_contract(connection) is None
    finally:
        await target_engine.dispose()
        async with admin_engine.connect() as connection:
            autocommit = await connection.execution_options(isolation_level="AUTOCOMMIT")
            await autocommit.execute(text(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)'))
        await admin_engine.dispose()


async def test_pipeline_projection_access_paths_rejects_invalid_execution_owners(
    pg_container: Any,
) -> None:
    admin_dsn = normalize_async_dsn(pg_container.get_connection_url())
    database = f"pipeline_projection_invalid_owners_{uuid4().hex}"
    target_dsn = make_url(admin_dsn).set(database=database).render_as_string(
        hide_password=False
    )
    admin_engine = make_async_engine(admin_dsn)
    async with admin_engine.connect() as connection:
        autocommit = await connection.execution_options(isolation_level="AUTOCOMMIT")
        await autocommit.execute(text(f'CREATE DATABASE "{database}"'))

    request_ids = (
        "a1000000-0000-4000-8000-000000000001",
        "a2000000-0000-4000-8000-000000000002",
        "a3000000-0000-4000-8000-000000000003",
        "a4000000-0000-4000-8000-000000000004",
    )
    job_ids = (
        "a1000000-0000-4000-9000-000000000001",
        "a2000000-0000-4000-9000-000000000002",
        "a3000000-0000-4000-9000-000000000003",
        "a4000000-0000-4000-9000-000000000004",
    )
    target_engine = make_async_engine(target_dsn)
    try:
        await asyncio.to_thread(_run_alembic, target_dsn, _PRE_REVISION)
        async with target_engine.begin() as connection:
            await connection.execute(
                text(
                    """
                    INSERT INTO ops.import_jobs (
                      job_id, kind, payload, status, dagster_run_id, trigger_kind
                    ) VALUES
                    (:job_1, 'feature_update_request', '{}'::jsonb,
                     'queued', NULL, 'update_request'),
                    (:job_2, 'feature_update_request', '{}'::jsonb,
                     'running', 'job-running-owner', 'update_request'),
                    (:job_3, 'feature_update_request', '{}'::jsonb,
                     'queued', 'job-owner-while-queued', 'update_request'),
                    (:job_4, 'feature_update_request', '{}'::jsonb,
                     'running', NULL, 'update_request')
                    """
                ),
                {f"job_{index}": job_id for index, job_id in enumerate(job_ids, 1)},
            )
            await connection.execute(
                text(
                    """
                    INSERT INTO ops.feature_update_requests (
                      request_id, scope_type, scope, run_mode, status,
                      dagster_run_id, job_id
                    ) VALUES
                    (:request_1, 'feature_ids',
                     '{"type":"feature_ids","feature_ids":[]}'::jsonb,
                     'queued', 'queued', 'request-owner-while-queued', :job_1),
                    (:request_2, 'feature_ids',
                     '{"type":"feature_ids","feature_ids":[]}'::jsonb,
                     'queued', 'running', NULL, :job_2),
                    (:request_3, 'feature_ids',
                     '{"type":"feature_ids","feature_ids":[]}'::jsonb,
                     'queued', 'queued', NULL, :job_3),
                    (:request_4, 'feature_ids',
                     '{"type":"feature_ids","feature_ids":[]}'::jsonb,
                     'queued', 'running', 'request-running-owner', :job_4)
                    """
                ),
                {
                    **{
                        f"request_{index}": request_id
                        for index, request_id in enumerate(request_ids, 1)
                    },
                    **{f"job_{index}": job_id for index, job_id in enumerate(job_ids, 1)},
                },
            )

        await target_engine.dispose()
        with pytest.raises(
            RuntimeError,
            match="invalid feature update execution owners",
        ) as raised:
            await asyncio.to_thread(_run_alembic, target_dsn, _TARGET_REVISION)
        diagnostic = str(raised.value)
        for request_id in request_ids:
            assert request_id in diagnostic

        target_engine = make_async_engine(target_dsn)
        async with target_engine.connect() as connection:
            assert (
                await connection.scalar(text("SELECT version_num FROM alembic_version"))
            ) == _PRE_REVISION
            persisted_rows = (
                await connection.execute(
                    text(
                        """
                        SELECT
                          request.request_id,
                          request.status AS request_status,
                          request.dagster_run_id AS request_owner,
                          job.status AS job_status,
                          job.dagster_run_id AS job_owner
                        FROM ops.feature_update_requests AS request
                        JOIN ops.import_jobs AS job ON job.job_id = request.job_id
                        WHERE request.request_id = ANY(CAST(:request_ids AS uuid[]))
                        ORDER BY request.request_id
                        """
                    ),
                    {"request_ids": list(request_ids)},
                )
            ).all()
            assert [str(row.request_id) for row in persisted_rows] == list(request_ids)
            assert [
                (row.request_status, row.request_owner, row.job_status, row.job_owner)
                for row in persisted_rows
            ] == [
                ("queued", "request-owner-while-queued", "queued", None),
                ("running", None, "running", "job-running-owner"),
                ("queued", None, "queued", "job-owner-while-queued"),
                ("running", "request-running-owner", "running", None),
            ]
    finally:
        await target_engine.dispose()
        async with admin_engine.connect() as connection:
            autocommit = await connection.execution_options(isolation_level="AUTOCOMMIT")
            await autocommit.execute(
                text(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)')
            )
        await admin_engine.dispose()


async def test_pipeline_projection_access_paths_rejects_active_orphan_update_job(
    pg_container: Any,
) -> None:
    admin_dsn = normalize_async_dsn(pg_container.get_connection_url())
    database = f"pipeline_projection_orphan_{uuid4().hex}"
    target_dsn = make_url(admin_dsn).set(database=database).render_as_string(hide_password=False)
    admin_engine = make_async_engine(admin_dsn)
    async with admin_engine.connect() as connection:
        autocommit = await connection.execution_options(isolation_level="AUTOCOMMIT")
        await autocommit.execute(text(f'CREATE DATABASE "{database}"'))

    target_engine = make_async_engine(target_dsn)
    orphan_job_id = "99000000-0000-4000-9000-000000000099"
    active_child_id = "99100000-0000-4000-9000-000000000099"
    try:
        await asyncio.to_thread(_run_alembic, target_dsn, _PRE_REVISION)
        async with target_engine.begin() as connection:
            await connection.execute(
                text(
                    """
                    INSERT INTO ops.import_jobs (
                      job_id, kind, parent_job_id, payload, status, trigger_kind
                    ) VALUES
                    (
                      :job_id, 'feature_update_request', NULL, '{}'::jsonb, 'done',
                      'update_request'
                    ),
                    (
                      :active_child_id, 'generic-child', :job_id, '{}'::jsonb,
                      'queued', NULL
                    )
                    """
                ),
                {"job_id": orphan_job_id, "active_child_id": active_child_id},
            )

        await target_engine.dispose()
        with pytest.raises(
            RuntimeError,
            match="active, request-linked, or cancellation-protected orphan feature",
        ) as raised:
            await asyncio.to_thread(_run_alembic, target_dsn, _TARGET_REVISION)
        assert orphan_job_id in str(raised.value)

        target_engine = make_async_engine(target_dsn)
        async with target_engine.begin() as connection:
            revision, kind, trigger_kind = (
                await connection.execute(
                    text(
                        """
                        SELECT version.version_num, job.kind, job.trigger_kind
                        FROM alembic_version AS version
                        JOIN ops.import_jobs AS job ON job.job_id = :job_id
                        """
                    ),
                    {"job_id": orphan_job_id},
                )
            ).one()
            assert revision == _PRE_REVISION
            assert kind == "feature_update_request"
            assert trigger_kind == "update_request"
    finally:
        await target_engine.dispose()
        async with admin_engine.connect() as connection:
            autocommit = await connection.execution_options(isolation_level="AUTOCOMMIT")
            await autocommit.execute(text(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)'))
        await admin_engine.dispose()


async def test_pipeline_projection_rejects_request_linked_orphan_component(
    pg_container: Any,
) -> None:
    admin_dsn = normalize_async_dsn(pg_container.get_connection_url())
    database = f"pipeline_projection_linked_orphan_{uuid4().hex}"
    target_dsn = make_url(admin_dsn).set(database=database).render_as_string(
        hide_password=False
    )
    admin_engine = make_async_engine(admin_dsn)
    async with admin_engine.connect() as connection:
        autocommit = await connection.execution_options(isolation_level="AUTOCOMMIT")
        await autocommit.execute(text(f'CREATE DATABASE "{database}"'))

    requested_job_id = "aa000000-0000-4000-9000-000000000001"
    orphan_neighbor_id = "ab000000-0000-4000-9000-000000000002"
    request_id = "ac000000-0000-4000-8000-000000000003"
    target_engine = make_async_engine(target_dsn)
    try:
        await asyncio.to_thread(_run_alembic, target_dsn, _PRE_REVISION)
        async with target_engine.begin() as connection:
            await connection.execute(
                text(
                    """
                    INSERT INTO ops.import_jobs (
                      job_id, kind, parent_job_id, payload, status, trigger_kind
                    ) VALUES
                    (
                      :requested_job_id, 'feature_update_request', NULL,
                      '{}'::jsonb, 'done', 'update_request'
                    ),
                    (
                      :orphan_neighbor_id, 'feature_update_request',
                      :requested_job_id, '{}'::jsonb, 'done', 'update_request'
                    )
                    """
                ),
                {
                    "requested_job_id": requested_job_id,
                    "orphan_neighbor_id": orphan_neighbor_id,
                },
            )
            await connection.execute(
                text(
                    """
                    INSERT INTO ops.feature_update_requests (
                      request_id, scope_type, scope, run_mode, status, job_id
                    ) VALUES (
                      :request_id, 'feature_ids',
                      '{"type":"feature_ids","feature_ids":[]}'::jsonb,
                      'queued', 'done', :requested_job_id
                    )
                    """
                ),
                {"request_id": request_id, "requested_job_id": requested_job_id},
            )

        await target_engine.dispose()
        with pytest.raises(
            RuntimeError,
            match="active, request-linked, or cancellation-protected orphan feature",
        ) as raised:
            await asyncio.to_thread(_run_alembic, target_dsn, _TARGET_REVISION)
        assert orphan_neighbor_id in str(raised.value)

        target_engine = make_async_engine(target_dsn)
        async with target_engine.connect() as connection:
            assert (
                await connection.scalar(text("SELECT version_num FROM alembic_version"))
            ) == _PRE_REVISION
            assert {"quarantined_at", "quarantine_reason"}.isdisjoint(
                await _import_job_columns(connection)
            )
            assert "quarantined_at" not in await _import_job_event_columns(connection)
            assert await _import_job_event_clock_row(connection) is None
            persisted = (
                await connection.execute(
                    text(
                        """
                        SELECT job_id, kind, parent_job_id
                        FROM ops.import_jobs
                        WHERE job_id IN (
                          CAST(:requested_job_id AS uuid),
                          CAST(:orphan_neighbor_id AS uuid)
                        )
                        ORDER BY job_id
                        """
                    ),
                    {
                        "requested_job_id": requested_job_id,
                        "orphan_neighbor_id": orphan_neighbor_id,
                    },
                )
            ).all()
            assert [
                (
                    str(row.job_id),
                    row.kind,
                    str(row.parent_job_id) if row.parent_job_id is not None else None,
                )
                for row in persisted
            ] == [
                (requested_job_id, "feature_update_request", None),
                (orphan_neighbor_id, "feature_update_request", requested_job_id),
            ]
    finally:
        await target_engine.dispose()
        async with admin_engine.connect() as connection:
            autocommit = await connection.execution_options(isolation_level="AUTOCOMMIT")
            await autocommit.execute(
                text(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)')
            )
        await admin_engine.dispose()


async def test_pipeline_projection_access_paths_merges_request_cancellation_into_job(
    pg_container: Any,
) -> None:
    admin_dsn = normalize_async_dsn(pg_container.get_connection_url())
    database = f"pipeline_projection_cancelled_{uuid4().hex}"
    target_dsn = make_url(admin_dsn).set(database=database).render_as_string(hide_password=False)
    admin_engine = make_async_engine(admin_dsn)
    async with admin_engine.connect() as connection:
        autocommit = await connection.execution_options(isolation_level="AUTOCOMMIT")
        await autocommit.execute(text(f'CREATE DATABASE "{database}"'))

    request_id = "c1000000-0000-4000-8000-000000000001"
    cancellation_id = "c2000000-0000-4000-8000-000000000002"
    target_engine = make_async_engine(target_dsn)
    try:
        await asyncio.to_thread(_run_alembic, target_dsn, _PRE_REVISION)
        async with target_engine.begin() as connection:
            await connection.execute(
                text(
                    """
                    INSERT INTO ops.feature_update_requests (
                      request_id, scope_type, scope, run_mode, status,
                      dagster_run_id, job_id
                    ) VALUES (
                      :request_id, 'bbox',
                      jsonb_build_object(
                        'type', 'bbox', 'min_lon', 126, 'min_lat', 37,
                        'max_lon', 127, 'max_lat', 38
                      ),
                      'queued', 'done', 'canonical-run', NULL
                    )
                    """
                ),
                {"request_id": request_id},
            )
            await connection.execute(
                text(
                    """
                    INSERT INTO ops.pipeline_cancellations (
                      cancellation_id, root_kind, root_id, status,
                      requested_by, finished_at
                    ) VALUES (
                      :cancellation_id, 'update_request', :request_id,
                      'completed', 'migration-test', now()
                    )
                    """
                ),
                {"cancellation_id": cancellation_id, "request_id": request_id},
            )
            await connection.execute(
                text(
                    """
                    UPDATE ops.feature_update_requests
                       SET cancellation_id = :cancellation_id,
                           cancellation_requested_at = now(),
                           cancellation_requested_by = 'migration-test'
                     WHERE request_id = :request_id
                    """
                ),
                {
                    "request_id": request_id,
                    "cancellation_id": cancellation_id,
                },
            )
            await connection.execute(
                text(
                    """
                    WITH inserted_run AS (
                      INSERT INTO ops.pipeline_cancellation_runs (
                        cancellation_id, dagster_run_id, result
                      ) VALUES (
                        :cancellation_id, 'legacy-request-run', 'already_terminal'
                      )
                      RETURNING cancellation_id, dagster_run_id
                    )
                    INSERT INTO ops.pipeline_cancellation_members (
                      cancellation_id, member_kind, member_id,
                      dagster_run_id, initial_status, result, terminal_status
                    )
                    SELECT
                      cancellation_id, 'update_request', :request_id,
                      dagster_run_id, 'done', 'already_terminal', 'done'
                    FROM inserted_run
                    """
                ),
                {
                    "request_id": request_id,
                    "cancellation_id": cancellation_id,
                },
            )

        await target_engine.dispose()
        await asyncio.to_thread(_run_alembic, target_dsn, _TARGET_REVISION)

        target_engine = make_async_engine(target_dsn)
        async with target_engine.connect() as connection:
            revision, linked_job_id, job_cancellation_id = (
                await connection.execute(
                    text(
                        """
                        SELECT
                          version.version_num,
                          request.job_id,
                          job.cancellation_id
                        FROM alembic_version AS version
                        CROSS JOIN ops.feature_update_requests AS request
                        JOIN ops.import_jobs AS job ON job.job_id = request.job_id
                        WHERE request.request_id = :request_id
                        """
                    ),
                    {"request_id": request_id},
                )
            ).one()
            members = (
                await connection.execute(
                    text(
                        """
                        SELECT job_id, dagster_run_id
                        FROM ops.pipeline_cancellation_members
                        WHERE cancellation_id = :cancellation_id
                        """
                    ),
                    {"cancellation_id": cancellation_id},
                )
            ).all()
            run_ids = tuple(
                await connection.scalars(
                    text(
                        "SELECT dagster_run_id "
                        "FROM ops.pipeline_cancellation_runs "
                        "WHERE cancellation_id = :cancellation_id "
                        "ORDER BY dagster_run_id"
                    ),
                    {"cancellation_id": cancellation_id},
                )
            )
            assert revision == _TARGET_REVISION
            assert str(job_cancellation_id) == cancellation_id
            assert [(str(row.job_id), row.dagster_run_id) for row in members] == [
                (str(linked_job_id), "canonical-run")
            ]
            assert run_ids == ("canonical-run",)
    finally:
        await target_engine.dispose()
        async with admin_engine.connect() as connection:
            autocommit = await connection.execution_options(isolation_level="AUTOCOMMIT")
            await autocommit.execute(text(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)'))
        await admin_engine.dispose()


async def test_pipeline_projection_access_paths_rejects_member_job_lifecycle_drift(
    pg_container: Any,
) -> None:
    admin_dsn = normalize_async_dsn(pg_container.get_connection_url())
    database = f"pipeline_projection_cancel_drift_{uuid4().hex}"
    target_dsn = make_url(admin_dsn).set(database=database).render_as_string(
        hide_password=False
    )
    admin_engine = make_async_engine(admin_dsn)
    async with admin_engine.connect() as connection:
        autocommit = await connection.execution_options(isolation_level="AUTOCOMMIT")
        await autocommit.execute(text(f'CREATE DATABASE "{database}"'))

    request_id = "c3000000-0000-4000-8000-000000000003"
    job_id = "c4000000-0000-4000-8000-000000000004"
    cancellation_id = "c5000000-0000-4000-8000-000000000005"
    target_engine = make_async_engine(target_dsn)
    try:
        await asyncio.to_thread(_run_alembic, target_dsn, _PRE_REVISION)
        async with target_engine.begin() as connection:
            await connection.execute(
                text(
                    """
                    WITH inserted_job AS (
                      INSERT INTO ops.import_jobs (
                      job_id, kind, payload, status, trigger_kind
                      ) VALUES (
                        :job_id, 'feature_update_request', '{}'::jsonb,
                        'queued', 'update_request'
                      )
                      RETURNING job_id
                    ),
                    inserted_request AS (
                      INSERT INTO ops.feature_update_requests (
                      request_id, scope_type, scope, run_mode, status, job_id
                      )
                      SELECT
                        :request_id, 'feature_ids',
                        '{"type":"feature_ids","feature_ids":[]}'::jsonb,
                        'queued', 'queued', job_id
                      FROM inserted_job
                      RETURNING request_id
                    ),
                    inserted_attempt AS (
                      INSERT INTO ops.pipeline_cancellations (
                      cancellation_id, root_kind, root_id, status,
                      requested_by, finished_at
                      )
                      SELECT
                        :cancellation_id, 'update_request', request_id,
                        'completed', 'migration-test', now()
                      FROM inserted_request
                      RETURNING cancellation_id
                    )
                    INSERT INTO ops.pipeline_cancellation_members (
                      cancellation_id, member_kind, member_id,
                      initial_status, result, terminal_status
                    )
                    SELECT
                      attempt.cancellation_id, 'update_request', request.request_id,
                      'queued', 'cancelled', 'cancelled'
                    FROM inserted_attempt AS attempt
                    CROSS JOIN inserted_request AS request
                    """
                ),
                {
                    "request_id": request_id,
                    "job_id": job_id,
                    "cancellation_id": cancellation_id,
                },
            )

        await target_engine.dispose()
        with pytest.raises(RuntimeError, match="conflicting request/job cancellation"):
            await asyncio.to_thread(_run_alembic, target_dsn, _TARGET_REVISION)

        target_engine = make_async_engine(target_dsn)
        async with target_engine.connect() as connection:
            assert (
                await connection.scalar(text("SELECT version_num FROM alembic_version"))
            ) == _PRE_REVISION
    finally:
        await target_engine.dispose()
        async with admin_engine.connect() as connection:
            autocommit = await connection.execution_options(isolation_level="AUTOCOMMIT")
            await autocommit.execute(
                text(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)')
            )
        await admin_engine.dispose()


async def test_pipeline_projection_access_paths_rejects_active_orphan_job_members(
    pg_container: Any,
) -> None:
    admin_dsn = normalize_async_dsn(pg_container.get_connection_url())
    database = f"pipeline_projection_orphan_members_{uuid4().hex}"
    target_dsn = make_url(admin_dsn).set(database=database).render_as_string(
        hide_password=False
    )
    admin_engine = make_async_engine(admin_dsn)
    async with admin_engine.connect() as connection:
        autocommit = await connection.execution_options(isolation_level="AUTOCOMMIT")
        await autocommit.execute(text(f'CREATE DATABASE "{database}"'))

    in_progress_cancellation_id = "c6000000-0000-4000-8000-000000000006"
    retryable_cancellation_id = "c7000000-0000-4000-8000-000000000007"
    in_progress_job_id = "c8000000-0000-4000-8000-000000000008"
    retryable_job_id = "c9000000-0000-4000-8000-000000000009"
    target_engine = make_async_engine(target_dsn)
    try:
        await asyncio.to_thread(_run_alembic, target_dsn, _PRE_REVISION)
        async with target_engine.begin() as connection:
            await connection.execute(
                text(
                    """
                    INSERT INTO ops.pipeline_cancellations (
                      cancellation_id, root_kind, root_id, status,
                      requested_by, error, finished_at
                    ) VALUES
                    (
                      :in_progress_cancellation_id, 'import_job',
                      :in_progress_job_id, 'in_progress',
                      'migration-test', NULL, NULL
                    ),
                    (
                      :retryable_cancellation_id, 'import_job',
                      :retryable_job_id, 'retryable',
                      'migration-test', '{}'::jsonb, now()
                    )
                    """
                ),
                {
                    "in_progress_cancellation_id": in_progress_cancellation_id,
                    "retryable_cancellation_id": retryable_cancellation_id,
                    "in_progress_job_id": in_progress_job_id,
                    "retryable_job_id": retryable_job_id,
                },
            )
            await connection.execute(
                text(
                    """
                    INSERT INTO ops.pipeline_cancellation_members (
                      cancellation_id, member_kind, member_id,
                      initial_status, result
                    ) VALUES
                    (
                      :in_progress_cancellation_id, 'import_job',
                      :in_progress_job_id, 'queued', 'pending'
                    ),
                    (
                      :retryable_cancellation_id, 'import_job',
                      :retryable_job_id, 'queued', 'pending'
                    )
                    """
                ),
                {
                    "in_progress_cancellation_id": in_progress_cancellation_id,
                    "retryable_cancellation_id": retryable_cancellation_id,
                    "in_progress_job_id": in_progress_job_id,
                    "retryable_job_id": retryable_job_id,
                },
            )

        await target_engine.dispose()
        with pytest.raises(
            RuntimeError,
            match="active/retryable orphan cancellation members",
        ) as raised:
            await asyncio.to_thread(_run_alembic, target_dsn, _TARGET_REVISION)
        diagnostic = str(raised.value)
        assert f"{in_progress_cancellation_id}:{in_progress_job_id}" in diagnostic
        assert f"{retryable_cancellation_id}:{retryable_job_id}" in diagnostic

        target_engine = make_async_engine(target_dsn)
        async with target_engine.connect() as connection:
            assert (
                await connection.scalar(text("SELECT version_num FROM alembic_version"))
            ) == _PRE_REVISION
            members = (
                await connection.execute(
                    text(
                        """
                        SELECT cancellation_id, member_kind, member_id
                        FROM ops.pipeline_cancellation_members
                        WHERE cancellation_id IN (
                          CAST(:in_progress_cancellation_id AS uuid),
                          CAST(:retryable_cancellation_id AS uuid)
                        )
                        ORDER BY cancellation_id
                        """
                    ),
                    {
                        "in_progress_cancellation_id": in_progress_cancellation_id,
                        "retryable_cancellation_id": retryable_cancellation_id,
                    },
                )
            ).all()
            assert [
                (str(row.cancellation_id), row.member_kind, str(row.member_id))
                for row in members
            ] == [
                (in_progress_cancellation_id, "import_job", in_progress_job_id),
                (retryable_cancellation_id, "import_job", retryable_job_id),
            ]
    finally:
        await target_engine.dispose()
        async with admin_engine.connect() as connection:
            autocommit = await connection.execution_options(isolation_level="AUTOCOMMIT")
            await autocommit.execute(
                text(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)')
            )
        await admin_engine.dispose()


async def test_pipeline_projection_access_paths_cleans_terminal_orphan_job_members(
    pg_container: Any,
) -> None:
    admin_dsn = normalize_async_dsn(pg_container.get_connection_url())
    database = f"pipeline_projection_terminal_orphans_{uuid4().hex}"
    target_dsn = make_url(admin_dsn).set(database=database).render_as_string(
        hide_password=False
    )
    admin_engine = make_async_engine(admin_dsn)
    async with admin_engine.connect() as connection:
        autocommit = await connection.execution_options(isolation_level="AUTOCOMMIT")
        await autocommit.execute(text(f'CREATE DATABASE "{database}"'))

    completed_cancellation_id = "ca000000-0000-4000-8000-00000000000a"
    failed_cancellation_id = "cb000000-0000-4000-8000-00000000000b"
    completed_job_id = "cc000000-0000-4000-8000-00000000000c"
    failed_job_id = "cd000000-0000-4000-8000-00000000000d"
    completed_run_id = "terminal-completed-run"
    failed_run_id = "terminal-failed-run"
    target_engine = make_async_engine(target_dsn)
    try:
        await asyncio.to_thread(_run_alembic, target_dsn, _PRE_REVISION)
        async with target_engine.begin() as connection:
            await connection.execute(
                text(
                    """
                    INSERT INTO ops.pipeline_cancellations (
                      cancellation_id, root_kind, root_id, status,
                      requested_by, error, finished_at
                    ) VALUES
                    (
                      :completed_cancellation_id, 'import_job', :completed_job_id,
                      'completed', 'migration-test', NULL, now()
                    ),
                    (
                      :failed_cancellation_id, 'import_job', :failed_job_id,
                      'failed', 'migration-test', '{}'::jsonb, now()
                    )
                    """
                ),
                {
                    "completed_cancellation_id": completed_cancellation_id,
                    "failed_cancellation_id": failed_cancellation_id,
                    "completed_job_id": completed_job_id,
                    "failed_job_id": failed_job_id,
                },
            )
            await connection.execute(
                text(
                    """
                    INSERT INTO ops.pipeline_cancellation_runs (
                      cancellation_id, dagster_run_id, initial_status,
                      result, terminal_status, error
                    ) VALUES
                    (
                      :completed_cancellation_id, :completed_run_id, 'STARTED',
                      'already_terminal', 'SUCCESS', NULL
                    ),
                    (
                      :failed_cancellation_id, :failed_run_id, 'STARTED',
                      'cancel_failed', NULL, '{}'::jsonb
                    )
                    """
                ),
                {
                    "completed_cancellation_id": completed_cancellation_id,
                    "failed_cancellation_id": failed_cancellation_id,
                    "completed_run_id": completed_run_id,
                    "failed_run_id": failed_run_id,
                },
            )
            await connection.execute(
                text(
                    """
                    INSERT INTO ops.pipeline_cancellation_members (
                      cancellation_id, member_kind, member_id, dagster_run_id,
                      operation_kind, requires_run_termination,
                      initial_status, result, terminal_status, error
                    ) VALUES
                    (
                      :completed_cancellation_id, 'import_job', :completed_job_id,
                      :completed_run_id, 'orphan-job', false,
                      'done', 'already_terminal', 'done', NULL
                    ),
                    (
                      :failed_cancellation_id, 'import_job', :failed_job_id,
                      :failed_run_id, 'orphan-job', true,
                      'running', 'cancel_failed', NULL, '{}'::jsonb
                    )
                    """
                ),
                {
                    "completed_cancellation_id": completed_cancellation_id,
                    "failed_cancellation_id": failed_cancellation_id,
                    "completed_job_id": completed_job_id,
                    "failed_job_id": failed_job_id,
                    "completed_run_id": completed_run_id,
                    "failed_run_id": failed_run_id,
                },
            )

        await target_engine.dispose()
        await asyncio.to_thread(_run_alembic, target_dsn, _TARGET_REVISION)
        target_engine = make_async_engine(target_dsn)
        async with target_engine.connect() as connection:
            assert (
                await connection.scalar(text("SELECT version_num FROM alembic_version"))
            ) == _TARGET_REVISION
            attempt_count = await connection.scalar(
                text(
                    """
                    SELECT count(*)
                    FROM ops.pipeline_cancellations
                    WHERE cancellation_id IN (
                      CAST(:completed_cancellation_id AS uuid),
                      CAST(:failed_cancellation_id AS uuid)
                    )
                    """
                ),
                {
                    "completed_cancellation_id": completed_cancellation_id,
                    "failed_cancellation_id": failed_cancellation_id,
                },
            )
            member_count = await connection.scalar(
                text(
                    """
                    SELECT count(*)
                    FROM ops.pipeline_cancellation_members
                    WHERE cancellation_id IN (
                      CAST(:completed_cancellation_id AS uuid),
                      CAST(:failed_cancellation_id AS uuid)
                    )
                    """
                ),
                {
                    "completed_cancellation_id": completed_cancellation_id,
                    "failed_cancellation_id": failed_cancellation_id,
                },
            )
            run_count = await connection.scalar(
                text(
                    """
                    SELECT count(*)
                    FROM ops.pipeline_cancellation_runs
                    WHERE cancellation_id IN (
                      CAST(:completed_cancellation_id AS uuid),
                      CAST(:failed_cancellation_id AS uuid)
                    )
                    """
                ),
                {
                    "completed_cancellation_id": completed_cancellation_id,
                    "failed_cancellation_id": failed_cancellation_id,
                },
            )
            assert attempt_count == 2
            assert member_count == 0
            assert run_count == 0
            member_columns, member_constraints, _ = (
                await _cancellation_member_contract(connection)
            )
            assert member_columns == {"job_id"}
            assert "ON DELETE RESTRICT" in member_constraints[
                "fk_pipeline_cancellation_members_job"
            ]
            with pytest.raises(IntegrityError):
                async with connection.begin_nested():
                    await connection.execute(
                        text(
                            """
                            INSERT INTO ops.pipeline_cancellation_members (
                              cancellation_id, job_id, initial_status,
                              result, terminal_status
                            ) VALUES (
                              :completed_cancellation_id, :completed_job_id,
                              'done', 'already_terminal', 'done'
                            )
                            """
                        ),
                        {
                            "completed_cancellation_id": completed_cancellation_id,
                            "completed_job_id": completed_job_id,
                        },
                    )
    finally:
        await target_engine.dispose()
        async with admin_engine.connect() as connection:
            autocommit = await connection.execution_options(isolation_level="AUTOCOMMIT")
            await autocommit.execute(
                text(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)')
            )
        await admin_engine.dispose()


async def test_pipeline_projection_access_paths_rejects_active_relink_candidate(
    pg_container: Any,
) -> None:
    admin_dsn = normalize_async_dsn(pg_container.get_connection_url())
    database = f"pipeline_projection_active_{uuid4().hex}"
    target_dsn = make_url(admin_dsn).set(database=database).render_as_string(hide_password=False)
    admin_engine = make_async_engine(admin_dsn)
    async with admin_engine.connect() as connection:
        autocommit = await connection.execution_options(isolation_level="AUTOCOMMIT")
        await autocommit.execute(text(f'CREATE DATABASE "{database}"'))

    request_id = "e1000000-0000-4000-8000-000000000001"
    jobless_request_id = "e2000000-0000-4000-8000-000000000002"
    source_job_id = "e3000000-0000-4000-8000-000000000003"
    child_job_id = "e4000000-0000-4000-8000-000000000004"
    target_engine = make_async_engine(target_dsn)
    try:
        await asyncio.to_thread(_run_alembic, target_dsn, _PRE_REVISION)
        async with target_engine.begin() as connection:
            await connection.execute(
                text(
                    """
                    INSERT INTO ops.import_jobs (
                      job_id, kind, parent_job_id, payload, status,
                      provider, dataset_key, dagster_run_id, trigger_kind,
                      operation_registry_version, dagster_run_status
                    ) VALUES
                    (
                      :source_job_id, 'provider_feature_load_run', NULL,
                      '{}'::jsonb, 'queued', NULL, NULL,
                      'active-source-run', 'manual', 'registry-v1', 'QUEUED'
                    ),
                    (
                      :child_job_id, 'provider_feature_load', :source_job_id,
                      '{}'::jsonb, 'done', 'canonical-provider', 'canonical-dataset',
                      'active-source-run', NULL, NULL, NULL
                    )
                    """
                ),
                {
                    "source_job_id": source_job_id,
                    "child_job_id": child_job_id,
                },
            )
            await connection.execute(
                text(
                    """
                    INSERT INTO ops.feature_update_requests (
                      request_id, scope_type, scope, run_mode, status, job_id
                    ) VALUES
                    (
                      :request_id, 'provider_dataset',
                      jsonb_build_object(
                        'type', 'provider_dataset',
                        'provider', 'canonical-provider',
                        'dataset_key', 'canonical-dataset'
                      ),
                      'queued', 'queued', :source_job_id
                    ),
                    (
                      :jobless_request_id, 'bbox',
                      jsonb_build_object(
                        'type', 'bbox', 'min_lon', 126, 'min_lat', 37,
                        'max_lon', 127, 'max_lat', 38
                      ),
                      'queued', 'queued', NULL
                    )
                    """
                ),
                {
                    "request_id": request_id,
                    "jobless_request_id": jobless_request_id,
                    "source_job_id": source_job_id,
                },
            )

        unsafe_states = (
            ("source_queued", "queued", "SUCCESS", "queued", "queued", "done"),
            ("source_running", "running", "SUCCESS", "queued", "queued", "done"),
            ("source_raw_queued", "done", "QUEUED", "queued", "queued", "done"),
            ("request_running", "done", "SUCCESS", "running", "queued", "done"),
            ("jobless_running", "done", "SUCCESS", "queued", "running", "done"),
            ("active_child", "done", "SUCCESS", "queued", "queued", "running"),
        )
        for (
            case_name,
            source_status,
            source_dagster_run_status,
            request_status,
            jobless_status,
            child_status,
        ) in unsafe_states:
            async with target_engine.begin() as connection:
                await connection.execute(
                    text(
                        """
                        UPDATE ops.import_jobs
                           SET status = :source_status,
                               dagster_run_status = :source_dagster_run_status,
                               started_at = CASE
                                 WHEN :source_status = 'running' THEN now()
                                 ELSE started_at
                               END
                         WHERE job_id = :source_job_id
                        """
                    ),
                    {
                        "source_status": source_status,
                        "source_dagster_run_status": source_dagster_run_status,
                        "source_job_id": source_job_id,
                    },
                )
                await connection.execute(
                    text(
                        """
                        UPDATE ops.import_jobs
                           SET status = :child_status,
                               started_at = CASE
                                 WHEN :child_status = 'running' THEN now()
                                 ELSE started_at
                               END
                         WHERE job_id = :child_job_id
                        """
                    ),
                    {
                        "child_status": child_status,
                        "child_job_id": child_job_id,
                    },
                )
                await connection.execute(
                    text(
                        """
                        UPDATE ops.feature_update_requests
                           SET status = :request_status,
                               started_at = CASE
                                 WHEN :request_status = 'running' THEN now()
                                 ELSE started_at
                               END
                         WHERE request_id = :request_id
                        """
                    ),
                    {
                        "request_status": request_status,
                        "request_id": request_id,
                    },
                )
                await connection.execute(
                    text(
                        """
                        UPDATE ops.feature_update_requests
                           SET status = :jobless_status,
                               started_at = CASE
                                 WHEN :jobless_status = 'running' THEN now()
                                 ELSE NULL
                               END
                         WHERE request_id = :jobless_request_id
                        """
                    ),
                    {
                        "jobless_status": jobless_status,
                        "jobless_request_id": jobless_request_id,
                    },
                )

            await target_engine.dispose()
            with pytest.raises(RuntimeError):
                await asyncio.to_thread(_run_alembic, target_dsn, _TARGET_REVISION)

            target_engine = make_async_engine(target_dsn)
            async with target_engine.connect() as connection:
                revision, linked_job_id, jobless_job_id = (
                    await connection.execute(
                        text(
                            """
                            SELECT
                              version.version_num,
                              linked.job_id AS linked_job_id,
                              jobless.job_id AS jobless_job_id
                            FROM alembic_version AS version
                            CROSS JOIN ops.feature_update_requests AS linked
                            CROSS JOIN ops.feature_update_requests AS jobless
                            WHERE linked.request_id = :request_id
                              AND jobless.request_id = :jobless_request_id
                            """
                        ),
                        {
                            "request_id": request_id,
                            "jobless_request_id": jobless_request_id,
                        },
                    )
                ).one()
                migration_audit_events = (
                    await connection.execute(
                        text(
                            """
                            SELECT count(*)
                            FROM ops.import_job_events
                            WHERE code = 'migration.feature_update_request_relinked'
                            """
                        )
                    )
                ).scalar_one()
                assert revision == _PRE_REVISION, case_name
                assert str(linked_job_id) == source_job_id, case_name
                assert jobless_job_id is None, case_name
                assert migration_audit_events == 0, case_name
                assert "WHERE (job_id IS NOT NULL)" in (
                    await _feature_update_job_index_definition(connection)
                )

        async with target_engine.begin() as connection:
            await connection.execute(
                text(
                    """
                    UPDATE ops.import_jobs
                       SET status = 'done',
                           dagster_run_status = 'SUCCESS',
                           finished_at = now()
                     WHERE job_id = :source_job_id
                    """
                ),
                {"source_job_id": source_job_id},
            )
            await connection.execute(
                text(
                    """
                    UPDATE ops.feature_update_requests
                       SET status = 'queued', started_at = NULL
                     WHERE request_id = :request_id
                    """
                ),
                {"request_id": request_id},
            )
            await connection.execute(
                text(
                    """
                    UPDATE ops.import_jobs
                       SET status = 'done', finished_at = now()
                     WHERE job_id = :child_job_id
                    """
                ),
                {"child_job_id": child_job_id},
            )
            await connection.execute(
                text(
                    """
                    UPDATE ops.feature_update_requests
                       SET status = 'queued', started_at = NULL
                     WHERE request_id = :jobless_request_id
                    """
                ),
                {"jobless_request_id": jobless_request_id},
            )

        await target_engine.dispose()
        await asyncio.to_thread(_run_alembic, target_dsn, _TARGET_REVISION)
        target_engine = make_async_engine(target_dsn)
        async with target_engine.connect() as connection:
            relinked_rows = {
                str(row.request_id): (
                    str(row.job_id),
                    row.provider,
                    row.dataset_key,
                )
                for row in await connection.execute(
                    text(
                        """
                        SELECT
                          request.request_id,
                          request.job_id,
                          job.provider,
                          job.dataset_key
                        FROM ops.feature_update_requests AS request
                        JOIN ops.import_jobs AS job ON job.job_id = request.job_id
                        WHERE request.request_id IN (
                          CAST(:request_id AS uuid),
                          CAST(:jobless_request_id AS uuid)
                        )
                        """
                    ),
                    {
                        "request_id": request_id,
                        "jobless_request_id": jobless_request_id,
                    },
                )
            }
            assert str(relinked_rows[request_id][0]) != source_job_id
            assert relinked_rows[request_id][1:] == (
                "canonical-provider",
                "canonical-dataset",
            )
            assert relinked_rows[jobless_request_id][1:] == (None, None)
            assert len({row[0] for row in relinked_rows.values()}) == 2
    finally:
        await target_engine.dispose()
        async with admin_engine.connect() as connection:
            autocommit = await connection.execution_options(isolation_level="AUTOCOMMIT")
            await autocommit.execute(text(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)'))
        await admin_engine.dispose()


async def test_pipeline_projection_access_paths_lock_blocks_concurrent_writer(
    pg_container: Any,
) -> None:
    admin_dsn = normalize_async_dsn(pg_container.get_connection_url())
    database = f"pipeline_projection_lock_{uuid4().hex}"
    target_dsn = make_url(admin_dsn).set(database=database).render_as_string(hide_password=False)
    admin_engine = make_async_engine(admin_dsn)
    async with admin_engine.connect() as connection:
        autocommit = await connection.execution_options(isolation_level="AUTOCOMMIT")
        await autocommit.execute(text(f'CREATE DATABASE "{database}"'))

    request_id = "d1000000-0000-4000-8000-000000000001"
    writer_job_id = "d2000000-0000-4000-8000-000000000002"
    target_engine = make_async_engine(target_dsn)
    observer_engine = make_async_engine(target_dsn)
    writer_engine = make_async_engine(target_dsn)
    lock_acquired = ThreadEvent()
    release_lock = ThreadEvent()
    locked_tables_seen: set[str] = set()
    migration_backend_pid: list[int] = []
    completed_statements: list[str] = []
    migration_task: asyncio.Task[None] | None = None
    writer_task: asyncio.Task[None] | None = None
    listener_installed = False

    def _pause_after_identity_locks(
        connection: Any,
        _cursor: Any,
        statement: str,
        _parameters: Any,
        _context: Any,
        _executemany: bool,
    ) -> None:
        if connection.engine.url.database != database:
            return
        normalized = " ".join(statement.lower().replace('"', "").split())
        completed_statements.append(normalized)
        if not normalized.startswith("lock table"):
            return
        for table_name in (
            "feature_update_requests",
            "import_jobs",
            "import_job_events",
        ):
            if f"ops.{table_name}" in normalized:
                locked_tables_seen.add(table_name)
        if locked_tables_seen != {
            "feature_update_requests",
            "import_jobs",
            "import_job_events",
        }:
            return
        driver_connection = connection.connection.driver_connection
        backend_pid = (
            driver_connection.get_server_pid()
            if hasattr(driver_connection, "get_server_pid")
            else driver_connection.info.backend_pid
        )
        migration_backend_pid[:] = [int(backend_pid)]
        lock_acquired.set()
        if not release_lock.wait(timeout=30):
            raise TimeoutError("migration identity lock test was not released")

    try:
        await asyncio.to_thread(_run_alembic, target_dsn, _PRE_REVISION)
        async with target_engine.begin() as connection:
            await connection.execute(
                text(
                    """
                    INSERT INTO ops.feature_update_requests (
                      request_id, scope_type, scope, run_mode, job_id
                    ) VALUES (
                      :request_id, 'provider_dataset',
                      jsonb_build_object(
                        'type', 'provider_dataset',
                        'provider', 'lock-provider',
                        'dataset_key', 'lock-dataset'
                      ),
                      'queued', NULL
                    )
                    """
                ),
                {"request_id": request_id},
            )
            assert "WHERE (job_id IS NOT NULL)" in (
                await _feature_update_job_index_definition(connection)
            )
        await target_engine.dispose()

        event.listen(Engine, "after_cursor_execute", _pause_after_identity_locks)
        listener_installed = True
        migration_task = asyncio.create_task(
            asyncio.to_thread(_run_alembic, target_dsn, _TARGET_REVISION)
        )
        assert await asyncio.to_thread(lock_acquired.wait, 10)
        assert migration_backend_pid

        identity_statements = [
            statement
            for statement in completed_statements
            if "ops.feature_update_requests" in statement
            or "ops.import_jobs" in statement
            or "ops.import_job_events" in statement
        ]
        assert identity_statements
        assert identity_statements[0].startswith("lock table")

        async with observer_engine.connect() as observer:
            held_locks = {
                (str(row.relname), str(row.mode), bool(row.granted))
                for row in await observer.execute(
                    text(
                        """
                        SELECT relation_row.relname, lock_row.mode, lock_row.granted
                        FROM pg_locks AS lock_row
                        JOIN pg_class AS relation_row
                          ON relation_row.oid = lock_row.relation
                        JOIN pg_namespace AS namespace_row
                          ON namespace_row.oid = relation_row.relnamespace
                        WHERE lock_row.pid = :migration_pid
                          AND namespace_row.nspname = 'ops'
                          AND relation_row.relname IN (
                            'feature_update_requests', 'import_jobs',
                            'import_job_events'
                          )
                        """
                    ),
                    {"migration_pid": migration_backend_pid[0]},
                )
            }
            assert {
                ("feature_update_requests", "AccessExclusiveLock", True),
                ("import_jobs", "AccessExclusiveLock", True),
                ("import_job_events", "AccessExclusiveLock", True),
            } <= held_locks
            revision = (
                await observer.execute(text("SELECT version_num FROM alembic_version"))
            ).scalar_one()
            assert revision == _PRE_REVISION

            writer_pid_future: asyncio.Future[int] = asyncio.get_running_loop().create_future()

            async def _write_import_job() -> None:
                async with writer_engine.begin() as writer:
                    await writer.execute(text("SET LOCAL lock_timeout = '30s'"))
                    writer_pid = int(
                        (await writer.execute(text("SELECT pg_backend_pid()"))).scalar_one()
                    )
                    writer_pid_future.set_result(writer_pid)
                    await writer.execute(
                        text(
                            """
                            INSERT INTO ops.import_jobs (
                              job_id, kind, payload, status
                            ) VALUES (
                              :job_id, 'concurrent_writer', '{}'::jsonb, 'queued'
                            )
                            """
                        ),
                        {"job_id": writer_job_id},
                    )

            writer_task = asyncio.create_task(_write_import_job())
            writer_pid = await asyncio.wait_for(writer_pid_future, timeout=10)
            writer_waiting = False
            for _ in range(200):
                writer_waiting = bool(
                    (
                        await observer.execute(
                            text(
                                """
                                SELECT EXISTS (
                                  SELECT 1
                                  FROM pg_locks AS lock_row
                                  JOIN pg_class AS relation_row
                                    ON relation_row.oid = lock_row.relation
                                  JOIN pg_namespace AS namespace_row
                                    ON namespace_row.oid = relation_row.relnamespace
                                  WHERE lock_row.pid = :writer_pid
                                    AND NOT lock_row.granted
                                    AND namespace_row.nspname = 'ops'
                                    AND relation_row.relname = 'import_jobs'
                                )
                                """
                            ),
                            {"writer_pid": writer_pid},
                        )
                    ).scalar_one()
                )
                if writer_waiting:
                    break
            assert writer_waiting
            assert not writer_task.done()

        release_lock.set()
        await asyncio.wait_for(migration_task, timeout=30)
        await asyncio.wait_for(writer_task, timeout=30)

        async with observer_engine.connect() as connection:
            revision, linked_job_id = (
                await connection.execute(
                    text(
                        """
                        SELECT version.version_num, request.job_id
                        FROM alembic_version AS version
                        CROSS JOIN ops.feature_update_requests AS request
                        WHERE request.request_id = :request_id
                        """
                    ),
                    {"request_id": request_id},
                )
            ).one()
            concurrent_job_count = (
                await connection.execute(
                    text("SELECT count(*) FROM ops.import_jobs WHERE job_id = :job_id"),
                    {"job_id": writer_job_id},
                )
            ).scalar_one()
            assert revision == _TARGET_REVISION
            assert linked_job_id is not None
            assert concurrent_job_count == 1
            assert " WHERE " not in (
                await _feature_update_job_index_definition(
                    connection,
                    index_name="uq_feature_update_requests_job_id",
                )
            )
    finally:
        release_lock.set()
        started_tasks = [task for task in (migration_task, writer_task) if task is not None]
        if started_tasks:
            await asyncio.wait_for(
                asyncio.gather(*started_tasks, return_exceptions=True),
                timeout=30,
            )
        if listener_installed:
            event.remove(
                Engine,
                "after_cursor_execute",
                _pause_after_identity_locks,
            )
        await target_engine.dispose()
        await observer_engine.dispose()
        await writer_engine.dispose()
        async with admin_engine.connect() as connection:
            autocommit = await connection.execution_options(isolation_level="AUTOCOMMIT")
            await autocommit.execute(text(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)'))
        await admin_engine.dispose()


async def test_import_job_event_clock_detects_late_commit_and_rollback(
    pg_container: Any,
) -> None:
    """Top-N 밖 late commit도 clock revision으로 감지하고 rollback은 되돌린다."""
    admin_dsn = normalize_async_dsn(pg_container.get_connection_url())
    database = f"pipeline_projection_event_clock_{uuid4().hex}"
    target_dsn = make_url(admin_dsn).set(database=database).render_as_string(
        hide_password=False
    )
    admin_engine = make_async_engine(admin_dsn)
    async with admin_engine.connect() as connection:
        autocommit = await connection.execution_options(isolation_level="AUTOCOMMIT")
        await autocommit.execute(text(f'CREATE DATABASE "{database}"'))

    job_id = "e1000000-0000-4000-8000-000000000001"
    target_engine = make_async_engine(target_dsn)
    old_connection: Any | None = None
    rollback_connection: Any | None = None
    try:
        await asyncio.to_thread(_run_alembic, target_dsn, _TARGET_REVISION)
        async with target_engine.begin() as connection:
            await connection.execute(
                text(
                    """
                    INSERT INTO ops.import_jobs (job_id, kind, payload, status)
                    VALUES (:job_id, 'event_clock_fixture', '{}'::jsonb, 'running')
                    """
                ),
                {"job_id": job_id},
            )

        async with AsyncSession(target_engine) as session:
            empty_job = await _import_job_events_snapshot(session, job_id)
            empty_global = await _import_jobs_snapshot(session)
        assert empty_job == {
            "job_id": job_id,
            "event_clock_revision": 0,
            "latest_event_at": None,
            "recent_events": [],
        }
        assert empty_global["event_clock_revision"] == 0
        assert empty_global["latest_event_id"] is None
        assert empty_global["latest_event_at"] is None

        old_connection = await target_engine.connect()
        old_transaction = await old_connection.begin()
        old_started_at = await old_connection.scalar(text("SELECT now()"))
        assert old_started_at is not None
        newer_occurred_at = old_started_at + timedelta(hours=1)

        async with target_engine.begin() as newer:
            await newer.execute(
                text(
                    """
                    INSERT INTO ops.import_job_events (
                      event_id, job_id, level, message, occurred_at
                    )
                    SELECT
                      ('e3000000-0000-4000-8000-'
                        || lpad(seed.n::text, 12, '0'))::uuid,
                      CAST(:job_id AS uuid), 'info',
                      'newer event ' || seed.n::text,
                      CAST(:occurred_at AS timestamptz)
                    FROM generate_series(1, 6) AS seed(n)
                    """
                ),
                {"job_id": job_id, "occurred_at": newer_occurred_at},
            )

        async with AsyncSession(target_engine) as session:
            after_newer_job = await _import_job_events_snapshot(session, job_id)
            after_newer_global = await _import_jobs_snapshot(session)
        expected_recent_ids = [
            f"e3000000-0000-4000-8000-{number:012d}"
            for number in range(6, 1, -1)
        ]
        assert after_newer_job["event_clock_revision"] == 1
        assert [
            event_row["event_id"] for event_row in after_newer_job["recent_events"]
        ] == expected_recent_ids
        assert after_newer_job["latest_event_at"] == newer_occurred_at.isoformat()
        assert after_newer_global["event_clock_revision"] == 1
        assert after_newer_global["latest_event_id"] == expected_recent_ids[0]
        for event_row in after_newer_job["recent_events"]:
            assert isinstance(event_row["occurred_at"], str)
            assert datetime.fromisoformat(event_row["occurred_at"]) == newer_occurred_at
        live_topics = {"import_jobs", f"import_job_events:{job_id}"}
        async with AsyncSession(target_engine) as session:
            snapshots_after_newer = await collect_live_topic_snapshots(
                session,
                live_topics,
            )
        for snapshot in snapshots_after_newer.values():
            assert isinstance(json.dumps(snapshot.data), str)

        await old_connection.execute(
            text(
                """
                INSERT INTO ops.import_job_events (
                  event_id, job_id, level, message
                ) VALUES (
                  'e4000000-0000-4000-8000-000000000001',
                  :job_id, 'warning', 'late committed older event'
                )
                """
            ),
            {"job_id": job_id},
        )
        await old_transaction.commit()
        await old_connection.close()
        old_connection = None

        async with AsyncSession(target_engine) as session:
            after_late_job = await _import_job_events_snapshot(session, job_id)
            after_late_global = await _import_jobs_snapshot(session)
        assert after_late_job["event_clock_revision"] == 2
        assert [
            event_row["event_id"] for event_row in after_late_job["recent_events"]
        ] == expected_recent_ids
        assert after_late_global["event_clock_revision"] == 2
        assert after_late_global["latest_event_id"] == expected_recent_ids[0]
        async with AsyncSession(target_engine) as session:
            snapshots_after_late = await collect_live_topic_snapshots(
                session,
                live_topics,
            )
        for topic in live_topics:
            assert (
                snapshots_after_late[topic].revision
                != snapshots_after_newer[topic].revision
            )
            assert isinstance(json.dumps(snapshots_after_late[topic].data), str)
        assert [
            event_row["event_id"]
            for event_row in snapshots_after_late[
                f"import_job_events:{job_id}"
            ].data["recent_events"]
        ] == expected_recent_ids

        rollback_connection = await target_engine.connect()
        rollback_transaction = await rollback_connection.begin()
        await rollback_connection.execute(
            text(
                """
                INSERT INTO ops.import_job_events (
                  event_id, job_id, level, message
                ) VALUES (
                  'e5000000-0000-4000-8000-000000000001',
                  :job_id, 'info', 'rolled back event'
                )
                """
            ),
            {"job_id": job_id},
        )
        assert int(
            await rollback_connection.scalar(
                text("SELECT revision FROM ops.import_job_event_clock WHERE clock_id")
            )
        ) == 3
        await rollback_transaction.rollback()
        await rollback_connection.close()
        rollback_connection = None

        async with AsyncSession(target_engine) as session:
            after_rollback = await _import_job_events_snapshot(session, job_id)
        assert after_rollback["event_clock_revision"] == 2
        assert [
            event_row["event_id"] for event_row in after_rollback["recent_events"]
        ] == expected_recent_ids

        async with target_engine.begin() as connection:
            await connection.execute(
                text("DELETE FROM ops.import_jobs WHERE job_id = :job_id"),
                {"job_id": job_id},
            )
        async with AsyncSession(target_engine) as session:
            after_last_job_delete = await _import_jobs_snapshot(session)
        assert after_last_job_delete["event_clock_revision"] == 3
        assert after_last_job_delete["latest_event_id"] is None
        assert after_last_job_delete["latest_event_at"] is None
        assert after_last_job_delete["counts_by_status"] == {}
        assert after_last_job_delete["active_jobs"] == []
        assert after_last_job_delete["latest_job_created_at"] is None
    finally:
        if old_connection is not None:
            await old_connection.close()
        if rollback_connection is not None:
            await rollback_connection.close()
        await target_engine.dispose()
        async with admin_engine.connect() as connection:
            autocommit = await connection.execution_options(isolation_level="AUTOCOMMIT")
            await autocommit.execute(text(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)'))
        await admin_engine.dispose()


async def test_pipeline_projection_lock_retry_allows_event_reader(
    pg_container: Any,
) -> None:
    """event/clock reader 경합 때 migration은 앞선 job lock을 남기지 않는다."""
    admin_dsn = normalize_async_dsn(pg_container.get_connection_url())
    database = f"pipeline_projection_event_lock_{uuid4().hex}"
    target_dsn = make_url(admin_dsn).set(database=database).render_as_string(
        hide_password=False
    )
    admin_engine = make_async_engine(admin_dsn)
    async with admin_engine.connect() as connection:
        autocommit = await connection.execution_options(isolation_level="AUTOCOMMIT")
        await autocommit.execute(text(f'CREATE DATABASE "{database}"'))

    writer_job_id = "e2000000-0000-4000-8000-000000000002"
    downgrade_writer_job_id = "e2100000-0000-4000-8000-000000000003"
    target_engine = make_async_engine(target_dsn)
    reader_engine = make_async_engine(target_dsn)
    writer_engine = make_async_engine(target_dsn)
    migration_retried = ThreadEvent()
    migration_lock_attempts: list[int] = []
    migration_task: asyncio.Task[None] | None = None
    listener_installed = False

    def _capture_migration_lock_attempt(
        connection: Any,
        _cursor: Any,
        statement: str,
        _parameters: Any,
        _context: Any,
        _executemany: bool,
    ) -> None:
        if connection.engine.url.database != database:
            return
        normalized = " ".join(statement.lower().replace('"', "").split())
        if normalized not in {
            _EXPECTED_IDENTITY_LOCK_SQL,
            _EXPECTED_IDENTITY_LOCK_SQL_WITH_CLOCK,
        }:
            return
        migration_lock_attempts.append(1)
        if len(migration_lock_attempts) >= 2:
            migration_retried.set()

    try:
        await asyncio.to_thread(_run_alembic, target_dsn, _PRE_REVISION)
        await target_engine.dispose()
        event.listen(Engine, "before_cursor_execute", _capture_migration_lock_attempt)
        listener_installed = True

        async with reader_engine.begin() as reader:
            await reader.execute(text("SELECT count(*) FROM ops.import_job_events"))
            migration_task = asyncio.create_task(
                asyncio.to_thread(_run_alembic, target_dsn, _TARGET_REVISION)
            )
            assert await asyncio.to_thread(migration_retried.wait, 10)
            assert len(migration_lock_attempts) >= 2
            assert migration_task is not None
            assert not migration_task.done()

            async with writer_engine.begin() as writer:
                await writer.execute(text("SET LOCAL lock_timeout = '5s'"))
                await writer.execute(
                    text(
                        """
                        INSERT INTO ops.import_jobs (
                          job_id, kind, payload, status
                        ) VALUES (
                          :job_id, 'event_lock_concurrent_writer',
                          '{}'::jsonb, 'queued'
                        )
                        """
                    ),
                    {"job_id": writer_job_id},
                )

            assert not migration_task.done()

        assert migration_task is not None
        await asyncio.wait_for(migration_task, timeout=30)
        target_engine = make_async_engine(target_dsn)
        async with target_engine.connect() as connection:
            revision, writer_count = (
                await connection.execute(
                    text(
                        """
                        SELECT version.version_num, count(job.job_id)
                        FROM alembic_version AS version
                        LEFT JOIN ops.import_jobs AS job
                          ON job.job_id = CAST(:job_id AS uuid)
                        GROUP BY version.version_num
                        """
                    ),
                    {"job_id": writer_job_id},
                )
            ).one()
            assert revision == _TARGET_REVISION
            assert writer_count == 1

        migration_task = None
        migration_lock_attempts.clear()
        migration_retried.clear()
        async with reader_engine.begin() as reader:
            await reader.execute(
                text("SELECT revision FROM ops.import_job_event_clock WHERE clock_id")
            )
            migration_task = asyncio.create_task(
                asyncio.to_thread(
                    _run_alembic,
                    target_dsn,
                    _PRE_REVISION,
                    downgrade=True,
                )
            )
            assert await asyncio.to_thread(migration_retried.wait, 10)
            assert len(migration_lock_attempts) >= 2
            assert not migration_task.done()

            async with writer_engine.begin() as writer:
                await writer.execute(text("SET LOCAL lock_timeout = '5s'"))
                await writer.execute(
                    text(
                        """
                        INSERT INTO ops.import_jobs (
                          job_id, kind, payload, status
                        ) VALUES (
                          :job_id, 'clock_lock_concurrent_writer',
                          '{}'::jsonb, 'queued'
                        )
                        """
                    ),
                    {"job_id": downgrade_writer_job_id},
                )

            assert not migration_task.done()

        await asyncio.wait_for(migration_task, timeout=30)
        async with target_engine.connect() as connection:
            revision, writer_count = (
                await connection.execute(
                    text(
                        """
                        SELECT version.version_num, count(job.job_id)
                        FROM alembic_version AS version
                        LEFT JOIN ops.import_jobs AS job
                          ON job.job_id IN (
                            CAST(:upgrade_job_id AS uuid),
                            CAST(:downgrade_job_id AS uuid)
                          )
                        GROUP BY version.version_num
                        """
                    ),
                    {
                        "upgrade_job_id": writer_job_id,
                        "downgrade_job_id": downgrade_writer_job_id,
                    },
                )
            ).one()
            assert revision == _PRE_REVISION
            assert writer_count == 2
    finally:
        if migration_task is not None:
            await asyncio.wait_for(
                asyncio.gather(migration_task, return_exceptions=True),
                timeout=30,
            )
        if listener_installed:
            event.remove(
                Engine,
                "before_cursor_execute",
                _capture_migration_lock_attempt,
            )
        await target_engine.dispose()
        await reader_engine.dispose()
        await writer_engine.dispose()
        async with admin_engine.connect() as connection:
            autocommit = await connection.execution_options(isolation_level="AUTOCOMMIT")
            await autocommit.execute(text(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)'))
        await admin_engine.dispose()


async def test_pipeline_projection_lock_retry_allows_cancellation_writer(
    pg_container: Any,
) -> None:
    """request → job writer가 끝날 때까지 migration은 부분 lock을 남기지 않는다."""
    admin_dsn = normalize_async_dsn(pg_container.get_connection_url())
    database = f"pipeline_projection_lock_order_{uuid4().hex}"
    target_dsn = make_url(admin_dsn).set(database=database).render_as_string(hide_password=False)
    admin_engine = make_async_engine(admin_dsn)
    async with admin_engine.connect() as connection:
        autocommit = await connection.execution_options(isolation_level="AUTOCOMMIT")
        await autocommit.execute(text(f'CREATE DATABASE "{database}"'))

    request_id = "f1000000-0000-4000-8000-000000000001"
    job_id = "f2000000-0000-4000-8000-000000000002"
    target_engine = make_async_engine(target_dsn)
    observer_engine = make_async_engine(target_dsn)
    writer_engine = make_async_engine(target_dsn)
    migration_retried = ThreadEvent()
    migration_backend_pid: list[int] = []
    migration_lock_attempts: list[int] = []
    migration_task: asyncio.Task[None] | None = None
    listener_installed = False

    def _capture_migration_lock_attempt(
        connection: Any,
        _cursor: Any,
        statement: str,
        _parameters: Any,
        _context: Any,
        _executemany: bool,
    ) -> None:
        if connection.engine.url.database != database:
            return
        normalized = " ".join(statement.lower().replace('"', "").split())
        if normalized not in {
            _EXPECTED_IDENTITY_LOCK_SQL,
            _EXPECTED_IDENTITY_LOCK_SQL_WITH_CLOCK,
        }:
            return
        driver_connection = connection.connection.driver_connection
        backend_pid = (
            driver_connection.get_server_pid()
            if hasattr(driver_connection, "get_server_pid")
            else driver_connection.info.backend_pid
        )
        migration_backend_pid[:] = [int(backend_pid)]
        migration_lock_attempts.append(1)
        if len(migration_lock_attempts) >= 2:
            migration_retried.set()

    try:
        await asyncio.to_thread(_run_alembic, target_dsn, _PRE_REVISION)
        async with target_engine.begin() as connection:
            await connection.execute(
                text(
                    """
                    INSERT INTO ops.import_jobs (
                      job_id, kind, payload, status, provider, dataset_key,
                      trigger_kind
                    ) VALUES (
                      :job_id, 'feature_update_request', '{}'::jsonb, 'queued',
                      'lock-provider', 'lock-dataset', 'update_request'
                    )
                    """
                ),
                {"job_id": job_id},
            )
            await connection.execute(
                text(
                    """
                    INSERT INTO ops.feature_update_requests (
                      request_id, scope_type, scope, run_mode, status, job_id
                    ) VALUES (
                      :request_id, 'provider_dataset',
                      jsonb_build_object(
                        'type', 'provider_dataset',
                        'provider', 'lock-provider',
                        'dataset_key', 'lock-dataset'
                      ),
                      'queued', 'queued', :job_id
                    )
                    """
                ),
                {"request_id": request_id, "job_id": job_id},
            )
        await target_engine.dispose()

        event.listen(Engine, "before_cursor_execute", _capture_migration_lock_attempt)
        listener_installed = True

        async with writer_engine.begin() as writer:
            await writer.execute(text("SET LOCAL lock_timeout = '5s'"))
            cancellation_id = "f3000000-0000-4000-8000-000000000003"
            await writer.execute(
                text(
                    """
                    INSERT INTO ops.pipeline_cancellations (
                      cancellation_id, root_kind, root_id, requested_by
                    ) VALUES (
                      :cancellation_id, 'update_request', :request_id,
                      'migration-lock-test'
                    )
                    """
                ),
                {"cancellation_id": cancellation_id, "request_id": request_id},
            )
            await writer.execute(
                text(
                    """
                    INSERT INTO ops.pipeline_cancellation_members (
                      cancellation_id, member_kind, member_id,
                      initial_status, result
                    ) VALUES (
                      :cancellation_id, 'import_job', :job_id,
                      'queued', 'pending'
                    )
                    """
                ),
                {"cancellation_id": cancellation_id, "job_id": job_id},
            )
            await writer.execute(
                text(
                    "SELECT cancellation_id FROM ops.pipeline_cancellations "
                    "WHERE cancellation_id = :cancellation_id FOR UPDATE"
                ),
                {"cancellation_id": cancellation_id},
            )

            migration_task = asyncio.create_task(
                asyncio.to_thread(_run_alembic, target_dsn, _TARGET_REVISION)
            )
            assert await asyncio.to_thread(migration_retried.wait, 10)
            assert migration_backend_pid
            assert len(migration_lock_attempts) >= 2
            assert migration_task is not None
            assert not migration_task.done()

            job_rows = (
                await writer.execute(
                    text(
                        "SELECT member_id FROM ops.pipeline_cancellation_members "
                        "WHERE member_kind = 'import_job' "
                        "AND member_id = CAST(:job_id AS uuid) FOR UPDATE"
                    ),
                    {"job_id": job_id},
                )
            ).all()
            assert [str(row.member_id) for row in job_rows] == [job_id]

        assert migration_task is not None
        await asyncio.wait_for(migration_task, timeout=30)
        async with observer_engine.connect() as connection:
            revision = (
                await connection.execute(text("SELECT version_num FROM alembic_version"))
            ).scalar_one()
            assert revision == _TARGET_REVISION
    finally:
        if migration_task is not None:
            await asyncio.wait_for(
                asyncio.gather(migration_task, return_exceptions=True),
                timeout=30,
            )
        if listener_installed:
            event.remove(
                Engine,
                "before_cursor_execute",
                _capture_migration_lock_attempt,
            )
        await target_engine.dispose()
        await observer_engine.dispose()
        await writer_engine.dispose()
        async with admin_engine.connect() as connection:
            autocommit = await connection.execution_options(isolation_level="AUTOCOMMIT")
            await autocommit.execute(text(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)'))
        await admin_engine.dispose()


async def test_pipeline_projection_lock_retry_allows_enqueue_writer(
    pg_container: Any,
) -> None:
    """job → request enqueue writer가 끝날 때까지 migration은 부분 lock을 남기지 않는다."""
    admin_dsn = normalize_async_dsn(pg_container.get_connection_url())
    database = f"pipeline_projection_enqueue_lock_{uuid4().hex}"
    target_dsn = make_url(admin_dsn).set(database=database).render_as_string(hide_password=False)
    admin_engine = make_async_engine(admin_dsn)
    async with admin_engine.connect() as connection:
        autocommit = await connection.execution_options(isolation_level="AUTOCOMMIT")
        await autocommit.execute(text(f'CREATE DATABASE "{database}"'))

    request_id = "fa000000-0000-4000-8000-000000000001"
    job_id = "fb000000-0000-4000-8000-000000000002"
    target_engine = make_async_engine(target_dsn)
    writer_engine = make_async_engine(target_dsn)
    migration_retried = ThreadEvent()
    migration_lock_attempts: list[int] = []
    migration_task: asyncio.Task[None] | None = None
    listener_installed = False

    def _capture_migration_lock_attempt(
        connection: Any,
        _cursor: Any,
        statement: str,
        _parameters: Any,
        _context: Any,
        _executemany: bool,
    ) -> None:
        if connection.engine.url.database != database:
            return
        normalized = " ".join(statement.lower().replace('"', "").split())
        if normalized not in {
            _EXPECTED_IDENTITY_LOCK_SQL,
            _EXPECTED_IDENTITY_LOCK_SQL_WITH_CLOCK,
        }:
            return
        migration_lock_attempts.append(1)
        if len(migration_lock_attempts) >= 2:
            migration_retried.set()

    try:
        await asyncio.to_thread(_run_alembic, target_dsn, _PRE_REVISION)
        await target_engine.dispose()
        event.listen(Engine, "before_cursor_execute", _capture_migration_lock_attempt)
        listener_installed = True

        async with writer_engine.begin() as writer:
            await writer.execute(text("SET LOCAL lock_timeout = '5s'"))
            await writer.execute(
                text(
                    """
                    INSERT INTO ops.import_jobs (
                      job_id, kind, payload, status, provider, dataset_key,
                      trigger_kind
                    ) VALUES (
                      :job_id, 'feature_update_request', '{}'::jsonb, 'queued',
                      'enqueue-provider', 'enqueue-dataset', 'update_request'
                    )
                    """
                ),
                {"job_id": job_id},
            )

            migration_task = asyncio.create_task(
                asyncio.to_thread(_run_alembic, target_dsn, _TARGET_REVISION)
            )
            assert await asyncio.to_thread(migration_retried.wait, 10)
            assert len(migration_lock_attempts) >= 2
            assert migration_task is not None
            assert not migration_task.done()

            await writer.execute(
                text(
                    """
                    INSERT INTO ops.feature_update_requests (
                      request_id, scope_type, scope, run_mode, status, job_id
                    ) VALUES (
                      :request_id, 'provider_dataset',
                      jsonb_build_object(
                        'type', 'provider_dataset',
                        'provider', 'enqueue-provider',
                        'dataset_key', 'enqueue-dataset'
                      ),
                      'queued', 'queued', :job_id
                    )
                    """
                ),
                {"request_id": request_id, "job_id": job_id},
            )

        assert migration_task is not None
        await asyncio.wait_for(migration_task, timeout=30)
        target_engine = make_async_engine(target_dsn)
        async with target_engine.connect() as connection:
            revision, linked_job_id = (
                await connection.execute(
                    text(
                        """
                        SELECT version.version_num, request.job_id
                        FROM alembic_version AS version
                        CROSS JOIN ops.feature_update_requests AS request
                        WHERE request.request_id = :request_id
                        """
                    ),
                    {"request_id": request_id},
                )
            ).one()
            assert revision == _TARGET_REVISION
            assert str(linked_job_id) == job_id

        migration_lock_attempts.clear()
        migration_retried.clear()
        async with writer_engine.begin() as writer:
            await writer.execute(
                text(
                    "SELECT job_id FROM ops.import_jobs "
                    "WHERE job_id = :job_id FOR UPDATE"
                ),
                {"job_id": job_id},
            )
            migration_task = asyncio.create_task(
                asyncio.to_thread(
                    _run_alembic,
                    target_dsn,
                    _PRE_REVISION,
                    downgrade=True,
                )
            )
            assert await asyncio.to_thread(migration_retried.wait, 10)
            assert len(migration_lock_attempts) >= 2
            assert not migration_task.done()

            async with target_engine.connect() as observer:
                assert (
                    await observer.scalar(text("SELECT version_num FROM alembic_version"))
                ) == _TARGET_REVISION
                request_columns = await _request_columns(observer)
                assert "generation" in request_columns
                assert _REQUEST_LIFECYCLE_COLUMNS.isdisjoint(request_columns)

        await asyncio.wait_for(migration_task, timeout=30)
        async with target_engine.connect() as connection:
            revision, linked_job_id = (
                await connection.execute(
                    text(
                        """
                        SELECT version.version_num, request.job_id
                        FROM alembic_version AS version
                        CROSS JOIN ops.feature_update_requests AS request
                        WHERE request.request_id = :request_id
                        """
                    ),
                    {"request_id": request_id},
                )
            ).one()
            assert revision == _PRE_REVISION
            assert str(linked_job_id) == job_id
            request_columns = await _request_columns(connection)
            assert "generation" not in request_columns
            assert request_columns >= _REQUEST_LIFECYCLE_COLUMNS
    finally:
        if migration_task is not None:
            await asyncio.wait_for(
                asyncio.gather(migration_task, return_exceptions=True),
                timeout=30,
            )
        if listener_installed:
            event.remove(
                Engine,
                "before_cursor_execute",
                _capture_migration_lock_attempt,
            )
        await target_engine.dispose()
        await writer_engine.dispose()
        async with admin_engine.connect() as connection:
            autocommit = await connection.execution_options(isolation_level="AUTOCOMMIT")
            await autocommit.execute(text(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)'))
        await admin_engine.dispose()
