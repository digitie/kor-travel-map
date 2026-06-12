"""``/ops/*`` 운영 조회 라우터 (ADR-045 T-207d)."""

from __future__ import annotations

from datetime import UTC, datetime
from time import perf_counter
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from kortravelmap.infra.jobs_repo import cancel_import_job
from kortravelmap.infra.ops_repo import (
    OpsConsistencyReport,
    OpsImportJob,
    OpsImportJobEvent,
    OpsIntegrityIssue,
    get_latest_consistency_report,
    get_ops_import_job,
    get_ops_integrity_issue_counts,
    list_ops_consistency_reports,
    list_ops_import_job_events,
    list_ops_import_jobs,
    list_ops_integrity_issues,
)
from kortravelmap.infra.status_repo import (
    DedupQueueFpStats,
    StatusCounts,
    dedup_fp_stats,
    gather_status_counts,
)
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.admin.db import get_session
from kortravelmap.admin.response import Meta, make_meta

__all__ = [
    "router",
    "OpsMetricsResponse",
    "OpsImportJobRecord",
    "OpsImportJobsListResponse",
    "OpsImportJobEventsListResponse",
    "OpsConsistencyReportsListResponse",
    "OpsIntegrityIssuesListResponse",
]


router = APIRouter(prefix="/ops", tags=["ops"])

ImportJobState = Literal["queued", "running", "done", "failed", "cancelled"]
ImportJobEventLevel = Literal["debug", "info", "warning", "error", "critical"]
ConsistencySeverity = Literal["OK", "WARN", "ERROR"]
IssueStatus = Literal["open", "acknowledged", "resolved", "ignored"]
IssueSeverity = Literal["info", "warning", "error", "critical"]


class OpsImportJobLink(BaseModel):
    """import job 상세 화면/연계 API가 쓰는 관련 링크."""

    model_config = ConfigDict(extra="forbid")

    rel: str
    href: str
    label: str | None = None


class OpsImportJobRecord(BaseModel):
    """``ops.import_jobs`` HTTP 표현."""

    model_config = ConfigDict(extra="forbid")

    job_id: str
    kind: str
    load_batch_id: str | None = None
    parent_job_id: str | None = None
    payload: dict[str, Any]
    status: str
    progress: int
    current_stage: str | None = None
    source_checksum: str | None = None
    error_message: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    heartbeat_at: datetime | None = None
    status_url: str
    links: list[OpsImportJobLink] = Field(default_factory=list)


class OpsImportJobEventRecord(BaseModel):
    """``ops.import_job_events`` HTTP 표현."""

    model_config = ConfigDict(extra="forbid")

    event_id: str
    job_id: str
    provider: str | None = None
    dataset_key: str | None = None
    feature_id: str | None = None
    stage: str | None = None
    level: str
    code: str | None = None
    message: str
    payload: dict[str, Any]
    occurred_at: datetime


class OpsImportJobsData(BaseModel):
    """import job 목록 data."""

    model_config = ConfigDict(extra="forbid")

    items: list[OpsImportJobRecord]


class OpsImportJobsListResponse(BaseModel):
    """``GET /ops/import-jobs`` 응답."""

    model_config = ConfigDict(extra="forbid")

    data: OpsImportJobsData
    meta: Meta


class OpsImportJobResponse(BaseModel):
    """``GET /ops/import-jobs/{job_id}`` 응답 (DA-D-03 envelope)."""

    model_config = ConfigDict(extra="forbid")

    data: OpsImportJobRecord
    meta: Meta


class OpsImportJobEventsData(BaseModel):
    """import job event 목록 data."""

    model_config = ConfigDict(extra="forbid")

    items: list[OpsImportJobEventRecord]


class OpsImportJobEventsListResponse(BaseModel):
    """``GET /ops/import-jobs/{job_id}/events`` 응답."""

    model_config = ConfigDict(extra="forbid")

    data: OpsImportJobEventsData
    meta: Meta


class OpsImportJobCancelRequest(BaseModel):
    """``POST /ops/import-jobs/{job_id}/cancel`` 요청."""

    model_config = ConfigDict(extra="forbid")

    operator: str | None = None
    reason: str | None = None


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


