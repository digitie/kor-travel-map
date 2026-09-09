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

DO $t39_owner$
DECLARE
    had_create boolean;
BEGIN
    -- 소유권 이전은 새 소유자가 담는 스키마의 CREATE 권한을 요구한다.
    -- 302_m03_child_issuance.py:324-330이 `ops`에서 같은 함정을 만났다. 다만 그
    -- 형태는 이미 CREATE를 가진 롤에서 권한을 빼앗으므로, 여기서는 **자기 상태를
    -- 보고** 되돌린다. 2026-09-09 n150 첫 실행이 이것을 잡았다
    -- (`permission denied for schema ops`).
    had_create := has_schema_privilege('ktm_manual_feature_procedure_owner', 'feature', 'CREATE');
    IF NOT had_create THEN
        EXECUTE 'GRANT CREATE ON SCHEMA feature TO ktm_manual_feature_procedure_owner';
    END IF;
    EXECUTE 'ALTER FUNCTION feature.read_admin_manual_feature_provenance(p_feature_id uuid) OWNER TO ktm_manual_feature_procedure_owner';
    IF NOT had_create THEN
        EXECUTE 'REVOKE CREATE ON SCHEMA feature FROM ktm_manual_feature_procedure_owner';
    END IF;
END
$t39_owner$;
