"""Generic cache-target snapshot reuse/prune repository 계약 테스트."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy.exc import DBAPIError

from kortravelmap.core.cache_target_stream import (
    SnapshotMerkleAccumulatorV1,
    SnapshotMerkleRowV1,
)
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

    def __aiter__(self) -> Any:
        async def _rows() -> Any:
            for row in self._rows:
                yield row

        return _rows()

    async def close(self) -> None:
        return None


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
        issued_at: datetime | None = None,
    ) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self._reusable = reusable
        self._issued_at = issued_at or datetime(2026, 8, 20, 12, 0, tzinfo=UTC)
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
        if "FOR SHARE OF material" in sql:
            row = (
                SimpleNamespace(_mapping=self._reusable)
                if self._reusable is not None
                else None
            )
            return _Result(row)
        if "INSERT INTO ops.poi_cache_target_snapshots (" in sql:
            return _Result(
                SimpleNamespace(
                    _mapping={
                        "created_at": self._issued_at,
                        "expires_at": self._issued_at + timedelta(hours=2),
                    }
                )
            )
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
        if "GROUP BY external_system" in sql:
            system = next(self._systems)
            row = (
                SimpleNamespace(_mapping={"external_system": system})
                if system is not None
                else None
            )
            return _Result(row)
        if "SET compacted_at = clock_timestamp()" in sql:
            return _Result(rows=[("m9",)])
        if "DELETE FROM ops.poi_cache_target_snapshot_material_items" in sql:
            return _Result(rows=[("m1", 1), ("m1", 2)])
        if "DELETE FROM ops.poi_cache_target_snapshot_materials" in sql:
            return _Result(rows=[("m1",)])
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
                        "snapshot_table_bytes": 10_000,
                        "snapshot_index_bytes": 2_000,
                        "snapshot_dead_tuples": 17,
                        "snapshot_vacuum_lag_seconds": 900,
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
            return _Result(scalar="5min")
        if "set_config('lock_timeout', '0'" in sql:
            return _Result(scalar="0")
        if (
            "SELECT stream.external_system" in sql
            and "stream.restore_epoch" not in sql
            and "FOR SHARE OF stream" in sql
        ):
            return _Result(SimpleNamespace(_mapping={"external_system": "pinvi"}))
        raise AssertionError(f"unexpected SQL: {sql}")

    async def stream(
        self,
        statement: Any,
        params: dict[str, Any] | None = None,
        *,
        execution_options: dict[str, Any] | None = None,
    ) -> _Result:
        sql = str(statement)
        values = params or {}
        self.calls.append((sql, values))
        assert execution_options == {"stream_results": True, "yield_per": 1_000}
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
        if "FOR SHARE OF stream" in sql or "FOR UPDATE" in sql:
            raise DBAPIError(None, params, _SqlStateError("55P03"), False)
        raise AssertionError(f"unexpected SQL: {sql}")


class _BlockedBuildLockSession:
    async def execute(
        self,
        statement: Any,
        params: dict[str, Any] | None = None,
    ) -> _Result:
        del params
        sql = str(statement)
        if "WHERE request.command_id = :command_id" in sql:
            return _Result()
        if "set_config('lock_timeout'" in sql:
            return _Result(scalar="5s")
        if "FOR UPDATE" in sql:
            await asyncio.Event().wait()
        raise AssertionError(f"unexpected SQL: {sql}")


class _BuildTimeoutSession(_BuildSession):
    async def stream(
        self,
        statement: Any,
        params: dict[str, Any] | None = None,
        *,
        execution_options: dict[str, Any] | None = None,
    ) -> _Result:
        del statement, execution_options
        raise DBAPIError(None, params, _SqlStateError("57014"), False)


class _PersistSession:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows
        self.item_batch_sizes: list[int] = []
        self.receipt_params: list[dict[str, Any]] = []

    async def execute(self, statement: Any, params: Any = None) -> _Result:
        sql = str(statement)
        if "INSERT INTO ops.poi_cache_target_snapshot_materials (" in sql:
            return _Result(
                SimpleNamespace(
                    _mapping={"materialized_at": datetime(2026, 8, 18, tzinfo=UTC)}
                )
            )
        if "INSERT INTO ops.poi_cache_target_snapshots (" in sql:
            self.receipt_params.append(dict(params or {}))
            return _Result(
                SimpleNamespace(
                    _mapping={
                        "created_at": datetime(2026, 8, 18, tzinfo=UTC),
                        "expires_at": datetime(2026, 8, 18, 2, tzinfo=UTC),
                    }
                )
            )
        if "INSERT INTO ops.poi_cache_target_snapshot_material_items (" in sql:
            assert isinstance(params, list)
            self.item_batch_sizes.append(len(params))
            return _Result()
        raise AssertionError(f"unexpected SQL: {sql}")

    async def stream(
        self,
        statement: Any,
        params: dict[str, Any] | None = None,
        *,
        execution_options: dict[str, Any] | None = None,
    ) -> _Result:
        del statement, params
        assert execution_options == {"stream_results": True, "yield_per": 1_000}
        return _Result(rows=self._rows)


class _BlockingStreamResult:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.closed = False

    def __aiter__(self) -> _BlockingStreamResult:
        return self

    async def __anext__(self) -> Any:
        self.started.set()
        await asyncio.Event().wait()
        raise StopAsyncIteration

    async def close(self) -> None:
        self.closed = True


class _BlockingStreamSession:
    def __init__(self, result: _BlockingStreamResult) -> None:
        self.result = result

    async def stream(self, *_args: Any, **_kwargs: Any) -> _BlockingStreamResult:
        return self.result


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
        compacted_materials=1,
        has_more=True,
    )
    select_sql, select_params = session.calls[0]
    assert 'COLLATE "C"' in select_sql
    assert "ORDER BY external_system" in select_sql
    assert select_params == {
        "after_external_system": "system-a",
        "compaction_retention_seconds": repo._MATERIAL_COMPACTION_RETENTION_SECONDS,  # pyright: ignore[reportPrivateUsage]
    }
    # receipt -> compaction 표시 -> item -> orphan material. 순서가 뜻을 갖는다.
    # receipt를 먼저 지워야 material이 orphan이 되고, 표시가 item 삭제보다 앞서야
    # 부분적으로 비운 material이 표시되지 않은 채 남지 않는다.
    assert "DELETE FROM ops.poi_cache_target_snapshots" in session.calls[1][0]
    assert session.calls[1][1] == {"external_system": "system-b", "limit": 100}
    assert "SET compacted_at = clock_timestamp()" in session.calls[2][0]
    assert session.calls[2][1]["limit"] == 100
    assert "DELETE FROM ops.poi_cache_target_snapshot_material_items" in (
        session.calls[3][0]
    )
    assert session.calls[3][1] == {"external_system": "system-b", "limit": 1_000}
    assert "DELETE FROM ops.poi_cache_target_snapshot_materials" in session.calls[4][0]
    assert session.calls[4][1] == {"external_system": "system-b", "limit": 100}
    assert "SELECT EXISTS" in session.calls[5][0]
    assert "count(*)" not in session.calls[5][0]


@pytest.mark.unit
async def test_background_gc_batch_wraps_keyset_once() -> None:
    session = _GcSession([None, "system-a"])

    result = await repo.prune_expired_cache_target_snapshots_batch(
        session,  # type: ignore[arg-type]
        after_external_system="system-z",
    )

    assert result.external_system == "system-a"
    assert session.calls[0][1]["after_external_system"] == "system-z"
    assert session.calls[1][1]["after_external_system"] is None


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
        snapshot_table_bytes=10_000,
        snapshot_index_bytes=2_000,
        snapshot_dead_tuples=17,
        snapshot_vacuum_lag_seconds=900,
    )
    assert len(session.calls) == 1
    assert "WITH snapshot_inventory AS MATERIALIZED" in session.calls[0][0]


@pytest.mark.unit
def test_reuse_identity_filters_material_events_but_snapshot_cursor_stays_global() -> None:
    identity_sql = repo._GET_SNAPSHOT_IDENTITY_SQL  # pyright: ignore[reportPrivateUsage]
    capture_sql = repo._CAPTURE_VIEW_SQL  # pyright: ignore[reportPrivateUsage]
    material_reuse_sql = repo._GET_REUSABLE_MATERIAL_SQL  # pyright: ignore[reportPrivateUsage]

    assert "event.event_type = 'cache_target.state_applied'" in identity_sql
    assert "material_high_watermark_relay_order" in identity_sql
    # identity는 membership을 정하는 값만 준다. replay cursor는 material이 처음
    # 고정될 때 관측한 값이고 material row에 남는다 — 재사용 시점에 다시 재지 않는다.
    assert "AS high_watermark_relay_order" not in identity_sql
    assert "AS high_watermark_relay_order" in capture_sql
    assert "event.event_type = 'cache_target.state_applied'" in capture_sql
    assert "AS material_high_watermark_relay_order" in capture_sql
    assert "LIMIT :capture_limit" not in capture_sql
    assert "ORDER BY head.sort_key" in capture_sql
    assert "material_high_watermark_relay_order" in material_reuse_sql
    assert "material.compacted_at IS NULL" in material_reuse_sql
    assert "FOR SHARE OF material" in material_reuse_sql
    # 재사용이 만료 시각을 물려받지 않으므로 receipt TTL도 참조 여부도 보지 않는다.
    # 그 둘을 다시 넣으면 공유가 한쪽으로만 흐른다.
    assert "expires_at" not in material_reuse_sql
    assert "poi_cache_target_reconciliation_requests" not in material_reuse_sql


@pytest.mark.unit
def test_snapshot_item_ceiling_accepts_exact_limit_and_rejects_limit_plus_one() -> None:
    repo._enforce_snapshot_admission(  # pyright: ignore[reportPrivateUsage]
        item_count=1_000_000,
        material_bytes=536_870_912,
    )

    with pytest.raises(repo.CacheTargetStreamConflict) as exceeded:
        repo._enforce_snapshot_admission(  # pyright: ignore[reportPrivateUsage]
            item_count=1_000_001,
            material_bytes=1,
        )

    assert exceeded.value.code == "snapshot_item_limit_exceeded"
    assert exceeded.value.current == {
        "item_count_lower_bound": 1_000_001,
        "item_limit": 1_000_000,
    }

    with pytest.raises(repo.CacheTargetStreamConflict) as byte_exceeded:
        repo._enforce_snapshot_admission(  # pyright: ignore[reportPrivateUsage]
            item_count=1,
            material_bytes=536_870_913,
        )
    assert byte_exceeded.value.code == "snapshot_byte_limit_exceeded"
    assert byte_exceeded.value.current == {
        "material_bytes_lower_bound": 536_870_913,
        "material_byte_limit": 536_870_912,
    }


@pytest.mark.unit
async def test_snapshot_material_scan_sets_timeout_and_uses_server_cursor() -> None:
    session = _BuildSession()

    scan = await repo._scan_snapshot_material(  # pyright: ignore[reportPrivateUsage]
        session,  # type: ignore[arg-type]
        external_system="pinvi",
    )

    assert scan.header["item_count"] == 0
    assert scan.material_bytes == 0
    assert "set_config('lock_timeout'" in session.calls[0][0]
    assert session.calls[0][1] == {
        "lock_timeout": "5s",
        "statement_timeout": "5min",
    }
    assert "FOR SHARE OF stream" in session.calls[1][0]
    assert "set_config('lock_timeout', '0'" in session.calls[2][0]
    assert "LIMIT :capture_limit" not in session.calls[3][0]
    assert session.calls[3][1] == {"external_system": "pinvi"}


@pytest.mark.unit
async def test_snapshot_barrier_and_build_timeouts_are_typed_conflicts() -> None:
    with pytest.raises(repo.CacheTargetStreamConflict) as barrier:
        await repo._barrier_snapshot_stream(  # pyright: ignore[reportPrivateUsage]
            _BarrierTimeoutSession(),  # type: ignore[arg-type]
            external_system="pinvi",
        )
    assert barrier.value.code == "snapshot_barrier_timeout"

    with pytest.raises(repo.CacheTargetStreamConflict) as first_lock:
        await repo._lock_snapshot_stream_for_build(  # pyright: ignore[reportPrivateUsage]
            _BarrierTimeoutSession(),  # type: ignore[arg-type]
            external_system="pinvi",
        )
    assert first_lock.value.code == "snapshot_barrier_timeout"

    with pytest.raises(repo.CacheTargetStreamConflict) as build:
        await repo._scan_snapshot_material(  # pyright: ignore[reportPrivateUsage]
            _BuildTimeoutSession(),  # type: ignore[arg-type]
            external_system="pinvi",
        )
    assert build.value.code == "snapshot_build_timeout"


@pytest.mark.unit
async def test_reconciliation_seal_deadline_starts_before_first_stream_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(repo, "_SNAPSHOT_BUILD_TIMEOUT_SECONDS", 0.01)

    with pytest.raises(repo.CacheTargetStreamConflict) as timeout:
        await repo.seal_cache_target_reconciliation(
            _BlockedBuildLockSession(),  # type: ignore[arg-type]
            request_id="11111111-1111-4111-8111-111111111111",
            external_system="pinvi",
            consumer_id="pinvi-consumer",
            expected_phase_version=1,
            expected_restore_epoch=1,
            expected_item_count=0,
            expected_merkle_root="a" * 64,
        )

    assert timeout.value.code == "snapshot_build_timeout"


@pytest.mark.unit
async def test_reconciliation_request_deadline_starts_before_first_stream_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(repo, "_SNAPSHOT_BUILD_TIMEOUT_SECONDS", 0.01)

    with pytest.raises(repo.CacheTargetStreamConflict) as timeout:
        await repo.request_cache_target_reconciliation(
            _BlockedBuildLockSession(),  # type: ignore[arg-type]
            command_id=1,
            external_system="pinvi",
            reason="snapshot deadline regression",
        )

    assert timeout.value.code == "snapshot_build_timeout"


@pytest.mark.unit
async def test_snapshot_build_uses_one_cumulative_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _slow_scan(*_args: Any, **_kwargs: Any) -> Any:
        await asyncio.sleep(10)

    monkeypatch.setattr(repo, "_SNAPSHOT_BUILD_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr(repo, "_scan_snapshot_material", _slow_scan)

    with pytest.raises(repo.CacheTargetStreamConflict) as timeout:
        await repo._create_snapshot(  # pyright: ignore[reportPrivateUsage]
            object(),  # type: ignore[arg-type]
            external_system="pinvi",
            receipt_kind="generic",
        )

    assert timeout.value.code == "snapshot_build_timeout"


@pytest.mark.unit
async def test_snapshot_build_does_not_relabel_unrelated_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _failed_scan(*_args: Any, **_kwargs: Any) -> Any:
        raise TimeoutError("unrelated timeout")

    monkeypatch.setattr(repo, "_scan_snapshot_material", _failed_scan)

    with pytest.raises(TimeoutError, match="unrelated timeout"):
        await repo._create_snapshot(  # pyright: ignore[reportPrivateUsage]
            object(),  # type: ignore[arg-type]
            external_system="pinvi",
            receipt_kind="generic",
        )


@pytest.mark.unit
async def test_snapshot_stream_external_cancellation_closes_cursor() -> None:
    result = _BlockingStreamResult()
    session = _BlockingStreamSession(result)

    async def _consume() -> None:
        async for _ in repo._stream_snapshot_capture(  # pyright: ignore[reportPrivateUsage]
            session,  # type: ignore[arg-type]
            external_system="pinvi",
        ):
            pass

    task = asyncio.create_task(_consume())
    await result.started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert result.closed is True


@pytest.mark.unit
async def test_snapshot_persistence_flushes_bounded_batches_and_returns_only_page() -> None:
    accumulator = SnapshotMerkleAccumulatorV1()
    rows: list[Any] = []
    for index in range(1_005):
        target_key = f"target-{index:04d}"
        merkle_row = SnapshotMerkleRowV1(
            external_system="pinvi",
            target_key=target_key,
            state="active",
            source_generation=1,
            source_payload_fingerprint="a" * 64,
        )
        accumulator.add(merkle_row)
        rows.append(
            SimpleNamespace(
                _mapping={
                    "external_system": merkle_row.external_system,
                    "target_key": merkle_row.target_key,
                    "state": merkle_row.state,
                    "source_generation": merkle_row.source_generation,
                    "source_payload_fingerprint": merkle_row.source_payload_fingerprint,
                }
            )
        )
    scan = repo._SnapshotMaterialScan(  # pyright: ignore[reportPrivateUsage]
        header={
            "material_id": "11111111-1111-4111-8111-111111111111",
            "external_system": "pinvi",
            "restore_epoch": 3,
            "high_watermark_relay_order": 8,
            "material_high_watermark_relay_order": 5,
            "item_count": accumulator.count,
            "merkle_root": accumulator.hexdigest(),
        },
        material_bytes=accumulator.material_bytes,
    )
    session = _PersistSession(rows)

    header, returned = await repo._persist_snapshot_material(  # pyright: ignore[reportPrivateUsage]
        session,  # type: ignore[arg-type]
        scan=scan,
        receipt_kind="generic",
        return_limit=7,
    )

    assert header["item_count"] == 1_005
    assert len(returned) == 7
    assert returned[-1].row_number == 7
    assert session.item_batch_sizes == [1_000, 5]
    # receipt는 item을 다 쓰고 검증한 **뒤에** 붙는다. 뒤집으면 검증 실패로 되감기기
    # 전 짧은 창 동안 불완전한 material을 가리키는 receipt가 존재한다.
    assert len(session.receipt_params) == 1
    assert session.receipt_params[0]["receipt_kind"] == "generic"
    assert session.receipt_params[0]["material_id"] == header["material_id"]


@pytest.mark.unit
async def test_create_snapshot_reuses_exact_unreferenced_material(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    issued = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)
    built = {
        "material_id": "11111111-1111-4111-8111-111111111111",
        "snapshot_id": "11111111-1111-4111-8111-111111111111",
        "external_system": "pinvi",
        "restore_epoch": 3,
        "high_watermark_relay_order": 8,
        "item_count": 0,
        "merkle_root": "a" * 64,
    }
    reusable = {
        "material_id": "22222222-2222-4222-8222-222222222222",
        "external_system": "pinvi",
        "restore_epoch": 3,
        "material_high_watermark_relay_order": 5,
        "high_watermark_relay_order": 6,
        "item_count": 0,
        "merkle_root": "a" * 64,
    }
    session = _Session(reusable, issued_at=issued)
    create_calls: list[tuple[str, str, int]] = []

    async def _create(
        _session: Any, *, external_system: str, receipt_kind: str, return_limit: int
    ) -> tuple[Any, tuple[Any, ...]]:
        create_calls.append((external_system, receipt_kind, return_limit))
        return built, ()

    monkeypatch.setattr(repo, "_create_snapshot", _create)

    header, items = await repo._create_generic_snapshot(  # pyright: ignore[reportPrivateUsage]
        session,  # type: ignore[arg-type]
        external_system="pinvi",
        limit=10,
    )

    assert items == ()
    assert create_calls == []
    assert header["material_id"] == reusable["material_id"]
    assert header["receipt_kind"] == "generic"
    # 재사용해도 receipt는 새로 만든다 — 만료 시각을 물려받지 않는다.
    assert header["snapshot_id"] != reusable["material_id"]
    assert header["created_at"] == issued
    assert header["expires_at"] == issued + timedelta(hours=2)
    # cursor는 material이 들고 온 값 그대로다. 재사용 시점에 다시 재면 그 사이에 낀
    # 비-membership event를 consumer가 건너뛴다.
    assert header["high_watermark_relay_order"] == 6
    assert "pg_try_advisory_xact_lock" in session.calls[0][0]
    assert "set_config('lock_timeout'" in session.calls[1][0]
    assert "FOR SHARE OF stream" in session.calls[2][0]
    assert "SELECT stream.restore_epoch" in session.calls[4][0]
    assert "FOR SHARE OF material" in session.calls[5][0]
    assert session.calls[5][1]["material_high_watermark_relay_order"] == 5
    assert "INSERT INTO ops.poi_cache_target_snapshots (" in session.calls[6][0]
    assert "poi_cache_target_snapshot_material_items" in session.calls[7][0]
    assert session.calls[7][1]["material_id"] == reusable["material_id"]
    assert all("DELETE FROM" not in sql for sql, _params in session.calls)


@pytest.mark.unit
async def test_handoff_ttl_floor_guards_the_build_path_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """handoff floor는 빌드 경로에만 걸린다.

    앞판에는 "재사용 후보의 잔여 TTL이 75분 미만이면 다시 만든다"는 분기가 있었다.
    header 하나가 material과 receipt를 겸해 재사용이 만료 시각까지 물려받았기
    때문이다. 이제 재사용도 새 receipt를 만들어 언제나 full TTL이라 그 분기 자체가
    없다 — 남은 것은 "두 번 scan + 대량 INSERT가 floor를 먹었는가"뿐이다.
    """

    built = {
        "material_id": "21111111-1111-4111-8111-111111111111",
        "snapshot_id": "21111111-1111-4111-8111-111111111111",
        "external_system": "pinvi",
        "restore_epoch": 3,
        "high_watermark_relay_order": 8,
        "item_count": 0,
        "merkle_root": "a" * 64,
        "created_at": datetime(2026, 8, 1, 12, 0, tzinfo=UTC),
        "expires_at": datetime(2026, 8, 1, 12, 30, tzinfo=UTC),
    }
    session = _Session(return_ttls=[False])

    async def _create(
        _session: Any, *, external_system: str, receipt_kind: str, return_limit: int
    ) -> tuple[Any, tuple[Any, ...]]:
        del external_system, receipt_kind, return_limit
        return built, ()

    monkeypatch.setattr(repo, "_create_snapshot", _create)

    with pytest.raises(repo.CacheTargetStreamConflict) as short:
        await repo._create_generic_snapshot(  # pyright: ignore[reportPrivateUsage]
            session,  # type: ignore[arg-type]
            external_system="pinvi",
            limit=10,
        )

    assert short.value.code == "snapshot_ttl_too_short"
    receipt_sql = repo._INSERT_RECEIPT_SQL  # pyright: ignore[reportPrivateUsage]
    assert "clock_timestamp() AS issued_at" in receipt_sql
    assert "issued_at, issued_at + interval '2 hours'" in receipt_sql


@pytest.mark.unit
async def test_create_generic_snapshot_prunes_only_before_full_capture(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    built = {
        "material_id": "33333333-3333-4333-8333-333333333333",
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
    create_calls: list[tuple[str, str, int]] = []

    async def _create(
        _session: Any, *, external_system: str, receipt_kind: str, return_limit: int
    ) -> tuple[Any, tuple[Any, ...]]:
        create_calls.append((external_system, receipt_kind, return_limit))
        return built, ()

    monkeypatch.setattr(repo, "_create_snapshot", _create)

    header, items = await repo._create_generic_snapshot(  # pyright: ignore[reportPrivateUsage]
        session,  # type: ignore[arg-type]
        external_system="pinvi",
        limit=10,
    )

    assert header == built
    assert items == ()
    assert create_calls == [("pinvi", "generic", 10)]
    assert "set_config('lock_timeout'" in session.calls[1][0]
    assert "LIMIT 2" in session.calls[6][0]
    assert "poi_cache_target_snapshot_materials" in session.calls[6][0]
    assert "FOR UPDATE OF snapshot SKIP LOCKED" in session.calls[7][0]
    assert session.calls[7][1]["limit"] == 100
    assert "SET compacted_at = clock_timestamp()" in session.calls[8][0]
    assert "FOR UPDATE OF material, item SKIP LOCKED" in session.calls[9][0]
    assert session.calls[9][1]["limit"] == 1000
    assert "FOR UPDATE OF material SKIP LOCKED" in session.calls[10][0]
    assert session.calls[10][1]["limit"] == 100


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
        return_limit: int,
    ) -> tuple[Any, tuple[Any, ...]]:
        pytest.fail(
            "capacity 초과 stream에서 full capture를 호출함: "
            f"{external_system}/{return_limit}"
        )

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
        return_limit: int,
    ) -> tuple[Any, tuple[Any, ...]]:
        pytest.fail(
            f"busy stream에서 full capture를 호출함: {external_system}/{return_limit}"
        )

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
    # receipt만 잠그면 compaction이 item을 지우는 사이에 부분 page가 나간다.
    # material까지 함께 잠가야 정상 page 또는 410 중 하나만 보인다.
    assert repo._GET_SNAPSHOT_SQL.rstrip().endswith(  # pyright: ignore[reportPrivateUsage]
        "FOR SHARE OF snapshot, material"
    )
    item_prune = repo._PRUNE_ORPHANED_MATERIAL_ITEMS_SQL  # pyright: ignore[reportPrivateUsage]
    material_prune = repo._PRUNE_ORPHANED_MATERIALS_SQL  # pyright: ignore[reportPrivateUsage]
    header_prune = repo._PRUNE_EXPIRED_SNAPSHOT_HEADERS_SQL  # pyright: ignore[reportPrivateUsage]
    assert "expires_at <= now()" in header_prune
    assert "NOT EXISTS" in header_prune
    assert "FOR UPDATE OF snapshot SKIP LOCKED" in header_prune
    # item/material은 만료가 아니라 **orphan 여부**로 고른다. receipt가 하나라도
    # 붙어 있으면 그 material은 아직 누군가의 것이다.
    assert "expires_at" not in item_prune
    assert "FOR UPDATE OF material, item SKIP LOCKED" in item_prune
    assert "FOR UPDATE OF material SKIP LOCKED" in material_prune
    assert "poi_cache_target_snapshot_material_items" in material_prune
