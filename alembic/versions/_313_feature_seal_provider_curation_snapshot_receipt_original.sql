CREATE OR REPLACE PROCEDURE feature.seal_provider_curation_snapshot_receipt(IN p_root_job_id uuid, IN p_provider_dataset_id bigint, IN p_sync_scope text, IN p_operation_key text, IN p_expected_input_member_count bigint, IN p_expected_input_set_hash text, OUT o_source_job_id uuid, OUT o_observed_at timestamp with time zone, OUT o_source_entity_count bigint, OUT o_source_input_set_hash text)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'feature', 'provider_sync', 'ops', 'x_extension'
    AS $_$
DECLARE
  v_child ops.import_jobs%ROWTYPE;
  v_input_member_count bigint;
  v_last_source_modified_at date;
BEGIN
  IF current_setting('transaction_isolation') <> 'serializable' THEN
    RAISE EXCEPTION 'provider snapshot seal requires SERIALIZABLE transaction'
      USING ERRCODE = '25001';
  END IF;
  IF NOT pg_has_role(session_user, 'ktm_curation_provider_executor', 'member')
     OR pg_has_role(session_user, 'ktm_curation_admin_executor', 'member') THEN
    RAISE EXCEPTION 'provider snapshot seal requires the provider executor'
      USING ERRCODE = '42501';
  END IF;
  SELECT child.* INTO STRICT v_child
  FROM ops.import_jobs AS child
  JOIN ops.import_job_datasets AS member ON member.job_id = child.job_id
  WHERE child.parent_job_id = p_root_job_id
    AND child.kind = 'provider_feature_load'
    AND child.status IN ('queued','running')
    AND child.cancellation_id IS NULL AND child.quarantined_at IS NULL
    AND member.provider_dataset_id = p_provider_dataset_id
    AND member.sync_scope = p_sync_scope
    AND member.operation_key = p_operation_key
  FOR UPDATE OF child;
  IF NOT EXISTS (
    SELECT 1 FROM ops.import_jobs AS root
    WHERE root.job_id = p_root_job_id
      AND root.kind = 'provider_feature_load_run'
      AND root.status = 'running'
      AND root.dagster_run_status IN ('STARTED','CANCELING')
      AND root.dagster_run_id = v_child.dagster_run_id
      AND root.cancellation_id IS NULL AND root.quarantined_at IS NULL
  ) OR (SELECT count(*) FROM ops.import_job_datasets AS member
        WHERE member.job_id = v_child.job_id) <> 1 THEN
    RAISE EXCEPTION 'provider snapshot seal requires one exact running member'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_provider_snapshot_member';
  END IF;

  PERFORM 1 FROM provider_sync.source_entities AS entity
  WHERE entity.provider_dataset_id = p_provider_dataset_id
  ORDER BY entity.source_entity_key FOR SHARE;
  PERFORM 1
  FROM provider_sync.source_records AS record
  JOIN provider_sync.source_entity_heads AS head
    ON head.source_entity_key = record.source_entity_key
   AND head.current_source_record_key = record.source_record_key
  JOIN provider_sync.source_entities AS entity
    ON entity.source_entity_key = head.source_entity_key
  WHERE entity.provider_dataset_id = p_provider_dataset_id
  ORDER BY record.source_entity_key, record.source_record_key
  FOR SHARE OF record;
  PERFORM 1
  FROM provider_sync.source_entity_heads AS head
  JOIN provider_sync.source_entities AS entity
    ON entity.source_entity_key = head.source_entity_key
  WHERE entity.provider_dataset_id = p_provider_dataset_id
  ORDER BY head.source_entity_key FOR SHARE OF head;

  o_source_job_id := v_child.job_id;
  o_observed_at := clock_timestamp();
  SELECT input.source_entity_count, input.input_member_count,
         input.last_source_modified_at, input.source_input_set_hash
  INTO STRICT o_source_entity_count, v_input_member_count,
       v_last_source_modified_at, o_source_input_set_hash
  FROM feature.current_provider_curation_input_set(p_provider_dataset_id) AS input;
  IF p_expected_input_member_count IS NULL
     OR p_expected_input_set_hash !~ '^[0-9a-f]{64}$'
     OR p_expected_input_member_count <> v_input_member_count
     OR p_expected_input_set_hash <> o_source_input_set_hash THEN
    RAISE EXCEPTION 'provider load input changed before child completion'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_provider_snapshot_load_input';
  END IF;

  INSERT INTO ops.curation_provider_snapshot_receipts (
    source_job_id, root_job_id, provider_dataset_id, sync_scope, operation_key,
    observed_at, source_entity_count, input_member_count,
    last_source_modified_at, source_input_set_hash
  )
  SELECT v_child.job_id, p_root_job_id, p_provider_dataset_id, p_sync_scope,
         p_operation_key, o_observed_at, o_source_entity_count,
         v_input_member_count, v_last_source_modified_at,
         o_source_input_set_hash;
END
$_$;
