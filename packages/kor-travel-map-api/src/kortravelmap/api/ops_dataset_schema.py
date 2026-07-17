"""``/ops/datasets`` HTTP schema (ADR-064, #678).

라우터·DB 조립·preview 실행과 분리해 C4 frontend가 소비하는 계약을 한 곳에 둔다.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from kortravelmap.api.ops_operation_schema import OperationState
from kortravelmap.api.pipeline_cancellation_schema import (
    PipelineCancellationSummaryRecord,
)
from kortravelmap.api.provider_refresh_schema import ProviderRefreshPolicyRecord
from kortravelmap.api.response import Meta

__all__ = [
    "OpsDatasetDetailResponse",
    "OpsDatasetPreviewRequest",
    "OpsDatasetPreviewResponse",
    "OpsDatasetRefreshPolicyResponse",
    "OpsDatasetsGridResponse",
]

FreshnessState = Literal["never_run", "fresh", "overdue", "disabled", "unknown"]
FreshnessBasis = Literal["policy_stale_after", "unknown", "disabled"]
CatalogState = Literal["canonical", "orphan"]
ScheduleSourceStatus = Literal["ok", "unavailable", "error"]


class OpsDatasetPreviewCapability(BaseModel):
    """dataset preview 입력·예산 계약."""

    model_config = ConfigDict(extra="forbid")

    supported: bool
    sources: list[Literal["fixture"]] = Field(default_factory=list)
    input_kind: Literal["none"] = "none"
    default_max_items: int = 20
    max_items_limit: int = 100
    timeout_seconds: float = 5.0
    external_call_budget: int = Field(
        default=0,
        description="fixture-only preview이므로 외부 provider 호출 허용 횟수는 0.",
    )


class OpsDatasetScopeRefreshCapability(BaseModel):
    """직접 갱신 요청에서 선택 가능한 effective sync scope 계약."""

    model_config = ConfigDict(extra="forbid")

    supported: bool
    selector: Literal["none", "poi_cache_targets"]
    effect: Literal["dataset_wide", "sync_scope"]
    default_sync_scope: str
    allowed_sync_scopes: list[str]
    reason: str | None = None


class OpsDatasetCatalogInfo(BaseModel):
    """ETL 카탈로그가 아는 dataset 메타."""

    model_config = ConfigDict(extra="forbid")

    feature_kind: str
    provider_state_default_scope: str
    label: str
    is_feature_load: bool
    is_refreshable: bool
    scope_refresh: OpsDatasetScopeRefreshCapability
    preview: OpsDatasetPreviewCapability


class OpsDatasetFreshness(BaseModel):
    """정책 SLA와 마지막 성공으로 서버가 계산한 freshness."""

    model_config = ConfigDict(extra="forbid")

    state: FreshnessState
    basis: FreshnessBasis
    sla_seconds: int | None
    due_at: datetime | None
    is_overdue: bool
    overdue_by_seconds: int


class OpsDatasetScheduleSummary(BaseModel):
    """Dagster GraphQL 실제 schedule 정의/상태 기반 다음 tick."""

    model_config = ConfigDict(extra="forbid")

    source: Literal["dagster_graphql"] = "dagster_graphql"
    basis: Literal["dagster_definition_tags", "not_scheduled", "unknown"]
    status: str | None
    schedule_names: list[str]
    active_schedule_names: list[str]
    next_scheduled_at: datetime | None = Field(
        description=(
            "RUNNING Dagster schedule의 futureTicks 첫 timestamp. refresh policy에서 "
            "파생한 시각이 아니며 STOPPED/미등록이면 null."
        )
    )


class OpsDatasetProjectedJob(BaseModel):
    """canonical root branch의 deterministic job projection."""

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
    depth: int
    detail_url: str


class OpsDatasetProviderDataset(BaseModel):
    """canonical root의 exact provider/dataset member 상태."""

    model_config = ConfigDict(extra="forbid")

    provider: str
    dataset_key: str
    sync_scope: str | None
    operation_member_id: UUID
    status: OperationState


class OpsDatasetLatestExecution(BaseModel):
    """그리드 N+1 없이 붙이는 최신 canonical operation."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["import_job", "update_request"]
    id: UUID
    detail_url: str
    status: OperationState
    pair_status: OperationState
    operation_member_id: UUID
    sync_scope: str | None
    providers: list[str]
    dataset_keys: list[str]
    provider_datasets: list[OpsDatasetProviderDataset]
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    dagster_run_id: str | None
    dagster_run_status: str | None
    trigger_kind: str | None
    operation_registry_version: str | None
    error_message: str | None
    projected_job: OpsDatasetProjectedJob
    cancellation: PipelineCancellationSummaryRecord | None


