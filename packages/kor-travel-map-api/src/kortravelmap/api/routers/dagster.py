"""``kortravelmap.api.routers.dagster`` — 작업 자동화 요약 API.

Dagster webserver 자체 화면은 frontend에서 iframe으로 embed하고, 본 라우터는
같은 Dagster GraphQL 데이터를 admin UI가 읽기 쉬운 요약 DTO로 변환한다.
외부 서비스가 Dagster를 직접 제어하지 않는다는 ADR-045 경계를 유지한다.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from time import perf_counter
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit, urlunsplit

import httpx
from fastapi import APIRouter, Depends, Query, Request
from kortravelmap.core.dagster_asset_labels import DAGSTER_ASSET_KOREAN_LABELS
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.api.db import get_session
from kortravelmap.api.response import Meta, make_meta
from kortravelmap.api.settings import ApiSettings

__all__ = [
    "router",
    "DagsterNuxSeenResponse",
    "DagsterRunDetailResponse",
    "DagsterScheduleCommandResponse",
    "DagsterSummaryResponse",
]


router = APIRouter(prefix="/ops/dagster", tags=["ops", "dagster"])

JsonDict = dict[str, Any]
_ALLOWED_DAGSTER_SCHEMES = {"http", "https"}

_DAGSTER_SUMMARY_QUERY = """
query KorTravelMapDagsterSummary($limit: Int!) {
  version
  repositoriesOrError {
    __typename
    ... on RepositoryConnection {
      nodes {
        name
        location { name }
        pipelines { name isJob }
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
            ticks(limit: 3) {
              tickId
              status
              timestamp
              endTimestamp
              runIds
              runKeys
              skipReason
              cursor
              error { message stack className }
            }
          }
        }
        sensors {
          name
          sensorState {
            status
            ticks(limit: 3) {
              tickId
              status
              timestamp
              endTimestamp
              runIds
              runKeys
              skipReason
              cursor
              error { message stack className }
            }
          }
        }
        assetNodes {
          id
          groupName
          assetKey { path }
        }
      }
    }
    ... on PythonError {
      message
    }
  }
  runsOrError(limit: $limit) {
    __typename
    ... on Runs {
      results {
        runId
        jobName
        status
        startTime
        endTime
        updateTime
        tags { key value }
      }
    }
    ... on PythonError {
      message
    }
  }
}
"""

_DAGSTER_RUN_DETAIL_QUERY = """
query KorTravelMapDagsterRunDetail(
  $runId: ID!, $eventLimit: Int!, $afterCursor: String
) {
  runOrError(runId: $runId) {
    __typename
    ... on Run {
      runId
      jobName
      status
      startTime
      endTime
      updateTime
      tags { key value }
      eventConnection(limit: $eventLimit, afterCursor: $afterCursor) {
        cursor
        hasMore
        events {
          __typename
          ... on MessageEvent {
            message
            timestamp
            level
            stepKey
            eventType
          }
          ... on ErrorEvent {
            error { message stack className }
          }
        }
      }
    }
    ... on RunNotFoundError {
      message
      runId
    }
    ... on PythonError {
      message
      stack
      className
    }
  }
}
"""

_DAGSTER_SET_NUX_SEEN_MUTATION = """
mutation KorTravelMapSetNuxSeen {
  setNuxSeen
}
"""

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

_DEFAULT_SCHEDULE_CRONS: dict[str, str] = {
    "consistency_dedup_refresh_daily_schedule": "45 5 * * *",
    "curated_features_refresh_daily_schedule": "55 4 * * *",
    "mois_localdata_source_sync_weekly_schedule": "0 4 * * 1",
    "feature_event_datagokr_cultural_festivals_monthly_schedule": "10 3 1 * *",
    "feature_place_opinet_stations_monthly_schedule": "5 3 1 * *",
    "feature_price_opinet_stations_daily_schedule": "18 18 * * *",
    "feature_place_krex_rest_areas_monthly_schedule": "20 2 1 * *",
    "feature_price_krex_rest_areas_twice_daily_schedule": "28 6,18 * * *",
    "feature_notice_krex_traffic_notices_monthly_schedule": "7 3 1 * *",
    "feature_weather_krex_rest_areas_hourly_schedule": "35 * * * *",
    "feature_place_krheritage_items_monthly_schedule": "15 2 2 * *",
    "feature_event_krheritage_events_monthly_schedule": "25 3 2 * *",
    "feature_place_mois_licenses_monthly_schedule": "35 4 2 * *",
    "feature_place_knps_points_monthly_schedule": "45 3 3 * *",
    "feature_geometry_knps_records_monthly_schedule": "15 4 3 * *",
    "feature_place_krforest_recreation_forests_monthly_schedule": "5 4 4 * *",
    "feature_place_krforest_arboretums_monthly_schedule": "15 4 4 * *",
    "feature_place_standard_museums_monthly_schedule": "25 4 4 * *",
    "feature_place_standard_tourist_attractions_monthly_schedule": "35 4 4 * *",
    "feature_place_standard_parking_lots_monthly_schedule": "45 4 4 * *",
    "feature_place_standard_special_streets_monthly_schedule": "50 4 4 * *",
    "feature_place_datagokr_seoul_bookstores_monthly_schedule": "52 4 4 * *",
    "feature_place_datagokr_gyeonggi_muslim_friendly_restaurants_monthly_schedule": "53 4 4 * *",
    "feature_place_datagokr_ansan_world_restaurants_monthly_schedule": "54 4 4 * *",
    "feature_place_datagokr_jeju_local_restaurants_monthly_schedule": "56 4 4 * *",
    "feature_place_khoa_beaches_monthly_schedule": "55 4 4 * *",
    "feature_place_krairport_airports_monthly_schedule": "5 5 4 * *",
    "feature_place_kor_travel_concierge_youtube_monthly_schedule": "40 3 3 * *",
    "feature_event_visitkorea_enrichment_monthly_schedule": "50 4 1 * *",
    "feature_weather_airkorea_air_quality_hourly_schedule": "10 * * * *",
    "feature_weather_kma_ultra_short_nowcast_hourly_schedule": "45 * * * *",
    "feature_weather_kma_ultra_short_forecast_hourly_schedule": "50 * * * *",
    "feature_weather_kma_short_forecast_hourly_schedule": "20 * * * *",
    "feature_weather_kma_mid_forecast_hourly_schedule": "25 * * * *",
    "feature_notice_kma_weather_alerts_hourly_schedule": "15 * * * *",
    "feature_place_mcst_culture_monthly_schedule": "30 4 3 * *",
}

_FILE_DOWNLOAD_SCHEDULE_HINTS = {
    "datagokr_filedata",
    "file_data",
    "localdata",
    "mcst_file",
}


class DagsterAssetSummary(BaseModel):
    """Dagster asset 표시 요약."""

    model_config = ConfigDict(extra="forbid")

    name: str
    display_name: str


class DagsterAssetGroup(BaseModel):
    """Dagster asset group 요약."""

    model_config = ConfigDict(extra="forbid")

    group_name: str
    asset_count: int
    assets: list[str]
    asset_items: list[DagsterAssetSummary] = Field(default_factory=list)


class DagsterJob(BaseModel):
    """Dagster job/pipeline 요약."""

    model_config = ConfigDict(extra="forbid")

    name: str
    is_job: bool


class DagsterGraphqlError(BaseModel):
    """Dagster GraphQL PythonError 요약."""

    model_config = ConfigDict(extra="forbid")

    message: str | None = None
    stack: list[str] = Field(default_factory=list)
    class_name: str | None = None


class DagsterInstigationTick(BaseModel):
    """Dagster schedule/sensor tick 요약."""

    model_config = ConfigDict(extra="forbid")

    tick_id: str
    status: str
    timestamp: float
    end_timestamp: float | None = None
    run_ids: list[str] = Field(default_factory=list)
    run_keys: list[str] = Field(default_factory=list)
    skip_reason: str | None = None
    cursor: str | None = None
    error: DagsterGraphqlError | None = None


class DagsterSchedule(BaseModel):
    """Dagster schedule 요약."""

    model_config = ConfigDict(extra="forbid")

    name: str
    description: str | None = None
    pipeline_name: str | None = None
    mode: str | None = None
    cron_schedule: str | None = None
    default_cron_schedule: str | None = None
    override_cron_schedule: str | None = None
    execution_timezone: str | None = None
    default_status: str | None = None
    can_reset: bool = False
    status: str | None = None
    state_id: str | None = None
    selector_id: str | None = None
    repository_name: str | None = None
    repository_location_name: str | None = None
    schedule_note: str | None = None
    recent_ticks: list[DagsterInstigationTick] = Field(default_factory=list)


class DagsterSensor(BaseModel):
    """Dagster sensor 요약."""

    model_config = ConfigDict(extra="forbid")

    name: str
    status: str | None = None
    recent_ticks: list[DagsterInstigationTick] = Field(default_factory=list)


class DagsterRepository(BaseModel):
    """Dagster code location/repository 요약."""

    model_config = ConfigDict(extra="forbid")

    name: str
    location_name: str
    jobs: list[DagsterJob]
    schedules: list[DagsterSchedule]
    sensors: list[DagsterSensor]
    asset_count: int
    asset_groups: list[DagsterAssetGroup]


class DagsterRunSummary(BaseModel):
    """최근 Dagster run 요약."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    job_name: str | None = None
    status: str
    start_time: float | None = None
    end_time: float | None = None
    update_time: float | None = None
    tags: dict[str, str]


