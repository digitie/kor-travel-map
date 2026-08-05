"""Map-owned C6c cancel-probe fixture lifecycle (T-VN-41F1J, ADR-084).

Fixture state is deliberately separate from normal import-job lifecycle.  The table keeps
the Map-generated probe job, canonical cancellation, and arm/consume/finalize transition
in one durable owner boundary.

Revision ID: 0084_c6c_cancel_probe_fixtures
Revises: 0083_nonderived_uuid_generator
Create Date: 2026-08-06
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0084_c6c_cancel_probe_fixtures"
down_revision: str | Sequence[str] | None = "0083_nonderived_uuid_generator"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "c6c_cancel_probe_fixtures",
        sa.Column("transaction_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("job_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("cancellation_id", postgresql.UUID(as_uuid=False), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("clock_timestamp()"),
            nullable=False,
        ),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finalized_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "state IN ('armed','consumed','finalized')",
            name="ck_c6c_cancel_probe_fixtures_state",
        ),
        sa.CheckConstraint(
            "(state = 'armed' AND cancellation_id IS NULL "
            " AND consumed_at IS NULL AND finalized_at IS NULL) OR "
            "(state = 'consumed' AND cancellation_id IS NOT NULL "
            " AND consumed_at IS NOT NULL AND finalized_at IS NULL) OR "
            "(state = 'finalized' AND cancellation_id IS NOT NULL "
            " AND consumed_at IS NOT NULL AND finalized_at IS NOT NULL "
            " AND finalized_at >= consumed_at)",
            name="ck_c6c_cancel_probe_fixtures_transition",
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["ops.import_jobs.job_id"],
            name="fk_c6c_cancel_probe_fixtures_job",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["cancellation_id"],
            ["ops.pipeline_cancellations.cancellation_id"],
            name="fk_c6c_cancel_probe_fixtures_cancellation",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("transaction_id", name="pk_c6c_cancel_probe_fixtures"),
        sa.UniqueConstraint("job_id", name="uq_c6c_cancel_probe_fixtures_job"),
        sa.UniqueConstraint("cancellation_id", name="uq_c6c_cancel_probe_fixtures_cancellation"),
        schema="ops",
    )
    # event audit은 ordered partial index만으로 읽는다. fixture job은 어떤 쓰기
    # 경로에서도 event를 가질 수 없다는 경계를 DB에서 강제해, 읽기 때 import job을
    # join하여 그 index 경로를 훼손하지 않는다. 기존 identity trigger가 job_id 변경을
    # 이미 불변으로 고정하므로 이 trigger는 새 event INSERT만 담당한다.
    op.execute(
        """
        CREATE FUNCTION ops.reject_c6c_cancel_probe_event()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
          IF EXISTS (
            SELECT 1
            FROM ops.import_jobs AS job
            WHERE job.job_id = NEW.job_id
              AND job.kind = 'c6c_cancel_probe'
          ) THEN
            RAISE EXCEPTION
              'c6c cancel-probe job cannot own import job events: %', NEW.job_id
              USING ERRCODE = 'check_violation';
          END IF;
          RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_import_job_events_reject_c6c_cancel_probe
        BEFORE INSERT ON ops.import_job_events
        FOR EACH ROW EXECUTE FUNCTION ops.reject_c6c_cancel_probe_event()
        """
    )


def downgrade() -> None:
    # 서비스 전 단계에서는 중간 fixture 이력 보전보다 schema 재구성이 우선이다.
    op.execute(
        "DROP TRIGGER trg_import_job_events_reject_c6c_cancel_probe "
        "ON ops.import_job_events"
    )
    op.execute("DROP FUNCTION ops.reject_c6c_cancel_probe_event()")
    op.drop_table("c6c_cancel_probe_fixtures", schema="ops")
