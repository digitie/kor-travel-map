"""features + source_records + source_links + provider_sync_state (ADR-012/018/019).

Revision ID: 0002_features_source
Revises: 0001_initial
Create Date: 2026-05-26 00:00:00.000000

Sprint 2 첫 provider 적재 직전 필수 테이블. `docs/data-model.md §1~§4`
DDL을 SQLAlchemy migration으로 옮긴 것.

후속 migration에서 추가될 테이블 (each in its own PR):
- detail 5종 (place/event/notice/area/route)
- feature_opening_periods, feature_special_days (PR with VisitKorea opening_hours)
- feature_weather_values (PR with KMA weather)
- price_points, price_values (PR with OpiNet price)
- feature_files (PR with first file upload)
- ops.* (import_jobs, dedup_review_queue, ...)
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from geoalchemy2 import Geometry
from sqlalchemy.dialects.postgresql import JSONB, UUID

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002_features_source"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ── feature.features ──────────────────────────────────────────────────
    op.create_table(
        "features",
        sa.Column("feature_id", sa.String(), primary_key=True),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("category", sa.String(), nullable=False),
        sa.Column("coord", Geometry("POINT", srid=4326)),
        sa.Column(
            "coord_5179",
            Geometry("POINT", srid=5179),
            sa.Computed(
                "CASE WHEN coord IS NULL THEN NULL "
                "ELSE ST_Transform(coord, 5179) END",
                persisted=True,
            ),
        ),
        sa.Column("geom", Geometry("GEOMETRY", srid=4326)),
        sa.Column(
            "address", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("legal_dong_code", sa.String(10)),
        sa.Column("road_name_code", sa.String()),
        sa.Column("road_address_management_no", sa.String()),
        sa.Column("admin_dong_code", sa.String(10)),
        sa.Column("sido_code", sa.String(2)),
        sa.Column("sigungu_code", sa.String(5)),
        sa.Column(
            "urls", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("marker_icon", sa.String()),
        sa.Column("marker_color", sa.String()),
        sa.Column(
            "parent_feature_id",
            sa.String(),
            sa.ForeignKey("feature.features.feature_id", ondelete="SET NULL"),
        ),
        sa.Column("sibling_group_id", UUID(as_uuid=False)),
        sa.Column(
            "detail", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "raw_refs", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "status", sa.String(), nullable=False, server_default=sa.text("'active'"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "kind IN ('place','event','notice','price','weather','route','area')",
            name="ck_features_kind",
        ),
        sa.CheckConstraint(
            "status IN ('draft','active','inactive','hidden','broken','deleted')",
            name="ck_features_status",
        ),
        sa.CheckConstraint(
            "coord IS NULL OR ("
            "ST_X(coord) BETWEEN 124.0 AND 132.0 AND "
            "ST_Y(coord) BETWEEN 33.0 AND 39.5)",
            name="ck_features_coord_pair",
        ),
        schema="feature",
    )
    # 인덱스 (docs/data-model.md §1 + docs/performance.md).
    op.execute(
        "CREATE INDEX idx_features_coord_gist ON feature.features "
        "USING GIST (coord) WHERE deleted_at IS NULL"
    )
    op.execute(
        "CREATE INDEX idx_features_coord_5179_gist ON feature.features "
        "USING GIST (coord_5179) WHERE deleted_at IS NULL"
    )
    op.execute(
        "CREATE INDEX idx_features_geom_gist ON feature.features "
        "USING GIST (geom) WHERE deleted_at IS NULL AND geom IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX idx_features_kind_category ON feature.features "
        "(kind, category) WHERE deleted_at IS NULL"
    )
    op.execute(
        "CREATE INDEX idx_features_status_updated ON feature.features "
        "(status, updated_at)"
    )
    op.execute(
        "CREATE INDEX idx_features_legal_dong_code ON feature.features "
        "(legal_dong_code)"
    )
    op.execute(
        "CREATE INDEX idx_features_sigungu ON feature.features "
        "(sigungu_code, kind) WHERE deleted_at IS NULL"
    )
    op.execute(
        "CREATE INDEX idx_features_parent ON feature.features "
        "(parent_feature_id) WHERE parent_feature_id IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX idx_features_sibling ON feature.features "
        "(sibling_group_id) WHERE sibling_group_id IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX idx_features_name_trgm ON feature.features "
        "USING GIN (name x_extension.gin_trgm_ops)"
    )

    # ── provider_sync.source_records ──────────────────────────────────────
    op.create_table(
        "source_records",
        sa.Column("source_record_key", sa.String(), primary_key=True),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("dataset_key", sa.String(), nullable=False),
        sa.Column("source_entity_type", sa.String(), nullable=False),
        sa.Column("source_entity_id", sa.String(), nullable=False),
        sa.Column("source_version", sa.String()),
        sa.Column("raw_name", sa.String()),
        sa.Column("raw_address", sa.String()),
        sa.Column("raw_longitude", sa.Numeric(12, 8)),
        sa.Column("raw_latitude", sa.Numeric(12, 8)),
        sa.Column(
            "raw_data", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("raw_payload_hash", sa.String(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "imported_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint(
            "provider",
            "dataset_key",
            "source_entity_type",
            "source_entity_id",
            "raw_payload_hash",
            name="uq_source_records",
        ),
        schema="provider_sync",
    )
    op.create_index(
        "idx_source_records_provider_dataset_entity",
        "source_records",
        ["provider", "dataset_key", "source_entity_type", "source_entity_id"],
        schema="provider_sync",
    )
    op.execute(
        "CREATE INDEX idx_source_records_imported_at_brin "
        "ON provider_sync.source_records USING BRIN (imported_at)"
    )
    op.execute(
        "CREATE INDEX idx_source_records_fetched_at_brin "
        "ON provider_sync.source_records USING BRIN (fetched_at)"
    )
    op.execute(
        "CREATE INDEX idx_source_records_expires_at "
        "ON provider_sync.source_records (expires_at) "
        "WHERE expires_at IS NOT NULL"
    )

    # ── provider_sync.source_links ────────────────────────────────────────
    op.create_table(
        "source_links",
        sa.Column(
            "feature_id",
            sa.String(),
            sa.ForeignKey("feature.features.feature_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "source_record_key",
            sa.String(),
            sa.ForeignKey(
                "provider_sync.source_records.source_record_key",
                ondelete="RESTRICT",
            ),
            primary_key=True,
        ),
        sa.Column(
            "source_role",
            sa.String(),
            nullable=False,
            server_default=sa.text("'enrichment'"),
        ),
        sa.Column("match_method", sa.String(), nullable=False),
        sa.Column("confidence", sa.Integer(), nullable=False),
        sa.Column(
            "is_primary_source",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "source_role IN ('primary','enrichment','geocoded','phone',"
            "'media','weather_context','observation','external_link')",
            name="ck_source_links_role",
        ),
        sa.CheckConstraint(
            "confidence BETWEEN 0 AND 100",
            name="ck_source_links_confidence",
        ),
        schema="provider_sync",
    )
    op.create_index(
        "idx_source_links_record",
        "source_links",
        ["source_record_key"],
        schema="provider_sync",
    )
    op.create_index(
        "idx_source_links_role",
        "source_links",
        ["source_role"],
        schema="provider_sync",
    )
    op.execute(
        "CREATE INDEX idx_source_links_primary "
        "ON provider_sync.source_links (feature_id) WHERE is_primary_source"
    )

    # ── provider_sync.provider_sync_state ─────────────────────────────────
    op.create_table(
        "provider_sync_state",
        sa.Column("provider", sa.String(), primary_key=True),
        sa.Column("dataset_key", sa.String(), primary_key=True),
        sa.Column("sync_scope", sa.String(), primary_key=True),
        sa.Column(
            "status",
            sa.String(),
            nullable=False,
            server_default=sa.text("'active'"),
        ),
        sa.Column(
            "cursor",
            JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("last_success_at", sa.DateTime(timezone=True)),
        sa.Column("last_failure_at", sa.DateTime(timezone=True)),
        sa.Column(
            "consecutive_failures",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("next_run_after", sa.DateTime(timezone=True)),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "status IN ('active','paused','disabled','failed')",
            name="ck_provider_sync_state_status",
        ),
        schema="provider_sync",
    )
    op.execute(
        "CREATE INDEX idx_sync_state_next_run "
        "ON provider_sync.provider_sync_state (next_run_after) "
        "WHERE status='active'"
    )


def downgrade() -> None:
    op.drop_table("provider_sync_state", schema="provider_sync")
    op.drop_table("source_links", schema="provider_sync")
    op.drop_table("source_records", schema="provider_sync")
    op.drop_table("features", schema="feature")
