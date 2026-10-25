-- 미호출 조각. claim/plan/apply caller와 전체430 ACL 합성 없이 설치하지 않는다.
CREATE FUNCTION ops._lock_provider_snapshot_executor(p_snapshot uuid,p_generation bigint,p_fence uuid)
RETURNS ops.provider_snapshot_controls
LANGUAGE plpgsql SECURITY DEFINER SET search_path TO pg_catalog AS $$
DECLARE
    v_artifact record;
    v_control ops.provider_snapshot_controls%ROWTYPE;
BEGIN
    IF NOT pg_has_role(session_user,'ktm_curation_provider_executor','member') THEN
        RAISE EXCEPTION 'snapshot command requires provider executor' USING ERRCODE='42501';
    END IF;
    IF p_snapshot IS NULL OR p_generation IS NULL OR p_generation<1 OR p_fence IS NULL THEN
        RAISE EXCEPTION 'exact executor fence required' USING ERRCODE='22023';
    END IF;
    IF current_setting('transaction_isolation')<>'read committed' THEN
        RAISE EXCEPTION 'snapshot command requires READ COMMITTED' USING ERRCODE='25001';
    END IF;
    PERFORM ops._arm_scoped_feature_write_deadline();
    PERFORM ops.lock_scoped_feature_write_protocol(false);
    SELECT artifact.root_job_id,artifact.source_job_id,artifact.import_job_dataset_id,
           artifact.provider_dataset_id,artifact.sync_scope,artifact.operation_key,
           artifact.dagster_run_id,artifact.capture_profile
      INTO STRICT v_artifact FROM ops.provider_snapshot_artifacts artifact
      WHERE artifact.snapshot_id=p_snapshot;
    PERFORM ops._lock_scoped_feature_write_scope(v_artifact.provider_dataset_id,'[]'::jsonb,false);
    -- B의 actual parent SHARE가 전제다. root/member tuple 및 quota 잠금은 없다.
    IF v_artifact.capture_profile IS DISTINCT FROM 'bounded-place-v1' OR NOT EXISTS(
        SELECT 1 FROM ops.import_jobs root
        JOIN ops.import_jobs child ON child.parent_job_id=root.job_id
        JOIN ops.import_job_datasets member ON member.job_id=child.job_id
        JOIN provider_sync.provider_datasets dataset ON dataset.provider_dataset_id=member.provider_dataset_id
        JOIN provider_sync.provider_dataset_operations operation
          ON operation.provider_dataset_id=member.provider_dataset_id AND operation.operation_key=member.operation_key
        WHERE root.job_id=v_artifact.root_job_id AND root.kind='provider_feature_load_run'
          AND root.status='running' AND root.dagster_run_status='STARTED'
          AND root.dagster_run_id=v_artifact.dagster_run_id
          AND root.cancellation_id IS NULL AND root.cancellation_requested_at IS NULL
          AND root.quarantined_at IS NULL AND root.root_id=root.job_id AND root.root_kind='import_job'
          AND child.job_id=v_artifact.source_job_id AND child.kind='provider_feature_load'
          AND child.status IN ('queued','running') AND child.dagster_run_id=root.dagster_run_id
          AND child.cancellation_id IS NULL AND child.cancellation_requested_at IS NULL
          AND child.quarantined_at IS NULL AND child.root_id=root.job_id AND child.root_kind='import_job'
          AND child.dataset_membership_mode='single'
          AND member.import_job_dataset_id=v_artifact.import_job_dataset_id
          AND member.provider_dataset_id=v_artifact.provider_dataset_id
          AND member.sync_scope=v_artifact.sync_scope AND member.operation_key=v_artifact.operation_key
          AND dataset.is_active AND operation.is_enabled AND operation.operation_kind='refresh'
          AND (SELECT count(*) FROM ops.import_job_datasets all_members WHERE all_members.job_id=child.job_id)=1
    ) THEN
        RAISE EXCEPTION 'snapshot executor member is no longer active'
            USING ERRCODE='23514',CONSTRAINT='ck_provider_snapshot_member_binding';
    END IF;
    SELECT * INTO STRICT v_control FROM ops.provider_snapshot_controls control
      WHERE control.snapshot_id=p_snapshot FOR UPDATE;
    IF v_control.executor_generation IS DISTINCT FROM p_generation
       OR v_control.executor_fence IS DISTINCT FROM p_fence
       OR v_control.lease_expires_at<=clock_timestamp() THEN
        RAISE EXCEPTION 'snapshot executor fence is stale' USING ERRCODE='40001';
    END IF;
    RETURN v_control;
