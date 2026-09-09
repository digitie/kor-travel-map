DROP FUNCTION feature.current_theme_candidate_snapshot(uuid, text, text);

CREATE FUNCTION feature.current_theme_candidate_snapshot(p_rule_id uuid, p_source_entity_key text, p_feature_id uuid) RETURNS TABLE(rule_row_revision bigint, rule_input_hash text, source_record_key text, source_record_hash text, candidate_input_hash text, match_evidence jsonb)
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'feature', 'provider_sync', 'ops', 'x_extension'
    AS $$
WITH rule_scope AS MATERIALIZED (
  SELECT
    rule.*,
    source.provider_dataset_id,
    feature.current_curation_rule_input(rule.rule_id) AS rule_input
  FROM feature.curated_source_rules AS rule
  JOIN feature.curated_sources AS source ON source.source_id = rule.source_id
  JOIN feature.curated_themes AS theme ON theme.theme_id = rule.theme_id
  JOIN provider_sync.provider_datasets AS dataset
    ON dataset.provider_dataset_id = source.provider_dataset_id
  WHERE rule.rule_id = p_rule_id
    AND rule.archived_at IS NULL
    AND source.archived_at IS NULL
    AND theme.archived_at IS NULL
    AND rule.enabled
    AND rule.default_action = 'candidate'
    AND dataset.is_active
),
effective_feature AS MATERIALIZED (
  SELECT
    core.feature_id,
    core.row_revision AS feature_row_revision,
    core.kind,
    core.category,
    core.sido_code,
    core.sigungu_code,
    core.lifecycle_state,
    core.publication_state,
    core.quality_state,
    place.place_kind,
    event.event_kind,
    CASE core.kind
      WHEN 'place' THEN COALESCE(to_jsonb(place), '{}'::jsonb)
      WHEN 'event' THEN COALESCE(to_jsonb(event), '{}'::jsonb)
      WHEN 'notice' THEN COALESCE(to_jsonb(notice), '{}'::jsonb)
      WHEN 'route' THEN COALESCE(to_jsonb(route), '{}'::jsonb)
      WHEN 'area' THEN COALESCE(to_jsonb(area_row), '{}'::jsonb)
      ELSE '{}'::jsonb
    END AS detail,
    COALESCE((
      SELECT jsonb_agg(
        jsonb_build_object(
          'override_id', override.override_id::text,
          'field_path', override.field_path,
          'override_value', override.override_value,
          'value_geometry_ewkb', CASE
            WHEN override.value_geometry IS NULL THEN NULL
            ELSE encode(x_extension.ST_AsEWKB(override.value_geometry), 'hex')
          END,
          'base_revision', override.base_revision,
          'command_id', override.command_id
        ) ORDER BY override.field_path, override.override_id
      )
      FROM ops.feature_overrides AS override
      WHERE override.feature_id = core.feature_id
        AND override.status = 'active'
    ), '[]'::jsonb) AS override_lineage
  FROM feature.features AS core
  LEFT JOIN feature.feature_places AS place ON place.feature_id = core.feature_id
  LEFT JOIN feature.feature_events AS event ON event.feature_id = core.feature_id
  LEFT JOIN feature.feature_notices AS notice ON notice.feature_id = core.feature_id
  LEFT JOIN feature.feature_routes AS route ON route.feature_id = core.feature_id
  LEFT JOIN feature.feature_areas AS area_row ON area_row.feature_id = core.feature_id
  WHERE core.feature_id = p_feature_id
    AND core.lifecycle_state = 'active'
    AND core.publication_state = 'published'
    AND core.quality_state = 'valid'
),
current_input AS MATERIALIZED (
  SELECT
    rule.row_revision AS current_rule_revision,
    rule.rule_input,
    head.current_source_record_key,
    record.raw_payload_hash,
    feature.feature_id,
    feature.feature_row_revision,
    feature.kind,
    feature.category,
    feature.sido_code,
    feature.sigungu_code,
    feature.lifecycle_state,
    feature.publication_state,
    feature.quality_state,
    feature.detail,
    feature.override_lineage,
    link.source_role,
    link.match_method,
    link.confidence,
    jsonb_build_object(
      'schema_version', 1,
      'source_entity_key', entity.source_entity_key,
      'source_record_key', head.current_source_record_key,
      'source_record_hash', record.raw_payload_hash,
      'source_link', jsonb_build_object(
        'feature_id', link.feature_id,
        'source_role', link.source_role,
        'match_method', link.match_method,
        'confidence', link.confidence
      ),
      'feature', jsonb_build_object(
        'feature_id', feature.feature_id,
        'feature_uuid', feature.feature_id::text,
        'row_revision', feature.feature_row_revision,
        'kind', feature.kind,
        'category', feature.category,
        'sido_code', feature.sido_code,
        'sigungu_code', feature.sigungu_code,
        'lifecycle_state', feature.lifecycle_state,
        'publication_state', feature.publication_state,
        'quality_state', feature.quality_state,
        'detail', feature.detail,
        'override_lineage', feature.override_lineage
      )
    ) AS candidate_input
  FROM rule_scope AS rule
  JOIN provider_sync.source_entities AS entity
    ON entity.source_entity_key = p_source_entity_key
   AND entity.provider_dataset_id = rule.provider_dataset_id
  JOIN provider_sync.source_entity_heads AS head
    ON head.source_entity_key = entity.source_entity_key
  JOIN provider_sync.source_records AS record
    ON record.source_entity_key = entity.source_entity_key
   AND record.source_record_key = head.current_source_record_key
  JOIN provider_sync.source_links AS link
    ON link.source_entity_key = entity.source_entity_key
   AND link.feature_id = p_feature_id
  JOIN effective_feature AS feature ON feature.feature_id = link.feature_id
  WHERE (rule.place_kind IS NULL
         OR feature.place_kind = rule.place_kind
         OR feature.event_kind = rule.place_kind)
    AND (rule.category IS NULL OR feature.category = rule.category)
    AND (
      rule.region_scope = '{}'::jsonb
      OR (
        (NOT rule.region_scope ? 'sido_code'
         OR feature.sido_code = rule.region_scope ->> 'sido_code')
        AND (NOT rule.region_scope ? 'sigungu_code'
         OR feature.sigungu_code = rule.region_scope ->> 'sigungu_code')
      )
    )
    AND (
      rule.detail_selector IS NULL
      OR feature.detail #>> ARRAY(
        SELECT jsonb_array_elements_text(rule.detail_selector -> 'path')
      ) = rule.detail_selector ->> 'value'
    )
)
SELECT
  input.current_rule_revision,
  encode(
    x_extension.digest(convert_to(input.rule_input::text, 'UTF8'), 'sha256'),
    'hex'
  ),
  input.current_source_record_key,
  input.raw_payload_hash,
  encode(
    x_extension.digest(convert_to(input.candidate_input::text, 'UTF8'), 'sha256'),
    'hex'
  ),
  jsonb_build_object(
    'schema_version', 1,
    'feature_row_revision', input.feature_row_revision,
    'feature_uuid', input.feature_id::text,
    'source_role', input.source_role,
    'match_method', input.match_method,
    'confidence', input.confidence,
    'rule_input', input.rule_input
  )
FROM current_input AS input
$$;

ALTER FUNCTION feature.current_theme_candidate_snapshot(p_rule_id uuid, p_source_entity_key text, p_feature_id uuid) OWNER TO ktm_curation_command_owner;

REVOKE ALL ON FUNCTION feature.current_theme_candidate_snapshot(uuid, text, uuid) FROM PUBLIC;
GRANT ALL ON FUNCTION feature.current_theme_candidate_snapshot(uuid, text, uuid) TO ktm_feature_schema_owner;
