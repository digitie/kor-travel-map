"""T-VN-40 public curation snapshot cap을 exact eligible set에서 판정한다.

Revision ID: 0220_tvn40_snapshot_cap_index
Revises: 0219_tvn40_routine_acl
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0220_tvn40_snapshot_cap_index"
down_revision: str | Sequence[str] | None = "0219_tvn40_routine_acl"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET ROLE ktm_feature_schema_owner")
    op.create_index(
        "idx_curation_items_service_snapshot_candidates",
        "curation_items",
        ["collection_id", "curation_item_id"],
        schema="feature",
        postgresql_include=[
            "accepted_link_decision_id",
            "feature_id",
            "source_record_key",
        ],
        postgresql_where=(
            "archived_at IS NULL AND source_present AND status = 'included' "
            "AND feature_id IS NOT NULL AND accepted_link_decision_id IS NOT NULL"
        ),
    )


def downgrade() -> None:
    raise RuntimeError(
        "0220_tvn40_snapshot_cap_index is forward-only; "
        "rebuild with the T-VN-40 release head"
    )
