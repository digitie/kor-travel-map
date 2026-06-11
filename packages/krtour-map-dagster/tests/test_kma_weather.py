"""KMA weather Dagster asset 3종 단위 테스트 (T-219b)."""

from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace
from typing import Any, cast

import pytest
from dagster import build_asset_context, build_init_resource_context
from krtour.map.dto import ForecastStyle, WeatherDomain
from pydantic import SecretStr

from krtour.map_dagster import kma_weather, resources
from krtour.map_dagster.kma_weather import (
    KmaForecastRow,
    KmaNowcastRow,
    forecast_rows_from_items,
    map_grid_targets,
    nowcast_rows_from_snapshot,
    run_feature_weather_kma_short_forecast,
    run_feature_weather_kma_ultra_short_forecast,
    run_feature_weather_kma_ultra_short_nowcast,
)

pytestmark = pytest.mark.filterwarnings(
    "ignore:Parameter `owners` of initializer `SensorDefinition.__init__`"
    ".*:dagster_shared.utils.warnings.BetaWarning"
)


def _int_grid(lat: float, lon: float) -> tuple[int, int]:
    """테스트용 결정적 격자: (nx, ny) = (floor(lon), floor(lat))."""
    return (int(lon), int(lat))


# -- map_grid_targets -----------------------------------------------------


def test_map_grid_targets_dedupes_caps_and_maps_places() -> None:
    targets = map_grid_targets(
        # 두 target이 같은 격자 (126, 37)로 dedupe.
        target_coords=[(126.9, 37.5), (126.95, 37.55)],
        # extra 2격자 — 상한(2)에 걸려 마지막 (130, 36)이 떨어진다.
        extra_points=[(129.0, 35.1), (130.2, 36.0)],
        place_coords=[
            ("f-in-first", 126.97, 37.56),
            ("f-in-second", 129.07, 35.17),
            ("f-outside", 127.5, 36.5),
            ("f-dropped-grid", 130.5, 36.2),
        ],
        to_grid=_int_grid,
        max_grids=2,
    )

    assert targets.grids == ((126, 37), (129, 35))
    assert targets.grids_dropped == 1
    assert targets.feature_ids_by_grid[(126, 37)] == ("f-in-first",)
    assert targets.feature_ids_by_grid[(129, 35)] == ("f-in-second",)


def test_map_grid_targets_rejects_nonpositive_cap() -> None:
    with pytest.raises(ValueError, match="max_grids"):
        map_grid_targets(
            target_coords=[],
            extra_points=[],
            place_coords=[],
            to_grid=_int_grid,
            max_grids=0,
        )


# -- raw payload → Protocol row -------------------------------------------


def test_nowcast_rows_from_snapshot_builds_protocol_rows() -> None:
    snapshot = SimpleNamespace(
        raw={
            "items": [
                {
                    "baseDate": "20260611",
                    "baseTime": "0500",
                    "nx": 60,
                    "ny": 127,
                    "category": "T1H",
                    "obsrValue": "18.2",
                }
            ]
        }
    )

    rows = nowcast_rows_from_snapshot(snapshot)

    assert rows == [
        KmaNowcastRow(
            base_date="20260611",
            base_time="0500",
            nx=60,
            ny=127,
            category="T1H",
            obsr_value="18.2",
        )
    ]


def test_forecast_rows_from_items_builds_protocol_rows() -> None:
    items = [
        SimpleNamespace(
            raw={
                "baseDate": "20260611",
                "baseTime": "0200",
                "fcstDate": "20260611",
                "fcstTime": "0900",
                "nx": "60",
                "ny": "127",
                "category": "TMP",
                "fcstValue": "23.5",
            }
        )
    ]

    rows = forecast_rows_from_items(items)

    assert rows == [
        KmaForecastRow(
            base_date="20260611",
            base_time="0200",
            fcst_date="20260611",
            fcst_time="0900",
            nx=60,
            ny=127,
            category="TMP",
            fcst_value="23.5",
        )
    ]


# -- asset runner fakes ----------------------------------------------------


