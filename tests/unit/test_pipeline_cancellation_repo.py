"""계층형 취소 repository의 정적 계약 단위 테스트 (T-ADM-C3d)."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from kortravelmap.core.pipeline_cancellation_states import (
    PIPELINE_CANCELLATION_MEMBER_KIND_VALUES,
    PIPELINE_CANCELLATION_RESULT_VALUES,
    PIPELINE_CANCELLATION_STATUS_VALUES,
)
from kortravelmap.infra import feature_update_repo, jobs_repo, pipeline_repo
from kortravelmap.infra.pipeline_cancellation_repo import (
    PipelineCancellationAttempt,
)
from kortravelmap.infra.pipeline_lineage import PIPELINE_LINEAGE_CTES_SQL


def test_cancellation_literals_keep_workflow_and_result_namespaces_separate() -> None:
    assert PIPELINE_CANCELLATION_STATUS_VALUES == (
        "in_progress",
        "retryable",
        "completed",
        "failed",
    )
    assert PIPELINE_CANCELLATION_RESULT_VALUES == (
        "pending",
        "cancelled",
        "already_terminal",
        "cancel_failed",
    )
    assert PIPELINE_CANCELLATION_MEMBER_KIND_VALUES == (
        "import_job",
        "update_request",
    )
    assert set(PIPELINE_CANCELLATION_STATUS_VALUES).isdisjoint(
        {"cancelled", "already_terminal", "cancel_failed"}
    )


def test_attempt_retryable_is_derived_only_from_workflow_status() -> None:
    at = datetime(2026, 7, 15, tzinfo=UTC)
    attempt = PipelineCancellationAttempt(
        cancellation_id="11111111-1111-4111-8111-111111111111",
        previous_cancellation_id=None,
        root_kind="import_job",
        root_id="22222222-2222-4222-8222-222222222222",
        status="retryable",
        requested_by="admin:test",
        reason=None,
        error=None,
        requested_at=at,
        updated_at=at,
        finished_at=at,
    )

    assert attempt.retryable is True


def test_pipeline_list_and_cancellation_resolver_share_lineage_cte() -> None:
    from kortravelmap.infra import pipeline_cancellation_repo

    assert PIPELINE_LINEAGE_CTES_SQL in pipeline_repo._LIST_EXECUTIONS_SQL
    assert PIPELINE_LINEAGE_CTES_SQL in pipeline_cancellation_repo._RESOLVE_SCOPE_SQL
    assert "payload" not in PIPELINE_LINEAGE_CTES_SQL


def test_import_job_mutator_inventory_has_marker_guards() -> None:
    guarded_sql = (
        jobs_repo._UPDATE_PAYLOAD_SQL,
        jobs_repo._ATTACH_BATCH_SQL,
        jobs_repo._CLAIM_JOB_SQL,
        jobs_repo._HEARTBEAT_SQL,
        jobs_repo._FINISH_SQL,
        jobs_repo._CANCEL_SQL,
        jobs_repo._RECOVER_STALE_SQL,
    )
    assert all("cancellation_id" in sql for sql in guarded_sql)
    assert "parent.cancellation_id IS NULL" in jobs_repo._INSERT_JOB_SQL
    assert "parent.cancellation_id IS NULL" in jobs_repo._START_JOB_SQL
    assert "cancellation_id" not in jobs_repo._INSERT_EVENT_SQL


def test_feature_update_mutator_inventory_has_marker_guards() -> None:
    request_sql = (
        feature_update_repo._CLAIM_REQUEST_SQL,
        feature_update_repo._START_REQUEST_SQL,
        feature_update_repo._SET_MATCHED_SCOPE_SQL,
        feature_update_repo._FINISH_REQUEST_SQL,
    )
    job_sql = (
        feature_update_repo._START_IMPORT_JOB_SQL,
        feature_update_repo._FINISH_IMPORT_JOB_SQL,
    )
    assert all("cancellation_id IS NULL" in sql for sql in (*request_sql, *job_sql))
    assert "cancellation_id IS NULL" in feature_update_repo._PEEK_REQUEST_SQL
    assert "job.cancellation_id IS NULL" in feature_update_repo._INSERT_REQUEST_SQL


def test_pipeline_mapper_keeps_base_status_and_adds_nullable_overlay() -> None:
    at = datetime(2026, 7, 15, tzinfo=UTC)
    row = SimpleNamespace(
        kind="import_job",
        id="11111111-1111-4111-8111-111111111111",
        status="running",
        created_at=at,
        providers=[],
        dataset_keys=[],
        scope_provider=None,
        scope_dataset=None,
        scope_sync_scope=None,
        progress=10,
        current_stage="load",
        scope_type=None,
        priority=None,
        run_mode=None,
        operator=None,
        error_message=None,
        started_at=at,
        finished_at=None,
        dagster_run_id="run-1",
        requested_job_id=None,
        lineage_owner=None,
        linked_job_count=1,
        projected_job_id=None,
        cancellation_id="22222222-2222-4222-8222-222222222222",
        cancellation_status="retryable",
        cancellation_requested_at=at,
        cancellation_requested_by="admin:test",
        cancellation_reason="운영자 요청",
        cancellation_retryable=True,
        cancellation_unresolved_member_count=1,
    )

    execution = pipeline_repo._row_to_execution(row)

    assert execution.status == "running"
    assert execution.cancellation is not None
    assert execution.cancellation.status == "retryable"
    assert execution.cancellation.unresolved_member_count == 1

    row.cancellation_id = None
    assert pipeline_repo._row_to_execution(row).cancellation is None
