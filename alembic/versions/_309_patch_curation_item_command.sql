-- ─────────────────────────────────────────────────────────────────────────
-- feature.patch_curation_item_command
--   4번째 인자 p_feature_id : text → uuid
--   1·2번째(p_collection_id / p_curation_item_id)는 원래 uuid다 — 무변경.
--   본문은 원문 그대로다: 술어·행 비교·INSERT·UPDATE 모두 uuid ↔ uuid 직결.
-- DROP PROCEDURE의 identity에는 IN 인자만 들어간다(OUT은 무시된다).
-- ─────────────────────────────────────────────────────────────────────────
SET ROLE ktm_curation_command_owner;

DROP PROCEDURE feature.patch_curation_item_command(uuid,uuid,bigint,text,text,text,text,text,text,text,integer,text,text,text,text,jsonb,bigint,text);

SET ROLE ktm_feature_schema_owner;

CREATE PROCEDURE feature.patch_curation_item_command(IN p_collection_id uuid, IN p_curation_item_id uuid, IN p_expected_item_revision bigint, IN p_feature_id uuid, IN p_source_record_key text, IN p_external_item_id text, IN p_external_component_id text, IN p_place_name text, IN p_address_hint text, IN p_status text, IN p_sort_order integer, IN p_item_title text, IN p_item_summary text, IN p_curation_relation text, IN p_reuse_policy text, IN p_metadata jsonb, IN p_command_id bigint, IN p_principal text, OUT o_curation_item_id uuid, OUT o_item_revision bigint, OUT o_collection_revision bigint)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'feature', 'ops'
    AS $$
