"""``/ops/pipeline/*`` — 파이프라인 운영 그룹 (ADR-064 T-ADM-C3).

admin ops 통합 재작성 페이지 ①(`/ops/pipeline`)의 백엔드 리소스 그룹이다.
설계 정본은 ``docs/reports/admin-ops-consolidation-plan-2026-07-14.md`` §2.

- **실행 타임라인**: ``ops.import_jobs`` ∪ ``ops.feature_update_requests``의
  DB-only UNION(공유 keyset cursor ``(created_at DESC, id DESC)`` + ``kind``
  discriminator). Dagster run(GraphQL, 휘발·cursor 없음)은 목록 cursor에 섞지
  않고 실컬럼 ``dagster_run_id`` 속성 + 보조 패널(`/dagster-runs`)로만 노출한다.
- **공개 application 경계**: Dagster transport/parser는 ``dagster_graphql``,
  조회와 schedule 조작은 각각 ``dagster_query_service``와
  ``dagster_schedule_service``를 사용한다. 갱신 요청은
  ``feature_update_schema``·``feature_update_service``의 6-type scope union,
  카탈로그 검증, geo resolver, advisory lock 계약을 공유한다.
- 게이트: ``app.py``에서 ``ops_routes_enabled`` + ``require_admin_frontend``
  의존성으로 마운트한다(조작 포함 — 무인증 ops 패턴 금지, ADR-064 §2).
"""

from __future__ import annotations

from datetime import UTC, datetime
from time import perf_counter
from typing import Annotated, Any, Literal
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response, status
from kortravelmap.infra.feature_update_repo import (
    FeatureUpdateRequest,
    get_update_request,
)
from kortravelmap.infra.ops_repo import (
    OpsImportJob,
    OpsImportJobEvent,
    get_ops_import_job,
    list_ops_import_job_events,
)
from kortravelmap.infra.pipeline_cancellation_repo import (
    get_current_pipeline_cancellation_detail,
)
from kortravelmap.infra.pipeline_repo import (
    PipelineExecution,
    PipelineProjectedJob,
    PipelineProviderDatasetIdentity,
    get_pipeline_execution,
    get_pipeline_status_counts,
    list_pipeline_executions,
)
from kortravelmap.settings import KorTravelMapSettings
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from kortravelmap.api import (
    dagster_graphql,
    dagster_query_service,
    dagster_schedule_service,
    feature_update_service,
    mois_source_precheck,
    pipeline_cancellation_service,
)
from kortravelmap.api.auth import AdminProxyContext, require_admin_frontend
from kortravelmap.api.dagster_graphql import DagsterUrlConfigurationError, DagsterUrls
from kortravelmap.api.dagster_http import (
    SCHEDULE_WRITE_ERROR_RESPONSES,
    dagster_http_dependencies,
    schedule_idempotency_http_exception,
    schedule_storage_http_exception,
    schedule_uncertain_outcome_http_exception,
    schedule_validation_http_exception,
)
from kortravelmap.api.dagster_http import (
    http_client_from_request as _http_client_from_request,
)
from kortravelmap.api.dagster_http import (
    settings_from_request as _settings_from_request,
)
from kortravelmap.api.dagster_schema import (
    DagsterRunDetailResponse,
    DagsterRunSummary,
    DagsterSchedule,
    DagsterScheduleClaimResolution,
    DagsterScheduleCommandData,
    DagsterScheduleCommandRequest,
    DagsterScheduleCommandResponse,
    DagsterScheduleOverrideRequest,
    DagsterSensor,
)
from kortravelmap.api.db import get_engine, get_session
from kortravelmap.api.feature_update_http import (
    FEATURE_UPDATE_CONFLICT_RESPONSES,
    to_http_exception,
)
from kortravelmap.api.feature_update_schema import (
    FeatureUpdateRequestCreateRequest,
    FeatureUpdateRequestCreateResponse,
    FeatureUpdateRequestMutationResponse,
    FeatureUpdateRequestPreviewRequest,
    FeatureUpdateRequestPreviewResponse,
    FeatureUpdateRequestRecord,
    FeatureUpdateRequestRunNowRequest,
)
from kortravelmap.api.ops_operation_schema import OperationState
from kortravelmap.api.pipeline_cancellation_http import (
    error_responses as cancellation_error_responses,
)
from kortravelmap.api.pipeline_cancellation_http import (
    to_http_exception as cancellation_to_http_exception,
)
from kortravelmap.api.pipeline_cancellation_schema import (
    PipelineCancellationDetailRecord,
    PipelineCancellationRequest,
    PipelineCancellationResponse,
    PipelineCancellationSummaryRecord,
    cancellation_detail_record,
    cancellation_summary_record,
)
from kortravelmap.api.provider_catalog import resolve_dataset_history_sync_scopes
from kortravelmap.api.response import Meta, ProblemDetail, make_meta

__all__ = [
    "router",
    "ExecutionKind",
    "PipelineExecutionRecord",
    "PipelineExecutionRootRecord",
    "PipelineExecutionsListResponse",
    "PipelineExecutionDetailResponse",
    "PipelineOverviewResponse",
    "PipelineSchedulesResponse",
    "PipelineScheduleCommandResponse",
    "PipelineScheduleClaimResolutionResponse",
]


router = APIRouter(prefix="/ops/pipeline", tags=["ops-pipeline"])

ExecutionKind = Literal["import_job", "update_request"]
ExecutionState = OperationState
JobEventLevel = Literal["debug", "info", "warning", "error", "critical"]
PipelineScheduleCommand = Literal["run", "start", "stop", "reset"]
PipelineScheduleClaimResolution = Literal["confirmed_applied", "confirmed_not_applied"]

_EXECUTIONS_URL_PREFIX = "/v1/ops/pipeline/executions"
_UPDATE_REQUEST_STATUS_URL_PREFIX = f"{_EXECUTIONS_URL_PREFIX}/update_request"

CronString = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
DagsterRunId = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=255),
]


# =============================================================================
# 응답 DTO
# =============================================================================


class PipelineExecutionRecord(BaseModel):
    """단건 detail/cancel의 기존 실행 표현."""

    model_config = ConfigDict(extra="forbid")

    kind: ExecutionKind
    id: UUID
    status: OperationState
    created_at: datetime
    job_kind: str | None
    provider: str | None
    dataset_key: str | None
    progress: int | None
    current_stage: str | None
    scope_type: str | None
    priority: int | None
    run_mode: str | None
    operator: str | None
    error_message: str | None
    started_at: datetime | None
    finished_at: datetime | None
    dagster_run_id: str | None
    dagster_run_status: str | None
    trigger_kind: str | None
    operation_registry_version: str | None
    job_id: UUID | None = Field(
        description="update_request 행이 연결된 import job id.",
    )
    request_id: UUID | None = Field(
        description="import_job 행이 연결된 feature update request id.",
    )
    load_batch_id: UUID | None
    parent_job_id: UUID | None
    detail_url: str


