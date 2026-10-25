-- P 보유와 현재 TX의 applying SH 권위만 읽는다. 새 잠금을 취득하지 않는다.
CREATE FUNCTION feature._strict_sh_data_context(p_allow_shared boolean)
RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path TO pg_catalog AS $$
DECLARE
    v_exclusive boolean;
    v_shared boolean;
    v_attempt ops.feature_write_attempts%ROWTYPE;
    v_candidate ops.feature_write_attempts%ROWTYPE;
    v_count integer := 0;
    v_scope ops.feature_write_dataset_scopes%ROWTYPE;
    v_region jsonb;
    v_index integer := 0;
    v_epoch bigint;
    v_owner uuid;
BEGIN
    IF p_allow_shared IS NULL THEN
        RAISE EXCEPTION 'strict data prefix mode is required'
            USING ERRCODE='23514', CONSTRAINT='ck_strict_data_protocol_prefix';
    END IF;
    SELECT coalesce(bool_or(mode='ExclusiveLock'),false),
           coalesce(bool_or(mode='ShareLock'),false)
      INTO v_exclusive,v_shared
      FROM pg_locks
     WHERE pid=pg_backend_pid() AND locktype='advisory' AND granted
       AND database=(SELECT oid FROM pg_database WHERE datname=current_database())
       AND classid=1369104691 AND objid=115 AND objsubid=2;
    IF v_exclusive THEN RETURN NULL; END IF;
    IF NOT v_shared OR NOT p_allow_shared THEN
        RAISE EXCEPTION 'data mutation requires its protocol prefix before epoch or rows'
            USING ERRCODE='23514', CONSTRAINT='ck_strict_data_protocol_prefix';
    END IF;
    -- 임의 GUC·ready·completed는 권위가 아니다. 실제 begin이 남긴 현재 TX만 읽는다.
    FOR v_candidate IN
        SELECT a.* FROM ops.feature_write_attempts a
         WHERE a.status='applying' AND NOT a.exclusive_protocol
           AND a.apply_txid=txid_current_if_assigned()
         ORDER BY a.attempt_id LIMIT 2
    LOOP
        v_count:=v_count+1;
        v_attempt:=v_candidate;
    END LOOP;
    IF v_count<>1 OR v_attempt.manifest_digest IS NULL THEN
        RAISE EXCEPTION 'shared data mutation requires one current applying manifest'
            USING ERRCODE='23514', CONSTRAINT='ck_strict_data_applying_context';
    END IF;
    SELECT * INTO v_scope FROM ops.feature_write_dataset_scopes
     WHERE provider_dataset_id=v_attempt.provider_dataset_id;
    IF NOT FOUND OR v_scope.epoch IS DISTINCT FROM v_attempt.dataset_epoch
       OR (jsonb_array_length(v_attempt.regions)=0
           AND v_scope.owner IS DISTINCT FROM v_attempt.attempt_id) THEN
        RAISE EXCEPTION 'shared data scope owner or epoch changed; replan'
            USING ERRCODE='40001', CONSTRAINT='ck_strict_data_scope_context';
    END IF;
    FOR v_region IN SELECT value FROM jsonb_array_elements(v_attempt.regions)
    LOOP
        v_index:=v_index+1;
        SELECT epoch,owner INTO v_epoch,v_owner FROM ops.feature_write_region_scopes
         WHERE provider_dataset_id=v_attempt.provider_dataset_id
           AND scope_version=(v_region->>'scope_version')::integer
           AND region_key=v_region->>'region_key';
        IF NOT FOUND OR v_epoch IS DISTINCT FROM v_attempt.region_epochs[v_index]
           OR v_owner IS DISTINCT FROM v_attempt.attempt_id THEN
            RAISE EXCEPTION 'shared data region owner or epoch changed; replan'
                USING ERRCODE='40001', CONSTRAINT='ck_strict_data_scope_context';
        END IF;
    END LOOP;
    -- 현재 applying TX는 기존 kernel처럼 lease 경과만으로 자기 권위를 잃지 않는다.
    -- frozen manifest는 typed kernel만 쓸 수 있다. 이 helper는 nonce/물리 prelock 증명이 아니다.
    RETURN v_attempt.attempt_id;
END;
$$;
