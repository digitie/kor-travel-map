CREATE FUNCTION ops._arm_scoped_feature_write_deadline()
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path TO pg_catalog AS $$
DECLARE v_statement bigint; v_lock bigint;
BEGIN
    SELECT setting::bigint INTO v_statement FROM pg_settings WHERE name='statement_timeout';
    SELECT setting::bigint INTO v_lock FROM pg_settings WHERE name='lock_timeout';
    -- 함수 안에서 statement_timeout을 바꿔도 현재 statement 전체를 제한하지 못한다.
    -- Python은 호출 직전 설정하며 SQL 직접 호출도 시작부터 유한한 제한을 요구한다.
    IF v_statement=0 OR v_statement>30000 THEN
        RAISE EXCEPTION 'kernel requires statement timeout of at most 30 seconds' USING ERRCODE='23514';
    END IF;
    PERFORM set_config('lock_timeout',LEAST(COALESCE(NULLIF(v_lock,0),1000),1000)::text,true);
END;
$$;
