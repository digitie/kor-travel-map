-- 보조 relation에 `public_ready` 파생 트리거를 붙인다.
--
-- 판정: 신설 트리거 + 그것을 위한 **일시적** EXECUTE 창
--
-- ## 왜 표 사이드카에서 분리했는가 — 통합 DB에서는 안 보이는 결함
--
-- `CREATE TRIGGER ... EXECUTE FUNCTION f()`는 **생성 시점에** `f`에 대한 EXECUTE를
-- 요구한다. 트리거를 만들 수 있는 것은 표 소유자(`ktm_feature_schema_owner`)인데,
-- `feature.derive_subtype_public_ready`의 소유자는
-- `ktm_feature_state_procedure_owner`다.
--
-- 갓 만든 DB에서는 이것이 문제가 되지 않는다. 함수의 ACL이 **기본값**이라
-- (`pg_proc.proacl IS NULL`) PUBLIC이 EXECUTE를 갖고, 스키마 소유자도 그 PUBLIC으로
-- 통과한다. 그래서 통합 스위트와 fresh 300 경로는 이 문장을 그냥 지나간다.
--
-- 그런데 런타임 권한 조정기가
-- `REVOKE ALL ON FUNCTION feature.derive_subtype_public_ready(...) FROM PUBLIC, ...`
-- 을 낸다(`runtime_privileges.py`의 `_SUBTYPE_READY_FUNCTION_ACL`). **조정기가 한 번이라도
-- 돈 DB**는 ACL이 명시 목록으로 굳어 PUBLIC 경로가 사라진다. 그 DB에서 이 문장은
-- `42501 permission denied for function feature.derive_subtype_public_ready`로 죽는다.
--
-- 2026-09-20 격리 live 스택(`~/ktm-live-301`)에 이 revision을 올리다 실측했다.
-- **통합 게이트 1,173건은 전부 초록이었다** — 갓 만든 DB에는 없는 상태이기 때문이다.
--
-- **범위를 정확히 적는다.** 지금의 운영 배포 경로(`chain17` → `rebuild-pinned`)는
-- DB를 `dropdb`/`createdb`로 다시 만들고 그 위에 마이그레이션을 올린다 — 그 순간
-- ACL은 기본값이므로 이 자리에서 멎지 않는다. 막히는 것은 **제자리 업그레이드**다:
-- 격리 live 스택, 그리고 재구축을 건너뛴 어떤 배포든. 그 경로가 실재하고(방금 그것을
-- 밟았다) 고치는 비용이 새 설치에서 0이므로 여기서 닫는다.
--
-- ## 창을 빌리고 **되돌려 놓는다**
--
-- 함수 소유자만 EXECUTE를 줄 수 있으므로 그 롤로 잠깐 들어가 부여하고, 트리거를
-- 만든 뒤 **빌린 만큼만** 돌려준다.
--
-- 무조건 `GRANT`/`REVOKE`를 내면 안 된다. ACL이 기본값(NULL)인 DB에서는 `GRANT` 하나가
-- 그 NULL을 명시 배열로 **구체화**하고, 뒤이은 `REVOKE`는 `{owner=X/owner}`를 남긴다 —
-- 즉 아무 일도 안 해야 할 곳에서 카탈로그가 바뀐다. 그래서 둘 다 조건부로 내고,
-- 부여했는지 여부를 트랜잭션 지역 GUC에 적어 두 문장이 짝을 맞춘다.
--
-- 새 설치(300 → 312)는 두 조건 모두 거짓이라 ACL을 **한 바이트도** 건드리지 않는다.

SET ROLE ktm_feature_state_procedure_owner;

DO $borrow_execute$
BEGIN
    IF has_function_privilege(
        'ktm_feature_schema_owner',
        'feature.derive_subtype_public_ready()',
        'EXECUTE'
    ) THEN
        PERFORM set_config('ktm312.borrowed_execute', 'no', true);
    ELSE
        EXECUTE 'GRANT EXECUTE ON FUNCTION feature.derive_subtype_public_ready() '
                'TO ktm_feature_schema_owner';
        PERFORM set_config('ktm312.borrowed_execute', 'yes', true);
    END IF;
END
$borrow_execute$;

SET ROLE ktm_feature_schema_owner;

-- **이것이 없으면 `public_ready`가 영원히 false로 남는다.** 공개 bbox 술어
-- (`WHERE bbox_hit_route.public_ready`)가 route를 한 건도 못 고르고, coord arm은
-- `kind NOT IN ('route','area')`로 route를 명시 배제하므로 대체 경로도 없다 —
-- 오류 없이 결과만 0건이라 조용하다.
--
-- provider가 넣는 feature는 DTO 기본값이 active/published/valid라 **core 3축을 바꾸는
-- UPDATE가 일어나지 않고**, 그래서 AFTER UPDATE 트리거(`sync_subtype_public_ready`)는
-- 영원히 발화하지 않는다. 값을 채우는 것은 INSERT 시점의 이 BEFORE 트리거다
-- (2026-09-19 적대 리뷰가 blocker로 잡았다).
--
-- `feature_routes`·`feature_areas`에 붙은 것과 **같은 함수**를 쓴다. 그 함수가 보는
-- 것은 `NEW.feature_id`/`NEW.kind`/`NEW.public_ready`뿐이고 셋 다 이 표에 있다.
CREATE TRIGGER trg_feature_route_geometries_public_ready
    BEFORE INSERT OR UPDATE ON feature.feature_route_geometries
    FOR EACH ROW EXECUTE FUNCTION feature.derive_subtype_public_ready();

SET ROLE ktm_feature_state_procedure_owner;

DO $return_execute$
BEGIN
    IF current_setting('ktm312.borrowed_execute', true) = 'yes' THEN
        EXECUTE 'REVOKE EXECUTE ON FUNCTION feature.derive_subtype_public_ready() '
                'FROM ktm_feature_schema_owner';
    END IF;
END
$return_execute$;

SET ROLE ktm_feature_schema_owner;
