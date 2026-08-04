"""cache-target writer drain lease의 작은 상태 집합.

상태 문자열은 migration/DB check와 private API image command가 함께 쓰는 정본이다.
외부 REST 계약에는 노출하지 않는다.
"""

from __future__ import annotations

from typing import Final

WRITER_DRAIN_OWNER_KINDS: Final[tuple[str, ...]] = ("diagnostic", "cutover")
WRITER_DRAIN_LEASE_STATES: Final[tuple[str, ...]] = (
    "draining",
    "drained",
    "restoring",
    "restored",
)
WRITER_DRAIN_ACTIVE_STATES: Final[tuple[str, ...]] = (
    "draining",
    "drained",
    "restoring",
)
WRITER_DRAIN_RECEIPT_OPERATIONS: Final[tuple[str, ...]] = (
    "begin",
    "attest",
    "restore",
)
WRITER_DRAIN_INSTIGATION_KINDS: Final[tuple[str, ...]] = ("schedule", "sensor")
WRITER_DRAIN_PAUSE_RESULTS: Final[tuple[str, ...]] = (
    "pending",
    "paused",
    "already_stopped",
    "not_required",
)
WRITER_DRAIN_RESTORE_RESULTS: Final[tuple[str, ...]] = (
    "not_requested",
    "restored",
    "already_running",
)
WRITER_DRAIN_CANCEL_RESULTS: Final[tuple[str, ...]] = (
    "pending",
    "reserved",
    "dispatched",
    "terminal",
    "outcome_uncertain",
)
