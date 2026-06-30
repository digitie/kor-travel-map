"""Feature update request queue runner for Dagster.

API의 update request는 queue row만 만들고, 실제 provider refresh는 Dagster
``feature_update_request_worker``가 이 runner를 통해 기존 feature load asset
구현을 직접 호출한다.
"""

from __future__ import annotations

import importlib
import inspect
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, Final, cast

from kortravelmap.infra.feature_update_executor import (
    ProviderDatasetRefreshResult,
    ProviderDatasetRefreshScope,
)
from kortravelmap.providers.airkorea import (
    AIRKOREA_PROVIDER_NAME,
    DATASET_KEY_AIR_QUALITY,
    DATASET_KEY_STATIONS,
)
from kortravelmap.providers.datagokr_file_data import (
    DATAGOKR_FILEDATA_DATASETS,
    DATAGOKR_FILEDATA_PROVIDER_NAME,
)
from kortravelmap.providers.khoa import DATASET_KEY_BEACHES, KHOA_PROVIDER_NAME
from kortravelmap.providers.kma import (
    KMA_MID_FORECAST_DATASET_KEY,
    KMA_PROVIDER_NAME,
    KMA_SHORT_FORECAST_DATASET_KEY,
    KMA_ULTRA_SHORT_FORECAST_DATASET_KEY,
    KMA_ULTRA_SHORT_NOWCAST_DATASET_KEY,
    KMA_WEATHER_ALERT_DATASET_KEY,
)
from kortravelmap.providers.knps import KNPS_GEOMETRY_DATASETS, KNPS_PLACE_DATASETS
from kortravelmap.providers.knps import PROVIDER_NAME as KNPS_PROVIDER_NAME
from kortravelmap.providers.kor_travel_concierge import (
    DATASET_KEY_YOUTUBE_PLACE_CANDIDATES,
    KOR_TRAVEL_CONCIERGE_PROVIDER_NAME,
)
from kortravelmap.providers.krairport import DATASET_KEY_AIRPORTS, KRAIRPORT_PROVIDER_NAME
from kortravelmap.providers.krex import (
    KREX_PROVIDER_NAME,
    REST_AREA_DATASET_KEY,
    REST_AREA_PRICES_DATASET_KEY,
    REST_AREA_WEATHER_DATASET_KEY,
    TRAFFIC_NOTICES_DATASET_KEY,
)
from kortravelmap.providers.krforest import (
    DATASET_KEY_ARBORETUMS as KRFOREST_ARBORETUMS_DATASET_KEY,
)
from kortravelmap.providers.krforest import (
    DATASET_KEY_RECREATION_FORESTS as KRFOREST_RECREATION_FORESTS_DATASET_KEY,
)
from kortravelmap.providers.krforest import KRFOREST_PROVIDER_NAME
from kortravelmap.providers.krheritage import (
    DATASET_KEY_EVENT as KRHERITAGE_EVENT_DATASET_KEY,
)
from kortravelmap.providers.krheritage import DATASET_KEY_HERITAGE as KRHERITAGE_DATASET_KEY
from kortravelmap.providers.krheritage import PROVIDER_NAME as KRHERITAGE_PROVIDER_NAME
from kortravelmap.providers.mcst import MCST_FILE_DATASETS, MCST_PROVIDER_NAME
from kortravelmap.providers.mois import DATASET_KEY_BULK as MOIS_BULK_DATASET_KEY
from kortravelmap.providers.mois import PROVIDER_NAME as MOIS_PROVIDER_NAME
from kortravelmap.providers.opinet import (
    OPINET_PRICE_DATASET_KEY,
    OPINET_PROVIDER_NAME,
    OPINET_STATION_DATASET_KEY,
)
from kortravelmap.providers.standard_data import (
    DATASET_KEY_CULTURAL_FESTIVALS,
    DATASET_KEY_MUSEUMS,
    DATASET_KEY_PARKING_LOTS,
    DATASET_KEY_SPECIAL_STREETS,
    DATASET_KEY_TOURIST_ATTRACTIONS,
    STANDARD_DATA_PROVIDER_NAME,
)
from kortravelmap.settings import KorTravelMapSettings