class PipelineProjectedJobRecord(BaseModel):
    """root branch/partition에서 대표로 고른 import job."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    job_kind: str
    status: OperationState
    progress: int
    current_stage: str | None
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    dagster_run_id: str | None
    dagster_run_status: str | None
    trigger_kind: str | None
    operation_registry_version: str | None
    load_batch_id: UUID | None
    parent_job_id: UUID | None
    depth: int
    detail_url: str


class PipelineProviderDatasetIdentityRecord(BaseModel):
    """canonical root에 귀속된 exact pair 상태."""

    model_config = ConfigDict(extra="forbid")

    provider: str
    dataset_key: str
    sync_scope: str | None
    operation_member_id: UUID
    status: OperationState


class PipelineExecutionRootRecord(BaseModel):
    """실행 목록의 request branch 또는 standalone partition root."""

    model_config = ConfigDict(extra="forbid")

    kind: ExecutionKind
    id: UUID
    status: OperationState
    created_at: datetime
    providers: list[str] = Field(description="표시·provider-only 필터용 정렬된 유효 provider 목록.")
    dataset_keys: list[str] = Field(
        description="표시·dataset-only 필터용 정렬된 유효 dataset 목록."
    )
    provider_datasets: list[PipelineProviderDatasetIdentityRecord] = Field(
        description="canonical branch의 exact pair와 pair별 lifecycle 상태.",
    )
    progress: int | None
    current_stage: str | None
    scope_type: str | None
    priority: int | None
    run_mode: str | None
    operator: str | None
    error_message: str | None
    started_at: datetime | None
    finished_at: datetime | None
    dagster_run_id: str | None
    dagster_run_status: str | None
    trigger_kind: str | None
    operation_registry_version: str | None
    requested_job_id: UUID | None = Field(
        description="update request가 원래 가리킨 import job id.",
    )
    linked_job_count: int = Field(ge=1)
    projected_job: PipelineProjectedJobRecord
    cancellation: PipelineCancellationSummaryRecord | None
    detail_url: str


class PipelineExecutionsData(BaseModel):
    """실행 타임라인 목록 data."""

    model_config = ConfigDict(extra="forbid")

    items: list[PipelineExecutionRootRecord]


class PipelineExecutionsListResponse(BaseModel):
    """``GET /ops/pipeline/executions`` 응답 (DA-D-03 envelope)."""

    model_config = ConfigDict(extra="forbid")

    data: PipelineExecutionsData
    meta: Meta


class PipelineImportJobRecord(BaseModel):
    """``ops.import_jobs`` 상세 표현 (pipeline 그룹 계약)."""

    model_config = ConfigDict(extra="forbid")

    job_id: UUID
    kind: str
    load_batch_id: UUID | None
    parent_job_id: UUID | None
    payload: dict[str, Any]
    status: OperationState
    progress: int
    current_stage: str | None
    source_checksum: str | None
    error_message: str | None
    dagster_run_id: str | None
    provider: str | None
    dataset_key: str | None
    trigger_kind: str | None
    operation_registry_version: str | None
    dagster_run_status: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    heartbeat_at: datetime | None


class PipelineJobEventRecord(BaseModel):
    """``ops.import_job_events`` 표현 (pipeline 그룹 계약)."""

    model_config = ConfigDict(extra="forbid")

    event_id: UUID
    job_id: UUID
    provider: str | None
    dataset_key: str | None
    feature_id: str | None
    stage: str | None
    level: str
    code: str | None
    message: str
    payload: dict[str, Any]
    occurred_at: datetime


class PipelineExecutionDetailData(BaseModel):
    """실행 상세 — 실행 행 + 연결 개체 + 이벤트 페이지."""

    model_config = ConfigDict(extra="forbid")

    execution: PipelineExecutionRecord
    root: PipelineExecutionRootRecord = Field(
        description="요청 id 또는 import member id가 귀속되는 canonical root projection."
    )
    import_job: PipelineImportJobRecord | None = Field(
        description="kind=import_job의 본체 또는 update_request가 연결한 job.",
    )
    update_request: FeatureUpdateRequestRecord | None = Field(
        description="kind=update_request의 본체 또는 import_job이 연결한 request.",
    )
    cancellation: PipelineCancellationDetailRecord | None = Field(
        description="base lifecycle을 덮지 않는 current cancellation 상세.",
    )
    events: list[PipelineJobEventRecord]
    events_next_cursor: str | None = Field(
        description="이벤트 로그 전진 페이지네이션 cursor (없으면 마지막 페이지).",
    )


class PipelineExecutionDetailResponse(BaseModel):
    """``GET /ops/pipeline/executions/{kind}/{id}`` 응답."""

    model_config = ConfigDict(extra="forbid")

    data: PipelineExecutionDetailData
    meta: Meta


class PipelineEventsData(BaseModel):
    """전역 job 이벤트 목록 data."""

    model_config = ConfigDict(extra="forbid")

    items: list[PipelineJobEventRecord]


class PipelineEventsListResponse(BaseModel):
    """``GET /ops/pipeline/events`` 응답."""

    model_config = ConfigDict(extra="forbid")

    data: PipelineEventsData
    meta: Meta


class PipelineDagsterOverview(BaseModel):
    """overview의 Dagster 요약 부분 — GraphQL degrade 허용."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["ok", "unavailable", "error"]
    dagster_url: str
    graphql_url: str
    version: str | None = None
    run_counts: dict[str, int] = Field(default_factory=dict)
    recent_runs: list[DagsterRunSummary] = Field(default_factory=list)
    schedule_count: int = 0
    sensor_count: int = 0
    sensors: list[DagsterSensor] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class PipelineOverviewData(BaseModel):
    """``GET /ops/pipeline/overview`` data — 상태 스트립 집계."""

    model_config = ConfigDict(extra="forbid")

    checked_at: datetime
    dagster: PipelineDagsterOverview
    operations_by_status: dict[OperationState, int]
    active_operations: int
    failed_operations_24h: int


class PipelineOverviewResponse(BaseModel):
    """``GET /ops/pipeline/overview`` 응답 (DA-D-03 envelope)."""

    model_config = ConfigDict(extra="forbid")

    data: PipelineOverviewData
    meta: Meta


class PipelineDagsterRunsData(BaseModel):
    """``GET /ops/pipeline/dagster-runs`` data — 보조 패널용 최근 run."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["ok", "unavailable", "error"]
    dagster_url: str
    graphql_url: str
    checked_at: datetime
    run_counts: dict[str, int] = Field(default_factory=dict)
    runs: list[DagsterRunSummary] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class PipelineDagsterRunsResponse(BaseModel):
    """``GET /ops/pipeline/dagster-runs`` 응답."""

    model_config = ConfigDict(extra="forbid")

    data: PipelineDagsterRunsData
    meta: Meta


class PipelineJobPrecheckData(BaseModel):
    """Dagster 선행 job의 최신 완료 상태와 freshness 판정."""

    model_config = ConfigDict(extra="forbid")

    job_name: str
    ready: bool
    checked_at: datetime
    max_age_hours: int = Field(ge=0)
    age_hours: float | None = Field(default=None, ge=0)
    latest_run: DagsterRunSummary | None
    disabled_reason: str | None


class PipelineJobPrecheckResponse(BaseModel):
    """``GET /ops/pipeline/prechecks/mois-source-sync`` 응답."""

    model_config = ConfigDict(extra="forbid")

    data: PipelineJobPrecheckData
    meta: Meta


class PipelineSchedulesData(BaseModel):
    """``GET /ops/pipeline/schedules`` data — override 병합 + sensor 상태."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["ok", "unavailable", "error"]
    dagster_url: str
    graphql_url: str
    checked_at: datetime
    schedules: list[DagsterSchedule] = Field(default_factory=list)
    sensors: list[DagsterSensor] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class PipelineSchedulesResponse(BaseModel):
    """``GET /ops/pipeline/schedules`` 응답."""

    model_config = ConfigDict(extra="forbid")

    data: PipelineSchedulesData
    meta: Meta


