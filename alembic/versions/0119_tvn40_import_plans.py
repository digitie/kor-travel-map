"""T-VN-40B immutable curation import preview/commit plans.

Revision ID: 0119_tvn40_import_plans
Revises: 0118_tvn40_import_quarantine
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# Frozen PostgreSQL procedure text intentionally exceeds Python line length.
# ruff: noqa: E501

revision: str = "0119_tvn40_import_plans"
down_revision: str | Sequence[str] | None = "0118_tvn40_import_quarantine"
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


_DDL = r"""
CREATE TABLE feature.curation_import_plans (
  import_plan_id uuid PRIMARY KEY,
  preview_command_id bigint NOT NULL UNIQUE
    REFERENCES ops.domain_commands(command_id) ON DELETE RESTRICT,
  actor text NOT NULL CHECK (actor = btrim(actor) AND actor <> ''),
  content_sha256 text NOT NULL CHECK (content_sha256 ~ '^[0-9a-f]{64}$'),
  provenance_sha256 text NULL CHECK (
    provenance_sha256 IS NULL OR provenance_sha256 ~ '^[0-9a-f]{64}$'
  ),
  plan_sha256 text NOT NULL UNIQUE CHECK (plan_sha256 ~ '^[0-9a-f]{64}$'),
  summary jsonb NOT NULL CHECK (jsonb_typeof(summary) = 'object'),
  row_count integer NOT NULL CHECK (row_count >= 0),
  revision_count integer NOT NULL CHECK (revision_count >= 0),
  expires_at timestamptz NOT NULL,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  CHECK (expires_at > created_at)
);

CREATE TABLE feature.curation_import_plan_rows (
  import_plan_id uuid NOT NULL
    REFERENCES feature.curation_import_plans(import_plan_id) ON DELETE RESTRICT,
  row_number integer NOT NULL CHECK (row_number >= 2),
  normalized_payload jsonb NULL CHECK (
    normalized_payload IS NULL OR jsonb_typeof(normalized_payload) = 'object'
  ),
  response_payload jsonb NOT NULL CHECK (jsonb_typeof(response_payload) = 'object'),
  PRIMARY KEY (import_plan_id, row_number)
);

CREATE TABLE feature.curation_import_plan_revisions (
  import_plan_id uuid NOT NULL
    REFERENCES feature.curation_import_plans(import_plan_id) ON DELETE RESTRICT,
  resource_kind text NOT NULL CHECK (
    resource_kind IN ('theme','source','collection','item','feature')
  ),
  resource_key text NOT NULL CHECK (resource_key <> ''),
  expected_revision bigint NULL CHECK (expected_revision IS NULL OR expected_revision >= 1),
  PRIMARY KEY (import_plan_id, resource_kind, resource_key)
);

CREATE TABLE ops.curation_import_plan_claims (
  import_plan_id uuid PRIMARY KEY
    REFERENCES feature.curation_import_plans(import_plan_id) ON DELETE RESTRICT,
  command_id bigint NOT NULL UNIQUE
    REFERENCES ops.domain_commands(command_id) ON DELETE RESTRICT,
  plan_sha256 text NOT NULL CHECK (plan_sha256 ~ '^[0-9a-f]{64}$'),
  claimed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  UNIQUE (import_plan_id, command_id)
);

CREATE TABLE ops.curation_import_plan_commits (
  import_plan_id uuid PRIMARY KEY
    REFERENCES feature.curation_import_plans(import_plan_id) ON DELETE RESTRICT,
  command_id bigint NOT NULL UNIQUE
    REFERENCES ops.domain_commands(command_id) ON DELETE RESTRICT,
  import_batch_id uuid NOT NULL UNIQUE
    REFERENCES feature.curation_import_batches(import_batch_id) ON DELETE RESTRICT,
  result_payload jsonb NOT NULL CHECK (jsonb_typeof(result_payload) = 'object'),
  committed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  FOREIGN KEY (import_plan_id, command_id)
    REFERENCES ops.curation_import_plan_claims(import_plan_id, command_id)
    ON DELETE RESTRICT,
  FOREIGN KEY (import_batch_id, command_id)
    REFERENCES feature.curation_import_batches(import_batch_id, command_id)
    ON DELETE RESTRICT
);

