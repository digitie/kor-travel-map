"""T-VN-40B provider cancellation lifecycle typed command boundary.

Revision ID: 0115_tvn40_cancel_cmds
Revises: 0114_tvn40_provider_ops_cmds
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# Frozen PostgreSQL command text intentionally exceeds Python line length.
# ruff: noqa: E501

revision: str = "0115_tvn40_cancel_cmds"
down_revision: str | Sequence[str] | None = "0114_tvn40_provider_ops_cmds"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_FILL_SIGNATURE = "ops.fill_provider_cancellation_starts_command(uuid,text,timestamptz)"
_TRANSITION_SIGNATURE = (
    "ops.transition_provider_cancellation_job_command(uuid,uuid,text,text[],text,text,text,"
    "timestamptz,timestamptz,boolean,text,text[])"
)

_FILL_COMMAND_SQL = r"""
CREATE FUNCTION ops.fill_provider_cancellation_starts_command(
  p_cancellation_id uuid,
  p_dagster_run_id text,
  p_engine_started_at timestamptz
) RETURNS TABLE(expected_count bigint, owned_count bigint, updated_job_ids uuid[])
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, ops
AS $command$
BEGIN
  IF session_user <> 'ktm_feature_api_runtime'
     AND NOT EXISTS (
       SELECT 1 FROM pg_catalog.pg_roles AS role
       WHERE role.rolname = session_user AND role.rolsuper
     ) THEN
    RAISE EXCEPTION 'provider cancellation command requires API runtime'
      USING ERRCODE = '42501';
  END IF;
  IF p_engine_started_at IS NULL OR p_dagster_run_id IS NULL OR btrim(p_dagster_run_id) = '' THEN
    RAISE EXCEPTION 'invalid provider cancellation start command'
      USING ERRCODE = '22023';
  END IF;
  IF NOT EXISTS (
    SELECT 1
    FROM ops.pipeline_cancellations AS attempt
    JOIN ops.pipeline_cancellation_runs AS run
      ON run.cancellation_id = attempt.cancellation_id
     AND run.dagster_run_id = p_dagster_run_id
    WHERE attempt.cancellation_id = p_cancellation_id
      AND attempt.status = 'in_progress'
      AND run.result IN ('cancelled','already_terminal')
      AND run.engine_started_at = p_engine_started_at
    FOR UPDATE OF attempt, run
  ) THEN
    RAISE EXCEPTION 'provider cancellation start proof is not current'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_provider_cancellation_start_proof';
  END IF;
  RETURN QUERY
  WITH canonical_jobs AS (
    SELECT job.job_id, job.cancellation_id, job.started_at
    FROM ops.pipeline_cancellation_members AS member
    JOIN ops.import_jobs AS job ON job.job_id = member.job_id
    WHERE member.cancellation_id = p_cancellation_id
      AND member.dagster_run_id = p_dagster_run_id
      AND member.operation_kind IN ('provider_feature_load_run','provider_feature_load')
  ),
  updated AS (
    UPDATE ops.import_jobs AS job
    SET started_at = p_engine_started_at
    FROM canonical_jobs AS candidate
    WHERE job.job_id = candidate.job_id
      AND candidate.cancellation_id = p_cancellation_id
      AND job.cancellation_id = p_cancellation_id
      AND job.started_at IS NULL
    RETURNING job.job_id
  )
  SELECT
    (SELECT count(*) FROM canonical_jobs),
    (SELECT count(*) FROM canonical_jobs WHERE cancellation_id = p_cancellation_id),
    COALESCE((SELECT array_agg(job_id ORDER BY job_id) FROM updated), '{}'::uuid[]);
END
$command$;
"""

_TRANSITION_COMMAND_SQL = r"""
CREATE FUNCTION ops.transition_provider_cancellation_job_command(
  p_cancellation_id uuid,
  p_job_id uuid,
  p_dagster_run_id text,
  p_expected_statuses text[],
  p_target_status text,
  p_error_message text,
  p_dagster_terminal_status text,
  p_engine_started_at timestamptz,
  p_engine_finished_at timestamptz,
  p_success_tracking_invariant boolean,
  p_result text,
  p_expected_member_results text[]
) RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, ops
AS $command$
DECLARE
  v_member ops.pipeline_cancellation_members%ROWTYPE;
  v_run ops.pipeline_cancellation_runs%ROWTYPE;
  v_changed bigint;
  v_finished_at timestamptz;
  v_generation_count bigint;
  v_generation_set_hash text;
  v_replayed boolean;
  v_stale_input boolean;
