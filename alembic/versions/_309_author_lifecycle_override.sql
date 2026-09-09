SET ROLE ktm_feature_state_procedure_owner;

DROP PROCEDURE feature.author_lifecycle_override(text, text, text, boolean, text, text, bigint);

CREATE PROCEDURE feature.author_lifecycle_override(IN p_feature_id uuid, IN p_source_lifecycle_state text, IN p_override_lifecycle_state text, IN p_prevent_provider_reactivation boolean, IN p_reason text, IN p_principal text, IN p_expected_row_revision bigint, OUT o_row_revision bigint)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog'
    AS $$
DECLARE
    v_current feature.features%ROWTYPE;
BEGIN
    IF p_source_lifecycle_state NOT IN ('active', 'retired')
       OR p_override_lifecycle_state NOT IN ('active', 'retired')
       OR p_prevent_provider_reactivation IS NULL
       OR p_expected_row_revision IS NULL OR p_expected_row_revision < 1
       OR coalesce(btrim(p_reason), '') = ''
       OR coalesce(btrim(p_principal), '') = '' THEN
        RAISE EXCEPTION 'lifecycle override has invalid typed arguments'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_lifecycle_override_command';
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
    -- A lifecycle override can only describe the tuple that is currently
    -- authoritative.  In particular a caller cannot pre-authorize a future
    -- provider reactivation by choosing an arbitrary override value.
    IF v_current.lifecycle_state <> p_override_lifecycle_state THEN
        RAISE EXCEPTION 'lifecycle override value must equal the current lifecycle state'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_lifecycle_override_command';
    END IF;

    -- ``source_value`` is evidence, never caller-authored history.  It is
    -- either the currently observed lifecycle (for an existing retired
    -- feature) or the ``from`` side of the exact audited state transition
    -- which produced ``p_expected_row_revision``.  The latter is what allows
    -- an active -> retired lifecycle command to retain its authoritative
    -- source state without opening a generic override write boundary.
    IF p_source_lifecycle_state <> v_current.lifecycle_state
       AND NOT EXISTS (
            SELECT 1
            FROM feature.feature_state_transitions AS transition
            WHERE transition.feature_id = p_feature_id
              AND transition.row_revision = p_expected_row_revision
              AND transition.from_lifecycle_state = p_source_lifecycle_state
              AND transition.to_lifecycle_state = v_current.lifecycle_state
       ) THEN
        RAISE EXCEPTION 'lifecycle override source must match current state or exact audited transition'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_lifecycle_override_command';
    END IF;

    INSERT INTO ops.feature_overrides (
        feature_id, source_record_key, field_path,
        source_value, override_value, prevent_provider_reactivation,
        status, reason, created_by
    ) VALUES (
        p_feature_id, NULL, 'lifecycle_state',
        to_jsonb(p_source_lifecycle_state), to_jsonb(p_override_lifecycle_state),
        p_prevent_provider_reactivation,
        'active', btrim(p_reason), btrim(p_principal)
    ) ON CONFLICT (feature_id, field_path) WHERE status = 'active'
    DO UPDATE SET
        source_value = EXCLUDED.source_value,
        override_value = EXCLUDED.override_value,
        prevent_provider_reactivation = EXCLUDED.prevent_provider_reactivation,
        reason = EXCLUDED.reason,
        created_by = EXCLUDED.created_by,
        created_at = clock_timestamp();

    o_row_revision := v_current.row_revision;
END;
$$;

ALTER PROCEDURE feature.author_lifecycle_override(IN p_feature_id uuid, IN p_source_lifecycle_state text, IN p_override_lifecycle_state text, IN p_prevent_provider_reactivation boolean, IN p_reason text, IN p_principal text, IN p_expected_row_revision bigint, OUT o_row_revision bigint) OWNER TO ktm_feature_state_procedure_owner;

REVOKE ALL ON PROCEDURE feature.author_lifecycle_override(uuid, text, text, boolean, text, text, bigint) FROM PUBLIC;
GRANT EXECUTE ON PROCEDURE feature.author_lifecycle_override(uuid, text, text, boolean, text, text, bigint) TO ktm_feature_runtime;

SET ROLE ktm_feature_schema_owner;
