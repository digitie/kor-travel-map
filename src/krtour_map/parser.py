from __future__ import annotations

from typing import Any

from krtour_map.models import Feature, SourceRecord, WeatherValue


def parse_feature_response(raw: dict[str, Any]) -> Feature:
    return Feature.model_validate(raw)


def parse_source_record_response(raw: dict[str, Any]) -> SourceRecord:
    return SourceRecord.model_validate(raw)


def parse_weather_value_response(raw: dict[str, Any]) -> WeatherValue:
    return WeatherValue.model_validate(raw)
