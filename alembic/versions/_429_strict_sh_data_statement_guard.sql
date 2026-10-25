-- 첫 prefix 검사는 기존 epoch/행잠금보다 앞이다. 설치는 별도 private installer만 한다.
CREATE FUNCTION feature._strict_sh_data_statement_guard()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path TO pg_catalog AS $$
DECLARE v_attempt uuid;
BEGIN
    IF TG_NARGS<>1 OR TG_ARGV[0] NOT IN ('strict_sh','ex_only') THEN
        RAISE EXCEPTION 'unknown strict data statement profile'
            USING ERRCODE='23514', CONSTRAINT='ck_strict_data_guard_profile';
    END IF;
    v_attempt:=feature._strict_sh_data_context(TG_ARGV[0]='strict_sh');
    IF v_attempt IS NOT NULL THEN
        -- P 없는/bare SH는 이 FOR SHARE helper까지 오지 못한다.
        PERFORM feature.lock_provider_field_policy_epoch();
    END IF;
    RETURN NULL;
END;
$$;
