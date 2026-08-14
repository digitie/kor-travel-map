"""T-VN-40B typed candidate promotion and trusted membership decision.

Revision ID: 0203_tvn40_candidate_promotion
Revises: 0202_tvn40_candidate_commands

Promotion is one database command: it validates the current candidate/source
proof, writes or updates one canonical item, appends an accepted admin-review
decision, advances the trusted pointer, and records the candidate transition.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# Frozen PostgreSQL procedure text intentionally exceeds Python line length.
# ruff: noqa: E501

revision: str = "0203_tvn40_candidate_promotion"
down_revision: str | Sequence[str] | None = "0202_tvn40_candidate_commands"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_CURRENT_SNAPSHOT_FUNCTION_SQL = r"""
CREATE FUNCTION feature.current_theme_candidate_snapshot(
  p_rule_id uuid,
  p_source_entity_key text,
  p_feature_id text
) RETURNS TABLE (
  rule_row_revision bigint,
  rule_input_hash text,
  source_record_key text,
  source_record_hash text,
  candidate_input_hash text,
  match_evidence jsonb
)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, feature, provider_sync, ops, x_extension
AS $snapshot$
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
    core.feature_uuid,
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
    feature.feature_uuid,
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
        'feature_uuid', feature.feature_uuid::text,
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
    'feature_uuid', input.feature_uuid::text,
    'source_role', input.source_role,
    'match_method', input.match_method,
    'confidence', input.confidence,
    'rule_input', input.rule_input
  )
