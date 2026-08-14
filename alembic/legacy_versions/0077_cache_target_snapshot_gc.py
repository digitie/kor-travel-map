"""cache target snapshot GC/reuse lookup index를 추가한다.

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

_RECONCILIATION_INDEX = "idx_cache_target_reconciliation_requests_snapshot_status"
_MATERIAL_WATERMARK_INDEX = "idx_cache_target_outbox_state_material_order"
_SNAPSHOT_CAPACITY_INDEX = "idx_cache_target_snapshots_stream_expiry"


def upgrade() -> None:
    op.create_index(
        _RECONCILIATION_INDEX,
        "poi_cache_target_reconciliation_requests",
        ["snapshot_id", "status"],
        schema="ops",
        postgresql_where=sa.text("snapshot_id IS NOT NULL"),
    )
    op.create_index(
        _MATERIAL_WATERMARK_INDEX,
        "poi_cache_target_outbox_events",
        ["external_system", sa.text("relay_order DESC")],
        schema="ops",
        postgresql_where=sa.text("event_type = 'cache_target.state_applied'"),
    )
    op.create_index(
        _SNAPSHOT_CAPACITY_INDEX,
        "poi_cache_target_snapshots",
        ["external_system", "expires_at", "snapshot_id"],
        schema="ops",
    )


def downgrade() -> None:
    op.drop_index(
        _SNAPSHOT_CAPACITY_INDEX,
        table_name="poi_cache_target_snapshots",
        schema="ops",
    )
    op.drop_index(
        _MATERIAL_WATERMARK_INDEX,
        table_name="poi_cache_target_outbox_events",
        schema="ops",
    )
    op.drop_index(
        _RECONCILIATION_INDEX,
        table_name="poi_cache_target_reconciliation_requests",
        schema="ops",
    )
