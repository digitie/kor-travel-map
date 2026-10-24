CREATE FUNCTION feature.validate_exclusive_provider_snapshot(p_attempt uuid,p_dataset bigint,p_targets jsonb,p_entities text[])
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path TO pg_catalog AS $$
DECLARE v_attempt ops.feature_write_attempts%ROWTYPE; v_target record; v_result jsonb:='{}';
    v_actual uuid[]; v_wanted uuid[]; v_count bigint;
BEGIN
    IF p_dataset IS NULL OR cardinality(p_entities) NOT BETWEEN 1 AND 2730
       OR p_entities IS NULL OR pg_column_size(p_entities)>1048576
       OR (p_attempt IS NOT NULL AND (jsonb_typeof(p_targets) IS DISTINCT FROM 'object'
           OR pg_column_size(p_targets)>1048576)) THEN
        RAISE EXCEPTION 'invalid bounded full refresh selection' USING ERRCODE='23514';
    END IF;
    IF EXISTS (SELECT 1 FROM provider_sync.source_entities
        WHERE source_entity_key=ANY(p_entities) AND provider_dataset_id<>p_dataset) THEN
        RAISE EXCEPTION 'full snapshot contains another dataset' USING ERRCODE='23514';
    END IF;
    IF p_attempt IS NOT NULL THEN
    SELECT * INTO STRICT v_attempt FROM ops.feature_write_attempts WHERE attempt_id=p_attempt;
    IF NOT v_attempt.exclusive_protocol OR v_attempt.provider_dataset_id<>p_dataset
       OR v_attempt.idempotency_key<>'native-full-refresh-v1:'||v_attempt.input_digest||':'||replace(v_attempt.attempt_id::text,'-','')
       OR v_attempt.status NOT IN ('applying','completed') THEN
        RAISE EXCEPTION 'not an explicit exclusive full refresh' USING ERRCODE='23514';
    END IF;
    END IF;
    SELECT array_agg(feature_id ORDER BY feature_id) INTO v_actual FROM (
        SELECT DISTINCT a.feature_id FROM feature.provider_field_active_policies a
        JOIN provider_sync.source_links l USING(feature_id)
        WHERE l.source_entity_key=ANY(p_entities) LIMIT 2731
    ) bounded_targets;
    IF cardinality(v_actual)>2730 THEN
        RAISE EXCEPTION 'too many active targets' USING ERRCODE='23514';
    END IF;
    SELECT array_agg(key::uuid ORDER BY key::uuid) INTO v_wanted FROM jsonb_each(p_targets);
    IF p_attempt IS NOT NULL AND (v_actual IS DISTINCT FROM v_wanted OR v_wanted IS NULL) THEN
        RAISE EXCEPTION 'full refresh active target set changed' USING ERRCODE='40001';
    END IF;
    FOR v_target IN SELECT a.*,f.kind FROM feature.provider_field_active_policies a
        JOIN feature.features f USING(feature_id) WHERE a.feature_id=ANY(v_actual) ORDER BY a.feature_id LOOP
        IF v_target.kind<>'place' OR (p_attempt IS NOT NULL AND
            (p_targets->>v_target.feature_id::text)::bigint<>v_target.policy_revision) THEN
            RAISE EXCEPTION 'active target revision or kind changed' USING ERRCODE='40001';
        END IF;
        IF EXISTS (SELECT 1 FROM provider_sync.source_links l
            JOIN provider_sync.source_links other USING(source_entity_key)
            WHERE l.feature_id=v_target.feature_id AND other.feature_id<>l.feature_id) THEN
            RAISE EXCEPTION 'shared active entity is unsupported, including retired area' USING ERRCODE='23514';
        END IF;
        IF v_attempt.status='applying' AND NOT feature._exclusive_provider_refresh_context(v_target.feature_id,p_dataset) THEN
            RAISE EXCEPTION 'full refresh target lacks applying context' USING ERRCODE='23514';
        END IF;
        v_result:=v_result||jsonb_build_object(v_target.feature_id::text,
            jsonb_build_array(v_target.policy_revision,to_jsonb(v_target.field_paths)));
    END LOOP;
    IF p_attempt IS NOT NULL AND v_attempt.status='applying' THEN
        SELECT count(*) INTO v_count FROM (SELECT DISTINCT source_entity_key
            FROM provider_sync.source_links WHERE feature_id=ANY(v_actual) LIMIT 8193) heads;
        IF v_count+2*cardinality(v_actual)>8192
           OR v_attempt.expected_members<>v_count+2*cardinality(v_actual) THEN
            RAISE EXCEPTION 'full refresh requires exact active closure' USING ERRCODE='23514';
        END IF;
    END IF;
    RETURN v_result;
END;
$$;
