"""``kortravelmap.infra.models`` — SQLAlchemy 2 declarative + GeoAlchemy2 매핑.

**매핑만**. 비즈니스 로직 / 쿼리 메서드 금지 — 쿼리는 ``infra/*_repo.py``의
raw SQL ``text()`` (ADR-004). 본 모듈은 Alembic ``target_metadata``의 원천이며
ORM 인스턴스 read mapping 용도로도 사용 가능.

구성:
- ``features`` — kind 공통 core (ADR-012 ``coord_5179`` STORED generated column).
  kind별 값과 선·면 geometry는 여기 없다 — subtype이 정본이다(ADR-086).
- kind별 typed subtype 5종 — ``feature_places`` / ``feature_events`` /
  ``feature_notices`` / ``feature_routes`` / ``feature_areas``. core의
  ``UNIQUE (feature_id, kind)``를 kind 상수 CHECK + 복합 FK로 참조하는
  **배타 arc**다(한 feature는 최대 한 subtype, subtype이 있는 동안 kind 불변).
- ``feature_weather_values`` / ``feature_price_values`` — weather/price는
  subtype이 없고 값 정본이 이 둘이다.
- ``source_records`` / ``source_links`` / ``provider_sync_state`` —
  provider 적재 추적. ``feature_files``, ``ops.*``도 여기 매핑돼 있다.
- 4 schemas (feature / provider_sync / ops / x_extension)

아직 없는 테이블: ``feature_opening_periods`` / ``feature_special_days``
(0002의 후속 PR 항목 — 영업시간은 현재 subtype JSONB가 갖는다).

뷰는 매핑하지 않는다 — ``feature.public_features``는 alembic이 소유하고 repo가
raw SQL로 읽는다. typed detail 조립은 public projection·materializer·reader가
각각 명시적으로 소유하며 private bridge view는 없다.

ADR 참조
--------
- ADR-004 — ORM 매핑만, 쿼리는 raw SQL (``infra/*_repo.py``)
- ADR-007 — PostgreSQL 16 + PostGIS 3.5 + pg_trgm + pgcrypto
- ADR-008 — extension은 ``x_extension`` schema 격리
- ADR-012 — ``coord_5179`` STORED generated column (반경 검색 인덱스)
- ADR-018 — Feature.detail은 kind별 Pydantic 모델 (자유 dict 금지)
- ADR-086 — kind별 typed subtype 분해와 배타 arc
- ADR-019 — 모든 datetime ``TIMESTAMPTZ`` (KST aware)
"""

from __future__ import annotations

from datetime import date, datetime
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
from kortravelmap.core.writer_drain_states import (
    WRITER_DRAIN_CANCEL_RESULTS,
    WRITER_DRAIN_INSTIGATION_KINDS,
    WRITER_DRAIN_LEASE_STATES,
    WRITER_DRAIN_OWNER_KINDS,
    WRITER_DRAIN_PAUSE_RESULTS,
    WRITER_DRAIN_RECEIPT_OPERATIONS,
    WRITER_DRAIN_RESTORE_RESULTS,
)
from kortravelmap.infra.curation_link_basis import ALL_LINK_BASES

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
    "FeatureStateTransitionRow",
    "FeatureAliasRow",
    "ProviderDatasetRow",
    "ProviderDatasetOperationRow",
    "ProviderDatasetOperationScopeRow",
    "SourceEntityRow",
    "SourceEntityHeadRow",
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
    "CurationImportBatchRow",
    "CurationImportRowRow",
    "CurationLinkDecisionRow",
    "ProviderSyncStateRow",
    "FeatureConsistencyReportRow",
    "DedupReviewQueueRow",
    "EnrichmentReviewQueueRow",
    "ImportJobRow",
    "ImportJobDatasetRow",
    "C6cCancelProbeFixtureRow",
    "ImportJobEventRow",
    "ImportJobEventClockRow",
    "OfflineUploadRow",
    "FeatureOverrideFieldPathRow",
    "FeatureBaseFieldValueRow",
    "FeatureOverrideRow",
    "FeatureUpdateRequestRow",
    "FeatureUpdateRequestDatasetRow",
    "FeatureUpdateRequestIdempotencyRow",
    "PipelineCancellationRow",
    "PipelineCancellationRunRow",
    "PipelineCancellationMemberRow",
    "CacheTargetWriterDrainLeaseRow",
    "CacheTargetWriterDrainInstigationRow",
    "CacheTargetWriterDrainRunRow",
    "IntegrityObservationScopeRow",
    "IntegrityObservationRunRow",
    "IntegrityFindingObservationRow",
    "DataIntegrityViolationRow",
    "PoiCacheTargetRow",
    "PoiCacheTargetFeatureLinkRow",
    "PoiCacheTargetStreamRow",
    "PoiCacheTargetRestoreFenceRow",
    "PoiCacheTargetSourceHeadRow",
    "PoiCacheTargetSourceEventRow",
    "PoiCacheTargetRefreshMemberRow",
    "PoiCacheTargetReconciliationRequestRow",
    "PoiCacheTargetOutboxEventRow",
    "PoiCacheTargetOutboxClaimRow",
    "PoiCacheTargetOutboxDeliveryRow",
    "PoiCacheTargetOutboxClaimEventRow",
    "PoiCacheTargetSnapshotRow",
    "PoiCacheTargetSnapshotItemRow",
    "PoiCacheTargetSnapshotGcObservationRow",
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
            "lifecycle_state IN ('active','retired')",
            name="lifecycle_state",
        ),
        CheckConstraint(
            "publication_state IN ('draft','published','suppressed')",
            name="publication_state",
        ),
        CheckConstraint(
            "quality_state IN ('valid','quarantined')",
            name="quality_state",
        ),
        CheckConstraint(
            "lifecycle_state = 'active' OR publication_state = 'suppressed'",
            name="state_tuple",
        ),
        CheckConstraint("row_revision >= 1", name="ck_features_row_revision"),
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
            postgresql_where=text(
                "lifecycle_state = 'active' "
                "AND publication_state = 'published' "
                "AND quality_state = 'valid'"
            ),
        ),
        Index(
            "idx_features_coord_5179_gist",
            "coord_5179",
            postgresql_using="gist",
            postgresql_where=text(
                "lifecycle_state = 'active' "
                "AND publication_state = 'published' "
                "AND quality_state = 'valid'"
            ),
        ),
        Index(
            "idx_features_public_weather_coord_5179_gist",
            "coord_5179",
            postgresql_using="gist",
            postgresql_where=text(
                "lifecycle_state = 'active' "
                "AND publication_state = 'published' "
                "AND quality_state = 'valid' "
                "AND kind = 'weather' "
                "AND coord_5179 IS NOT NULL"
            ),
        ),
        Index(
            "idx_features_kind_category",
            "kind",
            "category",
            postgresql_where=text(
                "lifecycle_state = 'active' "
                "AND publication_state = 'published' "
                "AND quality_state = 'valid'"
            ),
        ),
        Index(
            "idx_features_updated_keyset",
            text("updated_at DESC"),
            text("feature_id DESC"),
            postgresql_where=text(
                "lifecycle_state = 'active' "
                "AND publication_state = 'published' "
                "AND quality_state = 'valid'"
            ),
        ),
        Index(
            "idx_features_lower_name_keyset",
            text("lower(name)"),
            "feature_id",
            postgresql_where=text(
                "lifecycle_state = 'active' "
                "AND publication_state = 'published' "
                "AND quality_state = 'valid'"
            ),
        ),
        # admin scope 조회축. 0096이 공개 3축 partial로 좁힌 인덱스들은 admin이
        # 쓰지 못한다 — T-VN-34C가 admin 목록의 상태 기본 필터를 제거해 admin은
        # 상태 무필터로 읽고, 축을 지정해도 AND 결합이라 공개 술어를 함의하지 않는다.
        # 그래서 admin 기본 화면이 Seq Scan으로 떨어졌다(alembic 0098 참조).
        # 두 표면의 조회 의미를 맞추는 대신 admin에 자기 인덱스를 준다.
        Index(
            "idx_features_admin_lower_name_keyset",
            text("lower(name)"),
            "feature_id",
        ),
        Index(
            "idx_features_admin_updated_keyset",
            text("updated_at DESC"),
            text("feature_id DESC"),
        ),
        Index(
            "idx_features_admin_created_keyset",
            text("created_at DESC"),
            text("feature_id DESC"),
        ),
        Index("idx_features_legal_dong_code", "legal_dong_code"),
        Index(
            "idx_features_sigungu",
            "sigungu_code",
            "kind",
            postgresql_where=text(
                "lifecycle_state = 'active' "
                "AND publication_state = 'published' "
                "AND quality_state = 'valid' "
                "AND sigungu_code IS NOT NULL"
            ),
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
            postgresql_where=text(
                "lifecycle_state = 'active' "
                "AND publication_state = 'published' "
                "AND quality_state = 'valid'"
            ),
        ),
        UniqueConstraint("feature_uuid", name=conv("uq_features_feature_uuid")),
        # T-VN-32C(0083) — 파생 CHECK는 해제됐고(비파생 UUIDv7 generator),
        # 복합 UNIQUE가 alias 사본 일치 FK의 참조 대상이 된다.
        UniqueConstraint(
            "feature_id", "feature_uuid", name=conv("uq_features_identity_pair")
        ),
        # T-VN-35A(0084) — typed subtype의 배타 arc 참조 대상. subtype 행이
        # (feature_id, kind) 복합 FK로 이 UNIQUE를 참조하고 각자 kind 상수
        # CHECK를 가지므로 ① 한 feature는 최대 한 subtype에만 존재하고
        # ② subtype 행이 있는 동안 core kind 변경이 FK 위반으로 막힌다
        # (혼합 kind row 거부 = 35B 요구의 선언적 구현).
        UniqueConstraint("feature_id", "kind", name=conv("uq_features_identity_kind")),
        {"schema": "feature"},
    )

    feature_id: Mapped[str] = mapped_column(String, primary_key=True)
    # ADR-068 UUID 정본 identity — 기존 행은 0080 backfill의 uuid5 파생값을
    # 영구 보존하고, 신규 행은 0083부터 비파생 UUIDv7
    # (app 정본 core/ids.make_feature_uuid, raw SQL 안전망은 fill 트리거의
    # feature.uuid_generate_v7()). DB server default 없음.
    feature_uuid: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    kind: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    category: Mapped[str] = mapped_column(String, nullable=False)

    # 좌표 (ADR-012 — 양 좌표계 보유, coord_5179는 STORED generated).
    # T-VN-18(F-8/D-12-3): geoalchemy2 자동 full GiST를 끈다(spatial_index=False).
    # 공개 술어 partial GiST(idx_features_*_gist, WHERE 3축 public predicate)만
    # __table_args__에 명시적으로 유지한다 — 자동 full은 write 비용만 늘리고 공개
    # 조회는 partial로 충분하다. 0061이 DB의 자동 full 3개를 drop한다.
    coord: Mapped[Any | None] = mapped_column(Geometry("POINT", srid=4326, spatial_index=False))
    coord_precision_digits: Mapped[int | None] = mapped_column(SmallInteger)
    coord_5179: Mapped[Any | None] = mapped_column(
        Geometry("POINT", srid=5179, spatial_index=False),
        Computed(
            "CASE WHEN coord IS NULL THEN NULL ELSE ST_Transform(coord, 5179) END",
            persisted=True,
        ),
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
    raw_refs: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'[]'::jsonb"),
    )
    # T-VN-34C(ADR-090) 직교 상태 정본. legacy status/soft-delete/user-change
    # surrogate는 final migration에서 물리 제거했다.
    lifecycle_state: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        server_default=text("'active'"),
    )
    publication_state: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        server_default=text("'published'"),
    )
    quality_state: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        server_default=text("'valid'"),
    )
    # T-VN-13(D-10-3): server-owned monotonic row revision. 모든 UPDATE에서
    # feature.force_features_row_revision() 트리거가 +1 강제 — If-Match/ETag 낙관적
    # 동시성 validator.
    row_revision: Mapped[int] = mapped_column(
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


class FeatureStateTransitionRow(Base):
    """``feature.feature_state_transitions`` append-only full-tuple audit (ADR-090).

    ``feature_id``(현행 text business key)와 ``feature_uuid``(T39 final identity)에
    의도적으로 Feature FK가 없다. Feature hard purge 뒤에도 두 식별자와 state
    evidence가 남아야 하므로 cascade를 금지한다.
    """

    __tablename__ = "feature_state_transitions"
    __table_args__ = (
        CheckConstraint(
            "transition_kind IN ("
            "'initial','legacy_backfill','provider_sync','admin','user_request',"
            "'merge','quality_validation','system'"
            ")",
            name="kind",
        ),
        CheckConstraint(
            "btrim(reason_code) <> ''",
            name="reason",
        ),
        CheckConstraint(
            "btrim(principal) <> ''",
            name="principal",
        ),
        CheckConstraint(
            "(from_lifecycle_state IS NULL AND from_publication_state IS NULL "
            "AND from_quality_state IS NULL) OR ("
            "from_lifecycle_state IN ('active','retired') "
            "AND from_publication_state IN ('draft','published','suppressed') "
            "AND from_quality_state IN ('valid','quarantined') "
            "AND (from_lifecycle_state = 'active' OR from_publication_state = 'suppressed')"
            ")",
            name="old_tuple",
        ),
        CheckConstraint(
            "to_lifecycle_state IN ('active','retired') "
            "AND to_publication_state IN ('draft','published','suppressed') "
            "AND to_quality_state IN ('valid','quarantined') "
            "AND (to_lifecycle_state = 'active' OR to_publication_state = 'suppressed')",
            name="new_tuple",
        ),
        CheckConstraint(
            "(from_lifecycle_state IS NULL AND transition_kind IN ("
            "'initial','legacy_backfill','provider_sync'"
            ")) OR (from_lifecycle_state IS NOT NULL AND transition_kind NOT IN ("
            "'initial','legacy_backfill'"
            "))",
            name="initial_old_tuple",
        ),
        CheckConstraint(
            "(transition_kind = 'provider_sync' "
            "AND provider_dataset_id IS NOT NULL "
            "AND btrim(source_entity_key) <> '' "
            "AND btrim(source_record_key) <> '' "
            "AND jsonb_typeof(provider_evidence) = 'object' "
            "AND jsonb_typeof(provider_evidence -> 'authoritative_receipt') = 'string' "
            "AND btrim(provider_evidence ->> 'authoritative_receipt') <> '') "
            "OR (transition_kind <> 'provider_sync' "
            "AND provider_dataset_id IS NULL AND source_entity_key IS NULL "
            "AND source_record_key IS NULL AND provider_evidence IS NULL)",
            name="provider_provenance",
        ),
        CheckConstraint(
            "row_revision >= 1",
            name="row_revision",
        ),
        Index(
            "idx_feature_state_transitions_feature_occurred",
            "feature_id",
            "occurred_at",
            "transition_id",
        ),
        {"schema": "feature"},
    )

    transition_id: Mapped[int] = mapped_column(
        BigInteger,
        Identity(always=True),
        primary_key=True,
    )
    feature_id: Mapped[str] = mapped_column(Text, nullable=False)
    feature_uuid: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    from_lifecycle_state: Mapped[str | None] = mapped_column(Text)
    from_publication_state: Mapped[str | None] = mapped_column(Text)
    from_quality_state: Mapped[str | None] = mapped_column(Text)
    to_lifecycle_state: Mapped[str] = mapped_column(Text, nullable=False)
    to_publication_state: Mapped[str] = mapped_column(Text, nullable=False)
    to_quality_state: Mapped[str] = mapped_column(Text, nullable=False)
    transition_kind: Mapped[str] = mapped_column(Text, nullable=False)
    reason_code: Mapped[str] = mapped_column(Text, nullable=False)
    principal: Mapped[str] = mapped_column(Text, nullable=False)
    causation_ref: Mapped[str | None] = mapped_column(Text)
    provider_dataset_id: Mapped[int | None] = mapped_column(BigInteger)
    source_entity_key: Mapped[str | None] = mapped_column(Text)
    source_record_key: Mapped[str | None] = mapped_column(Text)
    provider_evidence: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    row_revision: Mapped[int] = mapped_column(BigInteger, nullable=False)
    invoker_role: Mapped[str] = mapped_column(Text, nullable=False)
    state_procedure_definer: Mapped[str] = mapped_column(Text, nullable=False)
    audit_writer_definer: Mapped[str] = mapped_column(Text, nullable=False)


# =============================================================================
# feature.feature_{places,events,notices,routes,areas}  (T-VN-35 typed subtype)
# =============================================================================
#
# 배타 arc(표준 typed-subtype 패턴): 각 subtype은 kind 상수 CHECK를 갖고
# ``(feature_id, kind)`` 복합 FK로 core를 참조한다 — 한 feature는 최대 한
# subtype에만 존재하고(core kind는 단일 값), subtype 행이 있는 동안 core
# kind 변경이 FK 위반으로 막힌다. ``(feature_id, feature_uuid)`` 복합 FK는
# 0083 ``feature_aliases`` 선례와 같은 identity 사본 일치 계약이다.
#
# T-VN-35(ADR-086 결정 4): core ``detail``/``geom``은 0086에서 **제거됐다**.
# kind별 값의 정본은 subtype 테이블이고, 응답용 ``detail``/``geom``은
# public projection과 snapshot materializer가 core+subtype을 명시적으로 직접
# 조립한다. 별도 detail bridge view는 T-VN-34C에서 제거됐다.


def _subtype_table_args(kind: str, *extra: Any) -> tuple[Any, ...]:
    """subtype 공통 제약 — kind 상수 CHECK + 배타 arc FK + identity 사본 FK."""
    table = f"feature_{kind}s"
    return (
        CheckConstraint(f"kind = '{kind}'", name=f"ck_{table}_kind"),
        ForeignKeyConstraint(
            ["feature_id", "kind"],
            ["feature.features.feature_id", "feature.features.kind"],
            name=conv(f"fk_{table}_feature_kind"),
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["feature_id", "feature_uuid"],
            ["feature.features.feature_id", "feature.features.feature_uuid"],
            name=conv(f"fk_{table}_identity_pair"),
            ondelete="CASCADE",
        ),
        *extra,
        {"schema": "feature"},
    )


class _FeatureSubtypeBase(Base):
    """subtype 공통 identity 컬럼 (추상 — 테이블을 만들지 않는다)."""

    __abstract__ = True

    feature_id: Mapped[str] = mapped_column(String, primary_key=True)
    feature_uuid: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    kind: Mapped[str] = mapped_column(String, nullable=False)


class FeaturePlaceRow(_FeatureSubtypeBase):
    """``feature.feature_places`` — place 전용 typed 컬럼 (dto ``PlaceDetail``)."""

    __tablename__ = "feature_places"
    __table_args__ = _subtype_table_args(
        "place",
        Index(
            "idx_feature_places_opening_hours",
            "feature_id",
            postgresql_where=text("business_hours IS NOT NULL"),
        ),
    )

    place_kind: Mapped[str] = mapped_column(String, nullable=False)
    phones: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'::text[]")
    )
    biz_number: Mapped[str | None] = mapped_column(String)
    license_date: Mapped[date | None] = mapped_column(Date)
    business_hours: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    facility_info: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    reviews_link: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )


