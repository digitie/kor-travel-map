CREATE FUNCTION feature.guard_stamp_writer_entry() RETURNS trigger
LANGUAGE plpgsql SECURITY INVOKER SET search_path TO pg_catalog AS $$
BEGIN
    -- runtime table ACL + 검토된 NOLOGIN owner SD만 허용한다. 정책 권한은 SD 본문이 검증한다.
    -- 동일 service LOGIN의 명시 SET ROLE owner는 기존 고권한 관리 경계다.
    IF current_user<>'ktm_feature_state_procedure_owner' OR TG_OP NOT IN ('INSERT','UPDATE') THEN
        RAISE EXCEPTION 'unsupported direct stamp writer; use reviewed entry' USING ERRCODE='42501';
    END IF;
    RETURN NEW;
END;
$$;
