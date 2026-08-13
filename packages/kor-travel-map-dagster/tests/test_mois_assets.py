"""MOIS 대용량 authoritative load의 bounded-batch 경계를 검증한다."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import pytest
from kortravelmap.infra.feature_repo import FeatureLoadResult

from kortravelmap.dagster import assets
from kortravelmap.dagster.etl import (
    AddressFindingObservationReceipt,
    DagsterFeatureLoadResult,
)
from kortravelmap.dagster.validation import FeatureAddressValidationSummary


@dataclass(frozen=True)
class _Bundle:
    batch: int
    ordinal: int


async def test_mois_asset_streams_transformed_batches_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = object()
    client = object()
    transformed_sizes: list[int] = []
    consumed_batches: list[tuple[int, ...]] = []
    sync_calls: list[tuple[str, str]] = []

    async def _record_batches(*args: Any, **kwargs: Any) -> Any:
        del args, kwargs
        for batch in ([1, 2], [3, 4], [5]):
            yield batch

    async def _to_bundles(records: list[int], **kwargs: Any) -> list[_Bundle]:
        del kwargs
        transformed_sizes.append(len(records))
        return [
            _Bundle(batch=records[0], ordinal=ordinal)
            for ordinal, _record in enumerate(records)
        ]

    async def _resource_value(
        _context: object, key: str, *, default: object = None
    ) -> object:
        del _context
        return {"mois_dataset_key": "bulk", "strict_address": "off"}.get(
            key, default
        )

    async def _load_batches(**kwargs: Any) -> DagsterFeatureLoadResult:
        async for batch in kwargs["batches"]:
            consumed_batches.append(tuple(item.batch for item in batch))
        return DagsterFeatureLoadResult(
            provider="python-mois-api",
            dataset_key="bulk",
            feature_ids=(),
            load=FeatureLoadResult(bundles_total=5),
            address_validation=FeatureAddressValidationSummary(
                total=5,
                issue_count=0,
                error_count=0,
                warning_count=0,
                issues=(),
            ),
            observation_receipt=AddressFindingObservationReceipt(
                authoritative_snapshot_complete=True,
                source_observations=5,
                findings_observed=0,
                findings_unique=0,
                findings_upserted=0,
                finding_persistence_complete=True,
            ),
        )

    async def _record_success(
        _context: object,
        _client: object,
        *,
        provider: str,
        dataset_key: str,
        **kwargs: Any,
    ) -> None:
        del _context, _client, kwargs
        sync_calls.append((provider, dataset_key))

    monkeypatch.setattr(assets, "_record_batches", _record_batches)
    monkeypatch.setattr(assets, "license_records_to_bundles", _to_bundles)
    monkeypatch.setattr(assets, "_resource_value", _resource_value)
    monkeypatch.setattr(assets, "_resource_object", lambda *_args: client)
    monkeypatch.setattr(assets, "_reverse_geocoder", lambda *_args: object())
    monkeypatch.setattr(
        assets,
        "_fetched_at",
        lambda *_args: _async_value(datetime(2026, 8, 14, tzinfo=UTC)),
    )
    monkeypatch.setattr(
        assets, "load_feature_bundle_batches_for_dagster", _load_batches
    )
    monkeypatch.setattr(assets, "_record_feature_sync_success", _record_success)

    result = await assets.run_feature_place_mois_licenses(context)  # type: ignore[arg-type]

    assert transformed_sizes == [2, 2, 1]
    assert consumed_batches == [(1, 1), (3, 3), (5,)]
    assert sync_calls == [(assets.MOIS_PROVIDER_NAME, "bulk")]
    assert result.load.bundles_total == 5


async def _async_value(value: Any) -> Any:
    return value
