"""Feature request 멱등 ledger와 Dagster schedule append-only 감사를 추가한다.

Revision ID: 0054_dagster_schedule_audit
Revises: 0053_update_scope_dispatch
Create Date: 2026-07-17
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0054_dagster_schedule_audit"
down_revision: str | Sequence[str] | None = "0053_update_scope_dispatch"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "feature_update_request_idempotency",
        sa.Column("actor", sa.Text(), nullable=False),
        sa.Column("idempotency_key", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column(
            "fingerprint_version",
            sa.Integer(),
            server_default=sa.text("1"),
            nullable=False,
        ),
        sa.Column("request_fingerprint", sa.Text(), nullable=False),
        sa.Column("request_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("reused_active_request", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "fingerprint_version = 1",
            name=op.f("ck_feature_update_request_idempotency_fingerprint_version"),
        ),
        sa.CheckConstraint(
            "request_fingerprint ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_feature_update_request_idempotency_fingerprint"),
        ),
        sa.CheckConstraint(
            "btrim(actor) <> '' AND char_length(actor) <= 200",
            name=op.f("ck_feature_update_request_idempotency_actor"),
        ),
        sa.ForeignKeyConstraint(
            ["request_id"],
            ["ops.feature_update_requests.request_id"],
            name=op.f("fk_feature_update_request_idempotency_request_id_feature_update_requests"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "actor",
            "idempotency_key",
            name=op.f("pk_feature_update_request_idempotency"),
        ),
        schema="ops",
    )
    op.create_index(
        "idx_feature_update_request_idempotency_request",
        "feature_update_request_idempotency",
        ["request_id"],
        unique=False,
        schema="ops",
    )
    op.execute(
        """
        CREATE FUNCTION ops.validate_feature_update_request_idempotency_insert()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
          IF NOT EXISTS (
            SELECT 1
            FROM ops.feature_update_requests AS request
            WHERE request.request_id = NEW.request_id
              AND request.operator IS NOT DISTINCT FROM NEW.actor
          ) THEN
            RAISE EXCEPTION 'idempotency actor must match feature update request operator'
              USING ERRCODE = '23514';
          END IF;
          RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_feature_update_request_idempotency_insert_valid
        BEFORE INSERT ON ops.feature_update_request_idempotency
        FOR EACH ROW
        EXECUTE FUNCTION ops.validate_feature_update_request_idempotency_insert()
        """
    )
    op.execute(
        """
        CREATE FUNCTION ops.reject_feature_update_request_idempotency_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
          RAISE EXCEPTION 'feature update request idempotency ledger is append-only'
            USING ERRCODE = '55000';
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_feature_update_request_idempotency_append_only
        BEFORE UPDATE OR DELETE ON ops.feature_update_request_idempotency
        FOR EACH ROW
        EXECUTE FUNCTION ops.reject_feature_update_request_idempotency_mutation()
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_feature_update_request_idempotency_no_truncate
        BEFORE TRUNCATE ON ops.feature_update_request_idempotency
        FOR EACH STATEMENT
        EXECUTE FUNCTION ops.reject_feature_update_request_idempotency_mutation()
        """
    )
    op.create_table(
        "dagster_schedule_audit_events",
        sa.Column(
            "event_id",
            sa.BigInteger(),
            sa.Identity(always=True),
            nullable=False,
        ),
        sa.Column("command_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("schedule_name", sa.Text(), nullable=False),
        sa.Column("command", sa.Text(), nullable=False),
        sa.Column("phase", sa.Text(), nullable=False),
        sa.Column("actor", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "details",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "btrim(schedule_name) <> ''",
            name=op.f("ck_dagster_schedule_audit_events_schedule_name_not_blank"),
        ),
        sa.CheckConstraint(
            "command IN ('update','default','start','stop','reset','run')",
            name=op.f("ck_dagster_schedule_audit_events_command"),
        ),
        sa.CheckConstraint(
            "phase IN ('requested','succeeded','failed')",
            name=op.f("ck_dagster_schedule_audit_events_phase"),
        ),
        sa.CheckConstraint(
            "btrim(actor) <> '' AND char_length(actor) <= 200",
            name=op.f("ck_dagster_schedule_audit_events_actor"),
        ),
        sa.CheckConstraint(
            "reason IS NULL OR char_length(reason) <= 500",
            name=op.f("ck_dagster_schedule_audit_events_reason"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(details) = 'object'",
            name=op.f("ck_dagster_schedule_audit_events_details_object"),
        ),
        sa.PrimaryKeyConstraint(
            "event_id",
            name=op.f("pk_dagster_schedule_audit_events"),
        ),
        schema="ops",
    )
    op.create_table(
        "dagster_schedule_active_claims",
        sa.Column("command_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("schedule_name", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "btrim(schedule_name) <> ''",
            name=op.f("ck_dagster_schedule_active_claims_schedule_name_not_blank"),
        ),
        sa.PrimaryKeyConstraint(
            "command_id",
            name=op.f("pk_dagster_schedule_active_claims"),
        ),
        sa.UniqueConstraint(
            "schedule_name",
            name=op.f("uq_dagster_schedule_active_claims_schedule_name"),
        ),
        schema="ops",
    )
    op.create_table(
        "dagster_schedule_claim_resolutions",
        sa.Column(
            "resolution_id",
            sa.BigInteger(),
            sa.Identity(always=True),
            nullable=False,
        ),
        sa.Column("command_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("schedule_name", sa.Text(), nullable=False),
        sa.Column("resolution", sa.Text(), nullable=False),
        sa.Column("actor", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "details",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "btrim(schedule_name) <> ''",
            name=op.f("ck_dagster_schedule_claim_resolutions_schedule_name_not_blank"),
        ),
        sa.CheckConstraint(
            "resolution IN ('confirmed_applied','confirmed_not_applied')",
            name=op.f("ck_dagster_schedule_claim_resolutions_resolution"),
        ),
        sa.CheckConstraint(
            "btrim(actor) <> '' AND char_length(actor) <= 200",
            name=op.f("ck_dagster_schedule_claim_resolutions_actor"),
        ),
        sa.CheckConstraint(
            "btrim(reason) <> '' AND char_length(reason) <= 500",
            name=op.f("ck_dagster_schedule_claim_resolutions_reason"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(details) = 'object'",
            name=op.f("ck_dagster_schedule_claim_resolutions_details_object"),
        ),
        sa.PrimaryKeyConstraint(
            "resolution_id",
            name=op.f("pk_dagster_schedule_claim_resolutions"),
        ),
        sa.UniqueConstraint(
            "command_id",
            name=op.f("uq_dagster_schedule_claim_resolutions_command_id"),
        ),
        schema="ops",
    )
    op.create_index(
        "idx_dagster_schedule_audit_schedule_created",
        "dagster_schedule_audit_events",
        ["schedule_name", sa.literal_column("created_at DESC"), sa.literal_column("event_id DESC")],
        unique=False,
        schema="ops",
    )
    op.create_index(
        "idx_dagster_schedule_audit_command",
        "dagster_schedule_audit_events",
        ["command_id", "event_id"],
        unique=False,
        schema="ops",
    )
    op.create_index(
        "uq_dagster_schedule_audit_requested_command",
        "dagster_schedule_audit_events",
        ["command_id"],
        unique=True,
        schema="ops",
        postgresql_where=sa.text("phase = 'requested'"),
    )
    op.create_index(
        "uq_dagster_schedule_audit_terminal_command",
        "dagster_schedule_audit_events",
        ["command_id"],
        unique=True,
        schema="ops",
        postgresql_where=sa.text("phase IN ('succeeded','failed')"),
    )
    op.create_index(
        "idx_dagster_schedule_claim_resolutions_schedule_created",
        "dagster_schedule_claim_resolutions",
        [
            "schedule_name",
            sa.literal_column("created_at DESC"),
            sa.literal_column("resolution_id DESC"),
        ],
        unique=False,
        schema="ops",
    )
    op.execute(
        """
        CREATE FUNCTION ops.validate_dagster_schedule_audit_terminal()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
          PERFORM 1
          FROM ops.dagster_schedule_active_claims AS claim
          WHERE claim.command_id = NEW.command_id
            AND claim.schedule_name = NEW.schedule_name
          FOR UPDATE;
          IF NOT FOUND THEN
            RAISE EXCEPTION 'terminal schedule audit event requires active claim'
              USING ERRCODE = '23514';
          END IF;
          IF NOT EXISTS (
            SELECT 1
            FROM ops.dagster_schedule_audit_events AS requested
            WHERE requested.command_id = NEW.command_id
              AND requested.phase = 'requested'
              AND requested.schedule_name = NEW.schedule_name
              AND requested.command = NEW.command
              AND requested.actor = NEW.actor
              AND requested.reason IS NOT DISTINCT FROM NEW.reason
          ) THEN
            RAISE EXCEPTION 'terminal schedule audit event does not match requested event'
              USING ERRCODE = '23514';
          END IF;
          IF EXISTS (
            SELECT 1
            FROM ops.dagster_schedule_claim_resolutions AS resolution
            WHERE resolution.command_id = NEW.command_id
          ) THEN
            RAISE EXCEPTION 'resolved schedule claim cannot receive terminal audit event'
              USING ERRCODE = '23514';
          END IF;
          RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_dagster_schedule_audit_terminal_matches_request
        BEFORE INSERT ON ops.dagster_schedule_audit_events
        FOR EACH ROW
        WHEN (NEW.phase IN ('succeeded','failed'))
        EXECUTE FUNCTION ops.validate_dagster_schedule_audit_terminal()
        """
    )
    op.execute(
        """
        CREATE FUNCTION ops.reject_dagster_schedule_audit_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
          RAISE EXCEPTION 'dagster schedule audit records are append-only'
            USING ERRCODE = '55000';
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION ops.validate_dagster_schedule_claim_resolution()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
          PERFORM 1
          FROM ops.dagster_schedule_active_claims AS claim
          WHERE claim.command_id = NEW.command_id
            AND claim.schedule_name = NEW.schedule_name
          FOR UPDATE;
          IF NOT FOUND THEN
            RAISE EXCEPTION 'only an active uncertain schedule claim can be resolved'
              USING ERRCODE = '23514';
          END IF;
          IF NOT EXISTS (
            SELECT 1
            FROM ops.dagster_schedule_audit_events AS requested
            WHERE requested.command_id = NEW.command_id
              AND requested.schedule_name = NEW.schedule_name
              AND requested.phase = 'requested'
          ) THEN
            RAISE EXCEPTION 'schedule claim resolution requires requested event'
              USING ERRCODE = '23514';
          END IF;
          IF EXISTS (
            SELECT 1
            FROM ops.dagster_schedule_audit_events AS terminal
            WHERE terminal.command_id = NEW.command_id
              AND terminal.phase IN ('succeeded','failed')
              AND (
                terminal.schedule_name <> NEW.schedule_name
                OR terminal.details ->> 'outcome_certainty' IS DISTINCT FROM 'uncertain'
              )
          ) THEN
            RAISE EXCEPTION 'confirmed schedule terminal event cannot be resolved'
              USING ERRCODE = '23514';
          END IF;
          RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_dagster_schedule_claim_resolution_valid
        BEFORE INSERT ON ops.dagster_schedule_claim_resolutions
        FOR EACH ROW
        EXECUTE FUNCTION ops.validate_dagster_schedule_claim_resolution()
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_dagster_schedule_claim_resolution_append_only
        BEFORE UPDATE OR DELETE ON ops.dagster_schedule_claim_resolutions
        FOR EACH ROW
        EXECUTE FUNCTION ops.reject_dagster_schedule_audit_mutation()
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_dagster_schedule_claim_resolution_no_truncate
        BEFORE TRUNCATE ON ops.dagster_schedule_claim_resolutions
        FOR EACH STATEMENT
        EXECUTE FUNCTION ops.reject_dagster_schedule_audit_mutation()
        """
    )
    op.execute(
        """
        CREATE FUNCTION ops.validate_dagster_schedule_active_claim_insert()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
          IF NOT EXISTS (
            SELECT 1
            FROM ops.dagster_schedule_audit_events AS requested
            WHERE requested.command_id = NEW.command_id
              AND requested.schedule_name = NEW.schedule_name
              AND requested.phase = 'requested'
          ) THEN
            RAISE EXCEPTION 'active schedule claim requires matching requested event'
              USING ERRCODE = '23514';
          END IF;
          RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_dagster_schedule_active_claim_insert_valid
        BEFORE INSERT ON ops.dagster_schedule_active_claims
        FOR EACH ROW
        EXECUTE FUNCTION ops.validate_dagster_schedule_active_claim_insert()
        """
    )
    op.execute(
        """
        CREATE FUNCTION ops.validate_dagster_schedule_active_claim_delete()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
          IF EXISTS (
            SELECT 1
            FROM ops.dagster_schedule_audit_events AS terminal
            WHERE terminal.command_id = OLD.command_id
              AND terminal.schedule_name = OLD.schedule_name
              AND terminal.phase IN ('succeeded','failed')
              AND terminal.details ->> 'outcome_certainty' = 'confirmed'
          ) THEN
            RETURN OLD;
          END IF;
          IF EXISTS (
            SELECT 1
            FROM ops.dagster_schedule_claim_resolutions AS resolution
            WHERE resolution.command_id = OLD.command_id
              AND resolution.schedule_name = OLD.schedule_name
          ) THEN
            RETURN OLD;
          END IF;
          RAISE EXCEPTION 'active schedule claim requires confirmed outcome or resolution'
            USING ERRCODE = '23514';
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_dagster_schedule_active_claim_delete_valid
        BEFORE DELETE ON ops.dagster_schedule_active_claims
        FOR EACH ROW
        EXECUTE FUNCTION ops.validate_dagster_schedule_active_claim_delete()
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_dagster_schedule_active_claim_update_rejected
        BEFORE UPDATE ON ops.dagster_schedule_active_claims
        FOR EACH ROW
        EXECUTE FUNCTION ops.reject_dagster_schedule_audit_mutation()
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_dagster_schedule_active_claim_no_truncate
        BEFORE TRUNCATE ON ops.dagster_schedule_active_claims
        FOR EACH STATEMENT
        EXECUTE FUNCTION ops.reject_dagster_schedule_audit_mutation()
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_dagster_schedule_audit_append_only
        BEFORE UPDATE OR DELETE ON ops.dagster_schedule_audit_events
        FOR EACH ROW
        EXECUTE FUNCTION ops.reject_dagster_schedule_audit_mutation()
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_dagster_schedule_audit_no_truncate
        BEFORE TRUNCATE ON ops.dagster_schedule_audit_events
        FOR EACH STATEMENT
        EXECUTE FUNCTION ops.reject_dagster_schedule_audit_mutation()
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER trg_feature_update_request_idempotency_insert_valid "
        "ON ops.feature_update_request_idempotency"
    )
    op.execute("DROP FUNCTION ops.validate_feature_update_request_idempotency_insert()")
    op.execute(
        "DROP TRIGGER trg_feature_update_request_idempotency_no_truncate "
        "ON ops.feature_update_request_idempotency"
    )
    op.execute(
        "DROP TRIGGER trg_feature_update_request_idempotency_append_only "
        "ON ops.feature_update_request_idempotency"
    )
    op.execute("DROP FUNCTION ops.reject_feature_update_request_idempotency_mutation()")
    op.drop_index(
        "idx_feature_update_request_idempotency_request",
        table_name="feature_update_request_idempotency",
        schema="ops",
    )
    op.drop_table("feature_update_request_idempotency", schema="ops")
    op.execute(
        "DROP TRIGGER trg_dagster_schedule_active_claim_insert_valid "
        "ON ops.dagster_schedule_active_claims"
    )
    op.execute("DROP FUNCTION ops.validate_dagster_schedule_active_claim_insert()")
    op.execute(
        "DROP TRIGGER trg_dagster_schedule_active_claim_no_truncate "
        "ON ops.dagster_schedule_active_claims"
    )
    op.execute(
        "DROP TRIGGER trg_dagster_schedule_active_claim_update_rejected "
        "ON ops.dagster_schedule_active_claims"
    )
    op.execute(
        "DROP TRIGGER trg_dagster_schedule_active_claim_delete_valid "
        "ON ops.dagster_schedule_active_claims"
    )
    op.execute("DROP FUNCTION ops.validate_dagster_schedule_active_claim_delete()")
    op.execute(
        "DROP TRIGGER trg_dagster_schedule_claim_resolution_no_truncate "
        "ON ops.dagster_schedule_claim_resolutions"
    )
    op.execute(
        "DROP TRIGGER trg_dagster_schedule_claim_resolution_append_only "
        "ON ops.dagster_schedule_claim_resolutions"
    )
    op.execute(
        "DROP TRIGGER trg_dagster_schedule_claim_resolution_valid "
        "ON ops.dagster_schedule_claim_resolutions"
    )
    op.execute("DROP FUNCTION ops.validate_dagster_schedule_claim_resolution()")
    op.execute(
        "DROP TRIGGER trg_dagster_schedule_audit_terminal_matches_request "
        "ON ops.dagster_schedule_audit_events"
    )
    op.execute(
        "DROP TRIGGER trg_dagster_schedule_audit_no_truncate ON ops.dagster_schedule_audit_events"
    )
    op.execute(
        "DROP TRIGGER trg_dagster_schedule_audit_append_only ON ops.dagster_schedule_audit_events"
    )
    op.execute("DROP FUNCTION ops.reject_dagster_schedule_audit_mutation()")
    op.execute("DROP FUNCTION ops.validate_dagster_schedule_audit_terminal()")
    op.drop_index(
        "uq_dagster_schedule_audit_terminal_command",
        table_name="dagster_schedule_audit_events",
        schema="ops",
    )
    op.drop_index(
        "uq_dagster_schedule_audit_requested_command",
        table_name="dagster_schedule_audit_events",
        schema="ops",
    )
    op.drop_index(
        "idx_dagster_schedule_audit_command",
        table_name="dagster_schedule_audit_events",
        schema="ops",
    )
    op.drop_index(
        "idx_dagster_schedule_audit_schedule_created",
        table_name="dagster_schedule_audit_events",
        schema="ops",
    )
    op.drop_index(
        "idx_dagster_schedule_claim_resolutions_schedule_created",
        table_name="dagster_schedule_claim_resolutions",
        schema="ops",
    )
    op.drop_table("dagster_schedule_claim_resolutions", schema="ops")
    op.drop_table("dagster_schedule_active_claims", schema="ops")
    op.drop_table("dagster_schedule_audit_events", schema="ops")
