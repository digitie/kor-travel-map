CREATE OR REPLACE PROCEDURE feature.create_manual_curation_item_with_feature_command(IN p_feature_payload jsonb, IN p_item_payload jsonb, IN p_domain_command_id bigint, OUT o_outcome text, OUT o_feature_id text, OUT o_feature_uuid uuid, OUT o_feature_row_revision bigint, OUT o_curation_item_id uuid, OUT o_item_row_revision bigint, OUT o_collection_row_revision bigint, OUT o_existing_feature_uuid uuid)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'feature', 'ops', 'x_extension'
    AS $$
DECLARE
    v_command ops.domain_commands%ROWTYPE;
    v_collection feature.curation_collections%ROWTYPE;
    v_feature_id text;
    v_feature_uuid uuid;
    v_feature_kind text;
    v_feature_name text;
    v_lon numeric;
    v_lat numeric;
    v_key record;
    v_claimed_feature_uuid uuid;
    v_created_feature_id text;
    v_created_feature_uuid uuid;
    v_created_row_revision bigint;
    v_created boolean;
    v_collection_id uuid;
    v_external_item_id text;
    v_external_component_id text;
    v_place_name text;
    v_address_hint text;
    v_status text;
    v_sort_order integer;
    v_item_title text;
    v_item_summary text;
    v_curation_relation text;
    v_reuse_policy text;
    v_metadata jsonb;
    v_decision_id uuid;
