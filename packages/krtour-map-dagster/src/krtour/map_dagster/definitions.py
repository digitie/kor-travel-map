"""Dagster code location entrypoint."""

from __future__ import annotations

from typing import Final

from dagster import Definitions, ResourceDefinition, resource

from .assets import FEATURE_LOAD_ASSETS

REQUIRED_RESOURCE_KEYS: Final[tuple[str, ...]] = (
    "krtour_map_client",
    "reverse_geocoder",
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
)
"""Feature 적재 asset이 요구하는 Dagster resource key."""

DEFAULT_RESOURCE_VALUES: Final[dict[str, object]] = {
    "fetched_at": None,
    "strict_address": True,
    "mois_dataset_key": "mois_license_features_bulk",
    "knps_point_dataset_key": "knps_visitor_centers",
    "knps_geometry_dataset_key": "knps_trails",
}
"""운영 definitions가 교체하지 않아도 안전한 기본 resource 값."""


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


defs = Definitions(
    assets=FEATURE_LOAD_ASSETS,
    resources={
        key: (
            _value_resource(key, DEFAULT_RESOURCE_VALUES[key])
            if key in DEFAULT_RESOURCE_VALUES
            else _missing_resource(key)
        )
        for key in REQUIRED_RESOURCE_KEYS
    },
)
"""``dagster dev -m krtour.map_dagster.definitions`` 진입점."""
