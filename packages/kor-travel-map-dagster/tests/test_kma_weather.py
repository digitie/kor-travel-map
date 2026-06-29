"""KMA weather Dagster asset 3종 단위 테스트 (T-219b)."""

from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace
from typing import Any, cast

import pytest
from dagster import build_asset_context, build_init_resource_context
from kortravelmap.dto import ForecastStyle, WeatherDomain
from kortravelmap.infra.feature_repo import FeatureLoadResult
from kortravelmap.settings import KorTravelMapSettings
from pydantic import SecretStr

from kortravelmap.dagster import kma_weather, provider_fetchers, resources
from kortravelmap.dagster.kma_weather import (
    KmaForecastRow,
    KmaNowcastRow,
    forecast_rows_from_items,
    map_grid_targets,
    mid_land_rows_from_items,
    mid_temp_rows_from_items,
    nowcast_rows_from_snapshot,
    run_feature_notice_kma_weather_alerts,
    run_feature_weather_kma_mid_forecast,
    run_feature_weather_kma_short_forecast,
    run_feature_weather_kma_ultra_short_forecast,
    run_feature_weather_kma_ultra_short_nowcast,
    weather_warning_rows,
)
from kortravelmap.dagster.provider_fetchers import (
    ProviderCredentialMissing,
    fetch_kma_weather_alerts,
)

pytestmark = pytest.mark.filterwarnings(
    "ignore:Parameter `owners` of initializer `SensorDefinition.__init__`"
    ".*:dagster_shared.utils.warnings.BetaWarning"
)


def _int_grid(lat: float, lon: float) -> tuple[int, int]:
    """테스트용 결정적 격자: (nx, ny) = (floor(lon), floor(lat))."""
    return (int(lon), int(lat))


# -- map_grid_targets -----------------------------------------------------


def test_map_grid_targets_dedupes_and_caps() -> None:
    targets = map_grid_targets(
        # 두 target이 같은 격자 (126, 37)로 dedupe.
        target_coords=[(126.9, 37.5), (126.95, 37.55)],
        # extra 2격자 — 상한(2)에 걸려 마지막 (130, 36)이 떨어진다.
        extra_points=[(129.0, 35.1), (130.2, 36.0)],
        to_grid=_int_grid,
        max_grids=2,
    )

    # 격자는 target → extra 순서로 dedupe·상한 적용된다(place feature 매핑 없음 —
    # 각 격자가 자체 weather feature로 적재되므로).
    assert targets.grids == ((126, 37), (129, 35))
    assert targets.grids_dropped == 1


