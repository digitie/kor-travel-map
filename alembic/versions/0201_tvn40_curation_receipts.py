"""T-VN-40A curation receipt, candidate, and audit spine.

Revision ID: 0201_tvn40_curation_receipts
Revises: 0200_schema_baseline

The final T-VN-40 cutover is forward-only.  This first revision installs the
closed receipt/audit relations and revision columns before the later writer
rewire and legacy-overlay removal revisions in the same release PR.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# Frozen PostgreSQL contract SQL is intentionally formatted independently of
# Python's line-length convention.
# ruff: noqa: E501

revision: str = "0201_tvn40_curation_receipts"
down_revision: str | Sequence[str] | None = "0200_schema_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _execute_commands(source: str) -> None:
    """Execute one PostgreSQL statement at a time for the asyncpg Alembic path.

    asyncpg deliberately rejects multiple commands in one prepared statement.
    Dollar-quoted PL/pgSQL bodies may contain semicolons, so a plain ``split``
    is unsafe; this bounded splitter understands SQL string/identifier quotes
    and PostgreSQL dollar tags used by the frozen migration text below.
    """

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


_ROLE_ASSERTIONS_SQL = r"""
DO $tvn40_roles$
DECLARE
    v_role text;
BEGIN
    FOREACH v_role IN ARRAY ARRAY[
        'ktm_curation_command_owner',
        'ktm_curation_audit_writer',
        'ktm_curation_admin_executor',
        'ktm_curation_provider_executor'
    ] LOOP
        IF NOT EXISTS (
            SELECT 1
            FROM pg_catalog.pg_roles
            WHERE rolname = v_role
              AND NOT rolcanlogin
              AND NOT rolinherit
              AND NOT rolsuper
              AND NOT rolcreaterole
              AND NOT rolcreatedb
              AND NOT rolbypassrls
        ) THEN
            RAISE EXCEPTION 'T-VN-40 role % is missing or unsafe', v_role
                USING ERRCODE = '42501';
        END IF;
    END LOOP;

    IF NOT pg_has_role('ktm_feature_schema_owner', 'ktm_curation_command_owner', 'set')
       OR NOT pg_has_role('ktm_feature_schema_owner', 'ktm_curation_audit_writer', 'set')
       OR NOT pg_has_role('ktm_feature_api_runtime', 'ktm_curation_admin_executor', 'member')
       OR NOT pg_has_role('ktm_feature_dagster_runtime', 'ktm_curation_provider_executor', 'member')
       OR pg_has_role('ktm_feature_api_runtime', 'ktm_curation_provider_executor', 'member')
       OR pg_has_role('ktm_feature_dagster_runtime', 'ktm_curation_admin_executor', 'member') THEN
        RAISE EXCEPTION 'T-VN-40 role membership graph is not exact'
            USING ERRCODE = '42501';
    END IF;
END
$tvn40_roles$;
"""


_REVISION_COLUMNS_SQL = r"""
ALTER TABLE feature.curated_themes
  ADD COLUMN row_revision bigint NOT NULL DEFAULT 1,
  ADD COLUMN archived_at timestamptz,
  ADD COLUMN owner_kind text,
  ADD COLUMN owner_provider_dataset_id bigint,
  ADD CONSTRAINT fk_curated_themes_owner_provider_dataset
    FOREIGN KEY (owner_provider_dataset_id)
    REFERENCES provider_sync.provider_datasets(provider_dataset_id) ON DELETE RESTRICT,
  ADD CONSTRAINT ck_curated_themes_owner_shape CHECK (
    (owner_kind IS NULL AND owner_provider_dataset_id IS NULL)
    OR (owner_kind = 'operator' AND owner_provider_dataset_id IS NULL)
    OR (owner_kind = 'provider_dataset' AND owner_provider_dataset_id IS NOT NULL)
  ) NOT VALID,
  ADD CONSTRAINT ck_curated_themes_revision_positive CHECK (row_revision >= 1);

