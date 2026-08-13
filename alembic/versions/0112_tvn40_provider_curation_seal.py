"""T-VN-40B provider curation snapshot/root receipts.

Revision ID: 0112_tvn40_provider_seal
Revises: 0111_tvn40_source_catalog

Authoritative child completion seals the exact source-head input before the
root becomes terminal.  Root finalization prelocks the complete Feature union
and is the only provider-executable path to observation/generation commands.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# Frozen PostgreSQL procedure text intentionally exceeds Python line length.
# ruff: noqa: E501

revision: str = "0112_tvn40_provider_seal"
down_revision: str | Sequence[str] | None = "0111_tvn40_source_catalog"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _execute_commands(source: str) -> None:
    """Dollar-quoted routine body를 보존하며 asyncpg statement를 분리한다."""

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


_RECEIPTS_SQL = r"""
CREATE FUNCTION feature.current_provider_curation_input_set(p_provider_dataset_id bigint)
RETURNS TABLE (
  source_entity_count bigint,
  input_member_count bigint,
  last_source_modified_at date,
  source_input_set_hash text
)
LANGUAGE sql STABLE
SECURITY DEFINER
SET search_path = pg_catalog, feature, provider_sync, ops, x_extension
AS $input$
  WITH canonical_input AS (
    SELECT entity.source_entity_key, head.current_source_record_key,
           record.raw_payload_hash, record.imported_at,
           link.feature_id, link.source_role, link.match_method, link.confidence
    FROM provider_sync.source_entities AS entity
    LEFT JOIN provider_sync.source_entity_heads AS head
      ON head.source_entity_key = entity.source_entity_key
    LEFT JOIN provider_sync.source_records AS record
      ON record.source_entity_key = head.source_entity_key
     AND record.source_record_key = head.current_source_record_key
    LEFT JOIN provider_sync.source_links AS link
      ON link.source_entity_key = entity.source_entity_key
    WHERE entity.provider_dataset_id = p_provider_dataset_id
  )
  SELECT count(DISTINCT input.source_entity_key)::bigint,
         count(input.source_entity_key)::bigint,
         max(input.imported_at)::date,
         encode(x_extension.digest(convert_to(
           COALESCE(jsonb_agg(jsonb_build_array(
             input.source_entity_key, input.current_source_record_key,
             input.raw_payload_hash, input.feature_id, input.source_role,
             input.match_method, input.confidence
           ) ORDER BY input.source_entity_key, input.feature_id)
           FILTER (WHERE input.source_entity_key IS NOT NULL), '[]'::jsonb)::text,
           'UTF8'), 'sha256'), 'hex')
  FROM canonical_input AS input
$input$;

CREATE TABLE ops.curation_provider_snapshot_receipts (
  source_job_id uuid PRIMARY KEY
    REFERENCES ops.import_jobs(job_id) ON DELETE RESTRICT,
  root_job_id uuid NOT NULL
    REFERENCES ops.import_jobs(job_id) ON DELETE RESTRICT,
  provider_dataset_id bigint NOT NULL
    REFERENCES provider_sync.provider_datasets(provider_dataset_id) ON DELETE RESTRICT,
  sync_scope text NOT NULL,
  operation_key text NOT NULL,
  observed_at timestamptz NOT NULL,
  source_entity_count bigint NOT NULL CHECK (source_entity_count >= 0),
  input_member_count bigint NOT NULL CHECK (input_member_count >= 0),
  last_source_modified_at date,
  source_input_set_hash text NOT NULL CHECK (source_input_set_hash ~ '^[0-9a-f]{64}$'),
  UNIQUE (root_job_id, provider_dataset_id, sync_scope, operation_key)
);

