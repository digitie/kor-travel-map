"""ops.dagster_schedule_overrides 읽기/쓰기 경로 + 0037 마이그레이션 계약 회귀(#613).

공용 schedule service의 raw ``text()`` SQL이 0037 테이블
스키마(컬럼명·ON CONFLICT 타겟·스키마 한정자)와 일치하는지 실제 DB로 검증한다 — 오타가
나면 CI에서 잡힌다(이전엔 n150 live e2e뿐이라 CI 미검출).

라우터 함수는 내부에서 ``session.commit()``하므로 rollback 격리용 ``migrated_session``
대신 ``migrated_engine``에 직접 autobegin 세션을 열고, finally에서 정리한다.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from time import perf_counter
from uuid import UUID, uuid4

import pytest
from kortravelmap.api import dagster_schedule_service
from kortravelmap.api.dagster_schedule_service import (
    DagsterScheduleClaimNotFound,
    DagsterScheduleClaimResolutionConflict,
    DagsterScheduleIdempotencyConflict,
    DagsterScheduleUncertainOutcome,
    DagsterScheduleStorageUnavailable,
    append_schedule_audit_event,
    delete_schedule_override,
    execute_audited_schedule_command,
    resolve_schedule_active_claim,
    schedule_overrides,
    upsert_schedule_override,
)
from kortravelmap.api.dagster_schema import (
    DagsterScheduleClaimResolution,
    DagsterScheduleCommandData,
    DagsterScheduleCommandResponse,
)
from kortravelmap.api.response import make_meta
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

pytestmark = pytest.mark.integration

_NAME = "__test_override_schedule__"


def _command_response() -> DagsterScheduleCommandResponse:
    return DagsterScheduleCommandResponse(
        data=DagsterScheduleCommandData(
            status="ok",
            dagster_url="http://dagster.test",
            graphql_url="http://dagster.test/graphql",
            checked_at=datetime.now(UTC),
            schedule_name=_NAME,
            command="start",
            effective_cron_schedule="0 4 * * *",
            schedule_status="RUNNING",
            save_status="not_applicable",
            reload_status="not_requested",
            effective_status="confirmed",
        ),
        meta=make_meta(started_at=perf_counter()),
    )


async def _row(session: AsyncSession, name: str) -> object | None:
    result = await session.execute(
        text(
            """
            SELECT cron_schedule, updated_by, reason, updated_at
            FROM ops.dagster_schedule_overrides
            WHERE schedule_name = :name
            """
        ),
        {"name": name},
    )
    return result.one_or_none()


async def _seed_active_schedule_claim(
    session: AsyncSession,
    *,
    command_id: UUID,
    schedule_name: str,
    command: str = "reset",
    reason: str = "운영 확인",
) -> None:
    await append_schedule_audit_event(
        session,
        command_id=command_id,
        schedule_name=schedule_name,
        command=command,
        phase="requested",
        actor="admin@example.test",
        reason=reason,
        details={"command": command},
    )
    await session.execute(
        text(
            """
            INSERT INTO ops.dagster_schedule_active_claims (
              command_id, schedule_name
            ) VALUES (CAST(:command_id AS uuid), :schedule_name)
            """
        ),
        {
            "command_id": str(command_id),
            "schedule_name": schedule_name,
        },
    )
    await session.commit()


async def _wait_for_lock_waiter(
    engine: AsyncEngine,
    *,
    backend_pid: int,
) -> None:
    for _ in range(500):
        async with AsyncSession(engine) as observer:
            waiting = await observer.scalar(
                text(
                    """
                    SELECT wait_event_type = 'Lock'
                    FROM pg_stat_activity
                    WHERE pid = :backend_pid
                    """
                ),
                {"backend_pid": backend_pid},
            )
        if waiting is True:
            return
        await asyncio.sleep(0.01)
    raise AssertionError(f"backend {backend_pid}가 row lock 대기 상태가 되지 않았습니다.")


async def test_schedule_override_upsert_read_conflict_delete(
    migrated_engine: AsyncEngine,
) -> None:
    async with AsyncSession(migrated_engine, expire_on_commit=False) as session:
        try:
            # INSERT
            await upsert_schedule_override(
                session,
                schedule_name=_NAME,
                cron_schedule="5 4 * * *",
                actor="op-1",
                reason="initial",
            )
            assert (await schedule_overrides(session)).get(_NAME) == "5 4 * * *"
            first = await _row(session, _NAME)
            assert first is not None
            assert (first.cron_schedule, first.updated_by, first.reason) == (
                "5 4 * * *",
                "op-1",
                "initial",
            )

            # ON CONFLICT (schedule_name) DO UPDATE → cron/updated_by/reason/updated_at 갱신
            await upsert_schedule_override(
                session,
                schedule_name=_NAME,
                cron_schedule="15 6 * * *",
                actor="op-2",
                reason="changed",
            )
            assert (await schedule_overrides(session)).get(_NAME) == "15 6 * * *"
            second = await _row(session, _NAME)
            assert second is not None
            assert (second.cron_schedule, second.updated_by, second.reason) == (
                "15 6 * * *",
                "op-2",
                "changed",
            )
            assert second.updated_at >= first.updated_at

            # DELETE
            await delete_schedule_override(session, schedule_name=_NAME)
            assert _NAME not in await schedule_overrides(session)
            assert await _row(session, _NAME) is None
        finally:
            await session.execute(
                text("DELETE FROM ops.dagster_schedule_overrides WHERE schedule_name = :name"),
                {"name": _NAME},
            )
            await session.commit()


async def test_schedule_audit_events_are_append_only_and_correlated(
    migrated_engine: AsyncEngine,
) -> None:
    command_id = uuid4()
    async with AsyncSession(migrated_engine, expire_on_commit=False) as session:
        await _seed_active_schedule_claim(
            session,
            command_id=command_id,
            schedule_name=_NAME,
            command="reset",
            reason="운영 기본값 복귀",
        )
        await append_schedule_audit_event(
            session,
            command_id=command_id,
            schedule_name=_NAME,
            command="reset",
            phase="succeeded",
            actor="admin@example.test",
            reason="운영 기본값 복귀",
            details={
                "effective_status": "confirmed",
                "outcome_certainty": "confirmed",
            },
        )
        result = await session.execute(
            text(
                """
                SELECT command_id::text, command, phase, actor, reason, details
                FROM ops.dagster_schedule_audit_events
                WHERE command_id = CAST(:command_id AS uuid)
                ORDER BY event_id
                """
            ),
            {"command_id": str(command_id)},
        )
        rows = result.all()
        assert [(row.command, row.phase) for row in rows] == [
            ("reset", "requested"),
            ("reset", "succeeded"),
        ]
        assert {row.actor for row in rows} == {"admin@example.test"}
        assert {row.reason for row in rows} == {"운영 기본값 복귀"}
        assert rows[1].details == {
            "effective_status": "confirmed",
            "outcome_certainty": "confirmed",
        }

        with pytest.raises(DBAPIError):
            await session.execute(
                text(
                    "UPDATE ops.dagster_schedule_audit_events "
                    "SET reason = '변조' "
                    "WHERE command_id = CAST(:command_id AS uuid)"
                ),
                {"command_id": str(command_id)},
            )
        await session.rollback()

        with pytest.raises(DBAPIError):
            await session.execute(text("TRUNCATE TABLE ops.dagster_schedule_audit_events"))
        await session.rollback()

        with pytest.raises(DBAPIError):
            await session.execute(
                text(
                    "DELETE FROM ops.dagster_schedule_audit_events "
                    "WHERE command_id = CAST(:command_id AS uuid)"
                ),
                {"command_id": str(command_id)},
            )
        await session.rollback()


async def test_schedule_terminal_audit_rejects_mismatched_request_fields(
    migrated_engine: AsyncEngine,
) -> None:
    command_id = uuid4()
    async with AsyncSession(migrated_engine, expire_on_commit=False) as session:
        await _seed_active_schedule_claim(
            session,
            command_id=command_id,
            schedule_name=_NAME,
            command="start",
            reason="원 요청",
        )

        with pytest.raises(DBAPIError):
            await session.execute(
                text(
                    """
                    INSERT INTO ops.dagster_schedule_audit_events (
                      command_id, schedule_name, command, phase, actor, reason, details
                    ) VALUES (
                      CAST(:command_id AS uuid), :schedule_name, 'stop', 'failed',
                      :actor, :reason, '{}'::jsonb
                    )
                    """
                ),
                {
                    "command_id": str(command_id),
                    "schedule_name": _NAME,
                    "actor": "admin@example.test",
                    "reason": "원 요청",
                },
            )
        await session.rollback()


async def test_schedule_command_idempotency_replays_terminal_result_without_remote_call(
    migrated_engine: AsyncEngine,
) -> None:
    command_id = uuid4()
    remote_calls = 0

    async def _operation() -> DagsterScheduleCommandResponse:
        nonlocal remote_calls
        remote_calls += 1
        return _command_response()

    async with AsyncSession(migrated_engine, expire_on_commit=False) as session:
        first = await execute_audited_schedule_command(
            session,
            schedule_name=_NAME,
            command="start",
            actor="admin@example.test",
            reason="재개",
            request_details={"command": "start"},
            command_id=command_id,
            operation=_operation,
        )
        replay = await execute_audited_schedule_command(
            session,
            schedule_name=_NAME,
            command="start",
            actor="admin@example.test",
            reason="재개",
            request_details={"command": "start"},
            command_id=command_id,
            operation=_operation,
        )

    assert remote_calls == 1
    assert first.data.schedule_status == "RUNNING"
    assert replay.data.schedule_status == "RUNNING"
    assert replay.data.audit_command_id == command_id


async def test_terminal_audit_failure_never_retries_remote_mutation(
    migrated_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    command_id = uuid4()
    schedule_name = f"{_NAME}_terminal_audit_failure"
    remote_calls = 0

    async def _operation() -> DagsterScheduleCommandResponse:
        nonlocal remote_calls
        remote_calls += 1
        return _command_response()

    async def _fail_terminal_audit(*_args: object, **_kwargs: object) -> None:
        raise DagsterScheduleStorageUnavailable("terminal audit unavailable")

    original_append = dagster_schedule_service.append_schedule_audit_event
    monkeypatch.setattr(
        dagster_schedule_service,
        "append_schedule_audit_event",
        _fail_terminal_audit,
    )

    async with AsyncSession(migrated_engine, expire_on_commit=False) as session:
        first = await execute_audited_schedule_command(
            session,
            schedule_name=schedule_name,
            command="start",
            actor="admin@example.test",
            reason="재개",
            request_details={"command": "start"},
            command_id=command_id,
            operation=_operation,
        )
        with pytest.raises(DagsterScheduleIdempotencyConflict):
            await execute_audited_schedule_command(
                session,
                schedule_name=schedule_name,
                command="start",
                actor="admin@example.test",
                reason="재개",
                request_details={"command": "start"},
                command_id=command_id,
                operation=_operation,
            )

        monkeypatch.setattr(
            dagster_schedule_service,
            "append_schedule_audit_event",
            original_append,
        )
        resolved = await resolve_schedule_active_claim(
            session,
            schedule_name=schedule_name,
            command_id=command_id,
            resolution="confirmed_applied",
            actor="admin@example.test",
            reason="Dagster schedule 상태에서 반영 확인",
        )

    assert first.data.audit_status == "terminal_record_failed"
    assert first.data.audit_command_id == command_id
    assert resolved.resolution == "confirmed_applied"
    assert remote_calls == 1


async def test_schedule_active_claim_blocks_new_key_until_terminal(
    migrated_engine: AsyncEngine,
) -> None:
    first_command_id = uuid4()
    second_command_id = uuid4()
    third_command_id = uuid4()
    operation_started = asyncio.Event()
    release_operation = asyncio.Event()
    remote_calls = 0

    async def _blocked_operation() -> DagsterScheduleCommandResponse:
        nonlocal remote_calls
        remote_calls += 1
        operation_started.set()
        await release_operation.wait()
        return _command_response()

    async def _unexpected_operation() -> DagsterScheduleCommandResponse:
        raise AssertionError("active claim 중 새 key remote mutation을 호출하면 안 됩니다.")

    async def _run_first() -> DagsterScheduleCommandResponse:
        async with AsyncSession(migrated_engine, expire_on_commit=False) as session:
            return await execute_audited_schedule_command(
                session,
                schedule_name=_NAME,
                command="start",
                actor="admin@example.test",
                reason="재개",
                request_details={"command": "start"},
                command_id=first_command_id,
                operation=_blocked_operation,
            )

    first_task = asyncio.create_task(_run_first())
    try:
        await asyncio.wait_for(operation_started.wait(), timeout=5)
        async with AsyncSession(migrated_engine, expire_on_commit=False) as session:
            with pytest.raises(DagsterScheduleIdempotencyConflict):
                await execute_audited_schedule_command(
                    session,
                    schedule_name=_NAME,
                    command="stop",
                    actor="admin@example.test",
                    reason="다른 key",
                    request_details={"command": "stop"},
                    command_id=second_command_id,
                    operation=_unexpected_operation,
                )
    finally:
        release_operation.set()
    await asyncio.wait_for(first_task, timeout=5)

    async with AsyncSession(migrated_engine, expire_on_commit=False) as session:
        await execute_audited_schedule_command(
            session,
            schedule_name=_NAME,
            command="stop",
            actor="admin@example.test",
            reason="terminal 후",
            request_details={"command": "stop"},
            command_id=third_command_id,
            operation=_blocked_operation,
        )

    assert remote_calls == 2


async def test_exception_terminal_replays_original_storage_outcome_without_remote_call(
    migrated_engine: AsyncEngine,
) -> None:
    command_id = uuid4()
    remote_calls = 0

    async def _operation() -> DagsterScheduleCommandResponse:
        nonlocal remote_calls
        remote_calls += 1
        raise DagsterScheduleStorageUnavailable("override read unavailable")

    async with AsyncSession(migrated_engine, expire_on_commit=False) as session:
        with pytest.raises(
            DagsterScheduleStorageUnavailable,
            match="override read unavailable",
        ):
            await execute_audited_schedule_command(
                session,
                schedule_name=_NAME,
                command="start",
                actor="admin@example.test",
                reason="재개",
                request_details={"command": "start"},
                command_id=command_id,
                operation=_operation,
            )
        with pytest.raises(
            DagsterScheduleStorageUnavailable,
            match="override read unavailable",
        ):
            await execute_audited_schedule_command(
                session,
                schedule_name=_NAME,
                command="start",
                actor="admin@example.test",
                reason="재개",
                request_details={"command": "start"},
                command_id=command_id,
                operation=_operation,
            )

    assert remote_calls == 1


async def test_unexpected_terminal_replays_as_structured_failure_without_remote_call(
    migrated_engine: AsyncEngine,
) -> None:
    command_id = uuid4()
    remote_calls = 0

    async def _operation() -> DagsterScheduleCommandResponse:
        nonlocal remote_calls
        remote_calls += 1
        raise RuntimeError("unexpected remote result")

    async with AsyncSession(migrated_engine, expire_on_commit=False) as session:
        with pytest.raises(
            DagsterScheduleUncertainOutcome,
            match="unexpected remote result",
        ):
            await execute_audited_schedule_command(
                session,
                schedule_name=_NAME,
                command="start",
                actor="admin@example.test",
                reason="재개",
                request_details={"command": "start"},
                command_id=command_id,
                operation=_operation,
            )
        with pytest.raises(
            DagsterScheduleUncertainOutcome,
            match="unexpected remote result",
        ):
            await execute_audited_schedule_command(
                session,
                schedule_name=_NAME,
                command="start",
                actor="admin@example.test",
                reason="재개",
                request_details={"command": "start"},
                command_id=command_id,
                operation=_operation,
            )

    assert remote_calls == 1


async def test_uncertain_remote_result_replays_same_key_and_blocks_new_key(
    migrated_engine: AsyncEngine,
) -> None:
    command_id = uuid4()
    other_command_id = uuid4()
    schedule_name = f"{_NAME}_uncertain_remote"
    remote_calls = 0

    async def _operation() -> DagsterScheduleCommandResponse:
        nonlocal remote_calls
        remote_calls += 1
        response = _command_response()
        response.data.status = "unavailable"
        response.data.outcome_certainty = "uncertain"
        response.data.effective_status = "unknown"
        response.data.errors = ["response lost after POST"]
        return response

    async def _unexpected_operation() -> DagsterScheduleCommandResponse:
        raise AssertionError("uncertain claim 뒤 새 key로 remote 호출하면 안 됩니다")

    async with AsyncSession(migrated_engine, expire_on_commit=False) as session:
        first = await execute_audited_schedule_command(
            session,
            schedule_name=schedule_name,
            command="run",
            actor="admin@example.test",
            reason="수동 실행",
            request_details={"command": "run"},
            command_id=command_id,
            operation=_operation,
        )
        replay = await execute_audited_schedule_command(
            session,
            schedule_name=schedule_name,
            command="run",
            actor="admin@example.test",
            reason="수동 실행",
            request_details={"command": "run"},
            command_id=command_id,
            operation=_operation,
        )
        with pytest.raises(DagsterScheduleIdempotencyConflict) as conflict:
            await execute_audited_schedule_command(
                session,
                schedule_name=schedule_name,
                command="run",
                actor="admin@example.test",
                reason="수동 실행",
                request_details={"command": "run"},
                command_id=other_command_id,
                operation=_unexpected_operation,
            )

    assert first.data.outcome_certainty == "uncertain"
    assert replay.data.outcome_certainty == "uncertain"
    assert replay.data.audit_status == first.data.audit_status == "recorded"
    assert conflict.value.active_command_id == command_id
    assert remote_calls == 1


async def test_uncertain_claim_requires_append_only_resolution_before_new_command(
    migrated_engine: AsyncEngine,
) -> None:
    command_id = uuid4()
    next_command_id = uuid4()
    schedule_name = f"{_NAME}_manual_resolution"
    remote_calls = 0

    async def _uncertain_operation() -> DagsterScheduleCommandResponse:
        nonlocal remote_calls
        remote_calls += 1
        response = _command_response()
        response.data.status = "unavailable"
        response.data.outcome_certainty = "uncertain"
        response.data.effective_status = "unknown"
        response.data.errors = ["response lost after POST"]
        return response

    async def _confirmed_operation() -> DagsterScheduleCommandResponse:
        nonlocal remote_calls
        remote_calls += 1
        return _command_response()

    async with AsyncSession(migrated_engine, expire_on_commit=False) as session:
        await execute_audited_schedule_command(
            session,
            schedule_name=schedule_name,
            command="run",
            actor="admin@example.test",
            reason="수동 실행",
            request_details={"command": "run"},
            command_id=command_id,
            operation=_uncertain_operation,
        )

        # DB 경계도 resolution 없는 uncertain claim 삭제를 거부한다.
        with pytest.raises(DBAPIError):
            await session.execute(
                text(
                    """
                    DELETE FROM ops.dagster_schedule_active_claims
                    WHERE command_id = CAST(:command_id AS uuid)
                    """
                ),
                {"command_id": str(command_id)},
            )
        await session.rollback()

        with pytest.raises(DagsterScheduleClaimNotFound):
            await resolve_schedule_active_claim(
                session,
                schedule_name=f"{schedule_name}_other",
                command_id=command_id,
                resolution="confirmed_not_applied",
                actor="admin@example.test",
                reason="Dagster run 목록 직접 확인",
            )

        resolved = await resolve_schedule_active_claim(
            session,
            schedule_name=schedule_name,
            command_id=command_id,
            resolution="confirmed_not_applied",
            actor="admin@example.test",
            reason="  Dagster run 목록 직접 확인  ",
        )
        assert resolved.command_id == command_id
        assert resolved.resolution == "confirmed_not_applied"
        assert resolved.reason == "Dagster run 목록 직접 확인"
        assert resolved.replayed is False

        replayed = await resolve_schedule_active_claim(
            session,
            schedule_name=schedule_name,
            command_id=command_id,
            resolution="confirmed_not_applied",
            actor="other-admin@example.test",
            reason=" Dagster run 목록 직접 확인 ",
        )
        assert replayed.replayed is True
        assert replayed.resolution_id == resolved.resolution_id
        assert replayed.resolved_at == resolved.resolved_at
        assert replayed.actor == "admin@example.test"

        with pytest.raises(DagsterScheduleClaimResolutionConflict):
            await resolve_schedule_active_claim(
                session,
                schedule_name=schedule_name,
                command_id=command_id,
                resolution="confirmed_applied",
                actor="admin@example.test",
                reason="Dagster run 목록 직접 확인",
            )
        with pytest.raises(DagsterScheduleClaimResolutionConflict):
            await resolve_schedule_active_claim(
                session,
                schedule_name=schedule_name,
                command_id=command_id,
                resolution="confirmed_not_applied",
                actor="admin@example.test",
                reason="다른 확인 근거",
            )

        stored = (
            await session.execute(
                text(
                    """
                    SELECT resolution, actor, reason,
                           count(*) OVER () AS resolution_count
                    FROM ops.dagster_schedule_claim_resolutions
                    WHERE command_id = CAST(:command_id AS uuid)
                    """
                ),
                {"command_id": str(command_id)},
            )
        ).one()
        assert tuple(stored) == (
            "confirmed_not_applied",
            "admin@example.test",
            "Dagster run 목록 직접 확인",
            1,
        )

        with pytest.raises(DBAPIError):
            await session.execute(
                text(
                    """
                    UPDATE ops.dagster_schedule_claim_resolutions
                    SET reason = '변조'
                    WHERE command_id = CAST(:command_id AS uuid)
                    """
                ),
                {"command_id": str(command_id)},
            )
        await session.rollback()

        await execute_audited_schedule_command(
            session,
            schedule_name=schedule_name,
            command="run",
            actor="admin@example.test",
            reason="확인 후 재실행",
            request_details={"command": "run"},
            command_id=next_command_id,
            operation=_confirmed_operation,
        )

    assert remote_calls == 2


async def test_confirmed_terminal_wins_concurrent_claim_resolution(
    migrated_engine: AsyncEngine,
) -> None:
    command_id = uuid4()
    schedule_name = f"{_NAME}_terminal_wins"
    async with AsyncSession(migrated_engine, expire_on_commit=False) as seed:
        await _seed_active_schedule_claim(
            seed,
            command_id=command_id,
            schedule_name=schedule_name,
            command="reset",
        )

    loop = asyncio.get_running_loop()
    terminal_pid: asyncio.Future[int] = loop.create_future()
    resolution_pid: asyncio.Future[int] = loop.create_future()

    async def _append_terminal() -> None:
        async with AsyncSession(migrated_engine, expire_on_commit=False) as session:
            terminal_pid.set_result(int(await session.scalar(text("SELECT pg_backend_pid()"))))
            await append_schedule_audit_event(
                session,
                command_id=command_id,
                schedule_name=schedule_name,
                command="reset",
                phase="succeeded",
                actor="admin@example.test",
                reason="운영 확인",
                details={"outcome_certainty": "confirmed"},
            )

    async def _resolve_claim() -> DagsterScheduleClaimResolution:
        async with AsyncSession(migrated_engine, expire_on_commit=False) as session:
            resolution_pid.set_result(int(await session.scalar(text("SELECT pg_backend_pid()"))))
            return await resolve_schedule_active_claim(
                session,
                schedule_name=schedule_name,
                command_id=command_id,
                resolution="confirmed_not_applied",
                actor="admin@example.test",
                reason="Dagster에서 미반영 확인",
            )

    async with AsyncSession(migrated_engine, expire_on_commit=False) as blocker:
        await blocker.execute(
            text(
                """
                SELECT command_id
                FROM ops.dagster_schedule_active_claims
                WHERE command_id = CAST(:command_id AS uuid)
                FOR UPDATE
                """
            ),
            {"command_id": str(command_id)},
        )
        terminal_task = asyncio.create_task(_append_terminal())
        await _wait_for_lock_waiter(
            migrated_engine,
            backend_pid=await terminal_pid,
        )
        resolution_task = asyncio.create_task(_resolve_claim())
        await _wait_for_lock_waiter(
            migrated_engine,
            backend_pid=await resolution_pid,
        )
        await blocker.commit()

    terminal_result, resolution_result = await asyncio.gather(
        terminal_task,
        resolution_task,
        return_exceptions=True,
    )
    assert terminal_result is None
    assert isinstance(resolution_result, DagsterScheduleClaimResolutionConflict)

    async with AsyncSession(migrated_engine) as session:
        terminal_count = await session.scalar(
            text(
                """
                SELECT count(*)
                FROM ops.dagster_schedule_audit_events
                WHERE command_id = CAST(:command_id AS uuid)
                  AND phase IN ('succeeded','failed')
                """
            ),
            {"command_id": str(command_id)},
        )
        resolution_count = await session.scalar(
            text(
                """
                SELECT count(*)
                FROM ops.dagster_schedule_claim_resolutions
                WHERE command_id = CAST(:command_id AS uuid)
                """
            ),
            {"command_id": str(command_id)},
        )
    assert (terminal_count, resolution_count) == (1, 0)


async def test_concurrent_identical_claim_resolution_replays_single_row(
    migrated_engine: AsyncEngine,
) -> None:
    command_id = uuid4()
    schedule_name = f"{_NAME}_concurrent_resolution_replay"
    async with AsyncSession(migrated_engine, expire_on_commit=False) as seed:
        await _seed_active_schedule_claim(
            seed,
            command_id=command_id,
            schedule_name=schedule_name,
            command="reset",
        )

    async def _resolve(actor: str) -> DagsterScheduleClaimResolution:
        async with AsyncSession(migrated_engine, expire_on_commit=False) as session:
            return await resolve_schedule_active_claim(
                session,
                schedule_name=schedule_name,
                command_id=command_id,
                resolution="confirmed_not_applied",
                actor=actor,
                reason=" Dagster에서 미반영 확인 ",
            )

    first, second = await asyncio.gather(
        _resolve("admin-a@example.test"),
        _resolve("admin-b@example.test"),
    )

    assert {first.replayed, second.replayed} == {False, True}
    assert first.resolution_id == second.resolution_id
    assert first.resolved_at == second.resolved_at
    assert first.actor == second.actor
    async with AsyncSession(migrated_engine) as session:
        resolution_count = await session.scalar(
            text(
                """
                SELECT count(*)
                FROM ops.dagster_schedule_claim_resolutions
                WHERE command_id = CAST(:command_id AS uuid)
                """
            ),
            {"command_id": str(command_id)},
        )
    assert resolution_count == 1


async def test_claim_resolution_wins_concurrent_late_terminal(
    migrated_engine: AsyncEngine,
) -> None:
    command_id = uuid4()
    schedule_name = f"{_NAME}_resolution_wins"
    async with AsyncSession(migrated_engine, expire_on_commit=False) as seed:
        await _seed_active_schedule_claim(
            seed,
            command_id=command_id,
            schedule_name=schedule_name,
            command="reset",
        )

    loop = asyncio.get_running_loop()
    terminal_pid: asyncio.Future[int] = loop.create_future()
    resolution_pid: asyncio.Future[int] = loop.create_future()

    async def _append_terminal() -> None:
        async with AsyncSession(migrated_engine, expire_on_commit=False) as session:
            terminal_pid.set_result(int(await session.scalar(text("SELECT pg_backend_pid()"))))
            await append_schedule_audit_event(
                session,
                command_id=command_id,
                schedule_name=schedule_name,
                command="reset",
                phase="succeeded",
                actor="admin@example.test",
                reason="운영 확인",
                details={"outcome_certainty": "confirmed"},
            )

    async def _resolve_claim() -> DagsterScheduleClaimResolution:
        async with AsyncSession(migrated_engine, expire_on_commit=False) as session:
            resolution_pid.set_result(int(await session.scalar(text("SELECT pg_backend_pid()"))))
            return await resolve_schedule_active_claim(
                session,
                schedule_name=schedule_name,
                command_id=command_id,
                resolution="confirmed_not_applied",
                actor="admin@example.test",
                reason="Dagster에서 미반영 확인",
            )

    async with AsyncSession(migrated_engine, expire_on_commit=False) as blocker:
        await blocker.execute(
            text(
                """
                SELECT command_id
                FROM ops.dagster_schedule_active_claims
                WHERE command_id = CAST(:command_id AS uuid)
                FOR UPDATE
                """
            ),
            {"command_id": str(command_id)},
        )
        resolution_task = asyncio.create_task(_resolve_claim())
        await _wait_for_lock_waiter(
            migrated_engine,
            backend_pid=await resolution_pid,
        )
        terminal_task = asyncio.create_task(_append_terminal())
        await _wait_for_lock_waiter(
            migrated_engine,
            backend_pid=await terminal_pid,
        )
        await blocker.commit()

    resolution_result, terminal_result = await asyncio.gather(
        resolution_task,
        terminal_task,
        return_exceptions=True,
    )
    assert isinstance(resolution_result, DagsterScheduleClaimResolution)
    assert resolution_result.replayed is False
    assert isinstance(terminal_result, DagsterScheduleStorageUnavailable)

    async with AsyncSession(migrated_engine) as session:
        terminal_count = await session.scalar(
            text(
                """
                SELECT count(*)
                FROM ops.dagster_schedule_audit_events
                WHERE command_id = CAST(:command_id AS uuid)
                  AND phase IN ('succeeded','failed')
                """
            ),
            {"command_id": str(command_id)},
        )
        resolution_count = await session.scalar(
            text(
                """
                SELECT count(*)
                FROM ops.dagster_schedule_claim_resolutions
                WHERE command_id = CAST(:command_id AS uuid)
                """
            ),
            {"command_id": str(command_id)},
        )
    assert (terminal_count, resolution_count) == (0, 1)
