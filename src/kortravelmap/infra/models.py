"""``kortravelmap.infra.models`` — SQLAlchemy 2 declarative + GeoAlchemy2 매핑.

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
- ``feature_weather_values`` / ``feature_price_values``
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
    ForeignKeyConstraint,
    Identity,
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
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.schema import conv

from kortravelmap.core.managed_file_states import (
    MANAGED_FILE_EVENT_KIND_VALUES,
    MANAGED_FILE_KIND_VALUES,
    MANAGED_FILE_ORPHAN_REASON_VALUES,
    MANAGED_FILE_REGISTERED_BY_VALUES,
    MANAGED_FILE_STATUS_VALUES,
    MANAGED_FILE_STORAGE_BACKEND_VALUES,
)
from kortravelmap.core.offline_upload_states import OFFLINE_UPLOAD_STATE_VALUES
from kortravelmap.core.pipeline_cancellation_states import (
    PIPELINE_CANCELLATION_RESULT_VALUES,
    PIPELINE_CANCELLATION_ROOT_KIND_VALUES,
    PIPELINE_CANCELLATION_STATUS_VALUES,
)

_CANONICAL_WHITESPACE_SQL = (
    "(' ' || chr(9) || chr(10) || chr(11) || chr(12) || chr(13) "
    "|| chr(28) || chr(29) || chr(30) || chr(31) || chr(133) "
    "|| chr(160) || chr(5760) || chr(8192) || chr(8193) || chr(8194) "
    "|| chr(8195) || chr(8196) || chr(8197) || chr(8198) || chr(8199) "
    "|| chr(8200) || chr(8201) || chr(8202) || chr(8232) || chr(8233) "
    "|| chr(8239) || chr(8287) || chr(12288))"
)

__all__ = [
    "metadata",
    "Base",
    "FeatureRow",
    "WeatherMetricSeriesRow",
    "FeatureVersionRow",
    "SourceEntityRow",
    "NoticeLifecycleScopeRow",
    "NoticeLineageStateRow",
    "SourceRecordRow",
    "SourceLinkRow",
    "CuratedThemeRow",
    "CuratedSourceRow",
    "CuratedSourceRuleRow",
    "CuratedFeatureRow",
    "CurationCollectionRow",
    "CurationItemRow",
    "ProviderSyncStateRow",
    "FeatureConsistencyReportRow",
    "DedupReviewQueueRow",
    "EnrichmentReviewQueueRow",
    "ImportJobRow",
    "ImportJobEventRow",
    "ImportJobEventClockRow",
    "OfflineUploadRow",
    "FeatureOverrideRow",
    "FeatureChangeRequestRow",
    "FeatureUpdateRequestRow",
    "FeatureUpdateRequestIdempotencyRow",
    "PipelineCancellationRow",
    "PipelineCancellationRunRow",
    "PipelineCancellationMemberRow",
    "DataIntegrityViolationRow",
    "PoiCacheTargetRow",
    "PoiCacheTargetFeatureLinkRow",
    "ProviderRefreshPolicyRow",
    "DagsterScheduleAuditEventRow",
    "DagsterScheduleActiveClaimRow",
    "DagsterScheduleClaimResolutionRow",
    "DagsterScheduleOverrideRow",
    "FeatureMergeHistoryRow",
    "ManagedFileRow",
    "ManagedFileEventRow",
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
# feature.features  (docs/architecture/data-model.md §1)
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
        CheckConstraint("row_revision >= 1", name="ck_features_row_revision"),
        CheckConstraint(
            "user_change_kind IS NULL OR user_change_kind IN ('add','update','delete')",
            name="ck_features_user_change_kind",
        ),
        CheckConstraint(
            "user_change_status IS NULL OR user_change_status IN ('pending','applied','rejected')",
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
        Index(
            "idx_features_coord_gist",
            "coord",
            postgresql_using="gist",
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index(
            "idx_features_coord_5179_gist",
            "coord_5179",
            postgresql_using="gist",
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index(
            "idx_features_public_weather_coord_5179_gist",
            "coord_5179",
            postgresql_using="gist",
            postgresql_where=text(
                "status = 'active' "
                "AND deleted_at IS NULL "
                "AND kind = 'weather' "
                "AND coord_5179 IS NOT NULL"
            ),
        ),
        Index(
            "idx_features_geom_gist",
            "geom",
            postgresql_using="gist",
            postgresql_where=text("deleted_at IS NULL AND geom IS NOT NULL"),
        ),
        Index(
            "idx_features_kind_category",
            "kind",
            "category",
            postgresql_where=text("deleted_at IS NULL"),
        ),
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
        Index(
            "idx_features_sigungu",
            "sigungu_code",
            "kind",
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index(
            "idx_features_parent",
            "parent_feature_id",
            postgresql_where=text("parent_feature_id IS NOT NULL"),
        ),
        Index(
            "idx_features_sibling",
            "sibling_group_id",
            postgresql_where=text("sibling_group_id IS NOT NULL"),
        ),
        Index(
            "idx_features_name_trgm",
            "name",
            postgresql_using="gin",
            postgresql_ops={"name": "x_extension.gin_trgm_ops"},
        ),
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
    # T-VN-18(F-8/D-12-3): geoalchemy2 자동 full GiST를 끈다(spatial_index=False).
    # 공개 술어 partial GiST(idx_features_*_gist, WHERE deleted_at IS NULL)만
    # __table_args__에 명시적으로 유지한다 — 자동 full은 write 비용만 늘리고 공개
    # 조회는 partial로 충분하다. 0061이 DB의 자동 full 3개를 drop한다.
    coord: Mapped[Any | None] = mapped_column(
        Geometry("POINT", srid=4326, spatial_index=False)
    )
    coord_precision_digits: Mapped[int | None] = mapped_column(SmallInteger)
    coord_5179: Mapped[Any | None] = mapped_column(
        Geometry("POINT", srid=5179, spatial_index=False),
        Computed(
            "CASE WHEN coord IS NULL THEN NULL ELSE ST_Transform(coord, 5179) END",
            persisted=True,
        ),
    )
    geom: Mapped[Any | None] = mapped_column(
        Geometry("GEOMETRY", srid=4326, spatial_index=False)
    )

    # 주소 (kortravelmap.dto.Address 직렬화, ADR-041 — kraddr-base 흡수).
    address: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    legal_dong_code: Mapped[str | None] = mapped_column(String(10))
    road_name_code: Mapped[str | None] = mapped_column(String)
    road_address_management_no: Mapped[str | None] = mapped_column(String)
    admin_dong_code: Mapped[str | None] = mapped_column(String(10))
    sido_code: Mapped[str | None] = mapped_column(String(2))
    sigungu_code: Mapped[str | None] = mapped_column(String(5))

    # 표시.
    urls: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    marker_icon: Mapped[str | None] = mapped_column(String)
    marker_color: Mapped[str | None] = mapped_column(String)

    # 관계.
    parent_feature_id: Mapped[str | None] = mapped_column(
        String,
        ForeignKey("feature.features.feature_id", ondelete="SET NULL"),
    )
    sibling_group_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False))

    # 상세 (ADR-018 — Pydantic DETAIL_MODELS 직렬화).
    detail: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    raw_refs: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'[]'::jsonb"),
    )
    status: Mapped[str] = mapped_column(
        String,
        nullable=False,
        server_default=text("'active'"),
    )
    data_origin: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        server_default=text("'provider'"),
    )
    data_version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("0"),
    )
    # T-VN-13(D-10-3): server-owned monotonic row revision. 모든 UPDATE에서
    # feature.force_features_row_revision() 트리거가 +1 강제 — If-Match/ETag 낙관적
    # 동시성 validator. provider-owned data_version(위)과 별개다.
    row_revision: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        server_default=text("1"),
    )


    user_change_kind: Mapped[str | None] = mapped_column(Text)
    user_change_status: Mapped[str | None] = mapped_column(Text)
    user_change_request_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False))
    user_deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    user_deleted_by: Mapped[str | None] = mapped_column(Text)
    user_change_reason: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WeatherMetricSeriesRow(Base):
    """weather history의 작은 physical-series registry.

    대용량 fact table에서 매 batch마다 ``DISTINCT``로 series를 재발견하지 않도록
    writer trigger가 단조롭게 등록한다. stale registry row는 조회 시 fact
    predecessor가 없어 자연스럽게 제외된다.
    """

    __tablename__ = "weather_metric_series"
    __table_args__ = ({"schema": "feature"},)

    feature_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("feature.features.feature_id", ondelete="CASCADE"),
        primary_key=True,
    )
    provider: Mapped[str] = mapped_column(Text, primary_key=True)
    weather_domain: Mapped[str] = mapped_column(Text, primary_key=True)
    forecast_style: Mapped[str] = mapped_column(Text, primary_key=True)
    metric_key: Mapped[str] = mapped_column(Text, primary_key=True)


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
    origin: Mapped[str] = mapped_column(Text, nullable=False)
    change_kind: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    request_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False))
    created_by: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )


# =============================================================================
# provider_sync.source_entities / source_records  (ADR-063)
# =============================================================================


class SourceEntityRow(Base):
    """Provider 자연 entity와 현재 immutable payload version의 매핑."""

    __tablename__ = "source_entities"
    __table_args__ = (
        UniqueConstraint(
            "provider",
            "dataset_key",
            "source_entity_type",
            "source_entity_id",
            name="uq_source_entities_identity",
        ),
        ForeignKeyConstraint(
            ["source_entity_key", "current_source_record_key"],
            [
                "provider_sync.source_records.source_entity_key",
                "provider_sync.source_records.source_record_key",
            ],
            name="fk_source_entities_current_record",
            ondelete="RESTRICT",
            deferrable=True,
            initially="DEFERRED",
        ),
        CheckConstraint(
            "first_seen_at <= last_seen_at",
            name="seen_order",
        ),
        Index(
            "idx_source_entities_current_record",
            "current_source_record_key",
            postgresql_where=text("current_source_record_key IS NOT NULL"),
        ),
        {"schema": "provider_sync"},
    )

    source_entity_key: Mapped[str] = mapped_column(Text, primary_key=True)
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    dataset_key: Mapped[str] = mapped_column(Text, nullable=False)
    source_entity_type: Mapped[str] = mapped_column(Text, nullable=False)
    source_entity_id: Mapped[str] = mapped_column(Text, nullable=False)
    current_source_record_key: Mapped[str | None] = mapped_column(Text)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class NoticeLifecycleScopeRow(Base):
    """notice lifecycle scope의 모드·적용 watermark·state fingerprint."""

    __tablename__ = "notice_lifecycle_scopes"
    __table_args__ = (
        CheckConstraint(
            "mode IN ('snapshot', 'event')",
            name="ck_notice_lifecycle_scopes_mode",
        ),
        {"schema": "provider_sync"},
    )

    provider: Mapped[str] = mapped_column(Text, primary_key=True)
    dataset_key: Mapped[str] = mapped_column(Text, primary_key=True)
    source_entity_type: Mapped[str] = mapped_column(Text, primary_key=True)
    mode: Mapped[str] = mapped_column(Text, nullable=False)
    applied_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    state_fingerprint: Mapped[str] = mapped_column(Text, nullable=False)


class NoticeLineageStateRow(Base):
    """Authoritative notice snapshot에 알려진 계보의 최근 존재 상태."""

    __tablename__ = "notice_lineage_states"
    __table_args__ = (
        ForeignKeyConstraint(
            ["provider", "dataset_key", "source_entity_type"],
            [
                "provider_sync.notice_lifecycle_scopes.provider",
                "provider_sync.notice_lifecycle_scopes.dataset_key",
                "provider_sync.notice_lifecycle_scopes.source_entity_type",
            ],
            name="fk_notice_lineage_states_scope",
            ondelete="CASCADE",
        ),
        {"schema": "provider_sync"},
    )

    provider: Mapped[str] = mapped_column(Text, primary_key=True)
    dataset_key: Mapped[str] = mapped_column(Text, primary_key=True)
    source_entity_type: Mapped[str] = mapped_column(Text, primary_key=True)
    lineage_key: Mapped[str] = mapped_column(Text, primary_key=True)
    present: Mapped[bool] = mapped_column(Boolean, nullable=False)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SourceRecordRow(Base):
    """``provider_sync.source_records`` row mapping.

    고유성: ``(provider, dataset_key, source_entity_type, source_entity_id,
    raw_payload_hash)`` (UNIQUE 제약). PK는 ``source_record_key``
    (``make_source_record_key(...)`` 결과).
    """

    __tablename__ = "source_records"
    __table_args__ = (
        UniqueConstraint(
            "provider",
            "dataset_key",
            "source_entity_type",
            "source_entity_id",
            "raw_payload_hash",
            name="uq_source_records",
        ),
        UniqueConstraint(
            "source_entity_key",
            "source_record_key",
            name="uq_source_records_entity_record",
        ),
        Index(
            "idx_source_records_provider_dataset_entity",
            "provider",
            "dataset_key",
            "source_entity_type",
            "source_entity_id",
        ),
        Index(
            "idx_source_records_imported_at_brin",
            "imported_at",
            postgresql_using="brin",
        ),
        Index(
            "idx_source_records_fetched_at_brin",
            "fetched_at",
            postgresql_using="brin",
        ),
        Index(
            "idx_source_records_last_seen_at_brin",
            "last_seen_at",
            postgresql_using="brin",
        ),
        Index(
            "idx_source_records_expires_at",
            "expires_at",
            postgresql_where=text("expires_at IS NOT NULL"),
        ),
        Index(
            "idx_source_records_entity_history",
            "source_entity_key",
            text("last_seen_at DESC"),
            text("fetched_at DESC"),
            text("imported_at DESC"),
            text("source_record_key DESC"),
        ),
        {"schema": "provider_sync"},
    )

    source_record_key: Mapped[str] = mapped_column(String, primary_key=True)
    source_entity_key: Mapped[str] = mapped_column(
        Text,
        ForeignKey(
            "provider_sync.source_entities.source_entity_key",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
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
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    raw_payload_hash: Mapped[str] = mapped_column(String, nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    imported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# =============================================================================
# provider_sync.source_links  (docs/architecture/data-model.md §3)
# =============================================================================


class SourceLinkRow(Base):
    """``provider_sync.source_links`` row mapping — Feature ↔ SourceEntity N:M.

    PK = ``(feature_id, source_entity_key)``. 한 Feature에 여러 primary entity를
    연결할 수 있다.
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
            "idx_source_links_entity",
            "source_entity_key",
        ),
        Index(
            "idx_source_links_role",
            "source_role",
        ),
        Index(
            "idx_source_links_primary",
            "feature_id",
            postgresql_where=text("is_primary_source"),
        ),
        {"schema": "provider_sync"},
    )

    feature_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("feature.features.feature_id", ondelete="CASCADE"),
        primary_key=True,
    )
    source_entity_key: Mapped[str] = mapped_column(
        Text,
        ForeignKey(
            "provider_sync.source_entities.source_entity_key",
            ondelete="RESTRICT",
        ),
        primary_key=True,
    )
    source_role: Mapped[str] = mapped_column(
        String,
        nullable=False,
        server_default=text("'enrichment'"),
    )
    match_method: Mapped[str] = mapped_column(String, nullable=False)
    confidence: Mapped[int] = mapped_column(Integer, nullable=False)
    is_primary_source: Mapped[bool] = mapped_column(
        nullable=False,
        server_default=text("false"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )


# =============================================================================
# feature.curated_*  (docs/curated-features.md, T-223c-1)
# =============================================================================


class CuratedThemeRow(Base):
    """``feature.curated_themes`` row mapping — 테마 metadata."""

    __tablename__ = "curated_themes"
    __table_args__ = (
        CheckConstraint(
            "visibility IN ('admin_only','public')",
            name="ck_curated_themes_visibility",
        ),
        # 0025는 inline ``TEXT NOT NULL UNIQUE``로 만들어 PostgreSQL 기본명
        # ``curated_themes_theme_slug_key``를 얻는다. 명시 constraint로 그 이름을
        # 그대로 반영한다(naming convention은 ``uq_curated_themes_theme_slug``라
        # 달라 column ``unique=True``는 이름이 어긋난다).
        UniqueConstraint("theme_slug", name="curated_themes_theme_slug_key"),
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
    theme_slug: Mapped[str] = mapped_column(Text, nullable=False)
    theme_name: Mapped[str] = mapped_column(Text, nullable=False)
    theme_description: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        server_default=text("''"),
    )
    theme_group: Mapped[str] = mapped_column(Text, nullable=False)
    default_curated: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("false"),
    )
    visibility: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        server_default=text("'admin_only'"),
    )
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
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
            "update_cycle IN ('realtime','daily','weekly','monthly','annual','one_time','unknown')",
            name="ck_curated_sources_update_cycle",
        ),
        CheckConstraint(
            "provider_status IN ('implemented','provider_needed','manual_only','deprecated')",
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
        Text,
        nullable=False,
        server_default=text("'unknown'"),
    )
    last_source_modified_at: Mapped[Any | None] = mapped_column(Date)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_expected_at: Mapped[Any | None] = mapped_column(Date)
    row_count: Mapped[int | None] = mapped_column(Integer)
    freshness_note: Mapped[str | None] = mapped_column(Text)
    provider_status: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        server_default=text("'implemented'"),
    )
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
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
        CheckConstraint(
            "detail_selector IS NULL OR jsonb_typeof(detail_selector) = 'object'",
            name="ck_curated_source_rules_detail_selector",
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
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    # 단일 source를 detail JSON 값으로 분할하는 선택 필터(예: concierge youtube
    # channel/playlist 그룹핑). {"path": ["payload","kor_travel_concierge",...],
    # "value": "<grouping-value>"}. NULL이면 미적용.
    detail_selector: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    default_action: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        server_default=text("'candidate'"),
    )
    priority: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("0"),
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("true"),
    )
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
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
            "curation_relation IN ("
            "'primary_stop','food_stop','cafe_stop','bookstore_stop',"
            "'nearby_option','accessibility_support','pet_support',"
            "'family_support','theme_area_anchor'"
            ")",
            name="ck_curated_features_curation_relation",
        ),
        CheckConstraint(
            "reuse_policy IN ('allowed','blocked','manual_review')",
            name="ck_curated_features_reuse_policy",
        ),
        CheckConstraint(
            "content_version >= 1",
            name="ck_curated_features_content_version",
        ),
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
        Text,
        nullable=False,
        server_default=text("'candidate'"),
    )
    selection_origin: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        server_default=text("'source_rule'"),
    )
    selected_by: Mapped[str | None] = mapped_column(Text)
    selected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rejected_by: Mapped[str | None] = mapped_column(Text)
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rejection_reason: Mapped[str | None] = mapped_column(Text)
    rank_score: Mapped[Any] = mapped_column(
        Numeric(10, 4),
        nullable=False,
        server_default=text("0"),
    )
    display_title: Mapped[str | None] = mapped_column(Text)
    display_summary: Mapped[str | None] = mapped_column(Text)
    curation_relation: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        server_default=text("'nearby_option'"),
    )
    reuse_policy: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        server_default=text("'manual_review'"),
    )
    content_version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("1"),
    )
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    operator_updated_by: Mapped[str | None] = mapped_column(Text)
    operator_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CurationCollectionRow(Base):
    """테마·제목·회차·공식 출처를 공유하는 큐레이션 묶음."""

    __tablename__ = "curation_collections"
    __table_args__ = (
        CheckConstraint("btrim(collection_key) <> ''", name="key"),
        CheckConstraint("btrim(title) <> ''", name="title"),
        CheckConstraint(
            "status IN ('draft','published','archived')",
            name="status",
        ),
        CheckConstraint(
            "visibility IN ('admin_only','public')",
            name="visibility",
        ),
        CheckConstraint(
            "jsonb_typeof(metadata) = 'object'",
            name="metadata",
        ),
        Index(
            "idx_curation_collections_theme_status_edition",
            "theme_id",
            "status",
            "edition_key",
            "collection_id",
        ),
        Index(
            "idx_curation_collections_source_status",
            "source_id",
            "status",
            "collection_id",
        ),
        {"schema": "feature"},
    )

    collection_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        server_default=text("x_extension.gen_random_uuid()"),
    )
    collection_key: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    theme_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("feature.curated_themes.theme_id", ondelete="RESTRICT"),
        nullable=False,
    )
    source_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("feature.curated_sources.source_id", ondelete="SET NULL"),
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    edition_key: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'draft'"))
    visibility: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'admin_only'")
    )
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_by: Mapped[str | None] = mapped_column(Text)
    updated_by: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CurationItemRow(Base):
    """기존 Feature가 큐레이션 묶음에 속한다는 membership 한 건."""

    __tablename__ = "curation_items"
    __table_args__ = (
        CheckConstraint("btrim(external_item_id) <> ''", name="external_id"),
        CheckConstraint(
            "external_component_id <> '' "
            "AND external_component_id = btrim(external_component_id)",
            name="external_component_id_canonical",
        ),
        CheckConstraint("btrim(place_name) <> ''", name="place_name"),
        CheckConstraint(
            "status IN ('candidate','included','rejected','archived')",
            name="status",
        ),
        CheckConstraint("sort_order >= 0", name="sort_order"),
        CheckConstraint(
            "curation_relation IN ("
            "'primary_stop','food_stop','cafe_stop','bookstore_stop',"
            "'nearby_option','accessibility_support','pet_support',"
            "'family_support','theme_area_anchor'"
            ")",
            name="relation",
        ),
        CheckConstraint(
            "reuse_policy IN ('allowed','blocked','manual_review')",
            name="reuse_policy",
        ),
        CheckConstraint(
            "jsonb_typeof(metadata) = 'object'",
            name="metadata",
        ),
        UniqueConstraint(
            "collection_id",
            "external_item_id",
            "external_component_id",
            name="uq_curation_items_component_identity",
        ),
        Index(
            "uq_curation_items_active_source_feature",
            "collection_id",
            "external_item_id",
            "feature_id",
            unique=True,
            postgresql_where=text(
                "source_present AND archived_at IS NULL AND feature_id IS NOT NULL"
            ),
        ),
        Index(
            "uq_curation_items_legacy_projection_id",
            "legacy_projection_id",
            unique=True,
            postgresql_where=text("legacy_projection_id IS NOT NULL"),
        ),
        Index(
            "idx_curation_items_collection_status_order",
            "collection_id",
            "source_present",
            "status",
            "sort_order",
            "curation_item_id",
        ),
        Index(
            "idx_curation_items_feature_status_collection",
            "feature_id",
            "source_present",
            "status",
            "collection_id",
        ),
        {"schema": "feature"},
    )

    curation_item_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        server_default=text("x_extension.gen_random_uuid()"),
    )
    collection_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("feature.curation_collections.collection_id", ondelete="CASCADE"),
        nullable=False,
    )
    feature_id: Mapped[str | None] = mapped_column(
        Text,
        ForeignKey("feature.features.feature_id", ondelete="SET NULL"),
    )
    source_record_key: Mapped[str | None] = mapped_column(
        Text,
        ForeignKey("provider_sync.source_records.source_record_key", ondelete="SET NULL"),
    )
    legacy_projection_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey(
            "feature.curated_features.curated_feature_id",
            ondelete="NO ACTION",
            deferrable=True,
            initially="DEFERRED",
        ),
    )
    external_item_id: Mapped[str] = mapped_column(Text, nullable=False)
    external_component_id: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        server_default=text("'primary'"),
    )
    place_name: Mapped[str] = mapped_column(Text, nullable=False)
    address_hint: Mapped[str | None] = mapped_column(Text)
    source_present: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    source_updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'candidate'"))
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    item_title: Mapped[str | None] = mapped_column(Text)
    item_summary: Mapped[str | None] = mapped_column(Text)
    curation_relation: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'nearby_option'")
    )
    reuse_policy: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'manual_review'")
    )
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_by: Mapped[str | None] = mapped_column(Text)
    updated_by: Mapped[str | None] = mapped_column(Text)
    operator_updated_by: Mapped[str | None] = mapped_column(Text)
    operator_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CuratedFeatureDetailSnapshotRow(Base):
    """``feature.curated_feature_detail_snapshots`` row mapping — detail cache."""

    __tablename__ = "curated_feature_detail_snapshots"
    __table_args__ = (
        CheckConstraint(
            "content_version >= 1",
            name="ck_curated_feature_detail_snapshots_version",
        ),
        CheckConstraint(
            "jsonb_typeof(snapshot) = 'object'",
            name="ck_curated_feature_detail_snapshots_snapshot",
        ),
        Index(
            "idx_curated_feature_detail_snapshots_updated",
            text("updated_at DESC"),
            text("curated_feature_id DESC"),
        ),
        Index("idx_curated_feature_detail_snapshots_etag", "etag"),
        {"schema": "feature"},
    )

    curated_feature_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("feature.curated_features.curated_feature_id", ondelete="CASCADE"),
        primary_key=True,
    )
    content_version: Mapped[int] = mapped_column(Integer, nullable=False)
    etag: Mapped[str] = mapped_column(Text, nullable=False)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    materialized_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )


