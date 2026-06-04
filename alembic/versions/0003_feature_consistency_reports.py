"""ops.feature_consistency_reports (ADR-033 Phase 1, Sprint 3).

Revision ID: 0003_consistency_reports
Revises: 0002_features_source
Create Date: 2026-05-29

``infra/models.py``의 ``FeatureConsistencyReportRow``와 1:1 (ADR-004 ORM=매핑,
쿼리는 raw SQL ``infra/consistency.py``). ADR-033 Phase 1 — F1~F3 정합성 배치
결과 영속화. UUID 기본값은 pgcrypto를 격리한
``x_extension.gen_random_uuid()``를 스키마 한정으로 호출한다. Dagster 게이트(swap
차단)는 Phase 2(Sprint 5)에서.

ADR 참조: ADR-004 / ADR-008 / ADR-017(미러) / ADR-033.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0003_consistency_reports"
down_revision: str | Sequence[str] | None = "0002_features_source"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "feature_consistency_reports",
        sa.Column(
            "report_id",
            postgresql.UUID(as_uuid=False),
            primary_key=True,
            server_default=sa.text("x_extension.gen_random_uuid()"),
        ),
        sa.Column("batch_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("severity_max", sa.String(), nullable=False),
        sa.Column("cases", postgresql.JSONB(), nullable=False),
        sa.Column("summary", postgresql.JSONB(), nullable=False),
        sa.CheckConstraint(
            "severity_max IN ('OK','WARN','ERROR')",
            name="feature_consistency_reports_severity_max",
        ),
        schema="ops",
    )
    op.create_index(
        "idx_reports_batch", "feature_consistency_reports", ["batch_id"],
        unique=False, schema="ops",
    )
    op.create_index(
        "idx_reports_started", "feature_consistency_reports",
        [sa.text("started_at DESC")], unique=False, schema="ops",
    )


def downgrade() -> None:
    op.drop_table("feature_consistency_reports", schema="ops")
