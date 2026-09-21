CREATE OR REPLACE PROCEDURE feature.archive_curation_item_command(IN p_collection_id uuid, IN p_curation_item_id uuid, IN p_expected_item_revision bigint, IN p_command_id bigint, IN p_principal text, OUT o_curation_item_id uuid, OUT o_item_revision bigint, OUT o_collection_revision bigint)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'feature', 'ops'
    AS $$
DECLARE
  v_command ops.domain_commands%ROWTYPE;
  v_collection feature.curation_collections%ROWTYPE;
  v_hint feature.curation_items%ROWTYPE;
  v_item feature.curation_items%ROWTYPE;
BEGIN
  IF current_setting('transaction_isolation') <> 'serializable' THEN
    RAISE EXCEPTION 'item command requires SERIALIZABLE transaction'
      USING ERRCODE = '25001';
  END IF;
  IF NOT pg_has_role(session_user, 'ktm_curation_admin_executor', 'member')
     OR pg_has_role(session_user, 'ktm_curation_provider_executor', 'member') THEN
    RAISE EXCEPTION 'item command requires the admin executor'
      USING ERRCODE = '42501';
  END IF;
  IF p_principal IS NULL OR p_principal <> btrim(p_principal) OR p_principal = ''
     OR p_collection_id IS NULL OR p_curation_item_id IS NULL
     OR p_expected_item_revision IS NULL OR p_expected_item_revision < 1 THEN
    RAISE EXCEPTION 'item archive input is not canonical'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_item_command_input';
  END IF;
  SELECT command.* INTO STRICT v_command
  FROM ops.domain_commands AS command WHERE command.command_id = p_command_id;
  IF v_command.actor <> p_principal
     OR v_command.operation <> 'admin.curation-item.archive' THEN
    RAISE EXCEPTION 'domain command does not match item archive'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_item_domain_command';
  END IF;

  SELECT item.* INTO STRICT v_hint FROM feature.curation_items AS item
  WHERE item.collection_id = p_collection_id
    AND item.curation_item_id = p_curation_item_id;
  PERFORM pg_advisory_xact_lock(hashtextextended('kortravelmap:curation-import', 0));
  PERFORM pg_advisory_xact_lock(hashtextextended('feature-curation-write', 0));
  IF v_hint.feature_id IS NOT NULL THEN
    PERFORM pg_advisory_xact_lock(hashtextextended('feature-write:' || v_hint.feature_id, 0));
  END IF;
  SELECT collection.* INTO STRICT v_collection
  FROM feature.curation_collections AS collection
  WHERE collection.collection_id = p_collection_id FOR UPDATE;
  SELECT item.* INTO STRICT v_item FROM feature.curation_items AS item
  WHERE item.collection_id = p_collection_id
    AND item.curation_item_id = p_curation_item_id FOR UPDATE;
  IF v_item.feature_id IS DISTINCT FROM v_hint.feature_id
     OR v_item.row_revision <> p_expected_item_revision THEN
    RAISE EXCEPTION 'item identity or revision changed while locking'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_item_expected_revision';
  END IF;
  PERFORM feature.claim_curation_catalog_command_effect(
    p_command_id, v_command.operation, 'item', p_curation_item_id
  );
  o_curation_item_id := p_curation_item_id;
  o_collection_revision := v_collection.row_revision;
  IF v_item.archived_at IS NOT NULL THEN
    o_item_revision := v_item.row_revision;
    RETURN;
  END IF;
  UPDATE feature.curation_items AS item
  SET status = 'archived', archived_at = clock_timestamp(),
      operator_updated_by = p_principal, operator_updated_at = clock_timestamp(),
      updated_by = p_principal, row_revision = item.row_revision + 1,
      updated_at = clock_timestamp()
  WHERE item.curation_item_id = p_curation_item_id
  RETURNING item.row_revision INTO STRICT o_item_revision;
  UPDATE feature.curation_collections AS collection
  SET updated_by = p_principal, updated_at = clock_timestamp(),
      row_revision = collection.row_revision + 1
  WHERE collection.collection_id = p_collection_id
  RETURNING collection.row_revision INTO STRICT o_collection_revision;
END
$$;
