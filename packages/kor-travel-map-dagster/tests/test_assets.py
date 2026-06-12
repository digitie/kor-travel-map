"""Dagster Feature asset helper unit test."""

from __future__ import annotations

from collections.abc import AsyncIterator

from dagster import build_asset_context

from kortravelmap.dagster.assets import _record_batches


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
