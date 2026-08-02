"""Generic cache-target snapshot reuse/prune repository 계약 테스트."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy.exc import DBAPIError

from kortravelmap.infra import cache_target_reconciliation_repo as repo


class _Result:
    def __init__(
        self,
        row: Any | None = None,
        *,
        scalar: Any = None,
        rows: list[Any] | None = None,
    ) -> None:
        self._row = row
        self._scalar = scalar
        self._rows = rows or []

    def one_or_none(self) -> Any | None:
        return self._row

    def one(self) -> Any:
        if self._row is None:
            raise AssertionError("expected one row")
        return self._row

    def scalar_one(self) -> Any:
        return self._scalar

    def all(self) -> list[Any]:
        return self._rows


class _Session:
    def __init__(
        self,
        reusable: dict[str, Any] | None = None,
        *,
        acquired: bool = True,
        return_ttls: list[bool] | None = None,
        generic_snapshot_count: int = 0,
        oldest_expires_at: datetime | None = None,
        retry_after_seconds: int = 1,
    ) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self._reusable = reusable
        self._acquired = acquired
        self._return_ttls = list(return_ttls or [True])
        self._generic_snapshot_count = generic_snapshot_count
        self._oldest_expires_at = oldest_expires_at
        self._retry_after_seconds = retry_after_seconds

    async def execute(
        self,
        statement: Any,
        params: dict[str, Any] | None = None,
    ) -> _Result:
        sql = str(statement)
        self.calls.append((sql, params or {}))
        if "pg_try_advisory_xact_lock" in sql:
            return _Result(scalar=self._acquired)
        if "clock_timestamp() + interval '75 minutes'" in sql:
            value = self._return_ttls.pop(0) if self._return_ttls else True
            return _Result(scalar=value)
        if (
            "SELECT stream.external_system" in sql
            and "stream.restore_epoch" not in sql
            and "FOR SHARE OF stream" in sql
        ):
            return _Result(SimpleNamespace(_mapping={"external_system": "pinvi"}))
        if "SELECT stream.restore_epoch" in sql:
            return _Result(
                SimpleNamespace(
                    _mapping={
                        "restore_epoch": 3,
                        "high_watermark_relay_order": 8,
                        "material_high_watermark_relay_order": 5,
                    }
                )
            )
        if "WITH candidates AS MATERIALIZED" in sql:
            return _Result(
                SimpleNamespace(
                    _mapping={
                        "snapshot_count": self._generic_snapshot_count,
                        "oldest_expires_at": self._oldest_expires_at,
                        "retry_after_seconds": self._retry_after_seconds,
                    }
                )
            )
        if (
            "FROM ops.poi_cache_target_snapshots AS snapshot" in sql
            and "expires_at > now()" in sql
        ):
            row = (
                SimpleNamespace(_mapping=self._reusable)
                if self._reusable is not None
                else None
            )
            return _Result(row)
        return _Result()


class _GcSession:
    def __init__(self, systems: list[str | None], *, has_more: bool = True) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self._systems = iter(systems)
        self._has_more = has_more

    async def execute(
        self,
        statement: Any,
        params: dict[str, Any] | None = None,
    ) -> _Result:
        sql = str(statement)
        self.calls.append((sql, params or {}))
        if "GROUP BY snapshot.external_system" in sql:
            system = next(self._systems)
            row = (
                SimpleNamespace(_mapping={"external_system": system})
                if system is not None
                else None
            )
            return _Result(row)
        if "DELETE FROM ops.poi_cache_target_snapshot_items" in sql:
            return _Result(rows=[("s1", 1), ("s1", 2)])
        if "DELETE FROM ops.poi_cache_target_snapshots" in sql:
            return _Result(rows=[("s1",)])
        if "SELECT EXISTS" in sql:
            return _Result(scalar=self._has_more)
        if "WITH snapshot_inventory AS MATERIALIZED" in sql:
            return _Result(
                SimpleNamespace(
                    _mapping={
                        "remaining_items": 7,
                        "remaining_headers": 3,
                        "total_items": 31,
                        "total_headers": 9,
                        "unexpired_unreferenced_items": 13,
                        "unexpired_unreferenced_headers": 4,
                        "referenced_items": 11,
                        "referenced_headers": 2,
                    }
                )
            )
        raise AssertionError(f"unexpected SQL: {sql}")


class _BuildSession:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def execute(
        self,
        statement: Any,
        params: dict[str, Any] | None = None,
    ) -> _Result:
        sql = str(statement)
        values = params or {}
        self.calls.append((sql, values))
        if "set_config('statement_timeout'" in sql:
            return _Result(scalar="30s")
        if "set_config('lock_timeout', '0'" in sql:
            return _Result(scalar="0")
        if (
            "SELECT stream.external_system" in sql
            and "stream.restore_epoch" not in sql
            and "FOR SHARE OF stream" in sql
        ):
            return _Result(SimpleNamespace(_mapping={"external_system": "pinvi"}))
        if "FROM ops.poi_cache_target_streams AS stream" in sql:
            return _Result(
                rows=[
                    SimpleNamespace(
                        _mapping={
                            "external_system": "pinvi",
                            "restore_epoch": 3,
                            "high_watermark_relay_order": 8,
                            "material_high_watermark_relay_order": 5,
                            "target_key": None,
                            "state": None,
                            "source_generation": None,
                            "source_payload_fingerprint": None,
                        }
                    )
                ]
            )
        raise AssertionError(f"unexpected SQL: {sql}")


class _SqlStateError(Exception):
    def __init__(self, sqlstate: str) -> None:
        super().__init__(sqlstate)
        self.sqlstate = sqlstate


class _BarrierTimeoutSession:
    async def execute(
        self,
        statement: Any,
        params: dict[str, Any] | None = None,
    ) -> _Result:
        sql = str(statement)
        if "set_config('lock_timeout'" in sql:
            return _Result(scalar="5s")
        if "FOR SHARE OF stream" in sql:
            raise DBAPIError(None, params, _SqlStateError("55P03"), False)
        raise AssertionError(f"unexpected SQL: {sql}")


class _BuildTimeoutSession(_BuildSession):
    async def execute(
        self,
        statement: Any,
        params: dict[str, Any] | None = None,
    ) -> _Result:
        sql = str(statement)
        if "LIMIT :capture_limit" in sql:
            raise DBAPIError(None, params, _SqlStateError("57014"), False)
        return await super().execute(statement, params)


@pytest.mark.unit
async def test_background_gc_batch_uses_exact_keyset_and_reports_backlog() -> None:
    session = _GcSession(["system-b"])

    result = await repo.prune_expired_cache_target_snapshots_batch(
        session,  # type: ignore[arg-type]
        after_external_system="system-a",
        item_limit=1_000,
        header_limit=100,
    )

    assert result == repo.CacheTargetSnapshotGcBatchResult(
        external_system="system-b",
        deleted_items=2,
        deleted_headers=1,
        has_more=True,
    )
    select_sql, select_params = session.calls[0]
    assert 'COLLATE "C"' in select_sql
    assert "ORDER BY snapshot.external_system" in select_sql
    assert select_params == {"after_external_system": "system-a"}
    assert session.calls[1][1] == {"external_system": "system-b", "limit": 1_000}
    assert session.calls[2][1] == {"external_system": "system-b", "limit": 100}
    assert "SELECT EXISTS" in session.calls[3][0]
    assert "count(*)" not in session.calls[3][0]


@pytest.mark.unit
async def test_background_gc_batch_wraps_keyset_once() -> None:
    session = _GcSession([None, "system-a"])

    result = await repo.prune_expired_cache_target_snapshots_batch(
        session,  # type: ignore[arg-type]
        after_external_system="system-z",
    )

    assert result.external_system == "system-a"
    assert session.calls[0][1] == {"after_external_system": "system-z"}
    assert session.calls[1][1] == {"after_external_system": None}


@pytest.mark.unit
async def test_background_gc_exact_backlog_is_a_separate_observation() -> None:
    session = _GcSession([])

    backlog = await repo.observe_expired_cache_target_snapshot_backlog(
        session  # type: ignore[arg-type]
    )

    assert backlog == repo.CacheTargetSnapshotGcBacklog(
        remaining_items=7,
        remaining_headers=3,
        total_items=31,
        total_headers=9,
        unexpired_unreferenced_items=13,
        unexpired_unreferenced_headers=4,
        referenced_items=11,
        referenced_headers=2,
    )
    assert len(session.calls) == 1
    assert "WITH snapshot_inventory AS MATERIALIZED" in session.calls[0][0]


@pytest.mark.unit
def test_reuse_identity_filters_material_events_but_snapshot_cursor_stays_global() -> None:
    identity_sql = repo._GET_SNAPSHOT_IDENTITY_SQL  # pyright: ignore[reportPrivateUsage]
    capture_sql = repo._CAPTURE_VIEW_SQL  # pyright: ignore[reportPrivateUsage]

    assert "event.event_type = 'cache_target.state_applied'" in identity_sql
    assert "material_high_watermark_relay_order" in identity_sql
    assert "AS high_watermark_relay_order" in capture_sql
    assert "event.event_type = 'cache_target.state_applied'" in capture_sql
    assert "AS material_high_watermark_relay_order" in capture_sql
    assert "LIMIT :capture_limit" in capture_sql


@pytest.mark.unit
def test_snapshot_item_ceiling_accepts_exact_limit_and_rejects_limit_plus_one() -> None:
    repo._enforce_snapshot_item_limit(100_000)  # pyright: ignore[reportPrivateUsage]

    with pytest.raises(repo.CacheTargetStreamConflict) as exceeded:
        repo._enforce_snapshot_item_limit(100_001)  # pyright: ignore[reportPrivateUsage]

    assert exceeded.value.code == "snapshot_item_limit_exceeded"
    assert exceeded.value.current == {
        "item_count_lower_bound": 100_001,
        "item_limit": 100_000,
    }


@pytest.mark.unit
async def test_snapshot_material_build_sets_timeout_and_uses_limit_sentinel() -> None:
    session = _BuildSession()

    header, items = await repo._build_snapshot_material(  # pyright: ignore[reportPrivateUsage]
        session,  # type: ignore[arg-type]
        external_system="pinvi",
    )

    assert header["item_count"] == 0
    assert items == ()
    assert "set_config('lock_timeout'" in session.calls[0][0]
    assert session.calls[0][1] == {
        "lock_timeout": "5s",
        "statement_timeout": "30s",
    }
    assert "FOR SHARE OF stream" in session.calls[1][0]
    assert "set_config('lock_timeout', '0'" in session.calls[2][0]
    assert "LIMIT :capture_limit" in session.calls[3][0]
    assert session.calls[3][1] == {
        "external_system": "pinvi",
        "capture_limit": 100_001,
    }


@pytest.mark.unit
async def test_snapshot_barrier_and_build_timeouts_are_typed_conflicts() -> None:
    with pytest.raises(repo.CacheTargetStreamConflict) as barrier:
        await repo._barrier_snapshot_stream(  # pyright: ignore[reportPrivateUsage]
            _BarrierTimeoutSession(),  # type: ignore[arg-type]
            external_system="pinvi",
        )
    assert barrier.value.code == "snapshot_barrier_timeout"

    with pytest.raises(repo.CacheTargetStreamConflict) as build:
        await repo._build_snapshot_material(  # pyright: ignore[reportPrivateUsage]
            _BuildTimeoutSession(),  # type: ignore[arg-type]
            external_system="pinvi",
        )
    assert build.value.code == "snapshot_build_timeout"


@pytest.mark.unit
async def test_create_snapshot_reuses_exact_unreferenced_material(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)
    material = {
        "snapshot_id": "11111111-1111-4111-8111-111111111111",
        "external_system": "pinvi",
        "restore_epoch": 3,
        "high_watermark_relay_order": 8,
        "item_count": 0,
        "merkle_root": "a" * 64,
    }
    reusable = {
        **material,
        "snapshot_id": "22222222-2222-4222-8222-222222222222",
        "created_at": now,
        "expires_at": now + timedelta(minutes=90),
    }
    session = _Session(reusable)
    create_calls: list[str] = []

    async def _create(_session: Any, *, external_system: str) -> tuple[Any, tuple[Any, ...]]:
        create_calls.append(external_system)
        return material, ()

    monkeypatch.setattr(repo, "_create_snapshot", _create)

    header, items = await repo._create_generic_snapshot(  # pyright: ignore[reportPrivateUsage]
        session,  # type: ignore[arg-type]
        external_system="pinvi",
        limit=10,
    )

    assert header == reusable
    assert items == ()
    assert create_calls == []
    assert "pg_try_advisory_xact_lock" in session.calls[0][0]
    assert "set_config('lock_timeout'" in session.calls[1][0]
    assert "FOR SHARE OF stream" in session.calls[2][0]
    assert "SELECT stream.restore_epoch" in session.calls[4][0]
    assert "expires_at > now() + interval '75 minutes'" in session.calls[5][0]
    assert "= :material_high_watermark_relay_order" in session.calls[5][0]
    assert session.calls[5][1]["material_high_watermark_relay_order"] == 5
    assert "poi_cache_target_reconciliation_requests" in session.calls[5][0]
    assert "FOR SHARE OF snapshot" in session.calls[5][0]
    assert "poi_cache_target_snapshot_items" in session.calls[6][0]
    assert "clock_timestamp() + interval '75 minutes'" in session.calls[7][0]
    assert all("DELETE FROM" not in sql for sql, _params in session.calls)


@pytest.mark.unit
async def test_reusable_snapshot_below_return_ttl_gate_is_rebuilt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)
    material = {
        "snapshot_id": "21111111-1111-4111-8111-111111111111",
        "external_system": "pinvi",
        "restore_epoch": 3,
        "high_watermark_relay_order": 8,
        "item_count": 0,
        "merkle_root": "a" * 64,
        "created_at": now,
        "expires_at": now + timedelta(hours=2),
    }
    reusable = {
        **material,
        "snapshot_id": "22222222-2222-4222-8222-222222222222",
        "expires_at": now + timedelta(minutes=75),
    }
    session = _Session(reusable, return_ttls=[False, True])
    create_calls: list[str] = []

    async def _create(_session: Any, *, external_system: str) -> tuple[Any, tuple[Any, ...]]:
        create_calls.append(external_system)
        return material, ()

    monkeypatch.setattr(repo, "_create_snapshot", _create)

    header, _items = await repo._create_generic_snapshot(  # pyright: ignore[reportPrivateUsage]
        session,  # type: ignore[arg-type]
        external_system="pinvi",
        limit=10,
    )

    assert header["snapshot_id"] == material["snapshot_id"]
    assert create_calls == ["pinvi"]
    assert sum(
        "clock_timestamp() + interval '75 minutes'" in sql
        for sql, _params in session.calls
    ) == 2
    insert_sql = repo._INSERT_SNAPSHOT_SQL  # pyright: ignore[reportPrivateUsage]
    assert "clock_timestamp() AS materialized_at" in insert_sql
    assert "materialized_at, materialized_at + interval '2 hours'" in insert_sql


@pytest.mark.unit
async def test_create_generic_snapshot_prunes_only_before_full_capture(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    material = {
        "snapshot_id": "33333333-3333-4333-8333-333333333333",
        "external_system": "pinvi",
        "restore_epoch": 3,
        "high_watermark_relay_order": 8,
        "item_count": 0,
        "merkle_root": "b" * 64,
        "created_at": datetime(2026, 8, 1, 12, 0, tzinfo=UTC),
        "expires_at": datetime(2026, 8, 1, 13, 0, tzinfo=UTC),
    }
    session = _Session()
    create_calls: list[str] = []

    async def _create(_session: Any, *, external_system: str) -> tuple[Any, tuple[Any, ...]]:
        create_calls.append(external_system)
        return material, ()

    monkeypatch.setattr(repo, "_create_snapshot", _create)

    header, items = await repo._create_generic_snapshot(  # pyright: ignore[reportPrivateUsage]
        session,  # type: ignore[arg-type]
        external_system="pinvi",
        limit=10,
    )

    assert header == material
    assert items == ()
    assert create_calls == ["pinvi"]
    assert "set_config('lock_timeout'" in session.calls[1][0]
    assert "LIMIT 2" in session.calls[6][0]
    assert "poi_cache_target_reconciliation_requests" in session.calls[6][0]
    assert "FOR UPDATE OF snapshot, item SKIP LOCKED" in session.calls[7][0]
    assert session.calls[7][1]["limit"] == 1000
    assert "FOR UPDATE OF snapshot SKIP LOCKED" in session.calls[8][0]
    assert session.calls[8][1]["limit"] == 100


@pytest.mark.unit
async def test_create_generic_snapshot_rejects_unexpired_unreferenced_copy_over_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    oldest = datetime(2026, 8, 1, 12, 45, tzinfo=UTC)
    session = _Session(
        generic_snapshot_count=2,
        oldest_expires_at=oldest,
        retry_after_seconds=2_701,
    )

    async def _unexpected_create(
        _session: Any,
        *,
        external_system: str,
    ) -> tuple[Any, tuple[Any, ...]]:
        pytest.fail(f"capacity 초과 stream에서 full capture를 호출함: {external_system}")

    monkeypatch.setattr(repo, "_create_snapshot", _unexpected_create)

    with pytest.raises(repo.CacheTargetStreamConflict) as capacity:
        await repo._create_generic_snapshot(  # pyright: ignore[reportPrivateUsage]
            session,  # type: ignore[arg-type]
            external_system="pinvi",
            limit=10,
        )

    assert capacity.value.code == "snapshot_capacity_exceeded"
    assert capacity.value.current == {
        "snapshot_count": 2,
        "snapshot_limit": 2,
        "oldest_expires_at": oldest.isoformat(),
        "retry_after_seconds": 2_701,
    }
    assert "pg_try_advisory_xact_lock" in session.calls[0][0]
    assert "LIMIT 2" in session.calls[6][0]
    assert all("DELETE FROM" not in sql for sql, _params in session.calls)


@pytest.mark.unit
async def test_create_generic_snapshot_fails_fast_when_stream_is_busy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _Session(acquired=False)

    async def _unexpected_create(
        _session: Any,
        *,
        external_system: str,
    ) -> tuple[Any, tuple[Any, ...]]:
        pytest.fail(f"busy stream에서 full capture를 호출함: {external_system}")

    monkeypatch.setattr(repo, "_create_snapshot", _unexpected_create)

    with pytest.raises(repo.CacheTargetStreamConflict) as busy:
        await repo._create_generic_snapshot(  # pyright: ignore[reportPrivateUsage]
            session,  # type: ignore[arg-type]
            external_system="pinvi",
            limit=10,
        )

    assert busy.value.code == "snapshot_busy"
    assert len(session.calls) == 1


@pytest.mark.unit
def test_snapshot_cursor_holds_header_share_lock_during_item_read() -> None:
    assert repo._GET_SNAPSHOT_SQL.rstrip().endswith("FOR SHARE")  # pyright: ignore[reportPrivateUsage]
    item_prune = repo._PRUNE_EXPIRED_SNAPSHOT_ITEMS_SQL  # pyright: ignore[reportPrivateUsage]
    header_prune = repo._PRUNE_EXPIRED_SNAPSHOT_HEADERS_SQL  # pyright: ignore[reportPrivateUsage]
    assert "expires_at <= now()" in item_prune
    assert "NOT EXISTS" in item_prune
    assert "FOR UPDATE OF snapshot, item SKIP LOCKED" in item_prune
    assert "NOT EXISTS" in header_prune
    assert "FOR UPDATE OF snapshot SKIP LOCKED" in header_prune
