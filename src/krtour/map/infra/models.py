"""``krtour.map.infra.models`` — SQLAlchemy 2 declarative + GeoAlchemy2 매핑.

**매핑만**. 비즈니스 로직 / 쿼리 메서드 금지 — 쿼리는 ``infra/*_repo.py``의
raw SQL ``text()`` (ADR-004). 본 모듈은 Alembic ``target_metadata``의 원천이며
ORM 인스턴스 read mapping 용도로도 사용 가능.

PR#28 (Sprint 2 prep) scope:
- ``features`` — 기준 테이블 (ADR-012 ``coord_5179`` STORED generated column)
- ``source_records`` / ``source_links`` / ``provider_sync_state`` —
  provider 적재 추적
- 4 schemas (feature / provider_sync / ops / x_extension)

후속 PR에서 추가될 테이블:
- detail 5종 (place/event/notice/area/route)
- ``feature_opening_periods`` / ``feature_special_days``
- ``feature_weather_values`` / ``price_points`` / ``price_values``
- ``feature_files``
- ``ops.*`` (import_jobs / dedup_review_queue / ...)

ADR 참조
--------
- ADR-004 — ORM 매핑만, 쿼리는 raw SQL (``infra/*_repo.py``)
- ADR-007 — PostgreSQL 16 + PostGIS 3.5 + pg_trgm + pgcrypto
- ADR-008 — extension은 ``x_extension`` schema 격리
- ADR-012 — ``coord_5179`` STORED generated column (반경 검색 인덱스)
- ADR-018 — Feature.detail JSONB (Pydantic 직렬화)
- ADR-019 — 모든 datetime ``TIMESTAMPTZ`` (KST aware)
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from geoalchemy2 import Geometry
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Computed,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from krtour.map.core.offline_upload_states import OFFLINE_UPLOAD_STATE_VALUES

__all__ = [
    "metadata",
    "Base",
    "FeatureRow",
    "FeatureVersionRow",
    "SourceRecordRow",
    "SourceLinkRow",
    "CuratedThemeRow",
    "CuratedSourceRow",
    "CuratedSourceRuleRow",
    "CuratedFeatureRow",
    "ProviderSyncStateRow",
    "FeatureConsistencyReportRow",
    "DedupReviewQueueRow",
    "EnrichmentReviewQueueRow",
    "ImportJobRow",
    "ImportJobEventRow",
    "OfflineUploadRow",
    "FeatureOverrideRow",
    "FeatureChangeRequestRow",
    "FeatureUpdateRequestRow",
    "DataIntegrityViolationRow",
    "PoiCacheTargetRow",
    "PoiCacheTargetFeatureLinkRow",
    "ProviderRefreshPolicyRow",
    "FeatureMergeHistoryRow",
]


# Naming convention — Alembic autogenerate 안정성 + DB 가시성.
_NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


def _sql_text_literals(values: tuple[str, ...]) -> str:
    """SQLAlchemy ``CheckConstraint`` 문자열용 quoted literal 목록."""

    return ",".join(f"'{value}'" for value in values)


class Base(DeclarativeBase):
    """SQLAlchemy 2 declarative base. 모든 row class 상속."""

    metadata = MetaData(naming_convention=_NAMING_CONVENTION)


metadata: MetaData = Base.metadata
"""Alembic ``target_metadata``의 원천."""


# =============================================================================
# feature.features  (docs/data-model.md §1)
# =============================================================================


class FeatureRow(Base):
    """``feature.features`` row mapping (ADR-012 ``coord_5179`` generated).

    raw SQL 쿼리는 ``infra/feature_repo.py``의 ``_SQL`` 상수에서 (ADR-004).
    본 클래스는 ORM read mapping + Alembic autogenerate 원천.
    """

    __tablename__ = "features"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('place','event','notice','price','weather','route','area')",
            name="features_kind",
        ),
        CheckConstraint(
            "status IN ('draft','active','inactive','hidden','broken','deleted')",
            name="features_status",
        ),
        CheckConstraint(
            "data_origin IN ('provider','user_request')",
            name="ck_features_data_origin",
        ),
        CheckConstraint("data_version >= 0", name="ck_features_data_version"),
        CheckConstraint(
            "user_change_kind IS NULL OR user_change_kind IN ('add','update','delete')",
            name="ck_features_user_change_kind",
        ),
        CheckConstraint(
            "user_change_status IS NULL OR user_change_status IN "
            "('pending','applied','rejected')",
            name="ck_features_user_change_status",
        ),
        CheckConstraint(
            "coord IS NULL OR ("
            "ST_X(coord) BETWEEN 124.0 AND 132.0 AND "
            "ST_Y(coord) BETWEEN 33.0 AND 39.5)",
            name="features_coord_pair",
        ),
        CheckConstraint(
            "("
            "coord IS NULL AND coord_precision_digits IS NULL"
            ") OR ("
            "coord IS NOT NULL AND coord_precision_digits BETWEEN 3 AND 8"
            ")",
            name="coord_precision",
        ),
        Index("idx_features_coord_gist", "coord", postgresql_using="gist",
              postgresql_where=text("deleted_at IS NULL")),
        Index("idx_features_coord_5179_gist", "coord_5179",
              postgresql_using="gist",
              postgresql_where=text("deleted_at IS NULL")),
        Index("idx_features_geom_gist", "geom", postgresql_using="gist",
              postgresql_where=text("deleted_at IS NULL AND geom IS NOT NULL")),
        Index("idx_features_kind_category", "kind", "category",
              postgresql_where=text("deleted_at IS NULL")),
        Index(
            "idx_features_updated_keyset",
            text("updated_at DESC"),
            text("feature_id DESC"),
        ),
        Index(
            "idx_features_status_updated",
            "status",
            text("updated_at DESC"),
            text("feature_id DESC"),
        ),
        Index("idx_features_lower_name_keyset", text("lower(name)"), "feature_id"),
        Index(
            "idx_features_opening_hours_keyset",
            "feature_id",
            postgresql_where=text(
                "deleted_at IS NULL "
                "AND detail IS NOT NULL "
                "AND detail <> '{}'::jsonb "
                "AND detail ?| ARRAY['business_hours','opening_hours']"
            ),
        ),
        Index("idx_features_legal_dong_code", "legal_dong_code"),
        Index("idx_features_sigungu", "sigungu_code", "kind",
              postgresql_where=text("deleted_at IS NULL")),
        Index("idx_features_parent", "parent_feature_id",
              postgresql_where=text("parent_feature_id IS NOT NULL")),
        Index("idx_features_sibling", "sibling_group_id",
              postgresql_where=text("sibling_group_id IS NOT NULL")),
        Index("idx_features_name_trgm", "name", postgresql_using="gin",
              postgresql_ops={"name": "x_extension.gin_trgm_ops"}),
        Index("idx_features_data_origin", "data_origin", "data_version"),
        Index(
            "idx_features_user_deleted",
            "user_deleted_at",
            postgresql_where=text("user_deleted_at IS NOT NULL"),
        ),
        {"schema": "feature"},
    )

    feature_id: Mapped[str] = mapped_column(String, primary_key=True)
    kind: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    category: Mapped[str] = mapped_column(String, nullable=False)

    # 좌표 (ADR-012 — 양 좌표계 보유, coord_5179는 STORED generated).
    coord: Mapped[Any | None] = mapped_column(Geometry("POINT", srid=4326))
    coord_precision_digits: Mapped[int | None] = mapped_column(SmallInteger)
    coord_5179: Mapped[Any | None] = mapped_column(
        Geometry("POINT", srid=5179),
        Computed(
            "CASE WHEN coord IS NULL THEN NULL "
            "ELSE ST_Transform(coord, 5179) END",
            persisted=True,
        ),
    )
    geom: Mapped[Any | None] = mapped_column(Geometry("GEOMETRY", srid=4326))

    # 주소 (krtour.map.dto.Address 직렬화, ADR-041 — kraddr-base 흡수).
    address: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb"),
    )
    legal_dong_code: Mapped[str | None] = mapped_column(String(10))
    road_name_code: Mapped[str | None] = mapped_column(String)
    road_address_management_no: Mapped[str | None] = mapped_column(String)
    admin_dong_code: Mapped[str | None] = mapped_column(String(10))
    sido_code: Mapped[str | None] = mapped_column(String(2))
    sigungu_code: Mapped[str | None] = mapped_column(String(5))

    # 표시.
    urls: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb"),
    )
    marker_icon: Mapped[str | None] = mapped_column(String)
    marker_color: Mapped[str | None] = mapped_column(String)

    # 관계.
    parent_feature_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("feature.features.feature_id", ondelete="SET NULL"),
    )
    sibling_group_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False))

    # 상세 (ADR-018 — Pydantic DETAIL_MODELS 직렬화).
    detail: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb"),
    )
    raw_refs: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb"),
    )
    status: Mapped[str] = mapped_column(
        String, nullable=False, server_default=text("'active'"),
    )
    data_origin: Mapped[str] = mapped_column(
        String, nullable=False, server_default=text("'provider'"),
    )
    data_version: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0"),
    )
    user_change_kind: Mapped[str | None] = mapped_column(String)
    user_change_status: Mapped[str | None] = mapped_column(String)
    user_change_request_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False))
    user_deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    user_deleted_by: Mapped[str | None] = mapped_column(String)
    user_change_reason: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()"),
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class FeatureVersionRow(Base):
    """``feature.feature_versions`` row mapping.

    provider 적재 snapshot은 version 0, 사용자/admin 요청으로 적용된 effective
    snapshot은 version 1에 저장한다. ``feature.features``는 조회용 effective row다.
    """

    __tablename__ = "feature_versions"
    __table_args__ = (
        CheckConstraint("version >= 0", name="ck_feature_versions_version"),
        CheckConstraint(
            "origin IN ('provider','user_request')",
            name="ck_feature_versions_origin",
        ),
        CheckConstraint(
            "change_kind IN ('load','add','update','delete')",
            name="ck_feature_versions_change_kind",
        ),
        Index("idx_feature_versions_request", "request_id"),
        {"schema": "feature"},
    )

    feature_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("feature.features.feature_id", ondelete="CASCADE"),
        primary_key=True,
    )
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    origin: Mapped[str] = mapped_column(String, nullable=False)
    change_kind: Mapped[str] = mapped_column(String, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb"),
    )
    request_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False))
    created_by: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()"),
    )


# =============================================================================
# provider_sync.source_records  (docs/data-model.md §2)
# =============================================================================


class SourceRecordRow(Base):
    """``provider_sync.source_records`` row mapping.

    고유성: ``(provider, dataset_key, source_entity_type, source_entity_id,
    raw_payload_hash)`` (UNIQUE 제약). PK는 ``source_record_key``
    (``make_source_record_key(...)`` 결과).
    """

    __tablename__ = "source_records"
    __table_args__ = (
        UniqueConstraint(
            "provider", "dataset_key", "source_entity_type",
            "source_entity_id", "raw_payload_hash",
            name="source_records",
        ),
        Index(
            "idx_source_records_provider_dataset_entity",
            "provider", "dataset_key", "source_entity_type", "source_entity_id",
        ),
        Index(
            "idx_source_records_imported_at_brin", "imported_at",
            postgresql_using="brin",
        ),
        Index(
            "idx_source_records_fetched_at_brin", "fetched_at",
            postgresql_using="brin",
        ),
        Index(
            "idx_source_records_expires_at", "expires_at",
            postgresql_where=text("expires_at IS NOT NULL"),
        ),
        {"schema": "provider_sync"},
    )

    source_record_key: Mapped[str] = mapped_column(String, primary_key=True)
    provider: Mapped[str] = mapped_column(String, nullable=False)
    dataset_key: Mapped[str] = mapped_column(String, nullable=False)
    source_entity_type: Mapped[str] = mapped_column(String, nullable=False)
    source_entity_id: Mapped[str] = mapped_column(String, nullable=False)
    source_version: Mapped[str | None] = mapped_column(String)
    raw_name: Mapped[str | None] = mapped_column(String)
    raw_address: Mapped[str | None] = mapped_column(String)
    raw_longitude: Mapped[Any | None] = mapped_column(Numeric(12, 8))
    raw_latitude: Mapped[Any | None] = mapped_column(Numeric(12, 8))
    raw_data: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb"),
    )
    raw_payload_hash: Mapped[str] = mapped_column(String, nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
    )
    imported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()"),
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# =============================================================================
# provider_sync.source_links  (docs/data-model.md §3)
# =============================================================================


class SourceLinkRow(Base):
    """``provider_sync.source_links`` row mapping — Feature ↔ SourceRecord N:M.

    PK = ``(feature_id, source_record_key)``. ``is_primary_source=True``는
    Feature당 최대 1건 (partial UNIQUE).
    """

    __tablename__ = "source_links"
    __table_args__ = (
        CheckConstraint(
            "source_role IN ('primary','base_address','base_coordinate',"
            "'enrichment','correction','duplicate_candidate','media',"
            "'weather_context')",
            name="source_links_role",
        ),
        CheckConstraint(
            "confidence BETWEEN 0 AND 100",
            name="source_links_confidence",
        ),
        Index(
            "idx_source_links_record", "source_record_key",
        ),
        Index(
            "idx_source_links_role", "source_role",
        ),
        Index(
            "idx_source_links_primary", "feature_id",
            postgresql_where=text("is_primary_source"),
        ),
        {"schema": "provider_sync"},
    )

    feature_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("feature.features.feature_id", ondelete="CASCADE"),
        primary_key=True,
    )
    source_record_key: Mapped[str] = mapped_column(
        String,
        ForeignKey(
            "provider_sync.source_records.source_record_key",
            ondelete="RESTRICT",
        ),
        primary_key=True,
    )
    source_role: Mapped[str] = mapped_column(
        String, nullable=False, server_default=text("'enrichment'"),
    )
    match_method: Mapped[str] = mapped_column(String, nullable=False)
    confidence: Mapped[int] = mapped_column(Integer, nullable=False)
    is_primary_source: Mapped[bool] = mapped_column(
        nullable=False, server_default=text("false"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()"),
    )


# =============================================================================
# feature.curated_*  (docs/curated-features.md, T-223c-1)
# =============================================================================


class CuratedThemeRow(Base):
    """``feature.curated_themes`` row mapping — 테마 metadata."""

    __tablename__ = "curated_themes"
    __table_args__ = (
        CheckConstraint(
            "visibility IN ('admin_only','public','tripmate')",
            name="ck_curated_themes_visibility",
        ),
        Index(
            "idx_curated_themes_group_visibility",
            "theme_group",
            "visibility",
            "theme_slug",
        ),
        {"schema": "feature"},
    )

    theme_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        server_default=text("x_extension.gen_random_uuid()"),
    )
    theme_slug: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    theme_name: Mapped[str] = mapped_column(Text, nullable=False)
    theme_description: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("''"),
    )
    theme_group: Mapped[str] = mapped_column(Text, nullable=False)
    default_curated: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false"),
    )
    visibility: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'admin_only'"),
    )
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()"),
    )


class CuratedSourceRow(Base):
    """``feature.curated_sources`` row mapping — provider source metadata."""

    __tablename__ = "curated_sources"
    __table_args__ = (
        UniqueConstraint(
            "provider",
            "dataset_key",
            name="uq_curated_sources_provider_dataset",
        ),
        CheckConstraint(
            "source_kind IN ('openapi','filedata','standard','internal','manual')",
            name="ck_curated_sources_source_kind",
        ),
        CheckConstraint(
            "update_cycle IN ("
            "'realtime','daily','weekly','monthly','annual','one_time','unknown'"
            ")",
            name="ck_curated_sources_update_cycle",
        ),
        CheckConstraint(
            "provider_status IN ("
            "'implemented','provider_needed','manual_only','deprecated'"
            ")",
            name="ck_curated_sources_provider_status",
        ),
        CheckConstraint(
            "row_count IS NULL OR row_count >= 0",
            name="ck_curated_sources_row_count",
        ),
        Index("idx_curated_sources_provider", "provider", "dataset_key"),
        Index(
            "idx_curated_sources_status",
            "provider_status",
            text("updated_at DESC"),
            text("source_id DESC"),
        ),
        {"schema": "feature"},
    )

    source_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        server_default=text("x_extension.gen_random_uuid()"),
    )
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    dataset_key: Mapped[str] = mapped_column(Text, nullable=False)
    source_name: Mapped[str] = mapped_column(Text, nullable=False)
    source_url: Mapped[str | None] = mapped_column(Text)
    source_kind: Mapped[str] = mapped_column(Text, nullable=False)
    license: Mapped[str | None] = mapped_column(Text)
    update_cycle: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'unknown'"),
    )
    last_source_modified_at: Mapped[Any | None] = mapped_column(Date)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_expected_at: Mapped[Any | None] = mapped_column(Date)
    row_count: Mapped[int | None] = mapped_column(Integer)
    freshness_note: Mapped[str | None] = mapped_column(Text)
    provider_status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'implemented'"),
    )
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()"),
    )


class CuratedSourceRuleRow(Base):
    """``feature.curated_source_rules`` row mapping — source 후보화 rule."""

    __tablename__ = "curated_source_rules"
    __table_args__ = (
        CheckConstraint(
            "default_action IN ('candidate','curated','ignore')",
            name="ck_curated_source_rules_action",
        ),
        CheckConstraint(
            "jsonb_typeof(region_scope) = 'object'",
            name="ck_curated_source_rules_region_scope",
        ),
        Index(
            "idx_curated_source_rules_enabled",
            "enabled",
            "source_id",
            text("priority DESC"),
        ),
        Index(
            "idx_curated_source_rules_theme",
            "theme_id",
            "enabled",
            text("priority DESC"),
        ),
        {"schema": "feature"},
    )

    rule_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        server_default=text("x_extension.gen_random_uuid()"),
    )
    theme_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("feature.curated_themes.theme_id", ondelete="CASCADE"),
        nullable=False,
    )
    source_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("feature.curated_sources.source_id", ondelete="CASCADE"),
        nullable=False,
    )
    dataset_key: Mapped[str] = mapped_column(Text, nullable=False)
    place_kind: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(Text)
    region_scope: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb"),
    )
    default_action: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'candidate'"),
    )
    priority: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0"),
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true"),
    )
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()"),
    )


class CuratedFeatureRow(Base):
    """``feature.curated_features`` row mapping — feature overlay 본체."""

    __tablename__ = "curated_features"
    __table_args__ = (
        CheckConstraint(
            "curation_status IN ('candidate','curated','rejected','archived')",
            name="ck_curated_features_status",
        ),
        CheckConstraint(
            "selection_origin IN ('source_rule','admin','external_api')",
            name="ck_curated_features_selection_origin",
        ),
        CheckConstraint(
            "tripmate_relation IN ("
            "'primary_stop','food_stop','cafe_stop','bookstore_stop',"
            "'nearby_option','accessibility_support','pet_support',"
            "'family_support','theme_area_anchor'"
            ")",
            name="ck_curated_features_tripmate_relation",
        ),
        CheckConstraint(
            "tripmate_copy_policy IN ("
            "'copy_allowed','copy_blocked','manual_review'"
            ")",
            name="ck_curated_features_copy_policy",
        ),
        CheckConstraint("copy_version >= 1", name="ck_curated_features_copy_version"),
        CheckConstraint(
            "jsonb_typeof(metadata) = 'object'",
            name="ck_curated_features_metadata",
        ),
        Index(
            "uq_curated_features_theme_feature_active",
            "theme_id",
            "feature_id",
            unique=True,
            postgresql_where=text("archived_at IS NULL"),
        ),
        Index(
            "idx_curated_features_status_keyset",
            "curation_status",
            text("updated_at DESC"),
            text("curated_feature_id DESC"),
        ),
        Index(
            "idx_curated_features_theme_status_score",
            "theme_id",
            "curation_status",
            text("rank_score DESC"),
            text("curated_feature_id DESC"),
        ),
        Index("idx_curated_features_source_status", "source_id", "curation_status"),
        Index("idx_curated_features_feature", "feature_id"),
        {"schema": "feature"},
    )

    curated_feature_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        server_default=text("x_extension.gen_random_uuid()"),
    )
    theme_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("feature.curated_themes.theme_id", ondelete="CASCADE"),
        nullable=False,
    )
    feature_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("feature.features.feature_id", ondelete="CASCADE"),
        nullable=False,
    )
    source_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("feature.curated_sources.source_id", ondelete="RESTRICT"),
        nullable=False,
    )
    source_record_key: Mapped[str | None] = mapped_column(
        Text,
        ForeignKey(
            "provider_sync.source_records.source_record_key",
            ondelete="SET NULL",
        ),
    )
    curation_status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'candidate'"),
    )
    selection_origin: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'source_rule'"),
    )
    selected_by: Mapped[str | None] = mapped_column(Text)
    selected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rejected_by: Mapped[str | None] = mapped_column(Text)
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rejection_reason: Mapped[str | None] = mapped_column(Text)
    rank_score: Mapped[Any] = mapped_column(
        Numeric(10, 4), nullable=False, server_default=text("0"),
    )
    display_title: Mapped[str | None] = mapped_column(Text)
    display_summary: Mapped[str | None] = mapped_column(Text)
    tripmate_relation: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'nearby_option'"),
    )
    tripmate_copy_policy: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'manual_review'"),
    )
    copy_version: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("1"),
    )
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()"),
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# =============================================================================
# provider_sync.provider_sync_state  (docs/data-model.md §4)
# =============================================================================


class ProviderSyncStateRow(Base):
    """``provider_sync.provider_sync_state`` row mapping — provider cursor 추적."""

    __tablename__ = "provider_sync_state"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active','paused','disabled','failed')",
            name="provider_sync_state_status",
        ),
        Index(
            "idx_sync_state_next_run", "next_run_after",
            postgresql_where=text("status='active'"),
        ),
        {"schema": "provider_sync"},
    )

    provider: Mapped[str] = mapped_column(String, primary_key=True)
    dataset_key: Mapped[str] = mapped_column(String, primary_key=True)
    sync_scope: Mapped[str] = mapped_column(String, primary_key=True)
    status: Mapped[str] = mapped_column(
        String, nullable=False, server_default=text("'active'"),
    )
    cursor: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb"),
    )
    last_success_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
    )
    last_failure_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
    )
    consecutive_failures: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0"),
    )
    next_run_after: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()"),
    )


# =============================================================================
# ops.feature_consistency_reports  (ADR-033 Phase 1 / ADR-017 미러)
# =============================================================================


class FeatureConsistencyReportRow(Base):
    """``ops.feature_consistency_reports`` row mapping — 정합성 배치 결과.

    ADR-033 Phase 1: F1~F3 critical 케이스를 ``infra/consistency.py``의 raw SQL
    (ADR-004)로 검사한 결과를 1 배치 = 1 행으로 영속화. ``cases``는 케이스별
    결과 array, ``summary``는 집계(total / by_severity / by_code). Dagster 게이트
    (swap 차단)는 Phase 2(Sprint 5) — 본 테이블은 그 전까지 "관측" 용도.
    """

    __tablename__ = "feature_consistency_reports"
    __table_args__ = (
        CheckConstraint(
            "severity_max IN ('OK','WARN','ERROR')",
            name="feature_consistency_reports_severity_max",
        ),
        Index("idx_reports_batch", "batch_id"),
        Index("idx_reports_started", text("started_at DESC"), text("report_id DESC")),
        Index(
            "idx_reports_severity_started",
            "severity_max",
            text("started_at DESC"),
            text("report_id DESC"),
        ),
        {"schema": "ops"},
    )

    report_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        server_default=text("x_extension.gen_random_uuid()"),
    )
    batch_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()"),
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    severity_max: Mapped[str] = mapped_column(String, nullable=False)
    cases: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    summary: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


# =============================================================================
# ops.dedup_review_queue  (ADR-016 / docs/data-model.md §9.2)
# =============================================================================


class DedupReviewQueueRow(Base):
    """``ops.dedup_review_queue`` row mapping — cross-provider 중복 후보 검토 큐.

    ``core.dedup.find_dedup_candidates``가 만든 ``manual_review``(및 옵션
    ``auto_merge``) 후보를 영속화한다 (ADR-016, SPRINT-3 §2.5). raw SQL은
    ``infra/dedup_repo.py``의 ``_SQL`` 상수에서 (ADR-004).

    점수는 0~100 ``NUMERIC(5,2)`` (core.scoring의 0.0~1.0 ×100). ``status``는
    운영자 검토 워크플로(pending→accepted/rejected/merged/ignored),
    ``decision_reason``에 알고리즘 제안(auto_merge/manual_review)을 보관.
    ``feature_id_a < feature_id_b`` 정규화 + ``(feature_id_a, feature_id_b)``
    UNIQUE — 재스캔은 pending 행 점수만 갱신.
    """

    __tablename__ = "dedup_review_queue"
    __table_args__ = (
        UniqueConstraint("feature_id_a", "feature_id_b", name="uq_dedup_pair"),
        CheckConstraint("feature_id_a < feature_id_b", name="ck_dedup_pair_order"),
        CheckConstraint(
            "status IN ('pending','accepted','rejected','merged','ignored')",
            name="ck_dedup_status",
        ),
        CheckConstraint(
            "total_score BETWEEN 0 AND 100 AND "
            "name_score BETWEEN 0 AND 100 AND "
            "spatial_score BETWEEN 0 AND 100 AND "
            "category_score BETWEEN 0 AND 100",
            name="ck_dedup_scores",
        ),
        Index(
            "idx_dedup_status_score",
            "status",
            text("total_score DESC"),
            text("review_id DESC"),
        ),
        {"schema": "ops"},
    )

    review_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        server_default=text("x_extension.gen_random_uuid()"),
    )
    feature_id_a: Mapped[str] = mapped_column(
        String,
        ForeignKey("feature.features.feature_id", ondelete="CASCADE"),
        nullable=False,
    )
    feature_id_b: Mapped[str] = mapped_column(
        String,
        ForeignKey("feature.features.feature_id", ondelete="CASCADE"),
        nullable=False,
    )
    total_score: Mapped[Any] = mapped_column(Numeric(5, 2), nullable=False)
    name_score: Mapped[Any] = mapped_column(Numeric(5, 2), nullable=False)
    spatial_score: Mapped[Any] = mapped_column(Numeric(5, 2), nullable=False)
    category_score: Mapped[Any] = mapped_column(Numeric(5, 2), nullable=False)
    status: Mapped[str] = mapped_column(
        String, nullable=False, server_default=text("'pending'"),
    )
    decision_reason: Mapped[str | None] = mapped_column(String)
    reviewed_by: Mapped[str | None] = mapped_column(String)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()"),
    )


# =============================================================================
# ops.enrichment_review_queue  (ADR-042 / T-RV-52c)
# =============================================================================


class EnrichmentReviewQueueRow(Base):
    """``ops.enrichment_review_queue`` row mapping — 축제 enrichment 수동 검토 큐.

    visitkorea(2차)↔datagokr(1차) 축제 이름 유사도가 자동 확정 임계 미만·검토 하한
    이상인 모호한 매칭을 영속화한다(``providers/visitkorea.festival_to_review_candidates``).
    raw SQL은 ``infra/enrichment_review_repo.py``의 ``_SQL`` 상수에서 (ADR-004).

    dedup_review_queue와 달리 두 번째 feature/병합이 없다 — 기존 1차 feature
    (``target_feature_id``)에 ``source_record``(직렬화 ``SourceRecord``)를 ENRICHMENT
    link으로 잇는다. ``status``: pending→accepted/rejected/ignored. ``name_score``는
    0~100 ``NUMERIC(5,2)``. ``(target_feature_id, source_provider, source_dataset_key,
    source_entity_id)`` UNIQUE — 재스캔은 pending 행 점수만 갱신.
    """

    __tablename__ = "enrichment_review_queue"
    __table_args__ = (
        UniqueConstraint(
            "target_feature_id",
            "source_provider",
            "source_dataset_key",
            "source_entity_id",
            name="uq_enrichment_review_candidate",
        ),
        CheckConstraint(
            "status IN ('pending','accepted','rejected','ignored')",
            name="ck_enrichment_review_status",
        ),
        CheckConstraint(
            "name_score BETWEEN 0 AND 100",
            name="ck_enrichment_review_name_score",
        ),
        Index(
            "idx_enrichment_review_status_score",
            "status",
            text("name_score DESC"),
            text("review_id DESC"),
        ),
        Index(
            "idx_enrichment_review_provider_status_score",
            "source_provider",
            "status",
            text("name_score DESC"),
            text("review_id DESC"),
        ),
        {"schema": "ops"},
    )

    review_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        server_default=text("x_extension.gen_random_uuid()"),
    )
    target_feature_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("feature.features.feature_id", ondelete="CASCADE"),
        nullable=False,
    )
    source_provider: Mapped[str] = mapped_column(String, nullable=False)
    source_dataset_key: Mapped[str] = mapped_column(String, nullable=False)
    source_entity_id: Mapped[str] = mapped_column(String, nullable=False)
    source_name: Mapped[str] = mapped_column(String, nullable=False)
    target_name: Mapped[str] = mapped_column(String, nullable=False)
    name_score: Mapped[Any] = mapped_column(Numeric(5, 2), nullable=False)
    source_record: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(
        String, nullable=False, server_default=text("'pending'"),
    )
    decision_reason: Mapped[str | None] = mapped_column(String)
    reviewed_by: Mapped[str | None] = mapped_column(String)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()"),
    )


# =============================================================================
# ops.feature_overrides  (ADR-045 D-8 / T-207c)
# =============================================================================


class FeatureOverrideRow(Base):
    """``ops.feature_overrides`` row mapping.

    운영자가 비활성화/수동 보정한 field를 provider 재적재가 되살리지 않도록 보존한다.
    raw SQL은 ``infra/admin_feature_repo.py``와 ``infra/feature_repo.py``에서 사용한다.
    """

    __tablename__ = "feature_overrides"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active','inactive','superseded')",
            name="ck_overrides_status",
        ),
        Index("idx_overrides_feature", "feature_id", "status"),
        Index("idx_overrides_field", "field_path"),
        Index(
            "uq_overrides_active_feature_field",
            "feature_id",
            "field_path",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
        Index(
            "idx_overrides_prevent_reactivation",
            "feature_id",
            "field_path",
            postgresql_where=text(
                "status = 'active' AND prevent_provider_reactivation"
            ),
        ),
        {"schema": "ops"},
    )

    override_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        server_default=text("x_extension.gen_random_uuid()"),
    )
    feature_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("feature.features.feature_id", ondelete="CASCADE"),
        nullable=False,
    )
    source_record_key: Mapped[str | None] = mapped_column(
        String,
        ForeignKey(
            "provider_sync.source_records.source_record_key",
            ondelete="SET NULL",
        ),
    )
    field_path: Mapped[str] = mapped_column(Text, nullable=False)
    source_value: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    override_value: Mapped[dict[str, Any] | str | int | float | bool | None] = (
        mapped_column(JSONB)
    )
    prevent_provider_reactivation: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false"),
    )
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'active'"),
    )
    reason: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()"),
    )


# =============================================================================
# ops.feature_change_requests  (user/admin feature add/update/delete)
# =============================================================================


class FeatureChangeRequestRow(Base):
    """``ops.feature_change_requests`` row mapping.

    place/event feature 추가·수정·삭제 요청을 보존한다. admin 설정에 따라
    ``pending``으로 남거나 즉시 ``applied``된다.
    """

    __tablename__ = "feature_change_requests"
    __table_args__ = (
        CheckConstraint(
            "action IN ('add','update','delete')",
            name="ck_feature_change_action",
        ),
        CheckConstraint(
            "state IN ('pending','applied','rejected')",
            name="ck_feature_change_state",
        ),
        CheckConstraint(
            "review_mode IN ('require_review','immediate')",
            name="ck_feature_change_review_mode",
        ),
        Index(
            "idx_feature_change_state_created",
            "state",
            text("created_at DESC"),
            text("request_id DESC"),
        ),
        Index("idx_feature_change_feature", "feature_id"),
        {"schema": "ops"},
    )

    request_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        server_default=text("x_extension.gen_random_uuid()"),
    )
    feature_id: Mapped[str] = mapped_column(String, nullable=False)
    action: Mapped[str] = mapped_column(String, nullable=False)
    state: Mapped[str] = mapped_column(
        String, nullable=False, server_default=text("'pending'"),
    )
    review_mode: Mapped[str] = mapped_column(String, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb"),
    )
    reason: Mapped[str | None] = mapped_column(Text)
    requested_by: Mapped[str | None] = mapped_column(Text)
    reviewed_by: Mapped[str | None] = mapped_column(Text)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()"),
    )


# =============================================================================
# ops.import_jobs  (ADR-011)
# =============================================================================


class ImportJobRow(Base):
    """``ops.import_jobs`` row mapping — ETL 적재 작업 큐 (data-model.md §9.1).

    프로세스 재시작 시 진행 상황을 잃지 않도록 작업 상태를 영속화한다 (ADR-011).
    다중 워커는 ``infra/jobs_repo.py``의 ``SELECT ... FOR UPDATE SKIP LOCKED`` +
    advisory lock으로 직렬화한다. raw SQL은 ``infra/jobs_repo.py`` (ADR-004).

    상태 전이: queued → running → done | failed | cancelled. ``heartbeat_at``은
    running 워커가 주기적으로 갱신 — lifespan startup 복구가 만료 행을 failed로
    정리한다.
    """

    __tablename__ = "import_jobs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued','running','done','failed','cancelled')",
            name="ck_import_jobs_status",
        ),
        CheckConstraint(
            "progress BETWEEN 0 AND 100",
            name="ck_import_jobs_progress",
        ),
        Index("idx_import_jobs_created_keyset", text("created_at DESC"), text("job_id DESC")),
        Index("idx_import_jobs_status", "status", "created_at", "queue_sequence"),
        Index(
            "idx_import_jobs_kind_status",
            "kind",
            "status",
            text("created_at DESC"),
            text("job_id DESC"),
        ),
        Index(
            "idx_import_jobs_heartbeat", "heartbeat_at",
            postgresql_where=text("status='running'"),
        ),
        Index(
            "idx_import_jobs_load_batch_created",
            "load_batch_id",
            text("created_at DESC"),
            text("job_id DESC"),
            postgresql_where=text("load_batch_id IS NOT NULL"),
        ),
        Index(
            "idx_import_jobs_parent_created",
            "parent_job_id",
            text("created_at DESC"),
            text("job_id DESC"),
            postgresql_where=text("parent_job_id IS NOT NULL"),
        ),
        {"schema": "ops"},
    )

    job_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        server_default=text("x_extension.gen_random_uuid()"),
    )
    queue_sequence: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        server_default=text("nextval('ops.import_jobs_queue_sequence_seq'::regclass)"),
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    load_batch_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False))
    parent_job_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("ops.import_jobs.job_id", ondelete="SET NULL"),
    )
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb"),
    )
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'queued'"),
    )
    progress: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0"),
    )
    current_stage: Mapped[str | None] = mapped_column(Text)
    source_checksum: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()"),
    )


# =============================================================================
# ops.import_job_events  (T-221b)
# =============================================================================


class ImportJobEventRow(Base):
    """``ops.import_job_events`` row mapping — import job 단계별 event timeline."""

    __tablename__ = "import_job_events"
    __table_args__ = (
        CheckConstraint(
            "level IN ('debug','info','warning','error','critical')",
            name="ck_import_job_events_level",
        ),
        Index(
            "idx_import_job_events_job_time",
            "job_id",
            text("occurred_at DESC"),
            text("event_id DESC"),
        ),
        Index(
            "idx_import_job_events_provider_time",
            "provider",
            text("occurred_at DESC"),
            text("event_id DESC"),
            postgresql_where=text("provider IS NOT NULL"),
        ),
        Index(
            "idx_import_job_events_level_time",
            "level",
            text("occurred_at DESC"),
            text("event_id DESC"),
        ),
        {"schema": "ops"},
    )

    event_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        server_default=text("x_extension.gen_random_uuid()"),
    )
    job_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("ops.import_jobs.job_id", ondelete="CASCADE"),
        nullable=False,
    )
    provider: Mapped[str | None] = mapped_column(Text)
    dataset_key: Mapped[str | None] = mapped_column(Text)
    feature_id: Mapped[str | None] = mapped_column(Text)
    stage: Mapped[str | None] = mapped_column(Text)
    level: Mapped[str] = mapped_column(Text, nullable=False)
    code: Mapped[str | None] = mapped_column(Text)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb"),
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()"),
    )


# =============================================================================
# ops.offline_uploads  (ADR-045 D-14 / T-208g)
# =============================================================================


class OfflineUploadRow(Base):
    """``ops.offline_uploads`` row mapping — 오프라인 원본 파일 메타데이터."""

    __tablename__ = "offline_uploads"
    __table_args__ = (
        CheckConstraint(
            f"status IN ({_sql_text_literals(OFFLINE_UPLOAD_STATE_VALUES)})",
            name="ck_offline_uploads_status",
        ),
        CheckConstraint("byte_size >= 0", name="ck_offline_uploads_byte_size"),
        CheckConstraint(
            "checksum_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_offline_uploads_checksum_sha256",
        ),
        UniqueConstraint(
            "provider",
            "dataset_key",
            "sync_scope",
            "checksum_sha256",
            name="uq_offline_uploads_provider_dataset_scope_checksum",
        ),
        Index(
            "idx_offline_uploads_provider_dataset",
            "provider",
            "dataset_key",
            text("created_at DESC"),
        ),
        Index("idx_offline_uploads_status", "status", text("created_at DESC")),
        {"schema": "ops"},
    )

    upload_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        server_default=text("x_extension.gen_random_uuid()"),
    )
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    dataset_key: Mapped[str] = mapped_column(Text, nullable=False)
    sync_scope: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'default'"),
    )
    original_filename: Mapped[str] = mapped_column(Text, nullable=False)
    storage_backend: Mapped[str] = mapped_column(Text, nullable=False)
    storage_key: Mapped[str] = mapped_column(Text, nullable=False)
    byte_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    checksum_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    detected_format: Mapped[str | None] = mapped_column(Text)
    detected_encoding: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'uploaded'"),
    )
    validation_job_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("ops.import_jobs.job_id", ondelete="SET NULL"),
    )
    load_job_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("ops.import_jobs.job_id", ondelete="SET NULL"),
    )
    created_by: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()"),
    )


# =============================================================================
# ops.feature_update_requests  (ADR-045)
# =============================================================================


class FeatureUpdateRequestRow(Base):
    """``ops.feature_update_requests`` row mapping — Dagster update request 큐.

    Admin/OpenAPI가 만든 지리 범위/provider 범위 업데이트 요청을 저장하고
    ``ops.import_jobs``/Dagster run과 연결한다. raw SQL repository와 상태 전이는
    T-206b에서 별도 구현한다.
    """

    __tablename__ = "feature_update_requests"
    __table_args__ = (
        CheckConstraint(
            "scope_type IN ("
            "'feature_ids','center_radius','sigungu_by_radius','bbox',"
            "'provider_dataset','cache_target_keys'"
            ")",
            name="ck_feature_update_scope",
        ),
        CheckConstraint(
            "run_mode IN ('queued','now')",
            name="ck_feature_update_run_mode",
        ),
        CheckConstraint(
            "status IN ('queued','running','done','failed','cancelled')",
            name="ck_feature_update_status",
        ),
        Index(
            "idx_feature_update_status_priority",
            "status",
            text("priority DESC"),
            "created_at",
        ),
        Index(
            "idx_feature_update_created",
            text("created_at DESC"),
        ),
        Index(
            "idx_feature_update_job",
            "job_id",
            postgresql_where=text("job_id IS NOT NULL"),
        ),
        {"schema": "ops"},
    )

    request_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        server_default=text("x_extension.gen_random_uuid()"),
    )
    scope_type: Mapped[str] = mapped_column(Text, nullable=False)
    scope: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    providers: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb"),
    )
    dataset_keys: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb"),
    )
    update_policy: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb"),
    )
    run_mode: Mapped[str] = mapped_column(Text, nullable=False)
    priority: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("50"),
    )
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'queued'"),
    )
    dry_run: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false"),
    )
    matched_scope: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb"),
    )
    job_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("ops.import_jobs.job_id", ondelete="SET NULL"),
    )
    dagster_run_id: Mapped[str | None] = mapped_column(Text)
    operator: Mapped[str | None] = mapped_column(Text)
    reason: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()"),
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()"),
    )


# =============================================================================
# ops.data_integrity_violations / poi_cache_* / provider_refresh_policies
# =============================================================================


class DataIntegrityViolationRow(Base):
    """``ops.data_integrity_violations`` row mapping — 이슈 1건 = 운영 큐 1행."""

    __tablename__ = "data_integrity_violations"
    __table_args__ = (
        CheckConstraint(
            "severity IN ('info','warning','error','critical')",
            name="ck_violations_severity",
        ),
        CheckConstraint(
            "status IN ('open','acknowledged','resolved','ignored')",
            name="ck_violations_status",
        ),
        Index(
            "idx_violations_type_status",
            "violation_type",
            "status",
        ),
        Index(
            "idx_violations_feature",
            "feature_id",
            postgresql_where=text("feature_id IS NOT NULL"),
        ),
        Index(
            "idx_violations_source_record",
            "source_record_key",
            postgresql_where=text("source_record_key IS NOT NULL"),
        ),
        Index(
            "idx_violations_detected_brin",
            "detected_at",
            postgresql_using="brin",
        ),
        Index(
            "idx_violations_status_detected",
            "status",
            text("detected_at DESC"),
            text("issue_id DESC"),
        ),
        Index(
            "idx_violations_provider_status_detected",
            "provider",
            "status",
            text("detected_at DESC"),
            text("issue_id DESC"),
            postgresql_where=text("provider IS NOT NULL"),
        ),
        Index(
            "idx_violations_feature_detected",
            "feature_id",
            text("detected_at DESC"),
            text("issue_id DESC"),
            postgresql_where=text("feature_id IS NOT NULL"),
        ),
        {"schema": "ops"},
    )

    issue_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        server_default=text("x_extension.gen_random_uuid()"),
    )
    provider: Mapped[str | None] = mapped_column(Text)
    dataset_key: Mapped[str | None] = mapped_column(Text)
    source_record_key: Mapped[str | None] = mapped_column(
        String,
        ForeignKey(
            "provider_sync.source_records.source_record_key",
            ondelete="SET NULL",
        ),
    )
    feature_id: Mapped[str | None] = mapped_column(
        String,
        ForeignKey("feature.features.feature_id", ondelete="CASCADE"),
    )
    violation_type: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(Text, nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb"),
    )
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'open'"),
    )
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()"),
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PoiCacheTargetRow(Base):
    """``ops.poi_cache_targets`` row mapping — 외부 POI/cache target."""

    __tablename__ = "poi_cache_targets"
    __table_args__ = (
        CheckConstraint(
            "scope_mode IN ('center_radius','sigungu_by_radius')",
            name="ck_poi_cache_targets_scope_mode",
        ),
        CheckConstraint(
            "refresh_policy IN ("
            "'provider_default','follow_system','allow_targeted','disabled'"
            ")",
            name="ck_poi_cache_targets_refresh_policy",
        ),
        CheckConstraint(
            "radius_km > 0 AND radius_km <= 100",
            name="ck_poi_cache_targets_radius",
        ),
        CheckConstraint(
            "ST_X(coord) BETWEEN 124.0 AND 132.0 AND "
            "ST_Y(coord) BETWEEN 33.0 AND 39.5",
            name="ck_poi_cache_targets_coord",
        ),
        CheckConstraint(
            "coord_precision_digits BETWEEN 3 AND 8",
            name="ck_poi_cache_targets_precision",
        ),
        Index(
            "uq_poi_cache_targets_active_key",
            "external_system",
            "target_key",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index(
            "idx_poi_cache_targets_coord_5179",
            "coord_5179",
            postgresql_using="gist",
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index(
            "idx_poi_cache_targets_next_refresh",
            "next_eligible_refresh_at",
            postgresql_where=text("deleted_at IS NULL AND update_enabled"),
        ),
        {"schema": "ops"},
    )

    target_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        server_default=text("x_extension.gen_random_uuid()"),
    )
    external_system: Mapped[str] = mapped_column(Text, nullable=False)
    target_key: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str | None] = mapped_column(Text)
    lon: Mapped[Any] = mapped_column(Numeric(12, 8), nullable=False)
    lat: Mapped[Any] = mapped_column(Numeric(12, 8), nullable=False)
    coord: Mapped[Any] = mapped_column(
        Geometry("POINT", srid=4326, spatial_index=False),
        nullable=False,
    )
    coord_5179: Mapped[Any] = mapped_column(
        Geometry("POINT", srid=5179, spatial_index=False),
        Computed("ST_Transform(coord, 5179)", persisted=True),
    )
    coord_precision_digits: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default=text("6"),
    )
    coord_key: Mapped[str] = mapped_column(Text, nullable=False)
    radius_km: Mapped[Any] = mapped_column(Numeric(8, 3), nullable=False)
    scope_mode: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'center_radius'"),
    )
    update_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true"),
    )
    refresh_policy: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'provider_default'"),
    )
    provider_overrides: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb"),
    )
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb"),
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()"),
    )
    last_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_refreshed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_eligible_refresh_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()"),
    )


class PoiCacheTargetFeatureLinkRow(Base):
    """``ops.poi_cache_target_feature_links`` row mapping."""

    __tablename__ = "poi_cache_target_feature_links"
    __table_args__ = (
        CheckConstraint(
            "relation IN ('within_radius','same_sigungu','manual')",
            name="ck_poi_cache_link_relation",
        ),
        Index(
            "idx_poi_cache_links_feature",
            "feature_id",
            postgresql_where=text("active"),
        ),
        Index(
            "idx_poi_cache_links_provider_dataset",
            "provider",
            "dataset_key",
            postgresql_where=text("active"),
        ),
        {"schema": "ops"},
    )

    target_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("ops.poi_cache_targets.target_id", ondelete="CASCADE"),
        primary_key=True,
    )
    feature_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("feature.features.feature_id", ondelete="CASCADE"),
        primary_key=True,
    )
    provider: Mapped[str | None] = mapped_column(Text)
    dataset_key: Mapped[str | None] = mapped_column(Text)
    distance_m: Mapped[Any | None] = mapped_column(Numeric(12, 2))
    relation: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'within_radius'"),
    )
    active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true"),
    )
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()"),
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()"),
    )
    last_refreshed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ProviderRefreshPolicyRow(Base):
    """``ops.provider_refresh_policies`` row mapping."""

    __tablename__ = "provider_refresh_policies"
    __table_args__ = (
        CheckConstraint(
            "source_kind IN ('openapi','filedata','manual','system')",
            name="ck_provider_refresh_source_kind",
        ),
        CheckConstraint(
            "targeted_policy IN ('follow_system','allow_targeted','disabled')",
            name="ck_provider_refresh_targeted_policy",
        ),
        CheckConstraint(
            "max_concurrent > 0",
            name="ck_provider_refresh_max_concurrent",
        ),
        CheckConstraint(
            "system_interval_seconds IS NULL OR system_interval_seconds > 0",
            name="ck_provider_refresh_system_interval",
        ),
        CheckConstraint(
            "optimal_interval_seconds IS NULL OR optimal_interval_seconds > 0",
            name="ck_provider_refresh_optimal_interval",
        ),
        CheckConstraint(
            "min_interval_seconds IS NULL OR min_interval_seconds > 0",
            name="ck_provider_refresh_min_interval",
        ),
        CheckConstraint(
            "max_requests_per_minute IS NULL OR max_requests_per_minute > 0",
            name="ck_provider_refresh_rpm",
        ),
        CheckConstraint(
            "max_requests_per_hour IS NULL OR max_requests_per_hour > 0",
            name="ck_provider_refresh_rph",
        ),
        CheckConstraint(
            "max_requests_per_day IS NULL OR max_requests_per_day > 0",
            name="ck_provider_refresh_rpd",
        ),
        CheckConstraint(
            "burst_size IS NULL OR burst_size > 0",
            name="ck_provider_refresh_burst",
        ),
        Index(
            "idx_provider_refresh_enabled",
            "enabled",
            "provider",
            "dataset_key",
        ),
        Index("idx_provider_refresh_source_kind", "source_kind"),
        {"schema": "ops"},
    )

    provider: Mapped[str] = mapped_column(Text, primary_key=True)
    dataset_key: Mapped[str] = mapped_column(Text, primary_key=True)
    source_kind: Mapped[str] = mapped_column(Text, nullable=False)
    targeted_policy: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'follow_system'"),
    )
    system_interval_seconds: Mapped[int | None] = mapped_column(Integer)
    optimal_interval_seconds: Mapped[int | None] = mapped_column(Integer)
    min_interval_seconds: Mapped[int | None] = mapped_column(Integer)
    max_requests_per_minute: Mapped[int | None] = mapped_column(Integer)
    max_requests_per_hour: Mapped[int | None] = mapped_column(Integer)
    max_requests_per_day: Mapped[int | None] = mapped_column(Integer)
    max_concurrent: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("1"),
    )
    burst_size: Mapped[int | None] = mapped_column(Integer)
    rate_limit_source: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb"),
    )
    config_source: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'db'"),
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()"),
    )


class FeatureMergeHistoryRow(Base):
    """``ops.feature_merge_history`` row mapping — dedup 병합 이력 (ADR-016).

    ``krtour-map dedup-merge``가 ``dedup_review_queue`` 후보 1쌍을 master/loser로
    확정해 병합할 때 1행 INSERT한다. loser의 ``source_links``는 master로 재지정되고
    loser feature는 soft-delete(status='deleted')된다. raw SQL은
    ``infra/merge_repo.py`` (ADR-004). master/loser FK는 feature 하드 삭제 시
    CASCADE, ``review_id`` FK는 큐 행 삭제 시 SET NULL(이력 보존).
    """

    __tablename__ = "feature_merge_history"
    __table_args__ = (
        CheckConstraint(
            "master_feature_id <> loser_feature_id",
            name="ck_merge_history_distinct",
        ),
        Index("idx_merge_history_loser", "loser_feature_id"),
        Index(
            "idx_merge_history_master",
            "master_feature_id",
            text("merged_at DESC"),
        ),
        {"schema": "ops"},
    )

    merge_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        server_default=text("x_extension.gen_random_uuid()"),
    )
    master_feature_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("feature.features.feature_id", ondelete="CASCADE"),
        nullable=False,
    )
    loser_feature_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("feature.features.feature_id", ondelete="CASCADE"),
        nullable=False,
    )
    score: Mapped[Any | None] = mapped_column(Numeric(5, 2))
    review_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("ops.dedup_review_queue.review_id", ondelete="SET NULL"),
    )
    merged_by: Mapped[str | None] = mapped_column(Text)
    reason: Mapped[str | None] = mapped_column(Text)
    merged_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()"),
    )
