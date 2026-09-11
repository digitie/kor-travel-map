-- ─────────────────────────────────────────────────────────────────────────
-- feature.create_curation_item_command
--   2번째 인자 p_feature_id : text → uuid
--   1번째(p_collection_id)와 OUT 3개는 원래 uuid/bigint다 — 무변경.
--   본문은 원문 그대로다: features.feature_id · curation_items.feature_id ·
--   curation_link_decisions.feature_id가 함께 uuid로 옮겨져 술어·INSERT가
--   uuid ↔ uuid 직결이다. evidence jsonb의 'requested_feature_id'는 캐스트
--   없이 그대로 둔다 — uuid도 jsonb 문자열로 나가므로 키 집합과 값 형태가
--   원문과 같다(patch_curation_item_command·apply_curation_import_items_command
--   와 같은 처리). 값의 출처만 legacy 문자열에서 uuid로 바뀐다.
--   v_feature_name은 features.name이라 text 그대로다.
-- DROP PROCEDURE의 identity에는 IN 인자만 들어간다(OUT은 무시된다).
-- ─────────────────────────────────────────────────────────────────────────
SET ROLE ktm_curation_command_owner;

DROP PROCEDURE feature.create_curation_item_command(uuid, text, text, text, text, text, text, text, integer, text, text, text, text, jsonb, bigint, text);

CREATE PROCEDURE feature.create_curation_item_command(IN p_collection_id uuid, IN p_feature_id uuid, IN p_source_record_key text, IN p_external_item_id text, IN p_external_component_id text, IN p_place_name text, IN p_address_hint text, IN p_status text, IN p_sort_order integer, IN p_item_title text, IN p_item_summary text, IN p_curation_relation text, IN p_reuse_policy text, IN p_metadata jsonb, IN p_command_id bigint, IN p_principal text, OUT o_curation_item_id uuid, OUT o_item_revision bigint, OUT o_collection_revision bigint)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'feature', 'ops', 'x_extension'
    AS $$
