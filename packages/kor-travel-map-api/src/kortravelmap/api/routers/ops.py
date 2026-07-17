"""``/ops/*`` 운영 조회 라우터 (ADR-045 T-207d)."""

from __future__ import annotations

from datetime import UTC, datetime
from time import perf_counter
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from kortravelmap.infra.ops_repo import (
    OpsConsistencyReport,
    OpsIntegrityIssue,
    get_latest_consistency_report,
    get_ops_integrity_issue_counts,
    list_ops_consistency_reports,
    list_ops_integrity_issues,
)
from kortravelmap.infra.status_repo import (
    DedupQueueFpStats,
    StatusCounts,
    dedup_fp_stats,
    gather_status_counts,
)
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.api.db import get_session
from kortravelmap.api.response import Meta, make_meta

__all__ = [
    "router",
    "OpsMetricsResponse",
    "OpsConsistencyReportsListResponse",
    "OpsIntegrityIssuesListResponse",
]


router = APIRouter(prefix="/ops", tags=["ops"])

ConsistencySeverity = Literal["OK", "WARN", "ERROR"]
IssueStatus = Literal["open", "acknowledged", "resolved", "ignored"]
IssueSeverity = Literal["info", "warning", "error", "critical"]


class OpsConsistencyReportRecord(BaseModel):
    """consistency report HTTP 표현."""

    model_config = ConfigDict(extra="forbid")

    report_id: str
    batch_id: str
    started_at: datetime
    finished_at: datetime | None = None
    severity_max: str
    cases: list[dict[str, Any]]
    summary: dict[str, Any]


class OpsConsistencyReportsData(BaseModel):
    """consistency report 목록 data."""

    model_config = ConfigDict(extra="forbid")

    items: list[OpsConsistencyReportRecord]


class OpsConsistencyReportsListResponse(BaseModel):
    """``GET /ops/consistency/reports`` 응답."""

    model_config = ConfigDict(extra="forbid")

    data: OpsConsistencyReportsData
    meta: Meta


class OpsIntegrityIssueRecord(BaseModel):
    """data integrity issue HTTP 표현."""

    model_config = ConfigDict(extra="forbid")

    issue_id: str
    provider: str | None = None
    dataset_key: str | None = None
    source_record_key: str | None = None
    feature_id: str | None = None
    violation_type: str
    severity: str
    message: str
    payload: dict[str, Any]
    status: str
    detected_at: datetime
    resolved_at: datetime | None = None


class OpsIntegrityIssuesData(BaseModel):
    """data integrity issue 목록 data."""

    model_config = ConfigDict(extra="forbid")

    items: list[OpsIntegrityIssueRecord]


class OpsIntegrityIssuesListResponse(BaseModel):
    """``GET /ops/consistency/issues`` 응답."""

    model_config = ConfigDict(extra="forbid")

    data: OpsIntegrityIssuesData
    meta: Meta


class OpsDedupFpStatsRecord(BaseModel):
    """dedup 검토 큐 FP 통계."""

    model_config = ConfigDict(extra="forbid")

    resolved: int
    confirmed: int
    rejected: int
    ignored: int
    pending: int
    precision: float | None
    fp_rate: float | None


class OpsIntegrityIssueCountsRecord(BaseModel):
    """운영 issue 집계."""

    model_config = ConfigDict(extra="forbid")

    open_total: int
    by_status: dict[str, int]
    by_severity: dict[str, int]
    by_type: dict[str, int]


class OpsMetricsData(BaseModel):
    """``GET /ops/metrics`` data."""

    model_config = ConfigDict(extra="forbid")

    checked_at: datetime
    features_total: int
    features_active: int
    features_inactive: int
    features_by_kind: dict[str, int]
    source_records_by_provider: dict[str, int]
    import_jobs_by_status: dict[str, int]
    dedup_queue_by_status: dict[str, int]
    dedup_fp_stats: OpsDedupFpStatsRecord
    data_integrity_issues: OpsIntegrityIssueCountsRecord
    latest_consistency_report: OpsConsistencyReportRecord | None = None


class OpsMetricsResponse(BaseModel):
    """``GET /ops/metrics`` 응답 (DA-D-03 envelope)."""

    model_config = ConfigDict(extra="forbid")

    data: OpsMetricsData
    meta: Meta


