"""feature update request Dagster runner 단위 테스트."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast

import pytest
from kortravelmap.api.provider_catalog import catalog_refreshable_entries
from kortravelmap.infra.feature_update_executor import ProviderDatasetRefreshScope
from kortravelmap.providers.airkorea import AIRKOREA_PROVIDER_NAME, DATASET_KEY_STATIONS
from kortravelmap.providers.datagokr_file_data import (
    DATAGOKR_FILEDATA_DATASETS,
    DATAGOKR_FILEDATA_PROVIDER_NAME,
)
from kortravelmap.providers.mois import (
    DATASET_KEY_BULK,
    DATASET_KEY_CLOSED,
    DATASET_KEY_DETAIL,
    DATASET_KEY_HISTORY,
)
from kortravelmap.providers.mois import PROVIDER_NAME as MOIS_PROVIDER_NAME
from kortravelmap.providers.opinet import OPINET_PROVIDER_NAME, OPINET_STATION_DATASET_KEY
from kortravelmap.settings import KorTravelMapSettings

from kortravelmap.dagster.feature_update_runner import (
    FeatureUpdateAssetRunner,
    FeatureUpdateRunnerSpec,
    RunnerResources,
)
from kortravelmap.dagster.provider_fetchers import ProviderCredentialMissing


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


def test_default_runner_accepts_airkorea_stations_alias() -> None:
    runner = FeatureUpdateAssetRunner(
        common_resources={
            "kor_travel_map_client": object(),
            "reverse_geocoder": None,
            "fetched_at": None,
            "strict_address": "off",
        },
        log=_Log(),
        settings_factory=lambda: cast(KorTravelMapSettings, object()),
    )

    spec = runner._spec_for_scope(  # noqa: SLF001 - default dispatch contract 회귀 테스트
        _scope(provider=AIRKOREA_PROVIDER_NAME, dataset_key=DATASET_KEY_STATIONS)
    )

    assert spec.asset_key == "feature_weather_airkorea_air_quality"


def test_default_runner_accepts_only_mois_bulk_dataset() -> None:
    runner = FeatureUpdateAssetRunner(
        common_resources={
            "kor_travel_map_client": object(),
            "reverse_geocoder": None,
            "fetched_at": None,
            "strict_address": "off",
        },
        log=_Log(),
        settings_factory=lambda: cast(KorTravelMapSettings, object()),
    )

    bulk_spec = runner._spec_for_scope(  # noqa: SLF001 - default dispatch contract 회귀 테스트
        _scope(provider=MOIS_PROVIDER_NAME, dataset_key=DATASET_KEY_BULK)
    )
    assert bulk_spec.asset_key == "feature_place_mois_licenses"

    for dataset_key in (DATASET_KEY_HISTORY, DATASET_KEY_CLOSED, DATASET_KEY_DETAIL):
        with pytest.raises(RuntimeError, match="지원하지 않는 provider/dataset"):
            runner._spec_for_scope(  # noqa: SLF001 - default dispatch contract 회귀 테스트
                _scope(provider=MOIS_PROVIDER_NAME, dataset_key=dataset_key)
            )


def test_default_runner_accepts_datagokr_file_data_datasets() -> None:
    runner = FeatureUpdateAssetRunner(
        common_resources={
            "kor_travel_map_client": object(),
            "reverse_geocoder": None,
            "fetched_at": None,
            "strict_address": "off",
        },
        log=_Log(),
        settings_factory=lambda: cast(KorTravelMapSettings, object()),
    )

    for dataset_key in DATAGOKR_FILEDATA_DATASETS:
        spec = runner._spec_for_scope(  # noqa: SLF001 - default dispatch contract 회귀 테스트
            _scope(provider=DATAGOKR_FILEDATA_PROVIDER_NAME, dataset_key=dataset_key)
        )
        assert spec.asset_key == "feature_place_datagokr_file_data"


def test_default_runner_supports_all_catalog_refreshable_entries() -> None:
    runner = FeatureUpdateAssetRunner(
        common_resources={
            "kor_travel_map_client": object(),
            "reverse_geocoder": None,
            "fetched_at": None,
            "strict_address": "off",
        },
        log=_Log(),
        settings_factory=lambda: cast(KorTravelMapSettings, object()),
    )
    supported = {
        (spec.provider, dataset_key)
        for spec in runner._specs  # noqa: SLF001 - catalog/runner drift 회귀 테스트
        for dataset_key in spec.dataset_keys
    }
    refreshable = {
        (entry.provider, entry.dataset_key) for entry in catalog_refreshable_entries()
    }

    assert sorted(refreshable - supported) == []


async def test_opinet_missing_key_fails_before_provider_client_auth_error() -> None:
    runner = FeatureUpdateAssetRunner(
        common_resources={
            "kor_travel_map_client": object(),
            "reverse_geocoder": None,
            "fetched_at": None,
            "strict_address": "off",
        },
        log=_Log(),
        settings_factory=lambda: KorTravelMapSettings.model_construct(
            opinet_api_key=None
        ),
    )

    with pytest.raises(ProviderCredentialMissing, match="KOR_TRAVEL_MAP_OPINET_API_KEY"):
        await runner(
            object(),
            _scope(provider=OPINET_PROVIDER_NAME, dataset_key=OPINET_STATION_DATASET_KEY),
        )
