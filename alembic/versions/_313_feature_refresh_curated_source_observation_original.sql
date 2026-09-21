CREATE PROCEDURE feature.refresh_curated_source_observation(IN p_provider_dataset_id bigint, IN p_import_job_id uuid, OUT o_source_id uuid, OUT o_source_revision bigint, OUT o_observation_revision bigint, OUT o_row_count integer)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'feature', 'provider_sync', 'ops'
    AS $$
DECLARE
  v_source feature.curated_sources%ROWTYPE;
  v_snapshot ops.curation_provider_snapshot_receipts%ROWTYPE;
  v_receipt ops.curation_source_observation_receipts%ROWTYPE;
  v_latest_receipt ops.curation_source_observation_receipts%ROWTYPE;
BEGIN
  IF current_setting('transaction_isolation') <> 'serializable' THEN
    RAISE EXCEPTION 'source observation requires SERIALIZABLE transaction' USING ERRCODE = '25001';
  END IF;
  IF (
       NOT pg_has_role(session_user, 'ktm_curation_provider_executor', 'member')
       OR pg_has_role(session_user, 'ktm_curation_admin_executor', 'member')
     ) AND NOT (
       session_user = 'ktm_feature_api_runtime'
       AND current_setting('ktm.curation_cancellation_root', true) IS NOT NULL
     ) THEN
    RAISE EXCEPTION 'source observation requires the provider executor' USING ERRCODE = '42501';
  END IF;
  SELECT snapshot.* INTO STRICT v_snapshot
  FROM ops.curation_provider_snapshot_receipts AS snapshot
  WHERE snapshot.source_job_id = p_import_job_id
    AND snapshot.provider_dataset_id = p_provider_dataset_id;
  IF NOT EXISTS (
    SELECT 1 FROM ops.import_jobs AS child
    JOIN ops.import_jobs AS root ON root.job_id = child.parent_job_id
    WHERE child.job_id = p_import_job_id AND child.status = 'done'
      AND root.job_id = v_snapshot.root_job_id AND root.status = 'done'
      AND root.dagster_run_status = 'SUCCESS'
      AND child.quarantined_at IS NULL AND root.quarantined_at IS NULL
      AND (
        (child.cancellation_id IS NULL AND root.cancellation_id IS NULL)
        OR (
          session_user = 'ktm_feature_api_runtime'
          AND root.job_id::text = current_setting(
            'ktm.curation_cancellation_root', true
          )
          AND child.cancellation_id = root.cancellation_id
          AND EXISTS (
            SELECT 1
            FROM ops.pipeline_cancellation_members AS member
            JOIN ops.pipeline_cancellation_runs AS run
              ON run.cancellation_id = member.cancellation_id
             AND run.dagster_run_id = member.dagster_run_id
            WHERE member.cancellation_id = root.cancellation_id
              AND member.job_id = root.job_id
              AND member.result = 'already_terminal'
              AND member.terminal_status = 'done'
              AND run.result = 'already_terminal'
              AND run.terminal_status = 'SUCCESS'
          )
        )
      )
  ) THEN
    RAISE EXCEPTION 'source observation requires a sealed terminal root member'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_source_observation_job';
  END IF;
  SELECT source.* INTO STRICT v_source FROM feature.curated_sources AS source
  WHERE source.provider_dataset_id = p_provider_dataset_id FOR UPDATE;
  SELECT receipt.* INTO v_receipt
  FROM ops.curation_source_observation_receipts AS receipt
  WHERE receipt.source_id = v_source.source_id AND receipt.import_job_id = p_import_job_id;
  IF FOUND THEN
    o_source_id := v_receipt.source_id;
    o_source_revision := v_receipt.source_revision;
    o_observation_revision := v_receipt.observation_revision;
    o_row_count := v_receipt.row_count;
    RETURN;
  END IF;
  IF v_source.archived_at IS NOT NULL THEN
    RAISE EXCEPTION 'archived source cannot receive new observations'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_source_active';
  END IF;
  SELECT receipt.* INTO v_latest_receipt
  FROM ops.curation_source_observation_receipts AS receipt
  WHERE receipt.source_id = v_source.source_id
  ORDER BY receipt.observed_at DESC, receipt.import_job_id DESC LIMIT 1;
  IF FOUND AND (v_snapshot.observed_at, p_import_job_id)
       <= (v_latest_receipt.observed_at, v_latest_receipt.import_job_id) THEN
    RAISE EXCEPTION 'source observation job is older than the current receipt'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_source_observation_order';
  END IF;
  IF v_snapshot.source_entity_count > 2147483647 THEN
    RAISE EXCEPTION 'source observation row count exceeds the catalog range'
      USING ERRCODE = '22003';
  END IF;
  o_row_count := v_snapshot.source_entity_count::integer;
  UPDATE feature.curated_sources AS source
  SET last_checked_at = v_snapshot.observed_at, row_count = o_row_count,
      last_source_modified_at = v_snapshot.last_source_modified_at,
      next_expected_at = CASE source.update_cycle
        WHEN 'realtime' THEN v_snapshot.observed_at::date
        WHEN 'daily' THEN v_snapshot.observed_at::date + 1
        WHEN 'weekly' THEN v_snapshot.observed_at::date + 7
        WHEN 'monthly' THEN (v_snapshot.observed_at + interval '1 month')::date
        WHEN 'annual' THEN (v_snapshot.observed_at + interval '1 year')::date
        ELSE NULL END,
      observation_revision = source.observation_revision + 1,
      updated_at = clock_timestamp()
  WHERE source.source_id = v_source.source_id
  RETURNING source.source_id, source.row_revision, source.observation_revision
    INTO STRICT o_source_id, o_source_revision, o_observation_revision;
  INSERT INTO ops.curation_source_observation_receipts (
    source_id, import_job_id, observed_at, source_revision,
    observation_revision, row_count, last_source_modified_at, source_input_set_hash
  ) VALUES (
    o_source_id, p_import_job_id, v_snapshot.observed_at, o_source_revision,
    o_observation_revision, o_row_count, v_snapshot.last_source_modified_at,
    v_snapshot.source_input_set_hash
  );
END
$$;
