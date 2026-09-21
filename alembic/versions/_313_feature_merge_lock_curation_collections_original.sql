CREATE OR REPLACE PROCEDURE feature.merge_lock_curation_collections(IN p_master uuid, IN p_loser uuid)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'feature', 'ops', 'x_extension'
    AS $$
BEGIN
    -- 0214와 같은 executor 게이트. admin executor(api runtime이 상속)만 부를 수 있고
    -- provider executor(dagster runtime)는 거부한다. EXECUTE grant와 이중이다.
    IF NOT pg_has_role(session_user, 'ktm_curation_admin_executor', 'member')
       OR pg_has_role(session_user, 'ktm_curation_provider_executor', 'member') THEN
        RAISE EXCEPTION 'merge command requires the admin executor'
            USING ERRCODE = '42501';
    END IF;
    PERFORM collection.collection_id
    FROM feature.curation_collections AS collection
    WHERE EXISTS (
        SELECT 1
        FROM feature.curation_items AS item
        WHERE item.collection_id = collection.collection_id
          AND item.feature_id IN (p_master, p_loser)
    )
    ORDER BY collection.collection_id
    FOR UPDATE OF collection;
END;
$$;
