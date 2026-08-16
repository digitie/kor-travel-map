"""T-VN-40B typed retained rule catalog commands.

Revision ID: 0206_tvn40_rule_catalog_commands
Revises: 0205_tvn40_rule_generation

Operator rule create/patch/archive is revision-CAS protected and materializes
the complete DB-derived candidate set in the same SERIALIZABLE transaction.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# Frozen PostgreSQL procedure text intentionally exceeds Python line length.
# ruff: noqa: E501

revision: str = "0206_tvn40_rule_catalog_commands"
down_revision: str | Sequence[str] | None = "0205_tvn40_rule_generation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _execute_commands(source: str) -> None:
    """Dollar-quoted routine bodies를 보존해 asyncpg statement를 분리한다."""

    statements: list[str] = []
    start = 0
    index = 0
    quote: str | None = None
    dollar_tag: str | None = None
    while index < len(source):
        character = source[index]
        if dollar_tag is not None:
            if source.startswith(dollar_tag, index):
                index += len(dollar_tag)
                dollar_tag = None
                continue
            index += 1
            continue
        if quote is not None:
            if character == quote:
                if index + 1 < len(source) and source[index + 1] == quote:
                    index += 2
                    continue
                quote = None
            index += 1
            continue
        if character in {"'", '"'}:
            quote = character
            index += 1
            continue
        if character == "$":
            end = source.find("$", index + 1)
            if end != -1:
                candidate = source[index : end + 1]
                inner = candidate[1:-1]
                if not inner or inner.replace("_", "a").isalnum():
                    dollar_tag = candidate
                    index = end + 1
                    continue
        if character == ";":
            statement = source[start:index].strip()
            if statement:
                statements.append(statement)
            start = index + 1
        index += 1
    trailing = source[start:].strip()
    if trailing:
        statements.append(trailing)
    for statement in statements:
        op.execute(statement)


_RECONCILE_RECEIPT_FUNCTION_SQL = r"""
CREATE FUNCTION feature.create_curation_rule_reconcile_receipt(
  p_rule_id uuid,
  p_operation_kind text,
  p_before_rule_revision bigint,
  p_after_rule_revision bigint,
  p_before_rule_input_hash text,
  p_after_rule_input_hash text,
  p_command_id bigint,
  p_actor text
) RETURNS uuid
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, feature, provider_sync, ops, x_extension
AS $receipt$
DECLARE
  v_operation_id uuid := x_extension.gen_random_uuid();
  v_provider_dataset_id bigint;
  v_scope_member_count bigint;
  v_scope_members_hash text;
