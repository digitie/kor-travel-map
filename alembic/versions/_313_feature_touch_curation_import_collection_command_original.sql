CREATE OR REPLACE PROCEDURE feature.touch_curation_import_collection_command(IN p_collection_id uuid, IN p_command_id bigint, IN p_principal text, OUT o_collection_revision bigint)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'feature', 'ops'
    AS $$
DECLARE
  v_effect ops.curation_import_collection_effects%ROWTYPE;
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
  PERFORM 1 FROM ops.domain_commands AS command
  WHERE command.command_id = p_command_id
    AND command.actor = p_principal
    AND command.operation = 'admin.curation.import'
    AND NOT EXISTS (
      SELECT 1 FROM ops.domain_command_results AS result
      WHERE result.command_id = command.command_id
    ) FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'domain command does not match active curation import'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_import_domain_command';
  END IF;
  SELECT effect.* INTO STRICT v_effect
  FROM ops.curation_import_collection_effects AS effect
  WHERE effect.command_id = p_command_id
    AND effect.collection_id = p_collection_id;
  IF v_effect.created THEN
    SELECT collection.row_revision INTO STRICT o_collection_revision
    FROM feature.curation_collections AS collection
    WHERE collection.collection_id = p_collection_id;
    RETURN;
  END IF;
  INSERT INTO ops.curation_import_collection_touches(command_id, collection_id)
  VALUES (p_command_id, p_collection_id);
  UPDATE feature.curation_collections AS collection
  SET updated_by = p_principal, updated_at = clock_timestamp(),
      row_revision = collection.row_revision + 1
  WHERE collection.collection_id = p_collection_id
  RETURNING collection.row_revision INTO STRICT o_collection_revision;
END
$$;
