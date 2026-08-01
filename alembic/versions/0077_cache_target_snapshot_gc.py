"""cache target snapshot GC의 reconciliation lookup index를 추가한다.

Revision ID: 0077_cache_target_snapshot_gc
Revises: 0076_cache_target_receipt
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0077_cache_target_snapshot_gc"
down_revision: str | Sequence[str] | None = "0076_cache_target_receipt"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INDEX = "idx_cache_target_reconciliation_requests_snapshot_status"


def upgrade() -> None:
    op.create_index(
        _INDEX,
        "poi_cache_target_reconciliation_requests",
        ["snapshot_id", "status"],
        schema="ops",
        postgresql_where=sa.text("snapshot_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        _INDEX,
        table_name="poi_cache_target_reconciliation_requests",
        schema="ops",
    )
