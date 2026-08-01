"""cache target source apply 시점의 target version을 영수증에 고정한다.

Revision ID: 0076_cache_target_receipt
Revises: 0075_cache_target_outbox
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0076_cache_target_receipt"
down_revision: str | Sequence[str] | None = "0075_cache_target_outbox"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_APPEND_ONLY_TRIGGER = "trg_poi_cache_target_source_events_append_only"


def _drop_append_only_trigger() -> None:
    op.execute(
        f"DROP TRIGGER {_APPEND_ONLY_TRIGGER} "
        "ON ops.poi_cache_target_source_events"
    )


def _create_append_only_trigger() -> None:
    op.execute(
        f"CREATE TRIGGER {_APPEND_ONLY_TRIGGER} "
        "BEFORE UPDATE OR DELETE ON ops.poi_cache_target_source_events "
        "FOR EACH ROW EXECUTE FUNCTION ops.reject_cache_target_history_mutation()"
    )


def upgrade() -> None:
    _drop_append_only_trigger()
    op.add_column(
        "poi_cache_target_source_events",
        sa.Column("target_lock_version", sa.BigInteger()),
        schema="ops",
    )

    # Active event는 immutable outbox payload의 당시 strong ETag가 정본이다. 현재
    # target row는 이후 source apply/refresh로 version이 전진했을 수 있으므로 쓰지 않는다.
    op.execute(
        r"""
        WITH material AS (
          SELECT source.event_id,
                 source.target_id,
                 outbox.target_id AS outbox_target_id,
                 outbox.payload,
                 outbox.payload -> 'target' ->> 'entity_tag' AS entity_tag
          FROM ops.poi_cache_target_source_events AS source
          JOIN ops.poi_cache_target_outbox_events AS outbox
            ON outbox.source_event_id = source.event_id
           AND outbox.event_type = 'cache_target.state_applied'
          WHERE source.outcome = 'applied'
            AND source.operation = 'upsert'
        ),
        parsed AS (
          SELECT event_id,
                 substring(
                   entity_tag FROM
                   '^"' || target_id::text || ':([1-9][0-9]*)"$'
                 ) AS version_text
          FROM material
          WHERE outbox_target_id = target_id
            AND payload ->> 'state' = 'active'
            AND payload -> 'target' ->> 'target_id' = target_id::text
        )
        UPDATE ops.poi_cache_target_source_events AS source
        SET target_lock_version = CASE
          WHEN char_length(parsed.version_text) < 19
            THEN parsed.version_text::bigint
          WHEN char_length(parsed.version_text) = 19
               AND parsed.version_text <= '9223372036854775807'
            THEN parsed.version_text::bigint
          ELSE NULL
        END
        FROM parsed
        WHERE source.event_id = parsed.event_id
        """
    )

    # 0075의 deleted payload에는 ETag material이 없었다. 정상 DELETE transaction은
    # target.deleted_at/updated_at/source.recorded_at이 같은 transaction timestamp다.
    # 이 증거가 보존된 tombstone만 현재 version으로 backfill하고 나머지는 아래에서
    # fail-close한다.
    op.execute(
        """
        UPDATE ops.poi_cache_target_source_events AS source
        SET target_lock_version = target.lock_version
        FROM ops.poi_cache_targets AS target,
             ops.poi_cache_target_outbox_events AS outbox
        WHERE source.outcome = 'applied'
          AND source.operation = 'delete'
          AND target.target_id = source.target_id
          AND target.external_system = source.external_system
          AND target.target_key = source.target_key
          AND target.deleted_at IS NOT NULL
          AND target.deleted_at = source.recorded_at
          AND target.updated_at = source.recorded_at
          AND outbox.source_event_id = source.event_id
          AND outbox.event_type = 'cache_target.state_applied'
          AND outbox.target_id = source.target_id
          AND outbox.payload ->> 'state' = 'deleted'
          AND outbox.payload -> 'target' = 'null'::jsonb
        """
    )

    op.execute(
        """
        DO $block$
        DECLARE
          invalid_count bigint;
        BEGIN
          SELECT count(*)
          INTO invalid_count
          FROM ops.poi_cache_target_source_events AS source
          LEFT JOIN LATERAL (
            SELECT count(*) AS receipt_count
            FROM ops.poi_cache_target_outbox_events AS outbox
            WHERE outbox.source_event_id = source.event_id
              AND outbox.event_type = 'cache_target.state_applied'
          ) AS receipt ON true
          WHERE source.outcome = 'applied'
            AND (
              source.target_id IS NULL
              OR source.target_lock_version IS NULL
              OR receipt.receipt_count <> 1
            );

          IF invalid_count <> 0 THEN
            RAISE EXCEPTION
              'cache target source receipt backfill drift: % invalid applied rows',
              invalid_count
              USING ERRCODE = '23514';
          END IF;
        END;
        $block$
        """
    )
    op.create_check_constraint(
        op.f("ck_cache_target_source_events_target_lock_version"),
        "poi_cache_target_source_events",
        "target_lock_version IS NULL OR target_lock_version > 0",
        schema="ops",
    )
    op.create_check_constraint(
        op.f("ck_cache_target_source_events_applied_target_receipt"),
        "poi_cache_target_source_events",
        "outcome <> 'applied' OR "
        "(target_id IS NOT NULL AND target_lock_version IS NOT NULL)",
        schema="ops",
    )
    _create_append_only_trigger()


def downgrade() -> None:
    _drop_append_only_trigger()
    op.drop_constraint(
        op.f("ck_cache_target_source_events_applied_target_receipt"),
        "poi_cache_target_source_events",
        schema="ops",
        type_="check",
    )
    op.drop_constraint(
        op.f("ck_cache_target_source_events_target_lock_version"),
        "poi_cache_target_source_events",
        schema="ops",
        type_="check",
    )
    op.drop_column(
        "poi_cache_target_source_events",
        "target_lock_version",
        schema="ops",
    )
    _create_append_only_trigger()
