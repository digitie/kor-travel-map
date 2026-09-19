-- override field-path 레지스트리를 geometry의 새 자리로 옮긴다.
--
-- 판정: CHECK 확장 + 행 1건 갱신
--
-- ## 무엇이 어긋났는가
--
-- `ops.feature_override_field_paths`는 "이 field_path가 어느 표의 어느 컬럼에
-- 앉는가"를 선언한다. `'route.geom'` 행은 `('feature_routes', 'geom')`을 가리키고
-- 있었는데, 312가 그 컬럼을 `feature.feature_route_geometries`로 옮겼다.
-- 레지스트리는 **없는 컬럼을 가리키는 선언**이 됐다.
--
-- 2026-09-20 적대 리뷰가 잡았다. 지금은 이 레지스트리에서 SQL을 유도하는 코드가
-- 없어 조용하지만, 그것이 이 행을 그대로 둘 이유는 아니다 — 레지스트리의 값어치는
-- "정본"이라는 데 있고, 틀린 정본은 없느니만 못하다.
--
-- ## field_path 문자열은 바꾸지 않는다
--
-- `'route.geom'`은 프로시저 셋(`p_geometry_wkt ? 'route.geom'`)과 admin API가
-- 주고받는 **외부 계약**이다. 바뀐 것은 그 값이 앉는 자리이지 이름이 아니다.
--
-- ## CHECK를 먼저 넓혀야 갱신이 통과한다
--
-- `ck_feature_override_field_paths_relation`이 312 이전 여섯 relation만 허용한다.
-- 넓히지 않으면 아래 UPDATE가 `23514`로 거절된다.

ALTER TABLE ops.feature_override_field_paths
    DROP CONSTRAINT ck_feature_override_field_paths_relation;

ALTER TABLE ops.feature_override_field_paths
    ADD CONSTRAINT ck_feature_override_field_paths_relation
    CHECK (target_relation = ANY (ARRAY[
        'features'::text,
        'feature_places'::text,
        'feature_events'::text,
        'feature_notices'::text,
        'feature_routes'::text,
        'feature_route_geometries'::text,
        'feature_areas'::text
    ]));

UPDATE ops.feature_override_field_paths
   SET target_relation = 'feature_route_geometries'
 WHERE field_path = 'route.geom'
   AND target_relation = 'feature_routes';

-- **갱신이 실제로 닿았는지 본다.** 레지스트리가 이미 다른 모양이면 위 UPDATE는
-- 0행을 고치고 조용히 지나간다 — 그러면 이 revision이 한 일이 없다.
DO $registry_moved$
DECLARE
    v_relation text;
BEGIN
    SELECT target_relation INTO v_relation
      FROM ops.feature_override_field_paths
     WHERE field_path = 'route.geom';
    IF v_relation IS DISTINCT FROM 'feature_route_geometries' THEN
        RAISE EXCEPTION
            '312: route.geom 레지스트리가 %를 가리킨다 — feature_route_geometries여야 한다.',
            COALESCE(v_relation, '(행 없음)');
    END IF;
END
$registry_moved$;
