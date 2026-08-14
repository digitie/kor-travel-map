"""Merge price values and generic curated migration branches.

Revision ID: 0035_merge_price_and_curated
Revises: 0034_feature_price_values, 0034_generic_curated_contract
Create Date: 2026-06-25

N150 production already had ``0034_feature_price_values`` applied, while main
introduced ``0034_generic_curated_contract`` from the same parent. Keep both
revision IDs valid and merge the Alembic graph without additional DDL.
"""

from __future__ import annotations

from collections.abc import Sequence

revision: str = "0035_merge_price_and_curated"
down_revision: str | Sequence[str] | None = (
    "0034_feature_price_values",
    "0034_generic_curated_contract",
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
