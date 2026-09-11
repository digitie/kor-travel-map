-- ADR-098 claim 축 해석기.
--
-- provider 적재는 "이 원천이 이미 Feature를 갖고 있나"를 먼저 물어야 한다. 재키 전에는
-- DTO의 `f_*`를 그대로 `feature.features`에서 찾으면 됐지만, 재키 후 정본 키는
-- `(provider_dataset_id, feature_kind, natural_key)` claim이 쥔다.
--
-- 그 claim 표(`provider_sync.provider_feature_identities`)를 repo가 **직접** 읽으면
-- 안 된다. 이 저장소에서 runtime 롤은 `provider_sync`의 어떤 표에도 직접 접근하지
-- 않는다 — 인벤토리(`src/kortravelmap/infra/runtime_privileges.py`)가 그 스키마의
-- 모든 표를 runtime에서 회수하고 다시 부여하지 않으며, 읽기는 전부 SECURITY DEFINER
-- 루틴을 지난다. 직접 SELECT를 넣으면 통합 테스트(마이그레이터 롤)에서는 통과하고
-- 운영(runtime 롤)에서만 `permission denied`가 난다 — 가장 나쁜 형태다.
--
-- 그래서 해석을 이 함수 안으로 넣는다. definer는 claim 표를 읽을 수 있는
-- `ktm_feature_state_procedure_owner`이고, 호출자는 EXECUTE만 갖는다.

SET ROLE ktm_feature_state_procedure_owner;

CREATE FUNCTION feature.resolve_provider_feature_id(
    p_provider_dataset_id bigint,
    p_feature_kind text,
    p_natural_key text
) RETURNS uuid
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path TO 'pg_catalog'
    AS $$
SELECT claim.feature_id
FROM provider_sync.provider_feature_identities AS claim
WHERE claim.provider_dataset_id = p_provider_dataset_id
  AND claim.feature_kind = p_feature_kind
  AND claim.natural_key = p_natural_key
$$;

ALTER FUNCTION feature.resolve_provider_feature_id(bigint, text, text)
    OWNER TO ktm_feature_state_procedure_owner;

REVOKE ALL ON FUNCTION feature.resolve_provider_feature_id(bigint, text, text) FROM PUBLIC;

-- 부여 대상은 provider 생성 wrapper와 **같은 집합**이다. 둘은 한 쌍으로 쓰인다 —
-- 먼저 claim을 풀어 존재를 묻고, 없으면 wrapper로 만든다. 한쪽만 부를 수 있는 롤이
-- 있으면 적재가 반쪽으로 죽는다.
--
-- `has_active_feature_override`처럼 REVOKE만 두는 형제들과 다른 이유: 그것들은 다른
-- SECURITY DEFINER 프로시저 **안에서** 불려 definer 권한으로 돌지만, 이 함수는
-- 파이썬 repo가 직접 부른다.
GRANT EXECUTE ON FUNCTION feature.resolve_provider_feature_id(bigint, text, text)
    TO ktm_feature_create_provider_executor;
GRANT EXECUTE ON FUNCTION feature.resolve_provider_feature_id(bigint, text, text)
    TO ktm_feature_runtime;

SET ROLE ktm_feature_schema_owner;