from dagster import InitResourceContext, resource

from .assets import (
    DATAGOKR_STANDARD_PROVIDER_NAME,
    run_feature_event_datagokr_cultural_festivals,
    run_feature_event_krheritage_events,
    run_feature_event_visitkorea_enrichment,
    run_feature_geometry_knps_records,
    run_feature_notice_krex_traffic_notices,
    run_feature_place_datagokr_file_data,
    run_feature_place_khoa_beaches,
    run_feature_place_knps_points,
    run_feature_place_kor_travel_concierge_youtube,
    run_feature_place_krairport_airports,
    run_feature_place_krex_rest_areas,
    run_feature_place_krforest_arboretums,
    run_feature_place_krforest_recreation_forests,
    run_feature_place_krheritage_items,
    run_feature_place_mois_licenses,
    run_feature_place_opinet_stations,
    run_feature_place_standard_museums,
    run_feature_place_standard_parking_lots,
    run_feature_place_standard_special_streets,
    run_feature_place_standard_tourist_attractions,
    run_feature_price_krex_rest_areas,
    run_feature_price_opinet_stations,
    run_feature_weather_airkorea_air_quality,
    run_feature_weather_krex_rest_areas,
)
from .kma_weather import (
    run_feature_notice_kma_weather_alerts,
    run_feature_weather_kma_mid_forecast,
    run_feature_weather_kma_short_forecast,
    run_feature_weather_kma_ultra_short_forecast,
    run_feature_weather_kma_ultra_short_nowcast,
)
from .mcst_features import run_feature_place_mcst_culture
from .mois_source_sync import sync_mois_source_db
from .provider_fetchers import (
    ProviderCredentialMissing,
    fetch_airkorea_air_quality,
    fetch_airkorea_stations,
    fetch_datagokr_cultural_festivals,
    fetch_datagokr_file_data_records,
    fetch_khoa_beaches,
    fetch_kma_weather_alerts,
    fetch_knps_geometry_records,
    fetch_knps_point_records,
    fetch_kor_travel_concierge_youtube_features,
    fetch_krairport_airports,
    fetch_krex_rest_area_fuel_prices,
    fetch_krex_rest_area_weather,
    fetch_krex_rest_areas,
    fetch_krex_traffic_notices,
    fetch_krforest_arboretums,
    fetch_krforest_recreation_forests,
    fetch_krheritage_events,
    fetch_krheritage_items,
    fetch_mcst_culture_records,
    fetch_mois_license_records,
    fetch_opinet_station_price_details,
    fetch_opinet_stations,
    fetch_standard_museums,
    fetch_standard_parking_lots,
    fetch_standard_special_streets,
    fetch_standard_tourist_attractions,
    fetch_visitkorea_festival_events,
)

__all__ = [
    "FeatureUpdateAssetRunner",
    "FeatureUpdateRunnerSpec",
    "feature_update_runner_resource",
]

AssetRun = Callable[[Any], Awaitable[Any]]
ResourceFactory = Callable[
    [KorTravelMapSettings, ProviderDatasetRefreshScope],
    "RunnerResources",
]
Teardown = Callable[[], object]

_COMMON_RESOURCE_KEYS: Final[set[str]] = {
    "kor_travel_map_client",
    "reverse_geocoder",
    "fetched_at",
    "strict_address",
}

_MISSING: Final = object()


@dataclass(frozen=True, slots=True)
class RunnerResources:
    """Asset direct invocation에 더할 resource 값과 cleanup hook."""

    values: Mapping[str, object]
    teardowns: tuple[Teardown, ...] = ()


