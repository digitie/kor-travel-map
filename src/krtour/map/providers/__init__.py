"""``krtour.map.providers`` — provider별 raw → DTO 변환 모듈.

각 provider 라이브러리(``python-*-api``)의 typed model을 본 라이브러리의
``FeatureBundle``로 정규화하는 **순수 함수 namespace**. wrapper/adapter/
gateway 신규 생성 금지 (ADR-006).

**Sprint 2~5에서 provider별 모듈 점진 추가** — ADR-034 9단계 순서:

| Sprint | provider 모듈 |
|--------|--------------|
| 2 | ``visitkorea`` / ``kma`` / ``airkorea`` / ``krforest_weather`` |
|   | / ``khoa_weather`` / ``opinet`` / ``krex`` |
| 3 | ``knps`` (14 dataset) / ``krforest_trails`` / ``krheritage`` |
| 4 | ``mois`` (4단계 lifecycle) |
| 5 | ``krforest`` (휴양림/수목원) / ``standard_data`` (5종) |

ADR 참조
--------
- ADR-006 — provider wrapper/adapter 금지 (public client 직접 사용)
- ADR-024 — canonical provider name (``python-mois-api``, ``python-knps-api``,
  등)
- ADR-034 — 구현 9단계 순서
"""

from __future__ import annotations

from krtour.map.providers.kma import (
    KMA_ALERT_LEVEL_SEVERITY,
    KMA_METRIC_NAMES,
    KMA_METRIC_UNITS,
    KMA_MID_FORECAST_DATASET_KEY,
    KMA_PROVIDER_NAME,
    KMA_WEATHER_ALERT_CATEGORY,
    KMA_WEATHER_ALERT_DATASET_KEY,
    KMA_WEATHER_ALERT_MARKER_COLOR,
    KMA_WEATHER_ALERT_MARKER_ICON,
    KmaMidLandForecastItem,
    KmaMidTemperatureItem,
    KmaShortForecastItem,
    KmaUltraShortForecastItem,
    KmaUltraShortNowcastItem,
    KmaWeatherAlertItem,
    KmaWeatherAlertRegion,
    mid_land_forecast_to_weather_values,
    mid_temperature_to_weather_values,
    short_forecast_to_weather_values,
    ultra_short_forecast_to_weather_values,
    ultra_short_nowcast_to_weather_values,
    weather_alerts_to_notice_bundles,
)
from krtour.map.providers.knps import (
    KNPS_GEOMETRY_DATASETS,
    KNPS_PLACE_DATASETS,
    KnpsGeometryRecord,
    KnpsPointRecord,
    knps_geometry_records_to_bundles,
    knps_point_records_to_bundles,
    resolve_cultural_resource_category,
)
from krtour.map.providers.knps import (
    PROVIDER_NAME as KNPS_PROVIDER_NAME,
)
from krtour.map.providers.krex import (
    KREX_PROVIDER_NAME,
    REST_AREA_CATEGORY,
    REST_AREA_DATASET_KEY,
    REST_AREA_MARKER_COLOR,
    REST_AREA_MARKER_ICON,
    REST_AREA_PRICES_DATASET_KEY,
    REST_AREA_WEATHER_DATASET_KEY,
    TRAFFIC_NOTICE_CATEGORY,
    TRAFFIC_NOTICE_MARKER_COLOR,
    TRAFFIC_NOTICE_MARKER_ICON,
    TRAFFIC_NOTICES_DATASET_KEY,
    KrexRestAreaItem,
    KrexRestAreaPriceItem,
    KrexRestAreaWeatherItem,
    KrexTrafficNoticeItem,
    rest_area_prices_to_values,
    rest_area_weather_to_values,
    rest_areas_to_bundles,
    traffic_notices_to_bundles,
)
from krtour.map.providers.krforest import (
    ARBORETUM_CATEGORY,
    DATASET_KEY_ARBORETUMS,
    DATASET_KEY_RECREATION_FORESTS,
    KRFOREST_MARKER_COLOR,
    RECREATION_FOREST_CATEGORY,
    ForestSpatialItem,
    RecreationForestItem,
    arboretums_to_bundles,
    recreation_forests_to_bundles,
)
from krtour.map.providers.krheritage import (
    DATASET_KEY_EVENT as KRHERITAGE_DATASET_KEY_EVENT,
)
from krtour.map.providers.krheritage import (
    DATASET_KEY_HERITAGE as KRHERITAGE_DATASET_KEY_HERITAGE,
)
from krtour.map.providers.krheritage import (
    HERITAGE_MARKER_COLOR,
    KrHeritageEvent,
    KrHeritageItem,
    classify_heritage_kind,
    heritage_events_to_bundles,
    heritage_items_to_bundles,
    resolve_heritage_category,
)
from krtour.map.providers.krheritage import (
    PROVIDER_NAME as KRHERITAGE_PROVIDER_NAME,
)
from krtour.map.providers.mois import (
    DATASET_KEY_BULK as MOIS_DATASET_KEY_BULK,
)
from krtour.map.providers.mois import (
    DATASET_KEY_CLOSED as MOIS_DATASET_KEY_CLOSED,
)
from krtour.map.providers.mois import (
    DATASET_KEY_DETAIL as MOIS_DATASET_KEY_DETAIL,
)
from krtour.map.providers.mois import (
    DATASET_KEY_HISTORY as MOIS_DATASET_KEY_HISTORY,
)
from krtour.map.providers.mois import (
    EXCLUDED_SERVICE_SLUGS,
    MOIS_MARKER_COLOR,
    PROMOTED_CATEGORY_BY_SLUG,
    PROMOTED_PLACE_KIND_BY_SLUG,
    PROMOTED_SERVICE_SLUGS,
    MoisLicensePlaceRecord,
    license_record_to_bundle,
    license_records_to_bundles,
    resolve_license_category,
    resolve_license_place_kind,
)
from krtour.map.providers.mois import (
    PROVIDER_NAME as MOIS_PROVIDER_NAME,
)
from krtour.map.providers.opinet import (
    OPINET_PRODUCT_KEY_MAP,
    OPINET_PRODUCT_NAME_KO,
    OPINET_PROVIDER_NAME,
    OPINET_STATION_CATEGORY,
    OPINET_STATION_DATASET_KEY,
    OPINET_STATION_MARKER_COLOR,
    OPINET_STATION_MARKER_ICON,
    OpinetPriceItem,
    OpinetStationItem,
    prices_to_values,
    stations_to_bundles,
)
from krtour.map.providers.standard_data import (
    DATASET_KEY_CULTURAL_FESTIVALS,
    FESTIVAL_CATEGORY,
    FESTIVAL_MARKER_COLOR,
    FESTIVAL_MARKER_ICON,
    CulturalFestivalItem,
    cultural_festivals_to_bundles,
)
from krtour.map.providers.visitkorea import (
    DATASET_KEY_FESTIVAL_EVENTS,
    VISITKOREA_PROVIDER_NAME,
    FestivalEnrichment,
    FestivalMatch,
    FestivalMatcher,
    VisitKoreaFestivalItem,
    festival_to_enrichment_links,
)

