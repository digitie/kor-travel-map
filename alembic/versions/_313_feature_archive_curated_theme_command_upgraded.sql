CREATE OR REPLACE PROCEDURE feature.archive_curated_theme_command(IN p_theme_id uuid, IN p_expected_theme_revision bigint, IN p_command_id bigint, IN p_reason_code text, IN p_principal text, OUT o_theme_id uuid, OUT o_theme_revision bigint, OUT o_generation_count bigint)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'feature', 'provider_sync', 'ops', 'x_extension'
    AS $$
DECLARE
  v_command ops.domain_commands%ROWTYPE;
  v_theme feature.curated_themes%ROWTYPE;
  v_rule_id uuid;
  v_rule_revision bigint;
  v_feature_id text;
  v_prelock_count bigint;
  v_prelock_hash text;
  v_current_count bigint;
  v_current_hash text;
  v_before_hashes jsonb := '{}'::jsonb;
  v_before_hash text;
  v_after_input jsonb;
  v_after_hash text;
  v_operation_id uuid;
  v_generation_id uuid;
  v_observed bigint;
  v_removed bigint;
  v_set_hash text;
  v_replayed boolean;
BEGIN
  IF current_setting('transaction_isolation') <> 'serializable' THEN
    RAISE EXCEPTION 'theme command requires SERIALIZABLE transaction' USING ERRCODE = '25001';
  END IF;
  IF NOT pg_has_role(session_user, 'ktm_curation_admin_executor', 'member') THEN
    RAISE EXCEPTION 'theme command requires the admin executor' USING ERRCODE = '42501';
  END IF;
  IF p_principal IS NULL OR p_principal <> btrim(p_principal) OR p_principal = ''
     OR p_reason_code IS NULL OR p_reason_code <> btrim(p_reason_code) OR p_reason_code = '' THEN
    RAISE EXCEPTION 'theme archive input is not canonical'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_theme_archive_input';
  END IF;
  SELECT command.* INTO STRICT v_command
  FROM ops.domain_commands AS command WHERE command.command_id = p_command_id;
  IF v_command.actor <> p_principal
     OR v_command.operation <> 'admin.curated-theme.archive' THEN
    RAISE EXCEPTION 'domain command does not match theme archive'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_theme_domain_command';
  END IF;
  SELECT count(*), encode(x_extension.digest(convert_to(
    COALESCE(jsonb_agg(touched.feature_id ORDER BY touched.feature_id)::text, '[]'),
    'UTF8'), 'sha256'), 'hex')
  INTO STRICT v_prelock_count, v_prelock_hash
  FROM (
    SELECT candidate.feature_id
    FROM feature.curated_source_rules AS rule
    JOIN feature.theme_feature_candidates AS candidate ON candidate.rule_id = rule.rule_id
    WHERE rule.theme_id = p_theme_id AND rule.archived_at IS NULL
      AND candidate.disposition = 'active'
    UNION
    SELECT link.feature_id
    FROM feature.curated_source_rules AS rule
    JOIN feature.curated_sources AS source ON source.source_id = rule.source_id
    JOIN provider_sync.source_entities AS entity
      ON entity.provider_dataset_id = source.provider_dataset_id
    JOIN provider_sync.source_links AS link ON link.source_entity_key = entity.source_entity_key
    WHERE rule.theme_id = p_theme_id AND rule.archived_at IS NULL
  ) AS touched;
  FOR v_feature_id IN
    SELECT touched.feature_id FROM (
      SELECT candidate.feature_id
      FROM feature.curated_source_rules AS rule
      JOIN feature.theme_feature_candidates AS candidate ON candidate.rule_id = rule.rule_id
      WHERE rule.theme_id = p_theme_id AND rule.archived_at IS NULL
        AND candidate.disposition = 'active'
      UNION
      SELECT link.feature_id
      FROM feature.curated_source_rules AS rule
      JOIN feature.curated_sources AS source ON source.source_id = rule.source_id
      JOIN provider_sync.source_entities AS entity
        ON entity.provider_dataset_id = source.provider_dataset_id
      JOIN provider_sync.source_links AS link ON link.source_entity_key = entity.source_entity_key
      WHERE rule.theme_id = p_theme_id AND rule.archived_at IS NULL
    ) AS touched ORDER BY touched.feature_id
  LOOP
    PERFORM pg_advisory_xact_lock(hashtextextended('feature-write:' || v_feature_id, 0));
  END LOOP;
  PERFORM pg_advisory_xact_lock(hashtextextended('curation-catalog-write', 0));
  SELECT theme.* INTO STRICT v_theme
  FROM feature.curated_themes AS theme WHERE theme.theme_id = p_theme_id FOR UPDATE;
  IF v_theme.row_revision <> p_expected_theme_revision THEN
    RAISE EXCEPTION 'theme revision mismatch'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_expected_revision';
  END IF;
  IF v_theme.owner_kind IS DISTINCT FROM 'operator' THEN
    RAISE EXCEPTION 'provider-owned theme cannot be archived by an admin command'
      USING ERRCODE = '42501';
  END IF;
  IF v_theme.archived_at IS NOT NULL THEN
    RAISE EXCEPTION 'theme is already archived'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_theme_active';
  END IF;
  PERFORM feature.claim_curation_catalog_command_effect(
    p_command_id, v_command.operation, 'theme', v_theme.theme_id
  );
  PERFORM 1 FROM feature.curated_source_rules AS rule
  WHERE rule.theme_id = p_theme_id AND rule.archived_at IS NULL
  ORDER BY rule.rule_id FOR SHARE;
  SELECT count(*), encode(x_extension.digest(convert_to(
    COALESCE(jsonb_agg(touched.feature_id ORDER BY touched.feature_id)::text, '[]'),
    'UTF8'), 'sha256'), 'hex')
  INTO STRICT v_current_count, v_current_hash
  FROM (
    SELECT candidate.feature_id
    FROM feature.curated_source_rules AS rule
    JOIN feature.theme_feature_candidates AS candidate ON candidate.rule_id = rule.rule_id
    WHERE rule.theme_id = p_theme_id AND rule.archived_at IS NULL
      AND candidate.disposition = 'active'
    UNION
    SELECT link.feature_id
    FROM feature.curated_source_rules AS rule
    JOIN feature.curated_sources AS source ON source.source_id = rule.source_id
    JOIN provider_sync.source_entities AS entity
      ON entity.provider_dataset_id = source.provider_dataset_id
    JOIN provider_sync.source_links AS link ON link.source_entity_key = entity.source_entity_key
    WHERE rule.theme_id = p_theme_id AND rule.archived_at IS NULL
  ) AS touched;
  IF v_current_count <> v_prelock_count OR v_current_hash <> v_prelock_hash THEN
    RAISE EXCEPTION 'theme archive scope changed while acquiring the catalog lock'
      USING ERRCODE = '40001';
  END IF;
  FOR v_rule_id IN
    SELECT rule.rule_id FROM feature.curated_source_rules AS rule
    WHERE rule.theme_id = p_theme_id AND rule.archived_at IS NULL ORDER BY rule.rule_id
  LOOP
    v_before_hashes := v_before_hashes || jsonb_build_object(
      v_rule_id::text,
      encode(x_extension.digest(convert_to(
        feature.current_curation_rule_input(v_rule_id)::text, 'UTF8'
      ), 'sha256'), 'hex')
    );
  END LOOP;
  UPDATE feature.curated_themes AS theme
  SET archived_at = clock_timestamp(), row_revision = theme.row_revision + 1,
      updated_at = clock_timestamp()
  WHERE theme.theme_id = p_theme_id
  RETURNING theme.theme_id, theme.row_revision INTO STRICT o_theme_id, o_theme_revision;
  o_generation_count := 0;
  FOR v_rule_id IN
    SELECT rule.rule_id FROM feature.curated_source_rules AS rule
    WHERE rule.theme_id = p_theme_id AND rule.archived_at IS NULL ORDER BY rule.rule_id
  LOOP
    SELECT rule.row_revision INTO STRICT v_rule_revision
    FROM feature.curated_source_rules AS rule WHERE rule.rule_id = v_rule_id;
    v_before_hash := v_before_hashes ->> v_rule_id::text;
    v_after_input := feature.current_curation_rule_input(v_rule_id);
    v_after_hash := encode(x_extension.digest(convert_to(v_after_input::text, 'UTF8'), 'sha256'), 'hex');
    v_operation_id := feature.create_curation_rule_reconcile_receipt(
      v_rule_id, 'archive',
      v_rule_revision, v_rule_revision,
      v_before_hash, v_after_hash, p_command_id, p_principal
    );
    CALL feature.materialize_theme_candidate_generation(
      v_rule_id, 'rule_reconcile', NULL, v_operation_id, p_command_id, NULL,
      jsonb_build_object('schema_version', 1, 'catalog_action', 'theme_archive',
        'theme_id', p_theme_id::text, 'reason_code', p_reason_code),
      v_generation_id, v_observed, v_removed, v_set_hash, v_replayed
    );
    o_generation_count := o_generation_count + 1;
  END LOOP;
END
$$;