class OpsIssueSummary(BaseModel):
    """미해결(open/acknowledged) integrity issue 집계."""

    model_config = ConfigDict(extra="forbid")

    open_count: int
    severity_counts: dict[str, int]


class OpsDatasetGridRow(BaseModel):
    """provider×dataset×sync_scope 그리드 1행."""

    model_config = ConfigDict(extra="forbid")

    provider: str
    dataset_key: str
    detail_url: str
    sync_scope: str
    status: str
    last_success_at: datetime | None
    last_failure_at: datetime | None
    consecutive_failures: int
    eligible_after: datetime | None = Field(
        description=(
            "provider rate-limit/backoff상 다시 호출 가능한 시각. schedule 시각이 아님."
        )
    )
    freshness: OpsDatasetFreshness
    schedule: OpsDatasetScheduleSummary
    latest_execution: OpsDatasetLatestExecution | None
    catalog_state: CatalogState
    orphan_reason: str | None
    mutable: bool
    catalog: OpsDatasetCatalogInfo | None
    refresh_policy: ProviderRefreshPolicyRecord | None
    dataset_issues: OpsIssueSummary
    provider_issues: OpsIssueSummary


class OpsDatasetsGridData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[OpsDatasetGridRow]
    schedule_source_status: ScheduleSourceStatus
    schedule_source_errors: list[str]
    latest_execution_coverage: Literal["db_recorded_canonical_operations"] = Field(
        default="db_recorded_canonical_operations",
        description=(
            "DB에 영속된 canonical root와 exact provider/dataset operation을 포함한다."
        ),
    )


class OpsDatasetsGridResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data: OpsDatasetsGridData
    meta: Meta


class OpsDatasetScopeState(BaseModel):
    """상세의 sync_scope 상태."""

    model_config = ConfigDict(extra="forbid")

    sync_scope: str
    status: str
    cursor: dict[str, Any]
    last_success_at: datetime | None
    last_failure_at: datetime | None
    consecutive_failures: int
    eligible_after: datetime | None
    freshness: OpsDatasetFreshness


class OpsDatasetEventRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: UUID
    job_id: UUID
    sync_scope: str
    stage: str | None
    level: str
    code: str | None
    message: str
    occurred_at: datetime


class OpsDatasetDetailData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str
    dataset_key: str
    catalog_state: CatalogState
    orphan_reason: str | None
    mutable: bool
    catalog: OpsDatasetCatalogInfo | None
    scopes: list[OpsDatasetScopeState]
    schedule: OpsDatasetScheduleSummary
    schedule_source_status: ScheduleSourceStatus
    schedule_source_errors: list[str]
    refresh_policy: ProviderRefreshPolicyRecord | None
    recent_runs: list[OpsDatasetLatestExecution]
    recent_runs_coverage: Literal["db_recorded_canonical_operations"] = Field(
        default="db_recorded_canonical_operations",
        description="DB에 영속된 exact pair canonical operation 이력.",
    )
    recent_runs_next_cursor: str | None
    pipeline_history_url: str
    recent_events: list[OpsDatasetEventRecord]
    recent_events_next_cursor: str | None
    event_history_url: str
    dataset_issues: OpsIssueSummary
    provider_issues: OpsIssueSummary


class OpsDatasetDetailResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data: OpsDatasetDetailData
    meta: Meta


class OpsDatasetRefreshPolicyResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data: ProviderRefreshPolicyRecord
    meta: Meta


class OpsDatasetPreviewRequest(BaseModel):
    """fixture preview의 유일한 typed 입력."""

    model_config = ConfigDict(extra="forbid")

    source: Literal["fixture"] = "fixture"
    max_items: int = Field(default=20, ge=1, le=100)


class OpsDatasetPreviewBudget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_items: int
    timeout_seconds: float
    external_call_budget: Literal[0] = 0


class OpsDatasetPreviewData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str
    dataset_key: str
    source: Literal["fixture"]
    variant: str
    description: str
    items: list[dict[str, Any]]
    total_items: int
    returned_items: int
    truncated: bool
    budget: OpsDatasetPreviewBudget


class OpsDatasetPreviewResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data: OpsDatasetPreviewData
    meta: Meta