DECLARE
  v_command ops.domain_commands%ROWTYPE;
  v_collection feature.curation_collections%ROWTYPE;
  v_feature_name text;
  v_place_name text;
  v_decision_id uuid;
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
     OR p_collection_id IS NULL
     OR p_external_item_id IS NULL
     OR p_external_item_id <> btrim(p_external_item_id)
     OR p_external_item_id = ''
     OR p_external_component_id IS NULL
     OR p_external_component_id <> btrim(p_external_component_id)
     OR p_external_component_id = ''
     OR p_address_hint IS DISTINCT FROM NULLIF(btrim(p_address_hint), '')
     OR p_status NOT IN ('candidate','included','rejected')
     OR p_sort_order IS NULL OR p_sort_order < 0
     OR p_curation_relation NOT IN (
       'primary_stop','food_stop','cafe_stop','bookstore_stop','nearby_option',
       'accessibility_support','pet_support','family_support','theme_area_anchor'
     )
     OR p_reuse_policy NOT IN ('allowed','blocked','manual_review')
     OR jsonb_typeof(p_metadata) <> 'object' THEN
    RAISE EXCEPTION 'item command input is not canonical'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_item_command_input';
  END IF;
  SELECT command.* INTO STRICT v_command
  FROM ops.domain_commands AS command WHERE command.command_id = p_command_id;
  IF v_command.actor <> p_principal
     OR v_command.operation <> 'admin.curation-item.create' THEN
    RAISE EXCEPTION 'domain command does not match item create'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_item_domain_command';
  END IF;

  PERFORM pg_advisory_xact_lock(hashtextextended('kortravelmap:curation-import', 0));
  PERFORM pg_advisory_xact_lock(hashtextextended('feature-curation-write', 0));
  IF p_feature_id IS NOT NULL THEN
    PERFORM pg_advisory_xact_lock(hashtextextended('feature-write:' || p_feature_id, 0));
  END IF;
  SELECT collection.* INTO STRICT v_collection
  FROM feature.curation_collections AS collection
  WHERE collection.collection_id = p_collection_id FOR UPDATE;
  IF v_collection.archived_at IS NOT NULL OR v_collection.status = 'archived' THEN
    RAISE EXCEPTION 'target curation collection is archived'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_item_collection_active';
  END IF;
  IF p_feature_id IS NOT NULL THEN
    SELECT feature.name INTO v_feature_name
    FROM feature.features AS feature
    WHERE feature.feature_id = p_feature_id
      AND feature.lifecycle_state = 'active'
      AND feature.publication_state <> 'suppressed'
    FOR SHARE;
    IF NOT FOUND THEN
      RAISE EXCEPTION 'feature_id must reference an active Feature'
        USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_item_active_feature';
    END IF;
  END IF;
  v_place_name := NULLIF(btrim(p_place_name), '');
  IF v_place_name IS NULL THEN
    v_place_name := v_feature_name;
  END IF;
  IF v_place_name IS NULL THEN
    RAISE EXCEPTION 'place_name or active feature is required'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_item_place_name';
  END IF;
  IF EXISTS (
    SELECT 1 FROM feature.curation_items AS item
    WHERE item.collection_id = p_collection_id
      AND item.external_item_id = p_external_item_id
      AND item.external_component_id = p_external_component_id
  ) THEN
    RAISE EXCEPTION 'curation item identity already exists'
      USING ERRCODE = '23505', CONSTRAINT = 'uq_curation_items_component_identity';
  END IF;
  IF p_feature_id IS NOT NULL AND EXISTS (
    SELECT 1 FROM feature.curation_items AS item
    WHERE item.collection_id = p_collection_id
      AND item.external_item_id = p_external_item_id
      AND item.feature_id = p_feature_id
      AND item.source_present AND item.archived_at IS NULL
  ) THEN
    RAISE EXCEPTION 'active source feature identity already exists'
      USING ERRCODE = '23505', CONSTRAINT = 'uq_curation_items_active_source_feature';
  END IF;

  o_curation_item_id := x_extension.gen_random_uuid();
  PERFORM feature.claim_curation_catalog_command_effect(
    p_command_id, v_command.operation, 'item', o_curation_item_id
  );
  INSERT INTO feature.curation_items (
    curation_item_id, collection_id, feature_id, source_record_key,
    external_item_id, external_component_id, place_name, address_hint,
    source_present, source_updated_at, status, sort_order, item_title,
    item_summary, curation_relation, reuse_policy, metadata, created_by,
    updated_by, operator_updated_by, operator_updated_at, row_revision,
    updated_at, archived_at
  ) VALUES (
    o_curation_item_id, p_collection_id, p_feature_id, p_source_record_key,
    p_external_item_id, p_external_component_id, v_place_name, p_address_hint,
    true, clock_timestamp(), p_status, p_sort_order, p_item_title,
    p_item_summary, p_curation_relation, p_reuse_policy, p_metadata, p_principal,
    p_principal, p_principal, clock_timestamp(), 1, clock_timestamp(), NULL
  ) RETURNING row_revision INTO STRICT o_item_revision;
  IF p_feature_id IS NOT NULL THEN
    INSERT INTO feature.curation_link_decisions (
      curation_item_id, feature_id, decision_kind, match_basis,
      resolver_version, evidence, actor
    ) VALUES (
      o_curation_item_id, p_feature_id, 'accepted', 'admin_review',
      'manual-admin-v1', jsonb_build_object(
        'operation', 'create_curation_item_command',
        'requested_feature_id', p_feature_id,
        'command_id', p_command_id
      ), p_principal
    ) RETURNING decision_id INTO STRICT v_decision_id;
    UPDATE feature.curation_items AS item
    SET accepted_link_decision_id = v_decision_id
    WHERE item.curation_item_id = o_curation_item_id;
  END IF;
  UPDATE feature.curation_collections AS collection
  SET updated_by = p_principal, updated_at = clock_timestamp(),
      row_revision = collection.row_revision + 1
  WHERE collection.collection_id = p_collection_id
  RETURNING collection.row_revision INTO STRICT o_collection_revision;
END
$$;

ALTER PROCEDURE feature.create_curation_item_command(IN p_collection_id uuid, IN p_feature_id uuid, IN p_source_record_key text, IN p_external_item_id text, IN p_external_component_id text, IN p_place_name text, IN p_address_hint text, IN p_status text, IN p_sort_order integer, IN p_item_title text, IN p_item_summary text, IN p_curation_relation text, IN p_reuse_policy text, IN p_metadata jsonb, IN p_command_id bigint, IN p_principal text, OUT o_curation_item_id uuid, OUT o_item_revision bigint, OUT o_collection_revision bigint) OWNER TO ktm_curation_command_owner;

REVOKE ALL ON PROCEDURE feature.create_curation_item_command(IN p_collection_id uuid, IN p_feature_id uuid, IN p_source_record_key text, IN p_external_item_id text, IN p_external_component_id text, IN p_place_name text, IN p_address_hint text, IN p_status text, IN p_sort_order integer, IN p_item_title text, IN p_item_summary text, IN p_curation_relation text, IN p_reuse_policy text, IN p_metadata jsonb, IN p_command_id bigint, IN p_principal text, OUT o_curation_item_id uuid, OUT o_item_revision bigint, OUT o_collection_revision bigint) FROM PUBLIC;
GRANT ALL ON PROCEDURE feature.create_curation_item_command(IN p_collection_id uuid, IN p_feature_id uuid, IN p_source_record_key text, IN p_external_item_id text, IN p_external_component_id text, IN p_place_name text, IN p_address_hint text, IN p_status text, IN p_sort_order integer, IN p_item_title text, IN p_item_summary text, IN p_curation_relation text, IN p_reuse_policy text, IN p_metadata jsonb, IN p_command_id bigint, IN p_principal text, OUT o_curation_item_id uuid, OUT o_item_revision bigint, OUT o_collection_revision bigint) TO ktm_curation_admin_executor;

SET ROLE ktm_feature_schema_owner;
