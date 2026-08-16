"""T-VN-40B typed candidate command boundary.

Revision ID: 0203_tvn40_candidate_commands
Revises: 0202_tvn40_curation_receipts

The transition table is append-only evidence.  Runtime logins may invoke the
named candidate procedures, but only the audit-writer helper can append a
transition row and no runtime principal can execute that helper directly.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# Frozen PostgreSQL procedure text intentionally exceeds Python line length.
# ruff: noqa: E501

revision: str = "0203_tvn40_candidate_commands"
down_revision: str | Sequence[str] | None = "0202_tvn40_curation_receipts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_TRANSITION_CONSTRAINTS_SQL = r"""
ALTER TABLE feature.theme_feature_candidate_transitions
  ADD CONSTRAINT ck_candidate_transition_initial_shape CHECK (
    (transition_kind = 'eligibility_materialize'
      AND from_review_state IS NULL AND from_eligibility_present IS NULL
      AND from_disposition IS NULL
      AND to_review_state = 'open' AND to_eligibility_present
      AND to_disposition = 'active')
    OR (transition_kind = 'legacy_backfill'
      AND from_review_state IS NULL AND from_eligibility_present IS NULL
      AND from_disposition IS NULL AND to_disposition = 'active')
    OR (transition_kind = 'eligibility_refresh'
      AND from_review_state = to_review_state
      AND from_eligibility_present AND to_eligibility_present
      AND from_disposition = 'active' AND to_disposition = 'active')
    OR (transition_kind = 'eligibility_restore'
      AND from_review_state = to_review_state
      AND NOT from_eligibility_present AND to_eligibility_present
      AND from_disposition = 'active' AND to_disposition = 'active')
    OR (transition_kind = 'eligibility_remove'
      AND from_review_state = to_review_state
      AND from_eligibility_present AND NOT to_eligibility_present
      AND from_disposition = 'active' AND to_disposition = 'active')
    OR (transition_kind = 'admin_promote'
      AND from_review_state = 'open' AND to_review_state = 'promoted'
      AND from_eligibility_present AND to_eligibility_present
      AND from_disposition = 'active' AND to_disposition = 'active')
    OR (transition_kind = 'admin_reject'
      AND from_review_state = 'open' AND to_review_state = 'rejected'
      AND from_eligibility_present AND to_eligibility_present
      AND from_disposition = 'active' AND to_disposition = 'active')
    OR (transition_kind = 'merge_retarget'
      AND from_review_state IS NOT NULL
      AND from_eligibility_present IS NOT NULL
      AND from_disposition = 'active' AND to_disposition = 'active'
      AND from_feature_id IS DISTINCT FROM to_feature_id)
    OR (transition_kind = 'merge_collapse'
      AND from_review_state IS NOT NULL
      AND from_eligibility_present IS NOT NULL
      AND from_disposition = 'active' AND to_disposition = 'merged'
      AND winner_candidate_id IS NOT NULL)
  ),
  ADD CONSTRAINT ck_candidate_transition_kind_shape CHECK (
    (transition_kind IN (
        'eligibility_materialize','eligibility_refresh',
        'eligibility_restore','eligibility_remove'
      )
      AND generation_id IS NOT NULL AND provider_dataset_id IS NOT NULL
      AND source_record_key IS NOT NULL AND source_record_hash IS NOT NULL
      AND command_id IS NULL AND collection_id IS NULL AND curation_item_id IS NULL)
    OR (transition_kind = 'admin_promote'
      AND generation_id IS NULL AND command_id IS NOT NULL
      AND collection_id IS NOT NULL AND curation_item_id IS NOT NULL)
    OR (transition_kind = 'admin_reject'
      AND generation_id IS NULL AND command_id IS NOT NULL
      AND collection_id IS NULL AND curation_item_id IS NULL)
    OR (transition_kind IN ('merge_retarget','merge_collapse')
      AND generation_id IS NULL AND command_id IS NOT NULL)
    OR (transition_kind = 'legacy_backfill'
      AND generation_id IS NOT NULL AND command_id IS NULL
      AND actor = 'migration:tvn40')
  );
"""


_AUDIT_FUNCTION_SQL = r"""
CREATE FUNCTION feature.append_theme_feature_candidate_transition(
  p_candidate_id uuid,
  p_from_feature_id text,
  p_to_feature_id text,
  p_rule_id uuid,
  p_source_entity_key text,
  p_from_review_state text,
  p_to_review_state text,
  p_from_eligibility_present boolean,
  p_to_eligibility_present boolean,
  p_from_disposition text,
  p_to_disposition text,
  p_winner_candidate_id uuid,
  p_transition_kind text,
  p_candidate_row_revision bigint,
  p_rule_row_revision bigint,
  p_rule_input_hash text,
  p_candidate_input_hash text,
  p_generation_id uuid,
  p_provider_dataset_id bigint,
  p_source_record_key text,
  p_source_record_hash text,
  p_collection_id uuid,
  p_curation_item_id uuid,
  p_command_id bigint,
  p_actor text,
  p_reason_code text,
  p_causation_ref jsonb
) RETURNS bigint
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, feature, ops
AS $audit$
DECLARE
  v_transition_id bigint;
