"""재시도 루프의 범용 도구 — ``kor-travel-common``으로 옮겨 갈 자리 (ADR-112).

이 모듈의 이름과 의미는 kor-travel-common에 추가되는 API와 같다.

- ``deadline.call_with_deadline(call, *, timeout_seconds, slots=...)`` / ``DeadlineExceeded``
- ``pg_errors.pg_error_info(exc) -> PgErrorInfo(sqlstate, constraint, message)``
- ``stall.StallClock`` + ``observe_failure`` / ``due_alert`` / ``mark_alerted`` / ``to_dict`` /
  ``from_dict``

common 쪽이 머지되면 이 모듈은 그 import로 바뀐다. Map 도메인(어떤 실패를 닫을 수 있는지, gate
표지, cursor 키, 트랜잭션 SQL)은 여기 두지 않는다 — 그것은 ``feature_operation_sensors``와
``kortravelmap.infra.transaction_limits``의 몫이다.
"""

from __future__ import annotations

import math
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Any, Final, TypeVar

__all__ = [
    "DeadlineExceeded",
    "PgErrorInfo",
    "StallClock",
    "call_with_deadline",
    "due_alert",
    "mark_alerted",
    "observe_failure",
    "pg_error_info",
]

_T = TypeVar("_T")
_DEFAULT_SLOTS: Final = threading.BoundedSemaphore(4)


class DeadlineExceeded(TimeoutError):
    """호출은 아직 살아 있을 수 있다. 소비자는 그 실행을 바로 끝내야 한다."""


def call_with_deadline(
    call: Callable[[], _T],
    *,
    timeout_seconds: float,
    slots: threading.BoundedSemaphore | None = None,
) -> _T:
    """동기 호출을 daemon thread에서 돌리고 기다림만 ``timeout_seconds``로 자른다.

    ``slots``가 다 차 있으면(앞 호출이 아직 돌아오지 않았다) 호출을 시작하지 않고 곧바로
    ``DeadlineExceeded``를 낸다. 시간이 넘은 호출도 실제로 끝날 때까지 slot을 들고 있으므로
    thread가 쌓이지 않는다. thread를 강제로 끝내지는 않는다.
    """
    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be a finite positive number")
    call_slots = slots if slots is not None else _DEFAULT_SLOTS
    if not call_slots.acquire(blocking=False):
        raise DeadlineExceeded("previous bounded call has not returned yet")
    values: list[_T] = []
    errors: list[BaseException] = []

    def invoke() -> None:
        try:
            values.append(call())
        except BaseException as exc:
            errors.append(exc)
        finally:
            call_slots.release()

    worker = threading.Thread(target=invoke, name="bounded-call", daemon=True)
    try:
        worker.start()
    except BaseException:
        call_slots.release()
        raise
    worker.join(timeout_seconds)
    if worker.is_alive():
        raise DeadlineExceeded("bounded call exceeded its deadline")
    if errors:
        raise errors[0]
    return values[0]


@dataclass(frozen=True)
class PgErrorInfo:
    """Postgres가 돌려준 오류 사실. 드라이버 오류가 아니면 셋 다 ``None``이다."""

    sqlstate: str | None
    constraint: str | None
    message: str | None