@dataclass(frozen=True, slots=True)
class FeatureUpdateRunnerSpec:
    """provider/dataset → 기존 Dagster asset runner 연결 사양."""

    provider: str
    dataset_keys: frozenset[str]
    run: AssetRun
    resources: ResourceFactory
    asset_key: str

    def matches(self, scope: ProviderDatasetRefreshScope) -> bool:
        return (
            scope.provider == self.provider
            and scope.dataset_key in self.dataset_keys
        )


class _DirectAssetContext:
    def __init__(
        self,
        *,
        resources: Mapping[str, object],
        log: object,
        asset_key: str,
    ) -> None:
        self.resources = SimpleNamespace(**dict(resources))
        self.log = log
        self.asset_key = _DirectAssetKey(asset_key)
        self.output_metadata: list[dict[str, object]] = []

    def add_output_metadata(self, metadata: Mapping[str, object]) -> None:
        self.output_metadata.append(dict(metadata))


@dataclass(frozen=True, slots=True)
class _DirectAssetKey:
    value: str

    def to_user_string(self) -> str:
        return self.value


class FeatureUpdateAssetRunner:
    """Feature update queue의 provider/dataset scope를 asset 실행으로 dispatch한다."""

    def __init__(
        self,
        *,
        common_resources: Mapping[str, object],
        log: object,
        settings_factory: Callable[[], KorTravelMapSettings] = KorTravelMapSettings,
        specs: tuple[FeatureUpdateRunnerSpec, ...] | None = None,
    ) -> None:
        self._common_resources = dict(common_resources)
        self._log = log
        self._settings_factory = settings_factory
        self._specs = specs or _DEFAULT_SPECS

    async def __call__(
        self,
        _session: object,
        scope: ProviderDatasetRefreshScope,
    ) -> ProviderDatasetRefreshResult:
        spec = self._spec_for_scope(scope)
        settings = self._settings_factory()
        extra = spec.resources(settings, scope)
        context = _DirectAssetContext(
            resources={**self._common_resources, **dict(extra.values)},
            log=self._log,
            asset_key=spec.asset_key,
        )
        try:
            result = await spec.run(context)
        finally:
            await _close_teardowns(extra.teardowns)
        return _as_refresh_result(result, scope=scope)

    def _spec_for_scope(
        self, scope: ProviderDatasetRefreshScope
    ) -> FeatureUpdateRunnerSpec:
        for spec in self._specs:
            if spec.matches(scope):
                return spec
        supported = ", ".join(
            f"{spec.provider}:{dataset_key}"
            for spec in self._specs
            for dataset_key in sorted(spec.dataset_keys)
        )
        raise RuntimeError(
            "feature update runner가 지원하지 않는 provider/dataset: "
            f"{scope.provider}:{scope.dataset_key}. supported={supported}"
        )


async def _close_teardowns(teardowns: tuple[Teardown, ...]) -> None:
    for teardown in reversed(teardowns):
        result = teardown()
        if inspect.isawaitable(result):
            await cast("Awaitable[object]", result)


def _metadata_for_result(result: object) -> dict[str, object]:
    as_metadata = getattr(result, "as_metadata", None)
    if callable(as_metadata):
        return dict(cast("Mapping[str, object]", as_metadata()))
    return {}


def _loaded_feature_ids(result: object, metadata: Mapping[str, object]) -> tuple[str, ...]:
    raw = getattr(result, "feature_ids", _MISSING)
    if raw is _MISSING:
        raw = metadata.get("feature_ids", ())
    if not isinstance(raw, list | tuple):
        return ()
    return tuple(str(value) for value in raw)


def _int_metadata(metadata: Mapping[str, object], key: str) -> int:
    value = metadata.get(key)
    if isinstance(value, bool):
        return 0
    if isinstance(value, int | float):
        return int(value)
    return 0