BEGIN
  IF session_user <> 'ktm_feature_api_runtime'
     AND NOT EXISTS (
       SELECT 1 FROM pg_catalog.pg_roles AS role
       WHERE role.rolname = session_user AND role.rolsuper
     ) THEN
    RAISE EXCEPTION 'provider cancellation command requires API runtime'
      USING ERRCODE = '42501';
  END IF;
  IF p_target_status NOT IN ('done','failed','cancelled')
     OR p_result NOT IN ('cancelled','already_terminal')
     OR p_expected_statuses IS NULL OR cardinality(p_expected_statuses) = 0
     OR p_expected_member_results IS NULL OR cardinality(p_expected_member_results) = 0 THEN
    RAISE EXCEPTION 'invalid provider cancellation terminal command'
      USING ERRCODE = '22023';
  END IF;
  PERFORM 1 FROM ops.pipeline_cancellations
  WHERE cancellation_id = p_cancellation_id AND status = 'in_progress'
  FOR UPDATE;
  IF NOT FOUND THEN
    RETURN false;
  END IF;
  SELECT member.* INTO v_member
  FROM ops.pipeline_cancellation_members AS member
  WHERE member.cancellation_id = p_cancellation_id
    AND member.job_id = p_job_id
  FOR UPDATE;
  IF NOT FOUND OR v_member.operation_kind NOT IN ('provider_feature_load_run','provider_feature_load')
     OR NOT (v_member.result = ANY(p_expected_member_results))
     OR v_member.dagster_run_id IS DISTINCT FROM p_dagster_run_id THEN
    RETURN false;
  END IF;
  IF v_member.requires_run_termination THEN
    SELECT run.* INTO v_run
    FROM ops.pipeline_cancellation_runs AS run
    WHERE run.cancellation_id = p_cancellation_id
      AND run.dagster_run_id = p_dagster_run_id
    FOR UPDATE;
    IF NOT FOUND OR v_run.result <> p_result
       OR v_run.engine_started_at IS DISTINCT FROM p_engine_started_at
       OR v_run.engine_finished_at IS DISTINCT FROM p_engine_finished_at
       OR p_engine_finished_at IS NULL
       OR p_dagster_terminal_status IS DISTINCT FROM v_run.terminal_status
       OR NOT (
         (p_result = 'cancelled' AND v_run.terminal_status = 'CANCELED' AND p_target_status = 'cancelled')
         OR (p_result = 'already_terminal' AND v_run.terminal_status = 'SUCCESS'
             AND ((NOT p_success_tracking_invariant AND p_target_status = 'done')
                  OR (p_success_tracking_invariant AND p_target_status = 'failed')))
         OR (p_result = 'already_terminal' AND v_run.terminal_status = 'FAILURE'
             AND NOT p_success_tracking_invariant AND p_target_status = 'failed')
       ) THEN
      RAISE EXCEPTION 'provider cancellation terminal proof does not match the command'
        USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_provider_cancellation_terminal_proof';
    END IF;
  ELSIF v_member.initial_status <> 'queued'
        OR p_expected_statuses <> ARRAY['queued']::text[]
        OR p_result <> 'cancelled' OR p_target_status <> 'cancelled'
        OR p_dagster_terminal_status IS NOT NULL
        OR p_engine_started_at IS NOT NULL OR p_engine_finished_at IS NOT NULL
        OR p_success_tracking_invariant THEN
    RAISE EXCEPTION 'queued provider cancellation proof does not match the command'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_provider_cancellation_terminal_proof';
  END IF;
  v_finished_at := COALESCE(p_engine_finished_at, clock_timestamp());

  UPDATE ops.import_jobs AS job
  SET status = p_target_status,
      error_message = COALESCE(p_error_message, job.error_message),
      finished_at = v_finished_at,
      started_at = COALESCE(job.started_at, p_engine_started_at),
      heartbeat_at = CASE WHEN job.status = 'running' THEN v_finished_at ELSE job.heartbeat_at END,
      progress = CASE WHEN p_target_status = 'done' THEN 100 ELSE job.progress END,
      current_stage = CASE p_target_status
        WHEN 'done' THEN 'completed'
        WHEN 'failed' THEN CASE WHEN p_success_tracking_invariant
          THEN 'tracking_invariant' ELSE 'failed' END
        WHEN 'cancelled' THEN 'cancelled'
      END,
      dagster_run_status = CASE WHEN job.kind = 'provider_feature_load_run'
        THEN p_dagster_terminal_status ELSE job.dagster_run_status END
  WHERE job.job_id = p_job_id
    AND job.cancellation_id = p_cancellation_id
    AND job.status = ANY(p_expected_statuses)
    AND job.dagster_run_id IS NOT DISTINCT FROM p_dagster_run_id
    AND job.kind = v_member.operation_kind
    AND (p_engine_finished_at IS NULL OR job.created_at <= p_engine_finished_at)
    AND (p_engine_started_at IS NULL OR job.created_at <= p_engine_started_at)
    AND (p_engine_finished_at IS NULL OR job.started_at IS NULL OR job.started_at <= p_engine_finished_at)
    AND (p_engine_started_at IS NULL OR job.started_at IS NULL OR job.started_at = p_engine_started_at);
  GET DIAGNOSTICS v_changed = ROW_COUNT;
  IF v_changed = 0 THEN
    RETURN false;
  END IF;
  UPDATE ops.pipeline_cancellation_members AS member
  SET result = p_result,
      terminal_status = p_target_status,
      error = NULL,
      updated_at = clock_timestamp()
  WHERE member.cancellation_id = p_cancellation_id
    AND member.job_id = p_job_id
    AND member.result = ANY(p_expected_member_results);
  IF NOT FOUND THEN
    RAISE EXCEPTION 'provider cancellation member CAS failed after base transition'
      USING ERRCODE = '40001';
  END IF;
  IF v_member.operation_kind = 'provider_feature_load_run'
     AND p_result = 'already_terminal'
     AND p_dagster_terminal_status = 'SUCCESS'
     AND p_target_status = 'done' THEN
    PERFORM set_config(
      'ktm.curation_cancellation_root', p_job_id::text, true
    );
    CALL feature.finalize_provider_curation_root(
      p_job_id, v_generation_count, v_generation_set_hash,
      v_replayed, v_stale_input
    );
    IF v_stale_input THEN
      RAISE EXCEPTION 'provider cancellation SUCCESS has stale curation input'
        USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_provider_curation_stale_input';
    END IF;
  END IF;
  RETURN true;
