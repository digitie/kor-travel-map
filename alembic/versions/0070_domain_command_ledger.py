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
