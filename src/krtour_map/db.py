from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Numeric,
    Table,
    Text,
    UniqueConstraint,
    create_engine,
)
from sqlalchemy.engine import Engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.types import UserDefinedType

from krtour_map.ids import make_payload_hash
from krtour_map.models import PricePoint, PriceValue, ProviderSyncState, WeatherValue

metadata = MetaData()


class PostgisGeometry(UserDefinedType[str]):
    """Minimal PostGIS geometry type without adding GeoAlchemy as a hard dependency."""

    cache_ok = True

    def __init__(self, geometry_type: str = "GEOMETRY", srid: int = 4326) -> None:
        self.geometry_type = geometry_type
        self.srid = srid

    def get_col_spec(self, **_: Any) -> str:
        return f"GEOMETRY({self.geometry_type}, {self.srid})"


@compiles(PostgisGeometry, "sqlite")
def _compile_postgis_geometry_sqlite(type_: PostgisGeometry, compiler: Any, **kw: Any) -> str:
    return "TEXT"


@dataclass(frozen=True)
class FeatureDbSettings:
    """Database settings supplied by the host application."""

    database_url: str
    pool_pre_ping: bool = True
    engine_options: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FeatureDbContext:
    """Initialized feature DB engine/session bundle."""

    settings: FeatureDbSettings
    engine: Engine
    session_factory: sessionmaker[Session]

    def create_schema(self) -> None:
        create_feature_schema(self.engine)

    def drop_schema(self) -> None:
        drop_feature_schema(self.engine)

    def dispose(self) -> None:
        self.engine.dispose()