CREATE FUNCTION ops.reject_curation_import_plan_mutation()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $guard$
BEGIN
  RAISE EXCEPTION 'curation import plans and receipts are append-only'
    USING ERRCODE = '42501';
END
$guard$;

CREATE FUNCTION ops.reject_curation_import_plan_truncate()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $guard$
BEGIN
  RAISE EXCEPTION 'curation import plans and receipts cannot be truncated'
    USING ERRCODE = '42501';
END
$guard$;

CREATE TRIGGER trg_curation_import_plans_immutable
BEFORE UPDATE OR DELETE ON feature.curation_import_plans
FOR EACH ROW EXECUTE FUNCTION ops.reject_curation_import_plan_mutation();
CREATE TRIGGER trg_curation_import_plan_rows_immutable
BEFORE UPDATE OR DELETE ON feature.curation_import_plan_rows
FOR EACH ROW EXECUTE FUNCTION ops.reject_curation_import_plan_mutation();
CREATE TRIGGER trg_curation_import_plan_revisions_immutable
BEFORE UPDATE OR DELETE ON feature.curation_import_plan_revisions
FOR EACH ROW EXECUTE FUNCTION ops.reject_curation_import_plan_mutation();
CREATE TRIGGER trg_curation_import_plan_commits_immutable
BEFORE UPDATE OR DELETE ON ops.curation_import_plan_commits
FOR EACH ROW EXECUTE FUNCTION ops.reject_curation_import_plan_mutation();
CREATE TRIGGER trg_curation_import_plan_claims_immutable
BEFORE UPDATE OR DELETE ON ops.curation_import_plan_claims
FOR EACH ROW EXECUTE FUNCTION ops.reject_curation_import_plan_mutation();
CREATE TRIGGER trg_curation_import_plans_no_truncate
BEFORE TRUNCATE ON feature.curation_import_plans
FOR EACH STATEMENT EXECUTE FUNCTION ops.reject_curation_import_plan_truncate();
CREATE TRIGGER trg_curation_import_plan_rows_no_truncate
BEFORE TRUNCATE ON feature.curation_import_plan_rows
FOR EACH STATEMENT EXECUTE FUNCTION ops.reject_curation_import_plan_truncate();
CREATE TRIGGER trg_curation_import_plan_revisions_no_truncate
BEFORE TRUNCATE ON feature.curation_import_plan_revisions
FOR EACH STATEMENT EXECUTE FUNCTION ops.reject_curation_import_plan_truncate();
CREATE TRIGGER trg_curation_import_plan_commits_no_truncate
BEFORE TRUNCATE ON ops.curation_import_plan_commits
FOR EACH STATEMENT EXECUTE FUNCTION ops.reject_curation_import_plan_truncate();
CREATE TRIGGER trg_curation_import_plan_claims_no_truncate
BEFORE TRUNCATE ON ops.curation_import_plan_claims
FOR EACH STATEMENT EXECUTE FUNCTION ops.reject_curation_import_plan_truncate();
"""


_COMMANDS = r"""
CREATE PROCEDURE feature.create_curation_import_plan_command(
  IN p_import_plan_id uuid,
  IN p_content_sha256 text,
  IN p_provenance_sha256 text,
  IN p_plan_sha256 text,
  IN p_summary jsonb,
  IN p_rows jsonb,
  IN p_revisions jsonb,
  IN p_expires_at timestamptz,
  IN p_command_id bigint,
  IN p_principal text
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, feature, ops
AS $command$
DECLARE
  v_command ops.domain_commands%ROWTYPE;
  v_row_count integer;
  v_revision_count integer;
BEGIN
  IF current_setting('transaction_isolation') <> 'serializable' THEN
    RAISE EXCEPTION 'curation import preview requires SERIALIZABLE transaction'
      USING ERRCODE = '25001';
  END IF;
  IF NOT pg_has_role(session_user, 'ktm_curation_admin_executor', 'member')
     OR pg_has_role(session_user, 'ktm_curation_provider_executor', 'member') THEN
    RAISE EXCEPTION 'curation import preview requires the admin executor'
      USING ERRCODE = '42501';
  END IF;
  IF p_import_plan_id IS NULL OR p_principal IS NULL
     OR p_principal <> btrim(p_principal) OR p_principal = ''
     OR p_content_sha256 !~ '^[0-9a-f]{64}$'
     OR (p_provenance_sha256 IS NOT NULL AND p_provenance_sha256 !~ '^[0-9a-f]{64}$')
     OR p_plan_sha256 !~ '^[0-9a-f]{64}$'
     OR jsonb_typeof(p_summary) <> 'object'
     OR jsonb_typeof(p_rows) <> 'array'
     OR jsonb_typeof(p_revisions) <> 'array'
     OR p_expires_at <= clock_timestamp() THEN
    RAISE EXCEPTION 'curation import preview input is not canonical'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_import_plan_input';
  END IF;
  SELECT command.* INTO STRICT v_command
  FROM ops.domain_commands AS command WHERE command.command_id = p_command_id
  FOR UPDATE;
  IF v_command.actor <> p_principal
     OR v_command.operation <> 'admin.curation-import.preview'
     OR EXISTS (
       SELECT 1 FROM ops.domain_command_results AS result
       WHERE result.command_id = p_command_id
     ) THEN
    RAISE EXCEPTION 'domain command does not match active curation import preview'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_import_plan_domain_command';
  END IF;
  SELECT count(*)::integer INTO STRICT v_row_count
  FROM jsonb_array_elements(p_rows);
  SELECT count(*)::integer INTO STRICT v_revision_count
  FROM jsonb_array_elements(p_revisions);
  INSERT INTO feature.curation_import_plans (
    import_plan_id, preview_command_id, actor, content_sha256,
    provenance_sha256, plan_sha256, summary, row_count, revision_count,
    expires_at
  ) VALUES (
    p_import_plan_id, p_command_id, p_principal, p_content_sha256,
    p_provenance_sha256, p_plan_sha256, p_summary, v_row_count,
    v_revision_count, p_expires_at
  );
  INSERT INTO feature.curation_import_plan_rows (
    import_plan_id, row_number, normalized_payload, response_payload
  )
  SELECT p_import_plan_id, value.row_number, value.normalized_payload,
         value.response_payload
  FROM jsonb_to_recordset(p_rows) AS value(
    row_number integer, normalized_payload jsonb, response_payload jsonb
  );
  INSERT INTO feature.curation_import_plan_revisions (
    import_plan_id, resource_kind, resource_key, expected_revision
  )
  SELECT p_import_plan_id, value.resource_kind, value.resource_key,
         value.expected_revision
  FROM jsonb_to_recordset(p_revisions) AS value(
    resource_kind text, resource_key text, expected_revision bigint
  );
  IF (SELECT count(*) FROM feature.curation_import_plan_rows AS row
      WHERE row.import_plan_id = p_import_plan_id) <> v_row_count
     OR (SELECT count(*) FROM feature.curation_import_plan_revisions AS revision
         WHERE revision.import_plan_id = p_import_plan_id) <> v_revision_count THEN
    RAISE EXCEPTION 'curation import plan rows or revision vector are not unique'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_import_plan_unique_set';
  END IF;
END
$command$;

CREATE PROCEDURE feature.claim_curation_import_plan_command(
  IN p_import_plan_id uuid,
  IN p_plan_sha256 text,
  IN p_command_id bigint,
  IN p_principal text,
  OUT o_content_sha256 text,
  OUT o_rows jsonb,
  OUT o_summary jsonb,
  OUT o_response_rows jsonb,
  OUT o_expires_at timestamptz
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, feature, ops
AS $command$
DECLARE
  v_command ops.domain_commands%ROWTYPE;
  v_plan feature.curation_import_plans%ROWTYPE;
BEGIN
  IF current_setting('transaction_isolation') <> 'serializable' THEN
    RAISE EXCEPTION 'curation import commit requires SERIALIZABLE transaction'
      USING ERRCODE = '25001';
  END IF;
  IF NOT pg_has_role(session_user, 'ktm_curation_admin_executor', 'member')
     OR pg_has_role(session_user, 'ktm_curation_provider_executor', 'member') THEN
    RAISE EXCEPTION 'curation import commit requires the admin executor'
      USING ERRCODE = '42501';
  END IF;
  PERFORM pg_advisory_xact_lock(
    hashtextextended('curation-import-plan:' || p_import_plan_id::text, 0)
  );
  SELECT command.* INTO STRICT v_command
  FROM ops.domain_commands AS command WHERE command.command_id = p_command_id
  FOR UPDATE;
  IF v_command.actor <> p_principal
     OR v_command.operation <> 'admin.curation.import'
     OR EXISTS (
       SELECT 1 FROM ops.domain_command_results AS result
       WHERE result.command_id = p_command_id
     ) THEN
    RAISE EXCEPTION 'domain command does not match active curation import commit'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_import_plan_commit_command';
  END IF;
  SELECT plan.* INTO STRICT v_plan
  FROM feature.curation_import_plans AS plan
  WHERE plan.import_plan_id = p_import_plan_id;
  IF v_plan.actor <> p_principal OR v_plan.plan_sha256 <> p_plan_sha256 THEN
    RAISE EXCEPTION 'curation import plan actor or ETag changed'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_import_plan_etag';
  END IF;
  IF v_plan.expires_at <= clock_timestamp() THEN
    RAISE EXCEPTION 'curation import plan expired'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_import_plan_expired';
  END IF;
  IF COALESCE((v_plan.summary ->> 'has_errors')::boolean, true) THEN
    RAISE EXCEPTION 'curation import plan contains unresolved validation errors'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_import_plan_has_errors';
  END IF;
  IF EXISTS (
    SELECT 1 FROM ops.curation_import_plan_commits AS committed
    WHERE committed.import_plan_id = p_import_plan_id
  ) THEN
    RAISE EXCEPTION 'curation import plan already committed'
      USING ERRCODE = '23505', CONSTRAINT = 'uq_tvn40_import_plan_commit';
  END IF;

  IF EXISTS (
    SELECT 1
    FROM feature.curation_import_plan_revisions AS expected
    LEFT JOIN LATERAL (
      SELECT current_row.row_revision
      FROM (
        SELECT theme.row_revision
        FROM feature.curated_themes AS theme
        WHERE expected.resource_kind = 'theme'
          AND theme.theme_id = expected.resource_key::uuid
          AND theme.archived_at IS NULL
        UNION ALL
        SELECT source.row_revision
        FROM feature.curated_sources AS source
        WHERE expected.resource_kind = 'source'
          AND source.source_id = expected.resource_key::uuid
          AND source.archived_at IS NULL
        UNION ALL
        SELECT collection.row_revision
        FROM feature.curation_collections AS collection
        WHERE expected.resource_kind = 'collection'
          AND collection.collection_key = expected.resource_key
          AND collection.archived_at IS NULL
        UNION ALL
        SELECT item.row_revision
        FROM feature.curation_items AS item
        JOIN feature.curation_collections AS collection
          ON collection.collection_id = item.collection_id
        WHERE expected.resource_kind = 'item'
          AND collection.collection_key = expected.resource_key::jsonb ->> 0
          AND item.external_item_id = expected.resource_key::jsonb ->> 1
          AND item.external_component_id = expected.resource_key::jsonb ->> 2
        UNION ALL
        SELECT core.row_revision
        FROM feature.features AS core
        WHERE expected.resource_kind = 'feature'
          AND core.feature_id = expected.resource_key
      ) AS current_row
    ) AS current ON true
    WHERE expected.import_plan_id = p_import_plan_id
      AND current.row_revision IS DISTINCT FROM expected.expected_revision
  ) THEN
    RAISE EXCEPTION 'curation import plan revision vector is stale'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_import_plan_revision_vector';
  END IF;
  o_content_sha256 := v_plan.content_sha256;
  o_summary := v_plan.summary;
  o_expires_at := v_plan.expires_at;
  SELECT COALESCE(jsonb_agg(row.normalized_payload ORDER BY row.row_number)
                  FILTER (WHERE row.normalized_payload IS NOT NULL), '[]'::jsonb)
  INTO STRICT o_rows
  FROM feature.curation_import_plan_rows AS row
  WHERE row.import_plan_id = p_import_plan_id;
  SELECT COALESCE(jsonb_agg(row.response_payload ORDER BY row.row_number), '[]'::jsonb)
  INTO STRICT o_response_rows
  FROM feature.curation_import_plan_rows AS row
  WHERE row.import_plan_id = p_import_plan_id;
  INSERT INTO ops.curation_import_plan_claims (
    import_plan_id, command_id, plan_sha256
  ) VALUES (
    p_import_plan_id, p_command_id, p_plan_sha256
  );
END
$command$;

CREATE PROCEDURE feature.complete_curation_import_plan_command(
  IN p_import_plan_id uuid,
  IN p_command_id bigint,
  IN p_import_batch_id uuid,
  IN p_result_payload jsonb,
  IN p_principal text
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, feature, ops
AS $command$
DECLARE
  v_batch feature.curation_import_batches%ROWTYPE;
BEGIN
  IF jsonb_typeof(p_result_payload) <> 'object' THEN
    RAISE EXCEPTION 'curation import terminal result must be an object'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_import_plan_result';
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
    RAISE EXCEPTION 'domain command does not match active curation import commit'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_import_plan_commit_command';
  END IF;
  SELECT batch.* INTO STRICT v_batch
  FROM feature.curation_import_batches AS batch
  JOIN ops.curation_import_plan_claims AS claim
    ON claim.command_id = batch.command_id
  JOIN feature.curation_import_plans AS plan
    ON plan.import_plan_id = claim.import_plan_id
  WHERE batch.import_batch_id = p_import_batch_id
    AND batch.command_id = p_command_id
    AND claim.import_plan_id = p_import_plan_id
    AND batch.content_sha256 = plan.content_sha256;
  INSERT INTO ops.curation_import_plan_commits (
    import_plan_id, command_id, import_batch_id, result_payload
  ) VALUES (
    p_import_plan_id, p_command_id, p_import_batch_id,
    p_result_payload || jsonb_build_object(
      'db_receipt', jsonb_build_object(
        'import_batch_id', v_batch.import_batch_id,
        'command_id', v_batch.command_id,
        'content_sha256', v_batch.content_sha256,
        'row_count', v_batch.row_count
      )
    )
  );
END
$command$;
"""


_CREATE_SIGNATURE = (
    "feature.create_curation_import_plan_command("
    "uuid,text,text,text,jsonb,jsonb,jsonb,timestamptz,bigint,text)"
)
_CLAIM_SIGNATURE = (
    "feature.claim_curation_import_plan_command(uuid,text,bigint,text)"
)
_COMPLETE_SIGNATURE = (
    "feature.complete_curation_import_plan_command(uuid,bigint,uuid,jsonb,text)"
)


def upgrade() -> None:
    _execute_commands(_DDL)
    _execute_commands(_COMMANDS)
    for signature in (_CREATE_SIGNATURE, _CLAIM_SIGNATURE, _COMPLETE_SIGNATURE):
        op.execute(f"ALTER PROCEDURE {signature} OWNER TO ktm_curation_command_owner")
    for function in (
        "ops.reject_curation_import_plan_mutation()",
        "ops.reject_curation_import_plan_truncate()",
    ):
        op.execute(f"ALTER FUNCTION {function} OWNER TO ktm_curation_audit_writer")
        op.execute(
            f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC, ktm_feature_runtime, "
            "ktm_curation_admin_executor, ktm_curation_provider_executor, "
            "ktm_curation_command_owner"
        )
    op.execute(
        "GRANT SELECT, INSERT ON feature.curation_import_plans, "
        "feature.curation_import_plan_rows, feature.curation_import_plan_revisions "
        "TO ktm_curation_command_owner"
    )
    op.execute(
        "GRANT SELECT, INSERT ON ops.curation_import_plan_claims, "
        "ops.curation_import_plan_commits "
        "TO ktm_curation_command_owner"
    )
    op.execute(
        "REVOKE ALL ON feature.curation_import_plans, "
        "feature.curation_import_plan_rows, feature.curation_import_plan_revisions, "
        "ops.curation_import_plan_claims, ops.curation_import_plan_commits "
        "FROM PUBLIC, ktm_feature_runtime, "
        "ktm_feature_api_runtime, ktm_feature_dagster_runtime, "
        "ktm_curation_admin_executor, ktm_curation_provider_executor"
    )
    op.execute("SET ROLE ktm_curation_command_owner")
    for signature in (_CREATE_SIGNATURE, _CLAIM_SIGNATURE, _COMPLETE_SIGNATURE):
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
    raise RuntimeError("0119 is forward-only; rebuild with the T-VN-40 release head")
