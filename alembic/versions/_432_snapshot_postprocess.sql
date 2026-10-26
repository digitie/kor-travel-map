-- 432: 고정 DB profile별 receipt/asset과 두 topic 순서를 보존한다. 기존430 원본은 보존한다.
CREATE OR REPLACE FUNCTION ops._provider_snapshot_postprocess_receipt(p_snapshot uuid,p_receipt bytea)
RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path TO pg_catalog AS $$
DECLARE
    v_receipt jsonb;
    v_artifact record;
    v_dataset record;
    v_domain text;
    v_context jsonb;
    v_key text;
    v_value jsonb;
    v_keys text[]:=ARRAY['version','domain','root_job_id','source_job_id','import_job_dataset_id',
        'root_run_id','artifact_sha256','context_sha256','result_sha256','provider_dataset_id',
        'sync_scope','operation_key','observation_generation','fetched_at','source_observations',
        'findings_observed','findings_unique','findings_set_sha256','sync_recorded','stale_close_completed'];
BEGIN
    IF p_snapshot IS NULL OR p_receipt IS NULL OR octet_length(p_receipt) NOT BETWEEN 1 AND 4096 THEN
        RAISE EXCEPTION 'bounded snapshot postprocess receipt required' USING ERRCODE='22023';
    END IF;
    v_receipt:=convert_from(p_receipt,'UTF8')::jsonb;
    IF jsonb_typeof(v_receipt) IS DISTINCT FROM 'object' THEN
        RAISE EXCEPTION 'postprocess receipt must be object' USING ERRCODE='22023';
    END IF;
    IF (SELECT count(*) FROM jsonb_object_keys(v_receipt))<>20 OR NOT(v_receipt ?& v_keys)
       OR v_receipt->'version' IS DISTINCT FROM '1'::jsonb
       OR v_receipt->'sync_recorded' IS DISTINCT FROM 'true'::jsonb
       OR v_receipt->'stale_close_completed' IS DISTINCT FROM 'true'::jsonb THEN
        RAISE EXCEPTION 'invalid full postprocess receipt' USING ERRCODE='22023';
    END IF;
    FOREACH v_key IN ARRAY ARRAY['provider_dataset_id','source_observations','findings_observed','findings_unique'] LOOP
        v_value:=v_receipt->v_key;
        IF jsonb_typeof(v_value) IS DISTINCT FROM 'number' THEN
            RAISE EXCEPTION 'postprocess counter must be integer' USING ERRCODE='22023';
        END IF;
        IF scale(v_value::numeric)<>0 OR v_value::numeric<0 OR v_value::numeric>9223372036854775807 THEN
            RAISE EXCEPTION 'postprocess counter exceeds bigint' USING ERRCODE='22023';
        END IF;
    END LOOP;
    FOREACH v_key IN ARRAY ARRAY['artifact_sha256','context_sha256','result_sha256','findings_set_sha256'] LOOP
        IF jsonb_typeof(v_receipt->v_key) IS DISTINCT FROM 'string'
           OR v_receipt->>v_key !~ '^[0-9a-f]{64}$' THEN
            RAISE EXCEPTION 'postprocess receipt SHA required' USING ERRCODE='22023';
        END IF;
    END LOOP;
    SELECT artifact.root_job_id,artifact.source_job_id,artifact.import_job_dataset_id,
           artifact.dagster_run_id,artifact.provider_dataset_id,artifact.sync_scope,artifact.operation_key,
           artifact.artifact_sha256,artifact.context_sha256,artifact.observation_context,
           control.result_sha256 INTO STRICT v_artifact
      FROM ops.provider_snapshot_artifacts artifact
      JOIN ops.provider_snapshot_controls control USING(snapshot_id)
      WHERE artifact.snapshot_id=p_snapshot;
    SELECT dataset.provider,dataset.dataset_key INTO STRICT v_dataset
      FROM provider_sync.provider_datasets dataset
      WHERE dataset.provider_dataset_id=v_artifact.provider_dataset_id;
    IF v_dataset.provider='kor-travel-transport' AND v_dataset.dataset_key='transport_airports' THEN
        v_domain:='airport-snapshot-postprocess-v1';
    ELSIF v_dataset.provider='kor-travel-transport' AND v_dataset.dataset_key='transport_rest_areas' THEN
        v_domain:='rest-area-snapshot-postprocess-v1';
    ELSE
        RAISE EXCEPTION 'unsupported snapshot postprocess dataset'
            USING ERRCODE='23514',CONSTRAINT='ck_provider_snapshot_member_binding';
    END IF;
    IF v_receipt->'domain' IS DISTINCT FROM to_jsonb(v_domain) THEN
        RAISE EXCEPTION 'snapshot postprocess domain differs from its dataset'
            USING ERRCODE='23514',CONSTRAINT='ck_provider_snapshot_member_binding';
    END IF;
    v_context:=convert_from(v_artifact.observation_context,'UTF8')::jsonb;
    IF v_receipt->>'root_job_id' IS DISTINCT FROM v_artifact.root_job_id::text
       OR v_receipt->>'source_job_id' IS DISTINCT FROM v_artifact.source_job_id::text
       OR v_receipt->>'import_job_dataset_id' IS DISTINCT FROM v_artifact.import_job_dataset_id::text
       OR v_receipt->>'root_run_id' IS DISTINCT FROM v_artifact.dagster_run_id
       OR v_receipt->'provider_dataset_id' IS DISTINCT FROM to_jsonb(v_artifact.provider_dataset_id)
       OR v_receipt->>'sync_scope' IS DISTINCT FROM v_artifact.sync_scope
       OR v_receipt->>'operation_key' IS DISTINCT FROM v_artifact.operation_key
       OR v_receipt->>'artifact_sha256' IS DISTINCT FROM v_artifact.artifact_sha256
       OR v_receipt->>'context_sha256' IS DISTINCT FROM v_artifact.context_sha256
       OR v_receipt->>'result_sha256' IS DISTINCT FROM v_artifact.result_sha256
       OR v_receipt->'observation_generation' IS DISTINCT FROM v_context->'observation_generation'
       OR v_receipt->'source_observations' IS DISTINCT FROM v_context->'source_observations'
       OR v_receipt->'findings_observed' IS DISTINCT FROM v_context->'validation'->'issue_count'
       OR (v_receipt->>'findings_unique')::bigint>(v_receipt->>'findings_observed')::bigint
       OR jsonb_typeof(v_receipt->'fetched_at') IS DISTINCT FROM 'string'
       OR octet_length(v_receipt->>'fetched_at') NOT BETWEEN 20 AND 64 THEN
        RAISE EXCEPTION 'postprocess receipt differs from its original snapshot'
            USING ERRCODE='23514',CONSTRAINT='ck_provider_snapshot_member_binding';
    END IF;
    -- 원 fetched_at의 정확 값/clock 표현과 finding 전 필드 지문은 정본 Python decoder가 검증한다.
    -- 이 private SQL은 DB 소속·수집량/검증량·실제 효과를 별도로 대조한다.
    RETURN v_receipt;
