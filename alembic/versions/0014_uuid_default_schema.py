"""UUID defaults schema qualification (T-RV-13).

Revision ID: 0014_uuid_default_schema
Revises: 0013_dedup_pair_order_invariant
Create Date: 2026-06-04

pgcrypto는 ADR-008에 따라 ``x_extension`` schema에 격리한다. 운영 테이블 UUID
default가 search_path에 의존하지 않도록 기존 bare ``gen_random_uuid()`` default를
모두 ``x_extension.gen_random_uuid()``로 표준화한다.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0014_uuid_default_schema"
down_revision: str | Sequence[str] | None = "0013_dedup_pair_order_invariant"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UUID_DEFAULT_COLUMNS: tuple[tuple[str, str], ...] = (
    ("feature_consistency_reports", "report_id"),
    ("dedup_review_queue", "review_key"),
    ("import_jobs", "job_id"),
    ("feature_merge_history", "merge_id"),
)


def _alter_uuid_default(*, expression: str) -> None:
    for table_name, column_name in _UUID_DEFAULT_COLUMNS:
        op.alter_column(
            table_name,
            column_name,
            schema="ops",
            server_default=sa.text(expression),
        )


def upgrade() -> None:
    _alter_uuid_default(expression="x_extension.gen_random_uuid()")


def downgrade() -> None:
    _alter_uuid_default(expression="gen_random_uuid()")
