-- ─────────────────────────────────────────────────────────────────────────
-- 판정: 유지(무변경). 아래는 alembic/head-schema.sql:4456-4488 원문 그대로이며
-- **참조용**이다 — T-VN-39는 이 루틴에 어떤 DDL도 발행하지 않는다.
-- 근거: ① ADR-083 결정 2가 이 SQL 거울을 이름으로 지목해 "역사 참조 전용으로
--       격하하고 제거하지 않는다"고 확정했다(docs/adr/083-...md:30-33).
--       참조 0건은 그 결정이 만든 의도된 상태다.
--       ② 표·컬럼 참조가 0건인 순수 IMMUTABLE 함수라 재키가 깨뜨리지 않는다.
--       ③ 인자 `legacy_feature_id text`는 오늘의 Feature id가 아니라 legacy `f_*`
--          텍스트다 — 그 값 부류는 `feature.feature_aliases.alias`(text 유지),
--          `manual_feature_purge_records.legacy_feature_id`,
--          `ops.tvn36_legacy_freeze_preflight_manifest.legacy_feature_id`로
--          재키 후에도 살아남는다. 따라서 인자 타입도 text 그대로가 옳다.
--       ④ 재키 후 `feature.feature_uuid_from_legacy(a.alias) = f.feature_id`가
--          backfill 731,600행 identity를 DB 안에서 재검증하는 유일한 수단이 된다
--          (0080/0081/0083의 파생 CHECK는 shadow 컬럼과 함께 사라진다).
-- ─────────────────────────────────────────────────────────────────────────

CREATE FUNCTION feature.feature_uuid_from_legacy(legacy_feature_id text) RETURNS uuid
    LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE
    SET search_path TO 'pg_catalog'
    AS $$
SELECT encode(
           set_byte(
               set_byte(
                   sha.digest16,
                   6,
                   (get_byte(sha.digest16, 6) & 15) | 80
               ),
               8,
               (get_byte(sha.digest16, 8) & 63) | 128
           ),
           'hex'
       )::uuid
FROM (
    SELECT substring(
               x_extension.digest(
                   decode('75d60e1327795b06a9206b1b892a7c84', 'hex')
                       || convert_to(legacy_feature_id, 'UTF8'),
                   'sha1'
               )
               FROM 1 FOR 16
           ) AS digest16
) AS sha
$$;


ALTER FUNCTION feature.feature_uuid_from_legacy(legacy_feature_id text) OWNER TO ktm_feature_schema_owner;
