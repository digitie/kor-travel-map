"""Generic cache-target snapshot reuse/prune repository 계약 테스트."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest

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
    ) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self._reusable = reusable
        self._acquired = acquired

    async def execute(
        self,
        statement: Any,
        params: dict[str, Any] | None = None,
    ) -> _Result:
        sql = str(statement)
        self.calls.append((sql, params or {}))
        if "pg_try_advisory_xact_lock" in sql:
            return _Result(scalar=self._acquired)
        if "SELECT stream.restore_epoch" in sql:
            return _Result(
                SimpleNamespace(
                    _mapping={
                        "restore_epoch": 3,
                        "high_watermark_relay_order": 8,
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
    assert "SELECT stream.restore_epoch" in session.calls[1][0]
    assert "expires_at > now() + interval '75 minutes'" in session.calls[2][0]
    assert "poi_cache_target_reconciliation_requests" in session.calls[2][0]
    assert "FOR SHARE OF snapshot" in session.calls[2][0]
    assert "poi_cache_target_snapshot_items" in session.calls[3][0]
    assert all("DELETE FROM" not in sql for sql, _params in session.calls)


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
    assert "FOR UPDATE OF snapshot, item SKIP LOCKED" in session.calls[3][0]
    assert session.calls[3][1]["limit"] == 1000
    assert "FOR UPDATE OF snapshot SKIP LOCKED" in session.calls[4][0]
    assert session.calls[4][1]["limit"] == 100


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