__all__ = [
    # standard_data (PR#34, ADR-042 — datagokr 표준데이터)
    "CulturalFestivalItem",
    "cultural_festivals_to_bundles",
    "DATASET_KEY_CULTURAL_FESTIVALS",
    "FESTIVAL_CATEGORY",
    "FESTIVAL_MARKER_ICON",
    "FESTIVAL_MARKER_COLOR",
    # visitkorea (PR#51, ADR-042 — TourAPI enrichment 2차)
    "VisitKoreaFestivalItem",
    "FestivalMatch",
    "FestivalMatcher",
    "FestivalEnrichment",
    "festival_to_enrichment_links",
    "VISITKOREA_PROVIDER_NAME",
    "DATASET_KEY_FESTIVAL_EVENTS",
    # krforest (T-RV-53, ADR-034 8단계 — 휴양림/수목원, MOIS-sibling)
    "RecreationForestItem",
    "ForestSpatialItem",
    "recreation_forests_to_bundles",
    "arboretums_to_bundles",
    "DATASET_KEY_RECREATION_FORESTS",
    "DATASET_KEY_ARBORETUMS",
    "RECREATION_FOREST_CATEGORY",
    "ARBORETUM_CATEGORY",
    "KRFOREST_MARKER_COLOR",
    # kma (PR#38 short, PR#39 nowcast, PR#41 ultra_short, PR#46 alerts —
    # ADR-010)
    "KmaShortForecastItem",
    "KmaUltraShortNowcastItem",
    "KmaUltraShortForecastItem",
    "KmaWeatherAlertItem",
    "KmaWeatherAlertRegion",
    "KmaMidLandForecastItem",
    "KmaMidTemperatureItem",
    "short_forecast_to_weather_values",
    "ultra_short_nowcast_to_weather_values",
    "ultra_short_forecast_to_weather_values",
    "weather_alerts_to_notice_bundles",
    "mid_land_forecast_to_weather_values",
    "mid_temperature_to_weather_values",
    "KMA_PROVIDER_NAME",
    "KMA_METRIC_UNITS",
    "KMA_METRIC_NAMES",
    "KMA_MID_FORECAST_DATASET_KEY",
    "KMA_WEATHER_ALERT_DATASET_KEY",
    "KMA_WEATHER_ALERT_CATEGORY",
    "KMA_WEATHER_ALERT_MARKER_ICON",
    "KMA_WEATHER_ALERT_MARKER_COLOR",
    "KMA_ALERT_LEVEL_SEVERITY",
    # opinet (PR#42 prices, PR#43 stations)
    "OpinetPriceItem",
    "OpinetStationItem",
    "prices_to_values",
    "stations_to_bundles",
    "OPINET_PROVIDER_NAME",
    "OPINET_PRODUCT_KEY_MAP",
    "OPINET_PRODUCT_NAME_KO",
    "OPINET_STATION_DATASET_KEY",
    "OPINET_STATION_CATEGORY",
    "OPINET_STATION_MARKER_ICON",
    "OPINET_STATION_MARKER_COLOR",
    # krex (PR#45 4 dataset — Sprint 2 §2.4 multi-kind)
    "KrexRestAreaItem",
    "KrexRestAreaPriceItem",
    "KrexRestAreaWeatherItem",
    "KrexTrafficNoticeItem",
    "rest_areas_to_bundles",
    "rest_area_prices_to_values",
    "rest_area_weather_to_values",
    "traffic_notices_to_bundles",
    "KREX_PROVIDER_NAME",
    "REST_AREA_DATASET_KEY",
    "REST_AREA_PRICES_DATASET_KEY",
    "REST_AREA_WEATHER_DATASET_KEY",
    "TRAFFIC_NOTICES_DATASET_KEY",
    "REST_AREA_CATEGORY",
    "TRAFFIC_NOTICE_CATEGORY",
    "REST_AREA_MARKER_ICON",
    "REST_AREA_MARKER_COLOR",
    "TRAFFIC_NOTICE_MARKER_ICON",
    "TRAFFIC_NOTICE_MARKER_COLOR",
    # mois (Sprint 4a — MOIS 인허가 LOCALDATA, ADR-024/034 ⑦)
    "MoisLicensePlaceRecord",
    "license_record_to_bundle",
    "license_records_to_bundles",
    "resolve_license_category",
    "resolve_license_place_kind",
    "PROMOTED_SERVICE_SLUGS",
    "EXCLUDED_SERVICE_SLUGS",
    "PROMOTED_CATEGORY_BY_SLUG",
    "PROMOTED_PLACE_KIND_BY_SLUG",
    "MOIS_PROVIDER_NAME",
    "MOIS_DATASET_KEY_BULK",
    "MOIS_DATASET_KEY_HISTORY",
    "MOIS_DATASET_KEY_CLOSED",
    "MOIS_DATASET_KEY_DETAIL",
    "MOIS_MARKER_COLOR",
    # knps (Sprint 3 — 국립공원공단, ADR-028/034 ⑤)
    "KnpsPointRecord",
    "KnpsGeometryRecord",
    "knps_point_records_to_bundles",
    "knps_geometry_records_to_bundles",
    "resolve_cultural_resource_category",
    "KNPS_PLACE_DATASETS",
    "KNPS_GEOMETRY_DATASETS",
    "KNPS_PROVIDER_NAME",
    # krheritage (Sprint 3 — 국가유산청, ADR-024/034 ⑥)
    "KrHeritageItem",
    "KrHeritageEvent",
    "heritage_items_to_bundles",
    "heritage_events_to_bundles",
    "classify_heritage_kind",
    "resolve_heritage_category",
    "KRHERITAGE_PROVIDER_NAME",
    "KRHERITAGE_DATASET_KEY_HERITAGE",
    "KRHERITAGE_DATASET_KEY_EVENT",
    "HERITAGE_MARKER_COLOR",
]
