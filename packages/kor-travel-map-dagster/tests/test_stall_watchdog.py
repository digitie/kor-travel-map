"""I/O 없이 멈춘 적재 step의 진단 — 2026-10-23 MCST 3.5시간 무이벤트."""

from __future__ import annotations

import asyncio
from typing import Any

from kortravelmap.dagster.stall_watchdog import stall_watchdog


class _Log:
    def __init__(self) -> None:
        self.warnings: list[str] = []

    def warning(self, msg: str, *args: Any) -> None:
        self.warnings.append(msg % args)


async def _never_finishes(event: asyncio.Event) -> None:
    await event.wait()


async def test_dumps_task_stacks_once_when_io_stops() -> None:
    log = _Log()
    event = asyncio.Event()
    with_stall = asyncio.create_task(_never_finishes(event), name="stuck")
    async with stall_watchdog(
        log, stall_after_seconds=0.03, poll_seconds=0.01, io_bytes=lambda: 7
    ):
        await asyncio.sleep(0.15)
    event.set()
    await with_stall

    assert len(log.warnings) == 1
    assert "I/O 없이 멈춰" in log.warnings[0]
    assert "_never_finishes" in log.warnings[0]


async def test_silent_while_io_moves() -> None:
    log = _Log()
    counter = iter(range(10_000))
    async with stall_watchdog(
        log, stall_after_seconds=0.03, poll_seconds=0.01, io_bytes=lambda: next(counter)
    ):
        await asyncio.sleep(0.15)

    assert log.warnings == []


async def test_noop_without_proc_io() -> None:
    log = _Log()
    async with stall_watchdog(
        log, stall_after_seconds=0.0, poll_seconds=0.01, io_bytes=lambda: None
    ):
        await asyncio.sleep(0.05)

    assert log.warnings == []