class PipelineScheduleUpdateRequest(BaseModel):
    """``PATCH /ops/pipeline/schedules/{name}`` body.

    ``cron_schedule``는 필수 키다 — 문자열이면 override 저장,
    **명시적 ``null``이면 override 삭제**(구 ``default`` 명령 대체, ADR-064 §6-5).
    """

    model_config = ConfigDict(extra="forbid")

    cron_schedule: CronString | None
    reason: str | None = Field(default=None, max_length=500)


class PipelineScheduleCommandRequest(BaseModel):
    """``POST /ops/pipeline/schedules/{name}/commands`` body — 4종 enum."""

    model_config = ConfigDict(extra="forbid")

    command: PipelineScheduleCommand
    reason: str | None = Field(default=None, max_length=500)


class PipelineScheduleCommandData(BaseModel):
    """schedule write(PATCH/commands) 결과."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["ok", "unavailable", "error"]
    dagster_url: str
    graphql_url: str
    checked_at: datetime
    schedule_name: str
    command: Literal["update", "clear_override", "run", "start", "stop", "reset"]
    cron_schedule: str | None = None
    default_cron_schedule: str | None = None
    override_cron_schedule: str | None = None
    effective_cron_schedule: str | None
    schedule_status: str | None = None
    run_id: str | None = None
    run_status: str | None = None
    save_status: Literal["not_applicable", "saved", "cleared"]
    reload_status: Literal["not_requested", "succeeded", "failed"]
    effective_status: Literal["confirmed", "pending_verification", "mismatch", "unknown"]
    outcome_certainty: Literal["confirmed", "uncertain"] = "confirmed"
    audit_command_id: UUID | None = None
    audit_status: Literal["recorded", "terminal_record_failed"]
    errors: list[str] = Field(default_factory=list)


class PipelineScheduleCommandResponse(BaseModel):
    """schedule write 응답."""

    model_config = ConfigDict(extra="forbid")

    data: PipelineScheduleCommandData
    meta: Meta


class PipelineScheduleClaimResolutionRequest(BaseModel):
    """불명 schedule claim을 운영자 확인 후 해제하는 요청."""

    model_config = ConfigDict(extra="forbid")

    resolution: PipelineScheduleClaimResolution
    reason: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=500),
    ]


class PipelineScheduleClaimResolutionResponse(BaseModel):
    """불명 schedule claim 해제 감사 결과."""

    model_config = ConfigDict(extra="forbid")

    data: DagsterScheduleClaimResolution
    meta: Meta


# =============================================================================
# Dagster GraphQL 조립 (routers/dagster.py 재사용 — T-ADM-C6b에서 본 그룹으로 이식)
# =============================================================================

_PIPELINE_OVERVIEW_QUERY = """
query KorTravelMapPipelineOverview($limit: Int!) {
  version
  repositoriesOrError {
    __typename
    ... on RepositoryConnection {
      nodes {
        name
        location { name }
        schedules { name }
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

_PIPELINE_DAGSTER_RUNS_QUERY = """
query KorTravelMapPipelineDagsterRuns($limit: Int!) {
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

_PIPELINE_SCHEDULES_QUERY = """
query KorTravelMapPipelineSchedules {
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


# =============================================================================
# 매핑 helper
# =============================================================================


def _execution_detail_url(kind: str, execution_id: str) -> str:
    return f"{_EXECUTIONS_URL_PREFIX}/{kind}/{execution_id}"


def _projected_job_record(row: PipelineProjectedJob) -> PipelineProjectedJobRecord:
    return PipelineProjectedJobRecord(
        id=row.id,
        job_kind=row.job_kind,
        status=row.status,
        progress=row.progress,
        current_stage=row.current_stage,
        error_message=row.error_message,
        created_at=row.created_at,
        started_at=row.started_at,
        finished_at=row.finished_at,
        dagster_run_id=row.dagster_run_id,
        dagster_run_status=row.dagster_run_status,
        trigger_kind=row.trigger_kind,
        operation_registry_version=row.operation_registry_version,
        load_batch_id=row.load_batch_id,
        parent_job_id=row.parent_job_id,
        depth=row.depth,
        detail_url=_execution_detail_url("import_job", row.id),
    )


def _provider_dataset_record(
    row: PipelineProviderDatasetIdentity,
) -> PipelineProviderDatasetIdentityRecord:
    return PipelineProviderDatasetIdentityRecord(
        provider=row.provider,
        dataset_key=row.dataset_key,
        sync_scope=row.sync_scope,
        operation_member_id=row.operation_member_id,
        status=row.status,
    )


def _record_from_execution(row: PipelineExecution) -> PipelineExecutionRootRecord:
    return PipelineExecutionRootRecord(
        kind=row.kind,
        id=row.id,
        status=row.status,
        created_at=row.created_at,
        providers=list(row.providers),
        dataset_keys=list(row.dataset_keys),
        provider_datasets=[_provider_dataset_record(item) for item in row.provider_datasets],
        progress=row.progress,
        current_stage=row.current_stage,
        scope_type=row.scope_type,
        priority=row.priority,
        run_mode=row.run_mode,
        operator=row.operator,
        error_message=row.error_message,
        started_at=row.started_at,
        finished_at=row.finished_at,
        dagster_run_id=row.dagster_run_id,
        dagster_run_status=row.dagster_run_status,
        trigger_kind=row.trigger_kind,
        operation_registry_version=row.operation_registry_version,
        requested_job_id=row.requested_job_id,
        linked_job_count=row.linked_job_count,
        projected_job=_projected_job_record(row.projected_job),
        cancellation=cancellation_summary_record(row.cancellation),
        detail_url=_execution_detail_url(row.kind, row.id),
    )


def _execution_from_job(
    job: OpsImportJob,
    *,
    canonical_request_id: str | None,
) -> PipelineExecutionRecord:
    return PipelineExecutionRecord(
        kind="import_job",
        id=job.job_id,
        status=job.status,
        created_at=job.created_at,
        job_kind=job.kind,
        provider=job.provider,
        dataset_key=job.dataset_key,
        progress=job.progress,
        current_stage=job.current_stage,
        error_message=job.error_message,
        started_at=job.started_at,
        finished_at=job.finished_at,
        dagster_run_id=job.dagster_run_id,
        dagster_run_status=job.dagster_run_status,
        trigger_kind=job.trigger_kind,
        operation_registry_version=job.operation_registry_version,
        job_id=None,
        request_id=canonical_request_id,
        load_batch_id=job.load_batch_id,
        parent_job_id=job.parent_job_id,
        scope_type=None,
        priority=None,
        run_mode=None,
        operator=None,
        detail_url=_execution_detail_url("import_job", job.job_id),
    )


def _execution_from_request(
    row: FeatureUpdateRequest,
    linked_job: OpsImportJob,
) -> PipelineExecutionRecord:
    return PipelineExecutionRecord(
        kind="update_request",
        id=row.request_id,
        status=row.status,
        created_at=row.created_at,
        job_kind=None,
        provider=linked_job.provider,
        dataset_key=linked_job.dataset_key,
        progress=None,
        current_stage=None,
        scope_type=row.scope_type,
        priority=row.priority,
        run_mode=row.run_mode,
        operator=row.operator,
        error_message=row.error_message,
        started_at=row.started_at,
        finished_at=row.finished_at,
        dagster_run_id=row.dagster_run_id,
        dagster_run_status=linked_job.dagster_run_status,
        trigger_kind="update_request",
        operation_registry_version=linked_job.operation_registry_version,
        job_id=row.job_id,
        request_id=None,
        load_batch_id=None,
        parent_job_id=None,
        detail_url=_execution_detail_url("update_request", row.request_id),
    )


def _import_job_record(job: OpsImportJob) -> PipelineImportJobRecord:
    return PipelineImportJobRecord(
        job_id=job.job_id,
        kind=job.kind,
        load_batch_id=job.load_batch_id,
        parent_job_id=job.parent_job_id,
        payload=job.payload,
        status=job.status,
        progress=job.progress,
        current_stage=job.current_stage,
        source_checksum=job.source_checksum,
        error_message=job.error_message,
        dagster_run_id=job.dagster_run_id,
        provider=job.provider,
        dataset_key=job.dataset_key,
        trigger_kind=job.trigger_kind,
        operation_registry_version=job.operation_registry_version,
        dagster_run_status=job.dagster_run_status,
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        heartbeat_at=job.heartbeat_at,
    )


def _event_record(event: OpsImportJobEvent) -> PipelineJobEventRecord:
    return PipelineJobEventRecord(
        event_id=event.event_id,
        job_id=event.job_id,
        provider=event.provider,
        dataset_key=event.dataset_key,
        feature_id=event.feature_id,
        stage=event.stage,
        level=event.level,
        code=event.code,
        message=event.message,
        payload=event.payload,
        occurred_at=event.occurred_at,
    )


def _update_request_record(row: FeatureUpdateRequest) -> FeatureUpdateRequestRecord:
    return feature_update_service.record_from_request(
        row, status_url_prefix=_UPDATE_REQUEST_STATUS_URL_PREFIX
    )


_COMMAND_NAME_MAP: dict[
    str, Literal["update", "clear_override", "run", "start", "stop", "reset"]
] = {
    "update": "update",
    "default": "clear_override",
    "run": "run",
    "start": "start",
    "stop": "stop",
    "reset": "reset",
}


def _pipeline_command_data(
    data: DagsterScheduleCommandData,
) -> PipelineScheduleCommandData:
    return PipelineScheduleCommandData(
        status=data.status,
        dagster_url=data.dagster_url,
        graphql_url=data.graphql_url,
        checked_at=data.checked_at,
        schedule_name=data.schedule_name,
        command=_COMMAND_NAME_MAP[data.command],
        cron_schedule=data.cron_schedule,
        default_cron_schedule=data.default_cron_schedule,
        override_cron_schedule=data.override_cron_schedule,
        effective_cron_schedule=data.effective_cron_schedule,
        schedule_status=data.schedule_status,
        run_id=data.run_id,
        run_status=data.run_status,
        save_status=data.save_status,
        reload_status=data.reload_status,
        effective_status=data.effective_status,
        outcome_certainty=data.outcome_certainty,
        audit_command_id=data.audit_command_id,
        audit_status=data.audit_status,
        errors=data.errors,
    )


def _pipeline_command_data_or_raise(
    data: DagsterScheduleCommandData,
) -> PipelineScheduleCommandData:
    """legacy service result를 canonical command 어휘로 변환한 후 HTTP 실패를 만든다."""

    canonical = _pipeline_command_data(data)
    if canonical.status == "ok":
        return canonical
    status_code = (
        status.HTTP_503_SERVICE_UNAVAILABLE
        if canonical.status == "unavailable"
        else status.HTTP_502_BAD_GATEWAY
    )
    code = (
        "DAGSTER_SCHEDULE_UNAVAILABLE"
        if canonical.status == "unavailable"
        else "DAGSTER_SCHEDULE_COMMAND_FAILED"
    )
    message = canonical.errors[0] if canonical.errors else "Dagster schedule 명령에 실패했습니다."
    raise HTTPException(
        status_code=status_code,
        detail={
            "code": code,
            "message": message,
            "details": canonical.model_dump(mode="json"),
        },
    )


async def _execute_audited_schedule_command(
    session: AsyncSession,
    *,
    schedule_name: str,
    command: dagster_schedule_service.ScheduleCommand,
    actor: str,
    reason: str | None,
    request_details: dict[str, object],
    command_id: UUID,
    operation: dagster_schedule_service.AuditedScheduleOperation,
) -> DagsterScheduleCommandResponse:
    try:
        return await dagster_schedule_service.execute_audited_schedule_command(
            session,
            schedule_name=schedule_name,
            command=command,
            actor=actor,
            reason=reason,
            request_details=request_details,
            command_id=command_id,
            operation=operation,
        )
    except dagster_schedule_service.DagsterScheduleIdempotencyConflict as exc:
        raise schedule_idempotency_http_exception(exc) from exc
    except dagster_schedule_service.DagsterScheduleUncertainOutcome as exc:
        raise schedule_uncertain_outcome_http_exception(exc) from exc
    except dagster_schedule_service.DagsterScheduleStorageUnavailable as exc:
        raise schedule_storage_http_exception(exc) from exc


# =============================================================================
# endpoints — overview / executions / events / dagster-runs
# =============================================================================


@router.get(
    "/overview",
    response_model=PipelineOverviewResponse,
    summary="파이프라인 상태 스트립 집계",
    description=(
        "Dagster 요약(run 카운트·sensor 상태 — 큐 sensor가 꺼지면 갱신요청 큐가 "
        "침묵 정지하는 실장애 모드를 상단에 노출)과 DB 작업/요청 카운트를 합친 "
        "상태 스트립 데이터. Dagster가 내려가도 200(status=unavailable)으로 "
        "DB 카운트는 계속 제공한다."
    ),
)
async def get_pipeline_overview(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    run_limit: int = Query(default=10, ge=1, le=50),
) -> PipelineOverviewResponse:
    started_at = perf_counter()
    checked_at = datetime.now(UTC)
    counts = await get_pipeline_status_counts(session)

    settings = _settings_from_request(request)
    dagster_part: PipelineDagsterOverview
    try:
        dagster_urls = dagster_graphql.dagster_urls(settings)
    except DagsterUrlConfigurationError as exc:
        dagster_part = PipelineDagsterOverview(
            status="error",
            dagster_url="",
            graphql_url="",
            errors=[str(exc)],
        )
    else:
        client = _http_client_from_request(request, settings)
        try:
            payload = await dagster_graphql.post_graphql(
                client=client,
                graphql_url=dagster_urls.graphql_url,
                variables={"limit": run_limit},
                query=_PIPELINE_OVERVIEW_QUERY,
            )
        except (httpx.HTTPError, ValueError) as exc:
            dagster_part = PipelineDagsterOverview(
                status="unavailable",
                dagster_url=dagster_urls.dagster_url,
                graphql_url=dagster_urls.graphql_url,
                errors=[str(exc)],
            )
        else:
            dagster_part = _parse_dagster_overview(payload, dagster_urls=dagster_urls)

    return PipelineOverviewResponse(
        data=PipelineOverviewData(
            checked_at=checked_at,
            dagster=dagster_part,
            operations_by_status=counts.operations_by_status,
            active_operations=counts.active_operations,
            failed_operations_24h=counts.failed_operations_24h,
        ),
        meta=make_meta(started_at=started_at),
    )


def _parse_dagster_overview(
    payload: dict[str, Any],
    *,
    dagster_urls: DagsterUrls,
) -> PipelineDagsterOverview:
    graphql_errors = payload.get("errors")
    if isinstance(graphql_errors, list) and graphql_errors:
        return PipelineDagsterOverview(
            status="error",
            dagster_url=dagster_urls.dagster_url,
            graphql_url=dagster_urls.graphql_url,
            errors=[dagster_graphql.graphql_error_message(error) for error in graphql_errors],
        )
    data = dagster_graphql.as_dict(payload.get("data"))
    repositories, repository_errors = dagster_graphql.parse_repositories(
        dagster_graphql.as_dict(data.get("repositoriesOrError")),
    )
    recent_runs, run_counts, run_errors = dagster_graphql.parse_runs(
        dagster_graphql.as_dict(data.get("runsOrError")),
    )
    errors = [*repository_errors, *run_errors]
    sensors = [sensor for repository in repositories for sensor in repository.sensors]
    return PipelineDagsterOverview(
        status="error" if errors else "ok",
        dagster_url=dagster_urls.dagster_url,
        graphql_url=dagster_urls.graphql_url,
        version=dagster_graphql.optional_string(data.get("version")),
        run_counts=run_counts,
        recent_runs=recent_runs,
        schedule_count=sum(len(repository.schedules) for repository in repositories),
        sensor_count=len(sensors),
        sensors=sensors,
        errors=errors,
    )


@router.get(
    "/executions",
    response_model=PipelineExecutionsListResponse,
    summary="root 실행 타임라인",
    description=(
        "import job hierarchy를 job별 nearest request anchor branch와 standalone "
        "partition으로 접어 root만 반환한다. keyset total order는 "
        "`(created_at DESC, id DESC, kind DESC)`이며 Dagster run은 각 root/대표 job의 "
        "`dagster_run_id`로만 연결한다. `sync_scope`는 `provider`와 `dataset_key`를 "
        "함께 요구하며 dataset 기본 state의 logical scope alias를 적용한다. "
        "`load_batch_id`와 `parent_job_id`는 root의 전체 component membership에 "
        "대해 cursor/LIMIT 전에 적용한다."
    ),
)
async def list_executions(
    session: Annotated[AsyncSession, Depends(get_session)],
    kind: Annotated[ExecutionKind | None, Query()] = None,
    status_filter: Annotated[ExecutionState | None, Query(alias="status")] = None,
    provider: Annotated[str | None, Query()] = None,
    dataset_key: Annotated[str | None, Query()] = None,
    sync_scope: Annotated[
        str | None,
        Query(
            min_length=1,
            description=(
                "provider+dataset exact pair의 논리 scope. 두 query를 함께 주어야 하며 "
                "기본 state는 dataset_wide/NULL 저장 표현을 같은 이력으로 조회한다."
            ),
        ),
    ] = None,
    load_batch_id: Annotated[UUID | None, Query()] = None,
    parent_job_id: Annotated[UUID | None, Query()] = None,
    created_from: Annotated[datetime | None, Query()] = None,
    created_to: Annotated[datetime | None, Query()] = None,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: Annotated[str | None, Query()] = None,
) -> PipelineExecutionsListResponse:
    started_at = perf_counter()
    try:
        dataset_sync_scopes = None
        if sync_scope is not None:
            if provider is None or dataset_key is None:
                raise ValueError("sync_scope requires both provider and dataset_key")
            dataset_sync_scopes = resolve_dataset_history_sync_scopes(
                provider,
                dataset_key,
                sync_scope,
            )
        page = await list_pipeline_executions(
            session,
            kind=kind,
            status=status_filter,
            provider=provider,
            dataset_key=dataset_key,
            dataset_sync_scopes=dataset_sync_scopes,
            load_batch_id=(str(load_batch_id) if load_batch_id is not None else None),
            parent_job_id=(str(parent_job_id) if parent_job_id is not None else None),
            created_from=created_from,
            created_to=created_to,
            limit=page_size,
            cursor=cursor,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return PipelineExecutionsListResponse(
        data=PipelineExecutionsData(
            items=[_record_from_execution(item) for item in page.items],
        ),
        meta=make_meta(
            started_at=started_at,
            page_size=page_size,
            next_cursor=page.next_cursor,
        ),
    )


async def _load_execution_detail(
    session: AsyncSession,
    *,
    kind: ExecutionKind,
    execution_id: str,
    level: JobEventLevel | None,
    page_size: int,
    cursor: str | None,
) -> PipelineExecutionDetailData:
    job: OpsImportJob | None = None
    update_request: FeatureUpdateRequest | None = None
    root = await get_pipeline_execution(
        session,
        kind=kind,
        execution_id=execution_id,
    )
    if kind == "import_job":
        job = await get_ops_import_job(session, execution_id)
        if job is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"import job not found: {execution_id}",
            )
        if root is not None and root.kind == "update_request":
            update_request = await get_update_request(session, root.id)
        execution = _execution_from_job(
            job,
            canonical_request_id=(
                root.id if root is not None and root.kind == "update_request" else None
            ),
        )
    else:
        update_request = await get_update_request(session, execution_id)
        if update_request is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"feature update request 없음: {execution_id!r}",
            )
        job = await get_ops_import_job(session, update_request.job_id)
        if job is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="feature update request의 canonical import job이 없습니다.",
            )
        execution = _execution_from_request(update_request, job)

    events: list[PipelineJobEventRecord] = []
    events_next_cursor: str | None = None
    if job is not None:
        try:
            events_page = await list_ops_import_job_events(
                session,
                job.job_id,
                level=level,
                limit=page_size,
                cursor=cursor,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        events = [_event_record(item) for item in events_page.items]
        events_next_cursor = events_page.next_cursor

    cancellation = cancellation_detail_record(
        await get_current_pipeline_cancellation_detail(
            session,
            kind=root.kind if root is not None else kind,
            execution_id=root.id if root is not None else execution_id,
        )
    )
    if root is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="canonical pipeline root projection을 찾을 수 없습니다.",
        )

    return PipelineExecutionDetailData(
        execution=execution,
        root=_record_from_execution(root),
        import_job=_import_job_record(job) if job is not None else None,
        update_request=(
            _update_request_record(update_request) if update_request is not None else None
        ),
        cancellation=cancellation,
        events=events,
        events_next_cursor=events_next_cursor,
    )


@router.get(
    "/executions/{kind}/{execution_id}",
    response_model=PipelineExecutionDetailResponse,
    summary="실행 상세 (+이벤트 cursor, 연결 개체)",
    responses={404: {"description": "실행 없음"}},
)
async def get_execution_detail(
    kind: ExecutionKind,
    execution_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    level: Annotated[JobEventLevel | None, Query()] = None,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: Annotated[str | None, Query()] = None,
) -> PipelineExecutionDetailResponse:
    # id는 UUID 경로 파라미터다 — 비정형 값은 FastAPI가 422로 거른다(SQL uuid
    # CAST의 DB 오류 500 유출 방지).
    started_at = perf_counter()
    data = await _load_execution_detail(
        session,
        kind=kind,
        execution_id=str(execution_id),
        level=level,
        page_size=page_size,
        cursor=cursor,
    )
    return PipelineExecutionDetailResponse(
        data=data,
        meta=make_meta(started_at=started_at),
    )


@router.post(
    "/executions/{kind}/{execution_id}/cancel",
    response_model=PipelineCancellationResponse,
    summary="canonical 실행 계층 취소",
    responses=cancellation_error_responses(not_found_description="실행 없음"),
)
async def cancel_execution(
    kind: ExecutionKind,
    execution_id: UUID,
    request: Request,
    engine: Annotated[AsyncEngine, Depends(get_engine)],
    context: Annotated[AdminProxyContext, Depends(require_admin_frontend)],
    body: PipelineCancellationRequest | None = None,
) -> PipelineCancellationResponse:
    started_at = perf_counter()
    settings, http_client = dagster_http_dependencies(request)
    try:
        record = await pipeline_cancellation_service.cancel_pipeline_execution(
            engine=engine,
            settings=settings,
            http_client=http_client,
            kind=kind,
            execution_id=str(execution_id),
            requested_by=context.actor,
            reason=body.reason if body is not None else None,
        )
    except pipeline_cancellation_service.PipelineCancellationServiceError as exc:
        raise cancellation_to_http_exception(exc) from exc
    return PipelineCancellationResponse(
        data=record,
        meta=make_meta(started_at=started_at),
    )


@router.get(
    "/events",
    response_model=PipelineEventsListResponse,
    summary="전역 job 이벤트 스트림",
    description=(
        "어느 job인지 모르는 상태에서 최근 error를 훑는 전역 "
        "`ops.import_job_events` 스트림 — level/provider/dataset/job 필터."
    ),
)
async def list_pipeline_events(
    session: Annotated[AsyncSession, Depends(get_session)],
    job_id: Annotated[UUID | None, Query()] = None,
    level: Annotated[JobEventLevel | None, Query()] = None,
    provider: Annotated[str | None, Query()] = None,
    dataset_key: Annotated[str | None, Query()] = None,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: Annotated[str | None, Query()] = None,
) -> PipelineEventsListResponse:
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
    return PipelineEventsListResponse(
        data=PipelineEventsData(items=[_event_record(item) for item in page.items]),
        meta=make_meta(
            started_at=started_at,
            page_size=page_size,
            next_cursor=page.next_cursor,
        ),
    )


@router.get(
    "/dagster-runs",
    response_model=PipelineDagsterRunsResponse,
    summary="보조 패널용 최근 Dagster run",
    description=(
        "import job을 만들지 못하고 죽은 순수 Dagster 실패의 가시성을 담당하는 "
        "보조 패널 데이터(GraphQL, limit, cursor 없음). Dagster가 내려가도 "
        "200(status=unavailable) graceful degrade 계약을 유지한다."
    ),
)
async def list_dagster_runs(
    request: Request,
    limit: int = Query(default=20, ge=1, le=100),
) -> PipelineDagsterRunsResponse:
    started_at = perf_counter()
    checked_at = datetime.now(UTC)
    settings = _settings_from_request(request)
    try:
        dagster_urls = dagster_graphql.dagster_urls(settings)
    except DagsterUrlConfigurationError as exc:
        return PipelineDagsterRunsResponse(
            data=PipelineDagsterRunsData(
                status="error",
                dagster_url="",
                graphql_url="",
                checked_at=checked_at,
                errors=[str(exc)],
            ),
            meta=make_meta(started_at=started_at),
        )
    client = _http_client_from_request(request, settings)
    try:
        payload = await dagster_graphql.post_graphql(
            client=client,
            graphql_url=dagster_urls.graphql_url,
            variables={"limit": limit},
            query=_PIPELINE_DAGSTER_RUNS_QUERY,
        )
    except (httpx.HTTPError, ValueError) as exc:
        return PipelineDagsterRunsResponse(
            data=PipelineDagsterRunsData(
                status="unavailable",
                dagster_url=dagster_urls.dagster_url,
                graphql_url=dagster_urls.graphql_url,
                checked_at=checked_at,
                errors=[str(exc)],
            ),
            meta=make_meta(started_at=started_at),
        )
    graphql_errors = payload.get("errors")
    if isinstance(graphql_errors, list) and graphql_errors:
        return PipelineDagsterRunsResponse(
            data=PipelineDagsterRunsData(
                status="error",
                dagster_url=dagster_urls.dagster_url,
                graphql_url=dagster_urls.graphql_url,
                checked_at=checked_at,
                errors=[dagster_graphql.graphql_error_message(error) for error in graphql_errors],
            ),
            meta=make_meta(started_at=started_at),
        )
    data = dagster_graphql.as_dict(payload.get("data"))
    runs, run_counts, run_errors = dagster_graphql.parse_runs(
        dagster_graphql.as_dict(data.get("runsOrError")),
    )
    return PipelineDagsterRunsResponse(
        data=PipelineDagsterRunsData(
            status="error" if run_errors else "ok",
            dagster_url=dagster_urls.dagster_url,
            graphql_url=dagster_urls.graphql_url,
            checked_at=checked_at,
            run_counts=run_counts,
            runs=runs,
            errors=run_errors,
        ),
        meta=make_meta(started_at=started_at),
    )


@router.get(
    "/prechecks/mois-source-sync",
    response_model=PipelineJobPrecheckResponse,
    summary="MOIS source sync 선행 job freshness 확인",
    description=(
        "Dagster runs를 exact jobName=mois_localdata_source_sync로 직접 필터링한다. "
        "최신 run이 SUCCESS이고, 현재 PROMOTED slug 집합의 SHA-256을 포함한 full-coverage "
        "tag가 일치하며, endTime이 존재하고 미래가 아닌 TTL 이내 시각일 때만 ready다. "
        "조건 누락·불일치는 fail-closed로 거부하며 provider sync_state의 가상 dataset "
        "key를 사용하지 않는다."
    ),
    responses={
        502: {"model": ProblemDetail, "description": "Dagster GraphQL/응답 오류"},
        503: {"model": ProblemDetail, "description": "Dagster 연결/설정 오류"},
    },
)
async def get_mois_source_sync_precheck(
    request: Request,
) -> PipelineJobPrecheckResponse:
    started_at = perf_counter()
    settings = _settings_from_request(request)
    client = _http_client_from_request(request, settings)
    try:
        precheck = await mois_source_precheck.fetch_mois_source_sync_precheck(
            settings=settings,
            client=client,
        )
    except mois_source_precheck.MoisSourceSyncPrecheckError as exc:
        raise mois_source_precheck.to_http_exception(exc) from exc
    return PipelineJobPrecheckResponse(
        data=PipelineJobPrecheckData(
            job_name=precheck.job_name,
            ready=precheck.ready,
            checked_at=precheck.checked_at,
            max_age_hours=precheck.max_age_hours,
            age_hours=precheck.age_hours,
            latest_run=precheck.latest_run,
            disabled_reason=precheck.disabled_reason,
        ),
        meta=make_meta(started_at=started_at),
    )


@router.get(
    "/dagster-runs/{run_id:path}",
    response_model=DagsterRunDetailResponse,
    summary="Dagster run event/failure 상세",
    description=(
        "선택한 Dagster run의 event cursor page와 구조화 실패 event를 조회한다. "
        "목록의 graceful degrade와 달리 성공만 200이며 not-found/unavailable/query "
        "실패는 각각 404/503/502 RFC7807로 반환한다."
    ),
    responses={
        404: {"description": "DAGSTER_RUN_NOT_FOUND — Dagster run 없음"},
        502: {"description": "DAGSTER_QUERY_FAILED — 설정/GraphQL/응답 오류"},
        503: {"description": "DAGSTER_UNAVAILABLE — Dagster 연결 실패"},
    },
)
async def get_pipeline_dagster_run_detail(
    request: Request,
    run_id: DagsterRunId,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
    after: Annotated[
        str | None,
        Query(
            min_length=1,
            max_length=2048,
            description="이전 응답의 event_cursor(Dagster opaque cursor).",
        ),
    ] = None,
) -> DagsterRunDetailResponse:
    settings = _settings_from_request(request)
    response = dagster_query_service.get_run_detail_configuration_error(settings)
    if response is None:
        client = _http_client_from_request(request, settings)
        response = await dagster_query_service.get_run_detail(
            settings=settings,
            client=client,
            run_id=run_id,
            page_size=page_size,
            after=after,
        )
    if response.data.status == "ok":
        return response

    if response.data.status == "not_found":
        status_code = status.HTTP_404_NOT_FOUND
        code = "DAGSTER_RUN_NOT_FOUND"
        message = "Dagster run을 찾을 수 없습니다."
    elif response.data.status == "unavailable":
        status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        code = "DAGSTER_UNAVAILABLE"
        message = "Dagster에 연결할 수 없습니다."
    else:
        status_code = status.HTTP_502_BAD_GATEWAY
        code = "DAGSTER_QUERY_FAILED"
        message = "Dagster run 상세 조회에 실패했습니다."
    raise HTTPException(
        status_code=status_code,
        detail={
            "code": code,
            "message": message,
            "details": {
                "run_id": run_id,
                "errors": response.data.errors,
            },
        },
    )


# =============================================================================
# endpoints — schedules
# =============================================================================


@router.get(
    "/schedules",
    response_model=PipelineSchedulesResponse,
    summary="스케줄 목록 (override 병합) + sensor 상태",
)
async def list_pipeline_schedules(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> PipelineSchedulesResponse:
    started_at = perf_counter()
    checked_at = datetime.now(UTC)
    settings = _settings_from_request(request)
    try:
        dagster_urls = dagster_graphql.dagster_urls(settings)
    except DagsterUrlConfigurationError as exc:
        return PipelineSchedulesResponse(
            data=PipelineSchedulesData(
                status="error",
                dagster_url="",
                graphql_url="",
                checked_at=checked_at,
                errors=[str(exc)],
            ),
            meta=make_meta(started_at=started_at),
        )
    client = _http_client_from_request(request, settings)
    try:
        overrides = await dagster_schedule_service.schedule_overrides(session)
    except dagster_schedule_service.DagsterScheduleStorageUnavailable as exc:
        raise schedule_storage_http_exception(exc) from exc
    try:
        payload = await dagster_graphql.post_graphql(
            client=client,
            graphql_url=dagster_urls.graphql_url,
            variables={},
            query=_PIPELINE_SCHEDULES_QUERY,
        )
    except (httpx.HTTPError, ValueError) as exc:
        return PipelineSchedulesResponse(
            data=PipelineSchedulesData(
                status="unavailable",
                dagster_url=dagster_urls.dagster_url,
                graphql_url=dagster_urls.graphql_url,
                checked_at=checked_at,
                errors=[str(exc)],
            ),
            meta=make_meta(started_at=started_at),
        )
    graphql_errors = payload.get("errors")
    if isinstance(graphql_errors, list) and graphql_errors:
        return PipelineSchedulesResponse(
            data=PipelineSchedulesData(
                status="error",
                dagster_url=dagster_urls.dagster_url,
                graphql_url=dagster_urls.graphql_url,
                checked_at=checked_at,
                errors=[dagster_graphql.graphql_error_message(error) for error in graphql_errors],
            ),
            meta=make_meta(started_at=started_at),
        )
    data = dagster_graphql.as_dict(payload.get("data"))
    repositories, errors = dagster_graphql.parse_repositories(
        dagster_graphql.as_dict(data.get("repositoriesOrError")),
        overrides=overrides,
    )
    schedules = [schedule for repository in repositories for schedule in repository.schedules]
    sensors = [sensor for repository in repositories for sensor in repository.sensors]
    return PipelineSchedulesResponse(
        data=PipelineSchedulesData(
            status="error" if errors else "ok",
            dagster_url=dagster_urls.dagster_url,
            graphql_url=dagster_urls.graphql_url,
            checked_at=checked_at,
            schedules=schedules,
            sensors=sensors,
            errors=errors,
        ),
        meta=make_meta(started_at=started_at),
    )


@router.patch(
    "/schedules/{schedule_name}",
    response_model=PipelineScheduleCommandResponse,
    summary="스케줄 cron 수정 (null = override 삭제)",
    description=(
        "`cron_schedule`이 문자열이면 override를 저장하고, 명시적 `null`이면 "
        "override를 삭제해 코드 기본값으로 되돌린다(구 `default` 명령 대체). "
        "override는 code location reload 이후 반영되므로 지연이 있을 수 있다."
    ),
    responses=SCHEDULE_WRITE_ERROR_RESPONSES,
)
async def patch_pipeline_schedule(
    request: Request,
    schedule_name: str,
    body: PipelineScheduleUpdateRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AdminProxyContext, Depends(require_admin_frontend)],
    idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
) -> PipelineScheduleCommandResponse:
    started_at = perf_counter()
    settings = _settings_from_request(request)
    client = _http_client_from_request(request, settings)
    if body.cron_schedule is None:
        response = await _execute_audited_schedule_command(
            session,
            schedule_name=schedule_name,
            command="default",
            actor=context.actor,
            reason=body.reason,
            request_details={"target": "code_default"},
            command_id=idempotency_key,
            operation=lambda mutation_guard: dagster_schedule_service.reset_schedule_default(
                settings=settings,
                client=client,
                session=session,
                schedule_name=schedule_name,
                mutation_guard=mutation_guard,
            ),
        )
    else:
        try:
            response = await _execute_audited_schedule_command(
                session,
                schedule_name=schedule_name,
                command="update",
                actor=context.actor,
                reason=body.reason,
                request_details={"cron_schedule": body.cron_schedule},
                command_id=idempotency_key,
                operation=lambda mutation_guard: dagster_schedule_service.update_schedule(
                    settings=settings,
                    client=client,
                    session=session,
                    schedule_name=schedule_name,
                    body=DagsterScheduleOverrideRequest(
                        cron_schedule=body.cron_schedule,
                        reason=body.reason,
                    ),
                    actor=context.actor,
                    mutation_guard=mutation_guard,
                ),
            )
        except dagster_schedule_service.DagsterScheduleValidationError as exc:
            raise schedule_validation_http_exception(exc) from exc
    return PipelineScheduleCommandResponse(
        data=_pipeline_command_data_or_raise(response.data),
        meta=make_meta(started_at=started_at),
    )


@router.post(
    "/schedules/{schedule_name}/commands",
    response_model=PipelineScheduleCommandResponse,
    summary="스케줄 명령 실행 — {command: run|start|stop|reset}",
    description=(
        "run은 스케줄이 가리키는 job을 현재 설정으로 1회 즉시 실행하고, "
        "start/stop은 스케줄 상태를 전환하며, reset은 코드 기본 상태로 되돌린다."
    ),
    responses=SCHEDULE_WRITE_ERROR_RESPONSES,
)
async def post_pipeline_schedule_command(
    request: Request,
    schedule_name: str,
    body: PipelineScheduleCommandRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AdminProxyContext, Depends(require_admin_frontend)],
    idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
) -> PipelineScheduleCommandResponse:
    started_at = perf_counter()
    settings = _settings_from_request(request)
    client = _http_client_from_request(request, settings)
    command = body.command
    if command == "run":
        response = await _execute_audited_schedule_command(
            session,
            schedule_name=schedule_name,
            actor=context.actor,
            command=command,
            reason=body.reason,
            request_details={"command": command},
            command_id=idempotency_key,
            operation=lambda mutation_guard: dagster_schedule_service.run_schedule_now(
                settings=settings,
                client=client,
                session=session,
                schedule_name=schedule_name,
                body=DagsterScheduleCommandRequest(reason=body.reason),
                actor=context.actor,
                mutation_guard=mutation_guard,
            ),
        )
    else:
        response = await _execute_audited_schedule_command(
            session,
            schedule_name=schedule_name,
            actor=context.actor,
            command=command,
            reason=body.reason,
            request_details={"command": command},
            command_id=idempotency_key,
            operation=lambda mutation_guard: dagster_schedule_service.mutate_schedule_state(
                settings=settings,
                client=client,
                session=session,
                schedule_name=schedule_name,
                command=command,
                mutation_guard=mutation_guard,
            ),
        )
    return PipelineScheduleCommandResponse(
        data=_pipeline_command_data_or_raise(response.data),
        meta=make_meta(started_at=started_at),
    )


@router.post(
    "/schedules/{schedule_name}/claims/{command_id}/resolve",
    response_model=PipelineScheduleClaimResolutionResponse,
    summary="결과 불명 schedule claim 수동 확인 및 해제",
    description=(
        "transport 장애 등으로 Dagster 반영 여부를 자동 확정할 수 없는 명령은 같은 "
        "schedule의 후속 조작을 막는다. 운영자가 Dagster 실제 상태를 별도로 확인한 뒤 "
        "반영 여부와 필수 사유를 기록하면 append-only 감사 이력을 남기고 claim을 해제한다. "
        "외부 호출 종료가 기록되지 않은 requested-only claim은 5분 안전 lease가 만료되기 "
        "전까지 active command ID를 노출하지 않고 해제도 거부한다. "
        "응답 유실 뒤 같은 command_id·resolution·정규화된 사유로 재요청하면 기존 결과를 "
        "replayed=true로 재생하고, resolution 또는 사유가 다르면 409로 거부한다."
    ),
    responses={
        404: {"model": ProblemDetail, "description": "schedule claim 없음"},
        409: {
            "model": ProblemDetail,
            "description": "확정 결과인 claim 또는 기존 해제 결과와 요청 body 불일치",
        },
        422: {"model": ProblemDetail, "description": "해제 사유 또는 resolution 검증 실패"},
        503: {"model": ProblemDetail, "description": "schedule 감사 저장소 장애"},
    },
)
async def resolve_pipeline_schedule_claim(
    schedule_name: str,
    command_id: UUID,
    body: PipelineScheduleClaimResolutionRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AdminProxyContext, Depends(require_admin_frontend)],
) -> PipelineScheduleClaimResolutionResponse:
    started_at = perf_counter()
    try:
        resolution = await dagster_schedule_service.resolve_schedule_active_claim(
            session,
            schedule_name=schedule_name,
            command_id=command_id,
            resolution=body.resolution,
            actor=context.actor,
            reason=body.reason,
        )
    except dagster_schedule_service.DagsterScheduleClaimNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "DAGSTER_SCHEDULE_CLAIM_NOT_FOUND",
                "message": str(exc),
                "details": {
                    "schedule_name": schedule_name,
                    "command_id": str(command_id),
                },
            },
        ) from exc
    except dagster_schedule_service.DagsterScheduleClaimResolutionConflict as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "DAGSTER_SCHEDULE_CLAIM_RESOLUTION_CONFLICT",
                "message": str(exc),
                "details": {
                    "schedule_name": schedule_name,
                    "command_id": str(command_id),
                },
            },
        ) from exc
    except dagster_schedule_service.DagsterScheduleStorageUnavailable as exc:
        raise schedule_storage_http_exception(exc) from exc
    return PipelineScheduleClaimResolutionResponse(
        data=resolution,
        meta=make_meta(started_at=started_at),
    )