END;
$$;

CREATE FUNCTION ops.bind_provider_snapshot_plan(
    p_snapshot uuid,p_generation bigint,p_fence uuid,p_attempt uuid,p_owner uuid,
    p_manifest text,p_kernel_input text
) RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path TO pg_catalog AS $$
DECLARE
    v_control ops.provider_snapshot_controls%ROWTYPE;
    v_artifact record;
    v_attempt ops.feature_write_attempts%ROWTYPE;
BEGIN
    IF p_attempt IS NULL OR p_owner IS NULL OR p_manifest IS NULL
       OR p_manifest !~ '^[0-9a-f]{64}$' OR p_kernel_input IS NULL
       OR p_kernel_input !~ '^[0-9a-f]{64}$' THEN
        RAISE EXCEPTION 'exact kernel plan binding required' USING ERRCODE='22023';
    END IF;
    v_control:=ops._lock_provider_snapshot_executor(p_snapshot,p_generation,p_fence);
    SELECT artifact.provider_dataset_id INTO STRICT v_artifact
      FROM ops.provider_snapshot_artifacts artifact WHERE artifact.snapshot_id=p_snapshot;
    SELECT * INTO STRICT v_attempt FROM ops.feature_write_attempts attempt
      WHERE attempt.attempt_id=p_attempt;
    IF v_control.status<>'prepared' OR v_attempt.provider_dataset_id<>v_artifact.provider_dataset_id
       OR v_attempt.owner IS DISTINCT FROM p_owner OR v_attempt.manifest_digest IS DISTINCT FROM p_manifest
       OR v_attempt.input_digest IS DISTINCT FROM p_kernel_input OR v_attempt.regions<>'[]'::jsonb
       OR v_attempt.exclusive_protocol IS DISTINCT FROM false
       OR v_attempt.status<>'ready' OR v_attempt.lease_until<=clock_timestamp() THEN
        RAISE EXCEPTION 'snapshot kernel plan is not ready'
            USING ERRCODE='23514',CONSTRAINT='ck_provider_snapshot_plan_binding';
    END IF;
    IF v_control.attempt_id IS NOT NULL THEN
        IF v_control.attempt_id IS DISTINCT FROM p_attempt
           OR v_control.attempt_owner IS DISTINCT FROM p_owner
           OR v_control.manifest_digest IS DISTINCT FROM p_manifest THEN
            -- 재계획/lease 회수 정책은 별도 typed 명령으로만 허용한다.
            RAISE EXCEPTION 'snapshot kernel plan is already bound'
                USING ERRCODE='23514',CONSTRAINT='ck_provider_snapshot_plan_binding';
        END IF;
        RETURN;
    END IF;
    UPDATE ops.provider_snapshot_controls SET attempt_id=p_attempt,attempt_owner=p_owner,
        manifest_digest=p_manifest,updated_at=clock_timestamp() WHERE snapshot_id=p_snapshot;
END;
$$;

CREATE FUNCTION ops.begin_provider_snapshot_apply(
    p_snapshot uuid,p_generation bigint,p_fence uuid,p_attempt uuid,p_owner uuid,p_manifest text,
    p_artifact_sha text
) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path TO pg_catalog AS $$
DECLARE
    v_attempt jsonb;
    v_control ops.provider_snapshot_controls%ROWTYPE;
