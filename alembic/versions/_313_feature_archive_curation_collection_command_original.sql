CREATE OR REPLACE PROCEDURE feature.archive_curation_collection_command(IN p_collection_id uuid, IN p_expected_collection_revision bigint, IN p_command_id bigint, IN p_principal text, OUT o_collection_id uuid, OUT o_collection_revision bigint)
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
     OR p_expected_collection_revision < 1 THEN
    RAISE EXCEPTION 'collection archive input is not canonical'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_collection_command_input';
  END IF;
  SELECT command.* INTO STRICT v_command
  FROM ops.domain_commands AS command WHERE command.command_id = p_command_id;
  IF v_command.actor <> p_principal
     OR v_command.operation <> 'admin.curation-collection.archive' THEN
    RAISE EXCEPTION 'domain command does not match collection archive'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_collection_domain_command';
  END IF;

  PERFORM pg_advisory_xact_lock(hashtextextended('kortravelmap:curation-import', 0));
  SELECT collection.* INTO STRICT v_collection
  FROM feature.curation_collections AS collection
  WHERE collection.collection_id = p_collection_id FOR UPDATE;
  IF v_collection.row_revision <> p_expected_collection_revision THEN
    RAISE EXCEPTION 'collection revision mismatch'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_collection_expected_revision';
  END IF;
  PERFORM feature.claim_curation_catalog_command_effect(
    p_command_id, v_command.operation, 'collection', p_collection_id
  );
  o_collection_id := v_collection.collection_id;
  IF v_collection.archived_at IS NOT NULL THEN
    o_collection_revision := v_collection.row_revision;
    RETURN;
  END IF;
  UPDATE feature.curation_collections AS collection
  SET status = 'archived', archived_at = clock_timestamp(),
      updated_by = p_principal, row_revision = collection.row_revision + 1,
      updated_at = clock_timestamp()
  WHERE collection.collection_id = p_collection_id
  RETURNING collection.collection_id, collection.row_revision
  INTO STRICT o_collection_id, o_collection_revision;
END
$$;
