"""Coordinator 원 backend 종료와 정상 연결 설정 복원 경계."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace

import anyio
import pytest

from kortravelmap.api import pipeline_cancellation_service as service

pytestmark = pytest.mark.unit
_START = datetime(2026, 10, 25, tzinfo=UTC)


class Driver:
    def __init__(self, pid, rows=()):
        self.pid = pid
        self.rows = list(rows)
        self.closed = False
        self.terminations = 0
        self.calls = []

    def get_server_pid(self):
        return self.pid

    def is_closed(self):
        return self.closed

    def terminate(self):
        self.terminations += 1
        self.closed = True

    async def execute(self, sql, **kwargs):
        self.calls.append(("execute", sql, kwargs["timeout"]))

    async def fetchrow(self, sql, *args, **kwargs):
        self.calls.append(("fetchrow", sql, args, kwargs["timeout"]))
        item = self.rows.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


class Connection:
    def __init__(self, driver, *, previous="0", start_gate=None):
        self.driver = driver
        self.previous = previous
        self.start_gate = start_gate
        self.invalidated = False
        self.closed = False
        self.commands = []
        self.proxy = SimpleNamespace(
            driver_connection=driver,
            invalidate=self.invalidate,
        )
        self.sync_connection = SimpleNamespace(
            connection=self.proxy,
            invalidate=self.invalidate,
            close=self.close_sync,
        )

    async def start(self):
        if self.start_gate is not None:
            await self.start_gate.wait()
        return self

    def invalidate(self, *_args, **_kwargs):
        self.invalidated = True
        self.proxy.driver_connection = None

    def close_sync(self):
        self.closed = True

    async def close(self):
        self.closed = True

    async def execute(self, sql, params=None):
        self.commands.append((str(sql), params))
        return SimpleNamespace(one=lambda: (_START, self.previous, "100ms"))

    async def commit(self):
        self.commands.append(("commit", None))


class Engine:
    def __init__(self, *connections):
        self.connections = list(connections)

    def connect(self):
        return self.connections.pop(0)


class Session:
    def __init__(self, *, bind, **_kwargs):
        self.connection = bind
        self.info = {}
        self.closed = False

    async def close(self):
        self.closed = True


def _backend(connection, engine):
    backend = service._capture_backend(connection, engine)
    backend.backend_start = _START
    return backend


@pytest.mark.asyncio
@pytest.mark.parametrize("previous", ["0", "25ms", "2s"])
async def test_normal_session_preserves_business_budget_and_restores_exact_guc(
    monkeypatch,
    previous,
):
    monkeypatch.setattr(service, "AsyncSession", Session)
    connection = Connection(Driver(10), previous=previous)
    async with service._coordinator_session(Engine(connection)) as (actual, session):
        assert actual is connection
        assert service._session_backend(session).driver is connection.driver
        # .5s 정상 phase cap을 두지 않는다. DB/Dagster 실제 상한은 이 단위시험으로 판정하지 않는다.
        await asyncio.sleep(0.51)
    assert not connection.driver.closed
    assert session.closed
    assert connection.closed
    init, restore = [item for item in connection.commands if item[0] != "commit"]
    assert "MATERIALIZED" in init[0]
    assert "LEAST" in init[0]
    assert init[1] == {"check_ms": 100}
    assert "statement_timeout" not in init[0]
    assert "lock_timeout" not in init[0]
    assert restore[1] == {"previous": previous}


@pytest.mark.asyncio
async def test_level_cancellation_shields_exact_termination_and_readback(monkeypatch):
    monkeypatch.setattr(service, "AsyncSession", Session)
    original = Connection(Driver(10))
    observer = Connection(
        Driver(
            11,
            [
                {"backend_present": True, "advisory_present": True},
                {"backend_present": False, "advisory_present": False},
            ],
        )
    )
    engine = Engine(original, observer)
    entered = asyncio.Event()
    caught = []
    scope = anyio.CancelScope()

    async def caller():
        with scope:
            try:
                async with service._coordinator_session(engine):
                    entered.set()
                    await asyncio.Event().wait()
            except BaseException as exc:
                caught.append(type(exc))
                raise

    task = asyncio.create_task(caller())
    await entered.wait()
    scope.cancel()
    await asyncio.wait_for(task, 1)
    assert caught == [asyncio.CancelledError]
    assert original.driver.closed
    assert observer.driver.closed
    assert original.closed
    assert observer.closed
    fetches = [c for c in observer.driver.calls if c[0] == "fetchrow"]
    assert len(fetches) == 2
    assert all(c[2] == (10, _START) for c in fetches)
    assert all("backend_start=$2" in c[1] for c in fetches)


@pytest.mark.asyncio
async def test_unknown_acquire_gap_and_duplicate_cleanup_use_one_observer(monkeypatch):
    monkeypatch.setattr(service, "AsyncSession", Session)
    original = Connection(Driver(10))
    observer = Connection(
        Driver(
            11,
            [
                {"backend_present": False, "advisory_present": False},
            ],
        )
    )
    engine = Engine(original, observer)

    async def cancel_in_gap():
        nonlocal backend
        async with service._coordinator_session(engine) as (_, session):
            backend = service._session_backend(session)
            try:
                raise asyncio.CancelledError("after real K commit, before caller assignment")
            finally:
                await service._hard_invalidate_connection(
                    backend,
                    cause=asyncio.CancelledError(),
                )

    backend = None
    with pytest.raises(asyncio.CancelledError):
        await cancel_in_gap()
    assert backend.cleanup_attempted
    assert backend.termination_confirmed
    assert not engine.connections
    assert original.driver.terminations == 1


@pytest.mark.asyncio
async def test_readback_failure_is_not_confirmed_and_preserves_caller_cancel(monkeypatch, caplog):
    monkeypatch.setattr(service, "AsyncSession", Session)
    original = Connection(Driver(10))
    observer = Connection(Driver(11, [TimeoutError("observer timeout")]))
    engine = Engine(original, observer)
    error = asyncio.CancelledError("caller")

    async def failed_request():
        nonlocal backend
        async with service._coordinator_session(engine) as (_, session):
            backend = service._session_backend(session)
            raise error

    backend = None
    with pytest.raises(asyncio.CancelledError) as raised:
        await failed_request()
    assert raised.value is error
    assert backend.cleanup_attempted
    assert not backend.termination_confirmed
    assert observer.driver.closed
    assert "confirmed=False" in caplog.text


@pytest.mark.asyncio
async def test_invalidated_connection_never_reconnects_or_sends_unlock(monkeypatch):
    monkeypatch.setattr(service, "AsyncSession", Session)
    original = Connection(Driver(10))
    observer = Connection(
        Driver(
            11,
            [
                {"backend_present": False, "advisory_present": False},
            ],
        )
    )
    engine = Engine(observer)
    backend = _backend(original, engine)
    original.invalidated = True
    original.sync_connection.connection = property(lambda _: pytest.fail("late proxy access"))
    session = Session(bind=original)
    session.info[service._BACKEND_INFO_KEY] = backend
    with pytest.raises(service.PipelineCancellationDatabaseUnavailable):
        await service._release_coordinator_lease(session, original, lease_key=7)
    assert original.commands == []
    assert backend.termination_confirmed


def test_released_proxy_cannot_terminate_another_checkout():
    connection = Connection(Driver(10))
    backend = _backend(connection, None)
    connection.proxy.driver_connection = Driver(99)
    with pytest.raises(service.PipelineCancellationUnsafe, match="ownership"):
        service._discard_exact_backend(backend, RuntimeError("cancel"))
    assert not backend.driver.closed
    assert not connection.proxy.driver_connection.closed


@pytest.mark.asyncio
async def test_observer_is_discarded_when_its_readonly_setup_fails():
    connection = Connection(Driver(10))
    observer = Connection(Driver(11))

    async def failed(*_args, **_kwargs):
        raise RuntimeError("readonly observer setup failed")

    observer.driver.execute = failed
    backend = _backend(connection, Engine(observer))
    assert not await service._confirm_backend_termination(
        backend,
        deadline=service.monotonic() + 0.2,
    )
    assert observer.closed
    assert observer.driver.closed


@pytest.mark.asyncio
async def test_observer_checkout_deadline_does_not_leave_started_connection():
    connection = Connection(Driver(10))
    observer = Connection(Driver(11), start_gate=asyncio.Event())
    backend = _backend(connection, Engine(observer))
    assert not await service._confirm_backend_termination(
        backend,
        deadline=service.monotonic() + 0.01,
    )
    assert observer.closed
    assert observer.invalidated


def test_database_cleanup_unavailable_maps_to_retryable_503():
    from kortravelmap.api.pipeline_cancellation_http import to_http_exception

    error = service.PipelineCancellationDatabaseUnavailable(
        "cleanup boundary",
        retry_after_seconds=1,
    )
    mapped = to_http_exception(error)
    assert mapped.status_code == 503
    assert mapped.headers == {"Retry-After": "1"}
    assert mapped.detail["code"] == "PIPELINE_CANCELLATION_DATABASE_UNAVAILABLE"


@pytest.mark.asyncio
async def test_unknown_k_commit_exception_discards_original_before_pool_return(monkeypatch):
    monkeypatch.setattr(service, "AsyncSession", Session)
    original = Connection(Driver(10))
    observer = Connection(
        Driver(
            11,
            [
                {"backend_present": False, "advisory_present": False},
            ],
        )
    )
    error = RuntimeError("K commit outcome unknown")

    async def unknown_commit():
        raise error

    async def request():
        async with service._coordinator_session(Engine(original, observer)) as (_, session):
            session.in_transaction = lambda: False
            session.execute = lambda *_args, **_kwargs: scalar_true()
            session.commit = unknown_commit
            await service._acquire_coordinator_lease(session, lease_key=7)

    async def scalar_true():
        return SimpleNamespace(scalar_one=lambda: True)

    with pytest.raises(RuntimeError) as raised:
        await request()
    assert raised.value is error
    assert original.closed
    assert original.driver.closed
    assert observer.closed
