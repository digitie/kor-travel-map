CREATE OR REPLACE PROCEDURE feature.patch_curated_source_command(IN p_source_id uuid, IN p_expected_source_revision bigint, IN p_source_name text, IN p_source_url text, IN p_source_kind text, IN p_license text, IN p_update_cycle text, IN p_freshness_note text, IN p_provider_status text, IN p_metadata jsonb, IN p_command_id bigint, IN p_principal text, OUT o_source_id uuid, OUT o_source_revision bigint, OUT o_observation_revision bigint)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'feature', 'ops'
    AS $$
DECLARE
  v_command ops.domain_commands%ROWTYPE;
  v_source feature.curated_sources%ROWTYPE;
BEGIN
  IF current_setting('transaction_isolation') <> 'serializable' THEN
    RAISE EXCEPTION 'source command requires SERIALIZABLE transaction' USING ERRCODE = '25001';
  END IF;
  IF NOT pg_has_role(session_user, 'ktm_curation_admin_executor', 'member')
     OR pg_has_role(session_user, 'ktm_curation_provider_executor', 'member') THEN
    RAISE EXCEPTION 'source command requires the admin executor' USING ERRCODE = '42501';
  END IF;
  IF p_principal IS NULL OR p_principal <> btrim(p_principal) OR p_principal = ''
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
  IF v_command.actor <> p_principal OR v_command.operation <> 'admin.curated-source.patch' THEN
    RAISE EXCEPTION 'domain command does not match source patch'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_source_domain_command';
  END IF;
  PERFORM pg_advisory_xact_lock(hashtextextended('curation-catalog-write', 0));
  SELECT source.* INTO STRICT v_source FROM feature.curated_sources AS source
  WHERE source.source_id = p_source_id FOR UPDATE;
  IF v_source.row_revision <> p_expected_source_revision THEN
    RAISE EXCEPTION 'source revision mismatch'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_expected_revision';
  END IF;
  IF v_source.archived_at IS NOT NULL THEN
    RAISE EXCEPTION 'archived source cannot be patched'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_source_active';
  END IF;
  PERFORM feature.claim_curation_catalog_command_effect(
    p_command_id, v_command.operation, 'source', v_source.source_id
  );
  IF v_source.source_name = p_source_name
     AND v_source.source_url IS NOT DISTINCT FROM p_source_url
     AND v_source.source_kind = p_source_kind
     AND v_source.license IS NOT DISTINCT FROM p_license
     AND v_source.update_cycle = p_update_cycle
     AND v_source.freshness_note IS NOT DISTINCT FROM p_freshness_note
     AND v_source.provider_status = p_provider_status
     AND v_source.metadata = p_metadata THEN
    o_source_id := v_source.source_id;
    o_source_revision := v_source.row_revision;
    o_observation_revision := v_source.observation_revision;
    RETURN;
  END IF;
  UPDATE feature.curated_sources AS source
  SET source_name = p_source_name, source_url = p_source_url,
      source_kind = p_source_kind, license = p_license,
      update_cycle = p_update_cycle, freshness_note = p_freshness_note,
      provider_status = p_provider_status, metadata = p_metadata,
      row_revision = source.row_revision + 1, updated_at = clock_timestamp()
  WHERE source.source_id = p_source_id
  RETURNING source.source_id, source.row_revision, source.observation_revision
    INTO STRICT o_source_id, o_source_revision, o_observation_revision;
END
$$;
