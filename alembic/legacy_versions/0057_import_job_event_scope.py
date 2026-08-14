"""Import job event에 canonical execution scope를 고정한다.

Revision ID: 0057_import_job_event_scope
Revises: 0056_refresh_policy_revision
Create Date: 2026-07-18
"""

from __future__ import annotations

from collections.abc import Sequence
from time import sleep

import sqlalchemy as sa

from alembic import op

revision: str = "0057_import_job_event_scope"
down_revision: str | Sequence[str] | None = "0056_refresh_policy_revision"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INDEX_NAME = "idx_import_job_events_provider_dataset_scope_time"
_DATASET_ONLY_INDEX_NAME = "idx_import_job_events_dataset_time"
_PAIR_CONSTRAINT = "ck_import_job_events_provider_dataset_pair"
_SCOPE_CONSTRAINT = "ck_import_job_events_sync_scope"
_LOCK_RETRIES = 600
_LOCK_RETRY_SECONDS = 0.05
_EXTERNAL_SYSTEM_SCOPE_PREFIX = "external_system:"
_MAX_SYNC_SCOPE_LENGTH = 128
_CANONICAL_WHITESPACE_SQL = (
    "(' ' || chr(9) || chr(10) || chr(11) || chr(12) || chr(13) "
    "|| chr(28) || chr(29) || chr(30) || chr(31) || chr(133) "
    "|| chr(160) || chr(5760) || chr(8192) || chr(8193) || chr(8194) "
    "|| chr(8195) || chr(8196) || chr(8197) || chr(8198) || chr(8199) "
    "|| chr(8200) || chr(8201) || chr(8202) || chr(8232) || chr(8233) "
    "|| chr(8239) || chr(8287) || chr(12288))"
)


def _canonical_sync_scope_check(column: str) -> str:
    prefix_length = len(_EXTERNAL_SYSTEM_SCOPE_PREFIX)
    return (
        f"({column} IN ('dataset_wide','target_grids') OR "
        f"(left({column}, {prefix_length}) = '{_EXTERNAL_SYSTEM_SCOPE_PREFIX}' "
        f"AND char_length({column}) <= {_MAX_SYNC_SCOPE_LENGTH} "
        f"AND char_length({column}) > {prefix_length} "
        f"AND substring({column} FROM {prefix_length + 1}) "
        f"= btrim(substring({column} FROM {prefix_length + 1}), "
        f"{_CANONICAL_WHITESPACE_SQL})))"
    )


def _lock_event_identity_writers() -> None:
    """Backfill과 trigger 설치 사이에 구 event writer가 끼어들지 못하게 한다."""
    connection = op.get_bind()
    for attempt in range(_LOCK_RETRIES):
        savepoint = connection.begin_nested()
        try:
            connection.execute(
                sa.text(
                    "LOCK TABLE ops.feature_update_requests, ops.import_jobs, "
                    "ops.import_job_events, ops.import_job_event_clock "
                    "IN ACCESS EXCLUSIVE MODE NOWAIT"
                )
            )
        except sa.exc.DBAPIError as exc:
            savepoint.rollback()
            sqlstate = getattr(exc.orig, "sqlstate", None) or getattr(
                exc.orig,
                "pgcode",
                None,
            )
            if sqlstate != "55P03":
                raise
            if attempt + 1 == _LOCK_RETRIES:
                raise RuntimeError(
                    "0057 event identity writer lock could not be acquired "
                    "within 30 seconds"
                ) from exc
            sleep(_LOCK_RETRY_SECONDS)
        else:
            savepoint.commit()
            return
    raise AssertionError("unreachable event identity lock retry state")


def _backfill_missing_event_pair_from_owner() -> None:
    """0052 writer의 NULL event pair를 immutable owning job identity로 복구한다."""
    op.execute(
        """
        UPDATE ops.import_job_events AS event
           SET provider = job.provider,
               dataset_key = job.dataset_key
          FROM ops.import_jobs AS job
         WHERE event.job_id = job.job_id
           AND event.quarantined_at IS NULL
           AND job.quarantined_at IS NULL
           AND event.provider IS NULL
           AND event.dataset_key IS NULL
           AND job.provider IS NOT NULL
           AND job.dataset_key IS NOT NULL
        """
    )