BEGIN
  SELECT source.provider_dataset_id INTO STRICT v_provider_dataset_id
  FROM feature.curated_source_rules AS rule
  JOIN feature.curated_sources AS source ON source.source_id = rule.source_id
  WHERE rule.rule_id = p_rule_id;

  WITH scope AS (
    SELECT 'source_entity'::text AS member_kind,
           entity.source_entity_key AS member_key,
           encode(x_extension.digest(convert_to(jsonb_build_array(
             entity.source_entity_key, head.current_source_record_key
           )::text, 'UTF8'), 'sha256'), 'hex') AS identity_hash
    FROM provider_sync.source_entities AS entity
    LEFT JOIN provider_sync.source_entity_heads AS head
      ON head.source_entity_key = entity.source_entity_key
    WHERE entity.provider_dataset_id = v_provider_dataset_id
    UNION
    SELECT 'feature'::text, link.feature_id,
           encode(x_extension.digest(convert_to(jsonb_build_array(
             link.feature_id, core.feature_uuid::text, core.row_revision,
             core.lifecycle_state, core.publication_state, core.quality_state
           )::text, 'UTF8'), 'sha256'), 'hex')
    FROM provider_sync.source_entities AS entity
    JOIN provider_sync.source_links AS link
      ON link.source_entity_key = entity.source_entity_key
    JOIN feature.features AS core ON core.feature_id = link.feature_id
    WHERE entity.provider_dataset_id = v_provider_dataset_id
  ), framed AS (
    SELECT member_kind, member_key,
           CASE WHEN p_operation_kind = 'create' THEN NULL ELSE identity_hash END
             AS before_identity_hash,
           identity_hash AS after_identity_hash
    FROM scope
  )
  SELECT count(*), encode(
    x_extension.digest(
      COALESCE(
        string_agg(
          convert_to(member_kind, 'UTF8') || decode('00', 'hex') ||
          convert_to(member_key, 'UTF8') || decode('00', 'hex') ||
          convert_to(COALESCE(before_identity_hash, ''), 'UTF8') || decode('00', 'hex') ||
          convert_to(COALESCE(after_identity_hash, ''), 'UTF8') ||
          convert_to(E'\n', 'UTF8'),
          ''::bytea ORDER BY member_kind, member_key
        ),
        ''::bytea
      ),
      'sha256'
    ),
    'hex'
  ) INTO STRICT v_scope_member_count, v_scope_members_hash
  FROM framed;

  INSERT INTO ops.curation_rule_reconcile_operations (
    operation_id, rule_id, operation_kind,
    before_rule_revision, after_rule_revision,
    before_rule_input_hash, after_rule_input_hash,
    command_id, system_operation_key, actor,
    scope_member_count, scope_members_hash
  ) VALUES (
    v_operation_id, p_rule_id, p_operation_kind,
    p_before_rule_revision, p_after_rule_revision,
    p_before_rule_input_hash, p_after_rule_input_hash,
    p_command_id, NULL, p_actor,
    v_scope_member_count, v_scope_members_hash
  );

  INSERT INTO ops.curation_rule_reconcile_scope_members (
    operation_id, member_kind, member_key,
    before_identity_hash, after_identity_hash
  )
  SELECT v_operation_id, scope.member_kind, scope.member_key,
         CASE WHEN p_operation_kind = 'create' THEN NULL ELSE scope.identity_hash END,
         scope.identity_hash
  FROM (
    SELECT 'source_entity'::text AS member_kind,
           entity.source_entity_key AS member_key,
           encode(x_extension.digest(convert_to(jsonb_build_array(
             entity.source_entity_key, head.current_source_record_key
           )::text, 'UTF8'), 'sha256'), 'hex') AS identity_hash
    FROM provider_sync.source_entities AS entity
    LEFT JOIN provider_sync.source_entity_heads AS head
      ON head.source_entity_key = entity.source_entity_key
    WHERE entity.provider_dataset_id = v_provider_dataset_id
    UNION
    SELECT 'feature'::text, link.feature_id,
           encode(x_extension.digest(convert_to(jsonb_build_array(
             link.feature_id, core.feature_uuid::text, core.row_revision,
             core.lifecycle_state, core.publication_state, core.quality_state
           )::text, 'UTF8'), 'sha256'), 'hex')
    FROM provider_sync.source_entities AS entity
    JOIN provider_sync.source_links AS link
      ON link.source_entity_key = entity.source_entity_key
    JOIN feature.features AS core ON core.feature_id = link.feature_id
    WHERE entity.provider_dataset_id = v_provider_dataset_id
  ) AS scope
  ORDER BY scope.member_kind, scope.member_key;

  RETURN v_operation_id;
