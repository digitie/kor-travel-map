CREATE OR REPLACE PROCEDURE ops.ensure_provider_feature_operation_command(IN p_dagster_run_id text, IN p_trigger_kind text, IN p_operation_key text, IN p_memberships jsonb, IN p_created_at timestamp with time zone, IN p_started_at timestamp with time zone, IN p_observed_status text, OUT o_root_job_id uuid, OUT o_inserted boolean, OUT o_changed boolean)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'ops', 'provider_sync'
    AS $$
DECLARE
  v_member record;
  v_base_status text;
  v_stage text;
  v_member_count bigint;
  v_distinct_member_count bigint;
BEGIN
  IF NOT pg_has_role(session_user, 'ktm_curation_provider_executor', 'member') THEN
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
$$;
