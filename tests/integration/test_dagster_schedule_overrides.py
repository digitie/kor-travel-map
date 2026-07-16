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
from uuid import uuid4

import pytest
from kortravelmap.api import dagster_schedule_service
from kortravelmap.api.dagster_schedule_service import (
    DagsterScheduleIdempotencyConflict,
    DagsterScheduleReplayedFailure,
    DagsterScheduleStorageUnavailable,
    append_schedule_audit_event,
    delete_schedule_override,
    execute_audited_schedule_command,
    schedule_overrides,
    upsert_schedule_override,
)
from kortravelmap.api.dagster_schema import (
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
                text(
                    "DELETE FROM ops.dagster_schedule_overrides "
                    "WHERE schedule_name = :name"
                ),
                {"name": _NAME},
            )
            await session.commit()


async def test_schedule_audit_events_are_append_only_and_correlated(
    migrated_engine: AsyncEngine,
) -> None:
    command_id = uuid4()
    async with AsyncSession(migrated_engine, expire_on_commit=False) as session:
        await append_schedule_audit_event(
            session,
            command_id=command_id,
            schedule_name=_NAME,
            command="reset",
            phase="requested",
            actor="admin@example.test",
            reason="운영 기본값 복귀",
            details={},
        )
        await append_schedule_audit_event(
            session,
            command_id=command_id,
            schedule_name=_NAME,
            command="reset",
            phase="succeeded",
            actor="admin@example.test",
            reason="운영 기본값 복귀",
            details={"effective_status": "confirmed"},
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
        assert rows[1].details == {"effective_status": "confirmed"}

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
            await session.execute(
                text("TRUNCATE TABLE ops.dagster_schedule_audit_events")
            )
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
        await append_schedule_audit_event(
            session,
            command_id=command_id,
            schedule_name=_NAME,
            command="start",
            phase="requested",
            actor="admin@example.test",
            reason="원 요청",
            details={"command": "start"},
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

    assert first.data.audit_status == "terminal_record_failed"
    assert first.data.audit_command_id == command_id
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
        with pytest.raises(RuntimeError, match="unexpected remote result"):
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
            DagsterScheduleReplayedFailure,
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
