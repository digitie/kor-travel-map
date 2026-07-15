"""계층형 취소 scope/attempt/marker repository 통합 테스트 (T-ADM-C3d)."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

from kortravelmap.infra.feature_update_repo import (
    finish_update_request,
    set_update_request_matched_scope,
    start_update_request,
)
from kortravelmap.infra.jobs_repo import (
    attach_import_jobs_to_batch,
    cancel_import_job,
    claim_next_import_job,
    enqueue_unpaired_import_job,
    finish_import_job,
    get_import_job,
    heartbeat_import_job,
    record_import_job_event,
    recover_stale_running_jobs,
    update_import_job_payload,
)
from kortravelmap.infra.pipeline_cancellation_repo import (
    PipelineCancellationConflict,
    PipelineCancellationInvariantError,
    cancel_queued_pipeline_cancellation_member,
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
    from collections.abc import AsyncIterator

    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

pytestmark = pytest.mark.integration

_T0 = datetime(2026, 7, 15, 1, 0, tzinfo=UTC)
_ROOT = "11111111-1111-4111-8111-111111111111"
_CHILD = "22222222-2222-4222-8222-222222222222"
_GRANDCHILD = "33333333-3333-4333-8333-333333333333"
_OWNER = "44444444-4444-4444-8444-444444444444"
_LOSER = "55555555-5555-4555-8555-555555555555"


@pytest.fixture(autouse=True)
async def _cleanup_committed_cancellation_state(
    migrated_engine: AsyncEngine,
) -> AsyncIterator[None]:
    """경쟁 테스트의 전용 session commit을 모듈 테스트 뒤 제거한다."""
    from sqlalchemy.ext.asyncio import AsyncSession

    async with AsyncSession(migrated_engine) as snapshot:
        job_ids = set(
            await snapshot.scalars(text("SELECT job_id FROM ops.import_jobs"))
        )
        cancellation_ids = set(
            await snapshot.scalars(
                text("SELECT cancellation_id FROM ops.pipeline_cancellations")
            )
        )
    try:
        yield
    finally:
        async with AsyncSession(migrated_engine) as cleanup, cleanup.begin():
            new_ids = tuple(
                str(value)
                for value in await cleanup.scalars(
                    text(
                        "SELECT cancellation_id FROM ops.pipeline_cancellations "
                        "WHERE cancellation_id <> ALL(CAST(:ids AS uuid[])) "
                        "ORDER BY requested_at DESC, cancellation_id DESC"
                    ),
                    {"ids": list(cancellation_ids)},
                )
            )
            if new_ids:
                await cleanup.execute(
                    text(
                        "DELETE FROM ops.pipeline_cancellation_members "
                        "WHERE cancellation_id = ANY(CAST(:ids AS uuid[]))"
                    ),
                    {"ids": list(new_ids)},
                )
                await cleanup.execute(
                    text(
                        "DELETE FROM ops.pipeline_cancellation_runs "
                        "WHERE cancellation_id = ANY(CAST(:ids AS uuid[]))"
                    ),
                    {"ids": list(new_ids)},
                )
                await cleanup.execute(
                    text(
                        "UPDATE ops.import_jobs SET cancellation_id = NULL, "
                        "cancellation_requested_at = NULL, "
                        "cancellation_requested_by = NULL, cancellation_reason = NULL "
                        "WHERE cancellation_id = ANY(CAST(:ids AS uuid[]))"
                    ),
                    {"ids": list(new_ids)},
                )
            await cleanup.execute(
                text(
                    "DELETE FROM ops.import_job_events "
                    "WHERE job_id <> ALL(CAST(:job_ids AS uuid[]))"
                ),
                {"job_ids": list(job_ids)},
            )
            await cleanup.execute(
                text(
                    "DELETE FROM ops.import_jobs "
                    "WHERE job_id <> ALL(CAST(:job_ids AS uuid[]))"
                ),
                {"job_ids": list(job_ids)},
            )
            if new_ids:
                await cleanup.execute(
                    text(
                        "DELETE FROM ops.pipeline_cancellations "
                        "WHERE cancellation_id = ANY(CAST(:ids AS uuid[]))"
                    ),
                    {"ids": list(new_ids)},
                )

_INSERT_JOB = text(
    """
    INSERT INTO ops.import_jobs (
        job_id, kind, parent_job_id, payload, status, progress, current_stage,
        dagster_run_id, created_at, started_at, heartbeat_at, trigger_kind
    ) VALUES (
        CAST(:job_id AS uuid), :kind, CAST(:parent_job_id AS uuid),
        '{}'::jsonb, :status, :progress, :current_stage, :dagster_run_id,
        :created_at, :started_at, :heartbeat_at, :trigger_kind
    )
    """
)

_INSERT_REQUEST = text(
    """
    INSERT INTO ops.feature_update_requests (
        request_id, scope_type, scope, providers, dataset_keys, update_policy,
        run_mode, priority, matched_scope, job_id, operator, created_at
    ) VALUES (
        CAST(:request_id AS uuid), 'feature_ids',
        '{"type":"feature_ids","feature_ids":["f-1"]}'::jsonb,
        '{}'::text[], '{}'::text[], '{}'::jsonb, 'queued', 50,
        '{}'::jsonb, CAST(:job_id AS uuid), 'tester', :created_at
    )
    """
)


async def _job(
    session: AsyncSession,
    job_id: str,
    *,
    kind: str = "provider_load",
    parent_job_id: str | None = None,
    status: str = "queued",
    dagster_run_id: str | None = None,
    created_at: datetime = _T0,
) -> None:
    await session.execute(
        _INSERT_JOB,
        {
            "job_id": job_id,
            "kind": kind,
            "parent_job_id": parent_job_id,
            "status": status,
            "progress": 20 if status == "running" else 0,
            "current_stage": "load" if status == "running" else None,
            "dagster_run_id": (
                dagster_run_id
                if dagster_run_id is not None
                else (
                    None
                    if kind == "feature_update_request" and status == "queued"
                    else f"run-{job_id[:8]}"
                )
            ),
            "created_at": created_at,
            "started_at": created_at if status == "running" else None,
            "heartbeat_at": created_at if status == "running" else None,
            "trigger_kind": "update_request" if kind == "feature_update_request" else None,
        },
    )


async def _request(
    session: AsyncSession,
    request_id: str,
    *,
    job_id: str,
    created_at: datetime = _T0,
) -> None:
    await session.execute(
        _INSERT_REQUEST,
        {
            "request_id": request_id,
            "job_id": job_id,
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


async def _force_member_failure(
    session: AsyncSession,
    *,
    cancellation_id: str,
    job_id: str,
    error: dict[str, str],
) -> None:
    """finish 방어를 검증하기 위해 setter를 우회한 normalized failure fixture."""
    await session.execute(
        text(
            "UPDATE ops.pipeline_cancellation_members "
            "SET result='cancel_failed', terminal_status=NULL, "
            "error=CAST(:error AS jsonb) "
            "WHERE cancellation_id=CAST(:cancellation_id AS uuid) "
            "AND job_id=CAST(:job_id AS uuid)"
        ),
        {
            "cancellation_id": cancellation_id,
            "job_id": job_id,
            "error": json.dumps(error),
        },
    )


async def test_scope_matches_canonical_request_and_standalone_boundaries(
    migrated_session: AsyncSession,
) -> None:
    await _job(migrated_session, _ROOT, kind="feature_update_request")
    await _job(migrated_session, _CHILD, parent_job_id=_ROOT)
    await _job(migrated_session, _GRANDCHILD, parent_job_id=_CHILD)
    await _request(migrated_session, _OWNER, job_id=_ROOT, created_at=_T0)
    await _job(migrated_session, _LOSER)

    owner = await _scope(
        migrated_session,
        kind="update_request",
        execution_id=_OWNER,
    )
    child_scope = await _scope(
        migrated_session,
        kind="import_job",
        execution_id=_GRANDCHILD,
    )
    standalone = await _scope(
        migrated_session,
        kind="import_job",
        execution_id=_LOSER,
    )

    assert (owner.root_kind, owner.root_id) == ("update_request", _OWNER)
    assert {item.job_id for item in owner.members} == {
        _ROOT,
        _CHILD,
        _GRANDCHILD,
    }
    assert (child_scope.root_kind, child_scope.root_id) == ("update_request", _OWNER)
    assert {item.job_id for item in child_scope.members} == {
        _ROOT,
        _CHILD,
        _GRANDCHILD,
    }
    assert [item.job_id for item in standalone.members] == [_LOSER]


async def test_scope_and_execution_projection_share_standalone_cycle_self_root_rules(
    migrated_session: AsyncSession,
) -> None:
    await _job(migrated_session, _ROOT)
    await _job(migrated_session, _CHILD, parent_job_id=_ROOT)
    standalone = await _scope(
        migrated_session,
        kind="import_job",
        execution_id=_CHILD,
    )
    page = await list_pipeline_executions(migrated_session)
    projected = next(item for item in page.items if item.id == _ROOT)
    assert (standalone.root_id, len(standalone.members)) == (
        projected.id,
        projected.linked_job_count,
    )

    await migrated_session.execute(
        text("DELETE FROM ops.import_jobs WHERE job_id = CAST(:job_id AS uuid)"),
        {"job_id": _ROOT},
    )
    self_root = await _scope(
        migrated_session,
        kind="import_job",
        execution_id=_CHILD,
    )
    assert (self_root.root_kind, self_root.root_id) == ("import_job", _CHILD)
    page = await list_pipeline_executions(migrated_session)
    self_root_projection = next(item for item in page.items if item.id == _CHILD)
    assert self_root_projection.linked_job_count == len(self_root.members) == 1

    await _job(migrated_session, _GRANDCHILD)
    await _job(migrated_session, _LOSER)
    await migrated_session.execute(
        text(
            "UPDATE ops.import_jobs SET parent_job_id = CASE "
            "WHEN job_id = CAST(:first AS uuid) THEN CAST(:second AS uuid) "
            "ELSE CAST(:first AS uuid) END "
            "WHERE job_id IN (CAST(:first AS uuid), CAST(:second AS uuid))"
        ),
        {"first": _GRANDCHILD, "second": _LOSER},
    )
    cycle = await _scope(
        migrated_session,
        kind="import_job",
        execution_id=_LOSER,
    )
    page = await list_pipeline_executions(migrated_session)
    cycle_projection = next(item for item in page.items if item.id == _GRANDCHILD)
    assert cycle.root_id == cycle_projection.id == _GRANDCHILD
    assert len(cycle.members) == cycle_projection.linked_job_count == 2


@pytest.mark.parametrize("start_id", [_GRANDCHILD, _LOSER])
async def test_cycle_scope_has_identical_canonical_root_from_both_start_nodes(
    migrated_session: AsyncSession,
    start_id: str,
) -> None:
    await _job(migrated_session, _GRANDCHILD)
    await _job(migrated_session, _LOSER)
    await migrated_session.execute(
        text(
            "UPDATE ops.import_jobs SET parent_job_id = CASE "
            "WHEN job_id = CAST(:first AS uuid) THEN CAST(:second AS uuid) "
            "ELSE CAST(:first AS uuid) END "
            "WHERE job_id IN (CAST(:first AS uuid), CAST(:second AS uuid))"
        ),
        {"first": _GRANDCHILD, "second": _LOSER},
    )

    cycle = await _scope(
        migrated_session,
        kind="import_job",
        execution_id=start_id,
    )

    assert (cycle.root_kind, cycle.root_id) == ("import_job", _GRANDCHILD)
    assert {member.job_id for member in cycle.members} == {_GRANDCHILD, _LOSER}


async def test_attempt_freezes_marker_deduplicates_runs_and_projects_overlay(
    migrated_session: AsyncSession,
) -> None:
    await _job(
        migrated_session,
        _ROOT,
        kind="feature_update_request",
        status="queued",
        dagster_run_id="shared-run",
    )
    await _job(
        migrated_session,
        _CHILD,
        parent_job_id=_ROOT,
        status="running",
        dagster_run_id="shared-run",
    )
    await _request(migrated_session, _OWNER, job_id=_ROOT)
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
    assert len(detail.members) == 2
    assert {run.dagster_run_id for run in detail.runs} == {"shared-run"}
    assert next(
        run for run in detail.runs if run.dagster_run_id == "shared-run"
    ).result == "pending"
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
    assert execution.status == "queued"
    assert execution.cancellation is not None
    assert execution.cancellation.status == "in_progress"
    assert execution.cancellation.unresolved_member_count == 2
    assert await set_pipeline_cancellation_run_result(
        migrated_session,
        cancellation_id=detail.attempt.cancellation_id,
        dagster_run_id="shared-run",
        result="cancelled",
        initial_status="STARTED",
        terminal_status="CANCELED",
        error=None,
    ) is True
    assert await transition_pipeline_cancellation_member(
        migrated_session,
        cancellation_id=detail.attempt.cancellation_id,
        job_id=_CHILD,
        dagster_run_id="shared-run",
        expected_status="running",
        target_status="cancelled",
        result="cancelled",
    ) is True
    assert await cancel_queued_pipeline_cancellation_member(
        migrated_session,
        cancellation_id=detail.attempt.cancellation_id,
        job_id=_ROOT,
    ) is True
    assert await finish_pipeline_cancellation_attempt(
        migrated_session,
        cancellation_id=detail.attempt.cancellation_id,
        status="completed",
        error=None,
    ) is not None


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
    await set_pipeline_cancellation_run_result(
        migrated_session,
        cancellation_id=first.attempt.cancellation_id,
        dagster_run_id=f"run-{_ROOT[:8]}",
        result="cancelled",
        initial_status="STARTED",
        terminal_status="CANCELED",
        error=None,
    )
    await transition_pipeline_cancellation_member(
        migrated_session,
        cancellation_id=first.attempt.cancellation_id,
        job_id=_ROOT,
        dagster_run_id=f"run-{_ROOT[:8]}",
        expected_status="running",
        target_status="cancelled",
        result="cancelled",
    )
    await set_pipeline_cancellation_run_result(
        migrated_session,
        cancellation_id=first.attempt.cancellation_id,
        dagster_run_id=f"run-{_CHILD[:8]}",
        result="cancel_failed",
        initial_status="STARTED",
        terminal_status=None,
        error={"code": "DAGSTER_UNAVAILABLE", "message": "timeout"},
    )
    await set_pipeline_cancellation_member_result(
        migrated_session,
        cancellation_id=first.attempt.cancellation_id,
        job_id=_CHILD,
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
    assert [member.job_id for member in retried.members] == [_CHILD]
    assert _GRANDCHILD not in {member.job_id for member in retried.members}
    assert retried.runs[0].dagster_run_id == f"run-{_CHILD[:8]}"


async def test_marked_rows_reject_mutators_but_allow_events(
    migrated_session: AsyncSession,
) -> None:
    await _job(
        migrated_session,
        _ROOT,
        kind="feature_update_request",
        status="queued",
    )
    await _job(migrated_session, _CHILD, parent_job_id=_ROOT, status="running")
    await _request(migrated_session, _OWNER, job_id=_ROOT)
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
        await enqueue_unpaired_import_job(
            migrated_session,
            kind="provider_load",
            parent_job_id=_ROOT,
        )

    assert (
        await start_update_request(
            migrated_session,
            _OWNER,
            dagster_run_id="run-marked-request",
            expected_generation=1,
        )
        is None
    )
    assert await set_update_request_matched_scope(
        migrated_session,
        _OWNER,
        matched_scope={"feature_count": 1},
        expected_generation=1,
        owner_dagster_run_id="run-marked-request",
    ) is None
    assert (
        await finish_update_request(
            migrated_session,
            _OWNER,
            owner_dagster_run_id="run-marked-request",
            expected_generation=1,
        )
        is None
    )
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

    with pytest.raises(PipelineCancellationConflict):
        await transition_pipeline_cancellation_member(
            migrated_session,
            cancellation_id=cancellation_id,
            job_id=_ROOT,
            dagster_run_id="run-wrong",
            expected_status="running",
            target_status="cancelled",
            result="cancelled",
        )
    with pytest.raises(PipelineCancellationInvariantError):
        await transition_pipeline_cancellation_member(
            migrated_session,
            cancellation_id=cancellation_id,
            job_id=_ROOT,
            dagster_run_id="run-exact",
            expected_status="running",
            target_status="cancelled",
            result="cancelled",
        )
    assert await set_pipeline_cancellation_run_result(
        migrated_session,
        cancellation_id=cancellation_id,
        dagster_run_id="run-exact",
        result="cancelled",
        initial_status="STARTED",
        terminal_status="CANCELED",
        error=None,
    ) is True
    assert await transition_pipeline_cancellation_member(
        migrated_session,
        cancellation_id=cancellation_id,
        job_id=_ROOT,
        dagster_run_id="run-exact",
        expected_status="running",
        target_status="cancelled",
        result="cancelled",
    ) is True
    completed = await finish_pipeline_cancellation_attempt(
        migrated_session,
        cancellation_id=cancellation_id,
        status="completed",
        error=None,
    )

    assert completed is not None
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
    assert [(member.result, member.terminal_status) for member in current.members] == [
        ("cancelled", "cancelled")
    ]
    assert [(run.result, run.terminal_status) for run in current.runs] == [
        ("cancelled", "CANCELED")
    ]


async def test_member_success_setter_is_forbidden_and_closed_attempt_is_immutable(
    migrated_session: AsyncSession,
) -> None:
    await _job(migrated_session, _ROOT, status="running", dagster_run_id="run-guard")
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
    with pytest.raises(ValueError, match="only accepts cancel_failed"):
        await set_pipeline_cancellation_member_result(
            migrated_session,
            cancellation_id=detail.attempt.cancellation_id,
            job_id=_ROOT,
            result="cancelled",
            terminal_status="cancelled",
            error=None,
        )
    await set_pipeline_cancellation_run_result(
        migrated_session,
        cancellation_id=detail.attempt.cancellation_id,
        dagster_run_id="run-guard",
        result="cancelled",
        initial_status="STARTED",
        terminal_status="CANCELED",
        error=None,
    )
    await transition_pipeline_cancellation_member(
        migrated_session,
        cancellation_id=detail.attempt.cancellation_id,
        job_id=_ROOT,
        dagster_run_id="run-guard",
        expected_status="running",
        target_status="cancelled",
        result="cancelled",
    )
    assert await finish_pipeline_cancellation_attempt(
        migrated_session,
        cancellation_id=detail.attempt.cancellation_id,
        status="completed",
        error=None,
    ) is not None
    assert await set_pipeline_cancellation_run_result(
        migrated_session,
        cancellation_id=detail.attempt.cancellation_id,
        dagster_run_id="run-guard",
        result="cancelled",
        initial_status="STARTED",
        terminal_status="CANCELED",
        error=None,
    ) is False


async def test_queued_only_run_uses_explicit_no_call_path(
    migrated_session: AsyncSession,
) -> None:
    await _job(migrated_session, _ROOT, status="queued", dagster_run_id="run-queued")
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
    assert detail.runs[0].result == "already_terminal"
    assert detail.runs[0].terminal_status is None
    assert await cancel_queued_pipeline_cancellation_member(
        migrated_session,
        cancellation_id=detail.attempt.cancellation_id,
        job_id=_ROOT,
    ) is True
    assert await finish_pipeline_cancellation_attempt(
        migrated_session,
        cancellation_id=detail.attempt.cancellation_id,
        status="completed",
        error=None,
    ) is not None


async def test_queued_shared_run_cancels_immediately_and_retry_copies_running_only(
    migrated_session: AsyncSession,
) -> None:
    await _job(
        migrated_session,
        _ROOT,
        status="queued",
        dagster_run_id="run-shared-retry",
    )
    await _job(
        migrated_session,
        _CHILD,
        parent_job_id=_ROOT,
        status="running",
        dagster_run_id="run-shared-retry",
    )
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
    assert detail.runs[0].result == "pending"
    assert await cancel_queued_pipeline_cancellation_member(
        migrated_session,
        cancellation_id=detail.attempt.cancellation_id,
        job_id=_ROOT,
    ) is True
    retry_error = {"code": "DAGSTER_UNAVAILABLE", "message": "timeout"}
    assert await set_pipeline_cancellation_run_result(
        migrated_session,
        cancellation_id=detail.attempt.cancellation_id,
        dagster_run_id="run-shared-retry",
        result="cancel_failed",
        initial_status="STARTED",
        terminal_status=None,
        error=retry_error,
    ) is True
    assert await set_pipeline_cancellation_member_result(
        migrated_session,
        cancellation_id=detail.attempt.cancellation_id,
        job_id=_CHILD,
        result="cancel_failed",
        terminal_status=None,
        error=retry_error,
    ) is True
    assert await finish_pipeline_cancellation_attempt(
        migrated_session,
        cancellation_id=detail.attempt.cancellation_id,
        status="retryable",
        error=retry_error,
    ) is not None

    retried = await retry_pipeline_cancellation_attempt(
        migrated_session,
        previous_cancellation_id=detail.attempt.cancellation_id,
        requested_by="admin:retry",
        reason=None,
    )

    assert [(member.job_id, member.initial_status) for member in retried.members] == [
        (_CHILD, "running")
    ]


@pytest.mark.parametrize(
    ("dagster_terminal", "target_status"),
    [("SUCCESS", "done"), ("FAILURE", "failed")],
)
async def test_terminal_run_maps_exactly_without_mutating_base_first(
    migrated_session: AsyncSession,
    dagster_terminal: str,
    target_status: str,
) -> None:
    await _job(migrated_session, _ROOT, status="running", dagster_run_id="run-terminal")
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
    before = (
        await migrated_session.execute(
            text(
                "SELECT status, dagster_run_id, cancellation_id "
                "FROM ops.import_jobs WHERE job_id = CAST(:job_id AS uuid)"
            ),
            {"job_id": _ROOT},
        )
    ).one()
    assert await set_pipeline_cancellation_run_result(
        migrated_session,
        cancellation_id=cancellation_id,
        dagster_run_id="run-terminal",
        result="already_terminal",
        initial_status="STARTED",
        terminal_status=dagster_terminal,
        error=None,
    ) is True
    unchanged = (
        await migrated_session.execute(
            text(
                "SELECT status, dagster_run_id, cancellation_id "
                "FROM ops.import_jobs WHERE job_id = CAST(:job_id AS uuid)"
            ),
            {"job_id": _ROOT},
        )
    ).one()
    assert unchanged == before
    wrong_target = "failed" if target_status == "done" else "done"
    with pytest.raises(PipelineCancellationInvariantError):
        await transition_pipeline_cancellation_member(
            migrated_session,
            cancellation_id=cancellation_id,
            job_id=_ROOT,
            dagster_run_id="run-terminal",
            expected_status="running",
            target_status=wrong_target,
            result="already_terminal",
        )
    assert await transition_pipeline_cancellation_member(
        migrated_session,
        cancellation_id=cancellation_id,
        job_id=_ROOT,
        dagster_run_id="run-terminal",
        expected_status="running",
        target_status=target_status,
        result="already_terminal",
    ) is True
    after = await get_import_job(migrated_session, _ROOT)
    assert after is not None
    assert after.status == target_status
    assert after.cancellation_id == cancellation_id
    assert await finish_pipeline_cancellation_attempt(
        migrated_session,
        cancellation_id=cancellation_id,
        status="completed",
        error=None,
    ) is not None


async def test_run_initial_status_preserves_first_observation(
    migrated_session: AsyncSession,
) -> None:
    await _job(migrated_session, _ROOT, status="running", dagster_run_id="run-status")
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
    error = {"code": "DAGSTER_UNAVAILABLE", "message": "timeout"}
    assert await set_pipeline_cancellation_run_result(
        migrated_session,
        cancellation_id=detail.attempt.cancellation_id,
        dagster_run_id="run-status",
        result="cancel_failed",
        initial_status="STARTED",
        terminal_status=None,
        error=error,
    ) is True
    assert await set_pipeline_cancellation_run_result(
        migrated_session,
        cancellation_id=detail.attempt.cancellation_id,
        dagster_run_id="run-status",
        result="cancel_failed",
        initial_status="STOPPING",
        terminal_status=None,
        error=error,
        expected_results=("cancel_failed",),
    ) is True
    initial_status = await migrated_session.scalar(
        text(
            "SELECT initial_status FROM ops.pipeline_cancellation_runs "
            "WHERE cancellation_id = CAST(:cancellation_id AS uuid) "
            "AND dagster_run_id = 'run-status'"
        ),
        {"cancellation_id": detail.attempt.cancellation_id},
    )
    assert initial_status == "STARTED"


@pytest.mark.parametrize(
    ("result", "terminal_status", "error"),
    [
        ("cancelled", "SUCCESS", None),
        ("already_terminal", "CANCELED", None),
        ("cancel_failed", "FAILURE", {"code": "DAGSTER_UNAVAILABLE", "message": "x"}),
    ],
)
async def test_run_result_rejects_illegal_result_terminal_combinations(
    migrated_session: AsyncSession,
    result: str,
    terminal_status: str,
    error: dict[str, str] | None,
) -> None:
    await _job(migrated_session, _ROOT, status="running", dagster_run_id="run-invalid")
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

    with pytest.raises(PipelineCancellationInvariantError):
        await set_pipeline_cancellation_run_result(
            migrated_session,
            cancellation_id=detail.attempt.cancellation_id,
            dagster_run_id="run-invalid",
            result=result,
            initial_status="STARTED",
            terminal_status=terminal_status,
            error=error,
        )


@pytest.mark.parametrize("terminal_status", ["SUCCESS", "FAILURE"])
async def test_definitive_base_run_mismatch_preserves_terminal_run_and_base(
    migrated_session: AsyncSession,
    terminal_status: str,
) -> None:
    await _job(migrated_session, _ROOT, status="running", dagster_run_id="run-frozen")
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
    assert await set_pipeline_cancellation_run_result(
        migrated_session,
        cancellation_id=cancellation_id,
        dagster_run_id="run-frozen",
        result="already_terminal",
        initial_status="STARTED",
        terminal_status=terminal_status,
        error=None,
    ) is True
    await migrated_session.execute(
        text(
            "UPDATE ops.import_jobs SET dagster_run_id = 'run-observed-later' "
            "WHERE job_id = CAST(:job_id AS uuid)"
        ),
        {"job_id": _ROOT},
    )
    before = (
        await migrated_session.execute(
            text(
                "SELECT status, dagster_run_id, cancellation_id "
                "FROM ops.import_jobs WHERE job_id = CAST(:job_id AS uuid)"
            ),
            {"job_id": _ROOT},
        )
    ).one()
    error = {
        "code": "DAGSTER_RECONCILE_FAILED",
        "message": "base run mapping changed after observation",
    }
    assert await set_pipeline_cancellation_member_result(
        migrated_session,
        cancellation_id=cancellation_id,
        job_id=_ROOT,
        result="cancel_failed",
        terminal_status=None,
        error=error,
    ) is True
    after = (
        await migrated_session.execute(
            text(
                "SELECT status, dagster_run_id, cancellation_id "
                "FROM ops.import_jobs WHERE job_id = CAST(:job_id AS uuid)"
            ),
            {"job_id": _ROOT},
        )
    ).one()
    assert after == before
    with pytest.raises(PipelineCancellationInvariantError):
        await finish_pipeline_cancellation_attempt(
            migrated_session,
            cancellation_id=cancellation_id,
            status="retryable",
            error={"code": "DAGSTER_UNAVAILABLE", "message": "retry"},
        )
    finished = await finish_pipeline_cancellation_attempt(
        migrated_session,
        cancellation_id=cancellation_id,
        status="failed",
        error=error,
    )
    assert finished is not None
    assert [(run.result, run.terminal_status) for run in finished.runs] == [
        ("already_terminal", terminal_status)
    ]


async def test_queued_member_cannot_use_definitive_failure_with_terminal_shared_run(
    migrated_session: AsyncSession,
) -> None:
    await _job(
        migrated_session,
        _ROOT,
        status="queued",
        dagster_run_id="run-queued-terminal",
    )
    await _job(
        migrated_session,
        _CHILD,
        parent_job_id=_ROOT,
        status="running",
        dagster_run_id="run-queued-terminal",
    )
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
    assert await set_pipeline_cancellation_run_result(
        migrated_session,
        cancellation_id=cancellation_id,
        dagster_run_id="run-queued-terminal",
        result="already_terminal",
        initial_status="STARTED",
        terminal_status="SUCCESS",
        error=None,
    ) is True
    assert await transition_pipeline_cancellation_member(
        migrated_session,
        cancellation_id=cancellation_id,
        job_id=_CHILD,
        dagster_run_id="run-queued-terminal",
        expected_status="running",
        target_status="done",
        result="already_terminal",
    ) is True
    error = {
        "code": "PIPELINE_CANCELLATION_UNSAFE",
        "message": "queued member cannot be a failure target",
    }
    with pytest.raises(
        PipelineCancellationInvariantError,
        match="restricted to running or run-backed active",
    ):
        await set_pipeline_cancellation_member_result(
            migrated_session,
            cancellation_id=cancellation_id,
            job_id=_ROOT,
            result="cancel_failed",
            terminal_status=None,
            error=error,
        )
    await _force_member_failure(
        migrated_session,
        cancellation_id=cancellation_id,
        job_id=_ROOT,
        error=error,
    )
    with pytest.raises(
        PipelineCancellationInvariantError,
        match="restricted to running or run-backed active",
    ):
        await finish_pipeline_cancellation_attempt(
            migrated_session,
            cancellation_id=cancellation_id,
            status="failed",
            error=error,
        )


@pytest.mark.parametrize("authoritative_failure", [False, True])
async def test_exact_running_definitive_requires_authoritative_run_failure(
    migrated_session: AsyncSession,
    authoritative_failure: bool,
) -> None:
    run_id = "run-exact-definitive"
    await _job(migrated_session, _ROOT, status="running", dagster_run_id=run_id)
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
    error = {
        "code": "DAGSTER_RECONCILE_FAILED",
        "message": "authoritative reconcile failed",
    }
    assert await set_pipeline_cancellation_run_result(
        migrated_session,
        cancellation_id=cancellation_id,
        dagster_run_id=run_id,
        result="cancel_failed" if authoritative_failure else "already_terminal",
        initial_status="STARTED",
        terminal_status=None if authoritative_failure else "SUCCESS",
        error=error if authoritative_failure else None,
    ) is True
    if authoritative_failure:
        assert await set_pipeline_cancellation_member_result(
            migrated_session,
            cancellation_id=cancellation_id,
            job_id=_ROOT,
            result="cancel_failed",
            terminal_status=None,
            error=error,
        ) is True
        finished = await finish_pipeline_cancellation_attempt(
            migrated_session,
            cancellation_id=cancellation_id,
            status="failed",
            error=error,
        )
        assert finished is not None
        assert finished.attempt.status == "failed"
        return

    with pytest.raises(
        PipelineCancellationInvariantError,
        match="authoritative run failure",
    ):
        await set_pipeline_cancellation_member_result(
            migrated_session,
            cancellation_id=cancellation_id,
            job_id=_ROOT,
            result="cancel_failed",
            terminal_status=None,
            error=error,
        )
    await _force_member_failure(
        migrated_session,
        cancellation_id=cancellation_id,
        job_id=_ROOT,
        error=error,
    )
    with pytest.raises(
        PipelineCancellationInvariantError,
        match="definitive member mismatch",
    ):
        await finish_pipeline_cancellation_attempt(
            migrated_session,
            cancellation_id=cancellation_id,
            status="failed",
            error=error,
        )


@pytest.mark.parametrize(
    "target",
    ["attempt_retryable", "attempt_failed", "run", "member"],
)
async def test_structured_error_shape_rejects_sql_null(
    migrated_session: AsyncSession,
    target: str,
) -> None:
    await _job(migrated_session, _ROOT, status="running", dagster_run_id="run-shape")
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
    statements = {
        "attempt_retryable": (
            "UPDATE ops.pipeline_cancellations SET status='retryable', "
            "finished_at=now(), error=NULL WHERE cancellation_id=CAST(:id AS uuid)"
        ),
        "attempt_failed": (
            "UPDATE ops.pipeline_cancellations SET status='failed', "
            "finished_at=now(), error=NULL WHERE cancellation_id=CAST(:id AS uuid)"
        ),
        "run": (
            "UPDATE ops.pipeline_cancellation_runs SET result='cancel_failed', "
            "terminal_status=NULL, error=NULL WHERE cancellation_id=CAST(:id AS uuid)"
        ),
        "member": (
            "UPDATE ops.pipeline_cancellation_members SET result='cancel_failed', "
            "terminal_status=NULL, error=NULL WHERE cancellation_id=CAST(:id AS uuid)"
        ),
    }
    with pytest.raises(IntegrityError):
        async with migrated_session.begin_nested():
            await migrated_session.execute(
                text(statements[target]),
                {"id": detail.attempt.cancellation_id},
            )


async def test_failed_attempt_preserves_retryable_member_evidence(
    migrated_session: AsyncSession,
) -> None:
    await _job(migrated_session, _ROOT, status="running", dagster_run_id="run-finish")
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
    with pytest.raises(PipelineCancellationInvariantError, match="fully terminal"):
        await finish_pipeline_cancellation_attempt(
            migrated_session,
            cancellation_id=detail.attempt.cancellation_id,
            status="completed",
            error=None,
        )
    await set_pipeline_cancellation_run_result(
        migrated_session,
        cancellation_id=detail.attempt.cancellation_id,
        dagster_run_id="run-finish",
        result="cancel_failed",
        initial_status="STARTED",
        terminal_status=None,
        error={"code": "DAGSTER_UNAVAILABLE", "message": "timeout"},
    )
    await set_pipeline_cancellation_member_result(
        migrated_session,
        cancellation_id=detail.attempt.cancellation_id,
        job_id=_ROOT,
        result="cancel_failed",
        terminal_status=None,
        error={"code": "DAGSTER_UNAVAILABLE", "message": "timeout"},
    )
    finished = await finish_pipeline_cancellation_attempt(
        migrated_session,
        cancellation_id=detail.attempt.cancellation_id,
        status="failed",
        error={
            "code": "PIPELINE_CANCELLATION_UNSAFE",
            "message": "coordinator invariant failed after transport observation",
        },
    )

    assert finished is not None
    assert finished.attempt.status == "failed"
    assert finished.members[0].error == {
        "code": "DAGSTER_UNAVAILABLE",
        "message": "timeout",
    }
    assert finished.runs[0].error == {
        "code": "DAGSTER_UNAVAILABLE",
        "message": "timeout",
    }


async def test_failed_attempt_preserves_mixed_retryable_and_definitive_evidence(
    migrated_session: AsyncSession,
) -> None:
    await _job(migrated_session, _ROOT, status="running", dagster_run_id="run-retry")
    await _job(
        migrated_session,
        _CHILD,
        parent_job_id=_ROOT,
        status="running",
        dagster_run_id="run-definitive",
    )
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
    retryable = {"code": "DAGSTER_UNAVAILABLE", "message": "response lost"}
    definitive = {
        "code": "DAGSTER_RECONCILE_FAILED",
        "message": "frozen base run mapping changed",
    }
    assert await set_pipeline_cancellation_run_result(
        migrated_session,
        cancellation_id=cancellation_id,
        dagster_run_id="run-retry",
        result="cancel_failed",
        initial_status="STARTED",
        terminal_status=None,
        error=retryable,
    ) is True
    assert await set_pipeline_cancellation_member_result(
        migrated_session,
        cancellation_id=cancellation_id,
        job_id=_ROOT,
        result="cancel_failed",
        terminal_status=None,
        error=retryable,
    ) is True
    assert await set_pipeline_cancellation_run_result(
        migrated_session,
        cancellation_id=cancellation_id,
        dagster_run_id="run-definitive",
        result="already_terminal",
        initial_status="STARTED",
        terminal_status="SUCCESS",
        error=None,
    ) is True
    await migrated_session.execute(
        text(
            "UPDATE ops.import_jobs SET dagster_run_id='run-drifted' "
            "WHERE job_id=CAST(:job_id AS uuid)"
        ),
        {"job_id": _CHILD},
    )
    assert await set_pipeline_cancellation_member_result(
        migrated_session,
        cancellation_id=cancellation_id,
        job_id=_CHILD,
        result="cancel_failed",
        terminal_status=None,
        error=definitive,
    ) is True

    finished = await finish_pipeline_cancellation_attempt(
        migrated_session,
        cancellation_id=cancellation_id,
        status="failed",
        error=definitive,
    )

    assert finished is not None
    assert finished.attempt.status == "failed"
    failures = {
        member.job_id: member.error
        for member in finished.members
        if member.result == "cancel_failed"
    }
    assert failures[_ROOT] == retryable
    assert failures[_CHILD] == definitive
    run_by_id = {run.dagster_run_id: run for run in finished.runs}
    assert run_by_id["run-retry"].error == retryable
    assert run_by_id["run-definitive"].result == "already_terminal"


async def test_failed_unexpected_close_preserves_pending_snapshot(
    migrated_session: AsyncSession,
) -> None:
    await _job(migrated_session, _ROOT, status="running", dagster_run_id="run-pending")
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
    error = {
        "code": "PIPELINE_CANCELLATION_INVARIANT",
        "message": "coordinator closed before authoritative observation",
    }

    finished = await finish_pipeline_cancellation_attempt(
        migrated_session,
        cancellation_id=detail.attempt.cancellation_id,
        status="failed",
        error=error,
    )

    assert finished is not None
    assert finished.attempt.status == "failed"
    assert [run.result for run in finished.runs] == ["pending"]
    assert [member.result for member in finished.members] == ["pending"]
    base = await get_import_job(migrated_session, _ROOT)
    assert base is not None
    assert base.status == "running"
    assert base.cancellation_id == detail.attempt.cancellation_id


async def test_running_member_without_run_closes_only_as_definitive_failed(
    migrated_session: AsyncSession,
) -> None:
    await _job(migrated_session, _ROOT, status="running")
    await migrated_session.execute(
        text(
            "UPDATE ops.import_jobs SET dagster_run_id = NULL "
            "WHERE job_id = CAST(:job_id AS uuid)"
        ),
        {"job_id": _ROOT},
    )
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
    error = {
        "code": "PIPELINE_CANCELLATION_INVARIANT",
        "message": "running member has no Dagster run",
    }
    assert await set_pipeline_cancellation_member_result(
        migrated_session,
        cancellation_id=detail.attempt.cancellation_id,
        job_id=_ROOT,
        result="cancel_failed",
        terminal_status=None,
        error=error,
    ) is True
    finished = await finish_pipeline_cancellation_attempt(
        migrated_session,
        cancellation_id=detail.attempt.cancellation_id,
        status="failed",
        error=error,
    )
    assert finished is not None
    assert finished.attempt.status == "failed"


async def test_finish_and_writer_serialize_on_attempt_row(
    migrated_engine: AsyncEngine,
) -> None:
    from sqlalchemy.ext.asyncio import AsyncSession

    async with AsyncSession(migrated_engine) as setup, setup.begin():
        await _job(setup, _ROOT, status="running", dagster_run_id="run-race")
        detail = await create_pipeline_cancellation_attempt(
            setup,
            scope=await _scope(
                setup,
                kind="import_job",
                execution_id=_ROOT,
            ),
            requested_by="admin:test",
            reason=None,
        )
        await set_pipeline_cancellation_run_result(
            setup,
            cancellation_id=detail.attempt.cancellation_id,
            dagster_run_id="run-race",
            result="cancelled",
            initial_status="STARTED",
            terminal_status="CANCELED",
            error=None,
        )
        await transition_pipeline_cancellation_member(
            setup,
            cancellation_id=detail.attempt.cancellation_id,
            job_id=_ROOT,
            dagster_run_id="run-race",
            expected_status="running",
            target_status="cancelled",
            result="cancelled",
        )

    async def stale_writer() -> bool:
        async with AsyncSession(migrated_engine) as writer, writer.begin():
            return await set_pipeline_cancellation_run_result(
                writer,
                cancellation_id=detail.attempt.cancellation_id,
                dagster_run_id="run-race",
                result="cancelled",
                initial_status="STARTED",
                terminal_status="CANCELED",
                error=None,
            )

    async with AsyncSession(migrated_engine) as finisher:
        transaction = await finisher.begin()
        assert await finish_pipeline_cancellation_attempt(
            finisher,
            cancellation_id=detail.attempt.cancellation_id,
            status="completed",
            error=None,
        ) is not None
        pending_writer = asyncio.create_task(stale_writer())
        await asyncio.sleep(0.05)
        assert pending_writer.done() is False
        await transaction.commit()
    assert await pending_writer is False


async def test_retry_and_old_attempt_writer_serialize(
    migrated_engine: AsyncEngine,
) -> None:
    from sqlalchemy.ext.asyncio import AsyncSession

    async with AsyncSession(migrated_engine) as setup, setup.begin():
        await _job(setup, _ROOT, status="running", dagster_run_id="run-retry")
        detail = await create_pipeline_cancellation_attempt(
            setup,
            scope=await _scope(
                setup,
                kind="import_job",
                execution_id=_ROOT,
            ),
            requested_by="admin:test",
            reason=None,
        )
        retry_error = {"code": "DAGSTER_UNAVAILABLE", "message": "timeout"}
        await set_pipeline_cancellation_run_result(
            setup,
            cancellation_id=detail.attempt.cancellation_id,
            dagster_run_id="run-retry",
            result="cancel_failed",
            initial_status="STARTED",
            terminal_status=None,
            error=retry_error,
        )
        await set_pipeline_cancellation_member_result(
            setup,
            cancellation_id=detail.attempt.cancellation_id,
            job_id=_ROOT,
            result="cancel_failed",
            terminal_status=None,
            error=retry_error,
        )
        await finish_pipeline_cancellation_attempt(
            setup,
            cancellation_id=detail.attempt.cancellation_id,
            status="retryable",
            error=retry_error,
        )

    async def old_writer() -> bool:
        async with AsyncSession(migrated_engine) as writer, writer.begin():
            return await set_pipeline_cancellation_member_result(
                writer,
                cancellation_id=detail.attempt.cancellation_id,
                job_id=_ROOT,
                result="cancel_failed",
                terminal_status=None,
                error=retry_error,
            )

    async with AsyncSession(migrated_engine) as retrier:
        transaction = await retrier.begin()
        await retry_pipeline_cancellation_attempt(
            retrier,
            previous_cancellation_id=detail.attempt.cancellation_id,
            requested_by="admin:retry",
            reason=None,
        )
        pending_writer = asyncio.create_task(old_writer())
        await asyncio.sleep(0.05)
        assert pending_writer.done() is False
        await transaction.commit()
    assert await pending_writer is False


async def test_lineage_mutations_share_one_transaction_lock(
    migrated_engine: AsyncEngine,
) -> None:
    from sqlalchemy.ext.asyncio import AsyncSession

    parent_id = "88888888-8888-4888-8888-888888888888"
    async with (
        AsyncSession(migrated_engine, expire_on_commit=False) as setup,
        setup.begin(),
    ):
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
            await enqueue_unpaired_import_job(
                writer,
                kind="provider_load",
                parent_job_id=parent_id,
            )
        await writer.rollback()
        await locker.rollback()

    async with (
        AsyncSession(migrated_engine, expire_on_commit=False) as cleanup,
        cleanup.begin(),
    ):
        await cleanup.execute(
            text("DELETE FROM ops.import_jobs WHERE job_id = CAST(:job_id AS uuid)"),
            {"job_id": parent_id},
        )
