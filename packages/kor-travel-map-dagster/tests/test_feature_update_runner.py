"""feature update request Dagster runner 단위 테스트."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast

import pytest
from kortravelmap.infra.feature_update_executor import ProviderDatasetRefreshScope
from kortravelmap.settings import KorTravelMapSettings

from kortravelmap.dagster.feature_update_runner import (
    FeatureUpdateAssetRunner,
    FeatureUpdateRunnerSpec,
    RunnerResources,
)


@dataclass(frozen=True)
class _FakeAssetResult:
    provider: str
    dataset_key: str
    feature_ids: tuple[str, ...]

    def as_metadata(self) -> dict[str, object]:
        return {
            "provider": self.provider,
            "dataset_key": self.dataset_key,
            "feature_ids": list(self.feature_ids),
            "features_inserted": 1,
            "features_updated": 1,
        }


class _Log:
    def info(self, *_args: object, **_kwargs: object) -> None:
        return None

    def warning(self, *_args: object, **_kwargs: object) -> None:
        return None


def _scope(
    *,
    provider: str = "demo",
    dataset_key: str = "places",
) -> ProviderDatasetRefreshScope:
    return ProviderDatasetRefreshScope(
        request_id="11111111-1111-4111-8111-111111111111",
        provider=provider,
        dataset_key=dataset_key,
        scope_type="provider_dataset",
        request_scope={
            "type": "provider_dataset",
            "provider": provider,
            "dataset_key": dataset_key,
        },
        update_policy={"prevent_provider_reactivation": True},
        feature_ids=("feature-1",),
        feature_count=1,
        prevent_provider_reactivation=True,
    )


async def test_feature_update_asset_runner_dispatches_asset_spec() -> None:
    called: list[dict[str, object]] = []

    async def _run(context: object) -> _FakeAssetResult:
        context_any = cast(Any, context)
        resources = cast(Any, context_any.resources)
        called.append(
            {
                "records": resources.demo_records,
                "asset_key": context_any.asset_key.to_user_string(),
            }
        )
        context_any.add_output_metadata({"seen": True})
        return _FakeAssetResult(
            provider="demo",
            dataset_key="places",
            feature_ids=("feature-1", "feature-2"),
        )

    def _resources(
        _settings: KorTravelMapSettings,
        scope: ProviderDatasetRefreshScope,
    ) -> RunnerResources:
        assert scope.request_id == "11111111-1111-4111-8111-111111111111"
        return RunnerResources({"demo_records": ("a", "b")})

    runner = FeatureUpdateAssetRunner(
        common_resources={
            "kor_travel_map_client": object(),
            "reverse_geocoder": None,
            "fetched_at": datetime(2026, 6, 28, 12, 0, tzinfo=UTC),
            "strict_address": "off",
        },
        log=_Log(),
        settings_factory=lambda: cast(KorTravelMapSettings, object()),
        specs=(
            FeatureUpdateRunnerSpec(
                provider="demo",
                dataset_keys=frozenset({"places"}),
                run=_run,
                resources=_resources,
                asset_key="feature_demo_places",
            ),
        ),
    )

    result = await runner(object(), _scope())

    assert called == [
        {"records": ("a", "b"), "asset_key": "feature_demo_places"}
    ]
    assert result.provider == "demo"
    assert result.dataset_key == "places"
    assert result.loaded_feature_ids == ("feature-1", "feature-2")
    assert result.loaded_count == 2
    assert result.metadata is not None
    assert result.metadata["features_inserted"] == 1


async def test_feature_update_asset_runner_rejects_unsupported_dataset() -> None:
    runner = FeatureUpdateAssetRunner(
        common_resources={
            "kor_travel_map_client": object(),
            "reverse_geocoder": None,
            "fetched_at": None,
            "strict_address": "off",
        },
        log=_Log(),
        settings_factory=lambda: cast(KorTravelMapSettings, object()),
        specs=(),
    )

    with pytest.raises(RuntimeError, match="지원하지 않는 provider/dataset"):
        await runner(object(), _scope(provider="unknown", dataset_key="missing"))
