"""계층형 취소 scope/attempt/marker repository 통합 테스트 (T-ADM-C3d)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from kortravelmap.infra.feature_update_repo import (
    cancel_update_request,
    claim_next_update_request,
    finish_update_request,
    set_update_request_matched_scope,
    start_update_request,
)
from kortravelmap.infra.jobs_repo import (
    attach_import_jobs_to_batch,
    cancel_import_job,
    claim_next_import_job,
    enqueue_import_job,
    finish_import_job,
    get_import_job,
    heartbeat_import_job,
    record_import_job_event,
    recover_stale_running_jobs,
    update_import_job_payload,
)
from kortravelmap.infra.pipeline_cancellation_repo import (
    PipelineCancellationConflict,
    create_pipeline_cancellation_attempt,
    finish_pipeline_cancellation_attempt,
    get_current_pipeline_cancellation_detail,
    lock_pipeline_lineage_mutation,
    resolve_pipeline_cancellation_scope,
    retry_pipeline_cancellation_attempt,
    set_pipeline_cancellation_member_result,
    set_pipeline_cancellation_run_result,
    transition_pipeline_cancellation_member,
)
from kortravelmap.infra.pipeline_repo import list_pipeline_executions

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

pytestmark = pytest.mark.integration

_T0 = datetime(2026, 7, 15, 1, 0, tzinfo=UTC)
_ROOT = "11111111-1111-4111-8111-111111111111"
_CHILD = "22222222-2222-4222-8222-222222222222"
_GRANDCHILD = "33333333-3333-4333-8333-333333333333"
_OWNER = "44444444-4444-4444-8444-444444444444"
_LOSER = "55555555-5555-4555-8555-555555555555"

_INSERT_JOB = text(
    """
    INSERT INTO ops.import_jobs (
        job_id, kind, parent_job_id, payload, status, progress, current_stage,
        dagster_run_id, created_at, started_at, heartbeat_at
    ) VALUES (
        CAST(:job_id AS uuid), 'provider_load', CAST(:parent_job_id AS uuid),
        '{}'::jsonb, :status, :progress, :current_stage, :dagster_run_id,
        :created_at, :started_at, :heartbeat_at
    )
    """
)

_INSERT_REQUEST = text(
    """
    INSERT INTO ops.feature_update_requests (
        request_id, scope_type, scope, providers, dataset_keys, update_policy,
        run_mode, priority, status, dry_run, matched_scope, job_id,
        dagster_run_id, operator, created_at
    ) VALUES (
        CAST(:request_id AS uuid), 'feature_ids',
        '{"type":"feature_ids","feature_ids":["f-1"]}'::jsonb,
        '[]'::jsonb, '[]'::jsonb, '{}'::jsonb, 'queued', 50, :status, false,
        '{}'::jsonb, CAST(:job_id AS uuid), :dagster_run_id, 'tester', :created_at
    )
    """
)


async def _job(
    session: AsyncSession,
    job_id: str,
    *,
    parent_job_id: str | None = None,
    status: str = "queued",
    dagster_run_id: str | None = None,
    created_at: datetime = _T0,
) -> None:
    await session.execute(
        _INSERT_JOB,
        {
            "job_id": job_id,
            "parent_job_id": parent_job_id,
            "status": status,
            "progress": 20 if status == "running" else 0,
            "current_stage": "load" if status == "running" else None,
            "dagster_run_id": dagster_run_id or f"run-{job_id[:8]}",
            "created_at": created_at,
            "started_at": created_at if status == "running" else None,
            "heartbeat_at": created_at if status == "running" else None,
        },
    )


async def _request(
    session: AsyncSession,
    request_id: str,
    *,
    job_id: str | None,
    status: str = "queued",
    created_at: datetime = _T0,
) -> None:
    await session.execute(
        _INSERT_REQUEST,
        {
            "request_id": request_id,
            "status": status,
            "job_id": job_id,
            "dagster_run_id": f"request-run-{request_id[:8]}",
            "created_at": created_at,
        },
    )


async def _scope(
    session: AsyncSession,
    *,
    kind: str,
    execution_id: str,
) -> Any:
    scope = await resolve_pipeline_cancellation_scope(
        session,
        kind=kind,
        execution_id=execution_id,
    )
    assert scope is not None
    return scope


async def test_scope_matches_owner_duplicate_nested_and_standalone_boundaries(
    migrated_session: AsyncSession,
) -> None:
    await _job(migrated_session, _ROOT)
    await _job(migrated_session, _CHILD, parent_job_id=_ROOT)
    await _job(migrated_session, _GRANDCHILD, parent_job_id=_CHILD)
    await _request(migrated_session, _OWNER, job_id=_ROOT, created_at=_T0)
    await _request(
        migrated_session,
        _LOSER,
        job_id=_ROOT,
        created_at=_T0 + timedelta(minutes=1),
    )
    nested = "66666666-6666-4666-8666-666666666666"
    await _request(
        migrated_session,
        nested,
        job_id=_CHILD,
        created_at=_T0 + timedelta(minutes=2),
    )

    owner = await _scope(
        migrated_session,
        kind="update_request",
        execution_id=_OWNER,
    )
    nested_scope = await _scope(
        migrated_session,
        kind="import_job",
        execution_id=_GRANDCHILD,
    )
    loser = await _scope(
        migrated_session,
        kind="update_request",
        execution_id=_LOSER,
    )

    assert (owner.root_kind, owner.root_id) == ("update_request", _OWNER)
    assert {(item.member_kind, item.member_id) for item in owner.members} == {
        ("update_request", _OWNER),
        ("import_job", _ROOT),
    }
    assert (nested_scope.root_kind, nested_scope.root_id) == (
        "update_request",
        nested,
    )
    assert {item.member_id for item in nested_scope.members} == {
        nested,
        _CHILD,
        _GRANDCHILD,
    }
    assert [(item.member_kind, item.member_id) for item in loser.members] == [
        ("update_request", _LOSER)
    ]


async def test_attempt_freezes_marker_deduplicates_runs_and_projects_overlay(
    migrated_session: AsyncSession,
) -> None:
    await _job(migrated_session, _ROOT, status="queued", dagster_run_id="shared-run")
    await _job(
        migrated_session,
        _CHILD,
        parent_job_id=_ROOT,
        status="running",
        dagster_run_id="shared-run",
    )
    await _request(migrated_session, _OWNER, job_id=_ROOT, status="done")
    scope = await _scope(
        migrated_session,
        kind="update_request",
        execution_id=_OWNER,
    )

    detail = await create_pipeline_cancellation_attempt(
        migrated_session,
        scope=scope,
        requested_by="admin:test",
        reason="통합 테스트",
    )

    assert detail.attempt.status == "in_progress"
    assert len(detail.members) == 3
    assert {run.dagster_run_id for run in detail.runs} == {
        "shared-run",
        f"request-run-{_OWNER[:8]}",
    }
    assert next(
        item for item in detail.members if item.member_id == _OWNER
    ).result == "already_terminal"
    markers = (
        await migrated_session.execute(
            text(
                "SELECT cancellation_id FROM ops.import_jobs "
                "WHERE job_id IN (CAST(:root AS uuid), CAST(:child AS uuid))"
            ),
            {"root": _ROOT, "child": _CHILD},
        )
    ).scalars().all()
    assert {str(value) for value in markers} == {detail.attempt.cancellation_id}

    page = await list_pipeline_executions(migrated_session)
    execution = next(item for item in page.items if item.id == _OWNER)
    assert execution.status == "done"
    assert execution.cancellation is not None
    assert execution.cancellation.status == "in_progress"
    assert execution.cancellation.unresolved_member_count == 2


async def test_terminal_scope_creates_durable_completed_noop(
    migrated_session: AsyncSession,
) -> None:
    await _job(migrated_session, _ROOT, status="done")
    scope = await _scope(
        migrated_session,
        kind="import_job",
        execution_id=_ROOT,
    )

    detail = await create_pipeline_cancellation_attempt(
        migrated_session,
        scope=scope,
        requested_by="admin:test",
        reason=None,
    )

    assert detail.attempt.status == "completed"
    assert [member.result for member in detail.members] == ["already_terminal"]
    assert [run.result for run in detail.runs] == ["already_terminal"]
    assert detail.unresolved_member_count == 0


async def test_retry_copies_only_unresolved_frozen_members_without_rediscovery(
    migrated_session: AsyncSession,
) -> None:
    await _job(migrated_session, _ROOT, status="running")
    await _job(migrated_session, _CHILD, parent_job_id=_ROOT, status="running")
    first = await create_pipeline_cancellation_attempt(
        migrated_session,
        scope=await _scope(
            migrated_session,
            kind="import_job",
            execution_id=_ROOT,
        ),
        requested_by="admin:first",
        reason="첫 시도",
    )
    await set_pipeline_cancellation_member_result(
        migrated_session,
        cancellation_id=first.attempt.cancellation_id,
        member_kind="import_job",
        member_id=_ROOT,
        result="cancelled",
        terminal_status="cancelled",
        error=None,
    )
    await set_pipeline_cancellation_member_result(
        migrated_session,
        cancellation_id=first.attempt.cancellation_id,
        member_kind="import_job",
        member_id=_CHILD,
        result="cancel_failed",
        terminal_status=None,
        error={"code": "DAGSTER_UNAVAILABLE", "message": "timeout"},
    )
    await finish_pipeline_cancellation_attempt(
        migrated_session,
        cancellation_id=first.attempt.cancellation_id,
        status="retryable",
        error={"code": "DAGSTER_UNAVAILABLE", "message": "timeout"},
    )
    await _job(
        migrated_session,
        _GRANDCHILD,
        parent_job_id=_ROOT,
        status="running",
        created_at=_T0 + timedelta(minutes=1),
    )

    retried = await retry_pipeline_cancellation_attempt(
        migrated_session,
        previous_cancellation_id=first.attempt.cancellation_id,
        requested_by="admin:retry",
        reason="재시도",
    )

    assert retried.attempt.previous_cancellation_id == first.attempt.cancellation_id
    assert [(member.member_kind, member.member_id) for member in retried.members] == [
        ("import_job", _CHILD)
    ]
    assert _GRANDCHILD not in {member.member_id for member in retried.members}
    assert retried.runs[0].dagster_run_id == f"run-{_CHILD[:8]}"


async def test_marked_rows_reject_mutators_but_allow_events(
    migrated_session: AsyncSession,
) -> None:
    await _job(migrated_session, _ROOT, status="queued")
    await _job(migrated_session, _CHILD, parent_job_id=_ROOT, status="running")
    await _request(migrated_session, _OWNER, job_id=_ROOT, status="queued")
    await create_pipeline_cancellation_attempt(
        migrated_session,
        scope=await _scope(
            migrated_session,
            kind="update_request",
            execution_id=_OWNER,
        ),
        requested_by="admin:test",
        reason=None,
    )

    assert await update_import_job_payload(
        migrated_session,
        _ROOT,
        payload={"changed": True},
    ) is None
    assert await heartbeat_import_job(migrated_session, _CHILD, progress=90) is None
    assert await finish_import_job(migrated_session, _CHILD, status="done") is None
    assert await cancel_import_job(migrated_session, _ROOT) is None
    assert await recover_stale_running_jobs(migrated_session, stale_after=None) == 0
    assert await claim_next_import_job(migrated_session) is None
    assert await attach_import_jobs_to_batch(
        migrated_session,
        (_CHILD,),
        load_batch_id="77777777-7777-4777-8777-777777777777",
        parent_job_id=_ROOT,
    ) == ()
    with pytest.raises(PipelineCancellationConflict):
        await enqueue_import_job(
            migrated_session,
            kind="provider_load",
            parent_job_id=_ROOT,
        )

    assert await claim_next_update_request(migrated_session) is None
    assert await start_update_request(migrated_session, _OWNER) is None
    assert await set_update_request_matched_scope(
        migrated_session,
        _OWNER,
        matched_scope={"feature_count": 1},
    ) is None
    assert await finish_update_request(migrated_session, _OWNER) is None
    assert await cancel_update_request(migrated_session, _OWNER) is None
    event = await record_import_job_event(
        migrated_session,
        _ROOT,
        code="cancellation.observed",
        message="marker 뒤 event append",
    )
    assert event is not None


async def test_coordinator_transition_requires_exact_marker_and_run_mapping(
    migrated_session: AsyncSession,
) -> None:
    await _job(migrated_session, _ROOT, status="running", dagster_run_id="run-exact")
    detail = await create_pipeline_cancellation_attempt(
        migrated_session,
        scope=await _scope(
            migrated_session,
            kind="import_job",
            execution_id=_ROOT,
        ),
        requested_by="admin:test",
        reason=None,
    )
    cancellation_id = detail.attempt.cancellation_id

    assert await transition_pipeline_cancellation_member(
        migrated_session,
        cancellation_id=cancellation_id,
        member_kind="import_job",
        member_id=_ROOT,
        dagster_run_id="run-wrong",
        expected_status="running",
        target_status="cancelled",
        result="cancelled",
    ) is False
    assert await transition_pipeline_cancellation_member(
        migrated_session,
        cancellation_id=cancellation_id,
        member_kind="import_job",
        member_id=_ROOT,
        dagster_run_id="run-exact",
        expected_status="running",
        target_status="cancelled",
        result="cancelled",
    ) is True
    assert await set_pipeline_cancellation_run_result(
        migrated_session,
        cancellation_id=cancellation_id,
        dagster_run_id="run-exact",
        result="cancelled",
        initial_status="STARTED",
        terminal_status="CANCELED",
        error=None,
    ) is True
    completed = await finish_pipeline_cancellation_attempt(
        migrated_session,
        cancellation_id=cancellation_id,
        status="completed",
        error=None,
    )

    assert completed.attempt.status == "completed"
    assert completed.unresolved_member_count == 0
    assert (await get_import_job(migrated_session, _ROOT)).status == "cancelled"  # type: ignore[union-attr]
    current = await get_current_pipeline_cancellation_detail(
        migrated_session,
        kind="import_job",
        execution_id=_ROOT,
    )
    assert current is not None
    assert current.attempt.cancellation_id == cancellation_id


async def test_lineage_mutations_share_one_transaction_lock(
    migrated_engine: AsyncEngine,
) -> None:
    from sqlalchemy.ext.asyncio import AsyncSession

    parent_id = "88888888-8888-4888-8888-888888888888"
    async with AsyncSession(migrated_engine, expire_on_commit=False) as setup:
        async with setup.begin():
            await _job(setup, parent_id)

    async with (
        AsyncSession(migrated_engine, expire_on_commit=False) as locker,
        AsyncSession(migrated_engine, expire_on_commit=False) as writer,
    ):
        await locker.begin()
        await lock_pipeline_lineage_mutation(locker)
        await writer.begin()
        await writer.execute(text("SET LOCAL lock_timeout = '100ms'"))
        with pytest.raises(DBAPIError):
            await enqueue_import_job(
                writer,
                kind="provider_load",
                parent_job_id=parent_id,
            )
        await writer.rollback()
        await locker.rollback()

    async with AsyncSession(migrated_engine, expire_on_commit=False) as cleanup:
        async with cleanup.begin():
            await cleanup.execute(
                text("DELETE FROM ops.import_jobs WHERE job_id = CAST(:job_id AS uuid)"),
                {"job_id": parent_id},
            )
