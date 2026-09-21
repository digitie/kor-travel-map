CREATE OR REPLACE PROCEDURE ops.finish_provider_feature_membership_command(IN p_root_job_id uuid, IN p_provider_dataset_id bigint, IN p_sync_scope text, IN p_operation_key text, IN p_authoritative_snapshot_complete boolean, IN p_finished_at timestamp with time zone, OUT o_changed boolean)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'ops'
    AS $$
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
$$;
