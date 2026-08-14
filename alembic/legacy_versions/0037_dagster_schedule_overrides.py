"""Dagster schedule override 저장소 추가.

Revision ID: 0037_dagster_schedule_overrides
Revises: 0036_merge_price_merge_aliases
Create Date: 2026-06-30
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0037_dagster_schedule_overrides"
down_revision: str | Sequence[str] | None = "0036_merge_price_merge_aliases"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "dagster_schedule_overrides",
        sa.Column("schedule_name", sa.Text(), nullable=False),
        sa.Column("cron_schedule", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("updated_by", sa.Text(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.CheckConstraint(
            "btrim(schedule_name) <> ''",
            name="ck_dagster_schedule_overrides_schedule_name_not_blank",
        ),
        sa.CheckConstraint(
            "btrim(cron_schedule) <> ''",
            name="ck_dagster_schedule_overrides_cron_schedule_not_blank",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(metadata) = 'object'",
            name="ck_dagster_schedule_overrides_metadata_object",
        ),
        sa.PrimaryKeyConstraint(
            "schedule_name",
            name=op.f("pk_dagster_schedule_overrides"),
        ),
        schema="ops",
    )


def downgrade() -> None:
    op.drop_table("dagster_schedule_overrides", schema="ops")