DECLARE
  v_command ops.domain_commands%ROWTYPE;
  v_collection feature.curation_collections%ROWTYPE;
  v_hint feature.curation_items%ROWTYPE;
  v_item feature.curation_items%ROWTYPE;
  v_decision_id uuid;
  v_source_owned_changed boolean;
  v_operator_owned_changed boolean;
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
     OR p_expected_item_revision IS NULL OR p_expected_item_revision < 1
     OR p_external_item_id IS NULL
     OR p_external_item_id <> btrim(p_external_item_id)
     OR p_external_item_id = ''
     OR p_external_component_id IS NULL
     OR p_external_component_id <> btrim(p_external_component_id)
     OR p_external_component_id = ''
     OR p_place_name IS NULL OR p_place_name <> btrim(p_place_name)
     OR p_place_name = ''
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
     OR v_command.operation <> 'admin.curation-item.patch' THEN
    RAISE EXCEPTION 'domain command does not match item patch'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_item_domain_command';
  END IF;

  SELECT item.* INTO STRICT v_hint FROM feature.curation_items AS item
  WHERE item.collection_id = p_collection_id
    AND item.curation_item_id = p_curation_item_id;
  PERFORM pg_advisory_xact_lock(hashtextextended('kortravelmap:curation-import', 0));
  PERFORM pg_advisory_xact_lock(hashtextextended('feature-curation-write', 0));
  PERFORM pg_advisory_xact_lock(hashtextextended('feature-write:' || touched.feature_id, 0))
  FROM (
    SELECT v_hint.feature_id AS feature_id
    UNION SELECT p_feature_id WHERE p_feature_id IS NOT NULL
  ) AS touched
  WHERE touched.feature_id IS NOT NULL
  ORDER BY touched.feature_id;
  SELECT collection.* INTO STRICT v_collection
  FROM feature.curation_collections AS collection
  WHERE collection.collection_id = p_collection_id FOR UPDATE;
  IF v_collection.archived_at IS NOT NULL OR v_collection.status = 'archived' THEN
    RAISE EXCEPTION 'target curation collection is archived'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_item_collection_active';
  END IF;
  SELECT item.* INTO STRICT v_item FROM feature.curation_items AS item
  WHERE item.collection_id = p_collection_id
    AND item.curation_item_id = p_curation_item_id FOR UPDATE;
  IF v_item.curation_item_id <> v_hint.curation_item_id
     OR v_item.feature_id IS DISTINCT FROM v_hint.feature_id
     OR v_item.row_revision <> p_expected_item_revision THEN
    RAISE EXCEPTION 'item identity or revision changed while locking'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_item_expected_revision';
  END IF;
  IF v_item.archived_at IS NOT NULL THEN
    RAISE EXCEPTION 'archived item cannot be patched'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_item_active';
  END IF;
  IF p_feature_id IS NOT NULL THEN
    PERFORM 1 FROM feature.features AS feature
    WHERE feature.feature_id = p_feature_id
      AND feature.lifecycle_state = 'active'
      AND feature.publication_state <> 'suppressed'
    FOR SHARE;
    IF NOT FOUND THEN
      RAISE EXCEPTION 'feature_id must reference an active Feature'
        USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_item_active_feature';
    END IF;
  END IF;
  IF EXISTS (
    SELECT 1 FROM feature.curation_items AS item
    WHERE item.collection_id = p_collection_id
      AND item.curation_item_id <> p_curation_item_id
      AND item.external_item_id = p_external_item_id
      AND item.external_component_id = p_external_component_id
  ) THEN
    RAISE EXCEPTION 'curation item identity already exists'
      USING ERRCODE = '23505', CONSTRAINT = 'uq_curation_items_component_identity';
  END IF;
  IF p_feature_id IS NOT NULL AND EXISTS (
    SELECT 1 FROM feature.curation_items AS item
    WHERE item.collection_id = p_collection_id
      AND item.curation_item_id <> p_curation_item_id
      AND item.external_item_id = p_external_item_id
      AND item.feature_id = p_feature_id
      AND item.source_present AND item.archived_at IS NULL
  ) THEN
    RAISE EXCEPTION 'active source feature identity already exists'
      USING ERRCODE = '23505', CONSTRAINT = 'uq_curation_items_active_source_feature';
  END IF;
  v_source_owned_changed := (
    v_item.feature_id, v_item.source_record_key, v_item.external_item_id,
    v_item.external_component_id, v_item.place_name, v_item.address_hint,
    v_item.sort_order, v_item.item_title, v_item.item_summary, v_item.metadata
  ) IS DISTINCT FROM (
    p_feature_id, p_source_record_key, p_external_item_id,
    p_external_component_id, p_place_name, p_address_hint,
    p_sort_order, p_item_title, p_item_summary, p_metadata
  );
  v_operator_owned_changed := (
    v_item.status, v_item.curation_relation, v_item.reuse_policy
  ) IS DISTINCT FROM (
    p_status, p_curation_relation, p_reuse_policy
  );
  PERFORM feature.claim_curation_catalog_command_effect(
    p_command_id, v_command.operation, 'item', p_curation_item_id
  );
  o_curation_item_id := p_curation_item_id;
  o_collection_revision := v_collection.row_revision;
  IF NOT v_source_owned_changed AND NOT v_operator_owned_changed THEN
    o_item_revision := v_item.row_revision;
    RETURN;
  END IF;
  IF v_item.feature_id IS DISTINCT FROM p_feature_id THEN
    IF p_feature_id IS NOT NULL THEN
      INSERT INTO feature.curation_link_decisions (
        curation_item_id, feature_id, decision_kind, match_basis,
        resolver_version, evidence, actor, supersedes_decision_id
      ) VALUES (
        p_curation_item_id, p_feature_id, 'accepted', 'admin_review',
        'manual-admin-v1', jsonb_build_object(
          'operation', 'patch_curation_item_command',
          'previous_feature_id', v_item.feature_id,
          'requested_feature_id', p_feature_id,
          'command_id', p_command_id
        ), p_principal, v_item.accepted_link_decision_id
      ) RETURNING decision_id INTO STRICT v_decision_id;
    ELSIF v_item.feature_id IS NOT NULL THEN
      INSERT INTO feature.curation_link_decisions (
        curation_item_id, feature_id, decision_kind, match_basis,
        resolver_version, evidence, actor, supersedes_decision_id
      ) VALUES (
        p_curation_item_id, v_item.feature_id, 'revoked', 'admin_review',
        'manual-admin-v1', jsonb_build_object(
          'operation', 'patch_curation_item_command',
          'previous_feature_id', v_item.feature_id,
          'reason', 'explicit feature_id=null',
          'command_id', p_command_id
        ), p_principal, v_item.accepted_link_decision_id
      ) RETURNING decision_id INTO STRICT v_decision_id;
    END IF;
  END IF;
  UPDATE feature.curation_items AS item
  SET feature_id = p_feature_id,
      source_record_key = p_source_record_key,
      external_item_id = p_external_item_id,
      external_component_id = p_external_component_id,
      place_name = p_place_name,
      address_hint = p_address_hint,
      status = p_status,
      sort_order = p_sort_order,
      item_title = p_item_title,
      item_summary = p_item_summary,
      curation_relation = p_curation_relation,
      reuse_policy = p_reuse_policy,
      metadata = p_metadata,
      accepted_link_decision_id = CASE
        WHEN v_item.feature_id IS NOT DISTINCT FROM p_feature_id
          THEN v_item.accepted_link_decision_id
        WHEN p_feature_id IS NULL THEN NULL
        ELSE v_decision_id
      END,
      source_updated_at = CASE WHEN v_source_owned_changed
        THEN clock_timestamp() ELSE item.source_updated_at END,
      operator_updated_by = CASE WHEN v_operator_owned_changed
        THEN p_principal ELSE item.operator_updated_by END,
      operator_updated_at = CASE WHEN v_operator_owned_changed
        THEN clock_timestamp() ELSE item.operator_updated_at END,
      updated_by = p_principal,
      row_revision = item.row_revision + 1,
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

