CREATE OR REPLACE PROCEDURE feature.reject_theme_feature_candidate(IN p_candidate_id uuid, IN p_expected_candidate_revision bigint, IN p_command_id bigint, IN p_reason_code text, IN p_principal text, OUT o_candidate_id uuid, OUT o_candidate_revision bigint, OUT o_transition_id bigint)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'feature', 'provider_sync', 'ops'
    AS $$
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
$$;