def _job(row: OpsImportJob) -> OpsImportJobRecord:
    return OpsImportJobRecord(
        job_id=row.job_id,
        kind=row.kind,
        load_batch_id=row.load_batch_id,
        parent_job_id=row.parent_job_id,
        payload=row.payload,
        status=row.status,
        progress=row.progress,
        current_stage=row.current_stage,
        source_checksum=row.source_checksum,
        error_message=row.error_message,
        created_at=row.created_at,
        started_at=row.started_at,
        finished_at=row.finished_at,
        heartbeat_at=row.heartbeat_at,
        status_url=f"/v1/ops/import-jobs/{row.job_id}",
        links=_job_links(row),
    )


def _payload_text(row: OpsImportJob, key: str) -> str | None:
    value = row.payload.get(key)
    if isinstance(value, str) and value:
        return value
    return None


def _job_links(row: OpsImportJob) -> list[OpsImportJobLink]:
    links = [
        OpsImportJobLink(
            rel="self",
            href=f"/v1/ops/import-jobs/{row.job_id}",
            label="import job",
        ),
        OpsImportJobLink(
            rel="events",
            href=f"/v1/ops/import-jobs/{row.job_id}/events",
            label="event timeline",
        ),
    ]
    if row.status in {"queued", "running"}:
        links.append(
            OpsImportJobLink(
                rel="cancel",
                href=f"/v1/ops/import-jobs/{row.job_id}/cancel",
                label="cancel import job",
            )
        )
    if row.parent_job_id:
        links.append(
            OpsImportJobLink(
                rel="parent_job",
                href=f"/v1/ops/import-jobs/{row.parent_job_id}",
                label="parent import job",
            )
        )
    if row.load_batch_id:
        links.append(
            OpsImportJobLink(
                rel="load_batch",
                href=f"/v1/ops/import-jobs?load_batch_id={row.load_batch_id}",
                label="load batch jobs",
            )
        )
    request_id = _payload_text(row, "request_id")
    if request_id:
        links.append(
            OpsImportJobLink(
                rel="feature_update_request",
                href=f"/v1/admin/feature-update-requests/{request_id}",
                label="feature update request",
            )
        )
    upload_id = _payload_text(row, "upload_id")
    if upload_id:
        links.append(
            OpsImportJobLink(
                rel="offline_upload",
                href=f"/v1/admin/offline-uploads/{upload_id}",
                label="offline upload",
            )
        )
    dagster_run_id = _payload_text(row, "dagster_run_id") or _payload_text(row, "run_id")
    if dagster_run_id:
        links.append(
            OpsImportJobLink(
                rel="dagster_run",
                href=f"/v1/ops/dagster/runs/{dagster_run_id}",
                label="Dagster run",
            )
        )
    return links