def test_map_grid_targets_rejects_nonpositive_cap() -> None:
    with pytest.raises(ValueError, match="max_grids"):
        map_grid_targets(
            target_coords=[],
            extra_points=[],
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
        self.loaded_bundles: list[Any] = []
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

    async def load_feature_bundles(self, bundles: Any) -> Any:
        # 격자 weather feature(앵커)를 적재한다. load_error는 weather-value 적재
        # 실패 경로 검증용이라 여기서는 던지지 않는다.
        materialized = list(bundles)
        self.loaded_bundles.extend(materialized)
        return SimpleNamespace(inserted=len(materialized))

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


def _context(kor_travel_map_client: _FakeKrtourClient, forecast: _FakeForecastService) -> Any:
    return build_asset_context(
        resources={
            "kor_travel_map_client": kor_travel_map_client,
            "kma_weather_client": SimpleNamespace(forecast=forecast),
            "kma_weather_extra_points": None,
            "kma_weather_max_grids_per_run": 50,
            # 격자 중심 좌표 reverse geocoding은 best-effort — None이면 이름 fallback.
            "reverse_geocoder": None,
        }
    )


def _patch_grid_and_bases(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(kma_weather, "_kma_grid", _int_grid)
    # 격자 중심 좌표(kma.grid.to_latlon)는 python-kma-api 미설치 환경에서 import
    # 실패하므로 결정적 stub으로 대체한다(격자 → 고정 중심).
    monkeypatch.setattr(
        kma_weather, "_grid_center", lambda nx, ny: (float(ny), float(nx))
    )
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
    kor_travel_map_client = _FakeKrtourClient(
        target_coords=[(126.978, 37.5665)],
        place_coords=[
            ("f1", 126.978, 37.5665),
            ("f2", 126.5, 37.9),
            ("f-far", 129.07, 35.17),
        ],
    )
    forecast = _FakeForecastService(snapshot=_NOWCAST_SNAPSHOT)

    result = await run_feature_weather_kma_ultra_short_nowcast(
        _context(kor_travel_map_client, forecast)
    )

    assert result.skipped is False
    assert result.base_datetime == "202606110500"
    assert result.grids_total == 1
    assert result.grids_fetched == 1
    assert result.features_total == 1
    # 격자당 1 feature·1 값세트 (2 카테고리 T1H+REH) — place feature를 빌리지 않는다.
    assert result.values_loaded == 2
    assert forecast.calls == [("now", 126, 37)]
    # 값은 격자 weather feature(126,37)에 붙는다 — place "f1"이 아니다(별개 마커).
    assert len(kor_travel_map_client.loaded_bundles) == 1
    grid_feature = kor_travel_map_client.loaded_bundles[0].feature
    assert grid_feature.kind.value == "weather"
    assert grid_feature.name == "기상청 초단기 격자 126,37"
    assert {value.feature_id for value in kor_travel_map_client.loaded_values} == {
        grid_feature.feature_id
    }
    assert grid_feature.feature_id != "f1"
    sample = kor_travel_map_client.loaded_values[0]
    assert sample.provider == "python-kma-api"
    assert sample.weather_domain == WeatherDomain.KMA_ULTRA_SHORT_NOWCAST
    assert kor_travel_map_client.success_calls == [
        {
            "provider": "python-kma-api",
            "dataset_key": "kma_ultra_short_nowcast",
            "cursor": {"base_datetime": "202606110500"},
        }
    ]
    assert kor_travel_map_client.failure_calls == []


async def test_asset_skips_when_cursor_matches_base(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_grid_and_bases(monkeypatch)
    kor_travel_map_client = _FakeKrtourClient(
        sync_state=SimpleNamespace(cursor={"base_datetime": "202606110500"}),
        target_coords=[(126.978, 37.5665)],
        place_coords=[("f1", 126.978, 37.5665)],
    )
    forecast = _FakeForecastService(snapshot=_NOWCAST_SNAPSHOT)

    result = await run_feature_weather_kma_ultra_short_nowcast(
        _context(kor_travel_map_client, forecast)
    )

    assert result.skipped is True
    assert result.values_loaded == 0
    assert forecast.calls == []
    assert kor_travel_map_client.success_calls == []


async def test_asset_creates_grid_feature_without_place_features(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """대상 격자에 place feature가 없어도 격자 자체 weather feature로 적재한다.

    예전엔 place feature가 없는 격자를 건너뛰었지만(borrow-anchor 시절), 이제 격자가
    자체 feature라 place 유무와 무관하게 적재된다 — KMA가 airkorea와 별개 마커.
    """
    _patch_grid_and_bases(monkeypatch)
    kor_travel_map_client = _FakeKrtourClient(
        target_coords=[(126.978, 37.5665)],
        # 대상 격자 (126, 37)에 속하는 place가 없다 — 그래도 격자 feature는 만든다.
        place_coords=[("f-far", 129.07, 35.17)],
    )
    forecast = _FakeForecastService(snapshot=_NOWCAST_SNAPSHOT)

    result = await run_feature_weather_kma_ultra_short_nowcast(
        _context(kor_travel_map_client, forecast)
    )

    assert result.skipped is False
    assert result.grids_total == 1
    assert result.grids_fetched == 1
    assert result.values_loaded == 2
    assert forecast.calls == [("now", 126, 37)]
    assert len(kor_travel_map_client.loaded_bundles) == 1
    # 호출이 있었으므로 cursor 전진.
    assert kor_travel_map_client.success_calls == [
        {
            "provider": "python-kma-api",
            "dataset_key": "kma_ultra_short_nowcast",
            "cursor": {"base_datetime": "202606110500"},
        }
    ]
    assert kor_travel_map_client.failure_calls == []


async def test_asset_records_sync_failure_when_load_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_grid_and_bases(monkeypatch)
    kor_travel_map_client = _FakeKrtourClient(
        target_coords=[(126.978, 37.5665)],
        place_coords=[("f1", 126.978, 37.5665)],
        load_error=RuntimeError("boom"),
    )
    forecast = _FakeForecastService(snapshot=_NOWCAST_SNAPSHOT)

    with pytest.raises(RuntimeError, match="boom"):
        await run_feature_weather_kma_ultra_short_nowcast(
            _context(kor_travel_map_client, forecast)
        )

    assert kor_travel_map_client.success_calls == []
    assert kor_travel_map_client.failure_calls == [
        {"provider": "python-kma-api", "dataset_key": "kma_ultra_short_nowcast"}
    ]


async def test_ultra_short_forecast_asset_uses_short_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_grid_and_bases(monkeypatch)
    kor_travel_map_client = _FakeKrtourClient(
        target_coords=[(126.978, 37.5665)],
        place_coords=[("f1", 126.978, 37.5665)],
    )
    forecast = _FakeForecastService(
        short_items=[_forecast_item("T1H", "18.0"), _forecast_item("LGT", "0")]
    )

    result = await run_feature_weather_kma_ultra_short_forecast(
        _context(kor_travel_map_client, forecast)
    )

    assert result.base_datetime == "202606110530"
    assert result.values_loaded == 2
    assert forecast.calls == [("short", 126, 37)]
    assert all(
        value.forecast_style == ForecastStyle.ULTRA_SHORT
        for value in kor_travel_map_client.loaded_values
    )
    assert kor_travel_map_client.success_calls[0]["dataset_key"] == "kma_ultra_short_forecast"


async def test_short_forecast_asset_uses_vilage_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_grid_and_bases(monkeypatch)
    kor_travel_map_client = _FakeKrtourClient(
        target_coords=[(126.978, 37.5665)],
        place_coords=[("f1", 126.978, 37.5665)],
    )
    forecast = _FakeForecastService(
        vilage_items=[_forecast_item("TMP", "23.5"), _forecast_item("POP", "30")]
    )

    result = await run_feature_weather_kma_short_forecast(
        _context(kor_travel_map_client, forecast)
    )

    assert result.base_datetime == "202606110200"
    assert result.values_loaded == 2
    assert forecast.calls == [("vilage", 126, 37)]
    assert all(
        value.forecast_style == ForecastStyle.SHORT
        for value in kor_travel_map_client.loaded_values
    )
    assert kor_travel_map_client.success_calls[0]["dataset_key"] == "kma_short_forecast"


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
        "KorTravelMapSettings",
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
        "KorTravelMapSettings",
        lambda: SimpleNamespace(data_go_kr_service_key=None),
    )

    resource_fn = cast(
        "Any", resources.kma_weather_client_resource.resource_fn
    )

    with pytest.raises(RuntimeError) as exc_info:
        next(resource_fn(build_init_resource_context()))

    message = str(exc_info.value)
    assert "kma_weather_client" in message
    assert "KOR_TRAVEL_MAP_DATA_GO_KR_SERVICE_KEY" in message
    assert "python-kma-api" in message


# -- T-219c: 중기예보 -------------------------------------------------------


_MID_LAND_ITEM = SimpleNamespace(
    reg_id="11B00000",
    tm_fc="202606110600",
    raw={
        "regId": "11B00000",
        "tmFc": "202606110600",
        "wf3Am": "맑음",
        "rnSt3Am": "20",
        "wf8": "구름많음",
        "rnSt8": 30,
    },
)

_MID_TEMP_ITEM = SimpleNamespace(
    reg_id="11B10101",
    tm_fc="202606110600",
    raw={
        "regId": "11B10101",
        "tmFc": "202606110600",
        "taMin3": "18",
        "taMax3": 29,
    },
)


def test_mid_rows_from_items_map_camel_case_raw() -> None:
    [land] = mid_land_rows_from_items([_MID_LAND_ITEM])
    assert land.reg_id == "11B00000"
    assert land.tm_fc == "202606110600"
    assert land.wf_3_am == "맑음"
    assert land.rn_st_3_am == 20
    assert land.wf_8 == "구름많음"
    assert land.rn_st_8 == 30
    assert land.wf_3_pm is None
    assert land.rn_st_10 is None

    [temp] = mid_temp_rows_from_items([_MID_TEMP_ITEM])
    assert temp.reg_id == "11B10101"
    assert temp.ta_min_3 == 18
    assert temp.ta_max_3 == 29
    assert temp.ta_min_4 is None


class _FakeDataGoKrClient:
    def __init__(
        self,
        *,
        land_items: list[Any] | None = None,
        temp_items: list[Any] | None = None,
    ) -> None:
        self._land_items = land_items or []
        self._temp_items = temp_items or []
        self.calls: list[tuple[str, str]] = []

    def mid_land_forecast(self, *, reg_id: str) -> list[Any]:
        self.calls.append(("land", reg_id))
        return list(self._land_items)

    def mid_temperature_forecast(self, *, reg_id: str) -> list[Any]:
        self.calls.append(("ta", reg_id))
        return list(self._temp_items)


_MID_REGION_JSON = (
    '[{"land_reg_id": "11B00000", "ta_reg_id": "11B10101",'
    ' "feature_ids": ["f1", "f2"]}]'
)


def _mid_context(
    kor_travel_map_client: _FakeKrtourClient,
    datagokr: _FakeDataGoKrClient,
    *,
    region_json: str | None = _MID_REGION_JSON,
) -> Any:
    return build_asset_context(
        resources={
            "kor_travel_map_client": kor_travel_map_client,
            "kma_datagokr_client": datagokr,
            "kma_mid_region_features": region_json,
        }
    )


async def test_mid_forecast_asset_loads_values_per_region_feature(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(kma_weather, "_latest_mid_base", lambda: "202606110600")
    kor_travel_map_client = _FakeKrtourClient()
    datagokr = _FakeDataGoKrClient(
        land_items=[_MID_LAND_ITEM], temp_items=[_MID_TEMP_ITEM]
    )

    result = await run_feature_weather_kma_mid_forecast(
        _mid_context(kor_travel_map_client, datagokr)
    )

    assert result.skipped is False
    assert result.base_datetime == "202606110600"
    assert result.regions_total == 1
    assert result.regions_fetched == 1
    assert result.features_total == 1
    # 복제 제거: land(SKY+POP ×2 시점) 4 + temp(TMN/TMX) 2 = 6, region anchor 1개.
    assert result.values_loaded == 6
    assert datagokr.calls == [("land", "11B00000"), ("ta", "11B10101")]
    assert kor_travel_map_client.success_calls == [
        {
            "provider": "python-kma-api",
            "dataset_key": "kma_mid_forecast",
            "cursor": {"base_datetime": "202606110600"},
        }
    ]


async def test_mid_forecast_asset_skips_when_cursor_matches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(kma_weather, "_latest_mid_base", lambda: "202606110600")
    kor_travel_map_client = _FakeKrtourClient(
        sync_state=SimpleNamespace(cursor={"base_datetime": "202606110600"})
    )
    datagokr = _FakeDataGoKrClient(land_items=[_MID_LAND_ITEM])

    result = await run_feature_weather_kma_mid_forecast(
        _mid_context(kor_travel_map_client, datagokr)
    )

    assert result.skipped is True
    assert datagokr.calls == []
    assert kor_travel_map_client.success_calls == []


async def test_mid_forecast_asset_skips_without_region_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(kma_weather, "_latest_mid_base", lambda: "202606110600")
    kor_travel_map_client = _FakeKrtourClient()
    datagokr = _FakeDataGoKrClient(land_items=[_MID_LAND_ITEM])

    result = await run_feature_weather_kma_mid_forecast(
        _mid_context(kor_travel_map_client, datagokr, region_json=None)
    )

    assert result.regions_total == 0
    assert result.values_loaded == 0
    assert datagokr.calls == []
    # 호출이 없었으므로 cursor를 전진시키지 않는다.
    assert kor_travel_map_client.success_calls == []


async def test_mid_forecast_asset_records_failure_when_load_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(kma_weather, "_latest_mid_base", lambda: "202606110600")
    kor_travel_map_client = _FakeKrtourClient(load_error=RuntimeError("boom"))
    datagokr = _FakeDataGoKrClient(
        land_items=[_MID_LAND_ITEM], temp_items=[_MID_TEMP_ITEM]
    )

    with pytest.raises(RuntimeError, match="boom"):
        await run_feature_weather_kma_mid_forecast(
            _mid_context(kor_travel_map_client, datagokr)
        )

    assert kor_travel_map_client.success_calls == []
    assert kor_travel_map_client.failure_calls == [
        {"provider": "python-kma-api", "dataset_key": "kma_mid_forecast"}
    ]


# -- T-219c: 특보 ------------------------------------------------------------


def _warning_record(
    *,
    title: str | None = "서울특별시 호우주의보 발표",
    tm_fc: str | None = "202606110500",
    stn_id: str | None = "108",
    seq: str | None = "1",
) -> SimpleNamespace:
    return SimpleNamespace(title=title, tm_fc=tm_fc, stn_id=stn_id, seq=seq)


def test_weather_warning_rows_extract_type_level_and_region() -> None:
    [row] = weather_warning_rows([_warning_record()])

    assert row.alert_id == "108:202606110500:1"
    assert row.alert_type == "호우"
    assert row.level == "주의보"
    assert row.title == "서울특별시 호우주의보 발표"
    assert row.issued_at.isoformat() == "2026-06-11T05:00:00+09:00"
    assert row.source_agency == "기상청"
    [region] = row.regions
    assert region.region_code == "stn:108"
    assert region.region_name == "전국"


def test_weather_warning_rows_generic_fallback_and_minute_padding() -> None:
    [row] = weather_warning_rows(
        [_warning_record(title="모르는 특보 경보", tm_fc="2026061105", stn_id="133")]
    )

    assert row.alert_type == "weather_alert"
    assert row.level == "경보"
    assert row.issued_at.isoformat() == "2026-06-11T05:00:00+09:00"
    [region] = row.regions
    assert region.region_code == "stn:133"
    assert region.region_name == "발표관서 133"


def test_weather_warning_rows_skip_unidentifiable_records() -> None:
    rows = weather_warning_rows(
        [
            _warning_record(title=None),
            _warning_record(tm_fc=None),
            _warning_record(),
        ]
    )

    assert len(rows) == 1


def test_parse_alert_tm_fc_rejects_bad_length() -> None:
    with pytest.raises(ValueError, match="tm_fc"):
        kma_weather._parse_alert_tm_fc("202606")


class _FakeBundleLoadClient:
    def __init__(self) -> None:
        self.loaded_bundles: list[Any] = []

    async def load_feature_bundles(self, bundles: Any) -> FeatureLoadResult:
        materialized = list(bundles)
        self.loaded_bundles.extend(materialized)
        return FeatureLoadResult(
            bundles_total=len(materialized),
            features_inserted=len(materialized),
        )


async def test_weather_alerts_asset_loads_notice_bundles() -> None:
    client = _FakeBundleLoadClient()
    context = build_asset_context(
        resources={
            "kor_travel_map_client": client,
            "reverse_geocoder": None,
            "fetched_at": None,
            "strict_address": True,
            "kma_weather_alert_records": [
                _warning_record(),
                _warning_record(title=None),  # 식별 불가 — 제외
            ],
        }
    )

    result = await run_feature_notice_kma_weather_alerts(context)

    assert result.provider == "python-kma-api"
    assert result.dataset_key == "kma_weather_alerts"
    assert result.load.bundles_total == 1
    [bundle] = client.loaded_bundles
    assert bundle.feature.kind.value == "notice"
    assert bundle.feature.detail.notice_type == "heavy_rain_warning"
    # region명이 위치 단서(raw_address) — strict 주소 검증 통과의 핵심.
    assert bundle.source_record.raw_address == "전국"
    assert result.address_validation.error_count == 0


# -- T-219c: 특보 fetcher / datagokr client resource --------------------------


class _FakeWarningDataGoKrClient:
    instances: list[_FakeWarningDataGoKrClient] = []
    pages: list[list[Any]] = []

    def __init__(self, *, service_key: str) -> None:
        self.service_key = service_key
        self.closed = False
        self.calls: list[dict[str, Any]] = []
        _FakeWarningDataGoKrClient.instances.append(self)

    def weather_warning_list(self, **kwargs: Any) -> list[Any]:
        self.calls.append(kwargs)
        index = len(self.calls) - 1
        pages = type(self).pages
        return pages[index] if index < len(pages) else []

    def close(self) -> None:
        self.closed = True


def _install_fake_kma_module(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    module = ModuleType("kma")
    module.__dict__["DataGoKrClient"] = _FakeWarningDataGoKrClient
    monkeypatch.setitem(sys.modules, "kma", module)
    return module


def test_fetch_kma_weather_alerts_paginates_and_closes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _FakeWarningDataGoKrClient.instances = []
    _FakeWarningDataGoKrClient.pages = [
        [_warning_record() for _ in range(100)],
        [_warning_record(seq="200")],
    ]
    _install_fake_kma_module(monkeypatch)
    settings = KorTravelMapSettings(
        data_go_kr_service_key=SecretStr("data-key"),
        kma_weather_alert_lookback_days=2,
    )

    records = list(fetch_kma_weather_alerts(settings))

    assert len(records) == 101
    [client] = _FakeWarningDataGoKrClient.instances
    assert client.service_key == "data-key"
    assert client.closed is True
    assert client.calls[0]["stn_id"] == provider_fetchers.KMA_WEATHER_ALERT_STN_ID
    assert client.calls[0]["page_no"] == 1
    assert client.calls[1]["page_no"] == 2
    window = client.calls[0]["to_tm_fc"] - client.calls[0]["from_tm_fc"]
    assert window.days == 1  # lookback 2일 = 오늘 포함 어제부터


def test_fetch_kma_weather_alerts_requires_credential() -> None:
    settings = KorTravelMapSettings(data_go_kr_service_key=None)

    with pytest.raises(ProviderCredentialMissing, match="DATA_GO_KR_SERVICE_KEY"):
        next(iter(fetch_kma_weather_alerts(settings)))


def test_kma_datagokr_client_resource_yields_client_and_closes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _FakeWarningDataGoKrClient.instances = []
    _FakeWarningDataGoKrClient.pages = []
    _install_fake_kma_module(monkeypatch)
    monkeypatch.setattr(
        resources,
        "KorTravelMapSettings",
        lambda: SimpleNamespace(data_go_kr_service_key=SecretStr("data-key")),
    )

    resource_fn = cast("Any", resources.kma_datagokr_client_resource.resource_fn)
    resource_iter = resource_fn(build_init_resource_context())
    client = next(resource_iter)

    assert client.service_key == "data-key"

    with pytest.raises(StopIteration):
        next(resource_iter)

    assert client.closed is True


def test_kma_datagokr_client_resource_guard_without_credential(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        resources,
        "KorTravelMapSettings",
        lambda: SimpleNamespace(data_go_kr_service_key=None),
    )

    resource_fn = cast("Any", resources.kma_datagokr_client_resource.resource_fn)

    with pytest.raises(RuntimeError) as exc_info:
        next(resource_fn(build_init_resource_context()))

    message = str(exc_info.value)
    assert "kma_datagokr_client" in message
    assert "KOR_TRAVEL_MAP_DATA_GO_KR_SERVICE_KEY" in message
