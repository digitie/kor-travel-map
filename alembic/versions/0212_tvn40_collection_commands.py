"""T-VN-40B canonical curation collection commands.

Revision ID: 0212_tvn40_collection_cmds
Revises: 0211_tvn40_cancel_cmds
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# Frozen PostgreSQL procedure text intentionally exceeds Python line length.
# ruff: noqa: E501

revision: str = "0212_tvn40_collection_cmds"
down_revision: str | Sequence[str] | None = "0211_tvn40_cancel_cmds"
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


_EFFECT_SHAPE_SQL = r"""
ALTER TABLE ops.curation_catalog_command_effects
  DROP CONSTRAINT curation_catalog_command_effects_resource_kind_check;
ALTER TABLE ops.curation_catalog_command_effects
  ADD CONSTRAINT curation_catalog_command_effects_resource_kind_check
  CHECK (resource_kind IN ('theme','source','rule','collection'));
"""


_COMMAND_PROCEDURES_SQL = r"""
CREATE PROCEDURE feature.create_curation_collection_command(
  IN p_collection_key text,
  IN p_theme_id uuid,
  IN p_source_id uuid,
  IN p_title text,
  IN p_edition_key text,
  IN p_description text,
  IN p_status text,
  IN p_visibility text,
  IN p_metadata jsonb,
  IN p_command_id bigint,
  IN p_principal text,
  OUT o_collection_id uuid,
  OUT o_collection_revision bigint
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, feature, ops, x_extension
AS $command$
DECLARE
  v_command ops.domain_commands%ROWTYPE;
BEGIN
  IF current_setting('transaction_isolation') <> 'serializable' THEN
    RAISE EXCEPTION 'collection command requires SERIALIZABLE transaction'
      USING ERRCODE = '25001';
  END IF;
  IF NOT pg_has_role(session_user, 'ktm_curation_admin_executor', 'member')
     OR pg_has_role(session_user, 'ktm_curation_provider_executor', 'member') THEN
    RAISE EXCEPTION 'collection command requires the admin executor'
      USING ERRCODE = '42501';
  END IF;
  IF p_principal IS NULL OR p_principal <> btrim(p_principal) OR p_principal = ''
     OR p_collection_key IS NULL OR p_collection_key <> btrim(p_collection_key)
     OR p_collection_key = ''
     OR p_theme_id IS NULL
     OR p_title IS NULL OR p_title <> btrim(p_title) OR p_title = ''
     OR p_edition_key IS NULL OR p_edition_key <> btrim(p_edition_key)
     OR p_status NOT IN ('draft','published')
     OR p_visibility NOT IN ('admin_only','public')
     OR jsonb_typeof(p_metadata) <> 'object' THEN
    RAISE EXCEPTION 'collection command input is not canonical'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_collection_command_input';
  END IF;
  SELECT command.* INTO STRICT v_command
  FROM ops.domain_commands AS command WHERE command.command_id = p_command_id;
  IF v_command.actor <> p_principal
     OR v_command.operation <> 'admin.curation-collection.create' THEN
    RAISE EXCEPTION 'domain command does not match collection create'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_collection_domain_command';
  END IF;

  PERFORM pg_advisory_xact_lock(hashtextextended('kortravelmap:curation-import', 0));
  PERFORM pg_advisory_xact_lock(hashtextextended('curation-catalog-write', 0));
  PERFORM pg_advisory_xact_lock(hashtextextended('curation-collection:' || p_collection_key, 0));
  PERFORM 1 FROM feature.curated_themes AS theme
  WHERE theme.theme_id = p_theme_id AND theme.archived_at IS NULL FOR SHARE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'active curated theme does not exist'
      USING ERRCODE = '23503', CONSTRAINT = 'fk_tvn40_collection_active_theme';
  END IF;
  IF p_source_id IS NOT NULL THEN
    PERFORM 1 FROM feature.curated_sources AS source
    WHERE source.source_id = p_source_id AND source.archived_at IS NULL FOR SHARE;
    IF NOT FOUND THEN
      RAISE EXCEPTION 'active curated source does not exist'
        USING ERRCODE = '23503', CONSTRAINT = 'fk_tvn40_collection_active_source';
    END IF;
  END IF;

  o_collection_id := x_extension.gen_random_uuid();
  PERFORM feature.claim_curation_catalog_command_effect(
    p_command_id, v_command.operation, 'collection', o_collection_id
  );
  INSERT INTO feature.curation_collections (
    collection_id, collection_key, theme_id, source_id, title, edition_key,
    description, status, visibility, metadata, created_by, updated_by,
    row_revision, updated_at, archived_at
  ) VALUES (
    o_collection_id, p_collection_key, p_theme_id, p_source_id, p_title,
    p_edition_key, p_description, p_status, p_visibility, p_metadata,
    p_principal, p_principal, 1, clock_timestamp(), NULL
  ) RETURNING row_revision INTO STRICT o_collection_revision;
END
$command$;

CREATE PROCEDURE feature.patch_curation_collection_command(
  IN p_collection_id uuid,
  IN p_expected_collection_revision bigint,
  IN p_theme_id uuid,
  IN p_source_id uuid,
  IN p_title text,
  IN p_edition_key text,
  IN p_description text,
  IN p_status text,
  IN p_visibility text,
  IN p_metadata jsonb,
  IN p_command_id bigint,
  IN p_principal text,
  OUT o_collection_id uuid,
  OUT o_collection_revision bigint
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, feature, ops
AS $command$
DECLARE
  v_command ops.domain_commands%ROWTYPE;
  v_collection feature.curation_collections%ROWTYPE;
BEGIN
  IF current_setting('transaction_isolation') <> 'serializable' THEN
    RAISE EXCEPTION 'collection command requires SERIALIZABLE transaction'
      USING ERRCODE = '25001';
  END IF;
  IF NOT pg_has_role(session_user, 'ktm_curation_admin_executor', 'member')
     OR pg_has_role(session_user, 'ktm_curation_provider_executor', 'member') THEN
    RAISE EXCEPTION 'collection command requires the admin executor'
      USING ERRCODE = '42501';
  END IF;
  IF p_principal IS NULL OR p_principal <> btrim(p_principal) OR p_principal = ''
     OR p_collection_id IS NULL OR p_expected_collection_revision IS NULL
     OR p_expected_collection_revision < 1 OR p_theme_id IS NULL
     OR p_title IS NULL OR p_title <> btrim(p_title) OR p_title = ''
     OR p_edition_key IS NULL OR p_edition_key <> btrim(p_edition_key)
     OR p_status NOT IN ('draft','published')
     OR p_visibility NOT IN ('admin_only','public')
     OR jsonb_typeof(p_metadata) <> 'object' THEN
    RAISE EXCEPTION 'collection command input is not canonical'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_collection_command_input';
  END IF;
  SELECT command.* INTO STRICT v_command
  FROM ops.domain_commands AS command WHERE command.command_id = p_command_id;
  IF v_command.actor <> p_principal
     OR v_command.operation <> 'admin.curation-collection.patch' THEN
    RAISE EXCEPTION 'domain command does not match collection patch'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_collection_domain_command';
  END IF;

  PERFORM pg_advisory_xact_lock(hashtextextended('kortravelmap:curation-import', 0));
  PERFORM pg_advisory_xact_lock(hashtextextended('curation-catalog-write', 0));
  SELECT collection.* INTO STRICT v_collection
  FROM feature.curation_collections AS collection
  WHERE collection.collection_id = p_collection_id FOR UPDATE;
  IF v_collection.row_revision <> p_expected_collection_revision THEN
    RAISE EXCEPTION 'collection revision mismatch'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_collection_expected_revision';
  END IF;
  IF v_collection.archived_at IS NOT NULL THEN
    RAISE EXCEPTION 'archived collection cannot be patched'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_collection_active';
  END IF;
  PERFORM 1 FROM feature.curated_themes AS theme
  WHERE theme.theme_id = p_theme_id AND theme.archived_at IS NULL FOR SHARE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'active curated theme does not exist'
      USING ERRCODE = '23503', CONSTRAINT = 'fk_tvn40_collection_active_theme';
  END IF;
  IF p_source_id IS NOT NULL THEN
    PERFORM 1 FROM feature.curated_sources AS source
    WHERE source.source_id = p_source_id AND source.archived_at IS NULL FOR SHARE;
    IF NOT FOUND THEN
      RAISE EXCEPTION 'active curated source does not exist'
        USING ERRCODE = '23503', CONSTRAINT = 'fk_tvn40_collection_active_source';
    END IF;
  END IF;
  PERFORM feature.claim_curation_catalog_command_effect(
    p_command_id, v_command.operation, 'collection', p_collection_id
  );

  o_collection_id := v_collection.collection_id;
  IF (v_collection.theme_id, v_collection.source_id, v_collection.title,
      v_collection.edition_key, v_collection.description, v_collection.status,
      v_collection.visibility, v_collection.metadata)
     IS NOT DISTINCT FROM
     (p_theme_id, p_source_id, p_title, p_edition_key, p_description, p_status,
      p_visibility, p_metadata) THEN
    o_collection_revision := v_collection.row_revision;
    RETURN;
  END IF;
  UPDATE feature.curation_collections AS collection
  SET theme_id = p_theme_id, source_id = p_source_id, title = p_title,
      edition_key = p_edition_key, description = p_description, status = p_status,
      visibility = p_visibility, metadata = p_metadata, updated_by = p_principal,
      row_revision = collection.row_revision + 1, updated_at = clock_timestamp()
  WHERE collection.collection_id = p_collection_id
  RETURNING collection.collection_id, collection.row_revision
  INTO STRICT o_collection_id, o_collection_revision;
END
$command$;

CREATE PROCEDURE feature.archive_curation_collection_command(
  IN p_collection_id uuid,
  IN p_expected_collection_revision bigint,
  IN p_command_id bigint,
  IN p_principal text,
  OUT o_collection_id uuid,
  OUT o_collection_revision bigint
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, feature, ops
AS $command$
DECLARE
  v_command ops.domain_commands%ROWTYPE;
  v_collection feature.curation_collections%ROWTYPE;
BEGIN
  IF current_setting('transaction_isolation') <> 'serializable' THEN
    RAISE EXCEPTION 'collection command requires SERIALIZABLE transaction'
      USING ERRCODE = '25001';
  END IF;
  IF NOT pg_has_role(session_user, 'ktm_curation_admin_executor', 'member')
     OR pg_has_role(session_user, 'ktm_curation_provider_executor', 'member') THEN
    RAISE EXCEPTION 'collection command requires the admin executor'
      USING ERRCODE = '42501';
  END IF;
  IF p_principal IS NULL OR p_principal <> btrim(p_principal) OR p_principal = ''
     OR p_collection_id IS NULL OR p_expected_collection_revision IS NULL
     OR p_expected_collection_revision < 1 THEN
    RAISE EXCEPTION 'collection archive input is not canonical'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_collection_command_input';
  END IF;
  SELECT command.* INTO STRICT v_command
  FROM ops.domain_commands AS command WHERE command.command_id = p_command_id;
  IF v_command.actor <> p_principal
     OR v_command.operation <> 'admin.curation-collection.archive' THEN
    RAISE EXCEPTION 'domain command does not match collection archive'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_collection_domain_command';
  END IF;

  PERFORM pg_advisory_xact_lock(hashtextextended('kortravelmap:curation-import', 0));
  SELECT collection.* INTO STRICT v_collection
  FROM feature.curation_collections AS collection
  WHERE collection.collection_id = p_collection_id FOR UPDATE;
  IF v_collection.row_revision <> p_expected_collection_revision THEN
    RAISE EXCEPTION 'collection revision mismatch'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_collection_expected_revision';
  END IF;
  PERFORM feature.claim_curation_catalog_command_effect(
    p_command_id, v_command.operation, 'collection', p_collection_id
  );
  o_collection_id := v_collection.collection_id;
  IF v_collection.archived_at IS NOT NULL THEN
    o_collection_revision := v_collection.row_revision;
    RETURN;
  END IF;
  UPDATE feature.curation_collections AS collection
  SET status = 'archived', archived_at = clock_timestamp(),
      updated_by = p_principal, row_revision = collection.row_revision + 1,
      updated_at = clock_timestamp()
  WHERE collection.collection_id = p_collection_id
  RETURNING collection.collection_id, collection.row_revision
  INTO STRICT o_collection_id, o_collection_revision;
END
$command$;
"""


_CREATE_SIGNATURE = (
    "feature.create_curation_collection_command("
    "text,uuid,uuid,text,text,text,text,text,jsonb,bigint,text)"
)
_PATCH_SIGNATURE = (
    "feature.patch_curation_collection_command("
    "uuid,bigint,uuid,uuid,text,text,text,text,text,jsonb,bigint,text)"
)
_ARCHIVE_SIGNATURE = (
    "feature.archive_curation_collection_command(uuid,bigint,bigint,text)"
)


def upgrade() -> None:
    _execute_commands(_EFFECT_SHAPE_SQL)
    _execute_commands(_COMMAND_PROCEDURES_SQL)
    for signature in (_CREATE_SIGNATURE, _PATCH_SIGNATURE, _ARCHIVE_SIGNATURE):
        op.execute(f"ALTER PROCEDURE {signature} OWNER TO ktm_curation_command_owner")
    op.execute(
        "GRANT INSERT (collection_id, collection_key, theme_id, source_id, title, "
        "edition_key, description, status, visibility, metadata, created_by, "
        "updated_by, row_revision, updated_at, archived_at) ON TABLE "
        "feature.curation_collections TO ktm_curation_command_owner"
    )
    op.execute(
        "GRANT UPDATE (theme_id, source_id, title, edition_key, description, status, "
        "visibility, metadata, updated_by, row_revision, updated_at, archived_at) "
        "ON TABLE feature.curation_collections TO ktm_curation_command_owner"
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
    raise RuntimeError("0212_tvn40_collection_cmds is forward-only; rebuild with the T-VN-40 release head")
