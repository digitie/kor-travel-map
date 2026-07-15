"""Pipeline 계층형 취소 marker와 정규화 attempt/member/run을 추가한다.

기존 ``ops.import_jobs``/``ops.feature_update_requests`` lifecycle status CHECK는
바꾸지 않는다. 취소 workflow 상태는 ``ops.pipeline_cancellations``, 실제 대상별
결과는 member/run 테이블이 소유한다. base marker는 worker와 lineage mutation의
CAS guard다.

downgrade는 queued/running marker 또는 in-progress/retryable attempt가 있으면
실패한다. 이를 조용히 제거하면 중단 요청을 잃고 worker가 재개될 수 있기 때문이다.

Revision ID: 0050_pipeline_cancellations
Revises: 0049_refresh_stale_after
Create Date: 2026-07-15
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0050_pipeline_cancellations"
down_revision: str | Sequence[str] | None = "0049_refresh_stale_after"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "pipeline_cancellations",
        sa.Column(
            "cancellation_id",
            postgresql.UUID(as_uuid=False),
            server_default=sa.text("x_extension.gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "previous_cancellation_id",
            postgresql.UUID(as_uuid=False),
            nullable=True,
        ),
        sa.Column("root_kind", sa.Text(), nullable=False),
        sa.Column("root_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column(
            "status",
            sa.Text(),
            server_default=sa.text("'in_progress'"),
            nullable=False,
        ),
        sa.Column("requested_by", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("error", postgresql.JSONB(), nullable=True),
        sa.Column(
            "requested_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "root_kind IN ('import_job','update_request')",
            name="ck_pipeline_cancellations_root_kind",
        ),
        sa.CheckConstraint(
            "status IN ('in_progress','retryable','completed','failed')",
            name="ck_pipeline_cancellations_status",
        ),
        sa.CheckConstraint(
            "previous_cancellation_id IS NULL "
            "OR previous_cancellation_id <> cancellation_id",
            name="ck_pipeline_cancellations_previous",
        ),
        sa.CheckConstraint(
            "(status = 'in_progress' AND finished_at IS NULL) OR "
            "(status <> 'in_progress' AND finished_at IS NOT NULL)",
            name="ck_pipeline_cancellations_finished",
        ),
        sa.CheckConstraint(
            "(status IN ('in_progress','completed') AND error IS NULL) OR "
            "(status IN ('retryable','failed') AND error IS NOT NULL "
            " AND jsonb_typeof(error) = 'object')",
            name="ck_pipeline_cancellations_error_shape",
        ),
        sa.ForeignKeyConstraint(
            ["previous_cancellation_id"],
            ["ops.pipeline_cancellations.cancellation_id"],
            name="fk_pipeline_cancellations_previous",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "cancellation_id",
            name="pk_pipeline_cancellations",
        ),
        schema="ops",
    )
    op.create_index(
        "uq_pipeline_cancellations_active_root",
        "pipeline_cancellations",
        ["root_kind", "root_id"],
        schema="ops",
        unique=True,
        postgresql_where=sa.text("status = 'in_progress'"),
    )
    op.create_index(
        "idx_pipeline_cancellations_root_history",
        "pipeline_cancellations",
        ["root_kind", "root_id", sa.text("requested_at DESC"), sa.text("cancellation_id DESC")],
        schema="ops",
    )
    op.create_index(
        "idx_pipeline_cancellations_previous",
        "pipeline_cancellations",
        ["previous_cancellation_id"],
        schema="ops",
    )

    op.create_table(
        "pipeline_cancellation_runs",
        sa.Column(
            "cancellation_id",
            postgresql.UUID(as_uuid=False),
            nullable=False,
        ),
        sa.Column("dagster_run_id", sa.Text(), nullable=False),
        sa.Column("initial_status", sa.Text(), nullable=True),
        sa.Column(
            "termination_reserved_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "result",
            sa.Text(),
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
        sa.Column("terminal_status", sa.Text(), nullable=True),
        sa.Column("error", postgresql.JSONB(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "result IN ('pending','cancelled','already_terminal','cancel_failed')",
            name="ck_pipeline_cancellation_runs_result",
        ),
        sa.CheckConstraint(
            "(termination_reserved_at IS NULL OR initial_status IS NOT NULL) AND ("
            " (result = 'pending' AND terminal_status IS NULL AND error IS NULL) OR "
            " (result = 'cancelled' AND terminal_status = 'CANCELED' AND error IS NULL) OR "
            " (result = 'already_terminal' AND "
            "  (terminal_status IS NULL OR terminal_status IN ('SUCCESS','FAILURE')) "
            "  AND error IS NULL) OR "
            " (result = 'cancel_failed' AND terminal_status IS NULL AND error IS NOT NULL "
            "  AND jsonb_typeof(error) = 'object'))",
            name="ck_pipeline_cancellation_runs_shape",
        ),
        sa.ForeignKeyConstraint(
            ["cancellation_id"],
            ["ops.pipeline_cancellations.cancellation_id"],
            name="fk_pipeline_cancellation_runs_attempt",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "cancellation_id",
            "dagster_run_id",
            name="pk_pipeline_cancellation_runs",
        ),
        schema="ops",
    )

    op.create_table(
        "pipeline_cancellation_members",
        sa.Column(
            "cancellation_id",
            postgresql.UUID(as_uuid=False),
            nullable=False,
        ),
        sa.Column("member_kind", sa.Text(), nullable=False),
        sa.Column("member_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("dagster_run_id", sa.Text(), nullable=True),
        sa.Column("initial_status", sa.Text(), nullable=False),
        sa.Column(
            "result",
            sa.Text(),
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
        sa.Column("terminal_status", sa.Text(), nullable=True),
        sa.Column("error", postgresql.JSONB(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "member_kind IN ('import_job','update_request')",
            name="ck_pipeline_cancellation_members_kind",
        ),
        sa.CheckConstraint(
            "result IN ('pending','cancelled','already_terminal','cancel_failed')",
            name="ck_pipeline_cancellation_members_result",
        ),
        sa.CheckConstraint(
            "(result = 'pending' AND terminal_status IS NULL AND error IS NULL) OR "
            "(result = 'cancelled' AND terminal_status = 'cancelled' AND error IS NULL) OR "
            "(result = 'already_terminal' "
            " AND terminal_status IN ('done','failed','cancelled') AND error IS NULL) OR "
            "(result = 'cancel_failed' AND terminal_status IS NULL AND error IS NOT NULL "
            " AND jsonb_typeof(error) = 'object')",
            name="ck_pipeline_cancellation_members_shape",
        ),
        sa.ForeignKeyConstraint(
            ["cancellation_id"],
            ["ops.pipeline_cancellations.cancellation_id"],
            name="fk_pipeline_cancellation_members_attempt",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["cancellation_id", "dagster_run_id"],
            [
                "ops.pipeline_cancellation_runs.cancellation_id",
                "ops.pipeline_cancellation_runs.dagster_run_id",
            ],
            name="fk_pipeline_cancellation_members_run",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "cancellation_id",
            "member_kind",
            "member_id",
            name="pk_pipeline_cancellation_members",
        ),
        schema="ops",
    )
    op.create_index(
        "idx_pipeline_cancellation_members_member",
        "pipeline_cancellation_members",
        [
            "member_kind",
            "member_id",
            sa.text("updated_at DESC"),
            sa.text("cancellation_id DESC"),
        ],
        schema="ops",
    )
    op.create_index(
        "idx_pipeline_cancellation_members_run",
        "pipeline_cancellation_members",
        ["cancellation_id", "dagster_run_id"],
        schema="ops",
    )

    for table_name, constraint_name in (
        ("import_jobs", "ck_import_jobs_cancellation_marker"),
        (
            "feature_update_requests",
            "ck_feature_update_requests_cancellation_marker",
        ),
    ):
        op.add_column(
            table_name,
            sa.Column(
                "cancellation_id",
                postgresql.UUID(as_uuid=False),
                nullable=True,
            ),
            schema="ops",
        )
        op.add_column(
            table_name,
            sa.Column(
                "cancellation_requested_at",
                sa.DateTime(timezone=True),
                nullable=True,
            ),
            schema="ops",
        )
        op.add_column(
            table_name,
            sa.Column("cancellation_requested_by", sa.Text(), nullable=True),
            schema="ops",
        )
        op.add_column(
            table_name,
            sa.Column("cancellation_reason", sa.Text(), nullable=True),
            schema="ops",
        )
        op.create_foreign_key(
            f"fk_{table_name}_cancellation",
            table_name,
            "pipeline_cancellations",
            ["cancellation_id"],
            ["cancellation_id"],
            source_schema="ops",
            referent_schema="ops",
            ondelete="RESTRICT",
        )
        op.create_check_constraint(
            constraint_name,
            table_name,
            "(cancellation_id IS NULL AND cancellation_requested_at IS NULL "
            "AND cancellation_requested_by IS NULL AND cancellation_reason IS NULL) "
            "OR (cancellation_id IS NOT NULL "
            "AND cancellation_requested_at IS NOT NULL "
            "AND cancellation_requested_by IS NOT NULL)",
            schema="ops",
        )
        op.create_index(
            f"idx_{table_name}_cancellation_id",
            table_name,
            ["cancellation_id"],
            schema="ops",
        )


def downgrade() -> None:
    connection = op.get_bind()
    # 검사와 DDL 사이에 marker/attempt writer가 끼어드는 TOCTOU를 막는다.
    # 정규화 attempt→member→run과 base request→job의 고정 순서로 잠가
    # Alembic transaction이 끝날 때까지 신규 writer를 대기시킨다.
    connection.execute(
        sa.text(
            """
            LOCK TABLE
                ops.pipeline_cancellations,
                ops.pipeline_cancellation_members,
                ops.pipeline_cancellation_runs,
                ops.feature_update_requests,
                ops.import_jobs
            IN ACCESS EXCLUSIVE MODE
            """
        )
    )
    blocked = connection.execute(
        sa.text(
            """
            SELECT EXISTS (
                SELECT 1
                FROM ops.pipeline_cancellations
                WHERE status IN ('in_progress', 'retryable')
                UNION ALL
                SELECT 1
                FROM ops.import_jobs
                WHERE cancellation_id IS NOT NULL
                  AND status IN ('queued', 'running')
                UNION ALL
                SELECT 1
                FROM ops.feature_update_requests
                WHERE cancellation_id IS NOT NULL
                  AND status IN ('queued', 'running')
            )
            """
        )
    ).scalar_one()
    if blocked:
        raise RuntimeError(
            "0050 downgrade refused: active pipeline cancellation marker/attempt exists"
        )

    for table_name, constraint_name in (
        ("feature_update_requests", "ck_feature_update_requests_cancellation_marker"),
        ("import_jobs", "ck_import_jobs_cancellation_marker"),
    ):
        op.drop_index(
            f"idx_{table_name}_cancellation_id",
            table_name=table_name,
            schema="ops",
        )
        op.drop_constraint(
            constraint_name,
            table_name,
            schema="ops",
            type_="check",
        )
        op.drop_constraint(
            f"fk_{table_name}_cancellation",
            table_name,
            schema="ops",
            type_="foreignkey",
        )
        op.drop_column(table_name, "cancellation_reason", schema="ops")
        op.drop_column(table_name, "cancellation_requested_by", schema="ops")
        op.drop_column(table_name, "cancellation_requested_at", schema="ops")
        op.drop_column(table_name, "cancellation_id", schema="ops")

    op.drop_index(
        "idx_pipeline_cancellation_members_run",
        table_name="pipeline_cancellation_members",
        schema="ops",
    )
    op.drop_index(
        "idx_pipeline_cancellation_members_member",
        table_name="pipeline_cancellation_members",
        schema="ops",
    )
    op.drop_table("pipeline_cancellation_members", schema="ops")
    op.drop_table("pipeline_cancellation_runs", schema="ops")
    op.drop_index(
        "idx_pipeline_cancellations_previous",
        table_name="pipeline_cancellations",
        schema="ops",
    )
    op.drop_index(
        "idx_pipeline_cancellations_root_history",
        table_name="pipeline_cancellations",
        schema="ops",
    )
    op.drop_index(
        "uq_pipeline_cancellations_active_root",
        table_name="pipeline_cancellations",
        schema="ops",
    )
    op.drop_table("pipeline_cancellations", schema="ops")
