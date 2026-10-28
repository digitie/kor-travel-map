
DECLARE v_prior_lock_timeout text;
BEGIN
    IF p_exclusive IS NULL THEN
        RAISE EXCEPTION 'protocol mode is required' USING ERRCODE='23514';
    END IF;
    -- 435 ADR-117: 공유(SH) 모드는 퇴역했다. P는 배타 전용 bulk gate다.
    IF NOT p_exclusive THEN
        RAISE EXCEPTION 'shared protocol mode was retired (ADR-117)' USING ERRCODE='23514';
    END IF;
    IF EXISTS (
        SELECT 1 FROM pg_locks WHERE locktype='advisory' AND pid=pg_backend_pid()
        AND classid=1369104691::oid AND objid=115::oid AND objsubid=2
        AND mode='ExclusiveLock' AND granted
    ) THEN
        -- pg_locks는 session/xact를 구별하지 않는다. 반드시 xact 소유를 덧붙인다.
        PERFORM pg_advisory_xact_lock(1369104691,115);
        RETURN;
    END IF;
    -- 두 정수의 고정 gate 한 개만 사용한다. Feature hash별 잠금을 만들지 않는다.
    SELECT setting INTO v_prior_lock_timeout FROM pg_settings WHERE name='lock_timeout';
    IF v_prior_lock_timeout='0' THEN PERFORM set_config('lock_timeout','1000',true); END IF;
    PERFORM pg_advisory_xact_lock(1369104691,115);
    IF v_prior_lock_timeout='0' THEN PERFORM set_config('lock_timeout',v_prior_lock_timeout,true); END IF;
END;
