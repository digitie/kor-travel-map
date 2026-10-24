CREATE FUNCTION feature.reobserve_scoped_provider_geocode_stamps(
    p_attempt uuid,p_owner uuid,p_manifest_digest text,p_input_digest text,p_targets jsonb
) RETURNS bigint LANGUAGE plpgsql SECURITY DEFINER SET search_path TO pg_catalog AS $$
DECLARE v_expected bigint; v_actual bigint;
BEGIN
    v_expected:=feature._validate_scoped_provider_geocode_stamps(
        p_attempt,p_owner,p_manifest_digest,p_input_digest,p_targets,true);
    -- 시각은 caller 입력을 사용하지 않는다. ID/token/outcome을 바꾸는 SQL은 없다.
    UPDATE feature.feature_geocode_stamps stamp SET stamped_at=now()
    FROM jsonb_array_elements(p_targets) input WHERE stamp.feature_id=(input->>'feature_id')::uuid;
    GET DIAGNOSTICS v_actual=ROW_COUNT;
    IF v_actual<>v_expected THEN
        RAISE EXCEPTION 'scoped stamp target disappeared' USING ERRCODE='40001';
    END IF;
    RETURN v_actual;
END;
$$;