class FeatureEventRow(_FeatureSubtypeBase):
    """``feature.feature_events`` — event 전용 typed 컬럼 (dto ``EventDetail``)."""

    __tablename__ = "feature_events"
    __table_args__ = _subtype_table_args(
        "event",
        CheckConstraint(
            "starts_on IS NULL OR ends_on IS NULL OR starts_on <= ends_on",
            name="ck_feature_events_period",
        ),
        Index(
            "idx_feature_events_period",
            "starts_on",
            "ends_on",
        ),
        Index(
            "idx_feature_events_opening_hours",
            "feature_id",
            postgresql_where=text("opening_hours IS NOT NULL"),
        ),
    )

    event_kind: Mapped[str] = mapped_column(String, nullable=False)
    starts_on: Mapped[date | None] = mapped_column(Date)
    ends_on: Mapped[date | None] = mapped_column(Date)
    timezone: Mapped[str] = mapped_column(
        String, nullable=False, server_default=text("'Asia/Seoul'")
    )
    opening_hours: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    venue_name: Mapped[str | None] = mapped_column(String)
    tel: Mapped[str | None] = mapped_column(String)
    content_id: Mapped[str | None] = mapped_column(String)
    content_type_id: Mapped[str | None] = mapped_column(String)
    area_code: Mapped[str | None] = mapped_column(String)
    sigungu_code: Mapped[str | None] = mapped_column(String)
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )


class FeatureNoticeRow(_FeatureSubtypeBase):
    """``feature.feature_notices`` — notice 전용 typed 컬럼 (dto ``NoticeDetail``).

    ``valid_start_time``/``valid_end_time``이 typed timestamptz가 되면서
    read 필터의 ``detail->>'valid_end_time'`` 파싱(+ ``pg_input_is_valid``
    방어 cast)이 소멸한다 — 35D의 최대 실익.
    """

    __tablename__ = "feature_notices"
    __table_args__ = _subtype_table_args(
        "notice",
        CheckConstraint(
            "severity IS NULL OR severity BETWEEN 0 AND 5",
            name="ck_feature_notices_severity",
        ),
        Index(
            "idx_feature_notices_validity",
            "valid_end_time",
            "valid_start_time",
        ),
    )

    notice_type: Mapped[str] = mapped_column(String, nullable=False)
    severity: Mapped[int | None] = mapped_column(SmallInteger)
    valid_start_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    valid_end_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_agency: Mapped[str | None] = mapped_column(String)
    officer_name: Mapped[str | None] = mapped_column(String)
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )


class FeatureRouteRow(_FeatureSubtypeBase):
    """``feature.feature_routes`` — route 전용 (geometry 정본이 여기로 이동)."""

    __tablename__ = "feature_routes"
    __table_args__ = _subtype_table_args(
        "route",
        Index(
            "idx_feature_routes_geom_gist",
            "geom",
            postgresql_using="gist",
            postgresql_where=text("public_ready"),
        ),
    )

    # core에서 이동한 geometry — route는 LineString 계열만 허용한다
    # (core의 GEOMETRY 느슨한 타입이 여기서 정확해진다).
    geom: Mapped[Any] = mapped_column(
        Geometry("MULTILINESTRING", srid=4326, spatial_index=False), nullable=False
    )
    # Core 3축의 DB-owned derived projection. Runtime은 이 열을 직접 쓸 수 없다.
    public_ready: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    route_type: Mapped[str] = mapped_column(String, nullable=False)
    geometry_source: Mapped[str | None] = mapped_column(String)
    geometry_status: Mapped[str | None] = mapped_column(String)
    total_distance_meters: Mapped[Any | None] = mapped_column(Numeric)
    expected_duration_minutes: Mapped[int | None] = mapped_column(Integer)
    difficulty: Mapped[str | None] = mapped_column(String)
    begin_name: Mapped[str | None] = mapped_column(String)
    begin_address: Mapped[str | None] = mapped_column(String)
    end_name: Mapped[str | None] = mapped_column(String)
    end_address: Mapped[str | None] = mapped_column(String)
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )


class FeatureAreaRow(_FeatureSubtypeBase):
    """``feature.feature_areas`` — area 전용 (geometry 정본이 여기로 이동)."""

    __tablename__ = "feature_areas"
    __table_args__ = _subtype_table_args(
        "area",
        Index(
            "idx_feature_areas_geom_gist",
            "geom",
            postgresql_using="gist",
            postgresql_where=text("public_ready"),
        ),
    )

    geom: Mapped[Any] = mapped_column(
        Geometry("MULTIPOLYGON", srid=4326, spatial_index=False), nullable=False
    )
    # Route와 같은 cross-relation index bridge; 독립 상태 정본이 아니다.
    public_ready: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    area_kind: Mapped[str] = mapped_column(String, nullable=False)
    boundary_source: Mapped[str | None] = mapped_column(String)
    area_square_meters: Mapped[Any | None] = mapped_column(Numeric)
    regulation_scope: Mapped[str | None] = mapped_column(String)
    administrative_office: Mapped[str | None] = mapped_column(String)
    description: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )


class FeatureAliasRow(Base):
    """``feature.feature_aliases`` — legacy ``f_*`` alias 보존 (T-VN-32A, ADR-068 결정 3).

    shadow 단계 구조: 실질 결합축은 legacy ``feature_id``(text FK)이고,
    ``feature_uuid``는 target 전환(T-VN-32C alias-map 이관) 때 재작성 없이
    그대로 쓰는 파생 사본이다. 컬럼·제약 이름은 freeze
    ``contracts/vnext/target-schema-v1.sql`` §4의 대응물과 정합한다
    (``pk_feature_aliases`` / ``fk_feature_aliases_feature`` /
    ``ck_feature_aliases_alias_canonical`` / ``ck_feature_aliases_kind_canonical`` /
    ``idx_feature_aliases_feature``).

    freeze가 미정으로 남긴 3건은 T-VN-32A가 결정했다 (alembic 0079 docstring):

    - alias_kind 값 집합 — 닫힌 CHECK ``('legacy_feature_id')``
    - FK ON DELETE — ``CASCADE`` (alias는 파생값·재계산 가능)
    - backfill generator — ``uuid5(FEATURE_UUID_NAMESPACE, feature_id)``

    행 생성은 0079 AFTER INSERT 트리거(``trg_features_legacy_alias``)가 feature
    INSERT와 같은 transaction에서 수행한다(원자 생성).
    """

    __tablename__ = "feature_aliases"
    __table_args__ = (
        CheckConstraint(
            "alias <> '' AND alias = btrim(alias)",
            name=conv("ck_feature_aliases_alias_canonical"),
        ),
        CheckConstraint(
            "alias_kind <> '' AND alias_kind = btrim(alias_kind)",
            name=conv("ck_feature_aliases_kind_canonical"),
        ),
        CheckConstraint(
            "alias_kind IN ('legacy_feature_id')",
            name=conv("ck_feature_aliases_alias_kind"),
        ),
        # T-VN-32C(0083) — 파생 CHECK 해제 후의 선언적 사본 일치: alias 행의
        # (feature_id, feature_uuid)는 정본 행의 쌍과 정확히 같아야 한다.
        ForeignKeyConstraint(
            ["feature_id", "feature_uuid"],
            ["feature.features.feature_id", "feature.features.feature_uuid"],
            name=conv("fk_feature_aliases_identity_pair"),
            # CASCADE 필수 — 기존 CASCADE FK와 공존 시 RI 트리거 이름순서
            # 의존을 제거한다(0083 docstring·적대 리뷰 1 H1 실측).
            ondelete="CASCADE",
        ),
        # 닫힌 kind 기간의 실질 불변식 — legacy alias는 자기 자신 (H1).
        CheckConstraint(
            "alias_kind <> 'legacy_feature_id' OR alias = feature_id",
            name=conv("ck_feature_aliases_legacy_identity"),
        ),
        Index("idx_feature_aliases_feature", "feature_id"),
        Index("idx_feature_aliases_feature_uuid", "feature_uuid"),
        # T-VN-32C alias-map 이관 표면의 keyset scan index (alembic 0081).
        # 실제 DDL은 `(alias COLLATE "C")`지만 PG 반영(reflection)은 index
        # collation을 노출하지 않아 metadata에 COLLATE 식을 쓰면 alembic
        # check가 영구 drift를 보고한다 — 컬럼 index로 선언해 반영과 정합
        # 시키고 COLLATE 정본은 0081 migration이 소유한다.
        Index("idx_feature_aliases_alias_c", "alias"),
        {"schema": "feature"},
    )

    alias: Mapped[str] = mapped_column(Text, primary_key=True)
    feature_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey(
            "feature.features.feature_id",
            ondelete="CASCADE",
            name=conv("fk_feature_aliases_feature"),
        ),
        nullable=False,
    )
    feature_uuid: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    alias_kind: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )


# =============================================================================
# provider_sync.provider_datasets / source lineage  (ADR-087)
# =============================================================================


class ProviderDatasetRow(Base):
    """DB가 소유하는 provider×dataset identity와 산출 capability."""

    __tablename__ = "provider_datasets"
    __table_args__ = (
        UniqueConstraint("provider", "dataset_key", name="uq_provider_datasets_identity"),
        CheckConstraint(
            "provider <> '' AND provider = btrim(provider) "
            "AND provider = normalize(provider, NFC) AND length(provider) <= 112",
            name="ck_provider_datasets_provider_canonical",
        ),
        CheckConstraint(
            "dataset_key <> '' AND dataset_key = btrim(dataset_key) "
            "AND dataset_key = normalize(dataset_key, NFC) AND length(dataset_key) <= 112",
            name="ck_provider_datasets_dataset_key_canonical",
        ),
        CheckConstraint(
            "display_name <> '' AND display_name = btrim(display_name) "
            "AND display_name = normalize(display_name, NFC) AND length(display_name) <= 256",
            name="ck_provider_datasets_display_name_canonical",
        ),
        CheckConstraint(
            "source_kind IN ('openapi', 'filedata', 'manual', 'system', 'standard', 'internal')",
            name="ck_provider_datasets_source_kind",
        ),
        CheckConstraint(
            "provider_sync.is_valid_provider_dataset_capabilities(capabilities)",
            name="ck_provider_datasets_capabilities",
        ),
        {"schema": "provider_sync"},
    )

    provider_dataset_id: Mapped[int] = mapped_column(
        BigInteger,
        Identity(always=True),
        primary_key=True,
    )
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    dataset_key: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    source_kind: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("true"),
    )
    capabilities: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        # NOTE: JSON 리터럴로 쓰면 ``:1``이 SQLAlchemy ``text()`` bind param으로
        # 잡혀 alembic autogenerate/check가 server-default 비교에서 크래시한다.
        # jsonb_build_object로 콜론을 없애 같은 기본값을 표현한다.
        server_default=text(
            "jsonb_build_object("
            "'schema_version', 1, "
            "'produces', jsonb_build_array(), "
            "'extensions', jsonb_build_object()"
            ")"
        ),
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


class ProviderDatasetOperationRow(Base):
    """Dataset별 enabled operation. scope는 별도 정규 child가 소유한다."""

    __tablename__ = "provider_dataset_operations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["provider_dataset_id"],
            ["provider_sync.provider_datasets.provider_dataset_id"],
            name="fk_provider_dataset_operations_dataset",
        ),
        UniqueConstraint(
            "provider_dataset_id",
            "operation_key",
            "operation_kind",
            name="uq_provider_dataset_operations_kind",
        ),
        CheckConstraint(
            "operation_key <> '' AND operation_key = btrim(operation_key) "
            "AND operation_key = normalize(operation_key, NFC) AND length(operation_key) <= 128",
            name="ck_provider_dataset_operations_key_canonical",
        ),
        CheckConstraint(
            "operation_kind IN ('feature_load', 'refresh', 'preview')",
            name="ck_provider_dataset_operations_kind",
        ),
        CheckConstraint(
            "jsonb_typeof(config) = 'object'",
            name="ck_provider_dataset_operations_config",
        ),
        Index(
            "idx_provider_dataset_operations_enabled",
            "provider_dataset_id",
            "operation_key",
            postgresql_where=text("is_enabled"),
        ),
        {"schema": "provider_sync"},
    )

    provider_dataset_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    operation_key: Mapped[str] = mapped_column(Text, primary_key=True)
    operation_kind: Mapped[str] = mapped_column(Text, nullable=False)
    is_enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("true"),
    )
    config: Mapped[dict[str, Any]] = mapped_column(
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


class ProviderDatasetOperationScopeRow(Base):
    """Refresh operation의 canonical scope child."""

    __tablename__ = "provider_dataset_operation_scopes"
    __table_args__ = (
        ForeignKeyConstraint(
            ["provider_dataset_id", "operation_key", "operation_kind"],
            [
                "provider_sync.provider_dataset_operations.provider_dataset_id",
                "provider_sync.provider_dataset_operations.operation_key",
                "provider_sync.provider_dataset_operations.operation_kind",
            ],
            name="fk_provider_dataset_operation_scopes_operation",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "operation_kind = 'refresh'",
            name="ck_provider_dataset_operation_scopes_refresh_only",
        ),
        CheckConstraint(
            "provider_sync.is_valid_provider_dataset_sync_scope(sync_scope)",
            name="ck_provider_dataset_operation_scopes_syntax",
        ),
        Index(
            "idx_provider_dataset_operation_scopes_operation",
            "provider_dataset_id",
            "operation_key",
        ),
        {"schema": "provider_sync"},
    )

    # DB PK는 triple이다(``pk_provider_dataset_operation_scopes``). 이 모듈은 raw SQL
    # 저장소의 Alembic ``target_metadata`` 원천이므로(모듈 docstring, ADR-004) 이
    # class를 ORM 방식으로 쓰는 코드는 없다 — identity map이 행을 접는 시나리오는
    # 이 저장소에서 도달하지 않는다. 실제 위험은 **아무 게이트도 이 어긋남을 보지
    # 못한다**는 것이다: alembic autogenerate는 PK 제약을 비교 대상에 넣지 않아
    # `alembic check`가 통과한다. 그래서 PK 전용 대조 게이트를 따로 세웠다
    # (``test_alembic_head_primary_keys_match_orm_declarations``).
    provider_dataset_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    sync_scope: Mapped[str] = mapped_column(Text, primary_key=True)
    operation_key: Mapped[str] = mapped_column(Text, primary_key=True)
    operation_kind: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        server_default=text("'refresh'"),
    )


