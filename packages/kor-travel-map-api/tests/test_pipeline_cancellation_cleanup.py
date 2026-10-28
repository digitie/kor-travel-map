"""Coordinator 원 backend 종료와 정상 연결 설정 복원 경계."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
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
        self.signal_result = {"signal_sent": True}

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
        if "pg_terminate_backend" in sql:
            if isinstance(self.signal_result, BaseException):
                raise self.signal_result
            return self.signal_result
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
            dbapi_connection=driver,
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
        self.proxy.dbapi_connection = None

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
        self.outcomes = []

    @asynccontextmanager
    async def begin(self):
        try:
            yield
        except BaseException:
            self.outcomes.append("rollback")
            raise
        else:
            self.outcomes.append("commit")

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
@pytest.mark.parametrize("fault", ["restore_error", "restore_delay"])
async def test_committed_result_survives_normal_cleanup_failure(monkeypatch, caplog, fault):
    """K 없는 정상 반환에서 정리만 실패하면 503이 아니다. 연결을 폐기하고 결과를 돌려준다.

    업무는 이미 commit됐다. 503을 내면 호출자는 같은 취소를 다시 보내고, 그동안 화면은
    commit된 상세 대신 오류를 보여 준다.
    """
    monkeypatch.setattr(service, "AsyncSession", Session)
    original = Connection(Driver(10))
    observer = Connection(Driver(11, [{"backend_present": False, "advisory_present": False}]))
    engine = Engine(original, observer)
    execute = original.execute

    async def faulty_restore(sql, params=None):
        if params is not None and "previous" in params:
            if fault == "restore_error":
                raise RuntimeError("injected GUC restore failure")
            await asyncio.sleep(service._CLEANUP_SECONDS * 3)
        return await execute(sql, params)

    original.execute = faulty_restore

    async def committed_request():
        async with service._coordinator_session(engine) as (_, session):
            return "committed-detail", service._session_backend(session)

    result, backend = await asyncio.wait_for(committed_request(), 5)
    assert result == "committed-detail"
    # 정리를 확인하지 못한 원 연결은 pool로 돌려보내지 않고 폐기한다.
    assert backend.cleanup_attempted
    assert original.driver.closed
    assert not engine.connections
    assert "after the committed result" in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("unsafe", ["lease_possible", "invalidated"])
async def test_unverifiable_success_still_maps_to_503(monkeypatch, unsafe):
    """위 완화의 경계: K를 쥐었을 수 있거나 연결이 무효화됐으면 정상 반환도 503이다."""
    monkeypatch.setattr(service, "AsyncSession", Session)
    original = Connection(Driver(10))
    observer = Connection(Driver(11, [{"backend_present": False, "advisory_present": False}]))

    async def request():
        async with service._coordinator_session(Engine(original, observer)) as (_, session):
            if unsafe == "lease_possible":
                service._session_backend(session).lease_possible = True
            else:
                original.invalidated = True
            return "unverifiable"

    with pytest.raises(service.PipelineCancellationDatabaseUnavailable):
        await request()
    assert original.driver.closed


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
    fetches = [
        c
        for c in observer.driver.calls
        if c[0] == "fetchrow" and "pg_terminate_backend" not in c[1]
    ]
    assert len(fetches) == 2
    signals = [
        c for c in observer.driver.calls if c[0] == "fetchrow" and "pg_terminate_backend" in c[1]
    ]
    assert len(signals) == 1
    assert signals[0][2] == (10, _START)
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


@pytest.mark.parametrize("original_closed", [False, True])
def test_released_proxy_cannot_terminate_another_checkout(original_closed):
    connection = Connection(Driver(10))
    backend = _backend(connection, None)
    connection.proxy.driver_connection = Driver(99)
    if original_closed:
        backend.driver.terminate()
    with pytest.raises(service.PipelineCancellationUnsafe, match="ownership"):
        service._discard_exact_backend(backend, RuntimeError("cancel"))
    assert backend.driver.closed is original_closed
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


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["connection_error", "creator_timeout"])
async def test_actual_sqlalchemy_checkout_failure_returns_pool_without_own_tasks(failure):
    from sqlalchemy.ext.asyncio import create_async_engine

    entered = asyncio.Event()
    finalized = asyncio.Event()
    pending = asyncio.Event()

    async def fail_before_native_connection():
        entered.set()
        try:
            if failure == "connection_error":
                raise OSError("injected connect failure before any native handle")
            await pending.wait()
        finally:
            finalized.set()

    # async_creator는 실제 connect를 호출하지 않는다. SQLAlchemy checkout 실패 회수만 검증한다.
    engine = create_async_engine(
        "postgresql+asyncpg://",
        async_creator=fail_before_native_connection,
        pool_size=1,
        max_overflow=0,
    )
    original = Connection(Driver(10))
    backend = _backend(original, engine)
    tasks_before = asyncio.all_tasks()
    try:
        confirmed = await service._confirm_backend_termination(
            backend,
            deadline=service.monotonic() + 0.02,
        )
        assert not confirmed
        assert entered.is_set()
        assert finalized.is_set()
        assert engine.pool.checkedout() == 0
        assert asyncio.all_tasks() == tasks_before
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_domain_rollback_continuation_and_normal_http_wait_keep_original_budget(monkeypatch):
    monkeypatch.setattr(service, "AsyncSession", Session)
    original = Connection(Driver(10))
    async with service._coordinator_session(Engine(original)) as (_, session):
        try:
            async with session.begin():
                raise service.PipelineCancellationTimelineConflict("recoverable timeline")
        except service.PipelineCancellationTimelineConflict:
            # continuation 가능한 domain 오류 뒤 HTTP 대기를 cleanup 예산에 넣지 않는다.
            await asyncio.sleep(0.51)
        async with session.begin():
            assert not original.driver.closed
    assert session.outcomes == ["rollback", "commit"]
    assert original.closed
    assert not original.driver.closed


@pytest.mark.asyncio
async def test_repeated_level_cancel_and_unconfirmed_latch_never_become_success(
    monkeypatch, caplog
):
    monkeypatch.setattr(service, "AsyncSession", Session)
    original = Connection(Driver(10))
    observer = Connection(Driver(11))
    observed = asyncio.Event()
    allow_failure = asyncio.Event()

    async def fail_during_readback(*_args, **_kwargs):
        observed.set()
        await allow_failure.wait()
        raise TimeoutError("injected observer timeout")

    observer.driver.fetchrow = fail_during_readback
    entered = asyncio.Event()
    scope = anyio.CancelScope()
    engine = Engine(original, observer)
    backend = None
    caught = []

    async def caller():
        nonlocal backend
        with scope:
            try:
                async with service._coordinator_session(engine) as (_, session):
                    backend = service._session_backend(session)
                    entered.set()
                    await asyncio.Event().wait()
            except BaseException as exc:
                caught.append(type(exc))
                raise

    task = asyncio.create_task(caller())
    await entered.wait()
    scope.cancel()
    await observed.wait()
    for _ in range(3):
        scope.cancel()
        await asyncio.sleep(0)
    assert not task.done()
    allow_failure.set()
    await asyncio.wait_for(task, 1)
    assert caught == [asyncio.CancelledError]
    assert backend.cleanup_attempted
    assert not backend.termination_confirmed
    assert original.closed
    assert observer.closed
    assert not engine.connections
    # 두 번째 cleanup은 재확인 없이 미확정 상태를 그대로 유지한다.
    await service._hard_invalidate_connection(backend, cause=RuntimeError("duplicate cleanup"))
    assert not backend.termination_confirmed
    assert "confirmed=False" in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("body_error", [None, ValueError("body domain failure")])
async def test_new_cancel_during_restore_has_priority_over_success_or_domain_error(
    monkeypatch,
    body_error,
):
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
    execute = original.execute
    cancel = asyncio.CancelledError("injected restore cancellation")

    async def cancelled_restore(sql, params=None):
        if params is not None and "previous" in params:
            raise cancel
        return await execute(sql, params)

    original.execute = cancelled_restore

    async def caller():
        async with service._coordinator_session(engine):
            if body_error is not None:
                raise body_error

    with pytest.raises(asyncio.CancelledError) as raised:
        await caller()
    assert raised.value is cancel
    assert original.driver.closed
    assert observer.driver.closed


@pytest.mark.asyncio
@pytest.mark.parametrize("body_error", [None, ValueError("body domain failure")])
async def test_direct_task_cancel_at_restore_barrier_is_preserved(monkeypatch, body_error):
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
    execute = original.execute
    restore_entered = asyncio.Event()
    caught = []

    async def blocked_restore(sql, params=None):
        if params is not None and "previous" in params:
            restore_entered.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError as exc:
                caught.append(exc)
                raise
        return await execute(sql, params)

    original.execute = blocked_restore

    async def caller():
        async with service._coordinator_session(engine):
            if body_error is not None:
                raise body_error

    task = asyncio.create_task(caller())
    await restore_entered.wait()
    task.cancel("direct restore barrier cancel")
    with pytest.raises(asyncio.CancelledError) as raised:
        await asyncio.wait_for(task, 1)
    assert len(caught) == 1
    assert raised.value is caught[0]
    assert original.driver.closed
    assert observer.driver.closed
    assert task.cancelled()


@pytest.mark.asyncio
async def test_original_caller_cancel_wins_over_new_cleanup_cancel(monkeypatch):
    monkeypatch.setattr(service, "AsyncSession", Session)
    original = Connection(Driver(10))
    primary = asyncio.CancelledError("original caller")
    cleanup_cancel = asyncio.CancelledError("cleanup interrupted")

    async def interrupted(backend, *, cause):
        service._discard_exact_backend(backend, cause)
        raise cleanup_cancel

    monkeypatch.setattr(service, "_hard_invalidate_connection", interrupted)

    async def caller():
        async with service._coordinator_session(Engine(original)):
            raise primary

    with pytest.raises(asyncio.CancelledError) as raised:
        await caller()
    assert raised.value is primary
    assert original.driver.closed


class _SqliteNative:
    """실 SQLAlchemy ownership 상태 검증용 DBAPI; PostgreSQL/네트워크 호출 없음."""

    def __init__(self):
        import sqlite3

        self.connection = sqlite3.connect(":memory:")
        self.closed = False
        self.terminations = 0

    def __getattr__(self, name):
        return getattr(self.connection, name)

    def is_closed(self):
        return self.closed

    def close(self):
        self.connection.close()
        self.closed = True

    def terminate(self):
        self.terminations += 1
        self.close()


class _SyncConnectionState:
    def __init__(self, connection):
        self.sync_connection = connection

    @property
    def closed(self):
        return self.sync_connection.closed

    @property
    def invalidated(self):
        return self.sync_connection.invalidated


def _sqlite_pool():
    from sqlalchemy import create_engine
    from sqlalchemy.pool import QueuePool

    return create_engine(
        "sqlite://",
        creator=_SqliteNative,
        poolclass=QueuePool,
        pool_size=1,
        max_overflow=0,
    )


def test_sqlalchemy_interrupted_invalidation_can_terminate_captured_native(monkeypatch):
    engine = _sqlite_pool()
    connection = engine.connect()
    proxy = connection.connection
    native = proxy.driver_connection
    backend = service._CoordinatorBackend(_SyncConnectionState(connection), None, proxy, native, 1)

    def interrupt_before_close(_driver):
        raise asyncio.CancelledError("injected before native close")

    try:
        # 최초 close가 취소된 경계만 주입한다. cleanup까지 영구 취소하는 가짜 dialect는 아니다.
        with monkeypatch.context() as fault:
            fault.setattr(engine.dialect, "do_terminate", interrupt_before_close)
            with pytest.raises(asyncio.CancelledError):
                connection.invalidate()
        assert not connection.closed
        assert not native.closed
        if connection.invalidated:
            # SQLAlchemy2.0.55: finally가 proxy를 비우고 slot을 반환한다.
            assert proxy.driver_connection is None
            assert proxy.dbapi_connection is None
            assert engine.pool.checkedout() == 0
        else:
            # constraints의2.0.54: 취소 직전의 정확 원 handle/proxy가 여전히 붙어 있다.
            assert proxy.driver_connection is native
            assert proxy.dbapi_connection is native
            assert engine.pool.checkedout() == 1

        service._discard_exact_backend(backend, RuntimeError("caller cancel"))
        assert native.closed
        assert native.terminations == 1
        assert connection.closed
        assert engine.pool.checkedout() == 0
    finally:
        if not native.closed:
            native.close()
        connection.close()
        engine.dispose()


@pytest.mark.parametrize("return_path", ["connection_close", "raw_proxy_close"])
def test_sqlalchemy_normal_return_same_native_recheckout_is_protected(return_path):
    engine = _sqlite_pool()
    connection = engine.connect()
    proxy = connection.connection
    native = proxy.driver_connection
    backend = service._CoordinatorBackend(_SyncConnectionState(connection), None, proxy, native, 1)
    try:
        if return_path == "connection_close":
            connection.close()
        else:
            proxy.close()
        with engine.connect() as next_checkout:
            assert next_checkout.connection.driver_connection is native
            assert not native.closed
            assert proxy.driver_connection is None
            assert not connection.invalidated
            with pytest.raises(service.PipelineCancellationUnsafe, match="ownership"):
                service._discard_exact_backend(backend, RuntimeError("late old caller"))
            assert native.terminations == 0
            assert not native.closed
            assert engine.pool.checkedout() == 1
        assert engine.pool.checkedout() == 0
    finally:
        connection.close()
        engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("signal_result", [None, {"signal_sent": False}, {"signal_sent": True}])
async def test_signal_result_never_substitutes_for_actual_zero_readback(signal_result):
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
    observer.driver.signal_result = signal_result
    backend = _backend(original, Engine(observer))
    assert await service._confirm_backend_termination(
        backend,
        deadline=service.monotonic() + 0.2,
    )
    signals = [
        c for c in observer.driver.calls if c[0] == "fetchrow" and "pg_terminate_backend" in c[1]
    ]
    readbacks = [
        c
        for c in observer.driver.calls
        if c[0] == "fetchrow" and "pg_terminate_backend" not in c[1]
    ]
    assert len(signals) == 1
    assert len(readbacks) == 2
    assert observer.driver.closed
    assert observer.closed


@pytest.mark.asyncio
async def test_signal_permission_failure_is_not_confirmed_and_preserves_cancel(monkeypatch, caplog):
    monkeypatch.setattr(service, "AsyncSession", Session)
    original = Connection(Driver(10))
    observer = Connection(Driver(11))
    observer.driver.signal_result = PermissionError("not an owned backend")
    backend = None
    error = asyncio.CancelledError("caller")
    async def failed_request():
        nonlocal backend
        async with service._coordinator_session(Engine(original, observer)) as (_, session):
            backend = service._session_backend(session)
            raise error

    with pytest.raises(asyncio.CancelledError) as raised:
        await failed_request()
    assert raised.value is error
    assert backend is not None
    assert not backend.termination_confirmed
    assert original.driver.closed
    assert observer.driver.closed
    assert "phase=exact_termination" in caplog.text
    assert "signal_sent=False" in caplog.text
