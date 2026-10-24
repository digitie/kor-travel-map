CREATE FUNCTION feature._validate_scoped_provider_geocode_stamps(
    p_attempt uuid,p_owner uuid,p_manifest_digest text,p_input_digest text,
    p_targets jsonb,p_after_source boolean
) RETURNS bigint LANGUAGE plpgsql SECURITY DEFINER SET search_path TO pg_catalog AS $$
DECLARE v_attempt ops.feature_write_attempts%ROWTYPE; v_item jsonb; v_count bigint;
        v_sources bigint; v_feature uuid; v_stamp feature.feature_geocode_stamps%ROWTYPE;
BEGIN
    IF jsonb_typeof(p_targets) IS DISTINCT FROM 'array' OR pg_column_size(p_targets)>1048576
       OR jsonb_array_length(p_targets) NOT BETWEEN 1 AND 2730 THEN
        RAISE EXCEPTION 'invalid scoped stamp batch' USING ERRCODE='23514';
    END IF;
    v_count:=jsonb_array_length(p_targets);
    FOR v_item IN SELECT value FROM jsonb_array_elements(p_targets) LOOP
        IF jsonb_typeof(v_item) IS DISTINCT FROM 'object'
           OR (SELECT count(*) FROM jsonb_object_keys(v_item))<>8
           OR EXISTS(SELECT 1 FROM jsonb_object_keys(v_item) key WHERE key NOT IN
               ('feature_id','source_entity_key','source_record_key','policy_revision',
                'geo_version_token','geo_data_token','reverse_outcome','stamped_at'))
           OR EXISTS(SELECT 1 FROM jsonb_each(v_item) e WHERE e.key<>'policy_revision'
                     AND jsonb_typeof(e.value)<>'string')
           OR jsonb_typeof(v_item->'policy_revision') IS DISTINCT FROM 'number'
           OR NOT pg_input_is_valid(v_item->>'feature_id','uuid')
           OR NOT pg_input_is_valid(v_item->>'policy_revision','bigint')
           OR (v_item->>'policy_revision')::bigint<=0
           OR (v_item->>'source_entity_key') !~ '^se_[0-9a-f]{64}$'
           OR (v_item->>'source_record_key') !~ '^sr_[0-9a-f]{20}$'
           OR (v_item->>'geo_version_token') !~ '^dv1-[0-9a-f]{32}$'
           OR (v_item->>'geo_data_token') !~ '^dd1-[0-9a-f]{32}$'
           OR (v_item->>'reverse_outcome') NOT IN ('called','geocoded','not_called')
           OR length(v_item->>'stamped_at')>64
           OR (v_item->>'stamped_at') !~ '(Z|[+-][0-9]{2}:[0-9]{2})$'
           OR NOT pg_input_is_valid(v_item->>'stamped_at','timestamp with time zone') THEN
            RAISE EXCEPTION 'invalid scoped stamp evidence' USING ERRCODE='23514';
        END IF;
    END LOOP;
    IF (SELECT count(DISTINCT (value->>'feature_id')::uuid) FROM jsonb_array_elements(p_targets))<>v_count
       OR (SELECT count(DISTINCT value->>'source_entity_key') FROM jsonb_array_elements(p_targets))<>v_count THEN
        RAISE EXCEPTION 'duplicate scoped stamp target' USING ERRCODE='23514';
    END IF;
    IF NOT EXISTS(SELECT 1 FROM pg_locks WHERE locktype='advisory' AND pid=pg_backend_pid()
        AND classid=1369104691 AND objid=115 AND objsubid=2 AND granted AND mode='ShareLock')
       OR EXISTS(SELECT 1 FROM pg_locks WHERE locktype='advisory' AND pid=pg_backend_pid()
        AND classid=1369104691 AND objid=115 AND objsubid=2 AND granted AND mode='ExclusiveLock') THEN
        RAISE EXCEPTION 'scoped stamp requires actual shared protocol' USING ERRCODE='23514';
    END IF;
    PERFORM ops._arm_scoped_feature_write_deadline();
    PERFORM feature.lock_provider_field_policy_epoch();
    v_attempt:=ops._locked_scoped_feature_write_attempt(p_attempt,p_owner);
    IF v_attempt.status<>'applying' OR v_attempt.apply_txid IS DISTINCT FROM txid_current()
       OR v_attempt.exclusive_protocol OR v_attempt.regions<>'[]'::jsonb
       OR v_attempt.manifest_digest IS DISTINCT FROM p_manifest_digest OR p_manifest_digest IS NULL
       OR v_attempt.input_digest IS DISTINCT FROM p_input_digest OR p_input_digest IS NULL THEN
        RAISE EXCEPTION 'scoped stamp is outside the applying input' USING ERRCODE='23514';
    END IF;
    IF (SELECT count(*) FROM ops.feature_write_manifests WHERE attempt_id=p_attempt
        AND dependency_kind='feature')<>v_count OR EXISTS(
        SELECT 1 FROM jsonb_array_elements(p_targets) input WHERE NOT EXISTS(
            SELECT 1 FROM ops.feature_write_manifests m WHERE m.attempt_id=p_attempt
            AND m.dependency_kind='feature' AND m.dependency_key=(input->>'feature_id')::uuid::text)) THEN
        RAISE EXCEPTION 'scoped stamp target set is not the full manifest' USING ERRCODE='23514';
    END IF;
    SELECT count(*) INTO v_sources FROM(
        SELECT DISTINCT link.source_entity_key FROM provider_sync.source_links link
        JOIN jsonb_array_elements(p_targets) input ON link.feature_id=(input->>'feature_id')::uuid
        LIMIT 8193) bounded;
    IF v_sources>8192 OR v_attempt.expected_members<>2*v_count+v_sources
       OR (SELECT count(*) FROM ops.feature_write_manifests WHERE attempt_id=p_attempt)
          <>v_attempt.expected_members THEN
        RAISE EXCEPTION 'scoped stamp manifest closure is not exact' USING ERRCODE='23514';
    END IF;
    FOR v_item IN SELECT value FROM jsonb_array_elements(p_targets)
        ORDER BY (value->>'feature_id')::uuid LOOP
        v_feature:=(v_item->>'feature_id')::uuid;
        PERFORM feature.assert_scoped_provider_scalar_target(p_attempt,v_feature,
            v_attempt.provider_dataset_id,v_item->>'source_entity_key',
            (v_item->>'policy_revision')::bigint);
        -- existing primary place만. 퇴역 여부와 무관한 shared source 거부는 정본 assert에 있다.
        IF NOT EXISTS(SELECT 1 FROM feature.features core JOIN feature.feature_places place USING(feature_id)
            WHERE core.feature_id=v_feature AND core.kind='place') THEN
            RAISE EXCEPTION 'scoped stamp requires existing place' USING ERRCODE='23514';
        END IF;
        IF p_after_source AND NOT EXISTS(SELECT 1 FROM provider_sync.source_entity_heads
            WHERE source_entity_key=v_item->>'source_entity_key'
              AND current_source_record_key=v_item->>'source_record_key') THEN
            RAISE EXCEPTION 'accepted source differs from full refresh input' USING ERRCODE='40001';
        END IF;
        -- kernel의 dataset/head/link/Feature 뒤에만 stamp 행을 UUID 정렬 잠금한다.
        SELECT * INTO v_stamp FROM feature.feature_geocode_stamps WHERE feature_id=v_feature FOR UPDATE;
        IF NOT FOUND OR (v_stamp.geo_version_token,v_stamp.geo_data_token,
             v_stamp.reverse_outcome,v_stamp.stamped_at) IS DISTINCT FROM
             (v_item->>'geo_version_token',v_item->>'geo_data_token',v_item->>'reverse_outcome',
              (v_item->>'stamped_at')::timestamptz) THEN
            RAISE EXCEPTION 'stamp evidence changed; replan' USING ERRCODE='40001';
        END IF;
    END LOOP;
    RETURN v_count;
END;
$$;
