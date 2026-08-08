"""DB operation key를 Dagster handler에 결박하는 좁은 registry.

T-VN-33에서 dataset identity와 operation enable은 PostgreSQL이 소유한다. 이 모듈은
``operation_key``(현재 Dagster job name)에서 실행 handler로 가는 코드 binding만
보유한다. provider, dataset, capability, scope 또는 pair 목록을 만들거나 유추하지
않는다.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final

__all__ = [
    "FEATURE_OPERATION_HANDLERS",
    "FeatureOperationHandlerBinding",
    "UnknownFeatureOperationHandlerError",
    "feature_operation_handler_keys",
    "resolve_feature_operation_handler",
]


@dataclass(frozen=True, slots=True)
class FeatureOperationHandlerBinding:
    """operation key에 대응하는 Dagster job/asset handler binding.

    ``operation_key``는 DB의 ``provider_dataset_operations.operation_key``와 exact
    일치해야 한다. binding은 dataset을 인자로 받지 않으며, 실행 대상 dataset은
    database catalog operation binding에서 caller가 전달한다.
    """

    operation_key: str
    job_name: str
    asset_keys: tuple[str, ...]


class UnknownFeatureOperationHandlerError(LookupError):
    """DB operation key에 대응하는 code handler가 없다."""

    def __init__(self, operation_key: str) -> None:
        super().__init__(f"unknown provider dataset operation handler: {operation_key!r}")
        self.operation_key = operation_key


def _handler(job_name: str, asset_key: str) -> FeatureOperationHandlerBinding:
    return FeatureOperationHandlerBinding(
        operation_key=job_name,
        job_name=job_name,
        asset_keys=(asset_key,),
    )


_HANDLER_BINDINGS: Final[tuple[FeatureOperationHandlerBinding, ...]] = (
    _handler(
        "feature_event_datagokr_cultural_festivals_job",
        "feature_event_datagokr_cultural_festivals",
    ),
    _handler("feature_place_opinet_stations_job", "feature_place_opinet_stations"),
    _handler("feature_price_opinet_stations_job", "feature_price_opinet_stations"),
    _handler("feature_place_krex_rest_areas_job", "feature_place_krex_rest_areas"),
    _handler("feature_price_krex_rest_areas_job", "feature_price_krex_rest_areas"),
    _handler(
        "feature_notice_krex_traffic_notices_job",
        "feature_notice_krex_traffic_notices",
    ),
    _handler("feature_weather_krex_rest_areas_job", "feature_weather_krex_rest_areas"),
    _handler("feature_place_krheritage_items_job", "feature_place_krheritage_items"),
    _handler("feature_event_krheritage_events_job", "feature_event_krheritage_events"),
    _handler("feature_place_mois_licenses_job", "feature_place_mois_licenses"),
    _handler(
        "feature_place_krforest_recreation_forests_job",
        "feature_place_krforest_recreation_forests",
    ),
    _handler(
        "feature_place_krforest_arboretums_job",
        "feature_place_krforest_arboretums",
    ),
    _handler("feature_place_standard_museums_job", "feature_place_standard_museums"),
    _handler(
        "feature_place_standard_tourist_attractions_job",
        "feature_place_standard_tourist_attractions",
    ),
    _handler(
        "feature_place_standard_parking_lots_job",
        "feature_place_standard_parking_lots",
    ),
    _handler(
        "feature_place_standard_special_streets_job",
        "feature_place_standard_special_streets",
    ),
    _handler("feature_place_khoa_beaches_job", "feature_place_khoa_beaches"),
    _handler("feature_place_krairport_airports_job", "feature_place_krairport_airports"),
    _handler(
        "feature_place_kor_travel_concierge_youtube_job",
        "feature_place_kor_travel_concierge_youtube",
    ),
    _handler(
        "feature_event_visitkorea_enrichment_job",
        "feature_event_visitkorea_enrichment",
    ),
    _handler(
        "feature_weather_airkorea_air_quality_job",
        "feature_weather_airkorea_air_quality",
    ),
    _handler(
        "feature_weather_kma_ultra_short_nowcast_job",
        "feature_weather_kma_ultra_short_nowcast",
    ),
    _handler(
        "feature_weather_kma_ultra_short_forecast_job",
        "feature_weather_kma_ultra_short_forecast",
    ),
    _handler("feature_weather_kma_short_forecast_job", "feature_weather_kma_short_forecast"),
    _handler("feature_weather_kma_mid_forecast_job", "feature_weather_kma_mid_forecast"),
    _handler(
        "feature_notice_kma_weather_alerts_job",
        "feature_notice_kma_weather_alerts",
    ),
    _handler(
        "feature_place_datagokr_seoul_bookstores_job",
        "feature_place_datagokr_file_data",
    ),
    _handler(
        "feature_place_datagokr_gyeonggi_muslim_friendly_restaurants_job",
        "feature_place_datagokr_file_data",
    ),
    _handler(
        "feature_place_datagokr_ansan_world_restaurants_job",
        "feature_place_datagokr_file_data",
    ),
    _handler(
        "feature_place_datagokr_jeju_local_restaurants_job",
        "feature_place_datagokr_file_data",
    ),
    _handler("feature_place_knps_points_job", "feature_place_knps_points"),
    _handler("feature_geometry_knps_records_job", "feature_geometry_knps_records"),
    _handler("feature_place_mcst_culture_job", "feature_place_mcst_culture"),
)

FEATURE_OPERATION_HANDLERS: Final[Mapping[str, FeatureOperationHandlerBinding]] = MappingProxyType(
    {binding.operation_key: binding for binding in _HANDLER_BINDINGS}
)
"""DB operation key → code handler binding. provider/dataset pair는 포함하지 않는다."""

if len(FEATURE_OPERATION_HANDLERS) != len(_HANDLER_BINDINGS):
    raise RuntimeError("feature operation handler operation_key가 중복됨")


def feature_operation_handler_keys() -> frozenset[str]:
    """exact-set 검증에 쓸 immutable handler operation key 집합."""
    return frozenset(FEATURE_OPERATION_HANDLERS)


def resolve_feature_operation_handler(
    operation_key: str,
) -> FeatureOperationHandlerBinding:
    """DB에서 받은 operation key의 handler binding을 strict하게 찾는다."""
    try:
        return FEATURE_OPERATION_HANDLERS[operation_key]
    except KeyError as exc:
        raise UnknownFeatureOperationHandlerError(operation_key) from exc
