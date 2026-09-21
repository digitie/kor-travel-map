CREATE OR REPLACE PROCEDURE feature.promote_theme_feature_candidate(IN p_candidate_id uuid, IN p_collection_id uuid, IN p_external_item_id text, IN p_external_component_id text, IN p_place_name text, IN p_address_hint text, IN p_item_title text, IN p_item_summary text, IN p_sort_order integer, IN p_curation_relation text, IN p_reuse_policy text, IN p_item_status text, IN p_expected_candidate_revision bigint, IN p_expected_collection_revision bigint, IN p_expected_item_revision bigint, IN p_command_id bigint, IN p_reason_code text, IN p_principal text, OUT o_candidate_id uuid, OUT o_candidate_revision bigint, OUT o_curation_item_id uuid, OUT o_curation_item_revision bigint, OUT o_transition_id bigint)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'feature', 'provider_sync', 'ops', 'x_extension'
    AS $$
DECLARE
  v_candidate_hint feature.theme_feature_candidates%ROWTYPE;
  v_candidate feature.theme_feature_candidates%ROWTYPE;
  v_rule feature.curated_source_rules%ROWTYPE;
  v_collection feature.curation_collections%ROWTYPE;
  v_item feature.curation_items%ROWTYPE;
  v_command ops.domain_commands%ROWTYPE;
  v_source_dataset_id bigint;
  v_current_source_record_key text;
  v_current_source_record_hash text;
  v_previous_decision_id uuid;
  v_decision_id uuid;
  v_item_found boolean := false;
  v_snapshot record;