BEGIN
  INSERT INTO feature.theme_feature_candidate_transitions (
    candidate_id, from_feature_id, to_feature_id, rule_id, source_entity_key,
    from_review_state, to_review_state,
    from_eligibility_present, to_eligibility_present,
    from_disposition, to_disposition, winner_candidate_id, transition_kind,
    candidate_row_revision, rule_row_revision, rule_input_hash,
    candidate_input_hash, generation_id, provider_dataset_id,
    source_record_key, source_record_hash, collection_id, curation_item_id,
    command_id, actor, reason_code, causation_ref, invoker_role,
    candidate_procedure_definer, audit_writer_definer
  ) VALUES (
    p_candidate_id, p_from_feature_id, p_to_feature_id, p_rule_id,
    p_source_entity_key, p_from_review_state, p_to_review_state,
    p_from_eligibility_present, p_to_eligibility_present,
    p_from_disposition, p_to_disposition, p_winner_candidate_id,
    p_transition_kind, p_candidate_row_revision, p_rule_row_revision,
    p_rule_input_hash, p_candidate_input_hash, p_generation_id,
    p_provider_dataset_id, p_source_record_key, p_source_record_hash,
    p_collection_id, p_curation_item_id, p_command_id, p_actor,
    p_reason_code, COALESCE(p_causation_ref, '{}'::jsonb), session_user,
    'ktm_curation_command_owner', current_user
  )
  RETURNING transition_id INTO STRICT v_transition_id;
  RETURN v_transition_id;
END
$audit$;
"""


_REJECT_PROCEDURE_SQL = r"""
CREATE PROCEDURE feature.reject_theme_feature_candidate(
  IN p_candidate_id uuid,
  IN p_expected_candidate_revision bigint,
  IN p_command_id bigint,
  IN p_reason_code text,
  IN p_principal text,
  OUT o_candidate_id uuid,
  OUT o_candidate_revision bigint,
  OUT o_transition_id bigint
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, feature, provider_sync, ops
AS $command$
DECLARE
  v_candidate feature.theme_feature_candidates%ROWTYPE;
  v_command ops.domain_commands%ROWTYPE;
BEGIN
  IF current_setting('transaction_isolation') <> 'serializable' THEN
    RAISE EXCEPTION 'candidate command requires SERIALIZABLE transaction'
      USING ERRCODE = '25001';
  END IF;
  IF NOT pg_has_role(session_user, 'ktm_curation_admin_executor', 'member')
     OR pg_has_role(session_user, 'ktm_curation_provider_executor', 'member') THEN
    RAISE EXCEPTION 'candidate rejection requires the admin executor'
      USING ERRCODE = '42501';
  END IF;
  IF p_expected_candidate_revision IS NULL OR p_expected_candidate_revision < 1 THEN
    RAISE EXCEPTION 'expected candidate revision must be positive'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_theme_candidate_expected_revision';
  END IF;
  IF p_reason_code IS NULL OR p_reason_code <> btrim(p_reason_code)
     OR p_reason_code = '' OR char_length(p_reason_code) > 128 THEN
    RAISE EXCEPTION 'reason_code must be canonical and non-empty'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_theme_candidate_reason_code';
  END IF;
  IF p_principal IS NULL OR p_principal <> btrim(p_principal)
     OR p_principal = '' OR char_length(p_principal) > 200 THEN
    RAISE EXCEPTION 'principal must be canonical and non-empty'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_theme_candidate_principal';
  END IF;

  SELECT command.* INTO STRICT v_command
  FROM ops.domain_commands AS command
  WHERE command.command_id = p_command_id;
  IF v_command.actor <> p_principal
     OR v_command.operation <> 'admin.theme-feature-candidate.reject' THEN
    RAISE EXCEPTION 'domain command does not match candidate rejection'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_theme_candidate_domain_command';
  END IF;

  SELECT candidate.* INTO STRICT v_candidate
  FROM feature.theme_feature_candidates AS candidate
  WHERE candidate.candidate_id = p_candidate_id
  FOR UPDATE;
  IF v_candidate.row_revision <> p_expected_candidate_revision THEN
    RAISE EXCEPTION 'candidate revision mismatch: expected %, current %',
      p_expected_candidate_revision, v_candidate.row_revision
      USING ERRCODE = '23514', CONSTRAINT = 'ck_theme_candidate_expected_revision';
  END IF;
  IF v_candidate.disposition <> 'active'
     OR v_candidate.review_state <> 'open'
     OR NOT v_candidate.eligibility_present THEN
    RAISE EXCEPTION 'only an active open eligible candidate can be rejected'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_theme_candidate_reject_state';
  END IF;

  UPDATE feature.theme_feature_candidates AS candidate
  SET review_state = 'rejected',
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
    'rejected',
    v_candidate.eligibility_present,
    v_candidate.eligibility_present,
    v_candidate.disposition,
    v_candidate.disposition,
    NULL,
    'admin_reject',
    o_candidate_revision,
    v_candidate.rule_row_revision,
    v_candidate.rule_input_hash,
    v_candidate.candidate_input_hash,
    NULL,
    NULL,
    v_candidate.source_record_key,
    v_candidate.source_record_hash,
    NULL,
    NULL,
    p_command_id,
    p_principal,
    p_reason_code,
    jsonb_build_object(
      'schema_version', 1,
      'candidate_id', p_candidate_id::text,
      'expected_candidate_revision', p_expected_candidate_revision
    )
  );
