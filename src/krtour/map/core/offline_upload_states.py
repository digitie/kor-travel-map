"""Offline upload 상태/포맷 계약.

라우터, repository, load/validation orchestration이 같은 상태 집합을 공유한다.
``cancelled``는 DB/종료 상태로 예약되어 있지만, 현재 admin API에는 offline upload
cancel producer가 없다.
"""

from __future__ import annotations

from typing import Final, Literal

__all__ = [
    "OfflineUploadState",
    "OFFLINE_UPLOAD_STATE_VALUES",
    "OFFLINE_UPLOAD_STATES",
    "OFFLINE_UPLOAD_DELETABLE_STATES",
    "OFFLINE_UPLOAD_IN_PROGRESS_STATES",
    "OFFLINE_UPLOAD_LOADABLE_STATES",
    "OFFLINE_UPLOAD_LOAD_FINISH_STATES",
    "OFFLINE_UPLOAD_LOAD_FINISH_SOURCE_STATES",
    "OFFLINE_UPLOAD_RESERVED_STATES",
    "OFFLINE_UPLOAD_TABULAR_FORMATS",
    "OFFLINE_UPLOAD_TABULAR_LOADABLE_STATES",
    "OFFLINE_UPLOAD_VALIDATABLE_STATES",
    "OFFLINE_UPLOAD_VALIDATION_FINISH_SOURCE_STATES",
    "OFFLINE_UPLOAD_VALIDATION_FINISH_STATES",
    "OFFLINE_UPLOAD_WRITEABLE_FORMATS",
]

OfflineUploadState = Literal[
    "uploaded",
    "validating",
    "validated",
    "validation_failed",
    "loading",
    "loaded",
    "load_failed",
    "cancelled",
]

OFFLINE_UPLOAD_STATE_VALUES: Final[tuple[OfflineUploadState, ...]] = (
    "uploaded",
    "validating",
    "validated",
    "validation_failed",
    "loading",
    "loaded",
    "load_failed",
    "cancelled",
)
OFFLINE_UPLOAD_STATES: Final[frozenset[OfflineUploadState]] = frozenset(OFFLINE_UPLOAD_STATE_VALUES)
OFFLINE_UPLOAD_VALIDATABLE_STATES: Final[frozenset[OfflineUploadState]] = frozenset(
    {"uploaded", "validated", "validation_failed", "load_failed"}
)
OFFLINE_UPLOAD_VALIDATION_FINISH_STATES: Final[frozenset[OfflineUploadState]] = frozenset(
    {"validated", "validation_failed"}
)
OFFLINE_UPLOAD_VALIDATION_FINISH_SOURCE_STATES: Final[frozenset[OfflineUploadState]] = frozenset(
    {"validating"}
)
OFFLINE_UPLOAD_LOADABLE_STATES: Final[frozenset[OfflineUploadState]] = frozenset(
    {"uploaded", "validated", "load_failed"}
)
OFFLINE_UPLOAD_TABULAR_LOADABLE_STATES: Final[frozenset[OfflineUploadState]] = frozenset(
    {"validated", "load_failed"}
)
OFFLINE_UPLOAD_LOAD_FINISH_STATES: Final[frozenset[OfflineUploadState]] = frozenset(
    {"loaded", "load_failed", "cancelled"}
)
OFFLINE_UPLOAD_LOAD_FINISH_SOURCE_STATES: Final[frozenset[OfflineUploadState]] = frozenset(
    {"loading"}
)
OFFLINE_UPLOAD_RESERVED_STATES: Final[frozenset[OfflineUploadState]] = frozenset({"cancelled"})
OFFLINE_UPLOAD_IN_PROGRESS_STATES: Final[frozenset[OfflineUploadState]] = frozenset(
    {"validating", "loading"}
)
OFFLINE_UPLOAD_DELETABLE_STATES: Final[frozenset[OfflineUploadState]] = (
    OFFLINE_UPLOAD_STATES - OFFLINE_UPLOAD_IN_PROGRESS_STATES
)

OFFLINE_UPLOAD_TABULAR_FORMATS: Final[frozenset[str]] = frozenset({"csv", "tsv"})
OFFLINE_UPLOAD_WRITEABLE_FORMATS: Final[frozenset[str]] = frozenset(
    {"json", "jsonl", *OFFLINE_UPLOAD_TABULAR_FORMATS}
)
