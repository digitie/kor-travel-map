DROP FUNCTION feature.read_admin_manual_feature_provenance(uuid);

CREATE FUNCTION feature.read_admin_manual_feature_provenance(p_feature_id uuid) RETURNS TABLE(feature_id uuid, feature_kind text, name_key text, lon_e6 integer, lat_e6 integer, claim_basis text, claimed_at timestamp with time zone, claimed_by_command_id bigint, origin_kind text, creation_command_id bigint, creator_principal_id text, created_by_actor text, origin_created_at timestamp with time zone, invoker_role text, procedure_definer text)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog'
    AS $$
BEGIN
    IF p_feature_id IS NULL THEN
        RAISE EXCEPTION 'manual Feature provenance requires a canonical UUID'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_manual_feature_provenance_input';
    END IF;

    -- ``features``를 driving relation으로 고정한다. purge 뒤 evidence는 남아도
    -- 일반 admin detail/read route로 그 snapshot을 탐색할 수 없다.
    RETURN QUERY
    SELECT
        core.feature_id,
        claim.feature_kind,
        claim.name_key,
        claim.lon_e6,
        claim.lat_e6,
        claim.claim_basis,
        claim.claimed_at,
        claim.claimed_by_command_id,
        origin.origin_kind,
        origin.creation_command_id,
        origin.creator_principal_id,
        origin.created_by_actor,
        origin.created_at,
        origin.invoker_role,
        origin.procedure_definer
    FROM feature.features AS core
    LEFT JOIN feature.manual_feature_identity_claims AS claim
      ON claim.feature_id = core.feature_id
    LEFT JOIN feature.feature_creation_origins AS origin
      ON origin.feature_id = claim.feature_id
     AND origin.creation_command_id = claim.claimed_by_command_id
    WHERE core.feature_id = p_feature_id;
END
$$;

ALTER FUNCTION feature.read_admin_manual_feature_provenance(p_feature_id uuid) OWNER TO ktm_manual_feature_procedure_owner;
