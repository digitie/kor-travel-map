from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from krtour_map.db import (
    feature_weather_values,
    metadata,
    weather_value_from_row,
    weather_value_to_row,
)
from krtour_map.enums import ForecastStyle, TimelineBucket, WeatherDomain
from krtour_map.models import WeatherValue


def test_feature_db_schema_is_owned_by_krtour_map() -> None:
    assert "feature_weather_values" in metadata.tables
    assert "map_feature_weather_values" not in metadata.tables

    columns = feature_weather_values.c
    assert columns.timeline_bucket.name == "timeline_bucket"
    assert columns.valid_from.name == "valid_from"
    assert columns.valid_until.name == "valid_until"
    assert columns.source_metric_key.name == "source_metric_key"
    assert columns.normalization_version.name == "normalization_version"


def test_weather_value_db_row_round_trip() -> None:
    now = datetime(2026, 5, 17, 9, 0, tzinfo=ZoneInfo("Asia/Seoul"))
    value = WeatherValue(
        feature_id="f_1",
        provider="kma",
        weather_domain=WeatherDomain.KMA_SHORT_FORECAST,
        forecast_style=ForecastStyle.SHORT,
        timeline_bucket=TimelineBucket.SHORT,
        metric_key="TMP",
        source_metric_key="TMP",
        value_number=Decimal("22.5"),
        valid_at=now,
        collected_at=now,
        normalization_version="weather-feature-v1",
    )

    row = weather_value_to_row(value)
    restored = weather_value_from_row(row)

    assert row["weather_value_key"].startswith("wv_")
    assert row["provider"] == "python-kma-api"
    assert row["timeline_bucket"] == "short"
    assert restored.provider == "python-kma-api"
    assert restored.timeline_bucket == "short"
    assert restored.normalization_version == "weather-feature-v1"
