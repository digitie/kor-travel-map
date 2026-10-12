"""Dagster provider feature operation의 main-package 불변 계약."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, TypeAlias

from kortravelmap.core.sync_scope import parse_canonical_sync_scope

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

DEDICATED_JOB_ONLY_OPERATION_KEYS: frozenset[str] = frozenset(
    {"feature_place_mois_licenses_job"}
)
"""feature update 큐로는 실행하지 않고 **전용 Dagster job으로만** 도는 operation (ADR-108).

큐 runner는 provider 쓰기를 executor transaction 하나에 묶는다. MOIS 재개형 적재는 chunk마다
commit해야 성립하므로 큐로는 돌 수 없다. 이 집합이 API enqueue 거부, 실행 계획의 skip 사유,
Dagster 큐 runner의 방어 skip이 함께 읽는 단일 정본이다.
"""

DEDICATED_JOB_ONLY_SKIP_REASON = "dedicated_job_only"
"""실행 계획이 위 operation을 건너뛸 때 ``skipped_provider_scopes[].reason`` 값."""
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


@dataclass(frozen=True, order=True)
class ProviderDatasetOperationMembership:
    """Dagster operation이 실행하는 immutable canonical dataset scope."""

    provider_dataset_id: int
    sync_scope: str
    operation_key: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.provider_dataset_id, int)
            or isinstance(self.provider_dataset_id, bool)
            or self.provider_dataset_id <= 0
        ):
            raise ValueError("provider_dataset_id must be a positive integer")
        parse_canonical_sync_scope(self.sync_scope)
        if (
            not isinstance(self.operation_key, str)
            or not self.operation_key
            or self.operation_key != self.operation_key.strip()
        ):
            raise ValueError("operation_key must be trimmed and non-empty")


@dataclass(frozen=True)
class DagsterFeatureOperationMember:
    job_id: str
    import_job_dataset_id: str
    membership: ProviderDatasetOperationMembership
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
    operation_key: str
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
    "DEDICATED_JOB_ONLY_OPERATION_KEYS",
    "DEDICATED_JOB_ONLY_SKIP_REASON",
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
    "ProviderDatasetOperationMembership",
    "TriggerKind",
]
