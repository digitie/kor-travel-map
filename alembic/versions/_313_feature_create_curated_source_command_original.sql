CREATE OR REPLACE PROCEDURE feature.create_curated_source_command(IN p_provider_dataset_id bigint, IN p_source_name text, IN p_source_url text, IN p_source_kind text, IN p_license text, IN p_update_cycle text, IN p_freshness_note text, IN p_provider_status text, IN p_metadata jsonb, IN p_command_id bigint, IN p_principal text, OUT o_source_id uuid, OUT o_source_revision bigint, OUT o_observation_revision bigint)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'feature', 'provider_sync', 'ops'
    AS $$
DECLARE
  v_command ops.domain_commands%ROWTYPE;
BEGIN
  IF current_setting('transaction_isolation') <> 'serializable' THEN
    RAISE EXCEPTION 'source command requires SERIALIZABLE transaction' USING ERRCODE = '25001';
  END IF;
  IF NOT pg_has_role(session_user, 'ktm_curation_admin_executor', 'member')
     OR pg_has_role(session_user, 'ktm_curation_provider_executor', 'member') THEN
    RAISE EXCEPTION 'source command requires the admin executor' USING ERRCODE = '42501';
  END IF;
  IF p_provider_dataset_id IS NULL OR p_provider_dataset_id <= 0
     OR p_principal IS NULL OR p_principal <> btrim(p_principal) OR p_principal = ''
     OR p_source_name IS NULL OR p_source_name <> btrim(p_source_name) OR p_source_name = ''
     OR p_source_kind NOT IN ('openapi','filedata','standard','internal','manual')
     OR p_update_cycle NOT IN ('realtime','daily','weekly','monthly','annual','one_time','unknown')
     OR p_provider_status NOT IN ('implemented','provider_needed','manual_only','deprecated')
     OR jsonb_typeof(p_metadata) <> 'object' THEN
    RAISE EXCEPTION 'source command input is not canonical'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_source_command_input';
  END IF;
  SELECT command.* INTO STRICT v_command
  FROM ops.domain_commands AS command WHERE command.command_id = p_command_id;
  IF v_command.actor <> p_principal OR v_command.operation <> 'admin.curated-source.create' THEN
    RAISE EXCEPTION 'domain command does not match source create'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_source_domain_command';
  END IF;
  PERFORM pg_advisory_xact_lock(hashtextextended('curation-catalog-write', 0));
  INSERT INTO feature.curated_sources (
    provider_dataset_id, source_name, source_url, source_kind, license,
    update_cycle, freshness_note, provider_status, metadata,
    row_revision, observation_revision, updated_at
  ) VALUES (
    p_provider_dataset_id, p_source_name, p_source_url, p_source_kind, p_license,
    p_update_cycle, p_freshness_note, p_provider_status, p_metadata,
    1, 1, clock_timestamp()
  ) RETURNING source_id, row_revision, observation_revision
    INTO STRICT o_source_id, o_source_revision, o_observation_revision;
  PERFORM feature.claim_curation_catalog_command_effect(
    p_command_id, v_command.operation, 'source', o_source_id
  );
END
$$;
