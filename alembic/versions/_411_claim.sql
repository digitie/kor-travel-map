CREATE FUNCTION ops.claim_scoped_feature_write(p_attempt uuid,p_owner uuid,p_dataset bigint,p_key text,p_regions jsonb,p_input_digest text,p_expected_members integer,p_lease_seconds integer,p_exclusive boolean)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path TO pg_catalog AS $$
DECLARE v_regions jsonb; v_region jsonb; v_dataset ops.feature_write_dataset_scopes%ROWTYPE;
        v_attempt ops.feature_write_attempts%ROWTYPE; v_epochs bigint[]:='{}'; v_epoch bigint; v_until timestamptz;
BEGIN
    IF p_attempt IS NULL OR p_owner IS NULL OR p_dataset IS NULL OR p_dataset<1
       OR p_key IS NULL OR p_key !~ '^[A-Za-z0-9_.:-]{1,128}$'
       OR p_input_digest IS NULL OR p_input_digest !~ '^[0-9a-f]{64}$'
       OR p_expected_members IS NULL OR p_expected_members NOT BETWEEN 0 AND 8192
       OR p_lease_seconds IS NULL OR p_lease_seconds NOT BETWEEN 1 AND 900
       OR p_exclusive IS NULL OR jsonb_typeof(p_regions) IS DISTINCT FROM 'array'
       OR pg_column_size(p_regions)>131072 THEN
        RAISE EXCEPTION 'invalid bounded scope plan' USING ERRCODE='23514';
    END IF;
    IF jsonb_array_length(p_regions)>256 THEN RAISE EXCEPTION 'too many regions' USING ERRCODE='23514'; END IF;
    FOR v_region IN SELECT value FROM jsonb_array_elements(p_regions) LOOP
        IF jsonb_typeof(v_region) IS DISTINCT FROM 'object' THEN
            RAISE EXCEPTION 'invalid region object' USING ERRCODE='23514';
        END IF;
        IF (SELECT array_agg(key ORDER BY key COLLATE "C") FROM jsonb_object_keys(v_region) key)
             IS DISTINCT FROM ARRAY['region_key','scope_version']::text[]
           OR jsonb_typeof(v_region->'region_key') IS DISTINCT FROM 'string'
           OR (v_region->>'region_key') !~ '^[A-Za-z0-9_.:-]{1,128}$'
           OR jsonb_typeof(v_region->'scope_version') IS DISTINCT FROM 'number'
           OR (v_region->>'scope_version') !~ '^[1-9][0-9]{0,9}$' THEN
            RAISE EXCEPTION 'invalid region fields' USING ERRCODE='23514';
        END IF;
        IF (v_region->>'scope_version')::numeric>2147483647 THEN
            RAISE EXCEPTION 'region version overflow' USING ERRCODE='23514';
        END IF;
    END LOOP;
    SELECT COALESCE(jsonb_agg(value ORDER BY (value->>'scope_version')::integer,value->>'region_key' COLLATE "C"),'[]')
        INTO v_regions FROM jsonb_array_elements(p_regions);
    IF (SELECT count(DISTINCT value) FROM jsonb_array_elements(v_regions))<>jsonb_array_length(v_regions) THEN
        RAISE EXCEPTION 'duplicate region' USING ERRCODE='23514';
    END IF;
    PERFORM ops._lock_scoped_feature_write_scope(p_dataset,v_regions,p_exclusive);
    SELECT * INTO v_attempt FROM ops.feature_write_attempts WHERE provider_dataset_id=p_dataset AND idempotency_key=p_key FOR UPDATE;
    IF FOUND THEN
        IF v_attempt.attempt_id IS DISTINCT FROM p_attempt OR v_attempt.owner IS DISTINCT FROM p_owner
           OR v_attempt.regions IS DISTINCT FROM v_regions OR v_attempt.input_digest IS DISTINCT FROM p_input_digest
           OR v_attempt.expected_members IS DISTINCT FROM p_expected_members OR v_attempt.exclusive_protocol IS DISTINCT FROM p_exclusive THEN
            RAISE EXCEPTION 'idempotency key is immutable' USING ERRCODE='23514';
        END IF;
        RETURN to_jsonb(v_attempt);
    END IF;
    SELECT * INTO v_dataset FROM ops.feature_write_dataset_scopes WHERE provider_dataset_id=p_dataset;
    IF v_dataset.owner IS NOT NULL AND v_dataset.lease_until>clock_timestamp() THEN
        RAISE EXCEPTION 'dataset has active owner' USING ERRCODE='55P03';
    END IF;
    v_until:=clock_timestamp()+make_interval(secs=>p_lease_seconds);
    IF jsonb_array_length(v_regions)=0 THEN
        IF EXISTS(SELECT 1 FROM ops.feature_write_region_scopes WHERE provider_dataset_id=p_dataset AND owner IS NOT NULL AND lease_until>clock_timestamp()) THEN
            RAISE EXCEPTION 'dataset has active region owners' USING ERRCODE='55P03';
        END IF;
        UPDATE ops.feature_write_dataset_scopes SET epoch=epoch+1,owner=p_attempt,lease_until=v_until WHERE provider_dataset_id=p_dataset RETURNING epoch INTO v_dataset.epoch;
    ELSE
        FOR v_region IN SELECT value FROM jsonb_array_elements(v_regions) LOOP
            IF EXISTS(SELECT 1 FROM ops.feature_write_region_scopes WHERE provider_dataset_id=p_dataset AND scope_version=(v_region->>'scope_version')::integer AND region_key=v_region->>'region_key' AND owner IS NOT NULL AND lease_until>clock_timestamp()) THEN
                RAISE EXCEPTION 'region has active owner' USING ERRCODE='55P03';
            END IF;
            UPDATE ops.feature_write_region_scopes SET epoch=epoch+1,owner=p_attempt,lease_until=v_until
                WHERE provider_dataset_id=p_dataset AND scope_version=(v_region->>'scope_version')::integer AND region_key=v_region->>'region_key' RETURNING epoch INTO v_epoch;
            v_epochs:=array_append(v_epochs,v_epoch);
        END LOOP;
    END IF;
    INSERT INTO ops.feature_write_attempts(attempt_id,provider_dataset_id,idempotency_key,owner,dataset_epoch,region_epochs,regions,exclusive_protocol,input_digest,expected_members,lease_until)
        VALUES(p_attempt,p_dataset,p_key,p_owner,v_dataset.epoch,v_epochs,v_regions,p_exclusive,p_input_digest,p_expected_members,v_until) RETURNING * INTO v_attempt;
    RETURN to_jsonb(v_attempt);
END;
$$;