# =============================================================================
# provider_sync.provider_sync_state  (docs/architecture/data-model.md §4)
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
            "idx_sync_state_next_run",
            "next_run_after",
            postgresql_where=text("status='active'"),
        ),
        {"schema": "provider_sync"},
    )

    provider: Mapped[str] = mapped_column(String, primary_key=True)
    dataset_key: Mapped[str] = mapped_column(String, primary_key=True)
    sync_scope: Mapped[str] = mapped_column(String, primary_key=True)
    status: Mapped[str] = mapped_column(
        String,
        nullable=False,
        server_default=text("'active'"),
    )
    cursor: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    last_success_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
    )
    last_failure_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
    )
    consecutive_failures: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("0"),
    )
    next_run_after: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
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
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    severity_max: Mapped[str] = mapped_column(String, nullable=False)
    cases: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    summary: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


# =============================================================================
# ops.dedup_review_queue  (ADR-016 / docs/architecture/data-model.md §9.2)
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
        String,
        nullable=False,
        server_default=text("'pending'"),
    )
    decision_reason: Mapped[str | None] = mapped_column(String)
    reviewed_by: Mapped[str | None] = mapped_column(String)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
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
        String,
        nullable=False,
        server_default=text("'pending'"),
    )
    decision_reason: Mapped[str | None] = mapped_column(String)
    reviewed_by: Mapped[str | None] = mapped_column(String)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
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
            postgresql_where=text("status = 'active' AND prevent_provider_reactivation"),
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
    override_value: Mapped[dict[str, Any] | str | int | float | bool | None] = mapped_column(JSONB)
    prevent_provider_reactivation: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("false"),
    )
    status: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        server_default=text("'active'"),
    )
    reason: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
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
    action: Mapped[str] = mapped_column(Text, nullable=False)
    state: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        server_default=text("'pending'"),
    )
    review_mode: Mapped[str] = mapped_column(Text, nullable=False)
    base_row_revision: Mapped[int | None] = mapped_column(BigInteger)
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    reason: Mapped[str | None] = mapped_column(Text)
    requested_by: Mapped[str | None] = mapped_column(Text)
    reviewed_by: Mapped[str | None] = mapped_column(Text)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
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
        CheckConstraint(
            "(cancellation_id IS NULL AND cancellation_requested_at IS NULL "
            "AND cancellation_requested_by IS NULL AND cancellation_reason IS NULL) OR "
            "(cancellation_id IS NOT NULL AND cancellation_requested_at IS NOT NULL "
            "AND cancellation_requested_by IS NOT NULL)",
            name="ck_import_jobs_cancellation_marker",
        ),
        CheckConstraint(
            "(provider IS NULL AND dataset_key IS NULL) OR "
            "(provider IS NOT NULL AND provider = btrim(provider) AND provider <> '' "
            "AND dataset_key IS NOT NULL AND dataset_key = btrim(dataset_key) "
            "AND dataset_key <> '')",
            name=conv("ck_import_jobs_provider_dataset_pair"),
        ),
        CheckConstraint(
            "trigger_kind IS NULL OR trigger_kind IN "
            "('schedule','manual','sensor','update_request','backfill','system')",
            name="ck_import_jobs_trigger_kind",
        ),
        CheckConstraint(
            "kind <> 'feature_update_request' OR quarantined_at IS NOT NULL OR "
            "(parent_job_id IS NULL AND load_batch_id IS NULL "
            "AND trigger_kind = 'update_request' "
            "AND operation_registry_version IS NULL AND dagster_run_status IS NULL "
            "AND payload = '{}'::jsonb "
            "AND (dagster_run_id IS NULL OR (dagster_run_id = btrim(dagster_run_id) "
            "AND dagster_run_id <> '')) "
            "AND (status <> 'queued' OR dagster_run_id IS NULL) "
            "AND (status <> 'running' OR dagster_run_id IS NOT NULL) "
            "AND ((provider IS NULL AND dataset_key IS NULL AND sync_scope IS NULL) OR "
            "(provider IS NOT NULL AND dataset_key IS NOT NULL "
            "AND sync_scope IS NOT NULL "
            "AND (sync_scope IN ('dataset_wide','target_grids') OR "
            "(left(sync_scope, 16) = 'external_system:' "
            "AND char_length(sync_scope) <= 128 AND char_length(sync_scope) > 16 "
            "AND substring(sync_scope FROM 17) = "
            f"btrim(substring(sync_scope FROM 17), {_CANONICAL_WHITESPACE_SQL})))))",
            name=conv("ck_import_jobs_update_request_shape"),
        ),
        CheckConstraint(
            "dispatch_requested_at IS NULL OR kind = 'feature_update_request'",
            name=conv("ck_import_jobs_dispatch_requested_at"),
        ),
        CheckConstraint(
            "(quarantined_at IS NULL AND quarantine_reason IS NULL) OR "
            "(quarantined_at IS NOT NULL AND "
            "quarantine_reason = 'unlinked_feature_update_component')",
            name=conv("ck_import_jobs_quarantine_shape"),
        ),
        CheckConstraint(
            "operation_registry_version IS NULL OR kind = 'provider_feature_load_run'",
            name="ck_import_jobs_registry_version_owner",
        ),
        CheckConstraint(
            "dagster_run_status IS NULL OR "
            "(kind = 'provider_feature_load_run' AND dagster_run_status IN "
            "('QUEUED','NOT_STARTED','MANAGED','STARTING','STARTED','CANCELING',"
            "'SUCCESS','FAILURE','CANCELED'))",
            name="ck_import_jobs_dagster_run_status",
        ),
        CheckConstraint(
            "(kind <> 'provider_feature_load_run' OR "
            "(parent_job_id IS NULL AND provider IS NULL AND dataset_key IS NULL "
            "AND dagster_run_id IS NOT NULL AND dagster_run_id = btrim(dagster_run_id) "
            "AND dagster_run_id <> '' AND trigger_kind IS NOT NULL "
            "AND operation_registry_version IS NOT NULL "
            "AND operation_registry_version = btrim(operation_registry_version) "
            "AND operation_registry_version <> '' AND dagster_run_status IS NOT NULL)) "
            "AND (kind <> 'provider_feature_load' OR "
            "(parent_job_id IS NOT NULL AND provider IS NOT NULL "
            "AND dataset_key IS NOT NULL AND dagster_run_id IS NOT NULL "
            "AND dagster_run_id = btrim(dagster_run_id) AND dagster_run_id <> '' "
            "AND trigger_kind IS NULL AND operation_registry_version IS NULL "
            "AND dagster_run_status IS NULL))",
            name="ck_import_jobs_feature_tracking_shape",
        ),
        CheckConstraint(
            "kind NOT IN ('provider_feature_load_run','provider_feature_load') OR "
            "((started_at IS NULL OR created_at <= started_at) AND "
            "(finished_at IS NULL OR created_at <= finished_at) AND "
            "(started_at IS NULL OR finished_at IS NULL OR "
            "started_at <= finished_at))",
            name="ck_import_jobs_feature_engine_timeline",
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
            "idx_import_jobs_feature_update_queue",
            "job_id",
            postgresql_where=text(
                "kind = 'feature_update_request' AND status = 'queued' AND cancellation_id IS NULL"
            ),
        ),
        Index(
            "uq_import_jobs_active_feature_update_scope",
            "provider",
            "dataset_key",
            "sync_scope",
            unique=True,
            postgresql_where=text(
                "kind = 'feature_update_request' "
                "AND status IN ('queued','running') "
                "AND quarantined_at IS NULL "
                "AND provider IS NOT NULL"
            ),
        ),
        Index(
            "idx_import_jobs_quarantined",
            text("quarantined_at DESC"),
            text("job_id DESC"),
            postgresql_where=text("quarantined_at IS NOT NULL"),
        ),
        Index(
            "idx_import_jobs_heartbeat",
            "heartbeat_at",
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
        Index(
            "idx_import_jobs_dagster_run_id",
            "dagster_run_id",
            postgresql_where=text("dagster_run_id IS NOT NULL"),
        ),
        Index(
            "uq_import_jobs_feature_run",
            "dagster_run_id",
            unique=True,
            postgresql_where=text("kind = 'provider_feature_load_run' AND parent_job_id IS NULL"),
        ),
        Index(
            "uq_import_jobs_feature_run_pair",
            "parent_job_id",
            "provider",
            "dataset_key",
            unique=True,
            postgresql_where=text("kind = 'provider_feature_load' AND parent_job_id IS NOT NULL"),
        ),
        Index(
            "idx_import_jobs_provider_dataset_created",
            "provider",
            "dataset_key",
            text("created_at DESC"),
            text("job_id DESC"),
            postgresql_where=text("provider IS NOT NULL AND dataset_key IS NOT NULL"),
        ),
        Index(
            "idx_import_jobs_dataset_created",
            "dataset_key",
            text("created_at DESC"),
            text("job_id DESC"),
            postgresql_where=text("dataset_key IS NOT NULL"),
        ),
        Index(
            "idx_import_jobs_provider_created",
            "provider",
            text("created_at DESC"),
            text("job_id DESC"),
            postgresql_where=text("provider IS NOT NULL"),
        ),
        Index("idx_import_jobs_cancellation_id", "cancellation_id"),
        CheckConstraint(
            "root_kind IN ('import_job','update_request')",
            name="ck_import_jobs_root_kind",
        ),
        Index("idx_import_jobs_root", "root_id", "root_kind"),
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
        # DB default는 ``nextval('ops.import_jobs_queue_sequence_seq')``이지만
        # alembic은 이 sequence를 SERIAL로 인식해 비교에서 omit한다. metadata에
        # 명시 server_default를 두면 None↔nextval 위양성 diff가 생겨 제거한다
        # (실제 default 부여는 0020 migration의 컬럼 DEFAULT가 담당).
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    load_batch_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False))
    parent_job_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("ops.import_jobs.job_id", ondelete="SET NULL"),
    )
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    status: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        server_default=text("'queued'"),
    )
    progress: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("0"),
    )
    current_stage: Mapped[str | None] = mapped_column(Text)
    source_checksum: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)
    # Dagster run 연결 실컬럼 (ADR-064/T-ADM-C3) — payload JSONB 조회 hot path 제거.
    dagster_run_id: Mapped[str | None] = mapped_column(Text)
    provider: Mapped[str | None] = mapped_column(Text)
    dataset_key: Mapped[str | None] = mapped_column(Text)
    sync_scope: Mapped[str | None] = mapped_column(Text)
    # root/component 멤버십을 stamp한다(ADR-077) — read-time 재귀 lineage 제거.
    # DB 트리거가 parent에서 파생(자식은 부모의 root 승계, root는 자기 자신).
    root_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    root_kind: Mapped[str] = mapped_column(Text, nullable=False)
    trigger_kind: Mapped[str | None] = mapped_column(Text)
    operation_registry_version: Mapped[str | None] = mapped_column(Text)
    dagster_run_status: Mapped[str | None] = mapped_column(Text)
    cancellation_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey(
            "ops.pipeline_cancellations.cancellation_id",
            ondelete="RESTRICT",
        ),
    )
    cancellation_requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
    )
    cancellation_requested_by: Mapped[str | None] = mapped_column(Text)
    cancellation_reason: Mapped[str | None] = mapped_column(Text)
    quarantined_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    quarantine_reason: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dispatch_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
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
        CheckConstraint(
            "quarantined_at IS NOT NULL OR "
            "((provider IS NULL AND dataset_key IS NULL) OR "
            "(provider IS NOT NULL AND provider = btrim(provider) AND provider <> '' "
            "AND dataset_key IS NOT NULL AND dataset_key = btrim(dataset_key) "
            "AND dataset_key <> ''))",
            name=conv("ck_import_job_events_provider_dataset_pair"),
        ),
        CheckConstraint(
            "sync_scope IS NULL OR (provider IS NOT NULL AND dataset_key IS NOT NULL "
            "AND (sync_scope IN ('dataset_wide','target_grids') OR "
            "(left(sync_scope, 16) = 'external_system:' "
            "AND char_length(sync_scope) <= 128 AND char_length(sync_scope) > 16 "
            "AND substring(sync_scope FROM 17) = "
            f"btrim(substring(sync_scope FROM 17), {_CANONICAL_WHITESPACE_SQL}))))",
            name=conv("ck_import_job_events_sync_scope"),
        ),
        Index(
            "idx_import_job_events_time",
            text("occurred_at DESC"),
            text("event_id DESC"),
            postgresql_where=text("quarantined_at IS NULL"),
        ),
        Index(
            "idx_import_job_events_job_time",
            "job_id",
            text("occurred_at DESC"),
            text("event_id DESC"),
            postgresql_where=text("quarantined_at IS NULL"),
        ),
        Index(
            "idx_import_job_events_provider_time",
            "provider",
            text("occurred_at DESC"),
            text("event_id DESC"),
            postgresql_where=text("provider IS NOT NULL AND quarantined_at IS NULL"),
        ),
        Index(
            "idx_import_job_events_provider_dataset_time",
            "provider",
            "dataset_key",
            text("occurred_at DESC"),
            text("event_id DESC"),
            postgresql_where=text(
                "provider IS NOT NULL AND dataset_key IS NOT NULL AND quarantined_at IS NULL"
            ),
        ),
        Index(
            "idx_import_job_events_level_time",
            "level",
            text("occurred_at DESC"),
            text("event_id DESC"),
            postgresql_where=text("quarantined_at IS NULL"),
        ),
        Index(
            "idx_import_job_events_provider_dataset_scope_time",
            "provider",
            "dataset_key",
            "sync_scope",
            text("occurred_at DESC"),
            text("event_id DESC"),
            postgresql_where=text(
                "provider IS NOT NULL AND dataset_key IS NOT NULL "
                "AND sync_scope IS NOT NULL AND quarantined_at IS NULL"
            ),
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
    sync_scope: Mapped[str | None] = mapped_column(Text)
    feature_id: Mapped[str | None] = mapped_column(Text)
    stage: Mapped[str | None] = mapped_column(Text)
    level: Mapped[str] = mapped_column(Text, nullable=False)
    code: Mapped[str | None] = mapped_column(Text)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    quarantined_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )


# =============================================================================
# ops.import_job_event_clock  (0052 live revision projection)
# =============================================================================


class ImportJobEventClockRow(Base):
    """Event DML commit을 누락 없이 감지하는 singleton revision projection."""

    __tablename__ = "import_job_event_clock"
    __table_args__ = (
        CheckConstraint("clock_id", name="ck_import_job_event_clock_singleton"),
        CheckConstraint(
            "revision >= 0",
            name="ck_import_job_event_clock_revision_nonnegative",
        ),
        {"schema": "ops"},
    )

    clock_id: Mapped[bool] = mapped_column(
        Boolean,
        primary_key=True,
        server_default=text("true"),
    )
    revision: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        server_default=text("0"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("clock_timestamp()"),
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
        Text,
        nullable=False,
        server_default=text("'default'"),
    )
    original_filename: Mapped[str] = mapped_column(Text, nullable=False)
    storage_backend: Mapped[str] = mapped_column(Text, nullable=False)
    storage_key: Mapped[str] = mapped_column(Text, nullable=False)
    byte_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    checksum_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    detected_format: Mapped[str | None] = mapped_column(Text)
    detected_encoding: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        server_default=text("'uploaded'"),
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
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )


# =============================================================================
# ops.feature_update_requests  (ADR-045)
# =============================================================================