class DagsterSummaryData(BaseModel):
    """`GET /ops/dagster/summary` data."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["ok", "unavailable", "error"]
    dagster_url: str
    graphql_url: str
    version: str | None = None
    checked_at: datetime
    repository_count: int
    job_count: int
    asset_count: int
    schedule_count: int
    sensor_count: int
    run_counts: dict[str, int]
    repositories: list[DagsterRepository]
    recent_runs: list[DagsterRunSummary]
    errors: list[str] = Field(default_factory=list)


class DagsterSummaryResponse(BaseModel):
    """`GET /ops/dagster/summary` 응답 (DA-D-03 envelope)."""

    model_config = ConfigDict(extra="forbid")

    data: DagsterSummaryData
    meta: Meta


class DagsterNuxSeenData(BaseModel):
    """`POST /ops/dagster/nux-seen` data."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["ok", "unavailable", "error"]
    dagster_url: str
    graphql_url: str
    checked_at: datetime
    seen: bool
    errors: list[str] = Field(default_factory=list)


class DagsterNuxSeenResponse(BaseModel):
    """`POST /ops/dagster/nux-seen` 응답 (DA-D-03 envelope)."""

    model_config = ConfigDict(extra="forbid")

    data: DagsterNuxSeenData
    meta: Meta


class DagsterScheduleOverrideRequest(BaseModel):
    """운영 화면 schedule cron override 요청."""

    model_config = ConfigDict(extra="forbid")

    cron_schedule: str = Field(min_length=1, max_length=120)
    operator: str | None = Field(default=None, max_length=120)
    reason: str | None = Field(default=None, max_length=500)


class DagsterScheduleCommandRequest(BaseModel):
    """Schedule start/stop/reset/run-now 명령 body."""

    model_config = ConfigDict(extra="forbid")

    operator: str | None = Field(default=None, max_length=120)
    reason: str | None = Field(default=None, max_length=500)


class DagsterScheduleCommandData(BaseModel):
    """Schedule write 명령 결과."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["ok", "unavailable", "error"]
    dagster_url: str
    graphql_url: str
    checked_at: datetime
    schedule_name: str
    command: Literal["update", "default", "start", "stop", "reset", "run"]
    cron_schedule: str | None = None
    default_cron_schedule: str | None = None
    override_cron_schedule: str | None = None
    schedule_status: str | None = None
    run_id: str | None = None
    run_status: str | None = None
    reloaded: bool = False
    errors: list[str] = Field(default_factory=list)


class DagsterScheduleCommandResponse(BaseModel):
    """Schedule write 명령 응답."""

    model_config = ConfigDict(extra="forbid")

    data: DagsterScheduleCommandData
    meta: Meta


class DagsterRunEvent(BaseModel):
    """Dagster run event/failure 요약."""

    model_config = ConfigDict(extra="forbid")

    event_type: str
    message: str | None = None
    timestamp: str | None = None
    level: str | None = None
    step_id: str | None = None
    dagster_event_type: str | None = None
    error: DagsterGraphqlError | None = None


class DagsterRunFailure(BaseModel):
    """Run failure 원인 요약."""

    model_config = ConfigDict(extra="forbid")

    event_type: str
    message: str | None = None
    timestamp: str | None = None
    level: str | None = None
    step_id: str | None = None
    dagster_event_type: str | None = None
    error: DagsterGraphqlError | None = None


class DagsterRunDetailData(BaseModel):
    """`GET /ops/dagster/runs/{run_id}` data."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["ok", "not_found", "unavailable", "error"]
    dagster_url: str
    graphql_url: str
    checked_at: datetime
    run: DagsterRunSummary | None = None
    events: list[DagsterRunEvent] = Field(default_factory=list)
    failure_reason: str | None = None
    failure_events: list[DagsterRunFailure] = Field(default_factory=list)
    event_cursor: str | None = None
    event_has_more: bool = False
    errors: list[str] = Field(default_factory=list)


class DagsterRunDetailResponse(BaseModel):
    """`GET /ops/dagster/runs/{run_id}` 응답 (DA-D-03 envelope)."""

    model_config = ConfigDict(extra="forbid")

    data: DagsterRunDetailData
    meta: Meta


@dataclass(frozen=True)
class _DagsterUrls:
    dagster_url: str
    graphql_url: str


class DagsterUrlConfigurationError(ValueError):
    """Dagster URL 설정이 backend allowlist를 통과하지 못했다."""


def _candidate_graphql_url(settings: ApiSettings) -> str:
    if settings.dagster_graphql_url:
        return settings.dagster_graphql_url
    return f"{settings.dagster_url.rstrip('/')}/graphql"


