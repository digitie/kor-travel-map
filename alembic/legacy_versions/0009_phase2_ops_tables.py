"""ops Phase 2 tables (ADR-045 T-205c).

Feature update request 실행 본체(T-206d)와 admin/Dagster 운영 화면(T-207/T-208)이
필요로 하는 Phase 2 기반 테이블을 추가한다.

- ``ops.data_integrity_violations`` — F5~F8/주소/좌표 이슈 1건 = 1행 운영 큐.
- ``ops.poi_cache_targets`` — 외부 앱 POI/cache target 등록.
- ``ops.poi_cache_target_feature_links`` — target 주변 feature 연결 cache.
- ``ops.provider_refresh_policies`` — provider/dataset별 refresh/rate-limit 정책.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from geoalchemy2 import Geometry
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0009_phase2_ops_tables"
down_revision: str | Sequence[str] | None = "0008_feature_update_requests"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "data_integrity_violations",
        sa.Column(
            "violation_key",
            postgresql.UUID(as_uuid=False),
            primary_key=True,
            server_default=sa.text("x_extension.gen_random_uuid()"),
        ),
        sa.Column("provider", sa.Text(), nullable=True),
        sa.Column("dataset_key", sa.Text(), nullable=True),
        sa.Column(
            "source_record_key",
            sa.String(),
            sa.ForeignKey(
                "provider_sync.source_records.source_record_key",
                ondelete="SET NULL",
            ),
            nullable=True,
        ),
        sa.Column(
            "feature_id",
            sa.String(),
            sa.ForeignKey("feature.features.feature_id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("violation_type", sa.Text(), nullable=False),
        sa.Column("severity", sa.Text(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column(
            "payload",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "status",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'open'"),
        ),
        sa.Column(
            "detected_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "severity IN ('info','warning','error','critical')",
            name="ck_violations_severity",
        ),
        sa.CheckConstraint(
            "status IN ('open','acknowledged','resolved','ignored')",
            name="ck_violations_status",
        ),
        schema="ops",
    )
    op.create_index(
        "idx_violations_type_status",
        "data_integrity_violations",
        ["violation_type", "status"],
        schema="ops",
    )
    op.create_index(
        "idx_violations_feature",
        "data_integrity_violations",
        ["feature_id"],
        schema="ops",
        postgresql_where=sa.text("feature_id IS NOT NULL"),
    )
    op.create_index(
        "idx_violations_source_record",
        "data_integrity_violations",
        ["source_record_key"],
        schema="ops",
        postgresql_where=sa.text("source_record_key IS NOT NULL"),
    )
    op.execute(
        "CREATE INDEX idx_violations_detected_brin "
        "ON ops.data_integrity_violations USING BRIN (detected_at)"
    )

    op.create_table(
        "poi_cache_targets",
        sa.Column(
            "target_id",
            postgresql.UUID(as_uuid=False),
            primary_key=True,
            server_default=sa.text("x_extension.gen_random_uuid()"),
        ),
        sa.Column("external_system", sa.Text(), nullable=False),
        sa.Column("target_key", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=True),
        sa.Column("lon", sa.Numeric(12, 8), nullable=False),
        sa.Column("lat", sa.Numeric(12, 8), nullable=False),
        sa.Column(
            "coord",
            Geometry("POINT", srid=4326, spatial_index=False),
            nullable=False,
        ),
        sa.Column(
            "coord_5179",
            Geometry("POINT", srid=5179, spatial_index=False),
            sa.Computed("ST_Transform(coord, 5179)", persisted=True),
        ),
        sa.Column(
            "coord_precision_digits",
            sa.SmallInteger(),
            nullable=False,
            server_default=sa.text("6"),
        ),
        sa.Column("coord_key", sa.Text(), nullable=False),
        sa.Column("radius_km", sa.Numeric(8, 3), nullable=False),
        sa.Column(
            "scope_mode",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'center_radius'"),
        ),
        sa.Column(
            "update_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "refresh_policy",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'provider_default'"),
        ),
        sa.Column(
            "provider_overrides",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "metadata",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("last_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_refreshed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "next_eligible_refresh_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.CheckConstraint(
            "scope_mode IN ('center_radius','sigungu_by_radius')",
            name="ck_poi_cache_targets_scope_mode",
        ),
        sa.CheckConstraint(
            "refresh_policy IN ("
            "'provider_default','follow_system','allow_targeted','disabled'"
            ")",
            name="ck_poi_cache_targets_refresh_policy",
        ),
        sa.CheckConstraint(
            "radius_km > 0 AND radius_km <= 100",
            name="ck_poi_cache_targets_radius",
        ),
        sa.CheckConstraint(
            "ST_X(coord) BETWEEN 124.0 AND 132.0 AND "
            "ST_Y(coord) BETWEEN 33.0 AND 39.5",
            name="ck_poi_cache_targets_coord",
        ),
        sa.CheckConstraint(
            "coord_precision_digits BETWEEN 3 AND 8",
            name="ck_poi_cache_targets_precision",
        ),
        schema="ops",
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_poi_cache_targets_active_key "
        "ON ops.poi_cache_targets (external_system, target_key) "
        "WHERE deleted_at IS NULL"
    )
    op.execute(
        "CREATE INDEX idx_poi_cache_targets_coord_5179 "
        "ON ops.poi_cache_targets USING GIST (coord_5179) "
        "WHERE deleted_at IS NULL"
    )
    op.execute(
        "CREATE INDEX idx_poi_cache_targets_next_refresh "
        "ON ops.poi_cache_targets (next_eligible_refresh_at) "
        "WHERE deleted_at IS NULL AND update_enabled"
    )

    op.create_table(
        "poi_cache_target_feature_links",
        sa.Column(
            "target_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("ops.poi_cache_targets.target_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "feature_id",
            sa.String(),
            sa.ForeignKey("feature.features.feature_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("provider", sa.Text(), nullable=True),
        sa.Column("dataset_key", sa.Text(), nullable=True),
        sa.Column("distance_m", sa.Numeric(12, 2), nullable=True),
        sa.Column(
            "relation",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'within_radius'"),
        ),
        sa.Column(
            "active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("last_refreshed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "relation IN ('within_radius','same_sigungu','manual')",
            name="ck_poi_cache_link_relation",
        ),
        schema="ops",
    )
    op.create_index(
        "idx_poi_cache_links_feature",
        "poi_cache_target_feature_links",
        ["feature_id"],
        schema="ops",
        postgresql_where=sa.text("active"),
    )
    op.create_index(
        "idx_poi_cache_links_provider_dataset",
        "poi_cache_target_feature_links",
        ["provider", "dataset_key"],
        schema="ops",
        postgresql_where=sa.text("active"),
    )

    op.create_table(
        "provider_refresh_policies",
        sa.Column("provider", sa.Text(), primary_key=True),
        sa.Column("dataset_key", sa.Text(), primary_key=True),
        sa.Column("source_kind", sa.Text(), nullable=False),
        sa.Column(
            "targeted_policy",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'follow_system'"),
        ),
        sa.Column("system_interval_seconds", sa.Integer(), nullable=True),
        sa.Column("optimal_interval_seconds", sa.Integer(), nullable=True),
        sa.Column("min_interval_seconds", sa.Integer(), nullable=True),
        sa.Column("max_requests_per_minute", sa.Integer(), nullable=True),
        sa.Column("max_requests_per_hour", sa.Integer(), nullable=True),
        sa.Column("max_requests_per_day", sa.Integer(), nullable=True),
        sa.Column(
            "max_concurrent",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.Column("burst_size", sa.Integer(), nullable=True),
        sa.Column(
            "rate_limit_source",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "config_source",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'db'"),
        ),
        sa.Column(
            "enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
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
        sa.CheckConstraint(
            "source_kind IN ('openapi','filedata','manual','system')",
            name="ck_provider_refresh_source_kind",
        ),
        sa.CheckConstraint(
            "targeted_policy IN ('follow_system','allow_targeted','disabled')",
            name="ck_provider_refresh_targeted_policy",
        ),
        sa.CheckConstraint(
            "max_concurrent > 0",
            name="ck_provider_refresh_max_concurrent",
        ),
        sa.CheckConstraint(
            "system_interval_seconds IS NULL OR system_interval_seconds > 0",
            name="ck_provider_refresh_system_interval",
        ),
        sa.CheckConstraint(
            "optimal_interval_seconds IS NULL OR optimal_interval_seconds > 0",
            name="ck_provider_refresh_optimal_interval",
        ),
        sa.CheckConstraint(
            "min_interval_seconds IS NULL OR min_interval_seconds > 0",
            name="ck_provider_refresh_min_interval",
        ),
        sa.CheckConstraint(
            "max_requests_per_minute IS NULL OR max_requests_per_minute > 0",
            name="ck_provider_refresh_rpm",
        ),
        sa.CheckConstraint(
            "max_requests_per_hour IS NULL OR max_requests_per_hour > 0",
            name="ck_provider_refresh_rph",
        ),
        sa.CheckConstraint(
            "max_requests_per_day IS NULL OR max_requests_per_day > 0",
            name="ck_provider_refresh_rpd",
        ),
        sa.CheckConstraint(
            "burst_size IS NULL OR burst_size > 0",
            name="ck_provider_refresh_burst",
        ),
        schema="ops",
    )
    op.create_index(
        "idx_provider_refresh_enabled",
        "provider_refresh_policies",
        ["enabled", "provider", "dataset_key"],
        schema="ops",
    )
    op.create_index(
        "idx_provider_refresh_source_kind",
        "provider_refresh_policies",
        ["source_kind"],
        schema="ops",
    )


def downgrade() -> None:
    op.drop_table("provider_refresh_policies", schema="ops")
    op.drop_table("poi_cache_target_feature_links", schema="ops")
    op.drop_table("poi_cache_targets", schema="ops")
    op.drop_table("data_integrity_violations", schema="ops")