class SourceEntityRow(Base):
    """Dataset FK 아래 provider 자연 entity. 현재 관측은 head가 소유한다."""

    __tablename__ = "source_entities"
    __table_args__ = (
        UniqueConstraint(
            "source_entity_key",
            "provider_dataset_id",
            name="uq_source_entities_key_dataset",
        ),
        UniqueConstraint(
            "provider_dataset_id",
            "source_entity_type",
            "source_entity_id",
            name="uq_source_entities_provider_identity",
        ),
        ForeignKeyConstraint(
            ["provider_dataset_id"],
            ["provider_sync.provider_datasets.provider_dataset_id"],
            name="fk_source_entities_provider_dataset",
        ),
        CheckConstraint(
            "first_seen_at <= last_seen_at",
            name="ck_source_entities_seen_order",
        ),
        CheckConstraint(
            "source_entity_type <> '' AND source_entity_type = btrim(source_entity_type) "
            "AND source_entity_type = normalize(source_entity_type, NFC) "
            "AND length(source_entity_type) <= 512",
            name="ck_source_entities_type_canonical",
        ),
        CheckConstraint(
            "source_entity_id <> '' AND source_entity_id = btrim(source_entity_id) "
            "AND source_entity_id = normalize(source_entity_id, NFC) "
            "AND length(source_entity_id) <= 512",
            name="ck_source_entities_id_canonical",
        ),
        Index(
            "idx_source_entities_provider_dataset",
            "provider_dataset_id",
        ),
        {"schema": "provider_sync"},
    )

    source_entity_key: Mapped[str] = mapped_column(Text, primary_key=True)
    provider_dataset_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source_entity_type: Mapped[str] = mapped_column(Text, nullable=False)
    source_entity_id: Mapped[str] = mapped_column(Text, nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class NoticeLifecycleScopeRow(Base):
    """notice lifecycle scope의 모드·적용 watermark·state fingerprint."""

    __tablename__ = "notice_lifecycle_scopes"
    __table_args__ = (
        ForeignKeyConstraint(
            ["provider_dataset_id"],
            ["provider_sync.provider_datasets.provider_dataset_id"],
            name="fk_notice_lifecycle_scopes_dataset",
        ),
        UniqueConstraint(
            "provider_dataset_id",
            "source_entity_type",
            name="uq_notice_lifecycle_scopes_identity",
        ),
        CheckConstraint(
            "mode IN ('snapshot', 'event')",
            name="ck_notice_lifecycle_scopes_mode",
        ),
        {"schema": "provider_sync"},
    )

    notice_lifecycle_scope_id: Mapped[int] = mapped_column(
        BigInteger,
        Identity(always=True),
        primary_key=True,
    )
    provider_dataset_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source_entity_type: Mapped[str] = mapped_column(Text, nullable=False)
    mode: Mapped[str] = mapped_column(Text, nullable=False)
    applied_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    state_fingerprint: Mapped[str] = mapped_column(Text, nullable=False)


class NoticeLineageStateRow(Base):
    """Authoritative notice snapshot에 알려진 계보의 최근 존재 상태."""

    __tablename__ = "notice_lineage_states"
    __table_args__ = (
        ForeignKeyConstraint(
            ["notice_lifecycle_scope_id"],
            ["provider_sync.notice_lifecycle_scopes.notice_lifecycle_scope_id"],
            name="fk_notice_lineage_states_scope",
            ondelete="CASCADE",
        ),
        Index(
            "idx_notice_lineage_states_scope_present",
            "notice_lifecycle_scope_id",
            "present",
            text("changed_at DESC"),
        ),
        {"schema": "provider_sync"},
    )

    notice_lifecycle_scope_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    lineage_key: Mapped[str] = mapped_column(Text, primary_key=True)
    present: Mapped[bool] = mapped_column(Boolean, nullable=False)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SourceRecordRow(Base):
    """``provider_sync.source_records`` row mapping.

    raw snapshot은 immutable이며 mutable 관측 시각·만료·current pointer는
    :class:`SourceEntityHeadRow`가 소유한다.
    """

    __tablename__ = "source_records"
    __table_args__ = (
        UniqueConstraint(
            "source_record_key",
            "source_entity_key",
            "fetched_at",
            name="uq_source_records_record_entity_fetched",
        ),
        UniqueConstraint(
            "source_entity_key",
            "raw_payload_hash",
            name="uq_source_records_entity_payload",
        ),
        UniqueConstraint(
            "source_entity_key",
            "source_record_key",
            name="uq_source_records_entity_record",
        ),
        Index(
            "idx_source_records_entity_history",
            "source_entity_key",
            text("fetched_at DESC"),
            text("imported_at DESC"),
            text("source_record_key DESC"),
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


class SourceEntityHeadRow(Base):
    """Entity의 검증된 immutable record head와 mutable observation 상태."""

    __tablename__ = "source_entity_heads"
    __table_args__ = (
        ForeignKeyConstraint(
            ["source_entity_key"],
            ["provider_sync.source_entities.source_entity_key"],
            name="fk_source_entity_heads_entity",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["source_entity_key", "current_source_record_key"],
            [
                "provider_sync.source_records.source_entity_key",
                "provider_sync.source_records.source_record_key",
            ],
            name="fk_source_entity_heads_record",
            ondelete="RESTRICT",
        ),
        Index(
            "idx_source_entity_heads_lineage",
            "lineage_key",
            text("observed_at DESC"),
            text("current_source_record_key DESC"),
        ),
        {"schema": "provider_sync"},
    )

    source_entity_key: Mapped[str] = mapped_column(Text, primary_key=True)
    current_source_record_key: Mapped[str] = mapped_column(Text, nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    # T-VN-33(0091)이 notice 계보 물화를 source_records에서 head로 옮겼다.
    # ``trg_source_entity_head_lineage_key``(ENABLE ALWAYS)가 값을 소유하므로
    # writer는 채우지 않는다 — metadata는 NOT NULL 물리 컬럼만 선언한다.
    lineage_key: Mapped[str] = mapped_column(String, nullable=False)


# =============================================================================
# provider_sync.source_links  (docs/architecture/data-model.md §3)
# =============================================================================


class SourceLinkRow(Base):
    """``provider_sync.source_links`` row mapping — Feature ↔ SourceEntity N:M.

    PK = ``(feature_id, source_entity_key)``. primary 판정은
    ``source_role = 'primary'`` 하나만 사용한다.
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
            postgresql_where=text("source_role = 'primary'"),
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
            "provider_dataset_id",
            name="uq_curated_sources_dataset",
        ),
        ForeignKeyConstraint(
            ["provider_dataset_id"],
            ["provider_sync.provider_datasets.provider_dataset_id"],
            name="fk_curated_sources_dataset",
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
        # ``uq_curated_sources_dataset``(UNIQUE)가 이미 provider_dataset_id 단일
        # 열 btree를 만든다 — 0090/freeze 계약 어디에도 같은 열의 별도 index는
        # 없다. 중복 선언은 metadata에만 존재하는 유령이었다.
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
    provider_dataset_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
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
            "external_component_id <> '' AND external_component_id = btrim(external_component_id)",
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
        ForeignKeyConstraint(
            ["current_import_row_id", "curation_item_id"],
            [
                "feature.curation_import_rows.import_row_id",
                "feature.curation_import_rows.curation_item_id",
            ],
            name=conv("fk_curation_items_current_import_row"),
            ondelete="RESTRICT",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            [
                "accepted_link_decision_id",
                "curation_item_id",
                "feature_id",
            ],
            [
                "feature.curation_link_decisions.decision_id",
                "feature.curation_link_decisions.curation_item_id",
                "feature.curation_link_decisions.feature_id",
            ],
            name=conv("fk_curation_items_accepted_link_decision"),
            ondelete="RESTRICT",
            deferrable=True,
            initially="DEFERRED",
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
    current_import_row_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False))
    accepted_link_decision_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False))
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


class CurationImportBatchRow(Base):
    """성공한 curation import 파일/정규화 row 집합의 append-only receipt."""

    __tablename__ = "curation_import_batches"
    __table_args__ = (
        CheckConstraint(
            "content_sha256 ~ '^[0-9a-f]{64}$'",
            name=conv("ck_curation_import_batches_sha256"),
        ),
        CheckConstraint(
            "batch_kind IN ('csv_upload','normalized_rows','forward_recovery')",
            name=conv("ck_curation_import_batches_kind"),
        ),
        CheckConstraint(
            "row_count >= 0",
            name=conv("ck_curation_import_batches_row_count"),
        ),
        CheckConstraint(
            "actor = btrim(actor) AND actor <> ''",
            name=conv("ck_curation_import_batches_actor"),
        ),
        CheckConstraint(
            "jsonb_typeof(metadata) = 'object'",
            name=conv("ck_curation_import_batches_metadata"),
        ),
        Index(
            "idx_curation_import_batches_sha_time",
            "content_sha256",
            text("imported_at DESC"),
            "import_batch_id",
        ),
        {"schema": "feature"},
    )

    import_batch_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        server_default=text("x_extension.gen_random_uuid()"),
    )
    content_sha256: Mapped[str] = mapped_column(Text, nullable=False)
    batch_kind: Mapped[str] = mapped_column(Text, nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    actor: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    imported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )


class CurationImportRowRow(Base):
    """한 import batch의 exact normalized source row evidence."""

    __tablename__ = "curation_import_rows"
    __table_args__ = (
        CheckConstraint(
            "row_number > 0",
            name=conv("ck_curation_import_rows_row_number"),
        ),
        CheckConstraint(
            "source_row_sha256 ~ '^[0-9a-f]{64}$'",
            name=conv("ck_curation_import_rows_sha256"),
        ),
        CheckConstraint(
            "jsonb_typeof(row_payload) = 'object'",
            name=conv("ck_curation_import_rows_payload"),
        ),
        CheckConstraint(
            "jsonb_typeof(provenance) = 'object'",
            name=conv("ck_curation_import_rows_provenance"),
        ),
        ForeignKeyConstraint(
            ["import_batch_id"],
            ["feature.curation_import_batches.import_batch_id"],
            name=conv("fk_curation_import_rows_batch"),
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["curation_item_id"],
            ["feature.curation_items.curation_item_id"],
            name=conv("fk_curation_import_rows_item"),
            ondelete="RESTRICT",
            # dedup merge의 legacy-conflict detach가 curation_items.curation_item_id를
            # 재작성한다(`merge_repo._DETACH_CONFLICTING_LEGACY_CURATION_ITEMS_SQL`).
            # NO ACTION(기본값)이면 그 UPDATE 자체가 FK 위반을 낸다 — T-VN-H41,
            # `0074_curation_item_rekey_cascade`.
            onupdate="CASCADE",
        ),
        UniqueConstraint(
            "import_batch_id",
            "row_number",
            name=conv("uq_curation_import_rows_batch_row"),
        ),
        UniqueConstraint(
            "import_row_id",
            "curation_item_id",
            name=conv("uq_curation_import_rows_item_pointer"),
        ),
        Index(
            "idx_curation_import_rows_item_time",
            "curation_item_id",
            text("imported_at DESC"),
            "import_row_id",
        ),
        {"schema": "feature"},
    )

    import_row_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        server_default=text("x_extension.gen_random_uuid()"),
    )
    import_batch_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        nullable=False,
    )
    curation_item_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        nullable=False,
    )
    row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    source_row_sha256: Mapped[str] = mapped_column(Text, nullable=False)
    row_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    provenance: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    imported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )


class CurationLinkDecisionRow(Base):
    """Feature link 승인·철회의 append-only 운영 결정."""

    __tablename__ = "curation_link_decisions"
    __table_args__ = (
        CheckConstraint(
            "decision_kind IN ('accepted','revoked')",
            name=conv("ck_curation_link_decisions_kind"),
        ),
        CheckConstraint(
            # 값 목록은 `curation_link_basis`가 소유한다. 여기 열거하면 값이 늘 때
            # 세 곳(DB CHECK / 공개·merge 술어 / 이 metadata)이 따로 놀게 된다.
            f"match_basis IN ({_sql_text_literals(tuple(sorted(ALL_LINK_BASES)))})",
            name=conv("ck_curation_link_decisions_basis"),
        ),
        CheckConstraint(
            "resolver_version = btrim(resolver_version) AND resolver_version <> ''",
            name=conv("ck_curation_link_decisions_resolver"),
        ),
        CheckConstraint(
            "jsonb_typeof(evidence) = 'object'",
            name=conv("ck_curation_link_decisions_evidence"),
        ),
        CheckConstraint(
            "actor = btrim(actor) AND actor <> ''",
            name=conv("ck_curation_link_decisions_actor"),
        ),
        CheckConstraint(
            "supersedes_decision_id IS DISTINCT FROM decision_id",
            name=conv("ck_curation_link_decisions_not_self_superseding"),
        ),
        ForeignKeyConstraint(
            ["curation_item_id"],
            ["feature.curation_items.curation_item_id"],
            name=conv("fk_curation_link_decisions_item"),
            ondelete="RESTRICT",
            # T-VN-H41 — `fk_curation_import_rows_item`과 같은 이유.
            onupdate="CASCADE",
        ),
        ForeignKeyConstraint(
            ["import_row_id", "curation_item_id"],
            [
                "feature.curation_import_rows.import_row_id",
                "feature.curation_import_rows.curation_item_id",
            ],
            name=conv("fk_curation_link_decisions_import_row"),
            ondelete="RESTRICT",
            # item이 재작성되면 import row 쪽도 위 FK로 먼저 캐스케이드된다. 이
            # 합성 FK도 같이 캐스케이드하지 않으면 그 직후 자기모순 상태가 된다.
            onupdate="CASCADE",
        ),
        ForeignKeyConstraint(
            ["supersedes_decision_id", "curation_item_id"],
            [
                "feature.curation_link_decisions.decision_id",
                "feature.curation_link_decisions.curation_item_id",
            ],
            name=conv("fk_curation_link_decisions_supersedes"),
            ondelete="RESTRICT",
            # supersedes 사슬은 전부 같은 item에 묶여 있다는 불변식을 이 합성
            # 키가 강제한다. item이 재작성되면 사슬 전체가 같이 옮겨가야 한다.
            onupdate="CASCADE",
        ),
        UniqueConstraint(
            "decision_id",
            "curation_item_id",
            name=conv("uq_curation_link_decisions_item_pointer"),
        ),
        UniqueConstraint(
            "decision_id",
            "curation_item_id",
            "feature_id",
            name=conv("uq_curation_link_decisions_item_target"),
        ),
        Index(
            "idx_curation_link_decisions_item_time",
            "curation_item_id",
            text("decided_at DESC"),
            "decision_id",
        ),
        Index(
            "idx_curation_link_decisions_basis_time",
            "match_basis",
            text("decided_at DESC"),
            "decision_id",
        ),
        {"schema": "feature"},
    )

    decision_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        server_default=text("x_extension.gen_random_uuid()"),
    )
    curation_item_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        nullable=False,
    )
    feature_id: Mapped[str] = mapped_column(Text, nullable=False)
    import_row_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False))
    decision_kind: Mapped[str] = mapped_column(Text, nullable=False)
    match_basis: Mapped[str] = mapped_column(Text, nullable=False)
    resolver_version: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    actor: Mapped[str] = mapped_column(Text, nullable=False)
    decided_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    supersedes_decision_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False))


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
    """``provider_sync.provider_sync_state`` row mapping — exact operation cursor 추적."""

    __tablename__ = "provider_sync_state"
    __table_args__ = (
        ForeignKeyConstraint(
            ["provider_dataset_id", "sync_scope", "operation_key"],
            [
                "provider_sync.provider_dataset_operation_scopes.provider_dataset_id",
                "provider_sync.provider_dataset_operation_scopes.sync_scope",
                "provider_sync.provider_dataset_operation_scopes.operation_key",
            ],
            name="fk_provider_sync_state_exact_operation_scope",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "status IN ('active','paused','disabled','failed')",
            name="provider_sync_state_status",
        ),
        Index(
            "idx_provider_sync_state_next_run",
            "next_run_after",
            postgresql_where=text("status='active'"),
        ),
        {"schema": "provider_sync"},
    )

    provider_dataset_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    sync_scope: Mapped[str] = mapped_column(String, primary_key=True)
    operation_key: Mapped[str] = mapped_column(Text, primary_key=True)
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
    (``target_feature_id``)에 이미 영속한 immutable source record를 ENRICHMENT
    link으로 잇는다. source의 provider/dataset/entity 식별과 raw payload는 queue에
    중복 저장하지 않고 canonical source entity/record를 join해 읽는다. ``status``은
    pending→accepted/rejected/ignored, ``name_score``는 0~100 ``NUMERIC(5,2)``이다.
    ``(target_feature_id, source_entity_key)``가 재스캔 identity이며 pending 행만
    점수·표시 이름·후보 record를 최신으로 바꾼다.
    """

    __tablename__ = "enrichment_review_queue"
    __table_args__ = (
        UniqueConstraint(
            "target_feature_id",
            "source_entity_key",
            name="uq_enrichment_review_candidate",
        ),
        ForeignKeyConstraint(
            ["source_entity_key"],
            ["provider_sync.source_entities.source_entity_key"],
            name="fk_enrichment_review_queue_source_entity",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["source_entity_key", "source_record_key"],
            [
                "provider_sync.source_records.source_entity_key",
                "provider_sync.source_records.source_record_key",
            ],
            name="fk_enrichment_review_queue_source_record",
            ondelete="RESTRICT",
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
        # 0090이 만든 index는 (source_entity_key, source_record_key) 2열이다 —
        # ``fk_enrichment_review_queue_source_record``를 그대로 뒷받침하고
        # source_entity_key 단독 조회는 선행 prefix로 함께 처리한다.
        Index(
            "idx_enrichment_review_queue_source_entity_record",
            "source_entity_key",
            "source_record_key",
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
    source_entity_key: Mapped[str] = mapped_column(Text, nullable=False)
    source_record_key: Mapped[str] = mapped_column(Text, nullable=False)
    source_name: Mapped[str] = mapped_column(String, nullable=False)
    target_name: Mapped[str] = mapped_column(String, nullable=False)
    name_score: Mapped[Any] = mapped_column(Numeric(5, 2), nullable=False)
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
# T-VN-36 field override lineage (ADR-091)
# =============================================================================


class FeatureOverrideFieldPathRow(Base):
    """``ops.feature_override_field_paths``의 고정 typed field registry.

    registry 문자열은 SQL 식별자로 실행되지 않는다. T-VN-36 command procedure가
    이 행을 allow-list로 읽은 뒤, path별 정적 assignment만 수행한다.
    """

    __tablename__ = "feature_override_field_paths"
    __table_args__ = (
        CheckConstraint(
            "field_path <> '' AND field_path = btrim(field_path)",
            name="ck_feature_override_field_paths_canonical",
        ),
        CheckConstraint(
            "feature_kind IN ('*','place','event','notice','route','area')",
            name="ck_feature_override_field_paths_kind",
        ),
        CheckConstraint(
            "target_relation IN ('features','feature_places','feature_events',"
            "'feature_notices','feature_routes','feature_areas')",
            name="ck_feature_override_field_paths_relation",
        ),
        CheckConstraint(
            "value_kind IN ('text','integer','numeric','boolean','json_object',"
            "'json_array','text_array','date','timestamptz','uuid','geometry')",
            name="ck_feature_override_field_paths_value_kind",
        ),
        CheckConstraint(
            "geometry_type IS NULL OR geometry_type IN "
            "('POINT','MULTILINESTRING','MULTIPOLYGON')",
            name="ck_feature_override_field_paths_geometry_type",
        ),
        CheckConstraint(
            "(value_kind = 'geometry' AND geometry_type IS NOT NULL) OR "
            "(value_kind <> 'geometry' AND geometry_type IS NULL)",
            name="ck_feature_override_field_paths_geometry_kind",
        ),
        UniqueConstraint(
            "feature_kind",
            "target_relation",
            "target_column",
            name="uq_feature_override_field_paths_target",
        ),
        {"schema": "ops"},
    )

    field_path: Mapped[str] = mapped_column(Text, primary_key=True)
    feature_kind: Mapped[str] = mapped_column(Text, nullable=False)
    target_relation: Mapped[str] = mapped_column(Text, nullable=False)
    target_column: Mapped[str] = mapped_column(Text, nullable=False)
    value_kind: Mapped[str] = mapped_column(Text, nullable=False)
    geometry_type: Mapped[str | None] = mapped_column(Text)
    allows_null: Mapped[bool] = mapped_column(Boolean, nullable=False)
    requires_source: Mapped[bool] = mapped_column(Boolean, nullable=False)
    provider_writable: Mapped[bool] = mapped_column(Boolean, nullable=False)
    operator_writable: Mapped[bool] = mapped_column(Boolean, nullable=False)
    sort_order: Mapped[int] = mapped_column(SmallInteger, nullable=False)


class FeatureBaseFieldValueRow(Base):
    """``feature.feature_base_field_values``의 최신 canonical provider base.

    행 부재는 원천이 아직 해당 field를 관측하지 않았음을 뜻하며 JSON ``null``과
    다르다. geometry는 JSON으로 다운캐스트하지 않고 별도 PostGIS 열에 보존한다.
    """

    __tablename__ = "feature_base_field_values"
    __table_args__ = (
        CheckConstraint(
            "base_revision >= 1",
            name="ck_feature_base_field_values_revision",
        ),
        CheckConstraint(
            "(value_json IS NULL) <> (value_geometry IS NULL)",
            name="ck_feature_base_field_values_single_value",
        ),
        CheckConstraint(
            "btrim(source_raw_payload_hash) <> ''",
            name="ck_feature_base_field_values_source_hash",
        ),
        ForeignKeyConstraint(
            ["feature_id", "feature_uuid"],
            ["feature.features.feature_id", "feature.features.feature_uuid"],
            name="fk_feature_base_field_values_feature_identity",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["field_path"],
            ["ops.feature_override_field_paths.field_path"],
            name="fk_feature_base_field_values_field_path",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["provider_dataset_id"],
            ["provider_sync.provider_datasets.provider_dataset_id"],
            name="fk_feature_base_field_values_dataset",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["source_entity_key"],
            ["provider_sync.source_entities.source_entity_key"],
            name="fk_feature_base_field_values_entity",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["source_record_key"],
            ["provider_sync.source_records.source_record_key"],
            name="fk_feature_base_field_values_record",
            ondelete="RESTRICT",
        ),
        Index(
            "idx_feature_base_field_values_source",
            "provider_dataset_id",
            "source_entity_key",
            "source_record_key",
        ),
        {"schema": "feature"},
    )

    feature_id: Mapped[str] = mapped_column(String, primary_key=True)
    field_path: Mapped[str] = mapped_column(Text, primary_key=True)
    feature_uuid: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    provider_dataset_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source_entity_key: Mapped[str] = mapped_column(String, nullable=False)
    source_record_key: Mapped[str] = mapped_column(String, nullable=False)
    source_raw_payload_hash: Mapped[str] = mapped_column(Text, nullable=False)
    value_json: Mapped[dict[str, Any] | str | int | float | bool | None] = mapped_column(JSONB)
    value_geometry: Mapped[Any | None] = mapped_column(
        Geometry("GEOMETRY", srid=4326, spatial_index=False)
    )
    base_revision: Mapped[int] = mapped_column(BigInteger, nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class FeatureOverrideRow(Base):
    """``ops.feature_overrides`` row mapping.

    active operator intent와 revoke tombstone을 보존한다. T-VN-36에서는
    ``feature_base_field_values``의 canonical provider base와 분리되고, generic
    field path는 registry/typed command를 거쳐서만 materialize된다. lifecycle path는
    ADR-090의 별도 state command가 계속 소유한다.
    """

    __tablename__ = "feature_overrides"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active','inactive','superseded','revoked')",
            name="ck_overrides_status",
        ),
        CheckConstraint(
            "field_path <> 'lifecycle_state' OR ("
            "jsonb_typeof(override_value) = 'string' "
            "AND override_value #>> '{}' IN ('active','retired')"
            ")",
            name="lifecycle_state_value",
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
    source_provider_dataset_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(
            "provider_sync.provider_datasets.provider_dataset_id", ondelete="SET NULL"
        ),
    )
    source_entity_key: Mapped[str | None] = mapped_column(
        String,
        ForeignKey(
            "provider_sync.source_entities.source_entity_key", ondelete="SET NULL"
        ),
    )
    source_raw_payload_hash: Mapped[str | None] = mapped_column(Text)
    field_path: Mapped[str] = mapped_column(Text, nullable=False)
    source_value: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    override_value: Mapped[dict[str, Any] | str | int | float | bool | None] = mapped_column(JSONB)
    value_geometry: Mapped[Any | None] = mapped_column(
        Geometry("GEOMETRY", srid=4326, spatial_index=False)
    )
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
    command_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("ops.domain_commands.command_id", ondelete="RESTRICT"),
    )
    base_revision: Mapped[int | None] = mapped_column(BigInteger)
    created_by: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_by: Mapped[str | None] = mapped_column(Text)
    revoked_reason: Mapped[str | None] = mapped_column(Text)


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
            "trigger_kind IS NULL OR trigger_kind IN "
            "('schedule','manual','sensor','update_request','backfill','system')",
            name="ck_import_jobs_trigger_kind",
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
            "(kind = 'provider_feature_load_run' "
            "AND operation_key IS NOT NULL "
            "AND operation_key = btrim(operation_key) AND operation_key <> '') "
            "OR (kind <> 'provider_feature_load_run' AND operation_key IS NULL)",
            name="ck_import_jobs_operation_key_shape",
        ),
        CheckConstraint(
            "dagster_run_status IS NULL OR "
            "(kind = 'provider_feature_load_run' AND dagster_run_status IN "
            "('QUEUED','NOT_STARTED','MANAGED','STARTING','STARTED','CANCELING',"
            "'SUCCESS','FAILURE','CANCELED'))",
            name="ck_import_jobs_dagster_run_status",
        ),
        CheckConstraint(
            "dataset_membership_mode IN ('root','single','multiple')",
            name="ck_import_jobs_membership_mode",
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
    dataset_membership_mode: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        server_default=text("'root'"),
    )
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
    # root/component 멤버십을 stamp한다(ADR-077) — read-time 재귀 lineage 제거.
    # DB 트리거가 parent에서 파생(자식은 부모의 root 승계, root는 자기 자신).
    root_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    root_kind: Mapped[str] = mapped_column(Text, nullable=False)
    trigger_kind: Mapped[str | None] = mapped_column(Text)
    operation_key: Mapped[str | None] = mapped_column(Text)
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
# ops.c6c_cancel_probe_fixtures  (ADR-086 / T-VN-41F1J)
# =============================================================================


class C6cCancelProbeFixtureRow(Base):
    """Map이 소유하는 runless cancel-probe fixture의 durable receipt."""

    __tablename__ = "c6c_cancel_probe_fixtures"
    __table_args__ = (
        CheckConstraint(
            "state IN ('armed','consumed','finalized')",
            name="ck_c6c_cancel_probe_fixtures_state",
        ),
        CheckConstraint(
            "(state = 'armed' AND cancellation_id IS NULL "
            " AND consumed_at IS NULL AND finalized_at IS NULL) OR "
            "(state = 'consumed' AND cancellation_id IS NOT NULL "
            " AND consumed_at IS NOT NULL AND finalized_at IS NULL) OR "
            "(state = 'finalized' AND cancellation_id IS NOT NULL "
            " AND consumed_at IS NOT NULL AND finalized_at IS NOT NULL "
            " AND finalized_at >= consumed_at)",
            name="ck_c6c_cancel_probe_fixtures_transition",
        ),
        ForeignKeyConstraint(
            ["job_id"],
            ["ops.import_jobs.job_id"],
            name="fk_c6c_cancel_probe_fixtures_job",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["cancellation_id"],
            ["ops.pipeline_cancellations.cancellation_id"],
            name="fk_c6c_cancel_probe_fixtures_cancellation",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("job_id", name="uq_c6c_cancel_probe_fixtures_job"),
        UniqueConstraint(
            "cancellation_id",
            name="uq_c6c_cancel_probe_fixtures_cancellation",
        ),
        {"schema": "ops"},
    )

    transaction_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
    )
    job_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    state: Mapped[str] = mapped_column(Text, nullable=False)
    cancellation_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("clock_timestamp()"),
    )
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# =============================================================================
# ops.import_job_datasets  (ADR-087)
# =============================================================================


class ImportJobDatasetRow(Base):
    """단일 import job에 snapshot된 canonical dataset-operation member."""

    __tablename__ = "import_job_datasets"
    __table_args__ = (
        ForeignKeyConstraint(
            ["job_id"],
            ["ops.import_jobs.job_id"],
            name="fk_import_job_datasets_job",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "job_id",
            "provider_dataset_id",
            "sync_scope",
            "operation_key",
            name="uq_import_job_datasets_exact_identity",
        ),
        ForeignKeyConstraint(
            ["provider_dataset_id", "sync_scope", "operation_key"],
            [
                "provider_sync.provider_dataset_operation_scopes.provider_dataset_id",
                "provider_sync.provider_dataset_operation_scopes.sync_scope",
                "provider_sync.provider_dataset_operation_scopes.operation_key",
            ],
            name="fk_import_job_datasets_exact_operation_scope",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "job_id",
            "import_job_dataset_id",
            name="uq_import_job_datasets_job_member",
        ),
        Index(
            "idx_import_job_datasets_exact_operation_job",
            "provider_dataset_id",
            "sync_scope",
            "operation_key",
            "job_id",
        ),
        {"schema": "ops"},
    )

    import_job_dataset_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        server_default=text("x_extension.gen_random_uuid()"),
    )
    job_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    provider_dataset_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sync_scope: Mapped[str] = mapped_column(Text, nullable=False)
    operation_key: Mapped[str] = mapped_column(Text, nullable=False)
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
        ForeignKeyConstraint(
            ["job_id", "import_job_dataset_id"],
            [
                "ops.import_job_datasets.job_id",
                "ops.import_job_datasets.import_job_dataset_id",
            ],
            name="fk_import_job_events_job_member",
            ondelete="RESTRICT",
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
            "idx_import_job_events_level_time",
            "level",
            text("occurred_at DESC"),
            text("event_id DESC"),
            postgresql_where=text("quarantined_at IS NULL"),
        ),
        # keyset은 ``(occurred_at, event_id)``다 — tiebreaker가 빠지면 페이지마다
        # Sort가 붙는다. 부분 술어도 질의의 ``quarantined_at IS NULL``과 같아야
        # 격리 행을 훑지 않는다 (0057이 갖고 있던 두 보증).
        # ``level``은 key가 아니라 INCLUDE다: dataset scope 조회는 member 마다
        # 상위 limit만 뽑아 합치는데, level filter가 heap을 때리면 member 수에
        # 비례한 random I/O가 살아난다. INCLUDE로 두면 그 scan이 index-only로
        # 남고 key 순서(=keyset 정렬)는 건드리지 않는다.
        Index(
            "idx_import_job_events_member_time",
            "import_job_dataset_id",
            text("occurred_at DESC"),
            text("event_id DESC"),
            postgresql_include=["level"],
            postgresql_where=text(
                "import_job_dataset_id IS NOT NULL AND quarantined_at IS NULL"
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
    import_job_dataset_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False))
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
        CheckConstraint(
            "(status = 'deleting') = (delete_command_id IS NOT NULL)",
            name="ck_offline_uploads_delete_owner",
        ),
        # offline upload도 실행 membership이라 scope PK와 같은 triple을 참조한다
        # (ADR-088 §결정 2). pair FK로 두면 scope PK가 triple인 이상 붙지 않는다.
        ForeignKeyConstraint(
            ["provider_dataset_id", "sync_scope", "operation_key"],
            [
                "provider_sync.provider_dataset_operation_scopes.provider_dataset_id",
                "provider_sync.provider_dataset_operation_scopes.sync_scope",
                "provider_sync.provider_dataset_operation_scopes.operation_key",
            ],
            name="fk_offline_uploads_exact_operation_scope",
            ondelete="RESTRICT",
        ),
        # 멱등 키는 identity triple + checksum 4열이다(alembic 0092). writer의
        # ``ON CONFLICT``가 이 열 집합을 중재자로 지목하므로 여기와
        # ``offline_upload_repo._RESERVE_SQL``이 어긋나면 42P10으로 죽는다.
        #
        # 3열(0090~0091)로 두면 identity와 모순이었다: 같은 (dataset, scope)에
        # 형제 refresh operation을 등록하는 것은 scope PK가 triple이 된 뒤로 정상
        # write인데, 멱등 키가 operation을 안 보면 operation을 교체한 뒤 같은 파일을
        # 다시 올릴 때 **없어진 operation에 결박된 옛 행**이 UNIQUE 위반을 냈다.
        # 형제 membership 테이블의 identity UNIQUE도 ``operation_key``를 포함한다
        # (uq_import_job_datasets_exact_identity = job_id + triple,
        # uq_feature_update_request_datasets_identity = request_id + triple).
        UniqueConstraint(
            "provider_dataset_id",
            "sync_scope",
            "operation_key",
            "checksum_sha256",
            name="uq_offline_uploads_dataset_scope_checksum",
        ),
        Index(
            "idx_offline_uploads_dataset_created",
            "provider_dataset_id",
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
    provider_dataset_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sync_scope: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        server_default=text("'dataset_wide'"),
    )
    operation_key: Mapped[str] = mapped_column(Text, nullable=False)
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
    delete_command_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("ops.domain_commands.command_id", ondelete="RESTRICT"),
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
            "ops.is_valid_feature_update_policy(update_policy)",
            name=conv("ck_feature_update_requests_update_policy_shape"),
        ),
        CheckConstraint(
            "dataset_membership_mode IN ('single','multiple')",
            name="ck_feature_update_requests_membership_mode",
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
        {"schema": "ops"},
    )

    request_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        server_default=text("x_extension.gen_random_uuid()"),
    )
    scope_type: Mapped[str] = mapped_column(Text, nullable=False)
    scope: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    dataset_membership_mode: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        server_default=text("'single'"),
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


class FeatureUpdateRequestDatasetRow(Base):
    """feature update request가 생성 시점에 고정한 canonical dataset/scope snapshot."""

    __tablename__ = "feature_update_request_datasets"
    __table_args__ = (
        ForeignKeyConstraint(
            ["request_id"],
            ["ops.feature_update_requests.request_id"],
            name="fk_feature_update_request_datasets_request",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["provider_dataset_id", "sync_scope", "operation_key"],
            [
                "provider_sync.provider_dataset_operation_scopes.provider_dataset_id",
                "provider_sync.provider_dataset_operation_scopes.sync_scope",
                "provider_sync.provider_dataset_operation_scopes.operation_key",
            ],
            name="fk_feature_update_request_datasets_exact_operation_scope",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "request_id",
            "provider_dataset_id",
            "sync_scope",
            "operation_key",
            name="uq_feature_update_request_datasets_identity",
        ),
        # 조회는 ``scoped_request_seeds``(pipeline_repo) 한 곳뿐이고 술어는
        # provider_dataset_id 하나, 투영은 request_id 하나다 — 0090/freeze 계약이
        # 정한 2열이 그 경로를 index-only로 덮는다. scope/operation을 중간에
        # 끼우면 index만 넓어지고 얻는 것이 없다.
        Index(
            "idx_feature_update_request_datasets_dataset_request",
            "provider_dataset_id",
            "request_id",
        ),
        {"schema": "ops"},
    )

    feature_update_request_dataset_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        server_default=text("x_extension.gen_random_uuid()"),
    )
    request_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    provider_dataset_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sync_scope: Mapped[str] = mapped_column(Text, nullable=False)
    operation_key: Mapped[str] = mapped_column(Text, nullable=False)


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


