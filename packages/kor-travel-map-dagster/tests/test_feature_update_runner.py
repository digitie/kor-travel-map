"""feature update request Dagster runner 단위 테스트."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast

import pytest
from kortravelmap.api.provider_catalog import catalog_refreshable_entries
from kortravelmap.client import AsyncKorTravelMapClient
from kortravelmap.infra.feature_update_executor import (
    ProviderDatasetRefreshFailure,
    ProviderDatasetRefreshScope,
)
from kortravelmap.providers.airkorea import AIRKOREA_PROVIDER_NAME, DATASET_KEY_STATIONS
from kortravelmap.providers.datagokr_file_data import (
    DATAGOKR_FILEDATA_DATASETS,
    DATAGOKR_FILEDATA_PROVIDER_NAME,
)
from kortravelmap.providers.kma import (
    KMA_PROVIDER_NAME,
    KMA_SHORT_FORECAST_DATASET_KEY,
)
from kortravelmap.providers.knps import PROVIDER_NAME as KNPS_PROVIDER_NAME
from kortravelmap.providers.mois import (
    DATASET_KEY_BULK,
    DATASET_KEY_CLOSED,
    DATASET_KEY_DETAIL,
    DATASET_KEY_HISTORY,
)
from kortravelmap.providers.mois import PROVIDER_NAME as MOIS_PROVIDER_NAME
from kortravelmap.providers.opinet import (
    OPINET_PRICE_DATASET_KEY,
    OPINET_PROVIDER_NAME,
    OPINET_STATION_DATASET_KEY,
)
from kortravelmap.settings import KorTravelMapSettings

from kortravelmap.dagster import feature_update_runner as runner_mod
from kortravelmap.dagster.assets import FEATURE_LOAD_ASSETS
from kortravelmap.dagster.feature_update_runner import (
    FeatureUpdateAssetRunner,
    FeatureUpdateRunnerSpec,
    RunnerResources,
)
from kortravelmap.dagster.kma_weather import KMA_WEATHER_ASSETS
from kortravelmap.dagster.mcst_features import MCST_FEATURE_ASSETS
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
    scope_type: str = "provider_dataset",
    sync_scope: str | None = None,
) -> ProviderDatasetRefreshScope:
    request_scope: dict[str, object]
    if scope_type == "provider_dataset":
        request_scope = {
            "type": "provider_dataset",
            "provider": provider,
            "dataset_key": dataset_key,
        }
        if sync_scope is not None:
            request_scope["sync_scope"] = sync_scope
    elif scope_type == "center_radius":
        request_scope = {
            "type": "center_radius",
            "center": {"lon": 127.0, "lat": 37.0},
            "radius_km": 1.0,
        }
    else:
        raise ValueError(f"unsupported test scope_type: {scope_type}")
    return ProviderDatasetRefreshScope(
        request_id="11111111-1111-4111-8111-111111111111",
        provider=provider,
        dataset_key=dataset_key,
        scope_type=scope_type,
        request_scope=request_scope,
        update_policy={"prevent_provider_reactivation": True},
        feature_ids=("feature-1",),
        feature_count=1,
        prevent_provider_reactivation=True,
        sync_scope=sync_scope,
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
    assert result.metadata["seen"] is True


async def test_feature_update_asset_runner_direct_raw_path_has_zero_tracking() -> None:
    class _ForbiddenGuard:
        def __init__(self) -> None:
            self.ensure_calls = 0

        async def ensure(self) -> None:
            self.ensure_calls += 1
            raise AssertionError("direct raw runner가 Dagster operation tracking을 호출함")

    guard = _ForbiddenGuard()

    async def _raw(context: object) -> _FakeAssetResult:
        assert cast(Any, context).resources.feature_operation_guard is guard
        return _FakeAssetResult(
            provider="demo",
            dataset_key="places",
            feature_ids=("feature-1",),
        )

    runner = FeatureUpdateAssetRunner(
        common_resources={"feature_operation_guard": guard},
        log=_Log(),
        settings_factory=lambda: cast(KorTravelMapSettings, object()),
        specs=(
            FeatureUpdateRunnerSpec(
                provider="demo",
                dataset_keys=frozenset({"places"}),
                run=_raw,
                resources=lambda _settings, _scope: RunnerResources({}),
                asset_key="feature_demo_places",
            ),
        ),
    )

    result = await runner(object(), _scope())

    assert result.status == "done"
    assert guard.ensure_calls == 0


def test_default_specs_reference_only_module_raw_symbols() -> None:
    public_wrappers = {
        cast(Any, asset_def.op.compute_fn).decorated_fn
        for asset_def in (
            *FEATURE_LOAD_ASSETS,
            *KMA_WEATHER_ASSETS,
            *MCST_FEATURE_ASSETS,
        )
    }

    assert runner_mod._DEFAULT_SPECS  # noqa: SLF001 - production dispatch contract
    for spec in runner_mod._DEFAULT_SPECS:  # noqa: SLF001
        assert spec.run not in public_wrappers
        assert getattr(runner_mod, spec.run.__name__, None) is spec.run
        assert spec.run.__name__.startswith(("run_feature_", "_run_kma_grid_"))


async def test_feature_update_asset_runner_closes_resources_when_bind_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    teardown_calls = 0

    async def _run(_context: object) -> _FakeAssetResult:
        raise AssertionError("transaction bind 실패 뒤 asset을 실행하면 안 된다.")

    def _teardown() -> None:
        nonlocal teardown_calls
        teardown_calls += 1

    def _resources(
        _settings: KorTravelMapSettings,
        _scope: ProviderDatasetRefreshScope,
    ) -> RunnerResources:
        return RunnerResources({}, (_teardown,))

    async def _fail_bind(
        _client: AsyncKorTravelMapClient,
        _session: object,
    ) -> AsyncKorTravelMapClient:
        raise RuntimeError("simulated transaction bind failure")

    monkeypatch.setattr(runner_mod, "_bind_client_to_session", _fail_bind)
    runner = FeatureUpdateAssetRunner(
        common_resources={
            "kor_travel_map_client": AsyncKorTravelMapClient(cast(Any, object())),
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

    with pytest.raises(ProviderDatasetRefreshFailure) as exc_info:
        await runner(object(), _scope(sync_scope="dataset_wide"))

    assert teardown_calls == 1
    failure = exc_info.value
    assert failure.provider == "demo"
    assert failure.dataset_key == "places"
    assert failure.sync_scope == "default"
    assert str(failure) == "provider refresh transaction binding failed"
    assert isinstance(failure.__cause__, RuntimeError)


async def test_feature_update_asset_runner_types_resource_initialization_failure() -> None:
    async def _run(_context: object) -> _FakeAssetResult:
        raise AssertionError("resource 초기화 실패 뒤 asset을 실행하면 안 된다.")

    def _resources(
        _settings: KorTravelMapSettings,
        _scope: ProviderDatasetRefreshScope,
    ) -> RunnerResources:
        raise RuntimeError("credential missing")

    runner = FeatureUpdateAssetRunner(
        common_resources={},
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

    with pytest.raises(ProviderDatasetRefreshFailure) as exc_info:
        await runner(cast(Any, object()), _scope(sync_scope="dataset_wide"))

    failure = exc_info.value
    assert failure.provider == "demo"
    assert failure.dataset_key == "places"
    assert failure.sync_scope == "default"
    assert str(failure) == "provider refresh resource initialization failed"


async def test_kma_grid_generic_run_failure_uses_effective_external_system_scope() -> None:
    async def _run(_context: object) -> _FakeAssetResult:
        raise RuntimeError("KMA provider failed")

    runner = FeatureUpdateAssetRunner(
        common_resources={},
        log=_Log(),
        settings_factory=lambda: cast(KorTravelMapSettings, object()),
        specs=(
            FeatureUpdateRunnerSpec(
                provider=KMA_PROVIDER_NAME,
                dataset_keys=frozenset({KMA_SHORT_FORECAST_DATASET_KEY}),
                run=_run,
                resources=lambda _settings, _scope: RunnerResources({}),
                asset_key="feature_weather_kma_grid_dispatch",
                sync_state_failure_scope=runner_mod._kma_grid_effective_sync_scope,
            ),
        ),
    )

    with pytest.raises(ProviderDatasetRefreshFailure) as exc_info:
        await runner(
            cast(Any, object()),
            _scope(
                provider=KMA_PROVIDER_NAME,
                dataset_key=KMA_SHORT_FORECAST_DATASET_KEY,
                sync_scope="external_system:tripmate",
            ),
        )

    failure = exc_info.value
    assert failure.provider == KMA_PROVIDER_NAME
    assert failure.dataset_key == KMA_SHORT_FORECAST_DATASET_KEY
    assert failure.sync_scope == "external_system:tripmate"
    assert str(failure) == "provider refresh asset execution failed"
    assert isinstance(failure.__cause__, RuntimeError)


async def test_feature_update_asset_runner_preserves_typed_failure_when_teardown_fails() -> None:
    failure = ProviderDatasetRefreshFailure(
        provider="demo",
        dataset_key="places",
        sync_scope="dataset_wide",
        message="provider failed",
    )

    async def _run(_context: object) -> _FakeAssetResult:
        raise failure

    def _teardown() -> None:
        raise RuntimeError("teardown failed")

    runner = FeatureUpdateAssetRunner(
        common_resources={},
        log=_Log(),
        settings_factory=lambda: cast(KorTravelMapSettings, object()),
        specs=(
            FeatureUpdateRunnerSpec(
                provider="demo",
                dataset_keys=frozenset({"places"}),
                run=_run,
                resources=lambda _settings, _scope: RunnerResources({}, (_teardown,)),
                asset_key="feature_demo_places",
            ),
        ),
    )

    with pytest.raises(ProviderDatasetRefreshFailure) as exc_info:
        await runner(cast(Any, object()), _scope())

    assert exc_info.value is failure


async def test_feature_update_asset_runner_types_teardown_failure_after_success() -> None:
    async def _run(_context: object) -> _FakeAssetResult:
        return _FakeAssetResult(
            provider="demo",
            dataset_key="places",
            feature_ids=("feature-1",),
        )

    def _teardown() -> None:
        raise RuntimeError("teardown failed")

    runner = FeatureUpdateAssetRunner(
        common_resources={},
        log=_Log(),
        settings_factory=lambda: cast(KorTravelMapSettings, object()),
        specs=(
            FeatureUpdateRunnerSpec(
                provider="demo",
                dataset_keys=frozenset({"places"}),
                run=_run,
                resources=lambda _settings, _scope: RunnerResources({}, (_teardown,)),
                asset_key="feature_demo_places",
            ),
        ),
    )

    with pytest.raises(ProviderDatasetRefreshFailure) as exc_info:
        await runner(cast(Any, object()), _scope())

    failure = exc_info.value
    assert failure.provider == "demo"
    assert failure.dataset_key == "places"
    assert failure.sync_scope == "default"
    assert "resource teardown failed" in str(failure)


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


@pytest.mark.parametrize(
    "dataset_key",
    [OPINET_STATION_DATASET_KEY, OPINET_PRICE_DATASET_KEY],
)
async def test_feature_update_asset_runner_skips_opinet_targeted_global_refetch(
    dataset_key: str,
) -> None:
    called = False

    async def _run(_context: object) -> _FakeAssetResult:
        nonlocal called
        called = True
        raise AssertionError("targeted OpiNet request가 asset fetch를 실행하면 안 된다.")

    def _resources(
        _settings: KorTravelMapSettings,
        _scope: ProviderDatasetRefreshScope,
    ) -> RunnerResources:
        raise AssertionError("targeted OpiNet request가 resource를 만들면 안 된다.")

    runner = FeatureUpdateAssetRunner(
        common_resources={},
        log=_Log(),
        settings_factory=lambda: cast(KorTravelMapSettings, object()),
        specs=(
            FeatureUpdateRunnerSpec(
                provider=OPINET_PROVIDER_NAME,
                dataset_keys=frozenset(
                    {OPINET_STATION_DATASET_KEY, OPINET_PRICE_DATASET_KEY}
                ),
                run=_run,
                resources=_resources,
                asset_key="feature_place_opinet_stations",
            ),
        ),
    )

    result = await runner(
        object(),
        _scope(
            provider=OPINET_PROVIDER_NAME,
            dataset_key=dataset_key,
            scope_type="center_radius",
        ),
    )

    assert called is False
    assert result.status == "skipped"
    assert result.loaded_count == 0
    assert result.metadata == {
        "provider": OPINET_PROVIDER_NAME,
        "dataset_key": dataset_key,
        "skipped": True,
        "skip_reason": "global_provider_not_targetable",
        "scope_type": "center_radius",
    }


async def test_feature_update_asset_runner_allows_opinet_provider_wide_refresh() -> None:
    called: list[str] = []

    async def _run(context: object) -> _FakeAssetResult:
        context_any = cast(Any, context)
        called.extend(cast(Any, context_any.resources).opinet_records)
        return _FakeAssetResult(
            provider=OPINET_PROVIDER_NAME,
            dataset_key=OPINET_STATION_DATASET_KEY,
            feature_ids=("station-1",),
        )

    def _resources(
        _settings: KorTravelMapSettings,
        _scope: ProviderDatasetRefreshScope,
    ) -> RunnerResources:
        return RunnerResources({"opinet_records": ("fetched",)})

    runner = FeatureUpdateAssetRunner(
        common_resources={},
        log=_Log(),
        settings_factory=lambda: cast(KorTravelMapSettings, object()),
        specs=(
            FeatureUpdateRunnerSpec(
                provider=OPINET_PROVIDER_NAME,
                dataset_keys=frozenset({OPINET_STATION_DATASET_KEY}),
                run=_run,
                resources=_resources,
                asset_key="feature_place_opinet_stations",
            ),
        ),
    )

    result = await runner(
        object(),
        _scope(
            provider=OPINET_PROVIDER_NAME,
            dataset_key=OPINET_STATION_DATASET_KEY,
        ),
    )

    assert called == ["fetched"]
    assert result.status == "done"
    assert result.loaded_feature_ids == ("station-1",)


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


@pytest.mark.parametrize(
    ("requested_scope", "effective_scope"),
    [
        ("target_grids", "target_grids"),
        ("external_system:tripmate", "external_system:tripmate"),
    ],
)
def test_kma_grid_resources_propagate_canonical_effective_scope(
    monkeypatch: pytest.MonkeyPatch,
    requested_scope: str | None,
    effective_scope: str,
) -> None:
    monkeypatch.setattr(
        runner_mod,
        "_kma_weather_resources",
        lambda _settings, _scope: RunnerResources({"kma_weather_client": object()}),
    )

    resources = runner_mod._kma_grid_resources(  # noqa: SLF001 - scope 경계 회귀
        cast(KorTravelMapSettings, object()),
        _scope(
            provider="python-kma-api",
            dataset_key="kma_short_forecast",
            sync_scope=requested_scope,
        ),
    )

    assert resources.values["feature_update_dataset_key"] == "kma_short_forecast"
    assert resources.values["kma_weather_sync_scope"] == effective_scope
    assert resources.values["kma_weather_sync_failure_managed_by_executor"] is True


def test_kma_grid_resources_reject_missing_typed_effective_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _unexpected(*_args: object) -> RunnerResources:
        raise AssertionError("missing typed scope must fail before KMA client creation")

    monkeypatch.setattr(runner_mod, "_kma_weather_resources", _unexpected)

    with pytest.raises(ValueError, match="effective sync_scope is required"):
        runner_mod._kma_grid_resources(  # noqa: SLF001 - fail-closed 회귀
            cast(KorTravelMapSettings, object()),
            _scope(
                provider="python-kma-api",
                dataset_key="kma_short_forecast",
                sync_scope=None,
            ),
        )


@pytest.mark.parametrize("sync_scope", ["default", "all", "dataset_wide", " "])
def test_kma_grid_resources_reject_non_target_scope_before_client_creation(
    monkeypatch: pytest.MonkeyPatch,
    sync_scope: str,
) -> None:
    def _unexpected(*_args: object) -> RunnerResources:
        raise AssertionError("invalid scope must fail before KMA client creation")

    monkeypatch.setattr(runner_mod, "_kma_weather_resources", _unexpected)

    with pytest.raises(ValueError, match="sync_scope|KMA grid"):
        runner_mod._kma_grid_resources(  # noqa: SLF001 - fail-closed 회귀
            cast(KorTravelMapSettings, object()),
            _scope(
                provider="python-kma-api",
                dataset_key="kma_short_forecast",
                sync_scope=sync_scope,
            ),
        )


def test_mois_runner_resources_sync_source_db_before_fetch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
) -> None:
    db_path = tmp_path / "mois.db"
    calls: list[tuple[str, str | None]] = []
    sentinel = [object()]
    settings = KorTravelMapSettings.model_construct(mois_source_db_path=str(db_path))

    def _fake_sync(
        actual_settings: KorTravelMapSettings, **_kwargs: object
    ) -> None:
        # freshness 게이트(ensure_mois_source_db_fresh)가 read 전에 호출됨을 검증.
        calls.append(("sync", actual_settings.mois_source_db_path))

    def _fake_fetch(actual_settings: KorTravelMapSettings) -> list[object]:
        calls.append(("fetch", actual_settings.mois_source_db_path))
        return sentinel

    monkeypatch.setattr(runner_mod, "ensure_mois_source_db_fresh", _fake_sync)
    monkeypatch.setattr(runner_mod, "fetch_mois_license_records", _fake_fetch)

    resources = runner_mod._mois_resources(  # noqa: SLF001 - runner resource contract
        settings,
        _scope(provider=MOIS_PROVIDER_NAME, dataset_key=DATASET_KEY_BULK),
    )

    assert resources.values["mois_license_records"] is sentinel
    assert resources.values["mois_dataset_key"] == DATASET_KEY_BULK
    assert calls == [("sync", str(db_path)), ("fetch", str(db_path))]


@pytest.mark.parametrize(
    ("factory_name", "fetch_name", "settings_attr", "records_key", "dataset_key"),
    [
        (
            "_knps_point_resources",
            "fetch_knps_point_records",
            "knps_point_dataset_key",
            "knps_point_records",
            "knps_restrooms",
        ),
        (
            "_knps_geometry_resources",
            "fetch_knps_geometry_records",
            "knps_geometry_dataset_key",
            "knps_geometry_records",
            "knps_hazard_zones",
        ),
    ],
)
def test_knps_direct_runner_freezes_same_non_default_dataset_for_fetch_and_asset(
    factory_name: str,
    fetch_name: str,
    settings_attr: str,
    records_key: str,
    dataset_key: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = KorTravelMapSettings(
        knps_point_dataset_key="knps_visitor_centers",
        knps_geometry_dataset_key="knps_trails",
    )
    fetched_settings: list[KorTravelMapSettings] = []
    records = [object()]

    def _fetch(actual_settings: KorTravelMapSettings) -> list[object]:
        fetched_settings.append(actual_settings)
        return records

    monkeypatch.setattr(runner_mod, fetch_name, _fetch)
    factory = cast(Any, getattr(runner_mod, factory_name))

    resources = factory(
        settings,
        _scope(provider=KNPS_PROVIDER_NAME, dataset_key=dataset_key),
    )

    assert resources.values[records_key] is records
    assert resources.values[settings_attr] == dataset_key
    assert len(fetched_settings) == 1
    assert getattr(fetched_settings[0], settings_attr) == dataset_key
    assert getattr(settings, settings_attr) != dataset_key


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


async def test_opinet_missing_key_is_typed_before_provider_client_auth_error() -> None:
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

    with pytest.raises(ProviderDatasetRefreshFailure) as exc_info:
        await runner(
            object(),
            _scope(provider=OPINET_PROVIDER_NAME, dataset_key=OPINET_STATION_DATASET_KEY),
        )

    failure = exc_info.value
    assert failure.sync_scope == "default"
    assert str(failure) == "provider refresh resource initialization failed"
    assert isinstance(failure.__cause__, ProviderCredentialMissing)
    assert "KOR_TRAVEL_MAP_OPINET_API_KEY" in str(failure.__cause__)
