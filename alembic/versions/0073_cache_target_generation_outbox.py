"""cache target generation, restore fence와 result outbox를 정규화한다.

Revision ID: 0073_cache_target_outbox
Revises: 0072_curation_provenance
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0073_cache_target_outbox"
down_revision: str | Sequence[str] | None = "0072_curation_provenance"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_SHA256_CHECK = "VALUE ~ '^[0-9a-f]{64}$'"


def _sha256_check(column: str, name: str) -> sa.CheckConstraint:
    return sa.CheckConstraint(
        _SHA256_CHECK.replace("VALUE", column),
        name=name,
    )


def upgrade() -> None:
    op.create_index(
        "uq_poi_cache_targets_source_identity",
        "poi_cache_targets",
        ["target_id", "external_system", "target_key"],
        unique=True,
        schema="ops",
    )
    op.create_table(
        "poi_cache_target_streams",
        sa.Column("external_system", sa.Text(), nullable=False),
        sa.Column("consumer_id", sa.Text(), nullable=False),
        sa.Column("restore_epoch", sa.BigInteger(), nullable=False),
        sa.Column(
            "control_version",
            sa.BigInteger(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.Column(
            "status",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'fenced'"),
        ),
        sa.Column("blocked_event_id", postgresql.UUID(as_uuid=False)),
        sa.Column("last_barrier_command_id", sa.BigInteger()),
        sa.Column(
            "consumer_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "btrim(external_system) <> '' AND char_length(external_system) <= 112",
            name="ck_cache_target_streams_external_system",
        ),
        sa.CheckConstraint(
            "btrim(consumer_id) <> '' AND char_length(consumer_id) <= 128",
            name="ck_cache_target_streams_consumer",
        ),
        sa.CheckConstraint(
            "restore_epoch > 0 AND control_version > 0",
            name="ck_cache_target_streams_versions",
        ),
        sa.CheckConstraint(
            "status IN ('ready','fenced','blocked')",
            name="ck_cache_target_streams_status",
        ),
        sa.CheckConstraint(
            "(status = 'blocked') = (blocked_event_id IS NOT NULL)",
            name="ck_cache_target_streams_blocked",
        ),
        sa.ForeignKeyConstraint(
            ["last_barrier_command_id"],
            ["ops.domain_commands.command_id"],
            name="fk_cache_target_streams_barrier_command",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "external_system",
            name="pk_poi_cache_target_streams",
        ),
        schema="ops",
    )

    op.create_table(
        "poi_cache_target_restore_fences",
        sa.Column(
            "fence_id",
            postgresql.UUID(as_uuid=False),
            nullable=False,
            server_default=sa.text("x_extension.gen_random_uuid()"),
        ),
        sa.Column("external_system", sa.Text(), nullable=False),
        sa.Column("consumer_id", sa.Text(), nullable=False),
        sa.Column("command_id", sa.BigInteger(), nullable=False),
        sa.Column("previous_restore_epoch", sa.BigInteger(), nullable=False),
        sa.Column("restore_epoch", sa.BigInteger(), nullable=False),
        sa.Column("previous_control_version", sa.BigInteger(), nullable=False),
        sa.Column("control_version", sa.BigInteger(), nullable=False),
        sa.Column("invalidated_claim_count", sa.BigInteger(), nullable=False),
        sa.Column("superseded_delivery_count", sa.BigInteger(), nullable=False),
        sa.Column("superseded_reconciliation_count", sa.BigInteger(), nullable=False),
        sa.Column(
            "superseded_reconciliation_request_id",
            postgresql.UUID(as_uuid=False),
        ),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("request_fingerprint", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        _sha256_check(
            "request_fingerprint",
            "ck_cache_target_restore_fences_fingerprint",
        ),
        sa.CheckConstraint(
            "restore_epoch = previous_restore_epoch + 1",
            name="ck_cache_target_restore_fences_epoch",
        ),
        sa.CheckConstraint(
            "control_version = previous_control_version + 1",
            name="ck_cache_target_restore_fences_version",
        ),
        sa.CheckConstraint(
            "superseded_delivery_count >= 0",
            name="ck_cache_target_restore_fences_superseded_count",
        ),
        sa.CheckConstraint(
            "invalidated_claim_count >= 0",
            name="ck_cache_target_restore_fences_invalidated_claim_count",
        ),
        sa.CheckConstraint(
            "(superseded_reconciliation_count = 0 "
            "AND superseded_reconciliation_request_id IS NULL) OR "
            "(superseded_reconciliation_count = 1 "
            "AND superseded_reconciliation_request_id IS NOT NULL)",
            name="ck_cache_target_restore_fences_superseded_reconciliation",
        ),
        sa.CheckConstraint(
            "btrim(reason) <> '' AND char_length(reason) <= 1000",
            name="ck_cache_target_restore_fences_reason",
        ),
        sa.ForeignKeyConstraint(
            ["external_system"],
            ["ops.poi_cache_target_streams.external_system"],
            name="fk_cache_target_restore_fences_stream",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["command_id"],
            ["ops.domain_commands.command_id"],
            name="fk_cache_target_restore_fences_command",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "fence_id",
            name="pk_poi_cache_target_restore_fences",
        ),
        sa.UniqueConstraint(
            "command_id",
            name="uq_cache_target_restore_fences_command",
        ),
        sa.UniqueConstraint(
            "external_system",
            "restore_epoch",
            name="uq_cache_target_restore_fences_epoch",
        ),
        schema="ops",
    )

    op.create_table(
        "poi_cache_target_source_heads",
        sa.Column("external_system", sa.Text(), nullable=False),
        sa.Column("target_key", sa.Text(), nullable=False),
        sa.Column("target_id", postgresql.UUID(as_uuid=False)),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("restore_epoch", sa.BigInteger(), nullable=False),
        sa.Column("source_generation", sa.BigInteger(), nullable=False),
        sa.Column("source_payload_fingerprint", sa.Text(), nullable=False),
        sa.Column("last_source_event_id", postgresql.UUID(as_uuid=False)),
        sa.Column(
            "target_sequence",
            sa.BigInteger(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        _sha256_check(
            "source_payload_fingerprint",
            "ck_cache_target_source_heads_fingerprint",
        ),
        sa.CheckConstraint(
            "btrim(target_key) <> '' AND char_length(target_key) <= 512",
            name="ck_cache_target_source_heads_key",
        ),
        sa.CheckConstraint(
            "state IN ('active','deleted')",
            name="ck_cache_target_source_heads_state",
        ),
        sa.CheckConstraint(
            "restore_epoch > 0 AND source_generation > 0 AND target_sequence >= 0",
            name="ck_cache_target_source_heads_versions",
        ),
        sa.CheckConstraint(
            "state <> 'active' OR target_id IS NOT NULL",
            name="ck_cache_target_source_heads_active_target",
        ),
        sa.ForeignKeyConstraint(
            ["external_system"],
            ["ops.poi_cache_target_streams.external_system"],
            name="fk_cache_target_source_heads_stream",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["target_id", "external_system", "target_key"],
            [
                "ops.poi_cache_targets.target_id",
                "ops.poi_cache_targets.external_system",
                "ops.poi_cache_targets.target_key",
            ],
            name="fk_cache_target_source_heads_target",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "external_system",
            "target_key",
            name="pk_poi_cache_target_source_heads",
        ),
        schema="ops",
    )
    op.create_index(
        "idx_cache_target_source_heads_target",
        "poi_cache_target_source_heads",
        ["target_id"],
        unique=True,
        schema="ops",
        postgresql_where=sa.text("target_id IS NOT NULL"),
    )

    op.create_table(
        "poi_cache_target_source_events",
        sa.Column("event_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("external_system", sa.Text(), nullable=False),
        sa.Column("target_key", sa.Text(), nullable=False),
        sa.Column("idempotency_key", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("operation", sa.Text(), nullable=False),
        sa.Column("restore_epoch", sa.BigInteger(), nullable=False),
        sa.Column("source_generation", sa.BigInteger(), nullable=False),
        sa.Column("request_fingerprint", sa.Text(), nullable=False),
        sa.Column("source_payload_fingerprint", sa.Text(), nullable=False),
        sa.Column("outcome", sa.Text(), nullable=False),
        sa.Column("target_id", postgresql.UUID(as_uuid=False)),
        sa.Column("refresh_request_id", postgresql.UUID(as_uuid=False)),
        sa.Column("job_id", postgresql.UUID(as_uuid=False)),
        sa.Column("domain_command_id", sa.BigInteger()),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        _sha256_check(
            "request_fingerprint",
            "ck_cache_target_source_events_request_fingerprint",
        ),
        _sha256_check(
            "source_payload_fingerprint",
            "ck_cache_target_source_events_payload_fingerprint",
        ),
        sa.CheckConstraint(
            "operation IN ('upsert','delete')",
            name="ck_cache_target_source_events_operation",
        ),
        sa.CheckConstraint(
            "outcome IN ('applied','stale')",
            name="ck_cache_target_source_events_outcome",
        ),
        sa.CheckConstraint(
            "restore_epoch > 0 AND source_generation > 0",
            name="ck_cache_target_source_events_versions",
        ),
        sa.ForeignKeyConstraint(
            ["external_system", "target_key"],
            [
                "ops.poi_cache_target_source_heads.external_system",
                "ops.poi_cache_target_source_heads.target_key",
            ],
            name="fk_cache_target_source_events_head",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["target_id"],
            ["ops.poi_cache_targets.target_id"],
            name="fk_cache_target_source_events_target",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["refresh_request_id"],
            ["ops.feature_update_requests.request_id"],
            name="fk_cache_target_source_events_refresh_request",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["ops.import_jobs.job_id"],
            name="fk_cache_target_source_events_job",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["domain_command_id"],
            ["ops.domain_commands.command_id"],
            name="fk_cache_target_source_events_domain_command",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "event_id",
            name="pk_poi_cache_target_source_events",
        ),
        sa.UniqueConstraint(
            "external_system",
            "idempotency_key",
            name="uq_cache_target_source_events_idempotency",
        ),
        sa.UniqueConstraint(
            "external_system",
            "target_key",
            "restore_epoch",
            "source_generation",
            name="uq_cache_target_source_events_generation",
        ),
        schema="ops",
    )
    op.create_index(
        "idx_cache_target_source_events_head_time",
        "poi_cache_target_source_events",
        ["external_system", "target_key", sa.text("recorded_at DESC"), "event_id"],
        schema="ops",
    )
    op.create_foreign_key(
        "fk_cache_target_source_heads_last_event",
        "poi_cache_target_source_heads",
        "poi_cache_target_source_events",
        ["last_source_event_id"],
        ["event_id"],
        source_schema="ops",
        referent_schema="ops",
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )

    op.create_table(
        "poi_cache_target_refresh_members",
        sa.Column("request_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("target_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("external_system", sa.Text(), nullable=False),
        sa.Column("target_key", sa.Text(), nullable=False),
        sa.Column("restore_epoch", sa.BigInteger(), nullable=False),
        sa.Column("source_generation", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "restore_epoch > 0 AND source_generation > 0",
            name="ck_cache_target_refresh_members_versions",
        ),
        sa.ForeignKeyConstraint(
            ["request_id"],
            ["ops.feature_update_requests.request_id"],
            name="fk_cache_target_refresh_members_request",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["external_system", "target_key"],
            [
                "ops.poi_cache_target_source_heads.external_system",
                "ops.poi_cache_target_source_heads.target_key",
            ],
            name="fk_cache_target_refresh_members_head",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["target_id"],
            ["ops.poi_cache_targets.target_id"],
            name="fk_cache_target_refresh_members_target",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "request_id",
            "target_id",
            name="pk_poi_cache_target_refresh_members",
        ),
        schema="ops",
    )
    op.create_index(
        "idx_cache_target_refresh_members_target",
        "poi_cache_target_refresh_members",
        ["target_id", "request_id"],
        schema="ops",
    )

    op.create_table(
        "poi_cache_target_reconciliation_requests",
        sa.Column(
            "request_id",
            postgresql.UUID(as_uuid=False),
            nullable=False,
            server_default=sa.text("x_extension.gen_random_uuid()"),
        ),
        sa.Column("external_system", sa.Text(), nullable=False),
        sa.Column("command_id", sa.BigInteger(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'preparing'"),
        ),
        sa.Column(
            "phase_version",
            sa.BigInteger(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.Column("snapshot_id", postgresql.UUID(as_uuid=False)),
        sa.Column("expected_merkle_root", sa.Text()),
        sa.Column("actual_merkle_root", sa.Text()),
        sa.Column("error_code", sa.Text()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "btrim(reason) <> '' AND char_length(reason) <= 1000",
            name=op.f("ck_cache_target_reconciliation_requests_reason"),
        ),
        sa.CheckConstraint(
            "status IN ('preparing','running','succeeded','failed','superseded')",
            name=op.f("ck_cache_target_reconciliation_requests_status"),
        ),
        sa.CheckConstraint(
            "phase_version > 0",
            name=op.f("ck_cache_target_reconciliation_requests_phase_version"),
        ),
        sa.CheckConstraint(
            "expected_merkle_root IS NULL OR "
            "expected_merkle_root ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_cache_target_reconciliation_requests_expected_root"),
        ),
        sa.CheckConstraint(
            "actual_merkle_root IS NULL OR actual_merkle_root ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_cache_target_reconciliation_requests_actual_root"),
        ),
        sa.CheckConstraint(
            "(status = 'preparing' AND started_at IS NOT NULL "
            "AND completed_at IS NULL AND snapshot_id IS NULL "
            "AND expected_merkle_root IS NULL AND actual_merkle_root IS NULL "
            "AND error_code IS NULL) OR "
            "(status = 'running' AND started_at IS NOT NULL "
            "AND completed_at IS NULL AND snapshot_id IS NOT NULL "
            "AND expected_merkle_root IS NOT NULL AND actual_merkle_root IS NULL "
            "AND error_code IS NULL) OR "
            "(status = 'succeeded' AND started_at IS NOT NULL "
            "AND completed_at IS NOT NULL AND snapshot_id IS NOT NULL "
            "AND expected_merkle_root IS NOT NULL AND actual_merkle_root IS NOT NULL "
            "AND error_code IS NULL) OR "
            "(status = 'failed' AND started_at IS NOT NULL "
            "AND completed_at IS NOT NULL AND snapshot_id IS NOT NULL "
            "AND expected_merkle_root IS NOT NULL AND actual_merkle_root IS NOT NULL "
            "AND error_code IS NOT NULL) OR "
            "(status = 'superseded' AND started_at IS NOT NULL "
            "AND completed_at IS NOT NULL AND actual_merkle_root IS NULL "
            "AND error_code = 'restore_fenced' AND "
            "((snapshot_id IS NULL AND expected_merkle_root IS NULL) OR "
            "(snapshot_id IS NOT NULL AND expected_merkle_root IS NOT NULL)))",
            name=op.f("ck_cache_target_reconciliation_requests_lifecycle"),
        ),
        sa.ForeignKeyConstraint(
            ["external_system"],
            ["ops.poi_cache_target_streams.external_system"],
            name="fk_cache_target_reconciliation_requests_stream",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["command_id"],
            ["ops.domain_commands.command_id"],
            name="fk_cache_target_reconciliation_requests_command",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "request_id",
            name="pk_poi_cache_target_reconciliation_requests",
        ),
        sa.UniqueConstraint(
            "command_id",
            name="uq_cache_target_reconciliation_requests_command",
        ),
        schema="ops",
    )
    op.create_index(
        "idx_cache_target_reconciliation_requests_stream_status",
        "poi_cache_target_reconciliation_requests",
        ["external_system", "status", sa.text("created_at DESC"), "request_id"],
        schema="ops",
    )
    op.create_index(
        "uq_cache_target_reconciliation_requests_active_stream",
        "poi_cache_target_reconciliation_requests",
        ["external_system"],
        unique=True,
        schema="ops",
        postgresql_where=sa.text("status IN ('preparing','running')"),
    )
    op.create_foreign_key(
        "fk_cache_target_restore_fences_superseded_reconciliation",
        "poi_cache_target_restore_fences",
        "poi_cache_target_reconciliation_requests",
        ["superseded_reconciliation_request_id"],
        ["request_id"],
        source_schema="ops",
        referent_schema="ops",
        ondelete="RESTRICT",
    )

    op.create_table(
        "poi_cache_target_outbox_events",
        sa.Column("event_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column(
            "relay_order",
            sa.BigInteger(),
            sa.Identity(always=True),
            nullable=False,
        ),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("event_scope", sa.Text(), nullable=False),
        sa.Column("external_system", sa.Text(), nullable=False),
        sa.Column("target_key", sa.Text()),
        sa.Column("target_id", postgresql.UUID(as_uuid=False)),
        sa.Column("restore_epoch", sa.BigInteger(), nullable=False),
        sa.Column("source_generation", sa.BigInteger()),
        sa.Column("target_sequence", sa.BigInteger()),
        sa.Column("source_payload_fingerprint", sa.Text(), nullable=False),
        sa.Column("payload_fingerprint", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("source_event_id", postgresql.UUID(as_uuid=False)),
        sa.Column("refresh_request_id", postgresql.UUID(as_uuid=False)),
        sa.Column("job_id", postgresql.UUID(as_uuid=False)),
        sa.Column("domain_command_id", sa.BigInteger()),
        sa.Column(
            "reconciliation_request_id",
            postgresql.UUID(as_uuid=False),
        ),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        _sha256_check(
            "source_payload_fingerprint",
            "ck_cache_target_outbox_source_fingerprint",
        ),
        _sha256_check(
            "payload_fingerprint",
            "ck_cache_target_outbox_payload_fingerprint",
        ),
        sa.CheckConstraint(
            "event_type IN ("
            "'cache_target.state_applied',"
            "'cache_target.links_reconciled',"
            "'refresh_request.status_changed',"
            "'cache_target.reconciled'"
            ")",
            name="ck_cache_target_outbox_event_type",
        ),
        sa.CheckConstraint(
            "restore_epoch > 0 AND ("
            "(event_scope = 'target' AND target_key IS NOT NULL "
            "AND target_id IS NOT NULL AND source_generation > 0 "
            "AND target_sequence > 0 AND event_type <> 'cache_target.reconciled') OR "
            "(event_scope = 'stream' AND target_key IS NULL "
            "AND target_id IS NULL AND source_generation IS NULL "
            "AND target_sequence IS NULL AND event_type = 'cache_target.reconciled' "
            "AND reconciliation_request_id IS NOT NULL))",
            name="ck_cache_target_outbox_versions",
        ),
        sa.CheckConstraint(
            "event_scope IN ('target','stream')",
            name="ck_cache_target_outbox_scope",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(payload) = 'object'",
            name="ck_cache_target_outbox_payload",
        ),
        sa.ForeignKeyConstraint(
            ["external_system", "target_key"],
            [
                "ops.poi_cache_target_source_heads.external_system",
                "ops.poi_cache_target_source_heads.target_key",
            ],
            name="fk_cache_target_outbox_head",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["target_id"],
            ["ops.poi_cache_targets.target_id"],
            name="fk_cache_target_outbox_target",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_event_id"],
            ["ops.poi_cache_target_source_events.event_id"],
            name="fk_cache_target_outbox_source_event",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["refresh_request_id"],
            ["ops.feature_update_requests.request_id"],
            name="fk_cache_target_outbox_refresh_request",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["ops.import_jobs.job_id"],
            name="fk_cache_target_outbox_job",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["domain_command_id"],
            ["ops.domain_commands.command_id"],
            name="fk_cache_target_outbox_domain_command",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["reconciliation_request_id"],
            ["ops.poi_cache_target_reconciliation_requests.request_id"],
            name="fk_cache_target_outbox_reconciliation_request",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "event_id",
            name="pk_poi_cache_target_outbox_events",
        ),
        sa.UniqueConstraint(
            "relay_order",
            name="uq_cache_target_outbox_relay_order",
        ),
        sa.UniqueConstraint(
            "external_system",
            "target_key",
            "restore_epoch",
            "source_generation",
            "target_sequence",
            name="uq_cache_target_outbox_semantic_order",
        ),
        schema="ops",
    )
    op.create_index(
        "idx_cache_target_outbox_stream_order",
        "poi_cache_target_outbox_events",
        ["external_system", "relay_order"],
        schema="ops",
    )

    op.create_table(
        "poi_cache_target_outbox_claims",
        sa.Column("claim_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("external_system", sa.Text(), nullable=False),
        sa.Column("consumer_id", sa.Text(), nullable=False),
        sa.Column("idempotency_key", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("request_fingerprint", sa.Text(), nullable=False),
        sa.Column("lease_token", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("first_relay_order", sa.BigInteger(), nullable=False),
        sa.Column("last_relay_order", sa.BigInteger(), nullable=False),
        sa.Column("acked_through_relay_order", sa.BigInteger()),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        _sha256_check(
            "request_fingerprint",
            "ck_cache_target_outbox_claims_fingerprint",
        ),
        sa.CheckConstraint(
            "status IN ('active','acked','expired','invalidated')",
            name="ck_cache_target_outbox_claims_status",
        ),
        sa.CheckConstraint(
            "first_relay_order > 0 AND last_relay_order >= first_relay_order",
            name="ck_cache_target_outbox_claims_order",
        ),
        sa.CheckConstraint(
            "acked_through_relay_order IS NULL OR "
            "acked_through_relay_order BETWEEN first_relay_order AND last_relay_order",
            name="ck_cache_target_outbox_claims_ack_order",
        ),
        sa.CheckConstraint(
            "(status = 'active' AND completed_at IS NULL) OR "
            "(status <> 'active' AND completed_at IS NOT NULL)",
            name="ck_cache_target_outbox_claims_completion",
        ),
        sa.ForeignKeyConstraint(
            ["external_system"],
            ["ops.poi_cache_target_streams.external_system"],
            name="fk_cache_target_outbox_claims_stream",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "claim_id",
            name="pk_poi_cache_target_outbox_claims",
        ),
        sa.UniqueConstraint(
            "external_system",
            "idempotency_key",
            name="uq_cache_target_outbox_claims_idempotency",
        ),
        schema="ops",
    )
    op.create_index(
        "uq_cache_target_outbox_claims_active_stream",
        "poi_cache_target_outbox_claims",
        ["external_system"],
        unique=True,
        schema="ops",
        postgresql_where=sa.text("status = 'active'"),
    )
    op.create_index(
        "idx_cache_target_outbox_claims_lease",
        "poi_cache_target_outbox_claims",
        ["lease_expires_at", "external_system"],
        schema="ops",
        postgresql_where=sa.text("status = 'active'"),
    )

    op.create_table(
        "poi_cache_target_outbox_deliveries",
        sa.Column("event_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column(
            "delivery_version",
            sa.BigInteger(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.Column(
            "attempt_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "available_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("claim_id", postgresql.UUID(as_uuid=False)),
        sa.Column("lease_token", postgresql.UUID(as_uuid=False)),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("error_class", sa.Text()),
        sa.Column("error_code", sa.Text()),
        sa.Column("error_fingerprint", sa.Text()),
        sa.Column("delivered_at", sa.DateTime(timezone=True)),
        sa.Column("superseded_at", sa.DateTime(timezone=True)),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "status IN ('pending','leased','retry','dead','delivered','superseded')",
            name="ck_cache_target_outbox_deliveries_status",
        ),
        sa.CheckConstraint(
            "delivery_version > 0 AND attempt_count >= 0",
            name="ck_cache_target_outbox_deliveries_versions",
        ),
        sa.CheckConstraint(
            "(status = 'leased') = "
            "(claim_id IS NOT NULL AND lease_token IS NOT NULL AND lease_expires_at IS NOT NULL)",
            name="ck_cache_target_outbox_deliveries_lease",
        ),
        sa.CheckConstraint(
            "(status = 'delivered') = (delivered_at IS NOT NULL)",
            name="ck_cache_target_outbox_deliveries_delivered",
        ),
        sa.CheckConstraint(
            "(status = 'superseded') = (superseded_at IS NOT NULL)",
            name="ck_cache_target_outbox_deliveries_superseded",
        ),
        sa.CheckConstraint(
            "error_class IS NULL OR error_class IN ('transient','permanent')",
            name="ck_cache_target_outbox_deliveries_error_class",
        ),
        sa.CheckConstraint(
            "error_fingerprint IS NULL OR error_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_cache_target_outbox_deliveries_error_fingerprint",
        ),
        sa.ForeignKeyConstraint(
            ["event_id"],
            ["ops.poi_cache_target_outbox_events.event_id"],
            name="fk_cache_target_outbox_deliveries_event",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["claim_id"],
            ["ops.poi_cache_target_outbox_claims.claim_id"],
            name="fk_cache_target_outbox_deliveries_claim",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "event_id",
            name="pk_poi_cache_target_outbox_deliveries",
        ),
        schema="ops",
    )
    op.create_index(
        "idx_cache_target_outbox_deliveries_due",
        "poi_cache_target_outbox_deliveries",
        ["available_at", "event_id"],
        schema="ops",
        postgresql_where=sa.text("status IN ('pending','retry')"),
    )
    op.create_index(
        "idx_cache_target_outbox_deliveries_claim",
        "poi_cache_target_outbox_deliveries",
        ["claim_id", "event_id"],
        schema="ops",
        postgresql_where=sa.text("claim_id IS NOT NULL"),
    )

    op.create_table(
        "poi_cache_target_outbox_claim_events",
        sa.Column("claim_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("event_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("relay_order", sa.BigInteger(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("consumer_applied_at", sa.DateTime(timezone=True)),
        sa.Column("prefix_acked_at", sa.DateTime(timezone=True)),
        sa.Column("ack_payload_fingerprint", sa.Text()),
        sa.CheckConstraint(
            "relay_order > 0 AND position > 0",
            name="ck_cache_target_claim_events_order",
        ),
        sa.CheckConstraint(
            "ack_payload_fingerprint IS NULL OR "
            "ack_payload_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_cache_target_claim_events_fingerprint",
        ),
        sa.CheckConstraint(
            "prefix_acked_at IS NULL OR consumer_applied_at IS NOT NULL",
            name="ck_cache_target_claim_events_ack",
        ),
        sa.ForeignKeyConstraint(
            ["claim_id"],
            ["ops.poi_cache_target_outbox_claims.claim_id"],
            name="fk_cache_target_claim_events_claim",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["event_id"],
            ["ops.poi_cache_target_outbox_events.event_id"],
            name="fk_cache_target_claim_events_event",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "claim_id",
            "event_id",
            name="pk_poi_cache_target_outbox_claim_events",
        ),
        sa.UniqueConstraint(
            "claim_id",
            "relay_order",
            name="uq_cache_target_claim_events_order",
        ),
        sa.UniqueConstraint(
            "claim_id",
            "position",
            name="uq_cache_target_claim_events_position",
        ),
        schema="ops",
    )
    op.create_index(
        "idx_cache_target_claim_events_applied_gap",
        "poi_cache_target_outbox_claim_events",
        ["claim_id", "relay_order"],
        schema="ops",
        postgresql_where=sa.text(
            "consumer_applied_at IS NOT NULL AND prefix_acked_at IS NULL"
        ),
    )

    op.create_table(
        "poi_cache_target_snapshots",
        sa.Column(
            "snapshot_id",
            postgresql.UUID(as_uuid=False),
            nullable=False,
            server_default=sa.text("x_extension.gen_random_uuid()"),
        ),
        sa.Column("external_system", sa.Text(), nullable=False),
        sa.Column("restore_epoch", sa.BigInteger(), nullable=False),
        sa.Column("high_watermark_relay_order", sa.BigInteger(), nullable=False),
        sa.Column("item_count", sa.BigInteger(), nullable=False),
        sa.Column("merkle_root", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        _sha256_check(
            "merkle_root",
            "ck_cache_target_snapshots_merkle_root",
        ),
        sa.CheckConstraint(
            "restore_epoch > 0 AND high_watermark_relay_order >= 0 AND item_count >= 0",
            name="ck_cache_target_snapshots_counts",
        ),
        sa.CheckConstraint(
            "expires_at > created_at",
            name="ck_cache_target_snapshots_expiry",
        ),
        sa.ForeignKeyConstraint(
            ["external_system"],
            ["ops.poi_cache_target_streams.external_system"],
            name="fk_cache_target_snapshots_stream",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "snapshot_id",
            name="pk_poi_cache_target_snapshots",
        ),
        sa.UniqueConstraint(
            "snapshot_id",
            "external_system",
            name="uq_cache_target_snapshots_stream",
        ),
        schema="ops",
    )
    op.create_index(
        "idx_cache_target_snapshots_stream_time",
        "poi_cache_target_snapshots",
        ["external_system", sa.text("created_at DESC"), "snapshot_id"],
        schema="ops",
    )
    op.create_index(
        "idx_cache_target_snapshots_expiry",
        "poi_cache_target_snapshots",
        ["expires_at", "snapshot_id"],
        schema="ops",
    )
    op.create_foreign_key(
        "fk_cache_target_reconciliation_requests_snapshot",
        "poi_cache_target_reconciliation_requests",
        "poi_cache_target_snapshots",
        ["snapshot_id"],
        ["snapshot_id"],
        source_schema="ops",
        referent_schema="ops",
        ondelete="RESTRICT",
    )

    op.create_table(
        "poi_cache_target_snapshot_items",
        sa.Column("snapshot_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("row_number", sa.BigInteger(), nullable=False),
        sa.Column("external_system", sa.Text(), nullable=False),
        sa.Column("target_key", sa.Text(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("source_generation", sa.BigInteger(), nullable=False),
        sa.Column("source_payload_fingerprint", sa.Text(), nullable=False),
        _sha256_check(
            "source_payload_fingerprint",
            "ck_cache_target_snapshot_items_fingerprint",
        ),
        sa.CheckConstraint(
            "row_number > 0 AND source_generation > 0",
            name="ck_cache_target_snapshot_items_versions",
        ),
        sa.CheckConstraint(
            "state IN ('active','deleted')",
            name="ck_cache_target_snapshot_items_state",
        ),
        sa.ForeignKeyConstraint(
            ["snapshot_id", "external_system"],
            [
                "ops.poi_cache_target_snapshots.snapshot_id",
                "ops.poi_cache_target_snapshots.external_system",
            ],
            name="fk_cache_target_snapshot_items_snapshot",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "snapshot_id",
            "row_number",
            name="pk_poi_cache_target_snapshot_items",
        ),
        sa.UniqueConstraint(
            "snapshot_id",
            "external_system",
            "target_key",
            name="uq_cache_target_snapshot_items_key",
        ),
        schema="ops",
    )

    op.create_foreign_key(
        "fk_cache_target_streams_blocked_event",
        "poi_cache_target_streams",
        "poi_cache_target_outbox_events",
        ["blocked_event_id"],
        ["event_id"],
        source_schema="ops",
        referent_schema="ops",
        ondelete="RESTRICT",
    )

    op.execute(
        """
        CREATE FUNCTION ops.reject_cache_target_history_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $function$
        BEGIN
          RAISE EXCEPTION 'cache target history is append-only'
            USING ERRCODE = '55000';
        END;
        $function$
        """
    )
    append_only_tables = (
        "poi_cache_target_restore_fences",
        "poi_cache_target_source_events",
        "poi_cache_target_refresh_members",
        "poi_cache_target_outbox_events",
    )
    fixed_snapshot_tables = (
        "poi_cache_target_snapshots",
        "poi_cache_target_snapshot_items",
    )
    for table_name in append_only_tables:
        op.execute(
            f"CREATE TRIGGER trg_{table_name}_append_only "
            f"BEFORE UPDATE OR DELETE ON ops.{table_name} "
            "FOR EACH ROW EXECUTE FUNCTION ops.reject_cache_target_history_mutation()"
        )
        op.execute(
            f"CREATE TRIGGER trg_{table_name}_no_truncate "
            f"BEFORE TRUNCATE ON ops.{table_name} "
            "FOR EACH STATEMENT EXECUTE FUNCTION ops.reject_cache_target_history_mutation()"
        )
    for table_name in fixed_snapshot_tables:
        op.execute(
            f"CREATE TRIGGER trg_{table_name}_append_only "
            f"BEFORE UPDATE ON ops.{table_name} "
            "FOR EACH ROW EXECUTE FUNCTION ops.reject_cache_target_history_mutation()"
        )
        op.execute(
            f"CREATE TRIGGER trg_{table_name}_no_truncate "
            f"BEFORE TRUNCATE ON ops.{table_name} "
            "FOR EACH STATEMENT EXECUTE FUNCTION ops.reject_cache_target_history_mutation()"
        )


def downgrade() -> None:
    for table_name in (
        "poi_cache_target_snapshot_items",
        "poi_cache_target_snapshots",
        "poi_cache_target_outbox_events",
        "poi_cache_target_refresh_members",
        "poi_cache_target_source_events",
        "poi_cache_target_restore_fences",
    ):
        op.execute(f"DROP TRIGGER trg_{table_name}_no_truncate ON ops.{table_name}")
        op.execute(f"DROP TRIGGER trg_{table_name}_append_only ON ops.{table_name}")
    op.drop_constraint(
        "fk_cache_target_streams_blocked_event",
        "poi_cache_target_streams",
        schema="ops",
        type_="foreignkey",
    )
    op.drop_table("poi_cache_target_snapshot_items", schema="ops")
    op.drop_index(
        "idx_cache_target_snapshots_expiry",
        table_name="poi_cache_target_snapshots",
        schema="ops",
    )
    op.drop_constraint(
        "fk_cache_target_reconciliation_requests_snapshot",
        "poi_cache_target_reconciliation_requests",
        schema="ops",
        type_="foreignkey",
    )
    op.drop_index(
        "idx_cache_target_snapshots_stream_time",
        table_name="poi_cache_target_snapshots",
        schema="ops",
    )
    op.drop_table("poi_cache_target_snapshots", schema="ops")
    op.drop_index(
        "idx_cache_target_claim_events_applied_gap",
        table_name="poi_cache_target_outbox_claim_events",
        schema="ops",
    )
    op.drop_table("poi_cache_target_outbox_claim_events", schema="ops")
    op.drop_index(
        "idx_cache_target_outbox_deliveries_claim",
        table_name="poi_cache_target_outbox_deliveries",
        schema="ops",
    )
    op.drop_index(
        "idx_cache_target_outbox_deliveries_due",
        table_name="poi_cache_target_outbox_deliveries",
        schema="ops",
    )
    op.drop_table("poi_cache_target_outbox_deliveries", schema="ops")
    op.drop_index(
        "idx_cache_target_outbox_claims_lease",
        table_name="poi_cache_target_outbox_claims",
        schema="ops",
    )
    op.drop_index(
        "uq_cache_target_outbox_claims_active_stream",
        table_name="poi_cache_target_outbox_claims",
        schema="ops",
    )
    op.drop_table("poi_cache_target_outbox_claims", schema="ops")
    op.drop_index(
        "idx_cache_target_outbox_stream_order",
        table_name="poi_cache_target_outbox_events",
        schema="ops",
    )
    op.drop_table("poi_cache_target_outbox_events", schema="ops")
    op.drop_constraint(
        "fk_cache_target_restore_fences_superseded_reconciliation",
        "poi_cache_target_restore_fences",
        schema="ops",
        type_="foreignkey",
    )
    op.drop_index(
        "uq_cache_target_reconciliation_requests_active_stream",
        table_name="poi_cache_target_reconciliation_requests",
        schema="ops",
    )
    op.drop_index(
        "idx_cache_target_reconciliation_requests_stream_status",
        table_name="poi_cache_target_reconciliation_requests",
        schema="ops",
    )
    op.drop_table("poi_cache_target_reconciliation_requests", schema="ops")
    op.drop_index(
        "idx_cache_target_refresh_members_target",
        table_name="poi_cache_target_refresh_members",
        schema="ops",
    )
    op.drop_table("poi_cache_target_refresh_members", schema="ops")
    op.drop_constraint(
        "fk_cache_target_source_heads_last_event",
        "poi_cache_target_source_heads",
        schema="ops",
        type_="foreignkey",
    )
    op.drop_index(
        "idx_cache_target_source_events_head_time",
        table_name="poi_cache_target_source_events",
        schema="ops",
    )
    op.drop_table("poi_cache_target_source_events", schema="ops")
    op.drop_index(
        "idx_cache_target_source_heads_target",
        table_name="poi_cache_target_source_heads",
        schema="ops",
    )
    op.drop_table("poi_cache_target_source_heads", schema="ops")
    op.drop_table("poi_cache_target_restore_fences", schema="ops")
    op.drop_table("poi_cache_target_streams", schema="ops")
    op.drop_index(
        "uq_poi_cache_targets_source_identity",
        table_name="poi_cache_targets",
        schema="ops",
    )
    op.execute("DROP FUNCTION ops.reject_cache_target_history_mutation()")
