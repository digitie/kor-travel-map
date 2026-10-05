"""Dagster summary and run-detail query application service."""

from __future__ import annotations

from datetime import UTC, datetime
from time import perf_counter

import httpx

from kortravelmap.api import dagster_graphql
from kortravelmap.api.dagster_schema import (
    DagsterRunDetailData,
    DagsterRunDetailResponse,
    DagsterSummaryData,
    DagsterSummaryResponse,
)
from kortravelmap.api.response import make_meta
from kortravelmap.api.settings import ApiSettings

__all__ = [
    "get_run_detail",
    "get_run_detail_configuration_error",
    "get_summary",
    "get_summary_configuration_error",
]

# 모든 tick 상태를 명시하면 전체 이력 batch rank 대신 selector별 LIMIT 조회를 사용한다.
# 공용 Dagster의 이력이 커져도 최신 3건의 정보와 상태를 그대로 제공한다.
_DAGSTER_SUMMARY_QUERY = """
query KorTravelMapDagsterSummary(
  $limit: Int!, $repositorySelector: RepositorySelector!,
  $runsFilter: RunsFilter!, $activeRunsFilter: RunsFilter!
) {
  version
  repositoryOrError(repositorySelector: $repositorySelector) {
    __typename
    ... on Repository {
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
          ticks(limit: 3, statuses: [STARTED, SKIPPED, SUCCESS, FAILURE]) {
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
          ticks(limit: 3, statuses: [STARTED, SKIPPED, SUCCESS, FAILURE]) {
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
    ... on RepositoryNotFoundError { message }
    ... on PythonError {
      message
    }
  }
  runsOrError(filter: $runsFilter, limit: $limit) {
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
  activeRunsOrError: runsOrError(filter: $activeRunsFilter, limit: 1000) {
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
      repositoryOrigin { repositoryName repositoryLocationName }
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


def _valid_summary_repository(raw: object, selector: dict[str, str]) -> bool:
    """필수 GraphQL 필드를 잃은 repository를 정상 빈 스냅샷으로 표시하지 않는다."""
    if not isinstance(raw, dict) or raw.get("__typename") != "Repository":
        return False
    if not isinstance(raw.get("name"), str) or not raw["name"].strip():
        return False
    location = raw.get("location")
    if (
        not isinstance(location, dict)
        or not isinstance(location.get("name"), str)
        or not location["name"].strip()
    ):
        return False
    if (
        raw["name"] != selector["repositoryName"]
        or location["name"] != selector["repositoryLocationName"]
    ):
        return False
    for key in ("pipelines", "schedules", "sensors", "assetNodes"):
        rows = raw.get(key)
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            return False
        for row in rows:
            if key == "assetNodes":
                asset_key = row.get("assetKey")
                path = asset_key.get("path") if isinstance(asset_key, dict) else None
                if (
                    not isinstance(path, list)
                    or not path
                    or any(not isinstance(part, str) or not part for part in path)
                ):
                    return False
            elif (
                not isinstance(row.get("name"), str)
                or not row["name"].strip()
                or key == "pipelines"
                and not isinstance(row.get("isJob"), bool)
            ):
                return False
    return True


def _summary_response(data: DagsterSummaryData, *, started_at: float) -> DagsterSummaryResponse:
    return DagsterSummaryResponse(data=data, meta=make_meta(started_at=started_at))


def _run_detail_response(
    data: DagsterRunDetailData, *, started_at: float
) -> DagsterRunDetailResponse:
    return DagsterRunDetailResponse(data=data, meta=make_meta(started_at=started_at))


def get_summary_configuration_error(settings: ApiSettings) -> DagsterSummaryResponse | None:
    """잘못된 Dagster URL 설정을 외부 자원 접근 전에 안전한 응답으로 바꾼다."""

    started_at = perf_counter()
    try:
        dagster_graphql.dagster_urls(settings)
    except dagster_graphql.DagsterUrlConfigurationError:
        return _summary_response(
            DagsterSummaryData(
                status="error",
                dagster_url="",
                graphql_url="",
                checked_at=datetime.now(UTC),
                repository_count=0,
                job_count=0,
                asset_count=0,
                schedule_count=0,
                sensor_count=0,
                run_counts={},
                repositories=[],
                recent_runs=[],
                errors=["Dagster 조회를 완료하지 못했습니다. 잠시 후 다시 시도하세요."],
            ),
            started_at=started_at,
        )
    return None


def get_run_detail_configuration_error(
    settings: ApiSettings,
) -> DagsterRunDetailResponse | None:
    """잘못된 Dagster URL을 run detail 외부 자원 접근 전에 차단한다."""

    started_at = perf_counter()
    try:
        dagster_graphql.dagster_urls(settings)
    except dagster_graphql.DagsterUrlConfigurationError as exc:
        return _run_detail_response(
            DagsterRunDetailData(
                status="error",
                dagster_url="",
                graphql_url="",
                checked_at=datetime.now(UTC),
                errors=[str(exc)],
            ),
            started_at=started_at,
        )
    return None


async def get_summary(
    *,
    settings: ApiSettings,
    client: httpx.AsyncClient,
    overrides: dict[str, str],
    page_size: int,
) -> DagsterSummaryResponse:
    """Dagster summary를 조회해 legacy 응답 계약으로 반환한다."""

    configuration_error = get_summary_configuration_error(settings)
    if configuration_error is not None:
        return configuration_error

    started_at = perf_counter()
    checked_at = datetime.now(UTC)
    urls = dagster_graphql.dagster_urls(settings)
    try:
        payload = await dagster_graphql.post_graphql(
            client=client,
            graphql_url=urls.graphql_url,
            variables={
                "limit": page_size,
                "repositorySelector": urls.repository_selector(),
                "runsFilter": urls.runs_filter(),
                "activeRunsFilter": urls.runs_filter(
                    statuses=dagster_graphql.ACTIVE_RUN_STATUSES,
                ),
            },
            query=_DAGSTER_SUMMARY_QUERY,
        )
    except (httpx.HTTPError, ValueError):
        return _summary_response(
            DagsterSummaryData(
                status="unavailable",
                dagster_url=urls.dagster_url,
                graphql_url=urls.public_graphql_url,
                checked_at=checked_at,
                repository_count=0,
                job_count=0,
                asset_count=0,
                schedule_count=0,
                sensor_count=0,
                run_counts={},
                repositories=[],
                recent_runs=[],
                errors=["Dagster 조회를 완료하지 못했습니다. 잠시 후 다시 시도하세요."],
            ),
            started_at=started_at,
        )
    graphql_errors = payload.get("errors")
    if isinstance(graphql_errors, list) and graphql_errors:
        return _summary_response(
            DagsterSummaryData(
                status="error",
                dagster_url=urls.dagster_url,
                graphql_url=urls.public_graphql_url,
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
    data = dagster_graphql.as_dict(payload.get("data"))
    repositories, repository_errors = dagster_graphql.parse_repositories(
        dagster_graphql.repository_connection(
            dagster_graphql.as_dict(data.get("repositoryOrError"))
        ),
        overrides=overrides,
    )
    recent_runs, run_counts, run_errors = dagster_graphql.merge_recent_active_runs(
        data, recent_limit=page_size
    )
    errors = [*repository_errors, *run_errors]
    if not repository_errors and not _valid_summary_repository(
        data.get("repositoryOrError"), urls.repository_selector()
    ):
        repositories = []
        errors.append("Dagster repository 응답의 필수 필드·소속을 확인하지 못했습니다.")
    return _summary_response(
        DagsterSummaryData(
            status="error" if errors else "ok",
            dagster_url=urls.dagster_url,
            graphql_url=urls.public_graphql_url,
            version=dagster_graphql.optional_string(data.get("version")),
            checked_at=checked_at,
            repository_count=len(repositories),
            job_count=sum(len(item.jobs) for item in repositories),
            asset_count=sum(item.asset_count for item in repositories),
            schedule_count=sum(len(item.schedules) for item in repositories),
            sensor_count=sum(len(item.sensors) for item in repositories),
            run_counts=run_counts,
            repositories=repositories,
            recent_runs=recent_runs,
            errors=errors,
        ),
        started_at=started_at,
    )


async def get_run_detail(
    *,
    settings: ApiSettings,
    client: httpx.AsyncClient,
    run_id: str,
    page_size: int,
    after: str | None,
) -> DagsterRunDetailResponse:
    """Dagster run event page를 조회한다."""

    configuration_error = get_run_detail_configuration_error(settings)
    if configuration_error is not None:
        return configuration_error

    started_at = perf_counter()
    checked_at = datetime.now(UTC)
    urls = dagster_graphql.dagster_urls(settings)
    try:
        payload = await dagster_graphql.post_graphql(
            client=client,
            graphql_url=urls.graphql_url,
            variables={
                "runId": run_id,
                "eventLimit": page_size,
                "afterCursor": after,
            },
            query=_DAGSTER_RUN_DETAIL_QUERY,
        )
    except (httpx.HTTPStatusError, ValueError) as exc:
        return _run_detail_response(
            DagsterRunDetailData(
                status="error",
                dagster_url=urls.dagster_url,
                graphql_url=urls.public_graphql_url,
                checked_at=checked_at,
                errors=[str(exc)],
            ),
            started_at=started_at,
        )
    except httpx.RequestError as exc:
        return _run_detail_response(
            DagsterRunDetailData(
                status="unavailable",
                dagster_url=urls.dagster_url,
                graphql_url=urls.public_graphql_url,
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
                dagster_url=urls.dagster_url,
                graphql_url=urls.public_graphql_url,
                checked_at=checked_at,
                errors=[dagster_graphql.graphql_error_message(error) for error in graphql_errors],
            ),
            started_at=started_at,
        )
    data = dagster_graphql.as_dict(payload.get("data"))
    return _run_detail_response(
        dagster_graphql.parse_run_detail(
            dagster_graphql.as_dict(data.get("runOrError")),
            dagster_urls=urls,
            checked_at=checked_at,
            expected_run_id=run_id,
        ),
        started_at=started_at,
    )
