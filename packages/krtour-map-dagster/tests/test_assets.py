"""Dagster Feature asset helper unit test."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from dagster import build_asset_context
from krtour.map.infra.feature_repo import FeatureLoadResult
from krtour.map.providers.tripmate_agent import (
    DATASET_KEY_YOUTUBE_PLACE_CANDIDATES,
    TRIPMATE_AGENT_PROVIDER_NAME,
    TRIPMATE_AGENT_SOURCE_ENTITY_TYPE,
)

from krtour.map_dagster.assets import (
    _record_batches,
    run_feature_place_tripmate_agent_youtube,
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


class _FakeTripmateClient:
    """`load_feature_bundles` + `deactivate_features_by_source_entity_ids`만 가진 fake."""

    def __init__(self) -> None:
        self.loaded_feature_ids: list[str] = []
        self.deactivate_call: dict[str, Any] | None = None

    async def load_feature_bundles(self, bundles: Any) -> FeatureLoadResult:
        items = list(bundles)
        self.loaded_feature_ids.extend(b.feature.feature_id for b in items)
        return FeatureLoadResult(bundles_total=len(items), features_inserted=len(items))

    async def deactivate_features_by_source_entity_ids(
        self,
        *,
        provider: str,
        dataset_key: str,
        source_entity_type: str,
        source_entity_ids: set[str],
    ) -> int:
        self.deactivate_call = {
            "provider": provider,
            "dataset_key": dataset_key,
            "source_entity_type": source_entity_type,
            "ids": set(source_entity_ids),
        }
        return len(source_entity_ids)


def _export_item(operation: str, entity_id: str) -> dict[str, Any]:
    return {
        "operation": operation,
        "candidate_id": entity_id,
        "place": {
            "name": f"장소-{entity_id}",
            "category_code_suggestion": "01020300",
            "longitude": 126.7958,
            "latitude": 33.5563,
            "address": {"legal_dong_code": "5011025624"},
        },
        "source_record": {"source_entity_id": entity_id},
    }


async def test_tripmate_asset_loads_upserts_and_deactivates_closures() -> None:
    records = [
        _export_item("upsert", "1"),
        _export_item("reject", "2"),
        _export_item("tombstone", "3"),
    ]
    client = _FakeTripmateClient()
    context = build_asset_context(
        resources={
            "tripmate_agent_youtube_features": records,
            "krtour_map_client": client,
            "fetched_at": datetime(2026, 6, 11, tzinfo=UTC),
            "strict_address": False,
        }
    )

    result = await run_feature_place_tripmate_agent_youtube(context)

    # upsert 1건만 적재되고, reject/tombstone 2건은 비활성화 경로로 간다.
    assert len(client.loaded_feature_ids) == 1
    assert client.deactivate_call is not None
    assert client.deactivate_call["ids"] == {"2", "3"}
    assert client.deactivate_call["provider"] == TRIPMATE_AGENT_PROVIDER_NAME
    assert client.deactivate_call["dataset_key"] == DATASET_KEY_YOUTUBE_PLACE_CANDIDATES
    assert (
        client.deactivate_call["source_entity_type"]
        == TRIPMATE_AGENT_SOURCE_ENTITY_TYPE
    )
    assert result.deactivated == 2


async def test_tripmate_asset_no_closures_skips_deactivate() -> None:
    records = [_export_item("upsert", "1")]
    client = _FakeTripmateClient()
    context = build_asset_context(
        resources={
            "tripmate_agent_youtube_features": records,
            "krtour_map_client": client,
            "fetched_at": datetime(2026, 6, 11, tzinfo=UTC),
            "strict_address": False,
        }
    )

    result = await run_feature_place_tripmate_agent_youtube(context)

    assert client.deactivate_call is None
    assert result.deactivated == 0