def pg_error_info(error: BaseException) -> PgErrorInfo:
    """SQLAlchemy 오류의 ``orig``·``__cause__`` 사슬에서 sqlstate·constraint·message를 읽는다.

    asyncpg 오류(``sqlstate``·``constraint_name``·``message``)를 먼저 찾는다. psycopg 계열은
    ``pgcode``·``diag``를 쓴다. 명시적 연결(``orig``·``raise ... from``)만 따라간다 —
    ``__context__``는 처리 중에 우연히 생긴 다른 오류일 수 있다. ``str(exc)``는 읽지 않는다.
    """
    seen: set[int] = set()
    pending: list[BaseException | None] = [error]
    fallback: str | None = None
    while pending:
        current = pending.pop(0)
        if current is None or id(current) in seen:
            continue
        seen.add(id(current))
        sqlstate = getattr(current, "sqlstate", None) or getattr(current, "pgcode", None)
        if isinstance(sqlstate, str) and sqlstate:
            diag = getattr(current, "diag", None)
            constraint = getattr(current, "constraint_name", None)
            message = getattr(current, "message", None)
            if diag is not None:
                constraint = constraint or getattr(diag, "constraint_name", None)
                message = message or getattr(diag, "message_primary", None)
            if isinstance(constraint, str) or isinstance(message, str):
                return PgErrorInfo(
                    sqlstate=sqlstate,
                    constraint=constraint if isinstance(constraint, str) else None,
                    message=message if isinstance(message, str) else None,
                )
            fallback = fallback or sqlstate
        pending.extend((getattr(current, "orig", None), current.__cause__))
    return PgErrorInfo(sqlstate=fallback, constraint=None, message=None)


@dataclass(frozen=True)
class StallClock:
    """한 대상의 멈춤 시계.

    ``first_failed_at``은 처음 본 실패가 **돌아온** 시각이다. 같은 ``key``라면 실패 서명
    (``last_failure``)이 바뀌어도 처음으로 돌아가지 않는다.
    """

    key: str
    first_failed_at: datetime
    last_failure: Mapping[str, Any]
    alerted_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.key or self.key != self.key.strip():
            raise ValueError("stall clock key must be trimmed and non-empty")
        for name in ("first_failed_at", "alerted_at"):
            value = getattr(self, name)
            if value is not None and (value.tzinfo is None or value.utcoffset() is None):
                raise ValueError(f"stall clock {name} must be timezone-aware")

    def to_dict(self) -> dict[str, Any]:
        return {
            "alerted_at": self.alerted_at.isoformat() if self.alerted_at is not None else None,
            "first_failed_at": self.first_failed_at.isoformat(),
            "key": self.key,
            "last_failure": dict(self.last_failure),
        }

    @classmethod
    def from_dict(cls, raw: object) -> StallClock:
        if not isinstance(raw, dict) or set(raw) != {
            "alerted_at",
            "first_failed_at",
            "key",
            "last_failure",
        }:
            raise ValueError("stall clock shape is invalid")
        if not isinstance(raw["key"], str) or not isinstance(raw["last_failure"], dict):
            raise ValueError("stall clock field types are invalid")
        alerted = raw["alerted_at"]
        return cls(
            key=raw["key"],
            first_failed_at=_parse_aware(raw["first_failed_at"]),
            last_failure=raw["last_failure"],
            alerted_at=_parse_aware(alerted) if alerted is not None else None,
        )


def observe_failure(
    clock: StallClock | None,
    *,
    key: str,
    failure: Mapping[str, Any],
    now: datetime,
) -> StallClock:
    """실패 하나를 반영한다. 같은 key면 시작 시각과 알림 시각을 잇고 서명만 바꾼다."""
    if clock is not None and clock.key == key:
        return replace(clock, last_failure=dict(failure))
    return StallClock(key=key, first_failed_at=now, last_failure=dict(failure))


def due_alert(
    clock: StallClock,
    *,
    now: datetime,
    stall_after: float = 900,
    realert_after: float = 3600,
) -> bool:
    """멈춤(``stall_after``초 이상)이고 마지막 알림에서 ``realert_after``초가 지났는가."""
    if now - clock.first_failed_at < timedelta(seconds=stall_after):
        return False
    return clock.alerted_at is None or now - clock.alerted_at >= timedelta(
        seconds=realert_after
    )


def mark_alerted(clock: StallClock, *, now: datetime) -> StallClock:
    return replace(clock, alerted_at=now)


def _parse_aware(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("stall clock time must be an ISO string")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("stall clock time must be timezone-aware")
    return parsed
