from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Numeric,
    Table,
    Text,
    UniqueConstraint,
    and_,
    create_engine,
)
from sqlalchemy.engine import Engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.types import UserDefinedType

from krtour_map.ids import make_payload_hash
from krtour_map.models import (
    AreaDetail,
    Coordinate,
    EventDetail,
    Feature,
    FeatureFile,
    FeatureOpeningHours,
    NoticeDetail,
    OpeningPeriod,
    OpeningTime,
    PlaceDetail,
    PricePoint,
    PriceValue,
    ProviderSyncState,
    RouteDetail,
    SourceLink,
    SourceRecord,
    SpecialOpeningDay,
    WeatherValue,
)

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


@dataclass(frozen=True)
class FeatureDbLoadResult:
    """Row counts written by a feature DB load operation."""

    features: int = 0
    source_records: int = 0
    source_links: int = 0
    place_details: int = 0
    event_details: int = 0
    area_details: int = 0
    route_details: int = 0
    notice_details: int = 0
    opening_periods: int = 0
    special_days: int = 0
    weather_values: int = 0
    price_points: int = 0
    price_values: int = 0
    feature_files: int = 0
    provider_sync_states: int = 0


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
Index("ix_features_kind_status_updated", features.c.kind, features.c.status, features.c.updated_at)
Index("ix_features_status", features.c.status)
Index("ix_features_updated_at", features.c.updated_at)
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

Index(
    "ix_source_records_provider_dataset_entity",
    source_records.c.provider,
    source_records.c.dataset_key,
    source_records.c.source_entity_type,
    source_records.c.source_entity_id,
)
Index("ix_source_records_imported_at", source_records.c.imported_at)

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

