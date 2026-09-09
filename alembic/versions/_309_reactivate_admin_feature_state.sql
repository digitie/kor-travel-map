SET ROLE ktm_feature_state_procedure_owner;

DROP PROCEDURE feature.reactivate_admin_feature_state(text, bigint, text, text, bigint, text, text);

CREATE PROCEDURE feature.reactivate_admin_feature_state(IN p_feature_id uuid, IN p_provider_dataset_id bigint, IN p_source_entity_key text, IN p_source_record_key text, IN p_expected_row_revision bigint, IN p_reason_code text, IN p_principal text, OUT o_feature_id uuid, OUT o_row_revision bigint, OUT o_transition_id bigint)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog'
    AS $$
DECLARE
    v_current feature.features%ROWTYPE;
    v_raw_payload_hash text;
    v_causation_ref text;
BEGIN
    IF p_provider_dataset_id IS NULL
       OR coalesce(btrim(p_source_entity_key), '') = ''
       OR coalesce(btrim(p_source_record_key), '') = ''
       OR p_expected_row_revision IS NULL OR p_expected_row_revision < 1
       OR coalesce(btrim(p_reason_code), '') = ''
       OR coalesce(btrim(p_principal), '') = '' THEN
        RAISE EXCEPTION 'admin reactivation has invalid arguments'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_admin_reactivation';
    END IF;
    -- Match provider ingestion's source→Feature lock order.  This proof stays
    -- locked through the override revocation, state transition and audit.
    v_raw_payload_hash := feature.lock_current_provider_feature_source_evidence(
        p_feature_id,
        p_provider_dataset_id,
        p_source_entity_key,
        p_source_record_key
    );
    SELECT * INTO v_current FROM feature.features
     WHERE feature_id = p_feature_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'feature % does not exist', p_feature_id USING ERRCODE = 'P0002';
    END IF;
    IF v_current.row_revision <> p_expected_row_revision THEN
        RAISE EXCEPTION 'feature % revision changed', p_feature_id USING ERRCODE = '40001';
    END IF;
    IF v_current.lifecycle_state <> 'retired' THEN
        RAISE EXCEPTION 'admin reactivation requires a retired feature'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_admin_reactivation';
    END IF;
    IF EXISTS (
        SELECT 1 FROM ops.feature_overrides AS override
        WHERE override.feature_id = p_feature_id
          AND override.field_path = 'lifecycle_state'
          AND override.status = 'active'
          AND override.override_value IS DISTINCT FROM '"retired"'::jsonb
    ) THEN
        RAISE EXCEPTION 'active lifecycle override is inconsistent with retired feature'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_admin_reactivation';
    END IF;
    UPDATE ops.feature_overrides AS override
       SET status = 'superseded',
           created_by = btrim(p_principal),
           created_at = clock_timestamp()
     WHERE override.feature_id = p_feature_id
       AND override.field_path = 'lifecycle_state'
       AND override.status = 'active'
       AND override.override_value = '"retired"'::jsonb;
    v_causation_ref := jsonb_build_object(
        'provider_dataset_id', p_provider_dataset_id,
        'source_entity_key', btrim(p_source_entity_key),
        'source_record_key', btrim(p_source_record_key),
        'raw_payload_hash', v_raw_payload_hash
    )::text;
    CALL feature.transition_feature_state(
        p_feature_id, 'active', 'suppressed', v_current.quality_state,
        p_expected_row_revision,
        jsonb_build_object(
            'transition_kind', 'admin',
            'reason_code', btrim(p_reason_code),
            'principal', btrim(p_principal),
            'causation_ref', v_causation_ref,
            'reactivation_evidence', v_causation_ref::jsonb
        ),
        o_feature_id, o_row_revision
    );
    SELECT transition.transition_id INTO o_transition_id
    FROM feature.feature_state_transitions AS transition
    WHERE transition.feature_id = o_feature_id
      AND transition.row_revision = o_row_revision
      AND transition.transition_kind = 'admin'
      AND transition.reason_code = btrim(p_reason_code)
      AND transition.principal = btrim(p_principal)
      AND transition.causation_ref = v_causation_ref
    ORDER BY transition.transition_id DESC
    LIMIT 1;
    IF o_transition_id IS NULL THEN
        RAISE EXCEPTION 'admin reactivation did not write its audit transition';
    END IF;
END;
$$;

ALTER PROCEDURE feature.reactivate_admin_feature_state(IN p_feature_id uuid, IN p_provider_dataset_id bigint, IN p_source_entity_key text, IN p_source_record_key text, IN p_expected_row_revision bigint, IN p_reason_code text, IN p_principal text, OUT o_feature_id uuid, OUT o_row_revision bigint, OUT o_transition_id bigint) OWNER TO ktm_feature_state_procedure_owner;

REVOKE ALL ON PROCEDURE feature.reactivate_admin_feature_state(IN p_feature_id uuid, IN p_provider_dataset_id bigint, IN p_source_entity_key text, IN p_source_record_key text, IN p_expected_row_revision bigint, IN p_reason_code text, IN p_principal text, OUT o_feature_id uuid, OUT o_row_revision bigint, OUT o_transition_id bigint) FROM PUBLIC;
GRANT ALL ON PROCEDURE feature.reactivate_admin_feature_state(IN p_feature_id uuid, IN p_provider_dataset_id bigint, IN p_source_entity_key text, IN p_source_record_key text, IN p_expected_row_revision bigint, IN p_reason_code text, IN p_principal text, OUT o_feature_id uuid, OUT o_row_revision bigint, OUT o_transition_id bigint) TO ktm_feature_runtime;

SET ROLE ktm_feature_schema_owner;
