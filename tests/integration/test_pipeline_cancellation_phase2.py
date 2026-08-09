"""Termination reservation과 application coordinator Postgres 통합 계약.

T-VN-33 cutover WIP 커밋(``2e76b80c``, 메시지에 "do not merge")이 이 파일에서
1801줄을 지웠고 복원되지 않았다. 지워진 회귀가 덮던 코드는 지금도 살아 있다 —
취소 coordinator의 lock 순서·CAS 예약, terminal sensor의 identity mismatch 처리,
run-backed queued 취소의 freeze 범위. 9라운드 적대 리뷰가 저장소 전수 grep으로
0 hit임을 실증했다.

identity를 triple로 옮겨 되살렸다. 지어낸 자연키(``("provider", "done")``)는
이제 만들 수 없으므로(실행 레코드가 ``provider_dataset_operation_scopes``를 FK로
참조한다) 시드에서 고른다 — ``tests/integration/_membership_seed.py``.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

import httpx
import pytest
from kortravelmap.api import pipeline_cancellation_service as service
from kortravelmap.api.pipeline_cancellation_service import cancel_pipeline_execution
from kortravelmap.api.settings import ApiSettings
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.infra.advisory_lock import advisory_lock_key
from kortravelmap.infra.feature_operation_repo import (
    ensure_dagster_feature_operation,
    finish_dagster_feature_membership,
)
from kortravelmap.infra.jobs_repo import enqueue_unpaired_import_job
from kortravelmap.infra.pipeline_cancellation_repo import (
    create_pipeline_cancellation_attempt,
    finish_pipeline_cancellation_attempt,
    get_pipeline_cancellation_detail,
    mark_pipeline_cancellation_run_termination_reserved,
    resolve_pipeline_cancellation_scope,
    retry_pipeline_cancellation_attempt,
    set_pipeline_cancellation_member_result,
    set_pipeline_cancellation_run_result,
    transition_pipeline_cancellation_member,
)
from kortravelmap.infra.pipeline_cancellation_types import (
    PipelineCancellationInvariantError,
    PipelineCancellationScope,
    PipelineCancellationTimelineConflict,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

from tests.integration._membership_seed import (
    MULTI_MEMBER_OPERATION,
    memberships_for_operation,
)

pytestmark = pytest.mark.integration


@pytest.fixture
async def committed_running_job(
    migrated_engine: AsyncEngine,
) -> AsyncIterator[tuple[str, str]]:
    job_id = str(uuid4())
    run_id = f"run-{uuid4()}"
    async with AsyncSession(migrated_engine) as session, session.begin():
        await session.execute(
            text(
                """
                INSERT INTO ops.import_jobs (
                    job_id, kind, payload, status, progress, current_stage,
                    dagster_run_id, started_at, heartbeat_at
                ) VALUES (
                    CAST(:job_id AS uuid), 'provider_load', '{}'::jsonb,
                    'running', 10, 'load', :run_id, now(), now()
                )
                """
            ),
            {"job_id": job_id, "run_id": run_id},
        )
    try:
        yield job_id, run_id
    finally:
        async with AsyncSession(migrated_engine) as session, session.begin():
            cancellation_ids = list(
                await session.scalars(
                    text(
                        "SELECT cancellation_id FROM ops.pipeline_cancellations "
                        "WHERE root_kind='import_job' AND root_id=CAST(:job_id AS uuid)"
                    ),
                    {"job_id": job_id},
                )
            )
            if cancellation_ids:
                await session.execute(
                    text(
                        "DELETE FROM ops.system_log "
                        "WHERE detail->>'cancellation_id'=ANY(CAST(:ids AS text[]))"
                    ),
                    {"ids": [str(value) for value in cancellation_ids]},
                )
                await session.execute(
                    text(
                        "DELETE FROM ops.pipeline_cancellation_members "
                        "WHERE cancellation_id=ANY(CAST(:ids AS uuid[]))"
                    ),
                    {"ids": cancellation_ids},
                )
                await session.execute(
                    text(
                        "DELETE FROM ops.pipeline_cancellation_runs "
                        "WHERE cancellation_id=ANY(CAST(:ids AS uuid[]))"
                    ),
                    {"ids": cancellation_ids},
                )
                await session.execute(
                    text(
                        "UPDATE ops.pipeline_cancellations "
                        "SET previous_cancellation_id=NULL "
                        "WHERE cancellation_id=ANY(CAST(:ids AS uuid[]))"
                    ),
                    {"ids": cancellation_ids},
                )
            await session.execute(
                text("DELETE FROM ops.import_jobs WHERE job_id=CAST(:job_id AS uuid)"),
                {"job_id": job_id},
            )
            if cancellation_ids:
                await session.execute(
                    text(
                        "DELETE FROM ops.pipeline_cancellations "
                        "WHERE cancellation_id=ANY(CAST(:ids AS uuid[]))"
                    ),
                    {"ids": cancellation_ids},
                )


async def _create_attempt(
    session: AsyncSession,
    *,
    job_id: str,
) -> Any:
    scope = await resolve_pipeline_cancellation_scope(
        session,
        kind="import_job",
        execution_id=job_id,
    )
    assert scope is not None
    return await create_pipeline_cancellation_attempt(
        session,
        scope=scope,
        requested_by="admin:test",
        reason="integration test",
    )


@pytest.mark.parametrize(
    (
        "terminal_status",
        "expected_status",
        "expected_stage",
        "all_pairs_done",
        "resume_after_root",
        "incoming_start_missing",
    ),
    [
        ("CANCELED", "cancelled", "cancelled", False, False, False),
        ("CANCELED", "cancelled", "cancelled", False, True, False),
        ("CANCELED", "cancelled", "cancelled", False, False, True),
        ("FAILURE", "failed", "failed", False, False, False),
        ("SUCCESS", "failed", "tracking_invariant", False, False, False),
        ("SUCCESS", "done", "completed", True, False, False),
    ],
)
async def test_canonical_same_marker_terminal_reconciles_authoritative_state(
    migrated_engine: AsyncEngine,
    terminal_status: str,
    expected_status: str,
    expected_stage: str,
    all_pairs_done: bool,
    resume_after_root: bool,
    incoming_start_missing: bool,
) -> None:
    run_id = f"canonical-cancel-{terminal_status.lower()}-{uuid4()}"
    created_at = datetime(2026, 7, 15, 1, tzinfo=UTC)
    started_at = created_at + timedelta(seconds=1)
    finished_at = created_at + timedelta(seconds=5)
    cancellation_id: str | None = None
    root_id: str | None = None
    async with AsyncSession(migrated_engine) as setup, setup.begin():
        done_pair, active_pair = await memberships_for_operation(setup, limit=2)
        ensured = await ensure_dagster_feature_operation(
            setup,
            dagster_run_id=run_id,
            trigger_kind="manual",
            selected_memberships=(done_pair, active_pair),
            operation_key=MULTI_MEMBER_OPERATION,
            engine_created_at=created_at,
            engine_started_at=None if all_pairs_done else started_at,
            observed_status="QUEUED" if all_pairs_done else "STARTED",
        )
        root_id = ensured.operation.root_job_id
        completed_done = await finish_dagster_feature_membership(
            setup, dagster_run_id=run_id, membership=done_pair
        )
        done_finished_at = next(
            member.finished_at
            for member in completed_done.operation.members
            if member.membership == done_pair
        )
        assert done_finished_at is not None
        if incoming_start_missing:
            done_id = next(
                member.job_id
                for member in completed_done.operation.members
                if member.membership == done_pair
            )
            await setup.execute(
                text(
                    "UPDATE ops.import_jobs SET started_at=NULL "
                    "WHERE job_id=CAST(:job_id AS uuid)"
                ),
                {"job_id": done_id},
            )
        if all_pairs_done:
            await finish_dagster_feature_membership(
                setup, dagster_run_id=run_id, membership=active_pair
            )
        attempt = await _create_attempt(setup, job_id=root_id)
        cancellation_id = attempt.attempt.cancellation_id

    try:
        async with AsyncSession(migrated_engine) as coordinator:
            async with coordinator.begin():
                detail = await get_pipeline_cancellation_detail(
                    coordinator, cancellation_id
                )
            assert detail is not None
            if resume_after_root:
                root_member = next(
                    member
                    for member in detail.members
                    if member.operation_kind == "provider_feature_load_run"
                )
                async with coordinator.begin():
                    assert await set_pipeline_cancellation_run_result(
                        coordinator,
                        cancellation_id=cancellation_id,
                        dagster_run_id=run_id,
                        result="cancelled",
                        initial_status="STARTED",
                        terminal_status="CANCELED",
                        error=None,
                        engine_started_at=started_at,
                        engine_finished_at=finished_at,
                    ) is True
                async with coordinator.begin():
                    assert await transition_pipeline_cancellation_member(
                        coordinator,
                        cancellation_id=cancellation_id,
                        job_id=root_member.job_id,
                        dagster_run_id=run_id,
                        expected_status=root_member.initial_status,
                        target_status="cancelled",
                        result="cancelled",
                        dagster_terminal_status="CANCELED",
                        engine_started_at=started_at,
                        engine_finished_at=finished_at,
                    ) is True
                async with coordinator.begin():
                    detail = await get_pipeline_cancellation_detail(
                        coordinator, cancellation_id
                    )
                assert detail is not None
                updated, failure = await service._propagate_recorded_run(
                    coordinator, detail, run_id=run_id
                )
            else:
                updated, failure = await service._record_terminal_run(
                    coordinator,
                    detail,
                    run_id=run_id,
                    initial_status="STARTED",
                    terminal_status=terminal_status,
                    engine_started_at=None if incoming_start_missing else started_at,
                    engine_finished_at=finished_at,
                )
            assert failure is None
            async with coordinator.begin():
                completed = await finish_pipeline_cancellation_attempt(
                    coordinator,
                    cancellation_id=cancellation_id,
                    status="completed",
                    error=None,
                )
            assert completed is not None
            assert updated.runs[0].engine_started_at == started_at
            assert updated.runs[0].engine_finished_at == finished_at

        async with AsyncSession(migrated_engine) as probe:
            rows = (
                await probe.execute(
                    text(
                        """
                        SELECT job.kind, job.status, job.progress,
                               job.current_stage, job.error_message,
                               job.dagster_run_status, job.cancellation_id,
                               job.started_at, job.finished_at, job.heartbeat_at,
                               member.provider_dataset_id, member.sync_scope,
                               member.operation_key
                        FROM ops.import_jobs AS job
                        LEFT JOIN ops.import_job_datasets AS member
                          ON member.job_id = job.job_id
                        WHERE job.job_id = CAST(:root_id AS uuid)
                           OR job.parent_job_id = CAST(:root_id AS uuid)
                        ORDER BY job.kind DESC,
                                 member.provider_dataset_id NULLS FIRST
                        """
                    ),
                    {"root_id": root_id},
                )
            ).all()
            root = next(row for row in rows if row.kind == "provider_feature_load_run")
            # identity가 triple로 바뀌어 `ops.import_jobs`에 provider/dataset_key
            # 열이 없다. member 행이 정본이므로 그쪽 축으로 고른다.
            done = next(
                row
                for row in rows
                if row.provider_dataset_id == done_pair.provider_dataset_id
            )
            active = next(
                row
                for row in rows
                if row.provider_dataset_id == active_pair.provider_dataset_id
            )
            tracking_logs = await probe.scalar(
                text(
                    "SELECT count(*) FROM ops.system_log "
                    "WHERE event='feature_operation.tracking_invariant' "
                    "AND detail->>'cancellation_id'=:cancellation_id"
                ),
                {"cancellation_id": cancellation_id},
            )

        assert root.status == expected_status
        assert root.current_stage == expected_stage
        assert root.progress == (100 if all_pairs_done else 50)
        assert root.dagster_run_status == terminal_status
        assert root.started_at == started_at
        assert root.finished_at == finished_at
        assert root.heartbeat_at == finished_at
        assert str(root.cancellation_id) == cancellation_id
        assert active.status == expected_status
        assert active.current_stage == expected_stage
        assert active.started_at == started_at
        if not all_pairs_done:
            assert active.finished_at == finished_at
            assert active.heartbeat_at == finished_at
        assert str(active.cancellation_id) == cancellation_id
        assert done.status == "done"
        assert done.progress == 100
        assert done.started_at == started_at
        assert done.finished_at == done_finished_at
        if terminal_status == "FAILURE":
            assert root.error_message is not None
            assert active.error_message is not None
        elif terminal_status == "SUCCESS" and not all_pairs_done:
            assert "tracking invariant" in root.error_message
            assert "tracking invariant" in active.error_message
            assert tracking_logs == 1
        else:
            assert root.error_message is None
            assert active.error_message is None
            assert tracking_logs == 0
    finally:
        if root_id is not None:
            async with AsyncSession(migrated_engine) as cleanup, cleanup.begin():
                await cleanup.execute(
                    text(
                        "UPDATE ops.import_jobs SET cancellation_id=NULL, "
                        "cancellation_requested_at=NULL, cancellation_requested_by=NULL, "
                        "cancellation_reason=NULL "
                        "WHERE job_id=CAST(:root_id AS uuid) "
                        "OR parent_job_id=CAST(:root_id AS uuid)"
                    ),
                    {"root_id": root_id},
                )
                if cancellation_id is not None:
                    await cleanup.execute(
                        text(
                            "DELETE FROM ops.pipeline_cancellation_members "
                            "WHERE cancellation_id=CAST(:cancellation_id AS uuid)"
                        ),
                        {"cancellation_id": cancellation_id},
                    )
                    await cleanup.execute(
                        text(
                            "DELETE FROM ops.pipeline_cancellation_runs "
                            "WHERE cancellation_id=CAST(:cancellation_id AS uuid)"
                        ),
                        {"cancellation_id": cancellation_id},
                    )
                    await cleanup.execute(
                        text(
                            "DELETE FROM ops.pipeline_cancellations "
                            "WHERE cancellation_id=CAST(:cancellation_id AS uuid)"
                        ),
                        {"cancellation_id": cancellation_id},
                    )
                await cleanup.execute(
                    text(
                        "DELETE FROM ops.import_jobs "
                        "WHERE parent_job_id=CAST(:root_id AS uuid)"
                    ),
                    {"root_id": root_id},
                )
                await cleanup.execute(
                    text(
                        "DELETE FROM ops.import_jobs "
                        "WHERE job_id=CAST(:root_id AS uuid)"
                    ),
                    {"root_id": root_id},
                )


async def test_canonical_cancellation_rejects_divergent_frozen_start_times(
    migrated_engine: AsyncEngine,
) -> None:
    run_id = f"canonical-cancel-start-drift-{uuid4()}"
    created_at = datetime(2026, 7, 15, 2, tzinfo=UTC)
    started_at = created_at + timedelta(seconds=1)
    finished_at = created_at + timedelta(seconds=5)
    async with AsyncSession(migrated_engine) as setup, setup.begin():
        pairs = await memberships_for_operation(setup, limit=2)
        ensured = await ensure_dagster_feature_operation(
            setup,
            dagster_run_id=run_id,
            trigger_kind="manual",
            selected_memberships=pairs,
            operation_key=MULTI_MEMBER_OPERATION,
            engine_created_at=created_at,
            engine_started_at=started_at,
            observed_status="STARTED",
        )
        root_id = ensured.operation.root_job_id
        await setup.execute(
            text(
                "UPDATE ops.import_jobs SET started_at=:drifted "
                "WHERE job_id=CAST(:job_id AS uuid)"
            ),
            {
                "job_id": ensured.operation.members[0].job_id,
                "drifted": started_at + timedelta(seconds=1),
            },
        )
        attempt = await _create_attempt(setup, job_id=root_id)
        cancellation_id = attempt.attempt.cancellation_id

    try:
        async with AsyncSession(migrated_engine) as coordinator:
            with pytest.raises(PipelineCancellationTimelineConflict):
                async with coordinator.begin():
                    await set_pipeline_cancellation_run_result(
                        coordinator,
                        cancellation_id=cancellation_id,
                        dagster_run_id=run_id,
                        result="cancelled",
                        initial_status="STARTED",
                        terminal_status="CANCELED",
                        error=None,
                        engine_started_at=None,
                        engine_finished_at=finished_at,
                    )
            async with coordinator.begin():
                unchanged = await get_pipeline_cancellation_detail(
                    coordinator, cancellation_id
                )
            assert unchanged is not None
            assert unchanged.runs[0].result == "pending"
            assert unchanged.runs[0].engine_started_at is None
            assert unchanged.runs[0].engine_finished_at is None

        async with AsyncSession(migrated_engine) as probe:
            active_count = await probe.scalar(
                text(
                    "SELECT count(*) FROM ops.import_jobs "
                    "WHERE (job_id=CAST(:root_id AS uuid) "
                    "OR parent_job_id=CAST(:root_id AS uuid)) "
                    "AND status='running'"
                ),
                {"root_id": root_id},
            )
            assert int(active_count) == 3
    finally:
        async with AsyncSession(migrated_engine) as cleanup, cleanup.begin():
            await cleanup.execute(
                text(
                    "UPDATE ops.import_jobs SET cancellation_id=NULL, "
                    "cancellation_requested_at=NULL, cancellation_requested_by=NULL, "
                    "cancellation_reason=NULL "
                    "WHERE job_id=CAST(:root_id AS uuid) "
                    "OR parent_job_id=CAST(:root_id AS uuid)"
                ),
                {"root_id": root_id},
            )
            await cleanup.execute(
                text(
                    "DELETE FROM ops.pipeline_cancellation_members "
                    "WHERE cancellation_id=CAST(:cancellation_id AS uuid)"
                ),
                {"cancellation_id": cancellation_id},
            )
            await cleanup.execute(
                text(
                    "DELETE FROM ops.pipeline_cancellation_runs "
                    "WHERE cancellation_id=CAST(:cancellation_id AS uuid)"
                ),
                {"cancellation_id": cancellation_id},
            )
            await cleanup.execute(
                text(
                    "DELETE FROM ops.pipeline_cancellations "
                    "WHERE cancellation_id=CAST(:cancellation_id AS uuid)"
                ),
                {"cancellation_id": cancellation_id},
            )
            await cleanup.execute(
                text(
                    "DELETE FROM ops.import_jobs "
                    "WHERE parent_job_id=CAST(:root_id AS uuid)"
                ),
                {"root_id": root_id},
            )
            await cleanup.execute(
                text(
                    "DELETE FROM ops.import_jobs "
                    "WHERE job_id=CAST(:root_id AS uuid)"
                ),
                {"root_id": root_id},
            )


async def test_reservation_is_single_cas_with_first_status_and_audit(
    migrated_engine: AsyncEngine,
    committed_running_job: tuple[str, str],
) -> None:
    job_id, run_id = committed_running_job
    async with AsyncSession(migrated_engine) as session, session.begin():
        detail = await _create_attempt(session, job_id=job_id)
        first = await mark_pipeline_cancellation_run_termination_reserved(
            session,
            cancellation_id=detail.attempt.cancellation_id,
            dagster_run_id=run_id,
            initial_status="started",
        )
        second = await mark_pipeline_cancellation_run_termination_reserved(
            session,
            cancellation_id=detail.attempt.cancellation_id,
            dagster_run_id=run_id,
            initial_status="canceling",
        )
        refreshed = await get_pipeline_cancellation_detail(
            session,
            detail.attempt.cancellation_id,
        )

        assert first is True
        assert second is False
        assert refreshed is not None
        assert refreshed.runs[0].initial_status == "STARTED"
        assert refreshed.runs[0].termination_reserved_at is not None
        audit_count = await session.scalar(
            text(
                "SELECT count(*) FROM ops.system_log "
                "WHERE event='pipeline.cancellation.run_termination_reserved' "
                "AND detail->>'cancellation_id'=:cancellation_id"
            ),
            {"cancellation_id": detail.attempt.cancellation_id},
        )
        assert audit_count == 1

        with pytest.raises(
            PipelineCancellationInvariantError,
            match="engine_started_at requires",
        ):
            await set_pipeline_cancellation_run_result(
                session,
                cancellation_id=detail.attempt.cancellation_id,
                dagster_run_id=run_id,
                result="cancelled",
                initial_status="STARTED",
                terminal_status="CANCELED",
                error=None,
                engine_started_at=datetime.now(UTC),
                engine_finished_at=None,
            )

        with pytest.raises(IntegrityError):
            async with session.begin_nested():
                await session.execute(
                    text(
                        "UPDATE ops.pipeline_cancellation_runs "
                        "SET initial_status=NULL "
                        "WHERE cancellation_id=CAST(:cancellation_id AS uuid)"
                    ),
                    {"cancellation_id": detail.attempt.cancellation_id},
                )


async def test_service_commits_marker_before_safe_terminate_and_reconciles(
    migrated_engine: AsyncEngine,
    committed_running_job: tuple[str, str],
) -> None:
    job_id, run_id = committed_running_job
    calls = {"status": 0, "terminate": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        query = str(payload["query"])
        if "terminateRun" in query:
            calls["terminate"] += 1
            async with AsyncSession(migrated_engine) as probe:
                marker = await probe.scalar(
                    text(
                        "SELECT cancellation_id IS NOT NULL "
                        "FROM ops.import_jobs WHERE job_id=CAST(:job_id AS uuid)"
                    ),
                    {"job_id": job_id},
                )
            assert marker is True
            return httpx.Response(
                200,
                json={
                    "data": {
                        "terminateRun": {
                            "__typename": "TerminateRunSuccess",
                            "run": {"runId": run_id, "status": "STARTED"},
                        }
                    }
                },
            )
        calls["status"] += 1
        status = "STARTED" if calls["status"] == 1 else "CANCELED"
        return httpx.Response(
            200,
            json={
                "data": {
                    "runOrError": {
                        "__typename": "Run",
                        "runId": run_id,
                        "status": status,
                    }
                }
            },
        )

    settings = ApiSettings(
        dagster_url="http://dagster.example",
        dagster_allowed_hosts=["dagster.example"],
        dagster_termination_poll_interval_seconds=0.05,
        dagster_termination_timeout_seconds=1.0,
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await cancel_pipeline_execution(
            engine=migrated_engine,
            settings=settings,
            http_client=client,
            kind="import_job",
            execution_id=job_id,
            requested_by="admin:test",
            reason="integration test",
        )

    assert result.status == "completed"
    assert result.members[0].result == "cancelled"
    assert result.dagster_runs[0].termination_reserved_at is not None
    assert calls == {"status": 2, "terminate": 1}


async def test_orphan_reserved_attempt_polls_without_second_mutation(
    migrated_engine: AsyncEngine,
    committed_running_job: tuple[str, str],
) -> None:
    job_id, run_id = committed_running_job
    async with AsyncSession(migrated_engine) as session, session.begin():
        attempt = await _create_attempt(session, job_id=job_id)
        reserved = await mark_pipeline_cancellation_run_termination_reserved(
            session,
            cancellation_id=attempt.attempt.cancellation_id,
            dagster_run_id=run_id,
            initial_status="STARTED",
        )
        assert reserved is True

    calls = {"status": 0, "terminate": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        if "terminateRun" in str(payload["query"]):
            calls["terminate"] += 1
            raise AssertionError("reserved orphan must not dispatch terminate again")
        calls["status"] += 1
        status = "STARTED" if calls["status"] == 1 else "CANCELED"
        return httpx.Response(
            200,
            json={
                "data": {
                    "runOrError": {
                        "__typename": "Run",
                        "runId": run_id,
                        "status": status,
                    }
                }
            },
        )

    settings = ApiSettings(
        dagster_url="http://dagster.example",
        dagster_allowed_hosts=["dagster.example"],
        dagster_termination_poll_interval_seconds=0.05,
        dagster_termination_timeout_seconds=1.0,
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await cancel_pipeline_execution(
            engine=migrated_engine,
            settings=settings,
            http_client=client,
            kind="import_job",
            execution_id=job_id,
            requested_by="admin:resume",
            reason="resume orphan",
        )

    assert result.cancellation_id == UUID(attempt.attempt.cancellation_id)
    assert result.status == "completed"
    assert calls == {"status": 2, "terminate": 0}


async def test_partial_run_failure_resumes_member_copy_without_dagster_call(
    migrated_engine: AsyncEngine,
    committed_running_job: tuple[str, str],
) -> None:
    job_id, run_id = committed_running_job
    failure = {"code": "DAGSTER_UNAVAILABLE", "message": "response lost"}
    async with AsyncSession(migrated_engine) as setup, setup.begin():
        attempt = await _create_attempt(setup, job_id=job_id)
        assert await set_pipeline_cancellation_run_result(
            setup,
            cancellation_id=attempt.attempt.cancellation_id,
            dagster_run_id=run_id,
            result="cancel_failed",
            initial_status="STARTED",
            terminal_status=None,
            error=failure,
        ) is True

    async def handler(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("recorded run failure resume must not call Dagster")

    settings = ApiSettings(
        dagster_url="http://dagster.example",
        dagster_allowed_hosts=["dagster.example"],
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(service.DagsterUnavailable) as raised:
            await cancel_pipeline_execution(
                engine=migrated_engine,
                settings=settings,
                http_client=client,
                kind="import_job",
                execution_id=job_id,
                requested_by="admin:resume",
                reason=None,
            )

    assert raised.value.detail is not None
    assert raised.value.detail.cancellation_id == UUID(attempt.attempt.cancellation_id)
    assert raised.value.detail.status == "retryable"
    assert raised.value.detail.members[0].error is not None
    assert raised.value.detail.members[0].error.code == "DAGSTER_UNAVAILABLE"


async def test_partial_finish_resume_completes_without_external_call(
    migrated_engine: AsyncEngine,
    committed_running_job: tuple[str, str],
) -> None:
    job_id, run_id = committed_running_job
    async with AsyncSession(migrated_engine) as setup, setup.begin():
        attempt = await _create_attempt(setup, job_id=job_id)
        assert await set_pipeline_cancellation_run_result(
            setup,
            cancellation_id=attempt.attempt.cancellation_id,
            dagster_run_id=run_id,
            result="cancelled",
            initial_status="STARTED",
            terminal_status="CANCELED",
            error=None,
        ) is True
        assert await transition_pipeline_cancellation_member(
            setup,
            cancellation_id=attempt.attempt.cancellation_id,
            job_id=job_id,
            dagster_run_id=run_id,
            expected_status="running",
            target_status="cancelled",
            result="cancelled",
        ) is True

    async def handler(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("terminal normalized resume must not call Dagster")

    settings = ApiSettings(
        dagster_url="http://dagster.example",
        dagster_allowed_hosts=["dagster.example"],
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await cancel_pipeline_execution(
            engine=migrated_engine,
            settings=settings,
            http_client=client,
            kind="import_job",
            execution_id=job_id,
            requested_by="admin:resume",
            reason=None,
        )

    assert result.cancellation_id == UUID(attempt.attempt.cancellation_id)
    assert result.status == "completed"


async def test_completed_attempt_replays_without_external_call(
    migrated_engine: AsyncEngine,
    committed_running_job: tuple[str, str],
) -> None:
    job_id, run_id = committed_running_job
    status_calls = 0

    async def first_handler(request: httpx.Request) -> httpx.Response:
        nonlocal status_calls
        payload = json.loads(request.content)
        if "terminateRun" in str(payload["query"]):
            return httpx.Response(
                200,
                json={
                    "data": {
                        "terminateRun": {
                            "__typename": "TerminateRunSuccess",
                            "run": {"runId": run_id, "status": "STARTED"},
                        }
                    }
                },
            )
        status_calls += 1
        return httpx.Response(
            200,
            json={
                "data": {
                    "runOrError": {
                        "__typename": "Run",
                        "runId": run_id,
                        "status": "STARTED" if status_calls == 1 else "CANCELED",
                    }
                }
            },
        )

    settings = ApiSettings(
        dagster_url="http://dagster.example",
        dagster_allowed_hosts=["dagster.example"],
        dagster_termination_poll_interval_seconds=0.05,
        dagster_termination_timeout_seconds=1.0,
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(first_handler)) as client:
        first = await cancel_pipeline_execution(
            engine=migrated_engine,
            settings=settings,
            http_client=client,
            kind="import_job",
            execution_id=job_id,
            requested_by="admin:first",
            reason=None,
        )

    async def replay_handler(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("completed replay must not call Dagster")

    async with httpx.AsyncClient(transport=httpx.MockTransport(replay_handler)) as client:
        replay = await cancel_pipeline_execution(
            engine=migrated_engine,
            settings=settings,
            http_client=client,
            kind="import_job",
            execution_id=job_id,
            requested_by="admin:replay",
            reason=None,
        )

    assert replay.cancellation_id == first.cancellation_id
    assert replay.status == "completed"


async def test_shared_and_multi_run_hierarchy_dispatches_once_per_run(
    migrated_engine: AsyncEngine,
    committed_running_job: tuple[str, str],
) -> None:
    root_id, shared_run_id = committed_running_job
    child_id = str(uuid4())
    grandchild_id = str(uuid4())
    second_run_id = f"run-{uuid4()}"
    async with AsyncSession(migrated_engine) as setup, setup.begin():
        await setup.execute(
            text(
                """
                INSERT INTO ops.import_jobs (
                    job_id, parent_job_id, kind, payload, status, progress,
                    current_stage, dagster_run_id, started_at, heartbeat_at
                ) VALUES
                (
                    CAST(:child_id AS uuid), CAST(:root_id AS uuid),
                    'provider_load', '{}'::jsonb, 'running', 10, 'load',
                    :shared_run_id, now(), now()
                ),
                (
                    CAST(:grandchild_id AS uuid), CAST(:root_id AS uuid),
                    'provider_load', '{}'::jsonb, 'running', 10, 'load',
                    :second_run_id, now(), now()
                )
                """
            ),
            {
                "child_id": child_id,
                "grandchild_id": grandchild_id,
                "root_id": root_id,
                "shared_run_id": shared_run_id,
                "second_run_id": second_run_id,
            },
        )

    status_calls = {shared_run_id: 0, second_run_id: 0}
    mutations = {shared_run_id: 0, second_run_id: 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        run_id = str(payload["variables"]["runId"])
        if "terminateRun" in str(payload["query"]):
            mutations[run_id] += 1
            return httpx.Response(
                200,
                json={
                    "data": {
                        "terminateRun": {
                            "__typename": "TerminateRunSuccess",
                            "run": {"runId": run_id, "status": "STARTED"},
                        }
                    }
                },
            )
        status_calls[run_id] += 1
        status = "STARTED" if status_calls[run_id] == 1 else "CANCELED"
        return httpx.Response(
            200,
            json={
                "data": {
                    "runOrError": {
                        "__typename": "Run",
                        "runId": run_id,
                        "status": status,
                    }
                }
            },
        )

    settings = ApiSettings(
        dagster_url="http://dagster.example",
        dagster_allowed_hosts=["dagster.example"],
        dagster_termination_poll_interval_seconds=0.05,
        dagster_termination_timeout_seconds=1.0,
    )
    try:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await cancel_pipeline_execution(
                engine=migrated_engine,
                settings=settings,
                http_client=client,
                kind="import_job",
                execution_id=grandchild_id,
                requested_by="admin:test",
                reason=None,
            )

        assert result.status == "completed"
        assert len(result.dagster_runs) == 2
        assert len(result.members) == 3
        assert {member.result for member in result.members} == {"cancelled"}
        assert mutations == {shared_run_id: 1, second_run_id: 1}
    finally:
        async with AsyncSession(migrated_engine) as cleanup, cleanup.begin():
            await cleanup.execute(
                text(
                    "DELETE FROM ops.pipeline_cancellation_members "
                    "WHERE job_id=ANY(CAST(:ids AS uuid[]))"
                ),
                {"ids": [grandchild_id, child_id]},
            )
            await cleanup.execute(
                text(
                    "DELETE FROM ops.import_jobs "
                    "WHERE job_id=ANY(CAST(:ids AS uuid[]))"
                ),
                {"ids": [grandchild_id, child_id]},
            )


async def test_definitive_terminate_http_failure_exposes_reloaded_5xx_detail(
    migrated_engine: AsyncEngine,
    committed_running_job: tuple[str, str],
) -> None:
    job_id, run_id = committed_running_job
    calls = {"status": 0, "mutation": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        if "terminateRun" in str(payload["query"]):
            calls["mutation"] += 1
            return httpx.Response(
                502,
                json={"error": "rejected"},
                request=request,
            )
        calls["status"] += 1
        return httpx.Response(
            200,
            json={
                "data": {
                    "runOrError": {
                        "__typename": "Run",
                        "runId": run_id,
                        "status": "STARTED",
                    }
                }
            },
        )

    settings = ApiSettings(
        dagster_url="http://dagster.example",
        dagster_allowed_hosts=["dagster.example"],
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(service.DagsterTerminateFailed) as raised:
            await cancel_pipeline_execution(
                engine=migrated_engine,
                settings=settings,
                http_client=client,
                kind="import_job",
                execution_id=job_id,
                requested_by="admin:test",
                reason=None,
            )

    assert calls == {"status": 1, "mutation": 1}
    assert raised.value.detail is not None
    assert raised.value.detail.status == "retryable"
    async with AsyncSession(migrated_engine) as probe:
        stored = await get_pipeline_cancellation_detail(
            probe,
            str(raised.value.detail.cancellation_id),
        )
    assert stored is not None
    assert stored.attempt.status == "retryable"
    assert stored.runs[0].error is not None
    assert stored.runs[0].error["code"] == "DAGSTER_TERMINATE_FAILED"


async def test_running_member_without_run_id_is_definitive_and_never_calls_dagster(
    migrated_engine: AsyncEngine,
) -> None:
    job_id = str(uuid4())
    async with AsyncSession(migrated_engine) as setup, setup.begin():
        await setup.execute(
            text(
                "INSERT INTO ops.import_jobs "
                "(job_id, kind, payload, status, progress, current_stage, "
                "started_at, heartbeat_at) VALUES "
                "(CAST(:job_id AS uuid), 'runless', '{}'::jsonb, 'running', "
                "1, 'running', now(), now())"
            ),
            {"job_id": job_id},
        )

    async def handler(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("runless cancellation must not call Dagster")

    settings = ApiSettings(
        dagster_url="http://dagster.example",
        dagster_allowed_hosts=["dagster.example"],
    )
    cancellation_id: str | None = None
    try:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        ) as client:
            with pytest.raises(service.PipelineCancellationUnsafe) as raised:
                await cancel_pipeline_execution(
                    engine=migrated_engine,
                    settings=settings,
                    http_client=client,
                    kind="import_job",
                    execution_id=job_id,
                    requested_by="admin:test",
                    reason="runless",
                )
        assert raised.value.detail is not None
        cancellation_id = raised.value.detail.cancellation_id
        assert raised.value.detail.status == "failed"
        assert raised.value.detail.dagster_runs == []
        assert raised.value.detail.members[0].result == "cancel_failed"
        assert raised.value.detail.members[0].error is not None
        assert (
            raised.value.detail.members[0].error.code
            == "PIPELINE_CANCELLATION_UNSAFE"
        )
    finally:
        async with AsyncSession(migrated_engine) as cleanup, cleanup.begin():
            await cleanup.execute(
                text(
                    "UPDATE ops.import_jobs SET cancellation_id=NULL, "
                    "cancellation_requested_at=NULL, cancellation_requested_by=NULL, "
                    "cancellation_reason=NULL WHERE job_id=CAST(:job_id AS uuid)"
                ),
                {"job_id": job_id},
            )
            if cancellation_id is not None:
                await cleanup.execute(
                    text(
                        "DELETE FROM ops.pipeline_cancellation_members "
                        "WHERE cancellation_id=CAST(:cancellation_id AS uuid)"
                    ),
                    {"cancellation_id": cancellation_id},
                )
                await cleanup.execute(
                    text(
                        "DELETE FROM ops.pipeline_cancellations "
                        "WHERE cancellation_id=CAST(:cancellation_id AS uuid)"
                    ),
                    {"cancellation_id": cancellation_id},
                )
            await cleanup.execute(
                text("DELETE FROM ops.import_jobs WHERE job_id=CAST(:job_id AS uuid)"),
                {"job_id": job_id},
            )


async def test_queued_canonical_terminate_failure_retries_same_frozen_scope(
    migrated_engine: AsyncEngine,
) -> None:
    run_id = f"canonical-queued-retry-{uuid4()}"
    created_at = datetime(2026, 7, 15, 4, tzinfo=UTC)
    started_at = created_at + timedelta(seconds=1)
    finished_at = created_at + timedelta(seconds=5)
    async with AsyncSession(migrated_engine) as setup, setup.begin():
        pairs = await memberships_for_operation(setup, limit=2)
        ensured = await ensure_dagster_feature_operation(
            setup,
            dagster_run_id=run_id,
            trigger_kind="manual",
            selected_memberships=pairs,
            operation_key=MULTI_MEMBER_OPERATION,
            engine_created_at=created_at,
            engine_started_at=None,
            observed_status="QUEUED",
        )
    root_id = ensured.operation.root_job_id
    first_cancellation_id: str | None = None
    second_cancellation_id: str | None = None
    settings = ApiSettings(
        dagster_url="http://dagster.example",
        dagster_allowed_hosts=["dagster.example"],
        dagster_termination_poll_interval_seconds=0.05,
        dagster_termination_timeout_seconds=1,
    )

    async def failed_handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        if "terminateRun" in str(payload["query"]):
            return httpx.Response(502, json={"error": "rejected"}, request=request)
        return httpx.Response(
            200,
            json={
                "data": {
                    "runOrError": {
                        "__typename": "Run",
                        "runId": run_id,
                        "status": "QUEUED",
                        "startTime": None,
                        "endTime": None,
                    }
                }
            },
        )

    try:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(failed_handler)
        ) as client:
            with pytest.raises(service.DagsterTerminateFailed) as raised:
                await cancel_pipeline_execution(
                    engine=migrated_engine,
                    settings=settings,
                    http_client=client,
                    kind="import_job",
                    execution_id=root_id,
                    requested_by="admin:first",
                    reason="first failure",
                )
        assert raised.value.detail is not None
        first_cancellation_id = raised.value.detail.cancellation_id
        first_job_ids = {
            member.job_id for member in raised.value.detail.members
        }
        assert raised.value.detail.status == "retryable"
        assert len(first_job_ids) == len(pairs) + 1
        assert {member.result for member in raised.value.detail.members} == {
            "cancel_failed"
        }

        status_calls = 0

        async def success_handler(request: httpx.Request) -> httpx.Response:
            nonlocal status_calls
            payload = json.loads(request.content)
            if "terminateRun" in str(payload["query"]):
                return httpx.Response(
                    200,
                    json={
                        "data": {
                            "terminateRun": {
                                "__typename": "TerminateRunSuccess",
                                "run": {"runId": run_id, "status": "QUEUED"},
                            }
                        }
                    },
                )
            status_calls += 1
            terminal = status_calls > 1
            return httpx.Response(
                200,
                json={
                    "data": {
                        "runOrError": {
                            "__typename": "Run",
                            "runId": run_id,
                            "status": "CANCELED" if terminal else "QUEUED",
                            "startTime": started_at.timestamp() if terminal else None,
                            "endTime": finished_at.timestamp() if terminal else None,
                        }
                    }
                },
            )

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(success_handler)
        ) as client:
            completed = await cancel_pipeline_execution(
                engine=migrated_engine,
                settings=settings,
                http_client=client,
                kind="import_job",
                execution_id=root_id,
                requested_by="admin:retry",
                reason="retry",
            )
        second_cancellation_id = completed.cancellation_id
        assert second_cancellation_id != first_cancellation_id
        assert completed.previous_cancellation_id == first_cancellation_id
        assert {member.job_id for member in completed.members} == first_job_ids
        assert {member.result for member in completed.members} == {"cancelled"}
        assert completed.dagster_runs[0].engine_started_at == started_at
        assert completed.dagster_runs[0].engine_finished_at == finished_at
    finally:
        async with AsyncSession(migrated_engine) as cleanup, cleanup.begin():
            await cleanup.execute(
                text(
                    "UPDATE ops.import_jobs SET cancellation_id=NULL, "
                    "cancellation_requested_at=NULL, cancellation_requested_by=NULL, "
                    "cancellation_reason=NULL WHERE job_id=CAST(:root_id AS uuid) "
                    "OR parent_job_id=CAST(:root_id AS uuid)"
                ),
                {"root_id": root_id},
            )
            cancellation_ids = [
                value
                for value in (first_cancellation_id, second_cancellation_id)
                if value is not None
            ]
            if cancellation_ids:
                for statement in (
                    "DELETE FROM ops.pipeline_cancellation_members "
                    "WHERE cancellation_id=ANY(CAST(:ids AS uuid[]))",
                    "DELETE FROM ops.pipeline_cancellation_runs "
                    "WHERE cancellation_id=ANY(CAST(:ids AS uuid[]))",
                ):
                    await cleanup.execute(
                        text(statement),
                        {"ids": cancellation_ids},
                    )
                for cancellation_id in reversed(cancellation_ids):
                    await cleanup.execute(
                        text(
                            "DELETE FROM ops.pipeline_cancellations "
                            "WHERE cancellation_id=CAST(:cancellation_id AS uuid)"
                        ),
                        {"cancellation_id": cancellation_id},
                    )
            await cleanup.execute(
                text(
                    "DELETE FROM ops.import_jobs "
                    "WHERE parent_job_id=CAST(:root_id AS uuid)"
                ),
                {"root_id": root_id},
            )
            await cleanup.execute(
                text(
                    "DELETE FROM ops.import_jobs "
                    "WHERE job_id=CAST(:root_id AS uuid)"
                ),
                {"root_id": root_id},
            )


async def test_ownership_loss_prefers_canonical_current_over_exact_old_attempt(
    migrated_engine: AsyncEngine,
    committed_running_job: tuple[str, str],
) -> None:
    job_id, run_id = committed_running_job
    retryable = {"code": "DAGSTER_UNAVAILABLE", "message": "response lost"}
    async with AsyncSession(migrated_engine) as session, session.begin():
        first = await _create_attempt(session, job_id=job_id)
        assert await set_pipeline_cancellation_run_result(
            session,
            cancellation_id=first.attempt.cancellation_id,
            dagster_run_id=run_id,
            result="cancel_failed",
            initial_status="STARTED",
            terminal_status=None,
            error=retryable,
        ) is True
        assert await set_pipeline_cancellation_member_result(
            session,
            cancellation_id=first.attempt.cancellation_id,
            job_id=job_id,
            result="cancel_failed",
            terminal_status=None,
            error=retryable,
        ) is True
        assert await finish_pipeline_cancellation_attempt(
            session,
            cancellation_id=first.attempt.cancellation_id,
            status="retryable",
            error=retryable,
        ) is not None
        current = await retry_pipeline_cancellation_attempt(
            session,
            previous_cancellation_id=first.attempt.cancellation_id,
            requested_by="admin:retry",
            reason="resume",
        )

    with pytest.raises(service.PipelineCancellationInProgress) as raised:
        await service._reload_after_ownership_loss(
            engine=migrated_engine,
            cancellation_id=first.attempt.cancellation_id,
            kind="import_job",
            execution_id=job_id,
            fallback_root=service._root_record("import_job", job_id),
            settings=ApiSettings(),
        )

    assert raised.value.detail is not None
    assert raised.value.detail.cancellation_id == UUID(
        current.attempt.cancellation_id
    )


async def test_unexpected_service_close_keeps_pending_facts(
    migrated_engine: AsyncEngine,
    committed_running_job: tuple[str, str],
) -> None:
    job_id, _run_id = committed_running_job
    async with AsyncSession(migrated_engine) as setup, setup.begin():
        attempt = await _create_attempt(setup, job_id=job_id)
    async with AsyncSession(migrated_engine) as coordinator:
        detail, failure = await service._close_attempt_unsafe(
            coordinator,
            cancellation_id=attempt.attempt.cancellation_id,
        )

    assert failure.code == "PIPELINE_CANCELLATION_UNSAFE"
    assert detail.attempt.status == "failed"
    assert [run.result for run in detail.runs] == ["pending"]
    assert [member.result for member in detail.members] == ["pending"]


async def test_unexpected_service_close_keeps_retryable_observations(
    migrated_engine: AsyncEngine,
    committed_running_job: tuple[str, str],
) -> None:
    job_id, run_id = committed_running_job
    retryable = {"code": "DAGSTER_UNAVAILABLE", "message": "response lost"}
    async with AsyncSession(migrated_engine) as setup, setup.begin():
        attempt = await _create_attempt(setup, job_id=job_id)
        assert await set_pipeline_cancellation_run_result(
            setup,
            cancellation_id=attempt.attempt.cancellation_id,
            dagster_run_id=run_id,
            result="cancel_failed",
            initial_status="STARTED",
            terminal_status=None,
            error=retryable,
        ) is True
        assert await set_pipeline_cancellation_member_result(
            setup,
            cancellation_id=attempt.attempt.cancellation_id,
            job_id=job_id,
            result="cancel_failed",
            terminal_status=None,
            error=retryable,
        ) is True

    async with AsyncSession(migrated_engine) as coordinator:
        detail, failure = await service._close_attempt_unsafe(
            coordinator,
            cancellation_id=attempt.attempt.cancellation_id,
        )

    assert failure.code == "PIPELINE_CANCELLATION_UNSAFE"
    assert detail.attempt.status == "failed"
    assert detail.runs[0].error == retryable
    assert detail.members[0].error == retryable


class _UnlockFailureSession:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def in_transaction(self) -> bool:
        return self._session.in_transaction()

    async def execute(self, statement: Any, parameters: Any = None) -> Any:
        if "pg_advisory_unlock" in str(statement):
            raise RuntimeError("simulated response loss during exact unlock")
        return await self._session.execute(statement, parameters)

    async def commit(self) -> None:
        await self._session.commit()

    async def rollback(self) -> None:
        await self._session.rollback()


async def test_unlock_exception_hard_invalidates_actual_backend_and_releases_lock(
    migrated_engine: AsyncEngine,
) -> None:
    lease_key = advisory_lock_key("pipeline-cancellation:test:hard-invalidate")
    async with (
        migrated_engine.connect() as connection,
        AsyncSession(bind=connection, expire_on_commit=False) as session,
    ):
        assert await service._acquire_coordinator_lease(
            session,
            lease_key=lease_key,
        ) is True
        backend_pid = await session.scalar(text("SELECT pg_backend_pid()"))
        await session.commit()
        assert session.in_transaction() is False
        with pytest.raises(service.PipelineCancellationUnsafe):
            await service._release_coordinator_lease(
                _UnlockFailureSession(session),  # type: ignore[arg-type]
                connection,
                lease_key=lease_key,
            )
        assert connection.invalidated is True

    async with migrated_engine.connect() as competitor:
        acquired = await competitor.scalar(
            text("SELECT pg_try_advisory_lock(:lock_id)"),
            {"lock_id": lease_key},
        )
        assert acquired is True
        assert await competitor.scalar(
            text("SELECT pg_advisory_unlock(:lock_id)"),
            {"lock_id": lease_key},
        ) is True
        active_old_backend = True
        for _ in range(20):
            active_old_backend = bool(
                await competitor.scalar(
                    text(
                        "SELECT EXISTS ("
                        "SELECT 1 FROM pg_stat_activity WHERE pid=:pid)"
                    ),
                    {"pid": backend_pid},
                )
            )
            if not active_old_backend:
                break
            await asyncio.sleep(0.01)
        assert active_old_backend is False


async def test_same_root_concurrent_service_has_one_coordinator_and_one_mutation(
    migrated_engine: AsyncEngine,
    committed_running_job: tuple[str, str],
) -> None:
    job_id, run_id = committed_running_job
    initial_status_entered = asyncio.Event()
    release_initial_status = asyncio.Event()
    calls = {"status": 0, "mutation": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        if "terminateRun" in str(payload["query"]):
            calls["mutation"] += 1
            return httpx.Response(
                200,
                json={
                    "data": {
                        "terminateRun": {
                            "__typename": "TerminateRunSuccess",
                            "run": {"runId": run_id, "status": "STARTED"},
                        }
                    }
                },
            )
        calls["status"] += 1
        if calls["status"] == 1:
            initial_status_entered.set()
            await release_initial_status.wait()
            status = "STARTED"
        else:
            status = "CANCELED"
        return httpx.Response(
            200,
            json={
                "data": {
                    "runOrError": {
                        "__typename": "Run",
                        "runId": run_id,
                        "status": status,
                    }
                }
            },
        )

    settings = ApiSettings(
        dagster_url="http://dagster.example",
        dagster_allowed_hosts=["dagster.example"],
        dagster_termination_poll_interval_seconds=0.05,
        dagster_termination_timeout_seconds=1.0,
        pipeline_cancellation_lease_reload_attempts=1,
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        winner = asyncio.create_task(
            cancel_pipeline_execution(
                engine=migrated_engine,
                settings=settings,
                http_client=client,
                kind="import_job",
                execution_id=job_id,
                requested_by="admin:winner",
                reason=None,
            )
        )
        await initial_status_entered.wait()
        try:
            with pytest.raises(service.PipelineCancellationInProgress):
                await cancel_pipeline_execution(
                    engine=migrated_engine,
                    settings=settings,
                    http_client=client,
                    kind="import_job",
                    execution_id=job_id,
                    requested_by="admin:loser",
                    reason=None,
                )
        finally:
            release_initial_status.set()
        result = await winner

    assert result.status == "completed"
    assert calls == {"status": 2, "mutation": 1}


async def test_resolve_to_lease_root_drift_retries_before_attempt_mutation(
    migrated_engine: AsyncEngine,
    committed_running_job: tuple[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job_id, run_id = committed_running_job
    async with AsyncSession(migrated_engine) as probe:
        actual_scope = await resolve_pipeline_cancellation_scope(
            probe,
            kind="import_job",
            execution_id=job_id,
        )
    assert actual_scope is not None
    drifted_scope = PipelineCancellationScope(
        root_kind="import_job",
        root_id=str(uuid4()),
        members=actual_scope.members,
    )
    resolve_calls = 0

    async def resolve_with_one_drift(
        _session: AsyncSession,
        *,
        kind: str,
        execution_id: str,
    ) -> PipelineCancellationScope:
        nonlocal resolve_calls
        assert (kind, execution_id) == ("import_job", job_id)
        resolve_calls += 1
        return drifted_scope if resolve_calls == 1 else actual_scope

    monkeypatch.setattr(
        service,
        "resolve_pipeline_cancellation_scope",
        resolve_with_one_drift,
    )
    status_calls = 0
    mutation_calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal status_calls, mutation_calls
        payload = json.loads(request.content)
        if "terminateRun" in str(payload["query"]):
            mutation_calls += 1
            return httpx.Response(
                200,
                json={
                    "data": {
                        "terminateRun": {
                            "__typename": "TerminateRunSuccess",
                            "run": {"runId": run_id, "status": "STARTED"},
                        }
                    }
                },
            )
        status_calls += 1
        return httpx.Response(
            200,
            json={
                "data": {
                    "runOrError": {
                        "__typename": "Run",
                        "runId": run_id,
                        "status": "STARTED" if status_calls == 1 else "CANCELED",
                    }
                }
            },
        )

    settings = ApiSettings(
        dagster_url="http://dagster.example",
        dagster_allowed_hosts=["dagster.example"],
        dagster_termination_poll_interval_seconds=0.05,
        dagster_termination_timeout_seconds=1.0,
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await cancel_pipeline_execution(
            engine=migrated_engine,
            settings=settings,
            http_client=client,
            kind="import_job",
            execution_id=job_id,
            requested_by="admin:test",
            reason=None,
        )

    assert result.root.id == UUID(actual_scope.root_id)
    assert result.status == "completed"
    assert resolve_calls == 4
    assert mutation_calls == 1


async def test_different_roots_coordinate_independently(
    migrated_engine: AsyncEngine,
    committed_running_job: tuple[str, str],
) -> None:
    first_job_id, first_run_id = committed_running_job
    second_job_id = str(uuid4())
    second_run_id = f"run-{uuid4()}"
    async with AsyncSession(migrated_engine) as setup, setup.begin():
        await setup.execute(
            text(
                """
                INSERT INTO ops.import_jobs (
                    job_id, kind, payload, status, progress, current_stage,
                    dagster_run_id, started_at, heartbeat_at
                ) VALUES (
                    CAST(:job_id AS uuid), 'provider_load', '{}'::jsonb,
                    'running', 10, 'load', :run_id, now(), now()
                )
                """
            ),
            {"job_id": second_job_id, "run_id": second_run_id},
        )

    status_calls = {first_run_id: 0, second_run_id: 0}
    mutations = {first_run_id: 0, second_run_id: 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        run_id = str(payload["variables"]["runId"])
        if "terminateRun" in str(payload["query"]):
            mutations[run_id] += 1
            return httpx.Response(
                200,
                json={
                    "data": {
                        "terminateRun": {
                            "__typename": "TerminateRunSuccess",
                            "run": {"runId": run_id, "status": "STARTED"},
                        }
                    }
                },
            )
        status_calls[run_id] += 1
        status = "STARTED" if status_calls[run_id] == 1 else "CANCELED"
        return httpx.Response(
            200,
            json={
                "data": {
                    "runOrError": {
                        "__typename": "Run",
                        "runId": run_id,
                        "status": status,
                    }
                }
            },
        )

    settings = ApiSettings(
        dagster_url="http://dagster.example",
        dagster_allowed_hosts=["dagster.example"],
        dagster_termination_poll_interval_seconds=0.05,
        dagster_termination_timeout_seconds=1.0,
    )
    try:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            results = await asyncio.gather(
                *(
                    cancel_pipeline_execution(
                        engine=migrated_engine,
                        settings=settings,
                        http_client=client,
                        kind="import_job",
                        execution_id=job_id,
                        requested_by="admin:test",
                        reason=None,
                    )
                    for job_id in (first_job_id, second_job_id)
                )
            )
        assert [result.status for result in results] == ["completed", "completed"]
        assert mutations == {first_run_id: 1, second_run_id: 1}
    finally:
        async with AsyncSession(migrated_engine) as cleanup, cleanup.begin():
            cancellation_ids = list(
                await cleanup.scalars(
                    text(
                        "SELECT cancellation_id FROM ops.pipeline_cancellations "
                        "WHERE root_kind='import_job' "
                        "AND root_id=CAST(:job_id AS uuid)"
                    ),
                    {"job_id": second_job_id},
                )
            )
            if cancellation_ids:
                await cleanup.execute(
                    text(
                        "DELETE FROM ops.system_log "
                        "WHERE detail->>'cancellation_id'=ANY(CAST(:ids AS text[]))"
                    ),
                    {"ids": [str(value) for value in cancellation_ids]},
                )
                await cleanup.execute(
                    text(
                        "DELETE FROM ops.pipeline_cancellation_members "
                        "WHERE cancellation_id=ANY(CAST(:ids AS uuid[]))"
                    ),
                    {"ids": cancellation_ids},
                )
                await cleanup.execute(
                    text(
                        "DELETE FROM ops.pipeline_cancellation_runs "
                        "WHERE cancellation_id=ANY(CAST(:ids AS uuid[]))"
                    ),
                    {"ids": cancellation_ids},
                )
            await cleanup.execute(
                text("DELETE FROM ops.import_jobs WHERE job_id=CAST(:job_id AS uuid)"),
                {"job_id": second_job_id},
            )
            if cancellation_ids:
                await cleanup.execute(
                    text(
                        "DELETE FROM ops.pipeline_cancellations "
                        "WHERE cancellation_id=ANY(CAST(:ids AS uuid[]))"
                    ),
                    {"ids": cancellation_ids},
                )

async def test_cancellation_reserves_one_generic_import_root(
    migrated_session: AsyncSession,
) -> None:
    job = await enqueue_unpaired_import_job(
        migrated_session,
        kind="cancellation-integration-fixture",
        payload={"fixture": str(uuid4())},
        source_checksum=None,
    )
    scope = await resolve_pipeline_cancellation_scope(
        migrated_session,
        kind="import_job",
        execution_id=job.job_id,
    )

    assert scope is not None
    attempt = await create_pipeline_cancellation_attempt(
        migrated_session,
        scope=scope,
        requested_by="admin:integration-test",
        reason="canonical cancellation reservation",
    )
    detail = await get_pipeline_cancellation_detail(
        migrated_session,
        attempt.attempt.cancellation_id,
    )

    assert detail is not None
    assert detail.attempt.root_id == job.job_id
    assert detail.attempt.root_kind == "import_job"
    assert len(detail.members) == 1
    assert detail.members[0].job_id == job.job_id


async def test_cancellation_scope_does_not_synthesize_provider_dataset_identity(
    migrated_session: AsyncSession,
) -> None:
    job = await enqueue_unpaired_import_job(
        migrated_session,
        kind="cancellation-integration-fixture",
        payload={"fixture": str(uuid4())},
        source_checksum=None,
    )

    scope = await resolve_pipeline_cancellation_scope(
        migrated_session,
        kind="import_job",
        execution_id=job.job_id,
    )

    assert scope is not None
    assert scope.root_kind == "import_job"
    assert scope.root_id == job.job_id
    assert tuple(member.job_id for member in scope.members) == (job.job_id,)
    # T-VN-33: unpaired root는 dataset membership을 만들지 않는다. 자연키 사본이
    # 사라졌으므로 합성 provider/dataset identity가 끼어들 자리도 없다 —
    # membership 정본인 ``ops.import_job_datasets``가 비어 있어야 한다.
    memberships = (
        (
            await migrated_session.execute(
                text(
                    """
                    SELECT provider_dataset_id, sync_scope, operation_key
                    FROM ops.import_job_datasets
                    WHERE job_id = CAST(:job_id AS uuid)
                    """
                ),
                {"job_id": job.job_id},
            )
        )
        .mappings()
        .all()
    )
    assert memberships == []
