"""source_records last_seen_at 추가.

Revision ID: 0038_source_record_last_seen
Revises: 0037_dagster_schedule_overrides
Create Date: 2026-07-02 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0038_source_record_last_seen"
down_revision: str | Sequence[str] | None = "0037_dagster_schedule_overrides"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "source_records",
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        schema="provider_sync",
    )
    op.execute(
        """
        UPDATE provider_sync.source_records
        SET last_seen_at = COALESCE(imported_at, fetched_at, now())
        """
    )
    op.execute(
        "CREATE INDEX idx_source_records_last_seen_at_brin "
        "ON provider_sync.source_records USING BRIN (last_seen_at)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS provider_sync.idx_source_records_last_seen_at_brin")
    op.drop_column("source_records", "last_seen_at", schema="provider_sync")