feature_files = Table(
    "feature_files",
    metadata,
    Column("file_id", Text, primary_key=True),
    Column(
        "feature_id",
        Text,
        ForeignKey("features.feature_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("file_type", Text, nullable=False, default="image"),
    Column("storage_backend", Text, nullable=False, default="rustfs"),
    Column("bucket", Text, nullable=False),
    Column("object_key", Text, nullable=False),
    Column("source_url", Text),
    Column("public_url", Text),
    Column("content_type", Text),
    Column("byte_size", Integer),
    Column("checksum_sha256", Text),
    Column("width", Integer),
    Column("height", Integer),
    Column("role", Text, nullable=False, default="gallery"),
    Column("display_order", Integer, nullable=False, default=0),
    Column("alt_text", Text),
    Column("provider", Text),
    Column("dataset_key", Text),
    Column(
        "source_record_key",
        Text,
        ForeignKey("source_records.source_record_key", ondelete="SET NULL"),
    ),
    Column("payload", JSON, nullable=False, default=dict),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint(
        "storage_backend",
        "bucket",
        "object_key",
        name="uq_feature_files_storage_object",
    ),
    CheckConstraint("storage_backend = 'rustfs'", name="ck_feature_files_storage_backend"),
    CheckConstraint(
        "file_type IN ('image', 'video', 'audio', 'document', 'file')",
        name="ck_feature_files_file_type",
    ),
    CheckConstraint("display_order >= 0", name="ck_feature_files_display_order"),
    CheckConstraint("byte_size IS NULL OR byte_size >= 0", name="ck_feature_files_byte_size"),
    CheckConstraint("width IS NULL OR width > 0", name="ck_feature_files_width"),
    CheckConstraint("height IS NULL OR height > 0", name="ck_feature_files_height"),
)

Index("ix_feature_files_feature_type", feature_files.c.feature_id, feature_files.c.file_type)
Index("ix_feature_files_feature_order", feature_files.c.feature_id, feature_files.c.display_order)
Index("ix_feature_files_storage_object", feature_files.c.bucket, feature_files.c.object_key)
Index("ix_feature_files_provider_dataset", feature_files.c.provider, feature_files.c.dataset_key)

feature_place_details = Table(
    "feature_place_details",
    metadata,
    Column(
        "feature_id",
        Text,
        ForeignKey("features.feature_id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("place_kind", Text, nullable=False, default="place"),
    Column("phones", JSON, nullable=False, default=list),
    Column("reviews_link", JSON, nullable=False, default=dict),
    Column("business_hours", JSON),
    Column("facility_info", JSON, nullable=False, default=dict),
    Column("license_date", Date),
    Column("biz_number", Text),
    Column("payload", JSON, nullable=False, default=dict),
)

Index("ix_feature_place_details_place_kind", feature_place_details.c.place_kind)
Index("ix_feature_place_details_biz_number", feature_place_details.c.biz_number)

feature_event_details = Table(
    "feature_event_details",
    metadata,
    Column(
        "feature_id",
        Text,
        ForeignKey("features.feature_id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("event_kind", Text, nullable=False),
    Column("starts_on", Date),
    Column("ends_on", Date),
    Column("timezone", Text, nullable=False, default="Asia/Seoul"),
    Column("venue_name", Text),
    Column("tel", Text),
    Column("content_id", Text),
    Column("content_type_id", Text),
    Column("area_code", Text),
    Column("sigungu_code", Text),
    Column("payload", JSON, nullable=False, default=dict),
    CheckConstraint(
        "starts_on IS NULL OR ends_on IS NULL OR ends_on >= starts_on",
        name="ck_feature_event_details_date_range",
    ),
)

Index(
    "ix_feature_event_details_dates",
    feature_event_details.c.starts_on,
    feature_event_details.c.ends_on,
)
Index("ix_feature_event_details_event_kind", feature_event_details.c.event_kind)
Index("ix_feature_event_details_content_id", feature_event_details.c.content_id)

feature_notice_details = Table(
    "feature_notice_details",
    metadata,
    Column(
        "feature_id",
        Text,
        ForeignKey("features.feature_id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("notice_type", Text, nullable=False),
    Column("severity", Integer),
    Column("valid_start_time", DateTime(timezone=True)),
    Column("valid_end_time", DateTime(timezone=True)),
    Column("source_agency", Text),
    Column("officer_name", Text),
    Column("payload", JSON, nullable=False, default=dict),
    CheckConstraint(
        "severity IS NULL OR (severity >= 0 AND severity <= 5)",
        name="ck_feature_notice_details_severity",
    ),
    CheckConstraint(
        "valid_start_time IS NULL OR valid_end_time IS NULL OR "
        "valid_end_time >= valid_start_time",
        name="ck_feature_notice_details_valid_time_range",
    ),
)

Index("ix_feature_notice_details_notice_type", feature_notice_details.c.notice_type)
Index(
    "ix_feature_notice_details_type_valid_time",
    feature_notice_details.c.notice_type,
    feature_notice_details.c.valid_start_time,
    feature_notice_details.c.valid_end_time,
)
Index("ix_feature_notice_details_valid_time", feature_notice_details.c.valid_start_time)
Index("ix_feature_notice_details_source_agency", feature_notice_details.c.source_agency)

feature_area_details = Table(
    "feature_area_details",
    metadata,
    Column(
        "feature_id",
        Text,
        ForeignKey("features.feature_id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("area_kind", Text, nullable=False, default="area"),
    Column("boundary_source", Text),
    Column("area_square_meters", Numeric(18, 4)),
    Column("regulation_scope", Text),
    Column("administrative_office", Text),
    Column("description", Text),
    Column("geometry", JSON),
    Column("payload", JSON, nullable=False, default=dict),
)

Index("ix_feature_area_details_area_kind", feature_area_details.c.area_kind)
Index("ix_feature_area_details_boundary_source", feature_area_details.c.boundary_source)

feature_route_details = Table(
    "feature_route_details",
    metadata,
    Column(
        "feature_id",
        Text,
        ForeignKey("features.feature_id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("route_type", Text, nullable=False, default="route"),
    Column("geometry_source", Text),
    Column("geometry_status", Text),
    Column("total_distance_meters", Numeric(14, 2)),
    Column("expected_duration_minutes", Integer),
    Column("difficulty", Text),
    Column("begin_name", Text),
    Column("begin_address", Text),
    Column("end_name", Text),
    Column("end_address", Text),
    Column("geometry", JSON),
    Column("payload", JSON, nullable=False, default=dict),
    CheckConstraint(
        "total_distance_meters IS NULL OR total_distance_meters >= 0",
        name="ck_feature_route_details_distance",
    ),
    CheckConstraint(
        "expected_duration_minutes IS NULL OR expected_duration_minutes > 0",
        name="ck_feature_route_details_duration",
    ),
)

Index("ix_feature_route_details_route_type", feature_route_details.c.route_type)
Index("ix_feature_route_details_geometry_status", feature_route_details.c.geometry_status)
Index("ix_feature_route_details_geometry_source", feature_route_details.c.geometry_source)

feature_opening_periods = Table(
    "feature_opening_periods",
    metadata,
    Column(
        "feature_id",
        Text,
        ForeignKey("features.feature_id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("period_index", Integer, primary_key=True),
    Column("start_weekday", Integer, nullable=False),
    Column("start_time", Text, nullable=False),
    Column("duration_minutes", Integer, nullable=False),
    Column("timezone", Text, nullable=False, default="Asia/Seoul"),
    Column("payload", JSON, nullable=False, default=dict),
    CheckConstraint(
        "start_weekday >= 0 AND start_weekday <= 6",
        name="ck_feature_opening_periods_start_weekday",
    ),
    CheckConstraint("length(start_time) = 4", name="ck_feature_opening_periods_start_time"),
    CheckConstraint(
        "duration_minutes > 0 AND duration_minutes <= 10080",
        name="ck_feature_opening_periods_duration",
    ),
)

Index(
    "ix_feature_opening_periods_start",
    feature_opening_periods.c.start_weekday,
    feature_opening_periods.c.start_time,
)

feature_special_days = Table(
    "feature_special_days",
    metadata,
    Column(
        "feature_id",
        Text,
        ForeignKey("features.feature_id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("special_date", Date, primary_key=True),
    Column("is_closed", Boolean, nullable=False),
    Column("periods", JSON),
    Column("payload", JSON, nullable=False, default=dict),
)

Index("ix_feature_special_days_date", feature_special_days.c.special_date)

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
    Column("metadata_hash", Text),
    Column("last_observed_source_version", Text),
    Column("last_success_at", DateTime(timezone=True)),
    Column("last_attempt_at", DateTime(timezone=True)),
    Column("last_full_scan_at", DateTime(timezone=True)),
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


def load_feature_rows(
    session: Session,
    *,
    feature_items: Iterable[Feature] = (),
    source_record_items: Iterable[SourceRecord] = (),
    source_link_items: Iterable[SourceLink] = (),
    place_detail_items: Iterable[PlaceDetail] = (),
    event_detail_items: Iterable[EventDetail] = (),
    area_detail_items: Iterable[AreaDetail] = (),
    route_detail_items: Iterable[RouteDetail] = (),
    notice_detail_items: Iterable[NoticeDetail] = (),
    feature_file_items: Iterable[FeatureFile] = (),
    opening_hours_by_feature_id: Mapping[str, FeatureOpeningHours] | None = None,
    weather_value_items: Iterable[WeatherValue] = (),
    price_point_items: Iterable[PricePoint] = (),
    price_value_items: Iterable[PriceValue] = (),
    provider_sync_state_items: Iterable[ProviderSyncState] = (),
) -> FeatureDbLoadResult:
    """Update-or-insert normalized feature rows into an open SQLAlchemy session.

    Callers own the transaction boundary. TripMate's Dagster op can pass its feature DB
    session here, inspect the returned counts, and commit or roll back with its own
    resource policy.
    """

    source_record_rows = list(source_record_items)
    feature_rows = list(feature_items)
    source_link_rows = list(source_link_items)
    place_detail_rows = list(place_detail_items)
    event_detail_rows = list(event_detail_items)
    area_detail_rows = list(area_detail_items)
    route_detail_rows = list(route_detail_items)
    notice_detail_rows = list(notice_detail_items)
    feature_file_rows = list(feature_file_items)
    weather_value_rows = list(weather_value_items)
    price_point_rows = list(price_point_items)
    price_value_rows = list(price_value_items)
    provider_sync_state_rows = list(provider_sync_state_items)
    opening_hours = dict(opening_hours_by_feature_id or {})

    for source_record in source_record_rows:
        _upsert_row(
            session,
            source_records,
            {"source_record_key": source_record.key()},
            source_record_to_row(source_record),
        )

    for feature in feature_rows:
        _upsert_row(
            session,
            features,
            {"feature_id": feature.feature_id},
            feature_to_row(feature),
        )

    for detail in place_detail_rows:
        _upsert_row(
            session,
            feature_place_details,
            {"feature_id": detail.feature_id},
            place_detail_to_row(detail),
        )

    for detail in event_detail_rows:
        _upsert_row(
            session,
            feature_event_details,
            {"feature_id": detail.feature_id},
            event_detail_to_row(detail),
        )

    for detail in area_detail_rows:
        _upsert_row(
            session,
            feature_area_details,
            {"feature_id": detail.feature_id},
            area_detail_to_row(detail),
        )

    for detail in route_detail_rows:
        _upsert_row(
            session,
            feature_route_details,
            {"feature_id": detail.feature_id},
            route_detail_to_row(detail),
        )

    for detail in notice_detail_rows:
        _upsert_row(
            session,
            feature_notice_details,
            {"feature_id": detail.feature_id},
            notice_detail_to_row(detail),
        )

    for feature_file in feature_file_rows:
        _upsert_row(
            session,
            feature_files,
            {"file_id": feature_file.file_id},
            feature_file_to_row(feature_file),
        )

    opening_period_count = 0
    special_day_count = 0
    for feature_id, hours in opening_hours.items():
        session.execute(
            feature_opening_periods.delete().where(
                feature_opening_periods.c.feature_id == feature_id
            )
        )
        session.execute(
            feature_special_days.delete().where(feature_special_days.c.feature_id == feature_id)
        )
        period_rows = opening_hours_to_period_rows(feature_id, hours)
        if period_rows:
            session.execute(feature_opening_periods.insert(), period_rows)
        special_rows = [
            special_opening_day_to_row(feature_id, special_day)
            for special_day in hours.special_days
        ]
        if special_rows:
            session.execute(feature_special_days.insert(), special_rows)
        opening_period_count += len(period_rows)
        special_day_count += len(special_rows)

    for point in price_point_rows:
        _upsert_row(
            session,
            price_points,
            {"feature_id": point.feature_id},
            price_point_to_row(point),
        )

    for value in price_value_rows:
        _upsert_row(
            session,
            price_values,
            {
                "feature_id": value.feature_id,
                "item_key": value.item_key,
                "observed_at": value.observed_at,
            },
            price_value_to_row(value),
        )

    for value in weather_value_rows:
        row = weather_value_to_row(value)
        _upsert_row(
            session,
            feature_weather_values,
            {"weather_value_key": row["weather_value_key"]},
            row,
        )

    for source_link in source_link_rows:
        _upsert_row(
            session,
            source_links,
            {
                "feature_id": source_link.feature_id,
                "source_record_key": source_link.source_record_key,
            },
            source_link_to_row(source_link),
        )

    for state in provider_sync_state_rows:
        _upsert_row(
            session,
            provider_sync_state,
            {
                "provider": state.provider,
                "dataset_key": state.dataset_key,
                "sync_scope": state.sync_scope,
            },
            provider_sync_state_to_row(state),
        )

    return FeatureDbLoadResult(
        features=len(feature_rows),
        source_records=len(source_record_rows),
        source_links=len(source_link_rows),
        place_details=len(place_detail_rows),
        event_details=len(event_detail_rows),
        area_details=len(area_detail_rows),
        route_details=len(route_detail_rows),
        notice_details=len(notice_detail_rows),
        opening_periods=opening_period_count,
        special_days=special_day_count,
        weather_values=len(weather_value_rows),
        price_points=len(price_point_rows),
        price_values=len(price_value_rows),
        feature_files=len(feature_file_rows),
        provider_sync_states=len(provider_sync_state_rows),
    )


def _upsert_row(
    session: Session,
    table: Table,
    key_values: Mapping[str, Any],
    values: Mapping[str, Any],
) -> None:
    condition = and_(*(table.c[column_name] == value for column_name, value in key_values.items()))
    result = session.execute(table.update().where(condition).values(dict(values)))
    if result.rowcount == 0:
        session.execute(table.insert().values(dict(values)))


def feature_to_row(feature: Feature) -> dict[str, Any]:
    """Convert a `Feature` DTO into a `features` row payload."""

    coord = feature.coord
    address_values = feature.address.to_orm_dict()
    return {
        "feature_id": feature.feature_id,
        "kind": str(feature.kind),
        "name": feature.name,
        "category": feature.category,
        "longitude": coord.longitude if coord is not None else None,
        "latitude": coord.latitude if coord is not None else None,
        "geom": None,
        "address": feature.address.model_dump(mode="json"),
        "legal_dong_code": address_values.get("legal_dong_code"),
        "road_name_code": address_values.get("road_name_code"),
        "road_address_management_no": address_values.get("road_name_address_code"),
        "admin_dong_code": getattr(feature.address, "admin_dong_code", None),
        "sido_code": address_values.get("sido_code"),
        "sigungu_code": address_values.get("sigungu_code"),
        "urls": feature.urls.model_dump(mode="json"),
        "marker_icon": feature.marker_icon,
        "marker_color": feature.marker_color,
        "parent_feature_id": feature.parent_feature_id,
        "sibling_group_id": feature.sibling_group_id,
        "detail": dict(feature.detail or {}),
        "raw_refs": [ref.model_dump(mode="json") for ref in feature.raw_refs],
        "status": str(feature.status),
        "created_at": feature.created_at,
        "updated_at": feature.updated_at,
        "deleted_at": feature.deleted_at,
    }


def feature_from_row(row: Mapping[str, Any]) -> Feature:
    """Convert a `features` row mapping into a `Feature` DTO."""

    longitude = row.get("longitude")
    latitude = row.get("latitude")
    coord = None
    if longitude is not None and latitude is not None:
        coord = Coordinate(lat=latitude, lon=longitude)

    return Feature(
        feature_id=str(row["feature_id"]),
        kind=str(row["kind"]),
        name=str(row["name"]),
        coord=coord,
        address=row.get("address") or {},
        category=str(row["category"]),
        urls=row.get("urls") or {},
        marker_icon=str(row["marker_icon"]),
        marker_color=str(row["marker_color"]),
        parent_feature_id=row.get("parent_feature_id"),
        sibling_group_id=row.get("sibling_group_id"),
        detail=dict(row.get("detail") or {}),
        raw_refs=list(row.get("raw_refs") or []),
        status=str(row["status"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        deleted_at=row.get("deleted_at"),
    )


def source_record_to_row(source_record: SourceRecord) -> dict[str, Any]:
    """Convert a `SourceRecord` DTO into a `source_records` row payload."""

    return {
        "source_record_key": source_record.key(),
        "provider": source_record.provider,
        "dataset_key": source_record.dataset_key,
        "source_entity_type": source_record.source_entity_type,
        "source_entity_id": source_record.source_entity_id,
        "source_version": source_record.source_version,
        "raw_name": source_record.raw_name,
        "raw_address": source_record.raw_address,
        "raw_longitude": source_record.raw_longitude,
        "raw_latitude": source_record.raw_latitude,
        "raw_data": dict(source_record.raw_data or {}),
        "raw_payload_hash": source_record.raw_payload_hash,
        "fetched_at": source_record.fetched_at or source_record.imported_at,
        "imported_at": source_record.imported_at,
        "expires_at": source_record.expires_at,
    }


def source_record_from_row(row: Mapping[str, Any]) -> SourceRecord:
    """Convert a `source_records` row mapping into a `SourceRecord` DTO."""

    return SourceRecord(
        provider=str(row["provider"]),
        dataset_key=str(row["dataset_key"]),
        source_entity_type=str(row["source_entity_type"]),
        source_entity_id=str(row["source_entity_id"]),
        source_version=row.get("source_version"),
        raw_name=row.get("raw_name"),
        raw_address=row.get("raw_address"),
        raw_longitude=row.get("raw_longitude"),
        raw_latitude=row.get("raw_latitude"),
        raw_data=dict(row.get("raw_data") or {}),
        raw_payload_hash=str(row["raw_payload_hash"]),
        fetched_at=row.get("fetched_at"),
        imported_at=row["imported_at"],
        expires_at=row.get("expires_at"),
        source_record_key=str(row["source_record_key"]),
    )


def source_link_to_row(source_link: SourceLink) -> dict[str, Any]:
    """Convert a `SourceLink` DTO into a `source_links` row payload."""

    return {
        "feature_id": source_link.feature_id,
        "source_record_key": source_link.source_record_key,
        "source_role": str(source_link.source_role),
        "match_method": source_link.match_method,
        "confidence": source_link.confidence,
        "is_primary_source": source_link.is_primary_source,
        "created_at": source_link.created_at,
    }


def source_link_from_row(row: Mapping[str, Any]) -> SourceLink:
    """Convert a `source_links` row mapping into a `SourceLink` DTO."""

    return SourceLink(
        feature_id=str(row["feature_id"]),
        source_record_key=str(row["source_record_key"]),
        source_role=str(row["source_role"]),
        match_method=str(row["match_method"]),
        confidence=int(row["confidence"]),
        is_primary_source=bool(row["is_primary_source"]),
        created_at=row["created_at"],
    )


def feature_file_to_row(feature_file: FeatureFile) -> dict[str, Any]:
    """Convert a `FeatureFile` DTO into a `feature_files` row payload."""

    return {
        "file_id": feature_file.file_id,
        "feature_id": feature_file.feature_id,
        "file_type": feature_file.file_type,
        "storage_backend": feature_file.storage_backend,
        "bucket": feature_file.bucket,
        "object_key": feature_file.object_key,
        "source_url": feature_file.source_url,
        "public_url": feature_file.public_url,
        "content_type": feature_file.content_type,
        "byte_size": feature_file.byte_size,
        "checksum_sha256": feature_file.checksum_sha256,
        "width": feature_file.width,
        "height": feature_file.height,
        "role": feature_file.role,
        "display_order": feature_file.display_order,
        "alt_text": feature_file.alt_text,
        "provider": feature_file.provider,
        "dataset_key": feature_file.dataset_key,
        "source_record_key": feature_file.source_record_key,
        "payload": dict(feature_file.payload),
        "created_at": feature_file.created_at,
        "updated_at": feature_file.updated_at,
    }


def feature_file_from_row(row: Mapping[str, Any]) -> FeatureFile:
    """Convert a `feature_files` row mapping into a `FeatureFile` DTO."""

    return FeatureFile(
        file_id=str(row["file_id"]),
        feature_id=str(row["feature_id"]),
        file_type=str(row["file_type"]),
        storage_backend=str(row["storage_backend"]),
        bucket=str(row["bucket"]),
        object_key=str(row["object_key"]),
        source_url=row.get("source_url"),
        public_url=row.get("public_url"),
        content_type=row.get("content_type"),
        byte_size=row.get("byte_size"),
        checksum_sha256=row.get("checksum_sha256"),
        width=row.get("width"),
        height=row.get("height"),
        role=str(row.get("role") or "gallery"),
        display_order=int(row.get("display_order") or 0),
        alt_text=row.get("alt_text"),
        provider=row.get("provider"),
        dataset_key=row.get("dataset_key"),
        source_record_key=row.get("source_record_key"),
        payload=dict(row.get("payload") or {}),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def place_detail_to_row(detail: PlaceDetail) -> dict[str, Any]:
    """Convert a `PlaceDetail` DTO into a `feature_place_details` row payload."""

    return {
        "feature_id": detail.feature_id,
        "place_kind": detail.place_kind,
        "phones": list(detail.phones),
        "reviews_link": dict(detail.reviews_link),
        "business_hours": (
            _opening_hours_payload(detail.business_hours)
            if detail.business_hours is not None
            else None
        ),
        "facility_info": dict(detail.facility_info),
        "license_date": detail.license_date,
        "biz_number": detail.biz_number,
        "payload": dict(detail.payload),
    }


def place_detail_from_row(row: Mapping[str, Any]) -> PlaceDetail:
    """Convert a `feature_place_details` row mapping into a `PlaceDetail` DTO."""

    business_hours = row.get("business_hours")
    return PlaceDetail(
        feature_id=str(row["feature_id"]),
        place_kind=str(row.get("place_kind") or "place"),
        phones=list(row.get("phones") or []),
        reviews_link=dict(row.get("reviews_link") or {}),
        business_hours=(
            FeatureOpeningHours.model_validate(business_hours)
            if business_hours is not None
            else None
        ),
        facility_info=dict(row.get("facility_info") or {}),
        license_date=row.get("license_date"),
        biz_number=row.get("biz_number"),
        payload=dict(row.get("payload") or {}),
    )


def event_detail_to_row(detail: EventDetail) -> dict[str, Any]:
    """Convert an `EventDetail` DTO into a `feature_event_details` row payload."""

    payload = dict(detail.payload)
    if detail.opening_hours is not None:
        payload["opening_hours"] = _opening_hours_payload(detail.opening_hours)

    return {
        "feature_id": detail.feature_id,
        "event_kind": detail.event_kind,
        "starts_on": detail.starts_on,
        "ends_on": detail.ends_on,
        "timezone": detail.timezone,
        "venue_name": detail.venue_name,
        "tel": detail.tel,
        "content_id": detail.content_id,
        "content_type_id": detail.content_type_id,
        "area_code": detail.area_code,
        "sigungu_code": detail.sigungu_code,
        "payload": payload,
    }


def event_detail_from_row(row: Mapping[str, Any]) -> EventDetail:
    """Convert a `feature_event_details` row mapping into an `EventDetail` DTO."""

    payload = dict(row.get("payload") or {})
    opening_hours_data = payload.pop("opening_hours", None)
    return EventDetail(
        feature_id=str(row["feature_id"]),
        event_kind=str(row["event_kind"]),
        starts_on=row.get("starts_on"),
        ends_on=row.get("ends_on"),
        timezone=str(row.get("timezone") or "Asia/Seoul"),
        opening_hours=(
            FeatureOpeningHours.model_validate(opening_hours_data)
            if opening_hours_data is not None
            else None
        ),
        venue_name=row.get("venue_name"),
        tel=row.get("tel"),
        content_id=row.get("content_id"),
        content_type_id=row.get("content_type_id"),
        area_code=row.get("area_code"),
        sigungu_code=row.get("sigungu_code"),
        payload=payload,
    )


def area_detail_to_row(detail: AreaDetail) -> dict[str, Any]:
    """Convert an `AreaDetail` DTO into a `feature_area_details` row payload."""

    return {
        "feature_id": detail.feature_id,
        "area_kind": detail.area_kind,
        "boundary_source": detail.boundary_source,
        "area_square_meters": detail.area_square_meters,
        "regulation_scope": detail.regulation_scope,
        "administrative_office": detail.administrative_office,
        "description": detail.description,
        "geometry": detail.geometry,
        "payload": dict(detail.payload),
    }


def area_detail_from_row(row: Mapping[str, Any]) -> AreaDetail:
    """Convert a `feature_area_details` row mapping into an `AreaDetail` DTO."""

    return AreaDetail(
        feature_id=str(row["feature_id"]),
        area_kind=str(row.get("area_kind") or "area"),
        boundary_source=row.get("boundary_source"),
        area_square_meters=row.get("area_square_meters"),
        regulation_scope=row.get("regulation_scope"),
        administrative_office=row.get("administrative_office"),
        description=row.get("description"),
        geometry=dict(row["geometry"]) if row.get("geometry") is not None else None,
        payload=dict(row.get("payload") or {}),
    )


def route_detail_to_row(detail: RouteDetail) -> dict[str, Any]:
    """Convert a `RouteDetail` DTO into a `feature_route_details` row payload."""

    return {
        "feature_id": detail.feature_id,
        "route_type": detail.route_type,
        "geometry_source": detail.geometry_source,
        "geometry_status": detail.geometry_status,
        "total_distance_meters": detail.total_distance_meters,
        "expected_duration_minutes": detail.expected_duration_minutes,
        "difficulty": detail.difficulty,
        "begin_name": detail.begin_name,
        "begin_address": detail.begin_address,
        "end_name": detail.end_name,
        "end_address": detail.end_address,
        "geometry": detail.geometry,
        "payload": dict(detail.payload),
    }


def route_detail_from_row(row: Mapping[str, Any]) -> RouteDetail:
    """Convert a `feature_route_details` row mapping into a `RouteDetail` DTO."""

    return RouteDetail(
        feature_id=str(row["feature_id"]),
        route_type=str(row.get("route_type") or row.get("route_kind") or "route"),
        geometry_source=row.get("geometry_source"),
        geometry_status=row.get("geometry_status"),
        total_distance_meters=row.get("total_distance_meters"),
        expected_duration_minutes=row.get("expected_duration_minutes"),
        difficulty=row.get("difficulty"),
        begin_name=row.get("begin_name"),
        begin_address=row.get("begin_address"),
        end_name=row.get("end_name"),
        end_address=row.get("end_address"),
        geometry=dict(row["geometry"]) if row.get("geometry") is not None else None,
        payload=dict(row.get("payload") or {}),
    )


def notice_detail_to_row(detail: NoticeDetail) -> dict[str, Any]:
    """Convert a `NoticeDetail` DTO into a `feature_notice_details` row payload."""

    return {
        "feature_id": detail.feature_id,
        "notice_type": detail.notice_type,
        "severity": detail.severity,
        "valid_start_time": detail.valid_start_time,
        "valid_end_time": detail.valid_end_time,
        "source_agency": detail.source_agency,
        "officer_name": detail.officer_name,
        "payload": dict(detail.payload),
    }


def notice_detail_from_row(row: Mapping[str, Any]) -> NoticeDetail:
    """Convert a `feature_notice_details` row mapping into a `NoticeDetail` DTO."""

    return NoticeDetail(
        feature_id=str(row["feature_id"]),
        notice_type=str(row["notice_type"]),
        severity=row.get("severity"),
        valid_start_time=row.get("valid_start_time"),
        valid_end_time=row.get("valid_end_time"),
        source_agency=row.get("source_agency"),
        officer_name=row.get("officer_name"),
        payload=dict(row.get("payload") or {}),
    )


def opening_period_to_row(
    feature_id: str,
    period: OpeningPeriod,
    *,
    period_index: int,
    timezone: str = "Asia/Seoul",
) -> dict[str, Any]:
    """Convert an `OpeningPeriod` into a `feature_opening_periods` row payload."""

    return {
        "feature_id": feature_id,
        "period_index": period_index,
        "start_weekday": period.open.day,
        "start_time": period.open.time,
        "duration_minutes": period.duration_minutes,
        "timezone": timezone,
        "payload": _opening_period_payload(period),
    }


def opening_period_from_row(row: Mapping[str, Any]) -> OpeningPeriod:
    """Convert a `feature_opening_periods` row mapping into an `OpeningPeriod` DTO."""

    payload = dict(row.get("payload") or {})
    if payload.get("open"):
        return OpeningPeriod.model_validate(payload)

    start = OpeningTime(day=int(row["start_weekday"]), time=str(row["start_time"]))
    duration = int(row["duration_minutes"])
    if duration == 7 * 24 * 60 and start.day == 0 and start.time == "0000":
        return OpeningPeriod(open=start)

    end_minute = (_minute_of_week(start.day, start.time) + duration) % (7 * 24 * 60)
    return OpeningPeriod(open=start, close=_opening_time_from_minute(end_minute))


def opening_hours_to_period_rows(
    feature_id: str,
    hours: FeatureOpeningHours,
) -> list[dict[str, Any]]:
    """Convert opening-hours periods into ordered DB row payloads."""

    return [
        opening_period_to_row(
            feature_id,
            period,
            period_index=index,
            timezone=hours.timezone,
        )
        for index, period in enumerate(hours.periods)
    ]


def special_opening_day_to_row(
    feature_id: str,
    special_day: SpecialOpeningDay,
) -> dict[str, Any]:
    """Convert a `SpecialOpeningDay` into a `feature_special_days` row payload."""

    periods = None
    if special_day.periods is not None:
        periods = [_opening_period_payload(period) for period in special_day.periods]

    return {
        "feature_id": feature_id,
        "special_date": special_day.date,
        "is_closed": special_day.is_closed,
        "periods": periods,
        "payload": {
            "exceptional_hours": special_day.exceptional_hours,
        },
    }


def special_opening_day_from_row(row: Mapping[str, Any]) -> SpecialOpeningDay:
    """Convert a `feature_special_days` row mapping into a `SpecialOpeningDay` DTO."""

    periods_data = row.get("periods")
    periods = None
    if periods_data is not None:
        periods = [OpeningPeriod.model_validate(period) for period in periods_data]
    payload = dict(row.get("payload") or {})
    return SpecialOpeningDay(
        date=row["special_date"],
        is_closed=bool(row["is_closed"]),
        periods=periods,
        exceptional_hours=bool(payload.get("exceptional_hours", True)),
    )


def _opening_period_payload(period: OpeningPeriod) -> dict[str, Any]:
    return {
        "open": {"day": period.open.day, "time": period.open.time},
        "close": (
            {"day": period.close.day, "time": period.close.time}
            if period.close is not None
            else None
        ),
    }


def _opening_hours_payload(hours: FeatureOpeningHours) -> dict[str, Any]:
    return {
        "timezone": hours.timezone,
        "open_now": hours.open_now,
        "periods": [_opening_period_payload(period) for period in hours.periods],
        "special_days": [
            {
                "date": special_day.date.isoformat(),
                "is_closed": special_day.is_closed,
                "periods": (
                    [_opening_period_payload(period) for period in special_day.periods]
                    if special_day.periods is not None
                    else None
                ),
                "exceptional_hours": special_day.exceptional_hours,
            }
            for special_day in hours.special_days
        ],
        "weekday_text": list(hours.weekday_text),
    }


def _minute_of_week(day: int, time_value: str) -> int:
    return day * 24 * 60 + _hhmm_to_minutes(time_value)


def _hhmm_to_minutes(time_value: str) -> int:
    return int(time_value[:2]) * 60 + int(time_value[2:])


def _opening_time_from_minute(minute_of_week: int) -> OpeningTime:
    day, minute_of_day = divmod(minute_of_week, 24 * 60)
    hour, minute = divmod(minute_of_day, 60)
    return OpeningTime(day=day, time=f"{hour:02d}{minute:02d}")


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
        "metadata_hash": state.metadata_hash,
        "last_observed_source_version": state.last_observed_source_version,
        "last_success_at": state.last_success_at,
        "last_attempt_at": state.last_attempt_at,
        "last_full_scan_at": state.last_full_scan_at,
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
        metadata_hash=row.get("metadata_hash"),
        last_observed_source_version=row.get("last_observed_source_version"),
        last_success_at=row.get("last_success_at"),
        last_attempt_at=row.get("last_attempt_at"),
        last_full_scan_at=row.get("last_full_scan_at"),
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