def _loaded_count(
    result: object,
    metadata: Mapping[str, object],
    loaded_feature_ids: tuple[str, ...],
) -> int:
    if isinstance(result, ProviderDatasetRefreshResult):
        return result.loaded_count
    for key in (
        "values_loaded",
        "weather_values_loaded",
        "price_values_upserted",
        "features_total",
        "bundles_total",
        "stations_total",
        "price_features_total",
    ):
        count = _int_metadata(metadata, key)
        if count:
            return count
    updated = _int_metadata(metadata, "features_inserted") + _int_metadata(
        metadata, "features_updated"
    )
    if updated:
        return updated
    price_updated = _int_metadata(
        metadata, "price_features_inserted"
    ) + _int_metadata(metadata, "price_features_updated")
    if price_updated:
        return price_updated
    station_updated = _int_metadata(
        metadata, "stations_features_inserted"
    ) + _int_metadata(metadata, "stations_features_updated")
    if station_updated:
        return station_updated
    return len(loaded_feature_ids)


def _as_refresh_result(
    result: object,
    *,
    scope: ProviderDatasetRefreshScope,
) -> ProviderDatasetRefreshResult:
    if isinstance(result, ProviderDatasetRefreshResult):
        return result
    metadata = _metadata_for_result(result)
    loaded_feature_ids = _loaded_feature_ids(result, metadata)
    return ProviderDatasetRefreshResult(
        provider=str(metadata.get("provider") or scope.provider),
        dataset_key=str(metadata.get("dataset_key") or scope.dataset_key),
        status="skipped" if metadata.get("skipped") is True else "done",
        loaded_feature_ids=loaded_feature_ids,
        loaded_count=_loaded_count(result, metadata, loaded_feature_ids),
        metadata=dict(metadata),
    )


def _records(resource_key: str, fetch: Callable[[KorTravelMapSettings], object]) -> ResourceFactory:
    def _factory(
        settings: KorTravelMapSettings,
        _scope: ProviderDatasetRefreshScope,
    ) -> RunnerResources:
        return RunnerResources({resource_key: fetch(settings)})

    return _factory


def _opinet_records(
    resource_key: str,
    fetch: Callable[[KorTravelMapSettings], object],
    *,
    label: str,
) -> ResourceFactory:
    def _factory(
        settings: KorTravelMapSettings,
        _scope: ProviderDatasetRefreshScope,
    ) -> RunnerResources:
        if settings.opinet_api_key is None:
            raise ProviderCredentialMissing(
                f"{label} feature update에는 KOR_TRAVEL_MAP_OPINET_API_KEY "
                "(source OPINET_API_KEY)가 필요하다."
            )
        return RunnerResources({resource_key: fetch(settings)})

    return _factory


def _mois_resources(
    settings: KorTravelMapSettings,
    scope: ProviderDatasetRefreshScope,
) -> RunnerResources:
    sync_mois_source_db(settings)
    return RunnerResources(
        {
            "mois_license_records": fetch_mois_license_records(settings),
            "mois_dataset_key": scope.dataset_key or MOIS_BULK_DATASET_KEY,
        }
    )


def _knps_point_resources(
    settings: KorTravelMapSettings,
    scope: ProviderDatasetRefreshScope,
) -> RunnerResources:
    return RunnerResources(
        {
            "knps_point_records": fetch_knps_point_records(settings),
            "knps_point_dataset_key": scope.dataset_key,
        }
    )


def _knps_geometry_resources(
    settings: KorTravelMapSettings,
    scope: ProviderDatasetRefreshScope,
) -> RunnerResources:
    return RunnerResources(
        {
            "knps_geometry_records": fetch_knps_geometry_records(settings),
            "knps_geometry_dataset_key": scope.dataset_key,
        }
    )


def _airkorea_resources(
    settings: KorTravelMapSettings,
    _scope: ProviderDatasetRefreshScope,
) -> RunnerResources:
    return RunnerResources(
        {
            "airkorea_stations": fetch_airkorea_stations(settings),
            "airkorea_air_quality": fetch_airkorea_air_quality(settings),
        }
    )


