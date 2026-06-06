"""Dagster Feature load helper unit test."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest
from krtour.map.infra.feature_repo import FeatureLoadResult

from krtour.map_dagster.etl import load_feature_bundles_for_dagster
from krtour.map_dagster.validation import FeatureAddressValidationSummary


@dataclass(frozen=True)
class _Feature:
    feature_id: str


@dataclass(frozen=True)
class _Bundle:
    feature: _Feature


class _Context:
    def __init__(self) -> None:
        self.metadata: list[dict[str, object]] = []

    def add_output_metadata(self, metadata: dict[str, object]) -> None:
        self.metadata.append(dict(metadata))


class _Client:
    def __init__(self) -> None:
        self.chunks: list[tuple[str, ...]] = []

    async def load_feature_bundles(
        self, bundles: list[_Bundle]
    ) -> FeatureLoadResult:
        self.chunks.append(tuple(bundle.feature.feature_id for bundle in bundles))
        return FeatureLoadResult(
            bundles_total=len(bundles),
            features_inserted=len(bundles),
        )


async def test_load_feature_bundles_for_dagster_chunks_db_load(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundles = [_Bundle(_Feature(f"feature-{index}")) for index in range(5)]
    context = _Context()
    client = _Client()

    def _validate(items: Any) -> FeatureAddressValidationSummary:
        return FeatureAddressValidationSummary(
            total=len(items),
            issue_count=0,
            error_count=0,
            warning_count=0,
            issues=(),
        )

    monkeypatch.setattr(
        "krtour.map_dagster.etl.validate_feature_bundles_address",
        _validate,
    )

    result = await load_feature_bundles_for_dagster(
        context=context,  # type: ignore[arg-type]
        client=client,  # type: ignore[arg-type]
        bundles=bundles,  # type: ignore[arg-type]
        provider="demo",
        dataset_key="places",
        chunk_size=2,
    )

    assert client.chunks == [
        ("feature-0", "feature-1"),
        ("feature-2", "feature-3"),
        ("feature-4",),
    ]
    assert result.feature_ids == tuple(bundle.feature.feature_id for bundle in bundles)
    assert result.load.bundles_total == 5
    assert result.load.features_inserted == 5
    assert context.metadata[-1]["bundles_total"] == 5
