-- T-VN-39 / ADR-098 — provider Feature identity의 착지처.
--
-- 재키가 `ON CONFLICT (feature_id) DO NOTHING`의 결정적 축을 없앤다. writer가 매 호출
-- 새 UUIDv7을 만들기 때문이다. 이 wrapper가 그 자리를 받는다 —
-- `(provider_dataset_id, feature_kind, natural_key)`로 identity를 **먼저 claim**하고,
-- 그 uuid로 core를 만들고, 결과가 claim과 같은지 검증한다.
--
-- manual 세 형제(`create_admin_manual_feature_with_initial_state` ·
-- `create_manual_curation_item_with_feature_command` ·
-- `approve_feature_request_with_initial_state`)가 이미 같은 삼단으로 산다. provider가
-- 네 번째 형제를 갖는 것이고, 그 대칭은 claim 표가 `feature.features`로 가는 FK를
-- **갖지 않는다**는 점까지 같다(claim이 Feature보다 먼저 서야 한다).
--
-- 왜 `f_*`를 축으로 쓰지 않는가: `make_feature_id`가 `bjd_code`·`category`를 해시
-- 입력에 쓰는데, ADR-068 결정 2가 그 둘을 identity 입력에서 **배제하라**고 정했다.
-- 그리고 `source_entity_key`도 축이 될 수 없다 — `providers/opinet.py`에서 한 주유소가
-- 제품코드마다 다른 entity를 갖고 그 가격들이 같은 anchor Feature에 누적된다(N:1).
--
-- `f_*`는 여기서 **alias**로만 쓰인다. 재분류로 그 값이 바뀌면 alias가 한 행 늘 뿐
-- Feature는 갈라지지 않는다 — 오늘은 갈라지고 뒤처리 기계가 필요했다.

SET ROLE ktm_feature_state_procedure_owner;

CREATE PROCEDURE feature.create_provider_feature_with_initial_state(IN p_feature_payload jsonb, IN p_identity jsonb, IN p_lifecycle_state text, IN p_publication_state text, IN p_quality_state text, IN p_context jsonb, OUT o_feature_id uuid, OUT o_row_revision bigint, OUT o_inserted boolean)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog'
    AS $$
DECLARE
    v_dataset_id bigint;
    v_kind text;
    v_natural text;
    v_alias text;
    v_candidate uuid;
    v_claimed uuid;
    v_created uuid;
    v_created_inserted boolean;
BEGIN
    v_dataset_id := nullif(btrim(p_identity ->> 'provider_dataset_id'), '')::bigint;
    v_kind := nullif(btrim(p_identity ->> 'feature_kind'), '');
    v_natural := nullif(btrim(p_identity ->> 'natural_key'), '');
    v_alias := nullif(btrim(p_identity ->> 'legacy_alias'), '');

    IF v_dataset_id IS NULL OR v_kind IS NULL OR v_natural IS NULL OR v_alias IS NULL THEN
        RAISE EXCEPTION
            'provider Feature identity is incomplete — dataset/kind/natural_key/alias가 모두 필요하다'
            USING ERRCODE = '23514',
                  CONSTRAINT = 'ck_provider_feature_identity_complete';
    END IF;

    -- claim이 직렬화 지점이다. 같은 축을 동시에 적재하는 둘 중 하나만 INSERT에
    -- 성공하고, 진 쪽은 아래 재조회로 이긴 쪽의 uuid를 받는다.
    v_candidate := feature.uuid_generate_v7();
    INSERT INTO provider_sync.provider_feature_identities
        (provider_dataset_id, feature_kind, natural_key, feature_id, bound_by_operation)
    VALUES (v_dataset_id, v_kind, v_natural, v_candidate, 'provider_sync')
    ON CONFLICT (provider_dataset_id, feature_kind, natural_key) DO NOTHING
    RETURNING feature_id INTO v_claimed;

    IF v_claimed IS NULL THEN
        -- 이미 claim이 있다 = 이 원천은 전에 적재됐다. **제자리 갱신 경로**다.
        -- READ COMMITTED에서 `DO NOTHING`은 미커밋 동시 행을 기다리지 않으므로,
        -- 여기서 못 찾으면 조용히 통과시키지 않고 재시도 가능한 오류로 올린다.
        SELECT claim.feature_id INTO v_claimed
        FROM provider_sync.provider_feature_identities AS claim
        WHERE (claim.provider_dataset_id, claim.feature_kind, claim.natural_key)
            = (v_dataset_id, v_kind, v_natural);
        IF v_claimed IS NULL THEN
            RAISE EXCEPTION
                'provider Feature identity claim raced a concurrent writer'
                USING ERRCODE = '40001',
                      CONSTRAINT = 'ck_provider_feature_identity_race';
        END IF;
    END IF;

    -- 재분류가 만든 새 `f_*`도 같은 Feature의 주소로 남는다. Feature는 갈라지지 않는다.
    -- `DO UPDATE`를 쓰면 안 된다 — `fence_feature_aliases_write()`가 alias 행의
    -- UPDATE를 무조건 거부한다(행 불변, ADR-068).
    INSERT INTO feature.feature_aliases (alias, feature_id, alias_kind)
    VALUES (v_alias, v_claimed, 'legacy_feature_id')
    ON CONFLICT (alias) DO NOTHING;

    CALL feature.create_feature_with_initial_state(
        p_feature_payload || jsonb_build_object('feature_id', v_claimed::text),
        p_lifecycle_state,
        p_publication_state,
        p_quality_state,
        p_context,
        v_created,
        o_row_revision,
        v_created_inserted
    );

    -- core가 claim과 다른 identity를 돌려주면 그것은 조용한 손상이다.
    -- manual 세 형제가 같은 규율로 산다("core result does not match identity claim").
    IF v_created IS DISTINCT FROM v_claimed THEN
        RAISE EXCEPTION
            'provider Feature core result does not match identity claim (claim=%, core=%)',
            v_claimed, v_created
            USING ERRCODE = '23514',
                  CONSTRAINT = 'ck_provider_feature_create_core_identity';
    END IF;

    o_feature_id := v_claimed;
    o_inserted := v_created_inserted;
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
    had_create := has_schema_privilege('ktm_feature_state_procedure_owner', 'feature', 'CREATE');
    IF NOT had_create THEN
        EXECUTE 'GRANT CREATE ON SCHEMA feature TO ktm_feature_state_procedure_owner';
    END IF;
    EXECUTE 'ALTER PROCEDURE feature.create_provider_feature_with_initial_state(jsonb, jsonb, text, text, text, jsonb) OWNER TO ktm_feature_state_procedure_owner';
    IF NOT had_create THEN
        EXECUTE 'REVOKE CREATE ON SCHEMA feature FROM ktm_feature_state_procedure_owner';
    END IF;
END
$t39_owner$;

REVOKE ALL ON PROCEDURE feature.create_provider_feature_with_initial_state(jsonb, jsonb, text, text, text, jsonb) FROM PUBLIC;

GRANT ALL ON PROCEDURE feature.create_provider_feature_with_initial_state(jsonb, jsonb, text, text, text, jsonb) TO ktm_feature_create_provider_executor;

SET ROLE ktm_feature_schema_owner;
