-- 독립 설치/호출 금지: RC finalizer/owner ACL/후처리 명령과 함께 합성한다.
-- 단독 marker 발급 함수를 노출하지 않는다. marker→정본 seal→child done이 한 CALL이다.
CREATE PROCEDURE ops.seal_provider_snapshot_member(
    IN p_snapshot uuid,IN p_artifact_sha text,IN p_context_sha text,
    IN p_generation bigint,IN p_fence uuid,IN p_result_sha text,IN p_postprocess_sha text,
    OUT o_observed_at timestamptz,OUT o_replayed boolean
) LANGUAGE plpgsql SECURITY DEFINER SET search_path TO pg_catalog AS $$
DECLARE
    v_artifact record;
    v_control ops.provider_snapshot_controls%ROWTYPE;
    v_root ops.import_jobs%ROWTYPE;
    v_child ops.import_jobs%ROWTYPE;
    v_member ops.import_job_datasets%ROWTYPE;
    v_result jsonb;
    v_count bigint;
    v_hash text;
    v_source uuid;
    v_entities bigint;
    v_source_hash text;
    v_changed boolean;
BEGIN
    IF NOT pg_has_role(session_user,'ktm_curation_provider_executor','member') THEN
        RAISE EXCEPTION 'snapshot seal requires provider executor' USING ERRCODE='42501';
    END IF;
    IF p_snapshot IS NULL OR p_generation IS NULL OR p_generation<1 OR p_fence IS NULL
       OR p_artifact_sha IS NULL OR p_artifact_sha !~ '^[0-9a-f]{64}$'
       OR p_context_sha IS NULL OR p_context_sha !~ '^[0-9a-f]{64}$'
       OR p_result_sha IS NULL OR p_result_sha !~ '^[0-9a-f]{64}$'
       OR p_postprocess_sha IS NULL OR p_postprocess_sha !~ '^[0-9a-f]{64}$' THEN
        RAISE EXCEPTION 'exact snapshot seal binding required' USING ERRCODE='22023';
    END IF;
    IF current_setting('transaction_isolation')<>'read committed' THEN
        RAISE EXCEPTION 'snapshot seal requires READ COMMITTED' USING ERRCODE='25001';
    END IF;
    -- P EX→L→root→child→member→control. apply/lease 쪽의 P SH와 교차하지 않는다.
    PERFORM ops.lock_provider_feature_tracking_protocol(true);
    SELECT artifact.root_job_id,artifact.source_job_id,artifact.import_job_dataset_id,
           artifact.provider_dataset_id,artifact.sync_scope,artifact.operation_key,
           artifact.dagster_run_id,artifact.capture_profile,artifact.artifact_sha256,artifact.context_sha256
      INTO STRICT v_artifact FROM ops.provider_snapshot_artifacts artifact
      WHERE artifact.snapshot_id=p_snapshot;
    IF v_artifact.capture_profile IS DISTINCT FROM 'bounded-place-v1'
       OR v_artifact.artifact_sha256 IS DISTINCT FROM p_artifact_sha
       OR v_artifact.context_sha256 IS DISTINCT FROM p_context_sha THEN
        RAISE EXCEPTION 'snapshot seal input binding changed'
            USING ERRCODE='23514',CONSTRAINT='ck_provider_snapshot_member_binding';
    END IF;
    SELECT * INTO STRICT v_root FROM ops.import_jobs job
      WHERE job.job_id=v_artifact.root_job_id FOR UPDATE;
    SELECT * INTO STRICT v_child FROM ops.import_jobs job
      WHERE job.job_id=v_artifact.source_job_id FOR UPDATE;
    SELECT * INTO STRICT v_member FROM ops.import_job_datasets member
      WHERE member.import_job_dataset_id=v_artifact.import_job_dataset_id FOR UPDATE;
    IF v_root.kind IS DISTINCT FROM 'provider_feature_load_run'
       OR v_root.dagster_run_id IS DISTINCT FROM v_artifact.dagster_run_id
       OR v_child.parent_job_id IS DISTINCT FROM v_root.job_id
       OR v_child.kind IS DISTINCT FROM 'provider_feature_load'
       OR v_child.dagster_run_id IS DISTINCT FROM v_root.dagster_run_id
       OR v_child.dataset_membership_mode IS DISTINCT FROM 'single'
       OR v_member.job_id IS DISTINCT FROM v_child.job_id
       OR v_member.provider_dataset_id IS DISTINCT FROM v_artifact.provider_dataset_id
       OR v_member.sync_scope IS DISTINCT FROM v_artifact.sync_scope
       OR v_member.operation_key IS DISTINCT FROM v_artifact.operation_key
       OR v_root.cancellation_id IS NOT NULL OR v_child.cancellation_id IS NOT NULL
       OR v_root.quarantined_at IS NOT NULL OR v_child.quarantined_at IS NOT NULL
       OR (SELECT count(*) FROM ops.import_job_datasets member WHERE member.job_id=v_child.job_id)<>1 THEN
        RAISE EXCEPTION 'snapshot seal canonical member changed'
            USING ERRCODE='23514',CONSTRAINT='ck_provider_snapshot_member_binding';
    END IF;
    SELECT * INTO STRICT v_control FROM ops.provider_snapshot_controls control
      WHERE control.snapshot_id=p_snapshot FOR UPDATE;
    IF v_control.executor_generation IS DISTINCT FROM p_generation
       OR v_control.executor_fence IS DISTINCT FROM p_fence THEN
        RAISE EXCEPTION 'snapshot seal executor fence is stale' USING ERRCODE='40001';
    END IF;
    IF v_control.result_sha256 IS DISTINCT FROM p_result_sha
       OR encode(x_extension.digest(v_control.postprocess_receipt,'sha256'),'hex') IS DISTINCT FROM p_postprocess_sha THEN
        RAISE EXCEPTION 'snapshot seal durable receipt changed'
            USING ERRCODE='23514',CONSTRAINT='ck_provider_snapshot_apply_required';
    END IF;
    v_result:=convert_from(v_control.applied_result,'UTF8')::jsonb;
    v_count:=(v_result->'load'->>'curation_input_member_count')::bigint;
    v_hash:=v_result->'load'->>'curation_input_set_hash';
    IF v_result->>'domain' IS DISTINCT FROM 'provider-full-snapshot-apply-result-v1'
       OR v_result->>'version' IS DISTINCT FROM '1'
       OR v_count IS NULL OR v_count<0 OR v_hash IS NULL OR v_hash !~ '^[0-9a-f]{64}$' THEN
        RAISE EXCEPTION 'snapshot original input capture is invalid'
            USING ERRCODE='23514',CONSTRAINT='ck_provider_snapshot_apply_required';
    END IF;
    IF v_control.status='child_sealed' THEN
        -- 미확정 commit 재확인은 원 receipt와 done 상태가 모두 일치할 때만 성공이다.
        IF v_child.status<>'done' OR v_root.status NOT IN ('running','done')
           OR coalesce(v_root.dagster_run_status,'') NOT IN ('STARTED','SUCCESS')
           OR (v_child.payload->>'authoritative_snapshot_complete') IS DISTINCT FROM 'true' THEN
            RAISE EXCEPTION 'snapshot sealed member is not a successful member'
                USING ERRCODE='23514',CONSTRAINT='ck_provider_snapshot_member_binding';
        END IF;
        SELECT receipt.observed_at INTO STRICT o_observed_at
          FROM ops.curation_provider_snapshot_receipts receipt
          WHERE receipt.source_job_id=v_child.job_id AND receipt.root_job_id=v_root.job_id
            AND receipt.provider_dataset_id=v_artifact.provider_dataset_id
            AND receipt.sync_scope=v_artifact.sync_scope AND receipt.operation_key=v_artifact.operation_key
            AND receipt.input_member_count=v_count AND receipt.source_input_set_hash=v_hash;
        IF o_observed_at IS DISTINCT FROM v_control.child_sealed_at THEN
            RAISE EXCEPTION 'snapshot child seal timestamp changed'
                USING ERRCODE='23514',CONSTRAINT='ck_provider_snapshot_member_binding';
        END IF;
        o_replayed:=true;
        RETURN;
    END IF;
    IF v_control.status<>'postprocessed' OR v_control.lease_expires_at<=clock_timestamp()
       OR v_root.status<>'running' OR v_root.dagster_run_status IS DISTINCT FROM 'STARTED'
       OR v_child.status NOT IN ('queued','running') THEN
        RAISE EXCEPTION 'snapshot seal requires live executor and complete postprocess'
            USING ERRCODE='23514',CONSTRAINT='ck_provider_snapshot_apply_required';
    END IF;
    UPDATE ops.provider_snapshot_controls SET seal_txid=txid_current()
      WHERE snapshot_id=p_snapshot;
    CALL feature.seal_provider_curation_snapshot_receipt(
        v_root.job_id,v_artifact.provider_dataset_id,v_artifact.sync_scope,v_artifact.operation_key,
        v_count,v_hash,v_source,o_observed_at,v_entities,v_source_hash);
    IF v_source IS DISTINCT FROM v_child.job_id OR v_source_hash IS DISTINCT FROM v_hash THEN
        RAISE EXCEPTION 'snapshot seal returned a different member'
            USING ERRCODE='23514',CONSTRAINT='ck_provider_snapshot_member_binding';
    END IF;
    CALL ops.finish_provider_feature_membership_command(
        v_root.job_id,v_artifact.provider_dataset_id,v_artifact.sync_scope,v_artifact.operation_key,
        true,o_observed_at,v_changed);
    IF v_changed IS DISTINCT FROM true THEN
        RAISE EXCEPTION 'snapshot child did not transition to done'
            USING ERRCODE='23514',CONSTRAINT='ck_provider_snapshot_member_binding';
    END IF;
    UPDATE ops.provider_snapshot_controls SET status='child_sealed',seal_txid=NULL,
        child_sealed_at=o_observed_at,updated_at=clock_timestamp() WHERE snapshot_id=p_snapshot;
    o_replayed:=false;
END;
$$;
