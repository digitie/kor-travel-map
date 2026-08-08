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
    basis: Literal["dagster_operation_key_tag", "not_scheduled", "unknown"]
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
    operation_key: str | None
    depth: int
    detail_url: str


class OpsDatasetProviderDataset(BaseModel):
    """canonical root의 exact provider/dataset member 상태."""

    model_config = ConfigDict(extra="forbid")

    provider_dataset_id: int = Field(ge=1)
    provider: str
    dataset_key: str
    # 실행 membership identity는 triple이다(ADR-088 §결정 2). 셋 다 non-null이라야
    # UI가 member를 구분해 표시하고 deep link를 만들 수 있다 — nullable로 두면
    # operation만 다른 두 member가 화면에서 같은 행으로 보인다.
    sync_scope: str
    operation_key: str
    operation_member_id: UUID
    status: OperationState


class OpsDatasetExecution(BaseModel):
    """dataset exact scope에 귀속된 canonical operation projection."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["import_job", "update_request"]
    id: UUID
    detail_url: str
    status: OperationState
    pair_status: OperationState
    operation_member_id: UUID
    # 공급원 ``DatasetLatestExecution.sync_scope``가 non-null이고 DB 열도 NOT NULL이다.
    sync_scope: str
    provider_datasets: list[OpsDatasetProviderDataset]
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    dagster_run_id: str | None
    dagster_run_status: str | None
    trigger_kind: str | None
    # 이 레코드가 **어느 membership을 본 것인지**를 말한다 — 바로 위 ``sync_scope``와
    # 같은 축이다. 한 root가 형제 operation 둘을 건드리면 레코드가 둘 나오고, 이
    # 값으로만 구분된다. root 자신의 trigger operation은 ``projected_job``이 든다.
    operation_key: str | None
    error_message: str | None
    projected_job: OpsDatasetProjectedJob
    cancellation: PipelineCancellationSummaryRecord | None


class OpsIssueSummary(BaseModel):
    """미해결(open/acknowledged) integrity issue 집계."""

    model_config = ConfigDict(extra="forbid")

    open_count: int
    severity_counts: dict[str, int]


class OpsDatasetGridRow(BaseModel):
    """exact membership triple 그리드 1행.

    행 identity는 ``provider_dataset_id × sync_scope × operation_key``다
    (ADR-088 §결정 2). 한 dataset이 refresh operation을 여럿 가질 수 있고 그 둘이
    같은 ``sync_scope``를 공유할 수 있으므로, pair로 접으면 형제 operation의 상태가
    무경고로 사라진다 — 실패 중인 operation이 형제에 가려 보이지 않는다.

    ``operation_key``가 null인 행은 **실행 가능한 refresh operation이 없는 catalog
    행**이다(실측 74개 dataset 중 18개). 그 행에는 결박할 실행 identity가 아예 없으며,
    운영자에게는 catalog 존재·orphan 사유·issue를 보이기 위해 남긴다.
    """

    model_config = ConfigDict(extra="forbid")

    provider_dataset_id: int = Field(ge=1)
    provider: str
    dataset_key: str
    detail_url: str
    sync_scope: str
    operation_key: str | None = Field(
        description=(
            "이 행이 가리키는 실행 operation. null이면 실행 가능한 refresh "
            "operation이 없는 catalog 전용 행이다."
        )
    )
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
    latest_execution: OpsDatasetExecution | None
    active_execution: OpsDatasetExecution | None = Field(
        description=(
            "같은 provider/dataset/sync_scope의 queued/running canonical operation. "
            "더 최신 terminal 실행과 독립적으로 조회한다."
        )
    )
    catalog_state: CatalogState
    orphan_reason: str | None
    mutable: bool
    catalog: OpsDatasetCatalogInfo | None
    refresh_policy: ProviderRefreshPolicyRecord | None
    dataset_issues: OpsIssueSummary


class OpsDatasetsGridData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[OpsDatasetGridRow]
    schedule_source_status: ScheduleSourceStatus
    schedule_source_errors: list[str]
    execution_coverage: Literal["db_recorded_canonical_operations"] = Field(
        description=(
            "DB에 영속된 canonical root와 exact provider/dataset operation을 포함한다."
        ),
    )


class OpsDatasetsGridResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data: OpsDatasetsGridData
    meta: Meta


class OpsDatasetScopeState(BaseModel):
    """상세의 membership별 sync state.

    ``pk_provider_sync_state``가 triple이므로 scope 하나에 operation별 state가 여러 개
    존재할 수 있다. ``operation_key`` 없이 내보내면 클라이언트가 어느 operation의
    상태인지 가릴 수 없다.
    """

    model_config = ConfigDict(extra="forbid")

    sync_scope: str
    # grid 행과 같은 규약이다 — refresh operation이 없는 catalog membership은 null이다.
    # 여기만 ``""``로 채우면 같은 응답 안에서 표면이 어긋나고, 빈 문자열이 실재하는
    # operation처럼 보인다.
    operation_key: str | None
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
    import_job_dataset_id: UUID | None
    provider_dataset_id: int | None
    sync_scope: str
    # membership identity의 나머지 한 축 — 형제 operation의 event를 가르려면 필요하다.
    # member가 없는 event(dataset에 결박되지 않은 job-level event)는 null이다.
    operation_key: str | None
    stage: str | None
    level: str
    code: str | None
    message: str
    occurred_at: datetime


class OpsDatasetRunHistory(BaseModel):
    """선택한 exact logical scope의 canonical 실행 이력 첫 page."""

    model_config = ConfigDict(extra="forbid")

    items: list[OpsDatasetExecution]
    next_cursor: str | None
    canonical_url: str = Field(
        description="cursor를 제외한 exact-scope pipeline 실행 이력 URL."
    )


class OpsDatasetEventHistory(BaseModel):
    """선택한 exact effective scope의 event 이력 첫 page."""

    model_config = ConfigDict(extra="forbid")

    items: list[OpsDatasetEventRecord]
    next_cursor: str | None
    canonical_url: str = Field(
        description="cursor를 제외한 exact-scope pipeline event 이력 URL."
    )


class OpsDatasetDetailData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider_dataset_id: int = Field(ge=1)
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
    latest_execution: OpsDatasetExecution | None = Field(
        description="선택 scope에서 가장 최근에 끝난 canonical operation."
    )
    active_execution: OpsDatasetExecution | None = Field(
        description="선택 scope에서 현재 queued/running인 canonical operation."
    )
    execution_coverage: Literal["db_recorded_canonical_operations"] = Field(
        description="DB에 영속된 exact pair canonical operation 이력.",
    )
    run_history: OpsDatasetRunHistory
    event_history: OpsDatasetEventHistory
    dataset_issues: OpsIssueSummary


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

    provider_dataset_id: int = Field(ge=1)
    sync_scope: str
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
