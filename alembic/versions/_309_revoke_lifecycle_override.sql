SET ROLE ktm_feature_state_procedure_owner;

DROP PROCEDURE feature.revoke_lifecycle_override(text, text, bigint);

CREATE PROCEDURE feature.revoke_lifecycle_override(IN p_feature_id uuid, IN p_principal text, IN p_expected_row_revision bigint, OUT o_row_revision bigint)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog'
    AS $$
DECLARE
    v_current feature.features%ROWTYPE;
BEGIN
    IF coalesce(btrim(p_principal), '') = ''
       OR p_expected_row_revision IS NULL OR p_expected_row_revision < 1 THEN
        RAISE EXCEPTION 'lifecycle override revoke has invalid typed arguments'
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

    UPDATE ops.feature_overrides
       SET status = 'superseded',
           created_by = btrim(p_principal),
           created_at = clock_timestamp()
     WHERE feature_id = p_feature_id
       AND field_path = 'lifecycle_state'
       AND status = 'active';
    IF NOT FOUND THEN
        RAISE EXCEPTION 'feature % has no active lifecycle override', p_feature_id
            USING ERRCODE = 'P0002';
    END IF;
    o_row_revision := v_current.row_revision;
END;
$$;

ALTER PROCEDURE feature.revoke_lifecycle_override(IN p_feature_id uuid, IN p_principal text, IN p_expected_row_revision bigint, OUT o_row_revision bigint) OWNER TO ktm_feature_state_procedure_owner;

REVOKE ALL ON PROCEDURE feature.revoke_lifecycle_override(uuid, text, bigint) FROM PUBLIC;
GRANT EXECUTE ON PROCEDURE feature.revoke_lifecycle_override(uuid, text, bigint) TO ktm_feature_runtime;

SET ROLE ktm_feature_schema_owner;
