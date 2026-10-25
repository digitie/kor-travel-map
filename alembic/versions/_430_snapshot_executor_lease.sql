-- 미호출 조각. Root의430 wrapper가 owner/의존EXEC/raw권한회수와 함께 설치한다.
CREATE FUNCTION ops.claim_provider_snapshot_executor(
    p_snapshot uuid,p_artifact_sha text,p_context_sha text,p_lease_seconds integer,
    p_generation bigint DEFAULT NULL,p_fence uuid DEFAULT NULL
) RETURNS TABLE(generation bigint,fence uuid,lease_expires_at timestamptz,snapshot_status text)
LANGUAGE plpgsql SECURITY DEFINER SET search_path TO pg_catalog AS $$
DECLARE
    v_artifact record;
    v_control ops.provider_snapshot_controls%ROWTYPE;
    v_now timestamptz;
    v_generation bigint;
    v_fence uuid;
BEGIN
    IF NOT pg_has_role(session_user,'ktm_curation_provider_executor','member') THEN
        RAISE EXCEPTION 'snapshot executor requires provider executor'
            USING ERRCODE='42501';
    END IF;
    IF p_snapshot IS NULL OR p_artifact_sha IS NULL OR p_context_sha IS NULL
       OR p_artifact_sha !~ '^[0-9a-f]{64}$' OR p_context_sha !~ '^[0-9a-f]{64}$'
       OR p_lease_seconds IS NULL OR p_lease_seconds NOT BETWEEN 5 AND 300
       OR ((p_generation IS NULL)<>(p_fence IS NULL)) THEN
        RAISE EXCEPTION 'invalid snapshot executor claim'
            USING ERRCODE='22023';
    END IF;
    IF current_setting('transaction_isolation')<>'read committed' THEN
        RAISE EXCEPTION 'snapshot executor requires READ COMMITTED'
            USING ERRCODE='25001';
    END IF;
    PERFORM ops._arm_scoped_feature_write_deadline();
    PERFORM ops.lock_scoped_feature_write_protocol(false);
    -- artifact는 immutable이다. 큰 bytea 대신 잠금 순서에 필요한 고정 metadata만 읽는다.
    SELECT artifact.root_job_id,artifact.source_job_id,artifact.import_job_dataset_id,
           artifact.provider_dataset_id,artifact.sync_scope,artifact.operation_key,
           artifact.dagster_run_id,artifact.artifact_sha256,artifact.context_sha256
      INTO STRICT v_artifact FROM ops.provider_snapshot_artifacts artifact
      WHERE artifact.snapshot_id=p_snapshot;
    IF v_artifact.artifact_sha256 IS DISTINCT FROM p_artifact_sha
       OR v_artifact.context_sha256 IS DISTINCT FROM p_context_sha THEN
        RAISE EXCEPTION 'snapshot input does not match the registered member'
            USING ERRCODE='23514',CONSTRAINT='ck_provider_snapshot_member_binding';
    END IF;
    PERFORM ops._lock_scoped_feature_write_scope(v_artifact.provider_dataset_id,'[]'::jsonb,false);
    -- P SH는 terminal/cancel을, own scope X는 apply와 다른 lease 변경을 먼저 배제한다.
    -- root/member tuple 잠금이나 quota 행을 뒤늦게 취득하지 않는다.
    IF NOT EXISTS(
        SELECT 1 FROM ops.import_jobs root
        JOIN ops.import_jobs child ON child.parent_job_id=root.job_id
        JOIN ops.import_job_datasets member ON member.job_id=child.job_id
        JOIN provider_sync.provider_datasets dataset ON dataset.provider_dataset_id=member.provider_dataset_id
        JOIN provider_sync.provider_dataset_operations operation
          ON operation.provider_dataset_id=member.provider_dataset_id AND operation.operation_key=member.operation_key
        WHERE root.job_id=v_artifact.root_job_id AND root.kind='provider_feature_load_run'
          AND root.status='running' AND root.dagster_run_status='STARTED'
          AND root.dagster_run_id=v_artifact.dagster_run_id
          AND root.cancellation_id IS NULL AND root.quarantined_at IS NULL
          AND child.job_id=v_artifact.source_job_id AND child.kind='provider_feature_load'
          AND child.status IN ('queued','running') AND child.dagster_run_id=root.dagster_run_id
          AND child.cancellation_id IS NULL AND child.quarantined_at IS NULL
          AND child.dataset_membership_mode='single'
          AND member.import_job_dataset_id=v_artifact.import_job_dataset_id
          AND member.provider_dataset_id=v_artifact.provider_dataset_id
          AND member.sync_scope=v_artifact.sync_scope AND member.operation_key=v_artifact.operation_key
          AND dataset.is_active AND operation.is_enabled
          AND (SELECT count(*) FROM ops.import_job_datasets all_members WHERE all_members.job_id=child.job_id)=1
    ) THEN
        RAISE EXCEPTION 'snapshot executor member is no longer active'
            USING ERRCODE='23514',CONSTRAINT='ck_provider_snapshot_member_binding';
    END IF;
    SELECT * INTO STRICT v_control FROM ops.provider_snapshot_controls control
        WHERE control.snapshot_id=p_snapshot FOR UPDATE;
    v_now:=clock_timestamp();
    IF p_generation IS NOT NULL THEN
        -- 오래된 token을 새 handoff 권위로 자동 변환하지 않는다.
        IF p_generation<>v_control.executor_generation OR p_fence<>v_control.executor_fence
           OR v_control.lease_expires_at<=v_now THEN
            RAISE EXCEPTION 'snapshot executor fence is stale'
                USING ERRCODE='40001';
        END IF;
        v_generation:=v_control.executor_generation;
        v_fence:=v_control.executor_fence;
    ELSE
        IF v_control.lease_expires_at>v_now THEN
            RAISE EXCEPTION 'snapshot executor lease remains active'
                USING ERRCODE='55P03';
        END IF;
        IF v_control.executor_generation=9223372036854775807 THEN
            RAISE EXCEPTION 'snapshot executor generation exhausted'
                USING ERRCODE='54000';
        END IF;
        v_generation:=v_control.executor_generation+1;
        v_fence:=x_extension.gen_random_uuid();
    END IF;
    UPDATE ops.provider_snapshot_controls control
       SET executor_generation=v_generation,executor_fence=v_fence,
           lease_expires_at=v_now+make_interval(secs=>p_lease_seconds),updated_at=v_now
       WHERE control.snapshot_id=p_snapshot;
    RETURN QUERY SELECT v_generation,v_fence,v_now+make_interval(secs=>p_lease_seconds),v_control.status;
END;
$$;