END;
$$;

CREATE OR REPLACE FUNCTION ops.begin_provider_snapshot_postprocess(
    p_snapshot uuid,p_generation bigint,p_fence uuid,p_receipt bytea
) RETURNS bytea LANGUAGE plpgsql SECURITY DEFINER SET search_path TO pg_catalog AS $$
DECLARE
    v_control ops.provider_snapshot_controls%ROWTYPE;
    v_receipt jsonb;
    v_dataset bigint;
    v_scope ops.integrity_observation_scopes%ROWTYPE;
    v_run ops.integrity_observation_runs%ROWTYPE;
    v_result jsonb;
    v_capture record;
    v_cursor jsonb;
BEGIN
    v_control:=ops._lock_provider_snapshot_executor(p_snapshot,p_generation,p_fence);
    v_receipt:=ops._provider_snapshot_postprocess_receipt(p_snapshot,p_receipt);
    IF v_control.status='postprocessed' AND v_control.postprocess_receipt=p_receipt THEN
        RETURN v_control.postprocess_receipt;
    END IF;
    IF v_control.status<>'applied' OR v_control.postprocess_receipt IS NOT NULL
       OR NOT EXISTS(SELECT 1 FROM ops.feature_write_attempts attempt
                     WHERE attempt.attempt_id=v_control.attempt_id AND attempt.status='completed'
                       AND attempt.owner=v_control.attempt_owner
                       AND attempt.manifest_digest=v_control.manifest_digest
                       AND attempt.apply_txid IS NOT NULL AND attempt.result_digest IS NOT NULL) THEN
        RAISE EXCEPTION 'snapshot postprocess requires its original completed apply'
            USING ERRCODE='23514',CONSTRAINT='ck_provider_snapshot_apply_required';
    END IF;
    v_dataset:=(v_receipt->>'provider_dataset_id')::bigint;
    SELECT * INTO STRICT v_scope FROM ops.integrity_observation_scopes scope
      WHERE scope.provider_dataset_id=v_dataset FOR UPDATE;
    SELECT * INTO STRICT v_run FROM ops.integrity_observation_runs run
      WHERE run.integrity_observation_scope_id=v_scope.integrity_observation_scope_id
        AND run.external_run_id=v_receipt->>'observation_generation' FOR UPDATE;
    -- generation은 source 적용 TX에서 이미 예약되어야 한다. 재시작 시 새 세대를 만들지 않는다.
    -- failed/preload run의 단순 세대 예약은 기존 적용을 무효화하지 않는다.
    -- 실제 새 적용 또는 더 최신 authoritative 후처리만 원 세대를 대체한다.
    IF v_run.generation<=v_scope.latest_authoritative_generation OR v_run.status='superseded'
       OR EXISTS(
           SELECT 1 FROM ops.provider_snapshot_artifacts artifact
           JOIN ops.provider_snapshot_controls control USING(snapshot_id)
           JOIN ops.integrity_observation_runs newer
             ON newer.integrity_observation_scope_id=v_scope.integrity_observation_scope_id
            AND newer.external_run_id=(convert_from(artifact.observation_context,'UTF8')::jsonb
                                        ->>'observation_generation')
           WHERE artifact.provider_dataset_id=v_dataset
             AND control.status IN ('applied','postprocessed','child_sealed')
             AND newer.generation>v_run.generation
       ) THEN
        RAISE EXCEPTION 'snapshot was superseded before postprocess'
            USING ERRCODE='55000',CONSTRAINT='ck_provider_snapshot_superseded';
    END IF;
    IF v_run.status<>'collecting' THEN
        RAISE EXCEPTION 'snapshot has a partial external postprocess state'
            USING ERRCODE='23514',CONSTRAINT='ck_provider_snapshot_apply_required';
    END IF;
    v_result:=convert_from(v_control.applied_result,'UTF8')::jsonb;
    SELECT * INTO STRICT v_capture FROM feature._bounded_provider_curation_input_set(v_dataset);
    IF NOT v_capture.capture_complete
       OR v_capture.input_member_count IS DISTINCT FROM (v_result->'load'->>'curation_input_member_count')::bigint
       OR v_capture.source_input_set_hash IS DISTINCT FROM v_result->'load'->>'curation_input_set_hash' THEN
        RAISE EXCEPTION 'snapshot source heads changed before postprocess'
            USING ERRCODE='55000',CONSTRAINT='ck_provider_snapshot_superseded';
    END IF;
    SELECT state.cursor INTO v_cursor FROM provider_sync.provider_sync_state state
      WHERE state.provider_dataset_id=v_dataset AND state.sync_scope=v_receipt->>'sync_scope'
        AND state.operation_key=v_receipt->>'operation_key' FOR UPDATE;
    IF v_cursor ? 'loaded_at'
       AND (v_cursor->>'loaded_at')::timestamptz>(v_receipt->>'fetched_at')::timestamptz THEN
        RAISE EXCEPTION 'snapshot sync cursor is newer than the original observation'
            USING ERRCODE='55000',CONSTRAINT='ck_provider_snapshot_superseded';
    END IF;
    UPDATE ops.provider_snapshot_controls SET postprocess_txid=txid_current(),
        postprocess_intent_sha256=encode(sha256(p_receipt),'hex'),updated_at=clock_timestamp()
      WHERE snapshot_id=p_snapshot;
    -- fence/domain/원 결과/marker 검증 뒤, 첫 callback topic DML 전에만 고정순 선취득한다.
    PERFORM ops._lock_snapshot_postprocess_topic_revisions();
    RETURN NULL;