ALTER TABLE feature.curated_sources
  ADD COLUMN row_revision bigint NOT NULL DEFAULT 1,
  ADD COLUMN observation_revision bigint NOT NULL DEFAULT 1,
  ADD COLUMN archived_at timestamptz,
  ADD CONSTRAINT ck_curated_sources_revision_positive CHECK (row_revision >= 1),
  ADD CONSTRAINT ck_curated_sources_observation_revision_positive
    CHECK (observation_revision >= 1);

ALTER TABLE feature.curated_source_rules
  ADD COLUMN row_revision bigint NOT NULL DEFAULT 1,
  ADD COLUMN archived_at timestamptz,
  ADD COLUMN owner_kind text,
  ADD COLUMN owner_provider_dataset_id bigint,
  ADD CONSTRAINT fk_curated_source_rules_owner_provider_dataset
    FOREIGN KEY (owner_provider_dataset_id)
    REFERENCES provider_sync.provider_datasets(provider_dataset_id) ON DELETE RESTRICT,
  ADD CONSTRAINT ck_curated_source_rules_owner_shape CHECK (
    (owner_kind IS NULL AND owner_provider_dataset_id IS NULL)
    OR (owner_kind = 'operator' AND owner_provider_dataset_id IS NULL)
    OR (owner_kind = 'provider_dataset' AND owner_provider_dataset_id IS NOT NULL)
  ) NOT VALID,
  ADD CONSTRAINT ck_curated_source_rules_revision_positive CHECK (row_revision >= 1);

ALTER TABLE feature.curation_collections
  ADD COLUMN row_revision bigint NOT NULL DEFAULT 1,
  ADD CONSTRAINT ck_curation_collections_revision_positive CHECK (row_revision >= 1);

ALTER TABLE feature.curation_items
  ADD COLUMN row_revision bigint NOT NULL DEFAULT 1,
  ADD CONSTRAINT ck_curation_items_revision_positive CHECK (row_revision >= 1);
"""


_CURRENT_RULE_INPUT_FUNCTION_SQL = r"""
CREATE FUNCTION feature.current_curation_rule_input(p_rule_id uuid)
RETURNS jsonb
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, feature, provider_sync
AS $rule_input$
SELECT jsonb_build_object(
  'schema_version', 3,
  'rule', jsonb_build_object(
    'rule_id', rule.rule_id::text,
    'theme_id', rule.theme_id::text,
    'source_id', rule.source_id::text,
    'place_kind', rule.place_kind,
    'category', rule.category,
    'region_scope', rule.region_scope,
    'detail_selector', rule.detail_selector,
    'default_action', rule.default_action,
    'priority', rule.priority,
    'enabled', rule.enabled,
    'archived_at', to_jsonb(rule.archived_at),
    'owner_kind', rule.owner_kind,
    'owner_provider_dataset_id', rule.owner_provider_dataset_id
  ),
  'theme', jsonb_build_object(
    'theme_id', theme.theme_id::text,
    'archived_at', to_jsonb(theme.archived_at),
    'owner_kind', theme.owner_kind,
    'owner_provider_dataset_id', theme.owner_provider_dataset_id
  ),
  'source', jsonb_build_object(
    'source_id', source.source_id::text,
    'provider_dataset_id', source.provider_dataset_id,
    'archived_at', to_jsonb(source.archived_at)
  )
)
FROM feature.curated_source_rules AS rule
JOIN feature.curated_themes AS theme ON theme.theme_id = rule.theme_id
JOIN feature.curated_sources AS source ON source.source_id = rule.source_id
WHERE rule.rule_id = p_rule_id
$rule_input$;
"""


_RECEIPT_TABLES_SQL = r"""
CREATE TABLE ops.curation_rule_reconcile_operations (
  operation_id uuid PRIMARY KEY DEFAULT x_extension.gen_random_uuid(),
  rule_id uuid NOT NULL
    REFERENCES feature.curated_source_rules(rule_id) ON DELETE RESTRICT,
  operation_kind text NOT NULL CHECK (operation_kind IN ('create','patch','archive')),
  before_rule_revision bigint CHECK (before_rule_revision >= 1),
  after_rule_revision bigint NOT NULL CHECK (after_rule_revision >= 1),
  before_rule_input_hash text
    CHECK (before_rule_input_hash ~ '^[0-9a-f]{64}$'),
  after_rule_input_hash text NOT NULL
    CHECK (after_rule_input_hash ~ '^[0-9a-f]{64}$'),
  command_id bigint REFERENCES ops.domain_commands(command_id) ON DELETE RESTRICT,
  system_operation_key text,
  actor text NOT NULL CHECK (actor = btrim(actor) AND actor <> ''),
  scope_member_count bigint NOT NULL CHECK (scope_member_count >= 0),
  scope_members_hash text NOT NULL CHECK (scope_members_hash ~ '^[0-9a-f]{64}$'),
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  CONSTRAINT ck_curation_rule_reconcile_operation_origin CHECK (
    (command_id IS NOT NULL AND system_operation_key IS NULL)
    OR (command_id IS NULL AND system_operation_key IS NOT NULL
      AND system_operation_key = btrim(system_operation_key)
      AND system_operation_key <> '')
  ),
  CONSTRAINT ck_curation_rule_reconcile_operation_revision_shape CHECK (
    (operation_kind = 'create'
      AND before_rule_revision IS NULL AND before_rule_input_hash IS NULL
      AND after_rule_revision = 1)
    OR (operation_kind IN ('patch','archive')
      AND before_rule_revision IS NOT NULL AND before_rule_input_hash IS NOT NULL
      AND after_rule_revision > before_rule_revision)
  )
);