class BackupCommandExecutionRow(Base):
    """Backup/restore side effect의 explicit recovery state machine."""

    __tablename__ = "backup_command_executions"
    __table_args__ = (
        CheckConstraint(
            "effect_kind IN ('create', 'delete', 'restore', 'swap')",
            name=conv("ck_backup_command_executions_effect_kind"),
        ),
        CheckConstraint(
            "phase IN ('prepared', 'effect_started', 'effect_succeeded')",
            name=conv("ck_backup_command_executions_phase"),
        ),
        CheckConstraint(
            "input_digest ~ '^[0-9a-f]{64}$'",
            name=conv("ck_backup_command_executions_input_digest"),
        ),
        CheckConstraint(
            "effect_token ~ '^[0-9a-f]{64}$'",
            name=conv("ck_backup_command_executions_effect_token"),
        ),
        CheckConstraint(
            "marker_key ~ '^[a-z0-9][a-z0-9_.-]{0,127}$'",
            name=conv("ck_backup_command_executions_marker_key"),
        ),
        CheckConstraint(
            "(effect_kind <> 'delete') OR "
            "(prepared_result IS NOT NULL "
            "AND jsonb_typeof(prepared_result) = 'object')",
            name=conv("ck_backup_command_executions_delete_result"),
        ),
        CheckConstraint(
            "(phase = 'prepared' AND effect_started_at IS NULL "
            "AND effect_completed_at IS NULL AND output_digest IS NULL "
            "AND marker_sha256 IS NULL) OR "
            "(phase = 'effect_started' AND effect_started_at IS NOT NULL "
            "AND effect_completed_at IS NULL AND output_digest IS NULL "
            "AND marker_sha256 IS NULL) OR "
            "(phase = 'effect_succeeded' AND effect_started_at IS NOT NULL "
            "AND effect_completed_at IS NOT NULL "
            "AND output_digest IS NOT NULL "
            "AND output_digest ~ '^[0-9a-f]{64}$' "
            "AND marker_sha256 IS NOT NULL "
            "AND marker_sha256 ~ '^[0-9a-f]{64}$')",
            name=conv("ck_backup_command_executions_phase_evidence"),
        ),
        {"schema": "ops"},
    )

    command_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("ops.domain_commands.command_id", ondelete="RESTRICT"),
        primary_key=True,
    )
    effect_kind: Mapped[str] = mapped_column(Text, nullable=False)
    effect_token: Mapped[str] = mapped_column(Text, nullable=False)
    phase: Mapped[str] = mapped_column(Text, nullable=False)
    backup_id: Mapped[str] = mapped_column(Text, nullable=False)
    app_db: Mapped[str | None] = mapped_column(Text)
    dagster_db: Mapped[str | None] = mapped_column(Text)
    rustfs_volume: Mapped[str | None] = mapped_column(Text)
    marker_key: Mapped[str] = mapped_column(Text, nullable=False)
    input_digest: Mapped[str] = mapped_column(Text, nullable=False)
    prepared_result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    output_digest: Mapped[str | None] = mapped_column(Text)
    marker_sha256: Mapped[str | None] = mapped_column(Text)
    prepared_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    effect_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    effect_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OfflineUploadCommandExecutionRow(Base):
    """Offline object/Dagster side effect의 explicit recovery state machine."""

    __tablename__ = "offline_upload_command_executions"
    __table_args__ = (
        CheckConstraint(
            "effect_kind IN ('create', 'delete', 'load')",
            name=conv("ck_offline_upload_command_executions_effect_kind"),
        ),
        CheckConstraint(
            "phase IN ('prepared', 'effect_started', 'effect_succeeded')",
            name=conv("ck_offline_upload_command_executions_phase"),
        ),
        CheckConstraint(
            "input_digest ~ '^[0-9a-f]{64}$'",
            name=conv("ck_offline_upload_command_executions_input_digest"),
        ),
        CheckConstraint(
            "(effect_kind <> 'create') OR "
            "(storage_backend IS NOT NULL AND btrim(storage_backend) <> '' "
            "AND bucket IS NOT NULL AND btrim(bucket) <> '' "
            "AND storage_key IS NOT NULL AND btrim(storage_key) <> '' "
            "AND content_type IS NOT NULL AND btrim(content_type) <> '' "
            "AND byte_size IS NOT NULL AND byte_size > 0 "
            "AND content_sha256 IS NOT NULL "
            "AND content_sha256 ~ '^[0-9a-f]{64}$' "
            "AND metadata_digest IS NOT NULL "
            "AND metadata_digest ~ '^[0-9a-f]{64}$')",
            name=conv("ck_offline_upload_command_executions_create_identity"),
        ),
        CheckConstraint(
            "(phase = 'prepared' AND effect_started_at IS NULL "
            "AND effect_completed_at IS NULL AND output_digest IS NULL "
            "AND dagster_run_id IS NULL) OR "
            "(phase = 'effect_started' AND effect_started_at IS NOT NULL "
            "AND effect_completed_at IS NULL AND output_digest IS NULL "
            "AND dagster_run_id IS NULL) OR "
            "(phase = 'effect_succeeded' AND effect_started_at IS NOT NULL "
            "AND effect_completed_at IS NOT NULL "
            "AND output_digest IS NOT NULL "
            "AND output_digest ~ '^[0-9a-f]{64}$')",
            name=conv("ck_offline_upload_command_executions_phase_evidence"),
        ),
        CheckConstraint(
            "(effect_kind <> 'load' OR phase <> 'effect_succeeded') OR "
            "(load_job_id IS NOT NULL AND dagster_run_id IS NOT NULL "
            "AND btrim(dagster_run_id) <> '')",
            name=conv("ck_offline_upload_command_executions_load_proof"),
        ),
        {"schema": "ops"},
    )

    command_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("ops.domain_commands.command_id", ondelete="RESTRICT"),
        primary_key=True,
    )
    effect_kind: Mapped[str] = mapped_column(Text, nullable=False)
    phase: Mapped[str] = mapped_column(Text, nullable=False)
    upload_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    storage_backend: Mapped[str | None] = mapped_column(Text)
    bucket: Mapped[str | None] = mapped_column(Text)
    storage_key: Mapped[str | None] = mapped_column(Text)
    content_type: Mapped[str | None] = mapped_column(Text)
    byte_size: Mapped[int | None] = mapped_column(BigInteger)
    content_sha256: Mapped[str | None] = mapped_column(Text)
    metadata_digest: Mapped[str | None] = mapped_column(Text)
    load_job_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False))
    dagster_run_id: Mapped[str | None] = mapped_column(Text)
    input_digest: Mapped[str] = mapped_column(Text, nullable=False)
    output_digest: Mapped[str | None] = mapped_column(Text)
    prepared_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    effect_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    effect_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# =============================================================================