def _normalised_allowed_hosts(settings: ApiSettings) -> set[str]:
    return {
        host.strip().lower().rstrip(".")
        for host in settings.dagster_allowed_hosts
        if host.strip()
    }


def _validated_http_url(
    raw_url: str,
    *,
    setting_name: str,
    allowed_hosts: set[str],
    require_graphql_path: bool = False,
) -> str:
    value = raw_url.strip()
    parsed = urlsplit(value)
    scheme = parsed.scheme.lower()
    if scheme not in _ALLOWED_DAGSTER_SCHEMES:
        raise DagsterUrlConfigurationError(
            f"{setting_name} scheme must be http or https"
        )
    if parsed.username is not None or parsed.password is not None:
        raise DagsterUrlConfigurationError(
            f"{setting_name} must not include userinfo"
        )
    hostname = parsed.hostname
    if hostname is None:
        raise DagsterUrlConfigurationError(f"{setting_name} host is required")
    if hostname.lower().rstrip(".") not in allowed_hosts:
        raise DagsterUrlConfigurationError(
            f"{setting_name} host is not in dagster_allowed_hosts"
        )
    if parsed.query or parsed.fragment:
        raise DagsterUrlConfigurationError(
            f"{setting_name} must not include query or fragment"
        )
    if require_graphql_path and not parsed.path.rstrip("/").endswith("/graphql"):
        raise DagsterUrlConfigurationError(
            f"{setting_name} path must end with /graphql"
        )
    return urlunsplit((scheme, parsed.netloc, parsed.path, "", ""))


def _dagster_urls(settings: ApiSettings) -> _DagsterUrls:
    allowed_hosts = _normalised_allowed_hosts(settings)
    dagster_url = _validated_http_url(
        settings.dagster_url,
        setting_name="dagster_url",
        allowed_hosts=allowed_hosts,
    )
    graphql_url = _validated_http_url(
        _candidate_graphql_url(settings),
        setting_name="dagster_graphql_url",
        allowed_hosts=allowed_hosts,
        require_graphql_path=True,
    )
    return _DagsterUrls(dagster_url=dagster_url.rstrip("/"), graphql_url=graphql_url)


def _dict(value: object) -> JsonDict:
    return value if isinstance(value, dict) else {}


def _list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _string(value: object, default: str = "") -> str:
    return value if isinstance(value, str) else default


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _optional_float(value: object) -> float | None:
    if isinstance(value, int | float):
        return float(value)
    return None


def _string_list(value: object) -> list[str]:
    return [item for item in _list(value) if isinstance(item, str)]


def _asset_name(asset_node: JsonDict) -> str:
    asset_key = _dict(asset_node.get("assetKey"))
    path = [part for part in _list(asset_key.get("path")) if isinstance(part, str)]
    if path:
        return "/".join(path)
    return _string(asset_node.get("id"), "unknown_asset")


def _asset_display_name(asset_name: str) -> str:
    return DAGSTER_ASSET_KOREAN_LABELS.get(asset_name, asset_name)


def _parse_jobs(raw_jobs: list[object]) -> list[DagsterJob]:
    jobs: list[DagsterJob] = []
    for raw in raw_jobs:
        entry = _dict(raw)
        jobs.append(
            DagsterJob(
                name=_string(entry.get("name"), "unknown_job"),
                is_job=bool(entry.get("isJob")),
            )
        )
    return jobs


def _parse_graphql_error(raw_error: object) -> DagsterGraphqlError | None:
    error = _dict(raw_error)
    if not error:
        return None
    return DagsterGraphqlError(
        message=_optional_string(error.get("message")),
        stack=_string_list(error.get("stack")),
        class_name=_optional_string(error.get("className")),
    )


def _graphql_error_message(raw_error: object) -> str:
    """GraphQL ``errors[]`` 항목 → 사람이 읽을 메시지(dict repr 노출 방지).

    GraphQL 스펙 오류는 ``{"message": ..., "locations": ..., "path": ...}`` dict라
    ``str(dict)``이면 UI에 파이썬 repr이 새어나간다. ``message``를 우선 추출한다.
    """
    error = _dict(raw_error)
    message = _optional_string(error.get("message"))
    if message:
        return message
    return str(raw_error)


def _parse_ticks(raw_ticks: object) -> list[DagsterInstigationTick]:
    ticks: list[DagsterInstigationTick] = []
    for raw in _list(raw_ticks):
        entry = _dict(raw)
        tick_id = _string(entry.get("tickId"))
        if not tick_id:
            continue
        ticks.append(
            DagsterInstigationTick(
                tick_id=tick_id,
                status=_string(entry.get("status"), "UNKNOWN"),
                timestamp=_optional_float(entry.get("timestamp")) or 0.0,
                end_timestamp=_optional_float(entry.get("endTimestamp")),
                run_ids=_string_list(entry.get("runIds")),
                run_keys=_string_list(entry.get("runKeys")),
                skip_reason=_optional_string(entry.get("skipReason")),
                cursor=_optional_string(entry.get("cursor")),
                error=_parse_graphql_error(entry.get("error")),
            )
        )
    return ticks


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
    return cron


def _schedule_note(schedule_name: str, default_cron: str | None) -> str | None:
    lowered = schedule_name.lower()
    if any(token in lowered for token in _FILE_DOWNLOAD_SCHEDULE_HINTS):
        return "파일 다운로드 계열 기본 주기는 월 1회입니다."
    if default_cron and default_cron.endswith(" * * * *"):
        return "provider rate limit의 약 90% 이하를 목표로 한 시간 단위 기본값입니다."
    return "provider rate limit의 약 90% 이하를 목표로 한 기본값입니다."


