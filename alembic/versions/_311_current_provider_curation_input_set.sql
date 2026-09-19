-- feature.current_provider_curation_input_set — **fold만 바꾼다.**
--
-- 판정: 교체(fold 한정)
--
-- ## 무엇이 문제였나
--
-- 종전 fold는 데이터셋 **전 행의 13항 배열을 하나의 jsonb 배열**로 모은 뒤 그 text를
-- sha256했다. 크기가 O(행수 x 행당 payload)라 PostgreSQL의 jsonb 배열 상한
-- 268435455 bytes에 걸린다. 2026-09-19 prod 실측:
--
--     feature_route_krforest_mountain_trails_job
--       4시간18분 지오코딩 완료 -> 적재 -> 봉인에서
--       asyncpg.ProgramLimitExceededError:
--         total size of jsonb array elements exceeds the maximum of 268435455 bytes
--       -> 같은 트랜잭션이므로 57,060행이 통째로 롤백
--
--     route 1건의 to_jsonb 평균            43 kB  (geometry가 98.5%)
--     57,060행 환산                      2.45 GB  vs 상한 256 MB
--     place 1건 평균                       323 B
--     MOIS 980,970행 환산                  302 MB  vs 상한 256 MB  <- geometry와 무관
--
-- 즉 geometry를 어디로 옮기든 **fold 자체가** 다음 큰 dataset에서 같은 벽에 닿는다.
--
-- ## 무엇을 바꾸고 무엇을 바꾸지 않는가
--
-- 아래 `canonical_input` CTE는 head-schema.sql:4230-4270과 **한 글자도 다르지 않다.**
-- 13항 배열의 정의도, `to_jsonb(route)`가 geometry를 담는 것도 그대로다. 그래서
-- **탐지 범위가 1비트도 줄지 않는다** — 이 revision은 크기 결함만 고치고, geometry를
-- 어디에 둘 것인가라는 별개의 논쟁과 분리된다.
--
-- 바뀌는 것은 마지막 fold 하나다.
--
--     종전: jsonb_agg(13항 배열 ORDER BY ...)::text -> sha256
--     변경: 행마다 digest(13항 배열::text) = 32 B
--           -> string_agg(bytea ORDER BY ...) -> sha256
--
-- 32바이트 고정폭이라 구분자가 필요 없다(경계가 모호해질 수 없다). 집계 결과는
-- 57,060행이면 1.8 MB, MOIS 980,970행이면 31 MB로 어느 상한에도 닿지 않는다.
--
-- **보존해야 하는 네 가지**를 그대로 옮겼다. 하나라도 빠지면 두 비교 지점
-- (`seal_provider_curation_snapshot_receipt` 23514, `finalize_provider_curation_root`
-- stale_input)의 의미가 바뀐다.
--
--   1. `count(DISTINCT input.source_entity_key)` / `count(input.source_entity_key)`
--   2. `max(input.imported_at)::date`
--   3. `ORDER BY input.source_entity_key, input.feature_id`
--   4. `FILTER (WHERE input.source_entity_key IS NOT NULL)` + 빈 집합 COALESCE
--
-- ## 시그니처를 바꾸지 않는다
--
-- 인자와 `RETURNS TABLE` 컬럼을 그대로 두어 `CREATE OR REPLACE`가 되게 한다. 바꾸면
-- DROP+CREATE가 되어 `ktm_curation_command_owner`에게 준 EXECUTE GRANT
-- (head-schema.sql의 `GRANT ALL ON FUNCTION ...`)가 날아가고
-- `tests/integration/test_runtime_privileges_acl.py`가 빨개진다.

CREATE OR REPLACE FUNCTION feature.current_provider_curation_input_set(p_provider_dataset_id bigint) RETURNS TABLE(source_entity_count bigint, input_member_count bigint, last_source_modified_at date, source_input_set_hash text)
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'feature', 'provider_sync', 'ops', 'x_extension'
    AS $$
  WITH canonical_input AS (
    SELECT entity.source_entity_key, head.current_source_record_key,
           record.raw_payload_hash, record.imported_at,
           link.feature_id, link.source_role, link.match_method, link.confidence,
           core.row_revision AS feature_row_revision,
           core.lifecycle_state, core.publication_state, core.quality_state,
           CASE core.kind
             WHEN 'place' THEN COALESCE(to_jsonb(place), '{}'::jsonb)
             WHEN 'event' THEN COALESCE(to_jsonb(event), '{}'::jsonb)
             WHEN 'notice' THEN COALESCE(to_jsonb(notice), '{}'::jsonb)
             WHEN 'route' THEN COALESCE(to_jsonb(route), '{}'::jsonb)
             WHEN 'area' THEN COALESCE(to_jsonb(area_row), '{}'::jsonb)
             ELSE '{}'::jsonb
           END AS feature_detail,
           COALESCE(override_input.override_lineage, '[]'::jsonb) AS override_lineage
    FROM provider_sync.source_entities AS entity
    LEFT JOIN provider_sync.source_entity_heads AS head
      ON head.source_entity_key = entity.source_entity_key
    LEFT JOIN provider_sync.source_records AS record
      ON record.source_entity_key = head.source_entity_key
     AND record.source_record_key = head.current_source_record_key
    LEFT JOIN provider_sync.source_links AS link
      ON link.source_entity_key = entity.source_entity_key
    LEFT JOIN feature.features AS core ON core.feature_id = link.feature_id
    LEFT JOIN feature.feature_places AS place ON place.feature_id = core.feature_id
    LEFT JOIN feature.feature_events AS event ON event.feature_id = core.feature_id
    LEFT JOIN feature.feature_notices AS notice ON notice.feature_id = core.feature_id
    LEFT JOIN feature.feature_routes AS route ON route.feature_id = core.feature_id
    LEFT JOIN feature.feature_areas AS area_row ON area_row.feature_id = core.feature_id
    LEFT JOIN LATERAL (
      SELECT jsonb_agg(jsonb_build_array(
        override.override_id::text, override.field_path, override.override_value,
        CASE WHEN override.value_geometry IS NULL THEN NULL
             ELSE encode(x_extension.ST_AsEWKB(override.value_geometry), 'hex') END,
        override.base_revision, override.command_id
      ) ORDER BY override.field_path, override.override_id) AS override_lineage
      FROM ops.feature_overrides AS override
      WHERE override.feature_id = core.feature_id AND override.status = 'active'
    ) AS override_input ON true
    WHERE entity.provider_dataset_id = p_provider_dataset_id
  )
  SELECT count(DISTINCT input.source_entity_key)::bigint,
         count(input.source_entity_key)::bigint,
         max(input.imported_at)::date,
         encode(x_extension.digest(
           COALESCE(string_agg(
             x_extension.digest(convert_to(jsonb_build_array(
               input.source_entity_key, input.current_source_record_key,
               input.raw_payload_hash, input.feature_id, input.source_role,
               input.match_method, input.confidence, input.feature_row_revision,
               input.lifecycle_state, input.publication_state, input.quality_state,
               input.feature_detail, input.override_lineage
             )::text, 'UTF8'), 'sha256'),
             ''::bytea ORDER BY input.source_entity_key, input.feature_id)
           FILTER (WHERE input.source_entity_key IS NOT NULL), ''::bytea),
           'sha256'), 'hex')
  FROM canonical_input AS input
$$;
