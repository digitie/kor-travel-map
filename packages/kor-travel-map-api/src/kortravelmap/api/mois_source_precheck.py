"""MOIS Phase A full-coverage Dagster run 선행조건.

UI 안내와 canonical feature-update write 경계가 같은 exact job/tag/TTL
판정을 사용한다. Dagster run ``SUCCESS``만으로는 custom
``service_slugs``/``org_code`` 부분 동기화를 전국 full sync로 인정하지
않는다.
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
from kortravelmap.providers.mois import (
    PROVIDER_NAME as MOIS_PROVIDER_NAME,
)

from kortravelmap.api import dagster_graphql
from kortravelmap.api.dagster_graphql import DagsterUrlConfigurationError
from kortravelmap.api.dagster_schema import DagsterRunSummary
from kortravelmap.api.response import ProblemDetail
from kortravelmap.api.settings import ApiSettings

__all__ = [
    "MOIS_SOURCE_SYNC_JOB_NAME",
    "MoisSourceSyncPrecheck",
    "MoisSourceSyncPrecheckError",
    "MoisSourceSyncRequired",
    "MOIS_SOURCE_PRECHECK_ERROR_RESPONSES",
    "ensure_mois_source_sync_for_plan",
    "fetch_mois_source_sync_precheck",
    "to_http_exception",
]

MOIS_SOURCE_SYNC_JOB_NAME: Final = "mois_localdata_source_sync"
MOIS_SOURCE_PRECHECK_ERROR_RESPONSES: Final[dict[int | str, dict[str, object]]] = {
    409: {
        "model": ProblemDetail,
        "description": "요청 계획 충돌/잠금 또는 MOIS full source sync 선행조건 미충족",
    },
    502: {"model": ProblemDetail, "description": "Dagster precheck 응답 오류"},
    503: {"model": ProblemDetail, "description": "Dagster precheck transport/설정 오류"},
}

_QUERY: Final = """
query KorTravelMapMoisSourceSyncPrecheck($filter: RunsFilter!) {
  runsOrError(filter: $filter, limit: 1) {
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


class MoisSourceSyncRequired(RuntimeError):
    """MOIS canonical write plan이 full source sync 선행조건을 만족하지 못했다."""

    def __init__(self, precheck: MoisSourceSyncPrecheck) -> None:
        super().__init__(precheck.disabled_reason or "MOIS source sync가 필요합니다.")
        self.precheck = precheck


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
            variables={"filter": {"pipelineName": MOIS_SOURCE_SYNC_JOB_NAME}},
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


async def ensure_mois_source_sync_for_plan(
    resolved_pairs: frozenset[tuple[str, str]],
    *,
    settings: ApiSettings,
    client: httpx.AsyncClient,
) -> None:
    """resolved canonical plan에 MOIS가 포함되면 full sync를 fail-closed로 검사한다."""

    if not any(provider == MOIS_PROVIDER_NAME for provider, _dataset in resolved_pairs):
        return
    precheck = await fetch_mois_source_sync_precheck(
        settings=settings,
        client=client,
    )
    if not precheck.ready:
        raise MoisSourceSyncRequired(precheck)


def to_http_exception(
    exc: MoisSourceSyncPrecheckError | MoisSourceSyncRequired,
) -> HTTPException:
    """MOIS source precheck exception을 일관된 RFC7807 중앙 handler 입력으로 바꾼다."""

    if isinstance(exc, MoisSourceSyncRequired):
        precheck = exc.precheck
        latest_run = precheck.latest_run
        return HTTPException(
            status_code=409,
            detail={
                "code": "MOIS_SOURCE_SYNC_REQUIRED",
                "message": str(exc),
                "details": {
                    "job_name": precheck.job_name,
                    "checked_at": precheck.checked_at.isoformat(),
                    "max_age_hours": precheck.max_age_hours,
                    "age_hours": precheck.age_hours,
                    "latest_run_id": latest_run.run_id if latest_run else None,
                    "latest_run_status": latest_run.status if latest_run else None,
                    "coverage": (
                        latest_run.tags.get(MOIS_SOURCE_SYNC_COVERAGE_TAG)
                        if latest_run
                        else None
                    ),
                },
            },
        )
    return HTTPException(
        status_code=exc.status_code,
        detail={
            "code": exc.code,
            "message": str(exc),
            "details": {"job_name": MOIS_SOURCE_SYNC_JOB_NAME},
        },
    )