async def _schedule_overrides(
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


async def _upsert_schedule_override(
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


async def _delete_schedule_override(
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


def _default_cron_for_schedule(schedule_name: str, current_cron: str | None) -> str | None:
    return _DEFAULT_SCHEDULE_CRONS.get(schedule_name, current_cron)


def _parse_schedules(
    raw_schedules: list[object],
    *,
    overrides: dict[str, str] | None = None,
) -> list[DagsterSchedule]:
    schedules: list[DagsterSchedule] = []
    overrides = overrides or {}
    for raw in raw_schedules:
        entry = _dict(raw)
        state = _dict(entry.get("scheduleState"))
        name = _string(entry.get("name"), "unknown_schedule")
        cron_schedule = _optional_string(entry.get("cronSchedule"))
        default_cron = _default_cron_for_schedule(name, cron_schedule)
        schedules.append(
            DagsterSchedule(
                name=name,
                description=_optional_string(entry.get("description")),
                pipeline_name=_optional_string(entry.get("pipelineName")),
                mode=_optional_string(entry.get("mode")),
                cron_schedule=cron_schedule,
                default_cron_schedule=default_cron,
                override_cron_schedule=overrides.get(name),
                execution_timezone=_optional_string(entry.get("executionTimezone")),
                default_status=_optional_string(entry.get("defaultStatus")),
                can_reset=bool(entry.get("canReset")),
                status=_optional_string(state.get("status")),
                state_id=_optional_string(state.get("id")),
                selector_id=_optional_string(state.get("selectorId")),
                repository_name=_optional_string(state.get("repositoryName")),
                repository_location_name=_optional_string(
                    state.get("repositoryLocationName")
                ),
                schedule_note=_schedule_note(name, default_cron),
                recent_ticks=_parse_ticks(state.get("ticks")),
            )
        )
    return schedules


def _parse_sensors(raw_sensors: list[object]) -> list[DagsterSensor]:
    sensors: list[DagsterSensor] = []
    for raw in raw_sensors:
        entry = _dict(raw)
        state = _dict(entry.get("sensorState"))
        sensors.append(
            DagsterSensor(
                name=_string(entry.get("name"), "unknown_sensor"),
                status=_optional_string(state.get("status")),
                recent_ticks=_parse_ticks(state.get("ticks")),
            )
        )
    return sensors


def _parse_asset_groups(raw_assets: list[object]) -> list[DagsterAssetGroup]:
    groups: defaultdict[str, list[str]] = defaultdict(list)
    for raw in raw_assets:
        entry = _dict(raw)
        group_name = _string(entry.get("groupName"), "default")
        groups[group_name].append(_asset_name(entry))

    return [
        DagsterAssetGroup(
            group_name=group_name,
            asset_count=len(assets),
            assets=sorted(assets),
            asset_items=[
                DagsterAssetSummary(
                    name=asset,
                    display_name=_asset_display_name(asset),
                )
                for asset in sorted(assets)
            ],
        )
        for group_name, assets in sorted(groups.items())
    ]


def _parse_repositories(
    raw_connection: JsonDict,
    *,
    overrides: dict[str, str] | None = None,
) -> tuple[list[DagsterRepository], list[str]]:
    errors: list[str] = []
    if raw_connection.get("__typename") != "RepositoryConnection":
        message = _optional_string(raw_connection.get("message")) or "Dagster repository 조회 실패"
        return [], [message]

    repositories: list[DagsterRepository] = []
    for raw in _list(raw_connection.get("nodes")):
        entry = _dict(raw)
        location = _dict(entry.get("location"))
        assets = _list(entry.get("assetNodes"))
        repositories.append(
            DagsterRepository(
                name=_string(entry.get("name"), "__repository__"),
                location_name=_string(location.get("name"), "unknown_location"),
                jobs=_parse_jobs(_list(entry.get("pipelines"))),
                schedules=_parse_schedules(
                    _list(entry.get("schedules")),
                    overrides=overrides,
                ),
                sensors=_parse_sensors(_list(entry.get("sensors"))),
                asset_count=len(assets),
                asset_groups=_parse_asset_groups(assets),
            )
        )
    return repositories, errors


def _parse_runs(raw_runs: JsonDict) -> tuple[list[DagsterRunSummary], dict[str, int], list[str]]:
    if raw_runs.get("__typename") != "Runs":
        message = _optional_string(raw_runs.get("message")) or "Dagster run 조회 실패"
        return [], {}, [message]

    runs: list[DagsterRunSummary] = []
    counts: Counter[str] = Counter()
    for raw in _list(raw_runs.get("results")):
        entry = _dict(raw)
        status = _string(entry.get("status"), "UNKNOWN")
        counts[status] += 1
        tags = {
            _string(_dict(tag).get("key")): _string(_dict(tag).get("value"))
            for tag in _list(entry.get("tags"))
            if _string(_dict(tag).get("key"))
        }
        runs.append(
            DagsterRunSummary(
                run_id=_string(entry.get("runId"), "unknown_run"),
                job_name=_optional_string(entry.get("jobName")),
                status=status,
                start_time=_optional_float(entry.get("startTime")),
                end_time=_optional_float(entry.get("endTime")),
                update_time=_optional_float(entry.get("updateTime")),
                tags=tags,
            )
        )
    return runs, dict(counts), []


def _parse_run_summary(entry: JsonDict) -> DagsterRunSummary:
    tags = {
        _string(_dict(tag).get("key")): _string(_dict(tag).get("value"))
        for tag in _list(entry.get("tags"))
        if _string(_dict(tag).get("key"))
    }
    return DagsterRunSummary(
        run_id=_string(entry.get("runId"), "unknown_run"),
        job_name=_optional_string(entry.get("jobName")),
        status=_string(entry.get("status"), "UNKNOWN"),
        start_time=_optional_float(entry.get("startTime")),
        end_time=_optional_float(entry.get("endTime")),
        update_time=_optional_float(entry.get("updateTime")),
        tags=tags,
    )


def _parse_run_event(raw_event: object) -> DagsterRunEvent:
    event = _dict(raw_event)
    return DagsterRunEvent(
        event_type=_string(event.get("__typename"), "DagsterEvent"),
        message=_optional_string(event.get("message")),
        timestamp=_optional_string(event.get("timestamp")),
        level=_optional_string(event.get("level")),
        step_id=_optional_string(event.get("stepKey")),
        dagster_event_type=_optional_string(event.get("eventType")),
        error=_parse_graphql_error(event.get("error")),
    )


def _is_failure_event(event: DagsterRunEvent) -> bool:
    if event.error is not None:
        return True
    event_type = (event.dagster_event_type or event.event_type).upper()
    return event.level == "ERROR" or "FAIL" in event_type


def _failure_message(event: DagsterRunEvent) -> str | None:
    if event.error is not None:
        if event.error.class_name and event.error.message:
            return f"{event.error.class_name}: {event.error.message}"
        if event.error.message:
            return event.error.message
        if event.error.class_name:
            return event.error.class_name
        return event.error.stack[0] if event.error.stack else None
    return event.message


def _run_failures(events: list[DagsterRunEvent]) -> list[DagsterRunFailure]:
    return [
        DagsterRunFailure(
            event_type=event.event_type,
            message=_failure_message(event),
            timestamp=event.timestamp,
            level=event.level,
            step_id=event.step_id,
            dagster_event_type=event.dagster_event_type,
            error=event.error,
        )
        for event in events
        if _is_failure_event(event)
    ]


def _parse_run_detail(
    raw_run: JsonDict,
    *,
    dagster_urls: _DagsterUrls,
    checked_at: datetime,
) -> DagsterRunDetailData:
    typename = _string(raw_run.get("__typename"))
    if typename == "Run":
        event_connection = _dict(raw_run.get("eventConnection"))
        events = [
            _parse_run_event(raw_event)
            for raw_event in _list(event_connection.get("events"))
        ]
        failure_events = _run_failures(events)
        return DagsterRunDetailData(
            status="ok",
            dagster_url=dagster_urls.dagster_url,
            graphql_url=dagster_urls.graphql_url,
            checked_at=checked_at,
            run=_parse_run_summary(raw_run),
            events=events,
            failure_reason=(
                failure_events[-1].message if failure_events else None
            ),
            failure_events=failure_events,
            event_cursor=_optional_string(event_connection.get("cursor")),
            event_has_more=bool(event_connection.get("hasMore")),
        )
    if typename == "RunNotFoundError":
        return DagsterRunDetailData(
            status="not_found",
            dagster_url=dagster_urls.dagster_url,
            graphql_url=dagster_urls.graphql_url,
            checked_at=checked_at,
            errors=[_string(raw_run.get("message"), "Dagster run을 찾을 수 없습니다.")],
        )
    if typename == "PythonError":
        message = _optional_string(raw_run.get("message")) or "Dagster run 상세 조회 실패"
        return DagsterRunDetailData(
            status="error",
            dagster_url=dagster_urls.dagster_url,
            graphql_url=dagster_urls.graphql_url,
            checked_at=checked_at,
            errors=[message],
        )
    return DagsterRunDetailData(
        status="error",
        dagster_url=dagster_urls.dagster_url,
        graphql_url=dagster_urls.graphql_url,
        checked_at=checked_at,
        errors=[f"알 수 없는 Dagster run 응답 타입: {typename or 'unknown'}"],
    )


async def _post_graphql(
    client: httpx.AsyncClient,
    graphql_url: str,
    variables: dict[str, object],
    query: str = _DAGSTER_SUMMARY_QUERY,
) -> JsonDict:
    response = await client.post(
        graphql_url,
        json={"query": query, "variables": variables},
    )
    response.raise_for_status()
    payload = response.json()
    return _dict(payload)


def _settings_from_request(request: Request) -> ApiSettings:
    settings = getattr(request.app.state, "settings", None)
    if isinstance(settings, ApiSettings):
        return settings
    return ApiSettings()


def _http_client_from_request(
    request: Request,
    settings: ApiSettings,
) -> httpx.AsyncClient:
    client = getattr(request.app.state, "dagster_http_client", None)
    if isinstance(client, httpx.AsyncClient) and not client.is_closed:
        return client
    client = httpx.AsyncClient(timeout=settings.dagster_request_timeout_seconds)
    request.app.state.dagster_http_client = client
    return client


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
    typename = _optional_string(result.get("__typename"))
    if typename in {
        "ScheduleStateResult",
        "LaunchRunSuccess",
        "WorkspaceLocationEntry",
    }:
        return None
    if typename == "RunConfigValidationInvalid":
        errors = [
            _optional_string(_dict(error).get("message")) or str(error)
            for error in _list(result.get("errors"))
        ]
        return " / ".join(errors) if errors else "run config validation failed"
    message = _optional_string(result.get("message"))
    class_name = _optional_string(result.get("className"))
    if class_name and message:
        return f"{class_name}: {message}"
    return message or f"Dagster mutation failed: {typename or 'unknown'}"


def _command_error_data(
    *,
    dagster_urls: _DagsterUrls,
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
        default_cron_schedule=_DEFAULT_SCHEDULE_CRONS.get(schedule_name),
        errors=[error],
    )


async def _repository_schedules(
    *,
    client: httpx.AsyncClient,
    dagster_urls: _DagsterUrls,
    overrides: dict[str, str] | None = None,
) -> tuple[list[DagsterRepository], list[str]]:
    payload = await _post_graphql(
        client=client,
        graphql_url=dagster_urls.graphql_url,
        variables={},
        query=_DAGSTER_SCHEDULES_QUERY,
    )
    graphql_errors = payload.get("errors")
    if isinstance(graphql_errors, list) and graphql_errors:
        return [], [_graphql_error_message(error) for error in graphql_errors]
    data = _dict(payload.get("data"))
    return _parse_repositories(
        _dict(data.get("repositoriesOrError")),
        overrides=overrides,
    )


async def _find_schedule(
    *,
    client: httpx.AsyncClient,
    dagster_urls: _DagsterUrls,
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
    dagster_urls: _DagsterUrls,
    repository_location_name: str | None,
) -> tuple[bool, str | None]:
    if not repository_location_name:
        return False, "repository location 이름이 없습니다."
    try:
        payload = await _post_graphql(
            client=client,
            graphql_url=dagster_urls.graphql_url,
            variables={"repositoryLocationName": repository_location_name},
            query=_DAGSTER_RELOAD_LOCATION_MUTATION,
        )
    except httpx.HTTPError as exc:
        return False, f"code location reload 요청 실패: {exc}"
    graphql_errors = payload.get("errors")
    if isinstance(graphql_errors, list) and graphql_errors:
        return False, " / ".join(_graphql_error_message(error) for error in graphql_errors)
    result = _dict(_dict(payload.get("data")).get("reloadRepositoryLocation"))
    error = _graphql_result_error(result)
    return error is None, error


def _summary_response(
    data: DagsterSummaryData, *, started_at: float
) -> DagsterSummaryResponse:
    return DagsterSummaryResponse(
        data=data,
        meta=make_meta(started_at=started_at),
    )


def _nux_seen_response(
    data: DagsterNuxSeenData, *, started_at: float
) -> DagsterNuxSeenResponse:
    return DagsterNuxSeenResponse(
        data=data,
        meta=make_meta(started_at=started_at),
    )


def _run_detail_response(
    data: DagsterRunDetailData, *, started_at: float
) -> DagsterRunDetailResponse:
    return DagsterRunDetailResponse(
        data=data,
        meta=make_meta(started_at=started_at),
    )


@router.get(
    "/summary",
    response_model=DagsterSummaryResponse,
    summary="작업 자동화 요약",
    description=(
        "Dagster GraphQL에서 repository, asset, schedule/sensor, recent run 정보를 "
        "읽어 admin UI 요약 DTO로 반환한다. Dagster webserver가 내려가도 200 "
        "응답(status=unavailable)으로 UI가 장애 상태를 표시할 수 있게 한다. "
        "GET은 조회 전용이며 Dagster mutation은 호출하지 않는다."
    ),
)
async def get_dagster_summary(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    page_size: int = Query(default=10, ge=1, le=50),
) -> DagsterSummaryResponse:
    started_at = perf_counter()
    settings = _settings_from_request(request)
    checked_at = datetime.now(UTC)
    raw_graphql_url = _candidate_graphql_url(settings)

    try:
        dagster_urls = _dagster_urls(settings)
    except DagsterUrlConfigurationError as exc:
        return _summary_response(
            DagsterSummaryData(
                status="error",
                dagster_url=settings.dagster_url,
                graphql_url=raw_graphql_url,
                checked_at=checked_at,
                repository_count=0,
                job_count=0,
                asset_count=0,
                schedule_count=0,
                sensor_count=0,
                run_counts={},
                repositories=[],
                recent_runs=[],
                errors=[str(exc)],
            ),
            started_at=started_at,
        )

    client = _http_client_from_request(request, settings)

    try:
        payload = await _post_graphql(
            client=client,
            graphql_url=dagster_urls.graphql_url,
            variables={"limit": page_size},
        )
    except (httpx.HTTPError, ValueError) as exc:
        return _summary_response(
            DagsterSummaryData(
                status="unavailable",
                dagster_url=dagster_urls.dagster_url,
                graphql_url=dagster_urls.graphql_url,
                checked_at=checked_at,
                repository_count=0,
                job_count=0,
                asset_count=0,
                schedule_count=0,
                sensor_count=0,
                run_counts={},
                repositories=[],
                recent_runs=[],
                errors=[str(exc)],
            ),
            started_at=started_at,
        )

    graphql_errors = payload.get("errors")
    if isinstance(graphql_errors, list) and graphql_errors:
        return _summary_response(
            DagsterSummaryData(
                status="error",
                dagster_url=dagster_urls.dagster_url,
                graphql_url=dagster_urls.graphql_url,
                checked_at=checked_at,
                repository_count=0,
                job_count=0,
                asset_count=0,
                schedule_count=0,
                sensor_count=0,
                run_counts={},
                repositories=[],
                recent_runs=[],
                errors=[str(error) for error in graphql_errors],
            ),
            started_at=started_at,
        )

    data = _dict(payload.get("data"))
    overrides = await _schedule_overrides(session)
    repositories, repository_errors = _parse_repositories(
        _dict(data.get("repositoriesOrError")),
        overrides=overrides,
    )
    recent_runs, run_counts, run_errors = _parse_runs(_dict(data.get("runsOrError")))
    errors = [*repository_errors, *run_errors]

    return _summary_response(
        DagsterSummaryData(
            status="error" if errors else "ok",
            dagster_url=dagster_urls.dagster_url,
            graphql_url=dagster_urls.graphql_url,
            version=_optional_string(data.get("version")),
            checked_at=checked_at,
            repository_count=len(repositories),
            job_count=sum(len(repository.jobs) for repository in repositories),
            asset_count=sum(repository.asset_count for repository in repositories),
            schedule_count=sum(len(repository.schedules) for repository in repositories),
            sensor_count=sum(len(repository.sensors) for repository in repositories),
            run_counts=run_counts,
            repositories=repositories,
            recent_runs=recent_runs,
            errors=errors,
        ),
        started_at=started_at,
    )


@router.get(
    "/runs/{run_id}",
    response_model=DagsterRunDetailResponse,
    summary="Dagster run 상세",
    description=(
        "Dagster GraphQL runOrError를 조회해 최근 event log와 실패 error payload를 "
        "admin UI용 DTO로 반환한다. 조회 전용이며 Dagster run을 재실행하거나 "
        "상태를 변경하지 않는다."
    ),
)
async def get_dagster_run_detail(
    request: Request,
    run_id: str,
    page_size: int = Query(default=50, ge=1, le=200),
    after: str | None = Query(
        default=None,
        description=(
            "event log cursor(이전 응답의 event_cursor). 긴 run의 뒤쪽(실패) 이벤트로 "
            "전진 페이지네이션하기 위함. 미지정이면 처음부터."
        ),
    ),
) -> DagsterRunDetailResponse:
    started_at = perf_counter()
    settings = _settings_from_request(request)
    checked_at = datetime.now(UTC)
    raw_graphql_url = _candidate_graphql_url(settings)

    try:
        dagster_urls = _dagster_urls(settings)
    except DagsterUrlConfigurationError as exc:
        return _run_detail_response(
            DagsterRunDetailData(
                status="error",
                dagster_url=settings.dagster_url,
                graphql_url=raw_graphql_url,
                checked_at=checked_at,
                errors=[str(exc)],
            ),
            started_at=started_at,
        )

    client = _http_client_from_request(request, settings)
    try:
        payload = await _post_graphql(
            client=client,
            graphql_url=dagster_urls.graphql_url,
            variables={
                "runId": run_id,
                "eventLimit": page_size,
                "afterCursor": after,
            },
            query=_DAGSTER_RUN_DETAIL_QUERY,
        )
    except (httpx.HTTPError, ValueError) as exc:
        return _run_detail_response(
            DagsterRunDetailData(
                status="unavailable",
                dagster_url=dagster_urls.dagster_url,
                graphql_url=dagster_urls.graphql_url,
                checked_at=checked_at,
                errors=[str(exc)],
            ),
            started_at=started_at,
        )

    graphql_errors = payload.get("errors")
    if isinstance(graphql_errors, list) and graphql_errors:
        return _run_detail_response(
            DagsterRunDetailData(
                status="error",
                dagster_url=dagster_urls.dagster_url,
                graphql_url=dagster_urls.graphql_url,
                checked_at=checked_at,
                errors=[_graphql_error_message(error) for error in graphql_errors],
            ),
            started_at=started_at,
        )

    data = _dict(payload.get("data"))
    return _run_detail_response(
        _parse_run_detail(
            _dict(data.get("runOrError")),
            dagster_urls=dagster_urls,
            checked_at=checked_at,
        ),
        started_at=started_at,
    )


@router.post(
    "/nux-seen",
    response_model=DagsterNuxSeenResponse,
    summary="Dagster NUX seen 처리",
    description=(
        "embedded Dagster 화면의 로컬 첫 실행 NUX를 접기 위해 Dagster GraphQL "
        "setNuxSeen mutation을 호출한다. GET summary의 부수효과를 제거하기 위해 "
        "명시 POST endpoint로 분리했다."
    ),
)
async def mark_dagster_nux_seen(request: Request) -> DagsterNuxSeenResponse:
    started_at = perf_counter()
    settings = _settings_from_request(request)
    checked_at = datetime.now(UTC)
    raw_graphql_url = _candidate_graphql_url(settings)

    try:
        dagster_urls = _dagster_urls(settings)
    except DagsterUrlConfigurationError as exc:
        return _nux_seen_response(
            DagsterNuxSeenData(
                status="error",
                dagster_url=settings.dagster_url,
                graphql_url=raw_graphql_url,
                checked_at=checked_at,
                seen=False,
                errors=[str(exc)],
            ),
            started_at=started_at,
        )

    client = _http_client_from_request(request, settings)
    try:
        payload = await _post_graphql(
            client=client,
            graphql_url=dagster_urls.graphql_url,
            variables={},
            query=_DAGSTER_SET_NUX_SEEN_MUTATION,
        )
    except (httpx.HTTPError, ValueError) as exc:
        return _nux_seen_response(
            DagsterNuxSeenData(
                status="unavailable",
                dagster_url=dagster_urls.dagster_url,
                graphql_url=dagster_urls.graphql_url,
                checked_at=checked_at,
                seen=False,
                errors=[str(exc)],
            ),
            started_at=started_at,
        )

    graphql_errors = payload.get("errors")
    if isinstance(graphql_errors, list) and graphql_errors:
        return _nux_seen_response(
            DagsterNuxSeenData(
                status="error",
                dagster_url=dagster_urls.dagster_url,
                graphql_url=dagster_urls.graphql_url,
                checked_at=checked_at,
                seen=False,
                errors=[str(error) for error in graphql_errors],
            ),
            started_at=started_at,
        )

    seen = _dict(payload.get("data")).get("setNuxSeen") is True
    return _nux_seen_response(
        DagsterNuxSeenData(
            status="ok" if seen else "error",
            dagster_url=dagster_urls.dagster_url,
            graphql_url=dagster_urls.graphql_url,
            checked_at=checked_at,
            seen=seen,
            errors=[] if seen else ["Dagster setNuxSeen mutation did not return true"],
        ),
        started_at=started_at,
    )


async def _schedule_write_context(
    request: Request,
    *,
    started_at: float,
    checked_at: datetime,
    schedule_name: str,
    command: Literal["update", "default", "start", "stop", "reset", "run"],
) -> tuple[ApiSettings, _DagsterUrls, httpx.AsyncClient] | DagsterScheduleCommandResponse:
    settings = _settings_from_request(request)
    raw_graphql_url = _candidate_graphql_url(settings)
    try:
        dagster_urls = _dagster_urls(settings)
    except DagsterUrlConfigurationError as exc:
        return _schedule_command_response(
            DagsterScheduleCommandData(
                status="error",
                dagster_url=settings.dagster_url,
                graphql_url=raw_graphql_url,
                checked_at=checked_at,
                schedule_name=schedule_name,
                command=command,
                errors=[str(exc)],
            ),
            started_at=started_at,
        )
    return settings, dagster_urls, _http_client_from_request(request, settings)


@router.patch(
    "/schedules/{schedule_name}",
    response_model=DagsterScheduleCommandResponse,
    summary="운영 스케줄 cron 수정",
    description=(
        "운영 스케줄의 cron override를 저장하고 code location reload를 요청한다. "
        "cron은 코드 정의를 직접 변경하지 않고 ops.dagster_schedule_overrides에 보관된다."
    ),
)
async def update_dagster_schedule(
    request: Request,
    schedule_name: str,
    body: DagsterScheduleOverrideRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> DagsterScheduleCommandResponse:
    started_at = perf_counter()
    checked_at = datetime.now(UTC)
    context = await _schedule_write_context(
        request,
        started_at=started_at,
        checked_at=checked_at,
        schedule_name=schedule_name,
        command="update",
    )
    if isinstance(context, DagsterScheduleCommandResponse):
        return context
    _, dagster_urls, client = context
    overrides = await _schedule_overrides(session)
    try:
        cron_schedule = _validate_cron_schedule(body.cron_schedule)
        schedule, errors = await _find_schedule(
            client=client,
            dagster_urls=dagster_urls,
            schedule_name=schedule_name,
            overrides=overrides,
        )
    except (httpx.HTTPError, ValueError) as exc:
        return _schedule_command_response(
            _command_error_data(
                dagster_urls=dagster_urls,
                checked_at=checked_at,
                schedule_name=schedule_name,
                command="update",
                error=str(exc),
            ),
            started_at=started_at,
        )
    if schedule is None:
        return _schedule_command_response(
            _command_error_data(
                dagster_urls=dagster_urls,
                checked_at=checked_at,
                schedule_name=schedule_name,
                command="update",
                error=" / ".join(errors),
            ),
            started_at=started_at,
        )
    await _upsert_schedule_override(
        session,
        schedule_name=schedule_name,
        cron_schedule=cron_schedule,
        operator=body.operator,
        reason=body.reason,
    )
    reloaded, reload_error = await _reload_location(
        client=client,
        dagster_urls=dagster_urls,
        repository_location_name=schedule.repository_location_name,
    )
    return _schedule_command_response(
        DagsterScheduleCommandData(
            status="ok",
            dagster_url=dagster_urls.dagster_url,
            graphql_url=dagster_urls.graphql_url,
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


@router.post(
    "/schedules/{schedule_name}/default",
    response_model=DagsterScheduleCommandResponse,
    summary="운영 스케줄 기본값 복귀",
    description="운영 스케줄 cron override를 삭제하고 code location reload를 요청한다.",
)
async def reset_dagster_schedule_default(
    request: Request,
    schedule_name: str,
    session: Annotated[AsyncSession, Depends(get_session)],
    body: DagsterScheduleCommandRequest | None = None,
) -> DagsterScheduleCommandResponse:
    del body
    started_at = perf_counter()
    checked_at = datetime.now(UTC)
    context = await _schedule_write_context(
        request,
        started_at=started_at,
        checked_at=checked_at,
        schedule_name=schedule_name,
        command="default",
    )
    if isinstance(context, DagsterScheduleCommandResponse):
        return context
    _, dagster_urls, client = context
    overrides = await _schedule_overrides(session)
    try:
        schedule, errors = await _find_schedule(
            client=client,
            dagster_urls=dagster_urls,
            schedule_name=schedule_name,
            overrides=overrides,
        )
    except (httpx.HTTPError, ValueError) as exc:
        return _schedule_command_response(
            _command_error_data(
                dagster_urls=dagster_urls,
                checked_at=checked_at,
                schedule_name=schedule_name,
                command="default",
                error=str(exc),
            ),
            started_at=started_at,
        )
    if schedule is None:
        return _schedule_command_response(
            _command_error_data(
                dagster_urls=dagster_urls,
                checked_at=checked_at,
                schedule_name=schedule_name,
                command="default",
                error=" / ".join(errors),
            ),
            started_at=started_at,
        )
    await _delete_schedule_override(session, schedule_name=schedule_name)
    reloaded, reload_error = await _reload_location(
        client=client,
        dagster_urls=dagster_urls,
        repository_location_name=schedule.repository_location_name,
    )
    return _schedule_command_response(
        DagsterScheduleCommandData(
            status="ok",
            dagster_url=dagster_urls.dagster_url,
            graphql_url=dagster_urls.graphql_url,
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


async def _mutate_schedule_state(
    *,
    request: Request,
    schedule_name: str,
    command: Literal["start", "stop", "reset"],
    session: AsyncSession,
) -> DagsterScheduleCommandResponse:
    started_at = perf_counter()
    checked_at = datetime.now(UTC)
    context = await _schedule_write_context(
        request,
        started_at=started_at,
        checked_at=checked_at,
        schedule_name=schedule_name,
        command=command,
    )
    if isinstance(context, DagsterScheduleCommandResponse):
        return context
    _, dagster_urls, client = context
    overrides = await _schedule_overrides(session)
    try:
        schedule, errors = await _find_schedule(
            client=client,
            dagster_urls=dagster_urls,
            schedule_name=schedule_name,
            overrides=overrides,
        )
    except (httpx.HTTPError, ValueError) as exc:
        return _schedule_command_response(
            _command_error_data(
                dagster_urls=dagster_urls,
                checked_at=checked_at,
                schedule_name=schedule_name,
                command=command,
                error=str(exc),
            ),
            started_at=started_at,
        )
    if schedule is None:
        return _schedule_command_response(
            _command_error_data(
                dagster_urls=dagster_urls,
                checked_at=checked_at,
                schedule_name=schedule_name,
                command=command,
                error=" / ".join(errors),
            ),
            started_at=started_at,
        )

    selector = _schedule_selector(schedule)
    if command == "start":
        query = _DAGSTER_START_SCHEDULE_MUTATION
        variables = {"selector": selector}
        result_key = "startSchedule"
    elif command == "reset":
        query = _DAGSTER_RESET_SCHEDULE_MUTATION
        variables = {"selector": selector}
        result_key = "resetSchedule"
    else:
        query = _DAGSTER_STOP_SCHEDULE_MUTATION
        variables = {
            "id": schedule.state_id,
            "originId": _schedule_origin_id(schedule.state_id),
            "selectorId": schedule.selector_id,
        }
        result_key = "stopRunningSchedule"

    try:
        payload = await _post_graphql(
            client=client,
            graphql_url=dagster_urls.graphql_url,
            variables=variables,
            query=query,
        )
    except (httpx.HTTPError, ValueError) as exc:
        return _schedule_command_response(
            _command_error_data(
                dagster_urls=dagster_urls,
                checked_at=checked_at,
                schedule_name=schedule_name,
                command=command,
                error=str(exc),
            ),
            started_at=started_at,
        )
    graphql_errors = payload.get("errors")
    if isinstance(graphql_errors, list) and graphql_errors:
        error = " / ".join(_graphql_error_message(item) for item in graphql_errors)
        return _schedule_command_response(
            _command_error_data(
                dagster_urls=dagster_urls,
                checked_at=checked_at,
                schedule_name=schedule_name,
                command=command,
                error=error,
            ),
            started_at=started_at,
        )

    result = _dict(_dict(payload.get("data")).get(result_key))
    error = _graphql_result_error(result)
    state = _dict(result.get("scheduleState"))
    return _schedule_command_response(
        DagsterScheduleCommandData(
            status="ok" if error is None else "error",
            dagster_url=dagster_urls.dagster_url,
            graphql_url=dagster_urls.graphql_url,
            checked_at=checked_at,
            schedule_name=schedule_name,
            command=command,
            cron_schedule=schedule.cron_schedule,
            default_cron_schedule=schedule.default_cron_schedule,
            override_cron_schedule=schedule.override_cron_schedule,
            schedule_status=_optional_string(state.get("status")) or schedule.status,
            errors=[] if error is None else [error],
        ),
        started_at=started_at,
    )


@router.post(
    "/schedules/{schedule_name}/start",
    response_model=DagsterScheduleCommandResponse,
    summary="운영 스케줄 시작",
)
async def start_dagster_schedule(
    request: Request,
    schedule_name: str,
    session: Annotated[AsyncSession, Depends(get_session)],
    body: DagsterScheduleCommandRequest | None = None,
) -> DagsterScheduleCommandResponse:
    del body
    return await _mutate_schedule_state(
        request=request,
        schedule_name=schedule_name,
        command="start",
        session=session,
    )


@router.post(
    "/schedules/{schedule_name}/stop",
    response_model=DagsterScheduleCommandResponse,
    summary="운영 스케줄 중지",
)
async def stop_dagster_schedule(
    request: Request,
    schedule_name: str,
    session: Annotated[AsyncSession, Depends(get_session)],
    body: DagsterScheduleCommandRequest | None = None,
) -> DagsterScheduleCommandResponse:
    del body
    return await _mutate_schedule_state(
        request=request,
        schedule_name=schedule_name,
        command="stop",
        session=session,
    )


@router.post(
    "/schedules/{schedule_name}/reset",
    response_model=DagsterScheduleCommandResponse,
    summary="운영 스케줄 상태 기본값 복귀",
)
async def reset_dagster_schedule_state(
    request: Request,
    schedule_name: str,
    session: Annotated[AsyncSession, Depends(get_session)],
    body: DagsterScheduleCommandRequest | None = None,
) -> DagsterScheduleCommandResponse:
    del body
    return await _mutate_schedule_state(
        request=request,
        schedule_name=schedule_name,
        command="reset",
        session=session,
    )


@router.post(
    "/schedules/{schedule_name}/run",
    response_model=DagsterScheduleCommandResponse,
    summary="운영 스케줄 즉시 실행",
    description="스케줄이 가리키는 job을 현재 설정으로 1회 실행한다.",
)
async def run_dagster_schedule_now(
    request: Request,
    schedule_name: str,
    session: Annotated[AsyncSession, Depends(get_session)],
    body: DagsterScheduleCommandRequest | None = None,
) -> DagsterScheduleCommandResponse:
    started_at = perf_counter()
    checked_at = datetime.now(UTC)
    context = await _schedule_write_context(
        request,
        started_at=started_at,
        checked_at=checked_at,
        schedule_name=schedule_name,
        command="run",
    )
    if isinstance(context, DagsterScheduleCommandResponse):
        return context
    _, dagster_urls, client = context
    overrides = await _schedule_overrides(session)
    try:
        schedule, errors = await _find_schedule(
            client=client,
            dagster_urls=dagster_urls,
            schedule_name=schedule_name,
            overrides=overrides,
        )
    except (httpx.HTTPError, ValueError) as exc:
        return _schedule_command_response(
            _command_error_data(
                dagster_urls=dagster_urls,
                checked_at=checked_at,
                schedule_name=schedule_name,
                command="run",
                error=str(exc),
            ),
            started_at=started_at,
        )
    if schedule is None or not schedule.pipeline_name:
        return _schedule_command_response(
            _command_error_data(
                dagster_urls=dagster_urls,
                checked_at=checked_at,
                schedule_name=schedule_name,
                command="run",
                error=" / ".join(errors) if errors else "schedule job 이름이 없습니다.",
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
                schedule.repository_location_name
                or "kortravelmap.dagster.definitions"
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
        payload = await _post_graphql(
            client=client,
            graphql_url=dagster_urls.graphql_url,
            variables={"executionParams": execution_params},
            query=_DAGSTER_LAUNCH_RUN_MUTATION,
        )
    except (httpx.HTTPError, ValueError) as exc:
        return _schedule_command_response(
            _command_error_data(
                dagster_urls=dagster_urls,
                checked_at=checked_at,
                schedule_name=schedule_name,
                command="run",
                error=str(exc),
            ),
            started_at=started_at,
        )
    graphql_errors = payload.get("errors")
    if isinstance(graphql_errors, list) and graphql_errors:
        error = " / ".join(_graphql_error_message(item) for item in graphql_errors)
        return _schedule_command_response(
            _command_error_data(
                dagster_urls=dagster_urls,
                checked_at=checked_at,
                schedule_name=schedule_name,
                command="run",
                error=error,
            ),
            started_at=started_at,
        )
    result = _dict(_dict(payload.get("data")).get("launchRun"))
    error = _graphql_result_error(result)
    run = _dict(result.get("run"))
    return _schedule_command_response(
        DagsterScheduleCommandData(
            status="ok" if error is None else "error",
            dagster_url=dagster_urls.dagster_url,
            graphql_url=dagster_urls.graphql_url,
            checked_at=checked_at,
            schedule_name=schedule_name,
            command="run",
            cron_schedule=schedule.cron_schedule,
            default_cron_schedule=schedule.default_cron_schedule,
            override_cron_schedule=schedule.override_cron_schedule,
            schedule_status=schedule.status,
            run_id=_optional_string(run.get("runId")),
            run_status=_optional_string(run.get("status")),
            errors=[] if error is None else [error],
        ),
        started_at=started_at,
    )
