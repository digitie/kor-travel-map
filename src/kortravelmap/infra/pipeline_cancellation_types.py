"""Pipeline cancellation repository가 공유하는 immutable record와 오류."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from kortravelmap.core.pipeline_cancellation_states import (
    PipelineCancellationResult,
    PipelineCancellationRootKind,
    PipelineCancellationStatus,
)


@dataclass(frozen=True)
class PipelineCancellationSummary:
    """목록 root에 붙는 current cancellation DB overlay."""

    cancellation_id: str
    status: PipelineCancellationStatus
    requested_at: datetime
    requested_by: str
    reason: str | None
    retryable: bool
    unresolved_member_count: int


@dataclass(frozen=True)
class PipelineCancellationAttempt:
    """``ops.pipeline_cancellations`` attempt 1행."""

    cancellation_id: str
    previous_cancellation_id: str | None
    root_kind: PipelineCancellationRootKind
    root_id: str
    status: PipelineCancellationStatus
    requested_by: str
    reason: str | None
    error: dict[str, Any] | None
    requested_at: datetime
    updated_at: datetime
    finished_at: datetime | None

    @property
    def retryable(self) -> bool:
        return self.status == "retryable"


@dataclass(frozen=True)
class PipelineCancellationMember:
    """frozen import job 대상과 대상별 결과."""

    cancellation_id: str
    job_id: str
    dagster_run_id: str | None
    initial_status: str
    result: PipelineCancellationResult
    terminal_status: str | None
    error: dict[str, Any] | None
    updated_at: datetime
    operation_kind: str | None = None
    requires_run_termination: bool = False


@dataclass(frozen=True)
class PipelineCancellationRun:
    """attempt당 한 번만 처리할 Dagster run."""

    cancellation_id: str
    dagster_run_id: str
    initial_status: str | None
    termination_reserved_at: datetime | None
    result: PipelineCancellationResult
    terminal_status: str | None
    error: dict[str, Any] | None
    updated_at: datetime
    engine_started_at: datetime | None = None
    engine_finished_at: datetime | None = None


@dataclass(frozen=True)
class PipelineCancellationDetail:
    """reload 가능한 current attempt + member/run 전체 결과."""

    attempt: PipelineCancellationAttempt
    members: tuple[PipelineCancellationMember, ...]
    runs: tuple[PipelineCancellationRun, ...]

    @property
    def unresolved_member_count(self) -> int:
        return sum(
            member.result in {"pending", "cancel_failed"}
            for member in self.members
        )


@dataclass(frozen=True)
class PipelineCancellationScopeMember:
    """marker 직전 C3b parity scope의 import job snapshot."""

    job_id: str
    initial_status: str
    dagster_run_id: str | None
    cancellation_id: str | None
    operation_kind: str | None = None
    current_stage: str | None = None

    @property
    def active(self) -> bool:
        return self.initial_status in {"queued", "running"}

    @property
    def requires_run_termination(self) -> bool:
        return self.dagster_run_id is not None and (
            self.initial_status == "running"
            or (
                self.initial_status == "queued"
                and self.operation_kind
                in {"provider_feature_load_run", "provider_feature_load"}
            )
        )


@dataclass(frozen=True)
class PipelineCancellationScope:
    """canonical root와 deterministic frozen member 목록."""

    root_kind: PipelineCancellationRootKind
    root_id: str
    members: tuple[PipelineCancellationScopeMember, ...]

    @property
    def active_members(self) -> tuple[PipelineCancellationScopeMember, ...]:
        return tuple(member for member in self.members if member.active)


class PipelineCancellationConflict(RuntimeError):
    """marker 또는 current attempt CAS가 더 이상 일치하지 않는다."""


class PipelineCancellationInvariantError(RuntimeError):
    """attempt workflow/result 불변식을 만족하지 않는다."""


class PipelineCancellationTimelineConflict(PipelineCancellationInvariantError):
    """Dagster terminal 시간이 frozen canonical operation timeline과 충돌한다."""
