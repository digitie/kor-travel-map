"""feature overrides for admin deactivate protection (ADR-045 T-207c).

Revision ID: 0010_feature_overrides
Revises: 0009_phase2_ops_tables
Create Date: 2026-06-03
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0010_feature_overrides"
down_revision: str | Sequence[str] | None = "0009_phase2_ops_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "feature_overrides",
        sa.Column(
            "override_key",
            postgresql.UUID(as_uuid=False),
            primary_key=True,
            server_default=sa.text("x_extension.gen_random_uuid()"),
        ),
        sa.Column(
            "feature_id",
            sa.String(),
            sa.ForeignKey("feature.features.feature_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "source_record_key",
            sa.String(),
            sa.ForeignKey(
                "provider_sync.source_records.source_record_key",
                ondelete="SET NULL",
            ),
            nullable=True,
        ),
        sa.Column("field_path", sa.Text(), nullable=False),
        sa.Column("source_value", postgresql.JSONB(), nullable=True),
        sa.Column("override_value", postgresql.JSONB(), nullable=True),
        sa.Column(
            "prevent_provider_reactivation",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "status",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'active'"),
        ),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "status IN ('active','inactive','superseded')",
            name="ck_overrides_status",
        ),
        schema="ops",
    )
    op.create_index(
        "idx_overrides_feature",
        "feature_overrides",
        ["feature_id", "status"],
        schema="ops",
    )
    op.create_index(
        "idx_overrides_field",
        "feature_overrides",
        ["field_path"],
        schema="ops",
    )
    op.create_index(
        "uq_overrides_active_feature_field",
        "feature_overrides",
        ["feature_id", "field_path"],
        unique=True,
        schema="ops",
        postgresql_where=sa.text("status = 'active'"),
    )
    op.create_index(
        "idx_overrides_prevent_reactivation",
        "feature_overrides",
        ["feature_id", "field_path"],
        schema="ops",
        postgresql_where=sa.text(
            "status = 'active' AND prevent_provider_reactivation"
        ),
    )


def downgrade() -> None:
    op.drop_index(
        "idx_overrides_prevent_reactivation",
        table_name="feature_overrides",
        schema="ops",
    )
    op.drop_index(
        "uq_overrides_active_feature_field",
        table_name="feature_overrides",
        schema="ops",
    )
    op.drop_index("idx_overrides_field", table_name="feature_overrides", schema="ops")
    op.drop_index("idx_overrides_feature", table_name="feature_overrides", schema="ops")
    op.drop_table("feature_overrides", schema="ops")
