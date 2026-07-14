"""Dagster schedule override persistence and mutation application service."""

from __future__ import annotations

from datetime import UTC, datetime
from time import perf_counter
from typing import Final, Literal

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.api import dagster_graphql
from kortravelmap.api.dagster_graphql import DagsterUrls, JsonDict
from kortravelmap.api.dagster_schema import (
    DagsterRepository,
    DagsterSchedule,
    DagsterScheduleCommandData,
    DagsterScheduleCommandRequest,
    DagsterScheduleCommandResponse,
    DagsterScheduleOverrideRequest,
)
from kortravelmap.api.response import make_meta
from kortravelmap.api.settings import ApiSettings

__all__ = [
    "delete_schedule_override",
    "mutate_schedule_state",
    "reset_schedule_default",
    "run_schedule_now",
    "schedule_overrides",
    "upsert_schedule_override",
    "update_schedule",
]

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


_RUN_CONFIG_REQUIRED_SCHEDULES: frozenset[str] = frozenset(
    {
        "feature_place_datagokr_seoul_bookstores_monthly_schedule",
        "feature_place_datagokr_gyeonggi_muslim_friendly_restaurants_monthly_schedule",
        "feature_place_datagokr_ansan_world_restaurants_monthly_schedule",
        "feature_place_datagokr_jeju_local_restaurants_monthly_schedule",
    }
)


_MIN_CRON_MINUTE_STEP: Final[int] = 10


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
    except Exception:
        return {}
    return {str(row.schedule_name): str(row.cron_schedule) for row in result}


