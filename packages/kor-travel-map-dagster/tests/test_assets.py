"""Dagster Feature asset helper unit test."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from types import SimpleNamespace

from dagster import build_asset_context

from kortravelmap.dagster.assets import (
    _record_batches,
    _record_feature_sync_success,
)
from kortravelmap.dagster.etl import AddressFindingObservationReceipt


class _Log:
    def warning(self, message: str) -> None:
        del message

    def info(self, message: str) -> None:
        del message


class _SyncClient:
    def __init__(self) -> None:
        self.sync_calls: list[dict[str, object]] = []
        self.close_calls: list[dict[str, object]] = []

    async def record_sync_success(self, **kwargs: object) -> None:
        self.sync_calls.append(dict(kwargs))

    async def close_stale_address_validation_findings(
        self, **kwargs: object
    ) -> int:
        self.close_calls.append(dict(kwargs))
        return 1


def _context() -> SimpleNamespace:
    return SimpleNamespace(
        resources=SimpleNamespace(
            fetched_at=datetime(2026, 7, 31, tzinfo=UTC)
        ),
        asset_key=SimpleNamespace(to_user_string=lambda: "feature/demo"),
        run_id="run-1",
        log=_Log(),
    )


def _receipt(*, source_observations: int) -> AddressFindingObservationReceipt:
    return AddressFindingObservationReceipt(
        authoritative_snapshot_complete=True,
        source_observations=source_observations,
        findings_observed=0,
        findings_unique=0,
        findings_upserted=0,
        finding_persistence_complete=True,
    )


async def test_record_batches_chunks_iterable_resource() -> None:
    context = build_asset_context(resources={"demo_records": [1, 2, 3, 4, 5]})

    batches = [
        batch
        async for batch in _record_batches(context, "demo_records", batch_size=2)
    ]

    assert batches == [[1, 2], [3, 4], [5]]


async def test_record_batches_chunks_async_iterable_resource() -> None:
    async def _records() -> AsyncIterator[int]:
        for item in range(5):
            yield item

    context = build_asset_context(resources={"demo_records": _records})

    batches = [
        batch
        async for batch in _record_batches(context, "demo_records", batch_size=3)
    ]

    assert batches == [[0, 1, 2], [3, 4]]


async def test_sync_success_without_typed_receipt_does_not_close_findings() -> None:
    client = _SyncClient()

    await _record_feature_sync_success(
        _context(),  # type: ignore[arg-type]
        client,  # type: ignore[arg-type]
        provider="demo",
        dataset_key="places",
        cursor_extra={},
    )

    assert len(client.sync_calls) == 1
    assert client.close_calls == []


async def test_empty_snapshot_receipt_does_not_close_findings() -> None:
    client = _SyncClient()

    await _record_feature_sync_success(
        _context(),  # type: ignore[arg-type]
        client,  # type: ignore[arg-type]
        provider="demo",
        dataset_key="places",
        cursor_extra={},
        observation_receipt=_receipt(source_observations=0),
    )

    assert len(client.sync_calls) == 1
    assert client.close_calls == []


async def test_complete_nonempty_snapshot_receipt_closes_findings_once() -> None:
    client = _SyncClient()

    await _record_feature_sync_success(
        _context(),  # type: ignore[arg-type]
        client,  # type: ignore[arg-type]
        provider="demo",
        dataset_key="places",
        cursor_extra={},
        observation_receipt=_receipt(source_observations=1),
    )

    assert len(client.sync_calls) == 1
    assert len(client.close_calls) == 1
    close_call = client.close_calls[0]
    assert close_call["provider"] == "demo"
    assert close_call["dataset_key"] == "places"
    assert close_call["run_id"] == "run-1"
    assert close_call["receipt"].permits_stale_close is True
