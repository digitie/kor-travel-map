from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from krtour_map.db import (
    data_integrity_violations,
    dedup_review_queue,
    event_detail_from_row,
    event_detail_to_row,
    feature_db_settings_from_object,
    feature_event_details,
    feature_from_row,
    feature_opening_periods,
    feature_overrides,
    feature_special_days,
    feature_to_row,
    feature_weather_values,
    features,
    initialize_feature_db,
    make_dedup_review_key,
    metadata,
    opening_period_from_row,
    opening_period_to_row,
    price_point_from_row,
    price_point_to_row,
    price_points,
    price_value_from_row,
    price_value_to_row,
    price_values,
    provider_sync_state,
    provider_sync_state_from_row,
    provider_sync_state_to_row,
    special_opening_day_from_row,
    special_opening_day_to_row,
    weather_value_from_row,
    weather_value_to_row,
)
from krtour_map.enums import ForecastStyle, TimelineBucket, WeatherDomain
from krtour_map.models import (
    EventDetail,
    FeatureOpeningHours,
    OpeningPeriod,
    OpeningTime,
    PricePoint,
    PriceValue,
    ProviderSyncState,
    SpecialOpeningDay,
    WeatherValue,
)


def test_feature_db_schema_is_owned_by_krtour_map() -> None:
    assert "features" in metadata.tables
    assert "source_links" in metadata.tables
    assert "feature_weather_values" in metadata.tables
    assert "price_points" in metadata.tables
    assert "price_values" in metadata.tables
    assert "provider_sync_state" in metadata.tables
    assert "feature_event_details" in metadata.tables
    assert "feature_opening_periods" in metadata.tables
    assert "feature_special_days" in metadata.tables
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

    assert feature_event_details.c.starts_on.name == "starts_on"
    assert feature_opening_periods.c.duration_minutes.name == "duration_minutes"
    assert feature_special_days.c.special_date.name == "special_date"


def test_feature_db_row_round_trip_allows_missing_coordinate(sample_feature) -> None:
    feature = sample_feature.model_copy(update={"coord": None})
    row = feature_to_row(feature)
    restored = feature_from_row(row)

    assert row["longitude"] is None
    assert row["latitude"] is None
    assert restored.coord is None
    assert restored.feature_id == feature.feature_id


def test_event_detail_and_opening_hours_db_rows_round_trip() -> None:
    period = OpeningPeriod(
        open=OpeningTime(day=5, time="2000"),
        close=OpeningTime(day=6, time="0200"),
    )
    detail = EventDetail(
        feature_id="f_event_1",
        event_kind="festival",
        starts_on=date(2026, 5, 1),
        ends_on=date(2026, 5, 5),
        content_id="123",
        content_type_id="15",
        opening_hours=FeatureOpeningHours(periods=[period]),
        payload={"event_start_date": "20260501"},
    )
    special_day = SpecialOpeningDay(date=date(2026, 5, 5), is_closed=True)

    detail_row = event_detail_to_row(detail)
    period_row = opening_period_to_row("f_event_1", period, period_index=0)
    special_row = special_opening_day_to_row("f_event_1", special_day)

    assert detail_row["starts_on"] == date(2026, 5, 1)
    assert period_row["duration_minutes"] == 360
    assert special_row["is_closed"] is True
    assert event_detail_from_row(detail_row) == detail
    assert opening_period_from_row(period_row) == period
    assert special_opening_day_from_row(special_row) == special_day


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
