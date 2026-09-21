CREATE OR REPLACE PROCEDURE ops.append_provider_feature_attempt_event_command(IN p_dagster_run_id text, IN p_provider_dataset_id bigint, IN p_sync_scope text, IN p_operation_key text, IN p_attempt_number integer, IN p_outcome text, IN p_error jsonb, OUT o_event_id uuid, OUT o_job_id uuid, OUT o_import_job_dataset_id uuid, OUT o_stage text, OUT o_level text, OUT o_code text, OUT o_message text, OUT o_payload jsonb, OUT o_occurred_at timestamp with time zone)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'ops'
    AS $$
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
$$;
