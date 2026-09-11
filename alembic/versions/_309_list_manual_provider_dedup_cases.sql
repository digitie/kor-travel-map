-- 이 사이드카는 자기 역할 창을 스스로 연다 — 소유자는 alembic/head-schema.sql이
-- 정본이다. 바깥에서 `SET ROLE`로 묶으면 순서에 결박되고, 자기 창을 가진 사이드카가
-- 끝에서 스키마 소유자로 되돌리는 순간 뒤따르는 파일이 엉뚱한 롤로 실행된다.
-- 이 파일은 소유권을 바꾸지 않으므로 `ALTER ... OWNER TO`가 없다. 그래도 `CREATE OR
-- REPLACE`와 `DROP`은 소유자만 할 수 있고 롤은 NOINHERIT라 창이 필요하다.
SET ROLE ktm_manual_provider_dedup_procedure_owner;

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

SET ROLE ktm_feature_schema_owner;
