"""I/O 없이 멈춘 적재 step의 진단 — 2026-10-23 MCST 3.5시간 무이벤트."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from kortravelmap.dagster.stall_watchdog import process_io_bytes, stall_watchdog


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
    assert "진척 신호" in log.warnings[0]
    assert "_never_finishes" in log.warnings[0]


async def test_silent_while_io_moves() -> None:
    log = _Log()
    counter = iter(range(10_000))
    async with stall_watchdog(
        log, stall_after_seconds=0.03, poll_seconds=0.01, io_bytes=lambda: next(counter)
    ):
        await asyncio.sleep(0.15)

    assert log.warnings == []


async def test_activity_marks_count_as_progress_without_file_io() -> None:
    """geo·DB 소켓 I/O는 ``rchar``에 안 잡힌다 — 그 경계의 표시가 진척이다(2026-10-23 MCST 오탐)."""
    from kortravelmap.core import activity

    log = _Log()

    async def _busy() -> None:
        for _ in range(30):
            activity.mark()
            await asyncio.sleep(0.005)

    async with stall_watchdog(
        log, stall_after_seconds=0.5, poll_seconds=0.01, io_bytes=lambda: 7
    ):
        await _busy()

    assert log.warnings == []


async def test_one_warning_per_stall_rearms_after_progress_and_is_capped() -> None:
    """조용한 단계의 오탐이 뒤의 진짜 멈춤을 가리지 않게 재무장하고, 덤프 수는 상한으로 묶는다."""
    log = _Log()
    value = [0]
    async with stall_watchdog(
        log, stall_after_seconds=0.02, poll_seconds=0.01, io_bytes=lambda: value[0]
    ):
        await asyncio.sleep(0.15)
        assert len(log.warnings) == 1
        for _ in range(4):
            value[0] += 1
            await asyncio.sleep(0.15)

    assert len(log.warnings) == 3


def test_db_statements_mark_activity() -> None:
    from kortravelmap.core import activity
    from sqlalchemy import create_engine, text

    before = activity.snapshot()
    engine = create_engine("sqlite://")
    with engine.connect() as conn:
        conn.execute(text("select 1"))
    engine.dispose()
    assert activity.snapshot() != before


def test_reading_proc_io_does_not_count_as_progress() -> None:
    """관측이 관측값을 움직이면 감시는 영원히 울리지 않는다(적대 리뷰 — 호출마다 +106)."""
    first = process_io_bytes()
    if first is None:
        pytest.skip("/proc/self/io 없음")
    assert [process_io_bytes() for _ in range(5)] == [first] * 5


async def test_log_failure_does_not_fail_the_block() -> None:
    class _Broken:
        def warning(self, msg: str, *args: Any) -> None:
            raise RuntimeError("event log down")

    async with stall_watchdog(
        _Broken(), stall_after_seconds=0.02, poll_seconds=0.01, io_bytes=lambda: 1
    ):
        await asyncio.sleep(0.08)
