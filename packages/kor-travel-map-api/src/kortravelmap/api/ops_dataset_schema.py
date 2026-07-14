"""``/ops/datasets`` HTTP schema (ADR-064, #678).

라우터·DB 조립·preview 실행과 분리해 C4 frontend가 소비하는 계약을 한 곳에 둔다.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

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


class OpsDatasetCatalogInfo(BaseModel):
    """ETL 카탈로그가 아는 dataset 메타."""

    model_config = ConfigDict(extra="forbid")

    feature_kind: str
    default_sync_scope: str
    label: str
    is_feature_load: bool
    is_refreshable: bool
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


class OpsDatasetLatestExecution(BaseModel):
    """그리드 N+1 없이 붙이는 최신 DB-recorded execution."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["import_job", "update_request"]
    execution_id: str
    status: str
    status_source: Literal["import_job", "update_request"]
    job_status: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    dagster_run_id: str | None
    job_id: str | None
    request_id: str | None
    progress: int | None
    current_stage: str | None
    error_message: str | None


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
    refresh_policy: ProviderRefreshPolicyRecord | None = None
    dataset_issues: OpsIssueSummary
    provider_issues: OpsIssueSummary


class OpsDatasetsGridData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[OpsDatasetGridRow]
    schedule_source_status: ScheduleSourceStatus
    schedule_source_errors: list[str] = Field(default_factory=list)
    latest_execution_coverage: Literal["db_recorded"] = Field(
        default="db_recorded",
        description=(
            "import job event와 provider_dataset update request로 DB identity가 남은 "
            "실행만 포함. schedule/manual 전체 operation 정본은 #679 범위."
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


class OpsDatasetRunSummary(BaseModel):
    """기존 update request + 연결 import job 상세 요약.

    schedule/manual 전체 operation 정본은 #679에서 교체한다.
    """

    model_config = ConfigDict(extra="forbid")

    request_id: str
    status: str
    run_mode: str
    scope_type: str
    dry_run: bool
    priority: int
    job_id: str | None = None
    dagster_run_id: str | None = None
    job_status: str | None = None
    job_progress: int | None = None
    job_current_stage: str | None = None
    operator: str | None = None
    reason: str | None = None
    error_message: str | None = None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    updated_at: datetime


class OpsDatasetEventRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str
    job_id: str
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
    schedule_source_errors: list[str] = Field(default_factory=list)
    refresh_policy: ProviderRefreshPolicyRecord | None = None
    recent_runs: list[OpsDatasetRunSummary]
    recent_runs_coverage: Literal["update_requests_only"] = Field(
        default="update_requests_only",
        description="schedule/manual 전체 operation 통합은 #679 범위.",
    )
    recent_events: list[OpsDatasetEventRecord]
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
    dataset: str
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