def _report(row: OpsConsistencyReport | None) -> OpsConsistencyReportRecord | None:
    if row is None:
        return None
    return OpsConsistencyReportRecord(
        report_id=row.report_id,
        batch_id=row.batch_id,
        started_at=row.started_at,
        finished_at=row.finished_at,
        severity_max=row.severity_max,
        cases=row.cases,
        summary=row.summary,
    )


def _issue(row: OpsIntegrityIssue) -> OpsIntegrityIssueRecord:
    return OpsIntegrityIssueRecord(
        issue_id=row.issue_id,
        provider=row.provider,
        dataset_key=row.dataset_key,
        source_record_key=row.source_record_key,
        feature_id=row.feature_id,
        violation_type=row.violation_type,
        severity=row.severity,
        message=row.message,
        payload=row.payload,
        status=row.status,
        detected_at=row.detected_at,
        resolved_at=row.resolved_at,
    )


def _dedup_stats(row: DedupQueueFpStats) -> OpsDedupFpStatsRecord:
    return OpsDedupFpStatsRecord(
        resolved=row.resolved,
        confirmed=row.confirmed,
        rejected=row.rejected,
        ignored=row.ignored,
        pending=row.pending,
        precision=row.precision,
        fp_rate=row.fp_rate,
    )


def _metrics_response(
    counts: StatusCounts,
    *,
    issue_counts: OpsIntegrityIssueCountsRecord,
    latest_report: OpsConsistencyReportRecord | None,
    started_at: float,
) -> OpsMetricsResponse:
    return OpsMetricsResponse(
        data=OpsMetricsData(
            checked_at=datetime.now(UTC),
            features_total=counts.features_total,
            features_active=counts.features_active,
            features_inactive=counts.features_inactive,
            features_by_kind=counts.features_by_kind,
            source_records_by_provider=counts.source_records_by_provider,
            import_jobs_by_status=counts.import_jobs_by_status,
            dedup_queue_by_status=counts.dedup_queue_by_status,
            dedup_fp_stats=_dedup_stats(dedup_fp_stats(counts.dedup_queue_by_status)),
            data_integrity_issues=issue_counts,
            latest_consistency_report=latest_report,
        ),
        meta=make_meta(started_at=started_at),
    )


