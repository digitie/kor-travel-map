-- 원 weather/transport/Feature 이력은 지우지 않는다. 종결된 복구 임시 입력만 고정7일 보존한다.
CREATE FUNCTION ops.collect_expired_provider_snapshots(p_limit integer) RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER SET search_path TO pg_catalog AS $$
DECLARE
    v_rows jsonb;
    v_row jsonb;
    v_quota bigint;
    v_count bigint;
    v_bytes bigint;
    v_limit ops.provider_snapshot_quota_limits%ROWTYPE;
    v_deleted integer:=0;
BEGIN
    IF NOT pg_has_role(session_user,'ktm_curation_provider_executor','member') THEN
        RAISE EXCEPTION 'snapshot cleanup requires provider executor' USING ERRCODE='42501';
    END IF;
    IF p_limit IS NULL OR p_limit NOT BETWEEN 1 AND 16 THEN
        RAISE EXCEPTION 'snapshot cleanup limit must be1..16' USING ERRCODE='22023';
    END IF;
    IF current_setting('transaction_isolation')<>'read committed' THEN
        RAISE EXCEPTION 'snapshot cleanup requires READ COMMITTED' USING ERRCODE='25001';
    END IF;
    PERFORM ops._arm_scoped_feature_write_deadline();
    PERFORM ops.lock_scoped_feature_write_protocol(true);
    SELECT coalesce(jsonb_agg(to_jsonb(candidate)),'[]'::jsonb) INTO v_rows FROM (
        SELECT artifact.snapshot_id,artifact.provider_dataset_id,reservation.reserved_bytes
        FROM ops.provider_snapshot_artifacts artifact
        JOIN ops.provider_snapshot_controls control USING(snapshot_id)
        JOIN ops.provider_snapshot_quota_reservations reservation USING(snapshot_id)
        JOIN ops.import_jobs root ON root.job_id=artifact.root_job_id
        JOIN ops.import_jobs child ON child.job_id=artifact.source_job_id
        WHERE root.kind='provider_feature_load_run' AND child.kind='provider_feature_load'
          AND child.parent_job_id=root.job_id AND child.dagster_run_id=root.dagster_run_id
          AND root.dagster_run_id=artifact.dagster_run_id
          AND root.quarantined_at IS NULL AND child.quarantined_at IS NULL
          AND root.status IN ('done','failed','cancelled')
          AND root.dagster_run_status IN ('SUCCESS','FAILURE','CANCELED')
          AND child.status IN ('done','failed','cancelled')
          AND root.finished_at IS NOT NULL AND child.finished_at IS NOT NULL
          AND control.lease_expires_at<=clock_timestamp()
          AND greatest(artifact.created_at,control.updated_at,root.finished_at,child.finished_at)
              <clock_timestamp()-interval '7 days'
          AND reservation.provider_dataset_id=artifact.provider_dataset_id
        ORDER BY artifact.created_at,artifact.snapshot_id LIMIT p_limit
    ) candidate;
    IF jsonb_array_length(v_rows)=0 THEN RETURN 0; END IF;
    -- 모든 등록은 P SH라 이 P EX와 겹치지 않는다. 계수는 전역0→정렬dataset 순서로 잠근다.
    FOR v_quota IN SELECT quota FROM (
        SELECT 0::bigint AS quota UNION
        SELECT (value->>'provider_dataset_id')::bigint FROM jsonb_array_elements(v_rows)
    ) keys ORDER BY quota LOOP
        SELECT * INTO STRICT v_limit FROM ops.provider_snapshot_quota_limits quota
          WHERE quota.quota_key=v_quota FOR UPDATE;
        SELECT count(*),coalesce(sum((value->>'reserved_bytes')::bigint),0)
          INTO v_count,v_bytes FROM jsonb_array_elements(v_rows)
          WHERE v_quota=0 OR (value->>'provider_dataset_id')::bigint=v_quota;
        IF v_limit.used_rows<v_count OR v_limit.used_bytes<v_bytes THEN
            RAISE EXCEPTION 'snapshot cleanup quota ledger is inconsistent'
                USING ERRCODE='23514',CONSTRAINT='ck_provider_snapshot_quota_available';
        END IF;
    END LOOP;
    FOR v_row IN SELECT value FROM jsonb_array_elements(v_rows) LOOP
        DELETE FROM ops.provider_snapshot_controls WHERE snapshot_id=(v_row->>'snapshot_id')::uuid;
        DELETE FROM ops.provider_snapshot_quota_reservations WHERE snapshot_id=(v_row->>'snapshot_id')::uuid;
        DELETE FROM ops.provider_snapshot_artifacts WHERE snapshot_id=(v_row->>'snapshot_id')::uuid;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'snapshot cleanup input disappeared' USING ERRCODE='40001';
        END IF;
        UPDATE ops.provider_snapshot_quota_limits SET used_rows=used_rows-1,
            used_bytes=used_bytes-(v_row->>'reserved_bytes')::bigint
          WHERE quota_key=0 OR quota_key=(v_row->>'provider_dataset_id')::bigint;
        v_deleted:=v_deleted+1;
    END LOOP;
    RETURN v_deleted;
END;
$$;
