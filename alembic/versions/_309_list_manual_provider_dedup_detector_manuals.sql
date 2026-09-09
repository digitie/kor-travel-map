DROP FUNCTION feature.list_manual_provider_dedup_detector_manuals(text, integer);

CREATE FUNCTION feature.list_manual_provider_dedup_detector_manuals(p_after uuid DEFAULT NULL::uuid, p_limit integer DEFAULT 1000) RETURNS TABLE(feature_id uuid, name text, category text, lon double precision, lat double precision)
    LANGUAGE plpgsql STABLE SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'feature', 'ops', 'x_extension'
    AS $$
BEGIN
    IF session_user <> 'ktm_feature_dagster_runtime'
       OR NOT pg_has_role(session_user, 'ktm_manual_provider_dedup_detector_executor', 'member')
       OR pg_has_role(session_user, 'ktm_manual_provider_dedup_admin_executor', 'member')
       OR pg_has_role(session_user, 'ktm_feature_reference_reconciliation_service_executor', 'member') THEN
        RAISE EXCEPTION 'manual/provider dedup detector requires the Dagster-only executor'
            USING ERRCODE = '42501', CONSTRAINT = 'ck_m05_detector_manuals_executor';
    END IF;
    IF p_limit IS NULL OR p_limit < 1 OR p_limit > 10000 THEN
        RAISE EXCEPTION 'manual/provider dedup detector page size is outside its canonical range'
            USING ERRCODE = '22023', CONSTRAINT = 'ck_m05_detector_manuals_limit';
    END IF;
    -- `feature.features`의 `name`·`category`는 `character varying`이다. RETURNS
    -- TABLE이 `text`이므로 명시 캐스트가 없으면 42804(structure of query does not
    -- match function result type)로 죽는다 — n150 실측으로 잡았다. `feature_id`는
    -- T-VN-39 재키로 uuid이고 RETURNS TABLE도 uuid이므로 캐스트를 두지 않는다.
    RETURN QUERY
    SELECT f.feature_id, f.name::text, f.category::text,
           ST_X(f.coord) AS lon, ST_Y(f.coord) AS lat
    FROM feature.features AS f
    JOIN feature.feature_creation_origins AS o ON o.feature_id = f.feature_id
    WHERE o.origin_kind IN ('manual_admin', 'manual_curation', 'manual_request')
      AND EXISTS (
          SELECT 1 FROM feature.manual_feature_identity_claims AS c
          WHERE c.feature_id = f.feature_id
            AND c.claimed_by_command_id = o.creation_command_id
      )
      AND f.lifecycle_state = 'active'
      AND f.publication_state = 'published'
      AND f.quality_state = 'valid'
      AND f.coord IS NOT NULL
      AND (p_after IS NULL OR f.feature_id > p_after)
    ORDER BY f.feature_id
    LIMIT p_limit;
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
    had_create := has_schema_privilege('ktm_manual_provider_dedup_procedure_owner', 'feature', 'CREATE');
    IF NOT had_create THEN
        EXECUTE 'GRANT CREATE ON SCHEMA feature TO ktm_manual_provider_dedup_procedure_owner';
    END IF;
    EXECUTE 'ALTER FUNCTION feature.list_manual_provider_dedup_detector_manuals(p_after uuid, p_limit integer) OWNER TO ktm_manual_provider_dedup_procedure_owner';
    IF NOT had_create THEN
        EXECUTE 'REVOKE CREATE ON SCHEMA feature FROM ktm_manual_provider_dedup_procedure_owner';
    END IF;
END
$t39_owner$;

REVOKE ALL ON FUNCTION feature.list_manual_provider_dedup_detector_manuals(p_after uuid, p_limit integer) FROM PUBLIC, ktm_feature_runtime, ktm_feature_api_runtime, ktm_feature_dagster_runtime, ktm_manual_provider_dedup_admin_executor, ktm_feature_reference_reconciliation_service_executor;
GRANT EXECUTE ON FUNCTION feature.list_manual_provider_dedup_detector_manuals(p_after uuid, p_limit integer) TO ktm_manual_provider_dedup_detector_executor;
