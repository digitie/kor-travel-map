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


@pytest.mark.parametrize("next_port", [30001, 30002])
async def test_restart_refreshes_owned_mapping_before_readiness(monkeypatch, next_port) -> None:
    class OwnedContainer:
        port = 30001
        reads = 0

        def get_connection_url(self) -> str:
            self.reads += 1
            return f"postgresql+psycopg2://owned:fixture@localhost:{self.port}/postgres"

    container = OwnedContainer()

    class OwnedDocker:
        def restart(self, *, timeout: int) -> None:
            assert timeout == 10
            assert container.reads == 0
            container.port = next_port

    ready: list[str] = []

    async def wait_ready(admin: str) -> None:
        ready.append(admin)
        assert container.reads == 1
        assert pg.make_url(admin).port == next_port

    monkeypatch.setattr(pg, "_wait_ready", wait_ready)
    current = await pg._restart_owned_database(container, OwnedDocker())
    assert current.drivername == "postgresql"
    assert current.port == next_port
    assert current.username == "owned"
    assert current.database == "postgres"
    assert ready == [current.render_as_string(hide_password=False)]
