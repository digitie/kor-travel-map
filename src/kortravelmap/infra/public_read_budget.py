"""공개 읽기 요청의 마감 예산 (읽기 성능 계획 T-READ-03).

API의 공개 읽기 의존성(``api/db.py``의 ``get_public_read_session`` 계열)이 요청 도착 시각에서 센
monotonic 마감을 ``session.info[PUBLIC_READ_DEADLINE_INFO_KEY]``에 싣는다. 이 모듈은 그 마감에서
남은 시간을 **문장 상한**(``statement_timeout``, transaction 범위 ``set_config``)으로 넘긴다.

- 마감은 세션에 싣는다. ContextVar를 쓰지 않는다 — ADR-112의 ``transaction_limits._DEADLINE``을
  재사용하면 공개 요청 안의 client 호출에 ADR-112의 여유 3초·바닥 1초가 걸린다.
- ``session.info``에 마감이 없으면 아무것도 하지 않는다 — Dagster·CLI·admin 호출자는 그대로다.
- 남은 시간이 여유(0.3초) 이하이면 SQL을 보내지 않고 ``ReadBudgetExceeded``를 올린다. API가 그것을
  503 ``READ_TIMEOUT``으로 바꾼다.
- 문장 상한 = 남은 시간 − 0.3초, 바닥 250 ms(0은 PostgreSQL에서 "상한 없음"이다).

ADR-112의 ``apply_transaction_limits``와 그 상수는 바꾸지 않는다.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Final

from sqlalchemy import text

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = [
    "PUBLIC_READ_DEADLINE_INFO_KEY",
    "ReadBudgetExceeded",
    "apply_public_read_budget",
    "public_read_deadline",
    "public_read_statement_timeout_ms",
]

PUBLIC_READ_DEADLINE_INFO_KEY: Final[str] = "public_read_deadline"
"""``AsyncSession.info``의 key. 값은 ``time.monotonic()`` 기준 절대 마감(초)."""

_STATEMENT_MARGIN_SECONDS: Final[float] = 0.3
"""문장 상한 = 남은 시간 − 0.3초. 취소 응답과 503 직렬화가 돌아올 여유."""
_STATEMENT_FLOOR_MS: Final[int] = 250


class ReadBudgetExceeded(Exception):
    """공개 읽기 요청의 마감이 지났거나 여유 이하만 남았다."""


def public_read_deadline(session: AsyncSession) -> float | None:
    """세션에 실린 마감. 없으면 ``None``(``info``가 없는 세션 대역도 ``None``)."""
    info = getattr(session, "info", None)
    if not isinstance(info, dict):
        return None
    value = info.get(PUBLIC_READ_DEADLINE_INFO_KEY)
    return value if isinstance(value, float) else None


def public_read_statement_timeout_ms(session: AsyncSession) -> int | None:
    """지금 남은 시간에서 유도한 문장 상한(ms). 마감이 없으면 ``None``.

    여유 이하만 남았으면 ``ReadBudgetExceeded``를 올린다(SQL을 보내기 전이다).
    """
    deadline = public_read_deadline(session)
    if deadline is None:
        return None
    remaining = deadline - time.monotonic()
    if remaining <= _STATEMENT_MARGIN_SECONDS:
        raise ReadBudgetExceeded
    return max(_STATEMENT_FLOOR_MS, int((remaining - _STATEMENT_MARGIN_SECONDS) * 1000))


async def apply_public_read_budget(session: AsyncSession) -> int | None:
    """남은 시간을 이 transaction의 ``statement_timeout``으로 건다. 마감이 없으면 no-op."""
    timeout_ms = public_read_statement_timeout_ms(session)
    if timeout_ms is None:
        return None
    await session.execute(
        text("SELECT set_config('statement_timeout', :timeout, true)"),
        {"timeout": f"{timeout_ms}ms"},
    )
    return timeout_ms