def _event(row: OpsImportJobEvent) -> OpsImportJobEventRecord:
    return OpsImportJobEventRecord(
        event_id=row.event_id,
        job_id=row.job_id,
        provider=row.provider,
        dataset_key=row.dataset_key,
        feature_id=row.feature_id,
        stage=row.stage,
        level=row.level,
        code=row.code,
        message=row.message,
        payload=row.payload,
        occurred_at=row.occurred_at,
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


async def _check_prewarm(session: AsyncSession) -> OpsHealthCheck:
    """pg_prewarm 확장/autoprewarm 상태(정보용, T-102). opt-in이라 degrade 안 함."""
    try:
        present = (
            await session.execute(
                text("SELECT 1 FROM pg_extension WHERE extname = 'pg_prewarm'")
            )
        ).scalar_one_or_none() is not None
        spl = (
            await session.execute(
                text("SELECT current_setting('shared_preload_libraries', true)")
            )
        ).scalar_one_or_none() or ""
    except SQLAlchemyError as exc:
        return OpsHealthCheck(
            component="prewarm", status="ok", detail=f"미점검: {str(exc)[:120]}"
        )
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


@router.get("/import-jobs", response_model=OpsImportJobsListResponse)
async def list_import_jobs(
    session: Annotated[AsyncSession, Depends(get_session)],
    status_filter: Annotated[ImportJobState | None, Query(alias="status")] = None,
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
            status=status_filter,
            kind=kind,
            load_batch_id=str(load_batch_id) if load_batch_id is not None else None,
            parent_job_id=str(parent_job_id) if parent_job_id is not None else None,
            limit=page_size,
            cursor=cursor,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return OpsImportJobsListResponse(
        data=OpsImportJobsData(items=[_job(item) for item in page.items]),
        meta=make_meta(
            started_at=started_at,
            page_size=page_size,
            next_cursor=page.next_cursor,
        ),
    )


@router.get(
    "/import-job-events",
    response_model=OpsImportJobEventsListResponse,
)
async def list_import_job_events_all(
    session: Annotated[AsyncSession, Depends(get_session)],
    job_id: Annotated[UUID | None, Query()] = None,
    level: Annotated[ImportJobEventLevel | None, Query()] = None,
    provider: Annotated[str | None, Query()] = None,
    dataset_key: Annotated[str | None, Query()] = None,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: Annotated[str | None, Query()] = None,
) -> OpsImportJobEventsListResponse:
    """전역 ``ops.import_job_events`` event stream."""
    started_at = perf_counter()
    try:
        page = await list_ops_import_job_events(
            session,
            str(job_id) if job_id is not None else None,
            level=level,
            provider=provider,
            dataset_key=dataset_key,
            limit=page_size,
            cursor=cursor,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return OpsImportJobEventsListResponse(
        data=OpsImportJobEventsData(items=[_event(item) for item in page.items]),
        meta=make_meta(
            started_at=started_at,
            page_size=page_size,
            next_cursor=page.next_cursor,
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
        meta=make_meta(started_at=started_at),
    )


@router.get(
    "/import-jobs/{job_id}/events",
    response_model=OpsImportJobEventsListResponse,
)
async def list_import_job_events(
    job_id: str,
    session: Annotated[AsyncSession, Depends(get_session)],
    level: Annotated[ImportJobEventLevel | None, Query()] = None,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: Annotated[str | None, Query()] = None,
) -> OpsImportJobEventsListResponse:
    """``ops.import_job_events`` 작업 event timeline."""
    started_at = perf_counter()
    if await get_ops_import_job(session, job_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"import job not found: {job_id}",
        )
    try:
        page = await list_ops_import_job_events(
            session,
            job_id,
            level=level,
            limit=page_size,
            cursor=cursor,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return OpsImportJobEventsListResponse(
        data=OpsImportJobEventsData(items=[_event(item) for item in page.items]),
        meta=make_meta(
            started_at=started_at,
            page_size=page_size,
            next_cursor=page.next_cursor,
        ),
    )


@router.post(
    "/import-jobs/{job_id}/cancel",
    response_model=OpsImportJobResponse,
    responses={
        404: {"description": "job_id 없음"},
        409: {"description": "이미 terminal 상태라 취소 불가"},
    },
)
async def cancel_import_job_route(
    job_id: str,
    session: Annotated[AsyncSession, Depends(get_session)],
    body: OpsImportJobCancelRequest | None = None,
) -> OpsImportJobResponse:
    """queued/running import job을 best-effort로 ``cancelled`` 전이한다."""
    started_at = perf_counter()
    reason = body.reason if body is not None and body.reason else None
    operator = body.operator if body is not None and body.operator else None
    error_message = reason or "cancelled by admin API"
    async with session.begin():
        existing = await get_ops_import_job(session, job_id)
        if existing is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"import job not found: {job_id}",
            )
        if existing.status not in {"queued", "running"}:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"cannot cancel import job in status: {existing.status}",
            )
        cancelled = await cancel_import_job(
            session,
            job_id,
            error_message=error_message,
            operator=operator,
            reason=reason,
        )
        if cancelled is None:
            refreshed = await get_ops_import_job(session, job_id)
            detail_status = refreshed.status if refreshed is not None else existing.status
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"cannot cancel import job in status: {detail_status}",
            )
    return OpsImportJobResponse(
        data=_job(await get_ops_import_job(session, job_id) or existing),
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
