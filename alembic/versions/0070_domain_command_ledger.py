"""Actor-scoped domain commands and terminal replay results.

Revision ID: 0070_domain_command_ledger
Revises: 0069_weather_series_catalog
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0070_domain_command_ledger"
down_revision: str | Sequence[str] | None = "0069_weather_series_catalog"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        "ck_offline_uploads_status",
        "offline_uploads",
        schema="ops",
        type_="check",
    )
    op.create_check_constraint(
        "ck_offline_uploads_status",
        "offline_uploads",
        "status IN ('uploading', 'uploaded', 'validating', 'validated', "
        "'validation_failed', 'loading', 'loaded', 'load_failed', 'cancelled')",
        schema="ops",
    )
    op.create_table(
        "domain_commands",
        sa.Column(
            "command_id",
            sa.BigInteger(),
            sa.Identity(always=True),
            nullable=False,
        ),
        sa.Column("actor", sa.Text(), nullable=False),
        sa.Column("operation", sa.Text(), nullable=False),
        sa.Column(
            "idempotency_key",
            postgresql.UUID(as_uuid=False),
            nullable=False,
        ),
        sa.Column(
            "fingerprint_version",
            sa.Integer(),
            server_default=sa.text("1"),
            nullable=False,
        ),
        sa.Column("request_fingerprint", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "btrim(actor) <> '' AND char_length(actor) <= 200",
            name=op.f("ck_domain_commands_actor"),
        ),
        sa.CheckConstraint(
            "operation ~ '^[a-z][a-z0-9_.-]{0,127}$'",
            name=op.f("ck_domain_commands_operation"),
        ),
        sa.CheckConstraint(
            "fingerprint_version = 1",
            name=op.f("ck_domain_commands_fingerprint_version"),
        ),
        sa.CheckConstraint(
            "request_fingerprint ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_domain_commands_request_fingerprint"),
        ),
        sa.PrimaryKeyConstraint(
            "command_id",
            name=op.f("pk_domain_commands"),
        ),
        sa.UniqueConstraint(
            "actor",
            "operation",
            "idempotency_key",
            name=op.f("uq_domain_commands_actor_operation_key"),
        ),
        schema="ops",
    )
    op.create_table(
        "domain_command_results",
        sa.Column(
            "command_id",
            sa.BigInteger(),
            nullable=False,
        ),
        sa.Column("response_status", sa.Integer(), nullable=False),
        sa.Column("response_body", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "response_headers",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "completed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "response_status BETWEEN 200 AND 599",
            name=op.f("ck_domain_command_results_response_status"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(response_body) = 'object'",
            name=op.f("ck_domain_command_results_response_body"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(response_headers) = 'object'",
            name=op.f("ck_domain_command_results_response_headers"),
        ),
        sa.PrimaryKeyConstraint(
            "command_id",
            name=op.f("pk_domain_command_results"),
        ),
        sa.ForeignKeyConstraint(
            ["command_id"],
            ["ops.domain_commands.command_id"],
            name=op.f("fk_domain_command_results_command"),
            ondelete="RESTRICT",
        ),
        schema="ops",
    )
    op.create_table(
        "backup_command_executions",
        sa.Column("command_id", sa.BigInteger(), nullable=False),
        sa.Column("effect_kind", sa.Text(), nullable=False),
        sa.Column("phase", sa.Text(), nullable=False),
        sa.Column("backup_id", sa.Text(), nullable=False),
        sa.Column("app_db", sa.Text(), nullable=True),
        sa.Column("dagster_db", sa.Text(), nullable=True),
        sa.Column("rustfs_volume", sa.Text(), nullable=True),
        sa.Column("marker_key", sa.Text(), nullable=False),
        sa.Column("input_digest", sa.Text(), nullable=False),
        sa.Column("output_digest", sa.Text(), nullable=True),
        sa.Column("marker_sha256", sa.Text(), nullable=True),
        sa.Column(
            "prepared_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("effect_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("effect_completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "effect_kind IN ('create', 'delete', 'restore', 'swap')",
            name=op.f("ck_backup_command_executions_effect_kind"),
        ),
        sa.CheckConstraint(
            "phase IN ('prepared', 'effect_started', 'effect_succeeded')",
            name=op.f("ck_backup_command_executions_phase"),
        ),
        sa.CheckConstraint(
            "input_digest ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_backup_command_executions_input_digest"),
        ),
        sa.CheckConstraint(
            "marker_key ~ '^[a-z0-9][a-z0-9_.-]{0,127}$'",
            name=op.f("ck_backup_command_executions_marker_key"),
        ),
        sa.CheckConstraint(
            "(phase = 'prepared' AND effect_started_at IS NULL "
            "AND effect_completed_at IS NULL AND output_digest IS NULL "
            "AND marker_sha256 IS NULL) OR "
            "(phase = 'effect_started' AND effect_started_at IS NOT NULL "
            "AND effect_completed_at IS NULL AND output_digest IS NULL "
            "AND marker_sha256 IS NULL) OR "
            "(phase = 'effect_succeeded' AND effect_started_at IS NOT NULL "
            "AND effect_completed_at IS NOT NULL "
            "AND output_digest IS NOT NULL "
            "AND output_digest ~ '^[0-9a-f]{64}$' "
            "AND marker_sha256 IS NOT NULL "
            "AND marker_sha256 ~ '^[0-9a-f]{64}$')",
            name=op.f("ck_backup_command_executions_phase_evidence"),
        ),
        sa.PrimaryKeyConstraint(
            "command_id",
            name=op.f("pk_backup_command_executions"),
        ),
        sa.ForeignKeyConstraint(
            ["command_id"],
            ["ops.domain_commands.command_id"],
            name=op.f("fk_backup_command_executions_command"),
            ondelete="RESTRICT",
        ),
        schema="ops",
    )
    op.create_table(
        "offline_upload_command_executions",
        sa.Column("command_id", sa.BigInteger(), nullable=False),
        sa.Column("effect_kind", sa.Text(), nullable=False),
        sa.Column("phase", sa.Text(), nullable=False),
        sa.Column(
            "upload_id",
            postgresql.UUID(as_uuid=False),
            nullable=False,
        ),
        sa.Column("storage_backend", sa.Text(), nullable=True),
        sa.Column("bucket", sa.Text(), nullable=True),
        sa.Column("storage_key", sa.Text(), nullable=True),
        sa.Column("content_type", sa.Text(), nullable=True),
        sa.Column("byte_size", sa.BigInteger(), nullable=True),
        sa.Column("content_sha256", sa.Text(), nullable=True),
        sa.Column("metadata_digest", sa.Text(), nullable=True),
        sa.Column(
            "load_job_id",
            postgresql.UUID(as_uuid=False),
            nullable=True,
        ),
        sa.Column("dagster_run_id", sa.Text(), nullable=True),
        sa.Column("input_digest", sa.Text(), nullable=False),
        sa.Column("output_digest", sa.Text(), nullable=True),
        sa.Column(
            "prepared_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("effect_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("effect_completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "effect_kind IN ('create', 'delete', 'load')",
            name=op.f("ck_offline_upload_command_executions_effect_kind"),
        ),
        sa.CheckConstraint(
            "phase IN ('prepared', 'effect_started', 'effect_succeeded')",
            name=op.f("ck_offline_upload_command_executions_phase"),
        ),
        sa.CheckConstraint(
            "input_digest ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_offline_upload_command_executions_input_digest"),
        ),
        sa.CheckConstraint(
            "(effect_kind <> 'create') OR "
            "(storage_backend IS NOT NULL AND btrim(storage_backend) <> '' "
            "AND bucket IS NOT NULL AND btrim(bucket) <> '' "
            "AND storage_key IS NOT NULL AND btrim(storage_key) <> '' "
            "AND content_type IS NOT NULL AND btrim(content_type) <> '' "
            "AND byte_size IS NOT NULL AND byte_size > 0 "
            "AND content_sha256 IS NOT NULL "
            "AND content_sha256 ~ '^[0-9a-f]{64}$' "
            "AND metadata_digest IS NOT NULL "
            "AND metadata_digest ~ '^[0-9a-f]{64}$')",
            name=op.f("ck_offline_upload_command_executions_create_identity"),
        ),
        sa.CheckConstraint(
            "(phase = 'prepared' AND effect_started_at IS NULL "
            "AND effect_completed_at IS NULL AND output_digest IS NULL "
            "AND dagster_run_id IS NULL) OR "
            "(phase = 'effect_started' AND effect_started_at IS NOT NULL "
            "AND effect_completed_at IS NULL AND output_digest IS NULL "
            "AND dagster_run_id IS NULL) OR "
            "(phase = 'effect_succeeded' AND effect_started_at IS NOT NULL "
            "AND effect_completed_at IS NOT NULL "
            "AND output_digest IS NOT NULL "
            "AND output_digest ~ '^[0-9a-f]{64}$')",
            name=op.f("ck_offline_upload_command_executions_phase_evidence"),
        ),
        sa.CheckConstraint(
            "(effect_kind <> 'load' OR phase <> 'effect_succeeded') OR "
            "(load_job_id IS NOT NULL AND dagster_run_id IS NOT NULL "
            "AND btrim(dagster_run_id) <> '')",
            name=op.f("ck_offline_upload_command_executions_load_proof"),
        ),
        sa.PrimaryKeyConstraint(
            "command_id",
            name=op.f("pk_offline_upload_command_executions"),
        ),
        sa.ForeignKeyConstraint(
            ["command_id"],
            ["ops.domain_commands.command_id"],
            name=op.f("fk_offline_upload_command_executions_command"),
            ondelete="RESTRICT",
        ),
        schema="ops",
    )
    op.execute(
        """
        CREATE FUNCTION ops.enforce_backup_command_execution_transition()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
          IF OLD.phase = 'effect_succeeded'
             OR (OLD.phase, NEW.phase) NOT IN (
               ('prepared', 'effect_started'),
               ('effect_started', 'effect_succeeded')
             ) THEN
            RAISE EXCEPTION 'invalid backup command execution transition'
              USING ERRCODE = '55000';
          END IF;
          IF (OLD.command_id, OLD.effect_kind, OLD.backup_id, OLD.app_db,
              OLD.dagster_db, OLD.rustfs_volume, OLD.marker_key,
              OLD.input_digest, OLD.prepared_at)
             IS DISTINCT FROM
             (NEW.command_id, NEW.effect_kind, NEW.backup_id, NEW.app_db,
              NEW.dagster_db, NEW.rustfs_volume, NEW.marker_key,
              NEW.input_digest, NEW.prepared_at) THEN
            RAISE EXCEPTION 'backup command execution identity is immutable'
              USING ERRCODE = '55000';
          END IF;
          RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_backup_command_execution_transition
        BEFORE UPDATE ON ops.backup_command_executions
        FOR EACH ROW
        EXECUTE FUNCTION ops.enforce_backup_command_execution_transition()
        """
    )
    op.execute(
        """
        CREATE FUNCTION ops.enforce_offline_upload_command_execution_transition()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
          IF OLD.phase = 'effect_succeeded'
             OR (OLD.phase, NEW.phase) NOT IN (
               ('prepared', 'effect_started'),
               ('effect_started', 'effect_succeeded')
             ) THEN
            RAISE EXCEPTION 'invalid offline upload command execution transition'
              USING ERRCODE = '55000';
          END IF;
          IF (OLD.command_id, OLD.effect_kind, OLD.upload_id,
              OLD.storage_backend, OLD.bucket, OLD.storage_key,
              OLD.content_type, OLD.byte_size, OLD.content_sha256,
              OLD.metadata_digest, OLD.load_job_id, OLD.input_digest,
              OLD.prepared_at)
             IS DISTINCT FROM
             (NEW.command_id, NEW.effect_kind, NEW.upload_id,
              NEW.storage_backend, NEW.bucket, NEW.storage_key,
              NEW.content_type, NEW.byte_size, NEW.content_sha256,
              NEW.metadata_digest, NEW.load_job_id, NEW.input_digest,
              NEW.prepared_at) THEN
            RAISE EXCEPTION 'offline upload command execution identity is immutable'
              USING ERRCODE = '55000';
          END IF;
          RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_offline_upload_command_execution_transition
        BEFORE UPDATE ON ops.offline_upload_command_executions
        FOR EACH ROW
        EXECUTE FUNCTION ops.enforce_offline_upload_command_execution_transition()
        """
    )
    op.execute(
        """
        CREATE FUNCTION ops.reject_domain_command_history_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
          RAISE EXCEPTION 'domain command history is append-only'
            USING ERRCODE = '55000';
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_backup_command_executions_no_delete
        BEFORE DELETE OR TRUNCATE ON ops.backup_command_executions
        FOR EACH STATEMENT
        EXECUTE FUNCTION ops.reject_domain_command_history_mutation()
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_offline_upload_command_executions_no_delete
        BEFORE DELETE OR TRUNCATE ON ops.offline_upload_command_executions
        FOR EACH STATEMENT
        EXECUTE FUNCTION ops.reject_domain_command_history_mutation()
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_domain_commands_append_only
        BEFORE UPDATE OR DELETE ON ops.domain_commands
        FOR EACH ROW
        EXECUTE FUNCTION ops.reject_domain_command_history_mutation()
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_domain_commands_no_truncate
        BEFORE TRUNCATE ON ops.domain_commands
        FOR EACH STATEMENT
        EXECUTE FUNCTION ops.reject_domain_command_history_mutation()
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_domain_command_results_append_only
        BEFORE UPDATE OR DELETE ON ops.domain_command_results
        FOR EACH ROW
        EXECUTE FUNCTION ops.reject_domain_command_history_mutation()
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_domain_command_results_no_truncate
        BEFORE TRUNCATE ON ops.domain_command_results
        FOR EACH STATEMENT
        EXECUTE FUNCTION ops.reject_domain_command_history_mutation()
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER trg_offline_upload_command_executions_no_delete "
        "ON ops.offline_upload_command_executions"
    )
    op.execute(
        "DROP TRIGGER trg_backup_command_executions_no_delete "
        "ON ops.backup_command_executions"
    )
    op.execute(
        "DROP TRIGGER trg_offline_upload_command_execution_transition "
        "ON ops.offline_upload_command_executions"
    )
    op.execute(
        "DROP FUNCTION ops.enforce_offline_upload_command_execution_transition()"
    )
    op.execute(
        "DROP TRIGGER trg_backup_command_execution_transition "
        "ON ops.backup_command_executions"
    )
    op.execute("DROP FUNCTION ops.enforce_backup_command_execution_transition()")
    op.drop_table("offline_upload_command_executions", schema="ops")
    op.drop_table("backup_command_executions", schema="ops")
    op.execute(
        "DROP TRIGGER trg_domain_command_results_no_truncate "
        "ON ops.domain_command_results"
    )
    op.execute(
        "DROP TRIGGER trg_domain_command_results_append_only "
        "ON ops.domain_command_results"
    )
    op.drop_table("domain_command_results", schema="ops")
    op.execute(
        "DROP TRIGGER trg_domain_commands_no_truncate "
        "ON ops.domain_commands"
    )
    op.execute(
        "DROP TRIGGER trg_domain_commands_append_only "
        "ON ops.domain_commands"
    )
    op.execute("DROP FUNCTION ops.reject_domain_command_history_mutation()")
    op.drop_table("domain_commands", schema="ops")
    op.drop_constraint(
        "ck_offline_uploads_status",
        "offline_uploads",
        schema="ops",
        type_="check",
    )
    op.create_check_constraint(
        "ck_offline_uploads_status",
        "offline_uploads",
        "status IN ('uploaded', 'validating', 'validated', "
        "'validation_failed', 'loading', 'loaded', 'load_failed', 'cancelled')",
        schema="ops",
    )
