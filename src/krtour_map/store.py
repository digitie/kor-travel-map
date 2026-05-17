from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from krtour_map.enums import FeatureStatus
from krtour_map.exceptions import (
    DuplicateFeatureError,
    FeatureNotFoundError,
    SourceRecordNotFoundError,
)
from krtour_map.models import (
    Feature,
    FeaturePatch,
    PricePoint,
    PriceValue,
    ProviderSyncState,
    SourceLink,
    SourceRecord,
    WeatherValue,
    kst_now,
)
from krtour_map.weather import latest_weather_values


class InMemoryFeatureStore:
    """Small deterministic store for tests, debug UI, and ETL dry-runs."""

    def __init__(self) -> None:
        self.features: dict[str, Feature] = {}
        self.source_records: dict[str, SourceRecord] = {}
        self.source_links: dict[tuple[str, str], SourceLink] = {}
        self.weather_values: dict[tuple[Any, ...], WeatherValue] = {}
        self.price_points: dict[str, PricePoint] = {}
        self.price_values: dict[tuple[str, str, Any], PriceValue] = {}
        self.sync_states: dict[tuple[str, str, str], ProviderSyncState] = {}

    def create_feature(self, feature: Feature) -> Feature:
        if feature.feature_id in self.features:
            raise DuplicateFeatureError(f"Feature already exists: {feature.feature_id}")
        self.features[feature.feature_id] = feature
        return feature

    def upsert_feature(self, feature: Feature) -> Feature:
        existing = self.features.get(feature.feature_id)
        if existing is not None and feature.created_at == feature.updated_at:
            feature = feature.model_copy(update={"created_at": existing.created_at})
        self.features[feature.feature_id] = feature.model_copy(update={"updated_at": kst_now()})
        return self.features[feature.feature_id]

    def get_feature(self, feature_id: str) -> Feature | None:
        return self.features.get(feature_id)

    def require_feature(self, feature_id: str) -> Feature:
        feature = self.get_feature(feature_id)
        if feature is None:
            raise FeatureNotFoundError(f"Feature not found: {feature_id}")
        return feature

    def update_feature(self, feature_id: str, patch: FeaturePatch | dict[str, Any]) -> Feature:
        feature = self.require_feature(feature_id)
        patch_model = (
            patch if isinstance(patch, FeaturePatch) else FeaturePatch.model_validate(patch)
        )
        update = patch_model.model_dump(exclude_unset=True)
        update["updated_at"] = kst_now()
        self.features[feature_id] = feature.model_copy(update=update)
        return self.features[feature_id]

    def delete_feature(self, feature_id: str, *, soft: bool = True) -> None:
        feature = self.require_feature(feature_id)
        if not soft:
            del self.features[feature_id]
            return
        self.features[feature_id] = feature.model_copy(
            update={
                "status": FeatureStatus.DELETED.value,
                "deleted_at": kst_now(),
                "updated_at": kst_now(),
            }
        )

    def list_features(
        self,
        *,
        kind: str | None = None,
        status: str | None = None,
        bjd_code: str | None = None,
        category: str | None = None,
        provider: str | None = None,
        source_role: str | None = None,
    ) -> list[Feature]:
        values: Iterable[Feature] = self.features.values()
        if kind is not None:
            values = [feature for feature in values if str(feature.kind) == kind]
        if status is not None:
            values = [feature for feature in values if str(feature.status) == status]
        if bjd_code is not None:
            values = [feature for feature in values if feature.address.bjd_code == bjd_code]
        if category is not None:
            values = [feature for feature in values if feature.category == category]
        if provider is not None:
            values = [
                feature
                for feature in values
                if any(ref.provider == provider for ref in feature.raw_refs)
            ]
        if source_role is not None:
            values = [
                feature
                for feature in values
                if any(ref.source_role == source_role for ref in feature.raw_refs)
            ]
        return sorted(values, key=lambda feature: feature.feature_id)

    def upsert_source_record(self, source_record: SourceRecord) -> SourceRecord:
        key = source_record.key()
        existing = self.source_records.get(key)
        if existing is not None:
            return existing
        stored = source_record.model_copy(update={"source_record_key": key})
        self.source_records[key] = stored
        return stored

    def require_source_record(self, source_record_key: str) -> SourceRecord:
        source_record = self.source_records.get(source_record_key)
        if source_record is None:
            raise SourceRecordNotFoundError(f"Source record not found: {source_record_key}")
        return source_record

    def link_source(self, link: SourceLink) -> SourceLink:
        self.require_feature(link.feature_id)
        self.require_source_record(link.source_record_key)
        self.source_links[(link.feature_id, link.source_record_key)] = link
        return link

    def source_links_for_feature(self, feature_id: str) -> list[SourceLink]:
        self.require_feature(feature_id)
        return sorted(
            [
                link
                for (stored_feature_id, _), link in self.source_links.items()
                if stored_feature_id == feature_id
            ],
            key=lambda link: (str(link.source_role), link.source_record_key),
        )

    def upsert_weather_value(self, value: WeatherValue) -> WeatherValue:
        self.require_feature(value.feature_id)
        self.weather_values[value.identity()] = value
        return value

    def list_weather_values(self, feature_id: str) -> list[WeatherValue]:
        self.require_feature(feature_id)
        return sorted(
            [value for value in self.weather_values.values() if value.feature_id == feature_id],
            key=lambda value: (
                str(value.weather_domain),
                str(value.forecast_style),
                value.metric_key,
            ),
        )

    def latest_weather_values(self, feature_id: str) -> list[WeatherValue]:
        return latest_weather_values(self.list_weather_values(feature_id))

    def upsert_price_point(self, point: PricePoint) -> PricePoint:
        self.require_feature(point.feature_id)
        self.price_points[point.feature_id] = point
        return point

    def upsert_price_value(self, value: PriceValue) -> PriceValue:
        if value.feature_id not in self.price_points:
            raise FeatureNotFoundError(f"Price point not found: {value.feature_id}")
        self.price_values[(value.feature_id, value.item_key, value.observed_at)] = value
        return value

    def set_sync_state(self, state: ProviderSyncState) -> ProviderSyncState:
        stored = state.model_copy(update={"updated_at": kst_now()})
        self.sync_states[state.identity()] = stored
        return stored

    def get_sync_state(
        self,
        *,
        provider: str,
        dataset_key: str,
        sync_scope: str = "global",
    ) -> ProviderSyncState | None:
        return self.sync_states.get((provider, dataset_key, sync_scope))
