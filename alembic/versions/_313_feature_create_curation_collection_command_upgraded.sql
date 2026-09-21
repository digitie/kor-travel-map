CREATE OR REPLACE PROCEDURE feature.create_curation_collection_command(IN p_collection_key text, IN p_theme_id uuid, IN p_source_id uuid, IN p_title text, IN p_edition_key text, IN p_description text, IN p_status text, IN p_visibility text, IN p_metadata jsonb, IN p_command_id bigint, IN p_principal text, OUT o_collection_id uuid, OUT o_collection_revision bigint)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'feature', 'ops', 'x_extension'
    AS $$
DECLARE
  v_command ops.domain_commands%ROWTYPE;
BEGIN
  IF current_setting('transaction_isolation') <> 'serializable' THEN
    RAISE EXCEPTION 'collection command requires SERIALIZABLE transaction'
      USING ERRCODE = '25001';
  END IF;
  IF NOT pg_has_role(session_user, 'ktm_curation_admin_executor', 'member') THEN
    RAISE EXCEPTION 'collection command requires the admin executor'
      USING ERRCODE = '42501';
  END IF;
  IF p_principal IS NULL OR p_principal <> btrim(p_principal) OR p_principal = ''
     OR p_collection_key IS NULL OR p_collection_key <> btrim(p_collection_key)
     OR p_collection_key = ''
     OR p_theme_id IS NULL
     OR p_title IS NULL OR p_title <> btrim(p_title) OR p_title = ''
     OR p_edition_key IS NULL OR p_edition_key <> btrim(p_edition_key)
     OR p_status NOT IN ('draft','published')
     OR p_visibility NOT IN ('admin_only','public')
     OR jsonb_typeof(p_metadata) <> 'object' THEN
    RAISE EXCEPTION 'collection command input is not canonical'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_collection_command_input';
  END IF;
  SELECT command.* INTO STRICT v_command
  FROM ops.domain_commands AS command WHERE command.command_id = p_command_id;
  IF v_command.actor <> p_principal
     OR v_command.operation <> 'admin.curation-collection.create' THEN
    RAISE EXCEPTION 'domain command does not match collection create'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_collection_domain_command';
  END IF;

  PERFORM pg_advisory_xact_lock(hashtextextended('kortravelmap:curation-import', 0));
  PERFORM pg_advisory_xact_lock(hashtextextended('curation-catalog-write', 0));
  PERFORM pg_advisory_xact_lock(hashtextextended('curation-collection:' || p_collection_key, 0));
  PERFORM 1 FROM feature.curated_themes AS theme
  WHERE theme.theme_id = p_theme_id AND theme.archived_at IS NULL FOR SHARE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'active curated theme does not exist'
      USING ERRCODE = '23503', CONSTRAINT = 'fk_tvn40_collection_active_theme';
  END IF;
  IF p_source_id IS NOT NULL THEN
    PERFORM 1 FROM feature.curated_sources AS source
    WHERE source.source_id = p_source_id AND source.archived_at IS NULL FOR SHARE;
    IF NOT FOUND THEN
      RAISE EXCEPTION 'active curated source does not exist'
        USING ERRCODE = '23503', CONSTRAINT = 'fk_tvn40_collection_active_source';
    END IF;
  END IF;

  o_collection_id := x_extension.gen_random_uuid();
  PERFORM feature.claim_curation_catalog_command_effect(
    p_command_id, v_command.operation, 'collection', o_collection_id
  );
  INSERT INTO feature.curation_collections (
    collection_id, collection_key, theme_id, source_id, title, edition_key,
    description, status, visibility, metadata, created_by, updated_by,
    row_revision, updated_at, archived_at
  ) VALUES (
    o_collection_id, p_collection_key, p_theme_id, p_source_id, p_title,
    p_edition_key, p_description, p_status, p_visibility, p_metadata,
    p_principal, p_principal, 1, clock_timestamp(), NULL
  ) RETURNING row_revision INTO STRICT o_collection_revision;
END
$$;
