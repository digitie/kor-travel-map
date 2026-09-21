CREATE OR REPLACE PROCEDURE feature.patch_curation_collection_command(IN p_collection_id uuid, IN p_expected_collection_revision bigint, IN p_theme_id uuid, IN p_source_id uuid, IN p_title text, IN p_edition_key text, IN p_description text, IN p_status text, IN p_visibility text, IN p_metadata jsonb, IN p_command_id bigint, IN p_principal text, OUT o_collection_id uuid, OUT o_collection_revision bigint)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'feature', 'ops'
    AS $$
DECLARE
  v_command ops.domain_commands%ROWTYPE;
  v_collection feature.curation_collections%ROWTYPE;
BEGIN
  IF current_setting('transaction_isolation') <> 'serializable' THEN
    RAISE EXCEPTION 'collection command requires SERIALIZABLE transaction'
      USING ERRCODE = '25001';
  END IF;
  IF NOT pg_has_role(session_user, 'ktm_curation_admin_executor', 'member')
     OR pg_has_role(session_user, 'ktm_curation_provider_executor', 'member') THEN
    RAISE EXCEPTION 'collection command requires the admin executor'
      USING ERRCODE = '42501';
  END IF;
  IF p_principal IS NULL OR p_principal <> btrim(p_principal) OR p_principal = ''
     OR p_collection_id IS NULL OR p_expected_collection_revision IS NULL
     OR p_expected_collection_revision < 1 OR p_theme_id IS NULL
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
     OR v_command.operation <> 'admin.curation-collection.patch' THEN
    RAISE EXCEPTION 'domain command does not match collection patch'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_collection_domain_command';
  END IF;

  PERFORM pg_advisory_xact_lock(hashtextextended('kortravelmap:curation-import', 0));
  PERFORM pg_advisory_xact_lock(hashtextextended('curation-catalog-write', 0));
  SELECT collection.* INTO STRICT v_collection
  FROM feature.curation_collections AS collection
  WHERE collection.collection_id = p_collection_id FOR UPDATE;
  IF v_collection.row_revision <> p_expected_collection_revision THEN
    RAISE EXCEPTION 'collection revision mismatch'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_collection_expected_revision';
  END IF;
  IF v_collection.archived_at IS NOT NULL THEN
    RAISE EXCEPTION 'archived collection cannot be patched'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_collection_active';
  END IF;
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
  PERFORM feature.claim_curation_catalog_command_effect(
    p_command_id, v_command.operation, 'collection', p_collection_id
  );

  o_collection_id := v_collection.collection_id;
  IF (v_collection.theme_id, v_collection.source_id, v_collection.title,
      v_collection.edition_key, v_collection.description, v_collection.status,
      v_collection.visibility, v_collection.metadata)
     IS NOT DISTINCT FROM
     (p_theme_id, p_source_id, p_title, p_edition_key, p_description, p_status,
      p_visibility, p_metadata) THEN
    o_collection_revision := v_collection.row_revision;
    RETURN;
  END IF;
  UPDATE feature.curation_collections AS collection
  SET theme_id = p_theme_id, source_id = p_source_id, title = p_title,
      edition_key = p_edition_key, description = p_description, status = p_status,
      visibility = p_visibility, metadata = p_metadata, updated_by = p_principal,
      row_revision = collection.row_revision + 1, updated_at = clock_timestamp()
  WHERE collection.collection_id = p_collection_id
  RETURNING collection.collection_id, collection.row_revision
  INTO STRICT o_collection_id, o_collection_revision;
END
$$;
