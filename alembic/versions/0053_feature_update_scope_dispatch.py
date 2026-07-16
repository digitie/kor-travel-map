"""Feature update job에 canonical sync scope와 dispatch intent를 추가한다.

Revision ID: 0053_update_scope_dispatch
Revises: 0052_pipeline_projection_access
Create Date: 2026-07-16
"""

from __future__ import annotations

from collections.abc import Sequence
from time import sleep

import sqlalchemy as sa

from alembic import op

revision: str = "0053_update_scope_dispatch"
down_revision: str | Sequence[str] | None = "0052_pipeline_projection_access"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ACTIVE_SCOPE_INDEX = "uq_import_jobs_active_feature_update_scope"
_POI_EXTERNAL_SYSTEM_CONSTRAINT = "ck_poi_cache_targets_external_system_identity"
_FEATURE_SCOPE_CONSTRAINT = "ck_feature_update_requests_scope_shape"
_LEGACY_SCOPE_VALIDATOR = "is_valid_feature_update_scope_0052"
_LOCK_RETRIES = 600
_LOCK_RETRY_SECONDS = 0.05
_EXTERNAL_SYSTEM_SCOPE_PREFIX = "external_system:"
_MAX_SYNC_SCOPE_LENGTH = 128
_MAX_EXTERNAL_SYSTEM_LENGTH = _MAX_SYNC_SCOPE_LENGTH - len(
    _EXTERNAL_SYSTEM_SCOPE_PREFIX
)
_CANONICAL_WHITESPACE_SQL = (
    "(' ' || chr(9) || chr(10) || chr(11) || chr(12) || chr(13) "
    "|| chr(28) || chr(29) || chr(30) || chr(31) || chr(133) "
    "|| chr(160) || chr(5760) || chr(8192) || chr(8193) || chr(8194) "
    "|| chr(8195) || chr(8196) || chr(8197) || chr(8198) || chr(8199) "
    "|| chr(8200) || chr(8201) || chr(8202) || chr(8232) || chr(8233) "
    "|| chr(8239) || chr(8287) || chr(12288))"
)
_KMA_GRID_DATASETS = (
    "kma_short_forecast",
    "kma_ultra_short_nowcast",
    "kma_ultra_short_forecast",
)


def _legacy_effective_scope_case(*, job_alias: str) -> str:
    """0052까지의 실제 실행 의미를 canonical job identity로 고정한다."""
    grid_datasets = ", ".join(f"'{dataset}'" for dataset in _KMA_GRID_DATASETS)
    return (
        "CASE "
        f"WHEN {job_alias}.provider = 'python-kma-api' "
        f"AND {job_alias}.dataset_key IN ({grid_datasets}) "
        "THEN 'target_grids' "
        "ELSE 'dataset_wide' END"
    )


def _canonical_sync_scope_check(column: str) -> str:
    """typed execution identity의 세 canonical 형식만 허용한다."""
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


def _external_system_identity_check(column: str) -> str:
    return (
        f"({column} <> '' "
        f"AND char_length({column}) <= {_MAX_EXTERNAL_SYSTEM_LENGTH} "
        f"AND {column} = btrim({column}, {_CANONICAL_WHITESPACE_SQL}))"
    )


def _fail_on_invalid_feature_scope_external_systems() -> None:
    rows = (
        op.get_bind()
        .execute(
            sa.text(
                f"""
                SELECT request_id::text, scope->>'external_system' AS external_system,
                       char_length(scope->>'external_system') AS name_length
                FROM ops.feature_update_requests
                WHERE scope_type = 'cache_target_keys'
                  AND char_length(scope->>'external_system') > {_MAX_EXTERNAL_SYSTEM_LENGTH}
                ORDER BY request_id
                LIMIT 20
                """
            )
        )
        .mappings()
        .all()
    )
    if rows:
        raise RuntimeError(
            "0053 found cache_target_keys external_system identities longer than "
            f"{_MAX_EXTERNAL_SYSTEM_LENGTH}: {[dict(row) for row in rows]}"
        )


def _upgrade_feature_scope_validator() -> None:
    """0052 validator를 보존하고 cache external-system 112자 계약을 덧씌운다."""
    op.drop_constraint(
        op.f(_FEATURE_SCOPE_CONSTRAINT),
        "feature_update_requests",
        schema="ops",
        type_="check",
    )
    op.execute(
        "ALTER FUNCTION ops.is_valid_feature_update_scope(text, jsonb) "
        f"RENAME TO {_LEGACY_SCOPE_VALIDATOR}"
    )
    op.execute(
        f"""
        CREATE FUNCTION ops.is_valid_feature_update_scope(
          p_scope_type text,
          p_scope jsonb
        ) RETURNS boolean
        LANGUAGE sql
        IMMUTABLE
        PARALLEL SAFE
        AS $$
          SELECT ops.{_LEGACY_SCOPE_VALIDATOR}(p_scope_type, p_scope)
             AND (
               p_scope_type <> 'cache_target_keys'
               OR char_length(p_scope->>'external_system')
                    <= {_MAX_EXTERNAL_SYSTEM_LENGTH}
             )
        $$
        """
    )
    op.create_check_constraint(
        op.f(_FEATURE_SCOPE_CONSTRAINT),
        "feature_update_requests",
        "ops.is_valid_feature_update_scope(scope_type, scope)",
        schema="ops",
    )