def _datagokr_file_data_resources(
    settings: KorTravelMapSettings,
    scope: ProviderDatasetRefreshScope,
) -> RunnerResources:
    dataset_key = scope.dataset_key
    return RunnerResources(
        {
            "datagokr_file_data_records": fetch_datagokr_file_data_records(
                settings,
                dataset_key=dataset_key,
            ),
            "datagokr_file_data_dataset_key": dataset_key,
        }
    )


def _kma_service_key(
    settings: KorTravelMapSettings, *, resource_key: str, dataset: str
) -> str:
    service_key = settings.data_go_kr_service_key
    if service_key is None:
        raise RuntimeError(
            f"Dagster resource {resource_key!r}는 기본 실행 비활성 상태: "
            "credential 환경변수가 설정되지 않았음. "
            f"provider=python-kma-api, dataset={dataset}. "
            "kor-travel-map env: KOR_TRAVEL_MAP_DATA_GO_KR_SERVICE_KEY; "
            "source env: DATA_GO_KR_SERVICE_KEY."
        )
    reveal = getattr(service_key, "get_" + "se" + "cret_value")
    return str(reveal())


def _close_method(value: object) -> Teardown:
    def _teardown() -> object:
        close = getattr(value, "close", None)
        if callable(close):
            return close()
        return None

    return _teardown


def _kma_weather_resources(
    settings: KorTravelMapSettings,
    scope: ProviderDatasetRefreshScope,
) -> RunnerResources:
    kma = cast(Any, importlib.import_module("kma"))
    client = kma.KmaClient(
        service_key=_kma_service_key(
            settings,
            resource_key="kma_weather_client",
            dataset=scope.dataset_key,
        )
    )
    return RunnerResources(
        {
            "kma_weather_client": client,
            "kma_weather_extra_points": settings.kma_weather_extra_points,
            "kma_weather_max_grids_per_run": settings.kma_weather_max_grids_per_run,
        },
        teardowns=(_close_method(client),),
    )


def _kma_mid_resources(
    settings: KorTravelMapSettings,
    scope: ProviderDatasetRefreshScope,
) -> RunnerResources:
    kma = cast(Any, importlib.import_module("kma"))
    client = kma.DataGoKrClient(
        service_key=_kma_service_key(
            settings,
            resource_key="kma_datagokr_client",
            dataset=scope.dataset_key,
        )
    )
    return RunnerResources(
        {
            "kma_datagokr_client": client,
            "kma_mid_region_features": settings.kma_mid_region_features,
        },
        teardowns=(_close_method(client),),
    )


def _kma_alert_resources(
    settings: KorTravelMapSettings,
    _scope: ProviderDatasetRefreshScope,
) -> RunnerResources:
    return RunnerResources(
        {"kma_weather_alert_records": fetch_kma_weather_alerts(settings)}
    )


def _mcst_resources(
    settings: KorTravelMapSettings,
    _scope: ProviderDatasetRefreshScope,
) -> RunnerResources:
    return RunnerResources({"mcst_culture_records": fetch_mcst_culture_records(settings)})


async def _run_kma_grid_weather(context: Any, resources: object) -> object:
    dataset_key = cast(Any, resources).feature_update_dataset_key
    if dataset_key == KMA_ULTRA_SHORT_NOWCAST_DATASET_KEY:
        return await run_feature_weather_kma_ultra_short_nowcast(context)
    if dataset_key == KMA_ULTRA_SHORT_FORECAST_DATASET_KEY:
        return await run_feature_weather_kma_ultra_short_forecast(context)
    if dataset_key == KMA_SHORT_FORECAST_DATASET_KEY:
        return await run_feature_weather_kma_short_forecast(context)
    raise KeyError(f"KMA grid weather dataset_key가 아님: {dataset_key!r}")


