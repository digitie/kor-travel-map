"""ops.import_jobs (ADR-011).

Revision ID: 0006_import_jobs
Revises: 0005_dedup_review_queue
Create Date: 2026-06-01

ETL 적재 작업 상태를 영속화하는 작업 큐 (data-model.md §9.1, SPEC V8 M-14).
프로세스 재시작 시 진행 상황을 잃지 않고, 다중 워커가
``pg_try_advisory_lock`` + ``SELECT ... FOR UPDATE SKIP LOCKED``로 직렬화한다
(``infra/advisory_lock.py`` + ``infra/jobs_repo.py``). UUID 기본값은 pgcrypto를
격리한 ``x_extension.gen_random_uuid()``를 스키마 한정으로 호출한다.

상태 전이: queued → running → done | failed | cancelled. lifespan startup 복구는
``state='running'`` 잔존 행(heartbeat 만료)을 failed로 정리한다 (jobs_repo).

ADR 참조: ADR-004 / ADR-008 / ADR-011 / ADR-019(TIMESTAMPTZ).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0006_import_jobs"
down_revision: str | Sequence[str] | None = "0005_dedup_review_queue"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "import_jobs",
        sa.Column(
            "job_id",
            postgresql.UUID(as_uuid=False),
            primary_key=True,
            server_default=sa.text("x_extension.gen_random_uuid()"),
        ),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column(
            "payload", postgresql.JSONB(), nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "state", sa.Text(), nullable=False,
            server_default=sa.text("'queued'"),
        ),
        sa.Column(
            "progress", sa.Integer(), nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("current_stage", sa.Text(), nullable=True),
        sa.Column("source_checksum", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "state IN ('queued','running','done','failed','cancelled')",
            name="ck_import_jobs_state",
        ),
        sa.CheckConstraint(
            "progress BETWEEN 0 AND 100",
            name="ck_import_jobs_progress",
        ),
        schema="ops",
    )
    op.create_index(
        "idx_import_jobs_state", "import_jobs",
        ["state", "created_at"], schema="ops",
    )
    op.create_index(
        "idx_import_jobs_kind_state", "import_jobs",
        ["kind", "state", sa.text("created_at DESC")], schema="ops",
    )
    op.create_index(
        "idx_import_jobs_heartbeat", "import_jobs",
        ["heartbeat_at"], schema="ops",
        postgresql_where=sa.text("state='running'"),
    )


def downgrade() -> None:
    op.drop_table("import_jobs", schema="ops")
