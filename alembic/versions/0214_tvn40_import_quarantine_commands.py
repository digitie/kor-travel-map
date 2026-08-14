"""T-VN-40B import/quarantine collection command fence.

Revision ID: 0214_tvn40_import_quarantine
Revises: 0213_tvn40_item_cmds
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# Frozen PostgreSQL procedure text intentionally exceeds Python line length.
# ruff: noqa: E501

revision: str = "0214_tvn40_import_quarantine"
down_revision: str | Sequence[str] | None = "0213_tvn40_item_cmds"
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


_RECEIPT_SQL = r"""
CREATE TABLE ops.curation_import_collection_effects (
  command_id bigint NOT NULL
    REFERENCES ops.domain_commands(command_id) ON DELETE RESTRICT,
  collection_id uuid NOT NULL
    REFERENCES feature.curation_collections(collection_id) ON DELETE RESTRICT,
  operation text NOT NULL CHECK (operation = 'admin.curation.import'),
  created boolean NOT NULL,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  PRIMARY KEY (command_id, collection_id)
);

CREATE FUNCTION ops.reject_curation_import_collection_effect_mutation()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $guard$
BEGIN
  RAISE EXCEPTION 'curation import collection effects are append-only'
    USING ERRCODE = '42501';
END
$guard$;

CREATE FUNCTION ops.reject_curation_import_collection_effect_truncate()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $guard$
BEGIN
  RAISE EXCEPTION 'curation import collection effects cannot be truncated'
    USING ERRCODE = '42501';
END
$guard$;

CREATE TRIGGER trg_curation_import_collection_effects_immutable
BEFORE UPDATE OR DELETE ON ops.curation_import_collection_effects
FOR EACH ROW EXECUTE FUNCTION ops.reject_curation_import_collection_effect_mutation();
CREATE TRIGGER trg_curation_import_collection_effects_no_truncate
BEFORE TRUNCATE ON ops.curation_import_collection_effects
FOR EACH STATEMENT EXECUTE FUNCTION ops.reject_curation_import_collection_effect_truncate();

ALTER TABLE feature.curation_import_batches
  ADD COLUMN command_id bigint NULL
    REFERENCES ops.domain_commands(command_id) ON DELETE RESTRICT;
ALTER TABLE feature.curation_import_batches
  ADD CONSTRAINT uq_curation_import_batches_command UNIQUE (command_id);
ALTER TABLE feature.curation_import_batches
  ADD CONSTRAINT uq_curation_import_batches_identity_command
  UNIQUE (import_batch_id, command_id);
