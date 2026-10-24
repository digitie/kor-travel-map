CREATE FUNCTION ops.seal_scoped_feature_write_manifest(p_attempt uuid,p_owner uuid)
RETURNS text LANGUAGE plpgsql SECURITY DEFINER SET search_path TO pg_catalog AS $$
DECLARE v_attempt ops.feature_write_attempts%ROWTYPE; v_count integer; v_max integer; v_digest text;
BEGIN
    v_attempt:=ops._locked_scoped_feature_write_attempt(p_attempt,p_owner);
    IF v_attempt.status='ready' THEN RETURN v_attempt.manifest_digest; END IF;
    IF v_attempt.status<>'preparing' THEN RAISE EXCEPTION 'attempt cannot seal' USING ERRCODE='23514'; END IF;
    SELECT count(*),COALESCE(max(ordinal),-1),encode(sha256(convert_to(COALESCE(string_agg(member_digest,'' ORDER BY ordinal),''),'UTF8')),'hex')
        INTO v_count,v_max,v_digest FROM ops.feature_write_manifests WHERE attempt_id=p_attempt;
    IF v_count<>v_attempt.expected_members OR v_max<>v_count-1 THEN RAISE EXCEPTION 'manifest is incomplete' USING ERRCODE='23514'; END IF;
    UPDATE ops.feature_write_attempts SET status='ready',manifest_digest=v_digest,updated_at=clock_timestamp() WHERE attempt_id=p_attempt;
    RETURN v_digest;
END;
$$;