END;
$$;

CREATE OR REPLACE FUNCTION ops.finish_provider_snapshot_postprocess(
    p_snapshot uuid,p_generation bigint,p_fence uuid,p_receipt bytea
) RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path TO pg_catalog AS $$
DECLARE
    v_control ops.provider_snapshot_controls%ROWTYPE;
    v_receipt jsonb;
    v_run record;
    v_cursor jsonb;
    v_result jsonb;
    v_expected_cursor jsonb;
    v_asset text;
    v_dataset record;
    v_key text;
BEGIN
    v_control:=ops._lock_provider_snapshot_executor(p_snapshot,p_generation,p_fence);
    v_receipt:=ops._provider_snapshot_postprocess_receipt(p_snapshot,p_receipt);
    IF v_control.status IS DISTINCT FROM 'applied'
       OR v_control.postprocess_txid IS DISTINCT FROM txid_current()
       OR v_control.postprocess_intent_sha256 IS DISTINCT FROM encode(sha256(p_receipt),'hex') THEN
        RAISE EXCEPTION 'postprocess effects must share their fenced transaction'
            USING ERRCODE='23514',CONSTRAINT='ck_provider_snapshot_apply_required';
    END IF;
    SELECT run.*,scope.latest_generation,scope.latest_authoritative_generation,
           (SELECT count(*) FROM ops.integrity_finding_observations observation
            WHERE observation.observation_run_id=run.observation_run_id) AS actual_findings
      INTO STRICT v_run FROM ops.integrity_observation_runs run
      JOIN ops.integrity_observation_scopes scope USING(integrity_observation_scope_id)
      WHERE scope.provider_dataset_id=(v_receipt->>'provider_dataset_id')::bigint
        AND run.external_run_id=v_receipt->>'observation_generation';
    IF v_run.status<>'authoritative' OR v_run.completed_at IS NULL
       OR v_run.generation<>v_run.latest_authoritative_generation
       OR v_run.source_observations<>(v_receipt->>'source_observations')::bigint
       OR v_run.findings_observed<>(v_receipt->>'findings_observed')::bigint
       OR v_run.findings_unique<>(v_receipt->>'findings_unique')::bigint
       OR v_run.findings_upserted<>v_run.findings_unique OR v_run.actual_findings<>v_run.findings_unique THEN
        RAISE EXCEPTION 'postprocess finding set was not durably finalized'
            USING ERRCODE='23514',CONSTRAINT='ck_provider_snapshot_apply_required';
    END IF;
    v_result:=convert_from(v_control.applied_result,'UTF8')::jsonb;
    SELECT dataset.provider,dataset.dataset_key INTO STRICT v_dataset
      FROM ops.provider_snapshot_artifacts artifact
      JOIN provider_sync.provider_datasets dataset USING(provider_dataset_id)
      WHERE artifact.snapshot_id=p_snapshot;
    IF v_dataset.provider='kor-travel-transport' AND v_dataset.dataset_key='transport_airports' THEN
        v_asset:='feature_place_transport_airports';
    ELSIF v_dataset.provider='kor-travel-transport' AND v_dataset.dataset_key='transport_rest_areas' THEN
        v_asset:='feature_place_transport_rest_areas';
    ELSE
        RAISE EXCEPTION 'unsupported snapshot postprocess dataset'
            USING ERRCODE='23514',CONSTRAINT='ck_provider_snapshot_member_binding';
    END IF;
    v_expected_cursor:=jsonb_build_object('loaded_at',v_receipt->>'fetched_at','asset_key',v_asset);
    FOREACH v_key IN ARRAY ARRAY['bundles_total','features_inserted','features_updated',
        'source_records_inserted','source_links_inserted','source_links_updated'] LOOP
        v_expected_cursor:=v_expected_cursor||jsonb_build_object(v_key,v_result->'load'->v_key);
    END LOOP;
    SELECT state.cursor INTO STRICT v_cursor FROM provider_sync.provider_sync_state state
      WHERE state.provider_dataset_id=(v_receipt->>'provider_dataset_id')::bigint
        AND state.sync_scope=v_receipt->>'sync_scope' AND state.operation_key=v_receipt->>'operation_key';
    IF v_cursor IS DISTINCT FROM v_expected_cursor THEN
        RAISE EXCEPTION 'postprocess sync state does not match original apply counters'
            USING ERRCODE='23514',CONSTRAINT='ck_provider_snapshot_apply_required';
    END IF;
    UPDATE ops.provider_snapshot_controls SET status='postprocessed',postprocess_receipt=p_receipt,
        postprocessed_at=clock_timestamp(),postprocess_txid=NULL,postprocess_intent_sha256=NULL,
        updated_at=clock_timestamp()
      WHERE snapshot_id=p_snapshot;
END;
$$;
