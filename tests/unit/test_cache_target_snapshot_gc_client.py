"""cache-target snapshot background drain client orchestration 테스트."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

import pytest

import kortravelmap.client as client_mod
from kortravelmap.client import AsyncKorTravelMapClient, CacheTargetSnapshotGcDrainResult
from kortravelmap.infra.cache_target_reconciliation_repo import (
    CacheTargetSnapshotGcBacklog,
    CacheTargetSnapshotGcBatchResult,
)
from kortravelmap.infra.cache_target_snapshot_gc_observation_repo import (
    CacheTargetSnapshotGcObservation,
)
from kortravelmap.infra.db import make_async_engine

pytestmark = pytest.mark.unit


class _BeginContext:
    def __init__(self, session: _Session) -> None:
        self._session = session

    async def __aenter__(self) -> None:
        self._session.begin_entries += 1

    async def __aexit__(self, *exc: object) -> bool:
        self._session.begin_exits += 1
        return False


class _Session:
    def __init__(self, number: int) -> None:
        self.number = number
        self.begin_entries = 0
        self.begin_exits = 0
        self.execute_calls: list[tuple[str, dict[str, Any]]] = []

    def begin(self) -> _BeginContext:
        return _BeginContext(self)

    async def execute(
        self, statement: object, params: dict[str, Any] | None = None
    ) -> None:
        self.execute_calls.append((str(statement), params or {}))


class _SessionContext:
    def __init__(self, session: _Session) -> None:
        self._session = session

    async def __aenter__(self) -> _Session:
        return self._session

    async def __aexit__(self, *exc: object) -> bool:
        return False


class _SessionFactory:
    def __init__(self) -> None:
        self.sessions: list[_Session] = []

    def __call__(self) -> _SessionContext:
        session = _Session(len(self.sessions))
        self.sessions.append(session)
        return _SessionContext(session)


class _LockConnection:
    def __init__(self) -> None:
        self.execute_calls: list[str] = []
        self.commits = 0

    async def execute(self, statement: object) -> None:
        self.execute_calls.append(str(statement))

    async def commit(self) -> None:
        self.commits += 1


class _LockConnectionContext:
    def __init__(self, connection: _LockConnection) -> None:
        self._connection = connection

    async def __aenter__(self) -> _LockConnection:
        return self._connection

    async def __aexit__(self, *exc: object) -> bool:
        return False


class _Engine:
    def __init__(self) -> None:
        self.connection = _LockConnection()

    def connect(self) -> _LockConnectionContext:
        return _LockConnectionContext(self.connection)


async def test_snapshot_gc_drain_uses_global_try_lock_and_transaction_per_batch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = make_async_engine("postgresql+asyncpg://u:p@localhost:5432/nodb")
    client = AsyncKorTravelMapClient(engine)
    factory = _SessionFactory()
    lock_engine = _Engine()
    monkeypatch.setattr(client, "_engine", lock_engine)
    monkeypatch.setattr(client, "_session_factory", factory)
    lock_calls: list[str] = []

    @asynccontextmanager
    async def _try_lock(_connection: _LockConnection, key: str):  # type: ignore[no-untyped-def]
        lock_calls.append(key)
        yield True

    batches = iter(
        [
            CacheTargetSnapshotGcBatchResult("system-a", 1_000, 0, True),
            CacheTargetSnapshotGcBatchResult("system-b", 5, 1, False),
        ]
    )
    batch_calls: list[dict[str, Any]] = []
    lock_commits_at_batch: list[int] = []

    async def _batch(_session: _Session, **kwargs: Any):  # type: ignore[no-untyped-def]
        lock_commits_at_batch.append(lock_engine.connection.commits)
        batch_calls.append(kwargs)
        return next(batches)

    observation_calls: list[int] = []
    trend_calls: list[dict[str, object]] = []

    async def _observe(session: _Session) -> CacheTargetSnapshotGcBacklog:
        observation_calls.append(session.number)
        return CacheTargetSnapshotGcBacklog(
            remaining_items=0,
            remaining_headers=0,
            total_items=31,
            total_headers=9,
            unexpired_unreferenced_items=13,
            unexpired_unreferenced_headers=4,
            referenced_items=18,
            referenced_headers=5,
        )

    async def _record_trend(
        session: _Session,
        **kwargs: object,
    ) -> CacheTargetSnapshotGcObservation:
        trend_calls.append({"session": session.number, **kwargs})
        return CacheTargetSnapshotGcObservation(
            observation_id=2,
            dagster_run_id="dagster-run-2",
            observed_at=datetime(2026, 8, 2, 1, 0, tzinfo=UTC),
            referenced_items=17,
            referenced_headers=4,
            previous_observation_run_id="dagster-run-1",
            previous_observed_at=datetime(2026, 8, 2, 0, 0, tzinfo=UTC),
            previous_referenced_items=10,
            previous_referenced_headers=4,
            growth_baseline_run_id="dagster-run-1",
            growth_baseline_observed_at=datetime(
                2026, 8, 2, 0, 0, tzinfo=UTC
            ),
            growth_baseline_referenced_items=10,
            growth_baseline_referenced_headers=4,
            growth_baseline_eligible=True,
            growth_min_interval_seconds=300,
        )

    monkeypatch.setattr(client_mod, "try_advisory_lock", _try_lock)
    monkeypatch.setattr(client_mod, "repo_prune_cache_target_snapshots_batch", _batch)
    monkeypatch.setattr(client_mod, "repo_observe_cache_target_snapshot_backlog", _observe)
    monkeypatch.setattr(
        client_mod,
        "repo_record_cache_target_snapshot_gc_observation",
        _record_trend,
    )

    try:
        result = await client.drain_expired_cache_target_snapshots(
            observation_run_id="dagster-run-2",
            observation_retention_days=30,
            observation_growth_min_interval_seconds=300,
        )
    finally:
        await engine.dispose()

    assert result == CacheTargetSnapshotGcDrainResult(
        acquired=True,
        skipped=False,
        batches=2,
        deleted_items=1_005,
        deleted_headers=1,
        remaining_items=0,
        remaining_headers=0,
        total_items=31,
        total_headers=9,
        unexpired_unreferenced_items=13,
        unexpired_unreferenced_headers=4,
        referenced_items=18,
        referenced_headers=5,
        observation_run_id="dagster-run-2",
        observed_at=datetime(2026, 8, 2, 1, 0, tzinfo=UTC),
        observation_referenced_items=17,
        observation_referenced_headers=4,
        previous_observation_run_id="dagster-run-1",
        previous_observed_at=datetime(2026, 8, 2, 0, 0, tzinfo=UTC),
        previous_referenced_items=10,
        previous_referenced_headers=4,
        growth_baseline_observation_run_id="dagster-run-1",
        growth_baseline_observed_at=datetime(2026, 8, 2, 0, 0, tzinfo=UTC),
        growth_baseline_referenced_items=10,
        growth_baseline_referenced_headers=4,
        observation_growth_baseline_eligible=True,
        observation_growth_min_interval_seconds=300,
    )
    assert lock_calls == ["cache-target-snapshot-gc"]
    assert lock_commits_at_batch == [1, 2]
    assert batch_calls == [
        {
            "after_external_system": None,
            "item_limit": 1_000,
            "header_limit": 100,
        },
        {
            "after_external_system": "system-a",
            "item_limit": 1_000,
            "header_limit": 100,
        },
    ]
    assert observation_calls == [2]
    assert trend_calls == [
        {
            "session": 2,
            "dagster_run_id": "dagster-run-2",
            "referenced_items": 18,
            "referenced_headers": 5,
            "retention_days": 30,
            "growth_min_interval_seconds": 300,
        }
    ]
    assert len(factory.sessions) == 3
    assert [session.begin_entries for session in factory.sessions] == [1, 1, 1]
    assert [session.begin_exits for session in factory.sessions] == [1, 1, 1]
    assert all(
        "set_config" in session.execute_calls[0][0] for session in factory.sessions
    )
    assert lock_engine.connection.commits == 3
    assert lock_engine.connection.execute_calls == ["SELECT 1", "SELECT 1"]


async def test_snapshot_gc_drain_skips_when_global_lock_is_held(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = make_async_engine("postgresql+asyncpg://u:p@localhost:5432/nodb")
    client = AsyncKorTravelMapClient(engine)
    factory = _SessionFactory()
    lock_engine = _Engine()
    monkeypatch.setattr(client, "_engine", lock_engine)
    monkeypatch.setattr(client, "_session_factory", factory)

    @asynccontextmanager
    async def _try_lock(_connection: _LockConnection, _key: str):  # type: ignore[no-untyped-def]
        yield False

    async def _unexpected_batch(_session: object, **_kwargs: object) -> object:
        pytest.fail("global lock을 얻지 못한 drain이 batch를 실행함")

    monkeypatch.setattr(client_mod, "try_advisory_lock", _try_lock)
    monkeypatch.setattr(
        client_mod,
        "repo_prune_cache_target_snapshots_batch",
        _unexpected_batch,
    )
    async def _unexpected_observation(_session: object) -> object:
        pytest.fail("global lock을 얻지 못한 drain이 backlog count를 실행함")

    monkeypatch.setattr(
        client_mod,
        "repo_observe_cache_target_snapshot_backlog",
        _unexpected_observation,
    )

    try:
        result = await client.drain_expired_cache_target_snapshots()
    finally:
        await engine.dispose()

    assert result == CacheTargetSnapshotGcDrainResult(
        acquired=False,
        skipped=True,
        batches=0,
        deleted_items=0,
        deleted_headers=0,
        remaining_items=None,
        remaining_headers=None,
    )
    assert factory.sessions == []
    assert lock_engine.connection.commits == 1


async def test_snapshot_gc_drain_propagates_cancellation_and_unwinds_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = make_async_engine("postgresql+asyncpg://u:p@localhost:5432/nodb")
    client = AsyncKorTravelMapClient(engine)
    factory = _SessionFactory()
    lock_engine = _Engine()
    monkeypatch.setattr(client, "_engine", lock_engine)
    monkeypatch.setattr(client, "_session_factory", factory)
    lock_exited = False

    @asynccontextmanager
    async def _try_lock(_connection: _LockConnection, _key: str):  # type: ignore[no-untyped-def]
        nonlocal lock_exited
        try:
            yield True
        finally:
            lock_exited = True

    async def _cancel(_session: object, **_kwargs: object) -> object:
        raise asyncio.CancelledError

    monkeypatch.setattr(client_mod, "try_advisory_lock", _try_lock)
    monkeypatch.setattr(
        client_mod,
        "repo_prune_cache_target_snapshots_batch",
        _cancel,
    )

    try:
        with pytest.raises(asyncio.CancelledError):
            await client.drain_expired_cache_target_snapshots()
    finally:
        await engine.dispose()

    assert lock_exited
    assert factory.sessions[0].begin_exits == 1
    assert lock_engine.connection.commits == 1


async def test_snapshot_gc_drain_stops_after_full_round_without_progress(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = make_async_engine("postgresql+asyncpg://u:p@localhost:5432/nodb")
    client = AsyncKorTravelMapClient(engine)
    factory = _SessionFactory()
    lock_engine = _Engine()
    monkeypatch.setattr(client, "_engine", lock_engine)
    monkeypatch.setattr(client, "_session_factory", factory)

    @asynccontextmanager
    async def _try_lock(_connection: _LockConnection, _key: str):  # type: ignore[no-untyped-def]
        yield True

    batches = iter(
        [
            CacheTargetSnapshotGcBatchResult("system-a", 0, 0, True),
            CacheTargetSnapshotGcBatchResult("system-b", 0, 0, True),
            CacheTargetSnapshotGcBatchResult("system-a", 0, 0, True),
        ]
    )
    calls = 0

    async def _batch(_session: object, **_kwargs: object) -> object:
        nonlocal calls
        calls += 1
        return next(batches)

    async def _observe(_session: object) -> CacheTargetSnapshotGcBacklog:
        return CacheTargetSnapshotGcBacklog(25, 2)

    monkeypatch.setattr(client_mod, "try_advisory_lock", _try_lock)
    monkeypatch.setattr(client_mod, "repo_prune_cache_target_snapshots_batch", _batch)
    monkeypatch.setattr(client_mod, "repo_observe_cache_target_snapshot_backlog", _observe)

    try:
        result = await client.drain_expired_cache_target_snapshots(
            max_batches=2_000,
        )
    finally:
        await engine.dispose()

    assert calls == result.batches == 3
    assert result.remaining_items == 25
    assert result.remaining_headers == 2
    assert lock_engine.connection.commits == 4
