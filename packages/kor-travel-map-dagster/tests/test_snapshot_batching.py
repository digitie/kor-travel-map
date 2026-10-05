"""snapshot 변환은 소비 속도에 맞추고 실패를 sync 성공으로 기록하지 않는다."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from kortravelmap.dagster import assets


@pytest.mark.asyncio
async def test_museum_snapshot_is_bounded_and_preserves_every_record(monkeypatch: Any) -> None:
    produced = 0
    consumed = 0
    sizes: list[int] = []

    async def records() -> AsyncIterator[int]:
        nonlocal produced
        for index in range(10001):
            produced += 1
            assert produced - consumed <= 100
            yield index

    context = SimpleNamespace(
        resources=SimpleNamespace(
            standard_museums=records(),
            fetched_at=datetime.now(UTC),
            reverse_geocoder=None,
        )
    )

    async def convert(items: Any, **kwargs: Any) -> Any:
        sizes.append(len(items))
        return items

    async def load(context: Any, *, batches: Any, **kwargs: Any) -> Any:
        nonlocal consumed
        async for batch in batches:
            assert batch == list(range(consumed, consumed + len(batch)))
            consumed += len(batch)
        return consumed

    monkeypatch.setattr(assets, "museums_to_bundles", convert)
    monkeypatch.setattr(assets, "_load_snapshot_batches", load)
    assert await assets.run_feature_place_standard_museums(context) == 10001
    assert sizes == [100] * 100 + [1]


@pytest.mark.asyncio
async def test_failed_snapshot_never_records_sync_success(monkeypatch: Any) -> None:
    calls: list[object] = []

    async def load(**kwargs: Any) -> Any:
        raise RuntimeError("transaction rolled back")

    async def record(*args: Any, **kwargs: Any) -> None:
        calls.append(kwargs)

    async def batches() -> AsyncIterator[list[object]]:
        yield []

    context = SimpleNamespace(
        resources=SimpleNamespace(kor_travel_map_client=object(), strict_address="off")
    )
    monkeypatch.setattr(assets, "load_feature_bundle_batches_for_dagster", load)
    monkeypatch.setattr(assets, "_record_feature_sync_success", record)
    with pytest.raises(RuntimeError, match="transaction rolled back"):
        await assets._load_snapshot_batches(
            context, provider="demo", dataset_key="demo", batches=batches()
        )
    assert not calls
