"""authoritative 큐레이션 source presence를 membership과 분리한다.

Revision ID: 0065_curation_source_presence
Revises: 0064_price_series_identity
Create Date: 2026-07-27

CSV에서 일시 누락된 membership을 삭제하면 운영자 status/relation/reuse override가
재등장 때 소실된다. ``source_present``를 durable membership에 저장해 누락은 비공개
상태 전환으로 표현하고, operator archive tombstone과 구분한다.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0065_curation_source_presence"
down_revision: str | Sequence[str] | None = "0064_price_series_identity"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "curation_items",
        sa.Column(
            "source_present",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        schema="feature",
    )
    op.drop_index(
        "idx_curation_items_collection_status_order",
        table_name="curation_items",
        schema="feature",
    )
    op.drop_index(
        "idx_curation_items_feature_status_collection",
        table_name="curation_items",
        schema="feature",
    )
    op.create_index(
        "idx_curation_items_collection_status_order",
        "curation_items",
        ["collection_id", "source_present", "status", "sort_order", "curation_item_id"],
        schema="feature",
    )
    op.create_index(
        "idx_curation_items_feature_status_collection",
        "curation_items",
        ["feature_id", "source_present", "status", "collection_id"],
        schema="feature",
    )


def downgrade() -> None:
    op.drop_index(
        "idx_curation_items_feature_status_collection",
        table_name="curation_items",
        schema="feature",
    )
    op.drop_index(
        "idx_curation_items_collection_status_order",
        table_name="curation_items",
        schema="feature",
    )
    op.create_index(
        "idx_curation_items_feature_status_collection",
        "curation_items",
        ["feature_id", "status", "collection_id"],
        schema="feature",
    )
    op.create_index(
        "idx_curation_items_collection_status_order",
        "curation_items",
        ["collection_id", "status", "sort_order", "curation_item_id"],
        schema="feature",
    )
    op.drop_column("curation_items", "source_present", schema="feature")
