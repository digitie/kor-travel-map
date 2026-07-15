"""Provider feature operation identity와 Dagster 상태 영속화를 추가한다.

Revision ID: 0051_canonical_provider_ops
Revises: 0050_pipeline_cancellations
Create Date: 2026-07-15
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0051_canonical_provider_ops"
down_revision: str | Sequence[str] | None = "0050_pipeline_cancellations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_LOG = logging.getLogger(__name__)


def _backfill_import_identity() -> None:
    connection = op.get_bind()
    # request direct pair는 event보다 권위가 높다. payload는 identity source가 아니다.
    connection.execute(
        sa.text(
            """
            WITH exact_request_pairs AS (
                SELECT
                    request.job_id,
                    min(request.scope->>'provider') AS provider,
                    min(request.scope->>'dataset_key') AS dataset_key
                FROM ops.feature_update_requests AS request
                WHERE request.job_id IS NOT NULL
                GROUP BY request.job_id
                HAVING count(*) = 1
                AND count(*) FILTER (WHERE
                    request.scope_type = 'provider_dataset'
                    AND jsonb_typeof(request.scope->'provider') = 'string'
                    AND jsonb_typeof(request.scope->'dataset_key') = 'string'
                    AND NULLIF(btrim(request.scope->>'provider'), '') IS NOT NULL
                    AND NULLIF(btrim(request.scope->>'dataset_key'), '') IS NOT NULL
                    AND request.scope->>'provider' =
                        btrim(request.scope->>'provider')
                    AND request.scope->>'dataset_key' =
                        btrim(request.scope->>'dataset_key')
                ) = 1
            )
            UPDATE ops.import_jobs AS job
               SET provider = pair.provider,
                   dataset_key = pair.dataset_key,
                   trigger_kind = 'update_request'
              FROM exact_request_pairs AS pair
             WHERE pair.job_id = job.job_id
            """
        )
    )
    connection.execute(
        sa.text(
            """
            WITH exact_event_pairs AS (
                SELECT
                    event.job_id,
                    min(event.provider) AS provider,
                    min(event.dataset_key) AS dataset_key
                FROM ops.import_job_events AS event
                WHERE event.provider IS NOT NULL OR event.dataset_key IS NOT NULL
                GROUP BY event.job_id
                HAVING count(*) = count(*) FILTER (WHERE
                    NULLIF(btrim(event.provider), '') IS NOT NULL
                    AND NULLIF(btrim(event.dataset_key), '') IS NOT NULL
                    AND event.provider = btrim(event.provider)
                    AND event.dataset_key = btrim(event.dataset_key)
                )
                AND count(DISTINCT ROW(event.provider, event.dataset_key)) = 1
            )
            UPDATE ops.import_jobs AS job
               SET provider = pair.provider,
                   dataset_key = pair.dataset_key
              FROM exact_event_pairs AS pair
             WHERE pair.job_id = job.job_id
               AND job.provider IS NULL
               AND job.dataset_key IS NULL
               AND NOT EXISTS (
                 SELECT 1
                 FROM ops.feature_update_requests AS request
                 WHERE request.job_id = job.job_id
               )
            """
        )
    )


def upgrade() -> None:
    for column in (
        sa.Column("provider", sa.Text(), nullable=True),
        sa.Column("dataset_key", sa.Text(), nullable=True),
        sa.Column("trigger_kind", sa.Text(), nullable=True),
        sa.Column("operation_registry_version", sa.Text(), nullable=True),
        sa.Column("dagster_run_status", sa.Text(), nullable=True),
    ):
        op.add_column("import_jobs", column, schema="ops")

    _backfill_import_identity()

    op.create_check_constraint(
        "ck_import_jobs_provider_dataset_pair",
        "import_jobs",
        "(provider IS NULL AND dataset_key IS NULL) OR "
        "(provider IS NOT NULL AND provider = btrim(provider) AND provider <> '' "
        "AND dataset_key IS NOT NULL AND dataset_key = btrim(dataset_key) "
        "AND dataset_key <> '')",
        schema="ops",
    )
    op.create_check_constraint(
        "ck_import_jobs_trigger_kind",
        "import_jobs",
        "trigger_kind IS NULL OR trigger_kind IN "
        "('schedule','manual','sensor','update_request','backfill','system')",
        schema="ops",
    )
    op.create_check_constraint(
        "ck_import_jobs_registry_version_owner",
        "import_jobs",
        "operation_registry_version IS NULL "
        "OR kind = 'provider_feature_load_run'",
        schema="ops",
    )
    op.create_check_constraint(
        "ck_import_jobs_dagster_run_status",
        "import_jobs",
        "dagster_run_status IS NULL OR "
        "(kind = 'provider_feature_load_run' AND dagster_run_status IN "
        "('QUEUED','NOT_STARTED','MANAGED','STARTING','STARTED','CANCELING',"
        "'SUCCESS','FAILURE','CANCELED'))",
        schema="ops",
    )
    op.create_check_constraint(
        "ck_import_jobs_feature_tracking_shape",
        "import_jobs",
        "(kind <> 'provider_feature_load_run' OR "
        "(parent_job_id IS NULL AND provider IS NULL AND dataset_key IS NULL "
        "AND dagster_run_id IS NOT NULL AND dagster_run_id = btrim(dagster_run_id) "
        "AND dagster_run_id <> '' AND trigger_kind IS NOT NULL "
        "AND operation_registry_version IS NOT NULL "
        "AND operation_registry_version = btrim(operation_registry_version) "
        "AND operation_registry_version <> '' AND dagster_run_status IS NOT NULL)) "
        "AND (kind <> 'provider_feature_load' OR "
        "(parent_job_id IS NOT NULL AND provider IS NOT NULL "
        "AND dataset_key IS NOT NULL AND dagster_run_id IS NOT NULL "
        "AND dagster_run_id = btrim(dagster_run_id) AND dagster_run_id <> '' "
        "AND trigger_kind IS NULL AND operation_registry_version IS NULL "
        "AND dagster_run_status IS NULL))",
        schema="ops",
    )
    op.create_check_constraint(
        "ck_import_jobs_feature_engine_timeline",
        "import_jobs",
        "kind NOT IN ('provider_feature_load_run','provider_feature_load') OR "
        "((started_at IS NULL OR created_at <= started_at) AND "
        "(finished_at IS NULL OR created_at <= finished_at) AND "
        "(started_at IS NULL OR finished_at IS NULL OR "
        "started_at <= finished_at))",
        schema="ops",
    )

    op.add_column(
        "pipeline_cancellation_members",
        sa.Column("operation_kind", sa.Text(), nullable=True),
        schema="ops",
    )
    op.add_column(
        "pipeline_cancellation_runs",
        sa.Column("engine_started_at", sa.DateTime(timezone=True), nullable=True),
        schema="ops",
    )
    op.add_column(
        "pipeline_cancellation_runs",
        sa.Column("engine_finished_at", sa.DateTime(timezone=True), nullable=True),
        schema="ops",
    )
    op.create_check_constraint(
        "ck_pipeline_cancellation_runs_engine_times",
        "pipeline_cancellation_runs",
        "(engine_started_at IS NULL AND engine_finished_at IS NULL) OR "
        "(result IN ('cancelled','already_terminal') "
        "AND engine_finished_at IS NOT NULL "
        "AND (engine_started_at IS NULL OR "
        "engine_started_at <= engine_finished_at))",
        schema="ops",
    )
    op.add_column(
        "pipeline_cancellation_members",
        sa.Column(
            "requires_run_termination",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        schema="ops",
    )
    connection = op.get_bind()
    connection.execute(
        sa.text(
            """
            UPDATE ops.pipeline_cancellation_members AS member
               SET operation_kind = CASE
                     WHEN job.kind = btrim(job.kind) AND job.kind <> '' THEN job.kind
                     ELSE NULL
                   END
              FROM ops.import_jobs AS job
             WHERE member.member_kind = 'import_job'
               AND member.member_id = job.job_id
            """
        )
    )
    malformed_count = connection.execute(
        sa.text(
            """
            SELECT count(*)
            FROM ops.pipeline_cancellation_members AS member
            JOIN ops.import_jobs AS job ON job.job_id = member.member_id
            WHERE member.member_kind = 'import_job'
              AND (job.kind = '' OR job.kind <> btrim(job.kind))
            """
        )
    ).scalar_one()
    if malformed_count:
        _LOG.warning(
            "0051 left %d malformed cancellation member operation kinds as NULL",
            malformed_count,
        )
    connection.execute(
        sa.text(
            """
            UPDATE ops.pipeline_cancellation_members
               SET requires_run_termination = true
             WHERE dagster_run_id IS NOT NULL
               AND (
                 initial_status = 'running'
                 OR (
                   initial_status = 'queued'
                   AND operation_kind IN (
                     'provider_feature_load_run', 'provider_feature_load'
                   )
                 )
               )
            """
        )
    )
    op.create_check_constraint(
        "ck_pipeline_cancellation_members_operation_kind",
        "pipeline_cancellation_members",
        "operation_kind IS NULL OR "
        "(member_kind = 'import_job' AND operation_kind = btrim(operation_kind) "
        "AND operation_kind <> '')",
        schema="ops",
    )
    op.create_check_constraint(
        "ck_pipeline_cancellation_members_run_termination",
        "pipeline_cancellation_members",
        "requires_run_termination = "
        "(dagster_run_id IS NOT NULL AND (initial_status = 'running' OR "
        "(initial_status = 'queued' AND COALESCE(operation_kind IN "
        "('provider_feature_load_run','provider_feature_load'), false))))",
        schema="ops",
    )

    op.execute(
        """
        CREATE FUNCTION ops.check_feature_operation_parent() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE
          parent_kind TEXT;
          parent_run_id TEXT;
          parent_created_at TIMESTAMPTZ;
        BEGIN
          SELECT kind, dagster_run_id, created_at
            INTO parent_kind, parent_run_id, parent_created_at
            FROM ops.import_jobs
           WHERE job_id = NEW.parent_job_id
           FOR KEY SHARE;
          IF NOT FOUND OR parent_kind <> 'provider_feature_load_run'
             OR parent_run_id IS DISTINCT FROM NEW.dagster_run_id
             OR parent_created_at IS DISTINCT FROM NEW.created_at THEN
            RAISE EXCEPTION
              'invalid provider feature operation parent/run/create time'
              USING ERRCODE = '23514';
          END IF;
          RETURN NULL;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER ck_import_jobs_feature_operation_parent
          AFTER INSERT OR UPDATE OF kind, parent_job_id, dagster_run_id, created_at
          ON ops.import_jobs
          DEFERRABLE INITIALLY IMMEDIATE
          FOR EACH ROW
          WHEN (NEW.kind = 'provider_feature_load')
          EXECUTE FUNCTION ops.check_feature_operation_parent()
        """
    )
    op.execute(
        """
        CREATE FUNCTION ops.reject_feature_operation_identity_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF OLD.kind IN ('provider_feature_load_run', 'provider_feature_load')
             OR NEW.kind IN ('provider_feature_load_run', 'provider_feature_load') THEN
            IF ROW(OLD.kind, OLD.parent_job_id, OLD.dagster_run_id, OLD.provider,
                   OLD.dataset_key, OLD.trigger_kind,
                   OLD.operation_registry_version, OLD.created_at)
               IS DISTINCT FROM
               ROW(NEW.kind, NEW.parent_job_id, NEW.dagster_run_id, NEW.provider,
                   NEW.dataset_key, NEW.trigger_kind,
                   NEW.operation_registry_version, NEW.created_at) THEN
              RAISE EXCEPTION 'provider feature operation identity is immutable'
                USING ERRCODE = '23514';
            END IF;
          END IF;
          RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER ck_import_jobs_feature_operation_identity_immutable
          BEFORE UPDATE OF kind, parent_job_id, dagster_run_id, provider,
                           dataset_key, trigger_kind, operation_registry_version,
                           created_at
          ON ops.import_jobs
          FOR EACH ROW
          EXECUTE FUNCTION ops.reject_feature_operation_identity_mutation()
        """
    )

    op.create_index(
        "uq_import_jobs_feature_run",
        "import_jobs",
        ["dagster_run_id"],
        schema="ops",
        unique=True,
        postgresql_where=sa.text(
            "kind = 'provider_feature_load_run' AND parent_job_id IS NULL"
        ),
    )
    op.create_index(
        "uq_import_jobs_feature_run_pair",
        "import_jobs",
        ["parent_job_id", "provider", "dataset_key"],
        schema="ops",
        unique=True,
        postgresql_where=sa.text(
            "kind = 'provider_feature_load' AND parent_job_id IS NOT NULL"
        ),
    )
    op.create_index(
        "idx_import_jobs_provider_dataset_created",
        "import_jobs",
        ["provider", "dataset_key", sa.text("created_at DESC"), sa.text("job_id DESC")],
        schema="ops",
        postgresql_where=sa.text("provider IS NOT NULL AND dataset_key IS NOT NULL"),
    )
    op.create_index(
        "idx_import_jobs_dataset_created",
        "import_jobs",
        ["dataset_key", sa.text("created_at DESC"), sa.text("job_id DESC")],
        schema="ops",
        postgresql_where=sa.text("dataset_key IS NOT NULL"),
    )
    op.create_index(
        "idx_import_jobs_provider_created",
        "import_jobs",
        ["provider", sa.text("created_at DESC"), sa.text("job_id DESC")],
        schema="ops",
        postgresql_where=sa.text("provider IS NOT NULL"),
    )


def downgrade() -> None:
    connection = op.get_bind()
    connection.execute(
        sa.text(
            """
            LOCK TABLE
              ops.pipeline_cancellations,
              ops.pipeline_cancellation_runs,
              ops.pipeline_cancellation_members,
              ops.import_jobs
            IN ACCESS EXCLUSIVE MODE
            """
        )
    )
    incompatible_history_count = connection.execute(
        sa.text(
            """
            SELECT count(*)
            FROM ops.pipeline_cancellation_members
            WHERE initial_status = 'queued'
              AND requires_run_termination IS true
              AND result = 'cancel_failed'
            """
        )
    ).scalar_one()
    incompatible_sample = connection.execute(
        sa.text(
            """
            SELECT cancellation_id::text, member_id::text
            FROM ops.pipeline_cancellation_members
            WHERE initial_status = 'queued'
              AND requires_run_termination IS true
              AND result = 'cancel_failed'
            ORDER BY cancellation_id, member_id
            LIMIT 5
            """
        )
    ).all()
    active_blocked = connection.execute(
        sa.text(
            """
            SELECT EXISTS (
              SELECT 1 FROM ops.import_jobs
              WHERE kind IN ('provider_feature_load_run','provider_feature_load')
                AND status IN ('queued','running')
              UNION ALL
              SELECT 1 FROM ops.pipeline_cancellations
              WHERE status IN ('in_progress','retryable')
            )
            """
        )
    ).scalar_one()
    if active_blocked or incompatible_history_count:
        sample = ", ".join(
            f"{row.cancellation_id}/{row.member_id}" for row in incompatible_sample
        ) or "none"
        raise RuntimeError(
            "0051 downgrade refused: active feature operation/cancellation exists="
            f"{bool(active_blocked)}; incompatible queued run-backed cancel_failed "
            f"history count={incompatible_history_count}; sample "
            f"cancellation_id/member_id={sample}. Export the incompatible history, "
            "perform explicit cleanup, then retry. Query "
            "ops.pipeline_cancellation_members where initial_status='queued' and "
            "requires_run_termination is true and result='cancel_failed'."
        )

    for index_name in (
        "idx_import_jobs_provider_created",
        "idx_import_jobs_dataset_created",
        "idx_import_jobs_provider_dataset_created",
        "uq_import_jobs_feature_run_pair",
        "uq_import_jobs_feature_run",
    ):
        op.drop_index(index_name, table_name="import_jobs", schema="ops")
    op.execute(
        "DROP TRIGGER ck_import_jobs_feature_operation_identity_immutable "
        "ON ops.import_jobs"
    )
    op.execute("DROP FUNCTION ops.reject_feature_operation_identity_mutation()")
    op.execute(
        "DROP TRIGGER ck_import_jobs_feature_operation_parent ON ops.import_jobs"
    )
    op.execute("DROP FUNCTION ops.check_feature_operation_parent()")

    for name in (
        "ck_pipeline_cancellation_members_run_termination",
        "ck_pipeline_cancellation_members_operation_kind",
    ):
        op.drop_constraint(
            name,
            "pipeline_cancellation_members",
            schema="ops",
            type_="check",
        )
    op.drop_constraint(
        "ck_pipeline_cancellation_runs_engine_times",
        "pipeline_cancellation_runs",
        schema="ops",
        type_="check",
    )
    op.drop_column(
        "pipeline_cancellation_runs", "engine_finished_at", schema="ops"
    )
    op.drop_column(
        "pipeline_cancellation_runs", "engine_started_at", schema="ops"
    )
    op.drop_column(
        "pipeline_cancellation_members",
        "requires_run_termination",
        schema="ops",
    )
    op.drop_column(
        "pipeline_cancellation_members", "operation_kind", schema="ops"
    )

    for name in (
        "ck_import_jobs_feature_engine_timeline",
        "ck_import_jobs_feature_tracking_shape",
        "ck_import_jobs_dagster_run_status",
        "ck_import_jobs_registry_version_owner",
        "ck_import_jobs_trigger_kind",
        "ck_import_jobs_provider_dataset_pair",
    ):
        op.drop_constraint(name, "import_jobs", schema="ops", type_="check")
    for column_name in (
        "dagster_run_status",
        "operation_registry_version",
        "trigger_kind",
        "dataset_key",
        "provider",
    ):
        op.drop_column("import_jobs", column_name, schema="ops")
