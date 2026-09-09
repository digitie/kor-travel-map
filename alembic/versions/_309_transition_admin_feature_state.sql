SET ROLE ktm_feature_state_procedure_owner;

DROP PROCEDURE feature.transition_admin_feature_state(text, text, text, text, bigint, text, text, text);

CREATE PROCEDURE feature.transition_admin_feature_state(IN p_feature_id uuid, IN p_lifecycle_state text, IN p_publication_state text, IN p_quality_state text, IN p_expected_row_revision bigint, IN p_reason_code text, IN p_principal text, IN p_action text, OUT o_feature_id uuid, OUT o_row_revision bigint, OUT o_transition_id bigint)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog'
    AS $$
DECLARE
    v_current feature.features%ROWTYPE;
    v_lifecycle_state text;
    v_publication_state text;
    v_quality_state text;
BEGIN
    IF p_action NOT IN ('patch', 'retire')
       OR p_expected_row_revision IS NULL OR p_expected_row_revision < 1
       OR coalesce(btrim(p_reason_code), '') = ''
       OR coalesce(btrim(p_principal), '') = '' THEN
        RAISE EXCEPTION 'admin state command has invalid arguments'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_admin_state_command';
    END IF;
    SELECT * INTO v_current FROM feature.features
     WHERE feature_id = p_feature_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'feature % does not exist', p_feature_id USING ERRCODE = 'P0002';
    END IF;
    IF v_current.row_revision <> p_expected_row_revision THEN
        RAISE EXCEPTION 'feature % revision changed', p_feature_id USING ERRCODE = '40001';
    END IF;
    IF p_action = 'patch' THEN
        IF p_lifecycle_state IS NOT NULL
           OR (p_publication_state IS NULL AND p_quality_state IS NULL)
           OR (p_publication_state IS NOT NULL
               AND p_publication_state NOT IN ('draft', 'published', 'suppressed'))
           OR (p_quality_state IS NOT NULL
               AND p_quality_state NOT IN ('valid', 'quarantined')) THEN
            RAISE EXCEPTION 'admin state patch may change only publication or quality'
                USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_admin_state_command';
        END IF;
        v_lifecycle_state := v_current.lifecycle_state;
        v_publication_state := coalesce(p_publication_state, v_current.publication_state);
        v_quality_state := coalesce(p_quality_state, v_current.quality_state);
    ELSE
        IF p_lifecycle_state IS NOT NULL
           OR p_publication_state IS NOT NULL
           OR p_quality_state IS NOT NULL THEN
            RAISE EXCEPTION 'retire action derives its complete state tuple'
                USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_admin_state_command';
        END IF;
        v_lifecycle_state := 'retired';
        v_publication_state := 'suppressed';
        v_quality_state := v_current.quality_state;
    END IF;
    CALL feature.transition_feature_state(
        p_feature_id, v_lifecycle_state, v_publication_state, v_quality_state,
        p_expected_row_revision,
        jsonb_build_object(
            'transition_kind', 'admin',
            'reason_code', btrim(p_reason_code),
            'principal', btrim(p_principal)
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
    ORDER BY transition.transition_id DESC
    LIMIT 1;
    IF o_transition_id IS NULL THEN
        RAISE EXCEPTION 'admin state command did not write its audit transition';
    END IF;
END;
$$;

ALTER PROCEDURE feature.transition_admin_feature_state(IN p_feature_id uuid, IN p_lifecycle_state text, IN p_publication_state text, IN p_quality_state text, IN p_expected_row_revision bigint, IN p_reason_code text, IN p_principal text, IN p_action text, OUT o_feature_id uuid, OUT o_row_revision bigint, OUT o_transition_id bigint) OWNER TO ktm_feature_state_procedure_owner;

REVOKE ALL ON PROCEDURE feature.transition_admin_feature_state(IN p_feature_id uuid, IN p_lifecycle_state text, IN p_publication_state text, IN p_quality_state text, IN p_expected_row_revision bigint, IN p_reason_code text, IN p_principal text, IN p_action text, OUT o_feature_id uuid, OUT o_row_revision bigint, OUT o_transition_id bigint) FROM PUBLIC;
GRANT ALL ON PROCEDURE feature.transition_admin_feature_state(IN p_feature_id uuid, IN p_lifecycle_state text, IN p_publication_state text, IN p_quality_state text, IN p_expected_row_revision bigint, IN p_reason_code text, IN p_principal text, IN p_action text, OUT o_feature_id uuid, OUT o_row_revision bigint, OUT o_transition_id bigint) TO ktm_feature_runtime;
GRANT ALL ON PROCEDURE feature.transition_admin_feature_state(IN p_feature_id uuid, IN p_lifecycle_state text, IN p_publication_state text, IN p_quality_state text, IN p_expected_row_revision bigint, IN p_reason_code text, IN p_principal text, IN p_action text, OUT o_feature_id uuid, OUT o_row_revision bigint, OUT o_transition_id bigint) TO ktm_manual_provider_dedup_procedure_owner;

SET ROLE ktm_feature_schema_owner;
