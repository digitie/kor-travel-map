CREATE FUNCTION feature.provider_field_policy_statement_barrier() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path TO pg_catalog AS $$
DECLARE v_epoch bigint;
BEGIN
    -- row·source 잠금 전에 statement당 한 번만 실행한다. 오래된 RR은 여기서 40001이다.
    SELECT epoch INTO STRICT v_epoch FROM feature.provider_field_policy_epoch
        WHERE singleton FOR SHARE;
    IF v_epoch > 0 AND NOT EXISTS (SELECT 1 FROM pg_locks WHERE pid=pg_backend_pid()
        AND locktype='advisory' AND granted AND classid=1369104691 AND objid=115 AND objsubid=2
        AND mode IN ('ShareLock','ExclusiveLock')) THEN
        -- 구형 writer의 늦은 gate 획득/SH→EX 승격으로 우회하지 않는다.
        RAISE EXCEPTION 'legacy writer cannot mutate after scalar policy cutover' USING ERRCODE='23514';
    END IF;
    RETURN NULL;
END;
$$;