# ops.cache_target_writer_drain_*  (T-VN-41D private control plane)
# =============================================================================


class CacheTargetWriterDrainLeaseRow(Base):
    """Map writer drain의 durable owner lease (공개 REST 미노출)."""

    __tablename__ = "cache_target_writer_drain_leases"
    __table_args__ = (
        UniqueConstraint(
            "owner_kind",
            "owner_id",
            name=conv("uq_cache_target_writer_drain_leases_owner"),
        ),
        CheckConstraint(
            f"owner_kind IN ({_sql_text_literals(WRITER_DRAIN_OWNER_KINDS)})",
            name=conv("ck_cache_target_writer_drain_leases_owner_kind"),
        ),
        CheckConstraint(
            f"state IN ({_sql_text_literals(WRITER_DRAIN_LEASE_STATES)})",
            name=conv("ck_cache_target_writer_drain_leases_state"),
        ),
        CheckConstraint(
            "snapshot_sha256 ~ '^[0-9a-f]{64}$'",
            name=conv("ck_cache_target_writer_drain_leases_snapshot_sha256"),
        ),
        CheckConstraint(
            "receipt_sha256 IS NULL OR receipt_sha256 ~ '^[0-9a-f]{64}$'",
            name=conv("ck_cache_target_writer_drain_leases_receipt_sha256"),
        ),
        CheckConstraint(
            "receipt_prior_sha256 IS NULL OR receipt_prior_sha256 ~ '^[0-9a-f]{64}$'",
            name=conv("ck_cache_target_writer_drain_leases_receipt_prior_sha256"),
        ),
        CheckConstraint(
            "failure_code IS NULL OR failure_code ~ '^[A-Z][A-Z0-9_]{0,63}$'",
            name=conv("ck_cache_target_writer_drain_leases_failure_code"),
        ),
        CheckConstraint(
            "(state <> 'draining') = (receipt_sha256 IS NOT NULL "
            "AND receipt_operation IS NOT NULL) AND "
            "(receipt_operation IS NULL OR receipt_operation IN "
            f"({_sql_text_literals(WRITER_DRAIN_RECEIPT_OPERATIONS)}))",
            name=conv("ck_cache_target_writer_drain_leases_receipt"),
        ),
        CheckConstraint(
            "(state = 'restored') = (restored_at IS NOT NULL)",
            name=conv("ck_cache_target_writer_drain_leases_restored_at"),
        ),
        Index(
            "uq_cache_target_writer_drain_leases_active",
            text("(1)"),
            unique=True,
            postgresql_where=text("state IN ('draining','drained','restoring')"),
        ),
        Index(
            "idx_cache_target_writer_drain_leases_owner_history",
            "owner_kind",
            "owner_id",
            text("created_at DESC"),
        ),
        {"schema": "ops"},
    )

    lease_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        server_default=text("x_extension.gen_random_uuid()"),
    )
    owner_kind: Mapped[str] = mapped_column(Text, nullable=False)
    owner_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    state: Mapped[str] = mapped_column(Text, nullable=False)
    snapshot_sha256: Mapped[str] = mapped_column(Text, nullable=False)
    receipt_sha256: Mapped[str | None] = mapped_column(Text)
    receipt_operation: Mapped[str | None] = mapped_column(Text)
    receipt_prior_sha256: Mapped[str | None] = mapped_column(Text)
    failure_code: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("clock_timestamp()"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("clock_timestamp()"),
    )
    restored_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CacheTargetWriterDrainInstigationRow(Base):
    """lease 시작 당시 schedule/sensor의 exact identity와 원래 상태."""

    __tablename__ = "cache_target_writer_drain_instigations"
    __table_args__ = (
        CheckConstraint(
            f"kind IN ({_sql_text_literals(WRITER_DRAIN_INSTIGATION_KINDS)})",
            name=conv("ck_cache_target_writer_drain_instigations_kind"),
        ),
        CheckConstraint(
            "selector_id = btrim(selector_id) AND selector_id <> '' AND "
            "state_id = btrim(state_id) AND state_id <> '' AND "
            "origin_id = btrim(origin_id) AND origin_id <> '' AND "
            "instigation_name = btrim(instigation_name) AND instigation_name <> '' AND "
            "repository_name = btrim(repository_name) AND repository_name <> '' AND "
            "repository_location_name = btrim(repository_location_name) "
            "AND repository_location_name <> ''",
            name=conv("ck_cache_target_writer_drain_instigations_identity"),
        ),
        CheckConstraint(
            f"pause_result IN ({_sql_text_literals(WRITER_DRAIN_PAUSE_RESULTS)}) AND "
            f"restore_result IN ({_sql_text_literals(WRITER_DRAIN_RESTORE_RESULTS)})",
            name=conv("ck_cache_target_writer_drain_instigations_results"),
        ),
        CheckConstraint(
            "(was_running AND pause_result <> 'not_required') OR "
            "(NOT was_running AND pause_result = 'not_required' "
            "AND restore_result = 'not_requested')",
            name=conv("ck_cache_target_writer_drain_instigations_original_state"),
        ),
        ForeignKeyConstraint(
            ["lease_id"],
            ["ops.cache_target_writer_drain_leases.lease_id"],
            ondelete="RESTRICT",
            name=conv("fk_cache_target_writer_drain_instigations_lease"),
        ),
        Index(
            "idx_cache_target_writer_drain_instigations_lease",
            "lease_id",
        ),
        {"schema": "ops"},
    )

    lease_id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    kind: Mapped[str] = mapped_column(Text, primary_key=True)
    selector_id: Mapped[str] = mapped_column(Text, primary_key=True)
    state_id: Mapped[str] = mapped_column(Text, nullable=False)
    origin_id: Mapped[str] = mapped_column(Text, nullable=False)
    instigation_name: Mapped[str] = mapped_column(Text, nullable=False)
    repository_name: Mapped[str] = mapped_column(Text, nullable=False)
    repository_location_name: Mapped[str] = mapped_column(Text, nullable=False)
    was_running: Mapped[bool] = mapped_column(Boolean, nullable=False)
    pause_result: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        server_default=text("'pending'"),
    )
    paused_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    restore_result: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        server_default=text("'not_requested'"),
    )
    restored_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CacheTargetWriterDrainRunRow(Base):
    """lease가 발견한 Dagster run과 terminal cancel의 one-shot reservation."""

    __tablename__ = "cache_target_writer_drain_runs"
    __table_args__ = (
        CheckConstraint(
            "dagster_run_id = btrim(dagster_run_id) AND dagster_run_id <> '' AND "
            "initial_status = btrim(initial_status) AND initial_status <> ''",
            name=conv("ck_cache_target_writer_drain_runs_identity"),
        ),
        CheckConstraint(
            f"cancel_result IN ({_sql_text_literals(WRITER_DRAIN_CANCEL_RESULTS)})",
            name=conv("ck_cache_target_writer_drain_runs_cancel_result"),
        ),
        CheckConstraint(
            "terminal_status IS NULL OR terminal_status ~ '^[A-Z_]+$'",
            name=conv("ck_cache_target_writer_drain_runs_terminal_status"),
        ),
        CheckConstraint(
            "(cancel_result = 'pending' AND cancel_reserved_at IS NULL "
            "AND cancel_dispatched_at IS NULL AND terminal_status IS NULL) OR "
            "(cancel_result IN ('reserved','outcome_uncertain') "
            "AND cancel_reserved_at IS NOT NULL AND cancel_dispatched_at IS NULL "
            "AND terminal_status IS NULL) OR "
            "(cancel_result = 'dispatched' AND cancel_reserved_at IS NOT NULL "
            "AND cancel_dispatched_at IS NOT NULL AND terminal_status IS NULL) OR "
            "(cancel_result = 'terminal' AND terminal_status IS NOT NULL)",
            name=conv("ck_cache_target_writer_drain_runs_cancel_evidence"),
        ),
        ForeignKeyConstraint(
            ["lease_id"],
            ["ops.cache_target_writer_drain_leases.lease_id"],
            ondelete="RESTRICT",
            name=conv("fk_cache_target_writer_drain_runs_lease"),
        ),
        Index("idx_cache_target_writer_drain_runs_lease", "lease_id"),
        {"schema": "ops"},
    )

    lease_id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    dagster_run_id: Mapped[str] = mapped_column(Text, primary_key=True)
    initial_status: Mapped[str] = mapped_column(Text, nullable=False)
    cancel_result: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        server_default=text("'pending'"),
    )
    cancel_reserved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    terminal_status: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("clock_timestamp()"),
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
# ops.integrity_observation_* / data_integrity_violations / poi_cache_*
# =============================================================================


