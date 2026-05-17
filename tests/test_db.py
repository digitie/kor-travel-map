from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from krtour_map.db import (
    data_integrity_violations,
    dedup_review_queue,
    feature_db_settings_from_object,
    feature_overrides,
    feature_weather_values,
    features,
    initialize_feature_db,
    make_dedup_review_key,
    metadata,
    price_point_from_row,
    price_point_to_row,
    price_points,
    price_value_from_row,
    price_value_to_row,
    price_values,
    provider_sync_state,
    provider_sync_state_from_row,
    provider_sync_state_to_row,
    weather_value_from_row,
    weather_value_to_row,
)
from krtour_map.enums import ForecastStyle, TimelineBucket, WeatherDomain
from krtour_map.models import PricePoint, PriceValue, ProviderSyncState, WeatherValue


def test_feature_db_schema_is_owned_by_krtour_map() -> None:
    assert "features" in metadata.tables
    assert "source_links" in metadata.tables
    assert "feature_weather_values" in metadata.tables
    assert "price_points" in metadata.tables
    assert "price_values" in metadata.tables
    assert "provider_sync_state" in metadata.tables
    assert "feature_overrides" in metadata.tables
    assert "dedup_review_queue" in metadata.tables
    assert "data_integrity_violations" in metadata.tables

    assert "map_features" not in metadata.tables
    assert "map_feature_source_links" not in metadata.tables
    assert "map_feature_weather_values" not in metadata.tables

    feature_columns = features.c
    assert feature_columns.legal_dong_code.name == "legal_dong_code"
    assert feature_columns.geom.name == "geom"
    assert feature_columns.urls.name == "urls"
    assert feature_columns.parent_feature_id.name == "parent_feature_id"
    assert feature_columns.sibling_group_id.name == "sibling_group_id"
    assert feature_columns.raw_refs.name == "raw_refs"
    assert feature_columns.deleted_at.name == "deleted_at"

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


def test_price_point_and_value_db_row_round_trip() -> None:
    observed_at = datetime(2026, 5, 17, 12, 0, tzinfo=ZoneInfo("Asia/Seoul"))
    point = PricePoint(
        feature_id="f_station_1",
        price_category="fuel",
        retention_days=3650,
    )
    value = PriceValue(
        feature_id="f_station_1",
        item_key="gasoline",
        observed_at=observed_at,
        value=Decimal("1699"),
        payload_hash="hash",
    )

    point_row = price_point_to_row(point)
    value_row = price_value_to_row(value)

    assert price_points.name == "price_points"
    assert price_values.name == "price_values"
    assert point_row["retention_days"] == 3650
    assert value_row["currency"] == "KRW"
    assert price_point_from_row(point_row) == point
    assert price_value_from_row(value_row) == value


def test_provider_sync_state_db_row_round_trip() -> None:
    updated_at = datetime(2026, 5, 17, 13, 0, tzinfo=ZoneInfo("Asia/Seoul"))
    state = ProviderSyncState(
        provider="kma",
        dataset_key="short_forecast",
        sync_scope="weather:short",
        status="active",
        cursor={"base_date": "20260517", "base_time": "1100"},
        next_run_after=updated_at,
        extra={"rate_limit": "public-data-portal"},
        updated_at=updated_at,
    )

    row = provider_sync_state_to_row(state)
    restored = provider_sync_state_from_row(row)

    assert provider_sync_state.name == "provider_sync_state"
    assert row["provider"] == "python-kma-api"
    assert restored.provider == "python-kma-api"
    assert restored.cursor == {"base_date": "20260517", "base_time": "1100"}
    assert restored.extra == {"rate_limit": "public-data-portal"}


def test_review_and_governance_tables_use_canonical_names() -> None:
    assert feature_overrides.name == "feature_overrides"
    assert dedup_review_queue.name == "dedup_review_queue"
    assert data_integrity_violations.name == "data_integrity_violations"
    assert make_dedup_review_key("f_b", "f_a") == make_dedup_review_key("f_a", "f_b")


def test_feature_db_initializes_from_host_settings_object() -> None:
    class Settings:
        database_url = "sqlite+pysqlite:///:memory:"

    settings = feature_db_settings_from_object(Settings())
    context = initialize_feature_db(settings)
    try:
        assert settings.database_url == "sqlite+pysqlite:///:memory:"
        assert "feature_weather_values" in metadata.tables
        assert context.session_factory.kw["autoflush"] is False
        assert context.engine.dialect.name == "sqlite"
    finally:
        context.dispose()
