-- validated begin에서만 호출한다. runtime에 원 table/함수 권한을 추가하지 않는다.
CREATE FUNCTION ops._lock_snapshot_postprocess_topic_revisions()
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path TO pg_catalog AS $$
DECLARE v_topic text; v_count integer:=0;
BEGIN
    FOR v_topic IN
        SELECT topic FROM ops.ops_live_topic_revisions
        WHERE topic=ANY(ARRAY['dataset_projection','provider_sync'])
        ORDER BY topic COLLATE "C" FOR UPDATE
    LOOP
        v_count:=v_count+1;
    END LOOP;
    IF v_count<>2 THEN
        RAISE EXCEPTION 'snapshot postprocess topics are not initialized'
            USING ERRCODE='23514',CONSTRAINT='ck_snapshot_postprocess_topics_present';
    END IF;
END;
$$;
