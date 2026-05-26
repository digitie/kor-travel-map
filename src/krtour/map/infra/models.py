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
    CheckConstraint,
    Computed,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Numeric,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

__all__ = [
    "metadata",
    "Base",
    "FeatureRow",
    "SourceRecordRow",
    "SourceLinkRow",
    "ProviderSyncStateRow",
]


# Naming convention — Alembic autogenerate 안정성 + DB 가시성.
_NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


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
            "coord IS NULL OR ("
            "ST_X(coord) BETWEEN 124.0 AND 132.0 AND "
            "ST_Y(coord) BETWEEN 33.0 AND 39.5)",
            name="features_coord_pair",
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
        Index("idx_features_status_updated", "status", "updated_at"),
        Index("idx_features_legal_dong_code", "legal_dong_code"),
        Index("idx_features_sigungu", "sigungu_code", "kind",
              postgresql_where=text("deleted_at IS NULL")),
        Index("idx_features_parent", "parent_feature_id",
              postgresql_where=text("parent_feature_id IS NOT NULL")),
        Index("idx_features_sibling", "sibling_group_id",
              postgresql_where=text("sibling_group_id IS NOT NULL")),
        Index("idx_features_name_trgm", "name", postgresql_using="gin",
              postgresql_ops={"name": "x_extension.gin_trgm_ops"}),
        {"schema": "feature"},
    )

    feature_id: Mapped[str] = mapped_column(String, primary_key=True)
    kind: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    category: Mapped[str] = mapped_column(String, nullable=False)

    # 좌표 (ADR-012 — 양 좌표계 보유, coord_5179는 STORED generated).
    coord: Mapped[Any | None] = mapped_column(Geometry("POINT", srid=4326))
    coord_5179: Mapped[Any | None] = mapped_column(
        Geometry("POINT", srid=5179),
        Computed(
            "CASE WHEN coord IS NULL THEN NULL "
            "ELSE ST_Transform(coord, 5179) END",
            persisted=True,
        ),
    )
    geom: Mapped[Any | None] = mapped_column(Geometry("GEOMETRY", srid=4326))

    # 주소 (kraddr.base.Address 직렬화).
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

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()"),
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


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
            "source_role IN ('primary','enrichment','geocoded','phone',"
            "'media','weather_context','observation','external_link')",
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
