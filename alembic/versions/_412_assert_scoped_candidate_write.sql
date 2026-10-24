-- begin이 모든 participant dataset/head와 Feature를 정렬 잠금한 뒤에만 호출한다.
CREATE FUNCTION feature.assert_scoped_candidate_write(p_attempt uuid,p_feature uuid)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path TO pg_catalog AS $$
DECLARE v_attempt ops.feature_write_attempts%ROWTYPE;
BEGIN
    IF p_attempt IS NULL OR p_feature IS NULL THEN
        RAISE EXCEPTION 'scoped candidate write requires an applying manifest' USING ERRCODE='23514';
    END IF;
    PERFORM feature.lock_provider_field_policy_epoch();
    SELECT * INTO v_attempt FROM ops.feature_write_attempts WHERE attempt_id=p_attempt;
    IF NOT FOUND OR v_attempt.status<>'applying'
       OR v_attempt.apply_txid IS DISTINCT FROM txid_current()
       OR v_attempt.manifest_digest IS NULL THEN
        RAISE EXCEPTION 'candidate attempt is not applying in this transaction' USING ERRCODE='23514';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM ops.feature_write_manifests manifest
        WHERE manifest.attempt_id=p_attempt AND manifest.dependency_kind='feature'
          AND manifest.dependency_key=p_feature::text) THEN
        RAISE EXCEPTION 'candidate Feature is outside the applying manifest' USING ERRCODE='23514';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM ops.feature_write_manifests manifest
        WHERE manifest.attempt_id=p_attempt AND manifest.dependency_kind='feature_membership'
          AND manifest.dependency_key=p_feature::text
          AND manifest.expected_value=ops.scoped_feature_write_membership_digest(p_feature)) THEN
        RAISE EXCEPTION 'candidate source membership changed; replan' USING ERRCODE='40001';
    END IF;
    -- membership를 축소해서 정상처럼 처리하지 않는다. begin 뒤 새 head 잠금은 취득하지 않는다.
    IF NOT EXISTS (SELECT 1 FROM provider_sync.source_links WHERE feature_id=p_feature)
       OR EXISTS (SELECT 1 FROM provider_sync.source_links link
          WHERE link.feature_id=p_feature AND NOT EXISTS (
            SELECT 1 FROM ops.feature_write_manifests manifest
            WHERE manifest.attempt_id=p_attempt AND manifest.dependency_kind='source_head'
              AND manifest.dependency_key=link.source_entity_key)) THEN
        RAISE EXCEPTION 'applying manifest lacks complete Feature source closure' USING ERRCODE='23514';
    END IF;
END;
$$;