ALTER PROCEDURE feature.patch_curation_item_command(IN p_collection_id uuid, IN p_curation_item_id uuid, IN p_expected_item_revision bigint, IN p_feature_id uuid, IN p_source_record_key text, IN p_external_item_id text, IN p_external_component_id text, IN p_place_name text, IN p_address_hint text, IN p_status text, IN p_sort_order integer, IN p_item_title text, IN p_item_summary text, IN p_curation_relation text, IN p_reuse_policy text, IN p_metadata jsonb, IN p_command_id bigint, IN p_principal text, OUT o_curation_item_id uuid, OUT o_item_revision bigint, OUT o_collection_revision bigint) OWNER TO ktm_curation_command_owner;

-- ACL은 정확히 소유자 role로 편집한다(0203:290-293).
SET ROLE ktm_curation_command_owner;

REVOKE ALL ON PROCEDURE feature.patch_curation_item_command(IN p_collection_id uuid, IN p_curation_item_id uuid, IN p_expected_item_revision bigint, IN p_feature_id uuid, IN p_source_record_key text, IN p_external_item_id text, IN p_external_component_id text, IN p_place_name text, IN p_address_hint text, IN p_status text, IN p_sort_order integer, IN p_item_title text, IN p_item_summary text, IN p_curation_relation text, IN p_reuse_policy text, IN p_metadata jsonb, IN p_command_id bigint, IN p_principal text, OUT o_curation_item_id uuid, OUT o_item_revision bigint, OUT o_collection_revision bigint) FROM PUBLIC;
GRANT ALL ON PROCEDURE feature.patch_curation_item_command(IN p_collection_id uuid, IN p_curation_item_id uuid, IN p_expected_item_revision bigint, IN p_feature_id uuid, IN p_source_record_key text, IN p_external_item_id text, IN p_external_component_id text, IN p_place_name text, IN p_address_hint text, IN p_status text, IN p_sort_order integer, IN p_item_title text, IN p_item_summary text, IN p_curation_relation text, IN p_reuse_policy text, IN p_metadata jsonb, IN p_command_id bigint, IN p_principal text, OUT o_curation_item_id uuid, OUT o_item_revision bigint, OUT o_collection_revision bigint) TO ktm_curation_admin_executor;

SET ROLE ktm_feature_schema_owner;
