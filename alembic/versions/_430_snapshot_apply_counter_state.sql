-- caller가 kernel begin과 executor fence를 통과한 같은 TX의 작은 계측이다.
CREATE FUNCTION ops.provider_snapshot_scalar_counter_state(
    p_snapshot uuid,p_generation bigint,p_fence uuid,p_items jsonb
) RETURNS TABLE(feature_id uuid,row_revision bigint,record_exists boolean)
LANGUAGE plpgsql SECURITY DEFINER SET search_path TO pg_catalog AS $$
DECLARE
    v_control ops.provider_snapshot_controls%ROWTYPE;
    v_attempt ops.feature_write_attempts%ROWTYPE;
    v_item jsonb;
    v_count integer;
BEGIN
    IF p_items IS NULL OR jsonb_typeof(p_items) IS DISTINCT FROM 'array'
       OR pg_column_size(p_items)>1048576 THEN
        RAISE EXCEPTION 'bounded scalar counter items required' USING ERRCODE='22023';
    END IF;
    v_count:=jsonb_array_length(p_items);
    IF v_count NOT BETWEEN 1 AND 2730 THEN
        RAISE EXCEPTION 'scalar counter item budget exceeded' USING ERRCODE='22023';
    END IF;
    FOR v_item IN SELECT value FROM jsonb_array_elements(p_items) LOOP
        IF jsonb_typeof(v_item) IS DISTINCT FROM 'object' THEN
            RAISE EXCEPTION 'invalid scalar counter item' USING ERRCODE='22023';
        END IF;
        IF (SELECT count(*) FROM jsonb_object_keys(v_item))<>3
           OR NOT (v_item ?& ARRAY['feature_id','source_entity_key','raw_payload_hash'])
           OR jsonb_typeof(v_item->'feature_id') IS DISTINCT FROM 'string'
           OR jsonb_typeof(v_item->'source_entity_key') IS DISTINCT FROM 'string'
           OR jsonb_typeof(v_item->'raw_payload_hash') IS DISTINCT FROM 'string'
           OR v_item->>'feature_id' !~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
           OR v_item->>'source_entity_key' !~ '^se_[0-9a-f]{64}$'
           OR v_item->>'raw_payload_hash' !~ '^[0-9a-f]{32}$' THEN
            RAISE EXCEPTION 'invalid scalar counter key' USING ERRCODE='22023';
        END IF;
    END LOOP;
    IF (SELECT count(DISTINCT value->>'feature_id') FROM jsonb_array_elements(p_items))<>v_count
       OR (SELECT count(DISTINCT value->>'source_entity_key') FROM jsonb_array_elements(p_items))<>v_count THEN
        RAISE EXCEPTION 'duplicate scalar counter item' USING ERRCODE='22023';
    END IF;
    v_control:=ops._lock_provider_snapshot_executor(p_snapshot,p_generation,p_fence);
    IF v_control.status<>'prepared' OR v_control.attempt_id IS NULL THEN
        RAISE EXCEPTION 'scalar counter requires prepared snapshot' USING ERRCODE='23514';
    END IF;
    SELECT * INTO STRICT v_attempt FROM ops.feature_write_attempts attempt
      WHERE attempt.attempt_id=v_control.attempt_id;
    IF v_attempt.status<>'applying' OR v_attempt.apply_txid IS DISTINCT FROM txid_current()
       OR v_attempt.owner IS DISTINCT FROM v_control.attempt_owner
       OR v_attempt.manifest_digest IS DISTINCT FROM v_control.manifest_digest THEN
        RAISE EXCEPTION 'scalar counter requires the original apply transaction' USING ERRCODE='23514';
    END IF;
    IF EXISTS(
        SELECT 1 FROM jsonb_array_elements(p_items) item
        WHERE NOT EXISTS(SELECT 1 FROM ops.feature_write_manifests m
                         WHERE m.attempt_id=v_attempt.attempt_id AND m.dependency_kind='feature'
                           AND m.dependency_key=item->>'feature_id')
           OR NOT EXISTS(SELECT 1 FROM ops.feature_write_manifests m
                         WHERE m.attempt_id=v_attempt.attempt_id AND m.dependency_kind='source_head'
                           AND m.dependency_key=item->>'source_entity_key')
           OR NOT EXISTS(SELECT 1 FROM provider_sync.source_entities e
                         JOIN provider_sync.source_links l ON l.source_entity_key=e.source_entity_key
                         WHERE e.source_entity_key=item->>'source_entity_key'
                           AND e.provider_dataset_id=v_attempt.provider_dataset_id
                           AND l.feature_id=(item->>'feature_id')::uuid AND l.source_role='primary')
    ) THEN
        RAISE EXCEPTION 'scalar counter items differ from the locked manifest' USING ERRCODE='23514';
    END IF;
    RETURN QUERY SELECT f.feature_id,f.row_revision,
        EXISTS(SELECT 1 FROM provider_sync.source_records r
               WHERE r.source_entity_key=item->>'source_entity_key'
                 AND r.raw_payload_hash=item->>'raw_payload_hash')
      FROM jsonb_array_elements(p_items) item
      JOIN feature.features f ON f.feature_id=(item->>'feature_id')::uuid
      ORDER BY f.feature_id;
END;
$$;
