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
    MetaData,
    Numeric,
    Table,
    Text,
    UniqueConstraint,
    create_engine,
)
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from krtour_map.ids import make_payload_hash
from krtour_map.models import WeatherValue

metadata = MetaData()


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
    Column("address", JSON, nullable=False, default=dict),
    Column("detail", JSON, nullable=False, default=dict),
    Column("status", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)

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
    Column("feature_id", Text, ForeignKey("features.feature_id", ondelete="CASCADE"), primary_key=True),
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
