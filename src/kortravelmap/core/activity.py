"""프로세스 단위 진척 신호 — 실제 일을 한 경계가 한 번씩 표시한다.

적재 step의 멈춤 감시(``kortravelmap.dagster.stall_watchdog``)가 읽는다.
``/proc/self/io``의 ``rchar``/``wchar``는 소켓 송수신(``recv``/``send``)을 세지 않는다 — 2026-10-23 MCST run은 geo를
수만 번 부르는 동안에도 그 값이 거의 그대로여서 감시가 15분마다 "멈췄다"고 오탐했다. 그래서 geo 왕복·
상류 요청·DB 문장처럼 **일을 한 자리**가 이 계수를 올린다.

값의 의미는 "바뀌었는가"뿐이다. 무엇을 몇 번 했는지는 각 경계의 자체 계수가 센다.
"""

from __future__ import annotations

import itertools
from typing import Final

__all__ = ["mark", "snapshot"]

_COUNTER: Final = itertools.count(1)
_last = 0


def mark() -> None:
    """일을 한 번 했다고 표시한다(스레드 안전 — ``itertools.count``는 GIL 아래 원자적이다)."""
    global _last
    _last = next(_COUNTER)


def snapshot() -> int:
    """지금까지의 표시 값. 비교만 의미가 있다."""
    return _last
