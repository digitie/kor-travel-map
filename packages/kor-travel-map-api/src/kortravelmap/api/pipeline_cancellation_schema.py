"""Pipeline 계층형 취소의 공용 HTTP DTO와 DB record mapper."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Self

from kortravelmap.infra.pipeline_cancellation_types import (
    PipelineCancellationDetail,
    PipelineCancellationSummary,
)
from pydantic import BaseModel, ConfigDict, Field, model_validator

from kortravelmap.api.response import Meta

__all__ = [
    "PipelineCancellationDetailRecord",
    "PipelineCancellationErrorRecord",
    "PipelineCancellationMemberRecord",
    "PipelineCancellationRequest",
    "PipelineCancellationResponse",
    "PipelineCancellationRootRecord",
    "PipelineCancellationRunRecord",
    "PipelineCancellationSummaryRecord",
    "cancellation_detail_record",
    "cancellation_summary_record",
]

PipelineCancellationStatus = Literal[
    "in_progress",
    "retryable",
    "completed",
    "failed",
]
PipelineCancellationResult = Literal[
    "pending",
    "cancelled",
    "already_terminal",
    "cancel_failed",
]
PipelineCancellationMemberKind = Literal["import_job", "update_request"]

_COMMITTED_DATA_WARNING = (
    "이미 commit된 scope 데이터와 외부 provider 효과는 rollback하지 않습니다."
)


class PipelineCancellationRequest(BaseModel):
    """취소 action body — actor는 인증 context에서만 파생한다."""

    model_config = ConfigDict(extra="forbid")

    reason: str | None = Field(default=None, max_length=500)


class PipelineCancellationErrorRecord(BaseModel):
    """upstream raw body/stack을 제외한 영속 가능 오류."""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    details: dict[str, Any] | None = None


class PipelineCancellationRootRecord(BaseModel):
    """canonical cancellation root."""

    model_config = ConfigDict(extra="forbid")

    kind: PipelineCancellationMemberKind
    id: str


class PipelineCancellationSummaryRecord(BaseModel):
    """실행 목록 root에 붙는 current cancellation overlay."""

    model_config = ConfigDict(extra="forbid")

    cancellation_id: str
    status: PipelineCancellationStatus
    requested_at: datetime
    requested_by: str
    reason: str | None
    retryable: bool
    unresolved_member_count: int = Field(ge=0)


class PipelineCancellationMemberRecord(BaseModel):
    """frozen base member와 대상별 결과."""

    model_config = ConfigDict(extra="forbid")

    member_kind: PipelineCancellationMemberKind
    member_id: str
    dagster_run_id: str | None
    initial_status: str
    result: PipelineCancellationResult
    terminal_status: str | None
    error: PipelineCancellationErrorRecord | None
    updated_at: datetime


class PipelineCancellationRunRecord(BaseModel):
    """attempt당 하나인 Dagster run terminate 결과."""

    model_config = ConfigDict(extra="forbid")

    dagster_run_id: str
    initial_status: str | None
    termination_reserved_at: datetime | None
    result: PipelineCancellationResult
    terminal_status: str | None
    error: PipelineCancellationErrorRecord | None
    updated_at: datetime


class PipelineCancellationDetailRecord(BaseModel):
    """POST 결과와 GET detail이 공유하는 reload 가능한 cancellation 표현."""

    model_config = ConfigDict(extra="forbid")

    cancellation_id: str
    previous_cancellation_id: str | None
    root: PipelineCancellationRootRecord
    status: PipelineCancellationStatus
    requested_at: datetime
    requested_by: str
    reason: str | None
    error: PipelineCancellationErrorRecord | None
    updated_at: datetime
    finished_at: datetime | None
    retryable: bool
    unresolved_member_count: int = Field(ge=0)
    members: list[PipelineCancellationMemberRecord]
    dagster_runs: list[PipelineCancellationRunRecord]
    committed_data_rolled_back: Literal[False] = False
    warnings: list[str] = Field(default_factory=lambda: [_COMMITTED_DATA_WARNING])

    @model_validator(mode="after")
    def completed_has_no_unresolved_result(self) -> Self:
        """200/reload completed 표현이 pending/cancel_failed를 숨기지 못하게 한다."""
        unresolved = {"pending", "cancel_failed"}
        unresolved_count = sum(
            member.result in unresolved for member in self.members
        )
        if self.unresolved_member_count != unresolved_count:
            raise ValueError(
                "unresolved_member_count must match unresolved cancellation members"
            )
        if self.retryable != (self.status == "retryable"):
            raise ValueError("retryable must match cancellation status")
        if self.status != "completed":
            return self
        if any(member.result in unresolved for member in self.members) or any(
            run.result in unresolved for run in self.dagster_runs
        ):
            raise ValueError("completed cancellation cannot contain unresolved results")
        return self


class PipelineCancellationResponse(BaseModel):
    """모든 pipeline cancellation action이 공유하는 성공 envelope."""

    model_config = ConfigDict(extra="forbid")

    data: PipelineCancellationDetailRecord
    meta: Meta


def _error_record(value: dict[str, Any] | None) -> PipelineCancellationErrorRecord | None:
    if value is None:
        return None
    return PipelineCancellationErrorRecord.model_validate(value)


def cancellation_summary_record(
    summary: PipelineCancellationSummary | None,
) -> PipelineCancellationSummaryRecord | None:
    """DB summary를 base status와 독립인 nullable HTTP overlay로 바꾼다."""
    if summary is None:
        return None
    return PipelineCancellationSummaryRecord(
        cancellation_id=summary.cancellation_id,
        status=summary.status,
        requested_at=summary.requested_at,
        requested_by=summary.requested_by,
        reason=summary.reason,
        retryable=summary.retryable,
        unresolved_member_count=summary.unresolved_member_count,
    )


def cancellation_detail_record(
    detail: PipelineCancellationDetail | None,
) -> PipelineCancellationDetailRecord | None:
    """정규화 attempt/member/run을 공용 HTTP detail로 변환한다."""
    if detail is None:
        return None
    attempt = detail.attempt
    return PipelineCancellationDetailRecord(
        cancellation_id=attempt.cancellation_id,
        previous_cancellation_id=attempt.previous_cancellation_id,
        root=PipelineCancellationRootRecord(
            kind=attempt.root_kind,
            id=attempt.root_id,
        ),
        status=attempt.status,
        requested_at=attempt.requested_at,
        requested_by=attempt.requested_by,
        reason=attempt.reason,
        error=_error_record(attempt.error),
        updated_at=attempt.updated_at,
        finished_at=attempt.finished_at,
        retryable=attempt.retryable,
        unresolved_member_count=detail.unresolved_member_count,
        members=[
            PipelineCancellationMemberRecord(
                member_kind=member.member_kind,
                member_id=member.member_id,
                dagster_run_id=member.dagster_run_id,
                initial_status=member.initial_status,
                result=member.result,
                terminal_status=member.terminal_status,
                error=_error_record(member.error),
                updated_at=member.updated_at,
            )
            for member in detail.members
        ],
        dagster_runs=[
            PipelineCancellationRunRecord(
                dagster_run_id=run.dagster_run_id,
                initial_status=run.initial_status,
                termination_reserved_at=run.termination_reserved_at,
                result=run.result,
                terminal_status=run.terminal_status,
                error=_error_record(run.error),
                updated_at=run.updated_at,
            )
            for run in detail.runs
        ],
    )
