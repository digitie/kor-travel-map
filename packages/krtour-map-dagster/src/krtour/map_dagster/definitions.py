"""Dagster code location entrypoint."""

from __future__ import annotations

from typing import Any, Final, cast

from dagster import Definitions, ResourceDefinition, resource
from krtour.map.settings import KrtourMapSettings

from .assets import FEATURE_LOAD_ASSETS
from .batch_dag import BATCH_DAG_JOBS
from .curated_features import (
    CURATED_FEATURE_ASSETS,
    CURATED_FEATURE_JOBS,
    CURATED_FEATURE_SCHEDULES,
)
from .kma_weather import KMA_WEATHER_ASSETS
from .maintenance import MAINTENANCE_JOBS, MAINTENANCE_SCHEDULES
from .mcst_features import MCST_FEATURE_ASSETS
from .mois_source_sync import MOIS_SOURCE_SYNC_JOBS, MOIS_SOURCE_SYNC_SCHEDULES
from .offline_uploads import OFFLINE_UPLOAD_JOBS
from .resources import (
    PROVIDER_RECORD_RESOURCE_DEFINITIONS,
    kma_datagokr_client_resource,
    kma_weather_client_resource,
    krtour_map_client_resource,
    offline_upload_store_resource,
    reverse_geocoder_resource,
)
from .schedules import FEATURE_LOAD_JOBS, FEATURE_LOAD_SCHEDULES
from .sensors import FEATURE_UPDATE_JOBS, FEATURE_UPDATE_SENSORS

REQUIRED_RESOURCE_KEYS: Final[tuple[str, ...]] = (
    "krtour_map_client",
    "reverse_geocoder",
    "feature_update_runner",
    "offline_upload_store",
    "fetched_at",
    "strict_address",
    "datagokr_cultural_festivals",
    "opinet_stations",
    "krex_rest_areas",
    "krex_traffic_notices",
    "krheritage_items",
    "krheritage_events",
    "mois_license_records",
    "mois_dataset_key",
    "knps_point_records",
    "knps_point_dataset_key",
    "knps_geometry_records",
    "knps_geometry_dataset_key",
    "krforest_recreation_forests",
    "krforest_arboretums",
    "standard_museums",
    "standard_tourist_attractions",
    "standard_parking_lots",
    "khoa_beaches",
    "krairport_airports",
    "airkorea_stations",
    "airkorea_air_quality",
    "visitkorea_festival_events",
    "krtour_ai_agent_youtube_features",
    "kma_weather_client",
    "kma_weather_extra_points",
    "kma_weather_max_grids_per_run",
    "kma_datagokr_client",
    "kma_mid_region_features",
    "kma_weather_alert_records",
    "mcst_culture_records",
)
"""Feature 적재 asset이 요구하는 Dagster resource key."""

DEFAULT_RESOURCE_VALUES: Final[dict[str, object]] = {
    "fetched_at": None,
    "feature_update_failure_notifier": None,
    "mois_dataset_key": "mois_license_features_bulk",
}
"""운영 definitions가 교체하지 않아도 안전한 기본 resource 값."""

# KNPS dataset key는 ``KrtourMapSettings``에서 읽어 fetcher(``fetch_knps_*_records``)와
# asset의 ``knps_*_dataset_key`` resource가 같은 dataset을 보게 한다(불일치 방지).
# KMA weather 대상 설정 2종(T-219b)도 같은 메커니즘으로 asset에 주입한다.
# strict_address는 주소/좌표 검증 모드(strict/drop/off, #376)를 settings에서 읽는다.
SETTINGS_VALUE_RESOURCES: Final[dict[str, str]] = {
    "knps_point_dataset_key": "knps_point_dataset_key",
    "knps_geometry_dataset_key": "knps_geometry_dataset_key",
    "kma_weather_extra_points": "kma_weather_extra_points",
    "kma_weather_max_grids_per_run": "kma_weather_max_grids_per_run",
    "kma_mid_region_features": "kma_mid_region_features",
    "strict_address": "dagster_address_validation",
}
"""resource key → 같은 값을 제공하는 ``KrtourMapSettings`` 속성명."""

DEFAULT_RESOURCE_DEFINITIONS: Final[dict[str, ResourceDefinition]] = {
    "krtour_map_client": krtour_map_client_resource,
    "offline_upload_store": offline_upload_store_resource,
    "reverse_geocoder": reverse_geocoder_resource,
    "kma_weather_client": kma_weather_client_resource,
    "kma_datagokr_client": kma_datagokr_client_resource,
    **PROVIDER_RECORD_RESOURCE_DEFINITIONS,
}
"""환경변수 기반 실제 구현을 제공하는 기본 Dagster resource."""


def _missing_resource(key: str) -> ResourceDefinition:
    @resource(description=f"{key} resource는 운영 definitions에서 실제 구현으로 교체한다.")
    def _resource() -> object:
        raise RuntimeError(
            f"Dagster resource {key!r}가 설정되지 않았음. "
            "krtour-map Dagster 배포 설정에서 실제 resource를 주입해야 함."
        )

    return _resource


def _value_resource(key: str, value: object) -> ResourceDefinition:
    @resource(description=f"{key} 기본 resource 값.")
    def _resource() -> object:
        return value

    return _resource


def _settings_value_resource(key: str, attr: str) -> ResourceDefinition:
    @resource(description=f"{key} resource 값을 ``KrtourMapSettings.{attr}``에서 읽는다.")
    def _resource() -> object:
        return getattr(KrtourMapSettings(), attr)

    return _resource


defs = Definitions(
    assets=[
        *FEATURE_LOAD_ASSETS,
        *KMA_WEATHER_ASSETS,
        *MCST_FEATURE_ASSETS,
        *CURATED_FEATURE_ASSETS,
    ],
    jobs=cast(
        "Any",
        [
            *FEATURE_LOAD_JOBS,
            *FEATURE_UPDATE_JOBS,
            *BATCH_DAG_JOBS,
            *MAINTENANCE_JOBS,
            *MOIS_SOURCE_SYNC_JOBS,
            *OFFLINE_UPLOAD_JOBS,
            *CURATED_FEATURE_JOBS,
        ],
    ),
    schedules=[
        *FEATURE_LOAD_SCHEDULES,
        *MAINTENANCE_SCHEDULES,
        *MOIS_SOURCE_SYNC_SCHEDULES,
        *CURATED_FEATURE_SCHEDULES,
    ],
    sensors=FEATURE_UPDATE_SENSORS,
    resources={
        key: (
            _value_resource(key, DEFAULT_RESOURCE_VALUES[key])
            if key in DEFAULT_RESOURCE_VALUES
            else _settings_value_resource(key, SETTINGS_VALUE_RESOURCES[key])
            if key in SETTINGS_VALUE_RESOURCES
            else DEFAULT_RESOURCE_DEFINITIONS[key]
            if key in DEFAULT_RESOURCE_DEFINITIONS
            else _missing_resource(key)
        )
        for key in REQUIRED_RESOURCE_KEYS
        + tuple(DEFAULT_RESOURCE_VALUES)
        + tuple(SETTINGS_VALUE_RESOURCES)
        + tuple(DEFAULT_RESOURCE_DEFINITIONS)
    },
)
"""``dagster dev -m krtour.map_dagster.definitions`` 진입점."""
