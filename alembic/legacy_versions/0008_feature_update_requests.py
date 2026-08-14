"""ops.feature_update_requests (ADR-045 feature update queue).

Revision ID: 0008_feature_update_requests
Revises: 0007_feature_merge_history
Create Date: 2026-06-03

OpenAPI로 들어온 feature update request를 Dagster run/import job과 연결해 추적하는
큐 테이블이다. T-205a는 테이블과 ORM 매핑까지만 추가하고, scope 해석과 enqueue/
claim repository는 T-206 계열에서 별도 PR로 구현한다.

ADR 참조: ADR-004 / ADR-008 / ADR-011 / ADR-019 / ADR-045 / ADR-047.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0008_feature_update_requests"
down_revision: str | Sequence[str] | None = "0007_feature_merge_history"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "feature_update_requests",
        sa.Column(
            "request_id",
            postgresql.UUID(as_uuid=False),
            primary_key=True,
            server_default=sa.text("x_extension.gen_random_uuid()"),
        ),
        sa.Column("scope_type", sa.Text(), nullable=False),
        sa.Column("scope", postgresql.JSONB(), nullable=False),
        sa.Column(
            "providers",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "dataset_keys",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "update_policy",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("run_mode", sa.Text(), nullable=False),
        sa.Column(
            "priority",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("50"),
        ),
        sa.Column(
            "state",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'queued'"),
        ),
        sa.Column(
            "dry_run",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "matched_scope",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "job_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("ops.import_jobs.job_id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("dagster_run_id", sa.Text(), nullable=True),
        sa.Column("operator", sa.Text(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "scope_type IN ("
            "'feature_ids','center_radius','sigungu_by_radius','bbox',"
            "'provider_dataset','cache_target_keys'"
            ")",
            name="ck_feature_update_scope",
        ),
        sa.CheckConstraint(
            "run_mode IN ('queued','now')",
            name="ck_feature_update_run_mode",
        ),
        sa.CheckConstraint(
            "state IN ('queued','running','done','failed','cancelled')",
            name="ck_feature_update_state",
        ),
        schema="ops",
    )
    op.create_index(
        "idx_feature_update_state_priority",
        "feature_update_requests",
        ["state", sa.text("priority DESC"), "created_at"],
        schema="ops",
    )
    op.create_index(
        "idx_feature_update_created",
        "feature_update_requests",
        [sa.text("created_at DESC")],
        schema="ops",
    )
    op.create_index(
        "idx_feature_update_job",
        "feature_update_requests",
        ["job_id"],
        schema="ops",
        postgresql_where=sa.text("job_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_table("feature_update_requests", schema="ops")
