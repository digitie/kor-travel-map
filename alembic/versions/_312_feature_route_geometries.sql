-- route geometry를 전용 PostGIS relation으로 옮긴다 (ADR-099 2단계).
--
-- 판정: 신설 + 이전 + 구 컬럼 제거
--
-- ## 왜 옮기는가 — 크기 압박이 아니다
--
-- 크기 천장은 311(fold를 행별 digest로)이 이미 닫았다. 그러므로 이 단계는 **자기
-- 근거**로 선다.
--
--   route 1건의 to_jsonb 평균           43 kB
--   그중 geometry                        98.5%
--   geom 제외                            633 B
--
-- `to_jsonb(route)`는 봉인 말고도 두 곳이 더 쓴다 —
-- `feature.current_theme_candidate_snapshot`의 `candidate_input_hash` 계산과,
-- admin 후보 목록 API 응답(**페이지당 N×43 kB**). 행을 좁히면 그 둘이 함께 줄어든다.
--
-- (2026-09-20 정정: 초안은 `match_evidence`가 그 43 kB를 영구 저장한다고 적었으나
-- 그 컬럼에는 detail이 들어가지 않는다. 적대 리뷰가 잡았다.)
--
-- ## ADR-086이 세운 불변식을 어떻게 지키는가
--
-- `0087_route_area_subtypes`가 geometry를 subtype으로 옮긴 이유는 성능이 아니라
-- **"geometry가 필수인 kind와 없어야 하는 kind가 술어가 아니라 테이블 구조로
-- 갈린다"**였다. 보조 relation은 "geometry 없는 route"를 다시 표현 가능하게 만든다.
--
-- 그래서 `feature_routes.feature_id`에 보조 relation을 가리키는 **DEFERRABLE
-- INITIALLY DEFERRED** FK를 건다. 한 트랜잭션 안에서는 어느 순서로 넣어도 되고,
-- COMMIT 시점에 "geometry 없는 route 행"이 있으면 23503으로 거절된다.
-- DEFERRABLE이어야 하는 이유가 하나 더 있다 — feature purge가 CASCADE로 두 표를
-- 지울 때 중간 상태가 잠시 위반이 된다.
--
-- ## FK는 feature_routes가 아니라 feature.features를 직접 가리킨다
--
-- purge 증거 포획(`_309_purge_manual_feature.sql`)이
-- `confrelid = 'feature.features'::regclass` **한 단계만** 훑는다. `feature_routes`에
-- 매달면 2단 CASCADE로 지워지되 `ops.manual_feature_purge_records.captured_rows`에
-- 남지 않아 복구점이 조용히 불완전해진다.
--
-- ## geom_digest는 생성 컬럼이다
--
-- geometry가 `to_jsonb(route)`에서 빠지면 봉인이 geometry 변경을 더는 못 본다.
-- 그 자리를 고정폭 지문으로 메우는데, **동기화할 코드를 만들지 않는다** —
-- `x_extension.digest`와 `x_extension.ST_AsEWKB`가 둘 다 IMMUTABLE임을 실측으로
-- 확인했으므로(`pg_proc.provolatile = 'i'`) `GENERATED ALWAYS AS ... STORED`가
-- 성립한다. DB가 유지하므로 트리거도, 이중 해시 식도, 직접 `UPDATE ... SET geom`
-- 경로의 누락도 없다.
--
-- ## public_ready는 복제한다
--
-- 공개 bbox 후보 술어가 `WHERE public_ready` partial GiST를 타는 것이 ADR-086
-- 결정 5의 핵심 성질이다(뷰의 geom을 술어에 쓰면 Hash Left Join 2단으로 퇴화함을
-- 그 ADR이 EXPLAIN으로 실측했다). 그 성질을 보존하려면 술어 컬럼이 geometry와
-- **같은 행**에 있어야 한다. 갱신은 기존 트리거 둘이 그대로 맡는다.

SET ROLE ktm_feature_schema_owner;

-- **head 기준으로 쓴다.** 309가 `feature_id`를 uuid로 재키하면서 shadow
-- `feature_uuid` 컬럼을 지웠다 — baseline(rev 300)의 모양이 아니라
-- `alembic/head-schema.sql`의 `feature.feature_routes`를 그대로 따른다.
CREATE TABLE feature.feature_route_geometries (
    feature_id uuid NOT NULL,
    kind character varying NOT NULL,
    geom x_extension.geometry(MultiLineString,4326) NOT NULL,
    public_ready boolean DEFAULT false NOT NULL,
    geom_digest text GENERATED ALWAYS AS (
        encode(x_extension.digest(x_extension.ST_AsEWKB(geom), 'sha256'), 'hex')
    ) STORED,
    CONSTRAINT ck_feature_route_geometries_kind CHECK (((kind)::text = 'route'::text))
);

ALTER TABLE feature.feature_route_geometries OWNER TO ktm_feature_schema_owner;

