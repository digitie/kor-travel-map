CREATE FUNCTION ops.scoped_feature_write_membership_digest(p_feature uuid)
RETURNS text LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path TO pg_catalog AS $$
DECLARE v_count bigint; v_digest text;
BEGIN
    SELECT count(*) INTO v_count FROM provider_sync.source_links WHERE feature_id=p_feature;
    IF v_count>8192 THEN RAISE EXCEPTION 'feature membership exceeds manifest capacity' USING ERRCODE='23514'; END IF;
    -- 행마다 JSON 배열로 경계를 고정하고 정렬된 고정폭 SHA256만 fold한다.
    SELECT encode(sha256(convert_to(COALESCE(string_agg(
        encode(sha256(convert_to(jsonb_build_array(source_entity_key,source_role)::text,'UTF8')),'hex'),
        '' ORDER BY source_entity_key COLLATE "C",source_role COLLATE "C"),''),'UTF8')),'hex')
    INTO v_digest FROM provider_sync.source_links WHERE feature_id=p_feature;
    RETURN v_digest;
END;
$$;
