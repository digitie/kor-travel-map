"""C3e-A1 provider feature operation frozen 계약 단위 회귀."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from kortravelmap.core.feature_operation import (
    FEATURE_OPERATION_MEMBER_KIND,
    FEATURE_OPERATION_ROOT_KIND,
    FeatureOperationInvariantConflict,
    ProviderDatasetOperationKey,
)
from kortravelmap.infra import feature_update_repo, jobs_repo
from kortravelmap.infra.feature_operation_repo import ensure_dagster_feature_operation
from kortravelmap.infra.pipeline_cancellation_types import (
    PipelineCancellationScopeMember,
)


def test_provider_dataset_key_rejects_blank_or_untrimmed_identity() -> None:
    with pytest.raises(ValueError, match="provider"):
        ProviderDatasetOperationKey(" provider", "dataset")
    with pytest.raises(ValueError, match="dataset_key"):
        ProviderDatasetOperationKey("provider", "")


@pytest.mark.parametrize(
    "kind", [FEATURE_OPERATION_ROOT_KIND, FEATURE_OPERATION_MEMBER_KIND]
)
async def test_generic_enqueue_rejects_reserved_feature_kind(kind: str) -> None:
    with pytest.raises(FeatureOperationInvariantConflict):
        await jobs_repo.enqueue_import_job(object(), kind=kind)  # type: ignore[arg-type]


def test_generic_writer_sql_excludes_reserved_feature_kinds() -> None:
    lifecycle_sql = (
        jobs_repo._UPDATE_PAYLOAD_SQL,
        jobs_repo._ATTACH_BATCH_SQL,
        jobs_repo._CLAIM_JOB_SQL,
        jobs_repo._HEARTBEAT_SQL,
        jobs_repo._FINISH_SQL,
        jobs_repo._CANCEL_SQL,
        jobs_repo._RECOVER_STALE_SQL,
        feature_update_repo._START_IMPORT_JOB_SQL,
        feature_update_repo._FINISH_IMPORT_JOB_SQL,
        feature_update_repo._REQUEUE_IMPORT_JOB_SQL,
    )
    assert all("provider_feature_load_run" in statement for statement in lifecycle_sql)
    assert all("provider_feature_load" in statement for statement in lifecycle_sql)


def test_run_backed_queued_scope_member_requires_dagster_termination() -> None:
    member = PipelineCancellationScopeMember(
        member_kind="import_job",
        member_id="11111111-1111-4111-8111-111111111111",
        initial_status="queued",
        dagster_run_id="run-1",
        cancellation_id=None,
        operation_kind=FEATURE_OPERATION_ROOT_KIND,
    )
    generic = PipelineCancellationScopeMember(
        member_kind="import_job",
        member_id="22222222-2222-4222-8222-222222222222",
        initial_status="queued",
        dagster_run_id="run-2",
        cancellation_id=None,
        operation_kind="offline_upload_load",
    )

    assert member.requires_run_termination is True
    assert generic.requires_run_termination is False


def test_reconcile_cursor_is_engine_time_ordered() -> None:
    from kortravelmap.core.feature_operation import DagsterFeatureOperationCursor

    earlier = DagsterFeatureOperationCursor(
        created_at=datetime(2026, 7, 15, 1, tzinfo=UTC),
        root_job_id="11111111-1111-4111-8111-111111111111",
    )
    later = DagsterFeatureOperationCursor(
        created_at=datetime(2026, 7, 15, 2, tzinfo=UTC),
        root_job_id="00000000-0000-4000-8000-000000000000",
    )
    assert earlier < later


@pytest.mark.asyncio
async def test_invalid_engine_time_fails_before_any_db_write() -> None:
    created_at = datetime(2026, 7, 15, 2, tzinfo=UTC)
    with pytest.raises(FeatureOperationInvariantConflict, match="precedes create"):
        await ensure_dagster_feature_operation(
            object(),  # type: ignore[arg-type]
            dagster_run_id="run-invalid-time",
            trigger_kind="manual",
            selected_pairs=(ProviderDatasetOperationKey("provider", "dataset"),),
            registry_version="registry-v1",
            engine_created_at=created_at,
            engine_started_at=datetime(2026, 7, 15, 1, tzinfo=UTC),
            observed_status="STARTED",
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("run_id", ["", " run", "run "])
async def test_generic_writer_rejects_blank_or_untrimmed_run_id(run_id: str) -> None:
    with pytest.raises(ValueError, match="trimmed and non-empty"):
        await jobs_repo.enqueue_import_job(
            object(),  # type: ignore[arg-type]
            kind="generic",
            dagster_run_id=run_id,
        )