-- **이 revision은 route를 이어 나르지 않는다.** 대신 **비어 있기를 요구한다.**
--
-- 소유자 결정(2026-09-19): *"마이그레이션 하지말고 db재설계후 다시데이터 로드해.
-- 지금데이터는 무의미함."* provider 적재분은 전부 재생성 가능하고, 등산로는 봉인
-- 천장 때문에 **한 번도 성공한 적이 없어** 남길 것도 없다(둘레길 26건이 전부다).
--
-- 그러면 왜 여기서 지우지 않는가. 마이그레이션이 데이터를 조용히 지우는 것은
-- 되돌릴 수 없고, `feature_routes`만 지우면 `feature.features`의 route 행이 subtype
-- 없이 남아 **다른 깨진 상태**가 된다. 지우는 것은 DB를 다시 세우는 절차의 일이고,
-- 이 revision의 일은 **그 절차를 건너뛴 것을 알아차리는 것**이다.
--
-- 새 설치(300 → 312)는 0행이라 그대로 지나간다.
DO $require_empty$
DECLARE
    v_rows bigint;
BEGIN
    SELECT count(*) INTO v_rows FROM feature.feature_routes;
    IF v_rows > 0 THEN
        RAISE EXCEPTION
            '312: feature_routes에 %행이 남아 있다. 이 revision은 route geometry를 '
            '이어 나르지 않는다 — DB를 다시 세우고 provider에서 재적재한 뒤 올릴 것.',
            v_rows;
    END IF;
END
$require_empty$;

ALTER TABLE feature.feature_route_geometries
    ADD CONSTRAINT pk_feature_route_geometries PRIMARY KEY (feature_id);

ALTER TABLE feature.feature_route_geometries
    ADD CONSTRAINT fk_feature_route_geometries_feature_kind
    FOREIGN KEY (feature_id, kind)
    REFERENCES feature.features(feature_id, kind) ON DELETE CASCADE;

-- **존재 불변식.** ADR-086의 `geom NOT NULL`을 대체한다. DEFERRABLE이므로 한
-- 트랜잭션 안의 삽입 순서는 자유롭고, COMMIT에서만 판정한다.
ALTER TABLE feature.feature_routes
    ADD CONSTRAINT fk_feature_routes_geometry
    FOREIGN KEY (feature_id)
    REFERENCES feature.feature_route_geometries(feature_id)
    DEFERRABLE INITIALLY DEFERRED;

-- **파생 트리거는 여기서 붙이지 않는다.** `CREATE TRIGGER`가 트리거 함수의
-- EXECUTE를 요구하는데 그 함수의 소유자는 다른 롤이고, 런타임 권한 조정기가
-- PUBLIC의 EXECUTE를 걷어낸 DB에서는 이 창(스키마 소유자)으로 통과하지 못한다.
-- 2026-09-20 격리 live 스택 실측 — 통합 게이트는 갓 만든 DB라 전부 초록이었다.
-- 트리거는 `_312_route_geometry_public_ready_trigger.sql`이 자기 창에서 만든다.

CREATE INDEX idx_feature_route_geometries_geom_gist
    ON feature.feature_route_geometries USING gist (geom) WHERE public_ready;

-- **구 컬럼은 여기서 지우지 않는다.** `feature.public_features` 뷰가 그 컬럼을
-- 참조하므로 먼저 뷰를 교체해야 한다 — 순서를 어기면
-- `DependentObjectsStillExistError: cannot drop column geom ... other objects
-- depend on it`이다(2026-09-19 n150 첫 실행이 이것을 잡았다). 드롭은
-- `312_route_geometry_sidecar.py`가 뷰 교체 **뒤에** 낸다.

GRANT SELECT ON TABLE feature.feature_route_geometries TO ktm_feature_runtime;
GRANT INSERT (feature_id, kind, geom)
    ON TABLE feature.feature_route_geometries TO ktm_feature_runtime;
GRANT UPDATE (geom) ON TABLE feature.feature_route_geometries TO ktm_feature_runtime;
GRANT SELECT (feature_id, public_ready), UPDATE (public_ready)
    ON TABLE feature.feature_route_geometries TO ktm_feature_state_procedure_owner;

-- **필드 패치 프로시저 셋이 이 롤로 실행된다.** 셋 다
-- `ktm_feature_state_procedure_owner` 소유의 SECURITY DEFINER이고, geometry 갱신을
-- `SET geom = CASE ... ELSE route_geom.geom END`으로 낸다 — 쓰기만이 아니라 **읽기도**
-- 필요하다. `feature_routes`·`feature_areas`는 테이블 레벨 SELECT로 그것을 갖고 있다.
--
-- 이 두 줄이 빠진 채 2026-09-20 통합 실행이 `permission denied for table
-- feature_route_geometries`로 죽었다. geometry가 relation을 옮겼는데 그것을 가리키던
-- 권한 선언이 옛 자리에 남아 있었다.
GRANT SELECT ON TABLE feature.feature_route_geometries
    TO ktm_feature_state_procedure_owner;
GRANT UPDATE (geom) ON TABLE feature.feature_route_geometries
    TO ktm_feature_state_procedure_owner;
