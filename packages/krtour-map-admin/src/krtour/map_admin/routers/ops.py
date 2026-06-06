"""``/ops/*`` 운영 조회 라우터 (ADR-045 T-207d)."""

from __future__ import annotations

from datetime import UTC, datetime
from time import perf_counter
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from krtour.map.infra.ops_repo import (
    OpsConsistencyReport,
    OpsImportJob,
    OpsIntegrityIssue,
    get_latest_consistency_report,
    get_ops_import_job,
    get_ops_integrity_issue_counts,
    list_ops_consistency_reports,
    list_ops_import_jobs,
    list_ops_integrity_issues,
)
from krtour.map.infra.status_repo import (
    DedupQueueFpStats,
    StatusCounts,
    dedup_fp_stats,
    gather_status_counts,
)
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from krtour.map_admin.db import get_session

__all__ = [
    "router",
    "OpsMetricsResponse",
    "OpsImportJobRecord",
    "OpsImportJobsListResponse",
    "OpsConsistencyReportsListResponse",
    "OpsIntegrityIssuesListResponse",
]


router = APIRouter(prefix="/ops", tags=["ops"])

ImportJobState = Literal["queued", "running", "done", "failed", "cancelled"]
ConsistencySeverity = Literal["OK", "WARN", "ERROR"]
IssueStatus = Literal["open", "acknowledged", "resolved", "ignored"]
IssueSeverity = Literal["info", "warning", "error", "critical"]


class OpsImportJobRecord(BaseModel):
    """``ops.import_jobs`` HTTP 표현."""

    model_config = ConfigDict(extra="forbid")

    job_id: str
    kind: str
    load_batch_id: str | None = None
    parent_job_id: str | None = None
    payload: dict[str, Any]
    state: str
    progress: int
    current_stage: str | None = None
    source_checksum: str | None = None
    error_message: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    heartbeat_at: datetime | None = None
    status_url: str


class OpsImportJobsData(BaseModel):
    """import job 목록 data."""

    model_config = ConfigDict(extra="forbid")

    items: list[OpsImportJobRecord]
    next_cursor: str | None = None


class OpsListMeta(BaseModel):
    """목록 공통 meta."""

    model_config = ConfigDict(extra="forbid")

    count: int
    page_size: int
    duration_ms: int


class OpsDetailMeta(BaseModel):
    """단건 응답 공통 meta."""

    model_config = ConfigDict(extra="forbid")

    duration_ms: int


class OpsImportJobsListResponse(BaseModel):
    """``GET /ops/import-jobs`` 응답."""

    model_config = ConfigDict(extra="forbid")

    data: OpsImportJobsData
    meta: OpsListMeta


class OpsImportJobResponse(BaseModel):
    """``GET /ops/import-jobs/{job_id}`` 응답 (DA-D-03 envelope)."""

    model_config = ConfigDict(extra="forbid")

    data: OpsImportJobRecord
    meta: OpsDetailMeta


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
    next_cursor: str | None = None


class OpsConsistencyReportsListResponse(BaseModel):
    """``GET /ops/consistency/reports`` 응답."""

    model_config = ConfigDict(extra="forbid")

    data: OpsConsistencyReportsData
    meta: OpsListMeta


class OpsIntegrityIssueRecord(BaseModel):
    """data integrity issue HTTP 표현."""

    model_config = ConfigDict(extra="forbid")

    violation_key: str
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
    next_cursor: str | None = None


class OpsIntegrityIssuesListResponse(BaseModel):
    """``GET /ops/consistency/issues`` 응답."""

    model_config = ConfigDict(extra="forbid")

    data: OpsIntegrityIssuesData
    meta: OpsListMeta


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
    import_jobs_by_state: dict[str, int]
    dedup_queue_by_status: dict[str, int]
    dedup_fp_stats: OpsDedupFpStatsRecord
    data_integrity_issues: OpsIntegrityIssueCountsRecord
    latest_consistency_report: OpsConsistencyReportRecord | None = None


class OpsMetricsResponse(BaseModel):
    """``GET /ops/metrics`` 응답 (DA-D-03 envelope)."""

    model_config = ConfigDict(extra="forbid")

    data: OpsMetricsData
    meta: OpsDetailMeta