class _FakeKrtourClient:
    def __init__(
        self,
        *,
        sync_state: Any | None = None,
        target_coords: list[tuple[float, float]] | None = None,
        place_coords: list[tuple[str, float, float]] | None = None,
        load_error: Exception | None = None,
    ) -> None:
        self.sync_state = sync_state
        self.target_coords = target_coords or []
        self.place_coords = place_coords or []
        self.load_error = load_error
        self.loaded_values: list[Any] = []
        self.success_calls: list[dict[str, Any]] = []
        self.failure_calls: list[dict[str, Any]] = []

    async def get_sync_state(
        self, *, provider: str, dataset_key: str, sync_scope: str = "default"
    ) -> Any | None:
        return self.sync_state

    async def list_poi_cache_target_coords(self) -> list[tuple[float, float]]:
        return list(self.target_coords)

    async def list_active_place_coords(self) -> list[tuple[str, float, float]]:
        return list(self.place_coords)

    async def load_weather_values(self, values: Any) -> int:
        materialized = list(values)
        if self.load_error is not None:
            raise self.load_error
        self.loaded_values.extend(materialized)
        return len(materialized)

    async def record_sync_success(
        self,
        *,
        provider: str,
        dataset_key: str,
        cursor: dict[str, Any],
        sync_scope: str = "default",
        next_run_after: Any = None,
    ) -> None:
        self.success_calls.append(
            {"provider": provider, "dataset_key": dataset_key, "cursor": cursor}
        )

    async def record_sync_failure(
        self,
        *,
        provider: str,
        dataset_key: str,
        sync_scope: str = "default",
        next_run_after: Any = None,
    ) -> None:
        self.failure_calls.append({"provider": provider, "dataset_key": dataset_key})


class _FakeForecastService:
    def __init__(
        self,
        *,
        snapshot: Any | None = None,
        short_items: list[Any] | None = None,
        vilage_items: list[Any] | None = None,
    ) -> None:
        self._snapshot = snapshot
        self._short_items = short_items or []
        self._vilage_items = vilage_items or []
        self.calls: list[tuple[str, int, int]] = []

    def now(self, *, nx: int, ny: int) -> Any:
        self.calls.append(("now", nx, ny))
        return self._snapshot

    def short(self, *, nx: int, ny: int) -> list[Any]:
        self.calls.append(("short", nx, ny))
        return list(self._short_items)

    def vilage(self, *, nx: int, ny: int) -> list[Any]:
        self.calls.append(("vilage", nx, ny))
        return list(self._vilage_items)


_NOWCAST_SNAPSHOT = SimpleNamespace(
    raw={
        "items": [
            {
                "baseDate": "20260611",
                "baseTime": "0500",
                "nx": 126,
                "ny": 37,
                "category": "T1H",
                "obsrValue": "18.2",
            },
            {
                "baseDate": "20260611",
                "baseTime": "0500",
                "nx": 126,
                "ny": 37,
                "category": "REH",
                "obsrValue": "70",
            },
        ]
    }
)


def _forecast_item(category: str, value: str) -> SimpleNamespace:
    return SimpleNamespace(
        raw={
            "baseDate": "20260611",
            "baseTime": "0200",
            "fcstDate": "20260611",
            "fcstTime": "0900",
            "nx": 126,
            "ny": 37,
            "category": category,
            "fcstValue": value,
        }
    )


def _context(krtour_client: _FakeKrtourClient, forecast: _FakeForecastService) -> Any:
    return build_asset_context(
        resources={
            "krtour_map_client": krtour_client,
            "kma_weather_client": SimpleNamespace(forecast=forecast),
            "kma_weather_extra_points": None,
            "kma_weather_max_grids_per_run": 50,
        }
    )


