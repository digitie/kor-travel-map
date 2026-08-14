"""ops-live ticket claim과 transaction-coupled topic revision clock을 추가한다.

Revision ID: 0055_ops_live_ticket_claims
Revises: 0054_dagster_schedule_audit
Create Date: 2026-07-17
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0055_ops_live_ticket_claims"
down_revision: str | Sequence[str] | None = "0054_dagster_schedule_audit"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ops_live_ticket_claims",
        sa.Column("nonce_hash", sa.LargeBinary(), nullable=False),
        sa.Column("actor", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "claimed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("clock_timestamp()"),
        ),
        sa.CheckConstraint(
            "octet_length(nonce_hash) = 32",
            name=op.f("ck_ops_live_ticket_claims_nonce_hash_length"),
        ),
        sa.CheckConstraint(
            "char_length(actor) BETWEEN 1 AND 80",
            name=op.f("ck_ops_live_ticket_claims_actor_length"),
        ),
        sa.PrimaryKeyConstraint(
            "nonce_hash",
            name=op.f("pk_ops_live_ticket_claims"),
        ),
        schema="ops",
    )
    op.create_index(
        op.f("ix_ops_live_ticket_claims_expires_at"),
        "ops_live_ticket_claims",
        ["expires_at"],
        unique=False,
        schema="ops",
    )
    op.create_table(
        "ops_live_topic_revisions",
        sa.Column("topic", sa.Text(), nullable=False),
        sa.Column(
            "revision",
            sa.BigInteger(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("clock_timestamp()"),
        ),
        sa.CheckConstraint(
            "btrim(topic) <> '' AND char_length(topic) <= 100",
            name=op.f("ck_ops_live_topic_revisions_topic"),
        ),
        sa.CheckConstraint(
            "revision >= 0",
            name=op.f("ck_ops_live_topic_revisions_revision"),
        ),
        sa.PrimaryKeyConstraint(
            "topic",
            name=op.f("pk_ops_live_topic_revisions"),
        ),
        schema="ops",
    )
    op.execute(
        """
        INSERT INTO ops.ops_live_topic_revisions (topic, revision)
        VALUES
          ('provider_sync', 0),
          ('dataset_projection', 0),
          ('dagster_schedules', 0)
        """
    )
    op.execute(
        """
        CREATE FUNCTION ops.bump_ops_live_topic_revision()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
          IF TG_NARGS <> 1 OR btrim(TG_ARGV[0]) = '' THEN
            RAISE EXCEPTION 'ops live revision trigger requires one topic argument';
          END IF;
          INSERT INTO ops.ops_live_topic_revisions AS live_revision (
            topic,
            revision,
            updated_at
          )
          VALUES (TG_ARGV[0], 1, clock_timestamp())
          ON CONFLICT (topic) DO UPDATE
          SET revision = live_revision.revision + 1,
              updated_at = clock_timestamp();
          RETURN NULL;
        END;
        $$
        """
    )
    _create_revision_trigger(
        name="trg_provider_sync_state_ops_live_revision",
        table="provider_sync.provider_sync_state",
        events="INSERT OR UPDATE OR DELETE OR TRUNCATE",
        topic="provider_sync",
    )
    _create_revision_trigger(
        name="trg_provider_refresh_policies_ops_live_revision",
        table="ops.provider_refresh_policies",
        events="INSERT OR UPDATE OR DELETE OR TRUNCATE",
        topic="provider_sync",
    )
    _create_revision_trigger(
        name="trg_data_integrity_violations_ops_live_revision",
        table="ops.data_integrity_violations",
        events="INSERT OR UPDATE OR DELETE OR TRUNCATE",
        topic="dataset_projection",
    )
    _create_revision_trigger(
        name="trg_poi_cache_targets_ops_live_revision",
        table="ops.poi_cache_targets",
        events="INSERT OR UPDATE OR DELETE OR TRUNCATE",
        topic="dataset_projection",
    )
    _create_revision_trigger(
        name="trg_dagster_schedule_overrides_ops_live_revision",
        table="ops.dagster_schedule_overrides",
        events="INSERT OR UPDATE OR DELETE OR TRUNCATE",
        topic="dagster_schedules",
    )
    _create_revision_trigger(
        name="trg_dagster_schedule_audit_ops_live_revision",
        table="ops.dagster_schedule_audit_events",
        events="INSERT",
        topic="dagster_schedules",
    )
    _create_revision_trigger(
        name="trg_dagster_schedule_claim_resolution_ops_live_revision",
        table="ops.dagster_schedule_claim_resolutions",
        events="INSERT",
        topic="dagster_schedules",
    )


def _create_revision_trigger(
    *,
    name: str,
    table: str,
    events: str,
    topic: str,
) -> None:
    op.execute(
        f"""
        CREATE TRIGGER {name}
        AFTER {events} ON {table}
        FOR EACH STATEMENT
        EXECUTE FUNCTION ops.bump_ops_live_topic_revision('{topic}')
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER trg_dagster_schedule_claim_resolution_ops_live_revision "
        "ON ops.dagster_schedule_claim_resolutions"
    )
    op.execute(
        "DROP TRIGGER trg_dagster_schedule_audit_ops_live_revision "
        "ON ops.dagster_schedule_audit_events"
    )
    op.execute(
        "DROP TRIGGER trg_dagster_schedule_overrides_ops_live_revision "
        "ON ops.dagster_schedule_overrides"
    )
    op.execute(
        "DROP TRIGGER trg_poi_cache_targets_ops_live_revision "
        "ON ops.poi_cache_targets"
    )
    op.execute(
        "DROP TRIGGER trg_data_integrity_violations_ops_live_revision "
        "ON ops.data_integrity_violations"
    )
    op.execute(
        "DROP TRIGGER trg_provider_refresh_policies_ops_live_revision "
        "ON ops.provider_refresh_policies"
    )
    op.execute(
        "DROP TRIGGER trg_provider_sync_state_ops_live_revision "
        "ON provider_sync.provider_sync_state"
    )
    op.execute("DROP FUNCTION ops.bump_ops_live_topic_revision()")
    op.drop_table("ops_live_topic_revisions", schema="ops")
    op.drop_index(
        op.f("ix_ops_live_ticket_claims_expires_at"),
        table_name="ops_live_ticket_claims",
        schema="ops",
    )
    op.drop_table("ops_live_ticket_claims", schema="ops")