# =============================================================================
# endpoints — 갱신 요청 생성/재큐잉
# =============================================================================


@router.post(
    "/requests",
    response_model=FeatureUpdateRequestCreateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="feature update request 생성",
    description=(
        "6-type scope union(feature_ids/center_radius/sigungu_by_radius/bbox/"
        "provider_dataset/cache_target_keys) + reason 감사 사유 + priority 계약을 "
        "전량 승계한다. operator는 인증된 admin actor를 사용한다. 카탈로그 refreshable 검증과 "
        "run_mode=now의 동일 scope advisory lock(409 + Retry-After)을 포함한다."
    ),
    responses={
        200: {
            "model": FeatureUpdateRequestCreateResponse,
            "description": (
                "같은 계획의 활성 canonical request 재사용 또는 같은 "
                "Idempotency-Key의 terminal 결과 재생"
            ),
        },
        **FEATURE_UPDATE_CONFLICT_RESPONSES,
        **mois_source_precheck.MOIS_SOURCE_PRECHECK_ERROR_RESPONSES,
    },
)
async def create_pipeline_update_request(
    request: Request,
    body: FeatureUpdateRequestCreateRequest,
    response: Response,
    idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AdminProxyContext, Depends(require_admin_frontend)],
) -> FeatureUpdateRequestCreateResponse:
    api_settings = _settings_from_request(request)
    dagster_client = _http_client_from_request(request, api_settings)

    async def _resolved_plan_guard(
        resolved_pairs: frozenset[tuple[str, str]],
    ) -> None:
        await mois_source_precheck.ensure_mois_source_sync_for_plan(
            resolved_pairs,
            settings=api_settings,
            client=dagster_client,
        )

    try:
        result = await feature_update_service.create_feature_update_request(
            body,
            session,
            idempotency_key=idempotency_key,
            operator=context.actor,
            status_url_prefix=_UPDATE_REQUEST_STATUS_URL_PREFIX,
            settings=KorTravelMapSettings(),
            resolved_plan_guard=_resolved_plan_guard,
        )
    except (
        mois_source_precheck.MoisSourceSyncPrecheckError,
        mois_source_precheck.MoisSourceSyncRequired,
    ) as exc:
        raise mois_source_precheck.to_http_exception(exc) from exc
    except feature_update_service.FeatureUpdateServiceError as exc:
        raise to_http_exception(exc) from exc
    if result.idempotent_replay or result.reused_active_request:
        response.status_code = status.HTTP_200_OK
    return result


