"""dedup pair order invariant (T-RV-12).

Revision ID: 0013_dedup_pair_order_invariant
Revises: 0012_import_jobs_batch_columns
Create Date: 2026-06-04

``ops.dedup_review_queue``의 feature pair를 ``feature_id_a < feature_id_b``로
정규화해 ``(a,b)``와 ``(b,a)``가 동시에 존재하는 중복 검토 큐를 DB 레벨에서 막는다.
기존 데이터는 check 추가 전에 self-pair를 제거하고, unordered pair 단위 중복은
검토 완료 행을 우선 보존한 뒤 canonical 방향으로 정규화한다.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0013_dedup_pair_order_invariant"
down_revision: str | Sequence[str] | None = "0012_import_jobs_batch_columns"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            DELETE FROM ops.dedup_review_queue
            WHERE feature_id_a = feature_id_b
            """
        )
    )
    op.execute(
        sa.text(
            """
            WITH ranked AS (
                SELECT
                    review_key,
                    row_number() OVER (
                        PARTITION BY
                            LEAST(feature_id_a, feature_id_b),
                            GREATEST(feature_id_a, feature_id_b)
                        ORDER BY
                            CASE WHEN status = 'pending' THEN 1 ELSE 0 END,
                            reviewed_at DESC NULLS LAST,
                            total_score DESC,
                            created_at DESC,
                            review_key::text DESC
                    ) AS rn
                FROM ops.dedup_review_queue
            )
            DELETE FROM ops.dedup_review_queue AS q
            USING ranked AS r
            WHERE q.review_key = r.review_key
              AND r.rn > 1
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE ops.dedup_review_queue
            SET
                feature_id_a = LEAST(feature_id_a, feature_id_b),
                feature_id_b = GREATEST(feature_id_a, feature_id_b)
            WHERE feature_id_a > feature_id_b
            """
        )
    )
    op.create_check_constraint(
        "ck_dedup_pair_order",
        "dedup_review_queue",
        "feature_id_a < feature_id_b",
        schema="ops",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_dedup_pair_order",
        "dedup_review_queue",
        schema="ops",
        type_="check",
    )
