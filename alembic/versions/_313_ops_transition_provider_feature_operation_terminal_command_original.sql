CREATE OR REPLACE PROCEDURE ops.transition_provider_feature_operation_terminal_command(IN p_root_job_id uuid, IN p_target_status text, IN p_dagster_terminal_status text, IN p_stage text, IN p_error_message text, IN p_started_at timestamp with time zone, IN p_finished_at timestamp with time zone, IN p_update_members boolean, OUT o_changed boolean)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'ops'
    AS $$
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
$$;
