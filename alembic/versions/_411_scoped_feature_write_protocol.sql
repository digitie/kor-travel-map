CREATE FUNCTION ops.lock_scoped_feature_write_protocol(p_exclusive boolean)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path TO pg_catalog AS $$
BEGIN
    IF p_exclusive IS NULL THEN
        RAISE EXCEPTION 'protocol mode is required' USING ERRCODE='23514';
    END IF;
    -- 두 정수의 고정 gate 한 개만 사용한다. Feature hash별 잠금을 만들지 않는다.
    IF p_exclusive AND EXISTS (
        SELECT 1 FROM pg_locks WHERE locktype='advisory' AND pid=pg_backend_pid()
        AND classid=1369104691::oid AND objid=115::oid AND objsubid=2
        AND mode='ShareLock' AND granted
    ) AND NOT EXISTS (
        SELECT 1 FROM pg_locks WHERE locktype='advisory' AND pid=pg_backend_pid()
        AND classid=1369104691::oid AND objid=115::oid AND objsubid=2
        AND mode='ExclusiveLock' AND granted
    ) THEN
        RAISE EXCEPTION 'protocol share to exclusive upgrade requires replan' USING ERRCODE='23514';
    END IF;
    IF p_exclusive THEN
        PERFORM pg_advisory_xact_lock(1369104691,115);
    ELSE
        PERFORM pg_advisory_xact_lock_shared(1369104691,115);
    END IF;
END;
$$;
