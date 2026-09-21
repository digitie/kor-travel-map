CREATE PROCEDURE feature.finalize_provider_curation_root(IN p_root_job_id uuid, OUT o_generation_count bigint, OUT o_generation_set_hash text, OUT o_replayed boolean, OUT o_stale_input boolean)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'feature', 'provider_sync', 'ops', 'x_extension'
    AS $$
DECLARE
  v_root ops.import_jobs%ROWTYPE;
  v_seal ops.curation_provider_root_receipts%ROWTYPE;
  v_child record;
  v_rule record;
  v_generation_id uuid;
  v_observed bigint;
  v_removed bigint;
  v_input_hash text;
  v_generation_replayed boolean;
  v_source_id uuid;
  v_source_revision bigint;
  v_observation_revision bigint;
  v_row_count integer;
  v_current_count bigint;
  v_current_member_count bigint;
  v_current_hash text;
  v_child_count bigint;
  v_child_hash text;
BEGIN
  o_stale_input := false;
  IF current_setting('transaction_isolation') <> 'serializable' THEN
    RAISE EXCEPTION 'provider curation root requires SERIALIZABLE transaction'
      USING ERRCODE = '25001';
  END IF;
  IF (
       NOT pg_has_role(session_user, 'ktm_curation_provider_executor', 'member')
       OR pg_has_role(session_user, 'ktm_curation_admin_executor', 'member')
     ) AND NOT (
       session_user = 'ktm_feature_service'
       AND current_setting('ktm.curation_cancellation_root', true)
         = p_root_job_id::text
     ) THEN
    RAISE EXCEPTION 'provider curation root requires the provider executor'
      USING ERRCODE = '42501';
  END IF;
  -- Provider load/retirement/notice/merge와 같은 global fence를 relation
  -- lock보다 먼저 잡아 head→link와 Feature→link 경로의 ABBA를 제거한다.
  PERFORM pg_advisory_xact_lock(hashtextextended('feature-curation-write', 0));
  SELECT root.* INTO STRICT v_root FROM ops.import_jobs AS root
  WHERE root.job_id = p_root_job_id FOR UPDATE;
  IF v_root.kind <> 'provider_feature_load_run' OR v_root.status <> 'done'
     OR v_root.dagster_run_status <> 'SUCCESS'
     OR (
       v_root.cancellation_id IS NOT NULL
       AND NOT EXISTS (
         SELECT 1
         FROM ops.pipeline_cancellation_members AS member
         JOIN ops.pipeline_cancellation_runs AS run
           ON run.cancellation_id = member.cancellation_id
          AND run.dagster_run_id = member.dagster_run_id
         WHERE member.cancellation_id = v_root.cancellation_id
           AND member.job_id = v_root.job_id
           AND member.operation_kind = 'provider_feature_load_run'
           AND member.result = 'already_terminal'
           AND member.terminal_status = 'done'
           AND run.result = 'already_terminal'
           AND run.terminal_status = 'SUCCESS'
       )
     ) OR v_root.quarantined_at IS NOT NULL THEN
    RAISE EXCEPTION 'provider curation root requires a successful terminal root'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_provider_curation_root';
  END IF;

  SELECT count(*)::bigint,
         encode(x_extension.digest(convert_to(COALESCE(jsonb_agg(jsonb_build_array(
           receipt.source_job_id::text, receipt.provider_dataset_id,
           receipt.sync_scope, receipt.operation_key, receipt.input_member_count,
           receipt.source_input_set_hash
         ) ORDER BY receipt.provider_dataset_id, receipt.sync_scope, receipt.operation_key)::text, '[]'),
         'UTF8'), 'sha256'), 'hex')
  INTO STRICT v_child_count, v_child_hash
  FROM ops.curation_provider_snapshot_receipts AS receipt
  WHERE receipt.root_job_id = p_root_job_id;

  IF EXISTS (
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
  ) OR EXISTS (
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
  ) THEN
    RAISE EXCEPTION 'provider curation root child receipt set is inconsistent'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_provider_curation_child_set';
  END IF;
  IF v_child_count = 0 THEN
    o_generation_count := 0;
    o_generation_set_hash := encode(
      x_extension.digest(convert_to('[]', 'UTF8'), 'sha256'), 'hex'
    );
    o_replayed := false;
    RETURN;
  END IF;

  SELECT root_receipt.* INTO v_seal FROM ops.curation_provider_root_receipts AS root_receipt
  WHERE root_receipt.root_job_id = p_root_job_id;
  IF FOUND THEN
    SELECT count(*)::bigint,
           encode(x_extension.digest(convert_to(COALESCE(jsonb_agg(jsonb_build_array(
             generation.rule_id::text, generation.generation_id::text,
             generation.generation_input_set_hash
           ) ORDER BY generation.rule_id, generation.source_job_id)::text, '[]'),
           'UTF8'), 'sha256'), 'hex')
    INTO STRICT o_generation_count, o_generation_set_hash
    FROM feature.theme_candidate_generations AS generation
    JOIN ops.curation_provider_snapshot_receipts AS receipt
      ON receipt.source_job_id = generation.source_job_id
    WHERE receipt.root_job_id = p_root_job_id
      AND generation.generation_kind = 'provider_full_snapshot';
    IF v_seal.child_receipt_count <> v_child_count
       OR v_seal.child_receipt_set_hash <> v_child_hash
       OR v_seal.generation_count <> o_generation_count
       OR v_seal.generation_set_hash <> o_generation_set_hash THEN
      RAISE EXCEPTION 'provider curation root replay receipt is inconsistent'
        USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_provider_curation_root_replay';
    END IF;
    o_replayed := true;
    RETURN;
  END IF;

  PERFORM pg_advisory_xact_lock(hashtextextended('feature-write:' || touched.feature_id, 0))
  FROM (
    SELECT link.feature_id
    FROM ops.curation_provider_snapshot_receipts AS receipt
    JOIN provider_sync.source_entities AS entity
      ON entity.provider_dataset_id = receipt.provider_dataset_id
    JOIN provider_sync.source_links AS link ON link.source_entity_key = entity.source_entity_key
    WHERE receipt.root_job_id = p_root_job_id
    UNION
    SELECT candidate.feature_id
    FROM ops.curation_provider_snapshot_receipts AS receipt
    JOIN feature.curated_sources AS source
      ON source.provider_dataset_id = receipt.provider_dataset_id
    JOIN feature.curated_source_rules AS rule ON rule.source_id = source.source_id
    JOIN feature.theme_feature_candidates AS candidate ON candidate.rule_id = rule.rule_id
    WHERE receipt.root_job_id = p_root_job_id AND candidate.disposition = 'active'
  ) AS touched ORDER BY touched.feature_id;
  PERFORM 1
  FROM provider_sync.source_links AS link
  JOIN provider_sync.source_entities AS entity
    ON entity.source_entity_key = link.source_entity_key
  JOIN ops.curation_provider_snapshot_receipts AS receipt
    ON receipt.provider_dataset_id = entity.provider_dataset_id
  WHERE receipt.root_job_id = p_root_job_id
  ORDER BY link.source_entity_key, link.feature_id
  FOR SHARE OF link;
  PERFORM pg_advisory_xact_lock(hashtextextended('curation-catalog-write', 0));

  -- Validate every immutable child seal before the first catalog/candidate DML.
  FOR v_child IN
    SELECT receipt.* FROM ops.curation_provider_snapshot_receipts AS receipt
    WHERE receipt.root_job_id = p_root_job_id
    ORDER BY receipt.provider_dataset_id, receipt.sync_scope, receipt.operation_key
  LOOP
    SELECT input.source_entity_count, input.input_member_count,
           input.source_input_set_hash
    INTO STRICT v_current_count, v_current_member_count, v_current_hash
    FROM feature.current_provider_curation_input_set(
      v_child.provider_dataset_id
    ) AS input;
    IF v_current_count <> v_child.source_entity_count
       OR v_current_member_count <> v_child.input_member_count
       OR v_current_hash <> v_child.source_input_set_hash THEN
      o_generation_count := 0;
      o_generation_set_hash := encode(
        x_extension.digest(convert_to('[]', 'UTF8'), 'sha256'), 'hex'
      );
      o_replayed := false;
      o_stale_input := true;
      RETURN;
    END IF;
  END LOOP;

  FOR v_child IN
    SELECT receipt.* FROM ops.curation_provider_snapshot_receipts AS receipt
    WHERE receipt.root_job_id = p_root_job_id
    ORDER BY receipt.provider_dataset_id, receipt.sync_scope, receipt.operation_key
  LOOP
    IF EXISTS (SELECT 1 FROM feature.curated_sources AS source
               WHERE source.provider_dataset_id = v_child.provider_dataset_id
                 AND source.archived_at IS NULL) THEN
      CALL feature.refresh_curated_source_observation(
        v_child.provider_dataset_id, v_child.source_job_id,
        v_source_id, v_source_revision, v_observation_revision, v_row_count
      );
    END IF;
    FOR v_rule IN
      SELECT rule.rule_id FROM feature.curated_source_rules AS rule
      JOIN feature.curated_sources AS source ON source.source_id = rule.source_id
      JOIN feature.curated_themes AS theme ON theme.theme_id = rule.theme_id
      WHERE source.provider_dataset_id = v_child.provider_dataset_id
        AND source.archived_at IS NULL AND theme.archived_at IS NULL
        AND rule.archived_at IS NULL AND rule.enabled
        AND rule.default_action = 'candidate'
      ORDER BY rule.rule_id
    LOOP
      CALL feature.materialize_theme_candidate_generation(
        v_rule.rule_id, 'provider_full_snapshot', v_child.source_job_id,
        NULL, NULL, NULL,
        jsonb_build_object('schema_version', 1, 'sync_scope', v_child.sync_scope,
                           'operation_key', v_child.operation_key),
        v_generation_id, v_observed, v_removed, v_input_hash, v_generation_replayed
      );
    END LOOP;
  END LOOP;

  SELECT count(*)::bigint,
         encode(x_extension.digest(convert_to(COALESCE(jsonb_agg(jsonb_build_array(
           generation.rule_id::text, generation.generation_id::text,
           generation.generation_input_set_hash
         ) ORDER BY generation.rule_id, generation.source_job_id)::text, '[]'),
         'UTF8'), 'sha256'), 'hex')
  INTO STRICT o_generation_count, o_generation_set_hash
  FROM feature.theme_candidate_generations AS generation
  JOIN ops.curation_provider_snapshot_receipts AS receipt
    ON receipt.source_job_id = generation.source_job_id
  WHERE receipt.root_job_id = p_root_job_id
    AND generation.generation_kind = 'provider_full_snapshot';
  INSERT INTO ops.curation_provider_root_receipts (
    root_job_id, child_receipt_count, child_receipt_set_hash,
    generation_count, generation_set_hash
  ) VALUES (p_root_job_id, v_child_count, v_child_hash,
            o_generation_count, o_generation_set_hash);
  o_replayed := false;
END
$$;
