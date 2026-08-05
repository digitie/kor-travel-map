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


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM ops.c6c_cancel_probe_fixtures) THEN
            RAISE EXCEPTION
              '0084 downgrade refused: C6c cancel-probe fixture history exists';
          END IF;
        END $$
        """
    )
    op.drop_table("c6c_cancel_probe_fixtures", schema="ops")
