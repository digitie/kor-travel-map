"""Termination reservation과 application coordinator Postgres 통합 계약."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any
from uuid import uuid4

import httpx
import pytest
from kortravelmap.api import pipeline_cancellation_service as service
from kortravelmap.api.pipeline_cancellation_service import cancel_pipeline_execution
from kortravelmap.api.settings import ApiSettings
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.infra.advisory_lock import advisory_lock_key
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
from kortravelmap.infra.pipeline_cancellation_types import PipelineCancellationScope

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

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
            await session.execute(
                text("DELETE FROM ops.import_jobs WHERE job_id=CAST(:job_id AS uuid)"),
                {"job_id": job_id},
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

    assert result.cancellation_id == attempt.attempt.cancellation_id
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
    assert raised.value.detail.cancellation_id == attempt.attempt.cancellation_id
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
            member_kind="import_job",
            member_id=job_id,
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

    assert result.cancellation_id == attempt.attempt.cancellation_id
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
                    CAST(:grandchild_id AS uuid), CAST(:child_id AS uuid),
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
            raised.value.detail.cancellation_id,
        )
    assert stored is not None
    assert stored.attempt.status == "retryable"
    assert stored.runs[0].error is not None
    assert stored.runs[0].error["code"] == "DAGSTER_TERMINATE_FAILED"


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
            member_kind="import_job",
            member_id=job_id,
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
    assert raised.value.detail.cancellation_id == current.attempt.cancellation_id


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
            member_kind="import_job",
            member_id=job_id,
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

    assert result.root.id == actual_scope.root_id
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
            await cleanup.execute(
                text("DELETE FROM ops.import_jobs WHERE job_id=CAST(:job_id AS uuid)"),
                {"job_id": second_job_id},
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
                    text(
                        "DELETE FROM ops.pipeline_cancellations "
                        "WHERE cancellation_id=ANY(CAST(:ids AS uuid[]))"
                    ),
                    {"ids": cancellation_ids},
                )