async def upsert_schedule_override(
    session: AsyncSession,
    *,
    schedule_name: str,
    cron_schedule: str,
    operator: str | None,
    reason: str | None,
) -> None:
    await session.execute(
        text(
            """
            INSERT INTO ops.dagster_schedule_overrides (
              schedule_name, cron_schedule, updated_by, reason, metadata
            )
            VALUES (:schedule_name, :cron_schedule, :operator, :reason, '{}'::jsonb)
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
            "operator": operator,
            "reason": reason,
        },
    )
    await session.commit()


async def delete_schedule_override(
    session: AsyncSession,
    *,
    schedule_name: str,
) -> None:
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


def _schedule_command_response(
    data: DagsterScheduleCommandData, *, started_at: float
) -> DagsterScheduleCommandResponse:
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
    typename = dagster_graphql.optional_string(result.get("__typename"))
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
    message = dagster_graphql.optional_string(result.get("message"))
    class_name = dagster_graphql.optional_string(result.get("className"))
    if class_name and message:
        return f"{class_name}: {message}"
    return message or f"Dagster mutation failed: {typename or 'unknown'}"


def _command_error_data(
    *,
    dagster_urls: DagsterUrls,
    checked_at: datetime,
    schedule_name: str,
    command: Literal["update", "default", "start", "stop", "reset", "run"],
    error: str,
) -> DagsterScheduleCommandData:
    return DagsterScheduleCommandData(
        status="error",
        dagster_url=dagster_urls.dagster_url,
        graphql_url=dagster_urls.graphql_url,
        checked_at=checked_at,
        schedule_name=schedule_name,
        command=command,
        default_cron_schedule=dagster_graphql.default_cron_for_schedule(schedule_name, None),
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
) -> tuple[bool, str | None]:
    if not repository_location_name:
        return False, "repository location 이름이 없습니다."
    try:
        payload = await dagster_graphql.post_graphql(
            client=client,
            graphql_url=dagster_urls.graphql_url,
            variables={"repositoryLocationName": repository_location_name},
            query=_DAGSTER_RELOAD_LOCATION_MUTATION,
        )
    except httpx.HTTPError as exc:
        return False, f"code location reload 요청 실패: {exc}"
    graphql_errors = payload.get("errors")
    if isinstance(graphql_errors, list) and graphql_errors:
        return False, " / ".join(
            dagster_graphql.graphql_error_message(error) for error in graphql_errors
        )
    result = dagster_graphql.as_dict(
        dagster_graphql.as_dict(payload.get("data")).get("reloadRepositoryLocation")
    )
    error = _graphql_result_error(result)
    return error is None, error


def _schedule_url_error(
    *,
    settings: ApiSettings,
    checked_at: datetime,
    schedule_name: str,
    command: Literal["update", "default", "start", "stop", "reset", "run"],
    error: Exception,
) -> DagsterScheduleCommandData:
    return DagsterScheduleCommandData(
        status="error",
        dagster_url=settings.dagster_url,
        graphql_url=dagster_graphql.candidate_graphql_url(settings),
        checked_at=checked_at,
        schedule_name=schedule_name,
        command=command,
        errors=[str(error)],
    )


async def update_schedule(
    *,
    settings: ApiSettings,
    client: httpx.AsyncClient,
    session: AsyncSession,
    schedule_name: str,
    body: DagsterScheduleOverrideRequest,
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
    overrides = await schedule_overrides(session)
    try:
        cron_schedule = _validate_cron_schedule(body.cron_schedule)
        schedule, errors = await _find_schedule(
            client=client,
            dagster_urls=urls,
            schedule_name=schedule_name,
            overrides=overrides,
        )
    except (httpx.HTTPError, ValueError) as exc:
        schedule = None
        errors = [str(exc)]
    if schedule is None:
        return _schedule_command_response(
            _command_error_data(
                dagster_urls=urls,
                checked_at=checked_at,
                schedule_name=schedule_name,
                command="update",
                error=" / ".join(errors),
            ),
            started_at=started_at,
        )
    await upsert_schedule_override(
        session,
        schedule_name=schedule_name,
        cron_schedule=cron_schedule,
        operator=body.operator,
        reason=body.reason,
    )
    reloaded, reload_error = await _reload_location(
        client=client,
        dagster_urls=urls,
        repository_location_name=schedule.repository_location_name,
    )
    return _schedule_command_response(
        DagsterScheduleCommandData(
            status="ok",
            dagster_url=urls.dagster_url,
            graphql_url=urls.graphql_url,
            checked_at=checked_at,
            schedule_name=schedule_name,
            command="update",
            cron_schedule=cron_schedule,
            default_cron_schedule=schedule.default_cron_schedule,
            override_cron_schedule=cron_schedule,
            schedule_status=schedule.status,
            reloaded=reloaded,
            errors=[] if reload_error is None else [reload_error],
        ),
        started_at=started_at,
    )


async def reset_schedule_default(
    *,
    settings: ApiSettings,
    client: httpx.AsyncClient,
    session: AsyncSession,
    schedule_name: str,
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
    except (httpx.HTTPError, ValueError) as exc:
        schedule = None
        errors = [str(exc)]
    if schedule is None:
        return _schedule_command_response(
            _command_error_data(
                dagster_urls=urls,
                checked_at=checked_at,
                schedule_name=schedule_name,
                command="default",
                error=" / ".join(errors),
            ),
            started_at=started_at,
        )
    await delete_schedule_override(session, schedule_name=schedule_name)
    reloaded, reload_error = await _reload_location(
        client=client,
        dagster_urls=urls,
        repository_location_name=schedule.repository_location_name,
    )
    return _schedule_command_response(
        DagsterScheduleCommandData(
            status="ok",
            dagster_url=urls.dagster_url,
            graphql_url=urls.graphql_url,
            checked_at=checked_at,
            schedule_name=schedule_name,
            command="default",
            cron_schedule=schedule.default_cron_schedule,
            default_cron_schedule=schedule.default_cron_schedule,
            schedule_status=schedule.status,
            reloaded=reloaded,
            errors=[] if reload_error is None else [reload_error],
        ),
        started_at=started_at,
    )


async def mutate_schedule_state(
    *,
    settings: ApiSettings,
    client: httpx.AsyncClient,
    session: AsyncSession,
    schedule_name: str,
    command: Literal["start", "stop", "reset"],
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
    except (httpx.HTTPError, ValueError) as exc:
        schedule = None
        errors = [str(exc)]
    if schedule is None:
        return _schedule_command_response(
            _command_error_data(
                dagster_urls=urls,
                checked_at=checked_at,
                schedule_name=schedule_name,
                command=command,
                error=" / ".join(errors),
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
        payload = await dagster_graphql.post_graphql(
            client=client,
            graphql_url=urls.graphql_url,
            variables=variables,
            query=query,
        )
    except (httpx.HTTPError, ValueError) as exc:
        return _schedule_command_response(
            _command_error_data(
                dagster_urls=urls,
                checked_at=checked_at,
                schedule_name=schedule_name,
                command=command,
                error=str(exc),
            ),
            started_at=started_at,
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
        )
    result = dagster_graphql.as_dict(dagster_graphql.as_dict(payload.get("data")).get(result_key))
    result_error = _graphql_result_error(result)
    state = dagster_graphql.as_dict(result.get("scheduleState"))
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
            schedule_status=dagster_graphql.optional_string(state.get("status")) or schedule.status,
            errors=[] if result_error is None else [result_error],
        ),
        started_at=started_at,
    )


async def run_schedule_now(
    *,
    settings: ApiSettings,
    client: httpx.AsyncClient,
    session: AsyncSession,
    schedule_name: str,
    body: DagsterScheduleCommandRequest | None = None,
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
    except (httpx.HTTPError, ValueError) as exc:
        schedule = None
        errors = [str(exc)]
    if schedule is None or not schedule.pipeline_name:
        return _schedule_command_response(
            _command_error_data(
                dagster_urls=urls,
                checked_at=checked_at,
                schedule_name=schedule_name,
                command="run",
                error=" / ".join(errors) if errors else "schedule job 이름이 없습니다.",
            ),
            started_at=started_at,
        )
    if schedule_name in _RUN_CONFIG_REQUIRED_SCHEDULES:
        return _schedule_command_response(
            _command_error_data(
                dagster_urls=urls,
                checked_at=checked_at,
                schedule_name=schedule_name,
                command="run",
                error=(
                    "이 스케줄은 run_config(dataset_key)로 동작해 즉시 실행이 잘못된 "
                    "dataset을 적재할 수 있어 지원하지 않습니다 — 스케줄 tick으로 실행됩니다."
                ),
            ),
            started_at=started_at,
        )
    operator = body.operator if body else None
    reason = body.reason if body else None
    execution_params = {
        "selector": {
            "jobName": schedule.pipeline_name,
            "repositoryName": schedule.repository_name or "__repository__",
            "repositoryLocationName": (
                schedule.repository_location_name or "kortravelmap.dagster.definitions"
            ),
        },
        "mode": schedule.mode or "default",
        "runConfigData": {},
        "executionMetadata": {
            "tags": [
                {"key": "kor_travel_map.trigger", "value": "admin-ui"},
                {"key": "kor_travel_map.schedule_name", "value": schedule_name},
                {"key": "kor_travel_map.operator", "value": operator or "admin-ui"},
                {"key": "kor_travel_map.reason", "value": reason or "manual run"},
            ]
        },
    }
    try:
        payload = await dagster_graphql.post_graphql(
            client=client,
            graphql_url=urls.graphql_url,
            variables={"executionParams": execution_params},
            query=_DAGSTER_LAUNCH_RUN_MUTATION,
        )
    except (httpx.HTTPError, ValueError) as exc:
        return _schedule_command_response(
            _command_error_data(
                dagster_urls=urls,
                checked_at=checked_at,
                schedule_name=schedule_name,
                command="run",
                error=str(exc),
            ),
            started_at=started_at,
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
        )
    result = dagster_graphql.as_dict(dagster_graphql.as_dict(payload.get("data")).get("launchRun"))
    result_error = _graphql_result_error(result)
    run = dagster_graphql.as_dict(result.get("run"))
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
            schedule_status=schedule.status,
            run_id=dagster_graphql.optional_string(run.get("runId")),
            run_status=dagster_graphql.optional_string(run.get("status")),
            errors=[] if result_error is None else [result_error],
        ),
        started_at=started_at,
    )
