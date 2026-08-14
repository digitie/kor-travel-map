"""가격/curated merge revision alias 병합.

Revision ID: 0036_merge_price_merge_aliases
Revises: 0035_merge_price_and_curated, 0035_merge_curated_price
Create Date: 2026-06-25

main hotfix는 ``0035_merge_price_and_curated``를 만들었고, N150 선배포는
``0035_merge_curated_price``로 먼저 stamp됐다. 두 revision ID를 모두 보존하고
DDL 없이 Alembic graph를 다시 단일 head로 합친다.
"""

from __future__ import annotations

from collections.abc import Sequence

revision: str = "0036_merge_price_merge_aliases"
down_revision: str | Sequence[str] | None = (
    "0035_merge_price_and_curated",
    "0035_merge_curated_price",
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
