"""T-VN-40B typed retained source catalog and observation commands.

Revision ID: 0111_tvn40_source_catalog
Revises: 0110_tvn40_theme_catalog
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# Frozen PostgreSQL procedure text intentionally exceeds Python line length.
# ruff: noqa: E501

revision: str = "0111_tvn40_source_catalog"
down_revision: str | Sequence[str] | None = "0110_tvn40_theme_catalog"
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


_COMMAND_PROCEDURES_SQL = r"""
CREATE PROCEDURE feature.create_curated_source_command(
  IN p_provider_dataset_id bigint,
  IN p_source_name text,
  IN p_source_url text,
  IN p_source_kind text,
  IN p_license text,
  IN p_update_cycle text,
  IN p_freshness_note text,
  IN p_provider_status text,
  IN p_metadata jsonb,
  IN p_command_id bigint,
  IN p_principal text,
  OUT o_source_id uuid,
  OUT o_source_revision bigint,
  OUT o_observation_revision bigint
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, feature, provider_sync, ops
AS $command$
DECLARE
  v_command ops.domain_commands%ROWTYPE;
BEGIN
  IF current_setting('transaction_isolation') <> 'serializable' THEN
    RAISE EXCEPTION 'source command requires SERIALIZABLE transaction' USING ERRCODE = '25001';
  END IF;
  IF NOT pg_has_role(session_user, 'ktm_curation_admin_executor', 'member')
     OR pg_has_role(session_user, 'ktm_curation_provider_executor', 'member') THEN
    RAISE EXCEPTION 'source command requires the admin executor' USING ERRCODE = '42501';
  END IF;
  IF p_provider_dataset_id IS NULL OR p_provider_dataset_id <= 0
     OR p_principal IS NULL OR p_principal <> btrim(p_principal) OR p_principal = ''
     OR p_source_name IS NULL OR p_source_name <> btrim(p_source_name) OR p_source_name = ''
     OR p_source_kind NOT IN ('openapi','filedata','standard','internal','manual')
     OR p_update_cycle NOT IN ('realtime','daily','weekly','monthly','annual','one_time','unknown')
     OR p_provider_status NOT IN ('implemented','provider_needed','manual_only','deprecated')
     OR jsonb_typeof(p_metadata) <> 'object' THEN
    RAISE EXCEPTION 'source command input is not canonical'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_source_command_input';
  END IF;
  SELECT command.* INTO STRICT v_command
  FROM ops.domain_commands AS command WHERE command.command_id = p_command_id;
  IF v_command.actor <> p_principal OR v_command.operation <> 'admin.curated-source.create' THEN
    RAISE EXCEPTION 'domain command does not match source create'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_source_domain_command';
  END IF;
  PERFORM pg_advisory_xact_lock(hashtextextended('curation-catalog-write', 0));
  INSERT INTO feature.curated_sources (
    provider_dataset_id, source_name, source_url, source_kind, license,
    update_cycle, freshness_note, provider_status, metadata,
    row_revision, observation_revision, updated_at
  ) VALUES (
    p_provider_dataset_id, p_source_name, p_source_url, p_source_kind, p_license,
    p_update_cycle, p_freshness_note, p_provider_status, p_metadata,
    1, 1, clock_timestamp()
  ) RETURNING source_id, row_revision, observation_revision
    INTO STRICT o_source_id, o_source_revision, o_observation_revision;
  PERFORM feature.claim_curation_catalog_command_effect(
    p_command_id, v_command.operation, 'source', o_source_id
  );
END
$command$;

CREATE PROCEDURE feature.patch_curated_source_command(
  IN p_source_id uuid,
  IN p_expected_source_revision bigint,
  IN p_source_name text,
  IN p_source_url text,
  IN p_source_kind text,
  IN p_license text,
  IN p_update_cycle text,
  IN p_freshness_note text,
  IN p_provider_status text,
  IN p_metadata jsonb,
  IN p_command_id bigint,
  IN p_principal text,
  OUT o_source_id uuid,
  OUT o_source_revision bigint,
  OUT o_observation_revision bigint
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, feature, ops
AS $command$
DECLARE
  v_command ops.domain_commands%ROWTYPE;
  v_source feature.curated_sources%ROWTYPE;
BEGIN
  IF current_setting('transaction_isolation') <> 'serializable' THEN
    RAISE EXCEPTION 'source command requires SERIALIZABLE transaction' USING ERRCODE = '25001';
  END IF;
  IF NOT pg_has_role(session_user, 'ktm_curation_admin_executor', 'member')
     OR pg_has_role(session_user, 'ktm_curation_provider_executor', 'member') THEN
    RAISE EXCEPTION 'source command requires the admin executor' USING ERRCODE = '42501';
  END IF;
  IF p_principal IS NULL OR p_principal <> btrim(p_principal) OR p_principal = ''
     OR p_source_name IS NULL OR p_source_name <> btrim(p_source_name) OR p_source_name = ''
     OR p_source_kind NOT IN ('openapi','filedata','standard','internal','manual')
     OR p_update_cycle NOT IN ('realtime','daily','weekly','monthly','annual','one_time','unknown')
     OR p_provider_status NOT IN ('implemented','provider_needed','manual_only','deprecated')
     OR jsonb_typeof(p_metadata) <> 'object' THEN
    RAISE EXCEPTION 'source command input is not canonical'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_source_command_input';
  END IF;
  SELECT command.* INTO STRICT v_command
  FROM ops.domain_commands AS command WHERE command.command_id = p_command_id;
  IF v_command.actor <> p_principal OR v_command.operation <> 'admin.curated-source.patch' THEN
    RAISE EXCEPTION 'domain command does not match source patch'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_source_domain_command';
  END IF;
  PERFORM pg_advisory_xact_lock(hashtextextended('curation-catalog-write', 0));
  SELECT source.* INTO STRICT v_source FROM feature.curated_sources AS source
  WHERE source.source_id = p_source_id FOR UPDATE;
  IF v_source.row_revision <> p_expected_source_revision THEN
    RAISE EXCEPTION 'source revision mismatch'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_expected_revision';
  END IF;
  IF v_source.archived_at IS NOT NULL THEN
    RAISE EXCEPTION 'archived source cannot be patched'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_source_active';
  END IF;
  PERFORM feature.claim_curation_catalog_command_effect(
    p_command_id, v_command.operation, 'source', v_source.source_id
  );
  IF v_source.source_name = p_source_name
     AND v_source.source_url IS NOT DISTINCT FROM p_source_url
     AND v_source.source_kind = p_source_kind
     AND v_source.license IS NOT DISTINCT FROM p_license
     AND v_source.update_cycle = p_update_cycle
     AND v_source.freshness_note IS NOT DISTINCT FROM p_freshness_note
     AND v_source.provider_status = p_provider_status
     AND v_source.metadata = p_metadata THEN
    o_source_id := v_source.source_id;
    o_source_revision := v_source.row_revision;
    o_observation_revision := v_source.observation_revision;
    RETURN;
  END IF;
  UPDATE feature.curated_sources AS source
  SET source_name = p_source_name, source_url = p_source_url,
      source_kind = p_source_kind, license = p_license,
      update_cycle = p_update_cycle, freshness_note = p_freshness_note,
      provider_status = p_provider_status, metadata = p_metadata,
      row_revision = source.row_revision + 1, updated_at = clock_timestamp()
  WHERE source.source_id = p_source_id
  RETURNING source.source_id, source.row_revision, source.observation_revision
    INTO STRICT o_source_id, o_source_revision, o_observation_revision;
END
$command$;

CREATE PROCEDURE feature.archive_curated_source_command(
  IN p_source_id uuid,
  IN p_expected_source_revision bigint,
  IN p_command_id bigint,
  IN p_reason_code text,
  IN p_principal text,
  OUT o_source_id uuid,
  OUT o_source_revision bigint,
  OUT o_observation_revision bigint,
  OUT o_generation_count bigint
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, feature, provider_sync, ops, x_extension
AS $command$
DECLARE
  v_command ops.domain_commands%ROWTYPE;
  v_source feature.curated_sources%ROWTYPE;
  v_rule_id uuid;
  v_rule_revision bigint;
  v_feature_id text;
  v_prelock_features text[];
  v_current_features text[];
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
    RAISE EXCEPTION 'source command requires SERIALIZABLE transaction' USING ERRCODE = '25001';
  END IF;
  IF NOT pg_has_role(session_user, 'ktm_curation_admin_executor', 'member')
     OR pg_has_role(session_user, 'ktm_curation_provider_executor', 'member') THEN
    RAISE EXCEPTION 'source command requires the admin executor' USING ERRCODE = '42501';
  END IF;
  IF p_principal IS NULL OR p_principal <> btrim(p_principal) OR p_principal = ''
     OR p_reason_code IS NULL OR p_reason_code <> btrim(p_reason_code) OR p_reason_code = '' THEN
    RAISE EXCEPTION 'source archive input is not canonical'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_source_archive_input';
  END IF;
  SELECT command.* INTO STRICT v_command
  FROM ops.domain_commands AS command WHERE command.command_id = p_command_id;
  IF v_command.actor <> p_principal OR v_command.operation <> 'admin.curated-source.archive' THEN
    RAISE EXCEPTION 'domain command does not match source archive'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_source_domain_command';
  END IF;
  SELECT COALESCE(array_agg(scope.feature_id ORDER BY scope.feature_id), ARRAY[]::text[])
  INTO STRICT v_prelock_features
  FROM (
    SELECT candidate.feature_id FROM feature.curated_source_rules AS rule
    JOIN feature.theme_feature_candidates AS candidate ON candidate.rule_id = rule.rule_id
    WHERE rule.source_id = p_source_id AND rule.archived_at IS NULL AND candidate.disposition = 'active'
    UNION
    SELECT link.feature_id FROM feature.curated_sources AS source
    JOIN provider_sync.source_entities AS entity ON entity.provider_dataset_id = source.provider_dataset_id
    JOIN provider_sync.source_links AS link ON link.source_entity_key = entity.source_entity_key
    WHERE source.source_id = p_source_id
  ) AS scope;
  FOREACH v_feature_id IN ARRAY v_prelock_features LOOP
    PERFORM pg_advisory_xact_lock(hashtextextended('feature-write:' || v_feature_id, 0));
  END LOOP;
  PERFORM pg_advisory_xact_lock(hashtextextended('curation-catalog-write', 0));
  SELECT source.* INTO STRICT v_source FROM feature.curated_sources AS source
  WHERE source.source_id = p_source_id FOR UPDATE;
  IF v_source.row_revision <> p_expected_source_revision THEN
    RAISE EXCEPTION 'source revision mismatch'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_expected_revision';
  END IF;
  IF v_source.archived_at IS NOT NULL THEN
    RAISE EXCEPTION 'source is already archived'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_source_active';
  END IF;
  PERFORM feature.claim_curation_catalog_command_effect(
    p_command_id, v_command.operation, 'source', v_source.source_id
  );
  PERFORM 1 FROM feature.curated_source_rules AS rule
  WHERE rule.source_id = p_source_id AND rule.archived_at IS NULL
  ORDER BY rule.rule_id FOR SHARE;
  SELECT COALESCE(array_agg(scope.feature_id ORDER BY scope.feature_id), ARRAY[]::text[])
  INTO STRICT v_current_features
  FROM (
    SELECT candidate.feature_id FROM feature.curated_source_rules AS rule
    JOIN feature.theme_feature_candidates AS candidate ON candidate.rule_id = rule.rule_id
    WHERE rule.source_id = p_source_id AND rule.archived_at IS NULL AND candidate.disposition = 'active'
    UNION
    SELECT link.feature_id FROM provider_sync.source_entities AS entity
    JOIN provider_sync.source_links AS link ON link.source_entity_key = entity.source_entity_key
    WHERE entity.provider_dataset_id = v_source.provider_dataset_id
  ) AS scope;
  IF v_current_features <> v_prelock_features THEN
    RAISE EXCEPTION 'source archive scope changed while acquiring the catalog lock' USING ERRCODE = '40001';
  END IF;
  FOR v_rule_id IN SELECT rule.rule_id FROM feature.curated_source_rules AS rule
    WHERE rule.source_id = p_source_id AND rule.archived_at IS NULL ORDER BY rule.rule_id
  LOOP
    v_before_hashes := v_before_hashes || jsonb_build_object(
      v_rule_id::text, encode(x_extension.digest(convert_to(
        feature.current_curation_rule_input(v_rule_id)::text, 'UTF8'
      ), 'sha256'), 'hex')
    );
  END LOOP;
  UPDATE feature.curated_sources AS source
  SET archived_at = clock_timestamp(), row_revision = source.row_revision + 1,
      updated_at = clock_timestamp()
  WHERE source.source_id = p_source_id
  RETURNING source.source_id, source.row_revision, source.observation_revision
    INTO STRICT o_source_id, o_source_revision, o_observation_revision;
  o_generation_count := 0;
  FOR v_rule_id IN SELECT rule.rule_id FROM feature.curated_source_rules AS rule
    WHERE rule.source_id = p_source_id AND rule.archived_at IS NULL ORDER BY rule.rule_id
  LOOP
    SELECT rule.row_revision INTO STRICT v_rule_revision
    FROM feature.curated_source_rules AS rule WHERE rule.rule_id = v_rule_id;
    v_before_hash := v_before_hashes ->> v_rule_id::text;
    v_after_input := feature.current_curation_rule_input(v_rule_id);
    v_after_hash := encode(x_extension.digest(convert_to(v_after_input::text, 'UTF8'), 'sha256'), 'hex');
    v_operation_id := feature.create_curation_rule_reconcile_receipt(
      v_rule_id, 'archive', v_rule_revision, v_rule_revision,
      v_before_hash, v_after_hash, p_command_id, p_principal
    );
    CALL feature.materialize_theme_candidate_generation(
      v_rule_id, 'rule_reconcile', NULL, v_operation_id, p_command_id, NULL,
      jsonb_build_object('schema_version', 1, 'catalog_action', 'source_archive',
        'source_id', p_source_id::text, 'reason_code', p_reason_code),
      v_generation_id, v_observed, v_removed, v_set_hash, v_replayed
    );
    o_generation_count := o_generation_count + 1;
  END LOOP;
END
$command$;

CREATE PROCEDURE feature.refresh_curated_source_observation(
  IN p_provider_dataset_id bigint,
  IN p_import_job_id uuid,
  OUT o_source_id uuid,
  OUT o_source_revision bigint,
  OUT o_observation_revision bigint,
  OUT o_row_count integer
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, feature, provider_sync, ops
AS $command$
DECLARE
  v_source feature.curated_sources%ROWTYPE;
  v_job ops.import_jobs%ROWTYPE;
  v_last_imported timestamptz;
BEGIN
  IF current_setting('transaction_isolation') <> 'serializable' THEN
    RAISE EXCEPTION 'source observation requires SERIALIZABLE transaction' USING ERRCODE = '25001';
  END IF;
  IF NOT pg_has_role(session_user, 'ktm_curation_provider_executor', 'member')
     OR pg_has_role(session_user, 'ktm_curation_admin_executor', 'member') THEN
    RAISE EXCEPTION 'source observation requires the provider executor' USING ERRCODE = '42501';
  END IF;
  SELECT job.* INTO STRICT v_job FROM ops.import_jobs AS job
  WHERE job.job_id = p_import_job_id FOR SHARE;
  IF v_job.kind <> 'provider_feature_load' OR v_job.status <> 'done'
     OR v_job.cancellation_id IS NOT NULL OR v_job.quarantined_at IS NOT NULL
     OR (SELECT count(*) FROM ops.import_job_datasets AS member WHERE member.job_id = p_import_job_id) <> 1
     OR NOT EXISTS (
       SELECT 1 FROM ops.import_job_datasets AS member
       WHERE member.job_id = p_import_job_id
         AND member.provider_dataset_id = p_provider_dataset_id
     ) THEN
    RAISE EXCEPTION 'source observation requires a done exact dataset member'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_source_observation_job';
  END IF;
  PERFORM pg_advisory_xact_lock(hashtextextended('curation-catalog-write', 0));
  SELECT source.* INTO STRICT v_source FROM feature.curated_sources AS source
  WHERE source.provider_dataset_id = p_provider_dataset_id FOR UPDATE;
  IF v_source.archived_at IS NOT NULL THEN
    RAISE EXCEPTION 'archived source cannot receive observations'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_source_active';
  END IF;
  SELECT count(head.source_entity_key)::integer, max(record.imported_at)
  INTO STRICT o_row_count, v_last_imported
  FROM provider_sync.source_entities AS entity
  LEFT JOIN provider_sync.source_entity_heads AS head ON head.source_entity_key = entity.source_entity_key
  LEFT JOIN provider_sync.source_records AS record ON record.source_record_key = head.current_source_record_key
  WHERE entity.provider_dataset_id = p_provider_dataset_id;
  UPDATE feature.curated_sources AS source
  SET last_checked_at = clock_timestamp(), row_count = o_row_count,
      last_source_modified_at = v_last_imported::date,
      next_expected_at = CASE source.update_cycle
        WHEN 'realtime' THEN current_date
        WHEN 'daily' THEN current_date + 1
        WHEN 'weekly' THEN current_date + 7
        WHEN 'monthly' THEN (current_date + interval '1 month')::date
        WHEN 'annual' THEN (current_date + interval '1 year')::date
        ELSE NULL END,
      observation_revision = source.observation_revision + 1,
      updated_at = clock_timestamp()
  WHERE source.source_id = v_source.source_id
  RETURNING source.source_id, source.row_revision, source.observation_revision
    INTO STRICT o_source_id, o_source_revision, o_observation_revision;
END
$command$;
"""


_CREATE_SIGNATURE = (
    "feature.create_curated_source_command(bigint,text,text,text,text,text,text,text,jsonb,bigint,text)"
)
_PATCH_SIGNATURE = (
    "feature.patch_curated_source_command(uuid,bigint,text,text,text,text,text,text,text,jsonb,bigint,text)"
)
_ARCHIVE_SIGNATURE = (
    "feature.archive_curated_source_command(uuid,bigint,bigint,text,text)"
)
_OBSERVATION_SIGNATURE = "feature.refresh_curated_source_observation(bigint,uuid)"


def upgrade() -> None:
    _execute_commands(_COMMAND_PROCEDURES_SQL)
    for signature in (
        _CREATE_SIGNATURE,
        _PATCH_SIGNATURE,
        _ARCHIVE_SIGNATURE,
        _OBSERVATION_SIGNATURE,
    ):
        op.execute(f"ALTER PROCEDURE {signature} OWNER TO ktm_curation_command_owner")
    op.execute(
        "GRANT INSERT (provider_dataset_id, source_name, source_url, source_kind, license, "
        "update_cycle, freshness_note, provider_status, metadata, row_revision, "
        "observation_revision, updated_at) ON TABLE feature.curated_sources "
        "TO ktm_curation_command_owner"
    )
    op.execute(
        "GRANT UPDATE (source_name, source_url, source_kind, license, update_cycle, "
        "freshness_note, provider_status, metadata, row_revision, archived_at, "
        "last_source_modified_at, last_checked_at, next_expected_at, row_count, "
        "observation_revision, updated_at) ON TABLE feature.curated_sources "
        "TO ktm_curation_command_owner"
    )
    op.execute("SET ROLE ktm_curation_command_owner")
    for signature in (_CREATE_SIGNATURE, _PATCH_SIGNATURE, _ARCHIVE_SIGNATURE):
        op.execute(
            f"REVOKE ALL ON PROCEDURE {signature} FROM PUBLIC, ktm_feature_runtime, "
            "ktm_feature_api_runtime, ktm_feature_dagster_runtime, "
            "ktm_curation_provider_executor"
        )
        op.execute(f"GRANT EXECUTE ON PROCEDURE {signature} TO ktm_curation_admin_executor")
    op.execute(
        f"REVOKE ALL ON PROCEDURE {_OBSERVATION_SIGNATURE} FROM PUBLIC, "
        "ktm_feature_runtime, ktm_feature_api_runtime, ktm_feature_dagster_runtime, "
        "ktm_curation_admin_executor"
    )
    op.execute(
        f"GRANT EXECUTE ON PROCEDURE {_OBSERVATION_SIGNATURE} "
        "TO ktm_curation_provider_executor"
    )
    op.execute("SET ROLE ktm_feature_schema_owner")


def downgrade() -> None:
    raise RuntimeError("0111 is forward-only; rebuild with the T-VN-40 release head")