END
$receipt$;
"""


_COMMAND_EFFECT_SQL = r"""
CREATE TABLE ops.curation_catalog_command_effects (
  command_id bigint PRIMARY KEY
    REFERENCES ops.domain_commands(command_id) ON DELETE RESTRICT,
  operation text NOT NULL,
  resource_kind text NOT NULL
    CHECK (resource_kind IN ('theme','source','rule')),
  resource_id uuid NOT NULL,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE FUNCTION ops.reject_curation_catalog_effect_mutation()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog
AS $guard$
BEGIN
  RAISE EXCEPTION 'curation catalog command effects are append-only'
    USING ERRCODE = '55000';
END
$guard$;

CREATE TRIGGER trg_curation_catalog_effects_immutable
BEFORE UPDATE OR DELETE ON ops.curation_catalog_command_effects
FOR EACH ROW EXECUTE FUNCTION ops.reject_curation_catalog_effect_mutation();

CREATE TRIGGER trg_curation_catalog_effects_no_truncate
BEFORE TRUNCATE ON ops.curation_catalog_command_effects
FOR EACH STATEMENT EXECUTE FUNCTION ops.reject_curation_catalog_effect_mutation();

CREATE FUNCTION feature.claim_curation_catalog_command_effect(
  p_command_id bigint,
  p_operation text,
  p_resource_kind text,
  p_resource_id uuid
)
RETURNS void
LANGUAGE plpgsql
SET search_path = pg_catalog, ops
AS $claim$
BEGIN
  PERFORM 1 FROM ops.domain_commands AS command
  WHERE command.command_id = p_command_id FOR UPDATE;
  IF EXISTS (
    SELECT 1 FROM ops.domain_command_results AS result
    WHERE result.command_id = p_command_id
  ) THEN
    RAISE EXCEPTION 'curation catalog command is already terminal'
      USING ERRCODE = '23514',
        CONSTRAINT = 'ck_tvn40_curation_catalog_open_command';
  END IF;
  INSERT INTO ops.curation_catalog_command_effects (
    command_id, operation, resource_kind, resource_id
  ) VALUES (
    p_command_id, p_operation, p_resource_kind, p_resource_id
  );
END
$claim$;
"""


_COMMAND_PROCEDURES_SQL = r"""
CREATE PROCEDURE feature.create_curated_source_rule_command(
  IN p_theme_id uuid,
  IN p_source_id uuid,
  IN p_place_kind text,
  IN p_category text,
  IN p_region_scope jsonb,
  IN p_detail_selector jsonb,
  IN p_default_action text,
  IN p_priority integer,
  IN p_enabled boolean,
  IN p_metadata jsonb,
  IN p_command_id bigint,
  IN p_principal text,
  OUT o_rule_id uuid,
  OUT o_rule_revision bigint,
  OUT o_generation_id uuid
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, feature, provider_sync, ops, x_extension
AS $command$
DECLARE
  v_command ops.domain_commands%ROWTYPE;
  v_provider_dataset_id bigint;
  v_prelock_count bigint;
  v_prelock_hash text;
  v_current_count bigint;
  v_current_hash text;
  v_rule_input jsonb;
  v_rule_input_hash text;
  v_operation_id uuid;
  v_observed bigint;
  v_removed bigint;
  v_set_hash text;
  v_replayed boolean;
BEGIN
  IF current_setting('transaction_isolation') <> 'serializable' THEN
    RAISE EXCEPTION 'rule command requires SERIALIZABLE transaction'
      USING ERRCODE = '25001';
  END IF;
  IF NOT pg_has_role(session_user, 'ktm_curation_admin_executor', 'member')
     OR pg_has_role(session_user, 'ktm_curation_provider_executor', 'member') THEN
    RAISE EXCEPTION 'rule command requires the admin executor'
      USING ERRCODE = '42501';
  END IF;
  IF p_principal IS NULL OR p_principal <> btrim(p_principal) OR p_principal = ''
     OR p_default_action NOT IN ('candidate','ignore')
     OR jsonb_typeof(p_region_scope) <> 'object'
     OR (p_detail_selector IS NOT NULL AND jsonb_typeof(p_detail_selector) <> 'object')
     OR jsonb_typeof(p_metadata) <> 'object' THEN
    RAISE EXCEPTION 'rule command input is not canonical'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_rule_command_input';
  END IF;
  SELECT command.* INTO STRICT v_command
  FROM ops.domain_commands AS command WHERE command.command_id = p_command_id;
  IF v_command.actor <> p_principal
     OR v_command.operation <> 'admin.curated-source-rule.create' THEN
    RAISE EXCEPTION 'domain command does not match rule create'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_rule_domain_command';
  END IF;

  SELECT source.provider_dataset_id INTO STRICT v_provider_dataset_id
  FROM feature.curated_sources AS source WHERE source.source_id = p_source_id;
  SELECT count(*), encode(x_extension.digest(convert_to(
    COALESCE(jsonb_agg(link.feature_id ORDER BY link.feature_id)::text, '[]'),
    'UTF8'), 'sha256'), 'hex')
  INTO STRICT v_prelock_count, v_prelock_hash
  FROM provider_sync.source_entities AS entity
  JOIN provider_sync.source_links AS link ON link.source_entity_key = entity.source_entity_key
  WHERE entity.provider_dataset_id = v_provider_dataset_id;
  PERFORM pg_advisory_xact_lock(hashtextextended('feature-write:' || link.feature_id, 0))
  FROM provider_sync.source_entities AS entity
  JOIN provider_sync.source_links AS link ON link.source_entity_key = entity.source_entity_key
  WHERE entity.provider_dataset_id = v_provider_dataset_id
  ORDER BY link.feature_id;
  PERFORM pg_advisory_xact_lock(hashtextextended('curation-catalog-write', 0));

  PERFORM 1 FROM feature.curated_themes AS theme
  WHERE theme.theme_id = p_theme_id AND theme.archived_at IS NULL FOR SHARE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'theme is missing or archived'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_rule_theme_active';
  END IF;
  PERFORM 1 FROM feature.curated_sources AS source
  WHERE source.source_id = p_source_id
    AND source.provider_dataset_id = v_provider_dataset_id
    AND source.archived_at IS NULL FOR SHARE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'source is missing, moved, or archived'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_rule_source_active';
  END IF;
  SELECT count(*), encode(x_extension.digest(convert_to(
    COALESCE(jsonb_agg(link.feature_id ORDER BY link.feature_id)::text, '[]'),
    'UTF8'), 'sha256'), 'hex')
  INTO STRICT v_current_count, v_current_hash
  FROM provider_sync.source_entities AS entity
  JOIN provider_sync.source_links AS link ON link.source_entity_key = entity.source_entity_key
  WHERE entity.provider_dataset_id = v_provider_dataset_id;
  IF v_current_count <> v_prelock_count OR v_current_hash <> v_prelock_hash THEN
    RAISE EXCEPTION 'rule create scope changed while acquiring the catalog lock'
      USING ERRCODE = '40001';
  END IF;

  INSERT INTO feature.curated_source_rules (
    theme_id, source_id, place_kind, category, region_scope, detail_selector,
    default_action, priority, enabled, metadata, row_revision, owner_kind,
    owner_provider_dataset_id, updated_at
  ) VALUES (
    p_theme_id, p_source_id, p_place_kind, p_category, p_region_scope,
    p_detail_selector, p_default_action, p_priority, p_enabled, p_metadata,
    1, 'operator', NULL, clock_timestamp()
  ) RETURNING rule_id, row_revision INTO STRICT o_rule_id, o_rule_revision;
  PERFORM feature.claim_curation_catalog_command_effect(
    p_command_id, v_command.operation, 'rule', o_rule_id
  );
  v_rule_input := feature.current_curation_rule_input(o_rule_id);
  v_rule_input_hash := encode(
    x_extension.digest(convert_to(v_rule_input::text, 'UTF8'), 'sha256'), 'hex'
  );
  v_operation_id := feature.create_curation_rule_reconcile_receipt(
    o_rule_id, 'create', NULL, o_rule_revision, NULL, v_rule_input_hash,
    p_command_id, p_principal
  );
  CALL feature.materialize_theme_candidate_generation(
    o_rule_id, 'rule_reconcile', NULL, v_operation_id, p_command_id, NULL,
    jsonb_build_object('schema_version', 1, 'catalog_action', 'create'),
    o_generation_id, v_observed, v_removed, v_set_hash, v_replayed
  );
END
$command$;

CREATE PROCEDURE feature.patch_curated_source_rule_command(
  IN p_rule_id uuid,
  IN p_expected_rule_revision bigint,
  IN p_place_kind text,
  IN p_category text,
  IN p_region_scope jsonb,
  IN p_detail_selector jsonb,
  IN p_default_action text,
  IN p_priority integer,
  IN p_enabled boolean,
  IN p_metadata jsonb,
  IN p_command_id bigint,
  IN p_principal text,
  OUT o_rule_id uuid,
  OUT o_rule_revision bigint,
  OUT o_generation_id uuid
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, feature, provider_sync, ops, x_extension
AS $command$
DECLARE
  v_command ops.domain_commands%ROWTYPE;
  v_rule feature.curated_source_rules%ROWTYPE;
  v_provider_dataset_id bigint;
  v_prelock_count bigint;
  v_prelock_hash text;
  v_current_count bigint;
  v_current_hash text;
  v_before_input jsonb;
  v_after_input jsonb;
  v_before_hash text;
  v_after_hash text;
  v_operation_id uuid;
  v_observed bigint;
  v_removed bigint;
  v_set_hash text;
  v_replayed boolean;
BEGIN
  IF current_setting('transaction_isolation') <> 'serializable' THEN
    RAISE EXCEPTION 'rule command requires SERIALIZABLE transaction'
      USING ERRCODE = '25001';
  END IF;
  IF NOT pg_has_role(session_user, 'ktm_curation_admin_executor', 'member')
     OR pg_has_role(session_user, 'ktm_curation_provider_executor', 'member') THEN
    RAISE EXCEPTION 'rule command requires the admin executor'
      USING ERRCODE = '42501';
  END IF;
  IF p_expected_rule_revision < 1 OR p_principal IS NULL
     OR p_principal <> btrim(p_principal) OR p_principal = ''
     OR p_default_action NOT IN ('candidate','ignore')
     OR jsonb_typeof(p_region_scope) <> 'object'
     OR (p_detail_selector IS NOT NULL AND jsonb_typeof(p_detail_selector) <> 'object')
     OR jsonb_typeof(p_metadata) <> 'object' THEN
    RAISE EXCEPTION 'rule command input is not canonical'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_rule_command_input';
  END IF;
  SELECT command.* INTO STRICT v_command
  FROM ops.domain_commands AS command WHERE command.command_id = p_command_id;
  IF v_command.actor <> p_principal
     OR v_command.operation <> 'admin.curated-source-rule.patch' THEN
    RAISE EXCEPTION 'domain command does not match rule patch'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_rule_domain_command';
  END IF;

  SELECT source.provider_dataset_id INTO STRICT v_provider_dataset_id
  FROM feature.curated_source_rules AS rule
  JOIN feature.curated_sources AS source ON source.source_id = rule.source_id
  WHERE rule.rule_id = p_rule_id;
  SELECT count(*), encode(x_extension.digest(convert_to(
    COALESCE(jsonb_agg(touched.feature_id ORDER BY touched.feature_id)::text, '[]'),
    'UTF8'), 'sha256'), 'hex')
  INTO STRICT v_prelock_count, v_prelock_hash
  FROM (
    SELECT candidate.feature_id FROM feature.theme_feature_candidates AS candidate
    WHERE candidate.rule_id = p_rule_id AND candidate.disposition = 'active'
    UNION
    SELECT link.feature_id FROM provider_sync.source_entities AS entity
    JOIN provider_sync.source_links AS link ON link.source_entity_key = entity.source_entity_key
    WHERE entity.provider_dataset_id = v_provider_dataset_id
  ) AS touched;
  PERFORM pg_advisory_xact_lock(hashtextextended('feature-write:' || touched.feature_id, 0))
  FROM (
    SELECT candidate.feature_id FROM feature.theme_feature_candidates AS candidate
    WHERE candidate.rule_id = p_rule_id AND candidate.disposition = 'active'
    UNION
    SELECT link.feature_id FROM provider_sync.source_entities AS entity
    JOIN provider_sync.source_links AS link ON link.source_entity_key = entity.source_entity_key
    WHERE entity.provider_dataset_id = v_provider_dataset_id
  ) AS touched ORDER BY touched.feature_id;
  PERFORM pg_advisory_xact_lock(hashtextextended('curation-catalog-write', 0));

  SELECT rule.* INTO STRICT v_rule FROM feature.curated_source_rules AS rule
  WHERE rule.rule_id = p_rule_id FOR UPDATE;
  PERFORM 1 FROM feature.curated_themes AS theme WHERE theme.theme_id = v_rule.theme_id FOR SHARE;
  PERFORM 1 FROM feature.curated_sources AS source
  WHERE source.source_id = v_rule.source_id
    AND source.provider_dataset_id = v_provider_dataset_id FOR SHARE;
  SELECT count(*), encode(x_extension.digest(convert_to(
    COALESCE(jsonb_agg(touched.feature_id ORDER BY touched.feature_id)::text, '[]'),
    'UTF8'), 'sha256'), 'hex')
  INTO STRICT v_current_count, v_current_hash
  FROM (
    SELECT candidate.feature_id FROM feature.theme_feature_candidates AS candidate
    WHERE candidate.rule_id = p_rule_id AND candidate.disposition = 'active'
    UNION
    SELECT link.feature_id FROM provider_sync.source_entities AS entity
    JOIN provider_sync.source_links AS link ON link.source_entity_key = entity.source_entity_key
    WHERE entity.provider_dataset_id = v_provider_dataset_id
  ) AS touched;
  IF v_current_count <> v_prelock_count OR v_current_hash <> v_prelock_hash THEN
    RAISE EXCEPTION 'rule patch scope changed while acquiring the catalog lock'
      USING ERRCODE = '40001';
  END IF;
  IF v_rule.row_revision <> p_expected_rule_revision THEN
    RAISE EXCEPTION 'rule revision mismatch'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_expected_revision';
  END IF;
  IF v_rule.archived_at IS NOT NULL THEN
    RAISE EXCEPTION 'archived rule cannot be patched'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_rule_active';
  END IF;
  IF v_rule.owner_kind IS DISTINCT FROM 'operator' THEN
    RAISE EXCEPTION 'provider-owned rule cannot be patched by an admin command'
      USING ERRCODE = '42501';
  END IF;
  PERFORM feature.claim_curation_catalog_command_effect(
    p_command_id, v_command.operation, 'rule', v_rule.rule_id
  );
  IF v_rule.place_kind IS NOT DISTINCT FROM p_place_kind
     AND v_rule.category IS NOT DISTINCT FROM p_category
     AND v_rule.region_scope = p_region_scope
     AND v_rule.detail_selector IS NOT DISTINCT FROM p_detail_selector
     AND v_rule.default_action = p_default_action
     AND v_rule.priority = p_priority
     AND v_rule.enabled = p_enabled
     AND v_rule.metadata = p_metadata THEN
    o_rule_id := v_rule.rule_id;
    o_rule_revision := v_rule.row_revision;
    o_generation_id := NULL;
    RETURN;
  END IF;
  IF v_rule.place_kind IS NOT DISTINCT FROM p_place_kind
     AND v_rule.category IS NOT DISTINCT FROM p_category
     AND v_rule.region_scope = p_region_scope
     AND v_rule.detail_selector IS NOT DISTINCT FROM p_detail_selector
     AND v_rule.default_action = p_default_action
     AND v_rule.priority = p_priority
     AND v_rule.enabled = p_enabled THEN
    UPDATE feature.curated_source_rules AS rule
    SET metadata = p_metadata,
        row_revision = rule.row_revision + 1,
        updated_at = clock_timestamp()
    WHERE rule.rule_id = p_rule_id
    RETURNING rule.rule_id, rule.row_revision
    INTO STRICT o_rule_id, o_rule_revision;
    o_generation_id := NULL;
    RETURN;
  END IF;
  v_before_input := feature.current_curation_rule_input(p_rule_id);
  v_before_hash := encode(
    x_extension.digest(convert_to(v_before_input::text, 'UTF8'), 'sha256'), 'hex'
  );
  UPDATE feature.curated_source_rules AS rule
  SET place_kind = p_place_kind, category = p_category,
      region_scope = p_region_scope, detail_selector = p_detail_selector,
      default_action = p_default_action, priority = p_priority,
      enabled = p_enabled, metadata = p_metadata,
      row_revision = rule.row_revision + 1, updated_at = clock_timestamp()
  WHERE rule.rule_id = p_rule_id
  RETURNING rule.rule_id, rule.row_revision INTO STRICT o_rule_id, o_rule_revision;
  v_after_input := feature.current_curation_rule_input(p_rule_id);
  v_after_hash := encode(
    x_extension.digest(convert_to(v_after_input::text, 'UTF8'), 'sha256'), 'hex'
  );
  v_operation_id := feature.create_curation_rule_reconcile_receipt(
    p_rule_id, 'patch', v_rule.row_revision, o_rule_revision,
    v_before_hash, v_after_hash, p_command_id, p_principal
  );
  CALL feature.materialize_theme_candidate_generation(
    p_rule_id, 'rule_reconcile', NULL, v_operation_id, p_command_id, NULL,
    jsonb_build_object('schema_version', 1, 'catalog_action', 'patch'),
    o_generation_id, v_observed, v_removed, v_set_hash, v_replayed
  );
END
$command$;

CREATE PROCEDURE feature.archive_curated_source_rule_command(
  IN p_rule_id uuid,
  IN p_expected_rule_revision bigint,
  IN p_command_id bigint,
  IN p_reason_code text,
  IN p_principal text,
  OUT o_rule_id uuid,
  OUT o_rule_revision bigint,
  OUT o_generation_id uuid
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, feature, provider_sync, ops, x_extension
AS $command$
DECLARE
  v_command ops.domain_commands%ROWTYPE;
  v_rule feature.curated_source_rules%ROWTYPE;
  v_provider_dataset_id bigint;
  v_prelock_count bigint;
  v_prelock_hash text;
  v_current_count bigint;
  v_current_hash text;
  v_before_input jsonb;
  v_after_input jsonb;
  v_before_hash text;
  v_after_hash text;
  v_operation_id uuid;
  v_observed bigint;
  v_removed bigint;
  v_set_hash text;
  v_replayed boolean;
BEGIN
  IF current_setting('transaction_isolation') <> 'serializable' THEN
    RAISE EXCEPTION 'rule command requires SERIALIZABLE transaction'
      USING ERRCODE = '25001';
  END IF;
  IF NOT pg_has_role(session_user, 'ktm_curation_admin_executor', 'member')
     OR pg_has_role(session_user, 'ktm_curation_provider_executor', 'member') THEN
    RAISE EXCEPTION 'rule command requires the admin executor'
      USING ERRCODE = '42501';
  END IF;
  IF p_expected_rule_revision < 1 OR p_principal IS NULL
     OR p_principal <> btrim(p_principal) OR p_principal = ''
     OR p_reason_code IS NULL OR p_reason_code <> btrim(p_reason_code)
     OR p_reason_code = '' THEN
    RAISE EXCEPTION 'rule archive input is not canonical'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_rule_command_input';
  END IF;
  SELECT command.* INTO STRICT v_command
  FROM ops.domain_commands AS command WHERE command.command_id = p_command_id;
  IF v_command.actor <> p_principal
     OR v_command.operation <> 'admin.curated-source-rule.archive' THEN
    RAISE EXCEPTION 'domain command does not match rule archive'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_rule_domain_command';
  END IF;
  SELECT source.provider_dataset_id INTO STRICT v_provider_dataset_id
  FROM feature.curated_source_rules AS rule
  JOIN feature.curated_sources AS source ON source.source_id = rule.source_id
  WHERE rule.rule_id = p_rule_id;
  SELECT count(*), encode(x_extension.digest(convert_to(
    COALESCE(jsonb_agg(touched.feature_id ORDER BY touched.feature_id)::text, '[]'),
    'UTF8'), 'sha256'), 'hex')
  INTO STRICT v_prelock_count, v_prelock_hash
  FROM (
    SELECT candidate.feature_id FROM feature.theme_feature_candidates AS candidate
    WHERE candidate.rule_id = p_rule_id AND candidate.disposition = 'active'
    UNION
    SELECT link.feature_id FROM provider_sync.source_entities AS entity
    JOIN provider_sync.source_links AS link ON link.source_entity_key = entity.source_entity_key
    WHERE entity.provider_dataset_id = v_provider_dataset_id
  ) AS touched;
  PERFORM pg_advisory_xact_lock(hashtextextended('feature-write:' || touched.feature_id, 0))
  FROM (
    SELECT candidate.feature_id FROM feature.theme_feature_candidates AS candidate
    WHERE candidate.rule_id = p_rule_id AND candidate.disposition = 'active'
    UNION
    SELECT link.feature_id FROM provider_sync.source_entities AS entity
    JOIN provider_sync.source_links AS link ON link.source_entity_key = entity.source_entity_key
    WHERE entity.provider_dataset_id = v_provider_dataset_id
  ) AS touched ORDER BY touched.feature_id;
  PERFORM pg_advisory_xact_lock(hashtextextended('curation-catalog-write', 0));
  SELECT rule.* INTO STRICT v_rule FROM feature.curated_source_rules AS rule
  WHERE rule.rule_id = p_rule_id FOR UPDATE;
  SELECT count(*), encode(x_extension.digest(convert_to(
    COALESCE(jsonb_agg(touched.feature_id ORDER BY touched.feature_id)::text, '[]'),
    'UTF8'), 'sha256'), 'hex')
  INTO STRICT v_current_count, v_current_hash
  FROM (
    SELECT candidate.feature_id FROM feature.theme_feature_candidates AS candidate
    WHERE candidate.rule_id = p_rule_id AND candidate.disposition = 'active'
    UNION
    SELECT link.feature_id FROM provider_sync.source_entities AS entity
    JOIN provider_sync.source_links AS link ON link.source_entity_key = entity.source_entity_key
    WHERE entity.provider_dataset_id = v_provider_dataset_id
  ) AS touched;
  IF v_current_count <> v_prelock_count OR v_current_hash <> v_prelock_hash THEN
    RAISE EXCEPTION 'rule archive scope changed while acquiring the catalog lock'
      USING ERRCODE = '40001';
  END IF;
  IF v_rule.row_revision <> p_expected_rule_revision THEN
    RAISE EXCEPTION 'rule revision mismatch'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_expected_revision';
  END IF;
  IF v_rule.owner_kind IS DISTINCT FROM 'operator' THEN
    RAISE EXCEPTION 'provider-owned rule cannot be archived by an admin command'
      USING ERRCODE = '42501';
  END IF;
  IF v_rule.archived_at IS NOT NULL THEN
    RAISE EXCEPTION 'rule is already archived'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_rule_active';
  END IF;
  PERFORM feature.claim_curation_catalog_command_effect(
    p_command_id, v_command.operation, 'rule', v_rule.rule_id
  );
  v_before_input := feature.current_curation_rule_input(p_rule_id);
  v_before_hash := encode(
    x_extension.digest(convert_to(v_before_input::text, 'UTF8'), 'sha256'), 'hex'
  );
  UPDATE feature.curated_source_rules AS rule
  SET archived_at = clock_timestamp(), enabled = false,
      metadata = rule.metadata || jsonb_build_object('archive_reason', p_reason_code),
      row_revision = rule.row_revision + 1, updated_at = clock_timestamp()
  WHERE rule.rule_id = p_rule_id
  RETURNING rule.rule_id, rule.row_revision INTO STRICT o_rule_id, o_rule_revision;
  v_after_input := feature.current_curation_rule_input(p_rule_id);
  v_after_hash := encode(
    x_extension.digest(convert_to(v_after_input::text, 'UTF8'), 'sha256'), 'hex'
  );
  v_operation_id := feature.create_curation_rule_reconcile_receipt(
    p_rule_id, 'archive', v_rule.row_revision, o_rule_revision,
    v_before_hash, v_after_hash, p_command_id, p_principal
  );
  CALL feature.materialize_theme_candidate_generation(
    p_rule_id, 'rule_reconcile', NULL, v_operation_id, p_command_id, NULL,
    jsonb_build_object('schema_version', 1, 'catalog_action', 'archive'),
    o_generation_id, v_observed, v_removed, v_set_hash, v_replayed
  );
END
$command$;
"""


_CREATE_SIGNATURE = (
    "feature.create_curated_source_rule_command("
    "uuid,uuid,text,text,jsonb,jsonb,text,integer,boolean,jsonb,bigint,text)"
)
_PATCH_SIGNATURE = (
    "feature.patch_curated_source_rule_command("
    "uuid,bigint,text,text,jsonb,jsonb,text,integer,boolean,jsonb,bigint,text)"
)
_ARCHIVE_SIGNATURE = (
    "feature.archive_curated_source_rule_command(uuid,bigint,bigint,text,text)"
)
_RECEIPT_SIGNATURE = (
    "feature.create_curation_rule_reconcile_receipt("
    "uuid,text,bigint,bigint,text,text,bigint,text)"
)


def upgrade() -> None:
    op.execute(_RECONCILE_RECEIPT_FUNCTION_SQL)
    _execute_commands(_COMMAND_EFFECT_SQL)
    op.execute(
        "ALTER FUNCTION feature.claim_curation_catalog_command_effect("
        "bigint,text,text,uuid) OWNER TO ktm_curation_command_owner"
    )
    op.execute(
        "GRANT INSERT, SELECT ON TABLE ops.curation_catalog_command_effects "
        "TO ktm_curation_command_owner"
    )
    op.execute(
        "GRANT SELECT ON TABLE ops.domain_command_results "
        "TO ktm_curation_command_owner"
    )
    op.execute(
        "GRANT SELECT, UPDATE (command_id) ON TABLE ops.domain_commands "
        "TO ktm_curation_command_owner"
    )
    _execute_commands(_COMMAND_PROCEDURES_SQL)
    op.execute(f"ALTER FUNCTION {_RECEIPT_SIGNATURE} OWNER TO ktm_curation_command_owner")
    for signature in (_CREATE_SIGNATURE, _PATCH_SIGNATURE, _ARCHIVE_SIGNATURE):
        op.execute(f"ALTER PROCEDURE {signature} OWNER TO ktm_curation_command_owner")
    op.execute(
        "GRANT INSERT (theme_id, source_id, place_kind, category, region_scope, "
        "detail_selector, default_action, priority, enabled, metadata, row_revision, "
        "owner_kind, owner_provider_dataset_id, updated_at) ON TABLE "
        "feature.curated_source_rules TO ktm_curation_command_owner"
    )
    op.execute(
        "GRANT UPDATE (place_kind, category, region_scope, detail_selector, "
        "default_action, priority, enabled, metadata, archived_at, row_revision, "
        "updated_at) ON TABLE feature.curated_source_rules "
        "TO ktm_curation_command_owner"
    )
    op.execute("SET ROLE ktm_curation_command_owner")
    op.execute(
        "REVOKE ALL ON FUNCTION feature.claim_curation_catalog_command_effect("
        "bigint,text,text,uuid) FROM PUBLIC, ktm_feature_runtime, "
        "ktm_feature_api_runtime, ktm_feature_dagster_runtime, "
        "ktm_curation_admin_executor, ktm_curation_provider_executor"
    )
    op.execute(
        f"REVOKE ALL ON FUNCTION {_RECEIPT_SIGNATURE} FROM PUBLIC, "
        "ktm_feature_runtime, ktm_feature_api_runtime, ktm_feature_dagster_runtime, "
        "ktm_curation_admin_executor, ktm_curation_provider_executor"
    )
    for signature in (_CREATE_SIGNATURE, _PATCH_SIGNATURE, _ARCHIVE_SIGNATURE):
        op.execute(
            f"REVOKE ALL ON PROCEDURE {signature} FROM PUBLIC, ktm_feature_runtime, "
            "ktm_feature_api_runtime, ktm_feature_dagster_runtime, "
            "ktm_curation_provider_executor"
        )
        op.execute(
            f"GRANT EXECUTE ON PROCEDURE {signature} TO ktm_curation_admin_executor"
        )
    op.execute("SET ROLE ktm_feature_schema_owner")


def downgrade() -> None:
    raise RuntimeError("0206_tvn40_rule_catalog_commands is forward-only; rebuild with the T-VN-40 release head")
