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


ALTER FUNCTION feature.has_active_feature_override(p_feature_id uuid, p_field_path text) OWNER TO ktm_feature_state_procedure_owner;

-- head-schema.sql:25012는 REVOKE만 있고 GRANT가 없다 — runtime login이 이
-- SECURITY DEFINER 함수를 EXECUTE할 수 있으면 db.py preflight가
-- 'unexpected SECURITY DEFINER functions'로 기동을 막는다.
REVOKE ALL ON FUNCTION feature.has_active_feature_override(p_feature_id uuid, p_field_path text) FROM PUBLIC;
