CREATE FUNCTION ops.cancel_scoped_feature_write(p_attempt uuid,p_owner uuid)
RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path TO pg_catalog AS $$
DECLARE v_attempt ops.feature_write_attempts%ROWTYPE;
BEGIN
    SELECT * INTO v_attempt FROM ops.feature_write_attempts WHERE attempt_id=p_attempt;
    IF NOT FOUND THEN RETURN false; END IF;
    PERFORM ops._lock_scoped_feature_write_scope(v_attempt.provider_dataset_id,v_attempt.regions,v_attempt.exclusive_protocol);
    SELECT * INTO v_attempt FROM ops.feature_write_attempts WHERE attempt_id=p_attempt FOR UPDATE;
    IF NOT FOUND OR v_attempt.owner IS DISTINCT FROM p_owner THEN RAISE EXCEPTION 'attempt owner mismatch' USING ERRCODE='40001'; END IF;
    IF v_attempt.status='completed' THEN RETURN false; END IF;
    IF v_attempt.status='applying' THEN RAISE EXCEPTION 'cancel applying transaction by rollback' USING ERRCODE='23514'; END IF;
    UPDATE ops.feature_write_attempts SET status='cancelled',updated_at=clock_timestamp() WHERE attempt_id=p_attempt;
    UPDATE ops.feature_write_dataset_scopes SET owner=NULL,lease_until=NULL WHERE provider_dataset_id=v_attempt.provider_dataset_id AND owner=p_attempt;
    UPDATE ops.feature_write_region_scopes SET owner=NULL,lease_until=NULL WHERE provider_dataset_id=v_attempt.provider_dataset_id AND owner=p_attempt;
    RETURN true;
END;
$$;