class IntegrityObservationScopeRow(Base):
    """canonical dataset별 monotonic observation generation fence."""

    __tablename__ = "integrity_observation_scopes"
    __table_args__ = (
        ForeignKeyConstraint(
            ["provider_dataset_id"],
            ["provider_sync.provider_datasets.provider_dataset_id"],
            name="fk_integrity_observation_scopes_dataset",
        ),
        UniqueConstraint(
            "provider_dataset_id",
            name="uq_integrity_observation_scopes_dataset",
        ),
        CheckConstraint(
            "latest_generation >= 0 "
            "AND latest_authoritative_generation >= 0 "
            "AND latest_authoritative_generation <= latest_generation",
            name=conv("ck_integrity_observation_scopes_generations"),
        ),
        {"schema": "ops"},
    )

    integrity_observation_scope_id: Mapped[int] = mapped_column(
        BigInteger,
        Identity(always=True),
        primary_key=True,
    )
    provider_dataset_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    latest_generation: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        server_default=text("0"),
    )
    latest_authoritative_generation: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        server_default=text("0"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )


class IntegrityObservationRunRow(Base):
    """한 external Dagster run의 불변 generation과 authoritative receipt."""

    __tablename__ = "integrity_observation_runs"
    __table_args__ = (
        CheckConstraint(
            "generation > 0",
            name=conv("ck_integrity_observation_runs_generation"),
        ),
        CheckConstraint(
            "external_run_id = btrim(external_run_id) AND external_run_id <> ''",
            name=conv("ck_integrity_observation_runs_external_run"),
        ),
        CheckConstraint(
            "status IN ('collecting','authoritative','superseded')",
            name=conv("ck_integrity_observation_runs_status"),
        ),
        CheckConstraint(
            "source_observations >= 0 "
            "AND findings_observed >= 0 "
            "AND findings_unique >= 0 "
            "AND findings_upserted >= 0 "
            "AND findings_unique <= findings_observed "
            "AND findings_upserted <= findings_unique",
            name=conv("ck_integrity_observation_runs_counts"),
        ),
        CheckConstraint(
            "(status = 'collecting' AND completed_at IS NULL) "
            "OR (status IN ('authoritative','superseded') "
            "AND completed_at IS NOT NULL)",
            name=conv("ck_integrity_observation_runs_completion"),
        ),
        ForeignKeyConstraint(
            ["integrity_observation_scope_id"],
            ["ops.integrity_observation_scopes.integrity_observation_scope_id"],
            name=conv("fk_integrity_observation_runs_scope"),
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "integrity_observation_scope_id",
            "generation",
            name=conv("uq_integrity_observation_runs_generation_v2"),
        ),
        UniqueConstraint(
            "integrity_observation_scope_id",
            "external_run_id",
            name=conv("uq_integrity_observation_runs_external_run_v2"),
        ),
        Index(
            "idx_integrity_observation_runs_scope_status",
            "integrity_observation_scope_id",
            "status",
            text("generation DESC"),
        ),
        {"schema": "ops"},
    )

    observation_run_id: Mapped[int] = mapped_column(
        BigInteger,
        Identity(always=True),
        primary_key=True,
    )
    integrity_observation_scope_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    generation: Mapped[int] = mapped_column(BigInteger, nullable=False)
    external_run_id: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        server_default=text("'collecting'"),
    )
    source_observations: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        server_default=text("0"),
    )
    findings_observed: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        server_default=text("0"),
    )
    findings_unique: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        server_default=text("0"),
    )
    findings_upserted: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        server_default=text("0"),
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class IntegrityFindingObservationRow(Base):
    """observation run이 실제로 본 dedupe key의 불변 집합."""

    __tablename__ = "integrity_finding_observations"
    __table_args__ = (
        CheckConstraint(
            "dedupe_key ~ '^av2_[0-9a-f]{64}$'",
            name=conv("ck_integrity_finding_observations_key"),
        ),
        ForeignKeyConstraint(
            ["observation_run_id"],
            ["ops.integrity_observation_runs.observation_run_id"],
            name=conv("fk_integrity_finding_observations_run"),
            ondelete="CASCADE",
        ),
        Index(
            "idx_integrity_finding_observations_key_run",
            "dedupe_key",
            "observation_run_id",
        ),
        {"schema": "ops"},
    )

    observation_run_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    dedupe_key: Mapped[str] = mapped_column(Text, primary_key=True)
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )


class DataIntegrityViolationRow(Base):
    """``ops.data_integrity_violations`` row mapping — 이슈 1건 = 운영 큐 1행."""

    __tablename__ = "data_integrity_violations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["provider_dataset_id"],
            ["provider_sync.provider_datasets.provider_dataset_id"],
            name="fk_data_integrity_violations_dataset",
        ),
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
            postgresql_where=text("status IN ('open', 'acknowledged') AND payload ? 'dedupe_key'"),
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
            "idx_data_integrity_violations_dataset_status",
            "provider_dataset_id",
            "status",
            text("last_seen_at DESC"),
            postgresql_where=text("provider_dataset_id IS NOT NULL"),
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
    provider_dataset_id: Mapped[int | None] = mapped_column(BigInteger)
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
            f"btrim(external_system, {_CANONICAL_WHITESPACE_SQL}) "
            "AND external_system = normalize(external_system, NFC)",
            name=conv("ck_poi_cache_targets_external_system_identity"),
        ),
        CheckConstraint(
            "target_key <> '' AND char_length(target_key) <= 512 "
            "AND target_key = "
            f"btrim(target_key, {_CANONICAL_WHITESPACE_SQL}) "
            "AND target_key = normalize(target_key, NFC)",
            name=conv("ck_poi_cache_targets_target_key_identity"),
        ),
        Index(
            "uq_poi_cache_targets_active_key",
            "external_system",
            "target_key",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index(
            "uq_poi_cache_targets_source_identity",
            "target_id",
            "external_system",
            "target_key",
            unique=True,
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
        ForeignKeyConstraint(
            ["provider_dataset_id"],
            ["provider_sync.provider_datasets.provider_dataset_id"],
            name="fk_poi_cache_target_feature_links_dataset",
        ),
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
            "idx_poi_cache_target_feature_links_dataset",
            "provider_dataset_id",
            postgresql_where=text("active AND provider_dataset_id IS NOT NULL"),
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
    provider_dataset_id: Mapped[int | None] = mapped_column(BigInteger)
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


class PoiCacheTargetStreamRow(Base):
    """외부 system별 cache target stream control."""

    __tablename__ = "poi_cache_target_streams"
    __table_args__ = (
        CheckConstraint(
            "external_system <> '' AND char_length(external_system) <= 112 "
            "AND external_system = "
            f"btrim(external_system, {_CANONICAL_WHITESPACE_SQL}) "
            "AND external_system = normalize(external_system, NFC)",
            name=conv("ck_cache_target_streams_external_system"),
        ),
        CheckConstraint(
            "btrim(consumer_id) <> '' AND char_length(consumer_id) <= 128",
            name=conv("ck_cache_target_streams_consumer"),
        ),
        CheckConstraint(
            "restore_epoch > 0 AND control_version > 0",
            name=conv("ck_cache_target_streams_versions"),
        ),
        CheckConstraint(
            "status IN ('ready','fenced','blocked')",
            name=conv("ck_cache_target_streams_status"),
        ),
        CheckConstraint(
            "(status = 'blocked') = (blocked_event_id IS NOT NULL)",
            name=conv("ck_cache_target_streams_blocked"),
        ),
        {"schema": "ops"},
    )

    external_system: Mapped[str] = mapped_column(Text, primary_key=True)
    consumer_id: Mapped[str] = mapped_column(Text, nullable=False)
    restore_epoch: Mapped[int] = mapped_column(BigInteger, nullable=False)
    control_version: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        server_default=text("1"),
    )
    status: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        server_default=text("'fenced'"),
    )
    blocked_event_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey(
            "ops.poi_cache_target_outbox_events.event_id",
            name="fk_cache_target_streams_blocked_event",
            ondelete="RESTRICT",
        ),
    )
    last_barrier_command_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(
            "ops.domain_commands.command_id",
            name="fk_cache_target_streams_barrier_command",
            ondelete="RESTRICT",
        ),
    )
    consumer_enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("false"),
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


class PoiCacheTargetRestoreFenceRow(Base):
    """restore epoch CAS와 barrier receipt의 불변 이력."""

    __tablename__ = "poi_cache_target_restore_fences"
    __table_args__ = (
        CheckConstraint(
            "request_fingerprint ~ '^[0-9a-f]{64}$'",
            name=conv("ck_cache_target_restore_fences_fingerprint"),
        ),
        CheckConstraint(
            "restore_epoch = previous_restore_epoch + 1",
            name=conv("ck_cache_target_restore_fences_epoch"),
        ),
        CheckConstraint(
            "control_version = previous_control_version + 1",
            name=conv("ck_cache_target_restore_fences_version"),
        ),
        CheckConstraint(
            "superseded_delivery_count >= 0",
            name=conv("ck_cache_target_restore_fences_superseded_count"),
        ),
        CheckConstraint(
            "invalidated_claim_count >= 0",
            name=conv("ck_cache_target_restore_fences_invalidated_claim_count"),
        ),
        CheckConstraint(
            "(superseded_reconciliation_count = 0 "
            "AND superseded_reconciliation_request_id IS NULL) OR "
            "(superseded_reconciliation_count = 1 "
            "AND superseded_reconciliation_request_id IS NOT NULL)",
            name=conv("ck_cache_target_restore_fences_superseded_reconciliation"),
        ),
        CheckConstraint(
            "btrim(reason) <> '' AND char_length(reason) <= 1000",
            name=conv("ck_cache_target_restore_fences_reason"),
        ),
        UniqueConstraint(
            "command_id",
            name=conv("uq_cache_target_restore_fences_command"),
        ),
        UniqueConstraint(
            "external_system",
            "restore_epoch",
            name=conv("uq_cache_target_restore_fences_epoch"),
        ),
        ForeignKeyConstraint(
            ["external_system", "superseded_reconciliation_request_id"],
            [
                "ops.poi_cache_target_reconciliation_requests.external_system",
                "ops.poi_cache_target_reconciliation_requests.request_id",
            ],
            name="fk_cache_target_restore_fences_superseded_reconciliation",
            ondelete="RESTRICT",
        ),
        {"schema": "ops"},
    )

    fence_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        server_default=text("x_extension.gen_random_uuid()"),
    )
    external_system: Mapped[str] = mapped_column(
        Text,
        ForeignKey(
            "ops.poi_cache_target_streams.external_system",
            name="fk_cache_target_restore_fences_stream",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    consumer_id: Mapped[str] = mapped_column(Text, nullable=False)
    command_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "ops.domain_commands.command_id",
            name="fk_cache_target_restore_fences_command",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    previous_restore_epoch: Mapped[int] = mapped_column(BigInteger, nullable=False)
    restore_epoch: Mapped[int] = mapped_column(BigInteger, nullable=False)
    previous_control_version: Mapped[int] = mapped_column(BigInteger, nullable=False)
    control_version: Mapped[int] = mapped_column(BigInteger, nullable=False)
    invalidated_claim_count: Mapped[int] = mapped_column(BigInteger, nullable=False)
    superseded_delivery_count: Mapped[int] = mapped_column(BigInteger, nullable=False)
    superseded_reconciliation_count: Mapped[int] = mapped_column(BigInteger, nullable=False)
    superseded_reconciliation_request_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False),
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )


