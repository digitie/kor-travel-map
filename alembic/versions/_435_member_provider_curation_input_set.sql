
DECLARE
    v_child uuid;
    v_member uuid;
    v_run text;
BEGIN
    IF p_stage IS NULL OR p_stage NOT IN ('child','root') THEN
        RAISE EXCEPTION 'explicit child/root capture stage required' USING ERRCODE='22023';
    END IF;
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

    -- 435 ADR-117: 스냅샷 artifact 경로는 퇴역했다. 모든 member는 P EX 아래 현재 집합을 봉인한다.
    RETURN QUERY SELECT current_set.source_entity_count,current_set.input_member_count,
                        current_set.last_source_modified_at,current_set.source_input_set_hash
        FROM feature.current_provider_curation_input_set(p_dataset) current_set;
END;
