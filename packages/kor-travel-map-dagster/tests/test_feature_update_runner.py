"""feature update request Dagster runner 단위 테스트."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast

import pytest
from kortravelmap.client import AsyncKorTravelMapClient
from kortravelmap.core.feature_operation import ProviderDatasetOperationMembership
from kortravelmap.infra.feature_update_executor import (
    ProviderDatasetRefreshFailure,
    ProviderDatasetRefreshScope,
)
from kortravelmap.providers.feature_operation_registry import feature_operation_handler_keys
from kortravelmap.providers.kma import (
    KMA_PROVIDER_NAME,
    KMA_SHORT_FORECAST_DATASET_KEY,
)
from kortravelmap.providers.knps import PROVIDER_NAME as KNPS_PROVIDER_NAME
from kortravelmap.providers.mois import DATASET_KEY_BULK
from kortravelmap.providers.mois import PROVIDER_NAME as MOIS_PROVIDER_NAME
from kortravelmap.providers.opinet import (
    OPINET_PRICE_DATASET_KEY,
    OPINET_PROVIDER_NAME,
    OPINET_STATION_DATASET_KEY,
)
from kortravelmap.settings import KorTravelMapSettings
from pydantic import SecretStr

from kortravelmap.dagster import feature_update_runner as runner_mod
from kortravelmap.dagster.assets import FEATURE_LOAD_ASSETS
from kortravelmap.dagster.feature_update_runner import (
    FeatureUpdateAssetRunner,
    FeatureUpdateRunnerSpec,
    RunnerResources,
)
from kortravelmap.dagster.kma_weather import (
    KMA_WEATHER_ASSETS,
    KmaWeatherTargetScopeEmptyError,
)
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
    sync_scope: str | None = "dataset_wide",
    operation_key: str = "feature_place_opinet_stations_job",
) -> ProviderDatasetRefreshScope:
    request_scope: dict[str, object]
    if scope_type == "provider_dataset":
        request_scope = {
            "type": "provider_dataset",
            "provider_dataset_id": 1,
            "sync_scope": sync_scope,
        }
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
        provider_dataset_id=1,
        operation_key=operation_key,
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
                "membership": resources.feature_update_membership,
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
                operation_key="feature_place_opinet_stations_job",
                run=_run,
                resources=_resources,
                asset_key="feature_place_opinet_stations",
            ),
        ),
    )

    result = await runner(object(), _scope())

    assert called == [
        {
            "records": ("a", "b"),
            "asset_key": "feature_place_opinet_stations",
            "membership": ProviderDatasetOperationMembership(
                provider_dataset_id=1,
                sync_scope="dataset_wide",
                operation_key="feature_place_opinet_stations_job",
            ),
        }
    ]
    assert result.provider == "demo"
    assert result.dataset_key == "places"
    assert result.operation_key == "feature_place_opinet_stations_job"
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
                operation_key="feature_place_opinet_stations_job",
                run=_raw,
                resources=lambda _settings, _scope: RunnerResources({}),
                asset_key="feature_place_opinet_stations",
            ),
        ),
    )

    result = await runner(object(), _scope())

    assert result.status == "done"
    assert guard.ensure_calls == 0


def test_operation_specs_reference_only_module_raw_symbols() -> None:
    public_wrappers = {
        cast(Any, asset_def.op.compute_fn).decorated_fn
        for asset_def in (
            *FEATURE_LOAD_ASSETS,
            *KMA_WEATHER_ASSETS,
            *MCST_FEATURE_ASSETS,
        )
    }

    assert runner_mod._OPERATION_RUNNER_SPECS  # noqa: SLF001 - production dispatch contract
    for spec in runner_mod._OPERATION_RUNNER_SPECS.values():  # noqa: SLF001
        assert spec.run not in public_wrappers
        assert getattr(runner_mod, spec.run.__name__, None) is spec.run
        assert spec.run.__name__.startswith(("run_feature_", "_run_kma_grid_"))
    assert frozenset(runner_mod._OPERATION_RUNNER_SPECS) == feature_operation_handler_keys()


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
                operation_key="feature_place_opinet_stations_job",
                run=_run,
                resources=_resources,
                asset_key="feature_place_opinet_stations",
            ),
        ),
    )

    with pytest.raises(ProviderDatasetRefreshFailure) as exc_info:
        await runner(object(), _scope(sync_scope="dataset_wide"))

    assert teardown_calls == 1
    failure = exc_info.value
    assert failure.provider_dataset_id == 1
    assert failure.sync_scope == "dataset_wide"
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
                operation_key="feature_place_opinet_stations_job",
                run=_run,
                resources=_resources,
                asset_key="feature_place_opinet_stations",
            ),
        ),
    )

    with pytest.raises(ProviderDatasetRefreshFailure) as exc_info:
        await runner(cast(Any, object()), _scope(sync_scope="dataset_wide"))

    failure = exc_info.value
    assert failure.provider_dataset_id == 1
    assert failure.sync_scope == "dataset_wide"
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
                operation_key="feature_weather_kma_short_forecast_job",
                run=_run,
                resources=lambda _settings, _scope: RunnerResources({}),
                asset_key="feature_weather_kma_short_forecast",
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
                operation_key="feature_weather_kma_short_forecast_job",
            ),
        )

    failure = exc_info.value
    assert failure.provider_dataset_id == 1
    assert failure.sync_scope == "external_system:tripmate"
    assert str(failure) == "provider refresh asset execution failed"
    assert isinstance(failure.__cause__, RuntimeError)


async def test_feature_update_asset_runner_preserves_typed_failure_when_teardown_fails() -> None:
    failure = ProviderDatasetRefreshFailure(
        provider_dataset_id=1,
        sync_scope="dataset_wide",
        operation_key="feature_place_opinet_stations_job",
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
                operation_key="feature_place_opinet_stations_job",
                run=_run,
                resources=lambda _settings, _scope: RunnerResources({}, (_teardown,)),
                asset_key="feature_place_opinet_stations",
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
                operation_key="feature_place_opinet_stations_job",
                run=_run,
                resources=lambda _settings, _scope: RunnerResources({}, (_teardown,)),
                asset_key="feature_place_opinet_stations",
            ),
        ),
    )

    with pytest.raises(ProviderDatasetRefreshFailure) as exc_info:
        await runner(cast(Any, object()), _scope())

    failure = exc_info.value
    assert failure.provider_dataset_id == 1
    assert failure.sync_scope == "dataset_wide"
    assert "resource teardown failed" in str(failure)


async def test_feature_update_asset_runner_rejects_unknown_operation_key() -> None:
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

    with pytest.raises(RuntimeError, match="지원하지 않는 operation_key"):
        await runner(object(), _scope(operation_key="feature_unknown_job"))


@pytest.mark.parametrize(
    ("dataset_key", "operation_key", "asset_key"),
    [
        (
            OPINET_STATION_DATASET_KEY,
            "feature_place_opinet_stations_job",
            "feature_place_opinet_stations",
        ),
        (
            OPINET_PRICE_DATASET_KEY,
            "feature_price_opinet_stations_job",
            "feature_price_opinet_stations",
        ),
    ],
)
async def test_feature_update_asset_runner_skips_opinet_targeted_global_refetch(
    dataset_key: str,
    operation_key: str,
    asset_key: str,
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
                operation_key=operation_key,
                run=_run,
                resources=_resources,
                asset_key=asset_key,
            ),
        ),
    )

    result = await runner(
        object(),
        _scope(
            provider=OPINET_PROVIDER_NAME,
            dataset_key=dataset_key,
            scope_type="center_radius",
            operation_key=operation_key,
        ),
    )

    assert called is False
    assert result.status == "skipped"
    assert result.loaded_count == 0
    assert result.metadata == {
        "provider_dataset_id": 1,
        "sync_scope": "dataset_wide",
        "operation_key": operation_key,
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
                operation_key="feature_place_opinet_stations_job",
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


def test_default_runner_uses_operation_key_not_catalog_labels() -> None:
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
        _scope(
            provider="arbitrary-catalog-label",
            dataset_key="arbitrary-display-key",
            operation_key="feature_weather_airkorea_air_quality_job",
        )
    )

    assert spec.asset_key == "feature_weather_airkorea_air_quality"


def test_default_runner_uses_mois_operation_key_without_dataset_filtering() -> None:
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
        _scope(
            provider="arbitrary-catalog-label",
            dataset_key="arbitrary-display-key",
            operation_key="feature_place_mois_licenses_job",
        )
    )
    assert spec.asset_key == "feature_place_mois_licenses"


def test_mcst_runner_scopes_fetch_to_the_claimed_exact_member(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[tuple[str, ...]] = []
    selected_slug, selected_spec = next(iter(runner_mod.MCST_FILE_DATASETS.items()))

    def _fetch(
        _settings: KorTravelMapSettings,
        *,
        slugs: tuple[str, ...],
    ) -> tuple[object, ...]:
        captured.append(slugs)
        return ()

    monkeypatch.setattr(runner_mod, "fetch_mcst_culture_records", _fetch)

    resources = runner_mod._mcst_resources(  # noqa: SLF001 - worker source boundary
        cast(KorTravelMapSettings, object()),
        _scope(
            provider="arbitrary-display-label",
            dataset_key=selected_spec.dataset_key,
            operation_key="feature_place_mcst_culture_job",
        ),
    )

    assert captured == [(selected_slug,)]
    assert resources.values["mcst_culture_records"] == ()


@pytest.mark.parametrize(
    ("requested_scope", "effective_scope"),
    [
        ("target_grids", "target_grids"),
        ("external_system:tripmate", "external_system:tripmate"),
    ],
)
def test_kma_grid_resources_propagate_exact_persisted_scope(
    requested_scope: str | None,
    effective_scope: str,
) -> None:
    settings = KorTravelMapSettings.model_construct(
        data_go_kr_service_key=None,
        kma_weather_extra_points=None,
        kma_weather_max_grids_per_run=17,
    )

    resources = runner_mod._kma_grid_resources(  # noqa: SLF001 - scope 경계 회귀
        settings,
        _scope(
            provider="python-kma-api",
            dataset_key="kma_short_forecast",
            sync_scope=requested_scope,
            operation_key="feature_weather_kma_short_forecast_job",
        ),
    )

    assert resources.values["feature_update_dataset_key"] == "kma_short_forecast"
    assert "feature_update_membership" not in resources.values
    assert resources.values["kma_weather_sync_scope"] == effective_scope
    assert resources.values["kma_weather_sync_failure_managed_by_executor"] is True
    assert "kma_weather_client" not in resources.values
    assert callable(resources.values["kma_weather_client_factory"])
    assert resources.values["kma_weather_extra_points"] is None
    assert resources.values["kma_weather_max_grids_per_run"] == 17


def test_kma_runner_clients_receive_timeout_and_inner_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """H45(재리뷰 N-4) — admin 재적재 runner 경로 2곳도 timeout·retries 정산값이
    실제 client 생성자에 도달한다(스케줄 resource와 갈리면 진단이 흐려진다)."""

    import sys
    from types import ModuleType

    created: list[tuple[str, dict[str, Any]]] = []

    class _RecordingClient:
        def __init__(self, *, service_key: str, **kwargs: Any) -> None:
            created.append((type(self).__name__, dict(kwargs)))
            self.service_key = service_key

        def close(self) -> None:
            pass

    fake = ModuleType("kma")
    fake.__dict__["KmaClient"] = type("KmaClient", (_RecordingClient,), {})
    fake.__dict__["DataGoKrClient"] = type("DataGoKrClient", (_RecordingClient,), {})
    monkeypatch.setitem(sys.modules, "kma", fake)
    settings = KorTravelMapSettings.model_construct(
        data_go_kr_service_key=SecretStr("svc"),
        provider_http_timeout_seconds=20.0,
        kma_mid_region_features=None,
    )

    runner_mod._new_kma_weather_client(  # noqa: SLF001 - 주입 경계 회귀
        settings,
        _scope(provider="python-kma-api", dataset_key="kma_short_forecast"),
    )
    resources = runner_mod._kma_mid_resources(  # noqa: SLF001 - 주입 경계 회귀
        settings,
        _scope(provider="python-kma-api", dataset_key="kma_mid_forecast"),
    )
    for teardown in resources.teardowns:
        teardown()

    assert created == [
        ("KmaClient", {"timeout": 20.0, "retries": 1}),
        ("DataGoKrClient", {"timeout": 20.0, "retries": 1}),
    ]


@pytest.mark.parametrize(
    "service_key",
    [None, SecretStr("configured-service-key")],
    ids=["credential-missing", "constructor-sentinel"],
)
async def test_default_kma_runner_empty_target_precedes_lazy_credential_and_client(
    monkeypatch: pytest.MonkeyPatch,
    service_key: SecretStr | None,
) -> None:
    constructor_calls: list[str] = []

    class _ForbiddenKmaClient:
        def __init__(self, *, service_key: str) -> None:
            constructor_calls.append(service_key)
            raise AssertionError("empty target 뒤 KmaClient를 만들면 안 된다")

    module = SimpleNamespace(KmaClient=_ForbiddenKmaClient)
    import_calls: list[str] = []

    def _import_module(name: str) -> object:
        import_calls.append(name)
        return module

    class _EmptyTargetClient:
        def __init__(self) -> None:
            self.target_calls: list[str | None] = []

        async def list_poi_cache_target_coords(
            self,
            *,
            external_system: str | None = None,
        ) -> list[tuple[float, float]]:
            self.target_calls.append(external_system)
            return []

    monkeypatch.setattr(runner_mod.importlib, "import_module", _import_module)
    target_client = _EmptyTargetClient()
    runner = FeatureUpdateAssetRunner(
        common_resources={
            "kor_travel_map_client": target_client,
            "reverse_geocoder": None,
        },
        log=_Log(),
        settings_factory=lambda: KorTravelMapSettings.model_construct(
            data_go_kr_service_key=service_key,
            kma_weather_extra_points=None,
            kma_weather_max_grids_per_run=50,
        ),
    )

    with pytest.raises(KmaWeatherTargetScopeEmptyError) as exc_info:
        await runner(
            cast(Any, object()),
            _scope(
                provider=KMA_PROVIDER_NAME,
                dataset_key=KMA_SHORT_FORECAST_DATASET_KEY,
                sync_scope="target_grids",
                operation_key="feature_weather_kma_short_forecast_job",
            ),
        )

    assert exc_info.value.event_code == "kma.target_scope_empty"
    assert target_client.target_calls == [None]
    assert import_calls == []
    assert constructor_calls == []


def test_kma_grid_resources_reject_missing_exact_scope_at_membership_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _unexpected(*_args: object) -> RunnerResources:
        raise AssertionError("missing typed scope must fail before KMA client creation")

    monkeypatch.setattr(runner_mod, "_kma_weather_resources", _unexpected)

    with pytest.raises(ValueError, match="sync_scope must be"):
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

    def _fake_sync(actual_settings: KorTravelMapSettings, **_kwargs: object) -> None:
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


def test_default_runner_uses_each_datagokr_file_operation_key() -> None:
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

    for operation_key in (
        "feature_place_datagokr_seoul_bookstores_job",
        "feature_place_datagokr_gyeonggi_muslim_friendly_restaurants_job",
        "feature_place_datagokr_ansan_world_restaurants_job",
        "feature_place_datagokr_jeju_local_restaurants_job",
    ):
        spec = runner._spec_for_scope(  # noqa: SLF001 - default dispatch contract 회귀 테스트
            _scope(operation_key=operation_key)
        )
        assert spec.asset_key == "feature_place_datagokr_file_data"


def test_default_runner_covers_every_canonical_operation_handler() -> None:
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
    assert frozenset(runner._specs) == feature_operation_handler_keys()  # noqa: SLF001


async def test_opinet_missing_key_is_typed_before_provider_client_auth_error() -> None:
    runner = FeatureUpdateAssetRunner(
        common_resources={
            "kor_travel_map_client": object(),
            "reverse_geocoder": None,
            "fetched_at": None,
            "strict_address": "off",
        },
        log=_Log(),
        settings_factory=lambda: KorTravelMapSettings.model_construct(opinet_api_key=None),
    )

    with pytest.raises(ProviderDatasetRefreshFailure) as exc_info:
        await runner(
            object(),
            _scope(provider=OPINET_PROVIDER_NAME, dataset_key=OPINET_STATION_DATASET_KEY),
        )

    failure = exc_info.value
    assert failure.provider_dataset_id == 1
    assert failure.sync_scope == "dataset_wide"
    assert str(failure) == "provider refresh resource initialization failed"
    assert isinstance(failure.__cause__, ProviderCredentialMissing)
    assert "KOR_TRAVEL_MAP_OPINET_API_KEY" in str(failure.__cause__)
