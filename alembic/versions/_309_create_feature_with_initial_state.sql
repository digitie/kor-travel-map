SET ROLE ktm_feature_state_procedure_owner;

-- OUT 목록이 바뀌면 반환 record 타입이 바뀌므로 CREATE OR REPLACE가 거부한다.
DROP PROCEDURE feature.create_feature_with_initial_state(jsonb, text, text, text, jsonb);

CREATE PROCEDURE feature.create_feature_with_initial_state(IN p_feature jsonb, IN p_lifecycle_state text, IN p_publication_state text, IN p_quality_state text, IN p_context jsonb, OUT o_feature_id uuid, OUT o_row_revision bigint, OUT o_inserted boolean)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog'
    AS $$
DECLARE
    v_feature_id uuid;
    v_kind text;
    v_name text;
    v_category text;
    v_coord feature.features.coord%TYPE;
BEGIN
    IF jsonb_typeof(p_feature) IS DISTINCT FROM 'object' THEN
        RAISE EXCEPTION 'feature payload must be an object'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_create_payload';
    END IF;
    IF EXISTS (
        SELECT 1 FROM jsonb_object_keys(p_feature) AS key_name(key_name)
        WHERE key_name NOT IN (
            'feature_id', 'kind', 'name', 'category',
            'lon', 'lat', 'coord_precision_digits', 'address',
            'legal_dong_code', 'road_name_code', 'road_address_management_no',
            'admin_dong_code', 'sido_code', 'sigungu_code', 'urls',
            'marker_icon', 'marker_color', 'parent_feature_id', 'sibling_group_id',
            'raw_refs'
        )
    ) THEN
        RAISE EXCEPTION 'feature create payload contains an unknown field'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_create_payload';
    END IF;
    IF (p_feature ? 'address' AND jsonb_typeof(p_feature -> 'address') IS DISTINCT FROM 'object')
       OR (p_feature ? 'urls' AND jsonb_typeof(p_feature -> 'urls') IS DISTINCT FROM 'object')
       OR (p_feature ? 'raw_refs' AND jsonb_typeof(p_feature -> 'raw_refs') IS DISTINCT FROM 'array') THEN
        RAISE EXCEPTION 'feature create payload has an invalid JSON field shape'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_create_payload';
    END IF;
    v_feature_id := nullif(btrim(p_feature ->> 'feature_id'), '')::uuid;
    v_kind := nullif(btrim(p_feature ->> 'kind'), '');
    v_name := nullif(btrim(p_feature ->> 'name'), '');
    v_category := nullif(btrim(p_feature ->> 'category'), '');
    IF v_feature_id IS NULL OR v_kind IS NULL OR v_name IS NULL OR v_category IS NULL THEN
        RAISE EXCEPTION 'feature create payload lacks required core fields'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_create_payload';
    END IF;
    IF (p_feature ? 'lon') <> (p_feature ? 'lat') THEN
        RAISE EXCEPTION 'feature coordinate requires both lon and lat'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_create_payload';
    END IF;
    IF p_feature ? 'lon' THEN
        v_coord := x_extension.st_setsrid(
            x_extension.st_makepoint(
                (p_feature ->> 'lon')::double precision,
                (p_feature ->> 'lat')::double precision
            ),
            4326
        );
    END IF;

    PERFORM feature.prepare_feature_state_context(p_context, 'create');
    -- Provider source writers advance an entity head before they create/update
    -- the Feature in the same transaction.  Take the identical locked proof
    -- before this INSERT, so the initial audit can never claim a record that
    -- stopped being current before this transaction commits.
    IF p_context ->> 'transition_kind' = 'provider_sync' THEN
        PERFORM feature.lock_current_provider_source_evidence(
            (p_context ->> 'provider_dataset_id')::bigint,
            p_context ->> 'source_entity_key',
            p_context ->> 'source_record_key'
        );
    END IF;
    INSERT INTO feature.features (
        feature_id, kind, name, category,
        coord, coord_precision_digits,
        address, legal_dong_code, road_name_code, road_address_management_no,
        admin_dong_code, sido_code, sigungu_code,
        urls, marker_icon, marker_color, parent_feature_id, sibling_group_id,
        raw_refs, lifecycle_state, publication_state, quality_state,
        created_at, updated_at
    ) VALUES (
        v_feature_id, v_kind, v_name,
        v_category, v_coord, (p_feature ->> 'coord_precision_digits')::smallint,
        coalesce(p_feature -> 'address', '{}'::jsonb), p_feature ->> 'legal_dong_code',
        p_feature ->> 'road_name_code', p_feature ->> 'road_address_management_no',
        p_feature ->> 'admin_dong_code', p_feature ->> 'sido_code', p_feature ->> 'sigungu_code',
        coalesce(p_feature -> 'urls', '{}'::jsonb), p_feature ->> 'marker_icon', p_feature ->> 'marker_color',
        nullif(p_feature ->> 'parent_feature_id', '')::uuid, nullif(p_feature ->> 'sibling_group_id', '')::uuid,
        coalesce(p_feature -> 'raw_refs', '[]'::jsonb), p_lifecycle_state,
        p_publication_state, p_quality_state,
        clock_timestamp(), clock_timestamp()
    ) ON CONFLICT (feature_id) DO NOTHING
    RETURNING feature_id, row_revision
         INTO o_feature_id, o_row_revision;

    o_inserted := FOUND;
    IF NOT o_inserted THEN
        SELECT feature_id, row_revision
          INTO o_feature_id, o_row_revision
          FROM feature.features
         WHERE feature_id = v_feature_id;
    END IF;
