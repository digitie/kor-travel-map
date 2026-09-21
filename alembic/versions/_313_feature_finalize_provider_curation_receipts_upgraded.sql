CREATE OR REPLACE PROCEDURE feature.finalize_provider_curation_receipts(IN p_provider_dataset_id bigint, IN p_import_job_id uuid, IN p_sync_scope text, IN p_operation_key text, OUT o_generation_count bigint, OUT o_generation_set_hash text, OUT o_replayed boolean)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'feature', 'provider_sync', 'ops', 'x_extension'
    AS $_$
DECLARE
  v_job ops.import_jobs%ROWTYPE;
  v_rule record;
  v_generation_id uuid;
  v_observed_candidate_count bigint;
  v_removed_candidate_count bigint;
  v_generation_input_set_hash text;
  v_generation_replayed boolean;
  v_source_id uuid;
  v_source_revision bigint;
  v_observation_revision bigint;
  v_row_count integer;
BEGIN
  IF current_setting('transaction_isolation') <> 'serializable' THEN
    RAISE EXCEPTION 'provider curation finalization requires SERIALIZABLE transaction'
      USING ERRCODE = '25001';
  END IF;
  IF NOT pg_has_role(session_user, 'ktm_curation_provider_executor', 'member') THEN
    RAISE EXCEPTION 'provider curation finalization requires the provider executor'
      USING ERRCODE = '42501';
  END IF;

  SELECT job.* INTO STRICT v_job
  FROM ops.import_jobs AS job
  WHERE job.job_id = p_import_job_id
  FOR UPDATE;
  IF v_job.kind <> 'provider_feature_load'
     OR v_job.status <> 'done'
     OR v_job.finished_at IS NULL
     OR v_job.parent_job_id IS NULL
     OR v_job.cancellation_id IS NOT NULL
     OR v_job.quarantined_at IS NOT NULL
     OR COALESCE(
       (v_job.payload ->> 'authoritative_snapshot_complete')::boolean,
       false
     ) IS NOT TRUE
     OR NOT EXISTS (
       SELECT 1
       FROM ops.import_jobs AS root
       WHERE root.job_id = v_job.parent_job_id
         AND root.kind = 'provider_feature_load_run'
         AND root.status = 'done'
         AND root.dagster_run_status = 'SUCCESS'
         AND root.dagster_run_id = v_job.dagster_run_id
         AND root.cancellation_id IS NULL
         AND root.quarantined_at IS NULL
     )
     OR (SELECT count(*) FROM ops.import_job_datasets AS member
         WHERE member.job_id = p_import_job_id) <> 1
     OR NOT EXISTS (
       SELECT 1
       FROM ops.import_job_datasets AS member
       WHERE member.job_id = p_import_job_id
         AND member.provider_dataset_id = p_provider_dataset_id
         AND member.sync_scope = p_sync_scope
         AND member.operation_key = p_operation_key
     ) THEN
    RAISE EXCEPTION 'provider curation finalization requires a done exact member'
      USING ERRCODE = '23514',
            CONSTRAINT = 'ck_tvn40_provider_curation_finalization_job';
  END IF;

  IF v_job.payload ? 'candidate_generation_sealed_at' THEN
    o_generation_count := (v_job.payload ->> 'candidate_generation_count')::bigint;
    o_generation_set_hash := v_job.payload ->> 'candidate_generation_set_hash';
    IF o_generation_count IS NULL
       OR COALESCE(o_generation_set_hash, '') !~ '^[0-9a-f]{64}$' THEN
      RAISE EXCEPTION 'sealed provider curation receipt is malformed'
        USING ERRCODE = '23514',
              CONSTRAINT = 'ck_tvn40_provider_curation_finalization_seal';
    END IF;
    o_replayed := true;
    RETURN;
  END IF;

  WITH observation AS (
    SELECT
      count(head.source_entity_key)::integer AS row_count,
      max(record.imported_at)::date AS last_source_modified_at,
      encode(
        x_extension.digest(
          convert_to(
            COALESCE(
              jsonb_agg(
                jsonb_build_array(
                  entity.source_entity_key,
                  head.current_source_record_key,
                  record.raw_payload_hash
                ) ORDER BY entity.source_entity_key
              ) FILTER (WHERE head.source_entity_key IS NOT NULL),
              '[]'::jsonb
            )::text,
            'UTF8'
          ),
          'sha256'
        ),
        'hex'
      ) AS input_set_hash
    FROM provider_sync.source_entities AS entity
    LEFT JOIN provider_sync.source_entity_heads AS head
      ON head.source_entity_key = entity.source_entity_key
    LEFT JOIN provider_sync.source_records AS record
      ON record.source_entity_key = head.source_entity_key
     AND record.source_record_key = head.current_source_record_key
    WHERE entity.provider_dataset_id = p_provider_dataset_id
  )
  UPDATE ops.import_jobs AS job
  SET payload = job.payload || jsonb_build_object(
    'source_observation', jsonb_build_object(
      'schema_version', 1,
      'row_count', observation.row_count,
      'last_source_modified_at', observation.last_source_modified_at,
      'input_set_hash', observation.input_set_hash
    )
  )
  FROM observation
  WHERE job.job_id = p_import_job_id;

  IF EXISTS (
    SELECT 1
    FROM feature.curated_sources AS source
    WHERE source.provider_dataset_id = p_provider_dataset_id
      AND source.archived_at IS NULL
  ) THEN
    CALL feature.refresh_curated_source_observation(
      p_provider_dataset_id,
      p_import_job_id,
      v_source_id,
      v_source_revision,
      v_observation_revision,
      v_row_count
    );
  END IF;

  PERFORM pg_advisory_xact_lock(
    hashtextextended('feature-write:' || touched.feature_id, 0)
  )
  FROM (
    SELECT link.feature_id
    FROM provider_sync.source_entities AS entity
    JOIN provider_sync.source_links AS link
      ON link.source_entity_key = entity.source_entity_key
    WHERE entity.provider_dataset_id = p_provider_dataset_id
    UNION
    SELECT candidate.feature_id
    FROM feature.curated_source_rules AS rule
    JOIN feature.curated_sources AS source ON source.source_id = rule.source_id
    JOIN feature.theme_feature_candidates AS candidate
      ON candidate.rule_id = rule.rule_id
     AND candidate.disposition = 'active'
    WHERE source.provider_dataset_id = p_provider_dataset_id
  ) AS touched
  ORDER BY touched.feature_id;

  FOR v_rule IN
    SELECT rule.rule_id
    FROM feature.curated_source_rules AS rule
    JOIN feature.curated_sources AS source ON source.source_id = rule.source_id
    JOIN feature.curated_themes AS theme ON theme.theme_id = rule.theme_id
    WHERE source.provider_dataset_id = p_provider_dataset_id
      AND source.archived_at IS NULL
      AND theme.archived_at IS NULL
      AND rule.archived_at IS NULL
      AND rule.enabled
      AND rule.default_action = 'candidate'
    ORDER BY rule.rule_id
  LOOP
    CALL feature.materialize_theme_candidate_generation(
      v_rule.rule_id,
      'provider_full_snapshot',
      p_import_job_id,
      NULL,
      NULL,
      NULL,
      jsonb_build_object(
        'schema_version', 1,
        'sync_scope', p_sync_scope,
        'operation_key', p_operation_key
      ),
      v_generation_id,
      v_observed_candidate_count,
      v_removed_candidate_count,
      v_generation_input_set_hash,
      v_generation_replayed
    );
  END LOOP;

  SELECT
    count(*)::bigint,
    encode(
      x_extension.digest(
        convert_to(
          COALESCE(
            jsonb_agg(
              jsonb_build_array(
                generation.rule_id::text,
                generation.generation_id::text,
                generation.generation_input_set_hash
              ) ORDER BY generation.rule_id
            )::text,
            '[]'
          ),
          'UTF8'
        ),
        'sha256'
      ),
      'hex'
    )
  INTO STRICT o_generation_count, o_generation_set_hash
  FROM feature.theme_candidate_generations AS generation
  WHERE generation.source_job_id = p_import_job_id
    AND generation.generation_kind = 'provider_full_snapshot';

  UPDATE ops.import_jobs AS job
  SET payload = job.payload || jsonb_build_object(
    'candidate_generation_count', o_generation_count,
    'candidate_generation_set_hash', o_generation_set_hash,
    'candidate_generation_sealed_at', clock_timestamp()
  )
  WHERE job.job_id = p_import_job_id;
  o_replayed := false;
END
$_$;