def _fail_on_event_pair_drift() -> None:
    """owner pair로 결정할 수 없는 partial/conflicting drift를 진단한다."""
    rows = (
        op.get_bind()
        .execute(
            sa.text(
                """
                SELECT event.event_id::text, event.job_id::text,
                       event.provider AS event_provider,
                       event.dataset_key AS event_dataset_key,
                       job.provider AS job_provider,
                       job.dataset_key AS job_dataset_key
                FROM ops.import_job_events AS event
                JOIN ops.import_jobs AS job ON job.job_id = event.job_id
                WHERE event.quarantined_at IS NULL
                  AND job.quarantined_at IS NULL
                  AND ROW(event.provider, event.dataset_key)
                      IS DISTINCT FROM ROW(job.provider, job.dataset_key)
                ORDER BY event.event_id
                LIMIT 20
                """
            )
        )
        .mappings()
        .all()
    )
    if rows:
        raise RuntimeError(
            "0057 found visible import job events whose typed pair differs from "
            f"the owning job: {[dict(row) for row in rows]}"
        )


def _backfill_canonical_feature_update_scope() -> None:
    op.execute(
        """
        UPDATE ops.import_job_events AS event
           SET sync_scope = job.sync_scope
          FROM ops.import_jobs AS job
          JOIN ops.feature_update_requests AS request
            ON request.job_id = job.job_id
         WHERE event.job_id = job.job_id
           AND event.quarantined_at IS NULL
           AND job.quarantined_at IS NULL
           AND job.kind = 'feature_update_request'
           AND request.scope_type = 'provider_dataset'
           AND job.provider IS NOT NULL
           AND job.dataset_key IS NOT NULL
           AND job.sync_scope IS NOT NULL
        """
    )


def _create_event_identity_trigger() -> None:
    canonical_scope = _canonical_sync_scope_check("linked_sync_scope")
    op.execute(
        f"""
        CREATE FUNCTION ops.enforce_import_job_event_identity()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
          linked_kind text;
          linked_provider text;
          linked_dataset_key text;
          linked_sync_scope text;
          linked_quarantined_at timestamptz;
        BEGIN
          IF TG_OP = 'UPDATE' THEN
            IF ROW(NEW.job_id, NEW.provider, NEW.dataset_key, NEW.sync_scope)
               IS DISTINCT FROM
               ROW(OLD.job_id, OLD.provider, OLD.dataset_key, OLD.sync_scope) THEN
              RAISE EXCEPTION 'import job event identity is immutable: %', OLD.event_id
                USING ERRCODE = 'check_violation';
            END IF;
            RETURN NEW;
          END IF;

          SELECT kind, provider, dataset_key, sync_scope, quarantined_at
            INTO linked_kind, linked_provider, linked_dataset_key,
                 linked_sync_scope, linked_quarantined_at
            FROM ops.import_jobs
           WHERE job_id = NEW.job_id
           FOR KEY SHARE;
          IF NOT FOUND THEN
            RAISE EXCEPTION 'import job event owner does not exist: %', NEW.job_id
              USING ERRCODE = 'foreign_key_violation';
          END IF;
          IF linked_quarantined_at IS NOT NULL THEN
            RAISE EXCEPTION 'cannot append an event to quarantined import job: %',
              NEW.job_id USING ERRCODE = 'check_violation';
          END IF;
          IF NEW.provider IS NOT NULL
             AND NEW.provider IS DISTINCT FROM linked_provider THEN
            RAISE EXCEPTION 'import job event provider differs from owning job: %',
              NEW.event_id USING ERRCODE = 'check_violation';
          END IF;
          IF NEW.dataset_key IS NOT NULL
             AND NEW.dataset_key IS DISTINCT FROM linked_dataset_key THEN
            RAISE EXCEPTION 'import job event dataset differs from owning job: %',
              NEW.event_id USING ERRCODE = 'check_violation';
          END IF;

          NEW.provider := linked_provider;
          NEW.dataset_key := linked_dataset_key;
          IF linked_kind = 'feature_update_request'
             AND linked_provider IS NOT NULL
             AND linked_dataset_key IS NOT NULL
             AND linked_sync_scope IS NOT NULL
             AND {canonical_scope} THEN
            IF NEW.sync_scope IS NOT NULL
               AND NEW.sync_scope IS DISTINCT FROM linked_sync_scope THEN
              RAISE EXCEPTION 'import job event scope differs from owning job: %',
                NEW.event_id USING ERRCODE = 'check_violation';
            END IF;
            NEW.sync_scope := linked_sync_scope;
          ELSE
            IF NEW.sync_scope IS NOT NULL THEN
              RAISE EXCEPTION
                'only canonical provider update events may own sync_scope: %',
                NEW.event_id USING ERRCODE = 'check_violation';
            END IF;
            NEW.sync_scope := NULL;
          END IF;
          RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_import_job_events_identity
        BEFORE INSERT OR UPDATE OF job_id, provider, dataset_key, sync_scope
        ON ops.import_job_events
        FOR EACH ROW EXECUTE FUNCTION ops.enforce_import_job_event_identity()
        """
    )


