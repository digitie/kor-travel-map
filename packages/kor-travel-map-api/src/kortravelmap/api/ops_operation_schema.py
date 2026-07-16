"""Admin ops에서 공유하는 canonical operation 상태 계약."""

from __future__ import annotations

from typing import Literal, TypeAlias

OperationState: TypeAlias = Literal[
    "queued",
    "running",
    "done",
    "failed",
    "cancelled",
]

__all__ = ["OperationState"]