END
$command$;
"""


def upgrade() -> None:
    op.execute(_TRANSITION_CONSTRAINTS_SQL)
    op.execute(_AUDIT_FUNCTION_SQL)
    op.execute(_REJECT_PROCEDURE_SQL)

    op.execute(
        "ALTER FUNCTION feature.append_theme_feature_candidate_transition("
        "uuid,text,text,uuid,text,text,text,boolean,boolean,text,text,uuid,text,"
        "bigint,bigint,text,text,uuid,bigint,text,text,uuid,uuid,bigint,text,text,jsonb) "
        "OWNER TO ktm_curation_audit_writer"
    )
    op.execute(
        "ALTER PROCEDURE feature.reject_theme_feature_candidate("
        "uuid,bigint,bigint,text,text) OWNER TO ktm_curation_command_owner"
    )
    op.execute(
        "GRANT SELECT ON TABLE ops.domain_commands TO ktm_curation_command_owner"
    )
    # The schema owner can transfer a routine but, after transfer, cannot edit
    # its ACL merely because it has SET membership in the new NOLOGIN owner.
    # Enter each exact owner explicitly; otherwise PostgreSQL only emits a
    # warning and leaves the default PUBLIC EXECUTE grant in place.
    op.execute("SET ROLE ktm_curation_audit_writer")
    op.execute(
        "REVOKE ALL ON FUNCTION feature.append_theme_feature_candidate_transition("
        "uuid,text,text,uuid,text,text,text,boolean,boolean,text,text,uuid,text,"
        "bigint,bigint,text,text,uuid,bigint,text,text,uuid,uuid,bigint,text,text,jsonb) "
        "FROM PUBLIC, ktm_feature_runtime, ktm_feature_api_runtime, "
        "ktm_feature_dagster_runtime, ktm_curation_admin_executor, "
        "ktm_curation_provider_executor"
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION feature.append_theme_feature_candidate_transition("
        "uuid,text,text,uuid,text,text,text,boolean,boolean,text,text,uuid,text,"
        "bigint,bigint,text,text,uuid,bigint,text,text,uuid,uuid,bigint,text,text,jsonb) "
        "TO ktm_curation_command_owner"
    )
    for guard in (
        "feature.reject_tvn40_append_only_mutation()",
        "feature.reject_tvn40_truncate()",
        "feature.validate_theme_candidate_merge_target()",
    ):
        op.execute(
            f"REVOKE ALL ON FUNCTION {guard} FROM PUBLIC, ktm_feature_runtime, "
            "ktm_feature_api_runtime, ktm_feature_dagster_runtime, "
            "ktm_curation_command_owner, ktm_curation_admin_executor, "
            "ktm_curation_provider_executor"
        )
    op.execute("SET ROLE ktm_feature_schema_owner")
    op.execute("SET ROLE ktm_curation_command_owner")
    op.execute(
        "REVOKE ALL ON PROCEDURE feature.reject_theme_feature_candidate("
        "uuid,bigint,bigint,text,text) FROM PUBLIC, ktm_feature_runtime, "
        "ktm_feature_api_runtime, ktm_feature_dagster_runtime, "
        "ktm_curation_provider_executor"
    )
    op.execute(
        "GRANT EXECUTE ON PROCEDURE feature.reject_theme_feature_candidate("
        "uuid,bigint,bigint,text,text) TO ktm_curation_admin_executor"
    )
    op.execute("SET ROLE ktm_feature_schema_owner")


def downgrade() -> None:
    raise RuntimeError("0203_tvn40_candidate_commands is forward-only; rebuild with the T-VN-40 release head")
