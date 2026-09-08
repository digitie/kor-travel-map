CREATE OR REPLACE PROCEDURE feature.create_admin_manual_feature_with_initial_state(IN p_feature_payload jsonb, IN p_domain_command_id bigint, OUT o_outcome text, OUT o_feature_id text, OUT o_feature_uuid uuid, OUT o_row_revision bigint, OUT o_existing_feature_uuid uuid)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog'
    AS $$
DECLARE
    v_command ops.domain_commands%ROWTYPE;
    v_feature_id text;
    v_feature_uuid uuid;
    v_feature_kind text;
    v_name text;
    v_lon numeric;
    v_lat numeric;
    v_key record;
    v_claimed_feature_uuid uuid;
    v_created_feature_id text;
    v_created_feature_uuid uuid;
    v_created_row_revision bigint;
    v_created boolean;
BEGIN
    IF current_setting('transaction_isolation') <> 'read committed' THEN
        RAISE EXCEPTION 'manual Feature writer requires READ COMMITTED'
            USING ERRCODE = '25001', CONSTRAINT = 'ck_manual_feature_create_isolation';
    END IF;
    IF session_user <> 'ktm_feature_api_runtime'
       OR NOT pg_has_role(session_user, 'ktm_manual_feature_admin_executor', 'member')
       OR pg_has_role(session_user, 'ktm_feature_create_provider_executor', 'member') THEN
        RAISE EXCEPTION 'manual Feature writer requires the API-only executor'
            USING ERRCODE = '42501', CONSTRAINT = 'ck_manual_feature_create_executor';
    END IF;
    IF p_domain_command_id IS NULL OR p_domain_command_id < 1 THEN
        RAISE EXCEPTION 'manual Feature domain command is invalid'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_manual_feature_create_command';
    END IF;
    SELECT command.* INTO v_command
    FROM ops.domain_commands AS command
    WHERE command.command_id = p_domain_command_id
    FOR UPDATE;
    IF NOT FOUND
       OR v_command.operation <> 'admin.feature.create.manual-v1'
       OR btrim(v_command.actor) = ''
       OR EXISTS (
           SELECT 1 FROM ops.domain_command_results AS result
           WHERE result.command_id = p_domain_command_id
       ) THEN
        RAISE EXCEPTION 'manual Feature domain command does not match open writer'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_manual_feature_create_command';
    END IF;
    IF jsonb_typeof(p_feature_payload) IS DISTINCT FROM 'object'
       OR EXISTS (
           SELECT 1
           FROM jsonb_object_keys(p_feature_payload) AS key_name(key_name)
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
       OR jsonb_typeof(p_feature_payload -> 'lat') IS DISTINCT FROM 'number' THEN
        RAISE EXCEPTION 'manual Feature payload is not canonical'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_create_payload';
    END IF;
    v_feature_id := nullif(btrim(p_feature_payload ->> 'feature_id'), '');
    v_feature_kind := nullif(btrim(p_feature_payload ->> 'kind'), '');
    v_name := nullif(btrim(p_feature_payload ->> 'name'), '');
    IF v_feature_id IS NULL OR v_feature_kind IS NULL OR v_name IS NULL
       OR nullif(btrim(p_feature_payload ->> 'category'), '') IS NULL THEN
        RAISE EXCEPTION 'manual Feature payload lacks required core values'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_create_payload';
    END IF;
    BEGIN
        v_feature_uuid := (p_feature_payload ->> 'feature_uuid')::uuid;
        v_lon := (p_feature_payload ->> 'lon')::numeric;
        v_lat := (p_feature_payload ->> 'lat')::numeric;
    EXCEPTION WHEN invalid_text_representation OR numeric_value_out_of_range THEN
        RAISE EXCEPTION 'manual Feature payload has invalid identity values'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_manual_feature_identity_coord_rounding';
    END;
    IF substring(v_feature_uuid::text FROM 15 FOR 1) <> '7' THEN
        RAISE EXCEPTION 'manual Feature UUID must be UUIDv7'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_manual_feature_create_core_identity';
    END IF;
    SELECT * INTO v_key
    FROM feature.manual_feature_identity_key(v_feature_kind, v_name, v_lon, v_lat);

    INSERT INTO feature.manual_feature_identity_claims (
        feature_id, feature_kind, name_key, lon_e6, lat_e6,
        claimed_by_command_id, claim_basis, claimed_at
    ) VALUES (
        v_feature_uuid, v_key.feature_kind, v_key.name_key, v_key.lon_e6, v_key.lat_e6,
        p_domain_command_id, 'manual_create', clock_timestamp()
    ) ON CONFLICT (feature_kind, name_key, lon_e6, lat_e6) WHERE NOT identity_released DO NOTHING
    RETURNING feature_id INTO v_claimed_feature_uuid;

    IF v_claimed_feature_uuid IS NULL THEN
        SELECT claim.feature_id INTO o_existing_feature_uuid
        FROM feature.manual_feature_identity_claims AS claim
        WHERE (claim.feature_kind, claim.name_key, claim.lon_e6, claim.lat_e6)
            = (v_key.feature_kind, v_key.name_key, v_key.lon_e6, v_key.lat_e6)
          AND NOT claim.identity_released;
        IF o_existing_feature_uuid IS NULL THEN
            RAISE EXCEPTION 'manual Feature exact winner disappeared'
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
            'reason_code', 'admin_feature_create',
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
        RAISE EXCEPTION 'manual Feature core result does not match identity claim'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_manual_feature_create_core_identity';
    END IF;
    INSERT INTO feature.feature_creation_origins (
        feature_id, origin_kind, creation_command_id, creator_principal_id,
        created_by_actor, created_at, invoker_role, procedure_definer
    ) VALUES (
        v_feature_uuid,
        'manual_admin',
        p_domain_command_id,
        'admin-ui-bff.manual-feature-create.v1',
        v_command.actor,
        clock_timestamp(),
        session_user,
        current_user
    );
    o_outcome := 'created';
    o_feature_id := v_created_feature_id;
    o_feature_uuid := v_created_feature_uuid;
    o_row_revision := v_created_row_revision;
END
$$
