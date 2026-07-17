"""Dagster schedule override persistence and mutation application service."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from time import perf_counter
from typing import Final, Literal
from uuid import UUID

import httpx
from kortravelmap.providers.feature_operation_registry import (
    ADMIN_MANUAL_TRIGGER_TAG,
    FeatureOperationRegistryError,
    feature_operation_launch_tags,
    resolve_feature_operation_launch,
    resolve_feature_operation_runtime_snapshot,
    validate_feature_operation_identity,
)
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.api import dagster_graphql
from kortravelmap.api.dagster_graphql import DagsterUrls, JsonDict
from kortravelmap.api.dagster_schema import (
    DagsterRepository,
    DagsterSchedule,
    DagsterScheduleClaimResolution,
    DagsterScheduleCommandData,
    DagsterScheduleCommandRequest,
    DagsterScheduleCommandResponse,
    DagsterScheduleOverrideRequest,
)
from kortravelmap.api.response import make_meta
from kortravelmap.api.settings import ApiSettings

__all__ = [
    "DagsterScheduleValidationError",
    "DagsterScheduleStorageUnavailable",
    "DagsterScheduleIdempotencyConflict",
    "DagsterScheduleUncertainOutcome",
    "DagsterScheduleClaimNotFound",
    "DagsterScheduleClaimResolutionConflict",
    "append_schedule_audit_event",
    "AuditedScheduleOperation",
    "ScheduleCommand",
    "ScheduleMutationGuard",
    "delete_schedule_override",
    "execute_audited_schedule_command",
    "mutate_schedule_state",
    "reset_schedule_default",
    "resolve_schedule_active_claim",
    "run_schedule_now",
    "schedule_overrides",
    "upsert_schedule_override",
    "update_schedule",
]

ScheduleCommand = Literal["update", "default", "start", "stop", "reset", "run"]
ScheduleMutationGuard = Callable[[], Awaitable[None]]
AuditedScheduleOperation = Callable[
    [ScheduleMutationGuard], Awaitable[DagsterScheduleCommandResponse]
]
_SCHEDULE_OPERATION_TIMEOUT_SECONDS: Final = 120.0


class DagsterScheduleValidationError(ValueError):
    """운영자 schedule 입력이 실행 전에 거부되었음을 나타낸다."""


class DagsterScheduleStorageUnavailable(RuntimeError):
    """schedule override/audit 영속 저장소를 안전하게 사용할 수 없다."""


class DagsterScheduleIdempotencyConflict(RuntimeError):
    """같은 idempotency key가 다른 요청이거나 결과 불명 상태다."""

    def __init__(
        self,
        message: str,
        *,
        command_id: UUID,
        active_command_id: UUID | None = None,
        active_claim_resolvable_at: datetime | None = None,
    ) -> None:
        super().__init__(message)
        self.command_id = command_id
        self.active_command_id = active_command_id
        self.active_claim_resolvable_at = active_claim_resolvable_at


class DagsterScheduleUncertainOutcome(RuntimeError):
    """외부 반영 여부를 확정할 수 없어 운영자 확인이 필요한 명령 결과."""

    def __init__(
        self,
        message: str,
        *,
        command_id: UUID,
        active_command_id: UUID | None = None,
    ) -> None:
        super().__init__(message)
        self.command_id = command_id
        self.active_command_id = active_command_id


class DagsterScheduleClaimNotFound(LookupError):
    """지정한 schedule/command의 감사 claim이 존재하지 않는다."""


class DagsterScheduleClaimResolutionConflict(RuntimeError):
    """claim이 이미 해제됐거나 결과가 불명 상태가 아니어서 해제할 수 없다."""


_LOG = logging.getLogger(__name__)

_DAGSTER_SCHEDULES_QUERY = """
query KorTravelMapDagsterSchedules {
  repositoriesOrError {
    __typename
    ... on RepositoryConnection {
      nodes {
        name
        location { name }
        schedules {
          name
          description
          pipelineName
          mode
          cronSchedule
          executionTimezone
          defaultStatus
          canReset
          scheduleState {
            id
            selectorId
            status
            repositoryName
            repositoryLocationName
          }
        }
      }
    }
    ... on PythonError {
      message
      stack
      className
    }
  }
}
"""

_DAGSTER_START_SCHEDULE_MUTATION = """
mutation KorTravelMapStartSchedule($selector: ScheduleSelector!) {
  startSchedule(scheduleSelector: $selector) {
    __typename
    ... on ScheduleStateResult {
      scheduleState { id selectorId status repositoryName repositoryLocationName }
    }
    ... on ScheduleNotFoundError { message }
    ... on UnauthorizedError { message }
    ... on PythonError { message stack className }
  }
}
"""

_DAGSTER_STOP_SCHEDULE_MUTATION = """
mutation KorTravelMapStopSchedule(
  $id: String, $originId: String, $selectorId: String
) {
  stopRunningSchedule(
    id: $id,
    scheduleOriginId: $originId,
    scheduleSelectorId: $selectorId
  ) {
    __typename
    ... on ScheduleStateResult {
      scheduleState { id selectorId status repositoryName repositoryLocationName }
    }
    ... on ScheduleNotFoundError { message }
    ... on UnauthorizedError { message }
    ... on PythonError { message stack className }
  }
}
"""

_DAGSTER_RESET_SCHEDULE_MUTATION = """
mutation KorTravelMapResetSchedule($selector: ScheduleSelector!) {
  resetSchedule(scheduleSelector: $selector) {
    __typename
    ... on ScheduleStateResult {
      scheduleState { id selectorId status repositoryName repositoryLocationName }
    }
    ... on ScheduleNotFoundError { message }
    ... on UnauthorizedError { message }
    ... on PythonError { message stack className }
  }
}
"""

_DAGSTER_RELOAD_LOCATION_MUTATION = """
mutation KorTravelMapReloadLocation($repositoryLocationName: String!) {
  reloadRepositoryLocation(repositoryLocationName: $repositoryLocationName) {
    __typename
    ... on WorkspaceLocationEntry {
      id
      name
      loadStatus
      locationOrLoadError {
        __typename
        ... on RepositoryLocation { name }
        ... on PythonError { message stack className }
      }
    }
    ... on ReloadNotSupported {
      message
    }
    ... on RepositoryLocationNotFound {
      message
    }
    ... on PythonError {
      message
      stack
      className
    }
  }
}
"""

_DAGSTER_LAUNCH_RUN_MUTATION = """
mutation KorTravelMapLaunchRun($executionParams: ExecutionParams!) {
  launchRun(executionParams: $executionParams) {
    __typename
    ... on LaunchRunSuccess {
      run { runId status jobName startTime endTime updateTime tags { key value } }
    }
    ... on RunConfigValidationInvalid {
      pipelineName
      errors { message }
    }
    ... on PipelineNotFoundError {
      message
      pipelineName
      repositoryName
      repositoryLocationName
    }
    ... on UnauthorizedError { message }
    ... on PythonError { message stack className }
  }
}
"""


_MIN_CRON_MINUTE_STEP: Final[int] = 10


def _admin_feature_operation_launch(
    job_name: str,
) -> tuple[dict[str, object], dict[str, str]]:
    """등록 feature job의 canonical manual run config/tag를 만든 뒤 자체 검증한다."""
    runtime_snapshot = resolve_feature_operation_runtime_snapshot()
    launch = resolve_feature_operation_launch(
        job_name=job_name,
        runtime_snapshot=runtime_snapshot,
    )
    if launch is None:
        return {}, {}
    identity, run_config = launch
    tags = {
        **feature_operation_launch_tags(identity, trigger_kind="manual"),
        ADMIN_MANUAL_TRIGGER_TAG: "admin-ui",
    }
    validate_feature_operation_identity(
        job_name=job_name,
        selected_asset_keys=identity.asset_keys,
        run_config=run_config,
        tags=tags,
    )
    return run_config, tags


def _cron_part_is_valid(part: str, *, min_value: int, max_value: int) -> bool:
    if part == "*":
        return True
    for segment in part.split(","):
        if not segment:
            return False
        base, _, step = segment.partition("/")
        if step and (not step.isdigit() or int(step) <= 0):
            return False
        if base == "*":
            continue
        if "-" in base:
            start, end = base.split("-", 1)
            if not start.isdigit() or not end.isdigit():
                return False
            start_value = int(start)
            end_value = int(end)
            if start_value > end_value:
                return False
            if start_value < min_value or end_value > max_value:
                return False
            continue
        if not base.isdigit():
            return False
        value = int(base)
        if value < min_value or value > max_value:
            return False
    return True


def _validate_cron_schedule(cron_schedule: str) -> str:
    cron = " ".join(cron_schedule.strip().split())
    parts = cron.split(" ")
    if len(parts) != 5:
        raise ValueError("cron은 분 시 일 월 요일 5개 필드여야 합니다.")
    ranges = (
        (0, 59),
        (0, 23),
        (1, 31),
        (1, 12),
        (0, 7),
    )
    for part, (min_value, max_value) in zip(parts, ranges, strict=True):
        if not _cron_part_is_valid(part, min_value=min_value, max_value=max_value):
            raise ValueError(f"cron 필드 범위가 올바르지 않습니다: {part}")
    # 운영자 override 최소 주기 가드(#613): 분 필드는 0~59 단일 고정값(시간당 1회 이하)
    # 또는 ``*/N``(N>=10, 즉 10분 이상 주기)만 허용한다 → 월간·대용량 작업을 매분/매5분으로
    # escalate하는 runaway는 막되, 정당한 10분 주기(예: 고속도로 교통공지 notice, #617)는
    # 허용한다. ``*``·범위·목록·``*/N``(N<10)은 거부.
    minute_field = parts[0]
    minute_ok = (minute_field.isdigit() and 0 <= int(minute_field) <= 59) or (
        minute_field.startswith("*/")
        and minute_field[2:].isdigit()
        and int(minute_field[2:]) >= _MIN_CRON_MINUTE_STEP
    )
    if not minute_ok:
        raise ValueError(
            f"분 필드는 0~59 단일 값 또는 '*/N'(N>={_MIN_CRON_MINUTE_STEP})이어야 합니다 "
            "(과도한 고빈도 방지). '*', 범위·목록, '*/N'(N<10)은 허용하지 않습니다."
        )
    return cron


async def schedule_overrides(
    session: AsyncSession,
) -> dict[str, str]:
    try:
        result = await session.execute(
            text(
                """
                SELECT schedule_name, cron_schedule
                FROM ops.dagster_schedule_overrides
                """
            )
        )
    except SQLAlchemyError as exc:
        await session.rollback()
        raise DagsterScheduleStorageUnavailable(
            "schedule override 저장소를 조회할 수 없습니다."
        ) from exc
    return {str(row.schedule_name): str(row.cron_schedule) for row in result}


async def upsert_schedule_override(
    session: AsyncSession,
    *,
    schedule_name: str,
    cron_schedule: str,
    actor: str,
    reason: str | None,
) -> None:
    try:
        await session.execute(
            text(
                """
            INSERT INTO ops.dagster_schedule_overrides (
              schedule_name, cron_schedule, updated_by, reason, metadata
            )
            VALUES (:schedule_name, :cron_schedule, :actor, :reason, '{}'::jsonb)
            ON CONFLICT (schedule_name) DO UPDATE
            SET cron_schedule = EXCLUDED.cron_schedule,
                updated_by = EXCLUDED.updated_by,
                reason = EXCLUDED.reason,
                updated_at = now()
                """
            ),
            {
                "schedule_name": schedule_name,
                "cron_schedule": cron_schedule,
                "actor": actor,
                "reason": reason,
            },
        )
        await session.commit()
    except SQLAlchemyError as exc:
        await session.rollback()
        raise DagsterScheduleStorageUnavailable("schedule override를 저장할 수 없습니다.") from exc


async def append_schedule_audit_event(
    session: AsyncSession,
    *,
    command_id: UUID,
    schedule_name: str,
    command: ScheduleCommand,
    phase: Literal["requested", "succeeded", "failed"],
    actor: str,
    reason: str | None,
    details: dict[str, object],
    release_active_claim: bool = True,
) -> None:
    """schedule 명령 감사 이벤트를 덮어쓰기 없이 1행 추가한다."""

    try:
        if phase != "requested":
            active_claim = await session.execute(
                text(
                    """
                    SELECT command_id
                    FROM ops.dagster_schedule_active_claims
                    WHERE command_id = CAST(:command_id AS uuid)
                      AND schedule_name = :schedule_name
                    FOR UPDATE
                    """
                ),
                {
                    "command_id": str(command_id),
                    "schedule_name": schedule_name,
                },
            )
            if active_claim.scalar_one_or_none() is None:
                await session.rollback()
                raise DagsterScheduleStorageUnavailable(
                    "schedule terminal 감사 이벤트에 대응하는 활성 claim이 없습니다."
                )
        await session.execute(
            text(
                """
            INSERT INTO ops.dagster_schedule_audit_events (
              command_id, schedule_name, command, phase, actor, reason, details
            ) VALUES (
              CAST(:command_id AS uuid), :schedule_name, :command, :phase,
              :actor, :reason, CAST(:details AS jsonb)
            )
                """
            ),
            {
                "command_id": str(command_id),
                "schedule_name": schedule_name,
                "command": command,
                "phase": phase,
                "actor": actor,
                "reason": reason,
                "details": json.dumps(details, ensure_ascii=False, sort_keys=True),
            },
        )
        if phase != "requested" and release_active_claim:
            await session.execute(
                text(
                    """
                    DELETE FROM ops.dagster_schedule_active_claims
                    WHERE command_id = CAST(:command_id AS uuid)
                      AND schedule_name = :schedule_name
                    """
                ),
                {
                    "command_id": str(command_id),
                    "schedule_name": schedule_name,
                },
            )
        await session.commit()
    except SQLAlchemyError as exc:
        await session.rollback()
        raise DagsterScheduleStorageUnavailable(
            "schedule 감사 이벤트를 저장할 수 없습니다."
        ) from exc


async def _claim_schedule_command(
    session: AsyncSession,
    *,
    command_id: UUID,
    schedule_name: str,
    command: ScheduleCommand,
    actor: str,
    reason: str | None,
    request_details: dict[str, object],
) -> DagsterScheduleCommandResponse | None:
    """idempotency key를 durable하게 선점하고 완료 응답이면 재생한다."""

    try:
        # active claim INSERT의 unique-index 대기가 길어져도 lease clock은 lock 해제 뒤
        # 시작돼야 한다. schedule 단위 xact lock을 먼저 잡으면 column default가 대기
        # 전에 평가되어 이미 만료된 claim이 생성되는 경로를 닫을 수 있다.
        await session.execute(
            text(
                """
                SELECT pg_advisory_xact_lock(
                  hashtextextended(
                    'ops.dagster_schedule_active_claims:' || :schedule_name,
                    0
                  )
                )
                """
            ),
            {"schedule_name": schedule_name},
        )
        inserted = await session.execute(
            text(
                """
                INSERT INTO ops.dagster_schedule_audit_events (
                  command_id, schedule_name, command, phase, actor, reason, details
                ) VALUES (
                  CAST(:command_id AS uuid), :schedule_name, :command, 'requested',
                  :actor, :reason, CAST(:details AS jsonb)
                )
                ON CONFLICT (command_id) WHERE phase = 'requested'
                DO NOTHING
                RETURNING event_id
                """
            ),
            {
                "command_id": str(command_id),
                "schedule_name": schedule_name,
                "command": command,
                "actor": actor,
                "reason": reason,
                "details": json.dumps(
                    request_details,
                    ensure_ascii=False,
                    sort_keys=True,
                ),
            },
        )
        inserted_event_id = inserted.scalar_one_or_none()
        if inserted_event_id is not None:
            claimed = await session.execute(
                text(
                    """
                    INSERT INTO ops.dagster_schedule_active_claims (
                      command_id, schedule_name
                    ) VALUES (
                      CAST(:command_id AS uuid), :schedule_name
                    )
                    ON CONFLICT (schedule_name) DO NOTHING
                    RETURNING command_id
                    """
                ),
                {
                    "command_id": str(command_id),
                    "schedule_name": schedule_name,
                },
            )
            if claimed.scalar_one_or_none() is None:
                active = await session.execute(
                    text(
                        """
                        SELECT command_id, resolvable_after,
                               operation_finished_at IS NOT NULL
                                 OR resolvable_after <= clock_timestamp()
                                 AS is_resolvable
                        FROM ops.dagster_schedule_active_claims
                        WHERE schedule_name = :schedule_name
                        """
                    ),
                    {"schedule_name": schedule_name},
                )
                active_row = active.one_or_none()
                active_command_id = (
                    UUID(str(active_row.command_id))
                    if active_row is not None and bool(active_row.is_resolvable)
                    else None
                )
                active_claim_resolvable_at = (
                    active_row.resolvable_after if active_row is not None else None
                )
                await session.rollback()
                raise DagsterScheduleIdempotencyConflict(
                    "이 schedule의 이전 명령이 실행 중이거나 결과가 확정되지 않았습니다. "
                    "같은 키로 상태를 다시 확인하세요"
                    + (
                        f" (active_command_id={active_command_id})"
                        if active_command_id is not None
                        else ""
                    ),
                    command_id=command_id,
                    active_command_id=active_command_id,
                    active_claim_resolvable_at=active_claim_resolvable_at,
                )
            await session.commit()
            return None
        existing = await session.execute(
            text(
                """
                SELECT schedule_name, command, phase, actor, reason, details
                FROM ops.dagster_schedule_audit_events
                WHERE command_id = CAST(:command_id AS uuid)
                ORDER BY event_id
                """
            ),
            {"command_id": str(command_id)},
        )
        rows = list(existing)
        active = await session.execute(
            text(
                """
                SELECT command_id, resolvable_after,
                       operation_finished_at IS NOT NULL
                         OR resolvable_after <= clock_timestamp()
                         AS is_resolvable
                FROM ops.dagster_schedule_active_claims
                WHERE command_id = CAST(:command_id AS uuid)
                  AND schedule_name = :schedule_name
                """
            ),
            {
                "command_id": str(command_id),
                "schedule_name": schedule_name,
            },
        )
        active_row = active.one_or_none()
        active_command_id = (
            UUID(str(active_row.command_id))
            if active_row is not None and bool(active_row.is_resolvable)
            else None
        )
        active_claim_resolvable_at = active_row.resolvable_after if active_row is not None else None
        await session.commit()
    except SQLAlchemyError as exc:
        await session.rollback()
        raise DagsterScheduleStorageUnavailable(
            "schedule 명령 idempotency 상태를 저장할 수 없습니다."
        ) from exc

    requested = next((row for row in rows if row.phase == "requested"), None)
    if requested is None:
        raise DagsterScheduleIdempotencyConflict(
            "idempotency key의 요청 이벤트를 찾을 수 없습니다.",
            command_id=command_id,
        )
    if (
        str(requested.schedule_name) != schedule_name
        or str(requested.command) != command
        or str(requested.actor) != actor
        or requested.reason != reason
        or dict(requested.details) != request_details
    ):
        raise DagsterScheduleIdempotencyConflict(
            "같은 Idempotency-Key를 다른 schedule 명령에 재사용할 수 없습니다.",
            command_id=command_id,
        )
    terminal = next(
        (row for row in reversed(rows) if row.phase in {"succeeded", "failed"}),
        None,
    )
    if terminal is None:
        raise DagsterScheduleIdempotencyConflict(
            "이 schedule 명령은 실행 중이거나 결과 확인이 필요합니다. 새 키로 재실행하지 마세요.",
            command_id=command_id,
            active_command_id=active_command_id,
            active_claim_resolvable_at=active_claim_resolvable_at,
        )
    if (
        str(terminal.schedule_name) != str(requested.schedule_name)
        or str(terminal.command) != str(requested.command)
        or str(terminal.actor) != str(requested.actor)
        or terminal.reason != requested.reason
    ):
        raise DagsterScheduleIdempotencyConflict(
            "저장된 schedule terminal 이벤트가 원 요청과 일치하지 않습니다.",
            command_id=command_id,
        )
    terminal_details = dict(terminal.details)
    if terminal_details.get("outcome") == "exception":
        message = str(terminal_details.get("message") or "schedule 명령이 예외로 실패했습니다.")
        exception_kind = terminal_details.get("exception_kind")
        if exception_kind == "validation":
            raise DagsterScheduleValidationError(message)
        if exception_kind == "storage_unavailable":
            raise DagsterScheduleStorageUnavailable(message)
        raise DagsterScheduleUncertainOutcome(
            message,
            command_id=command_id,
            active_command_id=command_id,
        )
    try:
        data = DagsterScheduleCommandData.model_validate(terminal_details)
    except ValueError as exc:
        raise DagsterScheduleIdempotencyConflict(
            "저장된 schedule 명령 결과를 해석할 수 없습니다.",
            command_id=command_id,
        ) from exc
    data.audit_command_id = command_id
    return _schedule_command_response(data, started_at=perf_counter())


def _claim_resolution_from_row(
    row: object,
    *,
    schedule_name: str,
    resolution: Literal["confirmed_applied", "confirmed_not_applied"],
    normalized_reason: str,
    replayed: bool,
) -> DagsterScheduleClaimResolution:
    row_schedule_name = str(getattr(row, "schedule_name"))
    row_resolution = str(getattr(row, "resolution"))
    row_reason = str(getattr(row, "reason"))
    if (
        row_schedule_name != schedule_name
        or row_resolution != resolution
        or row_reason != normalized_reason
    ):
        raise DagsterScheduleClaimResolutionConflict(
            "이미 기록된 claim 해제 결과와 resolution 또는 사유가 다릅니다."
        )
    return DagsterScheduleClaimResolution(
        resolution_id=int(getattr(row, "resolution_id")),
        command_id=UUID(str(getattr(row, "command_id"))),
        schedule_name=row_schedule_name,
        resolution=resolution,
        actor=str(getattr(row, "actor")),
        reason=row_reason,
        resolved_at=getattr(row, "created_at"),
        replayed=replayed,
    )


async def _existing_claim_resolution(
    session: AsyncSession,
    *,
    command_id: UUID,
) -> object | None:
    result = await session.execute(
        text(
            """
            SELECT resolution_id, command_id, schedule_name, resolution,
                   actor, reason, created_at
            FROM ops.dagster_schedule_claim_resolutions
            WHERE command_id = CAST(:command_id AS uuid)
            """
        ),
        {"command_id": str(command_id)},
    )
    return result.one_or_none()


async def _mark_schedule_claim_operation_finished(
    session: AsyncSession,
    *,
    command_id: UUID,
    schedule_name: str,
) -> None:
    """외부 호출 종료를 DB clock으로 단방향 기록해 안전한 claim 해제를 허용한다."""

    try:
        updated = await session.execute(
            text(
                """
                UPDATE ops.dagster_schedule_active_claims
                SET operation_finished_at = clock_timestamp()
                WHERE command_id = CAST(:command_id AS uuid)
                  AND schedule_name = :schedule_name
                  AND operation_finished_at IS NULL
                RETURNING command_id
                """
            ),
            {
                "command_id": str(command_id),
                "schedule_name": schedule_name,
            },
        )
        if updated.scalar_one_or_none() is None:
            existing = await session.execute(
                text(
                    """
                    SELECT operation_finished_at IS NOT NULL
                    FROM ops.dagster_schedule_active_claims
                    WHERE command_id = CAST(:command_id AS uuid)
                      AND schedule_name = :schedule_name
                    """
                ),
                {
                    "command_id": str(command_id),
                    "schedule_name": schedule_name,
                },
            )
            if existing.scalar_one_or_none() is not True:
                raise DagsterScheduleStorageUnavailable(
                    "schedule active claim의 외부 호출 종료를 기록할 수 없습니다."
                )
        await session.commit()
    except DagsterScheduleStorageUnavailable:
        await session.rollback()
        raise
    except SQLAlchemyError as exc:
        await session.rollback()
        raise DagsterScheduleStorageUnavailable(
            "schedule active claim의 외부 호출 종료를 기록할 수 없습니다."
        ) from exc


async def _assert_schedule_claim_mutation_allowed(
    session: AsyncSession,
    *,
    command_id: UUID,
    schedule_name: str,
) -> None:
    """실제 side effect 직전 claim 소유권과 아직 유효한 lease를 확인한다."""

    try:
        allowed = await session.scalar(
            text(
                """
                SELECT EXISTS (
                  SELECT 1
                  FROM ops.dagster_schedule_active_claims
                  WHERE command_id = CAST(:command_id AS uuid)
                    AND schedule_name = :schedule_name
                    AND operation_finished_at IS NULL
                    AND resolvable_after > clock_timestamp()
                )
                """
            ),
            {
                "command_id": str(command_id),
                "schedule_name": schedule_name,
            },
        )
        await session.rollback()
    except SQLAlchemyError as exc:
        await session.rollback()
        raise DagsterScheduleStorageUnavailable(
            "schedule mutation 직전 active claim을 확인할 수 없습니다."
        ) from exc
    if allowed is not True:
        raise DagsterScheduleUncertainOutcome(
            "schedule active claim lease가 만료되거나 해제되어 기존 mutation을 중단했습니다.",
            command_id=command_id,
            active_command_id=None,
        )


async def resolve_schedule_active_claim(
    session: AsyncSession,
    *,
    schedule_name: str,
    command_id: UUID,
    resolution: Literal["confirmed_applied", "confirmed_not_applied"],
    actor: str,
    reason: str,
) -> DagsterScheduleClaimResolution:
    """운영자가 외부 상태를 확인한 불명 claim을 감사 이력과 함께 해제한다."""

    normalized_reason = reason.strip()
    if not normalized_reason:
        raise DagsterScheduleValidationError("claim 해제 사유를 입력하세요.")
    try:
        existing_resolution = await _existing_claim_resolution(
            session,
            command_id=command_id,
        )
        if existing_resolution is not None:
            replay = _claim_resolution_from_row(
                existing_resolution,
                schedule_name=schedule_name,
                resolution=resolution,
                normalized_reason=normalized_reason,
                replayed=True,
            )
            await session.commit()
            return replay

        claim_result = await session.execute(
            text(
                """
                SELECT command_id, operation_finished_at, resolvable_after,
                       operation_finished_at IS NOT NULL
                         OR resolvable_after <= clock_timestamp()
                         AS is_resolvable
                FROM ops.dagster_schedule_active_claims
                WHERE command_id = CAST(:command_id AS uuid)
                  AND schedule_name = :schedule_name
                FOR UPDATE
                """
            ),
            {
                "command_id": str(command_id),
                "schedule_name": schedule_name,
            },
        )
        claim_row = claim_result.one_or_none()
        existing_resolution = await _existing_claim_resolution(
            session,
            command_id=command_id,
        )
        if existing_resolution is not None:
            replay = _claim_resolution_from_row(
                existing_resolution,
                schedule_name=schedule_name,
                resolution=resolution,
                normalized_reason=normalized_reason,
                replayed=True,
            )
            await session.commit()
            return replay
        if claim_row is None:
            known_result = await session.execute(
                text(
                    """
                    SELECT EXISTS (
                      SELECT 1
                      FROM ops.dagster_schedule_audit_events
                      WHERE command_id = CAST(:command_id AS uuid)
                        AND schedule_name = :schedule_name
                    ) OR EXISTS (
                      SELECT 1
                      FROM ops.dagster_schedule_claim_resolutions
                      WHERE command_id = CAST(:command_id AS uuid)
                        AND schedule_name = :schedule_name
                    )
                    """
                ),
                {
                    "command_id": str(command_id),
                    "schedule_name": schedule_name,
                },
            )
            known = bool(known_result.scalar_one())
            await session.rollback()
            if known:
                raise DagsterScheduleClaimResolutionConflict(
                    "이 schedule claim은 이미 해제됐거나 활성 상태가 아닙니다."
                )
            raise DagsterScheduleClaimNotFound("지정한 schedule claim을 찾을 수 없습니다.")
        if not bool(claim_row.is_resolvable):
            await session.rollback()
            raise DagsterScheduleClaimResolutionConflict(
                "이 schedule 명령은 아직 실행 중일 수 있어 안전 확인 시각 전에는 "
                "claim을 해제할 수 없습니다."
            )

        audit_result = await session.execute(
            text(
                """
                SELECT terminal.event_id AS terminal_event_id, terminal.details
                FROM ops.dagster_schedule_audit_events AS requested
                LEFT JOIN ops.dagster_schedule_audit_events AS terminal
                  ON terminal.command_id = requested.command_id
                 AND terminal.phase IN ('succeeded','failed')
                WHERE requested.command_id = CAST(:command_id AS uuid)
                  AND requested.phase = 'requested'
                  AND requested.schedule_name = :schedule_name
                  AND (
                    terminal.command_id IS NULL
                    OR terminal.schedule_name = :schedule_name
                  )
                """
            ),
            {
                "command_id": str(command_id),
                "schedule_name": schedule_name,
            },
        )
        audit_row = audit_result.one_or_none()
        if audit_row is None:
            await session.rollback()
            raise DagsterScheduleClaimResolutionConflict(
                "활성 schedule claim의 requested 감사 이벤트를 찾을 수 없습니다."
            )
        details = dict(audit_row.details) if audit_row.details is not None else {}
        if (
            audit_row.terminal_event_id is not None
            and details.get("outcome_certainty") != "uncertain"
        ):
            await session.rollback()
            raise DagsterScheduleClaimResolutionConflict(
                "결과가 확정된 schedule claim은 수동 해제할 수 없습니다."
            )
        inserted = await session.execute(
            text(
                """
                INSERT INTO ops.dagster_schedule_claim_resolutions (
                  command_id, schedule_name, resolution, actor, reason, details
                ) VALUES (
                  CAST(:command_id AS uuid), :schedule_name, :resolution,
                  :actor, :reason, CAST(:details AS jsonb)
                )
                RETURNING resolution_id, created_at
                """
            ),
            {
                "command_id": str(command_id),
                "schedule_name": schedule_name,
                "resolution": resolution,
                "actor": actor,
                "reason": normalized_reason,
                "details": json.dumps(
                    {
                        "terminal_recorded": audit_row.terminal_event_id is not None,
                        "terminal_outcome_certainty": details.get("outcome_certainty"),
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ),
            },
        )
        resolution_row = inserted.one()
        deleted = await session.execute(
            text(
                """
                DELETE FROM ops.dagster_schedule_active_claims
                WHERE command_id = CAST(:command_id AS uuid)
                  AND schedule_name = :schedule_name
                RETURNING command_id
                """
            ),
            {
                "command_id": str(command_id),
                "schedule_name": schedule_name,
            },
        )
        if deleted.scalar_one_or_none() is None:
            raise DagsterScheduleClaimResolutionConflict(
                "schedule claim이 동시에 변경되어 해제하지 못했습니다."
            )
        await session.commit()
    except (DagsterScheduleClaimNotFound, DagsterScheduleClaimResolutionConflict):
        await session.rollback()
        raise
    except SQLAlchemyError as exc:
        await session.rollback()
        raise DagsterScheduleStorageUnavailable(
            "schedule claim 해제 감사 이력을 저장할 수 없습니다."
        ) from exc
    return DagsterScheduleClaimResolution(
        resolution_id=int(resolution_row.resolution_id),
        command_id=command_id,
        schedule_name=schedule_name,
        resolution=resolution,
        actor=actor,
        reason=normalized_reason,
        resolved_at=resolution_row.created_at,
        replayed=False,
    )


async def execute_audited_schedule_command(
    session: AsyncSession,
    *,
    schedule_name: str,
    command: ScheduleCommand,
    actor: str,
    reason: str | None,
    request_details: dict[str, object],
    command_id: UUID,
    operation: AuditedScheduleOperation,
) -> DagsterScheduleCommandResponse:
    """인증 actor 기반 request/result 두 이벤트로 외부 mutation을 감싼다."""

    replay = await _claim_schedule_command(
        session,
        command_id=command_id,
        schedule_name=schedule_name,
        command=command,
        actor=actor,
        reason=reason,
        request_details=request_details,
    )
    if replay is not None:
        return replay
    mutation_guard = lambda: _assert_schedule_claim_mutation_allowed(
        session,
        command_id=command_id,
        schedule_name=schedule_name,
    )
    try:
        async with asyncio.timeout(_SCHEDULE_OPERATION_TIMEOUT_SECONDS):
            response = await operation(mutation_guard)
    except Exception as exc:
        await session.rollback()
        exception_kind = (
            "validation"
            if isinstance(exc, DagsterScheduleValidationError)
            else "storage_unavailable"
            if isinstance(exc, DagsterScheduleStorageUnavailable)
            else "unexpected"
        )
        marker_persisted = False
        try:
            await _mark_schedule_claim_operation_finished(
                session,
                command_id=command_id,
                schedule_name=schedule_name,
            )
            marker_persisted = True
        except DagsterScheduleStorageUnavailable:
            _LOG.exception(
                "schedule 실패 operation-finished marker 저장 실패 (command_id=%s)",
                command_id,
            )
        if marker_persisted:
            try:
                await append_schedule_audit_event(
                    session,
                    command_id=command_id,
                    schedule_name=schedule_name,
                    command=command,
                    phase="failed",
                    actor=actor,
                    reason=reason,
                    details={
                        "outcome": "exception",
                        "outcome_version": 1,
                        "exception_kind": exception_kind,
                        "exception_type": type(exc).__name__,
                        "message": str(exc),
                        "outcome_certainty": (
                            "confirmed"
                            if exception_kind in {"validation", "storage_unavailable"}
                            else "uncertain"
                        ),
                    },
                    release_active_claim=(exception_kind in {"validation", "storage_unavailable"}),
                )
            except DagsterScheduleStorageUnavailable:
                _LOG.exception(
                    "schedule 실패 terminal audit 저장 실패 (command_id=%s)",
                    command_id,
                )
        if exception_kind == "unexpected":
            raise DagsterScheduleUncertainOutcome(
                str(exc),
                command_id=command_id,
                active_command_id=command_id if marker_persisted else None,
            ) from exc
        raise
    try:
        await _mark_schedule_claim_operation_finished(
            session,
            command_id=command_id,
            schedule_name=schedule_name,
        )
    except DagsterScheduleStorageUnavailable:
        response.data.audit_command_id = None
        response.data.audit_status = "terminal_record_failed"
        _LOG.exception(
            "schedule 원격 결과 operation-finished marker 저장 실패; "
            "claim ID는 안전 lease 전까지 노출하지 않음 (command_id=%s, status=%s)",
            command_id,
            response.data.status,
        )
        return response
    response.data.audit_command_id = command_id
    try:
        await append_schedule_audit_event(
            session,
            command_id=command_id,
            schedule_name=schedule_name,
            command=command,
            phase="succeeded" if response.data.status == "ok" else "failed",
            actor=actor,
            reason=reason,
            details=response.data.model_dump(mode="json"),
            release_active_claim=response.data.outcome_certainty == "confirmed",
        )
    except DagsterScheduleStorageUnavailable:
        response.data.audit_status = "terminal_record_failed"
        _LOG.exception(
            "schedule 원격 결과 terminal audit 저장 실패; 결과는 재시도 유도 없이 반환 "
            "(command_id=%s, status=%s)",
            command_id,
            response.data.status,
        )
    return response


async def delete_schedule_override(
    session: AsyncSession,
    *,
    schedule_name: str,
) -> None:
    try:
        await session.execute(
            text(
                """
            DELETE FROM ops.dagster_schedule_overrides
            WHERE schedule_name = :schedule_name
                """
            ),
            {"schedule_name": schedule_name},
        )
        await session.commit()
    except SQLAlchemyError as exc:
        await session.rollback()
        raise DagsterScheduleStorageUnavailable("schedule override를 삭제할 수 없습니다.") from exc


def _schedule_command_response(
    data: DagsterScheduleCommandData,
    *,
    started_at: float,
    outcome_certainty: Literal["confirmed", "uncertain"] | None = None,
) -> DagsterScheduleCommandResponse:
    if outcome_certainty is not None:
        data.outcome_certainty = outcome_certainty
    return DagsterScheduleCommandResponse(
        data=data,
        meta=make_meta(started_at=started_at),
    )


def _schedule_selector(schedule: DagsterSchedule) -> dict[str, str]:
    return {
        "repositoryName": schedule.repository_name or "__repository__",
        "repositoryLocationName": (
            schedule.repository_location_name or "kortravelmap.dagster.definitions"
        ),
        "scheduleName": schedule.name,
    }


def _schedule_origin_id(state_id: str | None) -> str | None:
    if not state_id:
        return None
    return state_id.split("::", 1)[0]


def _graphql_result_error(result: JsonDict) -> str | None:
    typename = _nonblank_string(result.get("__typename"))
    if typename in {
        "ScheduleStateResult",
        "LaunchRunSuccess",
        "WorkspaceLocationEntry",
    }:
        return None
    if typename == "RunConfigValidationInvalid":
        raw_errors = result.get("errors")
        errors = [
            dagster_graphql.optional_string(dagster_graphql.as_dict(error).get("message"))
            or str(error)
            for error in (raw_errors if isinstance(raw_errors, list) else [])
        ]
        return " / ".join(errors) if errors else "run config validation failed"
    message = _nonblank_string(result.get("message"))
    class_name = _nonblank_string(result.get("className"))
    if class_name and message:
        return f"{class_name}: {message}"
    return message or f"Dagster mutation failed: {typename or 'unknown'}"


def _nonblank_string(value: object) -> str | None:
    text_value = dagster_graphql.optional_string(value)
    if text_value is None:
        return None
    normalized = text_value.strip()
    return normalized or None


def _command_error_data(
    *,
    dagster_urls: DagsterUrls,
    checked_at: datetime,
    schedule_name: str,
    command: ScheduleCommand,
    error: str,
    status: Literal["unavailable", "error"] = "error",
) -> DagsterScheduleCommandData:
    return DagsterScheduleCommandData(
        status=status,
        dagster_url=dagster_urls.dagster_url,
        graphql_url=dagster_urls.graphql_url,
        checked_at=checked_at,
        schedule_name=schedule_name,
        command=command,
        default_cron_schedule=dagster_graphql.default_cron_for_schedule(schedule_name, None),
        effective_cron_schedule=None,
        save_status="not_applicable",
        reload_status="not_requested",
        effective_status="unknown",
        errors=[error],
    )


async def _repository_schedules(
    *,
    client: httpx.AsyncClient,
    dagster_urls: DagsterUrls,
    overrides: dict[str, str] | None = None,
) -> tuple[list[DagsterRepository], list[str]]:
    payload = await dagster_graphql.post_graphql(
        client=client,
        graphql_url=dagster_urls.graphql_url,
        variables={},
        query=_DAGSTER_SCHEDULES_QUERY,
    )
    graphql_errors = payload.get("errors")
    if isinstance(graphql_errors, list) and graphql_errors:
        return [], [dagster_graphql.graphql_error_message(error) for error in graphql_errors]
    data = dagster_graphql.as_dict(payload.get("data"))
    return dagster_graphql.parse_repositories(
        dagster_graphql.as_dict(data.get("repositoriesOrError")),
        overrides=overrides,
    )


async def _find_schedule(
    *,
    client: httpx.AsyncClient,
    dagster_urls: DagsterUrls,
    schedule_name: str,
    overrides: dict[str, str] | None = None,
) -> tuple[DagsterSchedule | None, list[str]]:
    repositories, errors = await _repository_schedules(
        client=client,
        dagster_urls=dagster_urls,
        overrides=overrides,
    )
    for repository in repositories:
        for schedule in repository.schedules:
            if schedule.name == schedule_name:
                if not schedule.repository_name:
                    schedule.repository_name = repository.name
                if not schedule.repository_location_name:
                    schedule.repository_location_name = repository.location_name
                return schedule, errors
    return None, [*errors, f"스케줄을 찾을 수 없습니다: {schedule_name}"]


async def _reload_location(
    *,
    client: httpx.AsyncClient,
    dagster_urls: DagsterUrls,
    repository_location_name: str | None,
) -> tuple[
    Literal["succeeded", "unavailable", "error"],
    str | None,
    Literal["confirmed", "uncertain"],
]:
    if not repository_location_name:
        return "error", "repository location 이름이 없습니다.", "confirmed"
    try:
        payload = await dagster_graphql.post_graphql(
            client=client,
            graphql_url=dagster_urls.graphql_url,
            variables={"repositoryLocationName": repository_location_name},
            query=_DAGSTER_RELOAD_LOCATION_MUTATION,
        )
    except httpx.HTTPError as exc:
        return "unavailable", f"code location reload 요청 실패: {exc}", "uncertain"
    except ValueError as exc:
        return "error", f"code location reload 응답 해석 실패: {exc}", "uncertain"
    graphql_errors = payload.get("errors")
    if isinstance(graphql_errors, list) and graphql_errors:
        return (
            "error",
            " / ".join(dagster_graphql.graphql_error_message(error) for error in graphql_errors),
            "uncertain",
        )
    data = payload.get("data")
    raw_result = data.get("reloadRepositoryLocation") if isinstance(data, dict) else None
    result = dagster_graphql.as_dict(raw_result)
    typename = _nonblank_string(result.get("__typename"))
    if typename == "WorkspaceLocationEntry":
        load_status = _nonblank_string(result.get("loadStatus"))
        raw_location = result.get("locationOrLoadError")
        location = dagster_graphql.as_dict(raw_location)
        location_typename = _nonblank_string(location.get("__typename"))
        location_name = _nonblank_string(location.get("name"))
        if load_status is None:
            return (
                "error",
                "code location reload 응답에 loadStatus가 없습니다.",
                "uncertain",
            )
        if load_status not in {"LOADED", "LOADING"}:
            return (
                "error",
                f"code location reload 응답의 loadStatus를 해석할 수 없습니다: {load_status}",
                "uncertain",
            )
        if location_typename == "RepositoryLocation" and location_name is not None:
            if load_status != "LOADED":
                return (
                    "error",
                    f"code location reload가 아직 완료되지 않았습니다: {load_status}",
                    "confirmed",
                )
            return "succeeded", None, "confirmed"
        if location_typename == "PythonError":
            location_error = _graphql_result_error(location)
            return (
                "error",
                f"code location reload 후 load 실패(loadStatus={load_status}): {location_error}",
                "confirmed",
            )
        return (
            "error",
            "code location reload 응답의 locationOrLoadError shape를 확인할 수 없습니다.",
            "uncertain",
        )
    if typename in {"ReloadNotSupported", "RepositoryLocationNotFound", "PythonError"}:
        return "error", _graphql_result_error(result), "confirmed"
    return (
        "error",
        "code location reload 응답 union을 확인할 수 없습니다"
        f"(__typename={typename or 'unknown'}).",
        "uncertain",
    )


def _schedule_url_error(
    *,
    settings: ApiSettings,
    checked_at: datetime,
    schedule_name: str,
    command: ScheduleCommand,
    error: Exception,
) -> DagsterScheduleCommandData:
    return DagsterScheduleCommandData(
        status="unavailable",
        dagster_url=settings.dagster_url,
        graphql_url=dagster_graphql.candidate_graphql_url(settings),
        checked_at=checked_at,
        schedule_name=schedule_name,
        command=command,
        effective_cron_schedule=None,
        save_status="not_applicable",
        reload_status="not_requested",
        effective_status="unknown",
        errors=[str(error)],
    )


async def update_schedule(
    *,
    settings: ApiSettings,
    client: httpx.AsyncClient,
    session: AsyncSession,
    schedule_name: str,
    body: DagsterScheduleOverrideRequest,
    actor: str,
    mutation_guard: ScheduleMutationGuard,
) -> DagsterScheduleCommandResponse:
    """cron override를 저장하고 code location을 reload한다."""

    started_at = perf_counter()
    checked_at = datetime.now(UTC)
    try:
        urls = dagster_graphql.dagster_urls(settings)
    except dagster_graphql.DagsterUrlConfigurationError as exc:
        return _schedule_command_response(
            _schedule_url_error(
                settings=settings,
                checked_at=checked_at,
                schedule_name=schedule_name,
                command="update",
                error=exc,
            ),
            started_at=started_at,
        )
    try:
        cron_schedule = _validate_cron_schedule(body.cron_schedule)
    except ValueError as exc:
        raise DagsterScheduleValidationError(str(exc)) from exc
    overrides = await schedule_overrides(session)
    try:
        schedule, errors = await _find_schedule(
            client=client,
            dagster_urls=urls,
            schedule_name=schedule_name,
            overrides=overrides,
        )
    except httpx.HTTPError as exc:
        schedule = None
        errors = [str(exc)]
        unavailable = True
    except ValueError as exc:
        schedule = None
        errors = [str(exc)]
        unavailable = False
    else:
        unavailable = False
    if schedule is None:
        return _schedule_command_response(
            _command_error_data(
                dagster_urls=urls,
                checked_at=checked_at,
                schedule_name=schedule_name,
                command="update",
                error=" / ".join(errors),
                status="unavailable" if unavailable else "error",
            ),
            started_at=started_at,
        )
    await mutation_guard()
    await upsert_schedule_override(
        session,
        schedule_name=schedule_name,
        cron_schedule=cron_schedule,
        actor=actor,
        reason=body.reason,
    )
    await mutation_guard()
    reload_result, reload_error, outcome_certainty = await _reload_location(
        client=client,
        dagster_urls=urls,
        repository_location_name=schedule.repository_location_name,
    )
    return _schedule_command_response(
        DagsterScheduleCommandData(
            status=(
                "ok"
                if reload_result == "succeeded"
                else "unavailable"
                if reload_result == "unavailable"
                else "error"
            ),
            dagster_url=urls.dagster_url,
            graphql_url=urls.graphql_url,
            checked_at=checked_at,
            schedule_name=schedule_name,
            command="update",
            cron_schedule=cron_schedule,
            default_cron_schedule=schedule.default_cron_schedule,
            override_cron_schedule=cron_schedule,
            effective_cron_schedule=schedule.cron_schedule,
            schedule_status=schedule.status,
            save_status="saved",
            reload_status=("succeeded" if reload_result == "succeeded" else "failed"),
            effective_status=(
                "pending_verification"
                if reload_result == "succeeded"
                else ("confirmed" if schedule.cron_schedule == cron_schedule else "mismatch")
            ),
            errors=[] if reload_error is None else [reload_error],
        ),
        started_at=started_at,
        outcome_certainty=outcome_certainty,
    )


async def reset_schedule_default(
    *,
    settings: ApiSettings,
    client: httpx.AsyncClient,
    session: AsyncSession,
    schedule_name: str,
    mutation_guard: ScheduleMutationGuard,
) -> DagsterScheduleCommandResponse:
    """cron override를 삭제하고 code location을 reload한다."""

    started_at = perf_counter()
    checked_at = datetime.now(UTC)
    try:
        urls = dagster_graphql.dagster_urls(settings)
    except dagster_graphql.DagsterUrlConfigurationError as exc:
        return _schedule_command_response(
            _schedule_url_error(
                settings=settings,
                checked_at=checked_at,
                schedule_name=schedule_name,
                command="default",
                error=exc,
            ),
            started_at=started_at,
        )
    overrides = await schedule_overrides(session)
    try:
        schedule, errors = await _find_schedule(
            client=client,
            dagster_urls=urls,
            schedule_name=schedule_name,
            overrides=overrides,
        )
    except httpx.HTTPError as exc:
        schedule = None
        errors = [str(exc)]
        unavailable = True
    except ValueError as exc:
        schedule = None
        errors = [str(exc)]
        unavailable = False
    else:
        unavailable = False
    if schedule is None:
        return _schedule_command_response(
            _command_error_data(
                dagster_urls=urls,
                checked_at=checked_at,
                schedule_name=schedule_name,
                command="default",
                error=" / ".join(errors),
                status="unavailable" if unavailable else "error",
            ),
            started_at=started_at,
        )
    await mutation_guard()
    await delete_schedule_override(session, schedule_name=schedule_name)
    await mutation_guard()
    reload_result, reload_error, outcome_certainty = await _reload_location(
        client=client,
        dagster_urls=urls,
        repository_location_name=schedule.repository_location_name,
    )
    return _schedule_command_response(
        DagsterScheduleCommandData(
            status=(
                "ok"
                if reload_result == "succeeded"
                else "unavailable"
                if reload_result == "unavailable"
                else "error"
            ),
            dagster_url=urls.dagster_url,
            graphql_url=urls.graphql_url,
            checked_at=checked_at,
            schedule_name=schedule_name,
            command="default",
            cron_schedule=schedule.default_cron_schedule,
            default_cron_schedule=schedule.default_cron_schedule,
            override_cron_schedule=None,
            effective_cron_schedule=schedule.cron_schedule,
            schedule_status=schedule.status,
            save_status="cleared",
            reload_status=("succeeded" if reload_result == "succeeded" else "failed"),
            effective_status=(
                "pending_verification"
                if reload_result == "succeeded"
                else (
                    "confirmed"
                    if schedule.cron_schedule == schedule.default_cron_schedule
                    else "mismatch"
                )
            ),
            errors=[] if reload_error is None else [reload_error],
        ),
        started_at=started_at,
        outcome_certainty=outcome_certainty,
    )


async def mutate_schedule_state(
    *,
    settings: ApiSettings,
    client: httpx.AsyncClient,
    session: AsyncSession,
    schedule_name: str,
    command: Literal["start", "stop", "reset"],
    mutation_guard: ScheduleMutationGuard,
) -> DagsterScheduleCommandResponse:
    """스케줄의 실행 상태를 변경한다."""

    started_at = perf_counter()
    checked_at = datetime.now(UTC)
    try:
        urls = dagster_graphql.dagster_urls(settings)
    except dagster_graphql.DagsterUrlConfigurationError as exc:
        return _schedule_command_response(
            _schedule_url_error(
                settings=settings,
                checked_at=checked_at,
                schedule_name=schedule_name,
                command=command,
                error=exc,
            ),
            started_at=started_at,
        )
    overrides = await schedule_overrides(session)
    try:
        schedule, errors = await _find_schedule(
            client=client,
            dagster_urls=urls,
            schedule_name=schedule_name,
            overrides=overrides,
        )
    except httpx.HTTPError as exc:
        schedule = None
        errors = [str(exc)]
        unavailable = True
    except ValueError as exc:
        schedule = None
        errors = [str(exc)]
        unavailable = False
    else:
        unavailable = False
    if schedule is None:
        return _schedule_command_response(
            _command_error_data(
                dagster_urls=urls,
                checked_at=checked_at,
                schedule_name=schedule_name,
                command=command,
                error=" / ".join(errors),
                status="unavailable" if unavailable else "error",
            ),
            started_at=started_at,
        )
    selector = _schedule_selector(schedule)
    variables: dict[str, object]
    if command == "start":
        query = _DAGSTER_START_SCHEDULE_MUTATION
        variables = {"selector": selector}
        result_key = "startSchedule"
    elif command == "reset":
        query = _DAGSTER_RESET_SCHEDULE_MUTATION
        variables = {"selector": selector}
        result_key = "resetSchedule"
    else:
        state_id = schedule.state_id
        origin_id = _schedule_origin_id(state_id)
        selector_id = schedule.selector_id
        if not state_id or not origin_id or not selector_id:
            return _schedule_command_response(
                _command_error_data(
                    dagster_urls=urls,
                    checked_at=checked_at,
                    schedule_name=schedule_name,
                    command=command,
                    error="스케줄 상태 식별자를 찾을 수 없어 중지할 수 없습니다.",
                ),
                started_at=started_at,
            )
        query = _DAGSTER_STOP_SCHEDULE_MUTATION
        variables = {
            "id": state_id,
            "originId": origin_id,
            "selectorId": selector_id,
        }
        result_key = "stopRunningSchedule"
    try:
        await mutation_guard()
        payload = await dagster_graphql.post_graphql(
            client=client,
            graphql_url=urls.graphql_url,
            variables=variables,
            query=query,
        )
    except httpx.HTTPError as exc:
        return _schedule_command_response(
            _command_error_data(
                dagster_urls=urls,
                checked_at=checked_at,
                schedule_name=schedule_name,
                command=command,
                error=str(exc),
                status="unavailable",
            ),
            started_at=started_at,
            outcome_certainty="uncertain",
        )
    except ValueError as exc:
        return _schedule_command_response(
            _command_error_data(
                dagster_urls=urls,
                checked_at=checked_at,
                schedule_name=schedule_name,
                command=command,
                error=str(exc),
            ),
            started_at=started_at,
            outcome_certainty="uncertain",
        )
    graphql_errors = payload.get("errors")
    if isinstance(graphql_errors, list) and graphql_errors:
        error = " / ".join(dagster_graphql.graphql_error_message(item) for item in graphql_errors)
        return _schedule_command_response(
            _command_error_data(
                dagster_urls=urls,
                checked_at=checked_at,
                schedule_name=schedule_name,
                command=command,
                error=error,
            ),
            started_at=started_at,
            outcome_certainty="uncertain",
        )
    data = payload.get("data")
    raw_result = data.get(result_key) if isinstance(data, dict) else None
    result = dagster_graphql.as_dict(raw_result)
    typename = _nonblank_string(result.get("__typename"))
    known_failure = typename in {
        "ScheduleNotFoundError",
        "UnauthorizedError",
        "PythonError",
    }
    state = dagster_graphql.as_dict(result.get("scheduleState"))
    state_status = _nonblank_string(state.get("status"))
    if typename == "ScheduleStateResult":
        uncertain_result = state_status is None
        result_error = (
            None
            if state_status is not None
            else "Dagster schedule mutation 성공 응답에 scheduleState.status가 없습니다."
        )
    elif known_failure:
        uncertain_result = False
        result_error = _graphql_result_error(result)
    else:
        uncertain_result = True
        result_error = (
            "Dagster schedule mutation 응답 union을 확인할 수 없습니다"
            f"(__typename={typename or 'unknown'})."
        )
    return _schedule_command_response(
        DagsterScheduleCommandData(
            status="ok" if result_error is None else "error",
            dagster_url=urls.dagster_url,
            graphql_url=urls.graphql_url,
            checked_at=checked_at,
            schedule_name=schedule_name,
            command=command,
            cron_schedule=schedule.cron_schedule,
            default_cron_schedule=schedule.default_cron_schedule,
            override_cron_schedule=schedule.override_cron_schedule,
            effective_cron_schedule=schedule.effective_cron_schedule,
            schedule_status=state_status or schedule.status,
            save_status="not_applicable",
            reload_status="not_requested",
            effective_status="unknown" if uncertain_result else "confirmed",
            errors=[] if result_error is None else [result_error],
        ),
        started_at=started_at,
        outcome_certainty="uncertain" if uncertain_result else "confirmed",
    )


async def run_schedule_now(
    *,
    settings: ApiSettings,
    client: httpx.AsyncClient,
    session: AsyncSession,
    schedule_name: str,
    body: DagsterScheduleCommandRequest | None = None,
    actor: str,
    mutation_guard: ScheduleMutationGuard,
) -> DagsterScheduleCommandResponse:
    """스케줄이 가리키는 job을 1회 실행한다."""

    started_at = perf_counter()
    checked_at = datetime.now(UTC)
    try:
        urls = dagster_graphql.dagster_urls(settings)
    except dagster_graphql.DagsterUrlConfigurationError as exc:
        return _schedule_command_response(
            _schedule_url_error(
                settings=settings,
                checked_at=checked_at,
                schedule_name=schedule_name,
                command="run",
                error=exc,
            ),
            started_at=started_at,
        )
    overrides = await schedule_overrides(session)
    try:
        schedule, errors = await _find_schedule(
            client=client,
            dagster_urls=urls,
            schedule_name=schedule_name,
            overrides=overrides,
        )
    except httpx.HTTPError as exc:
        schedule = None
        errors = [str(exc)]
        unavailable = True
    except ValueError as exc:
        schedule = None
        errors = [str(exc)]
        unavailable = False
    else:
        unavailable = False
    if schedule is None or not schedule.pipeline_name:
        return _schedule_command_response(
            _command_error_data(
                dagster_urls=urls,
                checked_at=checked_at,
                schedule_name=schedule_name,
                command="run",
                error=" / ".join(errors) if errors else "schedule job 이름이 없습니다.",
                status="unavailable" if unavailable else "error",
            ),
            started_at=started_at,
        )
    reason = body.reason if body else None
    try:
        run_config, operation_tags = _admin_feature_operation_launch(schedule.pipeline_name)
    except FeatureOperationRegistryError as exc:
        return _schedule_command_response(
            _command_error_data(
                dagster_urls=urls,
                checked_at=checked_at,
                schedule_name=schedule_name,
                command="run",
                error=f"등록 feature operation launch identity 불일치: {exc.reason}",
            ),
            started_at=started_at,
        )
    metadata_tags = {
        **operation_tags,
        "kor_travel_map.schedule_name": schedule_name,
        "kor_travel_map.operator": actor,
        "kor_travel_map.reason": reason or "manual run",
    }
    execution_params = {
        "selector": {
            "jobName": schedule.pipeline_name,
            "repositoryName": schedule.repository_name or "__repository__",
            "repositoryLocationName": (
                schedule.repository_location_name or "kortravelmap.dagster.definitions"
            ),
        },
        "mode": schedule.mode or "default",
        "runConfigData": run_config,
        "executionMetadata": {
            "tags": [{"key": key, "value": value} for key, value in sorted(metadata_tags.items())]
        },
    }
    try:
        await mutation_guard()
        payload = await dagster_graphql.post_graphql(
            client=client,
            graphql_url=urls.graphql_url,
            variables={"executionParams": execution_params},
            query=_DAGSTER_LAUNCH_RUN_MUTATION,
        )
    except httpx.HTTPError as exc:
        return _schedule_command_response(
            _command_error_data(
                dagster_urls=urls,
                checked_at=checked_at,
                schedule_name=schedule_name,
                command="run",
                error=str(exc),
                status="unavailable",
            ),
            started_at=started_at,
            outcome_certainty="uncertain",
        )
    except ValueError as exc:
        return _schedule_command_response(
            _command_error_data(
                dagster_urls=urls,
                checked_at=checked_at,
                schedule_name=schedule_name,
                command="run",
                error=str(exc),
            ),
            started_at=started_at,
            outcome_certainty="uncertain",
        )
    graphql_errors = payload.get("errors")
    if isinstance(graphql_errors, list) and graphql_errors:
        error = " / ".join(dagster_graphql.graphql_error_message(item) for item in graphql_errors)
        return _schedule_command_response(
            _command_error_data(
                dagster_urls=urls,
                checked_at=checked_at,
                schedule_name=schedule_name,
                command="run",
                error=error,
            ),
            started_at=started_at,
            outcome_certainty="uncertain",
        )
    data = payload.get("data")
    raw_result = data.get("launchRun") if isinstance(data, dict) else None
    result = dagster_graphql.as_dict(raw_result)
    typename = _nonblank_string(result.get("__typename"))
    known_failure = typename in {
        "RunConfigValidationInvalid",
        "PipelineNotFoundError",
        "UnauthorizedError",
        "PythonError",
    }
    run = dagster_graphql.as_dict(result.get("run"))
    run_id = _nonblank_string(run.get("runId"))
    if typename == "LaunchRunSuccess":
        uncertain_result = run_id is None
        result_error = (
            None if run_id is not None else "Dagster launch 성공 응답에 run.runId가 없습니다."
        )
    elif known_failure:
        uncertain_result = False
        result_error = _graphql_result_error(result)
    else:
        uncertain_result = True
        result_error = (
            f"Dagster launch 응답 union을 확인할 수 없습니다(__typename={typename or 'unknown'})."
        )
    return _schedule_command_response(
        DagsterScheduleCommandData(
            status="ok" if result_error is None else "error",
            dagster_url=urls.dagster_url,
            graphql_url=urls.graphql_url,
            checked_at=checked_at,
            schedule_name=schedule_name,
            command="run",
            cron_schedule=schedule.cron_schedule,
            default_cron_schedule=schedule.default_cron_schedule,
            override_cron_schedule=schedule.override_cron_schedule,
            effective_cron_schedule=schedule.effective_cron_schedule,
            schedule_status=schedule.status,
            run_id=run_id,
            run_status=dagster_graphql.optional_string(run.get("status")),
            save_status="not_applicable",
            reload_status="not_requested",
            effective_status="unknown" if uncertain_result else "confirmed",
            errors=[] if result_error is None else [result_error],
        ),
        started_at=started_at,
        outcome_certainty="uncertain" if uncertain_result else "confirmed",
    )