class FeatureUpdateRequestRow(Base):
    """``ops.feature_update_requests`` row mapping — Dagster update request 큐.

    Admin/OpenAPI가 만든 지리 범위/provider 범위 업데이트 입력과 generation을 저장한다.
    lifecycle/Dagster/cancellation은 unique ``job_id``의 canonical import job 단일 정본이다.
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
            "ops.is_valid_feature_update_scope(scope_type, scope)",
            name=conv("ck_feature_update_requests_scope_shape"),
        ),
        CheckConstraint(
            "ops.is_valid_feature_update_filter_array(providers, 32)",
            name=conv("ck_feature_update_requests_providers_shape"),
        ),
        CheckConstraint(
            "ops.is_valid_feature_update_filter_array(dataset_keys, 64)",
            name=conv("ck_feature_update_requests_dataset_keys_shape"),
        ),
        CheckConstraint(
            "ops.is_valid_feature_update_policy(update_policy)",
            name=conv("ck_feature_update_requests_update_policy_shape"),
        ),
        CheckConstraint(
            "scope_type <> 'provider_dataset' OR "
            "(cardinality(providers) = 0 AND cardinality(dataset_keys) = 0)",
            name=conv("ck_feature_update_requests_direct_filters_empty"),
        ),
        CheckConstraint(
            "priority BETWEEN 0 AND 1000",
            name=conv("ck_feature_update_requests_priority_range"),
        ),
        CheckConstraint(
            "generation > 0",
            name=conv("ck_feature_update_requests_generation_positive"),
        ),
        CheckConstraint(
            "jsonb_typeof(matched_scope) = 'object'",
            name=conv("ck_feature_update_requests_matched_scope_object"),
        ),
        CheckConstraint(
            "reason IS NULL OR (reason <> '' AND reason = btrim(reason) "
            "AND reason !~ '^[[:space:]]|[[:space:]]$' "
            "AND char_length(reason) <= 500)",
            name=conv("ck_feature_update_requests_reason_shape"),
        ),
        UniqueConstraint(
            "job_id",
            name=conv("uq_feature_update_requests_job_id"),
        ),
        Index(
            "idx_feature_update_priority",
            text("priority DESC"),
            "created_at",
            "request_id",
        ),
        Index(
            "idx_feature_update_created",
            text("created_at DESC"),
            text("request_id DESC"),
        ),
        Index(
            "idx_feature_update_providers_gin",
            "providers",
            postgresql_using="gin",
        ),
        Index(
            "idx_feature_update_dataset_keys_gin",
            "dataset_keys",
            postgresql_using="gin",
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
        ARRAY(Text),
        nullable=False,
        server_default=text("'{}'::text[]"),
    )
    dataset_keys: Mapped[list[str]] = mapped_column(
        ARRAY(Text),
        nullable=False,
        server_default=text("'{}'::text[]"),
    )
    update_policy: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    run_mode: Mapped[str] = mapped_column(Text, nullable=False)
    priority: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("50"),
    )
    matched_scope: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    job_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("ops.import_jobs.job_id", ondelete="RESTRICT"),
        nullable=False,
    )
    operator: Mapped[str | None] = mapped_column(Text)
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    generation: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        server_default=text("1"),
    )


class FeatureUpdateRequestIdempotencyRow(Base):
    """Actor-scoped append-only feature update request idempotency ledger."""

    __tablename__ = "feature_update_request_idempotency"
    __table_args__ = (
        CheckConstraint(
            "fingerprint_version = 1",
            name=conv("ck_feature_update_request_idempotency_fingerprint_version"),
        ),
        CheckConstraint(
            "request_fingerprint ~ '^[0-9a-f]{64}$'",
            name=conv("ck_feature_update_request_idempotency_fingerprint"),
        ),
        CheckConstraint(
            "btrim(actor) <> '' AND char_length(actor) <= 200",
            name=conv("ck_feature_update_request_idempotency_actor"),
        ),
        Index(
            "idx_feature_update_request_idempotency_request",
            "request_id",
        ),
        {"schema": "ops"},
    )

    actor: Mapped[str] = mapped_column(Text, primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    fingerprint_version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("1"),
    )
    request_fingerprint: Mapped[str] = mapped_column(Text, nullable=False)
    request_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("ops.feature_update_requests.request_id", ondelete="RESTRICT"),
        nullable=False,
    )
    reused_active_request: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )


class DomainCommandRow(Base):
    """Actor-scoped immutable command identity."""

    __tablename__ = "domain_commands"
    __table_args__ = (
        CheckConstraint(
            "btrim(actor) <> '' AND char_length(actor) <= 200",
            name=conv("ck_domain_commands_actor"),
        ),
        CheckConstraint(
            "operation ~ '^[a-z][a-z0-9_.-]{0,127}$'",
            name=conv("ck_domain_commands_operation"),
        ),
        CheckConstraint(
            "fingerprint_version = 1",
            name=conv("ck_domain_commands_fingerprint_version"),
        ),
        CheckConstraint(
            "request_fingerprint ~ '^[0-9a-f]{64}$'",
            name=conv("ck_domain_commands_request_fingerprint"),
        ),
        UniqueConstraint(
            "actor",
            "operation",
            "idempotency_key",
            name=conv("uq_domain_commands_actor_operation_key"),
        ),
        {"schema": "ops"},
    )

    command_id: Mapped[int] = mapped_column(
        BigInteger,
        Identity(always=True),
        primary_key=True,
    )
    actor: Mapped[str] = mapped_column(Text, nullable=False)
    operation: Mapped[str] = mapped_column(Text, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    fingerprint_version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("1"),
    )
    request_fingerprint: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )


class DomainCommandResultRow(Base):
    """Actor-scoped immutable terminal command result."""

    __tablename__ = "domain_command_results"
    __table_args__ = (
        CheckConstraint(
            "response_status BETWEEN 200 AND 599",
            name=conv("ck_domain_command_results_response_status"),
        ),
        CheckConstraint(
            "jsonb_typeof(response_body) = 'object'",
            name=conv("ck_domain_command_results_response_body"),
        ),
        CheckConstraint(
            "jsonb_typeof(response_headers) = 'object'",
            name=conv("ck_domain_command_results_response_headers"),
        ),
        {"schema": "ops"},
    )

    command_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("ops.domain_commands.command_id", ondelete="RESTRICT"),
        primary_key=True,
    )
    response_status: Mapped[int] = mapped_column(Integer, nullable=False)
    response_body: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    response_headers: Mapped[dict[str, str]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    completed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )


# =============================================================================
# ops.pipeline_cancellations / members / runs  (ADR-064 T-ADM-C3d)
# =============================================================================


class PipelineCancellationRow(Base):
    """계층형 취소 workflow attempt."""

    __tablename__ = "pipeline_cancellations"
    __table_args__ = (
        CheckConstraint(
            f"root_kind IN ({_sql_text_literals(PIPELINE_CANCELLATION_ROOT_KIND_VALUES)})",
            name="ck_pipeline_cancellations_root_kind",
        ),
        CheckConstraint(
            f"status IN ({_sql_text_literals(PIPELINE_CANCELLATION_STATUS_VALUES)})",
            name="ck_pipeline_cancellations_status",
        ),
        CheckConstraint(
            "previous_cancellation_id IS NULL OR previous_cancellation_id <> cancellation_id",
            name="ck_pipeline_cancellations_previous",
        ),
        CheckConstraint(
            "(status = 'in_progress' AND finished_at IS NULL) OR "
            "(status <> 'in_progress' AND finished_at IS NOT NULL)",
            name="ck_pipeline_cancellations_finished",
        ),
        CheckConstraint(
            "(status IN ('in_progress','completed') AND error IS NULL) OR "
            "(status IN ('retryable','failed') AND error IS NOT NULL "
            " AND jsonb_typeof(error) = 'object')",
            name="ck_pipeline_cancellations_error_shape",
        ),
        Index(
            "uq_pipeline_cancellations_active_root",
            "root_kind",
            "root_id",
            unique=True,
            postgresql_where=text("status = 'in_progress'"),
        ),
        Index(
            "idx_pipeline_cancellations_root_history",
            "root_kind",
            "root_id",
            text("requested_at DESC"),
            text("cancellation_id DESC"),
        ),
        Index(
            "idx_pipeline_cancellations_previous",
            "previous_cancellation_id",
        ),
        {"schema": "ops"},
    )

    cancellation_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        server_default=text("x_extension.gen_random_uuid()"),
    )
    previous_cancellation_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey(
            "ops.pipeline_cancellations.cancellation_id",
            ondelete="RESTRICT",
        ),
    )
    root_kind: Mapped[str] = mapped_column(Text, nullable=False)
    root_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    status: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        server_default=text("'in_progress'"),
    )
    requested_by: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    error: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PipelineCancellationRunRow(Base):
    """attempt 안에서 한 번만 terminate할 Dagster run."""

    __tablename__ = "pipeline_cancellation_runs"
    __table_args__ = (
        CheckConstraint(
            f"result IN ({_sql_text_literals(PIPELINE_CANCELLATION_RESULT_VALUES)})",
            name="ck_pipeline_cancellation_runs_result",
        ),
        CheckConstraint(
            "(termination_reserved_at IS NULL OR initial_status IS NOT NULL) AND ("
            " (result = 'pending' AND terminal_status IS NULL AND error IS NULL) OR "
            " (result = 'cancelled' AND terminal_status = 'CANCELED' AND error IS NULL) OR "
            " (result = 'already_terminal' AND "
            "  (terminal_status IS NULL OR terminal_status IN ('SUCCESS','FAILURE')) "
            "  AND error IS NULL) OR "
            " (result = 'cancel_failed' AND terminal_status IS NULL AND error IS NOT NULL "
            "  AND jsonb_typeof(error) = 'object'))",
            name="ck_pipeline_cancellation_runs_shape",
        ),
        CheckConstraint(
            "(engine_started_at IS NULL AND engine_finished_at IS NULL) OR "
            "(result IN ('cancelled','already_terminal') "
            "AND engine_finished_at IS NOT NULL "
            "AND (engine_started_at IS NULL OR "
            "engine_started_at <= engine_finished_at))",
            name="ck_pipeline_cancellation_runs_engine_times",
        ),
        ForeignKeyConstraint(
            ["cancellation_id"],
            ["ops.pipeline_cancellations.cancellation_id"],
            ondelete="RESTRICT",
            name="fk_pipeline_cancellation_runs_attempt",
        ),
        {"schema": "ops"},
    )

    cancellation_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
    )
    dagster_run_id: Mapped[str] = mapped_column(Text, primary_key=True)
    initial_status: Mapped[str | None] = mapped_column(Text)
    termination_reserved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    result: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        server_default=text("'pending'"),
    )
    terminal_status: Mapped[str | None] = mapped_column(Text)
    error: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    engine_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    engine_finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )


class PipelineCancellationMemberRow(Base):
    """attempt의 frozen canonical import job과 대상별 실제 결과."""

    __tablename__ = "pipeline_cancellation_members"
    __table_args__ = (
        CheckConstraint(
            f"result IN ({_sql_text_literals(PIPELINE_CANCELLATION_RESULT_VALUES)})",
            name="ck_pipeline_cancellation_members_result",
        ),
        CheckConstraint(
            "(result = 'pending' AND terminal_status IS NULL AND error IS NULL) OR "
            "(result = 'cancelled' AND terminal_status = 'cancelled' AND error IS NULL) OR "
            "(result = 'already_terminal' "
            " AND terminal_status IN ('done','failed','cancelled') AND error IS NULL) OR "
            "(result = 'cancel_failed' AND terminal_status IS NULL AND error IS NOT NULL "
            " AND jsonb_typeof(error) = 'object')",
            name="ck_pipeline_cancellation_members_shape",
        ),
        CheckConstraint(
            "operation_kind IS NULL OR "
            "(operation_kind = btrim(operation_kind) AND operation_kind <> '')",
            name="ck_pipeline_cancellation_members_operation_kind",
        ),
        CheckConstraint(
            "requires_run_termination = "
            "(dagster_run_id IS NOT NULL AND (initial_status = 'running' OR "
            "(initial_status = 'queued' AND COALESCE(operation_kind IN "
            "('provider_feature_load_run','provider_feature_load'), false))))",
            name="ck_pipeline_cancellation_members_run_termination",
        ),
        ForeignKeyConstraint(
            ["cancellation_id"],
            ["ops.pipeline_cancellations.cancellation_id"],
            ondelete="RESTRICT",
            name="fk_pipeline_cancellation_members_attempt",
        ),
        ForeignKeyConstraint(
            ["cancellation_id", "dagster_run_id"],
            [
                "ops.pipeline_cancellation_runs.cancellation_id",
                "ops.pipeline_cancellation_runs.dagster_run_id",
            ],
            ondelete="RESTRICT",
            name="fk_pipeline_cancellation_members_run",
        ),
        Index(
            "idx_pipeline_cancellation_members_job",
            "job_id",
            text("updated_at DESC"),
            text("cancellation_id DESC"),
        ),
        Index(
            "idx_pipeline_cancellation_members_run",
            "cancellation_id",
            "dagster_run_id",
        ),
        {"schema": "ops"},
    )

    cancellation_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
    )
    job_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey(
            "ops.import_jobs.job_id",
            name="fk_pipeline_cancellation_members_job",
            ondelete="RESTRICT",
        ),
        primary_key=True,
    )
    dagster_run_id: Mapped[str | None] = mapped_column(Text)
    operation_kind: Mapped[str | None] = mapped_column(Text)
    requires_run_termination: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("false"),
    )
    initial_status: Mapped[str] = mapped_column(Text, nullable=False)
    result: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        server_default=text("'pending'"),
    )
    terminal_status: Mapped[str | None] = mapped_column(Text)
    error: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
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
        # T-VN-H30A (migration 0067): 열린 이슈에 한해 dedupe_key 1건으로 접는다.
        # 파이프라인이 매 run 같은 export를 전량 재생해도 큐가 부풀지 않게 하는 근거이며,
        # ``sync_integrity_findings``의 ON CONFLICT 추론 대상이다.
        Index(
            "uq_violations_open_dedupe_key",
            text("(payload ->> 'dedupe_key')"),
            unique=True,
            postgresql_where=text(
                "status IN ('open', 'acknowledged') AND payload ? 'dedupe_key'"
            ),
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
            "idx_violations_status_seen",
            "status",
            text("last_seen_at DESC"),
            text("issue_id DESC"),
        ),
        Index(
            "idx_violations_provider_status_seen",
            "provider",
            "status",
            text("last_seen_at DESC"),
            text("issue_id DESC"),
            postgresql_where=text("provider IS NOT NULL"),
        ),
        Index(
            "idx_violations_feature_seen",
            "feature_id",
            text("last_seen_at DESC"),
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
        ForeignKey("feature.features.feature_id", ondelete="SET NULL"),
    )
    violation_type: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(Text, nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    status: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        server_default=text("'open'"),
    )
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
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
            "refresh_policy IN ('provider_default','follow_system','allow_targeted','disabled')",
            name="ck_poi_cache_targets_refresh_policy",
        ),
        CheckConstraint(
            "radius_km > 0 AND radius_km <= 100",
            name="ck_poi_cache_targets_radius",
        ),
        CheckConstraint(
            "ST_X(coord) BETWEEN 124.0 AND 132.0 AND ST_Y(coord) BETWEEN 33.0 AND 39.5",
            name="ck_poi_cache_targets_coord",
        ),
        CheckConstraint(
            "coord_precision_digits BETWEEN 3 AND 8",
            name="ck_poi_cache_targets_precision",
        ),
        CheckConstraint(
            "lock_version >= 1",
            name="ck_poi_cache_targets_lock_version",
        ),
        CheckConstraint(
            "external_system <> '' AND char_length(external_system) <= 112 "
            "AND external_system = "
            f"btrim(external_system, {_CANONICAL_WHITESPACE_SQL})",
            name=conv("ck_poi_cache_targets_external_system_identity"),
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
    lock_version: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        server_default=text("1"),
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
        SmallInteger,
        nullable=False,
        server_default=text("6"),
    )
    coord_key: Mapped[str] = mapped_column(Text, nullable=False)
    radius_km: Mapped[Any] = mapped_column(Numeric(8, 3), nullable=False)
    scope_mode: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        server_default=text("'center_radius'"),
    )
    update_enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("true"),
    )
    refresh_policy: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        server_default=text("'provider_default'"),
    )
    provider_overrides: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    last_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_refreshed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_eligible_refresh_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
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
        Text,
        nullable=False,
        server_default=text("'within_radius'"),
    )
    active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("true"),
    )
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
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
            "stale_after_minutes IS NULL OR stale_after_minutes > 0",
            name="ck_provider_refresh_stale_after",
        ),
        CheckConstraint(
            "revision >= 1 AND revision <= 9223372036854775807",
            name="ck_provider_refresh_revision",
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
        Text,
        nullable=False,
        server_default=text("'follow_system'"),
    )
    system_interval_seconds: Mapped[int | None] = mapped_column(Integer)
    optimal_interval_seconds: Mapped[int | None] = mapped_column(Integer)
    min_interval_seconds: Mapped[int | None] = mapped_column(Integer)
    stale_after_minutes: Mapped[int | None] = mapped_column(Integer)
    max_requests_per_minute: Mapped[int | None] = mapped_column(Integer)
    max_requests_per_hour: Mapped[int | None] = mapped_column(Integer)
    max_requests_per_day: Mapped[int | None] = mapped_column(Integer)
    max_concurrent: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("1"),
    )
    burst_size: Mapped[int | None] = mapped_column(Integer)
    rate_limit_source: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    config_source: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        server_default=text("'db'"),
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("true"),
    )
    revision: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        server_default=text("1"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )


class DagsterScheduleAuditEventRow(Base):
    """``ops.dagster_schedule_audit_events`` append-only command event."""

    __tablename__ = "dagster_schedule_audit_events"
    __table_args__ = (
        CheckConstraint(
            "btrim(schedule_name) <> ''",
            name=conv("ck_dagster_schedule_audit_events_schedule_name_not_blank"),
        ),
        CheckConstraint(
            "command IN ('update','default','start','stop','reset','run')",
            name=conv("ck_dagster_schedule_audit_events_command"),
        ),
        CheckConstraint(
            "phase IN ('requested','succeeded','failed')",
            name=conv("ck_dagster_schedule_audit_events_phase"),
        ),
        CheckConstraint(
            "btrim(actor) <> '' AND char_length(actor) <= 200",
            name=conv("ck_dagster_schedule_audit_events_actor"),
        ),
        CheckConstraint(
            "reason IS NULL OR char_length(reason) <= 500",
            name=conv("ck_dagster_schedule_audit_events_reason"),
        ),
        CheckConstraint(
            "jsonb_typeof(details) = 'object'",
            name=conv("ck_dagster_schedule_audit_events_details_object"),
        ),
        Index(
            "idx_dagster_schedule_audit_schedule_created",
            "schedule_name",
            text("created_at DESC"),
            text("event_id DESC"),
        ),
        Index(
            "idx_dagster_schedule_audit_command",
            "command_id",
            "event_id",
        ),
        Index(
            "uq_dagster_schedule_audit_requested_command",
            "command_id",
            unique=True,
            postgresql_where=text("phase = 'requested'"),
        ),
        Index(
            "uq_dagster_schedule_audit_terminal_command",
            "command_id",
            unique=True,
            postgresql_where=text("phase IN ('succeeded','failed')"),
        ),
        {"schema": "ops"},
    )

    event_id: Mapped[int] = mapped_column(
        BigInteger,
        Identity(always=True),
        primary_key=True,
    )
    command_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    schedule_name: Mapped[str] = mapped_column(Text, nullable=False)
    command: Mapped[str] = mapped_column(Text, nullable=False)
    phase: Mapped[str] = mapped_column(Text, nullable=False)
    actor: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    details: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )


class DagsterScheduleActiveClaimRow(Base):
    """불명 terminal 결과 전 동일 schedule 재실행을 막는 durable claim."""

    __tablename__ = "dagster_schedule_active_claims"
    __table_args__ = (
        CheckConstraint(
            "btrim(schedule_name) <> ''",
            name=conv("ck_dagster_schedule_active_claims_schedule_name_not_blank"),
        ),
        CheckConstraint(
            "resolvable_after >= created_at + interval '5 minutes'",
            name=conv("ck_dagster_schedule_active_claims_resolution_lease"),
        ),
        CheckConstraint(
            "operation_finished_at IS NULL OR operation_finished_at >= created_at",
            name=conv("ck_dagster_schedule_active_claims_finished_after_create"),
        ),
        UniqueConstraint(
            "schedule_name",
            name=conv("uq_dagster_schedule_active_claims_schedule_name"),
        ),
        {"schema": "ops"},
    )

    command_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
    )
    schedule_name: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("clock_timestamp()"),
    )
    resolvable_after: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        # PostgreSQL이 저장·반사하는 정규형(괄호 포함 interval 리터럴)과 일치시킨다.
        server_default=text("(clock_timestamp() + '00:05:00'::interval)"),
    )
    operation_finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
    )


class DagsterScheduleClaimResolutionRow(Base):
    """불명 schedule claim의 운영자 확인 결과를 보존하는 append-only 행."""

    __tablename__ = "dagster_schedule_claim_resolutions"
    __table_args__ = (
        CheckConstraint(
            "btrim(schedule_name) <> ''",
            name=conv("ck_dagster_schedule_claim_resolutions_schedule_name_not_blank"),
        ),
        CheckConstraint(
            "resolution IN ('confirmed_applied','confirmed_not_applied')",
            name=conv("ck_dagster_schedule_claim_resolutions_resolution"),
        ),
        CheckConstraint(
            "btrim(actor) <> '' AND char_length(actor) <= 200",
            name=conv("ck_dagster_schedule_claim_resolutions_actor"),
        ),
        CheckConstraint(
            "btrim(reason) <> '' AND char_length(reason) <= 500",
            name=conv("ck_dagster_schedule_claim_resolutions_reason"),
        ),
        CheckConstraint(
            "jsonb_typeof(details) = 'object'",
            name=conv("ck_dagster_schedule_claim_resolutions_details_object"),
        ),
        UniqueConstraint(
            "command_id",
            name=conv("uq_dagster_schedule_claim_resolutions_command_id"),
        ),
        Index(
            "idx_dagster_schedule_claim_resolutions_schedule_created",
            "schedule_name",
            text("created_at DESC"),
            text("resolution_id DESC"),
        ),
        {"schema": "ops"},
    )

    resolution_id: Mapped[int] = mapped_column(
        BigInteger,
        Identity(always=True),
        primary_key=True,
    )
    command_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        nullable=False,
    )
    schedule_name: Mapped[str] = mapped_column(Text, nullable=False)
    resolution: Mapped[str] = mapped_column(Text, nullable=False)
    actor: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )


class DagsterScheduleOverrideRow(Base):
    """``ops.dagster_schedule_overrides`` row mapping.

    Dagster ``ScheduleDefinition``의 cron은 코드 location 로드 시점에 고정된다.
    운영 화면은 이 테이블에 override를 저장하고 repository location reload를
    요청해 다음 로드부터 수정된 cron을 사용하게 한다.
    """

    __tablename__ = "dagster_schedule_overrides"
    __table_args__ = (
        CheckConstraint(
            "btrim(schedule_name) <> ''",
            name="ck_dagster_schedule_overrides_schedule_name_not_blank",
        ),
        CheckConstraint(
            "btrim(cron_schedule) <> ''",
            name="ck_dagster_schedule_overrides_cron_schedule_not_blank",
        ),
        CheckConstraint(
            "jsonb_typeof(metadata) = 'object'",
            name="ck_dagster_schedule_overrides_metadata_object",
        ),
        {"schema": "ops"},
    )

    schedule_name: Mapped[str] = mapped_column(Text, primary_key=True)
    cron_schedule: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    updated_by: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )


class FeatureMergeHistoryRow(Base):
    """``ops.feature_merge_history`` row mapping — dedup 병합 이력 (ADR-016).

    ``ktmctl dedup-merge``가 ``dedup_review_queue`` 후보 1쌍을 master/loser로
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
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )


# =============================================================================
# ops.managed_files / ops.managed_file_events  (파일 관리 registry, PR-D)
# =============================================================================


class ManagedFileRow(Base):
    """``ops.managed_files`` row mapping — 시스템 저장 파일 현재 상태.

    파일 1개(백업 artifact는 디렉터리 1개) = 1행. ``location``은 논리 루트
    키(``backup_root``/``mois_source``/``object_store``/``offline_uploads``),
    ``path``는 루트 상대 경로/object key — 물리 경로는 배포마다 달라서
    ``meta.physical``에만 스냅샷한다. 이력은 ``ManagedFileEventRow``.
    """

    __tablename__ = "managed_files"
    __table_args__ = (
        CheckConstraint(
            f"storage_backend IN ({_sql_text_literals(MANAGED_FILE_STORAGE_BACKEND_VALUES)})",
            name="ck_managed_files_storage_backend",
        ),
        CheckConstraint(
            f"kind IN ({_sql_text_literals(MANAGED_FILE_KIND_VALUES)})",
            name="ck_managed_files_kind",
        ),
        CheckConstraint(
            f"status IN ({_sql_text_literals(MANAGED_FILE_STATUS_VALUES)})",
            name="ck_managed_files_status",
        ),
        CheckConstraint(
            "orphan_reason IS NULL OR orphan_reason IN "
            f"({_sql_text_literals(MANAGED_FILE_ORPHAN_REASON_VALUES)})",
            name="ck_managed_files_orphan_reason",
        ),
        CheckConstraint(
            f"registered_by IN ({_sql_text_literals(MANAGED_FILE_REGISTERED_BY_VALUES)})",
            name="ck_managed_files_registered_by",
        ),
        CheckConstraint("byte_size >= 0", name="ck_managed_files_byte_size"),
        CheckConstraint(
            "checksum_sha256 IS NULL OR checksum_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_managed_files_checksum_sha256",
        ),
        CheckConstraint(
            "jsonb_typeof(meta) = 'object'",
            name="ck_managed_files_meta_object",
        ),
        UniqueConstraint(
            "storage_backend",
            "location",
            "path",
            name="uq_managed_files_backend_location_path",
        ),
        Index(
            "idx_managed_files_status_kind",
            "status",
            "kind",
            text("updated_at DESC"),
        ),
        Index(
            "idx_managed_files_kind_downloaded",
            "kind",
            text("downloaded_at DESC"),
        ),
        Index(
            "idx_managed_files_provider",
            "provider",
            postgresql_where=text("provider IS NOT NULL"),
        ),
        Index(
            "idx_managed_files_origin_job",
            "origin_import_job_id",
            postgresql_where=text("origin_import_job_id IS NOT NULL"),
        ),
        Index(
            "idx_managed_files_upload",
            "upload_id",
            postgresql_where=text("upload_id IS NOT NULL"),
        ),
        # fillfactor=90은 마이그레이션 DDL이 소유한다(ORM 물리 스토리지 파라미터 불필요).
        {"schema": "ops"},
    )

    file_id: Mapped[int] = mapped_column(
        BigInteger,
        Identity(always=True),
        primary_key=True,
    )
    storage_backend: Mapped[str] = mapped_column(Text, nullable=False)
    location: Mapped[str] = mapped_column(Text, nullable=False)
    path: Mapped[str] = mapped_column(Text, nullable=False)
    is_directory: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("false"),
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    provider: Mapped[str | None] = mapped_column(Text)
    dataset_key: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        server_default=text("'active'"),
    )
    orphan_reason: Mapped[str | None] = mapped_column(Text)
    registered_by: Mapped[str] = mapped_column(Text, nullable=False)
    byte_size: Mapped[int | None] = mapped_column(BigInteger)
    checksum_sha256: Mapped[str | None] = mapped_column(Text)
    # soft ref (FK 없음): offline-uploads DELETE가 row를 hard-delete하므로
    # FK면 provenance가 지워지거나(SET NULL) 기존 삭제 API가 깨진다(RESTRICT).
    upload_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False))
    origin_import_job_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("ops.import_jobs.job_id", ondelete="SET NULL"),
    )
    origin_dagster_run_id: Mapped[str | None] = mapped_column(Text)
    downloaded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_loaded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # 비인덱스 유지 — scan마다 도는 UPDATE의 HOT 경로(fillfactor=90과 세트).
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    meta: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )


class ManagedFileEventRow(Base):
    """``ops.managed_file_events`` row mapping — registry append-only 이력.

    상태 전이 시에만 기록한다(스캔 no-op은 부모 ``last_seen_at``으로 충분).
    ``uq_managed_file_events_run_dedupe``가 run당 ``loaded`` 이벤트를 1개로
    dedupe한다(MOIS fetch가 한 run에서 slug 42회 반복 호출되는 경로).
    """

    __tablename__ = "managed_file_events"
    __table_args__ = (
        CheckConstraint(
            f"event_kind IN ({_sql_text_literals(MANAGED_FILE_EVENT_KIND_VALUES)})",
            name="ck_managed_file_events_event_kind",
        ),
        CheckConstraint(
            "jsonb_typeof(detail) = 'object'",
            name="ck_managed_file_events_detail_object",
        ),
        Index(
            "idx_managed_file_events_file",
            "file_id",
            text("occurred_at DESC"),
        ),
        Index(
            "idx_managed_file_events_job",
            "import_job_id",
            postgresql_where=text("import_job_id IS NOT NULL"),
        ),
        Index(
            "uq_managed_file_events_run_dedupe",
            "file_id",
            "event_kind",
            "dagster_run_id",
            unique=True,
            postgresql_where=text("dagster_run_id IS NOT NULL"),
        ),
        {"schema": "ops"},
    )

    event_id: Mapped[int] = mapped_column(
        BigInteger,
        Identity(always=True),
        primary_key=True,
    )
    file_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("ops.managed_files.file_id", ondelete="CASCADE"),
        nullable=False,
    )
    event_kind: Mapped[str] = mapped_column(Text, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    import_job_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("ops.import_jobs.job_id", ondelete="SET NULL"),
    )
    dagster_run_id: Mapped[str | None] = mapped_column(Text)
    actor: Mapped[str | None] = mapped_column(Text)
    detail: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
