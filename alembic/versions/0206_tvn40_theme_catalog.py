"""T-VN-40B typed retained theme catalog commands.

Revision ID: 0206_tvn40_theme_catalog
Revises: 0205_tvn40_rule_catalog_commands
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# Frozen PostgreSQL procedure text intentionally exceeds Python line length.
# ruff: noqa: E501

revision: str = "0206_tvn40_theme_catalog"
down_revision: str | Sequence[str] | None = "0205_tvn40_rule_catalog_commands"
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


_RECONCILE_SHAPE_SQL = r"""
ALTER TABLE ops.curation_rule_reconcile_operations
  DROP CONSTRAINT ck_curation_rule_reconcile_operation_revision_shape;
ALTER TABLE ops.curation_rule_reconcile_operations
  ADD CONSTRAINT ck_curation_rule_reconcile_operation_revision_shape CHECK (
    (operation_kind = 'create'
      AND before_rule_revision IS NULL AND before_rule_input_hash IS NULL
      AND after_rule_revision = 1)
    OR (operation_kind IN ('patch','archive')
      AND before_rule_revision IS NOT NULL AND before_rule_input_hash IS NOT NULL
      AND after_rule_revision >= before_rule_revision
      AND after_rule_input_hash IS DISTINCT FROM before_rule_input_hash)
  );
