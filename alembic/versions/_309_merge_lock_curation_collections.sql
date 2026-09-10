-- merge가 canonical collection을 잠그는 창. T-VN-39 재키의 **네 번째** 범위 누락이다.
--
-- 앞의 셋과 다른 이유로 놓쳤다. `test_feature_identifier_arguments_are_uuid.py`는
-- 인자 **이름**이 feature 식별자로 읽히는지를 봤는데, 이 프로시저의 인자는
-- `p_master`/`p_loser`다 — 이름에 `feature_id`가 없다. 그래서 검사의 시야 밖에
-- 있었다. 본문은 그 인자를 `feature.curation_items.feature_id`(재키 후 uuid)와
-- 직접 비교한다:
--
--     WHERE item.feature_id IN (p_master, p_loser)
--
-- 재키 뒤 이것은 42883 `operator does not exist: uuid = text`다. merge 전체가
-- 첫 CALL에서 선다.
--
-- 이름이 아니라 **본문**이 오라클이다. 그 눈은
-- `test_routine_text_arguments_never_meet_uuid_columns.py`가 갖는다.
--
-- 롤은 NOINHERIT라 멤버십만으로는 소유자 검사를 통과하지 못한다. `feature` 스키마는
-- 모든 소유자 롤이 `ALL`을 가지므로(alembic/head-schema.sql:24731-24737) 이 창 안에서
-- DROP·CREATE·GRANT가 모두 성립한다.
SET ROLE ktm_curation_command_owner;

DROP PROCEDURE feature.merge_lock_curation_collections(text, text);

CREATE PROCEDURE feature.merge_lock_curation_collections(IN p_master uuid, IN p_loser uuid)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'feature', 'ops', 'x_extension'
    AS $$
BEGIN
    -- 0214와 같은 executor 게이트. admin executor(api runtime이 상속)만 부를 수 있고
    -- provider executor(dagster runtime)는 거부한다. EXECUTE grant와 이중이다.
    IF NOT pg_has_role(session_user, 'ktm_curation_admin_executor', 'member')
       OR pg_has_role(session_user, 'ktm_curation_provider_executor', 'member') THEN
        RAISE EXCEPTION 'merge command requires the admin executor'
            USING ERRCODE = '42501';
    END IF;
    PERFORM collection.collection_id
    FROM feature.curation_collections AS collection
    WHERE EXISTS (
        SELECT 1
        FROM feature.curation_items AS item
        WHERE item.collection_id = collection.collection_id
          AND item.feature_id IN (p_master, p_loser)
    )
    ORDER BY collection.collection_id
    FOR UPDATE OF collection;
END;
$$;

ALTER PROCEDURE feature.merge_lock_curation_collections(IN p_master uuid, IN p_loser uuid)
    OWNER TO ktm_curation_command_owner;

REVOKE ALL ON PROCEDURE feature.merge_lock_curation_collections(IN p_master uuid, IN p_loser uuid) FROM PUBLIC;
GRANT ALL ON PROCEDURE feature.merge_lock_curation_collections(IN p_master uuid, IN p_loser uuid) TO ktm_curation_admin_executor;

SET ROLE ktm_feature_schema_owner;
