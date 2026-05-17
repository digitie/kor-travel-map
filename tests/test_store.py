from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest

from krtour_map.enums import FeatureStatus, ForecastStyle, SourceRole, WeatherDomain
from krtour_map.exceptions import DuplicateFeatureError, FeatureNotFoundError
from krtour_map.models import (
    FeaturePatch,
    PricePoint,
    PriceValue,
    ProviderSyncState,
    SourceLink,
    SourceRecord,
    WeatherValue,
)
from krtour_map.store import InMemoryFeatureStore


def test_create_and_get_feature(sample_feature) -> None:
    store = InMemoryFeatureStore()

    created = store.create_feature(sample_feature)

    assert created.feature_id == sample_feature.feature_id
    assert store.get_feature(sample_feature.feature_id) == sample_feature


def test_create_feature_rejects_duplicate(sample_feature) -> None:
    store = InMemoryFeatureStore()
    store.create_feature(sample_feature)

    with pytest.raises(DuplicateFeatureError):
        store.create_feature(sample_feature)


def test_update_feature_applies_patch_without_clearing_unspecified_fields(sample_feature) -> None:
    store = InMemoryFeatureStore()
    store.create_feature(sample_feature)

    updated = store.update_feature(
        sample_feature.feature_id,
        FeaturePatch(name="Renamed Fuel Station", marker_color="P-05"),
    )

    assert updated.name == "Renamed Fuel Station"
    assert updated.marker_color == "P-05"
    assert updated.coord == sample_feature.coord


def test_soft_delete_preserves_feature_and_marks_deleted(sample_feature) -> None:
    store = InMemoryFeatureStore()
    store.create_feature(sample_feature)

    store.delete_feature(sample_feature.feature_id)

    deleted = store.require_feature(sample_feature.feature_id)
    assert deleted.status == FeatureStatus.DELETED
    assert deleted.deleted_at is not None


def test_hard_delete_removes_feature(sample_feature) -> None:
    store = InMemoryFeatureStore()
    store.create_feature(sample_feature)

    store.delete_feature(sample_feature.feature_id, soft=False)

    with pytest.raises(FeatureNotFoundError):
        store.require_feature(sample_feature.feature_id)


def test_source_record_upsert_is_idempotent_and_linkable(sample_feature) -> None:
    store = InMemoryFeatureStore()
    store.create_feature(sample_feature)
    source = SourceRecord(
        provider="opinet",
        dataset_key="fuel_lowest_station",
        source_entity_type="price",
        source_entity_id="A0010207",
        raw_payload_hash="hash",
        raw_data={"price": 1620},
    )

    first = store.upsert_source_record(source)
    second = store.upsert_source_record(source)
    link = store.link_source(
        SourceLink(
            feature_id=sample_feature.feature_id,
            source_record_key=first.key(),
            source_role=SourceRole.PRIMARY,
            match_method="source_id",
            confidence=100,
            is_primary_source=True,
        )
    )

    assert first == second
    assert link.source_record_key == first.key()
    assert store.source_links_for_feature(sample_feature.feature_id) == [link]


def test_weather_values_upsert_by_identity_and_latest_selection(sample_feature, fixed_time) -> None:
    store = InMemoryFeatureStore()
    store.create_feature(sample_feature)
    older = WeatherValue(
        feature_id=sample_feature.feature_id,
        provider="kma",
        weather_domain=WeatherDomain.KMA_SHORT_FORECAST,
        forecast_style=ForecastStyle.SHORT,
        metric_key="temp_c",
        valid_at=fixed_time,
        value_number=Decimal("20.0"),
    )
    newer = older.model_copy(
        update={
            "valid_at": fixed_time + timedelta(hours=3),
            "value_number": Decimal("22.0"),
        }
    )

    store.upsert_weather_value(older)
    store.upsert_weather_value(newer)
    latest = store.latest_weather_values(sample_feature.feature_id)

    assert len(store.list_weather_values(sample_feature.feature_id)) == 2
    assert len(latest) == 1
    assert latest[0].value_number == Decimal("22.0")


def test_price_point_must_exist_before_price_value(sample_feature, fixed_time) -> None:
    store = InMemoryFeatureStore()
    store.create_feature(sample_feature)

    with pytest.raises(FeatureNotFoundError):
        store.upsert_price_value(
            PriceValue(
                feature_id=sample_feature.feature_id,
                item_key="gasoline",
                observed_at=fixed_time,
                value=Decimal("1600"),
            )
        )

    store.upsert_price_point(
        PricePoint(feature_id=sample_feature.feature_id, price_category="fuel")
    )
    stored = store.upsert_price_value(
        PriceValue(
            feature_id=sample_feature.feature_id,
            item_key="gasoline",
            observed_at=fixed_time,
            value=Decimal("1600"),
        )
    )
    assert stored.value == Decimal("1600")


def test_provider_sync_state_round_trip() -> None:
    store = InMemoryFeatureStore()
    state = store.set_sync_state(
        ProviderSyncState(
            provider="python-kma-api",
            dataset_key="weather_short_term",
            sync_scope="sigungu:11110",
            cursor={"base_time": "0900"},
        )
    )

    assert (
        store.get_sync_state(
            provider="python-kma-api",
            dataset_key="weather_short_term",
            sync_scope="sigungu:11110",
        )
        == state
    )