BEGIN
    -- kernel의 P→모든 실제 parent 정렬→scope→source/link/Feature를 먼저 보존한다.
    -- own scope를 선점한 뒤 foreign participant parent를 늦게 추가하지 않는다.
    -- begin의 applying 기록도 아래 fence 실패 시 같은 TX에서 rollback된다. 실제 DML은 아직0.
    IF NOT pg_has_role(session_user,'ktm_curation_provider_executor','member') THEN
        RAISE EXCEPTION 'snapshot apply requires provider executor' USING ERRCODE='42501';
    END IF;
    IF current_setting('transaction_isolation')<>'read committed' THEN
        RAISE EXCEPTION 'snapshot apply requires READ COMMITTED' USING ERRCODE='25001';
    END IF;
    IF p_artifact_sha IS NULL OR p_artifact_sha !~ '^[0-9a-f]{64}$' THEN
        RAISE EXCEPTION 'exact decoded artifact SHA required' USING ERRCODE='22023';
    END IF;
    v_attempt:=ops.begin_scoped_feature_write(p_attempt,p_owner,p_manifest);
    v_control:=ops._lock_provider_snapshot_executor(p_snapshot,p_generation,p_fence);
    IF NOT EXISTS(SELECT 1 FROM ops.provider_snapshot_artifacts artifact
                  WHERE artifact.snapshot_id=p_snapshot AND artifact.artifact_sha256=p_artifact_sha) THEN
        RAISE EXCEPTION 'decoded apply input differs from the registered artifact'
            USING ERRCODE='23514',CONSTRAINT='ck_provider_snapshot_plan_binding';
    END IF;
    IF v_control.status<>'prepared' OR v_control.attempt_id IS DISTINCT FROM p_attempt
       OR v_control.attempt_owner IS DISTINCT FROM p_owner
       OR v_control.manifest_digest IS DISTINCT FROM p_manifest
       OR v_attempt->>'status' IS DISTINCT FROM 'applying'
       OR v_attempt->>'apply_txid' IS DISTINCT FROM txid_current()::text THEN
        RAISE EXCEPTION 'snapshot apply does not match its live kernel plan'
            USING ERRCODE='23514',CONSTRAINT='ck_provider_snapshot_plan_binding';
    END IF;
    RETURN v_attempt || jsonb_build_object('snapshot_observation_generation',
        (SELECT convert_from(artifact.observation_context,'UTF8')::jsonb->>'observation_generation'
         FROM ops.provider_snapshot_artifacts artifact WHERE artifact.snapshot_id=p_snapshot));
END;
$$;

CREATE FUNCTION ops.finish_provider_snapshot_apply(
    p_snapshot uuid,p_generation bigint,p_fence uuid,p_result bytea
) RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path TO pg_catalog AS $$
DECLARE
    v_control ops.provider_snapshot_controls%ROWTYPE;
    v_attempt ops.feature_write_attempts%ROWTYPE;
    v_artifact record;
    v_result jsonb;
    v_load jsonb;
    v_key text;
    v_value jsonb;
    v_count bigint;
    v_hash text;
    v_capture record;
    v_keys text[]:=ARRAY['bundles_total','features_inserted','features_updated','source_records_inserted',
        'source_links_inserted','source_links_updated','geo_stamps_written','geo_stale_rewritten',
        'geo_stale_unchanged','geo_empty_guarded','geo_override_stale_findings','geo_partial_kept',
        'curation_input_member_count','curation_input_set_hash'];
