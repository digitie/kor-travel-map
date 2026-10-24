CREATE OR REPLACE FUNCTION feature._exclusive_provider_refresh_context(p_feature uuid,p_dataset bigint DEFAULT NULL)
RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path TO pg_catalog AS $$
DECLARE v_attempt ops.feature_write_attempts%ROWTYPE;
        v_row ops.feature_write_attempts%ROWTYPE; v_count integer:=0; v_entity text;
BEGIN
    -- 0/복수는 false이며 정확 1행일 때만 기존 검증 순서로 진행한다.
    FOR v_row IN SELECT a.* FROM ops.feature_write_attempts a
    JOIN ops.feature_write_manifests m ON m.attempt_id=a.attempt_id
    WHERE a.status='applying' AND a.apply_txid=txid_current() AND a.exclusive_protocol
      AND a.idempotency_key='native-full-refresh-v1:'||a.input_digest||':'||replace(a.attempt_id::text,'-','')
      AND m.dependency_kind='feature' AND m.dependency_key=p_feature::text
      AND (p_dataset IS NULL OR a.provider_dataset_id=p_dataset) LIMIT 2 LOOP
        v_count:=v_count+1;
        IF v_count>1 THEN RETURN false; END IF;
        v_attempt:=v_row;
    END LOOP;
    IF v_count=0 THEN RETURN false; END IF;
    -- prefix는 용도 구분일 뿐이다. 실제 TX/membership/closure/epoch와 EX를 검증한다.
    PERFORM ops.lock_scoped_feature_write_protocol(true);
    PERFORM feature.assert_scoped_candidate_write(v_attempt.attempt_id,p_feature);
    SELECT l.source_entity_key INTO STRICT v_entity FROM provider_sync.source_links l
    JOIN provider_sync.source_entities e USING(source_entity_key)
    WHERE l.feature_id=p_feature AND l.source_role='primary'
      AND e.provider_dataset_id=v_attempt.provider_dataset_id;
    PERFORM feature.assert_scoped_provider_scalar_target(v_attempt.attempt_id,p_feature,
        v_attempt.provider_dataset_id,v_entity,
        (SELECT policy_revision FROM feature.provider_field_active_policies WHERE feature_id=p_feature));
    RETURN true;
END;
$$;