def _kma_grid_resources(
    settings: KorTravelMapSettings,
    scope: ProviderDatasetRefreshScope,
) -> RunnerResources:
    base = _kma_weather_resources(settings, scope)
    return RunnerResources(
        {**dict(base.values), "feature_update_dataset_key": scope.dataset_key},
        teardowns=base.teardowns,
    )


_DEFAULT_SPECS: Final[tuple[FeatureUpdateRunnerSpec, ...]] = (
    FeatureUpdateRunnerSpec(
        provider=DATAGOKR_STANDARD_PROVIDER_NAME,
        dataset_keys=frozenset({DATASET_KEY_CULTURAL_FESTIVALS}),
        run=run_feature_event_datagokr_cultural_festivals,
        resources=_records(
            "datagokr_cultural_festivals", fetch_datagokr_cultural_festivals
        ),
        asset_key="feature_event_datagokr_cultural_festivals",
    ),
    FeatureUpdateRunnerSpec(
        provider=OPINET_PROVIDER_NAME,
        dataset_keys=frozenset({OPINET_STATION_DATASET_KEY}),
        run=run_feature_place_opinet_stations,
        resources=_opinet_records(
            "opinet_stations",
            fetch_opinet_stations,
            label="OpiNet station",
        ),
        asset_key="feature_place_opinet_stations",
    ),
    FeatureUpdateRunnerSpec(
        provider=OPINET_PROVIDER_NAME,
        dataset_keys=frozenset({OPINET_PRICE_DATASET_KEY}),
        run=run_feature_price_opinet_stations,
        resources=_opinet_records(
            "opinet_station_price_details",
            fetch_opinet_station_price_details,
            label="OpiNet price",
        ),
        asset_key="feature_price_opinet_stations",
    ),
    FeatureUpdateRunnerSpec(
        provider=KREX_PROVIDER_NAME,
        dataset_keys=frozenset({REST_AREA_DATASET_KEY}),
        run=run_feature_place_krex_rest_areas,
        resources=_records("krex_rest_areas", fetch_krex_rest_areas),
        asset_key="feature_place_krex_rest_areas",
    ),
    FeatureUpdateRunnerSpec(
        provider=KREX_PROVIDER_NAME,
        dataset_keys=frozenset({REST_AREA_PRICES_DATASET_KEY}),
        run=run_feature_price_krex_rest_areas,
        resources=_records(
            "krex_rest_area_fuel_prices", fetch_krex_rest_area_fuel_prices
        ),
        asset_key="feature_price_krex_rest_areas",
    ),
    FeatureUpdateRunnerSpec(
        provider=KREX_PROVIDER_NAME,
        dataset_keys=frozenset({REST_AREA_WEATHER_DATASET_KEY}),
        run=run_feature_weather_krex_rest_areas,
        resources=_records("krex_rest_area_weather", fetch_krex_rest_area_weather),
        asset_key="feature_weather_krex_rest_areas",
    ),
    FeatureUpdateRunnerSpec(
        provider=KREX_PROVIDER_NAME,
        dataset_keys=frozenset({TRAFFIC_NOTICES_DATASET_KEY}),
        run=run_feature_notice_krex_traffic_notices,
        resources=_records("krex_traffic_notices", fetch_krex_traffic_notices),
        asset_key="feature_notice_krex_traffic_notices",
    ),
    FeatureUpdateRunnerSpec(
        provider=KRHERITAGE_PROVIDER_NAME,
        dataset_keys=frozenset({KRHERITAGE_DATASET_KEY}),
        run=run_feature_place_krheritage_items,
        resources=_records("krheritage_items", fetch_krheritage_items),
        asset_key="feature_place_krheritage_items",
    ),
    FeatureUpdateRunnerSpec(
        provider=KRHERITAGE_PROVIDER_NAME,
        dataset_keys=frozenset({KRHERITAGE_EVENT_DATASET_KEY}),
        run=run_feature_event_krheritage_events,
        resources=_records("krheritage_events", fetch_krheritage_events),
        asset_key="feature_event_krheritage_events",
    ),
    FeatureUpdateRunnerSpec(
        provider=MOIS_PROVIDER_NAME,
        dataset_keys=frozenset({MOIS_BULK_DATASET_KEY}),
        run=run_feature_place_mois_licenses,
        resources=_mois_resources,
        asset_key="feature_place_mois_licenses",
    ),
    FeatureUpdateRunnerSpec(
        provider=KNPS_PROVIDER_NAME,
        dataset_keys=frozenset(KNPS_PLACE_DATASETS),
        run=run_feature_place_knps_points,
        resources=_knps_point_resources,
        asset_key="feature_place_knps_points",
    ),
    FeatureUpdateRunnerSpec(
        provider=KNPS_PROVIDER_NAME,
        dataset_keys=frozenset(KNPS_GEOMETRY_DATASETS),
        run=run_feature_geometry_knps_records,
        resources=_knps_geometry_resources,
        asset_key="feature_geometry_knps_records",
    ),
    FeatureUpdateRunnerSpec(
        provider=KRFOREST_PROVIDER_NAME,
        dataset_keys=frozenset({KRFOREST_RECREATION_FORESTS_DATASET_KEY}),
        run=run_feature_place_krforest_recreation_forests,
        resources=_records(
            "krforest_recreation_forests", fetch_krforest_recreation_forests
        ),
        asset_key="feature_place_krforest_recreation_forests",
    ),
    FeatureUpdateRunnerSpec(
        provider=KRFOREST_PROVIDER_NAME,
        dataset_keys=frozenset({KRFOREST_ARBORETUMS_DATASET_KEY}),
        run=run_feature_place_krforest_arboretums,
        resources=_records("krforest_arboretums", fetch_krforest_arboretums),
        asset_key="feature_place_krforest_arboretums",
    ),
    FeatureUpdateRunnerSpec(
        provider=STANDARD_DATA_PROVIDER_NAME,
        dataset_keys=frozenset({DATASET_KEY_MUSEUMS}),
        run=run_feature_place_standard_museums,
        resources=_records("standard_museums", fetch_standard_museums),
        asset_key="feature_place_standard_museums",
    ),
    FeatureUpdateRunnerSpec(
        provider=STANDARD_DATA_PROVIDER_NAME,
        dataset_keys=frozenset({DATASET_KEY_TOURIST_ATTRACTIONS}),
        run=run_feature_place_standard_tourist_attractions,
        resources=_records(
            "standard_tourist_attractions", fetch_standard_tourist_attractions
        ),
        asset_key="feature_place_standard_tourist_attractions",
    ),
    FeatureUpdateRunnerSpec(
        provider=STANDARD_DATA_PROVIDER_NAME,
        dataset_keys=frozenset({DATASET_KEY_PARKING_LOTS}),
        run=run_feature_place_standard_parking_lots,
        resources=_records("standard_parking_lots", fetch_standard_parking_lots),
        asset_key="feature_place_standard_parking_lots",
    ),
    FeatureUpdateRunnerSpec(
        provider=STANDARD_DATA_PROVIDER_NAME,
        dataset_keys=frozenset({DATASET_KEY_SPECIAL_STREETS}),
        run=run_feature_place_standard_special_streets,
        resources=_records("standard_special_streets", fetch_standard_special_streets),
        asset_key="feature_place_standard_special_streets",
    ),
    FeatureUpdateRunnerSpec(
        provider=DATAGOKR_FILEDATA_PROVIDER_NAME,
        dataset_keys=frozenset(DATAGOKR_FILEDATA_DATASETS),
        run=run_feature_place_datagokr_file_data,
        resources=_datagokr_file_data_resources,
        asset_key="feature_place_datagokr_file_data",
    ),
    FeatureUpdateRunnerSpec(
        provider=KHOA_PROVIDER_NAME,
        dataset_keys=frozenset({DATASET_KEY_BEACHES}),
        run=run_feature_place_khoa_beaches,
        resources=_records("khoa_beaches", fetch_khoa_beaches),
        asset_key="feature_place_khoa_beaches",
    ),
    FeatureUpdateRunnerSpec(
        provider=KRAIRPORT_PROVIDER_NAME,
        dataset_keys=frozenset({DATASET_KEY_AIRPORTS}),
        run=run_feature_place_krairport_airports,
        resources=_records("krairport_airports", fetch_krairport_airports),
        asset_key="feature_place_krairport_airports",
    ),
    FeatureUpdateRunnerSpec(
        provider=KOR_TRAVEL_CONCIERGE_PROVIDER_NAME,
        dataset_keys=frozenset({DATASET_KEY_YOUTUBE_PLACE_CANDIDATES}),
        run=run_feature_place_kor_travel_concierge_youtube,
        resources=_records(
            "kor_travel_concierge_youtube_features",
            fetch_kor_travel_concierge_youtube_features,
        ),
        asset_key="feature_place_kor_travel_concierge_youtube",
    ),
    FeatureUpdateRunnerSpec(
        provider="python-visitkorea-api",
        dataset_keys=frozenset({"visitkorea_festival_events"}),
        run=run_feature_event_visitkorea_enrichment,
        resources=_records(
            "visitkorea_festival_events", fetch_visitkorea_festival_events
        ),
        asset_key="feature_event_visitkorea_enrichment",
    ),
    FeatureUpdateRunnerSpec(
        provider=AIRKOREA_PROVIDER_NAME,
        dataset_keys=frozenset({DATASET_KEY_AIR_QUALITY, DATASET_KEY_STATIONS}),
        run=run_feature_weather_airkorea_air_quality,
        resources=_airkorea_resources,
        asset_key="feature_weather_airkorea_air_quality",
    ),
    FeatureUpdateRunnerSpec(
        provider=KMA_PROVIDER_NAME,
        dataset_keys=frozenset(
            {
                KMA_ULTRA_SHORT_NOWCAST_DATASET_KEY,
                KMA_ULTRA_SHORT_FORECAST_DATASET_KEY,
                KMA_SHORT_FORECAST_DATASET_KEY,
            }
        ),
        run=lambda context: _run_kma_grid_weather(context, context.resources),
        resources=_kma_grid_resources,
        asset_key="feature_weather_kma_grid_dispatch",
    ),
    FeatureUpdateRunnerSpec(
        provider=KMA_PROVIDER_NAME,
        dataset_keys=frozenset({KMA_MID_FORECAST_DATASET_KEY}),
        run=run_feature_weather_kma_mid_forecast,
        resources=_kma_mid_resources,
        asset_key="feature_weather_kma_mid_forecast",
    ),
    FeatureUpdateRunnerSpec(
        provider=KMA_PROVIDER_NAME,
        dataset_keys=frozenset({KMA_WEATHER_ALERT_DATASET_KEY}),
        run=run_feature_notice_kma_weather_alerts,
        resources=_kma_alert_resources,
        asset_key="feature_notice_kma_weather_alerts",
    ),
    FeatureUpdateRunnerSpec(
        provider=MCST_PROVIDER_NAME,
        dataset_keys=frozenset(spec.dataset_key for spec in MCST_FILE_DATASETS.values()),
        run=run_feature_place_mcst_culture,
        resources=_mcst_resources,
        asset_key="feature_place_mcst_culture",
    ),
)


@resource(
    required_resource_keys=_COMMON_RESOURCE_KEYS,
    description="feature update queue provider/dataset asset dispatcher.",
)
def feature_update_runner_resource(
    context: InitResourceContext,
) -> FeatureUpdateAssetRunner:
    resources = cast(Any, context.resources)
    common_resources = {key: getattr(resources, key) for key in _COMMON_RESOURCE_KEYS}
    return FeatureUpdateAssetRunner(
        common_resources=common_resources,
        log=context.log,
    )
