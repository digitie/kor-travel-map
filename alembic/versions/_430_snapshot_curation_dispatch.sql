-- child/root prefix 완료 후 새 RC statement에서만 부른다. generic EX 의미는 보존한다.
CREATE FUNCTION feature._member_provider_curation_input_set(
    p_root uuid,p_dataset bigint,p_scope text,p_operation text
) RETURNS TABLE(
    source_entity_count bigint,input_member_count bigint,
    last_source_modified_at date,source_input_set_hash text
) LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path TO pg_catalog AS $$
DECLARE
    v_child uuid;
    v_member uuid;
    v_run text;
    v_artifact record;
    v_state record;
    v_capture record;
BEGIN
    IF current_setting('transaction_isolation')<>'read committed' THEN
        RAISE EXCEPTION 'member capture requires fresh READ COMMITTED'
            USING ERRCODE='25001';
    END IF;
    IF NOT EXISTS(
        SELECT 1 FROM pg_catalog.pg_locks
        WHERE pid=pg_backend_pid() AND locktype='advisory' AND granted
          AND database=(SELECT oid FROM pg_catalog.pg_database WHERE datname=current_database())
          AND classid=1369104691 AND objid=115 AND objsubid=2 AND mode='ExclusiveLock'
    ) OR NOT EXISTS(
        SELECT 1 FROM pg_catalog.pg_locks
        WHERE pid=pg_backend_pid() AND locktype='advisory' AND granted
          AND database=(SELECT oid FROM pg_catalog.pg_database WHERE datname=current_database())
          AND classid=1590807301 AND objid=1746797985 AND objsubid=1 AND mode='ExclusiveLock'
    ) THEN
        RAISE EXCEPTION 'member capture requires its existing finalization prefix'
            USING ERRCODE='23514',CONSTRAINT='ck_provider_tracking_prefix';
    END IF;
    -- membership를 먼저 정본 resolver로 읽는다. domain mismatch를 행 부재로 분류하지 않는다.
    SELECT child.job_id,member.import_job_dataset_id,root.dagster_run_id
      INTO STRICT v_child,v_member,v_run
    FROM ops.import_jobs root
    JOIN ops.import_jobs child ON child.parent_job_id=root.job_id
    JOIN ops.import_job_datasets member ON member.job_id=child.job_id
    WHERE root.job_id=p_root AND root.kind='provider_feature_load_run'
      AND child.kind='provider_feature_load' AND child.dagster_run_id=root.dagster_run_id
      AND member.provider_dataset_id=p_dataset AND member.sync_scope=p_scope
      AND member.operation_key=p_operation;

    SELECT artifact.snapshot_id,artifact.root_job_id,artifact.source_job_id,
           artifact.provider_dataset_id,artifact.sync_scope,artifact.operation_key,
           artifact.dagster_run_id,artifact.capture_profile
      INTO v_artifact
    FROM ops.provider_snapshot_artifacts artifact WHERE artifact.import_job_dataset_id=v_member;
    IF NOT FOUND THEN
        -- 새 profile의 control이 전혀 없는 기존 EX만 기존 non-place aggregate를 유지한다.
        RETURN QUERY SELECT current_set.source_entity_count,current_set.input_member_count,
                            current_set.last_source_modified_at,current_set.source_input_set_hash
            FROM feature.current_provider_curation_input_set(p_dataset) current_set;
        RETURN;
    END IF;
    IF v_artifact.root_job_id IS DISTINCT FROM p_root
       OR v_artifact.source_job_id IS DISTINCT FROM v_child
       OR v_artifact.provider_dataset_id IS DISTINCT FROM p_dataset
       OR v_artifact.sync_scope IS DISTINCT FROM p_scope
       OR v_artifact.operation_key IS DISTINCT FROM p_operation
       OR v_artifact.dagster_run_id IS DISTINCT FROM v_run
       OR v_artifact.capture_profile IS DISTINCT FROM 'bounded-place-v1' THEN
        RAISE EXCEPTION 'snapshot profile does not match its canonical member'
            USING ERRCODE='23514',CONSTRAINT='ck_provider_snapshot_member_binding';
    END IF;
    SELECT control.status,(control.applied_result IS NOT NULL) AS result_present
      INTO v_state FROM ops.provider_snapshot_controls control
      WHERE control.snapshot_id=v_artifact.snapshot_id;
    IF NOT FOUND OR v_state.status NOT IN ('applied','postprocessed','child_sealed')
       OR NOT v_state.result_present THEN
        RAISE EXCEPTION 'snapshot apply result is not durably complete'
            USING ERRCODE='23514',CONSTRAINT='ck_provider_snapshot_apply_required';
    END IF;
    SELECT * INTO STRICT v_capture FROM feature._bounded_provider_curation_input_set(p_dataset);
    IF NOT v_capture.capture_complete THEN
        RAISE EXCEPTION 'bounded snapshot capture is no longer supported'
            USING ERRCODE='23514',CONSTRAINT='ck_provider_snapshot_bounded_capture';
    END IF;
    RETURN QUERY SELECT v_capture.source_entity_count,v_capture.input_member_count,
                        v_capture.last_source_modified_at,v_capture.source_input_set_hash;
END;
$$;
