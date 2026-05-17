from __future__ import annotations

from datetime import datetime

from krtour_map.models import WeatherValue


def _sort_time(value: WeatherValue) -> datetime:
    return value.valid_at or value.observed_at or value.issued_at or value.collected_at


def latest_weather_values(values: list[WeatherValue]) -> list[WeatherValue]:
    latest: dict[tuple[str, str, str], WeatherValue] = {}
    for value in values:
        key = (str(value.weather_domain), str(value.forecast_style), value.metric_key)
        previous = latest.get(key)
        if previous is None or _sort_time(value) >= _sort_time(previous):
            latest[key] = value
    return sorted(
        latest.values(),
        key=lambda value: (str(value.weather_domain), str(value.forecast_style), value.metric_key),
    )
