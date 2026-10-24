CREATE FUNCTION feature._provider_field_projection_dependency_active(p_relation text,p_key text)
RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path TO pg_catalog AS $$
    SELECT CASE
      WHEN p_relation IN ('source_entities','source_entity_heads') THEN EXISTS (
        SELECT 1 FROM provider_sync.source_links link
        JOIN feature.provider_field_active_policies active USING(feature_id)
        WHERE link.source_entity_key=p_key)
      WHEN p_relation='provider_datasets' THEN EXISTS (
        SELECT 1 FROM provider_sync.source_entities entity
        JOIN provider_sync.source_links link USING(source_entity_key)
        JOIN feature.provider_field_active_policies active USING(feature_id)
        WHERE entity.provider_dataset_id=p_key::bigint)
      ELSE EXISTS (SELECT 1 FROM feature.provider_field_active_policies WHERE feature_id=p_key::uuid)
    END;
$$;
