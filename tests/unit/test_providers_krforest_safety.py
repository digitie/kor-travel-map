"""산림청 산악기상·산불위험·산사태 변환 테스트."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from kortravelmap.dto import FeatureKind, ForecastStyle, WeatherDomain
from kortravelmap.providers.krforest_safety import (
    LANDSLIDE_FORECAST_DATASET_KEY,
    MOUNTAIN_WEATHER_DATASET_KEY,
    landslide_active_lineage_keys,
    landslide_forecast_issues_to_bundles,
    mountain_weather_stations_to_bundles,
    mountain_weather_to_values,
    wildfire_risk_forecasts_to_bundles,
    wildfire_risk_region_key,
    wildfire_risk_to_values,
)

KST = timezone(timedelta(hours=9))


@dataclass(frozen=True)
class _MountainWeather:
    obs_id: str | None
    obs_name: str | None
    local_area: str | None
    observed_at: datetime | None
    temperature_10m: float | None = None
    temperature_2m: float | None = None
    humidity_10m: float | None = None
    humidity_2m: float | None = None
    pressure: float | None = None
    rainfall_tipping: float | None = None
    rainfall_weight: float | None = None
    ground_temperature: float | None = None
    wind_direction_10m: float | None = None
    wind_direction_10m_name: str | None = None
    wind_direction_2m: float | None = None
    wind_direction_2m_name: str | None = None
    wind_speed_10m: float | None = None
    wind_speed_2m: float | None = None
    latitude: float | None = None
    longitude: float | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class _WildfireRisk:
    scope: str
    analysis_at: datetime | None
    area: str | None
    region_code: str | None
    region_name: str | None
    upper_region_code: str | None = None
    d1: float | None = None
    d2: float | None = None
    d3: float | None = None
    d4: float | None = None
    maximum: float | None = None
    mean_average: float | None = None
    minimum: float | None = None
    standard_deviation: float | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class _LandslideIssue:
    issue_kind_code: str | None
    issue_kind_name: str | None
    issuing_institution: str | None
    status: str | None
    issued_at: datetime | None
    raw: dict[str, Any] = field(default_factory=dict)


def _now(hour: int = 12) -> datetime:
    return datetime(2026, 8, 20, hour, 0, tzinfo=KST)


@pytest.mark.unit
def test_mountain_weather_creates_anchors_and_observed_values() -> None:
    item = _MountainWeather(
        obs_id="M-001",
        obs_name="설악산",
        local_area="강원",
        observed_at=_now(),
        temperature_2m=21.5,
        humidity_2m=65,
        wind_speed_2m=2.4,
        wind_direction_2m=180,
        wind_direction_2m_name="남",
        latitude=38.12,
        longitude=128.47,
        raw={"obsid": "M-001", "tm2m": "21.5"},
    )

    bundles = mountain_weather_stations_to_bundles([item, item], fetched_at=_now())
    assert len(bundles) == 1
    bundle = bundles[0]
    assert bundle.feature.kind is FeatureKind.WEATHER
    assert bundle.source_record.dataset_key == MOUNTAIN_WEATHER_DATASET_KEY
    values = mountain_weather_to_values(
        [item],
        feature_id_by_obs_id={"M-001": bundle.feature.feature_id},
        source_record_key="sr_weather_response",
    )

    assert {value.metric_key for value in values} == {"TMP", "REH", "WSD", "VEC", "VEC_NAME"}
    assert all(value.weather_domain is WeatherDomain.FOREST_MOUNTAIN_WEATHER for value in values)
    assert all(value.forecast_style is ForecastStyle.OBSERVED for value in values)
    assert all(value.source_record_key == "sr_weather_response" for value in values)


@pytest.mark.unit
def test_wildfire_risk_keeps_region_identity_and_forecast_metrics() -> None:
    item = _WildfireRisk(
        scope="sigungu",
        analysis_at=_now(9),
        area="강원도",
        region_code="51820",
        region_name="속초시",
        upper_region_code="51",
        d1=2.0,
        d2=3.0,
        d4=4.0,
        maximum=4.0,
        mean_average=2.5,
        minimum=1.0,
        raw={"regioncode": "51820", "meanavg": "2.5"},
    )
    other = _WildfireRisk(
        scope="sigungu",
        analysis_at=_now(9),
        area="강원도",
        region_code="51830",
        region_name="고성군",
        upper_region_code="51",
        mean_average=1.2,
    )

    bundles = wildfire_risk_forecasts_to_bundles([item, other], fetched_at=_now())
    assert len(bundles) == 2
    ids = {
        wildfire_risk_region_key(item): bundles[0].feature.feature_id,
        wildfire_risk_region_key(other): bundles[1].feature.feature_id,
    }
    values = wildfire_risk_to_values(
        [item, other], feature_id_by_region_key=ids, source_record_key="sr_fire"
    )
    assert len(values) == 5
    assert {value.metric_key for value in values} == {
        "FIRE_RISK",
        "FIRE_RISK_D1",
        "FIRE_RISK_D2",
        "FIRE_RISK_D4",
    }
    assert all(value.weather_domain is WeatherDomain.FOREST_FIRE_RISK for value in values)


@pytest.mark.unit
def test_landslide_release_is_same_lineage_but_not_active() -> None:
    active = _LandslideIssue(
        issue_kind_code="1",
        issue_kind_name="산사태주의보",
        issuing_institution="강원특별자치도",
        status="발령",
        issued_at=_now(8),
    )
    released = _LandslideIssue(
        issue_kind_code="1",
        issue_kind_name="산사태주의보",
        issuing_institution="강원특별자치도",
        status="해제",
        issued_at=_now(10),
    )
    bundles = landslide_forecast_issues_to_bundles(
        [active, released], fetched_at=_now()
    )
    assert len(bundles) == 1
    assert bundles[0].source_record.dataset_key == LANDSLIDE_FORECAST_DATASET_KEY
    assert bundles[0].feature.detail is not None
    assert bundles[0].feature.detail.valid_end_time == _now(10)  # type: ignore[union-attr]
    assert not landslide_active_lineage_keys([released])
