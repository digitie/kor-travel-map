"""T-VN-40B provider feature-operation typed command boundary.

Revision ID: 0114_tvn40_provider_ops_cmds
Revises: 0113_tvn40_concierge_catalog

The Dagster login may read canonical operation rows, but it may not forge the
provider root/member identity or terminal evidence with raw DML.  The API
cancellation path remains independently authorized by its own login.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# Frozen PostgreSQL command text intentionally exceeds Python line length.
# ruff: noqa: E501

revision: str = "0114_tvn40_provider_ops_cmds"
down_revision: str | Sequence[str] | None = "0113_tvn40_concierge_catalog"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _execute_commands(source: str) -> None:
    """Dollar-quoted routine bodies를 보존해 asyncpg statement를 분리한다."""

    statements: list[str] = []
    start = 0
    index = 0
    quote: str | None = None
    dollar_tag: str | None = None
    while index < len(source):
        character = source[index]
        if dollar_tag is not None:
            if source.startswith(dollar_tag, index):
                index += len(dollar_tag)
                dollar_tag = None
                continue
            index += 1
            continue
        if quote is not None:
            if character == quote:
                if index + 1 < len(source) and source[index + 1] == quote:
                    index += 2
                    continue
                quote = None
            index += 1
            continue
        if character in {"'", '"'}:
            quote = character
            index += 1
            continue
        if character == "$":
            end = source.find("$", index + 1)
            if end != -1:
                candidate = source[index : end + 1]
                inner = candidate[1:-1]
                if not inner or inner.replace("_", "a").isalnum():
                    dollar_tag = candidate
                    index = end + 1
                    continue
        if character == ";":
            statement = source[start:index].strip()
            if statement:
                statements.append(statement)
            start = index + 1
        index += 1
    trailing = source[start:].strip()
    if trailing:
        statements.append(trailing)
    for statement in statements:
        op.execute(statement)


_HELPERS_SQL = r"""
CREATE FUNCTION ops.reject_provider_feature_operation_raw_dml()
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
       AND (
         to_jsonb(NEW) - ARRAY[
           'cancellation_id','cancellation_requested_at',
           'cancellation_requested_by','cancellation_reason'
         ]::text[]
         = to_jsonb(OLD) - ARRAY[
           'cancellation_id','cancellation_requested_at',
           'cancellation_requested_by','cancellation_reason'
         ]::text[]
         OR to_jsonb(NEW) - ARRAY['started_at']::text[]
            = to_jsonb(OLD) - ARRAY['started_at']::text[]
         OR to_jsonb(NEW) - ARRAY[
              'status','error_message','finished_at','started_at','heartbeat_at',
              'progress','current_stage','dagster_run_status'
            ]::text[]
            = to_jsonb(OLD) - ARRAY[
              'status','error_message','finished_at','started_at','heartbeat_at',
              'progress','current_stage','dagster_run_status'
            ]::text[]
       ) THEN
      RETURN NEW;
    END IF;
    RAISE EXCEPTION 'provider feature operations require a typed command'
      USING ERRCODE = '42501', CONSTRAINT = 'ck_tvn40_provider_operation_typed_command';
  END IF;
  RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
END
$guard$;

CREATE FUNCTION ops.reject_provider_feature_membership_raw_dml()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, ops
AS $guard$
DECLARE
  v_job_id uuid;
BEGIN
  IF current_user = 'ktm_curation_command_owner'
     OR EXISTS (
       SELECT 1 FROM pg_catalog.pg_roles AS role
       WHERE role.rolname = session_user AND role.rolsuper
     ) THEN
    RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
  END IF;
  v_job_id := CASE WHEN TG_OP = 'DELETE' THEN OLD.job_id ELSE NEW.job_id END;
  IF EXISTS (
    SELECT 1 FROM ops.import_jobs AS job
    WHERE job.job_id = v_job_id
      AND job.kind = 'provider_feature_load'
  ) OR (TG_OP = 'UPDATE' AND EXISTS (
    SELECT 1 FROM ops.import_jobs AS job
    WHERE job.job_id = OLD.job_id
      AND job.kind = 'provider_feature_load'
  )) THEN
    RAISE EXCEPTION 'provider feature memberships require a typed command'
      USING ERRCODE = '42501', CONSTRAINT = 'ck_tvn40_provider_membership_typed_command';
  END IF;
  RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