"""


_COMMAND_SQL = r"""
CREATE PROCEDURE feature.resolve_curation_import_collection_command(
  IN p_collection_key text,
  IN p_theme_id uuid,
  IN p_source_id uuid,
  IN p_title text,
  IN p_edition_key text,
  IN p_command_id bigint,
  IN p_principal text,
  OUT o_collection_id uuid,
  OUT o_collection_revision bigint,
  OUT o_created boolean
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, feature, ops, x_extension
AS $command$
DECLARE
  v_command ops.domain_commands%ROWTYPE;
  v_collection feature.curation_collections%ROWTYPE;
BEGIN
  IF current_setting('transaction_isolation') <> 'serializable' THEN
    RAISE EXCEPTION 'curation import command requires SERIALIZABLE transaction'
      USING ERRCODE = '25001';
  END IF;
  IF NOT pg_has_role(session_user, 'ktm_curation_admin_executor', 'member')
     OR pg_has_role(session_user, 'ktm_curation_provider_executor', 'member') THEN
    RAISE EXCEPTION 'curation import command requires the admin executor'
      USING ERRCODE = '42501';
  END IF;
  IF p_principal IS NULL OR p_principal <> btrim(p_principal) OR p_principal = ''
     OR p_collection_key IS NULL OR p_collection_key <> btrim(p_collection_key)
     OR p_collection_key = '' OR p_theme_id IS NULL
     OR p_title IS NULL OR p_title <> btrim(p_title) OR p_title = ''
     OR p_edition_key IS NULL OR p_edition_key <> btrim(p_edition_key) THEN
    RAISE EXCEPTION 'curation import collection input is not canonical'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_import_collection_input';
  END IF;
  SELECT command.* INTO STRICT v_command
  FROM ops.domain_commands AS command WHERE command.command_id = p_command_id
  FOR UPDATE;
  IF v_command.actor <> p_principal
     OR v_command.operation <> 'admin.curation.import'
     OR EXISTS (
       SELECT 1 FROM ops.domain_command_results AS result
       WHERE result.command_id = p_command_id
     ) THEN
    RAISE EXCEPTION 'domain command does not match active curation import'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_import_domain_command';
  END IF;

  PERFORM pg_advisory_xact_lock(hashtextextended('kortravelmap:curation-import', 0));
  PERFORM pg_advisory_xact_lock(hashtextextended('curation-catalog-write', 0));
  PERFORM pg_advisory_xact_lock(hashtextextended('curation-collection:' || p_collection_key, 0));
  PERFORM 1 FROM feature.curated_themes AS theme
  WHERE theme.theme_id = p_theme_id AND theme.archived_at IS NULL FOR SHARE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'active curated theme does not exist'
      USING ERRCODE = '23503', CONSTRAINT = 'fk_tvn40_import_active_theme';
  END IF;
  IF p_source_id IS NOT NULL THEN
    PERFORM 1 FROM feature.curated_sources AS source
    WHERE source.source_id = p_source_id AND source.archived_at IS NULL FOR SHARE;
    IF NOT FOUND THEN
      RAISE EXCEPTION 'active curated source does not exist'
        USING ERRCODE = '23503', CONSTRAINT = 'fk_tvn40_import_active_source';
    END IF;
  END IF;

  SELECT collection.* INTO v_collection
  FROM feature.curation_collections AS collection
  WHERE collection.collection_key = p_collection_key FOR UPDATE;
  IF FOUND THEN
    IF (v_collection.theme_id, v_collection.source_id, v_collection.title,
        v_collection.edition_key, v_collection.status, v_collection.visibility,
        v_collection.archived_at IS NULL)
       IS DISTINCT FROM
       (p_theme_id, p_source_id, p_title, p_edition_key,
        'published'::text, 'public'::text, true) THEN
      RAISE EXCEPTION 'existing collection differs from immutable import catalog input'
        USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_import_collection_cas';
    END IF;
    o_collection_id := v_collection.collection_id;
    o_collection_revision := v_collection.row_revision;
    o_created := false;
  ELSE
    o_collection_id := x_extension.gen_random_uuid();
    INSERT INTO feature.curation_collections (
      collection_id, collection_key, theme_id, source_id, title, edition_key,
      description, status, visibility, metadata, created_by, updated_by,
      row_revision, updated_at, archived_at
    ) VALUES (
      o_collection_id, p_collection_key, p_theme_id, p_source_id, p_title,
      p_edition_key, NULL, 'published', 'public', '{}'::jsonb,
      p_principal, p_principal, 1, clock_timestamp(), NULL
    ) RETURNING row_revision INTO STRICT o_collection_revision;
    o_created := true;
  END IF;
  INSERT INTO ops.curation_import_collection_effects (
    command_id, collection_id, operation, created
  ) VALUES (p_command_id, o_collection_id, v_command.operation, o_created);
END
$command$;

CREATE PROCEDURE feature.touch_curation_import_collection_command(
  IN p_collection_id uuid,
  IN p_command_id bigint,
  IN p_principal text,
  OUT o_collection_revision bigint
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, feature, ops
AS $command$
DECLARE
  v_effect ops.curation_import_collection_effects%ROWTYPE;
BEGIN
  IF current_setting('transaction_isolation') <> 'serializable' THEN
    RAISE EXCEPTION 'curation import command requires SERIALIZABLE transaction'
      USING ERRCODE = '25001';
  END IF;
  IF NOT pg_has_role(session_user, 'ktm_curation_admin_executor', 'member')
     OR pg_has_role(session_user, 'ktm_curation_provider_executor', 'member') THEN
    RAISE EXCEPTION 'curation import command requires the admin executor'
      USING ERRCODE = '42501';
  END IF;
  PERFORM 1 FROM ops.domain_commands AS command
  WHERE command.command_id = p_command_id
    AND command.actor = p_principal
    AND command.operation = 'admin.curation.import'
    AND NOT EXISTS (
      SELECT 1 FROM ops.domain_command_results AS result
      WHERE result.command_id = command.command_id
    ) FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'domain command does not match active curation import'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_import_domain_command';
  END IF;
  SELECT effect.* INTO STRICT v_effect
  FROM ops.curation_import_collection_effects AS effect
  WHERE effect.command_id = p_command_id
    AND effect.collection_id = p_collection_id;
  IF v_effect.created THEN
    SELECT collection.row_revision INTO STRICT o_collection_revision
    FROM feature.curation_collections AS collection
    WHERE collection.collection_id = p_collection_id;
    RETURN;
  END IF;
  UPDATE feature.curation_collections AS collection
  SET updated_by = p_principal, updated_at = clock_timestamp(),
      row_revision = collection.row_revision + 1
  WHERE collection.collection_id = p_collection_id
  RETURNING collection.row_revision INTO STRICT o_collection_revision;
END
$command$;

CREATE PROCEDURE feature.reclassify_curation_quarantine_command(
  IN p_quarantine_collection_id uuid,
  IN p_expected_quarantine_revision bigint,
  IN p_action text,
  IN p_target_collection_id uuid,
  IN p_expected_target_revision bigint,
  IN p_item_ids uuid[],
  IN p_collection_key text,
  IN p_title text,
  IN p_command_id bigint,
  IN p_principal text,
  OUT o_moved_item_ids uuid[],
  OUT o_quarantine_deleted boolean,
  OUT o_collection_id uuid,
  OUT o_collection_key text,
  OUT o_collection_revision bigint,
  OUT o_conflicts jsonb
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, feature, ops
AS $command$
DECLARE
  v_command ops.domain_commands%ROWTYPE;
  v_quarantine_hint feature.curation_collections%ROWTYPE;
  v_quarantine feature.curation_collections%ROWTYPE;
  v_target feature.curation_collections%ROWTYPE;
  v_target_id uuid;
  v_locked_item_ids uuid[];
BEGIN
  IF current_setting('transaction_isolation') <> 'serializable' THEN
    RAISE EXCEPTION 'quarantine command requires SERIALIZABLE transaction'
      USING ERRCODE = '25001';
  END IF;
  IF NOT pg_has_role(session_user, 'ktm_curation_admin_executor', 'member')
     OR pg_has_role(session_user, 'ktm_curation_provider_executor', 'member') THEN
    RAISE EXCEPTION 'quarantine command requires the admin executor'
      USING ERRCODE = '42501';
  END IF;
  IF p_principal IS NULL OR p_principal <> btrim(p_principal) OR p_principal = ''
     OR p_quarantine_collection_id IS NULL
     OR p_expected_quarantine_revision IS NULL OR p_expected_quarantine_revision < 1
     OR p_action NOT IN ('move','confirm_standalone')
     OR (p_action = 'move' AND (
       p_collection_key IS NOT NULL OR p_title IS NOT NULL
       OR p_expected_target_revision IS NULL OR p_expected_target_revision < 1
     ))
     OR (p_action = 'confirm_standalone' AND (
       p_target_collection_id IS NOT NULL OR p_expected_target_revision IS NOT NULL
       OR p_item_ids IS NOT NULL OR p_collection_key IS NULL
       OR p_collection_key <> btrim(p_collection_key) OR p_collection_key = ''
       OR p_title IS NULL OR p_title <> btrim(p_title) OR p_title = ''
     )) THEN
    RAISE EXCEPTION 'quarantine command input is not canonical'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_quarantine_command_input';
  END IF;
  SELECT command.* INTO STRICT v_command
  FROM ops.domain_commands AS command WHERE command.command_id = p_command_id;
  IF v_command.actor <> p_principal
     OR v_command.operation <> 'admin.curation-quarantine.reclassify' THEN
    RAISE EXCEPTION 'domain command does not match quarantine reclassify'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_quarantine_domain_command';
  END IF;

  SELECT collection.* INTO STRICT v_quarantine_hint
  FROM feature.curation_collections AS collection
  WHERE collection.collection_id = p_quarantine_collection_id;
  IF v_quarantine_hint.created_by <> 'migration:0065'
     OR v_quarantine_hint.metadata ->> 'migration_quarantine' <> '0065' THEN
    RAISE EXCEPTION 'curation quarantine collection does not exist'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_quarantine_marker';
  END IF;
  IF p_action = 'move' THEN
    v_target_id := COALESCE(
      p_target_collection_id,
      NULLIF(v_quarantine_hint.metadata ->> 'original_collection_id', '')::uuid
    );
    IF v_target_id IS NULL OR v_target_id = p_quarantine_collection_id THEN
      RAISE EXCEPTION 'valid target collection is required'
        USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_quarantine_target';
    END IF;
  END IF;

  PERFORM pg_advisory_xact_lock(hashtextextended('kortravelmap:curation-import', 0));
  PERFORM pg_advisory_xact_lock(hashtextextended('feature-curation-write', 0));
  IF p_action = 'confirm_standalone' THEN
    PERFORM pg_advisory_xact_lock(hashtextextended('curation-collection:' || p_collection_key, 0));
  END IF;
  PERFORM collection.collection_id
  FROM feature.curation_collections AS collection
  WHERE collection.collection_id = ANY(
    CASE WHEN v_target_id IS NULL
      THEN ARRAY[p_quarantine_collection_id]
      ELSE ARRAY[p_quarantine_collection_id, v_target_id]
    END
  )
  ORDER BY collection.collection_id FOR UPDATE;
  SELECT collection.* INTO STRICT v_quarantine
  FROM feature.curation_collections AS collection
  WHERE collection.collection_id = p_quarantine_collection_id;
  IF v_quarantine.row_revision <> p_expected_quarantine_revision
     OR v_quarantine.created_by <> 'migration:0065'
     OR v_quarantine.metadata ->> 'migration_quarantine' <> '0065' THEN
    RAISE EXCEPTION 'quarantine collection revision or marker changed'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_quarantine_expected_revision';
  END IF;
  PERFORM feature.claim_curation_catalog_command_effect(
    p_command_id, v_command.operation, 'collection', p_quarantine_collection_id
  );

  IF p_action = 'confirm_standalone' THEN
    UPDATE feature.curation_collections AS collection
    SET collection_key = p_collection_key, title = p_title,
        metadata = collection.metadata - 'migration_quarantine' - 'original_collection_id',
        updated_by = p_principal, updated_at = clock_timestamp(),
        row_revision = collection.row_revision + 1
    WHERE collection.collection_id = p_quarantine_collection_id
    RETURNING collection.collection_id, collection.collection_key,
              collection.row_revision
    INTO STRICT o_collection_id, o_collection_key, o_collection_revision;
    o_moved_item_ids := NULL;
    o_quarantine_deleted := NULL;
    o_conflicts := '[]'::jsonb;
    RETURN;
  END IF;

  SELECT collection.* INTO STRICT v_target
  FROM feature.curation_collections AS collection
  WHERE collection.collection_id = v_target_id;
  IF v_target.row_revision <> p_expected_target_revision
     OR v_target.archived_at IS NOT NULL OR v_target.status = 'archived'
     OR (v_target.created_by = 'migration:0065'
         AND v_target.metadata ->> 'migration_quarantine' = '0065') THEN
    RAISE EXCEPTION 'target collection revision or state changed'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_quarantine_target_revision';
  END IF;
  PERFORM item.curation_item_id
  FROM feature.curation_items AS item
  WHERE item.collection_id = p_quarantine_collection_id
  ORDER BY item.curation_item_id FOR UPDATE;
  SELECT COALESCE(array_agg(item.curation_item_id ORDER BY item.curation_item_id), ARRAY[]::uuid[])
  INTO STRICT v_locked_item_ids
  FROM feature.curation_items AS item
  WHERE item.collection_id = p_quarantine_collection_id;
  IF p_item_ids IS NULL THEN
    o_moved_item_ids := v_locked_item_ids;
  ELSE
    IF cardinality(p_item_ids) <> (
      SELECT count(DISTINCT requested)::integer FROM unnest(p_item_ids) AS requested
    ) OR EXISTS (
      SELECT 1 FROM unnest(p_item_ids) AS requested
      WHERE NOT requested = ANY(v_locked_item_ids)
    ) THEN
      RAISE EXCEPTION 'item_ids contain duplicates or non-members'
        USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_quarantine_item_set';
    END IF;
    SELECT COALESCE(array_agg(requested ORDER BY requested), ARRAY[]::uuid[])
    INTO STRICT o_moved_item_ids FROM unnest(p_item_ids) AS requested;
  END IF;

  SELECT COALESCE(jsonb_agg(jsonb_build_object(
    'curation_item_id', moving.curation_item_id,
    'conflict_kind', moving.conflict_kind,
    'conflict_item_id', moving.conflict_item_id
  ) ORDER BY moving.curation_item_id), '[]'::jsonb)
  INTO STRICT o_conflicts
  FROM (
    SELECT item.curation_item_id,
      CASE WHEN component.curation_item_id IS NOT NULL
        THEN 'component_identity_conflict'
        ELSE 'active_source_feature_conflict' END AS conflict_kind,
      COALESCE(component.curation_item_id, active_feature.curation_item_id) AS conflict_item_id
    FROM feature.curation_items AS item
    LEFT JOIN LATERAL (
      SELECT occupant.curation_item_id
      FROM feature.curation_items AS occupant
      WHERE occupant.collection_id = v_target_id
        AND occupant.external_item_id = item.external_item_id
        AND occupant.external_component_id = item.external_component_id
      LIMIT 1
    ) AS component ON true
    LEFT JOIN LATERAL (
      SELECT occupant.curation_item_id
      FROM feature.curation_items AS occupant
      WHERE item.source_present AND item.archived_at IS NULL
        AND occupant.collection_id = v_target_id
        AND occupant.external_item_id = item.external_item_id
        AND occupant.feature_id = item.feature_id
        AND occupant.source_present AND occupant.archived_at IS NULL
      LIMIT 1
    ) AS active_feature ON true
    WHERE item.curation_item_id = ANY(o_moved_item_ids)
      AND (component.curation_item_id IS NOT NULL
           OR active_feature.curation_item_id IS NOT NULL)
  ) AS moving;
  IF jsonb_array_length(o_conflicts) > 0 THEN
    RETURN;
  END IF;
  IF cardinality(o_moved_item_ids) > 0 THEN
    UPDATE feature.curation_items AS item
    SET collection_id = v_target_id, updated_by = p_principal,
        updated_at = clock_timestamp(), row_revision = item.row_revision + 1
    WHERE item.curation_item_id = ANY(o_moved_item_ids);
    UPDATE feature.curation_collections AS collection
    SET updated_by = p_principal, updated_at = clock_timestamp(),
        row_revision = collection.row_revision + 1
    WHERE collection.collection_id = v_target_id
    RETURNING collection.row_revision INTO STRICT o_collection_revision;
  ELSE
    o_collection_revision := v_target.row_revision;
  END IF;
  DELETE FROM feature.curation_collections AS collection
  WHERE collection.collection_id = p_quarantine_collection_id
    AND NOT EXISTS (
      SELECT 1 FROM feature.curation_items AS item
      WHERE item.collection_id = p_quarantine_collection_id
    );
  o_quarantine_deleted := FOUND;
  IF NOT o_quarantine_deleted THEN
    UPDATE feature.curation_collections AS collection
    SET updated_by = p_principal, updated_at = clock_timestamp(),
        row_revision = collection.row_revision + 1
    WHERE collection.collection_id = p_quarantine_collection_id;
  END IF;
  o_collection_id := v_target_id;
  o_collection_key := v_target.collection_key;
END
$command$;
"""


_RESOLVE_SIGNATURE = (
    "feature.resolve_curation_import_collection_command("
    "text,uuid,uuid,text,text,bigint,text)"
)
_TOUCH_SIGNATURE = "feature.touch_curation_import_collection_command(uuid,bigint,text)"
_QUARANTINE_SIGNATURE = (
    "feature.reclassify_curation_quarantine_command("
    "uuid,bigint,text,uuid,bigint,uuid[],text,text,bigint,text)"
)


def upgrade() -> None:
    _execute_commands(_RECEIPT_SQL)
    _execute_commands(_COMMAND_SQL)
    for signature in (_RESOLVE_SIGNATURE, _TOUCH_SIGNATURE, _QUARANTINE_SIGNATURE):
        op.execute(f"ALTER PROCEDURE {signature} OWNER TO ktm_curation_command_owner")
    op.execute("GRANT USAGE, CREATE ON SCHEMA ops TO ktm_curation_audit_writer")
    op.execute(
        "ALTER FUNCTION ops.reject_curation_import_collection_effect_mutation() "
        "OWNER TO ktm_curation_audit_writer"
    )
    op.execute(
        "ALTER FUNCTION ops.reject_curation_import_collection_effect_truncate() "
        "OWNER TO ktm_curation_audit_writer"
    )
    op.execute(
        "REVOKE ALL ON FUNCTION "
        "ops.reject_curation_import_collection_effect_mutation(), "
        "ops.reject_curation_import_collection_effect_truncate() "
        "FROM PUBLIC, ktm_feature_runtime, ktm_curation_admin_executor, "
        "ktm_curation_provider_executor, ktm_curation_command_owner"
    )
    op.execute(
        "REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON TABLE "
        "feature.curation_collections FROM PUBLIC, ktm_feature_runtime, "
        "ktm_feature_api_runtime, ktm_feature_dagster_runtime, "
        "ktm_curation_admin_executor, ktm_curation_provider_executor"
    )
    op.execute(
        "GRANT SELECT, INSERT ON TABLE ops.curation_import_collection_effects "
        "TO ktm_curation_command_owner"
    )
    op.execute(
        "GRANT DELETE ON TABLE feature.curation_collections "
        "TO ktm_curation_command_owner"
    )
    op.execute(
        "GRANT UPDATE (collection_key) ON TABLE feature.curation_collections "
        "TO ktm_curation_command_owner"
    )
    op.execute("SET ROLE ktm_curation_command_owner")
    for signature in (_RESOLVE_SIGNATURE, _TOUCH_SIGNATURE, _QUARANTINE_SIGNATURE):
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
    raise RuntimeError("0118 is forward-only; rebuild with the T-VN-40 release head")
