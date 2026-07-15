"""Pipeline 계층형 취소의 workflow/result 상태 정본 (ADR-064, T-ADM-C3d)."""

from __future__ import annotations

from typing import Literal, TypeAlias

PipelineCancellationStatus: TypeAlias = Literal[
    "in_progress",
    "retryable",
    "completed",
    "failed",
]
PipelineCancellationResult: TypeAlias = Literal[
    "pending",
    "cancelled",
    "already_terminal",
    "cancel_failed",
]
PipelineCancellationRootKind: TypeAlias = Literal["import_job", "update_request"]

PIPELINE_CANCELLATION_STATUS_VALUES: tuple[PipelineCancellationStatus, ...] = (
    "in_progress",
    "retryable",
    "completed",
    "failed",
)
PIPELINE_CANCELLATION_RESULT_VALUES: tuple[PipelineCancellationResult, ...] = (
    "pending",
    "cancelled",
    "already_terminal",
    "cancel_failed",
)
PIPELINE_CANCELLATION_ROOT_KIND_VALUES: tuple[
    PipelineCancellationRootKind, ...
] = ("import_job", "update_request")

__all__ = [
    "PIPELINE_CANCELLATION_ROOT_KIND_VALUES",
    "PIPELINE_CANCELLATION_RESULT_VALUES",
    "PIPELINE_CANCELLATION_STATUS_VALUES",
    "PipelineCancellationRootKind",
    "PipelineCancellationResult",
    "PipelineCancellationStatus",
]
