"""ops.enrichment_review_queue (ADR-042, T-RV-52c).

Revision ID: 0019_enrichment_review_queue
Revises: 0018_ops_logs
Create Date: 2026-06-08

visitkorea(2차) 축제 enrichment이 datagokr(1차) festival에 매칭될 때, 이름 유사도가
자동 확정 임계(0.90) 미만·검토 하한(0.70) 이상인 **모호한 밴드**의 매칭을 운영자
수동 검토 큐로 영속화한다(``providers/visitkorea.festival_to_review_candidates``).

dedup_review_queue(두 feature 병합)와 달리 enrichment은 **기존 1차 feature에 source만
잇는다** — 두 번째 feature도, 병합도 없으므로 별도 테이블이다. ``status``는
pending→accepted/rejected/ignored. accept 시 ``source_record``(직렬화된 ``SourceRecord``)
를 복원해 ``SourceLink``(ENRICHMENT, target_feature_id)와 함께 적재한다.

``(target_feature_id, source_provider, source_dataset_key, source_entity_id)`` UNIQUE —
재스캔 시 점수만 갱신, 검토 완료 행은 보존(``infra/enrichment_review_repo.py`` upsert
WHERE status='pending'). UUID 기본값은 schema-한정 ``x_extension.gen_random_uuid()``.

ADR 참조: ADR-004 / ADR-016 / ADR-019(TIMESTAMPTZ) / ADR-042.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0019_enrichment_review_queue"
down_revision: str | Sequence[str] | None = "0018_ops_logs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "enrichment_review_queue",
        sa.Column(
            "review_key",
            postgresql.UUID(as_uuid=False),
            primary_key=True,
            server_default=sa.text("x_extension.gen_random_uuid()"),
        ),
        sa.Column(
            "target_feature_id",
            sa.String(),
            sa.ForeignKey(
                "feature.features.feature_id",
                ondelete="CASCADE",
                name="fk_enrichment_review_queue_target_feature_id_features",
            ),
            nullable=False,
        ),
        sa.Column("source_provider", sa.String(), nullable=False),
        sa.Column("source_dataset_key", sa.String(), nullable=False),
        sa.Column("source_entity_id", sa.String(), nullable=False),
        sa.Column("source_name", sa.String(), nullable=False),
        sa.Column("target_name", sa.String(), nullable=False),
        sa.Column("name_score", sa.Numeric(5, 2), nullable=False),
        sa.Column(
            "source_record",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
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
            "target_feature_id",
            "source_provider",
            "source_dataset_key",
            "source_entity_id",
            name="uq_enrichment_review_candidate",
        ),
        sa.CheckConstraint(
            "status IN ('pending','accepted','rejected','ignored')",
            name="ck_enrichment_review_status",
        ),
        sa.CheckConstraint(
            "name_score BETWEEN 0 AND 100",
            name="ck_enrichment_review_name_score",
        ),
        schema="ops",
    )
    op.create_index(
        "idx_enrichment_review_status_score",
        "enrichment_review_queue",
        ["status", sa.text("name_score DESC")],
        unique=False,
        schema="ops",
    )


def downgrade() -> None:
    op.drop_table("enrichment_review_queue", schema="ops")
