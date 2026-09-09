SET ROLE ktm_feature_state_procedure_owner;

DROP PROCEDURE feature.transition_feature_state(text, text, text, text, bigint, jsonb);

CREATE PROCEDURE feature.transition_feature_state(IN p_feature_id uuid, IN p_lifecycle_state text, IN p_publication_state text, IN p_quality_state text, IN p_expected_row_revision bigint, IN p_context jsonb, OUT o_feature_id uuid, OUT o_row_revision bigint)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog'
    AS $$
DECLARE
    v_current feature.features%ROWTYPE;
    v_override_row_revision bigint;
BEGIN
    IF p_expected_row_revision IS NULL OR p_expected_row_revision < 1 THEN
        RAISE EXCEPTION 'expected feature row revision is required'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_state_expected_revision';
    END IF;
    PERFORM feature.prepare_feature_state_context(p_context, 'transition');
    -- Provider ingestion locks dataset/entity/record/current-head, then the
    -- Feature source link, then the Feature.  Do the same for every provider
    -- transition. A head advance can therefore either happen before this call
    -- (and reject stale evidence) or after this transition/audit commit,
    -- never between proof and audit.
    IF p_context ->> 'transition_kind' = 'provider_sync' THEN
        PERFORM feature.lock_current_provider_feature_source_evidence(
            p_feature_id,
            (p_context ->> 'provider_dataset_id')::bigint,
            p_context ->> 'source_entity_key',
            p_context ->> 'source_record_key'
        );
    END IF;
    SELECT * INTO v_current
      FROM feature.features
     WHERE feature_id = p_feature_id
     FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'feature % does not exist', p_feature_id USING ERRCODE = 'P0002';
    END IF;
    IF v_current.row_revision <> p_expected_row_revision THEN
        RAISE EXCEPTION 'feature % revision changed', p_feature_id USING ERRCODE = '40001';
    END IF;
    IF (v_current.lifecycle_state, v_current.publication_state, v_current.quality_state)
       IS NOT DISTINCT FROM (p_lifecycle_state, p_publication_state, p_quality_state) THEN
        RAISE EXCEPTION 'feature state transition must change at least one axis'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_state_transition_non_noop';
    END IF;
    IF v_current.lifecycle_state = 'retired' AND p_lifecycle_state = 'active' THEN
        IF p_context ->> 'transition_kind' <> 'provider_sync'
           AND (p_context ->> 'transition_kind' NOT IN ('admin', 'user_request', 'system')
           OR coalesce(btrim(p_context ->> 'reactivation_evidence'), '') = '') THEN
            RAISE EXCEPTION 'retired feature may be reactivated only by explicit reingest'
                USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_reactivation_explicit';
        END IF;
        IF EXISTS (
            SELECT 1 FROM ops.feature_overrides AS override
            WHERE override.feature_id = p_feature_id
              AND override.field_path = 'lifecycle_state'
              AND override.status = 'active'
              AND override.override_value = '"retired"'::jsonb
              AND override.prevent_provider_reactivation
        ) AND p_context ->> 'transition_kind' = 'provider_sync' THEN
            RAISE EXCEPTION 'provider reactivation is fenced by lifecycle override'
                USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_provider_reactivation_override';
        END IF;
    END IF;
    UPDATE feature.features
       SET lifecycle_state = p_lifecycle_state,
           publication_state = p_publication_state,
           quality_state = p_quality_state,
           updated_at = clock_timestamp()
     WHERE feature_id = p_feature_id
     RETURNING feature_id, row_revision INTO o_feature_id, o_row_revision;
    -- Any non-provider retirement is not a provider tombstone. Make its
    -- lifecycle override inseparable from the state transition so callers of
    -- this generic internal procedure cannot create a retired row that a
    -- later provider observation can resurrect.
    IF v_current.lifecycle_state = 'active'
       AND p_lifecycle_state = 'retired'
       AND (p_context ->> 'transition_kind') <> 'provider_sync' THEN
        CALL feature.author_lifecycle_override(
            p_feature_id,
            v_current.lifecycle_state,
            'retired',
            true,
            btrim(p_context ->> 'reason_code'),
            btrim(p_context ->> 'principal'),
            o_row_revision,
            v_override_row_revision
        );
        IF v_override_row_revision <> o_row_revision THEN
            RAISE EXCEPTION 'non-provider retirement wrote an inconsistent lifecycle override';
        END IF;
    END IF;
END;
$$;

ALTER PROCEDURE feature.transition_feature_state(IN p_feature_id uuid, IN p_lifecycle_state text, IN p_publication_state text, IN p_quality_state text, IN p_expected_row_revision bigint, IN p_context jsonb, OUT o_feature_id uuid, OUT o_row_revision bigint) OWNER TO ktm_feature_state_procedure_owner;

REVOKE ALL ON PROCEDURE feature.transition_feature_state(uuid, text, text, text, bigint, jsonb) FROM PUBLIC;
GRANT EXECUTE ON PROCEDURE feature.transition_feature_state(uuid, text, text, text, bigint, jsonb) TO ktm_feature_runtime;

SET ROLE ktm_feature_schema_owner;
