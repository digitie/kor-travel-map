SET ROLE ktm_manual_feature_procedure_owner;

DROP PROCEDURE feature.create_admin_manual_feature_with_initial_state(jsonb, bigint);

CREATE PROCEDURE feature.create_admin_manual_feature_with_initial_state(IN p_feature_payload jsonb, IN p_domain_command_id bigint, OUT o_outcome text, OUT o_feature_id uuid, OUT o_row_revision bigint, OUT o_existing_feature_id uuid)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog'
    AS $$
DECLARE
    v_command ops.domain_commands%ROWTYPE;
    v_feature_id uuid;
    v_feature_kind text;
    v_name text;
    v_lon numeric;
    v_lat numeric;
    v_key record;
    v_claimed_feature_id uuid;
    v_created_feature_id uuid;
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
               'feature_id', 'kind', 'name', 'category',
               'lon', 'lat', 'coord_precision_digits', 'address',
               'legal_dong_code', 'road_name_code', 'road_address_management_no',
               'admin_dong_code', 'sido_code', 'sigungu_code', 'urls',
               'marker_icon', 'marker_color', 'parent_feature_id', 'sibling_group_id',
               'raw_refs'
           )
       )
       OR jsonb_typeof(p_feature_payload -> 'feature_id') IS DISTINCT FROM 'string'
       OR jsonb_typeof(p_feature_payload -> 'kind') IS DISTINCT FROM 'string'
       OR jsonb_typeof(p_feature_payload -> 'name') IS DISTINCT FROM 'string'
       OR jsonb_typeof(p_feature_payload -> 'category') IS DISTINCT FROM 'string'
       OR jsonb_typeof(p_feature_payload -> 'lon') IS DISTINCT FROM 'number'
       OR jsonb_typeof(p_feature_payload -> 'lat') IS DISTINCT FROM 'number' THEN
        RAISE EXCEPTION 'manual Feature payload is not canonical'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_create_payload';
    END IF;
    v_feature_kind := nullif(btrim(p_feature_payload ->> 'kind'), '');
    v_name := nullif(btrim(p_feature_payload ->> 'name'), '');
    IF nullif(btrim(p_feature_payload ->> 'feature_id'), '') IS NULL
       OR v_feature_kind IS NULL OR v_name IS NULL
       OR nullif(btrim(p_feature_payload ->> 'category'), '') IS NULL THEN
        RAISE EXCEPTION 'manual Feature payload lacks required core values'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_create_payload';
    END IF;
    BEGIN
        v_feature_id := (p_feature_payload ->> 'feature_id')::uuid;
        v_lon := (p_feature_payload ->> 'lon')::numeric;
        v_lat := (p_feature_payload ->> 'lat')::numeric;
    EXCEPTION WHEN invalid_text_representation OR numeric_value_out_of_range THEN
        RAISE EXCEPTION 'manual Feature payload has invalid identity values'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_manual_feature_identity_coord_rounding';
    END;
    IF substring(v_feature_id::text FROM 15 FOR 1) <> '7' THEN
        RAISE EXCEPTION 'manual Feature UUID must be UUIDv7'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_manual_feature_create_core_identity';
    END IF;
    SELECT * INTO v_key
    FROM feature.manual_feature_identity_key(v_feature_kind, v_name, v_lon, v_lat);

    INSERT INTO feature.manual_feature_identity_claims (
        feature_id, feature_kind, name_key, lon_e6, lat_e6,
        claimed_by_command_id, claim_basis, claimed_at
    ) VALUES (
        v_feature_id, v_key.feature_kind, v_key.name_key, v_key.lon_e6, v_key.lat_e6,
        p_domain_command_id, 'manual_create', clock_timestamp()
    ) ON CONFLICT (feature_kind, name_key, lon_e6, lat_e6) WHERE NOT identity_released DO NOTHING
    RETURNING feature_id INTO v_claimed_feature_id;

    IF v_claimed_feature_id IS NULL THEN
        SELECT claim.feature_id INTO o_existing_feature_id
        FROM feature.manual_feature_identity_claims AS claim
        WHERE (claim.feature_kind, claim.name_key, claim.lon_e6, claim.lat_e6)
            = (v_key.feature_kind, v_key.name_key, v_key.lon_e6, v_key.lat_e6)
          AND NOT claim.identity_released;
        IF o_existing_feature_id IS NULL THEN
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
        v_created_row_revision,
        v_created
    );
    IF v_created IS DISTINCT FROM true
       OR v_created_feature_id IS DISTINCT FROM v_feature_id
       OR v_created_row_revision IS NULL OR v_created_row_revision < 1 THEN
        RAISE EXCEPTION 'manual Feature core result does not match identity claim'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_manual_feature_create_core_identity';
    END IF;
    INSERT INTO feature.feature_creation_origins (
        feature_id, origin_kind, creation_command_id, creator_principal_id,
        created_by_actor, created_at, invoker_role, procedure_definer
    ) VALUES (
        v_feature_id,
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
    o_row_revision := v_created_row_revision;
END
$$;

DO $t39_owner$
DECLARE
    had_create boolean;
BEGIN
    -- 소유권 이전은 새 소유자가 담는 스키마의 CREATE 권한을 요구한다.
    -- 302_m03_child_issuance.py:324-330이 `ops`에서 같은 함정을 만났다. 다만 그
    -- 형태는 이미 CREATE를 가진 롤에서 권한을 빼앗으므로, 여기서는 **자기 상태를
    -- 보고** 되돌린다. 2026-09-09 n150 첫 실행이 이것을 잡았다
    -- (`permission denied for schema ops`).
    had_create := has_schema_privilege('ktm_manual_feature_procedure_owner', 'feature', 'CREATE');
    IF NOT had_create THEN
        EXECUTE 'GRANT CREATE ON SCHEMA feature TO ktm_manual_feature_procedure_owner';
    END IF;
    EXECUTE 'ALTER PROCEDURE feature.create_admin_manual_feature_with_initial_state(IN p_feature_payload jsonb, IN p_domain_command_id bigint, OUT o_outcome text, OUT o_feature_id uuid, OUT o_row_revision bigint, OUT o_existing_feature_id uuid) OWNER TO ktm_manual_feature_procedure_owner';
    IF NOT had_create THEN
        EXECUTE 'REVOKE CREATE ON SCHEMA feature FROM ktm_manual_feature_procedure_owner';
    END IF;
END
$t39_owner$;

-- head-schema.sql은 이 프로시저에 ACL 블록을 갖지 않는다(덤프 시점 ACL이 기본값 +
-- PUBLIC EXECUTE라 pg_dump가 아무것도 내지 않았다). DROP PROCEDURE가 ACL을 버리고
-- CREATE가 PUBLIC EXECUTE를 다시 심으므로, runtime_privileges.py:617-621의
-- _MANUAL_FEATURE_WRITER_ACL과 같은 문장을 여기서 복원한다.
REVOKE ALL ON PROCEDURE feature.create_admin_manual_feature_with_initial_state(jsonb, bigint) FROM PUBLIC, ktm_feature_runtime, ktm_feature_dagster_runtime, ktm_feature_create_provider_executor;
GRANT EXECUTE ON PROCEDURE feature.create_admin_manual_feature_with_initial_state(jsonb, bigint) TO ktm_manual_feature_admin_executor;

SET ROLE ktm_feature_schema_owner;
