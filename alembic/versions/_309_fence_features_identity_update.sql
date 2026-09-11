CREATE OR REPLACE FUNCTION feature.fence_features_identity_update() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog'
    AS $$
BEGIN
    IF NEW.feature_id IS DISTINCT FROM OLD.feature_id THEN
        RAISE EXCEPTION
            'T-VN-32C legacy write fence: feature identity(feature_id)는 '
            '불변입니다 — 재키잉은 soft-delete + 신규 행으로 표현한다 '
            '(ADR-068).';
    END IF;
    RETURN NEW;
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
    had_create := has_schema_privilege('ktm_feature_schema_owner', 'feature', 'CREATE');
    IF NOT had_create THEN
        EXECUTE 'GRANT CREATE ON SCHEMA feature TO ktm_feature_schema_owner';
    END IF;
    EXECUTE 'ALTER FUNCTION feature.fence_features_identity_update() OWNER TO ktm_feature_schema_owner';
    IF NOT had_create THEN
        EXECUTE 'REVOKE CREATE ON SCHEMA feature FROM ktm_feature_schema_owner';
    END IF;
END
$t39_owner$;

-- **트리거는 이 파일에 없다.** `trg_features_identity_fence`는
-- `BEFORE UPDATE OF feature_id, feature_uuid`라 PostgreSQL이 컬럼 목록의 **각
-- 컬럼에** DEPENDENCY_AUTO를 건다 — 재키가 어느 쪽을 DROP하든 트리거가 오류도
-- 경고도 없이 함께 사라진다. 그래서 재생성을 재키 **뒤**에 놓아야 하고, 그 위치는
-- 마이그레이션 순서의 일부다(`309`의 `_TRIGGER_RECREATE`). 여기서 만들면 새
-- 트리거가 아직 text인 컬럼에 의존을 걸고 곧바로 다시 사라진다.