features = Table(
    "features",
    metadata,
    Column("feature_id", Text, primary_key=True),
    Column("kind", Text, nullable=False),
    Column("name", Text, nullable=False),
    Column("category", Text, nullable=False),
    Column("longitude", Numeric(12, 8)),
    Column("latitude", Numeric(12, 8)),
    Column("geom", PostgisGeometry()),
    Column("address", JSON, nullable=False, default=dict),
    Column("legal_dong_code", Text),
    Column("road_name_code", Text),
    Column("road_address_management_no", Text),
    Column("admin_dong_code", Text),
    Column("sido_code", Text),
    Column("sigungu_code", Text),
    Column("urls", JSON, nullable=False, default=dict),
    Column("marker_icon", Text),
    Column("marker_color", Text),
    Column("parent_feature_id", Text, ForeignKey("features.feature_id", ondelete="SET NULL")),
    Column("sibling_group_id", Text),
    Column("detail", JSON, nullable=False, default=dict),
    Column("raw_refs", JSON, nullable=False, default=list),
    Column("status", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    Column("deleted_at", DateTime(timezone=True)),
    CheckConstraint(
        "kind IN ('place', 'event', 'notice', 'price', 'weather', 'route', 'area')",
        name="ck_features_kind",
    ),
    CheckConstraint(
        "status IN ('draft', 'active', 'inactive', 'hidden', 'broken', 'deleted')",
        name="ck_features_status",
    ),
    CheckConstraint(
        "(longitude IS NULL AND latitude IS NULL) OR "
        "(longitude IS NOT NULL AND latitude IS NOT NULL)",
        name="ck_features_coordinate_pair",
    ),
    CheckConstraint(
        "longitude IS NULL OR (longitude >= 124 AND longitude <= 132)",
        name="ck_features_korea_longitude",
    ),
    CheckConstraint(
        "latitude IS NULL OR (latitude >= 33 AND latitude <= 39.5)",
        name="ck_features_korea_latitude",
    ),
)

Index("ix_features_kind_category", features.c.kind, features.c.category)
Index("ix_features_status", features.c.status)
Index("ix_features_legal_dong_code", features.c.legal_dong_code)
Index("ix_features_parent_feature_id", features.c.parent_feature_id)
Index("ix_features_sibling_group_id", features.c.sibling_group_id)
Index("ix_features_lon_lat", features.c.longitude, features.c.latitude)

source_records = Table(
    "source_records",
    metadata,
    Column("source_record_key", Text, primary_key=True),
    Column("provider", Text, nullable=False),
    Column("dataset_key", Text, nullable=False),
    Column("source_entity_type", Text, nullable=False),
    Column("source_entity_id", Text, nullable=False),
    Column("source_version", Text),
    Column("raw_name", Text),
    Column("raw_address", Text),
    Column("raw_longitude", Numeric(12, 8)),
    Column("raw_latitude", Numeric(12, 8)),
    Column("raw_data", JSON, nullable=False, default=dict),
    Column("raw_payload_hash", Text, nullable=False),
    Column("fetched_at", DateTime(timezone=True), nullable=False),
    Column("imported_at", DateTime(timezone=True), nullable=False),
    Column("expires_at", DateTime(timezone=True)),
    UniqueConstraint(
        "provider",
        "dataset_key",
        "source_entity_type",
        "source_entity_id",
        "raw_payload_hash",
        name="uq_source_records_provider_entity_hash",
    ),
)

source_links = Table(
    "source_links",
    metadata,
    Column(
        "feature_id",
        Text,
        ForeignKey("features.feature_id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "source_record_key",
        Text,
        ForeignKey("source_records.source_record_key", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("source_role", Text, nullable=False),
    Column("match_method", Text, nullable=False),
    Column("confidence", Numeric(5, 2), nullable=False),
    Column("is_primary_source", Boolean, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    CheckConstraint("confidence >= 0 AND confidence <= 100", name="ck_source_links_confidence"),
    CheckConstraint(
        "source_role IN ("
        "'base_address', 'base_coordinate', 'primary', 'enrichment', 'correction', "
        "'duplicate_candidate', 'media', 'weather_context'"
        ")",
        name="ck_source_links_source_role",
    ),
)

feature_weather_values = Table(
    "feature_weather_values",
    metadata,
    Column("weather_value_key", Text, primary_key=True),
    Column(
        "feature_id",
        Text,
        ForeignKey("features.feature_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("provider", Text, nullable=False),
    Column("weather_domain", Text, nullable=False),
    Column("forecast_style", Text, nullable=False),
    Column("timeline_bucket", Text),
    Column(
        "source_record_key",
        Text,
        ForeignKey("source_records.source_record_key", ondelete="SET NULL"),
    ),
    Column("issued_at", DateTime(timezone=True)),
    Column("valid_at", DateTime(timezone=True)),
    Column("valid_from", DateTime(timezone=True)),
    Column("valid_until", DateTime(timezone=True)),
    Column("observed_at", DateTime(timezone=True)),
    Column("metric_key", Text, nullable=False),
    Column("source_metric_key", Text),
    Column("source_metric_name", Text),
    Column("metric_name", Text),
    Column("value_number", Numeric(14, 4)),
    Column("value_text", Text),
    Column("unit", Text),
    Column("severity", Text),
    Column("normalization_version", Text),
    Column("payload", JSON, nullable=False, default=dict),
    Column("collected_at", DateTime(timezone=True), nullable=False),
    CheckConstraint(
        "timeline_bucket IS NULL OR timeline_bucket IN ('ultra_short', 'short', 'mid')",
        name="ck_feature_weather_values_timeline_bucket",
    ),
    UniqueConstraint(
        "feature_id",
        "provider",
        "weather_domain",
        "forecast_style",
        "metric_key",
        "issued_at",
        "valid_at",
        "observed_at",
        name="uq_feature_weather_values_feature_provider_time",
    ),
)

Index(
    "ix_feature_weather_values_feature_valid",
    feature_weather_values.c.feature_id,
    feature_weather_values.c.valid_at,
)
Index(
    "ix_feature_weather_values_feature_timeline_valid",
    feature_weather_values.c.feature_id,
    feature_weather_values.c.timeline_bucket,
    feature_weather_values.c.valid_at,
)
Index(
    "ix_feature_weather_values_provider_domain",
    feature_weather_values.c.provider,
    feature_weather_values.c.weather_domain,
)
Index("ix_feature_weather_values_valid_at", feature_weather_values.c.valid_at)
Index("ix_feature_weather_values_observed_at", feature_weather_values.c.observed_at)

price_points = Table(
    "price_points",
    metadata,
    Column(
        "feature_id",
        Text,
        ForeignKey("features.feature_id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("price_category", Text, nullable=False),
    Column("retention_days", Integer, nullable=False),
    CheckConstraint("retention_days >= 1", name="ck_price_points_retention_days"),
)

Index("ix_price_points_category", price_points.c.price_category)

price_values = Table(
    "price_values",
    metadata,
    Column(
        "feature_id",
        Text,
        ForeignKey("price_points.feature_id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("item_key", Text, primary_key=True),
    Column("observed_at", DateTime(timezone=True), primary_key=True),
    Column("value", Numeric(12, 2), nullable=False),
    Column("currency", Text, nullable=False, default="KRW"),
    Column("payload_hash", Text),
    Column("payload", JSON, nullable=False, default=dict),
    CheckConstraint("length(currency) = 3", name="ck_price_values_currency_length"),
)

Index("ix_price_values_observed_at", price_values.c.observed_at)
Index("ix_price_values_feature_observed", price_values.c.feature_id, price_values.c.observed_at)

provider_sync_state = Table(
    "provider_sync_state",
    metadata,
    Column("provider", Text, primary_key=True),
    Column("dataset_key", Text, primary_key=True),
    Column("sync_scope", Text, primary_key=True, default="global"),
    Column("status", Text, nullable=False, default="active"),
    Column("cursor", JSON),
    Column("last_success_at", DateTime(timezone=True)),
    Column("last_attempt_at", DateTime(timezone=True)),
    Column("next_run_after", DateTime(timezone=True)),
    Column("last_error", Text),
    Column("last_error_at", DateTime(timezone=True)),
    Column("extra", JSON, nullable=False, default=dict),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)

Index(
    "ix_provider_sync_state_next_run",
    provider_sync_state.c.status,
    provider_sync_state.c.next_run_after,
)

feature_overrides = Table(
    "feature_overrides",
    metadata,
    Column("override_key", Text, primary_key=True),
    Column("feature_id", Text, ForeignKey("features.feature_id", ondelete="SET NULL")),
    Column(
        "source_record_key",
        Text,
        ForeignKey("source_records.source_record_key", ondelete="SET NULL"),
    ),
    Column("provider", Text),
    Column("dataset_key", Text),
    Column("field_path", Text, nullable=False),
    Column("source_value", JSON),
    Column("override_value", JSON),
    Column("status", Text, nullable=False, default="active"),
    Column("reason", Text),
    Column("created_by", Text),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    CheckConstraint(
        "status IN ('active', 'inactive', 'superseded')",
        name="ck_feature_overrides_status",
    ),
)

Index(
    "ix_feature_overrides_feature_status",
    feature_overrides.c.feature_id,
    feature_overrides.c.status,
)
Index(
    "ix_feature_overrides_provider_dataset",
    feature_overrides.c.provider,
    feature_overrides.c.dataset_key,
)

dedup_review_queue = Table(
    "dedup_review_queue",
    metadata,
    Column("review_key", Text, primary_key=True),
    Column(
        "feature_id_a",
        Text,
        ForeignKey("features.feature_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "feature_id_b",
        Text,
        ForeignKey("features.feature_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("score", Numeric(5, 2), nullable=False),
    Column("name_score", Numeric(5, 2)),
    Column("spatial_score", Numeric(5, 2)),
    Column("category_score", Numeric(5, 2)),
    Column("status", Text, nullable=False, default="pending"),
    Column("decision_reason", Text),
    Column("reviewed_by", Text),
    Column("reviewed_at", DateTime(timezone=True)),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("feature_id_a", "feature_id_b", name="uq_dedup_review_queue_pair"),
    CheckConstraint("feature_id_a <> feature_id_b", name="ck_dedup_review_queue_distinct_pair"),
    CheckConstraint("score >= 0 AND score <= 100", name="ck_dedup_review_queue_score"),
    CheckConstraint(
        "status IN ('pending', 'accepted', 'rejected', 'merged', 'ignored')",
        name="ck_dedup_review_queue_status",
    ),
)

Index("ix_dedup_review_queue_status_score", dedup_review_queue.c.status, dedup_review_queue.c.score)

data_integrity_violations = Table(
    "data_integrity_violations",
    metadata,
    Column("violation_key", Text, primary_key=True),
    Column("provider", Text, nullable=False),
    Column("dataset_key", Text, nullable=False),
    Column(
        "source_record_key",
        Text,
        ForeignKey("source_records.source_record_key", ondelete="SET NULL"),
    ),
    Column("feature_id", Text, ForeignKey("features.feature_id", ondelete="SET NULL")),
    Column("violation_type", Text, nullable=False),
    Column("severity", Text, nullable=False, default="warning"),
    Column("message", Text, nullable=False),
    Column("payload", JSON, nullable=False, default=dict),
    Column("status", Text, nullable=False, default="open"),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("resolved_at", DateTime(timezone=True)),
    CheckConstraint(
        "severity IN ('info', 'warning', 'error', 'critical')",
        name="ck_data_integrity_violations_severity",
    ),
    CheckConstraint(
        "status IN ('open', 'acknowledged', 'resolved', 'ignored')",
        name="ck_data_integrity_violations_status",
    ),
)

Index(
    "ix_data_integrity_violations_status_severity",
    data_integrity_violations.c.status,
    data_integrity_violations.c.severity,
)
Index(
    "ix_data_integrity_violations_provider_dataset",
    data_integrity_violations.c.provider,
    data_integrity_violations.c.dataset_key,
)


def create_feature_schema(bind: Any) -> None:
    """Create the python-krtour-map owned feature schema on a SQLAlchemy bind."""

    metadata.create_all(bind)


def drop_feature_schema(bind: Any) -> None:
    """Drop the python-krtour-map owned feature schema on a SQLAlchemy bind."""

    metadata.drop_all(bind)


def feature_db_settings_from_object(
    settings: FeatureDbSettings | str | Mapping[str, Any] | object,
    *,
    database_url_key: str = "database_url",
    pool_pre_ping: bool | None = None,
    engine_options: Mapping[str, Any] | None = None,
) -> FeatureDbSettings:
    """Build feature DB settings from TripMate settings, a mapping, or a URL."""

    if isinstance(settings, FeatureDbSettings):
        base = settings
    elif isinstance(settings, str):
        base = FeatureDbSettings(database_url=settings)
    elif isinstance(settings, Mapping):
        database_url = settings.get(database_url_key)
        if not isinstance(database_url, str) or not database_url:
            raise ValueError(f"{database_url_key} must be a non-empty database URL")
        base = FeatureDbSettings(database_url=database_url)
    else:
        database_url = getattr(settings, database_url_key, None)
        if not isinstance(database_url, str) or not database_url:
            raise ValueError(f"{database_url_key} must be a non-empty database URL")
        base = FeatureDbSettings(database_url=database_url)

    return FeatureDbSettings(
        database_url=base.database_url,
        pool_pre_ping=base.pool_pre_ping if pool_pre_ping is None else pool_pre_ping,
        engine_options={**dict(base.engine_options), **dict(engine_options or {})},
    )


def create_feature_engine(
    settings: FeatureDbSettings | str | Mapping[str, Any] | object,
    **engine_options: Any,
) -> Engine:
    """Create an SQLAlchemy engine from host application DB settings."""

    feature_settings = feature_db_settings_from_object(
        settings,
        engine_options=engine_options,
    )
    return create_engine(
        feature_settings.database_url,
        pool_pre_ping=feature_settings.pool_pre_ping,
        **dict(feature_settings.engine_options),
    )


def create_feature_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Create the standard session factory for feature DB writes."""

    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def initialize_feature_db(
    settings: FeatureDbSettings | str | Mapping[str, Any] | object,
    *,
    create_schema: bool = True,
    **engine_options: Any,
) -> FeatureDbContext:
    """Initialize feature DB access from TripMate-provided DB settings."""

    feature_settings = feature_db_settings_from_object(
        settings,
        engine_options=engine_options,
    )
    engine = create_feature_engine(feature_settings)
    context = FeatureDbContext(
        settings=feature_settings,
        engine=engine,
        session_factory=create_feature_session_factory(engine),
    )
    if create_schema:
        context.create_schema()
    return context


def weather_value_to_row(value: WeatherValue) -> dict[str, Any]:
    """Convert a `WeatherValue` DTO into a `feature_weather_values` row payload."""

    return {
        "weather_value_key": make_weather_value_key(value),
        "feature_id": value.feature_id,
        "provider": value.provider,
        "weather_domain": str(value.weather_domain),
        "forecast_style": str(value.forecast_style),
        "timeline_bucket": str(value.timeline_bucket) if value.timeline_bucket else None,
        "source_record_key": value.source_record_key,
        "issued_at": value.issued_at,
        "valid_at": value.valid_at,
        "valid_from": value.valid_from,
        "valid_until": value.valid_until,
        "observed_at": value.observed_at,
        "metric_key": value.metric_key,
        "source_metric_key": value.source_metric_key,
        "source_metric_name": value.source_metric_name,
        "metric_name": value.metric_name,
        "value_number": value.value_number,
        "value_text": value.value_text,
        "unit": value.unit,
        "severity": value.severity,
        "normalization_version": value.normalization_version,
        "payload": value.payload,
        "collected_at": value.collected_at,
    }


def weather_value_from_row(row: Mapping[str, Any]) -> WeatherValue:
    """Convert a `feature_weather_values` row mapping into a `WeatherValue` DTO."""

    return WeatherValue(
        feature_id=str(row["feature_id"]),
        provider=str(row["provider"]),
        weather_domain=str(row["weather_domain"]),
        forecast_style=str(row["forecast_style"]),
        timeline_bucket=row.get("timeline_bucket"),
        source_record_key=row.get("source_record_key"),
        issued_at=row.get("issued_at"),
        valid_at=row.get("valid_at"),
        valid_from=row.get("valid_from"),
        valid_until=row.get("valid_until"),
        observed_at=row.get("observed_at"),
        metric_key=str(row["metric_key"]),
        source_metric_key=row.get("source_metric_key"),
        source_metric_name=row.get("source_metric_name"),
        metric_name=row.get("metric_name"),
        value_number=row.get("value_number"),
        value_text=row.get("value_text"),
        unit=row.get("unit"),
        severity=row.get("severity"),
        normalization_version=row.get("normalization_version"),
        payload=dict(row.get("payload") or {}),
        collected_at=row["collected_at"],
    )


def make_weather_value_key(value: WeatherValue) -> str:
    """Return the deterministic primary key for a weather value row."""

    digest = make_payload_hash(
        {
            "feature_id": value.feature_id,
            "provider": value.provider,
            "weather_domain": str(value.weather_domain),
            "forecast_style": str(value.forecast_style),
            "metric_key": value.metric_key,
            "issued_at": value.issued_at,
            "valid_at": value.valid_at,
            "observed_at": value.observed_at,
        },
        length=20,
    )
    return f"wv_{digest}"


def price_point_to_row(point: PricePoint) -> dict[str, Any]:
    """Convert a `PricePoint` DTO into a `price_points` row payload."""

    return {
        "feature_id": point.feature_id,
        "price_category": point.price_category,
        "retention_days": point.retention_days,
    }


def price_point_from_row(row: Mapping[str, Any]) -> PricePoint:
    """Convert a `price_points` row mapping into a `PricePoint` DTO."""

    return PricePoint(
        feature_id=str(row["feature_id"]),
        price_category=str(row["price_category"]),
        retention_days=int(row["retention_days"]),
    )


def price_value_to_row(value: PriceValue) -> dict[str, Any]:
    """Convert a `PriceValue` DTO into a `price_values` row payload."""

    return {
        "feature_id": value.feature_id,
        "item_key": value.item_key,
        "observed_at": value.observed_at,
        "value": value.value,
        "currency": value.currency,
        "payload_hash": value.payload_hash,
        "payload": {},
    }


def price_value_from_row(row: Mapping[str, Any]) -> PriceValue:
    """Convert a `price_values` row mapping into a `PriceValue` DTO."""

    return PriceValue(
        feature_id=str(row["feature_id"]),
        item_key=str(row["item_key"]),
        observed_at=row["observed_at"],
        value=row["value"],
        currency=str(row["currency"]),
        payload_hash=row.get("payload_hash"),
    )


def provider_sync_state_to_row(state: ProviderSyncState) -> dict[str, Any]:
    """Convert a `ProviderSyncState` DTO into a `provider_sync_state` row payload."""

    return {
        "provider": state.provider,
        "dataset_key": state.dataset_key,
        "sync_scope": state.sync_scope,
        "status": state.status,
        "cursor": state.cursor,
        "last_success_at": state.last_success_at,
        "last_attempt_at": state.last_attempt_at,
        "next_run_after": state.next_run_after,
        "last_error": state.last_error,
        "last_error_at": state.last_error_at,
        "extra": state.extra,
        "updated_at": state.updated_at,
    }


def provider_sync_state_from_row(row: Mapping[str, Any]) -> ProviderSyncState:
    """Convert a `provider_sync_state` row mapping into a `ProviderSyncState` DTO."""

    return ProviderSyncState(
        provider=str(row["provider"]),
        dataset_key=str(row["dataset_key"]),
        sync_scope=str(row["sync_scope"]),
        status=str(row["status"]),
        cursor=dict(row["cursor"]) if row.get("cursor") is not None else None,
        last_success_at=row.get("last_success_at"),
        last_attempt_at=row.get("last_attempt_at"),
        next_run_after=row.get("next_run_after"),
        last_error=row.get("last_error"),
        last_error_at=row.get("last_error_at"),
        extra=dict(row.get("extra") or {}),
        updated_at=row["updated_at"],
    )


def make_feature_override_key(
    *,
    feature_id: str | None,
    source_record_key: str | None,
    field_path: str,
    source_value: Any = None,
    override_value: Any = None,
) -> str:
    """Return a deterministic key for a feature override row."""

    digest = make_payload_hash(
        {
            "feature_id": feature_id,
            "source_record_key": source_record_key,
            "field_path": field_path,
            "source_value": source_value,
            "override_value": override_value,
        },
        length=20,
    )
    return f"fo_{digest}"


def make_dedup_review_key(feature_id_a: str, feature_id_b: str) -> str:
    """Return a deterministic key for a dedup review pair."""

    pair = sorted((feature_id_a, feature_id_b))
    digest = make_payload_hash({"feature_id_a": pair[0], "feature_id_b": pair[1]}, length=20)
    return f"dr_{digest}"


def make_data_integrity_violation_key(
    *,
    provider: str,
    dataset_key: str,
    violation_type: str,
    source_record_key: str | None = None,
    feature_id: str | None = None,
    payload: Any = None,
) -> str:
    """Return a deterministic key for a data integrity violation row."""

    digest = make_payload_hash(
        {
            "provider": provider,
            "dataset_key": dataset_key,
            "violation_type": violation_type,
            "source_record_key": source_record_key,
            "feature_id": feature_id,
            "payload": payload,
        },
        length=20,
    )
    return f"dv_{digest}"
