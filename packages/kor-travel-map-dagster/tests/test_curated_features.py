"""curated_features Dagster asset group 단위 테스트."""

from __future__ import annotations

from typing import Any

import pytest
from dagster import build_asset_context

from kortravelmap.dagster.curated_features import (
    CURATED_FEATURE_ASSETS,
    run_curated_feature_candidates,
    run_curated_feature_status_sweep,
    run_curated_pinvi_copy_snapshots,
    run_curated_source_metadata,
)
from kortravelmap.dagster.maintenance import MAINTENANCE_RETRY_POLICY

pytestmark = pytest.mark.filterwarnings(
    "ignore:Parameter `owners` of initializer `SensorDefinition.__init__`"
    ".*:dagster_shared.utils.warnings.BetaWarning"
)


class _Result:
    def __init__(self, metadata: dict[str, object]) -> None:
        self._metadata = metadata

    def as_metadata(self) -> dict[str, object]:
        return self._metadata


class _Client:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def refresh_curated_source_metadata(self) -> _Result:
        self.calls.append("source_metadata")
        return _Result({"sources_checked": 2})

    async def apply_curated_source_rules(self) -> _Result:
        self.calls.append("feature_candidates")
        return _Result({"rules_applied": 3, "inserted_or_updated": 7})

    async def sweep_curated_feature_status(self) -> _Result:
        self.calls.append("status_sweep")
        return _Result({"archived": 1})

    async def materialize_curated_pinvi_copy_snapshots(self) -> _Result:
        self.calls.append("copy_snapshots")
        return _Result(
            {
                "curated_features_total": 5,
                "snapshots_materialized": 4,
            }
        )


def _context(client: _Client) -> Any:
    return build_asset_context(resources={"kor_travel_map_client": client})


async def test_curated_feature_asset_runners_call_client_methods() -> None:
    client = _Client()
    context = _context(client)

    assert await run_curated_source_metadata(context) == {"sources_checked": 2}
    assert await run_curated_feature_candidates(context) == {
        "rules_applied": 3,
        "inserted_or_updated": 7,
    }
    assert await run_curated_feature_status_sweep(context) == {"archived": 1}
    assert await run_curated_pinvi_copy_snapshots(context) == {
        "curated_features_total": 5,
        "snapshots_materialized": 4,
    }

    assert client.calls == [
        "source_metadata",
        "feature_candidates",
        "status_sweep",
        "copy_snapshots",
    ]


def test_curated_feature_assets_have_retry_policy_and_group() -> None:
    assert {asset.key.to_user_string() for asset in CURATED_FEATURE_ASSETS} == {
        "curated_source_metadata",
        "curated_feature_candidates",
        "curated_feature_status_sweep",
        "curated_pinvi_copy_snapshots",
    }
    for asset_def in CURATED_FEATURE_ASSETS:
        assert asset_def.group_names_by_key[asset_def.key] == "curated_features"
        assert asset_def.op.retry_policy == MAINTENANCE_RETRY_POLICY