BEGIN
    IF current_setting('transaction_isolation') <> 'serializable' THEN
        RAISE EXCEPTION 'manual curation writer requires SERIALIZABLE'
            USING ERRCODE = '25001', CONSTRAINT = 'ck_manual_curation_create_isolation';
    END IF;
    IF session_user <> 'ktm_feature_api_runtime'
       OR NOT pg_has_role(session_user, 'ktm_curation_admin_executor', 'member')
       OR pg_has_role(session_user, 'ktm_curation_provider_executor', 'member') THEN
        RAISE EXCEPTION 'manual curation writer requires the admin executor'
            USING ERRCODE = '42501', CONSTRAINT = 'ck_manual_curation_create_executor';
    END IF;
    IF p_domain_command_id IS NULL OR p_domain_command_id < 1 THEN
        RAISE EXCEPTION 'manual curation domain command is invalid'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_manual_curation_create_command';
    END IF;
    SELECT command.* INTO v_command
    FROM ops.domain_commands AS command
    WHERE command.command_id = p_domain_command_id
    FOR UPDATE;
    IF NOT FOUND
       OR v_command.operation <> 'admin.curation-item.create.manual-feature-v1'
       OR btrim(v_command.actor) = ''
       OR EXISTS (
           SELECT 1 FROM ops.domain_command_results AS result
           WHERE result.command_id = p_domain_command_id
       ) THEN
        RAISE EXCEPTION 'manual curation domain command does not match open writer'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_manual_curation_create_command';
    END IF;
    IF jsonb_typeof(p_feature_payload) IS DISTINCT FROM 'object'
       OR EXISTS (
           SELECT 1 FROM jsonb_object_keys(p_feature_payload) AS key_name(key_name)
           WHERE key_name NOT IN (
               'feature_id', 'feature_uuid', 'kind', 'name', 'category',
               'lon', 'lat', 'coord_precision_digits', 'address',
               'legal_dong_code', 'road_name_code', 'road_address_management_no',
               'admin_dong_code', 'sido_code', 'sigungu_code', 'urls',
               'marker_icon', 'marker_color', 'parent_feature_id', 'sibling_group_id',
               'raw_refs'
           )
       )
       OR jsonb_typeof(p_feature_payload -> 'feature_id') IS DISTINCT FROM 'string'
       OR jsonb_typeof(p_feature_payload -> 'feature_uuid') IS DISTINCT FROM 'string'
       OR jsonb_typeof(p_feature_payload -> 'kind') IS DISTINCT FROM 'string'
       OR jsonb_typeof(p_feature_payload -> 'name') IS DISTINCT FROM 'string'
       OR jsonb_typeof(p_feature_payload -> 'category') IS DISTINCT FROM 'string'
       OR jsonb_typeof(p_feature_payload -> 'lon') IS DISTINCT FROM 'number'
       OR jsonb_typeof(p_feature_payload -> 'lat') IS DISTINCT FROM 'number'
       OR jsonb_typeof(p_item_payload) IS DISTINCT FROM 'object'
       OR EXISTS (
           SELECT 1 FROM jsonb_object_keys(p_item_payload) AS key_name(key_name)
           WHERE key_name NOT IN (
               'collection_id', 'external_item_id', 'external_component_id',
               'place_name', 'address_hint', 'status', 'sort_order', 'item_title',
               'item_summary', 'curation_relation', 'reuse_policy', 'metadata',
               'source_record_key'
           )
       ) THEN
        RAISE EXCEPTION 'manual curation payload is not canonical'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_manual_curation_create_payload';
    END IF;

    v_feature_id := nullif(btrim(p_feature_payload ->> 'feature_id'), '');
    v_feature_kind := nullif(btrim(p_feature_payload ->> 'kind'), '');
    v_feature_name := nullif(btrim(p_feature_payload ->> 'name'), '');
    IF v_feature_id IS NULL OR v_feature_kind IS NULL OR v_feature_name IS NULL
       OR nullif(btrim(p_feature_payload ->> 'category'), '') IS NULL THEN
        RAISE EXCEPTION 'manual curation Feature lacks required core values'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_manual_curation_create_payload';
    END IF;
    BEGIN
        v_feature_uuid := (p_feature_payload ->> 'feature_uuid')::uuid;
        v_lon := (p_feature_payload ->> 'lon')::numeric;
        v_lat := (p_feature_payload ->> 'lat')::numeric;
        v_collection_id := (p_item_payload ->> 'collection_id')::uuid;
        v_sort_order := (p_item_payload ->> 'sort_order')::integer;
    EXCEPTION WHEN invalid_text_representation OR numeric_value_out_of_range THEN
        RAISE EXCEPTION 'manual curation identity is invalid'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_manual_curation_create_payload';
    END;
    IF substring(v_feature_uuid::text FROM 15 FOR 1) <> '7' THEN
        RAISE EXCEPTION 'manual curation Feature UUID must be UUIDv7'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_manual_feature_create_core_identity';
    END IF;
    v_external_item_id := nullif(btrim(p_item_payload ->> 'external_item_id'), '');
    v_external_component_id := nullif(btrim(p_item_payload ->> 'external_component_id'), '');
    v_place_name := nullif(btrim(p_item_payload ->> 'place_name'), '');
    v_address_hint := nullif(btrim(p_item_payload ->> 'address_hint'), '');
    v_status := nullif(btrim(p_item_payload ->> 'status'), '');
    v_item_title := nullif(btrim(p_item_payload ->> 'item_title'), '');
    v_item_summary := nullif(btrim(p_item_payload ->> 'item_summary'), '');
    v_curation_relation := nullif(btrim(p_item_payload ->> 'curation_relation'), '');
    v_reuse_policy := nullif(btrim(p_item_payload ->> 'reuse_policy'), '');
    v_metadata := p_item_payload -> 'metadata';
    IF v_collection_id IS NULL
       OR v_external_item_id IS NULL
       OR v_external_component_id IS NULL
       OR v_status NOT IN ('candidate', 'included', 'rejected')
       OR v_sort_order IS NULL OR v_sort_order < 0
       OR v_curation_relation NOT IN (
           'primary_stop', 'food_stop', 'cafe_stop', 'bookstore_stop', 'nearby_option',
           'accessibility_support', 'pet_support', 'family_support', 'theme_area_anchor'
       )
       OR v_reuse_policy NOT IN ('allowed', 'blocked', 'manual_review')
       OR jsonb_typeof(v_metadata) IS DISTINCT FROM 'object'
       OR (p_item_payload ? 'source_record_key' AND p_item_payload -> 'source_record_key' <> 'null'::jsonb) THEN
        RAISE EXCEPTION 'manual curation item payload is not canonical'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_manual_curation_create_payload';
    END IF;

    PERFORM pg_advisory_xact_lock(hashtextextended('kortravelmap:curation-import', 0));
    PERFORM pg_advisory_xact_lock(hashtextextended('feature-curation-write', 0));
    PERFORM pg_advisory_xact_lock(hashtextextended('feature-write:' || v_feature_id, 0));
    SELECT collection.* INTO STRICT v_collection
    FROM feature.curation_collections AS collection
    WHERE collection.collection_id = v_collection_id
    FOR UPDATE;
    IF v_collection.archived_at IS NOT NULL OR v_collection.status = 'archived' THEN
        RAISE EXCEPTION 'target curation collection is archived'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_item_collection_active';
    END IF;
    IF EXISTS (
        SELECT 1 FROM feature.curation_items AS item
        WHERE item.collection_id = v_collection_id
          AND item.external_item_id = v_external_item_id
          AND item.external_component_id = v_external_component_id
    ) THEN
        RAISE EXCEPTION 'curation item identity already exists'
            USING ERRCODE = '23505', CONSTRAINT = 'uq_curation_items_component_identity';
    END IF;

    SELECT * INTO v_key
    FROM feature.manual_feature_identity_key(v_feature_kind, v_feature_name, v_lon, v_lat);
    INSERT INTO feature.manual_feature_identity_claims (
        feature_id, feature_kind, name_key, lon_e6, lat_e6,
        claimed_by_command_id, claim_basis, claimed_at
    ) VALUES (
        v_feature_uuid, v_key.feature_kind, v_key.name_key, v_key.lon_e6, v_key.lat_e6,
        p_domain_command_id, 'manual_create', clock_timestamp()
    ) ON CONFLICT ON CONSTRAINT uq_manual_feature_identity_claims_exact DO NOTHING
    RETURNING feature_id INTO v_claimed_feature_uuid;
    IF v_claimed_feature_uuid IS NULL THEN
        SELECT claim.feature_id INTO o_existing_feature_uuid
        FROM feature.manual_feature_identity_claims AS claim
        WHERE (claim.feature_kind, claim.name_key, claim.lon_e6, claim.lat_e6)
            = (v_key.feature_kind, v_key.name_key, v_key.lon_e6, v_key.lat_e6);
        IF o_existing_feature_uuid IS NULL THEN
            RAISE EXCEPTION 'manual curation exact winner disappeared'
                USING ERRCODE = '23514', CONSTRAINT = 'ck_manual_feature_create_core_identity';
        END IF;
        o_outcome := 'exact_conflict';
        RETURN;
    END IF;

    CALL feature.create_feature_with_initial_state(
        p_feature_payload,
        'active',
        'published',
        'valid',
        jsonb_build_object(
            'transition_kind', 'initial',
            'reason_code', 'admin_curation_manual_feature_create',
            'principal', v_command.actor,
            'causation_ref', 'domain-command:' || p_domain_command_id::text
        ),
        v_created_feature_id,
        v_created_feature_uuid,
        v_created_row_revision,
        v_created
    );
    IF v_created IS DISTINCT FROM true
       OR v_created_feature_id IS DISTINCT FROM v_feature_id
       OR v_created_feature_uuid IS DISTINCT FROM v_feature_uuid
       OR v_created_row_revision IS NULL OR v_created_row_revision < 1 THEN
        RAISE EXCEPTION 'manual curation core result does not match identity claim'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_manual_feature_create_core_identity';
    END IF;
    INSERT INTO feature.feature_creation_origins (
        feature_id, origin_kind, creation_command_id, creator_principal_id,
        created_by_actor, created_at, invoker_role, procedure_definer
    ) VALUES (
        v_feature_uuid,
        'manual_curation',
        p_domain_command_id,
        'admin-ui-bff.manual-curation-feature-create.v1',
        v_command.actor,
        clock_timestamp(),
        session_user,
        current_user
    );
    PERFORM feature.claim_curation_catalog_command_effect(
        p_domain_command_id, v_command.operation, 'item', x_extension.gen_random_uuid()
    );
    SELECT effect.resource_id INTO o_curation_item_id
    FROM ops.curation_catalog_command_effects AS effect
    WHERE effect.command_id = p_domain_command_id;
    INSERT INTO feature.curation_items (
        curation_item_id, collection_id, feature_id, source_record_key,
        external_item_id, external_component_id, place_name, address_hint,
        source_present, source_updated_at, status, sort_order, item_title,
        item_summary, curation_relation, reuse_policy, metadata, created_by,
        updated_by, operator_updated_by, operator_updated_at, row_revision,
        updated_at, archived_at
    ) VALUES (
        o_curation_item_id, v_collection_id, v_feature_id, NULL,
        v_external_item_id, v_external_component_id, coalesce(v_place_name, v_feature_name),
        v_address_hint, true, clock_timestamp(), v_status, v_sort_order, v_item_title,
        v_item_summary, v_curation_relation, v_reuse_policy, v_metadata, v_command.actor,
        v_command.actor, v_command.actor, clock_timestamp(), 1, clock_timestamp(), NULL
    ) RETURNING row_revision INTO STRICT o_item_row_revision;
    INSERT INTO feature.curation_link_decisions (
        curation_item_id, feature_id, decision_kind, match_basis,
        resolver_version, evidence, actor
    ) VALUES (
        o_curation_item_id, v_feature_id, 'accepted', 'admin_review',
        'manual-curation-feature-v1', jsonb_build_object(
            'operation', v_command.operation,
            'command_id', p_domain_command_id,
            'feature_uuid', v_feature_uuid
        ), v_command.actor
    ) RETURNING decision_id INTO STRICT v_decision_id;
    UPDATE feature.curation_items AS item
    SET accepted_link_decision_id = v_decision_id
    WHERE item.curation_item_id = o_curation_item_id;
    UPDATE feature.curation_collections AS collection
    SET updated_by = v_command.actor, updated_at = clock_timestamp(),
        row_revision = collection.row_revision + 1
    WHERE collection.collection_id = v_collection_id
    RETURNING collection.row_revision INTO STRICT o_collection_row_revision;
    o_outcome := 'created';
    o_feature_id := v_created_feature_id;
    o_feature_uuid := v_created_feature_uuid;
    o_feature_row_revision := v_created_row_revision;
END
$$;