END
$guard$;

CREATE FUNCTION ops.reject_provider_feature_event_raw_dml()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, ops
AS $guard$
DECLARE
  v_job_id uuid;
BEGIN
  IF current_user = 'ktm_curation_command_owner'
     OR EXISTS (
       SELECT 1 FROM pg_catalog.pg_roles AS role
       WHERE role.rolname = session_user AND role.rolsuper
     ) THEN
    RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
  END IF;
  v_job_id := CASE WHEN TG_OP = 'DELETE' THEN OLD.job_id ELSE NEW.job_id END;
  IF EXISTS (
    SELECT 1 FROM ops.import_jobs AS job
    WHERE job.job_id = v_job_id
      AND job.kind IN ('provider_feature_load_run','provider_feature_load')
  ) THEN
    RAISE EXCEPTION 'provider feature events require a typed command'
      USING ERRCODE = '42501', CONSTRAINT = 'ck_tvn40_provider_event_typed_command';
  END IF;
  RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
END
$guard$;

CREATE TRIGGER trg_provider_feature_operation_typed_command
BEFORE INSERT OR UPDATE OR DELETE ON ops.import_jobs
FOR EACH ROW EXECUTE FUNCTION ops.reject_provider_feature_operation_raw_dml();

CREATE TRIGGER trg_provider_feature_membership_typed_command
BEFORE INSERT OR UPDATE OR DELETE ON ops.import_job_datasets
FOR EACH ROW EXECUTE FUNCTION ops.reject_provider_feature_membership_raw_dml();

