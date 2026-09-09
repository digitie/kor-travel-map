CREATE FUNCTION feature.fence_features_identity_update() RETURNS trigger
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

-- T-VN-39: head 21795의 트리거는 `BEFORE UPDATE OF feature_id, feature_uuid`다.
-- PostgreSQL은 컬럼 목록의 각 컬럼에 트리거→컬럼 DEPENDENCY_AUTO를 기록하므로,
-- 재키가 text `feature_id`를 DROP하든 `feature_uuid`를 DROP하든 이 트리거가
-- CASCADE 없이 함께 삭제된다(오류도 경고도 없다). 함수만 재정의하면 fence가
-- 사라진 채 남으므로 같은 트랜잭션에서 축소된 컬럼 목록으로 재생성한다.
DROP TRIGGER IF EXISTS trg_features_identity_fence ON feature.features;
CREATE TRIGGER trg_features_identity_fence BEFORE UPDATE OF feature_id ON feature.features FOR EACH ROW EXECUTE FUNCTION feature.fence_features_identity_update();