class PoiCacheTargetSourceHeadRow(Base):
    """natural key별 source generation head와 durable tombstone."""

    __tablename__ = "poi_cache_target_source_heads"
    __table_args__ = (
        CheckConstraint(
            "source_payload_fingerprint ~ '^[0-9a-f]{64}$'",
            name=conv("ck_cache_target_source_heads_fingerprint"),
        ),
        CheckConstraint(
            "target_key <> '' AND char_length(target_key) <= 512 "
            "AND target_key = "
            f"btrim(target_key, {_CANONICAL_WHITESPACE_SQL}) "
            "AND target_key = normalize(target_key, NFC)",
            name=conv("ck_cache_target_source_heads_key"),
        ),
        CheckConstraint(
            "state IN ('active','deleted')",
            name=conv("ck_cache_target_source_heads_state"),
        ),
        CheckConstraint(
            "restore_epoch > 0 AND source_generation > 0 AND target_sequence >= 0",
            name=conv("ck_cache_target_source_heads_versions"),
        ),
        CheckConstraint(
            "state <> 'active' OR target_id IS NOT NULL",
            name=conv("ck_cache_target_source_heads_active_target"),
        ),
        ForeignKeyConstraint(
            ["target_id", "external_system", "target_key"],
            [
                "ops.poi_cache_targets.target_id",
                "ops.poi_cache_targets.external_system",
                "ops.poi_cache_targets.target_key",
            ],
            name=conv("fk_cache_target_source_heads_target"),
            ondelete="RESTRICT",
        ),
        Index(
            "idx_cache_target_source_heads_target",
            "target_id",
            unique=True,
            postgresql_where=text("target_id IS NOT NULL"),
        ),
        {"schema": "ops"},
    )

    external_system: Mapped[str] = mapped_column(
        Text,
        ForeignKey(
            "ops.poi_cache_target_streams.external_system",
            name="fk_cache_target_source_heads_stream",
            ondelete="RESTRICT",
        ),
        primary_key=True,
    )
    target_key: Mapped[str] = mapped_column(Text, primary_key=True)
    target_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False))
    state: Mapped[str] = mapped_column(Text, nullable=False)
    restore_epoch: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source_generation: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source_payload_fingerprint: Mapped[str] = mapped_column(Text, nullable=False)
    last_source_event_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey(
            "ops.poi_cache_target_source_events.event_id",
            name="fk_cache_target_source_heads_last_event",
            ondelete="RESTRICT",
            deferrable=True,
            initially="DEFERRED",
        ),
    )
    target_sequence: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        server_default=text("0"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )


class PoiCacheTargetSourceEventRow(Base):
    """source command의 immutable event/replay ledger."""

    __tablename__ = "poi_cache_target_source_events"
    __table_args__ = (
        CheckConstraint(
            "request_fingerprint ~ '^[0-9a-f]{64}$'",
            name=conv("ck_cache_target_source_events_request_fingerprint"),
        ),
        CheckConstraint(
            "source_payload_fingerprint ~ '^[0-9a-f]{64}$'",
            name=conv("ck_cache_target_source_events_payload_fingerprint"),
        ),
        CheckConstraint(
            "operation IN ('upsert','delete')",
            name=conv("ck_cache_target_source_events_operation"),
        ),
        CheckConstraint(
            "outcome IN ('applied','stale')",
            name=conv("ck_cache_target_source_events_outcome"),
        ),
        CheckConstraint(
            "restore_epoch > 0 AND source_generation > 0",
            name=conv("ck_cache_target_source_events_versions"),
        ),
        CheckConstraint(
            "target_lock_version IS NULL OR target_lock_version > 0",
            name=conv("ck_cache_target_source_events_target_lock_version"),
        ),
        CheckConstraint(
            "outcome <> 'applied' OR "
            "(target_id IS NOT NULL AND target_lock_version IS NOT NULL)",
            name=conv("ck_cache_target_source_events_applied_target_receipt"),
        ),
        ForeignKeyConstraint(
            ["external_system", "target_key"],
            [
                "ops.poi_cache_target_source_heads.external_system",
                "ops.poi_cache_target_source_heads.target_key",
            ],
            name=conv("fk_cache_target_source_events_head"),
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "external_system",
            "idempotency_key",
            name=conv("uq_cache_target_source_events_idempotency"),
        ),
        UniqueConstraint(
            "external_system",
            "target_key",
            "restore_epoch",
            "source_generation",
            name=conv("uq_cache_target_source_events_generation"),
        ),
        Index(
            "idx_cache_target_source_events_head_time",
            "external_system",
            "target_key",
            text("recorded_at DESC"),
            "event_id",
        ),
        {"schema": "ops"},
    )

    event_id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    external_system: Mapped[str] = mapped_column(Text, nullable=False)
    target_key: Mapped[str] = mapped_column(Text, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    operation: Mapped[str] = mapped_column(Text, nullable=False)
    restore_epoch: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source_generation: Mapped[int] = mapped_column(BigInteger, nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(Text, nullable=False)
    source_payload_fingerprint: Mapped[str] = mapped_column(Text, nullable=False)
    outcome: Mapped[str] = mapped_column(Text, nullable=False)
    target_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey(
            "ops.poi_cache_targets.target_id",
            name="fk_cache_target_source_events_target",
            ondelete="RESTRICT",
        ),
    )
    target_lock_version: Mapped[int | None] = mapped_column(BigInteger)
    refresh_request_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey(
            "ops.feature_update_requests.request_id",
            name="fk_cache_target_source_events_refresh_request",
            ondelete="RESTRICT",
        ),
    )
    job_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey(
            "ops.import_jobs.job_id",
            name="fk_cache_target_source_events_job",
            ondelete="RESTRICT",
        ),
    )
    domain_command_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(
            "ops.domain_commands.command_id",
            name="fk_cache_target_source_events_domain_command",
            ondelete="RESTRICT",
        ),
    )
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )


class PoiCacheTargetRefreshMemberRow(Base):
    """refresh request 시작 시 캡처한 target source stamp."""

    __tablename__ = "poi_cache_target_refresh_members"
    __table_args__ = (
        CheckConstraint(
            "restore_epoch > 0 AND source_generation > 0",
            name=conv("ck_cache_target_refresh_members_versions"),
        ),
        ForeignKeyConstraint(
            ["external_system", "target_key"],
            [
                "ops.poi_cache_target_source_heads.external_system",
                "ops.poi_cache_target_source_heads.target_key",
            ],
            name=conv("fk_cache_target_refresh_members_head"),
            ondelete="RESTRICT",
        ),
        Index(
            "idx_cache_target_refresh_members_target",
            "target_id",
            "request_id",
        ),
        {"schema": "ops"},
    )

    request_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey(
            "ops.feature_update_requests.request_id",
            name="fk_cache_target_refresh_members_request",
            ondelete="RESTRICT",
        ),
        primary_key=True,
    )
    target_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey(
            "ops.poi_cache_targets.target_id",
            name="fk_cache_target_refresh_members_target",
            ondelete="RESTRICT",
        ),
        primary_key=True,
    )
    external_system: Mapped[str] = mapped_column(Text, nullable=False)
    target_key: Mapped[str] = mapped_column(Text, nullable=False)
    restore_epoch: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source_generation: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )


class PoiCacheTargetReconciliationRequestRow(Base):
    """operator가 요청한 snapshot reconciliation lifecycle."""

    __tablename__ = "poi_cache_target_reconciliation_requests"
    __table_args__ = (
        CheckConstraint(
            "btrim(reason) <> '' AND char_length(reason) <= 1000",
            name=conv("ck_cache_target_reconciliation_requests_reason"),
        ),
        CheckConstraint(
            "status IN ('preparing','running','succeeded','failed','superseded')",
            name=conv("ck_cache_target_reconciliation_requests_status"),
        ),
        CheckConstraint(
            "phase_version > 0",
            name=conv("ck_cache_target_reconciliation_requests_phase_version"),
        ),
        CheckConstraint(
            "expected_merkle_root IS NULL OR "
            "expected_merkle_root ~ '^[0-9a-f]{64}$'",
            name=conv("ck_cache_target_reconciliation_requests_expected_root"),
        ),
        CheckConstraint(
            "actual_merkle_root IS NULL OR actual_merkle_root ~ '^[0-9a-f]{64}$'",
            name=conv("ck_cache_target_reconciliation_requests_actual_root"),
        ),
        CheckConstraint(
            "(status = 'preparing' AND started_at IS NOT NULL "
            "AND completed_at IS NULL AND snapshot_id IS NULL "
            "AND expected_merkle_root IS NULL AND actual_merkle_root IS NULL "
            "AND error_code IS NULL) OR "
            "(status = 'running' AND started_at IS NOT NULL "
            "AND completed_at IS NULL AND snapshot_id IS NOT NULL "
            "AND expected_merkle_root IS NOT NULL AND actual_merkle_root IS NULL "
            "AND error_code IS NULL) OR "
            "(status = 'succeeded' AND started_at IS NOT NULL "
            "AND completed_at IS NOT NULL AND snapshot_id IS NOT NULL "
            "AND expected_merkle_root IS NOT NULL AND actual_merkle_root IS NOT NULL "
            "AND error_code IS NULL) OR "
            "(status = 'failed' AND started_at IS NOT NULL "
            "AND completed_at IS NOT NULL AND snapshot_id IS NOT NULL "
            "AND expected_merkle_root IS NOT NULL AND actual_merkle_root IS NOT NULL "
            "AND error_code IS NOT NULL) OR "
            "(status = 'superseded' AND started_at IS NOT NULL "
            "AND completed_at IS NOT NULL AND actual_merkle_root IS NULL "
            "AND error_code = 'restore_fenced' AND "
            "((snapshot_id IS NULL AND expected_merkle_root IS NULL) OR "
            "(snapshot_id IS NOT NULL AND expected_merkle_root IS NOT NULL)))",
            name=conv("ck_cache_target_reconciliation_requests_lifecycle"),
        ),
        UniqueConstraint(
            "command_id",
            name=conv("uq_cache_target_reconciliation_requests_command"),
        ),
        UniqueConstraint(
            "external_system",
            "request_id",
            name=conv("uq_cache_target_reconciliation_requests_stream_request"),
        ),
        Index(
            "idx_cache_target_reconciliation_requests_stream_status",
            "external_system",
            "status",
            text("created_at DESC"),
            "request_id",
        ),
        Index(
            "idx_cache_target_reconciliation_requests_snapshot_status",
            "snapshot_id",
            "status",
            postgresql_where=text("snapshot_id IS NOT NULL"),
        ),
        Index(
            "uq_cache_target_reconciliation_requests_active_stream",
            "external_system",
            unique=True,
            postgresql_where=text("status IN ('preparing','running')"),
        ),
        {"schema": "ops"},
    )

    request_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        server_default=text("x_extension.gen_random_uuid()"),
    )
    external_system: Mapped[str] = mapped_column(
        Text,
        ForeignKey(
            "ops.poi_cache_target_streams.external_system",
            name="fk_cache_target_reconciliation_requests_stream",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    command_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "ops.domain_commands.command_id",
            name="fk_cache_target_reconciliation_requests_command",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        server_default=text("'preparing'"),
    )
    phase_version: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        server_default=text("1"),
    )
    snapshot_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey(
            "ops.poi_cache_target_snapshots.snapshot_id",
            name="fk_cache_target_reconciliation_requests_snapshot",
            ondelete="RESTRICT",
        ),
    )
    expected_merkle_root: Mapped[str | None] = mapped_column(Text)
    actual_merkle_root: Mapped[str | None] = mapped_column(Text)
    error_code: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PoiCacheTargetOutboxEventRow(Base):
    """PinVi에 전달하는 immutable cache target result event."""

    __tablename__ = "poi_cache_target_outbox_events"
    __table_args__ = (
        CheckConstraint(
            "source_payload_fingerprint ~ '^[0-9a-f]{64}$'",
            name=conv("ck_cache_target_outbox_source_fingerprint"),
        ),
        CheckConstraint(
            "payload_fingerprint ~ '^[0-9a-f]{64}$'",
            name=conv("ck_cache_target_outbox_payload_fingerprint"),
        ),
        CheckConstraint(
            "event_type IN ("
            "'cache_target.state_applied',"
            "'cache_target.links_reconciled',"
            "'refresh_request.status_changed',"
            "'cache_target.reconciled'"
            ")",
            name=conv("ck_cache_target_outbox_event_type"),
        ),
        CheckConstraint(
            "restore_epoch > 0 AND ("
            "(event_scope = 'target' AND target_key IS NOT NULL "
            "AND target_id IS NOT NULL AND source_generation > 0 "
            "AND target_sequence > 0 AND event_type <> 'cache_target.reconciled') OR "
            "(event_scope = 'stream' AND target_key IS NULL "
            "AND target_id IS NULL AND source_generation IS NULL "
            "AND target_sequence IS NULL AND event_type = 'cache_target.reconciled' "
            "AND reconciliation_request_id IS NOT NULL))",
            name=conv("ck_cache_target_outbox_versions"),
        ),
        CheckConstraint(
            "event_scope IN ('target','stream')",
            name=conv("ck_cache_target_outbox_scope"),
        ),
        CheckConstraint(
            "jsonb_typeof(payload) = 'object'",
            name=conv("ck_cache_target_outbox_payload"),
        ),
        ForeignKeyConstraint(
            ["external_system", "target_key"],
            [
                "ops.poi_cache_target_source_heads.external_system",
                "ops.poi_cache_target_source_heads.target_key",
            ],
            name=conv("fk_cache_target_outbox_head"),
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "relay_order",
            name=conv("uq_cache_target_outbox_relay_order"),
        ),
        UniqueConstraint(
            "external_system",
            "target_key",
            "restore_epoch",
            "source_generation",
            "target_sequence",
            name=conv("uq_cache_target_outbox_semantic_order"),
        ),
        Index(
            "idx_cache_target_outbox_stream_order",
            "external_system",
            "relay_order",
        ),
        Index(
            "idx_cache_target_outbox_state_material_order",
            "external_system",
            text("relay_order DESC"),
            postgresql_where=text("event_type = 'cache_target.state_applied'"),
        ),
        {"schema": "ops"},
    )

    event_id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    relay_order: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
    )
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    event_scope: Mapped[str] = mapped_column(Text, nullable=False)
    external_system: Mapped[str] = mapped_column(Text, nullable=False)
    target_key: Mapped[str | None] = mapped_column(Text)
    target_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey(
            "ops.poi_cache_targets.target_id",
            name="fk_cache_target_outbox_target",
            ondelete="RESTRICT",
        ),
    )
    restore_epoch: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source_generation: Mapped[int | None] = mapped_column(BigInteger)
    target_sequence: Mapped[int | None] = mapped_column(BigInteger)
    source_payload_fingerprint: Mapped[str] = mapped_column(Text, nullable=False)
    payload_fingerprint: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    source_event_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey(
            "ops.poi_cache_target_source_events.event_id",
            name="fk_cache_target_outbox_source_event",
            ondelete="RESTRICT",
        ),
    )
    refresh_request_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey(
            "ops.feature_update_requests.request_id",
            name="fk_cache_target_outbox_refresh_request",
            ondelete="RESTRICT",
        ),
    )
    job_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey(
            "ops.import_jobs.job_id",
            name="fk_cache_target_outbox_job",
            ondelete="RESTRICT",
        ),
    )
    domain_command_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(
            "ops.domain_commands.command_id",
            name="fk_cache_target_outbox_domain_command",
            ondelete="RESTRICT",
        ),
    )
    reconciliation_request_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey(
            "ops.poi_cache_target_reconciliation_requests.request_id",
            name="fk_cache_target_outbox_reconciliation_request",
            ondelete="RESTRICT",
        ),
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )


