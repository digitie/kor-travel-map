"""사용자 feature 변경 요청과 version 1 우선순위.

Revision ID: 0021_user_feature_versions
Revises: 0020_t212d_perf_keyset_indexes
Create Date: 2026-06-08

provider 적재 데이터는 version 0, 사용자/admin 요청으로 적용된 데이터는 version 1로
구분한다. ``feature.features``는 조회용 effective row이고,
``feature.feature_versions``가 provider/user snapshot을 보존한다.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0021_user_feature_versions"
down_revision: str | Sequence[str] | None = "0020_t212d_perf_keyset_indexes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "features",
        sa.Column(
            "data_origin",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'provider'"),
        ),
        schema="feature",
    )
    op.add_column(
        "features",
        sa.Column(
            "data_version",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        schema="feature",
    )
    op.add_column(
        "features",
        sa.Column("user_change_kind", sa.Text(), nullable=True),
        schema="feature",
    )
    op.add_column(
        "features",
        sa.Column("user_change_status", sa.Text(), nullable=True),
        schema="feature",
    )
    op.add_column(
        "features",
        sa.Column("user_change_request_id", postgresql.UUID(as_uuid=False), nullable=True),
        schema="feature",
    )
    op.add_column(
        "features",
        sa.Column("user_deleted_at", sa.DateTime(timezone=True), nullable=True),
        schema="feature",
    )
    op.add_column(
        "features",
        sa.Column("user_deleted_by", sa.Text(), nullable=True),
        schema="feature",
    )
    op.add_column(
        "features",
        sa.Column("user_change_reason", sa.Text(), nullable=True),
        schema="feature",
    )
    op.create_check_constraint(
        "ck_features_data_origin",
        "features",
        "data_origin IN ('provider','user_request')",
        schema="feature",
    )
    op.create_check_constraint(
        "ck_features_data_version",
        "features",
        "data_version >= 0",
        schema="feature",
    )
    op.create_check_constraint(
        "ck_features_user_change_kind",
        "features",
        "user_change_kind IS NULL OR user_change_kind IN ('add','update','delete')",
        schema="feature",
    )
    op.create_check_constraint(
        "ck_features_user_change_status",
        "features",
        "user_change_status IS NULL OR user_change_status IN "
        "('pending','applied','rejected')",
        schema="feature",
    )
    op.create_index(
        "idx_features_data_origin",
        "features",
        ["data_origin", "data_version"],
        schema="feature",
    )
    op.create_index(
        "idx_features_user_deleted",
        "features",
        ["user_deleted_at"],
        schema="feature",
        postgresql_where=sa.text("user_deleted_at IS NOT NULL"),
    )

    op.create_table(
        "feature_versions",
        sa.Column(
            "feature_id",
            sa.String(),
            sa.ForeignKey("feature.features.feature_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("version", sa.Integer(), primary_key=True),
        sa.Column("origin", sa.Text(), nullable=False),
        sa.Column("change_kind", sa.Text(), nullable=False),
        sa.Column(
            "payload",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("request_id", postgresql.UUID(as_uuid=False), nullable=True),
        sa.Column("created_by", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint("version >= 0", name="ck_feature_versions_version"),
        sa.CheckConstraint(
            "origin IN ('provider','user_request')",
            name="ck_feature_versions_origin",
        ),
        sa.CheckConstraint(
            "change_kind IN ('load','add','update','delete')",
            name="ck_feature_versions_change_kind",
        ),
        schema="feature",
    )
    op.create_index(
        "idx_feature_versions_request",
        "feature_versions",
        ["request_id"],
        schema="feature",
    )

    op.create_table(
        "feature_change_requests",
        sa.Column(
            "request_id",
            postgresql.UUID(as_uuid=False),
            primary_key=True,
            server_default=sa.text("x_extension.gen_random_uuid()"),
        ),
        sa.Column("feature_id", sa.String(), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column(
            "state",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column("review_mode", sa.Text(), nullable=False),
        sa.Column(
            "payload",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("requested_by", sa.Text(), nullable=True),
        sa.Column("reviewed_by", sa.Text(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "action IN ('add','update','delete')",
            name="ck_feature_change_action",
        ),
        sa.CheckConstraint(
            "state IN ('pending','applied','rejected')",
            name="ck_feature_change_state",
        ),
        sa.CheckConstraint(
            "review_mode IN ('require_review','immediate')",
            name="ck_feature_change_review_mode",
        ),
        schema="ops",
    )
    op.execute(
        """
        CREATE INDEX idx_feature_change_state_created
        ON ops.feature_change_requests (state, created_at DESC, request_id DESC)
        """
    )
    op.create_index(
        "idx_feature_change_feature",
        "feature_change_requests",
        ["feature_id"],
        schema="ops",
    )


def downgrade() -> None:
    op.drop_index(
        "idx_feature_change_feature",
        table_name="feature_change_requests",
        schema="ops",
    )
    op.execute("DROP INDEX IF EXISTS ops.idx_feature_change_state_created")
    op.drop_table("feature_change_requests", schema="ops")

    op.drop_index(
        "idx_feature_versions_request",
        table_name="feature_versions",
        schema="feature",
    )
    op.drop_table("feature_versions", schema="feature")

    op.drop_index("idx_features_user_deleted", table_name="features", schema="feature")
    op.drop_index("idx_features_data_origin", table_name="features", schema="feature")
    op.drop_constraint("ck_features_user_change_status", "features", schema="feature")
    op.drop_constraint("ck_features_user_change_kind", "features", schema="feature")
    op.drop_constraint("ck_features_data_version", "features", schema="feature")
    op.drop_constraint("ck_features_data_origin", "features", schema="feature")
    op.drop_column("features", "user_change_reason", schema="feature")
    op.drop_column("features", "user_deleted_by", schema="feature")
    op.drop_column("features", "user_deleted_at", schema="feature")
    op.drop_column("features", "user_change_request_id", schema="feature")
    op.drop_column("features", "user_change_status", schema="feature")
    op.drop_column("features", "user_change_kind", schema="feature")
    op.drop_column("features", "data_version", schema="feature")
    op.drop_column("features", "data_origin", schema="feature")
