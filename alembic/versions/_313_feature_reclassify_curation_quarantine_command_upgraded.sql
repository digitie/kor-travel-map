CREATE OR REPLACE PROCEDURE feature.reclassify_curation_quarantine_command(IN p_quarantine_collection_id uuid, IN p_expected_quarantine_revision bigint, IN p_action text, IN p_target_collection_id uuid, IN p_expected_target_revision bigint, IN p_item_ids uuid[], IN p_collection_key text, IN p_title text, IN p_command_id bigint, IN p_principal text, OUT o_moved_item_ids uuid[], OUT o_quarantine_deleted boolean, OUT o_collection_id uuid, OUT o_collection_key text, OUT o_collection_revision bigint, OUT o_conflicts jsonb)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'feature', 'ops'
    AS $$
DECLARE
  v_command ops.domain_commands%ROWTYPE;
  v_quarantine_hint feature.curation_collections%ROWTYPE;
  v_quarantine feature.curation_collections%ROWTYPE;
  v_target feature.curation_collections%ROWTYPE;
  v_target_id uuid;
  v_locked_item_ids uuid[];
BEGIN
  IF current_setting('transaction_isolation') <> 'serializable' THEN
    RAISE EXCEPTION 'quarantine command requires SERIALIZABLE transaction'
      USING ERRCODE = '25001';
  END IF;
  IF NOT pg_has_role(session_user, 'ktm_curation_admin_executor', 'member') THEN
    RAISE EXCEPTION 'quarantine command requires the admin executor'
      USING ERRCODE = '42501';
  END IF;
  IF p_principal IS NULL OR p_principal <> btrim(p_principal) OR p_principal = ''
     OR p_quarantine_collection_id IS NULL
     OR p_expected_quarantine_revision IS NULL OR p_expected_quarantine_revision < 1
     OR p_action NOT IN ('move','confirm_standalone')
     OR (p_action = 'move' AND (
       p_collection_key IS NOT NULL OR p_title IS NOT NULL
       OR p_expected_target_revision IS NULL OR p_expected_target_revision < 1
     ))
     OR (p_action = 'confirm_standalone' AND (
       p_target_collection_id IS NOT NULL OR p_expected_target_revision IS NOT NULL
       OR p_item_ids IS NOT NULL OR p_collection_key IS NULL
       OR p_collection_key <> btrim(p_collection_key) OR p_collection_key = ''
       OR p_title IS NULL OR p_title <> btrim(p_title) OR p_title = ''
     )) THEN
    RAISE EXCEPTION 'quarantine command input is not canonical'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_quarantine_command_input';
  END IF;
  SELECT command.* INTO STRICT v_command
  FROM ops.domain_commands AS command WHERE command.command_id = p_command_id;
  IF v_command.actor <> p_principal
     OR v_command.operation <> 'admin.curation-quarantine.reclassify' THEN
    RAISE EXCEPTION 'domain command does not match quarantine reclassify'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_quarantine_domain_command';
  END IF;

  SELECT collection.* INTO STRICT v_quarantine_hint
  FROM feature.curation_collections AS collection
  WHERE collection.collection_id = p_quarantine_collection_id;
  IF v_quarantine_hint.created_by IS DISTINCT FROM 'migration:0065'
     OR v_quarantine_hint.metadata ->> 'migration_quarantine' IS DISTINCT FROM '0065' THEN
    RAISE EXCEPTION 'curation quarantine collection does not exist'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_quarantine_marker';
  END IF;
  IF p_action = 'move' THEN
    v_target_id := COALESCE(
      p_target_collection_id,
      NULLIF(v_quarantine_hint.metadata ->> 'original_collection_id', '')::uuid
    );
    IF v_target_id IS NULL OR v_target_id = p_quarantine_collection_id THEN
      RAISE EXCEPTION 'valid target collection is required'
        USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_quarantine_target';
    END IF;
  END IF;

  PERFORM pg_advisory_xact_lock(hashtextextended('kortravelmap:curation-import', 0));
  PERFORM pg_advisory_xact_lock(hashtextextended('feature-curation-write', 0));
  IF p_action = 'confirm_standalone' THEN
    PERFORM pg_advisory_xact_lock(hashtextextended('curation-collection:' || p_collection_key, 0));
  END IF;
  PERFORM collection.collection_id
  FROM feature.curation_collections AS collection
  WHERE collection.collection_id = ANY(
    CASE WHEN v_target_id IS NULL
      THEN ARRAY[p_quarantine_collection_id]
      ELSE ARRAY[p_quarantine_collection_id, v_target_id]
    END
  )
  ORDER BY collection.collection_id FOR UPDATE;
  SELECT collection.* INTO STRICT v_quarantine
  FROM feature.curation_collections AS collection
  WHERE collection.collection_id = p_quarantine_collection_id;
  IF v_quarantine.row_revision <> p_expected_quarantine_revision
     OR v_quarantine.created_by IS DISTINCT FROM 'migration:0065'
     OR v_quarantine.metadata ->> 'migration_quarantine' IS DISTINCT FROM '0065' THEN
    RAISE EXCEPTION 'quarantine collection revision or marker changed'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_quarantine_expected_revision';
  END IF;
  PERFORM feature.claim_curation_catalog_command_effect(
    p_command_id, v_command.operation, 'collection', p_quarantine_collection_id
  );

  IF p_action = 'confirm_standalone' THEN
    UPDATE feature.curation_collections AS collection
    SET collection_key = p_collection_key, title = p_title,
        metadata = collection.metadata - 'migration_quarantine' - 'original_collection_id',
        updated_by = p_principal, updated_at = clock_timestamp(),
        row_revision = collection.row_revision + 1
    WHERE collection.collection_id = p_quarantine_collection_id
    RETURNING collection.collection_id, collection.collection_key,
              collection.row_revision
    INTO STRICT o_collection_id, o_collection_key, o_collection_revision;
    o_moved_item_ids := NULL;
    o_quarantine_deleted := NULL;
    o_conflicts := '[]'::jsonb;
    RETURN;
  END IF;

  SELECT collection.* INTO STRICT v_target
  FROM feature.curation_collections AS collection
  WHERE collection.collection_id = v_target_id;
  IF v_target.row_revision <> p_expected_target_revision
     OR v_target.archived_at IS NOT NULL OR v_target.status = 'archived'
     OR (v_target.created_by = 'migration:0065'
         AND v_target.metadata ->> 'migration_quarantine' = '0065') THEN
    RAISE EXCEPTION 'target collection revision or state changed'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_quarantine_target_revision';
  END IF;
  PERFORM item.curation_item_id
  FROM feature.curation_items AS item
  WHERE item.collection_id = p_quarantine_collection_id
  ORDER BY item.curation_item_id FOR UPDATE;
  SELECT COALESCE(array_agg(item.curation_item_id ORDER BY item.curation_item_id), ARRAY[]::uuid[])
  INTO STRICT v_locked_item_ids
  FROM feature.curation_items AS item
  WHERE item.collection_id = p_quarantine_collection_id;
  IF p_item_ids IS NULL THEN
    o_moved_item_ids := v_locked_item_ids;
  ELSE
    IF cardinality(p_item_ids) <> (
      SELECT count(DISTINCT requested)::integer FROM unnest(p_item_ids) AS requested
    ) OR EXISTS (
      SELECT 1 FROM unnest(p_item_ids) AS requested
      WHERE NOT requested = ANY(v_locked_item_ids)
    ) THEN
      RAISE EXCEPTION 'item_ids contain duplicates or non-members'
        USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_quarantine_item_set';
    END IF;
    SELECT COALESCE(array_agg(requested ORDER BY requested), ARRAY[]::uuid[])
    INTO STRICT o_moved_item_ids FROM unnest(p_item_ids) AS requested;
  END IF;

  SELECT COALESCE(jsonb_agg(jsonb_build_object(
    'curation_item_id', moving.curation_item_id,
    'conflict_kind', moving.conflict_kind,
    'conflict_item_id', moving.conflict_item_id
  ) ORDER BY moving.curation_item_id), '[]'::jsonb)
  INTO STRICT o_conflicts
  FROM (
    SELECT item.curation_item_id,
      CASE WHEN component.curation_item_id IS NOT NULL
        THEN 'component_identity_conflict'
        ELSE 'active_source_feature_conflict' END AS conflict_kind,
      COALESCE(component.curation_item_id, active_feature.curation_item_id) AS conflict_item_id
    FROM feature.curation_items AS item
    LEFT JOIN LATERAL (
      SELECT occupant.curation_item_id
      FROM feature.curation_items AS occupant
      WHERE occupant.collection_id = v_target_id
        AND occupant.external_item_id = item.external_item_id
        AND occupant.external_component_id = item.external_component_id
      LIMIT 1
    ) AS component ON true
    LEFT JOIN LATERAL (
      SELECT occupant.curation_item_id
      FROM feature.curation_items AS occupant
      WHERE item.source_present AND item.archived_at IS NULL
        AND occupant.collection_id = v_target_id
        AND occupant.external_item_id = item.external_item_id
        AND occupant.feature_id = item.feature_id
        AND occupant.source_present AND occupant.archived_at IS NULL
      LIMIT 1
    ) AS active_feature ON true
    WHERE item.curation_item_id = ANY(o_moved_item_ids)
      AND (component.curation_item_id IS NOT NULL
           OR active_feature.curation_item_id IS NOT NULL)
  ) AS moving;
  IF jsonb_array_length(o_conflicts) > 0 THEN
    RETURN;
  END IF;
  IF cardinality(o_moved_item_ids) > 0 THEN
    UPDATE feature.curation_items AS item
    SET collection_id = v_target_id, updated_by = p_principal,
        updated_at = clock_timestamp(), row_revision = item.row_revision + 1
    WHERE item.curation_item_id = ANY(o_moved_item_ids);
    UPDATE feature.curation_collections AS collection
    SET updated_by = p_principal, updated_at = clock_timestamp(),
        row_revision = collection.row_revision + 1
    WHERE collection.collection_id = v_target_id
    RETURNING collection.row_revision INTO STRICT o_collection_revision;
  ELSE
    o_collection_revision := v_target.row_revision;
  END IF;
  DELETE FROM feature.curation_collections AS collection
  WHERE collection.collection_id = p_quarantine_collection_id
    AND NOT EXISTS (
      SELECT 1 FROM feature.curation_items AS item
      WHERE item.collection_id = p_quarantine_collection_id
    );
  o_quarantine_deleted := FOUND;
  IF NOT o_quarantine_deleted THEN
    UPDATE feature.curation_collections AS collection
    SET updated_by = p_principal, updated_at = clock_timestamp(),
        row_revision = collection.row_revision + 1
    WHERE collection.collection_id = p_quarantine_collection_id;
  END IF;
  o_collection_id := v_target_id;
  o_collection_key := v_target.collection_key;
END
$$;
