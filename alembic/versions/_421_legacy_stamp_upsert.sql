CREATE FUNCTION feature.upsert_provider_geocode_stamps_ex(
    p_feature_ids uuid[],p_outcomes text[],p_version_token text,p_data_token text
) RETURNS bigint LANGUAGE plpgsql SECURITY DEFINER SET search_path TO pg_catalog AS $$
DECLARE v_feature uuid; v_count bigint;
BEGIN
    -- caller의 짧은/긴 유한 GUC를 변경하지 않는다. SH→EX는 정본 gate가 즉시 거부한다.
    PERFORM ops.lock_scoped_feature_write_protocol(true);
    PERFORM pg_advisory_xact_lock(hashtextextended('feature-curation-write',0));
    PERFORM feature.lock_provider_field_policy_epoch();
    IF p_feature_ids IS NULL OR p_outcomes IS NULL
       OR cardinality(p_feature_ids)<>cardinality(p_outcomes)
       OR array_ndims(p_feature_ids)>1 OR array_ndims(p_outcomes)>1
       OR EXISTS(SELECT 1 FROM unnest(p_feature_ids) id WHERE id IS NULL)
       OR EXISTS(SELECT 1 FROM unnest(p_outcomes) outcome WHERE outcome IS NULL
                 OR outcome NOT IN ('called','geocoded','not_called'))
       OR cardinality(p_feature_ids)<>(SELECT count(DISTINCT id) FROM unnest(p_feature_ids) id)
       OR p_version_token IS NULL OR p_version_token !~ '^dv1-[0-9a-f]{32}$'
       OR p_data_token IS NULL OR p_data_token !~ '^dd1-[0-9a-f]{32}$' THEN
        RAISE EXCEPTION 'invalid legacy stamp batch' USING ERRCODE='23514';
    END IF;
    -- noactive 비용은 bulk 조회1회다. target마다 context를 호출하지 않는다.
    FOR v_feature IN SELECT active.feature_id FROM feature.provider_field_active_policies active
        JOIN unnest(p_feature_ids) id ON id=active.feature_id ORDER BY active.feature_id LOOP
        IF NOT feature._exclusive_provider_refresh_context(v_feature) THEN
            RAISE EXCEPTION 'active stamp requires applying EX full context' USING ERRCODE='23514';
        END IF;
    END LOOP;
    -- 원래 Mapping의 모든 항목과 transaction now()를 보존한다.
    -- EX/global의 직렬화와 SH의 정렬 잠금·cap은 분리한다.
    EXECUTE $fixed_stamp_sql$
    INSERT INTO feature.feature_geocode_stamps AS stamp(
        feature_id,geo_version_token,geo_data_token,reverse_outcome,stamped_at)
    SELECT id,$3,$4,outcome,now()
        FROM unnest($1::uuid[],$2::text[]) AS input(id,outcome)
    ON CONFLICT(feature_id) DO UPDATE SET geo_version_token=EXCLUDED.geo_version_token,
        geo_data_token=EXCLUDED.geo_data_token,reverse_outcome=EXCLUDED.reverse_outcome,
        stamped_at=EXCLUDED.stamped_at;
    $fixed_stamp_sql$ USING p_feature_ids,p_outcomes,p_version_token,p_data_token;
    GET DIAGNOSTICS v_count=ROW_COUNT;
    RETURN v_count;
END;
$$;
