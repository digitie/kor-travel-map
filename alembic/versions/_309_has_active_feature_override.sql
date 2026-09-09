-- 인자 타입이 바뀌므로 CREATE OR REPLACE가 거부한다(다른 함수로 취급된다).
DROP FUNCTION feature.has_active_feature_override(text, text);

CREATE FUNCTION feature.has_active_feature_override(p_feature_id uuid, p_field_path text) RETURNS boolean
    LANGUAGE sql SECURITY DEFINER
    SET search_path TO 'pg_catalog'
    AS $$
    SELECT EXISTS (
        SELECT 1
        FROM ops.feature_overrides AS override
        WHERE override.feature_id = p_feature_id
          AND override.field_path = p_field_path
          AND override.status = 'active'
    );
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
    EXECUTE 'ALTER FUNCTION feature.has_active_feature_override(p_feature_id uuid, p_field_path text) OWNER TO ktm_feature_state_procedure_owner';
    IF NOT had_create THEN
        EXECUTE 'REVOKE CREATE ON SCHEMA feature FROM ktm_feature_state_procedure_owner';
    END IF;
END
$t39_owner$;

-- head-schema.sql:25012는 REVOKE만 있고 GRANT가 없다 — runtime login이 이
-- SECURITY DEFINER 함수를 EXECUTE할 수 있으면 db.py preflight가
-- 'unexpected SECURITY DEFINER functions'로 기동을 막는다.
REVOKE ALL ON FUNCTION feature.has_active_feature_override(p_feature_id uuid, p_field_path text) FROM PUBLIC;
