CREATE OR REPLACE FUNCTION feature.list_manual_provider_dedup_cases(p_status text, p_after_created_at timestamp with time zone, p_after_case_id uuid, p_limit integer) RETURNS TABLE(o_case_id uuid, o_status text, o_created_at timestamp with time zone, o_evidence_fingerprint text, o_manual_feature jsonb, o_provider_feature jsonb, o_scores jsonb)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'feature', 'ops'
    AS $$
BEGIN
    IF session_user <> 'ktm_feature_api_runtime'
       OR NOT pg_has_role(
           session_user, 'ktm_manual_provider_dedup_admin_executor', 'member'
       ) THEN
        RAISE EXCEPTION 'manual/provider dedup case read requires the admin-only executor'
            USING ERRCODE = '42501', CONSTRAINT = 'ck_m05_case_read_executor';
    END IF;
    IF p_status NOT IN ('pending', 'terminal') AND p_status IS NOT NULL
       OR p_limit IS NULL OR p_limit < 1 OR p_limit > 100
       OR (p_after_created_at IS NULL) <> (p_after_case_id IS NULL) THEN
        RAISE EXCEPTION 'manual/provider dedup case list input is invalid'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_m05_case_read_input';
    END IF;

    RETURN QUERY
    SELECT
        candidate.case_id,
        CASE WHEN resolution.case_id IS NULL THEN 'pending' ELSE 'terminal' END,
        candidate.created_at,
        candidate.evidence_fingerprint,
        jsonb_build_object(
            'feature_id', candidate.manual_feature_id,
            'feature_uuid', CAST(candidate.manual_feature_id AS text),
            'row_revision', candidate.manual_feature_row_revision,
            'snapshot', candidate.manual_feature_snapshot
        ),
        jsonb_build_object(
            'feature_id', candidate.provider_feature_id,
            'feature_uuid', CAST(candidate.provider_feature_id AS text),
            'row_revision', candidate.provider_feature_row_revision,
            'snapshot', candidate.provider_feature_snapshot
        ),
        jsonb_build_object(
            'scorer_id', candidate.scorer_id,
            'scorer_input_sha256', candidate.scorer_input_sha256,
            'name_score', candidate.name_score,
            'spatial_score', candidate.spatial_score,
            'category_score', candidate.category_score,
            'total_score', candidate.total_score,
            'distance_meters', candidate.distance_meters
        )
    FROM ops.manual_provider_dedup_cases AS candidate
    LEFT JOIN ops.manual_provider_dedup_resolutions AS resolution
      ON resolution.case_id = candidate.case_id
    WHERE (
        (p_status IS NULL)
        OR (p_status = 'pending' AND resolution.case_id IS NULL)
        OR (p_status = 'terminal' AND resolution.case_id IS NOT NULL)
    )
      AND (
          p_after_created_at IS NULL
          OR (candidate.created_at, candidate.case_id) < (p_after_created_at, p_after_case_id)
      )
    ORDER BY candidate.created_at DESC, candidate.case_id DESC
    LIMIT p_limit;
END
$$;
