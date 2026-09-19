-- feature.sync_subtype_public_ready — 보조 relation의 public_ready도 함께 민다.
--
-- 판정: 교체(UPDATE 대상 추가 한정)
--
-- ## 왜 이 사이드카가 자기 역할 창을 여는가
--
-- 이 함수의 소유자는 `ktm_feature_state_procedure_owner`인데 312의 나머지 문장은
-- `ktm_feature_schema_owner` 창에서 돈다. ADR-090의 롤은 전부 `NOINHERIT`이라
-- **멤버십만으로는 소유자 검사를 통과하지 못한다** — 2026-09-19 n150 첫 실행이
-- `must be owner of function sync_subtype_public_ready`로 죽었다.
--
-- `_309_derive_subtype_public_ready.sql`이 2026-09-09에 같은 오류를 겪고 같은 답을
-- 적어 두었다. 그 파일의 경고도 함께 지킨다 — **창을 열었으면 닫는다.** 자기 창을
-- 연 사이드카가 스키마 소유자로 되돌리지 않고 끝나면, 뒤따르는 문장이 바깥 그룹이
-- 지정한 롤이 아니라 이 롤로 실행된다.
--
-- ## 무엇이 바뀌는가
--
-- `UPDATE` 대상이 하나 는다. ADR-099 2단계에서 route geometry가
-- `feature.feature_route_geometries`로 갔고, 공개 bbox 후보 술어가
-- `WHERE public_ready` partial GiST를 **조인 없이** 타려면 그 술어 컬럼이
-- geometry와 같은 행에 있어야 하기 때문이다.
--
-- **순서를 subtype → geometry로 고정한다.** 재적재 경로
-- (`feature_subtype.write_subtype`)도 같은 순서로 두 문장을 낸다 — 두 경로의 잠금
-- 순서가 반대면 40P01 교착 창이 열린다.
--
-- `IS DISTINCT FROM` 가드는 셋 다 그대로다. 값이 같으면 쓰지 않는다.

SET ROLE ktm_feature_state_procedure_owner;

CREATE OR REPLACE FUNCTION feature.sync_subtype_public_ready() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog'
    AS $$
DECLARE
    v_public_ready boolean;
BEGIN
    -- The UPDATE which invoked this trigger already holds NEW's parent row
    -- lock.  Keep it until the subtype cache rows have been refreshed.
    v_public_ready := NEW.lifecycle_state = 'active'
        AND NEW.publication_state = 'published'
        AND NEW.quality_state = 'valid';

    UPDATE feature.feature_routes
       SET public_ready = v_public_ready
     WHERE feature_id = NEW.feature_id
       AND public_ready IS DISTINCT FROM v_public_ready;
    UPDATE feature.feature_route_geometries
       SET public_ready = v_public_ready
     WHERE feature_id = NEW.feature_id
       AND public_ready IS DISTINCT FROM v_public_ready;
    UPDATE feature.feature_areas
       SET public_ready = v_public_ready
     WHERE feature_id = NEW.feature_id
       AND public_ready IS DISTINCT FROM v_public_ready;
    RETURN NULL;
END;
$$;

SET ROLE ktm_feature_schema_owner;
