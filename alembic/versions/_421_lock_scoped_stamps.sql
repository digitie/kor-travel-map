CREATE FUNCTION feature.lock_scoped_provider_geocode_stamps(
    p_attempt uuid,p_owner uuid,p_manifest_digest text,p_input_digest text,p_targets jsonb
) RETURNS bigint LANGUAGE plpgsql SECURITY DEFINER SET search_path TO pg_catalog AS $$
BEGIN
    RETURN feature._validate_scoped_provider_geocode_stamps(
        p_attempt,p_owner,p_manifest_digest,p_input_digest,p_targets,false);
END;
$$;