BEGIN
  IF current_setting('transaction_isolation') <> 'serializable' THEN
    RAISE EXCEPTION 'candidate command requires SERIALIZABLE transaction'
      USING ERRCODE = '25001';
  END IF;
  IF NOT pg_has_role(session_user, 'ktm_curation_admin_executor', 'member') THEN
    RAISE EXCEPTION 'candidate promotion requires the admin executor'
      USING ERRCODE = '42501';
  END IF;
  IF p_expected_candidate_revision IS NULL OR p_expected_candidate_revision < 1
     OR p_expected_collection_revision IS NULL OR p_expected_collection_revision < 1
     OR (p_expected_item_revision IS NOT NULL AND p_expected_item_revision < 1) THEN
    RAISE EXCEPTION 'expected revisions must be positive'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_theme_candidate_expected_revision';
  END IF;
  IF p_external_item_id IS NULL OR p_external_item_id <> btrim(p_external_item_id)
     OR p_external_item_id = '' OR char_length(p_external_item_id) > 512
     OR p_external_component_id IS NULL
     OR p_external_component_id <> btrim(p_external_component_id)
     OR p_external_component_id = '' OR char_length(p_external_component_id) > 512
     OR p_place_name IS NULL OR p_place_name <> btrim(p_place_name)
     OR p_place_name = '' OR char_length(p_place_name) > 512
     OR p_sort_order IS NULL OR p_sort_order < 0
     OR p_item_status NOT IN ('candidate','included')
     OR p_curation_relation NOT IN (
       'primary_stop','food_stop','cafe_stop','bookstore_stop',
       'nearby_option','accessibility_support','pet_support',
       'family_support','theme_area_anchor'
     )
     OR p_reuse_policy NOT IN ('allowed','blocked','manual_review') THEN
    RAISE EXCEPTION 'candidate promotion item payload is not canonical'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_theme_candidate_promotion_payload';
  END IF;
  IF p_reason_code IS NULL OR p_reason_code <> btrim(p_reason_code)
     OR p_reason_code = '' OR char_length(p_reason_code) > 128
     OR p_principal IS NULL OR p_principal <> btrim(p_principal)
     OR p_principal = '' OR char_length(p_principal) > 200 THEN
    RAISE EXCEPTION 'promotion principal and reason must be canonical'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_theme_candidate_promotion_actor';
  END IF;

  SELECT command.* INTO STRICT v_command
  FROM ops.domain_commands AS command
  WHERE command.command_id = p_command_id;
  IF v_command.actor <> p_principal
     OR v_command.operation <> 'admin.theme-feature-candidate.promote' THEN
    RAISE EXCEPTION 'domain command does not match candidate promotion'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_theme_candidate_domain_command';
  END IF;

  -- The first read discovers the advisory-fence identity only.  Every value is
  -- read again after the common feature fence and exact relation locks.
  SELECT candidate.* INTO STRICT v_candidate_hint
  FROM feature.theme_feature_candidates AS candidate
  WHERE candidate.candidate_id = p_candidate_id;
  PERFORM pg_advisory_xact_lock(
    hashtextextended('feature-write:' || v_candidate_hint.feature_id, 0)
  );

  SELECT rule.* INTO STRICT v_rule
  FROM feature.curated_source_rules AS rule
  WHERE rule.rule_id = v_candidate_hint.rule_id
  FOR SHARE;

  SELECT source.provider_dataset_id
  INTO STRICT v_source_dataset_id
  FROM feature.curated_sources AS source
  WHERE source.source_id = v_rule.source_id
    AND source.archived_at IS NULL
  FOR SHARE;

  PERFORM 1
  FROM provider_sync.provider_datasets AS dataset
  WHERE dataset.provider_dataset_id = v_source_dataset_id
    AND dataset.is_active
  FOR SHARE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'candidate source dataset is not active'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_theme_candidate_current_source';
  END IF;

  PERFORM 1
  FROM provider_sync.source_entities AS entity
  WHERE entity.source_entity_key = v_candidate_hint.source_entity_key
    AND entity.provider_dataset_id = v_source_dataset_id
  FOR SHARE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'candidate source entity is not in the rule dataset'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_theme_candidate_current_source';
  END IF;

  SELECT head.current_source_record_key
  INTO STRICT v_current_source_record_key
  FROM provider_sync.source_entity_heads AS head
  WHERE head.source_entity_key = v_candidate_hint.source_entity_key
  FOR SHARE;
  SELECT record.raw_payload_hash
  INTO STRICT v_current_source_record_hash
  FROM provider_sync.source_records AS record
  WHERE record.source_entity_key = v_candidate_hint.source_entity_key
    AND record.source_record_key = v_current_source_record_key
  FOR SHARE;

  PERFORM 1
  FROM provider_sync.source_links AS link
  WHERE link.source_entity_key = v_candidate_hint.source_entity_key
    AND link.feature_id = v_candidate_hint.feature_id
  FOR SHARE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'candidate source link is no longer current'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_theme_candidate_current_source';
  END IF;

  PERFORM 1
  FROM feature.features AS current_feature
  WHERE current_feature.feature_id = v_candidate_hint.feature_id
    AND current_feature.lifecycle_state = 'active'
    AND current_feature.publication_state = 'published'
    AND current_feature.quality_state = 'valid'
  FOR SHARE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'candidate Feature is not currently public-eligible'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_theme_candidate_current_feature';
  END IF;

  SELECT candidate.* INTO STRICT v_candidate
  FROM feature.theme_feature_candidates AS candidate
  WHERE candidate.candidate_id = p_candidate_id
  FOR UPDATE;
  IF v_candidate.feature_id <> v_candidate_hint.feature_id
     OR v_candidate.rule_id <> v_candidate_hint.rule_id
     OR v_candidate.source_entity_key <> v_candidate_hint.source_entity_key
     OR v_candidate.row_revision <> p_expected_candidate_revision THEN
    RAISE EXCEPTION 'candidate identity or revision changed while locking'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_theme_candidate_expected_revision';
  END IF;
  IF v_candidate.disposition <> 'active'
     OR v_candidate.review_state <> 'open'
     OR NOT v_candidate.eligibility_present THEN
    RAISE EXCEPTION 'only an active open eligible candidate can be promoted'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_theme_candidate_promote_state';
  END IF;

  SELECT snapshot.* INTO v_snapshot
  FROM feature.current_theme_candidate_snapshot(
    v_candidate.rule_id,
    v_candidate.source_entity_key,
    v_candidate.feature_id
  ) AS snapshot;
  IF NOT FOUND
     OR v_snapshot.rule_input_hash <> v_candidate.rule_input_hash
     OR v_snapshot.source_record_key <> v_candidate.source_record_key
     OR v_snapshot.source_record_hash <> v_candidate.source_record_hash
     OR v_snapshot.candidate_input_hash <> v_candidate.candidate_input_hash
     OR v_current_source_record_key <> v_candidate.source_record_key
     OR v_current_source_record_hash <> v_candidate.source_record_hash THEN
    RAISE EXCEPTION 'candidate proof is stale'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_theme_candidate_current_proof';
  END IF;

  SELECT collection.* INTO STRICT v_collection
  FROM feature.curation_collections AS collection
  WHERE collection.collection_id = p_collection_id
  FOR UPDATE;
  IF v_collection.archived_at IS NOT NULL OR v_collection.status = 'archived' THEN
    RAISE EXCEPTION 'target curation collection is archived'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_theme_candidate_collection_active';
  END IF;
  IF v_collection.row_revision <> p_expected_collection_revision THEN
    RAISE EXCEPTION 'collection revision mismatch: expected %, current %',
      p_expected_collection_revision, v_collection.row_revision
      USING ERRCODE = '23514', CONSTRAINT = 'ck_theme_candidate_collection_revision';
  END IF;

  SELECT item.* INTO v_item
  FROM feature.curation_items AS item
  WHERE item.collection_id = p_collection_id
    AND item.external_item_id = p_external_item_id
    AND item.external_component_id = p_external_component_id
  FOR UPDATE;
  v_item_found := FOUND;
  IF v_item_found AND p_expected_item_revision IS NULL THEN
    RAISE EXCEPTION 'create-only curation item identity already exists'
      USING ERRCODE = '23505', CONSTRAINT = 'uq_curation_items_component_identity';
  ELSIF NOT v_item_found AND p_expected_item_revision IS NOT NULL THEN
    RAISE EXCEPTION 'expected curation item does not exist'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_theme_candidate_item_revision';
  ELSIF v_item_found AND v_item.row_revision <> p_expected_item_revision THEN
    RAISE EXCEPTION 'item revision mismatch: expected %, current %',
      p_expected_item_revision, v_item.row_revision
      USING ERRCODE = '23514', CONSTRAINT = 'ck_theme_candidate_item_revision';
  END IF;

  IF v_item_found THEN
    o_curation_item_id := v_item.curation_item_id;
    v_previous_decision_id := v_item.accepted_link_decision_id;
    UPDATE feature.curation_items AS item
    SET feature_id = v_candidate.feature_id,
        source_record_key = v_candidate.source_record_key,
        place_name = p_place_name,
        address_hint = p_address_hint,
        source_present = true,
        source_updated_at = clock_timestamp(),
        status = p_item_status,
        sort_order = p_sort_order,
        item_title = p_item_title,
        item_summary = p_item_summary,
        curation_relation = p_curation_relation,
        reuse_policy = p_reuse_policy,
        updated_by = p_principal,
        operator_updated_by = p_principal,
        operator_updated_at = clock_timestamp(),
        archived_at = NULL,
        updated_at = clock_timestamp(),
        row_revision = item.row_revision + 1
    WHERE item.curation_item_id = o_curation_item_id
    RETURNING item.row_revision INTO STRICT o_curation_item_revision;
  ELSE
    o_curation_item_id := x_extension.gen_random_uuid();
    INSERT INTO feature.curation_items (
      curation_item_id, collection_id, feature_id, source_record_key,
      external_item_id, external_component_id, place_name, address_hint,
      source_present, source_updated_at, status, sort_order, item_title,
      item_summary, curation_relation, reuse_policy, metadata, created_by,
      updated_by, operator_updated_by, operator_updated_at, row_revision
    ) VALUES (
      o_curation_item_id, p_collection_id, v_candidate.feature_id,
      v_candidate.source_record_key, p_external_item_id,
      p_external_component_id, p_place_name, p_address_hint, true,
      clock_timestamp(), p_item_status, p_sort_order, p_item_title,
      p_item_summary, p_curation_relation, p_reuse_policy,
      jsonb_build_object(
        'schema_version', 1,
        'promotion_candidate_id', p_candidate_id::text,
        'promotion_command_id', p_command_id
      ), p_principal, p_principal, p_principal, clock_timestamp(), 1
    )
    RETURNING row_revision INTO STRICT o_curation_item_revision;
    v_previous_decision_id := NULL;
  END IF;

  -- A legacy source-rule trigger can only add an intermediate accepted pointer
  -- while the old overlay still exists.  Chain the explicit admin decision to
  -- the actual locked pointer so history remains linear during this one-release
  -- migration; the final cutover drops that trigger.
  SELECT item.accepted_link_decision_id
  INTO v_previous_decision_id
  FROM feature.curation_items AS item
  WHERE item.curation_item_id = o_curation_item_id
  FOR UPDATE;

  INSERT INTO feature.curation_link_decisions (
    curation_item_id, feature_id, import_row_id, decision_kind, match_basis,
    resolver_version, evidence, actor, supersedes_decision_id
  ) VALUES (
    o_curation_item_id, v_candidate.feature_id, NULL, 'accepted',
    'admin_review', 'tvn40-candidate-promotion-v1',
    jsonb_build_object(
      'schema_version', 1,
      'candidate_id', p_candidate_id::text,
      'candidate_revision', p_expected_candidate_revision,
      'rule_revision', v_candidate.rule_row_revision,
      'source_entity_key', v_candidate.source_entity_key,
      'source_record_key', v_candidate.source_record_key,
      'source_record_hash', v_candidate.source_record_hash,
      'command_id', p_command_id
    ),
    p_principal, v_previous_decision_id
  ) RETURNING decision_id INTO STRICT v_decision_id;

  UPDATE feature.curation_items AS item
  SET accepted_link_decision_id = v_decision_id
  WHERE item.curation_item_id = o_curation_item_id;

  -- collection detail은 ordered child set을 포함한다. item promotion으로 body가
  -- 바뀌면 parent command/representation revision도 같은 transaction에서 전진한다.
  UPDATE feature.curation_collections AS collection
  SET row_revision = collection.row_revision + 1,
      updated_by = p_principal,
      updated_at = clock_timestamp()
  WHERE collection.collection_id = p_collection_id;

  UPDATE feature.theme_feature_candidates AS candidate
  SET review_state = 'promoted',
      row_revision = candidate.row_revision + 1,
      updated_at = clock_timestamp()
  WHERE candidate.candidate_id = p_candidate_id
  RETURNING candidate.candidate_id, candidate.row_revision
  INTO STRICT o_candidate_id, o_candidate_revision;

  o_transition_id := feature.append_theme_feature_candidate_transition(
    p_candidate_id,
    v_candidate.feature_id,
    v_candidate.feature_id,
    v_candidate.rule_id,
    v_candidate.source_entity_key,
    v_candidate.review_state,
    'promoted',
    v_candidate.eligibility_present,
    v_candidate.eligibility_present,
    v_candidate.disposition,
    v_candidate.disposition,
    NULL,
    'admin_promote',
    o_candidate_revision,
    v_candidate.rule_row_revision,
    v_candidate.rule_input_hash,
    v_candidate.candidate_input_hash,
    NULL,
    v_source_dataset_id,
    v_candidate.source_record_key,
    v_candidate.source_record_hash,
    p_collection_id,
    o_curation_item_id,
    p_command_id,
    p_principal,
    p_reason_code,
    jsonb_build_object(
      'schema_version', 1,
      'candidate_id', p_candidate_id::text,
      'expected_candidate_revision', p_expected_candidate_revision,
      'expected_collection_revision', p_expected_collection_revision,
      'expected_item_revision', p_expected_item_revision,
      'link_decision_id', v_decision_id::text
    )
  );
END
$$;
