CREATE FUNCTION ops.finish_scoped_feature_write(p_attempt uuid,p_owner uuid,p_result_digest text)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path TO pg_catalog AS $$
DECLARE v_attempt ops.feature_write_attempts%ROWTYPE;
BEGIN
    v_attempt:=ops._locked_scoped_feature_write_attempt(p_attempt,p_owner);
    IF p_result_digest IS NULL OR p_result_digest !~ '^[0-9a-f]{64}$' THEN RAISE EXCEPTION 'invalid result digest' USING ERRCODE='23514'; END IF;
    IF v_attempt.status='completed' AND v_attempt.result_digest=p_result_digest THEN RETURN to_jsonb(v_attempt); END IF;
    IF v_attempt.status<>'applying' OR v_attempt.apply_txid IS DISTINCT FROM txid_current() THEN
        RAISE EXCEPTION 'completion must share the apply transaction' USING ERRCODE='23514';
    END IF;
    UPDATE ops.feature_write_attempts SET status='completed',result_digest=p_result_digest,updated_at=clock_timestamp() WHERE attempt_id=p_attempt RETURNING * INTO v_attempt;
    UPDATE ops.feature_write_dataset_scopes SET owner=NULL,lease_until=NULL WHERE provider_dataset_id=v_attempt.provider_dataset_id AND owner=p_attempt;
    UPDATE ops.feature_write_region_scopes SET owner=NULL,lease_until=NULL WHERE provider_dataset_id=v_attempt.provider_dataset_id AND owner=p_attempt;
    RETURN to_jsonb(v_attempt);
END;
$$;
