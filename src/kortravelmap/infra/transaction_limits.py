"""트랜잭션별 서버 쪽 상한 (ADR-112 결정 2).

호출자가 ``transaction_deadline``(또는 ``connection_check_interval``)으로 구간을 감싸면, 그 안에서
client가 여는 트랜잭션마다 ``apply_transaction_limits``가 ``set_config(..., true)``(트랜잭션
범위)로 서버 쪽 상한을 건다.

- ``statement_timeout`` = 마감까지 남은 시간 − 3초, ``lock_timeout`` = min(5초, 남은 시간 − 4초)
  (5초 상한은 2026-10-21 소유자 결정 — odroid tenant와 같은 값).
  시간이 넘으면 **Postgres가 statement를 취소**한다(57014 / 55P03). client 쪽 ``asyncio.timeout``은
  그 뒤를 받치는 보조 장치일 뿐이다.
- ``client_connection_check_interval`` — 연결 저편(worker)이 죽었을 때 서버가 그 statement를
  스스로 취소하게 한다(completion sweep이 쓴다).

SERIALIZABLE 트랜잭션에서는 ``SET TRANSACTION ISOLATION LEVEL`` **다음에** 불러야 한다. 그보다
먼저 쿼리를 보내면 isolation 문이 25001로 거부된다.

마감이 걸려 있지 않으면 아무것도 하지 않는다 — API·run 같은 기존 호출자의 동작은 그대로다.
트랜잭션과 domain SQL은 소비자(Map)의 몫이라 이 모듈은 Map에 둔다.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from sqlalchemy import text

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = [
    "TransactionBudget",
    "apply_transaction_limits",
    "connection_check_interval",
    "current_transaction_budget",
    "remaining_seconds",
    "transaction_deadline",
]

_STATEMENT_MARGIN_SECONDS: Final[float] = 3.0
"""statement_timeout = 남은 시간 − 3초. 취소 응답이 돌아올 여유."""
_LOCK_MARGIN_SECONDS: Final[float] = 4.0
"""lock_timeout = min(상한, 남은 시간 − 4초). lock 대기가 statement보다 먼저 끝난다."""
_LOCK_TIMEOUT_CAP_SECONDS: Final[float] = 5.0
"""lock_timeout 상한(ADR-112 결정 2, 2026-10-21 소유자 결정).

lock 하나를 5초 넘게 기다리지 않고 다음 tick에 다시 한다 — odroid tenant(geo·weather·transport)와
같은 값이다."""
_MIN_STATEMENT_SECONDS: Final[float] = 1.0
_MIN_LOCK_SECONDS: Final[float] = 0.5
"""바닥값. 0은 Postgres에서 '상한 없음'이라 절대 그 값이 되지 않게 한다."""

_DEADLINE: ContextVar[float | None] = ContextVar("kortravelmap_transaction_deadline", default=None)
_CONNECTION_CHECK: ContextVar[int | None] = ContextVar(
    "kortravelmap_connection_check_interval", default=None
)


@contextmanager
def transaction_deadline(deadline: float) -> Iterator[None]:
    """이 구간에서 여는 트랜잭션의 마감을 ``time.monotonic()`` 기준 절대 시각으로 정한다.

    이미 더 이른 마감이 걸려 있으면 그쪽을 지킨다(안쪽이 바깥보다 늦을 수 없다).
    """
    outer = _DEADLINE.get()
    token = _DEADLINE.set(deadline if outer is None else min(outer, deadline))
    try:
        yield
    finally:
        _DEADLINE.reset(token)


@contextmanager
def connection_check_interval(seconds: int) -> Iterator[None]:
    """이 구간의 트랜잭션에 ``client_connection_check_interval``을 건다."""
    if isinstance(seconds, bool) or not isinstance(seconds, int) or seconds < 1:
        raise ValueError("connection check interval must be a positive integer of seconds")
    token = _CONNECTION_CHECK.set(seconds)
    try:
        yield
    finally:
        _CONNECTION_CHECK.reset(token)


def remaining_seconds() -> float | None:
    """걸린 마감까지 남은 초. 마감이 없으면 ``None``."""
    deadline = _DEADLINE.get()
    if deadline is None:
        return None
    return deadline - time.monotonic()


@dataclass(frozen=True)
class TransactionBudget:
    """트랜잭션 하나에 거는 서버 쪽 상한(밀리초)."""

    statement_timeout_ms: int
    lock_timeout_ms: int

    @classmethod
    def from_remaining(cls, remaining: float) -> TransactionBudget:
        statement = max(_MIN_STATEMENT_SECONDS, remaining - _STATEMENT_MARGIN_SECONDS)
        lock = max(
            _MIN_LOCK_SECONDS,
            min(_LOCK_TIMEOUT_CAP_SECONDS, remaining - _LOCK_MARGIN_SECONDS),
        )
        return cls(statement_timeout_ms=int(statement * 1000), lock_timeout_ms=int(lock * 1000))


def current_transaction_budget() -> TransactionBudget | None:
    """지금 걸린 마감에서 유도한 상한. 마감이 없으면 ``None``."""
    remaining = remaining_seconds()
    return None if remaining is None else TransactionBudget.from_remaining(remaining)


async def apply_transaction_limits(session: AsyncSession) -> TransactionBudget | None:
    """걸린 구간 설정을 이 트랜잭션에 건다(트랜잭션 범위 ``set_config``).

    트랜잭션을 연 직후, SERIALIZABLE이면 isolation 문 **다음**에 부른다. 걸린 것이 없으면 DB에
    아무것도 보내지 않는다.
    """
    budget = current_transaction_budget()
    check = _CONNECTION_CHECK.get()
    if budget is not None:
        await session.execute(
            text(
                "SELECT set_config('statement_timeout', :statement, true), "
                "set_config('lock_timeout', :lock, true)"
            ),
            {
                "statement": f"{budget.statement_timeout_ms}ms",
                "lock": f"{budget.lock_timeout_ms}ms",
            },
        )
    if check is not None:
        await session.execute(
            text("SELECT set_config('client_connection_check_interval', :interval, true)"),
            {"interval": f"{check}s"},
        )
    return budget


async def apply_bounded_transaction_limits(
    session: AsyncSession,
    *,
    statement_timeout_ms: int = 30_000,
    lock_timeout_ms: int = 1_000,
) -> None:
    """작은 복구 TX는 기존 GUC·호출자 마감·고정 상한 중 가장 짧은 값을 보존한다."""
    caps = (statement_timeout_ms, lock_timeout_ms)
    if any(type(value) is not int or value < 1 for value in caps):
        raise ValueError("bounded transaction limits require positive integer milliseconds")
    budget = current_transaction_budget()
    statement = statement_timeout_ms
    lock = lock_timeout_ms
    if budget is not None:
        statement = min(statement, budget.statement_timeout_ms)
        lock = min(lock, budget.lock_timeout_ms)
    await session.execute(
        text("""SELECT set_config(name,
            LEAST(COALESCE(NULLIF(setting::bigint,0),cap),cap)::text,true)
            FROM pg_settings JOIN (VALUES ('statement_timeout',CAST(:statement AS bigint)),
            ('lock_timeout',CAST(:lock AS bigint))) caps(name,cap) USING(name)"""),
        {"statement": statement, "lock": lock},
    )
    check = _CONNECTION_CHECK.get()
    if check is not None:
        await session.execute(
            text("""SELECT set_config(name,
                LEAST(COALESCE(NULLIF(setting::bigint,0),:interval),:interval)::text,true)
                FROM pg_settings WHERE name='client_connection_check_interval'"""),
            {"interval": check * 1000},
        )
