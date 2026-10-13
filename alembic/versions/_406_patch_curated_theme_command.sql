-- 406 (ADR-111): feature.patch_curated_theme_command
-- head-schema.sql(405) 원문에서 Feature advisory fence와 그 주변만 바꾼 사본이다.
CREATE OR REPLACE PROCEDURE feature.patch_curated_theme_command(IN p_theme_id uuid, IN p_expected_theme_revision bigint, IN p_theme_slug text, IN p_theme_name text, IN p_theme_description text, IN p_theme_group text, IN p_visibility text, IN p_metadata jsonb, IN p_command_id bigint, IN p_principal text, OUT o_theme_id uuid, OUT o_theme_revision bigint, OUT o_generation_count bigint)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'feature', 'provider_sync', 'ops', 'x_extension'
    AS $$
DECLARE
  v_command ops.domain_commands%ROWTYPE;
  v_theme feature.curated_themes%ROWTYPE;
  v_rule_id uuid;
  v_feature_id text;
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
    RAISE EXCEPTION 'theme command requires SERIALIZABLE transaction'
      USING ERRCODE = '25001';
  END IF;
  IF NOT pg_has_role(session_user, 'ktm_curation_admin_executor', 'member') THEN
    RAISE EXCEPTION 'theme command requires the admin executor'
      USING ERRCODE = '42501';
  END IF;
  IF p_principal IS NULL OR p_principal <> btrim(p_principal) OR p_principal = ''
     OR p_theme_slug IS NULL OR p_theme_slug <> btrim(p_theme_slug) OR p_theme_slug = ''
     OR p_theme_name IS NULL OR p_theme_name <> btrim(p_theme_name) OR p_theme_name = ''
     OR p_theme_description IS NULL
     OR p_theme_group IS NULL OR p_theme_group <> btrim(p_theme_group) OR p_theme_group = ''
     OR p_visibility NOT IN ('admin_only','public')
     OR jsonb_typeof(p_metadata) <> 'object' THEN
    RAISE EXCEPTION 'theme command input is not canonical'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_theme_command_input';
  END IF;
  SELECT command.* INTO STRICT v_command
  FROM ops.domain_commands AS command WHERE command.command_id = p_command_id;
  IF v_command.actor <> p_principal
     OR v_command.operation <> 'admin.curated-theme.patch' THEN
    RAISE EXCEPTION 'domain command does not match theme patch'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_theme_domain_command';
  END IF;

  -- ADR-111: one exclusive gate instead of one lock per touched Feature.
  PERFORM pg_advisory_xact_lock(hashtextextended('feature-write-all', 0));
  PERFORM pg_advisory_xact_lock(hashtextextended('curation-catalog-write', 0));
  SELECT theme.* INTO STRICT v_theme
  FROM feature.curated_themes AS theme WHERE theme.theme_id = p_theme_id FOR UPDATE;
  IF v_theme.row_revision <> p_expected_theme_revision THEN
    RAISE EXCEPTION 'theme revision mismatch'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_expected_revision';
  END IF;
  IF v_theme.archived_at IS NOT NULL THEN
    RAISE EXCEPTION 'archived theme cannot be patched'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_theme_active';
  END IF;
  IF v_theme.owner_kind IS DISTINCT FROM 'operator' THEN
    RAISE EXCEPTION 'provider-owned theme cannot be patched by an admin command'
      USING ERRCODE = '42501';
  END IF;
  PERFORM feature.claim_curation_catalog_command_effect(
    p_command_id, v_command.operation, 'theme', v_theme.theme_id
  );
  PERFORM 1 FROM feature.curated_source_rules AS rule
  WHERE rule.theme_id = p_theme_id AND rule.archived_at IS NULL
  ORDER BY rule.rule_id FOR SHARE;
  IF v_theme.theme_slug = p_theme_slug AND v_theme.theme_name = p_theme_name
     AND v_theme.theme_description = p_theme_description
     AND v_theme.theme_group = p_theme_group AND v_theme.visibility = p_visibility
     AND v_theme.metadata = p_metadata THEN
    o_theme_id := v_theme.theme_id;
    o_theme_revision := v_theme.row_revision;
    o_generation_count := 0;
    RETURN;
  END IF;
  UPDATE feature.curated_themes AS theme
  SET theme_slug = p_theme_slug, theme_name = p_theme_name,
      theme_description = p_theme_description, theme_group = p_theme_group,
      visibility = p_visibility, metadata = p_metadata,
      row_revision = theme.row_revision + 1, updated_at = clock_timestamp()
  WHERE theme.theme_id = p_theme_id
  RETURNING theme.theme_id, theme.row_revision INTO STRICT o_theme_id, o_theme_revision;
  o_generation_count := 0;
END
$$
