"""적재 step이 I/O 없이 멈추면 asyncio task 스택을 경고 로그로 남긴다.

**왜 있는가.** 2026-10-23 MCST 적재 run이 3시간 반 동안 이벤트 0건으로 STARTED에 머물렀다.
step 프로세스는 살아 있었지만 ``/proc/<pid>/io``의 ``rchar``가 1분 동안 한 바이트도 늘지
않았고, geo·DB 소켓에는 대기 중인 요청이 없었으며, main thread는 이벤트 루프의 ``select``에서
쉬고 있었다. 즉 **I/O가 아닌 무언가를 영원히 await**하고 있었다. py-spy는 coroutine 스택을
보여 주지 않고, 진행 로그는 ``python_log_level: WARNING`` 아래라 Dagster에 실리지 않는다 —
그래서 어디서 멈췄는지 알 길이 없었다.

이 watchdog은 그 상태를 **효과로** 잡는다: 프로세스 I/O 바이트(``rchar + wchar``)가
``stall_after_seconds`` 동안 그대로면 모든 task의 스택을 WARNING으로 한 번 남긴다. 멈춤
한 번에 한 번만 남기고(I/O가 다시 움직이면 재무장), run을 실패시키거나 취소하지 않는다 —
진단만 한다. ``/proc/self/io``가 없는 환경(macOS 등)에서는 아무것도 하지 않는다.
"""

from __future__ import annotations

import asyncio
import io
import logging
import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any, Final

__all__ = ["DEFAULT_STALL_AFTER_SECONDS", "process_io_bytes", "stall_watchdog"]

#: 이 시간 동안 프로세스 I/O가 그대로면 멈춤으로 본다. geo 호출 하나의 read 상한(수십 초)보다
#: 충분히 길어야 느린 응답을 멈춤으로 오인하지 않는다.
DEFAULT_STALL_AFTER_SECONDS: Final[float] = 900.0

_STACK_LIMIT: Final[int] = 40
_LOGGER = logging.getLogger(__name__)
_MAX_TASKS: Final[int] = 50


def process_io_bytes() -> int | None:
    """이 프로세스가 지금까지 읽고 쓴 바이트(소켓 포함). ``/proc/self/io``가 없으면 None."""
    try:
        with open("/proc/self/io", encoding="ascii") as handle:
            fields = dict(line.split(":", 1) for line in handle if ":" in line)
    except OSError:
        return None
    try:
        return int(fields["rchar"]) + int(fields["wchar"])
    except (KeyError, ValueError):
        return None


def _task_dump(current: asyncio.Task[Any] | None) -> str:
    tasks = [task for task in asyncio.all_tasks() if task is not current]
    out = io.StringIO()
    out.write(f"task {len(tasks)}개")
    if len(tasks) > _MAX_TASKS:
        out.write(f"(앞 {_MAX_TASKS}개만)")
    out.write("\n")
    for task in tasks[:_MAX_TASKS]:
        task.print_stack(limit=_STACK_LIMIT, file=out)
    return out.getvalue()


@asynccontextmanager
async def stall_watchdog(
    log: Any,
    *,
    stall_after_seconds: float = DEFAULT_STALL_AFTER_SECONDS,
    poll_seconds: float = 30.0,
    io_bytes: Callable[[], int | None] = process_io_bytes,
    clock: Callable[[], float] = time.monotonic,
) -> AsyncIterator[None]:
    """블록이 도는 동안 I/O 정지를 감시한다.

    ``log``는 ``warning(msg, *args)``를 가진 logger(보통 ``context.log``). None이면 모듈 logger.
    """
    logger: Any = _LOGGER if log is None else log
    if io_bytes() is None:
        yield
        return

    async def _watch() -> None:
        last = io_bytes()
        moved_at = clock()
        reported = False
        while True:
            await asyncio.sleep(poll_seconds)
            now_bytes = io_bytes()
            if now_bytes != last:
                last, moved_at, reported = now_bytes, clock(), False
                continue
            idle = clock() - moved_at
            if not reported and idle >= stall_after_seconds:
                reported = True
                logger.warning(
                    "적재 step이 %.0f초 동안 I/O 없이 멈춰 있다 — asyncio task 스택:\n%s",
                    idle,
                    _task_dump(asyncio.current_task()),
                )

    watcher = asyncio.create_task(_watch(), name="kortravelmap-stall-watchdog")
    try:
        yield
    finally:
        watcher.cancel()
        try:
            await watcher
        except asyncio.CancelledError:
            pass