CREATE TABLE ops.curation_provider_root_receipts (
  root_job_id uuid PRIMARY KEY
    REFERENCES ops.import_jobs(job_id) ON DELETE RESTRICT,
  child_receipt_count bigint NOT NULL CHECK (child_receipt_count >= 0),
  child_receipt_set_hash text NOT NULL CHECK (child_receipt_set_hash ~ '^[0-9a-f]{64}$'),
  generation_count bigint NOT NULL CHECK (generation_count >= 0),
  generation_set_hash text NOT NULL CHECK (generation_set_hash ~ '^[0-9a-f]{64}$'),
  completed_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE FUNCTION feature.reject_curation_provider_receipt_mutation()
RETURNS trigger LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, feature, ops
AS $guard$
BEGIN
  RAISE EXCEPTION 'provider curation receipts are append-only'
    USING ERRCODE = '55000', CONSTRAINT = 'ck_tvn40_provider_curation_receipt_immutable';
END
$guard$;

CREATE TRIGGER trg_curation_provider_snapshot_receipts_immutable
BEFORE UPDATE OR DELETE OR TRUNCATE ON ops.curation_provider_snapshot_receipts
FOR EACH STATEMENT EXECUTE FUNCTION feature.reject_curation_provider_receipt_mutation();

CREATE TRIGGER trg_curation_provider_root_receipts_immutable
BEFORE UPDATE OR DELETE OR TRUNCATE ON ops.curation_provider_root_receipts
FOR EACH STATEMENT EXECUTE FUNCTION feature.reject_curation_provider_receipt_mutation();
"""


_SEAL_CHILD_SQL = r"""
CREATE PROCEDURE feature.seal_provider_curation_snapshot_receipt(
  IN p_root_job_id uuid,
  IN p_provider_dataset_id bigint,
  IN p_sync_scope text,
  IN p_operation_key text,
  IN p_expected_input_member_count bigint,
  IN p_expected_input_set_hash text,
  OUT o_source_job_id uuid,
  OUT o_observed_at timestamptz,
  OUT o_source_entity_count bigint,
  OUT o_source_input_set_hash text
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, feature, provider_sync, ops, x_extension
AS $command$
DECLARE
  v_child ops.import_jobs%ROWTYPE;
  v_input_member_count bigint;
  v_last_source_modified_at date;
BEGIN
  IF current_setting('transaction_isolation') <> 'serializable' THEN
    RAISE EXCEPTION 'provider snapshot seal requires SERIALIZABLE transaction'
      USING ERRCODE = '25001';
  END IF;
  IF NOT pg_has_role(session_user, 'ktm_curation_provider_executor', 'member')
     OR pg_has_role(session_user, 'ktm_curation_admin_executor', 'member') THEN
    RAISE EXCEPTION 'provider snapshot seal requires the provider executor'
      USING ERRCODE = '42501';
  END IF;
  SELECT child.* INTO STRICT v_child
  FROM ops.import_jobs AS child
  JOIN ops.import_job_datasets AS member ON member.job_id = child.job_id
  WHERE child.parent_job_id = p_root_job_id
    AND child.kind = 'provider_feature_load'
    AND child.status IN ('queued','running')
    AND child.cancellation_id IS NULL AND child.quarantined_at IS NULL
    AND member.provider_dataset_id = p_provider_dataset_id
    AND member.sync_scope = p_sync_scope
    AND member.operation_key = p_operation_key
  FOR UPDATE OF child;
  IF NOT EXISTS (
    SELECT 1 FROM ops.import_jobs AS root
    WHERE root.job_id = p_root_job_id
      AND root.kind = 'provider_feature_load_run'
      AND root.status = 'running'
      AND root.dagster_run_status IN ('STARTED','CANCELING')
      AND root.dagster_run_id = v_child.dagster_run_id
      AND root.cancellation_id IS NULL AND root.quarantined_at IS NULL
  ) OR (SELECT count(*) FROM ops.import_job_datasets AS member
        WHERE member.job_id = v_child.job_id) <> 1 THEN
    RAISE EXCEPTION 'provider snapshot seal requires one exact running member'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_provider_snapshot_member';
  END IF;

  PERFORM 1 FROM provider_sync.source_entities AS entity
  WHERE entity.provider_dataset_id = p_provider_dataset_id
  ORDER BY entity.source_entity_key FOR SHARE;
  PERFORM 1
  FROM provider_sync.source_records AS record
  JOIN provider_sync.source_entity_heads AS head
    ON head.source_entity_key = record.source_entity_key
   AND head.current_source_record_key = record.source_record_key
  JOIN provider_sync.source_entities AS entity
    ON entity.source_entity_key = head.source_entity_key
  WHERE entity.provider_dataset_id = p_provider_dataset_id
  ORDER BY record.source_entity_key, record.source_record_key
  FOR SHARE OF record;
  PERFORM 1
  FROM provider_sync.source_entity_heads AS head
  JOIN provider_sync.source_entities AS entity
    ON entity.source_entity_key = head.source_entity_key
  WHERE entity.provider_dataset_id = p_provider_dataset_id
  ORDER BY head.source_entity_key FOR SHARE OF head;

  o_source_job_id := v_child.job_id;
  o_observed_at := clock_timestamp();
  SELECT input.source_entity_count, input.input_member_count,
         input.last_source_modified_at, input.source_input_set_hash
  INTO STRICT o_source_entity_count, v_input_member_count,
       v_last_source_modified_at, o_source_input_set_hash
  FROM feature.current_provider_curation_input_set(p_provider_dataset_id) AS input;
  IF p_expected_input_member_count IS NULL
     OR p_expected_input_set_hash !~ '^[0-9a-f]{64}$'
     OR p_expected_input_member_count <> v_input_member_count
     OR p_expected_input_set_hash <> o_source_input_set_hash THEN
    RAISE EXCEPTION 'provider load input changed before child completion'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_provider_snapshot_load_input';
  END IF;

  INSERT INTO ops.curation_provider_snapshot_receipts (
    source_job_id, root_job_id, provider_dataset_id, sync_scope, operation_key,
    observed_at, source_entity_count, input_member_count,
    last_source_modified_at, source_input_set_hash
  )
  SELECT v_child.job_id, p_root_job_id, p_provider_dataset_id, p_sync_scope,
         p_operation_key, o_observed_at, o_source_entity_count,
         v_input_member_count, v_last_source_modified_at,
         o_source_input_set_hash;
END
$command$;
"""


_REFRESH_SOURCE_SQL = r"""
CREATE OR REPLACE PROCEDURE feature.refresh_curated_source_observation(
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
  v_snapshot ops.curation_provider_snapshot_receipts%ROWTYPE;
  v_receipt ops.curation_source_observation_receipts%ROWTYPE;
  v_latest_receipt ops.curation_source_observation_receipts%ROWTYPE;
BEGIN
  IF current_setting('transaction_isolation') <> 'serializable' THEN
    RAISE EXCEPTION 'source observation requires SERIALIZABLE transaction' USING ERRCODE = '25001';
  END IF;
  IF NOT pg_has_role(session_user, 'ktm_curation_provider_executor', 'member')
     OR pg_has_role(session_user, 'ktm_curation_admin_executor', 'member') THEN
    RAISE EXCEPTION 'source observation requires the provider executor' USING ERRCODE = '42501';
  END IF;
  SELECT snapshot.* INTO STRICT v_snapshot
  FROM ops.curation_provider_snapshot_receipts AS snapshot
  WHERE snapshot.source_job_id = p_import_job_id
    AND snapshot.provider_dataset_id = p_provider_dataset_id;
  IF NOT EXISTS (
    SELECT 1 FROM ops.import_jobs AS child
    JOIN ops.import_jobs AS root ON root.job_id = child.parent_job_id
    WHERE child.job_id = p_import_job_id AND child.status = 'done'
      AND root.job_id = v_snapshot.root_job_id AND root.status = 'done'
      AND root.dagster_run_status = 'SUCCESS'
      AND child.cancellation_id IS NULL AND child.quarantined_at IS NULL
      AND root.cancellation_id IS NULL AND root.quarantined_at IS NULL
  ) THEN
    RAISE EXCEPTION 'source observation requires a sealed terminal root member'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_source_observation_job';
  END IF;
  SELECT source.* INTO STRICT v_source FROM feature.curated_sources AS source
  WHERE source.provider_dataset_id = p_provider_dataset_id FOR UPDATE;
  SELECT receipt.* INTO v_receipt
  FROM ops.curation_source_observation_receipts AS receipt
  WHERE receipt.source_id = v_source.source_id AND receipt.import_job_id = p_import_job_id;
  IF FOUND THEN
    o_source_id := v_receipt.source_id;
    o_source_revision := v_receipt.source_revision;
    o_observation_revision := v_receipt.observation_revision;
    o_row_count := v_receipt.row_count;
    RETURN;
  END IF;
  IF v_source.archived_at IS NOT NULL THEN
    RAISE EXCEPTION 'archived source cannot receive new observations'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_source_active';
  END IF;
  SELECT receipt.* INTO v_latest_receipt
  FROM ops.curation_source_observation_receipts AS receipt
  WHERE receipt.source_id = v_source.source_id
  ORDER BY receipt.observed_at DESC, receipt.import_job_id DESC LIMIT 1;
  IF FOUND AND (v_snapshot.observed_at, p_import_job_id)
       <= (v_latest_receipt.observed_at, v_latest_receipt.import_job_id) THEN
    RAISE EXCEPTION 'source observation job is older than the current receipt'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_source_observation_order';
  END IF;
  IF v_snapshot.source_entity_count > 2147483647 THEN
    RAISE EXCEPTION 'source observation row count exceeds the catalog range'
      USING ERRCODE = '22003';
  END IF;
  o_row_count := v_snapshot.source_entity_count::integer;
  UPDATE feature.curated_sources AS source
  SET last_checked_at = v_snapshot.observed_at, row_count = o_row_count,
      last_source_modified_at = v_snapshot.last_source_modified_at,
      next_expected_at = CASE source.update_cycle
        WHEN 'realtime' THEN v_snapshot.observed_at::date
        WHEN 'daily' THEN v_snapshot.observed_at::date + 1
        WHEN 'weekly' THEN v_snapshot.observed_at::date + 7
        WHEN 'monthly' THEN (v_snapshot.observed_at + interval '1 month')::date
        WHEN 'annual' THEN (v_snapshot.observed_at + interval '1 year')::date
        ELSE NULL END,
      observation_revision = source.observation_revision + 1,
      updated_at = clock_timestamp()
  WHERE source.source_id = v_source.source_id
  RETURNING source.source_id, source.row_revision, source.observation_revision
    INTO STRICT o_source_id, o_source_revision, o_observation_revision;
  INSERT INTO ops.curation_source_observation_receipts (
    source_id, import_job_id, observed_at, source_revision,
    observation_revision, row_count, last_source_modified_at, source_input_set_hash
  ) VALUES (
    o_source_id, p_import_job_id, v_snapshot.observed_at, o_source_revision,
    o_observation_revision, o_row_count, v_snapshot.last_source_modified_at,
    v_snapshot.source_input_set_hash
  );
END
$command$;
"""


_FINALIZE_ROOT_SQL = r"""
CREATE PROCEDURE feature.finalize_provider_curation_root(
  IN p_root_job_id uuid,
  OUT o_generation_count bigint,
  OUT o_generation_set_hash text,
  OUT o_replayed boolean,
  OUT o_stale_input boolean
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, feature, provider_sync, ops, x_extension
AS $command$
DECLARE
  v_root ops.import_jobs%ROWTYPE;
  v_seal ops.curation_provider_root_receipts%ROWTYPE;
  v_child record;
  v_rule record;
  v_generation_id uuid;
  v_observed bigint;
  v_removed bigint;
  v_input_hash text;
  v_generation_replayed boolean;
  v_source_id uuid;
  v_source_revision bigint;
  v_observation_revision bigint;
  v_row_count integer;
  v_current_count bigint;
  v_current_member_count bigint;
  v_current_hash text;
  v_child_count bigint;
  v_child_hash text;
BEGIN
  o_stale_input := false;
  IF current_setting('transaction_isolation') <> 'serializable' THEN
    RAISE EXCEPTION 'provider curation root requires SERIALIZABLE transaction'
      USING ERRCODE = '25001';
  END IF;
  IF NOT pg_has_role(session_user, 'ktm_curation_provider_executor', 'member')
     OR pg_has_role(session_user, 'ktm_curation_admin_executor', 'member') THEN
    RAISE EXCEPTION 'provider curation root requires the provider executor'
      USING ERRCODE = '42501';
  END IF;
  SELECT root.* INTO STRICT v_root FROM ops.import_jobs AS root
  WHERE root.job_id = p_root_job_id FOR UPDATE;
  IF v_root.kind <> 'provider_feature_load_run' OR v_root.status <> 'done'
     OR v_root.dagster_run_status <> 'SUCCESS' OR v_root.cancellation_id IS NOT NULL
     OR v_root.quarantined_at IS NOT NULL THEN
    RAISE EXCEPTION 'provider curation root requires a successful terminal root'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_provider_curation_root';
  END IF;

  SELECT count(*)::bigint,
         encode(x_extension.digest(convert_to(COALESCE(jsonb_agg(jsonb_build_array(
           receipt.source_job_id::text, receipt.provider_dataset_id,
           receipt.sync_scope, receipt.operation_key, receipt.input_member_count,
           receipt.source_input_set_hash
         ) ORDER BY receipt.provider_dataset_id, receipt.sync_scope, receipt.operation_key)::text, '[]'),
         'UTF8'), 'sha256'), 'hex')
  INTO STRICT v_child_count, v_child_hash
  FROM ops.curation_provider_snapshot_receipts AS receipt
  WHERE receipt.root_job_id = p_root_job_id;

  SELECT root_receipt.* INTO v_seal FROM ops.curation_provider_root_receipts AS root_receipt
  WHERE root_receipt.root_job_id = p_root_job_id;
  IF FOUND THEN
    SELECT count(*)::bigint,
           encode(x_extension.digest(convert_to(COALESCE(jsonb_agg(jsonb_build_array(
             generation.rule_id::text, generation.generation_id::text,
             generation.generation_input_set_hash
           ) ORDER BY generation.rule_id, generation.source_job_id)::text, '[]'),
           'UTF8'), 'sha256'), 'hex')
    INTO STRICT o_generation_count, o_generation_set_hash
    FROM feature.theme_candidate_generations AS generation
    JOIN ops.curation_provider_snapshot_receipts AS receipt
      ON receipt.source_job_id = generation.source_job_id
    WHERE receipt.root_job_id = p_root_job_id
      AND generation.generation_kind = 'provider_full_snapshot';
    IF v_seal.child_receipt_count <> v_child_count
       OR v_seal.child_receipt_set_hash <> v_child_hash
       OR v_seal.generation_count <> o_generation_count
       OR v_seal.generation_set_hash <> o_generation_set_hash THEN
      RAISE EXCEPTION 'provider curation root replay receipt is inconsistent'
        USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_provider_curation_root_replay';
    END IF;
    o_replayed := true;
    RETURN;
  END IF;

  PERFORM pg_advisory_xact_lock(hashtextextended('feature-write:' || touched.feature_id, 0))
  FROM (
    SELECT link.feature_id
    FROM ops.curation_provider_snapshot_receipts AS receipt
    JOIN provider_sync.source_entities AS entity
      ON entity.provider_dataset_id = receipt.provider_dataset_id
    JOIN provider_sync.source_links AS link ON link.source_entity_key = entity.source_entity_key
    WHERE receipt.root_job_id = p_root_job_id
    UNION
    SELECT candidate.feature_id
    FROM ops.curation_provider_snapshot_receipts AS receipt
    JOIN feature.curated_sources AS source
      ON source.provider_dataset_id = receipt.provider_dataset_id
    JOIN feature.curated_source_rules AS rule ON rule.source_id = source.source_id
    JOIN feature.theme_feature_candidates AS candidate ON candidate.rule_id = rule.rule_id
    WHERE receipt.root_job_id = p_root_job_id AND candidate.disposition = 'active'
  ) AS touched ORDER BY touched.feature_id;
  PERFORM 1
  FROM provider_sync.source_links AS link
  JOIN provider_sync.source_entities AS entity
    ON entity.source_entity_key = link.source_entity_key
  JOIN ops.curation_provider_snapshot_receipts AS receipt
    ON receipt.provider_dataset_id = entity.provider_dataset_id
  WHERE receipt.root_job_id = p_root_job_id
  ORDER BY link.source_entity_key, link.feature_id
  FOR SHARE OF link;
  PERFORM pg_advisory_xact_lock(hashtextextended('curation-catalog-write', 0));

  -- Validate every immutable child seal before the first catalog/candidate DML.
  FOR v_child IN
    SELECT receipt.* FROM ops.curation_provider_snapshot_receipts AS receipt
    WHERE receipt.root_job_id = p_root_job_id
    ORDER BY receipt.provider_dataset_id, receipt.sync_scope, receipt.operation_key
  LOOP
    SELECT input.source_entity_count, input.input_member_count,
           input.source_input_set_hash
    INTO STRICT v_current_count, v_current_member_count, v_current_hash
    FROM feature.current_provider_curation_input_set(
      v_child.provider_dataset_id
    ) AS input;
    IF v_current_count <> v_child.source_entity_count
       OR v_current_member_count <> v_child.input_member_count
       OR v_current_hash <> v_child.source_input_set_hash THEN
      o_generation_count := 0;
      o_generation_set_hash := encode(
        x_extension.digest(convert_to('[]', 'UTF8'), 'sha256'), 'hex'
      );
      o_replayed := false;
      o_stale_input := true;
      RETURN;
    END IF;
  END LOOP;

  FOR v_child IN
    SELECT receipt.* FROM ops.curation_provider_snapshot_receipts AS receipt
    WHERE receipt.root_job_id = p_root_job_id
    ORDER BY receipt.provider_dataset_id, receipt.sync_scope, receipt.operation_key
  LOOP
    IF EXISTS (SELECT 1 FROM feature.curated_sources AS source
               WHERE source.provider_dataset_id = v_child.provider_dataset_id
                 AND source.archived_at IS NULL) THEN
      CALL feature.refresh_curated_source_observation(
        v_child.provider_dataset_id, v_child.source_job_id,
        v_source_id, v_source_revision, v_observation_revision, v_row_count
      );
    END IF;
    FOR v_rule IN
      SELECT rule.rule_id FROM feature.curated_source_rules AS rule
      JOIN feature.curated_sources AS source ON source.source_id = rule.source_id
      JOIN feature.curated_themes AS theme ON theme.theme_id = rule.theme_id
      WHERE source.provider_dataset_id = v_child.provider_dataset_id
        AND source.archived_at IS NULL AND theme.archived_at IS NULL
        AND rule.archived_at IS NULL AND rule.enabled
        AND rule.default_action = 'candidate'
      ORDER BY rule.rule_id
    LOOP
      CALL feature.materialize_theme_candidate_generation(
        v_rule.rule_id, 'provider_full_snapshot', v_child.source_job_id,
        NULL, NULL, NULL,
        jsonb_build_object('schema_version', 1, 'sync_scope', v_child.sync_scope,
                           'operation_key', v_child.operation_key),
        v_generation_id, v_observed, v_removed, v_input_hash, v_generation_replayed
      );
    END LOOP;
  END LOOP;

  SELECT count(*)::bigint,
         encode(x_extension.digest(convert_to(COALESCE(jsonb_agg(jsonb_build_array(
           generation.rule_id::text, generation.generation_id::text,
           generation.generation_input_set_hash
         ) ORDER BY generation.rule_id, generation.source_job_id)::text, '[]'),
         'UTF8'), 'sha256'), 'hex')
  INTO STRICT o_generation_count, o_generation_set_hash
  FROM feature.theme_candidate_generations AS generation
  JOIN ops.curation_provider_snapshot_receipts AS receipt
    ON receipt.source_job_id = generation.source_job_id
  WHERE receipt.root_job_id = p_root_job_id
    AND generation.generation_kind = 'provider_full_snapshot';
  INSERT INTO ops.curation_provider_root_receipts (
    root_job_id, child_receipt_count, child_receipt_set_hash,
    generation_count, generation_set_hash
  ) VALUES (p_root_job_id, v_child_count, v_child_hash,
            o_generation_count, o_generation_set_hash);
  o_replayed := false;
END
$command$;
"""


_SEAL_SIGNATURE = (
    "feature.seal_provider_curation_snapshot_receipt(uuid,bigint,text,text,bigint,text)"
)
_ROOT_SIGNATURE = "feature.finalize_provider_curation_root(uuid)"
_OLD_FINALIZE_SIGNATURE = "feature.finalize_provider_curation_receipts(bigint,uuid,text,text)"
_MATERIALIZE_SIGNATURE = "feature.materialize_theme_candidate_generation(uuid,text,uuid,uuid,bigint,text,jsonb)"
_OBSERVATION_SIGNATURE = "feature.refresh_curated_source_observation(bigint,uuid)"


def upgrade() -> None:
    _execute_commands(_RECEIPTS_SQL)
    op.execute(_SEAL_CHILD_SQL)
    op.execute("SET ROLE ktm_curation_command_owner")
    op.execute(_REFRESH_SOURCE_SQL)
    op.execute("SET ROLE ktm_feature_schema_owner")
    op.execute(_FINALIZE_ROOT_SQL)
    op.execute(
        "REVOKE ALL ON FUNCTION feature.current_provider_curation_input_set(bigint) "
        "FROM PUBLIC"
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION feature.current_provider_curation_input_set(bigint) "
        "TO ktm_feature_runtime, ktm_curation_command_owner"
    )
    op.execute(
        "ALTER FUNCTION feature.reject_curation_provider_receipt_mutation() "
        "OWNER TO ktm_curation_audit_writer"
    )
    for signature in (_SEAL_SIGNATURE, _ROOT_SIGNATURE):
        op.execute(f"ALTER PROCEDURE {signature} OWNER TO ktm_curation_command_owner")
    op.execute(
        "GRANT INSERT, SELECT ON TABLE ops.curation_provider_snapshot_receipts, "
        "ops.curation_provider_root_receipts TO ktm_curation_command_owner"
    )
    op.execute(
        "REVOKE ALL ON TABLE ops.curation_provider_snapshot_receipts, "
        "ops.curation_provider_root_receipts FROM PUBLIC, ktm_feature_runtime, "
        "ktm_feature_api_runtime, ktm_feature_dagster_runtime, "
        "ktm_curation_admin_executor, ktm_curation_provider_executor"
    )
    op.execute("SET ROLE ktm_curation_command_owner")
    for signature in (_SEAL_SIGNATURE, _ROOT_SIGNATURE):
        op.execute(
            f"REVOKE ALL ON PROCEDURE {signature} FROM PUBLIC, ktm_feature_runtime, "
            "ktm_feature_api_runtime, ktm_feature_dagster_runtime, ktm_curation_admin_executor"
        )
        op.execute(f"GRANT EXECUTE ON PROCEDURE {signature} TO ktm_curation_provider_executor")
    for signature in (_OLD_FINALIZE_SIGNATURE, _OBSERVATION_SIGNATURE):
        op.execute(
            f"REVOKE ALL ON PROCEDURE {signature} FROM PUBLIC, ktm_feature_runtime, "
            "ktm_feature_api_runtime, ktm_feature_dagster_runtime, "
            "ktm_curation_admin_executor, ktm_curation_provider_executor"
        )
    op.execute(
        f"REVOKE ALL ON PROCEDURE {_MATERIALIZE_SIGNATURE} FROM PUBLIC, "
        "ktm_feature_runtime, ktm_feature_api_runtime, ktm_feature_dagster_runtime, "
        "ktm_curation_provider_executor"
    )
    op.execute(
        f"GRANT EXECUTE ON PROCEDURE {_MATERIALIZE_SIGNATURE} "
        "TO ktm_curation_admin_executor"
    )
    op.execute("SET ROLE ktm_feature_schema_owner")


def downgrade() -> None:
    raise RuntimeError("0112 is forward-only; rebuild with the T-VN-40 release head")
