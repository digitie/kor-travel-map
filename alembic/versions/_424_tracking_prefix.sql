-- Provider tracking prefix: 데이터 P와 lineage L의 취득 순서만 고정한다.
-- snapshot/isolation/데이터 적격성 권위는 바꾸지 않는다.
CREATE FUNCTION ops.lock_provider_feature_tracking_protocol(p_finalizing boolean)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path TO pg_catalog AS $$
DECLARE
    v_protocol_held boolean;
    v_protocol_exclusive boolean;
    v_lineage_held boolean;
    v_lock_timeout text := current_setting('lock_timeout');
BEGIN
    IF p_finalizing IS NULL THEN
        RAISE EXCEPTION 'provider tracking prefix mode must not be null'
            USING ERRCODE='22023';
    END IF;
    SELECT COALESCE(bool_or(mode IN ('ShareLock','ExclusiveLock')),false),
           COALESCE(bool_or(mode='ExclusiveLock'),false)
    INTO v_protocol_held,v_protocol_exclusive
    FROM pg_catalog.pg_locks
    WHERE pid=pg_backend_pid() AND locktype='advisory' AND granted
      AND database=(SELECT oid FROM pg_catalog.pg_database WHERE datname=current_database())
      AND classid=1369104691 AND objid=115 AND objsubid=2;
    -- canonical advisory_lock_key('kortravelmap:pipeline-lineage:mutation'):
    -- unsigned BLAKE2b64 - 2^63 = 6832465333779826081; bigint lock subid=1.
    SELECT EXISTS(
        SELECT 1 FROM pg_catalog.pg_locks
        WHERE pid=pg_backend_pid() AND locktype='advisory' AND granted
          AND database=(SELECT oid FROM pg_catalog.pg_database WHERE datname=current_database())
          AND classid=1590807301 AND objid=1746797985 AND objsubid=1
          AND mode='ExclusiveLock'
    ) INTO v_lineage_held;
    IF p_finalizing AND v_lineage_held AND NOT v_protocol_exclusive THEN
        RAISE EXCEPTION 'provider finalization cannot acquire protocol after lineage'
            USING ERRCODE='23514',CONSTRAINT='ck_provider_tracking_prefix';
    END IF;
    IF NOT p_finalizing AND v_protocol_held
       AND NOT (v_protocol_exclusive AND v_lineage_held) THEN
        RAISE EXCEPTION 'provider leaf cannot acquire lineage after a data writer'
            USING ERRCODE='23514',CONSTRAINT='ck_provider_tracking_prefix';
    END IF;
    -- 기존 유한 caller timeout은 보존한다. 미설정 direct SQL의 새 L 대기만 유한화한다.
    IF current_setting('lock_timeout')='0' THEN
        PERFORM set_config('lock_timeout','1s',true);
    END IF;
    IF p_finalizing THEN
        PERFORM ops.lock_scoped_feature_write_protocol(true);
    END IF;
    -- 보유 관측이 session lock이어도 성공 경로에는 항상 xact L을 재확보한다.
    -- 관측만으로 session/xact의 과거 취득 순서를 attest하지 않는다.
    PERFORM pg_advisory_xact_lock(6832465333779826081::bigint);
    PERFORM set_config('lock_timeout',v_lock_timeout,true);
EXCEPTION WHEN OTHERS THEN
    PERFORM set_config('lock_timeout',v_lock_timeout,true);
    RAISE;
END;
$$;
