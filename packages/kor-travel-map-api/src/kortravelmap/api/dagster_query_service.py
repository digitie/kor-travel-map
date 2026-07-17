"""Dagster summary, run detail, and NUX query application service."""

from __future__ import annotations

from datetime import UTC, datetime
from time import perf_counter

import httpx

from kortravelmap.api import dagster_graphql
from kortravelmap.api.dagster_schema import (
    DagsterNuxSeenData,
    DagsterNuxSeenResponse,
    DagsterRunDetailData,
    DagsterRunDetailResponse,
    DagsterSummaryData,
    DagsterSummaryResponse,
)
from kortravelmap.api.response import make_meta
from kortravelmap.api.settings import ApiSettings

__all__ = [
    "get_run_detail",
    "get_summary",
    "get_summary_configuration_error",
    "mark_nux_seen",
]

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


def _summary_response(data: DagsterSummaryData, *, started_at: float) -> DagsterSummaryResponse:
    return DagsterSummaryResponse(data=data, meta=make_meta(started_at=started_at))


def _nux_seen_response(data: DagsterNuxSeenData, *, started_at: float) -> DagsterNuxSeenResponse:
    return DagsterNuxSeenResponse(data=data, meta=make_meta(started_at=started_at))


def _run_detail_response(
    data: DagsterRunDetailData, *, started_at: float
) -> DagsterRunDetailResponse:
    return DagsterRunDetailResponse(data=data, meta=make_meta(started_at=started_at))


def get_summary_configuration_error(settings: ApiSettings) -> DagsterSummaryResponse | None:
    """잘못된 Dagster URL 설정을 외부 자원 접근 전에 안전한 응답으로 바꾼다."""

    started_at = perf_counter()
    try:
        dagster_graphql.dagster_urls(settings)
    except dagster_graphql.DagsterUrlConfigurationError as exc:
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
            variables={"limit": page_size},
            query=_DAGSTER_SUMMARY_QUERY,
        )
    except (httpx.HTTPError, ValueError) as exc:
        return _summary_response(
            DagsterSummaryData(
                status="unavailable",
                dagster_url=urls.dagster_url,
                graphql_url=urls.graphql_url,
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
                dagster_url=urls.dagster_url,
                graphql_url=urls.graphql_url,
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
        dagster_graphql.as_dict(data.get("repositoriesOrError")), overrides=overrides
    )
    recent_runs, run_counts, run_errors = dagster_graphql.parse_runs(
        dagster_graphql.as_dict(data.get("runsOrError"))
    )
    errors = [*repository_errors, *run_errors]
    return _summary_response(
        DagsterSummaryData(
            status="error" if errors else "ok",
            dagster_url=urls.dagster_url,
            graphql_url=urls.graphql_url,
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

    started_at = perf_counter()
    checked_at = datetime.now(UTC)
    raw_graphql_url = dagster_graphql.candidate_graphql_url(settings)
    try:
        urls = dagster_graphql.dagster_urls(settings)
    except dagster_graphql.DagsterUrlConfigurationError as exc:
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
                graphql_url=urls.graphql_url,
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
                graphql_url=urls.graphql_url,
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
                graphql_url=urls.graphql_url,
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


async def mark_nux_seen(
    *, settings: ApiSettings, client: httpx.AsyncClient
) -> DagsterNuxSeenResponse:
    """Dagster NUX 상태를 명시적 mutation으로 변경한다."""

    started_at = perf_counter()
    checked_at = datetime.now(UTC)
    raw_graphql_url = dagster_graphql.candidate_graphql_url(settings)
    try:
        urls = dagster_graphql.dagster_urls(settings)
    except dagster_graphql.DagsterUrlConfigurationError as exc:
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
    try:
        payload = await dagster_graphql.post_graphql(
            client=client,
            graphql_url=urls.graphql_url,
            variables={},
            query=_DAGSTER_SET_NUX_SEEN_MUTATION,
        )
    except (httpx.HTTPError, ValueError) as exc:
        return _nux_seen_response(
            DagsterNuxSeenData(
                status="unavailable",
                dagster_url=urls.dagster_url,
                graphql_url=urls.graphql_url,
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
                dagster_url=urls.dagster_url,
                graphql_url=urls.graphql_url,
                checked_at=checked_at,
                seen=False,
                errors=[str(error) for error in graphql_errors],
            ),
            started_at=started_at,
        )
    seen = dagster_graphql.as_dict(payload.get("data")).get("setNuxSeen") is True
    return _nux_seen_response(
        DagsterNuxSeenData(
            status="ok" if seen else "error",
            dagster_url=urls.dagster_url,
            graphql_url=urls.graphql_url,
            checked_at=checked_at,
            seen=seen,
            errors=[] if seen else ["Dagster setNuxSeen mutation did not return true"],
        ),
        started_at=started_at,
    )
