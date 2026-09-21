CREATE OR REPLACE PROCEDURE feature.create_curated_source_rule_command(IN p_theme_id uuid, IN p_source_id uuid, IN p_place_kind text, IN p_category text, IN p_region_scope jsonb, IN p_detail_selector jsonb, IN p_default_action text, IN p_priority integer, IN p_enabled boolean, IN p_metadata jsonb, IN p_command_id bigint, IN p_principal text, OUT o_rule_id uuid, OUT o_rule_revision bigint, OUT o_generation_id uuid)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'feature', 'provider_sync', 'ops', 'x_extension'
    AS $$
DECLARE
  v_command ops.domain_commands%ROWTYPE;
  v_provider_dataset_id bigint;
  v_prelock_count bigint;
  v_prelock_hash text;
  v_current_count bigint;
  v_current_hash text;
  v_rule_input jsonb;
  v_rule_input_hash text;
  v_operation_id uuid;
  v_observed bigint;
  v_removed bigint;
  v_set_hash text;
  v_replayed boolean;
BEGIN
  IF current_setting('transaction_isolation') <> 'serializable' THEN
    RAISE EXCEPTION 'rule command requires SERIALIZABLE transaction'
      USING ERRCODE = '25001';
  END IF;
  IF NOT pg_has_role(session_user, 'ktm_curation_admin_executor', 'member')
     OR pg_has_role(session_user, 'ktm_curation_provider_executor', 'member') THEN
    RAISE EXCEPTION 'rule command requires the admin executor'
      USING ERRCODE = '42501';
  END IF;
  IF p_principal IS NULL OR p_principal <> btrim(p_principal) OR p_principal = ''
     OR p_default_action NOT IN ('candidate','ignore')
     OR jsonb_typeof(p_region_scope) <> 'object'
     OR (p_detail_selector IS NOT NULL AND jsonb_typeof(p_detail_selector) <> 'object')
     OR jsonb_typeof(p_metadata) <> 'object' THEN
    RAISE EXCEPTION 'rule command input is not canonical'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_rule_command_input';
  END IF;
  SELECT command.* INTO STRICT v_command
  FROM ops.domain_commands AS command WHERE command.command_id = p_command_id;
  IF v_command.actor <> p_principal
     OR v_command.operation <> 'admin.curated-source-rule.create' THEN
    RAISE EXCEPTION 'domain command does not match rule create'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_rule_domain_command';
  END IF;

  SELECT source.provider_dataset_id INTO STRICT v_provider_dataset_id
  FROM feature.curated_sources AS source WHERE source.source_id = p_source_id;
  SELECT count(*), encode(x_extension.digest(convert_to(
    COALESCE(jsonb_agg(link.feature_id ORDER BY link.feature_id)::text, '[]'),
    'UTF8'), 'sha256'), 'hex')
  INTO STRICT v_prelock_count, v_prelock_hash
  FROM provider_sync.source_entities AS entity
  JOIN provider_sync.source_links AS link ON link.source_entity_key = entity.source_entity_key
  WHERE entity.provider_dataset_id = v_provider_dataset_id;
  PERFORM pg_advisory_xact_lock(hashtextextended('feature-write:' || link.feature_id, 0))
  FROM provider_sync.source_entities AS entity
  JOIN provider_sync.source_links AS link ON link.source_entity_key = entity.source_entity_key
  WHERE entity.provider_dataset_id = v_provider_dataset_id
  ORDER BY link.feature_id;
  PERFORM pg_advisory_xact_lock(hashtextextended('curation-catalog-write', 0));

  PERFORM 1 FROM feature.curated_themes AS theme
  WHERE theme.theme_id = p_theme_id AND theme.archived_at IS NULL FOR SHARE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'theme is missing or archived'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_rule_theme_active';
  END IF;
  PERFORM 1 FROM feature.curated_sources AS source
  WHERE source.source_id = p_source_id
    AND source.provider_dataset_id = v_provider_dataset_id
    AND source.archived_at IS NULL FOR SHARE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'source is missing, moved, or archived'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_rule_source_active';
  END IF;
  SELECT count(*), encode(x_extension.digest(convert_to(
    COALESCE(jsonb_agg(link.feature_id ORDER BY link.feature_id)::text, '[]'),
    'UTF8'), 'sha256'), 'hex')
  INTO STRICT v_current_count, v_current_hash
  FROM provider_sync.source_entities AS entity
  JOIN provider_sync.source_links AS link ON link.source_entity_key = entity.source_entity_key
  WHERE entity.provider_dataset_id = v_provider_dataset_id;
  IF v_current_count <> v_prelock_count OR v_current_hash <> v_prelock_hash THEN
    RAISE EXCEPTION 'rule create scope changed while acquiring the catalog lock'
      USING ERRCODE = '40001';
  END IF;

  INSERT INTO feature.curated_source_rules (
    theme_id, source_id, place_kind, category, region_scope, detail_selector,
    default_action, priority, enabled, metadata, row_revision, owner_kind,
    owner_provider_dataset_id, updated_at
  ) VALUES (
    p_theme_id, p_source_id, p_place_kind, p_category, p_region_scope,
    p_detail_selector, p_default_action, p_priority, p_enabled, p_metadata,
    1, 'operator', NULL, clock_timestamp()
  ) RETURNING rule_id, row_revision INTO STRICT o_rule_id, o_rule_revision;
  PERFORM feature.claim_curation_catalog_command_effect(
    p_command_id, v_command.operation, 'rule', o_rule_id
  );
  v_rule_input := feature.current_curation_rule_input(o_rule_id);
  v_rule_input_hash := encode(
    x_extension.digest(convert_to(v_rule_input::text, 'UTF8'), 'sha256'), 'hex'
  );
  v_operation_id := feature.create_curation_rule_reconcile_receipt(
    o_rule_id, 'create', NULL, o_rule_revision, NULL, v_rule_input_hash,
    p_command_id, p_principal
  );
  CALL feature.materialize_theme_candidate_generation(
    o_rule_id, 'rule_reconcile', NULL, v_operation_id, p_command_id, NULL,
    jsonb_build_object('schema_version', 1, 'catalog_action', 'create'),
    o_generation_id, v_observed, v_removed, v_set_hash, v_replayed
  );
END
$$;
