-- ─────────────────────────────────────────────────────────────────────────
-- feature.append_theme_feature_candidate_transition
--   p_from_feature_id / p_to_feature_id : text → uuid
--   본문은 원문 그대로다(컬럼 목록·VALUES·DECLARE 모두 무변경).
-- DROP은 소유자만 할 수 있다 — schema owner가 멤버십을 갖는다(302:310-311).
-- ─────────────────────────────────────────────────────────────────────────
SET ROLE ktm_curation_audit_writer;

DROP FUNCTION feature.append_theme_feature_candidate_transition(uuid,text,text,uuid,text,text,text,boolean,boolean,text,text,uuid,text,bigint,bigint,text,text,uuid,bigint,text,text,uuid,uuid,bigint,text,text,jsonb);

-- CREATE는 schema owner로 수행한다(0203:272-274 / 304의 착지 패턴).
SET ROLE ktm_feature_schema_owner;

CREATE FUNCTION feature.append_theme_feature_candidate_transition(p_candidate_id uuid, p_from_feature_id uuid, p_to_feature_id uuid, p_rule_id uuid, p_source_entity_key text, p_from_review_state text, p_to_review_state text, p_from_eligibility_present boolean, p_to_eligibility_present boolean, p_from_disposition text, p_to_disposition text, p_winner_candidate_id uuid, p_transition_kind text, p_candidate_row_revision bigint, p_rule_row_revision bigint, p_rule_input_hash text, p_candidate_input_hash text, p_generation_id uuid, p_provider_dataset_id bigint, p_source_record_key text, p_source_record_hash text, p_collection_id uuid, p_curation_item_id uuid, p_command_id bigint, p_actor text, p_reason_code text, p_causation_ref jsonb) RETURNS bigint
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'feature', 'ops'
    AS $$
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
$$;

ALTER FUNCTION feature.append_theme_feature_candidate_transition(p_candidate_id uuid, p_from_feature_id uuid, p_to_feature_id uuid, p_rule_id uuid, p_source_entity_key text, p_from_review_state text, p_to_review_state text, p_from_eligibility_present boolean, p_to_eligibility_present boolean, p_from_disposition text, p_to_disposition text, p_winner_candidate_id uuid, p_transition_kind text, p_candidate_row_revision bigint, p_rule_row_revision bigint, p_rule_input_hash text, p_candidate_input_hash text, p_generation_id uuid, p_provider_dataset_id bigint, p_source_record_key text, p_source_record_hash text, p_collection_id uuid, p_curation_item_id uuid, p_command_id bigint, p_actor text, p_reason_code text, p_causation_ref jsonb) OWNER TO ktm_curation_audit_writer;

-- ACL은 정확히 그 소유자 role로 편집해야 한다. schema owner가 멤버십만으로
-- REVOKE하면 경고만 나고 기본 PUBLIC EXECUTE가 남는다(0203:290-293 실측).
SET ROLE ktm_curation_audit_writer;

REVOKE ALL ON FUNCTION feature.append_theme_feature_candidate_transition(p_candidate_id uuid, p_from_feature_id uuid, p_to_feature_id uuid, p_rule_id uuid, p_source_entity_key text, p_from_review_state text, p_to_review_state text, p_from_eligibility_present boolean, p_to_eligibility_present boolean, p_from_disposition text, p_to_disposition text, p_winner_candidate_id uuid, p_transition_kind text, p_candidate_row_revision bigint, p_rule_row_revision bigint, p_rule_input_hash text, p_candidate_input_hash text, p_generation_id uuid, p_provider_dataset_id bigint, p_source_record_key text, p_source_record_hash text, p_collection_id uuid, p_curation_item_id uuid, p_command_id bigint, p_actor text, p_reason_code text, p_causation_ref jsonb) FROM PUBLIC;
GRANT ALL ON FUNCTION feature.append_theme_feature_candidate_transition(p_candidate_id uuid, p_from_feature_id uuid, p_to_feature_id uuid, p_rule_id uuid, p_source_entity_key text, p_from_review_state text, p_to_review_state text, p_from_eligibility_present boolean, p_to_eligibility_present boolean, p_from_disposition text, p_to_disposition text, p_winner_candidate_id uuid, p_transition_kind text, p_candidate_row_revision bigint, p_rule_row_revision bigint, p_rule_input_hash text, p_candidate_input_hash text, p_generation_id uuid, p_provider_dataset_id bigint, p_source_record_key text, p_source_record_hash text, p_collection_id uuid, p_curation_item_id uuid, p_command_id bigint, p_actor text, p_reason_code text, p_causation_ref jsonb) TO ktm_curation_command_owner;

SET ROLE ktm_feature_schema_owner;
