from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from krtour_map.enums import ForecastStyle, WeatherDomain
from krtour_map.models import Address, Coordinate, SourceRecord, WeatherValue


def test_coordinate_rejects_non_korean_bounds() -> None:
    with pytest.raises(ValidationError):
        Coordinate(longitude=-122.0, latitude=37.0)


def test_address_requires_ten_digit_bjd_code() -> None:
    with pytest.raises(ValidationError):
        Address(bjd_code="11110")


def test_source_record_uses_canonical_provider_name() -> None:
    source = SourceRecord(
        provider="pykrex",
        dataset_key="rest_area_weather",
        source_entity_type="weather",
        source_entity_id="RA-1",
        raw_payload_hash="hash",
    )

    assert source.provider == "python-krex-api"
    assert source.key().startswith("sr_")


def test_unknown_provider_is_rejected() -> None:
    with pytest.raises(ValidationError):
        SourceRecord(
            provider="random-provider",
            dataset_key="x",
            source_entity_type="place",
            source_entity_id="1",
            raw_payload_hash="hash",
        )


def test_weather_value_accepts_numeric_or_text_metric() -> None:
    value = WeatherValue(
        feature_id="f_1",
        provider="kma",
        weather_domain=WeatherDomain.KMA_SHORT_FORECAST,
        forecast_style=ForecastStyle.SHORT,
        metric_key="temp_c",
        value_number=Decimal("21.5"),
        unit="deg_c",
    )

    assert value.provider == "python-kma-api"
    assert value.value_number == Decimal("21.5")
