CREATE OR REPLACE PROCEDURE feature.create_curated_theme_command(IN p_theme_slug text, IN p_theme_name text, IN p_theme_description text, IN p_theme_group text, IN p_visibility text, IN p_metadata jsonb, IN p_command_id bigint, IN p_principal text, OUT o_theme_id uuid, OUT o_theme_revision bigint)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'feature', 'ops', 'x_extension'
    AS $$
DECLARE
  v_command ops.domain_commands%ROWTYPE;
BEGIN
  IF current_setting('transaction_isolation') <> 'serializable' THEN
    RAISE EXCEPTION 'theme command requires SERIALIZABLE transaction'
      USING ERRCODE = '25001';
  END IF;
  IF NOT pg_has_role(session_user, 'ktm_curation_admin_executor', 'member')
     OR pg_has_role(session_user, 'ktm_curation_provider_executor', 'member') THEN
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
     OR v_command.operation <> 'admin.curated-theme.create' THEN
    RAISE EXCEPTION 'domain command does not match theme create'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_theme_domain_command';
  END IF;
  PERFORM pg_advisory_xact_lock(hashtextextended('curation-catalog-write', 0));
  INSERT INTO feature.curated_themes (
    theme_slug, theme_name, theme_description, theme_group, default_curated,
    visibility, metadata, row_revision, owner_kind, owner_provider_dataset_id,
    updated_at
  ) VALUES (
    p_theme_slug, p_theme_name, p_theme_description, p_theme_group, false,
    p_visibility, p_metadata, 1, 'operator', NULL, clock_timestamp()
  ) RETURNING theme_id, row_revision INTO STRICT o_theme_id, o_theme_revision;
  PERFORM feature.claim_curation_catalog_command_effect(
    p_command_id, v_command.operation, 'theme', o_theme_id
  );
END
$$;
