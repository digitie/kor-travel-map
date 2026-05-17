from __future__ import annotations

from enum import StrEnum


class FeatureKind(StrEnum):
    PLACE = "place"
    EVENT = "event"
    NOTICE = "notice"
    PRICE = "price"
    WEATHER = "weather"
    ROUTE = "route"
    AREA = "area"


class FeatureStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    INACTIVE = "inactive"
    HIDDEN = "hidden"
    BROKEN = "broken"
    DELETED = "deleted"


class SourceRole(StrEnum):
    BASE_ADDRESS = "base_address"
    BASE_COORDINATE = "base_coordinate"
    PRIMARY = "primary"
    ENRICHMENT = "enrichment"
    CORRECTION = "correction"
    DUPLICATE_CANDIDATE = "duplicate_candidate"
    MEDIA = "media"
    WEATHER_CONTEXT = "weather_context"


class ForecastStyle(StrEnum):
    NOWCAST = "nowcast"
    ULTRA_SHORT = "ultra_short"
    SHORT = "short"
    MID = "mid"
    OBSERVED = "observed"
    INDEX = "index"
    ADVISORY = "advisory"


class TimelineBucket(StrEnum):
    ULTRA_SHORT = "ultra_short"
    SHORT = "short"
    MID = "mid"


class WeatherDomain(StrEnum):
    KMA_ULTRA_SHORT_NOWCAST = "kma_ultra_short_nowcast"
    KMA_ULTRA_SHORT_FORECAST = "kma_ultra_short_forecast"
    KMA_SHORT_FORECAST = "kma_short_forecast"
    KMA_MID_FORECAST = "kma_mid_forecast"
    REST_AREA_WEATHER = "rest_area_weather"
    AIRPORT_WEATHER = "airport_weather"
    TOURIST_SPOT_WEATHER = "tourist_spot_weather"
    AIR_QUALITY = "air_quality"
    BEACH_MARINE = "beach_marine"
    FOREST_MOUNTAIN_WEATHER = "forest_mountain_weather"
    FOREST_FIRE_RISK = "forest_fire_risk"
    FOREST_LANDSLIDE_RISK = "forest_landslide_risk"
    AGRI_WEATHER = "agri_weather"
    HYDRO_WEATHER = "hydro_weather"