FROM current_input AS input
$snapshot$;
"""


_PROMOTE_PROCEDURE_SQL = r"""
CREATE PROCEDURE feature.promote_theme_feature_candidate(
  IN p_candidate_id uuid,
  IN p_collection_id uuid,
  IN p_external_item_id text,
  IN p_external_component_id text,
  IN p_place_name text,
  IN p_address_hint text,
  IN p_item_title text,
  IN p_item_summary text,
  IN p_sort_order integer,
  IN p_curation_relation text,
  IN p_reuse_policy text,
  IN p_item_status text,
  IN p_expected_candidate_revision bigint,
  IN p_expected_collection_revision bigint,
  IN p_expected_item_revision bigint,
  IN p_command_id bigint,
  IN p_reason_code text,
  IN p_principal text,
  OUT o_candidate_id uuid,
  OUT o_candidate_revision bigint,
  OUT o_curation_item_id uuid,
  OUT o_curation_item_revision bigint,
  OUT o_transition_id bigint
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, feature, provider_sync, ops, x_extension
AS $command$
DECLARE
  v_candidate_hint feature.theme_feature_candidates%ROWTYPE;
  v_candidate feature.theme_feature_candidates%ROWTYPE;
  v_rule feature.curated_source_rules%ROWTYPE;
  v_collection feature.curation_collections%ROWTYPE;
  v_item feature.curation_items%ROWTYPE;
  v_command ops.domain_commands%ROWTYPE;
  v_source_dataset_id bigint;
  v_current_source_record_key text;
  v_current_source_record_hash text;
  v_previous_decision_id uuid;
  v_decision_id uuid;
  v_item_found boolean := false;
  v_snapshot record;
BEGIN
  IF current_setting('transaction_isolation') <> 'serializable' THEN
    RAISE EXCEPTION 'candidate command requires SERIALIZABLE transaction'
      USING ERRCODE = '25001';
  END IF;
  IF NOT pg_has_role(session_user, 'ktm_curation_admin_executor', 'member')
     OR pg_has_role(session_user, 'ktm_curation_provider_executor', 'member') THEN
    RAISE EXCEPTION 'candidate promotion requires the admin executor'
      USING ERRCODE = '42501';
  END IF;
  IF p_expected_candidate_revision IS NULL OR p_expected_candidate_revision < 1
     OR p_expected_collection_revision IS NULL OR p_expected_collection_revision < 1
     OR (p_expected_item_revision IS NOT NULL AND p_expected_item_revision < 1) THEN
    RAISE EXCEPTION 'expected revisions must be positive'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_theme_candidate_expected_revision';
  END IF;
  IF p_external_item_id IS NULL OR p_external_item_id <> btrim(p_external_item_id)
     OR p_external_item_id = '' OR char_length(p_external_item_id) > 512
     OR p_external_component_id IS NULL
     OR p_external_component_id <> btrim(p_external_component_id)
     OR p_external_component_id = '' OR char_length(p_external_component_id) > 512
     OR p_place_name IS NULL OR p_place_name <> btrim(p_place_name)
     OR p_place_name = '' OR char_length(p_place_name) > 512
     OR p_sort_order IS NULL OR p_sort_order < 0
     OR p_item_status NOT IN ('candidate','included')
     OR p_curation_relation NOT IN (
       'primary_stop','food_stop','cafe_stop','bookstore_stop',
       'nearby_option','accessibility_support','pet_support',
       'family_support','theme_area_anchor'
     )
     OR p_reuse_policy NOT IN ('allowed','blocked','manual_review') THEN
    RAISE EXCEPTION 'candidate promotion item payload is not canonical'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_theme_candidate_promotion_payload';
  END IF;
  IF p_reason_code IS NULL OR p_reason_code <> btrim(p_reason_code)
     OR p_reason_code = '' OR char_length(p_reason_code) > 128
     OR p_principal IS NULL OR p_principal <> btrim(p_principal)
     OR p_principal = '' OR char_length(p_principal) > 200 THEN
    RAISE EXCEPTION 'promotion principal and reason must be canonical'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_theme_candidate_promotion_actor';
  END IF;

  SELECT command.* INTO STRICT v_command
  FROM ops.domain_commands AS command
  WHERE command.command_id = p_command_id;
  IF v_command.actor <> p_principal
     OR v_command.operation <> 'admin.theme-feature-candidate.promote' THEN
    RAISE EXCEPTION 'domain command does not match candidate promotion'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_theme_candidate_domain_command';
  END IF;

  -- The first read discovers the advisory-fence identity only.  Every value is
  -- read again after the common feature fence and exact relation locks.
  SELECT candidate.* INTO STRICT v_candidate_hint
  FROM feature.theme_feature_candidates AS candidate
  WHERE candidate.candidate_id = p_candidate_id;
  PERFORM pg_advisory_xact_lock(
    hashtextextended('feature-write:' || v_candidate_hint.feature_id, 0)
  );

  SELECT rule.* INTO STRICT v_rule
  FROM feature.curated_source_rules AS rule
  WHERE rule.rule_id = v_candidate_hint.rule_id
  FOR SHARE;

  SELECT source.provider_dataset_id
  INTO STRICT v_source_dataset_id
  FROM feature.curated_sources AS source
  WHERE source.source_id = v_rule.source_id
    AND source.archived_at IS NULL
  FOR SHARE;

  PERFORM 1
  FROM provider_sync.provider_datasets AS dataset
  WHERE dataset.provider_dataset_id = v_source_dataset_id
    AND dataset.is_active
  FOR SHARE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'candidate source dataset is not active'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_theme_candidate_current_source';
  END IF;

  PERFORM 1
  FROM provider_sync.source_entities AS entity
  WHERE entity.source_entity_key = v_candidate_hint.source_entity_key
    AND entity.provider_dataset_id = v_source_dataset_id
  FOR SHARE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'candidate source entity is not in the rule dataset'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_theme_candidate_current_source';
  END IF;

  SELECT head.current_source_record_key
  INTO STRICT v_current_source_record_key
  FROM provider_sync.source_entity_heads AS head
  WHERE head.source_entity_key = v_candidate_hint.source_entity_key
  FOR SHARE;
  SELECT record.raw_payload_hash
  INTO STRICT v_current_source_record_hash
  FROM provider_sync.source_records AS record
  WHERE record.source_entity_key = v_candidate_hint.source_entity_key
    AND record.source_record_key = v_current_source_record_key
  FOR SHARE;

  PERFORM 1
  FROM provider_sync.source_links AS link
  WHERE link.source_entity_key = v_candidate_hint.source_entity_key
    AND link.feature_id = v_candidate_hint.feature_id
  FOR SHARE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'candidate source link is no longer current'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_theme_candidate_current_source';
  END IF;

  PERFORM 1
  FROM feature.features AS current_feature
  WHERE current_feature.feature_id = v_candidate_hint.feature_id
    AND current_feature.lifecycle_state = 'active'
    AND current_feature.publication_state = 'published'
    AND current_feature.quality_state = 'valid'
  FOR SHARE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'candidate Feature is not currently public-eligible'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_theme_candidate_current_feature';
  END IF;

  SELECT candidate.* INTO STRICT v_candidate
  FROM feature.theme_feature_candidates AS candidate
  WHERE candidate.candidate_id = p_candidate_id
  FOR UPDATE;
  IF v_candidate.feature_id <> v_candidate_hint.feature_id
     OR v_candidate.rule_id <> v_candidate_hint.rule_id
     OR v_candidate.source_entity_key <> v_candidate_hint.source_entity_key
     OR v_candidate.row_revision <> p_expected_candidate_revision THEN
    RAISE EXCEPTION 'candidate identity or revision changed while locking'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_theme_candidate_expected_revision';
  END IF;
  IF v_candidate.disposition <> 'active'
     OR v_candidate.review_state <> 'open'
     OR NOT v_candidate.eligibility_present THEN
    RAISE EXCEPTION 'only an active open eligible candidate can be promoted'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_theme_candidate_promote_state';
  END IF;

  SELECT snapshot.* INTO v_snapshot
  FROM feature.current_theme_candidate_snapshot(
    v_candidate.rule_id,
    v_candidate.source_entity_key,
    v_candidate.feature_id
  ) AS snapshot;
  IF NOT FOUND
     OR v_snapshot.rule_input_hash <> v_candidate.rule_input_hash
     OR v_snapshot.source_record_key <> v_candidate.source_record_key
     OR v_snapshot.source_record_hash <> v_candidate.source_record_hash
     OR v_snapshot.candidate_input_hash <> v_candidate.candidate_input_hash
     OR v_current_source_record_key <> v_candidate.source_record_key
     OR v_current_source_record_hash <> v_candidate.source_record_hash THEN
    RAISE EXCEPTION 'candidate proof is stale'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_theme_candidate_current_proof';
  END IF;

  SELECT collection.* INTO STRICT v_collection
  FROM feature.curation_collections AS collection
  WHERE collection.collection_id = p_collection_id
  FOR UPDATE;
  IF v_collection.archived_at IS NOT NULL OR v_collection.status = 'archived' THEN
    RAISE EXCEPTION 'target curation collection is archived'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_theme_candidate_collection_active';
  END IF;
  IF v_collection.row_revision <> p_expected_collection_revision THEN
    RAISE EXCEPTION 'collection revision mismatch: expected %, current %',
      p_expected_collection_revision, v_collection.row_revision
      USING ERRCODE = '23514', CONSTRAINT = 'ck_theme_candidate_collection_revision';
  END IF;

  SELECT item.* INTO v_item
  FROM feature.curation_items AS item
  WHERE item.collection_id = p_collection_id
    AND item.external_item_id = p_external_item_id
    AND item.external_component_id = p_external_component_id
  FOR UPDATE;
  v_item_found := FOUND;
  IF v_item_found AND p_expected_item_revision IS NULL THEN
    RAISE EXCEPTION 'create-only curation item identity already exists'
      USING ERRCODE = '23505', CONSTRAINT = 'uq_curation_items_component_identity';
  ELSIF NOT v_item_found AND p_expected_item_revision IS NOT NULL THEN
    RAISE EXCEPTION 'expected curation item does not exist'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_theme_candidate_item_revision';
  ELSIF v_item_found AND v_item.row_revision <> p_expected_item_revision THEN
    RAISE EXCEPTION 'item revision mismatch: expected %, current %',
      p_expected_item_revision, v_item.row_revision
      USING ERRCODE = '23514', CONSTRAINT = 'ck_theme_candidate_item_revision';
  END IF;

  IF v_item_found THEN
    o_curation_item_id := v_item.curation_item_id;
    v_previous_decision_id := v_item.accepted_link_decision_id;
    UPDATE feature.curation_items AS item
    SET feature_id = v_candidate.feature_id,
        source_record_key = v_candidate.source_record_key,
        place_name = p_place_name,
        address_hint = p_address_hint,
        source_present = true,
        source_updated_at = clock_timestamp(),
        status = p_item_status,
        sort_order = p_sort_order,
        item_title = p_item_title,
        item_summary = p_item_summary,
        curation_relation = p_curation_relation,
        reuse_policy = p_reuse_policy,
        updated_by = p_principal,
        operator_updated_by = p_principal,
        operator_updated_at = clock_timestamp(),
        archived_at = NULL,
        updated_at = clock_timestamp(),
        row_revision = item.row_revision + 1
    WHERE item.curation_item_id = o_curation_item_id
    RETURNING item.row_revision INTO STRICT o_curation_item_revision;
  ELSE
    o_curation_item_id := x_extension.gen_random_uuid();
    INSERT INTO feature.curation_items (
      curation_item_id, collection_id, feature_id, source_record_key,
      external_item_id, external_component_id, place_name, address_hint,
      source_present, source_updated_at, status, sort_order, item_title,
      item_summary, curation_relation, reuse_policy, metadata, created_by,
      updated_by, operator_updated_by, operator_updated_at, row_revision
    ) VALUES (
      o_curation_item_id, p_collection_id, v_candidate.feature_id,
      v_candidate.source_record_key, p_external_item_id,
      p_external_component_id, p_place_name, p_address_hint, true,
      clock_timestamp(), p_item_status, p_sort_order, p_item_title,
      p_item_summary, p_curation_relation, p_reuse_policy,
      jsonb_build_object(
        'schema_version', 1,
        'promotion_candidate_id', p_candidate_id::text,
        'promotion_command_id', p_command_id
      ), p_principal, p_principal, p_principal, clock_timestamp(), 1
    )
    RETURNING row_revision INTO STRICT o_curation_item_revision;
    v_previous_decision_id := NULL;
  END IF;

  -- A legacy source-rule trigger can only add an intermediate accepted pointer
  -- while the old overlay still exists.  Chain the explicit admin decision to
  -- the actual locked pointer so history remains linear during this one-release
  -- migration; the final cutover drops that trigger.
  SELECT item.accepted_link_decision_id
  INTO v_previous_decision_id
  FROM feature.curation_items AS item
  WHERE item.curation_item_id = o_curation_item_id
  FOR UPDATE;

  INSERT INTO feature.curation_link_decisions (
    curation_item_id, feature_id, import_row_id, decision_kind, match_basis,
    resolver_version, evidence, actor, supersedes_decision_id
  ) VALUES (
    o_curation_item_id, v_candidate.feature_id, NULL, 'accepted',
    'admin_review', 'tvn40-candidate-promotion-v1',
    jsonb_build_object(
      'schema_version', 1,
      'candidate_id', p_candidate_id::text,
      'candidate_revision', p_expected_candidate_revision,
      'rule_revision', v_candidate.rule_row_revision,
      'source_entity_key', v_candidate.source_entity_key,
      'source_record_key', v_candidate.source_record_key,
      'source_record_hash', v_candidate.source_record_hash,
      'command_id', p_command_id
    ),
    p_principal, v_previous_decision_id
  ) RETURNING decision_id INTO STRICT v_decision_id;

  UPDATE feature.curation_items AS item
  SET accepted_link_decision_id = v_decision_id
  WHERE item.curation_item_id = o_curation_item_id;

  -- collection detail은 ordered child set을 포함한다. item promotion으로 body가
  -- 바뀌면 parent command/representation revision도 같은 transaction에서 전진한다.
  UPDATE feature.curation_collections AS collection
  SET row_revision = collection.row_revision + 1,
      updated_by = p_principal,
      updated_at = clock_timestamp()
  WHERE collection.collection_id = p_collection_id;

  UPDATE feature.theme_feature_candidates AS candidate
  SET review_state = 'promoted',
      row_revision = candidate.row_revision + 1,
      updated_at = clock_timestamp()
  WHERE candidate.candidate_id = p_candidate_id
  RETURNING candidate.candidate_id, candidate.row_revision
  INTO STRICT o_candidate_id, o_candidate_revision;

  o_transition_id := feature.append_theme_feature_candidate_transition(
    p_candidate_id,
    v_candidate.feature_id,
    v_candidate.feature_id,
    v_candidate.rule_id,
    v_candidate.source_entity_key,
    v_candidate.review_state,
    'promoted',
    v_candidate.eligibility_present,
    v_candidate.eligibility_present,
    v_candidate.disposition,
    v_candidate.disposition,
    NULL,
    'admin_promote',
    o_candidate_revision,
    v_candidate.rule_row_revision,
    v_candidate.rule_input_hash,
    v_candidate.candidate_input_hash,
    NULL,
    v_source_dataset_id,
    v_candidate.source_record_key,
    v_candidate.source_record_hash,
    p_collection_id,
    o_curation_item_id,
    p_command_id,
    p_principal,
    p_reason_code,
    jsonb_build_object(
      'schema_version', 1,
      'candidate_id', p_candidate_id::text,
      'expected_candidate_revision', p_expected_candidate_revision,
      'expected_collection_revision', p_expected_collection_revision,
      'expected_item_revision', p_expected_item_revision,
      'link_decision_id', v_decision_id::text
    )
  );
END
$command$;
"""


_PROMOTE_SIGNATURE = (
    "feature.promote_theme_feature_candidate("
    "uuid,uuid,text,text,text,text,text,text,integer,text,text,text,"
    "bigint,bigint,bigint,bigint,text,text)"
)


def upgrade() -> None:
    op.execute(_CURRENT_SNAPSHOT_FUNCTION_SQL)
    op.execute(_PROMOTE_PROCEDURE_SQL)
    op.execute(
        "ALTER FUNCTION feature.current_theme_candidate_snapshot(uuid,text,text) "
        "OWNER TO ktm_curation_command_owner"
    )
    op.execute(f"ALTER PROCEDURE {_PROMOTE_SIGNATURE} OWNER TO ktm_curation_command_owner")

    # Read/lock proof relations and mutate only the canonical membership rows
    # owned by this named procedure.  Column UPDATE grants on proof relations
    # exist solely because PostgreSQL requires UPDATE privilege for row locks.
    op.execute(
        "GRANT SELECT ON TABLE feature.curated_themes, feature.curated_source_rules, feature.curated_sources, "
        "feature.curation_collections, feature.curation_items, "
        "feature.curation_link_decisions, feature.curated_features, feature.features, "
        "provider_sync.provider_datasets, provider_sync.source_entities, "
        "provider_sync.source_entity_heads, provider_sync.source_records, "
        "provider_sync.source_links, feature.feature_places, feature.feature_events, "
        "feature.feature_notices, feature.feature_routes, feature.feature_areas, "
        "ops.feature_overrides TO ktm_curation_command_owner"
    )
    for relation, column in (
        ("feature.curated_source_rules", "row_revision"),
        ("feature.curated_sources", "row_revision"),
        ("feature.curation_collections", "row_revision"),
        ("feature.curation_collections", "updated_by"),
        ("feature.curation_collections", "updated_at"),
        ("feature.features", "row_revision"),
        ("provider_sync.provider_datasets", "provider_dataset_id"),
        ("provider_sync.source_entities", "source_entity_key"),
        ("provider_sync.source_entity_heads", "source_entity_key"),
        ("provider_sync.source_records", "source_record_key"),
        ("provider_sync.source_links", "feature_id"),
    ):
        op.execute(
            f"GRANT UPDATE ({column}) ON TABLE {relation} "
            "TO ktm_curation_command_owner"
        )
    op.execute(
        "GRANT INSERT, UPDATE ON TABLE feature.curation_items "
        "TO ktm_curation_command_owner"
    )
    op.execute(
        "GRANT INSERT ON TABLE feature.curation_link_decisions "
        "TO ktm_curation_command_owner"
    )

    op.execute("SET ROLE ktm_curation_command_owner")
    op.execute(
        "REVOKE ALL ON FUNCTION "
        "feature.current_theme_candidate_snapshot(uuid,text,text) "
        "FROM PUBLIC, ktm_feature_runtime, ktm_feature_api_runtime, "
        "ktm_feature_dagster_runtime, ktm_curation_admin_executor, "
        "ktm_curation_provider_executor"
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION "
        "feature.current_theme_candidate_snapshot(uuid,text,text) "
        "TO ktm_feature_schema_owner"
    )
    op.execute(
        f"REVOKE ALL ON PROCEDURE {_PROMOTE_SIGNATURE} FROM PUBLIC, "
        "ktm_feature_runtime, ktm_feature_api_runtime, "
        "ktm_feature_dagster_runtime, ktm_curation_provider_executor"
    )
    op.execute(
        f"GRANT EXECUTE ON PROCEDURE {_PROMOTE_SIGNATURE} "
        "TO ktm_curation_admin_executor"
    )
    op.execute("SET ROLE ktm_feature_schema_owner")


def downgrade() -> None:
    raise RuntimeError("0203_tvn40_candidate_promotion is forward-only; rebuild with the T-VN-40 release head")
