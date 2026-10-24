"""연결 후 PG가 SELECT에 응답하지 않아도 준비 probe의 deadline과 close를 지킨다."""

from __future__ import annotations

import asyncio

import pytest

from scripts import _scoped_write_baseline_pg as pg


class SilentConnection:
    def __init__(self, closed: list[bool]) -> None:
        self.closed = closed

    async def execute(self, query: str) -> None:
        assert query == "SELECT 1"
        await asyncio.Event().wait()

    async def close(self) -> None:
        self.closed.append(True)


async def test_connected_but_silent_query_has_attempt_deadline(monkeypatch) -> None:
    closed: list[bool] = []

    async def connect(*args, **kwargs):
        assert kwargs["autocommit"] is True
        return SilentConnection(closed)

    monkeypatch.setattr(pg.psycopg.AsyncConnection, "connect", connect)
    monkeypatch.setattr(pg, "_READY_ATTEMPT_SECONDS", 0.02)
    async with asyncio.timeout(2) as failsafe:
        assert await pg._ready("mock-only") is False
        assert not failsafe.expired()
    assert closed == [True]


async def test_overall_readiness_deadline_closes_each_connected_probe(monkeypatch) -> None:
    closed: list[bool] = []
    opened: list[bool] = []

    async def connect(*args, **kwargs):
        assert kwargs["autocommit"] is True
        opened.append(True)
        return SilentConnection(closed)

    monkeypatch.setattr(pg.psycopg.AsyncConnection, "connect", connect)
    monkeypatch.setattr(pg, "_READY_ATTEMPT_SECONDS", 0.01)
    monkeypatch.setattr(pg, "_READY_TOTAL_SECONDS", 0.05)
    monkeypatch.setattr(pg, "_READY_PAUSE_SECONDS", 0.001)
    async with asyncio.timeout(2) as failsafe:
        with pytest.raises(TimeoutError):
            await pg._wait_ready("mock-only")
        assert not failsafe.expired()
    assert opened
    assert len(closed) == len(opened)
