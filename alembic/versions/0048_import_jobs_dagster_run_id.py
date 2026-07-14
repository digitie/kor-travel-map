"""``ops.import_jobs.dagster_run_id`` 실컬럼 + payload 백필 + 부분 인덱스.

ADR-064 (T-ADM-C3): ``/ops/live`` dagster_runs 스냅샷/역조회가 payload JSONB
``?``/``->>`` 연산 풀스캔에 의존하던 hot path(기본 2s poll)를 실컬럼 기반으로
전환한다(전례: feature_id 검색 #639). 기존 행은 ``payload->>'dagster_run_id'``
(레거시 ``payload->>'run_id'`` fallback)로 백필한다.

배포 순서 주의 (mixed-version 창)
---------------------------------
migration runner는 **api-entrypoint뿐**이다(dagster는 alembic을 돌리지 않음).
따라서 (a) 신 jobs_repo(dagster/CLI)가 api migration **이전**에 INSERT하면
UndefinedColumn으로 실패한다 — **api 컨테이너를 먼저 기동해 0048을 적용한 뒤
dagster를 재기동**하라. (b) 구 dagster 이미지가 migration **이후** payload-only
row를 쓰는 창이 남는다 — 읽기 경로(ops_live)는 COALESCE payload 폴백으로 창
내 row도 잡지만, 컬럼을 수렴시키려면 구 이미지 소진 후 백필 SQL을 1회 재실행:

    UPDATE ops.import_jobs
    SET dagster_run_id = NULLIF(
        COALESCE(payload->>'dagster_run_id', payload->>'run_id'), '')
    WHERE dagster_run_id IS NULL
      AND (payload ? 'dagster_run_id' OR payload ? 'run_id');

Revision ID: 0048_import_jobs_dagster_run_id
Revises: 0047_notice_reconcile_stats
Create Date: 2026-07-14
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0048_import_jobs_dagster_run_id"
down_revision: str | Sequence[str] | None = "0047_notice_reconcile_stats"
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