"""


_COMMAND_PROCEDURES_SQL = r"""
CREATE PROCEDURE feature.create_curated_theme_command(
  IN p_theme_slug text,
  IN p_theme_name text,
  IN p_theme_description text,
  IN p_theme_group text,
  IN p_visibility text,
  IN p_metadata jsonb,
  IN p_command_id bigint,
  IN p_principal text,
  OUT o_theme_id uuid,
  OUT o_theme_revision bigint
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, feature, ops, x_extension
AS $command$
DECLARE
  v_command ops.domain_commands%ROWTYPE;
BEGIN
  IF current_setting('transaction_isolation') <> 'serializable' THEN
    RAISE EXCEPTION 'theme command requires SERIALIZABLE transaction'
      USING ERRCODE = '25001';
  END IF;
  IF NOT pg_has_role(session_user, 'ktm_curation_admin_executor', 'member')
     OR pg_has_role(session_user, 'ktm_curation_provider_executor', 'member') THEN
    RAISE EXCEPTION 'theme command requires the admin executor'
      USING ERRCODE = '42501';
  END IF;
  IF p_principal IS NULL OR p_principal <> btrim(p_principal) OR p_principal = ''
     OR p_theme_slug IS NULL OR p_theme_slug <> btrim(p_theme_slug) OR p_theme_slug = ''
     OR p_theme_name IS NULL OR p_theme_name <> btrim(p_theme_name) OR p_theme_name = ''
     OR p_theme_description IS NULL
     OR p_theme_group IS NULL OR p_theme_group <> btrim(p_theme_group) OR p_theme_group = ''
     OR p_visibility NOT IN ('admin_only','public')
     OR jsonb_typeof(p_metadata) <> 'object' THEN
    RAISE EXCEPTION 'theme command input is not canonical'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_theme_command_input';
  END IF;
  SELECT command.* INTO STRICT v_command
  FROM ops.domain_commands AS command WHERE command.command_id = p_command_id;
  IF v_command.actor <> p_principal
     OR v_command.operation <> 'admin.curated-theme.create' THEN
    RAISE EXCEPTION 'domain command does not match theme create'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_theme_domain_command';
  END IF;
  PERFORM pg_advisory_xact_lock(hashtextextended('curation-catalog-write', 0));
  INSERT INTO feature.curated_themes (
    theme_slug, theme_name, theme_description, theme_group, default_curated,
    visibility, metadata, row_revision, owner_kind, owner_provider_dataset_id,
    updated_at
  ) VALUES (
    p_theme_slug, p_theme_name, p_theme_description, p_theme_group, false,
    p_visibility, p_metadata, 1, 'operator', NULL, clock_timestamp()
  ) RETURNING theme_id, row_revision INTO STRICT o_theme_id, o_theme_revision;
  PERFORM feature.claim_curation_catalog_command_effect(
    p_command_id, v_command.operation, 'theme', o_theme_id
  );
END
$command$;

CREATE PROCEDURE feature.patch_curated_theme_command(
  IN p_theme_id uuid,
  IN p_expected_theme_revision bigint,
  IN p_theme_slug text,
  IN p_theme_name text,
  IN p_theme_description text,
  IN p_theme_group text,
  IN p_visibility text,
  IN p_metadata jsonb,
  IN p_command_id bigint,
  IN p_principal text,
  OUT o_theme_id uuid,
  OUT o_theme_revision bigint,
  OUT o_generation_count bigint
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, feature, provider_sync, ops, x_extension
AS $command$
DECLARE
  v_command ops.domain_commands%ROWTYPE;
  v_theme feature.curated_themes%ROWTYPE;
  v_rule_id uuid;
  v_feature_id text;
  v_prelock_count bigint;
  v_prelock_hash text;
  v_current_count bigint;
  v_current_hash text;
  v_before_hashes jsonb := '{}'::jsonb;
  v_before_hash text;
  v_after_input jsonb;
  v_after_hash text;
  v_operation_id uuid;
  v_generation_id uuid;
  v_observed bigint;
  v_removed bigint;
  v_set_hash text;
  v_replayed boolean;
BEGIN
  IF current_setting('transaction_isolation') <> 'serializable' THEN
    RAISE EXCEPTION 'theme command requires SERIALIZABLE transaction'
      USING ERRCODE = '25001';
  END IF;
  IF NOT pg_has_role(session_user, 'ktm_curation_admin_executor', 'member')
     OR pg_has_role(session_user, 'ktm_curation_provider_executor', 'member') THEN
    RAISE EXCEPTION 'theme command requires the admin executor'
      USING ERRCODE = '42501';
  END IF;
  IF p_principal IS NULL OR p_principal <> btrim(p_principal) OR p_principal = ''
     OR p_theme_slug IS NULL OR p_theme_slug <> btrim(p_theme_slug) OR p_theme_slug = ''
     OR p_theme_name IS NULL OR p_theme_name <> btrim(p_theme_name) OR p_theme_name = ''
     OR p_theme_description IS NULL
     OR p_theme_group IS NULL OR p_theme_group <> btrim(p_theme_group) OR p_theme_group = ''
     OR p_visibility NOT IN ('admin_only','public')
     OR jsonb_typeof(p_metadata) <> 'object' THEN
    RAISE EXCEPTION 'theme command input is not canonical'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_theme_command_input';
  END IF;
  SELECT command.* INTO STRICT v_command
  FROM ops.domain_commands AS command WHERE command.command_id = p_command_id;
  IF v_command.actor <> p_principal
     OR v_command.operation <> 'admin.curated-theme.patch' THEN
    RAISE EXCEPTION 'domain command does not match theme patch'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_theme_domain_command';
  END IF;

  SELECT count(*), encode(x_extension.digest(convert_to(
    COALESCE(jsonb_agg(touched.feature_id ORDER BY touched.feature_id)::text, '[]'),
    'UTF8'), 'sha256'), 'hex')
  INTO STRICT v_prelock_count, v_prelock_hash
  FROM (
    SELECT DISTINCT candidate.feature_id
    FROM feature.curated_source_rules AS rule
    JOIN feature.theme_feature_candidates AS candidate ON candidate.rule_id = rule.rule_id
    WHERE rule.theme_id = p_theme_id AND rule.archived_at IS NULL
      AND candidate.disposition = 'active'
    UNION
    SELECT DISTINCT link.feature_id
    FROM feature.curated_source_rules AS rule
    JOIN feature.curated_sources AS source ON source.source_id = rule.source_id
    JOIN provider_sync.source_entities AS entity
      ON entity.provider_dataset_id = source.provider_dataset_id
    JOIN provider_sync.source_links AS link ON link.source_entity_key = entity.source_entity_key
    WHERE rule.theme_id = p_theme_id AND rule.archived_at IS NULL
  ) AS touched;
  FOR v_feature_id IN
    SELECT touched.feature_id FROM (
      SELECT candidate.feature_id
      FROM feature.curated_source_rules AS rule
      JOIN feature.theme_feature_candidates AS candidate ON candidate.rule_id = rule.rule_id
      WHERE rule.theme_id = p_theme_id AND rule.archived_at IS NULL
        AND candidate.disposition = 'active'
      UNION
      SELECT link.feature_id
      FROM feature.curated_source_rules AS rule
      JOIN feature.curated_sources AS source ON source.source_id = rule.source_id
      JOIN provider_sync.source_entities AS entity
        ON entity.provider_dataset_id = source.provider_dataset_id
      JOIN provider_sync.source_links AS link ON link.source_entity_key = entity.source_entity_key
      WHERE rule.theme_id = p_theme_id AND rule.archived_at IS NULL
    ) AS touched ORDER BY touched.feature_id
  LOOP
    PERFORM pg_advisory_xact_lock(hashtextextended('feature-write:' || v_feature_id, 0));
  END LOOP;
  PERFORM pg_advisory_xact_lock(hashtextextended('curation-catalog-write', 0));
  SELECT theme.* INTO STRICT v_theme
  FROM feature.curated_themes AS theme WHERE theme.theme_id = p_theme_id FOR UPDATE;
  IF v_theme.row_revision <> p_expected_theme_revision THEN
    RAISE EXCEPTION 'theme revision mismatch'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_expected_revision';
  END IF;
  IF v_theme.archived_at IS NOT NULL THEN
    RAISE EXCEPTION 'archived theme cannot be patched'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_theme_active';
  END IF;
  IF v_theme.owner_kind IS DISTINCT FROM 'operator' THEN
    RAISE EXCEPTION 'provider-owned theme cannot be patched by an admin command'
      USING ERRCODE = '42501';
  END IF;
  PERFORM feature.claim_curation_catalog_command_effect(
    p_command_id, v_command.operation, 'theme', v_theme.theme_id
  );
  PERFORM 1 FROM feature.curated_source_rules AS rule
  WHERE rule.theme_id = p_theme_id AND rule.archived_at IS NULL
  ORDER BY rule.rule_id FOR SHARE;
  SELECT count(*), encode(x_extension.digest(convert_to(
    COALESCE(jsonb_agg(touched.feature_id ORDER BY touched.feature_id)::text, '[]'),
    'UTF8'), 'sha256'), 'hex')
  INTO STRICT v_current_count, v_current_hash
  FROM (
    SELECT DISTINCT candidate.feature_id
    FROM feature.curated_source_rules AS rule
    JOIN feature.theme_feature_candidates AS candidate ON candidate.rule_id = rule.rule_id
    WHERE rule.theme_id = p_theme_id AND rule.archived_at IS NULL
      AND candidate.disposition = 'active'
    UNION
    SELECT DISTINCT link.feature_id
    FROM feature.curated_source_rules AS rule
    JOIN feature.curated_sources AS source ON source.source_id = rule.source_id
    JOIN provider_sync.source_entities AS entity
      ON entity.provider_dataset_id = source.provider_dataset_id
    JOIN provider_sync.source_links AS link ON link.source_entity_key = entity.source_entity_key
    WHERE rule.theme_id = p_theme_id AND rule.archived_at IS NULL
  ) AS touched;
  IF v_current_count <> v_prelock_count OR v_current_hash <> v_prelock_hash THEN
    RAISE EXCEPTION 'theme patch scope changed while acquiring the catalog lock'
      USING ERRCODE = '40001';
  END IF;
  IF v_theme.theme_slug = p_theme_slug AND v_theme.theme_name = p_theme_name
     AND v_theme.theme_description = p_theme_description
     AND v_theme.theme_group = p_theme_group AND v_theme.visibility = p_visibility
     AND v_theme.metadata = p_metadata THEN
    o_theme_id := v_theme.theme_id;
    o_theme_revision := v_theme.row_revision;
    o_generation_count := 0;
    RETURN;
  END IF;
  UPDATE feature.curated_themes AS theme
  SET theme_slug = p_theme_slug, theme_name = p_theme_name,
      theme_description = p_theme_description, theme_group = p_theme_group,
      visibility = p_visibility, metadata = p_metadata,
      row_revision = theme.row_revision + 1, updated_at = clock_timestamp()
  WHERE theme.theme_id = p_theme_id
  RETURNING theme.theme_id, theme.row_revision INTO STRICT o_theme_id, o_theme_revision;
  o_generation_count := 0;
END
$command$;

CREATE PROCEDURE feature.archive_curated_theme_command(
  IN p_theme_id uuid,
  IN p_expected_theme_revision bigint,
  IN p_command_id bigint,
  IN p_reason_code text,
  IN p_principal text,
  OUT o_theme_id uuid,
  OUT o_theme_revision bigint,
  OUT o_generation_count bigint
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, feature, provider_sync, ops, x_extension
AS $command$
DECLARE
  v_command ops.domain_commands%ROWTYPE;
  v_theme feature.curated_themes%ROWTYPE;
  v_rule_id uuid;
  v_rule_revision bigint;
  v_feature_id text;
  v_prelock_count bigint;
  v_prelock_hash text;
  v_current_count bigint;
  v_current_hash text;
  v_before_hashes jsonb := '{}'::jsonb;
  v_before_hash text;
  v_after_input jsonb;
  v_after_hash text;
  v_operation_id uuid;
  v_generation_id uuid;
  v_observed bigint;
  v_removed bigint;
  v_set_hash text;
  v_replayed boolean;
BEGIN
  IF current_setting('transaction_isolation') <> 'serializable' THEN
    RAISE EXCEPTION 'theme command requires SERIALIZABLE transaction' USING ERRCODE = '25001';
  END IF;
  IF NOT pg_has_role(session_user, 'ktm_curation_admin_executor', 'member')
     OR pg_has_role(session_user, 'ktm_curation_provider_executor', 'member') THEN
    RAISE EXCEPTION 'theme command requires the admin executor' USING ERRCODE = '42501';
  END IF;
  IF p_principal IS NULL OR p_principal <> btrim(p_principal) OR p_principal = ''
     OR p_reason_code IS NULL OR p_reason_code <> btrim(p_reason_code) OR p_reason_code = '' THEN
    RAISE EXCEPTION 'theme archive input is not canonical'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_theme_archive_input';
  END IF;
  SELECT command.* INTO STRICT v_command
  FROM ops.domain_commands AS command WHERE command.command_id = p_command_id;
  IF v_command.actor <> p_principal
     OR v_command.operation <> 'admin.curated-theme.archive' THEN
    RAISE EXCEPTION 'domain command does not match theme archive'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_theme_domain_command';
  END IF;
  SELECT count(*), encode(x_extension.digest(convert_to(
    COALESCE(jsonb_agg(touched.feature_id ORDER BY touched.feature_id)::text, '[]'),
    'UTF8'), 'sha256'), 'hex')
  INTO STRICT v_prelock_count, v_prelock_hash
  FROM (
    SELECT candidate.feature_id
    FROM feature.curated_source_rules AS rule
    JOIN feature.theme_feature_candidates AS candidate ON candidate.rule_id = rule.rule_id
    WHERE rule.theme_id = p_theme_id AND rule.archived_at IS NULL
      AND candidate.disposition = 'active'
    UNION
    SELECT link.feature_id
    FROM feature.curated_source_rules AS rule
    JOIN feature.curated_sources AS source ON source.source_id = rule.source_id
    JOIN provider_sync.source_entities AS entity
      ON entity.provider_dataset_id = source.provider_dataset_id
    JOIN provider_sync.source_links AS link ON link.source_entity_key = entity.source_entity_key
    WHERE rule.theme_id = p_theme_id AND rule.archived_at IS NULL
  ) AS touched;
  FOR v_feature_id IN
    SELECT touched.feature_id FROM (
      SELECT candidate.feature_id
      FROM feature.curated_source_rules AS rule
      JOIN feature.theme_feature_candidates AS candidate ON candidate.rule_id = rule.rule_id
      WHERE rule.theme_id = p_theme_id AND rule.archived_at IS NULL
        AND candidate.disposition = 'active'
      UNION
      SELECT link.feature_id
      FROM feature.curated_source_rules AS rule
      JOIN feature.curated_sources AS source ON source.source_id = rule.source_id
      JOIN provider_sync.source_entities AS entity
        ON entity.provider_dataset_id = source.provider_dataset_id
      JOIN provider_sync.source_links AS link ON link.source_entity_key = entity.source_entity_key
      WHERE rule.theme_id = p_theme_id AND rule.archived_at IS NULL
    ) AS touched ORDER BY touched.feature_id
  LOOP
    PERFORM pg_advisory_xact_lock(hashtextextended('feature-write:' || v_feature_id, 0));
  END LOOP;
  PERFORM pg_advisory_xact_lock(hashtextextended('curation-catalog-write', 0));
  SELECT theme.* INTO STRICT v_theme
  FROM feature.curated_themes AS theme WHERE theme.theme_id = p_theme_id FOR UPDATE;
  IF v_theme.row_revision <> p_expected_theme_revision THEN
    RAISE EXCEPTION 'theme revision mismatch'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_expected_revision';
  END IF;
  IF v_theme.owner_kind IS DISTINCT FROM 'operator' THEN
    RAISE EXCEPTION 'provider-owned theme cannot be archived by an admin command'
      USING ERRCODE = '42501';
  END IF;
  IF v_theme.archived_at IS NOT NULL THEN
    RAISE EXCEPTION 'theme is already archived'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_theme_active';
  END IF;
  PERFORM feature.claim_curation_catalog_command_effect(
    p_command_id, v_command.operation, 'theme', v_theme.theme_id
  );
  PERFORM 1 FROM feature.curated_source_rules AS rule
  WHERE rule.theme_id = p_theme_id AND rule.archived_at IS NULL
  ORDER BY rule.rule_id FOR SHARE;
  SELECT count(*), encode(x_extension.digest(convert_to(
    COALESCE(jsonb_agg(touched.feature_id ORDER BY touched.feature_id)::text, '[]'),
    'UTF8'), 'sha256'), 'hex')
  INTO STRICT v_current_count, v_current_hash
  FROM (
    SELECT candidate.feature_id
    FROM feature.curated_source_rules AS rule
    JOIN feature.theme_feature_candidates AS candidate ON candidate.rule_id = rule.rule_id
    WHERE rule.theme_id = p_theme_id AND rule.archived_at IS NULL
      AND candidate.disposition = 'active'
    UNION
    SELECT link.feature_id
    FROM feature.curated_source_rules AS rule
    JOIN feature.curated_sources AS source ON source.source_id = rule.source_id
    JOIN provider_sync.source_entities AS entity
      ON entity.provider_dataset_id = source.provider_dataset_id
    JOIN provider_sync.source_links AS link ON link.source_entity_key = entity.source_entity_key
    WHERE rule.theme_id = p_theme_id AND rule.archived_at IS NULL
  ) AS touched;
  IF v_current_count <> v_prelock_count OR v_current_hash <> v_prelock_hash THEN
    RAISE EXCEPTION 'theme archive scope changed while acquiring the catalog lock'
      USING ERRCODE = '40001';
  END IF;
  FOR v_rule_id IN
    SELECT rule.rule_id FROM feature.curated_source_rules AS rule
    WHERE rule.theme_id = p_theme_id AND rule.archived_at IS NULL ORDER BY rule.rule_id
  LOOP
    v_before_hashes := v_before_hashes || jsonb_build_object(
      v_rule_id::text,
      encode(x_extension.digest(convert_to(
        feature.current_curation_rule_input(v_rule_id)::text, 'UTF8'
      ), 'sha256'), 'hex')
    );
  END LOOP;
  UPDATE feature.curated_themes AS theme
  SET archived_at = clock_timestamp(), row_revision = theme.row_revision + 1,
      updated_at = clock_timestamp()
  WHERE theme.theme_id = p_theme_id
  RETURNING theme.theme_id, theme.row_revision INTO STRICT o_theme_id, o_theme_revision;
  o_generation_count := 0;
  FOR v_rule_id IN
    SELECT rule.rule_id FROM feature.curated_source_rules AS rule
    WHERE rule.theme_id = p_theme_id AND rule.archived_at IS NULL ORDER BY rule.rule_id
  LOOP
    SELECT rule.row_revision INTO STRICT v_rule_revision
    FROM feature.curated_source_rules AS rule WHERE rule.rule_id = v_rule_id;
    v_before_hash := v_before_hashes ->> v_rule_id::text;
    v_after_input := feature.current_curation_rule_input(v_rule_id);
    v_after_hash := encode(x_extension.digest(convert_to(v_after_input::text, 'UTF8'), 'sha256'), 'hex');
    v_operation_id := feature.create_curation_rule_reconcile_receipt(
      v_rule_id, 'archive',
      v_rule_revision, v_rule_revision,
      v_before_hash, v_after_hash, p_command_id, p_principal
    );
    CALL feature.materialize_theme_candidate_generation(
      v_rule_id, 'rule_reconcile', NULL, v_operation_id, p_command_id, NULL,
      jsonb_build_object('schema_version', 1, 'catalog_action', 'theme_archive',
        'theme_id', p_theme_id::text, 'reason_code', p_reason_code),
      v_generation_id, v_observed, v_removed, v_set_hash, v_replayed
    );
    o_generation_count := o_generation_count + 1;
  END LOOP;
END
$command$;
"""


_CREATE_SIGNATURE = (
    "feature.create_curated_theme_command(text,text,text,text,text,jsonb,bigint,text)"
)
_PATCH_SIGNATURE = (
    "feature.patch_curated_theme_command(uuid,bigint,text,text,text,text,text,jsonb,bigint,text)"
)
_ARCHIVE_SIGNATURE = (
    "feature.archive_curated_theme_command(uuid,bigint,bigint,text,text)"
)


def upgrade() -> None:
    _execute_commands(_RECONCILE_SHAPE_SQL)
    _execute_commands(_COMMAND_PROCEDURES_SQL)
    for signature in (_CREATE_SIGNATURE, _PATCH_SIGNATURE, _ARCHIVE_SIGNATURE):
        op.execute(f"ALTER PROCEDURE {signature} OWNER TO ktm_curation_command_owner")
    op.execute(
        "GRANT INSERT (theme_slug, theme_name, theme_description, theme_group, "
        "default_curated, visibility, metadata, row_revision, archived_at, owner_kind, "
        "owner_provider_dataset_id, updated_at) ON TABLE feature.curated_themes "
        "TO ktm_curation_command_owner"
    )
    op.execute(
        "GRANT UPDATE (theme_slug, theme_name, theme_description, theme_group, visibility, "
        "metadata, row_revision, archived_at, updated_at) ON TABLE feature.curated_themes "
        "TO ktm_curation_command_owner"
    )
    op.execute("SET ROLE ktm_curation_command_owner")
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
    raise RuntimeError("0206_tvn40_theme_catalog is forward-only; rebuild with the T-VN-40 release head")
