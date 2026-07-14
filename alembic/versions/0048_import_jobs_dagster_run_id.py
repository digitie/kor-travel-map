"""``ops.import_jobs.dagster_run_id`` 실컬럼 + payload 백필 + 부분 인덱스.

ADR-064 (T-ADM-C3): ``/ops/live`` dagster_runs 스냅샷/역조회가 payload JSONB
``?``/``->>`` 연산 풀스캔에 의존하던 hot path(기본 2s poll)를 실컬럼 기반으로
전환한다(전례: feature_id 검색 #639). 기존 행은 ``payload->>'dagster_run_id'``
(레거시 ``payload->>'run_id'`` fallback)로 백필한다.

Revision ID: 0048_import_jobs_dagster_run_id
Revises: 0047_notice_reconcile_statistics
Create Date: 2026-07-14
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0048_import_jobs_dagster_run_id"
down_revision: str | Sequence[str] | None = "0047_notice_reconcile_statistics"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "import_jobs",
        sa.Column("dagster_run_id", sa.Text(), nullable=True),
        schema="ops",
    )
    # 기존 payload 백필 — 신규 키 ``dagster_run_id`` 우선, 레거시 ``run_id`` fallback.
    # 빈 문자열은 컬럼 NULL로 정규화한다.
    op.execute(
        sa.text(
            """
            UPDATE ops.import_jobs
            SET dagster_run_id = NULLIF(
                COALESCE(payload->>'dagster_run_id', payload->>'run_id'),
                ''
            )
            WHERE payload ? 'dagster_run_id' OR payload ? 'run_id'
            """
        )
    )
    op.create_index(
        "idx_import_jobs_dagster_run_id",
        "import_jobs",
        ["dagster_run_id"],
        schema="ops",
        postgresql_where=sa.text("dagster_run_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "idx_import_jobs_dagster_run_id",
        table_name="import_jobs",
        schema="ops",
    )
    op.drop_column("import_jobs", "dagster_run_id", schema="ops")
