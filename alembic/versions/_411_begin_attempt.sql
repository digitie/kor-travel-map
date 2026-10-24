CREATE FUNCTION ops.begin_scoped_feature_write(p_attempt uuid,p_owner uuid,p_manifest_digest text)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path TO pg_catalog AS $$
DECLARE v_attempt ops.feature_write_attempts%ROWTYPE; v_dependency ops.feature_write_manifests%ROWTYPE; v_value text;
BEGIN
    v_attempt:=ops._locked_scoped_feature_write_attempt(p_attempt,p_owner);
    IF v_attempt.manifest_digest IS DISTINCT FROM p_manifest_digest OR p_manifest_digest IS NULL THEN
        RAISE EXCEPTION 'manifest digest mismatch' USING ERRCODE='23514';
    END IF;
    IF v_attempt.status='completed' THEN RETURN to_jsonb(v_attempt); END IF;
    IF v_attempt.status='applying' AND v_attempt.apply_txid=txid_current() THEN RETURN to_jsonb(v_attempt); END IF;
    IF v_attempt.status<>'ready' THEN RAISE EXCEPTION 'attempt is not ready' USING ERRCODE='23514'; END IF;
    -- 단일 dataset의 알려진 source/head→Feature 의존만 지원한다. 전체 closure/phantom의
    -- 완결성 증명이나 claim/redirect/catalog 검증은 후속 진입점이 제공하기 전 enable하지 않는다.
    FOR v_dependency IN SELECT * FROM ops.feature_write_manifests WHERE attempt_id=p_attempt
        ORDER BY CASE dependency_kind WHEN 'source_head' THEN 0 ELSE 1 END,dependency_key COLLATE "C" LOOP
        v_value:=NULL;
        IF v_dependency.dependency_kind='source_head' THEN
            PERFORM 1 FROM provider_sync.source_entities WHERE source_entity_key=v_dependency.dependency_key AND provider_dataset_id=v_attempt.provider_dataset_id FOR UPDATE;
            IF NOT FOUND THEN RAISE EXCEPTION 'source dependency no longer exists' USING ERRCODE='40001'; END IF;
            SELECT current_source_record_key INTO v_value FROM provider_sync.source_entity_heads WHERE source_entity_key=v_dependency.dependency_key FOR UPDATE;
        ELSE
            SELECT row_revision::text INTO v_value FROM feature.features WHERE feature_id=v_dependency.dependency_key::uuid FOR UPDATE;
        END IF;
        IF v_value IS DISTINCT FROM v_dependency.expected_value THEN RAISE EXCEPTION 'manifest dependency changed; replan' USING ERRCODE='40001'; END IF;
    END LOOP;
    UPDATE ops.feature_write_attempts SET status='applying',apply_txid=txid_current(),updated_at=clock_timestamp() WHERE attempt_id=p_attempt RETURNING * INTO v_attempt;
    RETURN to_jsonb(v_attempt);
END;
$$;
