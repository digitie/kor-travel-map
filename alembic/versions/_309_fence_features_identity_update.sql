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


ALTER FUNCTION feature.fence_features_identity_update() OWNER TO ktm_feature_schema_owner;

-- **트리거는 이 파일에 없다.** `trg_features_identity_fence`는
-- `BEFORE UPDATE OF feature_id, feature_uuid`라 PostgreSQL이 컬럼 목록의 **각
-- 컬럼에** DEPENDENCY_AUTO를 건다 — 재키가 어느 쪽을 DROP하든 트리거가 오류도
-- 경고도 없이 함께 사라진다. 그래서 재생성을 재키 **뒤**에 놓아야 하고, 그 위치는
-- 마이그레이션 순서의 일부다(`309`의 `_TRIGGER_RECREATE`). 여기서 만들면 새
-- 트리거가 아직 text인 컬럼에 의존을 걸고 곧바로 다시 사라진다.
