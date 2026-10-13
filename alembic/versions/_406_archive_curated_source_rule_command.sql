-- 406 (ADR-111): feature.archive_curated_source_rule_command
-- head-schema.sql(405) 원문에서 Feature advisory fence와 그 주변만 바꾼 사본이다.
CREATE OR REPLACE PROCEDURE feature.archive_curated_source_rule_command(IN p_rule_id uuid, IN p_expected_rule_revision bigint, IN p_command_id bigint, IN p_reason_code text, IN p_principal text, OUT o_rule_id uuid, OUT o_rule_revision bigint, OUT o_generation_id uuid)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'feature', 'provider_sync', 'ops', 'x_extension'
    AS $$
DECLARE
  v_command ops.domain_commands%ROWTYPE;
  v_rule feature.curated_source_rules%ROWTYPE;
  v_provider_dataset_id bigint;
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
  -- ADR-111: one exclusive gate instead of one lock per touched Feature.
  PERFORM pg_advisory_xact_lock(hashtextextended('feature-write-all', 0));
  PERFORM pg_advisory_xact_lock(hashtextextended('curation-catalog-write', 0));
  SELECT rule.* INTO STRICT v_rule FROM feature.curated_source_rules AS rule
  WHERE rule.rule_id = p_rule_id FOR UPDATE;
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
$$
