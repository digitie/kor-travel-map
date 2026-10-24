CREATE FUNCTION ops.expire_scoped_feature_write_attempt(p_attempt uuid)
RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path TO pg_catalog AS $$
DECLARE v_attempt ops.feature_write_attempts%ROWTYPE;
BEGIN
    SELECT * INTO v_attempt FROM ops.feature_write_attempts WHERE attempt_id=p_attempt;
    IF NOT FOUND OR v_attempt.status IN ('completed','cancelled') THEN RETURN false; END IF;
    PERFORM ops._lock_scoped_feature_write_scope(v_attempt.provider_dataset_id,v_attempt.regions,v_attempt.exclusive_protocol);
    SELECT * INTO v_attempt FROM ops.feature_write_attempts WHERE attempt_id=p_attempt FOR UPDATE;
    IF NOT FOUND OR v_attempt.status IN ('completed','cancelled') THEN RETURN false; END IF;
    IF v_attempt.lease_until>clock_timestamp() THEN RAISE EXCEPTION 'attempt lease is active' USING ERRCODE='55P03'; END IF;
    RETURN ops.cancel_scoped_feature_write(p_attempt,v_attempt.owner);
END;
$$;