def upgrade() -> None:
    _lock_event_identity_writers()
    _backfill_missing_event_pair_from_owner()
    _fail_on_event_pair_drift()
    op.add_column(
        "import_job_events",
        sa.Column("sync_scope", sa.Text(), nullable=True),
        schema="ops",
    )
    _backfill_canonical_feature_update_scope()
    op.create_check_constraint(
        op.f(_PAIR_CONSTRAINT),
        "import_job_events",
        "quarantined_at IS NOT NULL OR "
        "((provider IS NULL AND dataset_key IS NULL) OR "
        "(provider IS NOT NULL AND provider = btrim(provider) AND provider <> '' "
        "AND dataset_key IS NOT NULL AND dataset_key = btrim(dataset_key) "
        "AND dataset_key <> ''))",
        schema="ops",
    )
    op.create_check_constraint(
        op.f(_SCOPE_CONSTRAINT),
        "import_job_events",
        "sync_scope IS NULL OR (provider IS NOT NULL AND dataset_key IS NOT NULL AND "
        f"{_canonical_sync_scope_check('sync_scope')})",
        schema="ops",
    )
    _create_event_identity_trigger()
    # dataset_key는 provider namespace 안의 식별자다. REST/repository 모두
    # provider 없는 dataset-only event 조회를 거부하므로 0052의 단독 인덱스는
    # 쓰기 증폭만 남는다.
    op.drop_index(
        _DATASET_ONLY_INDEX_NAME,
        table_name="import_job_events",
        schema="ops",
    )
    op.create_index(
        _INDEX_NAME,
        "import_job_events",
        [
            "provider",
            "dataset_key",
            "sync_scope",
            sa.text("occurred_at DESC"),
            sa.text("event_id DESC"),
        ],
        schema="ops",
        postgresql_where=sa.text(
            "provider IS NOT NULL AND dataset_key IS NOT NULL "
            "AND sync_scope IS NOT NULL AND quarantined_at IS NULL"
        ),
    )


def downgrade() -> None:
    _lock_event_identity_writers()
    op.drop_index(_INDEX_NAME, table_name="import_job_events", schema="ops")
    op.create_index(
        _DATASET_ONLY_INDEX_NAME,
        "import_job_events",
        ["dataset_key", sa.text("occurred_at DESC"), sa.text("event_id DESC")],
        schema="ops",
        postgresql_where=sa.text(
            "dataset_key IS NOT NULL AND quarantined_at IS NULL"
        ),
    )
    op.execute(
        "DROP TRIGGER trg_import_job_events_identity ON ops.import_job_events"
    )
    op.execute("DROP FUNCTION ops.enforce_import_job_event_identity()")
    op.drop_constraint(
        op.f(_SCOPE_CONSTRAINT),
        "import_job_events",
        schema="ops",
        type_="check",
    )
    op.drop_constraint(
        op.f(_PAIR_CONSTRAINT),
        "import_job_events",
        schema="ops",
        type_="check",
    )
    op.drop_column("import_job_events", "sync_scope", schema="ops")