class PoiCacheTargetOutboxClaimRow(Base):
    """external system global stream의 단일 active lease."""

    __tablename__ = "poi_cache_target_outbox_claims"
    __table_args__ = (
        CheckConstraint(
            "request_fingerprint ~ '^[0-9a-f]{64}$'",
            name=conv("ck_cache_target_outbox_claims_fingerprint"),
        ),
        CheckConstraint(
            "status IN ('active','acked','expired','invalidated')",
            name=conv("ck_cache_target_outbox_claims_status"),
        ),
        CheckConstraint(
            "first_relay_order > 0 AND last_relay_order >= first_relay_order",
            name=conv("ck_cache_target_outbox_claims_order"),
        ),
        CheckConstraint(
            "acked_through_relay_order IS NULL OR "
            "acked_through_relay_order BETWEEN first_relay_order AND last_relay_order",
            name=conv("ck_cache_target_outbox_claims_ack_order"),
        ),
        CheckConstraint(
            "(status = 'active' AND completed_at IS NULL) OR "
            "(status <> 'active' AND completed_at IS NOT NULL)",
            name=conv("ck_cache_target_outbox_claims_completion"),
        ),
        UniqueConstraint(
            "external_system",
            "idempotency_key",
            name=conv("uq_cache_target_outbox_claims_idempotency"),
        ),
        Index(
            "uq_cache_target_outbox_claims_active_stream",
            "external_system",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
        Index(
            "idx_cache_target_outbox_claims_lease",
            "lease_expires_at",
            "external_system",
            postgresql_where=text("status = 'active'"),
        ),
        {"schema": "ops"},
    )

    claim_id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    external_system: Mapped[str] = mapped_column(
        Text,
        ForeignKey(
            "ops.poi_cache_target_streams.external_system",
            name="fk_cache_target_outbox_claims_stream",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    consumer_id: Mapped[str] = mapped_column(Text, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(Text, nullable=False)
    lease_token: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    first_relay_order: Mapped[int] = mapped_column(BigInteger, nullable=False)
    last_relay_order: Mapped[int] = mapped_column(BigInteger, nullable=False)
    acked_through_relay_order: Mapped[int | None] = mapped_column(BigInteger)
    lease_expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PoiCacheTargetOutboxDeliveryRow(Base):
    """outbox event별 retry/dead/terminal 가변 전달 상태."""

    __tablename__ = "poi_cache_target_outbox_deliveries"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','leased','retry','dead','delivered','superseded')",
            name=conv("ck_cache_target_outbox_deliveries_status"),
        ),
        CheckConstraint(
            "delivery_version > 0 AND attempt_count >= 0",
            name=conv("ck_cache_target_outbox_deliveries_versions"),
        ),
        CheckConstraint(
            "(status = 'leased') = "
            "(claim_id IS NOT NULL AND lease_token IS NOT NULL "
            "AND lease_expires_at IS NOT NULL)",
            name=conv("ck_cache_target_outbox_deliveries_lease"),
        ),
        CheckConstraint(
            "(status = 'delivered') = (delivered_at IS NOT NULL)",
            name=conv("ck_cache_target_outbox_deliveries_delivered"),
        ),
        CheckConstraint(
            "(status = 'superseded') = (superseded_at IS NOT NULL)",
            name=conv("ck_cache_target_outbox_deliveries_superseded"),
        ),
        CheckConstraint(
            "error_class IS NULL OR error_class IN ('transient','permanent')",
            name=conv("ck_cache_target_outbox_deliveries_error_class"),
        ),
        CheckConstraint(
            "error_fingerprint IS NULL OR error_fingerprint ~ '^[0-9a-f]{64}$'",
            name=conv("ck_cache_target_outbox_deliveries_error_fingerprint"),
        ),
        Index(
            "idx_cache_target_outbox_deliveries_due",
            "available_at",
            "event_id",
            postgresql_where=text("status IN ('pending','retry')"),
        ),
        Index(
            "idx_cache_target_outbox_deliveries_claim",
            "claim_id",
            "event_id",
            postgresql_where=text("claim_id IS NOT NULL"),
        ),
        {"schema": "ops"},
    )

    event_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey(
            "ops.poi_cache_target_outbox_events.event_id",
            name="fk_cache_target_outbox_deliveries_event",
            ondelete="RESTRICT",
        ),
        primary_key=True,
    )
    status: Mapped[str] = mapped_column(Text, nullable=False)
    delivery_version: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        server_default=text("1"),
    )
    attempt_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("0"),
    )
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    claim_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey(
            "ops.poi_cache_target_outbox_claims.claim_id",
            name="fk_cache_target_outbox_deliveries_claim",
            ondelete="RESTRICT",
        ),
    )
    lease_token: Mapped[str | None] = mapped_column(UUID(as_uuid=False))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_class: Mapped[str | None] = mapped_column(Text)
    error_code: Mapped[str | None] = mapped_column(Text)
    error_fingerprint: Mapped[str | None] = mapped_column(Text)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )


class PoiCacheTargetOutboxClaimEventRow(Base):
    """claim event의 consumer 적용과 contiguous ACK 사이 durable gap."""

    __tablename__ = "poi_cache_target_outbox_claim_events"
    __table_args__ = (
        CheckConstraint(
            "relay_order > 0 AND position > 0",
            name=conv("ck_cache_target_claim_events_order"),
        ),
        CheckConstraint(
            "ack_payload_fingerprint IS NULL OR "
            "ack_payload_fingerprint ~ '^[0-9a-f]{64}$'",
            name=conv("ck_cache_target_claim_events_fingerprint"),
        ),
        CheckConstraint(
            "prefix_acked_at IS NULL OR consumer_applied_at IS NOT NULL",
            name=conv("ck_cache_target_claim_events_ack"),
        ),
        UniqueConstraint(
            "claim_id",
            "relay_order",
            name=conv("uq_cache_target_claim_events_order"),
        ),
        UniqueConstraint(
            "claim_id",
            "position",
            name=conv("uq_cache_target_claim_events_position"),
        ),
        Index(
            "idx_cache_target_claim_events_applied_gap",
            "claim_id",
            "relay_order",
            postgresql_where=text(
                "consumer_applied_at IS NOT NULL AND prefix_acked_at IS NULL"
            ),
        ),
        {"schema": "ops"},
    )

    claim_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey(
            "ops.poi_cache_target_outbox_claims.claim_id",
            name="fk_cache_target_claim_events_claim",
            ondelete="RESTRICT",
        ),
        primary_key=True,
    )
    event_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey(
            "ops.poi_cache_target_outbox_events.event_id",
            name="fk_cache_target_claim_events_event",
            ondelete="RESTRICT",
        ),
        primary_key=True,
    )
    relay_order: Mapped[int] = mapped_column(BigInteger, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    consumer_applied_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    prefix_acked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ack_payload_fingerprint: Mapped[str | None] = mapped_column(Text)


class PoiCacheTargetSnapshotRow(Base):
    """한 MVCC view에서 만든 fixed paged reconciliation snapshot."""

    __tablename__ = "poi_cache_target_snapshots"
    __table_args__ = (
        CheckConstraint(
            "merkle_root ~ '^[0-9a-f]{64}$'",
            name=conv("ck_cache_target_snapshots_merkle_root"),
        ),
        CheckConstraint(
            "restore_epoch > 0 AND high_watermark_relay_order >= 0 "
            "AND material_high_watermark_relay_order >= 0 "
            "AND high_watermark_relay_order >= material_high_watermark_relay_order "
            "AND item_count >= 0",
            name=conv("ck_cache_target_snapshots_counts"),
        ),
        CheckConstraint(
            "expires_at > created_at",
            name=conv("ck_cache_target_snapshots_expiry"),
        ),
        UniqueConstraint(
            "snapshot_id",
            "external_system",
            name=conv("uq_cache_target_snapshots_stream"),
        ),
        Index(
            "idx_cache_target_snapshots_stream_time",
            "external_system",
            text("created_at DESC"),
            "snapshot_id",
        ),
        Index(
            "idx_cache_target_snapshots_expiry",
            "expires_at",
            "snapshot_id",
        ),
        Index(
            "idx_cache_target_snapshots_stream_expiry",
            "external_system",
            "expires_at",
            "snapshot_id",
        ),
        {"schema": "ops"},
    )

    snapshot_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        server_default=text("x_extension.gen_random_uuid()"),
    )
    external_system: Mapped[str] = mapped_column(
        Text,
        ForeignKey(
            "ops.poi_cache_target_streams.external_system",
            name="fk_cache_target_snapshots_stream",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    restore_epoch: Mapped[int] = mapped_column(BigInteger, nullable=False)
    high_watermark_relay_order: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
    )
    material_high_watermark_relay_order: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
    )
    item_count: Mapped[int] = mapped_column(BigInteger, nullable=False)
    merkle_root: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PoiCacheTargetSnapshotItemRow(Base):
    """snapshot에 고정한 NFC byte-order canonical row."""

    __tablename__ = "poi_cache_target_snapshot_items"
    __table_args__ = (
        CheckConstraint(
            "source_payload_fingerprint ~ '^[0-9a-f]{64}$'",
            name=conv("ck_cache_target_snapshot_items_fingerprint"),
        ),
        CheckConstraint(
            "row_number > 0 AND source_generation > 0",
            name=conv("ck_cache_target_snapshot_items_versions"),
        ),
        CheckConstraint(
            "state IN ('active','deleted')",
            name=conv("ck_cache_target_snapshot_items_state"),
        ),
        ForeignKeyConstraint(
            ["snapshot_id", "external_system"],
            [
                "ops.poi_cache_target_snapshots.snapshot_id",
                "ops.poi_cache_target_snapshots.external_system",
            ],
            name=conv("fk_cache_target_snapshot_items_snapshot"),
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "snapshot_id",
            "external_system",
            "target_key",
            name=conv("uq_cache_target_snapshot_items_key"),
        ),
        {"schema": "ops"},
    )

    snapshot_id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    row_number: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    external_system: Mapped[str] = mapped_column(Text, nullable=False)
    target_key: Mapped[str] = mapped_column(Text, nullable=False)
    state: Mapped[str] = mapped_column(Text, nullable=False)
    source_generation: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source_payload_fingerprint: Mapped[str] = mapped_column(Text, nullable=False)


class PoiCacheTargetSnapshotGcObservationRow(Base):
    """Acquired background GC run별 referenced snapshot 보존 추세."""

    __tablename__ = "poi_cache_target_snapshot_gc_observations"
    __table_args__ = (
        CheckConstraint(
            "(previous_observation_run_id IS NULL "
            "AND previous_observed_at IS NULL "
            "AND previous_referenced_items IS NULL "
            "AND previous_referenced_headers IS NULL) OR "
            "(previous_observation_run_id IS NOT NULL "
            "AND previous_observation_run_id = btrim(previous_observation_run_id) "
            "AND previous_observation_run_id <> '' "
            "AND length(previous_observation_run_id) <= 255 "
            "AND previous_observation_run_id <> dagster_run_id "
            "AND previous_observed_at IS NOT NULL "
            "AND previous_referenced_items IS NOT NULL "
            "AND previous_referenced_items >= 0 "
            "AND previous_referenced_headers IS NOT NULL "
            "AND previous_referenced_headers >= 0)",
            name=conv("ck_cache_target_snapshot_gc_observations_previous"),
        ),
        CheckConstraint(
            "dagster_run_id = btrim(dagster_run_id) "
            "AND dagster_run_id <> '' "
            "AND length(dagster_run_id) <= 255",
            name=conv("ck_cache_target_snapshot_gc_observations_run_id"),
        ),
        CheckConstraint(
            "referenced_items >= 0 AND referenced_headers >= 0",
            name=conv("ck_cache_target_snapshot_gc_observations_counts"),
        ),
        CheckConstraint(
            "growth_min_interval_seconds BETWEEN 1 AND 86400",
            name=conv("ck_cache_target_snapshot_gc_observations_growth_interval"),
        ),
        CheckConstraint(
            "(growth_baseline_run_id IS NULL "
            "AND growth_baseline_observed_at IS NULL "
            "AND growth_baseline_referenced_items IS NULL "
            "AND growth_baseline_referenced_headers IS NULL) OR "
            "(growth_baseline_run_id IS NOT NULL "
            "AND growth_baseline_run_id = btrim(growth_baseline_run_id) "
            "AND growth_baseline_run_id <> '' "
            "AND length(growth_baseline_run_id) <= 255 "
            "AND growth_baseline_run_id <> dagster_run_id "
            "AND growth_baseline_observed_at IS NOT NULL "
            "AND growth_baseline_referenced_items IS NOT NULL "
            "AND growth_baseline_referenced_items >= 0 "
            "AND growth_baseline_referenced_headers IS NOT NULL "
            "AND growth_baseline_referenced_headers >= 0)",
            name=conv("ck_cache_target_snapshot_gc_observations_growth_baseline"),
        ),
        CheckConstraint(
            "(growth_baseline_run_id IS NULL "
            "AND growth_baseline_eligible = ("
            "previous_observation_run_id IS NULL "
            "OR observed_at > previous_observed_at)) OR "
            "(growth_baseline_run_id IS NOT NULL "
            "AND growth_baseline_eligible = ("
            "observed_at > growth_baseline_observed_at "
            "AND (previous_observation_run_id IS NULL "
            "OR observed_at > previous_observed_at) "
            "AND extract(epoch FROM observed_at - growth_baseline_observed_at) "
            ">= growth_min_interval_seconds))",
            name=conv("ck_cache_target_snapshot_gc_observations_eligibility"),
        ),
        UniqueConstraint(
            "dagster_run_id",
            name=conv("uq_cache_target_snapshot_gc_observations_run_id"),
        ),
        Index(
            "idx_cache_target_snapshot_gc_observations_time",
            "observed_at",
        ),
        Index(
            "idx_cache_target_snapshot_gc_observations_growth_baseline",
            "observation_id",
            postgresql_where=text("growth_baseline_eligible"),
        ),
        {"schema": "ops"},
    )

    observation_id: Mapped[int] = mapped_column(
        BigInteger,
        Identity(always=True),
        primary_key=True,
    )
    dagster_run_id: Mapped[str] = mapped_column(Text, nullable=False)
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("clock_timestamp()"),
    )
    referenced_items: Mapped[int] = mapped_column(BigInteger, nullable=False)
    referenced_headers: Mapped[int] = mapped_column(BigInteger, nullable=False)
    previous_observation_run_id: Mapped[str | None] = mapped_column(Text)
    previous_observed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    previous_referenced_items: Mapped[int | None] = mapped_column(BigInteger)
    previous_referenced_headers: Mapped[int | None] = mapped_column(BigInteger)
    growth_baseline_run_id: Mapped[str | None] = mapped_column(Text)
    growth_baseline_observed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    growth_baseline_referenced_items: Mapped[int | None] = mapped_column(BigInteger)
    growth_baseline_referenced_headers: Mapped[int | None] = mapped_column(BigInteger)
    growth_baseline_eligible: Mapped[bool] = mapped_column(Boolean, nullable=False)
    growth_min_interval_seconds: Mapped[int] = mapped_column(
        BigInteger, nullable=False
    )


class ProviderRefreshPolicyRow(Base):
    """``ops.provider_refresh_policies`` row mapping."""

    __tablename__ = "provider_refresh_policies"
    __table_args__ = (
        ForeignKeyConstraint(
            ["provider_dataset_id"],
            ["provider_sync.provider_datasets.provider_dataset_id"],
            name="fk_provider_refresh_policies_dataset",
        ),
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
            "provider_dataset_id",
        ),
        Index("idx_provider_refresh_source_kind", "source_kind"),
        {"schema": "ops"},
    )

    provider_dataset_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
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
        ForeignKeyConstraint(
            ["provider_dataset_id"],
            ["provider_sync.provider_datasets.provider_dataset_id"],
            name="fk_managed_files_dataset",
        ),
        CheckConstraint(
            "(provider_dataset_id IS NOT NULL AND provider_name IS NULL) OR "
            "(provider_dataset_id IS NULL AND provider_name IS NOT NULL) OR "
            "(provider_dataset_id IS NULL AND provider_name IS NULL)",
            name="ck_managed_files_owner_v2",
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
            "idx_managed_files_provider_dataset",
            "provider_dataset_id",
            postgresql_where=text("provider_dataset_id IS NOT NULL"),
        ),
        Index(
            "idx_managed_files_provider_name",
            "provider_name",
            postgresql_where=text("provider_name IS NOT NULL"),
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
    provider_dataset_id: Mapped[int | None] = mapped_column(BigInteger)
    provider_name: Mapped[str | None] = mapped_column(Text)
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