def _job(row: OpsImportJob) -> OpsImportJobRecord:
    return OpsImportJobRecord(
        job_id=row.job_id,
        kind=row.kind,
        load_batch_id=row.load_batch_id,
        parent_job_id=row.parent_job_id,
        payload=row.payload,
        state=row.state,
        progress=row.progress,
        current_stage=row.current_stage,
        source_checksum=row.source_checksum,
        error_message=row.error_message,
        created_at=row.created_at,
        started_at=row.started_at,
        finished_at=row.finished_at,
        heartbeat_at=row.heartbeat_at,
        status_url=f"/ops/import-jobs/{row.job_id}",
    )


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
        violation_key=row.violation_key,
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
            import_jobs_by_state=counts.import_jobs_by_state,
            dedup_queue_by_status=counts.dedup_queue_by_status,
            dedup_fp_stats=_dedup_stats(dedup_fp_stats(counts.dedup_queue_by_status)),
            data_integrity_issues=issue_counts,
            latest_consistency_report=latest_report,
        ),
        meta=OpsDetailMeta(
            duration_ms=max(0, int((perf_counter() - started_at) * 1000)),
        ),
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
    meta: OpsDetailMeta


async def _check_database(session: AsyncSession) -> OpsHealthCheck:
    try:
        await session.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        return OpsHealthCheck(
            component="database", status="error", detail=str(exc)[:200]
        )
    return OpsHealthCheck(component="database", status="ok")


async def _check_postgis(session: AsyncSession) -> OpsHealthCheck:
    try:
        version = (
            await session.execute(
                text("SELECT extversion FROM pg_extension WHERE extname = 'postgis'")
            )
        ).scalar_one_or_none()
    except SQLAlchemyError as exc:
        return OpsHealthCheck(
            component="postgis", status="error", detail=str(exc)[:200]
        )
    if version is None:
        return OpsHealthCheck(
            component="postgis", status="error", detail="postgis extension 미설치"
        )
    return OpsHealthCheck(component="postgis", status="ok", detail=str(version))


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
    ]
    overall = "ok" if all(check.status == "ok" for check in checks) else "degraded"
    if overall != "ok":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return OpsHealthDeepResponse(
        data=OpsHealthDeepData(status=overall, checks=checks),
        meta=OpsDetailMeta(
            duration_ms=max(0, int((perf_counter() - started_at) * 1000)),
        ),
    )


@router.get("/import-jobs", response_model=OpsImportJobsListResponse)
async def list_import_jobs(
    session: Annotated[AsyncSession, Depends(get_session)],
    state: Annotated[ImportJobState | None, Query()] = None,
    kind: Annotated[str | None, Query()] = None,
    load_batch_id: Annotated[UUID | None, Query()] = None,
    parent_job_id: Annotated[UUID | None, Query()] = None,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: Annotated[str | None, Query()] = None,
) -> OpsImportJobsListResponse:
    """``ops.import_jobs`` 작업 목록."""
    started_at = perf_counter()
    try:
        page = await list_ops_import_jobs(
            session,
            state=state,
            kind=kind,
            load_batch_id=str(load_batch_id) if load_batch_id is not None else None,
            parent_job_id=str(parent_job_id) if parent_job_id is not None else None,
            limit=page_size,
            cursor=cursor,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return OpsImportJobsListResponse(
        data=OpsImportJobsData(
            items=[_job(item) for item in page.items],
            next_cursor=page.next_cursor,
        ),
        meta=OpsListMeta(
            count=len(page.items),
            page_size=page_size,
            duration_ms=max(0, int((perf_counter() - started_at) * 1000)),
        ),
    )


@router.get("/import-jobs/{job_id}", response_model=OpsImportJobResponse)
async def get_import_job(
    job_id: str,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> OpsImportJobResponse:
    """``ops.import_jobs`` 작업 단건."""
    started_at = perf_counter()
    row = await get_ops_import_job(session, job_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"import job not found: {job_id}",
        )
    return OpsImportJobResponse(
        data=_job(row),
        meta=OpsDetailMeta(
            duration_ms=max(0, int((perf_counter() - started_at) * 1000)),
        ),
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
            next_cursor=page.next_cursor,
        ),
        meta=OpsListMeta(
            count=len(page.items),
            page_size=page_size,
            duration_ms=max(0, int((perf_counter() - started_at) * 1000)),
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
        data=OpsIntegrityIssuesData(
            items=[_issue(item) for item in page.items],
            next_cursor=page.next_cursor,
        ),
        meta=OpsListMeta(
            count=len(page.items),
            page_size=page_size,
            duration_ms=max(0, int((perf_counter() - started_at) * 1000)),
        ),
    )
