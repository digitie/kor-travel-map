-- advisory protocol gate의 소유와 snapshot 신선도는 다른 증거다.
-- 이 행은 최초 정책 활성화 전의 RR transaction이 새 active pointer를 못 보는 우회를 막는다.
CREATE FUNCTION feature.lock_provider_field_policy_epoch() RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path TO pg_catalog AS $$
DECLARE v_epoch bigint;
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_locks WHERE pid=pg_backend_pid()
        AND locktype='advisory' AND granted AND classid=1369104691 AND objid=115 AND objsubid=2
        AND mode IN ('ShareLock','ExclusiveLock')) THEN
        RAISE EXCEPTION 'policy epoch entry requires the protocol gate first' USING ERRCODE='23514';
    END IF;
    SELECT epoch INTO STRICT v_epoch FROM feature.provider_field_policy_epoch
        WHERE singleton FOR SHARE;
END;
$$;
