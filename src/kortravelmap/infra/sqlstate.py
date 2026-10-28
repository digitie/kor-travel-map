"""SQLAlchemy/asyncpg 예외 사슬에서 PostgreSQL SQLSTATE를 꺼내는 **단일** 판별기(434 WI-2).

55P03(lock timeout)·40001(serialization) 같은 재시도 판정이 경로마다
``getattr(exc.orig, "sqlstate")``·제각각의 사슬 탐색으로 갈라져 있었다. 번역된 예외의 ``orig``만
보면 driver가 원인을 ``__cause__``에 둔 경우를 놓친다. 이 함수 하나로 통일한다.
"""

from __future__ import annotations

__all__ = ["LOCK_NOT_AVAILABLE", "sqlstate_of"]

LOCK_NOT_AVAILABLE = "55P03"
"""``lock_timeout``이 끝난 잠금 대기(SQLSTATE 55P03)."""


def sqlstate_of(error: BaseException) -> str | None:
    """SQLAlchemy/asyncpg wrapper chain에서 PostgreSQL SQLSTATE를 찾는다.

    명시적 연결(``orig``·``raise ... from``)만 따른다 — ``__context__``는 처리 중에 우연히
    겹친 다른 예외일 수 있다.
    """

    current: BaseException | None = error
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        for candidate in (
            current,
            getattr(current, "orig", None),
            getattr(current, "__cause__", None),
        ):
            if candidate is None:
                continue
            value = getattr(candidate, "sqlstate", None) or getattr(candidate, "pgcode", None)
            if value is not None:
                return str(value)
        current = getattr(current, "orig", None) or getattr(current, "__cause__", None)
    return None
