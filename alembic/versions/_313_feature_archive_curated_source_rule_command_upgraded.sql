CREATE OR REPLACE PROCEDURE feature.archive_curated_source_rule_command(IN p_rule_id uuid, IN p_expected_rule_revision bigint, IN p_command_id bigint, IN p_reason_code text, IN p_principal text, OUT o_rule_id uuid, OUT o_rule_revision bigint, OUT o_generation_id uuid)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'feature', 'provider_sync', 'ops', 'x_extension'
    AS $$
DECLARE
  v_command ops.domain_commands%ROWTYPE;
  v_rule feature.curated_source_rules%ROWTYPE;
  v_provider_dataset_id bigint;
  v_prelock_count bigint;
  v_prelock_hash text;
  v_current_count bigint;
  v_current_hash text;
  v_before_input jsonb;
  v_after_input jsonb;
  v_before_hash text;
  v_after_hash text;
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
  IF NOT pg_has_role(session_user, 'ktm_curation_admin_executor', 'member') THEN
    RAISE EXCEPTION 'rule command requires the admin executor'
      USING ERRCODE = '42501';
  END IF;
  IF p_expected_rule_revision < 1 OR p_principal IS NULL
     OR p_principal <> btrim(p_principal) OR p_principal = ''
     OR p_reason_code IS NULL OR p_reason_code <> btrim(p_reason_code)
     OR p_reason_code = '' THEN
    RAISE EXCEPTION 'rule archive input is not canonical'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_rule_command_input';
  END IF;
  SELECT command.* INTO STRICT v_command
  FROM ops.domain_commands AS command WHERE command.command_id = p_command_id;
  IF v_command.actor <> p_principal
     OR v_command.operation <> 'admin.curated-source-rule.archive' THEN
    RAISE EXCEPTION 'domain command does not match rule archive'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_rule_domain_command';
  END IF;
  SELECT source.provider_dataset_id INTO STRICT v_provider_dataset_id
  FROM feature.curated_source_rules AS rule
  JOIN feature.curated_sources AS source ON source.source_id = rule.source_id
  WHERE rule.rule_id = p_rule_id;
  SELECT count(*), encode(x_extension.digest(convert_to(
    COALESCE(jsonb_agg(touched.feature_id ORDER BY touched.feature_id)::text, '[]'),
    'UTF8'), 'sha256'), 'hex')
  INTO STRICT v_prelock_count, v_prelock_hash
  FROM (
    SELECT candidate.feature_id FROM feature.theme_feature_candidates AS candidate
    WHERE candidate.rule_id = p_rule_id AND candidate.disposition = 'active'
    UNION
    SELECT link.feature_id FROM provider_sync.source_entities AS entity
    JOIN provider_sync.source_links AS link ON link.source_entity_key = entity.source_entity_key
    WHERE entity.provider_dataset_id = v_provider_dataset_id
  ) AS touched;
  PERFORM pg_advisory_xact_lock(hashtextextended('feature-write:' || touched.feature_id, 0))
  FROM (
    SELECT candidate.feature_id FROM feature.theme_feature_candidates AS candidate
    WHERE candidate.rule_id = p_rule_id AND candidate.disposition = 'active'
    UNION
    SELECT link.feature_id FROM provider_sync.source_entities AS entity
    JOIN provider_sync.source_links AS link ON link.source_entity_key = entity.source_entity_key
    WHERE entity.provider_dataset_id = v_provider_dataset_id
  ) AS touched ORDER BY touched.feature_id;
  PERFORM pg_advisory_xact_lock(hashtextextended('curation-catalog-write', 0));
  SELECT rule.* INTO STRICT v_rule FROM feature.curated_source_rules AS rule
  WHERE rule.rule_id = p_rule_id FOR UPDATE;
  SELECT count(*), encode(x_extension.digest(convert_to(
    COALESCE(jsonb_agg(touched.feature_id ORDER BY touched.feature_id)::text, '[]'),
    'UTF8'), 'sha256'), 'hex')
  INTO STRICT v_current_count, v_current_hash
  FROM (
    SELECT candidate.feature_id FROM feature.theme_feature_candidates AS candidate
    WHERE candidate.rule_id = p_rule_id AND candidate.disposition = 'active'
    UNION
    SELECT link.feature_id FROM provider_sync.source_entities AS entity
    JOIN provider_sync.source_links AS link ON link.source_entity_key = entity.source_entity_key
    WHERE entity.provider_dataset_id = v_provider_dataset_id
  ) AS touched;
  IF v_current_count <> v_prelock_count OR v_current_hash <> v_prelock_hash THEN
    RAISE EXCEPTION 'rule archive scope changed while acquiring the catalog lock'
      USING ERRCODE = '40001';
  END IF;
  IF v_rule.row_revision <> p_expected_rule_revision THEN
    RAISE EXCEPTION 'rule revision mismatch'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_expected_revision';
  END IF;
  IF v_rule.owner_kind IS DISTINCT FROM 'operator' THEN
    RAISE EXCEPTION 'provider-owned rule cannot be archived by an admin command'
      USING ERRCODE = '42501';
  END IF;
  IF v_rule.archived_at IS NOT NULL THEN
    RAISE EXCEPTION 'rule is already archived'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_rule_active';
  END IF;
  PERFORM feature.claim_curation_catalog_command_effect(
    p_command_id, v_command.operation, 'rule', v_rule.rule_id
  );
  v_before_input := feature.current_curation_rule_input(p_rule_id);
  v_before_hash := encode(
    x_extension.digest(convert_to(v_before_input::text, 'UTF8'), 'sha256'), 'hex'
  );
  UPDATE feature.curated_source_rules AS rule
  SET archived_at = clock_timestamp(), enabled = false,
      metadata = rule.metadata || jsonb_build_object('archive_reason', p_reason_code),
      row_revision = rule.row_revision + 1, updated_at = clock_timestamp()
  WHERE rule.rule_id = p_rule_id
  RETURNING rule.rule_id, rule.row_revision INTO STRICT o_rule_id, o_rule_revision;
  v_after_input := feature.current_curation_rule_input(p_rule_id);
  v_after_hash := encode(
    x_extension.digest(convert_to(v_after_input::text, 'UTF8'), 'sha256'), 'hex'
  );
  v_operation_id := feature.create_curation_rule_reconcile_receipt(
    p_rule_id, 'archive', v_rule.row_revision, o_rule_revision,
    v_before_hash, v_after_hash, p_command_id, p_principal
  );
  CALL feature.materialize_theme_candidate_generation(
    p_rule_id, 'rule_reconcile', NULL, v_operation_id, p_command_id, NULL,
    jsonb_build_object('schema_version', 1, 'catalog_action', 'archive'),
    o_generation_id, v_observed, v_removed, v_set_hash, v_replayed
  );
END
$$;
