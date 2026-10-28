"""잠금을 잡는 **한 문장** 동안만 대기 상한을 늘리는 공통 실행기(T-LOAD-LOCK-WAIT · 434 WI-2).

provider 적재와 권위 membership 완료(finish)는 다른 적재가 P EX를 쥔 동안 기다려야 한다. 엔진의
``lock_timeout``(Dagster 30초)으로는 그 뒤에서 55P03으로 죽는다. 그래서 그 transaction의
**첫 P EX 획득 한 문장**만 상한을 늘리고 곧바로 되돌린다. 같은 transaction의 다른 잠금(행·다른
advisory)은 종전 짧은 상한을 그대로 쓴다.

종전 구현은 현재 ``lock_timeout``이 0(무한)이면 그대로 실행했다. 그런데 protocol gate는 0을
1초로 바꿔 잡으므로 무장한 대기가 오히려 1초로 줄었다(WI-2, A1-02). 이제 0이어도 그 문장 동안만
``wait_ms``로 바꾸고 끝나면 0으로 되돌린다. 이미 ``wait_ms`` 이상인 유한 상한만 그대로 둔다.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, Final

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = [
    "FEATURE_CURATION_WRITE_WAIT_INFO_KEY",
    "execute_with_lock_wait",
    "pop_armed_lock_wait",
]

_LOG = logging.getLogger(__name__)

FEATURE_CURATION_WRITE_WAIT_INFO_KEY: Final[str] = "kortravelmap.feature_curation_write_wait_ms"
"""``session.info`` 키 — 이 transaction이 P EX를 **처음** 잡을 때 기다릴 상한(ms).

provider 적재(``feature-curation-write`` fence)와 권위 finish(tracking 확정 prefix)가 쓴다.
값은 그 transaction의 첫 획득이 꺼내 쓰고 지운다(한 번)."""

_STATEMENT_MARGIN_MS: Final[int] = 60_000
"""긴 대기 동안 ``statement_timeout``을 ``대기 + 이 여유``까지 올린다 — lock 대기가 먼저 끝나
statement 취소(57014)가 아니라 종전과 같은 55P03으로 실패하게."""

_CONNECTION_CHECK_MS: Final[int] = 10_000
"""긴 대기 동안 ``client_connection_check_interval``(꺼져 있을 때만). worker가 죽으면 그
backend가 최대 대기 내내 줄에 남지 않고 10초 안에 빠진다(completion sweep과 같은 값)."""

_SESSION_LOCK_TIMEOUTS_SQL: Final[str] = """
SELECT name, setting
FROM pg_catalog.pg_settings
WHERE name IN ('lock_timeout', 'statement_timeout', 'client_connection_check_interval')
"""

_SET_LOCAL_LOCK_TIMEOUTS_SQL: Final[str] = """
SELECT pg_catalog.set_config('lock_timeout', :lock_timeout, true),
       pg_catalog.set_config('statement_timeout', :statement_timeout, true),
       pg_catalog.set_config(
         'client_connection_check_interval', :client_connection_check_interval, true
       )
"""


def pop_armed_lock_wait(session: AsyncSession) -> int | None:
    """무장된 대기(ms)를 꺼내고 지운다. 무장이 없거나 0이면 ``None``."""
    info = getattr(session, "info", None)
    if not isinstance(info, dict):
        return None
    value = info.pop(FEATURE_CURATION_WRITE_WAIT_INFO_KEY, None)
    return value if isinstance(value, int) and value > 0 else None


async def execute_with_lock_wait(
    session: AsyncSession,
    statement: str,
    wait_ms: int,
    *,
    label: str,
    params: Mapping[str, Any] | None = None,
) -> None:
    """``statement`` 한 문장 동안만 ``lock_timeout``을 ``wait_ms``로 바꿔 실행하고 되돌린다.

    늘리기만 한다 — 이미 ``wait_ms`` 이상인 유한 상한은 그대로 실행한다. 0(무한)은
    protocol gate가 1초로 바꾸므로 그대로 두면 무장이 줄어든다. 그래서 0도 바꾼다.
    대기가 55P03으로 끝나면 transaction이 abort되므로 되돌릴 필요가 없다.
    """
    if wait_ms <= 0:
        raise ValueError("wait_ms는 1 이상이어야 합니다.")
    rows = (await session.execute(text(_SESSION_LOCK_TIMEOUTS_SQL), {})).all()
    current = {str(name): int(setting) for name, setting in rows}
    prior_lock_ms = current["lock_timeout"]
    prior_statement_ms = current["statement_timeout"]
    prior_check_ms = current["client_connection_check_interval"]
    if prior_lock_ms != 0 and prior_lock_ms >= wait_ms:
        await session.execute(text(statement), dict(params or {}))
        return
    statement_ms = prior_statement_ms
    floor_ms = wait_ms + _STATEMENT_MARGIN_MS
    if statement_ms != 0 and statement_ms < floor_ms:
        statement_ms = floor_ms
    check_ms = prior_check_ms or _CONNECTION_CHECK_MS
    await session.execute(
        text(_SET_LOCAL_LOCK_TIMEOUTS_SQL),
        {
            "lock_timeout": str(wait_ms),
            "statement_timeout": str(statement_ms),
            "client_connection_check_interval": str(check_ms),
        },
    )
    started = time.monotonic()
    try:
        await session.execute(text(statement), dict(params or {}))
    except DBAPIError:
        # 성공만 남기면 15분 뒤의 맨 55P03이 왜 그렇게 늦었는지 아무도 모른다.
        _LOG.warning(
            "%s를 %.1f초 기다리다 실패했다 (상한 %dms, 종전 %dms)",
            label,
            time.monotonic() - started,
            wait_ms,
            prior_lock_ms,
        )
        raise
    waited = time.monotonic() - started
    await session.execute(
        text(_SET_LOCAL_LOCK_TIMEOUTS_SQL),
        {
            "lock_timeout": str(prior_lock_ms),
            "statement_timeout": str(prior_statement_ms),
            "client_connection_check_interval": str(prior_check_ms),
        },
    )
    if waited >= 1.0:
        _LOG.info(
            "%s를 %.1f초 기다려 잡았다 (상한 %dms, 종전 %dms)",
            label,
            waited,
            wait_ms,
            prior_lock_ms,
        )
