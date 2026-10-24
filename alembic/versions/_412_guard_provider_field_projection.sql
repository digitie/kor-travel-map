CREATE FUNCTION feature.guard_provider_field_projection() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path TO pg_catalog AS $$
DECLARE v_old jsonb; v_new jsonb; v_feature uuid; v_entity text; v_dataset bigint;
BEGIN
    IF TG_OP<>'INSERT' THEN v_old:=to_jsonb(OLD); END IF;
    IF TG_OP<>'DELETE' THEN v_new:=to_jsonb(NEW); END IF;
    -- 삭제/identity 변경에서는 old와 new의 양쪽 영향을 검사한다.
    IF TG_TABLE_NAME='provider_datasets' THEN
        FOR v_feature IN SELECT DISTINCT link.feature_id FROM provider_sync.source_links link
            JOIN provider_sync.source_entities entity USING(source_entity_key)
            WHERE entity.provider_dataset_id IN ((v_old->>'provider_dataset_id')::bigint,
                (v_new->>'provider_dataset_id')::bigint) LOOP
            PERFORM feature._assert_provider_field_projection(v_feature);
        END LOOP;
    ELSIF TG_TABLE_NAME IN ('source_entity_heads','source_entities','source_records') THEN
        FOR v_feature IN SELECT DISTINCT feature_id FROM provider_sync.source_links
            WHERE source_entity_key IN (v_old->>'source_entity_key',v_new->>'source_entity_key') LOOP
            PERFORM feature._assert_provider_field_projection(v_feature);
        END LOOP;
    ELSE
        FOR v_feature IN SELECT DISTINCT value::uuid FROM unnest(ARRAY[
            v_old->>'feature_id',v_new->>'feature_id']) value WHERE value IS NOT NULL LOOP
            PERFORM feature._assert_provider_field_projection(v_feature);
        END LOOP;
    END IF;
    RETURN NULL;
END;
$$;
