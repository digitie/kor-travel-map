"""cache-target writer drain의 Map 소유 durable lease를 추가한다.

Revision ID: 0079_cache_target_writer_drain
Revises: 0078_cache_target_gc_observe
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0079_cache_target_writer_drain"
down_revision: str | Sequence[str] | None = "0078_cache_target_gc_observe"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "cache_target_writer_drain_leases",
        sa.Column(
            "lease_id",
            postgresql.UUID(as_uuid=False),
            server_default=sa.text("x_extension.gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("owner_kind", sa.Text(), nullable=False),
        sa.Column("owner_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("snapshot_sha256", sa.Text(), nullable=False),
        sa.Column("receipt_sha256", sa.Text(), nullable=True),
        sa.Column("receipt_operation", sa.Text(), nullable=True),
        sa.Column("receipt_prior_sha256", sa.Text(), nullable=True),
        sa.Column("failure_code", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("clock_timestamp()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("clock_timestamp()"),
            nullable=False,
        ),
        sa.Column("restored_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "owner_kind IN ('diagnostic','cutover')",
            name=op.f("ck_cache_target_writer_drain_leases_owner_kind"),
        ),
        sa.CheckConstraint(
            "state IN ('draining','drained','restoring','restored')",
            name=op.f("ck_cache_target_writer_drain_leases_state"),
        ),
        sa.CheckConstraint(
            "snapshot_sha256 ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_cache_target_writer_drain_leases_snapshot_sha256"),
        ),
        sa.CheckConstraint(
            "receipt_sha256 IS NULL OR receipt_sha256 ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_cache_target_writer_drain_leases_receipt_sha256"),
        ),
        sa.CheckConstraint(
            "receipt_prior_sha256 IS NULL OR receipt_prior_sha256 ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_cache_target_writer_drain_leases_receipt_prior_sha256"),
        ),
        sa.CheckConstraint(
            "failure_code IS NULL OR failure_code ~ '^[A-Z][A-Z0-9_]{0,63}$'",
            name=op.f("ck_cache_target_writer_drain_leases_failure_code"),
        ),
        sa.CheckConstraint(
            "(state <> 'draining') = (receipt_sha256 IS NOT NULL "
            "AND receipt_operation IS NOT NULL) AND "
            "(receipt_operation IS NULL OR receipt_operation IN "
            "('begin','attest','restore'))",
            name=op.f("ck_cache_target_writer_drain_leases_receipt"),
        ),
        sa.CheckConstraint(
            "(state = 'restored') = (restored_at IS NOT NULL)",
            name=op.f("ck_cache_target_writer_drain_leases_restored_at"),
        ),
        sa.PrimaryKeyConstraint("lease_id", name=op.f("pk_cache_target_writer_drain_leases")),
        sa.UniqueConstraint(
            "owner_kind",
            "owner_id",
            name=op.f("uq_cache_target_writer_drain_leases_owner"),
        ),
        schema="ops",
    )
    op.create_index(
        "uq_cache_target_writer_drain_leases_active",
        "cache_target_writer_drain_leases",
        [sa.text("(1)")],
        unique=True,
        schema="ops",
        postgresql_where=sa.text("state IN ('draining','drained','restoring')"),
    )
    op.create_index(
        "idx_cache_target_writer_drain_leases_owner_history",
        "cache_target_writer_drain_leases",
        ["owner_kind", "owner_id", sa.text("created_at DESC")],
        schema="ops",
    )
    op.create_table(
        "cache_target_writer_drain_instigations",
        sa.Column("lease_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("selector_id", sa.Text(), nullable=False),
        sa.Column("state_id", sa.Text(), nullable=False),
        sa.Column("origin_id", sa.Text(), nullable=False),
        sa.Column("instigation_name", sa.Text(), nullable=False),
        sa.Column("repository_name", sa.Text(), nullable=False),
        sa.Column("repository_location_name", sa.Text(), nullable=False),
        sa.Column("was_running", sa.Boolean(), nullable=False),
        sa.Column(
            "pause_result",
            sa.Text(),
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
        sa.Column("paused_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "restore_result",
            sa.Text(),
            server_default=sa.text("'not_requested'"),
            nullable=False,
        ),
        sa.Column("restored_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "kind IN ('schedule','sensor')",
            name=op.f("ck_cache_target_writer_drain_instigations_kind"),
        ),
        sa.CheckConstraint(
            "selector_id = btrim(selector_id) AND selector_id <> '' AND "
            "state_id = btrim(state_id) AND state_id <> '' AND "
            "origin_id = btrim(origin_id) AND origin_id <> '' AND "
            "instigation_name = btrim(instigation_name) AND instigation_name <> '' AND "
            "repository_name = btrim(repository_name) AND repository_name <> '' AND "
            "repository_location_name = btrim(repository_location_name) "
            "AND repository_location_name <> ''",
            name=op.f("ck_cache_target_writer_drain_instigations_identity"),
        ),
        sa.CheckConstraint(
            "pause_result IN ('pending','paused','already_stopped','not_required') "
            "AND restore_result IN ('not_requested','restored','already_running')",
            name=op.f("ck_cache_target_writer_drain_instigations_results"),
        ),
        sa.CheckConstraint(
            "(was_running AND pause_result <> 'not_required') OR "
            "(NOT was_running AND pause_result = 'not_required' "
            "AND restore_result = 'not_requested')",
            name=op.f("ck_cache_target_writer_drain_instigations_original_state"),
        ),
        sa.ForeignKeyConstraint(
            ["lease_id"],
            ["ops.cache_target_writer_drain_leases.lease_id"],
            name=op.f("fk_cache_target_writer_drain_instigations_lease"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "lease_id",
            "kind",
            "selector_id",
            name=op.f("pk_cache_target_writer_drain_instigations"),
        ),
        schema="ops",
    )
    op.create_index(
        "idx_cache_target_writer_drain_instigations_lease",
        "cache_target_writer_drain_instigations",
        ["lease_id"],
        schema="ops",
    )
    op.create_table(
        "cache_target_writer_drain_runs",
        sa.Column("lease_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("dagster_run_id", sa.Text(), nullable=False),
        sa.Column("initial_status", sa.Text(), nullable=False),
        sa.Column(
            "cancel_result",
            sa.Text(),
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
        sa.Column("cancel_reserved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancel_dispatched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("terminal_status", sa.Text(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("clock_timestamp()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "dagster_run_id = btrim(dagster_run_id) AND dagster_run_id <> '' AND "
            "initial_status = btrim(initial_status) AND initial_status <> ''",
            name=op.f("ck_cache_target_writer_drain_runs_identity"),
        ),
        sa.CheckConstraint(
            "cancel_result IN ('pending','reserved','dispatched','terminal','outcome_uncertain')",
            name=op.f("ck_cache_target_writer_drain_runs_cancel_result"),
        ),
        sa.CheckConstraint(
            "terminal_status IS NULL OR terminal_status ~ '^[A-Z_]+$'",
            name=op.f("ck_cache_target_writer_drain_runs_terminal_status"),
        ),
        sa.CheckConstraint(
            "(cancel_result = 'pending' AND cancel_reserved_at IS NULL "
            "AND cancel_dispatched_at IS NULL AND terminal_status IS NULL) OR "
            "(cancel_result IN ('reserved','outcome_uncertain') "
            "AND cancel_reserved_at IS NOT NULL AND cancel_dispatched_at IS NULL "
            "AND terminal_status IS NULL) OR "
            "(cancel_result = 'dispatched' AND cancel_reserved_at IS NOT NULL "
            "AND cancel_dispatched_at IS NOT NULL AND terminal_status IS NULL) OR "
            "(cancel_result = 'terminal' AND terminal_status IS NOT NULL)",
            name=op.f("ck_cache_target_writer_drain_runs_cancel_evidence"),
        ),
        sa.ForeignKeyConstraint(
            ["lease_id"],
            ["ops.cache_target_writer_drain_leases.lease_id"],
            name=op.f("fk_cache_target_writer_drain_runs_lease"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "lease_id",
            "dagster_run_id",
            name=op.f("pk_cache_target_writer_drain_runs"),
        ),
        schema="ops",
    )
    op.create_index(
        "idx_cache_target_writer_drain_runs_lease",
        "cache_target_writer_drain_runs",
        ["lease_id"],
        schema="ops",
    )


def downgrade() -> None:
    op.execute("LOCK TABLE ops.cache_target_writer_drain_leases IN ACCESS EXCLUSIVE MODE")
    op.execute(
        """
        DO $$
        BEGIN
          IF EXISTS (
            SELECT 1
            FROM ops.cache_target_writer_drain_leases
            WHERE state IN ('draining','drained','restoring')
          ) THEN
            RAISE EXCEPTION 'active cache-target writer drain lease prevents downgrade';
          END IF;
        END
        $$
        """
    )
    op.drop_index(
        "idx_cache_target_writer_drain_runs_lease",
        table_name="cache_target_writer_drain_runs",
        schema="ops",
    )
    op.drop_table("cache_target_writer_drain_runs", schema="ops")
    op.drop_index(
        "idx_cache_target_writer_drain_instigations_lease",
        table_name="cache_target_writer_drain_instigations",
        schema="ops",
    )
    op.drop_table("cache_target_writer_drain_instigations", schema="ops")
    op.drop_index(
        "idx_cache_target_writer_drain_leases_owner_history",
        table_name="cache_target_writer_drain_leases",
        schema="ops",
    )
    op.drop_index(
        "uq_cache_target_writer_drain_leases_active",
        table_name="cache_target_writer_drain_leases",
        schema="ops",
    )
    op.drop_table("cache_target_writer_drain_leases", schema="ops")
