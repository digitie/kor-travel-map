CREATE FUNCTION feature.assert_scoped_provider_scalar_target(
    p_attempt uuid,p_feature uuid,p_dataset bigint,p_entity text,p_revision bigint
) RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path TO pg_catalog AS $$
BEGIN
    PERFORM feature.assert_scoped_candidate_write(p_attempt,p_feature);
    IF NOT EXISTS (SELECT 1 FROM feature.provider_field_active_policies active
        WHERE active.feature_id=p_feature AND active.policy_revision=p_revision) THEN
        RAISE EXCEPTION 'active scalar revision changed; replan' USING ERRCODE='40001';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM ops.feature_write_attempts attempt
        JOIN provider_sync.provider_datasets dataset ON dataset.provider_dataset_id=attempt.provider_dataset_id
        JOIN provider_sync.source_entities entity ON entity.provider_dataset_id=dataset.provider_dataset_id
        JOIN provider_sync.source_links link ON link.source_entity_key=entity.source_entity_key
        JOIN provider_sync.source_entity_heads head ON head.source_entity_key=entity.source_entity_key
        WHERE attempt.attempt_id=p_attempt AND attempt.provider_dataset_id=p_dataset
          AND dataset.is_active AND entity.source_entity_key=p_entity
          AND link.feature_id=p_feature AND link.source_role='primary'
          AND head.current_source_record_key IS NOT NULL AND head.expires_at IS NULL) THEN
        RAISE EXCEPTION 'scalar target is outside the applying dataset or existing primary source' USING ERRCODE='23514';
    END IF;
END;
$$;