CREATE UNIQUE INDEX uq_curation_rule_reconcile_command
  ON ops.curation_rule_reconcile_operations (rule_id, command_id)
  WHERE command_id IS NOT NULL;

CREATE UNIQUE INDEX uq_curation_rule_reconcile_system_operation
  ON ops.curation_rule_reconcile_operations (rule_id, system_operation_key)
  WHERE system_operation_key IS NOT NULL;

CREATE TABLE ops.curation_rule_reconcile_scope_members (
  operation_id uuid NOT NULL
    REFERENCES ops.curation_rule_reconcile_operations(operation_id) ON DELETE RESTRICT,
  member_kind text NOT NULL CHECK (member_kind IN ('source_entity','feature')),
  member_key text NOT NULL CHECK (member_key = btrim(member_key) AND member_key <> ''),
  before_identity_hash text CHECK (before_identity_hash ~ '^[0-9a-f]{64}$'),
  after_identity_hash text CHECK (after_identity_hash ~ '^[0-9a-f]{64}$'),
  PRIMARY KEY (operation_id, member_kind, member_key),
  CONSTRAINT ck_curation_rule_reconcile_scope_identity CHECK (
    before_identity_hash IS NOT NULL OR after_identity_hash IS NOT NULL
  )
);

CREATE TABLE ops.curation_cutover_identity_mappings (
  legacy_curated_feature_id uuid PRIMARY KEY,
  collection_id uuid NOT NULL
    REFERENCES feature.curation_collections(collection_id) ON DELETE RESTRICT,
  curation_item_id uuid NOT NULL UNIQUE
    REFERENCES feature.curation_items(curation_item_id) ON DELETE RESTRICT,
  mapping_kind text NOT NULL CHECK (
    mapping_kind IN ('legacy_projection','official_membership','manual_membership')
  ),
  source_row_hash text NOT NULL CHECK (source_row_hash ~ '^[0-9a-f]{64}$'),
  created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE feature.theme_candidate_generations (
  generation_id uuid PRIMARY KEY DEFAULT x_extension.gen_random_uuid(),
  rule_id uuid NOT NULL
    REFERENCES feature.curated_source_rules(rule_id) ON DELETE RESTRICT,
  rule_row_revision bigint NOT NULL CHECK (rule_row_revision >= 1),
  generation_kind text NOT NULL CHECK (
    generation_kind IN ('provider_full_snapshot','scoped_reconcile','rule_reconcile','legacy_backfill')
  ),
  source_job_id uuid REFERENCES ops.import_jobs(job_id) ON DELETE RESTRICT,
  reconcile_operation_id uuid
    REFERENCES ops.curation_rule_reconcile_operations(operation_id) ON DELETE RESTRICT,
  command_id bigint REFERENCES ops.domain_commands(command_id) ON DELETE RESTRICT,
  generation_key text NOT NULL UNIQUE
    CHECK (generation_key = btrim(generation_key) AND generation_key <> ''),
  rule_input_hash text NOT NULL CHECK (rule_input_hash ~ '^[0-9a-f]{64}$'),
  rule_input jsonb NOT NULL CHECK (jsonb_typeof(rule_input) = 'object'),
  generation_input_set_hash text NOT NULL
    CHECK (generation_input_set_hash ~ '^[0-9a-f]{64}$'),
  observed_candidate_count bigint NOT NULL CHECK (observed_candidate_count >= 0),
  eligibility_removed_candidate_count bigint NOT NULL
    CHECK (eligibility_removed_candidate_count >= 0),
  completed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  CONSTRAINT ck_theme_candidate_generations_origin CHECK (
    (generation_kind = 'provider_full_snapshot'
      AND source_job_id IS NOT NULL
      AND reconcile_operation_id IS NULL AND command_id IS NULL)
    OR (generation_kind IN ('scoped_reconcile','rule_reconcile')
      AND source_job_id IS NULL AND reconcile_operation_id IS NOT NULL)
    OR (generation_kind = 'legacy_backfill'
      AND source_job_id IS NULL AND reconcile_operation_id IS NULL AND command_id IS NULL)
  )
);
CREATE INDEX idx_theme_candidate_generations_rule_completed
  ON feature.theme_candidate_generations
    (rule_id, completed_at DESC, generation_id DESC);
CREATE UNIQUE INDEX uq_theme_candidate_generation_provider_job
  ON feature.theme_candidate_generations (rule_id, source_job_id)
  WHERE generation_kind = 'provider_full_snapshot';

CREATE UNIQUE INDEX uq_theme_candidate_generation_reconcile_operation
  ON feature.theme_candidate_generations (rule_id, reconcile_operation_id)
  WHERE generation_kind IN ('scoped_reconcile','rule_reconcile');

CREATE TABLE feature.theme_candidate_generation_observations (
  generation_id uuid NOT NULL
    REFERENCES feature.theme_candidate_generations(generation_id) ON DELETE RESTRICT,
  candidate_id uuid NOT NULL,
  source_entity_key text NOT NULL,
  feature_id text NOT NULL,
  source_record_key text NOT NULL,
  candidate_input_hash text NOT NULL CHECK (candidate_input_hash ~ '^[0-9a-f]{64}$'),
  observed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  PRIMARY KEY (generation_id, candidate_id),
  CONSTRAINT uq_theme_candidate_generation_observation_identity
    UNIQUE (generation_id, source_entity_key, feature_id)
);

CREATE INDEX idx_theme_candidate_generation_observations_candidate
  ON feature.theme_candidate_generation_observations (candidate_id, generation_id DESC);
"""


_CANDIDATE_TABLES_SQL = r"""
CREATE TABLE feature.theme_feature_candidates (
  candidate_id uuid PRIMARY KEY DEFAULT x_extension.gen_random_uuid(),
  rule_id uuid NOT NULL
    REFERENCES feature.curated_source_rules(rule_id) ON DELETE RESTRICT,
  source_entity_key text NOT NULL
    REFERENCES provider_sync.source_entities(source_entity_key) ON DELETE RESTRICT,
  feature_id text NOT NULL
    REFERENCES feature.features(feature_id) ON DELETE RESTRICT,
  source_record_key text NOT NULL,
  rule_row_revision bigint NOT NULL CHECK (rule_row_revision >= 1),
  rule_input_hash text NOT NULL CHECK (rule_input_hash ~ '^[0-9a-f]{64}$'),
  source_record_hash text NOT NULL CHECK (source_record_hash ~ '^[0-9a-f]{1,64}$'),
  candidate_input_hash text NOT NULL CHECK (candidate_input_hash ~ '^[0-9a-f]{64}$'),
  review_state text NOT NULL DEFAULT 'open'
    CHECK (review_state IN ('open','promoted','rejected')),
  eligibility_present boolean NOT NULL DEFAULT true,
  disposition text NOT NULL DEFAULT 'active'
    CHECK (disposition IN ('active','merged')),
  merged_into_candidate_id uuid
    REFERENCES feature.theme_feature_candidates(candidate_id) ON DELETE RESTRICT,
  retired_at timestamptz,
  rank_score numeric(10,4) NOT NULL DEFAULT 0,
  proposal_title text,
  proposal_summary text,
  match_evidence jsonb NOT NULL DEFAULT '{}'::jsonb
    CHECK (jsonb_typeof(match_evidence) = 'object'),
  row_revision bigint NOT NULL DEFAULT 1 CHECK (row_revision >= 1),
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  CONSTRAINT uq_theme_feature_candidates_rule_entity_feature
    UNIQUE (rule_id, source_entity_key, feature_id),
  CONSTRAINT ck_theme_feature_candidates_disposition CHECK (
    (disposition = 'active' AND merged_into_candidate_id IS NULL AND retired_at IS NULL)
    OR (disposition = 'merged' AND merged_into_candidate_id IS NOT NULL AND retired_at IS NOT NULL)
  ),
  CONSTRAINT fk_theme_feature_candidates_source_record
    FOREIGN KEY (source_entity_key, source_record_key)
    REFERENCES provider_sync.source_records(source_entity_key, source_record_key)
    ON DELETE RESTRICT
);

CREATE INDEX idx_theme_feature_candidates_rule_open_keyset
  ON feature.theme_feature_candidates
    (rule_id, updated_at DESC, candidate_id DESC)
  WHERE disposition = 'active' AND review_state = 'open' AND eligibility_present;

CREATE INDEX idx_theme_feature_candidates_open_keyset
  ON feature.theme_feature_candidates (updated_at DESC, candidate_id DESC)
  WHERE disposition = 'active' AND review_state = 'open' AND eligibility_present;

CREATE INDEX idx_theme_feature_candidates_state_keyset
  ON feature.theme_feature_candidates
    (review_state, eligibility_present, updated_at DESC, candidate_id DESC)
  WHERE disposition = 'active';

CREATE INDEX idx_theme_feature_candidates_feature_state
  ON feature.theme_feature_candidates
    (feature_id, review_state, eligibility_present, candidate_id)
  WHERE disposition = 'active';

CREATE INDEX idx_theme_feature_candidates_source_entity
  ON feature.theme_feature_candidates (source_entity_key, candidate_id);

CREATE TABLE feature.theme_feature_candidate_transitions (
  transition_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  candidate_id uuid NOT NULL,
  from_feature_id text,
  to_feature_id text,
  rule_id uuid NOT NULL,
  source_entity_key text NOT NULL,
  from_review_state text CHECK (from_review_state IN ('open','promoted','rejected')),
  to_review_state text NOT NULL CHECK (to_review_state IN ('open','promoted','rejected')),
  from_eligibility_present boolean,
  to_eligibility_present boolean NOT NULL,
  from_disposition text CHECK (from_disposition IN ('active','merged')),
  to_disposition text NOT NULL CHECK (to_disposition IN ('active','merged')),
  winner_candidate_id uuid,
  transition_kind text NOT NULL CHECK (
    transition_kind IN (
      'eligibility_materialize','eligibility_refresh','eligibility_restore','eligibility_remove',
      'admin_promote','admin_reject','merge_retarget','merge_collapse','legacy_backfill'
    )
  ),
  candidate_row_revision bigint NOT NULL CHECK (candidate_row_revision >= 1),
  rule_row_revision bigint NOT NULL CHECK (rule_row_revision >= 1),
  rule_input_hash text NOT NULL CHECK (rule_input_hash ~ '^[0-9a-f]{64}$'),
  candidate_input_hash text NOT NULL CHECK (candidate_input_hash ~ '^[0-9a-f]{64}$'),
  generation_id uuid REFERENCES feature.theme_candidate_generations(generation_id)
    ON DELETE RESTRICT,
  provider_dataset_id bigint,
  source_record_key text,
  source_record_hash text,
  collection_id uuid,
  curation_item_id uuid,
  command_id bigint REFERENCES ops.domain_commands(command_id) ON DELETE RESTRICT,
  actor text NOT NULL CHECK (actor = btrim(actor) AND actor <> ''),
  reason_code text NOT NULL CHECK (reason_code = btrim(reason_code) AND reason_code <> ''),
  causation_ref jsonb NOT NULL DEFAULT '{}'::jsonb
    CHECK (jsonb_typeof(causation_ref) = 'object'),
  invoker_role text NOT NULL,
  candidate_procedure_definer text NOT NULL,
  audit_writer_definer text NOT NULL,
  occurred_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  CONSTRAINT uq_candidate_transition_candidate_revision
    UNIQUE (candidate_id, candidate_row_revision)
);

CREATE INDEX idx_candidate_transitions_candidate_keyset
  ON feature.theme_feature_candidate_transitions (candidate_id, transition_id DESC);

CREATE INDEX idx_candidate_transitions_command
  ON feature.theme_feature_candidate_transitions (command_id)
  WHERE command_id IS NOT NULL;
"""


_GUARD_FUNCTIONS_SQL = r"""
CREATE FUNCTION feature.reject_tvn40_append_only_mutation()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $guard$
BEGIN
  RAISE EXCEPTION '% is append-only', TG_TABLE_SCHEMA || '.' || TG_TABLE_NAME
    USING ERRCODE = '42501';
END
$guard$;

CREATE FUNCTION feature.reject_tvn40_truncate()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $guard$
BEGIN
  RAISE EXCEPTION '% cannot be truncated', TG_TABLE_SCHEMA || '.' || TG_TABLE_NAME
    USING ERRCODE = '42501';
END
$guard$;

CREATE FUNCTION feature.validate_theme_candidate_merge_target()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, feature
AS $guard$
BEGIN
  IF NEW.disposition = 'merged' THEN
    IF NEW.merged_into_candidate_id = NEW.candidate_id OR NOT EXISTS (
      SELECT 1
      FROM feature.theme_feature_candidates AS winner
      WHERE winner.candidate_id = NEW.merged_into_candidate_id
        AND winner.rule_id = NEW.rule_id
        AND winner.source_entity_key = NEW.source_entity_key
        AND winner.disposition = 'active'
        AND winner.merged_into_candidate_id IS NULL
      FOR SHARE
    ) THEN
      RAISE EXCEPTION 'merged candidate requires an active same-identity winner'
        USING ERRCODE = '23514', CONSTRAINT = 'ck_theme_feature_candidate_merge_target';
    END IF;
  END IF;
  RETURN NEW;
END
$guard$;
"""


_TRIGGERS_SQL = r"""
CREATE TRIGGER trg_curation_rule_reconcile_operations_immutable
BEFORE UPDATE OR DELETE ON ops.curation_rule_reconcile_operations
FOR EACH ROW EXECUTE FUNCTION feature.reject_tvn40_append_only_mutation();
CREATE TRIGGER trg_curation_rule_reconcile_operations_no_truncate
BEFORE TRUNCATE ON ops.curation_rule_reconcile_operations
FOR EACH STATEMENT EXECUTE FUNCTION feature.reject_tvn40_truncate();

CREATE TRIGGER trg_curation_rule_reconcile_scope_members_immutable
BEFORE UPDATE OR DELETE ON ops.curation_rule_reconcile_scope_members
FOR EACH ROW EXECUTE FUNCTION feature.reject_tvn40_append_only_mutation();
CREATE TRIGGER trg_curation_rule_reconcile_scope_members_no_truncate
BEFORE TRUNCATE ON ops.curation_rule_reconcile_scope_members
FOR EACH STATEMENT EXECUTE FUNCTION feature.reject_tvn40_truncate();

CREATE TRIGGER trg_curation_cutover_identity_mappings_immutable
BEFORE UPDATE OR DELETE ON ops.curation_cutover_identity_mappings
FOR EACH ROW EXECUTE FUNCTION feature.reject_tvn40_append_only_mutation();
CREATE TRIGGER trg_curation_cutover_identity_mappings_no_truncate
BEFORE TRUNCATE ON ops.curation_cutover_identity_mappings
FOR EACH STATEMENT EXECUTE FUNCTION feature.reject_tvn40_truncate();

CREATE TRIGGER trg_theme_candidate_generations_immutable
BEFORE UPDATE OR DELETE ON feature.theme_candidate_generations
FOR EACH ROW EXECUTE FUNCTION feature.reject_tvn40_append_only_mutation();
CREATE TRIGGER trg_theme_candidate_generations_no_truncate
BEFORE TRUNCATE ON feature.theme_candidate_generations
FOR EACH STATEMENT EXECUTE FUNCTION feature.reject_tvn40_truncate();

CREATE TRIGGER trg_theme_candidate_generation_observations_immutable
BEFORE UPDATE OR DELETE ON feature.theme_candidate_generation_observations
FOR EACH ROW EXECUTE FUNCTION feature.reject_tvn40_append_only_mutation();
CREATE TRIGGER trg_theme_candidate_generation_observations_no_truncate
BEFORE TRUNCATE ON feature.theme_candidate_generation_observations
FOR EACH STATEMENT EXECUTE FUNCTION feature.reject_tvn40_truncate();

CREATE TRIGGER trg_theme_feature_candidate_transitions_immutable
BEFORE UPDATE OR DELETE ON feature.theme_feature_candidate_transitions
FOR EACH ROW EXECUTE FUNCTION feature.reject_tvn40_append_only_mutation();
CREATE TRIGGER trg_theme_feature_candidate_transitions_no_truncate
BEFORE TRUNCATE ON feature.theme_feature_candidate_transitions
FOR EACH STATEMENT EXECUTE FUNCTION feature.reject_tvn40_truncate();

CREATE TRIGGER trg_theme_feature_candidates_no_delete
BEFORE DELETE ON feature.theme_feature_candidates
FOR EACH ROW EXECUTE FUNCTION feature.reject_tvn40_append_only_mutation();
CREATE TRIGGER trg_theme_feature_candidates_no_truncate
BEFORE TRUNCATE ON feature.theme_feature_candidates
FOR EACH STATEMENT EXECUTE FUNCTION feature.reject_tvn40_truncate();
CREATE TRIGGER trg_theme_feature_candidates_merge_target
BEFORE INSERT OR UPDATE OF disposition, merged_into_candidate_id, rule_id, source_entity_key
ON feature.theme_feature_candidates
FOR EACH ROW EXECUTE FUNCTION feature.validate_theme_candidate_merge_target();
"""


_OWNERSHIP_AND_ACL_SQL = r"""
GRANT USAGE, CREATE ON SCHEMA feature TO ktm_curation_command_owner;
GRANT USAGE ON SCHEMA ops TO ktm_curation_command_owner;
GRANT USAGE ON SCHEMA provider_sync, x_extension TO ktm_curation_command_owner;
GRANT USAGE, CREATE ON SCHEMA feature TO ktm_curation_audit_writer;

ALTER FUNCTION feature.reject_tvn40_append_only_mutation()
  OWNER TO ktm_curation_audit_writer;
ALTER FUNCTION feature.reject_tvn40_truncate()
  OWNER TO ktm_curation_audit_writer;
ALTER FUNCTION feature.validate_theme_candidate_merge_target()
  OWNER TO ktm_curation_audit_writer;

REVOKE ALL ON TABLE
  ops.curation_rule_reconcile_operations,
  ops.curation_rule_reconcile_scope_members,
  ops.curation_cutover_identity_mappings,
  feature.theme_candidate_generations,
  feature.theme_candidate_generation_observations,
  feature.theme_feature_candidates,
  feature.theme_feature_candidate_transitions
FROM PUBLIC, ktm_feature_runtime, ktm_curation_admin_executor, ktm_curation_provider_executor;

GRANT SELECT, INSERT ON TABLE
  ops.curation_rule_reconcile_operations,
  ops.curation_rule_reconcile_scope_members,
  feature.theme_candidate_generations,
  feature.theme_candidate_generation_observations
TO ktm_curation_command_owner;
GRANT SELECT, INSERT, UPDATE ON TABLE feature.theme_feature_candidates
TO ktm_curation_command_owner;
GRANT SELECT ON TABLE feature.theme_feature_candidates
TO ktm_curation_audit_writer;
GRANT SELECT ON TABLE feature.theme_feature_candidate_transitions
TO ktm_curation_command_owner;
GRANT SELECT, INSERT ON TABLE feature.theme_feature_candidate_transitions
TO ktm_curation_audit_writer;

REVOKE ALL ON SEQUENCE feature.theme_feature_candidate_transitions_transition_id_seq
FROM PUBLIC, ktm_feature_runtime, ktm_curation_admin_executor, ktm_curation_provider_executor,
  ktm_curation_command_owner;
GRANT USAGE, SELECT ON SEQUENCE feature.theme_feature_candidate_transitions_transition_id_seq
TO ktm_curation_audit_writer;
REVOKE ALL ON FUNCTION
  feature.reject_tvn40_append_only_mutation(),
  feature.reject_tvn40_truncate(),
  feature.validate_theme_candidate_merge_target()
FROM PUBLIC, ktm_feature_runtime, ktm_curation_admin_executor, ktm_curation_provider_executor,
  ktm_curation_command_owner;
"""


def upgrade() -> None:
    op.execute(_ROLE_ASSERTIONS_SQL)
    _execute_commands(_REVISION_COLUMNS_SQL)
    op.execute(_CURRENT_RULE_INPUT_FUNCTION_SQL)
    op.execute(
        "ALTER FUNCTION feature.current_curation_rule_input(uuid) "
        "OWNER TO ktm_curation_command_owner"
    )
    _execute_commands(_RECEIPT_TABLES_SQL)
    _execute_commands(_CANDIDATE_TABLES_SQL)
    _execute_commands(_GUARD_FUNCTIONS_SQL)
    _execute_commands(_TRIGGERS_SQL)
    _execute_commands(_OWNERSHIP_AND_ACL_SQL)
    op.execute(
        "GRANT SELECT ON TABLE feature.curated_themes, feature.curated_sources, "
        "feature.curated_source_rules TO ktm_curation_command_owner"
    )
    op.execute("SET ROLE ktm_curation_command_owner")
    op.execute(
        "REVOKE ALL ON FUNCTION feature.current_curation_rule_input(uuid) "
        "FROM PUBLIC, ktm_feature_runtime, ktm_feature_api_runtime, "
        "ktm_feature_dagster_runtime, ktm_curation_admin_executor, "
        "ktm_curation_provider_executor"
    )
    op.execute("SET ROLE ktm_feature_schema_owner")


def downgrade() -> None:
    raise RuntimeError("0105 is forward-only; rebuild with the T-VN-40 release head")
