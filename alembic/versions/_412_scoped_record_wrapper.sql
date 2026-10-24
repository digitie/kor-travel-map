CREATE PROCEDURE feature.record_scoped_provider_field_candidates(
    IN p_attempt uuid, IN p_feature_id uuid, IN p_provider_dataset_id bigint,
    IN p_source_entity_key text, IN p_source_record_key text,
    IN p_policy_revision bigint, IN p_normalizer_revision text, IN p_presence_proven boolean,
    IN p_values jsonb, IN p_geometry_wkt jsonb,
    OUT o_field_count integer, OUT o_unresolved_count integer
)
LANGUAGE plpgsql SECURITY DEFINER SET search_path TO pg_catalog AS $$
BEGIN
    IF p_attempt IS NULL OR NOT EXISTS (SELECT 1 FROM feature.provider_field_active_policies
        WHERE feature_id=p_feature_id AND policy_revision=p_policy_revision) THEN
        RAISE EXCEPTION 'scoped capture requires the explicitly active scalar policy' USING ERRCODE='23514';
    END IF;
    CALL feature._record_provider_field_candidates(p_attempt,p_feature_id,p_provider_dataset_id,
        p_source_entity_key,p_source_record_key,p_policy_revision,p_normalizer_revision,
        p_presence_proven,p_values,p_geometry_wkt,o_field_count,o_unresolved_count);
END;
$$;
