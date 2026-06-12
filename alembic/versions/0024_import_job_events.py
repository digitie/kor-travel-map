"""ops.import_job_events 단계 이벤트 테이블 추가.

Revision ID: 0024_import_job_events
Revises: 0023_t216f_rest_names
Create Date: 2026-06-12

T-221b admin job 상세 화면이 작업 단계별 event timeline을 조회할 수 있게
``ops.import_jobs``에 종속된 구조화 event 테이블을 추가한다.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0024_import_job_events"
down_revision: str | Sequence[str] | None = "0023_t216f_rest_names"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE ops.import_job_events (
            event_id    UUID PRIMARY KEY DEFAULT x_extension.gen_random_uuid(),
            job_id      UUID NOT NULL
                REFERENCES ops.import_jobs(job_id) ON DELETE CASCADE,
            provider    TEXT,
            dataset_key TEXT,
            feature_id  TEXT,
            stage       TEXT,
            level       TEXT NOT NULL,
            code        TEXT,
            message     TEXT NOT NULL,
            payload     JSONB NOT NULL DEFAULT '{}'::jsonb,
            occurred_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_import_job_events_level
                CHECK (level IN ('debug','info','warning','error','critical'))
        )
        """
    )
    op.execute(
        """
        CREATE INDEX idx_import_job_events_job_time
        ON ops.import_job_events (job_id, occurred_at DESC, event_id DESC)
        """
    )
    op.execute(
        """
        CREATE INDEX idx_import_job_events_provider_time
        ON ops.import_job_events (provider, occurred_at DESC, event_id DESC)
        WHERE provider IS NOT NULL
        """
    )
    op.execute(
        """
        CREATE INDEX idx_import_job_events_level_time
        ON ops.import_job_events (level, occurred_at DESC, event_id DESC)
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS ops.import_job_events")