END
$command$;
"""

_GUARD_SQL = r"""
CREATE OR REPLACE FUNCTION ops.reject_provider_feature_operation_raw_dml()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, ops
AS $guard$
DECLARE
  v_kind text;
BEGIN
  IF current_user = 'ktm_curation_command_owner'
     OR EXISTS (
       SELECT 1 FROM pg_catalog.pg_roles AS role
       WHERE role.rolname = session_user AND role.rolsuper
     ) THEN
    RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
  END IF;
  v_kind := CASE WHEN TG_OP = 'DELETE' THEN OLD.kind ELSE NEW.kind END;
  IF v_kind IN ('provider_feature_load_run', 'provider_feature_load')
     OR (TG_OP = 'UPDATE' AND OLD.kind IN (
       'provider_feature_load_run', 'provider_feature_load'
     )) THEN
    IF TG_OP = 'UPDATE'
       AND session_user = 'ktm_feature_api_runtime'
       AND NEW.cancellation_id IS NOT NULL
       AND EXISTS (
         SELECT 1
         FROM ops.pipeline_cancellation_members AS member
         JOIN ops.pipeline_cancellations AS attempt
           ON attempt.cancellation_id = member.cancellation_id
         WHERE member.cancellation_id = NEW.cancellation_id
           AND member.job_id = NEW.job_id
           AND attempt.status = 'in_progress'
       )
       AND to_jsonb(NEW) - ARRAY[
         'cancellation_id','cancellation_requested_at',
         'cancellation_requested_by','cancellation_reason'
       ]::text[]
       = to_jsonb(OLD) - ARRAY[
         'cancellation_id','cancellation_requested_at',
         'cancellation_requested_by','cancellation_reason'
       ]::text[] THEN
      RETURN NEW;
    END IF;
    RAISE EXCEPTION 'provider feature operations require a typed command'
      USING ERRCODE = '42501', CONSTRAINT = 'ck_tvn40_provider_operation_typed_command';
  END IF;
  RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
END
$guard$;
"""


def upgrade() -> None:
    op.execute(_FILL_COMMAND_SQL)
    op.execute(_TRANSITION_COMMAND_SQL)
    op.execute(_GUARD_SQL)
    op.execute("GRANT USAGE, CREATE ON SCHEMA ops TO ktm_curation_command_owner")
    op.execute(f"ALTER FUNCTION {_FILL_SIGNATURE} OWNER TO ktm_curation_command_owner")
    op.execute(f"ALTER FUNCTION {_TRANSITION_SIGNATURE} OWNER TO ktm_curation_command_owner")
    op.execute("REVOKE CREATE ON SCHEMA ops FROM ktm_curation_command_owner")
    op.execute(
        "GRANT SELECT, UPDATE ON TABLE ops.pipeline_cancellations, "
        "ops.pipeline_cancellation_runs TO ktm_curation_command_owner"
    )
    op.execute(
        "GRANT SELECT, UPDATE ON TABLE ops.pipeline_cancellation_members "
        "TO ktm_curation_command_owner"
    )
    op.execute("SET ROLE ktm_curation_command_owner")
    for signature in (_FILL_SIGNATURE, _TRANSITION_SIGNATURE):
        op.execute(
            f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC, ktm_feature_runtime, "
            "ktm_feature_dagster_runtime, ktm_curation_provider_executor, "
            "ktm_curation_admin_executor"
        )
        op.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO ktm_feature_api_runtime")
    op.execute("SET ROLE ktm_feature_schema_owner")


def downgrade() -> None:
    raise RuntimeError("0115 is forward-only; rebuild with the T-VN-40 release head")