def _downgrade_feature_scope_validator() -> None:
    op.drop_constraint(
        op.f(_FEATURE_SCOPE_CONSTRAINT),
        "feature_update_requests",
        schema="ops",
        type_="check",
    )
    op.execute("DROP FUNCTION ops.is_valid_feature_update_scope(text, jsonb)")
    op.execute(
        f"ALTER FUNCTION ops.{_LEGACY_SCOPE_VALIDATOR}(text, jsonb) "
        "RENAME TO is_valid_feature_update_scope"
    )
    op.create_check_constraint(
        op.f(_FEATURE_SCOPE_CONSTRAINT),
        "feature_update_requests",
        "ops.is_valid_feature_update_scope(scope_type, scope)",
        schema="ops",
    )


def _lock_feature_update_identity_writers() -> None:
    """backfill과 제약 설치 사이에 request/job writer가 끼어들지 못하게 한다."""
    connection = op.get_bind()
    for attempt in range(_LOCK_RETRIES):
        savepoint = connection.begin_nested()
        try:
            connection.execute(
                sa.text(
                    "LOCK TABLE ops.feature_update_requests, ops.import_jobs, "
                    "ops.poi_cache_targets "
                    "IN ACCESS EXCLUSIVE MODE NOWAIT"
                )
            )
        except sa.exc.DBAPIError as exc:
            savepoint.rollback()
            sqlstate = getattr(exc.orig, "sqlstate", None) or getattr(exc.orig, "pgcode", None)
            if sqlstate != "55P03":
                raise
            if attempt + 1 == _LOCK_RETRIES:
                raise RuntimeError(
                    "0053 feature update identity writer lock could not be acquired "
                    "within 30 seconds"
                ) from exc
            sleep(_LOCK_RETRY_SECONDS)
        else:
            savepoint.commit()
            return
    raise AssertionError("unreachable identity lock retry state")


def _fail_on_active_scope_ambiguity() -> None:
    """active 중복은 임의 취소하지 않고 운영 정리를 요구한다."""
    effective_scope = _legacy_effective_scope_case(job_alias="job")
    rows = (
        op.get_bind()
        .execute(
            sa.text(
                f"""
                SELECT
                  job.provider,
                  job.dataset_key,
                  {effective_scope} AS sync_scope,
                  array_agg(job.job_id::text ORDER BY
                    (job.status = 'running') DESC,
                    request.created_at,
                    job.job_id
                  ) AS job_ids,
                  array_agg(job.status ORDER BY
                    (job.status = 'running') DESC,
                    request.created_at,
                    job.job_id
                  ) AS statuses
                FROM ops.import_jobs AS job
                JOIN ops.feature_update_requests AS request
                  ON request.job_id = job.job_id
                WHERE job.kind = 'feature_update_request'
                  AND job.quarantined_at IS NULL
                  AND job.status IN ('queued', 'running')
                  AND request.scope_type = 'provider_dataset'
                GROUP BY
                  job.provider,
                  job.dataset_key,
                  {effective_scope}
                HAVING COUNT(*) > 1
                ORDER BY job.provider, job.dataset_key, sync_scope
                LIMIT 20
                """
            )
        )
        .mappings()
        .all()
    )
    if rows:
        details = [
            {
                "provider": row["provider"],
                "dataset_key": row["dataset_key"],
                "sync_scope": row["sync_scope"],
                "job_ids": list(row["job_ids"]),
                "statuses": list(row["statuses"]),
            }
            for row in rows
        ]
        raise RuntimeError(
            "0053 cannot choose a winner for active or running feature update scope "
            f"duplicates; resolve the operations before migration: {details!r}"
        )


