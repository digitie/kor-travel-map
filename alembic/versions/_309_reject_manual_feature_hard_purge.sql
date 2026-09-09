CREATE OR REPLACE FUNCTION feature.reject_manual_feature_hard_purge() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog'
    AS $$
DECLARE
    v_claim feature.manual_feature_identity_claims%ROWTYPE;
BEGIN
    SELECT * INTO v_claim
    FROM feature.manual_feature_identity_claims AS claim
    WHERE claim.feature_id = OLD.feature_id;
    IF NOT FOUND THEN
        RETURN OLD;
    END IF;
    IF v_claim.purged_by_command_id IS NULL THEN
        RAISE EXCEPTION 'manual Feature delete needs an authorised purge command'
            USING ERRCODE = '23514',
                CONSTRAINT = 'ck_manual_feature_purge_unauthorised';
    END IF;
    RETURN OLD;
END
$$;


ALTER FUNCTION feature.reject_manual_feature_hard_purge() OWNER TO ktm_manual_feature_procedure_owner;
