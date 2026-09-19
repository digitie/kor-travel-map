-- feature.current_provider_curation_input_set — route geometry 지문을 되넣는다.
--
-- 판정: 교체(route arm 한정)
--
-- ## 왜
--
-- 312가 `feature_routes.geom`을 `feature.feature_route_geometries`로 옮긴다.
-- 그 순간 `to_jsonb(route)`에서 geometry가 **조용히 사라지고**, 봉인은 geometry만
-- 바뀐 재적재를 같은 해시로 본다. 기존 검사는 전부 초록이다 — 해시는 여전히
-- 64자이고 재현성도 유지되기 때문이다.
--
-- 그래서 그 자리를 **고정폭 지문**으로 메운다. `route_geom.geom_digest`는 보조
-- relation의 `GENERATED ALWAYS AS ... STORED` 컬럼이라 DB가 유지한다 — 동기화할
-- 코드가 없고, 프로시저를 우회한 `UPDATE ... SET geom` 경로까지 전부 덮는다.
--
-- ## 크기
--
-- 64 hex × 57,060행 = 3.7 MB. 311이 fold를 행별 digest로 바꿔 두었으므로 배열이
-- 만들어지지도 않는다. geometry 자체(43 kB/행)를 되넣는 것과는 다른 축이다.
--
-- ## 311과 달라지는 것은 route arm 하나뿐
--
-- 311이 바꾼 fold도, 나머지 12항도, 다른 kind의 arm도 그대로다. `jsonb_build_object`
-- 한 항이 더해지고 LEFT JOIN 하나가 늘 뿐이다(PK↔PK).
--
-- ## 시그니처를 바꾸지 않는다
--
-- `CREATE OR REPLACE`가 되어야 `ktm_curation_command_owner`의 EXECUTE GRANT가
-- 보존된다.

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
               || jsonb_build_object('geom_digest', route_geom.geom_digest)
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
    LEFT JOIN feature.feature_route_geometries AS route_geom
      ON route_geom.feature_id = core.feature_id
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