@router.post(
    "/requests/preview",
    response_model=FeatureUpdateRequestPreviewResponse,
    status_code=status.HTTP_200_OK,
    summary="feature update request 비영속 미리보기",
    description="scope 대상과 provider/dataset 실행 계획을 계산하며 DB 행은 만들지 않는다.",
)
async def preview_pipeline_update_request(
    body: FeatureUpdateRequestPreviewRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> FeatureUpdateRequestPreviewResponse:
    try:
        return await feature_update_service.preview_feature_update_request(
            body,
            session,
            settings=KorTravelMapSettings(),
        )
    except feature_update_service.FeatureUpdateServiceError as exc:
        raise to_http_exception(exc) from exc


@router.post(
    "/requests/{request_id}/run-now",
    response_model=FeatureUpdateRequestMutationResponse,
    status_code=status.HTTP_200_OK,
    summary="기존 canonical request 우선 dispatch 요청",
    description=(
        "새 request를 만들지 않고 같은 canonical job의 dispatch_requested_at을 "
        "최초 한 번 기록한다. queued 재호출과 running 조회는 멱등이다."
    ),
    responses={
        404: {"description": "request_id 없음"},
        **FEATURE_UPDATE_CONFLICT_RESPONSES,
    },
)
async def run_pipeline_update_request_now(
    request_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    _context: Annotated[AdminProxyContext, Depends(require_admin_frontend)],
    _body: FeatureUpdateRequestRunNowRequest | None = None,
) -> FeatureUpdateRequestMutationResponse:
    started_at = perf_counter()
    try:
        async with session.begin():
            result = await feature_update_service.run_feature_update_request_now(
                session,
                request_id=str(request_id),
            )
    except feature_update_service.FeatureUpdateServiceError as exc:
        raise to_http_exception(exc) from exc
    return feature_update_service.persisted_response(
        result,
        started_at=started_at,
        status_url_prefix=_UPDATE_REQUEST_STATUS_URL_PREFIX,
    )
