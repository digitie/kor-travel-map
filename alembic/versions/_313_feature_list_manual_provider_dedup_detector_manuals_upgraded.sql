CREATE OR REPLACE FUNCTION feature.list_manual_provider_dedup_detector_manuals(
    p_after text DEFAULT NULL,
    p_limit integer DEFAULT 1000
) RETURNS TABLE (
    feature_id text,
    name text,
    category text,
    lon double precision,
    lat double precision
)
    LANGUAGE plpgsql STABLE SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'feature', 'ops', 'x_extension'
    AS $$
BEGIN
    IF session_user <> 'ktm_feature_service'
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
    RETURN QUERY
    SELECT f.feature_id::text, f.name::text, f.category::text,
           ST_X(f.coord) AS lon, ST_Y(f.coord) AS lat
    FROM feature.features AS f
    JOIN feature.feature_creation_origins AS o ON o.feature_id = f.feature_uuid
    WHERE o.origin_kind IN ('manual_admin', 'manual_curation', 'manual_request')
      AND EXISTS (
          SELECT 1 FROM feature.manual_feature_identity_claims AS c
          WHERE c.feature_id = f.feature_uuid
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
