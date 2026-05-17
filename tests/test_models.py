from __future__ import annotations

from decimal import Decimal

import pytest
from kraddr.base import AddressRegion
from pydantic import ValidationError

from krtour_map import PlaceCategoryCode
from krtour_map.enums import FeatureKind, ForecastStyle, TimelineBucket, WeatherDomain
from krtour_map.models import Address, Coordinate, Feature, SourceRecord, WeatherValue


def test_feature_rejects_coordinate_outside_korean_bounds() -> None:
    with pytest.raises(ValidationError):
        Feature(
            feature_id="feature-1",
            kind=FeatureKind.PLACE,
            name="Outside Korea",
            coord=Coordinate(longitude=-122.0, latitude=37.0),
            category="unknown",
            marker_icon="marker",
            marker_color="#2f6fed",
        )


def test_address_uses_kraddr_base_legal_dong_validation() -> None:
    with pytest.raises(ValidationError):
        Address(region={"legal_dong_code": "11110"})


def test_feature_uses_kraddr_base_category_helpers() -> None:
    feature = Feature(
        feature_id="feature-1",
        kind=FeatureKind.PLACE,
        name="Beach",
        coord=Coordinate(longitude=127.0, latitude=37.0),
        address=Address(region=AddressRegion.from_legal_dong_code("1111010100")),
        category=PlaceCategoryCode.TOURISM_NATURE_BEACH,
        marker_icon="marker",
        marker_color="#2f6fed",
    )

    assert feature.category == PlaceCategoryCode.TOURISM_NATURE_BEACH.value
    assert feature.category_info is not None
    assert feature.category_path
    assert feature.category_label != feature.category
    assert feature.mapbox_maki_icon == "beach"


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
        timeline_bucket=TimelineBucket.SHORT,
        metric_key="temp_c",
        source_metric_key="TMP",
        source_metric_name="temperature",
        normalization_version="weather-feature-v1",
        value_number=Decimal("21.5"),
        unit="deg_c",
    )

    assert value.provider == "python-kma-api"
    assert value.timeline_bucket == "short"
    assert value.source_metric_key == "TMP"
    assert value.value_number == Decimal("21.5")
