"""``krtour.map.dto._enums`` — Feature/Source/Weather enum 정의.

ADR 참조
--------
- ADR-010 — ``forecast_style`` vs ``timeline_bucket`` 두 축 분리
- ADR-018 — ``Feature.detail`` 자유 dict 금지 (``FeatureKind`` 분기 강제)
"""

from __future__ import annotations

from enum import StrEnum

__all__ = [
    "FeatureKind",
    "FeatureStatus",
    "SourceRole",
    "WeatherDomain",
    "ForecastStyle",
    "TimelineBucket",
]


class FeatureKind(StrEnum):
    """Feature 종류 7종 (``docs/feature-model.md §1``)."""

    PLACE = "place"
    EVENT = "event"
    NOTICE = "notice"
    PRICE = "price"
    WEATHER = "weather"
    ROUTE = "route"
    AREA = "area"


class FeatureStatus(StrEnum):
    """Feature 상태 (``docs/feature-model.md §2``)."""

    DRAFT = "draft"
    ACTIVE = "active"
    INACTIVE = "inactive"
    HIDDEN = "hidden"
    BROKEN = "broken"
    DELETED = "deleted"


class SourceRole(StrEnum):
    """SourceRecord/SourceLink role (``docs/feature-model.md §3``)."""

    PRIMARY = "primary"
    BASE_ADDRESS = "base_address"
    BASE_COORDINATE = "base_coordinate"
    ENRICHMENT = "enrichment"
    CORRECTION = "correction"
    DUPLICATE_CANDIDATE = "duplicate_candidate"
    MEDIA = "media"
    WEATHER_CONTEXT = "weather_context"


class WeatherDomain(StrEnum):
    """``WeatherValue.weather_domain`` — provider별 dataset 식별자.

    ``docs/weather-feature-normalization.md §3`` provider별 1차 매핑 표 참조.
    표에 없는 신규 dataset은 새 enum 값 + ADR + 본 문서 갱신.
    """

    # KMA (`python-kma-api`)
    KMA_ULTRA_SHORT_NOWCAST = "kma_ultra_short_nowcast"
    KMA_ULTRA_SHORT_FORECAST = "kma_ultra_short_forecast"
    KMA_SHORT_FORECAST = "kma_short_forecast"
    KMA_MID_FORECAST = "kma_mid_forecast"
    KMA_WEATHER_ALERT = "kma_weather_alert"

    # 산림청 (`python-krforest-api`)
    FOREST_MOUNTAIN_WEATHER = "forest_mountain_weather"
    FOREST_FIRE_RISK = "forest_fire_risk"
    FOREST_LANDSLIDE_RISK = "forest_landslide_risk"

    # 휴게소 (`python-krex-api`)
    REST_AREA_WEATHER = "rest_area_weather"

    # 공항 (`python-krairport-api`)
    AIRPORT_WEATHER = "airport_weather"

    # 해양 (`python-khoa-api`)
    BEACH_MARINE = "beach_marine"
    COASTAL_OBSERVATION = "coastal_observation"

    # 대기질 (`python-airkorea-api`)
    AIR_QUALITY = "air_quality"

    # 농촌진흥청 / 한국수자원공사 (data.go.kr) — 후속
    AGRI_WEATHER = "agri_weather"
    HYDRO_WEATHER = "hydro_weather"


class ForecastStyle(StrEnum):
    """``WeatherValue.forecast_style`` — 원천값 성격 (ADR-010).

    `nowcast`/`ultra_short`/`short`/`mid` (예보), `observed` (관측), `index`
    (지수성), `advisory` (특보/경보). 관측 ↔ 예보 가공 금지 — provider 원천
    성격 보존.
    """

    NOWCAST = "nowcast"
    ULTRA_SHORT = "ultra_short"
    SHORT = "short"
    MID = "mid"
    OBSERVED = "observed"
    INDEX = "index"
    ADVISORY = "advisory"


class TimelineBucket(StrEnum):
    """``WeatherValue.timeline_bucket`` — KMA식 조회 시간축 (ADR-010).

    `null` 허용 (지수/특보 등 시간축 모호한 경우). unique key에 포함되지
    **않는다** — 분류 결과이므로 재계산 가능.
    """

    ULTRA_SHORT = "ultra_short"
    SHORT = "short"
    MID = "mid"
