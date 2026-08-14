"""curated 계약 migration과 가격 시계열 migration head 병합.

Revision ID: 0035_merge_curated_price
Revises: 0034_generic_curated_contract, 0034_feature_price_values
Create Date: 2026-06-25

``0034_generic_curated_contract``는 main에서 먼저 도입됐고,
``0034_feature_price_values``는 가격 시계열 작업 중 N150에 먼저 적용됐다.
두 migration은 서로 다른 테이블을 다루므로 DDL 없이 Alembic graph만 병합한다.
"""

from __future__ import annotations

from collections.abc import Sequence

revision: str = "0035_merge_curated_price"
down_revision: str | Sequence[str] | None = (
    "0034_generic_curated_contract",
    "0034_feature_price_values",
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
