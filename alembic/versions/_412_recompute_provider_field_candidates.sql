CREATE PROCEDURE feature.recompute_provider_field_candidates(
    IN p_attempt uuid,IN p_feature uuid,IN p_policy_revision bigint)
LANGUAGE plpgsql SECURITY DEFINER SET search_path TO pg_catalog AS $$
BEGIN
    PERFORM feature.assert_scoped_candidate_write(p_attempt,p_feature);
    IF NOT EXISTS (SELECT 1 FROM feature.provider_field_active_policies
        WHERE feature_id=p_feature AND policy_revision=p_policy_revision) THEN
        RAISE EXCEPTION 'active scalar revision changed; replan' USING ERRCODE='40001';
    END IF;
    PERFORM feature._project_provider_field_candidates(p_feature);
END;
$$;
