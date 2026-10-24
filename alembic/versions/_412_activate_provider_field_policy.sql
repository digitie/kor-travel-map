-- 활성화는 runtime에 공개하지 않는다. 운영 정책의 rank/coverage를 자동 seed하지 않는다.
CREATE PROCEDURE feature.activate_provider_field_policy(
    IN p_feature uuid,IN p_revision bigint,IN p_fields text[])
LANGUAGE plpgsql SECURITY DEFINER SET search_path TO pg_catalog AS $$
DECLARE v_key text; v_dataset bigint;
BEGIN
    PERFORM ops.lock_scoped_feature_write_protocol(true);
    PERFORM pg_advisory_xact_lock(hashtextextended('feature-curation-write',0));
    -- 기본 OFF에는 trigger/event 비용이 없다. 첫 명시 cutover에서만 DDL을 원자 설치한다.
    PERFORM feature._install_provider_field_projection_guards();
    PERFORM 1 FROM feature.provider_field_policy_epoch WHERE singleton FOR UPDATE;
    -- begin과 동일하게 모든 dataset→entity/head→Feature 순서를 지킨다.
    FOR v_dataset IN SELECT DISTINCT entity.provider_dataset_id
        FROM provider_sync.source_links link JOIN provider_sync.source_entities entity USING(source_entity_key)
        WHERE link.feature_id=p_feature ORDER BY entity.provider_dataset_id LOOP
        PERFORM 1 FROM provider_sync.provider_datasets WHERE provider_dataset_id=v_dataset FOR SHARE;
    END LOOP;
    FOR v_key IN SELECT source_entity_key FROM provider_sync.source_links
        WHERE feature_id=p_feature ORDER BY source_entity_key COLLATE "C" LOOP
        PERFORM 1 FROM provider_sync.source_entities WHERE source_entity_key=v_key FOR SHARE;
        PERFORM 1 FROM provider_sync.source_entity_heads WHERE source_entity_key=v_key FOR SHARE;
    END LOOP;
    PERFORM 1 FROM feature.features WHERE feature_id=p_feature FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'unknown Feature' USING ERRCODE='23514'; END IF;
    -- 읽기만으로 완전성을 먼저 검증한다. 이후 어느 단계가 실패해도 pointer/epoch/투영 모두 rollback한다.
    PERFORM * FROM feature.provider_field_scalar_winners(p_feature,p_revision,p_fields);
    INSERT INTO feature.provider_field_active_policies(feature_id,policy_revision,field_paths)
    VALUES(p_feature,p_revision,p_fields)
    ON CONFLICT(feature_id) DO UPDATE SET policy_revision=EXCLUDED.policy_revision,field_paths=EXCLUDED.field_paths;
    PERFORM feature._project_provider_field_candidates(p_feature);
    UPDATE feature.provider_field_policy_epoch SET epoch=epoch+1 WHERE singleton;
END;
$$;
