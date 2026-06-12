"""ops.feature_merge_history (ADR-016 manual merge).

Revision ID: 0007_feature_merge_history
Revises: 0006_import_jobs
Create Date: 2026-06-01

dedup 중복 병합 이력. ADR-016이 명시한 ``feature_merge_history(loser_id,
master_id, score, merged_at)``를 영속화한다. ``kor-travel-map dedup-merge`` 명령이
``ops.dedup_review_queue``의 후보 1쌍을 master/loser로 확정해 병합할 때, loser의
``source_links``를 master로 재지정하고 loser feature를 soft-delete(status='deleted')
한 뒤 본 테이블에 이력을 남긴다.

UUID 기본값은 pgcrypto를 격리한 ``x_extension.gen_random_uuid()``를 스키마 한정으로
호출한다. master/loser FK는 feature 하드 삭제 시 CASCADE(dedup_review_queue와 동일 정책);
``review_key`` FK는 큐 행이 사라지면 SET NULL(이력은 보존).

ADR 참조: ADR-004 / ADR-008 / ADR-016 / ADR-017 / ADR-019(TIMESTAMPTZ).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0007_feature_merge_history"
down_revision: str | Sequence[str] | None = "0006_import_jobs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "feature_merge_history",
        sa.Column(
            "merge_id",
            postgresql.UUID(as_uuid=False),
            primary_key=True,
            server_default=sa.text("x_extension.gen_random_uuid()"),
        ),
        sa.Column(
            "master_feature_id",
            sa.Text(),
            sa.ForeignKey(
                "feature.features.feature_id", ondelete="CASCADE"
            ),
            nullable=False,
        ),
        sa.Column(
            "loser_feature_id",
            sa.Text(),
            sa.ForeignKey(
                "feature.features.feature_id", ondelete="CASCADE"
            ),
            nullable=False,
        ),
        sa.Column("score", sa.Numeric(5, 2), nullable=True),
        sa.Column(
            "review_key",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey(
                "ops.dedup_review_queue.review_key", ondelete="SET NULL"
            ),
            nullable=True,
        ),
        sa.Column("merged_by", sa.Text(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "merged_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "master_feature_id <> loser_feature_id",
            name="ck_merge_history_distinct",
        ),
        schema="ops",
    )
    # "이 feature가 어디로 병합됐나" 역추적 — loser_feature_id로 1건 조회.
    op.create_index(
        "idx_merge_history_loser",
        "feature_merge_history",
        ["loser_feature_id"],
        schema="ops",
    )
    # master가 흡수한 loser 목록 + 시간순.
    op.create_index(
        "idx_merge_history_master",
        "feature_merge_history",
        ["master_feature_id", sa.text("merged_at DESC")],
        schema="ops",
    )


def downgrade() -> None:
    op.drop_table("feature_merge_history", schema="ops")
