CREATE FUNCTION ops._locked_scoped_feature_write_attempt(p_attempt uuid, p_owner uuid)
RETURNS ops.feature_write_attempts LANGUAGE plpgsql SECURITY DEFINER SET search_path TO pg_catalog AS $$
DECLARE v_attempt ops.feature_write_attempts%ROWTYPE; v_dataset ops.feature_write_dataset_scopes%ROWTYPE;
        v_region jsonb; v_epoch bigint; v_owner uuid; v_index integer:=0;
BEGIN
    SELECT * INTO v_attempt FROM ops.feature_write_attempts WHERE attempt_id=p_attempt;
    IF NOT FOUND THEN RAISE EXCEPTION 'unknown attempt' USING ERRCODE='23514'; END IF;
    PERFORM ops._lock_scoped_feature_write_scope(v_attempt.provider_dataset_id,v_attempt.regions,v_attempt.exclusive_protocol);
    SELECT * INTO v_attempt FROM ops.feature_write_attempts WHERE attempt_id=p_attempt FOR UPDATE;
    IF NOT FOUND OR v_attempt.owner IS DISTINCT FROM p_owner THEN
        RAISE EXCEPTION 'attempt owner is not current' USING ERRCODE='40001';
    END IF;
    IF v_attempt.status IN ('completed','cancelled') THEN RETURN v_attempt; END IF;
    SELECT * INTO v_dataset FROM ops.feature_write_dataset_scopes WHERE provider_dataset_id=v_attempt.provider_dataset_id;
    IF v_dataset.epoch <> v_attempt.dataset_epoch THEN
        RAISE EXCEPTION 'dataset epoch changed' USING ERRCODE='40001';
    END IF;
    IF jsonb_array_length(v_attempt.regions)=0 AND v_dataset.owner IS DISTINCT FROM p_attempt THEN
        RAISE EXCEPTION 'dataset owner changed' USING ERRCODE='40001';
    END IF;
    FOR v_region IN SELECT value FROM jsonb_array_elements(v_attempt.regions) LOOP
        v_index:=v_index+1;
        SELECT epoch,owner INTO v_epoch,v_owner FROM ops.feature_write_region_scopes
            WHERE provider_dataset_id=v_attempt.provider_dataset_id
            AND scope_version=(v_region->>'scope_version')::integer AND region_key=v_region->>'region_key';
        IF v_epoch IS DISTINCT FROM v_attempt.region_epochs[v_index] OR v_owner IS DISTINCT FROM p_attempt THEN
            RAISE EXCEPTION 'region epoch or owner changed' USING ERRCODE='40001';
        END IF;
    END LOOP;
    IF v_attempt.lease_until <= clock_timestamp()
       AND NOT (v_attempt.status='applying' AND v_attempt.apply_txid=txid_current()) THEN
        RAISE EXCEPTION 'attempt lease expired; replan' USING ERRCODE='40001';
    END IF;
    RETURN v_attempt;
END;
$$;