CREATE TRIGGER trg_provider_feature_event_typed_command
BEFORE INSERT OR UPDATE OR DELETE ON ops.import_job_events
FOR EACH ROW EXECUTE FUNCTION ops.reject_provider_feature_event_raw_dml();
"""


_COMMANDS_SQL = r"""
CREATE PROCEDURE ops.ensure_provider_feature_operation_command(
  IN p_dagster_run_id text,
  IN p_trigger_kind text,
  IN p_operation_key text,
  IN p_memberships jsonb,
  IN p_created_at timestamptz,
  IN p_started_at timestamptz,
  IN p_observed_status text,
  OUT o_root_job_id uuid,
  OUT o_inserted boolean,
  OUT o_changed boolean
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, ops, provider_sync
AS $command$
DECLARE
  v_member record;
  v_base_status text;
  v_stage text;
  v_member_count bigint;
  v_distinct_member_count bigint;
BEGIN
  IF NOT pg_has_role(session_user, 'ktm_curation_provider_executor', 'member')
     OR pg_has_role(session_user, 'ktm_curation_admin_executor', 'member') THEN
    RAISE EXCEPTION 'provider operation command requires provider executor'
      USING ERRCODE = '42501';
  END IF;
  IF p_dagster_run_id IS NULL OR btrim(p_dagster_run_id) = ''
     OR p_operation_key IS NULL OR btrim(p_operation_key) = ''
     OR p_trigger_kind NOT IN ('schedule','sensor','manual','retry','system')
     OR p_observed_status NOT IN (
       'QUEUED','NOT_STARTED','MANAGED','STARTING','STARTED','CANCELING'
     )
     OR jsonb_typeof(p_memberships) <> 'array'
     OR jsonb_array_length(p_memberships) = 0 THEN
    RAISE EXCEPTION 'invalid provider operation command input'
      USING ERRCODE = '22023';
  END IF;
  IF p_observed_status IN ('STARTED','CANCELING') AND p_started_at IS NULL THEN
    RAISE EXCEPTION 'running provider operation requires started_at'
      USING ERRCODE = '22023';
  END IF;
  SELECT count(*), count(DISTINCT (member.provider_dataset_id, member.sync_scope, member.operation_key))
  INTO STRICT v_member_count, v_distinct_member_count
  FROM jsonb_to_recordset(p_memberships) AS member(
    provider_dataset_id bigint, sync_scope text, operation_key text
  );
  IF v_member_count <> jsonb_array_length(p_memberships)
     OR v_distinct_member_count <> v_member_count THEN
    RAISE EXCEPTION 'provider operation memberships are not unique'
      USING ERRCODE = '22023';
  END IF;
  IF EXISTS (
    SELECT 1
    FROM jsonb_to_recordset(p_memberships) AS member(
      provider_dataset_id bigint, sync_scope text, operation_key text
    )
    WHERE member.operation_key <> p_operation_key
       OR member.sync_scope IS NULL OR btrim(member.sync_scope) = ''
       OR NOT EXISTS (
         SELECT 1
         FROM provider_sync.provider_dataset_operation_scopes AS scope
         JOIN provider_sync.provider_dataset_operations AS operation
           ON operation.provider_dataset_id = scope.provider_dataset_id
          AND operation.operation_key = scope.operation_key
          AND operation.operation_kind = scope.operation_kind
         JOIN provider_sync.provider_datasets AS dataset
           ON dataset.provider_dataset_id = scope.provider_dataset_id
         WHERE scope.provider_dataset_id = member.provider_dataset_id
           AND scope.sync_scope = member.sync_scope
           AND scope.operation_key = member.operation_key
           AND operation.operation_kind = 'refresh'
           AND operation.is_enabled AND dataset.is_active
       )
  ) THEN
    RAISE EXCEPTION 'provider operation membership is not active canonical scope'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_provider_operation_membership';
  END IF;

  v_base_status := CASE WHEN p_observed_status IN (
    'QUEUED','NOT_STARTED','MANAGED','STARTING'
  ) THEN 'queued' ELSE 'running' END;
  v_stage := CASE WHEN v_base_status = 'queued' THEN 'queued' ELSE 'loading' END;
  INSERT INTO ops.import_jobs (
    kind, payload, status, progress, current_stage, dagster_run_id,
    dataset_membership_mode, trigger_kind, operation_key, dagster_run_status,
    created_at, started_at, heartbeat_at
  ) VALUES (
    'provider_feature_load_run', '{}'::jsonb, v_base_status, 0, v_stage,
    p_dagster_run_id, 'root', p_trigger_kind, p_operation_key,
    p_observed_status, p_created_at,
    CASE WHEN v_base_status = 'running' THEN p_started_at ELSE NULL END,
    CASE WHEN v_base_status = 'running' THEN p_started_at ELSE NULL END
  )
  ON CONFLICT (dagster_run_id)
    WHERE kind = 'provider_feature_load_run' AND parent_job_id IS NULL
  DO NOTHING
  RETURNING job_id INTO o_root_job_id;
  o_inserted := FOUND;
  IF NOT o_inserted THEN
    SELECT root.job_id INTO o_root_job_id
    FROM ops.import_jobs AS root
    WHERE root.kind = 'provider_feature_load_run'
      AND root.parent_job_id IS NULL
      AND root.dagster_run_id = p_dagster_run_id
      AND root.quarantined_at IS NULL
    FOR UPDATE;
  END IF;
  IF o_root_job_id IS NULL THEN
    RAISE EXCEPTION 'provider operation root is quarantined or missing'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_provider_operation_root';
  END IF;
  IF o_inserted THEN
    FOR v_member IN
      SELECT member.*
      FROM jsonb_to_recordset(p_memberships) AS member(
        provider_dataset_id bigint, sync_scope text, operation_key text
      )
      ORDER BY member.provider_dataset_id, member.sync_scope, member.operation_key
    LOOP
      WITH child AS (
        INSERT INTO ops.import_jobs (
          kind, parent_job_id, payload, status, progress, current_stage,
          dagster_run_id, dataset_membership_mode, created_at, started_at, heartbeat_at
        ) VALUES (
          'provider_feature_load', o_root_job_id, '{}'::jsonb,
          v_base_status, 0, v_stage, p_dagster_run_id, 'single', p_created_at,
          CASE WHEN v_base_status = 'running' THEN p_started_at ELSE NULL END,
          CASE WHEN v_base_status = 'running' THEN p_started_at ELSE NULL END
        ) RETURNING job_id
      )
      INSERT INTO ops.import_job_datasets (
        job_id, provider_dataset_id, sync_scope, operation_key
      ) SELECT child.job_id, v_member.provider_dataset_id,
               v_member.sync_scope, v_member.operation_key FROM child;
    END LOOP;
  END IF;
  o_changed := o_inserted;
  IF p_observed_status IN ('STARTED','CANCELING') THEN
    UPDATE ops.import_jobs AS root
    SET status = 'running', current_stage = 'loading',
        dagster_run_status = p_observed_status,
        started_at = COALESCE(root.started_at, p_started_at),
        heartbeat_at = COALESCE(p_started_at, root.heartbeat_at)
    WHERE root.job_id = o_root_job_id AND root.kind = 'provider_feature_load_run'
      AND root.status = 'queued' AND root.cancellation_id IS NULL
      AND root.quarantined_at IS NULL;
    o_changed := o_changed OR FOUND;
    IF p_observed_status = 'CANCELING' THEN
      UPDATE ops.import_jobs AS root
      SET dagster_run_status = 'CANCELING',
          heartbeat_at = COALESCE(p_started_at, root.heartbeat_at)
      WHERE root.job_id = o_root_job_id
        AND root.kind = 'provider_feature_load_run'
        AND root.status = 'running'
        AND root.dagster_run_status = 'STARTED'
        AND root.cancellation_id IS NULL
        AND root.quarantined_at IS NULL;
      o_changed := o_changed OR FOUND;
    END IF;
    UPDATE ops.import_jobs AS child
    SET status = 'running', current_stage = 'loading',
        started_at = COALESCE(child.started_at, p_started_at),
        heartbeat_at = COALESCE(p_started_at, child.heartbeat_at)
    WHERE child.parent_job_id = o_root_job_id AND child.kind = 'provider_feature_load'
      AND child.status = 'queued' AND child.cancellation_id IS NULL
      AND child.quarantined_at IS NULL;
    o_changed := o_changed OR FOUND;
  ELSIF p_observed_status = 'STARTING' THEN
    UPDATE ops.import_jobs AS root SET dagster_run_status = 'STARTING'
    WHERE root.job_id = o_root_job_id AND root.kind = 'provider_feature_load_run'
      AND root.status = 'queued'
      AND root.dagster_run_status IN ('QUEUED','NOT_STARTED','MANAGED')
      AND root.quarantined_at IS NULL;
    o_changed := o_changed OR FOUND;
  END IF;
END
$command$;

CREATE PROCEDURE ops.finish_provider_feature_membership_command(
  IN p_root_job_id uuid,
  IN p_provider_dataset_id bigint,
  IN p_sync_scope text,
  IN p_operation_key text,
  IN p_authoritative_snapshot_complete boolean,
  IN p_finished_at timestamptz,
  OUT o_changed boolean
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, ops
AS $command$
DECLARE
  v_child_job_id uuid;
  v_has_receipt boolean;
BEGIN
  IF NOT pg_has_role(session_user, 'ktm_curation_provider_executor', 'member')
     OR pg_has_role(session_user, 'ktm_curation_admin_executor', 'member') THEN
    RAISE EXCEPTION 'provider membership command requires provider executor'
      USING ERRCODE = '42501';
  END IF;
  IF p_authoritative_snapshot_complete IS NULL THEN
    RAISE EXCEPTION 'provider membership completion kind is required'
      USING ERRCODE = '22023';
  END IF;
  SELECT child.job_id INTO STRICT v_child_job_id
  FROM ops.import_jobs AS child
  JOIN ops.import_job_datasets AS member ON member.job_id = child.job_id
  WHERE child.parent_job_id = p_root_job_id
    AND child.kind = 'provider_feature_load'
    AND member.provider_dataset_id = p_provider_dataset_id
    AND member.sync_scope = p_sync_scope
    AND member.operation_key = p_operation_key
    AND child.cancellation_id IS NULL AND child.quarantined_at IS NULL
  FOR UPDATE OF child;
  SELECT EXISTS (
    SELECT 1 FROM ops.curation_provider_snapshot_receipts AS receipt
    WHERE receipt.source_job_id = v_child_job_id
      AND receipt.root_job_id = p_root_job_id
      AND receipt.provider_dataset_id = p_provider_dataset_id
      AND receipt.sync_scope = p_sync_scope
      AND receipt.operation_key = p_operation_key
  ) INTO STRICT v_has_receipt;
  IF p_authoritative_snapshot_complete IS DISTINCT FROM v_has_receipt THEN
    RAISE EXCEPTION 'provider membership completion does not match its immutable seal'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_provider_membership_receipt';
  END IF;
  UPDATE ops.import_jobs AS child
  SET status = 'done', progress = 100, current_stage = 'completed',
      finished_at = COALESCE(child.finished_at, p_finished_at, clock_timestamp()),
      heartbeat_at = clock_timestamp(), error_message = NULL,
      payload = child.payload || jsonb_build_object(
        'authoritative_snapshot_complete', p_authoritative_snapshot_complete
      )
  WHERE child.job_id = v_child_job_id
    AND child.status IN ('queued','running')
    AND child.cancellation_id IS NULL AND child.quarantined_at IS NULL;
  o_changed := FOUND;
  WITH counts AS (
    SELECT count(*)::integer AS total,
           count(*) FILTER (WHERE status = 'done')::integer AS done
    FROM ops.import_jobs AS child
    WHERE child.parent_job_id = p_root_job_id
      AND child.kind = 'provider_feature_load' AND child.quarantined_at IS NULL
  )
  UPDATE ops.import_jobs AS root
  SET progress = CASE WHEN counts.total = 0 THEN 0
    ELSE floor(100.0 * counts.done / counts.total)::integer END
  FROM counts WHERE root.job_id = p_root_job_id AND root.quarantined_at IS NULL;
END
$command$;

CREATE PROCEDURE ops.append_provider_feature_attempt_event_command(
  IN p_dagster_run_id text,
  IN p_provider_dataset_id bigint,
  IN p_sync_scope text,
  IN p_operation_key text,
  IN p_attempt_number integer,
  IN p_outcome text,
  IN p_error jsonb,
  OUT o_event_id uuid,
  OUT o_job_id uuid,
  OUT o_import_job_dataset_id uuid,
  OUT o_stage text,
  OUT o_level text,
  OUT o_code text,
  OUT o_message text,
  OUT o_payload jsonb,
  OUT o_occurred_at timestamptz
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, ops
AS $command$
BEGIN
  IF NOT pg_has_role(session_user, 'ktm_curation_provider_executor', 'member')
     OR pg_has_role(session_user, 'ktm_curation_admin_executor', 'member') THEN
    RAISE EXCEPTION 'provider attempt event requires provider executor'
      USING ERRCODE = '42501';
  END IF;
  IF p_attempt_number < 1 OR p_outcome NOT IN ('failed','retryable_failure')
     OR jsonb_typeof(p_error) <> 'object' THEN
    RAISE EXCEPTION 'invalid provider attempt event input'
      USING ERRCODE = '22023';
  END IF;
  INSERT INTO ops.import_job_events (
    job_id, import_job_dataset_id, stage, level, code, message, payload
  )
  SELECT child.job_id, member.import_job_dataset_id, child.current_stage,
         'error', 'feature_operation.attempt',
         'provider feature operation attempt recorded',
         jsonb_build_object(
           'attempt_number', p_attempt_number,
           'outcome', p_outcome,
           'error', p_error,
           'provider_dataset_id', member.provider_dataset_id,
           'sync_scope', member.sync_scope,
           'operation_key', member.operation_key
         )
  FROM ops.import_jobs AS root
  JOIN ops.import_jobs AS child
    ON child.parent_job_id = root.job_id
   AND child.kind = 'provider_feature_load'
  JOIN ops.import_job_datasets AS member ON member.job_id = child.job_id
  WHERE root.kind = 'provider_feature_load_run'
    AND root.dagster_run_id = p_dagster_run_id
    AND root.quarantined_at IS NULL AND child.quarantined_at IS NULL
    AND member.provider_dataset_id = p_provider_dataset_id
    AND member.sync_scope = p_sync_scope
    AND member.operation_key = p_operation_key
  RETURNING event_id, job_id, import_job_dataset_id, stage, level, code,
            message, payload, occurred_at
  INTO STRICT o_event_id, o_job_id, o_import_job_dataset_id, o_stage, o_level,
              o_code, o_message, o_payload, o_occurred_at;
END
$command$;

CREATE PROCEDURE ops.transition_provider_feature_operation_terminal_command(
  IN p_root_job_id uuid,
  IN p_target_status text,
  IN p_dagster_terminal_status text,
  IN p_stage text,
  IN p_error_message text,
  IN p_started_at timestamptz,
  IN p_finished_at timestamptz,
  IN p_update_members boolean,
  OUT o_changed boolean
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, ops
AS $command$
BEGIN
  IF NOT pg_has_role(session_user, 'ktm_curation_provider_executor', 'member')
     OR pg_has_role(session_user, 'ktm_curation_admin_executor', 'member') THEN
    RAISE EXCEPTION 'provider terminal command requires provider executor'
      USING ERRCODE = '42501';
  END IF;
  IF p_target_status NOT IN ('done','failed','cancelled')
     OR p_dagster_terminal_status NOT IN ('SUCCESS','FAILURE','CANCELED')
     OR NOT (
       (p_target_status = 'done' AND p_dagster_terminal_status = 'SUCCESS'
        AND p_stage = 'completed')
       OR (p_target_status = 'failed' AND p_stage IN (
         'failed','tracking_invariant','stale_input'
       ))
       OR (p_target_status = 'cancelled' AND p_dagster_terminal_status = 'CANCELED'
        AND p_stage = 'cancelled')
     ) THEN
    RAISE EXCEPTION 'invalid provider terminal transition'
      USING ERRCODE = '22023';
  END IF;
  IF p_target_status = 'done' AND p_update_members THEN
    RAISE EXCEPTION 'successful provider root cannot complete unfinished members'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_provider_terminal_members';
  END IF;
  IF p_target_status = 'done' AND (
    EXISTS (
      SELECT 1 FROM ops.import_jobs AS child
      WHERE child.parent_job_id = p_root_job_id
        AND child.kind = 'provider_feature_load'
        AND child.quarantined_at IS NULL
        AND (
          child.status <> 'done'
          OR jsonb_typeof(child.payload -> 'authoritative_snapshot_complete')
             IS DISTINCT FROM 'boolean'
        )
    )
    OR EXISTS (
      SELECT 1
      FROM ops.import_jobs AS child
      JOIN ops.import_job_datasets AS member ON member.job_id = child.job_id
      WHERE child.parent_job_id = p_root_job_id
        AND child.kind = 'provider_feature_load'
        AND child.quarantined_at IS NULL
        AND (child.payload ->> 'authoritative_snapshot_complete')::boolean
        AND NOT EXISTS (
          SELECT 1 FROM ops.curation_provider_snapshot_receipts AS receipt
          WHERE receipt.source_job_id = child.job_id
            AND receipt.root_job_id = p_root_job_id
            AND receipt.provider_dataset_id = member.provider_dataset_id
            AND receipt.sync_scope = member.sync_scope
            AND receipt.operation_key = member.operation_key
        )
    )
    OR EXISTS (
      SELECT 1 FROM ops.curation_provider_snapshot_receipts AS receipt
      WHERE receipt.root_job_id = p_root_job_id
        AND NOT EXISTS (
          SELECT 1
          FROM ops.import_jobs AS child
          JOIN ops.import_job_datasets AS member ON member.job_id = child.job_id
          WHERE child.job_id = receipt.source_job_id
            AND child.parent_job_id = p_root_job_id
            AND child.kind = 'provider_feature_load'
            AND child.status = 'done'
            AND child.quarantined_at IS NULL
            AND (child.payload ->> 'authoritative_snapshot_complete')::boolean
            AND member.provider_dataset_id = receipt.provider_dataset_id
            AND member.sync_scope = receipt.sync_scope
            AND member.operation_key = receipt.operation_key
        )
    )
  ) THEN
    RAISE EXCEPTION 'successful provider root has incomplete or mismatched evidence'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_provider_terminal_receipts';
  END IF;
  UPDATE ops.import_jobs AS child
  SET started_at = COALESCE(child.started_at, p_started_at)
  WHERE child.parent_job_id = p_root_job_id
    AND child.kind = 'provider_feature_load'
    AND child.cancellation_id IS NULL AND child.quarantined_at IS NULL;
  IF p_update_members THEN
    UPDATE ops.import_jobs AS child
    SET status = p_target_status, current_stage = p_stage,
        error_message = COALESCE(p_error_message, child.error_message),
        finished_at = COALESCE(child.finished_at, p_finished_at),
        heartbeat_at = COALESCE(p_finished_at, child.heartbeat_at)
    WHERE child.parent_job_id = p_root_job_id
      AND child.kind = 'provider_feature_load'
      AND child.status IN ('queued','running')
      AND child.cancellation_id IS NULL AND child.quarantined_at IS NULL;
  END IF;
  WITH counts AS (
    SELECT count(*)::integer AS total,
           count(*) FILTER (WHERE status = 'done')::integer AS done
    FROM ops.import_jobs AS child
    WHERE child.parent_job_id = p_root_job_id
      AND child.kind = 'provider_feature_load' AND child.quarantined_at IS NULL
  )
  UPDATE ops.import_jobs AS root
  SET progress = CASE WHEN counts.total = 0 THEN 0
    ELSE floor(100.0 * counts.done / counts.total)::integer END
  FROM counts WHERE root.job_id = p_root_job_id AND root.quarantined_at IS NULL;
  UPDATE ops.import_jobs AS root
  SET status = p_target_status, dagster_run_status = p_dagster_terminal_status,
      current_stage = p_stage,
      error_message = COALESCE(p_error_message, root.error_message),
      progress = CASE WHEN p_target_status = 'done' THEN 100
                      WHEN p_stage = 'stale_input' THEN 0 ELSE root.progress END,
      started_at = COALESCE(root.started_at, p_started_at),
      finished_at = COALESCE(root.finished_at, p_finished_at),
      heartbeat_at = COALESCE(p_finished_at, root.heartbeat_at)
  WHERE root.job_id = p_root_job_id AND root.kind = 'provider_feature_load_run'
    AND root.cancellation_id IS NULL AND root.quarantined_at IS NULL
    AND (
      root.status IN ('queued','running')
      OR (root.status = 'done' AND p_target_status = 'failed'
          AND p_stage = 'stale_input')
    );
  o_changed := FOUND;
END
$command$;
"""


_ENSURE_SIGNATURE = (
    "ops.ensure_provider_feature_operation_command(text,text,text,jsonb,"
    "timestamptz,timestamptz,text)"
)
_FINISH_SIGNATURE = (
    "ops.finish_provider_feature_membership_command(uuid,bigint,text,text,boolean,timestamptz)"
)
_ATTEMPT_SIGNATURE = (
    "ops.append_provider_feature_attempt_event_command(text,bigint,text,text,integer,text,jsonb)"
)
_TERMINAL_SIGNATURE = (
    "ops.transition_provider_feature_operation_terminal_command(uuid,text,text,text,text,"
    "timestamptz,timestamptz,boolean)"
)


def upgrade() -> None:
    _execute_commands(_HELPERS_SQL)
    _execute_commands(_COMMANDS_SQL)
    op.execute("GRANT USAGE, CREATE ON SCHEMA ops TO ktm_curation_command_owner")
    for signature in (
        _ENSURE_SIGNATURE,
        _FINISH_SIGNATURE,
        _ATTEMPT_SIGNATURE,
        _TERMINAL_SIGNATURE,
    ):
        op.execute(f"ALTER PROCEDURE {signature} OWNER TO ktm_curation_command_owner")
    op.execute("REVOKE CREATE ON SCHEMA ops FROM ktm_curation_command_owner")
    op.execute(
        "GRANT SELECT, INSERT, UPDATE ON TABLE ops.import_jobs, ops.import_job_datasets, "
        "ops.import_job_events "
        "TO ktm_curation_command_owner"
    )
    op.execute(
        "GRANT SELECT ON TABLE ops.feature_update_requests "
        "TO ktm_curation_command_owner"
    )
    op.execute(
        "GRANT USAGE, SELECT ON SEQUENCE ops.import_jobs_queue_sequence_seq "
        "TO ktm_curation_command_owner"
    )
    op.execute("SET ROLE ktm_curation_command_owner")
    for signature in (
        _ENSURE_SIGNATURE,
        _FINISH_SIGNATURE,
        _ATTEMPT_SIGNATURE,
        _TERMINAL_SIGNATURE,
    ):
        op.execute(
            f"REVOKE ALL ON PROCEDURE {signature} FROM PUBLIC, ktm_feature_runtime, "
            "ktm_feature_api_runtime, ktm_feature_dagster_runtime, "
            "ktm_curation_admin_executor"
        )
        op.execute(
            f"GRANT EXECUTE ON PROCEDURE {signature} TO ktm_curation_provider_executor"
        )
    op.execute("SET ROLE ktm_feature_schema_owner")


def downgrade() -> None:
    raise RuntimeError("0114 is forward-only; rebuild with the T-VN-40 release head")
