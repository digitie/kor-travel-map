-- SDK를 다시 호출하기 전에 member로 찾는 private 읽기다. 반환값 자체는 apply/seal 권위가 아니다.
CREATE FUNCTION ops.read_provider_snapshot_for_member(p_root uuid,p_child uuid,p_member uuid)
RETURNS TABLE(
    snapshot_id uuid,artifact_payload bytea,artifact_sha256 text,
    observation_context bytea,context_sha256 text,native_input_digest text,
    snapshot_status text,applied_result bytea,postprocess_receipt bytea,
    lease_expires_at timestamptz,root_status text,child_status text,cancellation_present boolean,
    attempt_id uuid,attempt_owner uuid,manifest_digest text,
    kernel_status text,kernel_input_digest text,kernel_lease_expires_at timestamptz
) LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path TO pg_catalog AS $$
DECLARE
    v_member record;
    v_artifact record;
BEGIN
    IF NOT pg_has_role(session_user,'ktm_curation_provider_executor','member') THEN
        RAISE EXCEPTION 'snapshot read requires provider executor' USING ERRCODE='42501';
    END IF;
    IF p_root IS NULL OR p_child IS NULL OR p_member IS NULL THEN
        RAISE EXCEPTION 'canonical snapshot member IDs required' USING ERRCODE='22023';
    END IF;
    SELECT member.provider_dataset_id,member.sync_scope,member.operation_key,
           root.dagster_run_id,root.status AS root_status,child.status AS child_status,
           (root.cancellation_id IS NOT NULL OR child.cancellation_id IS NOT NULL
            OR root.quarantined_at IS NOT NULL OR child.quarantined_at IS NOT NULL) AS blocked
      INTO STRICT v_member FROM ops.import_jobs root
      JOIN ops.import_jobs child ON child.parent_job_id=root.job_id
      JOIN ops.import_job_datasets member ON member.job_id=child.job_id
      WHERE root.job_id=p_root AND root.kind='provider_feature_load_run'
        AND child.job_id=p_child AND child.kind='provider_feature_load'
        AND child.dagster_run_id=root.dagster_run_id
        AND member.import_job_dataset_id=p_member;
    -- root/domain 조건으로 먼저 거르면 불일치를 artifact 부재로 오인할 수 있다.
    SELECT artifact.snapshot_id,artifact.root_job_id,artifact.source_job_id,
           artifact.provider_dataset_id,artifact.sync_scope,artifact.operation_key,
           artifact.dagster_run_id,artifact.capture_profile
      INTO v_artifact FROM ops.provider_snapshot_artifacts artifact
      WHERE artifact.import_job_dataset_id=p_member;
    IF NOT FOUND THEN
        RETURN;
    END IF;
    IF v_artifact.root_job_id IS DISTINCT FROM p_root
       OR v_artifact.source_job_id IS DISTINCT FROM p_child
       OR v_artifact.provider_dataset_id IS DISTINCT FROM v_member.provider_dataset_id
       OR v_artifact.sync_scope IS DISTINCT FROM v_member.sync_scope
       OR v_artifact.operation_key IS DISTINCT FROM v_member.operation_key
       OR v_artifact.dagster_run_id IS DISTINCT FROM v_member.dagster_run_id
       OR v_artifact.capture_profile IS DISTINCT FROM 'bounded-place-v1' THEN
        RAISE EXCEPTION 'snapshot read does not match its canonical member'
            USING ERRCODE='23514',CONSTRAINT='ck_provider_snapshot_member_binding';
    END IF;
    IF NOT EXISTS(SELECT 1 FROM ops.provider_snapshot_controls control
                  WHERE control.snapshot_id=v_artifact.snapshot_id) THEN
        RAISE EXCEPTION 'registered snapshot control is missing'
            USING ERRCODE='23514',CONSTRAINT='ck_provider_snapshot_apply_required';
    END IF;
    IF EXISTS(
        SELECT 1 FROM ops.provider_snapshot_controls control
        LEFT JOIN ops.feature_write_attempts attempt ON attempt.attempt_id=control.attempt_id
        WHERE control.snapshot_id=v_artifact.snapshot_id AND control.attempt_id IS NOT NULL
          AND (attempt.attempt_id IS NULL OR attempt.owner IS DISTINCT FROM control.attempt_owner
               OR attempt.manifest_digest IS DISTINCT FROM control.manifest_digest
               OR attempt.provider_dataset_id IS DISTINCT FROM v_member.provider_dataset_id
               OR (control.status IN ('applied','postprocessed','child_sealed')
                   AND attempt.status IS DISTINCT FROM 'completed'))
    ) THEN
        RAISE EXCEPTION 'snapshot kernel binding is inconsistent'
            USING ERRCODE='23514',CONSTRAINT='ck_provider_snapshot_plan_binding';
    END IF;
    -- 같은 STABLE statement snapshot에서 immutable 입력과 mutable 상태를 함께 읽는다.
    -- lease nonce는 반환하지 않는다. 새 실행자는 typed claim으로만 권위를 얻는다.
    RETURN QUERY SELECT artifact.snapshot_id,artifact.artifact_payload,artifact.artifact_sha256,
           artifact.observation_context,artifact.context_sha256,artifact.native_input_digest,
           control.status,control.applied_result,control.postprocess_receipt,
           control.lease_expires_at,v_member.root_status,v_member.child_status,v_member.blocked,
           control.attempt_id,control.attempt_owner,control.manifest_digest,
           attempt.status,attempt.input_digest,attempt.lease_until
      FROM ops.provider_snapshot_artifacts artifact
      JOIN ops.provider_snapshot_controls control USING(snapshot_id)
      LEFT JOIN ops.feature_write_attempts attempt ON attempt.attempt_id=control.attempt_id
      WHERE artifact.snapshot_id=v_artifact.snapshot_id;
END;
$$;
