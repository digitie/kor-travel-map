"""MOIS Phase A full-coverage Dagster run 선행조건(운영 화면 안내).

Dagster run ``SUCCESS``만으로는 custom ``service_slugs``/``org_code`` 부분 동기화를
전국 full sync로 인정하지 않는다. 종전에는 feature-update 큐의 쓰기 경계도 이 판정으로
막았으나, ADR-108부터 큐는 MOIS를 실행하지 않으므로 그 경계(``ensure_*``)는 걷어냈다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final

import httpx
from fastapi import HTTPException
from kortravelmap.providers.mois import (
    MOIS_SOURCE_SYNC_COVERAGE_TAG,
    MOIS_SOURCE_SYNC_FULL_COVERAGE,
)

from kortravelmap.api import dagster_graphql
from kortravelmap.api.dagster_graphql import DagsterUrlConfigurationError
from kortravelmap.api.dagster_schema import DagsterRunSummary
from kortravelmap.api.settings import ApiSettings

__all__ = [
    "MOIS_SOURCE_SYNC_JOB_NAME",
    "MoisSourceSyncPrecheck",
    "MoisSourceSyncPrecheckError",
    "fetch_mois_source_sync_precheck",
    "to_http_exception",
]

MOIS_SOURCE_SYNC_JOB_NAME: Final = "mois_localdata_source_sync"

_QUERY: Final = """
query KorTravelMapMoisSourceSyncPrecheck(
  $repositorySelector: RepositorySelector!, $runsFilter: RunsFilter!
) {
  repositoryOrError(repositorySelector: $repositorySelector) {
    __typename
    ... on RepositoryNotFoundError { message }
    ... on PythonError { message }
  }
  runsOrError(filter: $runsFilter, limit: 1) {
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
    ... on InvalidPipelineRunsFilterError { message }
    ... on PythonError { message }
  }
}
"""


class MoisSourceSyncPrecheckError(RuntimeError):
    """Dagster precheck 자체를 완료할 수 없다."""

    def __init__(self, message: str, *, code: str, status_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


@dataclass(frozen=True, slots=True)
class MoisSourceSyncPrecheck:
    """MOIS full-coverage source sync 최신 run 판정."""

    job_name: str
    ready: bool
    checked_at: datetime
    max_age_hours: int
    age_hours: float | None
    latest_run: DagsterRunSummary | None
    disabled_reason: str | None


async def fetch_mois_source_sync_precheck(
    *,
    settings: ApiSettings,
    client: httpx.AsyncClient,
    checked_at: datetime | None = None,
) -> MoisSourceSyncPrecheck:
    """exact job의 최신 SUCCESS·full coverage tag·TTL을 모두 확인한다."""

    checked_at = checked_at or datetime.now(UTC)
    try:
        dagster_urls = dagster_graphql.dagster_urls(settings)
    except DagsterUrlConfigurationError as exc:
        raise MoisSourceSyncPrecheckError(
            str(exc),
            code="DAGSTER_UNAVAILABLE",
            status_code=503,
        ) from exc
    try:
        payload = await dagster_graphql.post_graphql(
            client=client,
            graphql_url=dagster_urls.graphql_url,
            variables={
                "repositorySelector": dagster_urls.repository_selector(),
                "runsFilter": dagster_urls.runs_filter(pipelineName=MOIS_SOURCE_SYNC_JOB_NAME),
            },
            query=_QUERY,
        )
    except httpx.HTTPError as exc:
        raise MoisSourceSyncPrecheckError(
            str(exc),
            code="DAGSTER_UNAVAILABLE",
            status_code=503,
        ) from exc
    except ValueError as exc:
        raise MoisSourceSyncPrecheckError(
            str(exc),
            code="DAGSTER_QUERY_FAILED",
            status_code=502,
        ) from exc

    graphql_errors = payload.get("errors")
    if isinstance(graphql_errors, list) and graphql_errors:
        raise MoisSourceSyncPrecheckError(
            " / ".join(
                dagster_graphql.graphql_error_message(error)
                for error in graphql_errors
            ),
            code="DAGSTER_QUERY_FAILED",
            status_code=502,
        )
    data = dagster_graphql.as_dict(payload.get("data"))
    # location 이름이 틀리면 tag filter가 조용히 0건이다 — "sync 필요"로 오판하지 않는다.
    repository_error = dagster_graphql.repository_guard_error(data)
    if repository_error is not None:
        raise MoisSourceSyncPrecheckError(
            repository_error,
            code="DAGSTER_QUERY_FAILED",
            status_code=502,
        )
    runs, _counts, run_errors = dagster_graphql.parse_runs(
        dagster_graphql.as_dict(data.get("runsOrError"))
    )
    if run_errors:
        raise MoisSourceSyncPrecheckError(
            " / ".join(run_errors),
            code="DAGSTER_QUERY_FAILED",
            status_code=502,
        )
    latest_run = runs[0] if runs else None
    if latest_run is not None and latest_run.job_name != MOIS_SOURCE_SYNC_JOB_NAME:
        raise MoisSourceSyncPrecheckError(
            "Dagster RunsFilter가 다른 job run을 반환했습니다.",
            code="DAGSTER_QUERY_FAILED",
            status_code=502,
        )

    max_age_hours = settings.mois_source_sync_ttl_hours
    completed_at = latest_run.end_time if latest_run is not None else None
    elapsed_seconds = (
        checked_at.timestamp() - completed_at
        if completed_at is not None
        else None
    )
    age_hours = (
        elapsed_seconds / 3600
        if elapsed_seconds is not None and elapsed_seconds >= 0
        else None
    )
    has_full_coverage = bool(
        latest_run is not None
        and latest_run.tags.get(MOIS_SOURCE_SYNC_COVERAGE_TAG)
        == MOIS_SOURCE_SYNC_FULL_COVERAGE
    )
    ready = bool(
        latest_run is not None
        and latest_run.status == "SUCCESS"
        and has_full_coverage
        and age_hours is not None
        and max_age_hours > 0
        and age_hours <= max_age_hours
    )
    disabled_reason: str | None = None
    if not ready:
        if latest_run is None:
            disabled_reason = "MOIS source sync 실행 이력이 없습니다."
        elif latest_run.status != "SUCCESS":
            disabled_reason = (
                f"MOIS source sync 최신 run 상태가 {latest_run.status}입니다."
            )
        elif not has_full_coverage:
            disabled_reason = (
                "MOIS source sync 최신 성공은 PROMOTED 전체 업종·전국 "
                "full sync가 아닙니다."
            )
        elif completed_at is None:
            disabled_reason = "MOIS source sync 최신 성공 시각이 없습니다."
        elif elapsed_seconds is not None and elapsed_seconds < 0:
            disabled_reason = "MOIS source sync 최신 완료 시각이 미래입니다."
        elif max_age_hours <= 0:
            disabled_reason = "MOIS source sync freshness TTL이 0시간입니다."
        else:
            disabled_reason = (
                f"MOIS source sync 최신 성공이 TTL({max_age_hours}시간)을 넘었습니다."
            )
    return MoisSourceSyncPrecheck(
        job_name=MOIS_SOURCE_SYNC_JOB_NAME,
        ready=ready,
        checked_at=checked_at,
        max_age_hours=max_age_hours,
        age_hours=age_hours,
        latest_run=latest_run,
        disabled_reason=disabled_reason,
    )


def to_http_exception(exc: MoisSourceSyncPrecheckError) -> HTTPException:
    """MOIS source precheck exception을 일관된 RFC7807 중앙 handler 입력으로 바꾼다."""

    return HTTPException(
        status_code=exc.status_code,
        detail={
            "code": exc.code,
            "message": str(exc),
            "details": {"job_name": MOIS_SOURCE_SYNC_JOB_NAME},
        },
    )