@router.get("/metrics", response_model=OpsMetricsResponse)
async def get_ops_metrics(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> OpsMetricsResponse:
    """운영 홈/대시보드가 쓰는 DB 기반 summary metric."""
    started_at = perf_counter()
    counts = await gather_status_counts(session)
    issue_counts = await get_ops_integrity_issue_counts(session)
    return _metrics_response(
        counts,
        issue_counts=OpsIntegrityIssueCountsRecord(
            open_total=issue_counts.open_total,
            by_status=issue_counts.by_status,
            by_severity=issue_counts.by_severity,
            by_type=issue_counts.by_type,
        ),
        latest_report=_report(await get_latest_consistency_report(session)),
        started_at=started_at,
    )


class OpsHealthCheck(BaseModel):
    """deep readiness 개별 컴포넌트 점검 결과."""

    model_config = ConfigDict(extra="forbid")

    component: str
    status: Literal["ok", "error"]
    detail: str | None = None


class OpsHealthDeepData(BaseModel):
    """``GET /ops/health-deep`` data — 전체 readiness + 컴포넌트별 점검."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["ok", "degraded"]
    checks: list[OpsHealthCheck]


class OpsHealthDeepResponse(BaseModel):
    """``GET /ops/health-deep`` 응답 (DA-D-03 envelope)."""

    model_config = ConfigDict(extra="forbid")

    data: OpsHealthDeepData
    meta: Meta


async def _check_database(session: AsyncSession) -> OpsHealthCheck:
    try:
        await session.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        return OpsHealthCheck(component="database", status="error", detail=str(exc)[:200])
    return OpsHealthCheck(component="database", status="ok")


async def _check_postgis(session: AsyncSession) -> OpsHealthCheck:
    try:
        version = (
            await session.execute(
                text("SELECT extversion FROM pg_extension WHERE extname = 'postgis'")
            )
        ).scalar_one_or_none()
    except SQLAlchemyError as exc:
        return OpsHealthCheck(component="postgis", status="error", detail=str(exc)[:200])
    if version is None:
        return OpsHealthCheck(
            component="postgis", status="error", detail="postgis extension 미설치"
        )
    return OpsHealthCheck(component="postgis", status="ok", detail=str(version))


async def _check_prewarm(session: AsyncSession) -> OpsHealthCheck:
    """pg_prewarm 확장/autoprewarm 상태(정보용, T-102). opt-in이라 degrade 안 함."""
    try:
        present = (
            await session.execute(text("SELECT 1 FROM pg_extension WHERE extname = 'pg_prewarm'"))
        ).scalar_one_or_none() is not None
        spl = (
            await session.execute(text("SELECT current_setting('shared_preload_libraries', true)"))
        ).scalar_one_or_none() or ""
    except SQLAlchemyError as exc:
        return OpsHealthCheck(component="prewarm", status="ok", detail=f"미점검: {str(exc)[:120]}")
    autoprewarm = "pg_prewarm" in spl
    return OpsHealthCheck(
        component="prewarm",
        status="ok",
        detail=(
            f"extension={'present' if present else 'absent'}, "
            f"autoprewarm={'on' if autoprewarm else 'off'}"
        ),
    )


@router.get(
    "/health-deep",
    response_model=OpsHealthDeepResponse,
    summary="deep readiness (DB/PostGIS)",
    description=(
        "DB 연결 + PostGIS 확장 readiness를 점검한다. liveness용 public ``/health``"
        "(DB-free 정적 200)와 달리 실제 DB를 친다. 한 컴포넌트라도 error면 전체"
        " ``status=degraded`` + HTTP 503(모니터링이 body로 컴포넌트별 상태를 읽음)."
    ),
)
async def get_ops_health_deep(
    session: Annotated[AsyncSession, Depends(get_session)],
    response: Response,
) -> OpsHealthDeepResponse:
    started_at = perf_counter()
    checks = [
        await _check_database(session),
        await _check_postgis(session),
        await _check_prewarm(session),
    ]
    overall = "ok" if all(check.status == "ok" for check in checks) else "degraded"
    if overall != "ok":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return OpsHealthDeepResponse(
        data=OpsHealthDeepData(status=overall, checks=checks),
        meta=make_meta(started_at=started_at),
    )


@router.get(
    "/consistency/reports",
    response_model=OpsConsistencyReportsListResponse,
)
async def list_consistency_reports(
    session: Annotated[AsyncSession, Depends(get_session)],
    severity_max: Annotated[ConsistencySeverity | None, Query()] = None,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: Annotated[str | None, Query()] = None,
) -> OpsConsistencyReportsListResponse:
    """최근 consistency report 목록."""
    started_at = perf_counter()
    try:
        page = await list_ops_consistency_reports(
            session,
            severity_max=severity_max,
            limit=page_size,
            cursor=cursor,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return OpsConsistencyReportsListResponse(
        data=OpsConsistencyReportsData(
            items=[item for item in (_report(row) for row in page.items) if item],
        ),
        meta=make_meta(
            started_at=started_at,
            page_size=page_size,
            next_cursor=page.next_cursor,
        ),
    )


@router.get(
    "/consistency/issues",
    response_model=OpsIntegrityIssuesListResponse,
)
async def list_integrity_issues(
    session: Annotated[AsyncSession, Depends(get_session)],
    issue_status: Annotated[IssueStatus | None, Query(alias="status")] = "open",
    severity: Annotated[IssueSeverity | None, Query()] = None,
    violation_type: Annotated[str | None, Query()] = None,
    provider: Annotated[str | None, Query()] = None,
    dataset_key: Annotated[str | None, Query()] = None,
    feature_id: Annotated[str | None, Query()] = None,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: Annotated[str | None, Query()] = None,
) -> OpsIntegrityIssuesListResponse:
    """열린 data integrity issue 목록."""
    started_at = perf_counter()
    try:
        page = await list_ops_integrity_issues(
            session,
            status=issue_status,
            severity=severity,
            violation_type=violation_type,
            provider=provider,
            dataset_key=dataset_key,
            feature_id=feature_id,
            limit=page_size,
            cursor=cursor,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return OpsIntegrityIssuesListResponse(
        data=OpsIntegrityIssuesData(items=[_issue(item) for item in page.items]),
        meta=make_meta(
            started_at=started_at,
            page_size=page_size,
            next_cursor=page.next_cursor,
        ),
    )
