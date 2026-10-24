CREATE FUNCTION ops._lock_scoped_feature_write_scope(p_dataset bigint, p_regions jsonb, p_exclusive boolean)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path TO pg_catalog AS $$
DECLARE v_region jsonb;
BEGIN
    PERFORM ops._arm_scoped_feature_write_deadline();
    PERFORM ops.lock_scoped_feature_write_protocol(p_exclusive);
    INSERT INTO ops.feature_write_dataset_scopes(provider_dataset_id) VALUES(p_dataset)
        ON CONFLICT DO NOTHING;
    IF jsonb_array_length(p_regions)=0 THEN
        PERFORM 1 FROM ops.feature_write_dataset_scopes WHERE provider_dataset_id=p_dataset FOR UPDATE;
    ELSE
        PERFORM 1 FROM ops.feature_write_dataset_scopes WHERE provider_dataset_id=p_dataset FOR SHARE;
    END IF;
    IF NOT FOUND THEN RAISE EXCEPTION 'scope is not visible; replan' USING ERRCODE='40001'; END IF;
    FOR v_region IN SELECT value FROM jsonb_array_elements(p_regions) LOOP
        INSERT INTO ops.feature_write_region_scopes(provider_dataset_id,scope_version,region_key)
            VALUES(p_dataset,(v_region->>'scope_version')::integer,v_region->>'region_key') ON CONFLICT DO NOTHING;
        PERFORM 1 FROM ops.feature_write_region_scopes WHERE provider_dataset_id=p_dataset
            AND scope_version=(v_region->>'scope_version')::integer AND region_key=v_region->>'region_key' FOR UPDATE;
        IF NOT FOUND THEN RAISE EXCEPTION 'region is not visible; replan' USING ERRCODE='40001'; END IF;
    END LOOP;
END;
$$;
