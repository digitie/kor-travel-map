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
-- `to_jsonb(route)`는 봉인 말고도 두 곳이 더 쓴다. 하나는 그 43 kB를
-- `feature.theme_feature_candidates.match_evidence`에 **영구 저장**하고, 하나는
-- admin 후보 목록 API 응답에 **페이지당 N×43 kB**로 내보낸다. 행을 좁히면 그 둘이
-- 함께 줄어든다.
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

INSERT INTO feature.feature_route_geometries
    (feature_id, kind, geom, public_ready)
SELECT feature_id, kind, geom, public_ready
  FROM feature.feature_routes;

-- **무손실을 바이트로 증명한다.** 행 수 일치도 `ST_Equals`(위상 동등)도 증명이
-- 아니다 — 이 설계는 `geom_digest`를 통해 **바이트**에 걸려 있다. 구 컬럼을
-- 드롭하기 **전에** 증명해야 되돌릴 수 있다.
DO $migrate$
DECLARE
    v_mismatched bigint;
    v_orphaned bigint;
BEGIN
    SELECT count(*) INTO v_mismatched
      FROM feature.feature_routes AS r
      JOIN feature.feature_route_geometries AS g ON g.feature_id = r.feature_id
     WHERE NOT x_extension.ST_OrderingEquals(r.geom, g.geom);
    IF v_mismatched > 0 THEN
        RAISE EXCEPTION
            '312: geometry 이전이 무손실이 아니다 — %건이 바이트 단위로 다르다',
            v_mismatched;
    END IF;

    SELECT count(*) INTO v_orphaned
      FROM feature.feature_routes AS r
      LEFT JOIN feature.feature_route_geometries AS g ON g.feature_id = r.feature_id
     WHERE g.feature_id IS NULL;
    IF v_orphaned > 0 THEN
        RAISE EXCEPTION '312: geometry 행이 없는 route가 %건 남았다', v_orphaned;
    END IF;
END
$migrate$;

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

CREATE INDEX idx_feature_route_geometries_geom_gist
    ON feature.feature_route_geometries USING gist (geom) WHERE public_ready;

-- 구 컬럼을 지운다. 컬럼에 달린 GiST 인덱스는 함께 사라진다.
ALTER TABLE feature.feature_routes DROP COLUMN geom;

GRANT SELECT ON TABLE feature.feature_route_geometries TO ktm_feature_runtime;
GRANT INSERT (feature_id, kind, geom)
    ON TABLE feature.feature_route_geometries TO ktm_feature_runtime;
GRANT UPDATE (geom) ON TABLE feature.feature_route_geometries TO ktm_feature_runtime;
GRANT SELECT (feature_id, public_ready), UPDATE (public_ready)
    ON TABLE feature.feature_route_geometries TO ktm_feature_state_procedure_owner;