def _fail_on_invalid_poi_external_systems() -> None:
    """scope identity로 표현할 수 없는 기존 POI system은 자동 변형하지 않는다."""
    rows = (
        op.get_bind()
        .execute(
            sa.text(
                f"""
                SELECT target_id::text, external_system
                  FROM ops.poi_cache_targets
                 WHERE NOT {_external_system_identity_check('external_system')}
                 ORDER BY target_id
                 LIMIT 20
                """
            )
        )
        .mappings()
        .all()
    )
    if rows:
        details = [
            {
                "target_id": row["target_id"],
                "external_system": row["external_system"],
                "length": len(row["external_system"]),
            }
            for row in rows
        ]
        raise RuntimeError(
            "0053 cannot install canonical external_system identity; rename the "
            f"invalid POI cache targets before migration: {details!r}"
        )


def _replace_update_request_shape_constraint(*, include_scope: bool) -> None:
    op.drop_constraint(
        op.f("ck_import_jobs_update_request_shape"),
        "import_jobs",
        schema="ops",
        type_="check",
    )
    scope_shape = ""
    if include_scope:
        scope_shape = (
            "AND ((provider IS NULL AND dataset_key IS NULL AND sync_scope IS NULL) OR "
            "(provider IS NOT NULL AND dataset_key IS NOT NULL "
            "AND sync_scope IS NOT NULL "
            f"AND {_canonical_sync_scope_check('sync_scope')})) "
        )
    op.create_check_constraint(
        op.f("ck_import_jobs_update_request_shape"),
        "import_jobs",
        "kind <> 'feature_update_request' OR quarantined_at IS NOT NULL OR "
        "(parent_job_id IS NULL AND load_batch_id IS NULL "
        "AND trigger_kind = 'update_request' "
        "AND operation_registry_version IS NULL AND dagster_run_status IS NULL "
        "AND payload = '{}'::jsonb "
        "AND (dagster_run_id IS NULL OR (dagster_run_id = btrim(dagster_run_id) "
        "AND dagster_run_id <> '')) "
        "AND (status <> 'queued' OR dagster_run_id IS NULL) "
        "AND (status <> 'running' OR dagster_run_id IS NOT NULL) "
        f"{scope_shape})",
        schema="ops",
    )


def _replace_import_job_identity_guard(*, include_scope: bool) -> None:
    op.execute("DROP TRIGGER trg_import_jobs_identity_immutable ON ops.import_jobs")
    scope_guard = "OR NEW.sync_scope IS DISTINCT FROM OLD.sync_scope" if include_scope else ""
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION ops.reject_import_job_identity_change()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
          IF NEW.kind IS DISTINCT FROM OLD.kind
             OR NEW.provider IS DISTINCT FROM OLD.provider
             OR NEW.dataset_key IS DISTINCT FROM OLD.dataset_key
             {scope_guard}
             OR (
               OLD.kind = 'feature_update_request'
               AND NEW.payload IS DISTINCT FROM OLD.payload
             ) THEN
            RAISE EXCEPTION
              'import job kind/provider/dataset/scope/payload identity is immutable for job %',
              OLD.job_id
              USING ERRCODE = 'check_violation';
          END IF;
          RETURN NEW;
        END;
        $$
        """
    )
    update_columns = "kind, provider, dataset_key, payload"
    if include_scope:
        update_columns = "kind, provider, dataset_key, sync_scope, payload"
    op.execute(
        f"""
        CREATE TRIGGER trg_import_jobs_identity_immutable
        BEFORE UPDATE OF {update_columns} ON ops.import_jobs
        FOR EACH ROW EXECUTE FUNCTION ops.reject_import_job_identity_change()
        """
    )


def _replace_request_job_identity_guard(*, include_scope: bool) -> None:
    scope_declaration = "linked_sync_scope text;" if include_scope else ""
    select_scope = ", job.sync_scope" if include_scope else ""
    into_scope = ", linked_sync_scope" if include_scope else ""
    non_direct_scope_guard = ""
    direct_requested_scope_guard = ""
    if include_scope:
        non_direct_scope_guard = " OR linked_sync_scope IS NOT NULL"
        requested_scope_check = _canonical_sync_scope_check(
            "(NEW.scope->>'sync_scope')"
        )
        direct_requested_scope_guard = f"""
            IF NEW.scope ? 'sync_scope' AND (
                 NOT {requested_scope_check}
                 OR linked_sync_scope IS DISTINCT FROM NEW.scope->>'sync_scope'
               ) THEN
              RAISE EXCEPTION
                'explicit requested sync_scope must equal canonical linked job scope'
                USING ERRCODE = 'check_violation';
            END IF;
        """
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION ops.enforce_feature_update_request_job_identity()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
          linked_kind text;
          linked_provider text;
          linked_dataset_key text;
          {scope_declaration}
          linked_quarantined_at timestamptz;
        BEGIN
          SELECT job.kind, job.provider, job.dataset_key{select_scope}, job.quarantined_at
            INTO linked_kind, linked_provider, linked_dataset_key{into_scope},
                 linked_quarantined_at
            FROM ops.import_jobs AS job
           WHERE job.job_id = NEW.job_id
           FOR KEY SHARE;
          IF NOT FOUND THEN
            RAISE EXCEPTION 'feature update request job does not exist: %', NEW.job_id
              USING ERRCODE = 'foreign_key_violation';
          END IF;

          IF linked_kind IS DISTINCT FROM 'feature_update_request' THEN
            RAISE EXCEPTION
              'feature update request must link a canonical feature_update_request job'
              USING ERRCODE = 'check_violation';
          END IF;

          IF linked_quarantined_at IS NOT NULL THEN
            RAISE EXCEPTION
              'feature update request cannot link a quarantined import job'
              USING ERRCODE = 'check_violation';
          END IF;

          IF NEW.scope_type = 'provider_dataset' THEN
            IF linked_provider IS DISTINCT FROM NEW.scope->>'provider'
               OR linked_dataset_key IS DISTINCT FROM NEW.scope->>'dataset_key' THEN
              RAISE EXCEPTION
                'provider_dataset request scope must equal linked job identity'
                USING ERRCODE = 'check_violation';
            END IF;
            {direct_requested_scope_guard}
          ELSIF linked_provider IS NOT NULL OR linked_dataset_key IS NOT NULL
                {non_direct_scope_guard} THEN
            RAISE EXCEPTION
              'non-provider_dataset request must link an unpaired import job'
              USING ERRCODE = 'check_violation';
          END IF;
          RETURN NEW;
        END;
        $$
        """
    )