def _patch_grid_and_bases(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(kma_weather, "_kma_grid", _int_grid)
    monkeypatch.setattr(
        kma_weather, "_latest_nowcast_base", lambda: ("20260611", "0500")
    )
    monkeypatch.setattr(
        kma_weather,
        "_latest_ultra_short_forecast_base",
        lambda: ("20260611", "0530"),
    )
    monkeypatch.setattr(
        kma_weather, "_latest_short_forecast_base", lambda: ("20260611", "0200")
    )


# -- asset runner ----------------------------------------------------------


async def test_nowcast_asset_loads_values_per_feature_and_advances_cursor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_grid_and_bases(monkeypatch)
    krtour_client = _FakeKrtourClient(
        target_coords=[(126.978, 37.5665)],
        place_coords=[
            ("f1", 126.978, 37.5665),
            ("f2", 126.5, 37.9),
            ("f-far", 129.07, 35.17),
        ],
    )
    forecast = _FakeForecastService(snapshot=_NOWCAST_SNAPSHOT)

    result = await run_feature_weather_kma_ultra_short_nowcast(
        _context(krtour_client, forecast)
    )

    assert result.skipped is False
    assert result.base_datetime == "202606110500"
    assert result.grids_total == 1
    assert result.grids_fetched == 1
    assert result.features_total == 2
    # 2 카테고리 × 2 feature.
    assert result.values_loaded == 4
    assert forecast.calls == [("now", 126, 37)]
    assert {value.feature_id for value in krtour_client.loaded_values} == {"f1", "f2"}
    sample = krtour_client.loaded_values[0]
    assert sample.provider == "python-kma-api"
    assert sample.weather_domain == WeatherDomain.KMA_ULTRA_SHORT_NOWCAST
    assert krtour_client.success_calls == [
        {
            "provider": "python-kma-api",
            "dataset_key": "kma_ultra_short_nowcast",
            "cursor": {"base_datetime": "202606110500"},
        }
    ]
    assert krtour_client.failure_calls == []


async def test_asset_skips_when_cursor_matches_base(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_grid_and_bases(monkeypatch)
    krtour_client = _FakeKrtourClient(
        sync_state=SimpleNamespace(cursor={"base_datetime": "202606110500"}),
        target_coords=[(126.978, 37.5665)],
        place_coords=[("f1", 126.978, 37.5665)],
    )
    forecast = _FakeForecastService(snapshot=_NOWCAST_SNAPSHOT)

    result = await run_feature_weather_kma_ultra_short_nowcast(
        _context(krtour_client, forecast)
    )

    assert result.skipped is True
    assert result.values_loaded == 0
    assert forecast.calls == []
    assert krtour_client.success_calls == []


async def test_asset_skips_kma_call_for_grid_without_features(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_grid_and_bases(monkeypatch)
    krtour_client = _FakeKrtourClient(
        target_coords=[(126.978, 37.5665)],
        # 대상 격자 (126, 37)에 속하는 place가 없다.
        place_coords=[("f-far", 129.07, 35.17)],
    )
    forecast = _FakeForecastService(snapshot=_NOWCAST_SNAPSHOT)

    result = await run_feature_weather_kma_ultra_short_nowcast(
        _context(krtour_client, forecast)
    )

    assert result.skipped is False
    assert result.grids_total == 1
    assert result.grids_fetched == 0
    assert result.values_loaded == 0
    assert forecast.calls == []
    # 호출이 없었으므로 cursor를 전진시키지 않는다.
    assert krtour_client.success_calls == []
    assert krtour_client.failure_calls == []


async def test_asset_records_sync_failure_when_load_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_grid_and_bases(monkeypatch)
    krtour_client = _FakeKrtourClient(
        target_coords=[(126.978, 37.5665)],
        place_coords=[("f1", 126.978, 37.5665)],
        load_error=RuntimeError("boom"),
    )
    forecast = _FakeForecastService(snapshot=_NOWCAST_SNAPSHOT)

    with pytest.raises(RuntimeError, match="boom"):
        await run_feature_weather_kma_ultra_short_nowcast(
            _context(krtour_client, forecast)
        )

    assert krtour_client.success_calls == []
    assert krtour_client.failure_calls == [
        {"provider": "python-kma-api", "dataset_key": "kma_ultra_short_nowcast"}
    ]


async def test_ultra_short_forecast_asset_uses_short_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_grid_and_bases(monkeypatch)
    krtour_client = _FakeKrtourClient(
        target_coords=[(126.978, 37.5665)],
        place_coords=[("f1", 126.978, 37.5665)],
    )
    forecast = _FakeForecastService(
        short_items=[_forecast_item("T1H", "18.0"), _forecast_item("LGT", "0")]
    )

    result = await run_feature_weather_kma_ultra_short_forecast(
        _context(krtour_client, forecast)
    )

    assert result.base_datetime == "202606110530"
    assert result.values_loaded == 2
    assert forecast.calls == [("short", 126, 37)]
    assert all(
        value.forecast_style == ForecastStyle.ULTRA_SHORT
        for value in krtour_client.loaded_values
    )
    assert krtour_client.success_calls[0]["dataset_key"] == "kma_ultra_short_forecast"


async def test_short_forecast_asset_uses_vilage_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_grid_and_bases(monkeypatch)
    krtour_client = _FakeKrtourClient(
        target_coords=[(126.978, 37.5665)],
        place_coords=[("f1", 126.978, 37.5665)],
    )
    forecast = _FakeForecastService(
        vilage_items=[_forecast_item("TMP", "23.5"), _forecast_item("POP", "30")]
    )

    result = await run_feature_weather_kma_short_forecast(
        _context(krtour_client, forecast)
    )

    assert result.base_datetime == "202606110200"
    assert result.values_loaded == 2
    assert forecast.calls == [("vilage", 126, 37)]
    assert all(
        value.forecast_style == ForecastStyle.SHORT
        for value in krtour_client.loaded_values
    )
    assert krtour_client.success_calls[0]["dataset_key"] == "kma_short_forecast"


# -- lazy provider helper ----------------------------------------------------


def test_lazy_kma_helpers_use_provider_modules(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    grid_module = ModuleType("kma.grid")
    grid_module.__dict__["to_grid"] = lambda lat, lon: (60, 127)
    time_module = ModuleType("kma.time_utils")
    time_module.__dict__["latest_ultra_srt_ncst_base"] = lambda: ("20260611", "0500")
    time_module.__dict__["latest_ultra_srt_fcst_base"] = lambda: ("20260611", "0530")
    time_module.__dict__["latest_vilage_base"] = lambda: ("20260611", "0200")
    monkeypatch.setitem(sys.modules, "kma.grid", grid_module)
    monkeypatch.setitem(sys.modules, "kma.time_utils", time_module)

    assert kma_weather._kma_grid(37.5665, 126.978) == (60, 127)
    assert kma_weather._latest_nowcast_base() == ("20260611", "0500")
    assert kma_weather._latest_ultra_short_forecast_base() == ("20260611", "0530")
    assert kma_weather._latest_short_forecast_base() == ("20260611", "0200")


# -- kma_weather_client resource ---------------------------------------------


class _FakeKmaClient:
    instances: list[_FakeKmaClient] = []

    def __init__(self, *, service_key: str) -> None:
        self.service_key = service_key
        self.closed = False
        _FakeKmaClient.instances.append(self)

    def close(self) -> None:
        self.closed = True


def test_kma_weather_client_resource_yields_client_and_closes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _FakeKmaClient.instances = []
    module = ModuleType("kma")
    module.__dict__["KmaClient"] = _FakeKmaClient
    monkeypatch.setitem(sys.modules, "kma", module)
    monkeypatch.setattr(
        resources,
        "KrtourMapSettings",
        lambda: SimpleNamespace(data_go_kr_service_key=SecretStr("kma-key")),
    )

    resource_fn = cast(
        "Any", resources.kma_weather_client_resource.resource_fn
    )
    resource_iter = resource_fn(build_init_resource_context())
    client = next(resource_iter)

    assert client.service_key == "kma-key"
    assert client.closed is False

    with pytest.raises(StopIteration):
        next(resource_iter)

    assert client.closed is True


def test_kma_weather_client_resource_guard_without_credential(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        resources,
        "KrtourMapSettings",
        lambda: SimpleNamespace(data_go_kr_service_key=None),
    )

    resource_fn = cast(
        "Any", resources.kma_weather_client_resource.resource_fn
    )

    with pytest.raises(RuntimeError) as exc_info:
        next(resource_fn(build_init_resource_context()))

    message = str(exc_info.value)
    assert "kma_weather_client" in message
    assert "KRTOUR_MAP_DATA_GO_KR_SERVICE_KEY" in message
    assert "python-kma-api" in message
