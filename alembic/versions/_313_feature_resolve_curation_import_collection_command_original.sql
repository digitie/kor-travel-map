CREATE OR REPLACE PROCEDURE feature.resolve_curation_import_collection_command(IN p_collection_key text, IN p_theme_id uuid, IN p_source_id uuid, IN p_title text, IN p_edition_key text, IN p_command_id bigint, IN p_principal text, OUT o_collection_id uuid, OUT o_collection_revision bigint, OUT o_created boolean)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'feature', 'ops', 'x_extension'
    AS $$
DECLARE
  v_command ops.domain_commands%ROWTYPE;
  v_collection feature.curation_collections%ROWTYPE;
BEGIN
  IF current_setting('transaction_isolation') <> 'serializable' THEN
    RAISE EXCEPTION 'curation import command requires SERIALIZABLE transaction'
      USING ERRCODE = '25001';
  END IF;
  IF NOT pg_has_role(session_user, 'ktm_curation_admin_executor', 'member')
     OR pg_has_role(session_user, 'ktm_curation_provider_executor', 'member') THEN
    RAISE EXCEPTION 'curation import command requires the admin executor'
      USING ERRCODE = '42501';
  END IF;
  IF p_principal IS NULL OR p_principal <> btrim(p_principal) OR p_principal = ''
     OR p_collection_key IS NULL OR p_collection_key <> btrim(p_collection_key)
     OR p_collection_key = '' OR p_theme_id IS NULL
     OR p_title IS NULL OR p_title <> btrim(p_title) OR p_title = ''
     OR p_edition_key IS NULL OR p_edition_key <> btrim(p_edition_key) THEN
    RAISE EXCEPTION 'curation import collection input is not canonical'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_import_collection_input';
  END IF;
  SELECT command.* INTO STRICT v_command
  FROM ops.domain_commands AS command WHERE command.command_id = p_command_id
  FOR UPDATE;
  IF v_command.actor <> p_principal
     OR v_command.operation <> 'admin.curation.import'
     OR EXISTS (
       SELECT 1 FROM ops.domain_command_results AS result
       WHERE result.command_id = p_command_id
     ) THEN
    RAISE EXCEPTION 'domain command does not match active curation import'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_import_domain_command';
  END IF;

  PERFORM pg_advisory_xact_lock(hashtextextended('kortravelmap:curation-import', 0));
  PERFORM pg_advisory_xact_lock(hashtextextended('curation-catalog-write', 0));
  PERFORM pg_advisory_xact_lock(hashtextextended('curation-collection:' || p_collection_key, 0));
  PERFORM 1 FROM feature.curated_themes AS theme
  WHERE theme.theme_id = p_theme_id AND theme.archived_at IS NULL FOR SHARE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'active curated theme does not exist'
      USING ERRCODE = '23503', CONSTRAINT = 'fk_tvn40_import_active_theme';
  END IF;
  IF p_source_id IS NOT NULL THEN
    PERFORM 1 FROM feature.curated_sources AS source
    WHERE source.source_id = p_source_id AND source.archived_at IS NULL FOR SHARE;
    IF NOT FOUND THEN
      RAISE EXCEPTION 'active curated source does not exist'
        USING ERRCODE = '23503', CONSTRAINT = 'fk_tvn40_import_active_source';
    END IF;
  END IF;

  SELECT collection.* INTO v_collection
  FROM feature.curation_collections AS collection
  WHERE collection.collection_key = p_collection_key FOR UPDATE;
  IF FOUND THEN
    IF (v_collection.theme_id, v_collection.source_id, v_collection.title,
        v_collection.edition_key, v_collection.status, v_collection.visibility,
        v_collection.archived_at IS NULL)
       IS DISTINCT FROM
       (p_theme_id, p_source_id, p_title, p_edition_key,
        'published'::text, 'public'::text, true) THEN
      RAISE EXCEPTION 'existing collection differs from immutable import catalog input'
        USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_import_collection_cas';
    END IF;
    o_collection_id := v_collection.collection_id;
    o_collection_revision := v_collection.row_revision;
    o_created := false;
  ELSE
    o_collection_id := x_extension.gen_random_uuid();
    INSERT INTO feature.curation_collections (
      collection_id, collection_key, theme_id, source_id, title, edition_key,
      description, status, visibility, metadata, created_by, updated_by,
      row_revision, updated_at, archived_at
    ) VALUES (
      o_collection_id, p_collection_key, p_theme_id, p_source_id, p_title,
      p_edition_key, NULL, 'published', 'public', '{}'::jsonb,
      p_principal, p_principal, 1, clock_timestamp(), NULL
    ) RETURNING row_revision INTO STRICT o_collection_revision;
    o_created := true;
  END IF;
  INSERT INTO ops.curation_import_collection_effects (
    command_id, collection_id, operation, created
  ) VALUES (p_command_id, o_collection_id, v_command.operation, o_created);
END
$$;
