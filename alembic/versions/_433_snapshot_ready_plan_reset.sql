-- 선택 stale의 전체 rollback 뒤 현재 executor가 정확한 READY binding만 정리한다.
CREATE FUNCTION ops.reset_ready_provider_snapshot_plan(
    p_snapshot uuid,p_generation bigint,p_fence uuid,
    p_expected_attempt uuid,p_expected_owner uuid,p_expected_manifest text
) RETURNS text LANGUAGE plpgsql SECURITY DEFINER SET search_path TO pg_catalog AS $$
DECLARE
    v_dataset bigint;
    v_attempt ops.feature_write_attempts%ROWTYPE;
    v_control ops.provider_snapshot_controls%ROWTYPE;
    v_scope ops.feature_write_dataset_scopes%ROWTYPE;
BEGIN
    IF NOT pg_has_role(session_user,'ktm_curation_provider_executor','member') THEN
        RAISE EXCEPTION 'snapshot reset requires provider executor' USING ERRCODE='42501';
    END IF;
    IF p_snapshot IS NULL OR p_generation IS NULL OR p_generation<1 OR p_fence IS NULL
       OR p_expected_attempt IS NULL OR p_expected_owner IS NULL
       OR p_expected_manifest IS NULL OR p_expected_manifest !~ '^[0-9a-f]{64}$' THEN
        RAISE EXCEPTION 'exact ready snapshot plan required' USING ERRCODE='22023';
    END IF;
    IF current_setting('transaction_isolation')<>'read committed' THEN
        RAISE EXCEPTION 'snapshot reset requires READ COMMITTED' USING ERRCODE='25001';
    END IF;
    PERFORM ops._arm_scoped_feature_write_deadline();
    PERFORM ops.lock_scoped_feature_write_protocol(false);
    SELECT artifact.provider_dataset_id INTO STRICT v_dataset
      FROM ops.provider_snapshot_artifacts artifact WHERE artifact.snapshot_id=p_snapshot;
    -- 외부 dataset의 attempt 행을 잠근 뒤 participant를 늦게 추가하지 않는다.
    SELECT * INTO v_attempt FROM ops.feature_write_attempts attempt
      WHERE attempt.attempt_id=p_expected_attempt;
    IF NOT FOUND OR v_attempt.provider_dataset_id IS DISTINCT FROM v_dataset
       OR v_attempt.regions IS DISTINCT FROM '[]'::jsonb
       OR v_attempt.exclusive_protocol IS DISTINCT FROM false THEN
        RAISE EXCEPTION 'snapshot reset attempt domain changed'
            USING ERRCODE='23514',CONSTRAINT='ck_provider_snapshot_plan_binding';
    END IF;
    -- 430B helper: P SH→actual parent SHARE→own whole scope UPDATE.
    PERFORM ops._lock_scoped_feature_write_scope(v_dataset,'[]'::jsonb,false);
    SELECT * INTO STRICT v_attempt FROM ops.feature_write_attempts attempt
      WHERE attempt.attempt_id=p_expected_attempt FOR UPDATE;
    IF v_attempt.provider_dataset_id IS DISTINCT FROM v_dataset
       OR v_attempt.regions IS DISTINCT FROM '[]'::jsonb
       OR v_attempt.exclusive_protocol IS DISTINCT FROM false
       OR v_attempt.owner IS DISTINCT FROM p_expected_owner
       OR v_attempt.manifest_digest IS DISTINCT FROM p_expected_manifest THEN
        RAISE EXCEPTION 'snapshot reset attempt changed' USING ERRCODE='40001';
    END IF;
    -- 반드시 old attempt 다음 control이다. helper는 P/parent/scope 재진입 및
    -- 현재 executor·member 활동성 검증을 담당하며 root/member/quota 행을 잠그지 않는다.
    v_control:=ops._lock_provider_snapshot_executor(p_snapshot,p_generation,p_fence);
    IF v_control.status IS DISTINCT FROM 'prepared' THEN
        RAISE EXCEPTION 'completed snapshot result cannot be replanned'
            USING ERRCODE='23514',CONSTRAINT='ck_provider_snapshot_apply_required';
    END IF;
    IF v_control.attempt_id IS NULL THEN
        -- 응답 유실일 수 있지만 임의의 옛 cancelled attempt로 성공을 증명하지 않는다.
        -- 변경0. caller가 SDK0 read로 상태를 읽은 뒤 새 계획을 결정한다.
        RETURN 'needs_read';
    END IF;
    IF v_control.attempt_id IS DISTINCT FROM p_expected_attempt
       OR v_control.attempt_owner IS DISTINCT FROM p_expected_owner
       OR v_control.manifest_digest IS DISTINCT FROM p_expected_manifest THEN
        RAISE EXCEPTION 'snapshot reset binding changed' USING ERRCODE='40001';
    END IF;
    -- old apply는 같은 scope/attempt를 끝까지 잠근다. 기다리는 동안 commit했다면
    -- 위 prepared 검사가 거부하며, rollback하여 READY인 현재 owner만 정리한다.
    IF v_attempt.status IS DISTINCT FROM 'ready'
       OR v_attempt.apply_txid IS NOT NULL OR v_attempt.result_digest IS NOT NULL THEN
        RAISE EXCEPTION 'snapshot reset requires an unapplied ready plan'
            USING ERRCODE='23514',CONSTRAINT='ck_provider_snapshot_plan_binding';
    END IF;
    SELECT * INTO STRICT v_scope FROM ops.feature_write_dataset_scopes
      WHERE provider_dataset_id=v_dataset;
    IF v_scope.epoch IS DISTINCT FROM v_attempt.dataset_epoch
       OR v_scope.owner IS DISTINCT FROM p_expected_attempt THEN
        RAISE EXCEPTION 'snapshot ready plan scope changed' USING ERRCODE='40001';
    END IF;
    -- kernel lease를 연장하거나 다른 executor로 인계하지 않는다. 현재 executor fence와
    -- 정확한 bound READY의 rowlock 증거로만 취소하고 새 attempt를 계획한다.
    IF NOT ops.cancel_scoped_feature_write(p_expected_attempt,p_expected_owner) THEN
        RAISE EXCEPTION 'snapshot kernel plan was not cancelled' USING ERRCODE='40001';
    END IF;
    UPDATE ops.provider_snapshot_controls
      SET attempt_id=NULL,attempt_owner=NULL,manifest_digest=NULL,updated_at=clock_timestamp()
      WHERE snapshot_id=p_snapshot;
    RETURN 'reset';
END;
$$;
