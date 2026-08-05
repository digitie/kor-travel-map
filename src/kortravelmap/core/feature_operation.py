"""Dagster provider feature operation의 main-package 불변 계약."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, TypeAlias

ExecutionState: TypeAlias = Literal["queued", "running", "done", "failed", "cancelled"]
TriggerKind: TypeAlias = Literal[
    "schedule", "manual", "sensor", "update_request", "backfill", "system"
]
DagsterFeatureRunStatus: TypeAlias = Literal[
    "QUEUED",
    "NOT_STARTED",
    "MANAGED",
    "STARTING",
    "STARTED",
    "CANCELING",
    "SUCCESS",
    "FAILURE",
    "CANCELED",
]
DagsterFeatureOperationOutcome: TypeAlias = Literal["applied", "noop", "blocked"]
DagsterFeatureOperationBlockReason: TypeAlias = Literal["cancellation", "terminal"]

FEATURE_OPERATION_ROOT_KIND = "provider_feature_load_run"
FEATURE_OPERATION_MEMBER_KIND = "provider_feature_load"
FEATURE_UPDATE_REQUEST_JOB_KIND = "feature_update_request"
C6C_CANCEL_PROBE_JOB_KIND = "c6c_cancel_probe"
FEATURE_OPERATION_RESERVED_KINDS = frozenset(
    {
        FEATURE_OPERATION_ROOT_KIND,
        FEATURE_OPERATION_MEMBER_KIND,
    }
)
TRIGGER_KIND_VALUES: tuple[TriggerKind, ...] = (
    "schedule",
    "manual",
    "sensor",
    "update_request",
    "backfill",
    "system",
)
DAGSTER_FEATURE_RUN_STATUS_VALUES: tuple[DagsterFeatureRunStatus, ...] = (
    "QUEUED",
    "NOT_STARTED",
    "MANAGED",
    "STARTING",
    "STARTED",
    "CANCELING",
    "SUCCESS",
    "FAILURE",
    "CANCELED",
)
DAGSTER_FEATURE_ACTIVE_STATUS_VALUES = frozenset(
    {"QUEUED", "NOT_STARTED", "MANAGED", "STARTING", "STARTED", "CANCELING"}
)
DAGSTER_FEATURE_TERMINAL_STATUS_VALUES = frozenset({"SUCCESS", "FAILURE", "CANCELED"})


@dataclass(frozen=True, order=True)
class ProviderDatasetOperationKey:
    """trim된 exact provider/dataset identity."""

    provider: str
    dataset_key: str

    def __post_init__(self) -> None:
        if not self.provider or self.provider != self.provider.strip():
            raise ValueError("provider must be trimmed and non-empty")
        if not self.dataset_key or self.dataset_key != self.dataset_key.strip():
            raise ValueError("dataset_key must be trimmed and non-empty")


@dataclass(frozen=True)
class DagsterFeatureOperationMember:
    job_id: str
    pair: ProviderDatasetOperationKey
    status: ExecutionState
    progress: int
    current_stage: str | None
    started_at: datetime | None
    finished_at: datetime | None


@dataclass(frozen=True)
class DagsterFeatureOperation:
    root_job_id: str
    dagster_run_id: str
    status: ExecutionState
    dagster_run_status: DagsterFeatureRunStatus
    progress: int
    current_stage: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    trigger_kind: TriggerKind
    registry_version: str
    members: tuple[DagsterFeatureOperationMember, ...]


@dataclass(frozen=True)
class DagsterFeatureOperationMutation:
    outcome: DagsterFeatureOperationOutcome
    operation: DagsterFeatureOperation
    block_reason: DagsterFeatureOperationBlockReason | None = None


@dataclass(frozen=True, order=True)
class DagsterFeatureOperationCursor:
    created_at: datetime
    root_job_id: str


@dataclass(frozen=True)
class DagsterFeatureOperationPage:
    items: tuple[DagsterFeatureOperation, ...]
    next_cursor: DagsterFeatureOperationCursor | None


class FeatureOperationInvariantConflict(RuntimeError):
    """run identity/selection 불변식 위반. 부분 mutation은 남기지 않는다."""

    code = "FEATURE_OPERATION_INVARIANT_CONFLICT"

    def __init__(
        self,
        message: str,
        *,
        dagster_run_id: str,
        root_job_id: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.dagster_run_id = dagster_run_id
        self.root_job_id = root_job_id
        self.details = details or {}


__all__ = [
    "DAGSTER_FEATURE_ACTIVE_STATUS_VALUES",
    "DAGSTER_FEATURE_RUN_STATUS_VALUES",
    "DAGSTER_FEATURE_TERMINAL_STATUS_VALUES",
    "C6C_CANCEL_PROBE_JOB_KIND",
    "FEATURE_OPERATION_MEMBER_KIND",
    "FEATURE_OPERATION_RESERVED_KINDS",
    "FEATURE_OPERATION_ROOT_KIND",
    "FEATURE_UPDATE_REQUEST_JOB_KIND",
    "TRIGGER_KIND_VALUES",
    "DagsterFeatureOperation",
    "DagsterFeatureOperationBlockReason",
    "DagsterFeatureOperationCursor",
    "DagsterFeatureOperationMember",
    "DagsterFeatureOperationMutation",
    "DagsterFeatureOperationOutcome",
    "DagsterFeatureOperationPage",
    "DagsterFeatureRunStatus",
    "ExecutionState",
    "FeatureOperationInvariantConflict",
    "ProviderDatasetOperationKey",
    "TriggerKind",
]