def upgrade() -> None:
    _lock_feature_update_identity_writers()
    _fail_on_invalid_poi_external_systems()
    _fail_on_invalid_feature_scope_external_systems()
    _fail_on_active_scope_ambiguity()
    _upgrade_feature_scope_validator()

    op.add_column(
        "import_jobs",
        sa.Column("sync_scope", sa.Text(), nullable=True),
        schema="ops",
    )
    op.add_column(
        "import_jobs",
        sa.Column("dispatch_requested_at", sa.DateTime(timezone=True), nullable=True),
        schema="ops",
    )
    effective_scope = _legacy_effective_scope_case(job_alias="job")
    op.execute(
        f"""
        UPDATE ops.import_jobs AS job
           SET sync_scope = {effective_scope}
          FROM ops.feature_update_requests AS request
         WHERE request.job_id = job.job_id
           AND request.scope_type = 'provider_dataset'
           AND job.kind = 'feature_update_request'
           AND job.quarantined_at IS NULL
        """
    )
    op.execute(
        """
        UPDATE ops.import_jobs AS job
           SET dispatch_requested_at = request.created_at
          FROM ops.feature_update_requests AS request
         WHERE request.job_id = job.job_id
           AND request.run_mode = 'now'
           AND job.kind = 'feature_update_request'
           AND job.quarantined_at IS NULL
        """
    )

    _replace_update_request_shape_constraint(include_scope=True)
    op.create_check_constraint(
        op.f(_POI_EXTERNAL_SYSTEM_CONSTRAINT),
        "poi_cache_targets",
        _external_system_identity_check("external_system"),
        schema="ops",
    )
    op.create_check_constraint(
        op.f("ck_import_jobs_dispatch_requested_at"),
        "import_jobs",
        "dispatch_requested_at IS NULL OR kind = 'feature_update_request'",
        schema="ops",
    )
    _replace_import_job_identity_guard(include_scope=True)
    _replace_request_job_identity_guard(include_scope=True)
    op.create_index(
        _ACTIVE_SCOPE_INDEX,
        "import_jobs",
        ["provider", "dataset_key", "sync_scope"],
        unique=True,
        schema="ops",
        postgresql_where=sa.text(
            "kind = 'feature_update_request' "
            "AND status IN ('queued','running') "
            "AND quarantined_at IS NULL "
            "AND provider IS NOT NULL"
        ),
    )


def downgrade() -> None:
    op.drop_index(_ACTIVE_SCOPE_INDEX, table_name="import_jobs", schema="ops")
    _replace_request_job_identity_guard(include_scope=False)
    _replace_import_job_identity_guard(include_scope=False)
    op.drop_constraint(
        op.f("ck_import_jobs_dispatch_requested_at"),
        "import_jobs",
        schema="ops",
        type_="check",
    )
    _replace_update_request_shape_constraint(include_scope=False)
    op.drop_constraint(
        op.f(_POI_EXTERNAL_SYSTEM_CONSTRAINT),
        "poi_cache_targets",
        schema="ops",
        type_="check",
    )
    _downgrade_feature_scope_validator()
    op.drop_column("import_jobs", "dispatch_requested_at", schema="ops")
    op.drop_column("import_jobs", "sync_scope", schema="ops")
