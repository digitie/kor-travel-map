"""ops.dedup_review_queue (ADR-016, SPRINT-3 §2.5).

Revision ID: 0005_dedup_review_queue
Revises: 0004_fix_source_role_check
Create Date: 2026-05-29

cross-provider 중복 후보(예: knps 사찰 ↔ krheritage temple)를 ``score_pair``
(ADR-016 Record Linkage)로 cross-score한 결과 중 ``manual_review``(및 옵션
``auto_merge``)를 운영자 검토 큐로 영속화한다. ``infra/models.py``의
``DedupReviewQueueRow``와 1:1 (ADR-004 ORM=매핑, 쿼리는 raw SQL
``infra/dedup_repo.py``). UUID 기본값은 pgcrypto를 격리한
``x_extension.gen_random_uuid()``를 스키마 한정으로 호출한다.

점수는 0~100 ``NUMERIC(5,2)`` (core.scoring의 0.0~1.0 점수 ×100). ``status``는
운영자 검토 워크플로(pending→accepted/rejected/merged/ignored)이며
``decision_reason``에 알고리즘 제안(auto_merge/manual_review)을 보관한다.
``(feature_id_a, feature_id_b)`` UNIQUE — 재스캔 시 점수만 갱신, 검토 완료 행은
보존(``infra/dedup_repo.py`` upsert WHERE status='pending').

ADR 참조: ADR-004 / ADR-008 / ADR-016 / ADR-019(TIMESTAMPTZ).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0005_dedup_review_queue"
down_revision: str | Sequence[str] | None = "0004_fix_source_role_check"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "dedup_review_queue",
        sa.Column(
            "review_key",
            postgresql.UUID(as_uuid=False),
            primary_key=True,
            server_default=sa.text("x_extension.gen_random_uuid()"),
        ),
        sa.Column(
            "feature_id_a",
            sa.String(),
            sa.ForeignKey(
                "feature.features.feature_id", ondelete="CASCADE",
                name="fk_dedup_review_queue_feature_id_a_features",
            ),
            nullable=False,
        ),
        sa.Column(
            "feature_id_b",
            sa.String(),
            sa.ForeignKey(
                "feature.features.feature_id", ondelete="CASCADE",
                name="fk_dedup_review_queue_feature_id_b_features",
            ),
            nullable=False,
        ),
        sa.Column("total_score", sa.Numeric(5, 2), nullable=False),
        sa.Column("name_score", sa.Numeric(5, 2), nullable=False),
        sa.Column("spatial_score", sa.Numeric(5, 2), nullable=False),
        sa.Column("category_score", sa.Numeric(5, 2), nullable=False),
        sa.Column(
            "status", sa.String(), nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column("decision_reason", sa.String(), nullable=True),
        sa.Column("reviewed_by", sa.String(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "feature_id_a", "feature_id_b", name="uq_dedup_pair",
        ),
        sa.CheckConstraint(
            "status IN ('pending','accepted','rejected','merged','ignored')",
            name="ck_dedup_status",
        ),
        sa.CheckConstraint(
            "total_score BETWEEN 0 AND 100 AND "
            "name_score BETWEEN 0 AND 100 AND "
            "spatial_score BETWEEN 0 AND 100 AND "
            "category_score BETWEEN 0 AND 100",
            name="ck_dedup_scores",
        ),
        schema="ops",
    )
    op.create_index(
        "idx_dedup_status_score", "dedup_review_queue",
        ["status", sa.text("total_score DESC")], unique=False, schema="ops",
    )


def downgrade() -> None:
    op.drop_table("dedup_review_queue", schema="ops")
