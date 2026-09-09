-- 이 사이드카는 자기 역할 창을 스스로 연다.
--
-- 바깥에서 `SET ROLE`로 묶으면 순서에 결박된다 — 자기 창을 가진 사이드카가 끝에서
-- 스키마 소유자로 되돌리는 순간, 뒤따르는 파일은 바깥 그룹이 지정한 롤이 아니라
-- 스키마 소유자로 실행된다. 2026-09-09 n150 실행이 그것을 잡았다
-- (`must be owner of function derive_subtype_public_ready`).
--
-- 롤은 NOINHERIT라 멤버십만으로는 소유자 검사를 통과하지 못한다. `feature` 스키마는
-- 모든 소유자 롤이 `ALL`을 가지므로(alembic/head-schema.sql:24731-24737) 이 창 안에서
-- DROP·CREATE·GRANT가 모두 성립한다.
SET ROLE ktm_manual_feature_procedure_owner;

CREATE OR REPLACE FUNCTION feature.reject_manual_feature_hard_purge() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog'
    AS $$
DECLARE
    v_claim feature.manual_feature_identity_claims%ROWTYPE;
BEGIN
    SELECT * INTO v_claim
    FROM feature.manual_feature_identity_claims AS claim
    WHERE claim.feature_id = OLD.feature_id;
    IF NOT FOUND THEN
        RETURN OLD;
    END IF;
    IF v_claim.purged_by_command_id IS NULL THEN
        RAISE EXCEPTION 'manual Feature delete needs an authorised purge command'
            USING ERRCODE = '23514',
                CONSTRAINT = 'ck_manual_feature_purge_unauthorised';
    END IF;
    RETURN OLD;
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
    EXECUTE 'ALTER FUNCTION feature.reject_manual_feature_hard_purge() OWNER TO ktm_manual_feature_procedure_owner';
    IF NOT had_create THEN
        EXECUTE 'REVOKE CREATE ON SCHEMA feature FROM ktm_manual_feature_procedure_owner';
    END IF;
END
$t39_owner$;

SET ROLE ktm_feature_schema_owner;