BEGIN
    IF p_result IS NULL OR octet_length(p_result) NOT BETWEEN 1 AND 4096 THEN
        RAISE EXCEPTION 'bounded original apply result required' USING ERRCODE='22023';
    END IF;
    v_control:=ops._lock_provider_snapshot_executor(p_snapshot,p_generation,p_fence);
    IF v_control.status<>'prepared' OR v_control.attempt_id IS NULL THEN
        RAISE EXCEPTION 'snapshot apply result is already complete or has no plan'
            USING ERRCODE='23514',CONSTRAINT='ck_provider_snapshot_apply_required';
    END IF;
    SELECT * INTO STRICT v_attempt FROM ops.feature_write_attempts attempt
      WHERE attempt.attempt_id=v_control.attempt_id;
    IF v_attempt.status<>'completed' OR v_attempt.apply_txid IS DISTINCT FROM txid_current()
       OR v_attempt.owner IS DISTINCT FROM v_control.attempt_owner
       OR v_attempt.manifest_digest IS DISTINCT FROM v_control.manifest_digest
       OR v_attempt.result_digest IS NULL THEN
        RAISE EXCEPTION 'original result must share the kernel apply transaction'
            USING ERRCODE='23514',CONSTRAINT='ck_provider_snapshot_apply_required';
    END IF;
    SELECT artifact.provider_dataset_id INTO STRICT v_artifact
      FROM ops.provider_snapshot_artifacts artifact WHERE artifact.snapshot_id=p_snapshot;
    IF v_attempt.provider_dataset_id<>v_artifact.provider_dataset_id THEN
        RAISE EXCEPTION 'snapshot kernel dataset changed'
            USING ERRCODE='23514',CONSTRAINT='ck_provider_snapshot_plan_binding';
    END IF;
    v_result:=convert_from(p_result,'UTF8')::jsonb;
    IF jsonb_typeof(v_result) IS DISTINCT FROM 'object'
       OR v_result->>'domain' IS DISTINCT FROM 'provider-full-snapshot-apply-result-v1'
       OR v_result->'version' IS DISTINCT FROM '1'::jsonb THEN
        RAISE EXCEPTION 'invalid original result envelope' USING ERRCODE='22023';
    END IF;
    IF (SELECT count(*) FROM jsonb_object_keys(v_result))<>4
       OR NOT (v_result ?& ARRAY['domain','version','load','retired'])
       OR jsonb_typeof(v_result->'load') IS DISTINCT FROM 'object' THEN
        RAISE EXCEPTION 'invalid original result fields' USING ERRCODE='22023';
    END IF;
    v_load:=v_result->'load';
    IF (SELECT count(*) FROM jsonb_object_keys(v_load))<>14 OR NOT (v_load ?& v_keys) THEN
        RAISE EXCEPTION 'partial original result is forbidden' USING ERRCODE='22023';
    END IF;
    FOREACH v_key IN ARRAY array_append(v_keys,'retired') LOOP
        IF v_key='curation_input_set_hash' THEN CONTINUE; END IF;
        v_value:=CASE WHEN v_key='retired' THEN v_result->v_key ELSE v_load->v_key END;
        IF jsonb_typeof(v_value) IS DISTINCT FROM 'number' THEN
            RAISE EXCEPTION 'original result counter must be integer' USING ERRCODE='22023';
        END IF;
        IF scale(v_value::numeric)<>0 OR v_value::numeric<0 OR v_value::numeric>9223372036854775807 THEN
            RAISE EXCEPTION 'original result counter exceeds bigint' USING ERRCODE='22023';
        END IF;
    END LOOP;
    IF jsonb_typeof(v_load->'curation_input_set_hash') IS DISTINCT FROM 'string'
       OR v_load->>'curation_input_set_hash' !~ '^[0-9a-f]{64}$' THEN
        RAISE EXCEPTION 'original result capture hash required' USING ERRCODE='22023';
    END IF;
    v_count:=(v_load->>'curation_input_member_count')::bigint;
    v_hash:=v_load->>'curation_input_set_hash';
    SELECT * INTO STRICT v_capture FROM feature._bounded_provider_curation_input_set(v_artifact.provider_dataset_id);
    IF NOT v_capture.capture_complete OR v_count IS DISTINCT FROM v_capture.input_member_count
       OR v_hash IS DISTINCT FROM v_capture.source_input_set_hash THEN
        RAISE EXCEPTION 'original result capture differs from same-TX source heads'
            USING ERRCODE='23514',CONSTRAINT='ck_provider_snapshot_bounded_capture';
    END IF;
    -- 원 counter를 다시 계산하거나 새 성공으로 대체하지 않는다. 입력/후처리 권위는 별도다.
    UPDATE ops.provider_snapshot_controls SET status='applied',applied_result=p_result,
        applied_generation=p_generation,applied_fence=p_fence,applied_at=clock_timestamp(),
        updated_at=clock_timestamp() WHERE snapshot_id=p_snapshot;
END;
$$;