END;
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
    had_create := has_schema_privilege('ktm_feature_state_procedure_owner', 'feature', 'CREATE');
    IF NOT had_create THEN
        EXECUTE 'GRANT CREATE ON SCHEMA feature TO ktm_feature_state_procedure_owner';
    END IF;
    EXECUTE 'ALTER PROCEDURE feature.create_feature_with_initial_state(IN p_feature jsonb, IN p_lifecycle_state text, IN p_publication_state text, IN p_quality_state text, IN p_context jsonb, OUT o_feature_id uuid, OUT o_row_revision bigint, OUT o_inserted boolean) OWNER TO ktm_feature_state_procedure_owner';
    IF NOT had_create THEN
        EXECUTE 'REVOKE CREATE ON SCHEMA feature FROM ktm_feature_state_procedure_owner';
    END IF;
END
$t39_owner$;

-- DROP PROCEDURE가 ACL을 통째로 버린다. head-schema.sql:24957-24959의 세 GRANT을
-- 새 시그니처로 되살린다.
GRANT ALL ON PROCEDURE feature.create_feature_with_initial_state(IN p_feature jsonb, IN p_lifecycle_state text, IN p_publication_state text, IN p_quality_state text, IN p_context jsonb, OUT o_feature_id uuid, OUT o_row_revision bigint, OUT o_inserted boolean) TO ktm_manual_feature_procedure_owner;
GRANT ALL ON PROCEDURE feature.create_feature_with_initial_state(IN p_feature jsonb, IN p_lifecycle_state text, IN p_publication_state text, IN p_quality_state text, IN p_context jsonb, OUT o_feature_id uuid, OUT o_row_revision bigint, OUT o_inserted boolean) TO ktm_curation_command_owner;
GRANT ALL ON PROCEDURE feature.create_feature_with_initial_state(IN p_feature jsonb, IN p_lifecycle_state text, IN p_publication_state text, IN p_quality_state text, IN p_context jsonb, OUT o_feature_id uuid, OUT o_row_revision bigint, OUT o_inserted boolean) TO ktm_feature_request_procedure_owner;

-- CREATE PROCEDURE는 PUBLIC에 EXECUTE를 기본 부여한다. src/kortravelmap/infra/db.py:585
-- preflight("API runtime must not EXECUTE create_feature_with_initial_state directly")가
-- 그 상태를 거부하므로 runtime_privileges.py:351-353·369-371과 같은 문장을 함께 되살린다.
REVOKE ALL ON PROCEDURE feature.create_feature_with_initial_state(jsonb, text, text, text, jsonb) FROM PUBLIC, ktm_feature_runtime, ktm_feature_api_runtime;
GRANT EXECUTE ON PROCEDURE feature.create_feature_with_initial_state(jsonb, text, text, text, jsonb) TO ktm_feature_create_provider_executor, ktm_manual_feature_procedure_owner;

SET ROLE ktm_feature_schema_owner;
