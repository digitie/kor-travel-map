CREATE OR REPLACE FUNCTION feature.reject_unsupported_active_scalar_mutation() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path TO pg_catalog AS $$
DECLARE v_feature uuid; v_active feature.provider_field_active_policies%ROWTYPE;
        v_generated text[];
BEGIN
    IF TG_TABLE_NAME='source_links' THEN
        IF EXISTS (SELECT 1 FROM provider_sync.source_links link
            JOIN feature.provider_field_active_policies active USING(feature_id)
            WHERE link.source_entity_key IN (
                CASE WHEN TG_OP<>'DELETE' THEN NEW.source_entity_key END,
                CASE WHEN TG_OP<>'INSERT' THEN OLD.source_entity_key END))
           OR EXISTS (SELECT 1 FROM feature.provider_field_active_policies active
            WHERE active.feature_id IN (CASE WHEN TG_OP<>'DELETE' THEN NEW.feature_id END,
                CASE WHEN TG_OP<>'INSERT' THEN OLD.feature_id END)) THEN
            RAISE EXCEPTION 'active scalar source link mutation is unsupported' USING ERRCODE='23514';
        END IF;
        RETURN CASE WHEN TG_OP='DELETE' THEN OLD ELSE NEW END;
    END IF;
    IF TG_TABLE_NAME='provider_datasets' THEN
        IF (TG_OP='DELETE' OR NEW.is_active IS DISTINCT FROM OLD.is_active) AND EXISTS (
            SELECT 1 FROM feature.provider_field_active_policies active
            JOIN provider_sync.source_links link USING(feature_id)
            JOIN provider_sync.source_entities entity USING(source_entity_key)
            WHERE entity.provider_dataset_id=OLD.provider_dataset_id) THEN
            RAISE EXCEPTION 'active scalar membership retirement is unsupported' USING ERRCODE='23514';
        END IF;
        RETURN CASE WHEN TG_OP='DELETE' THEN OLD ELSE NEW END;
    END IF;
    IF TG_TABLE_NAME='source_entities' THEN
        IF (TG_OP='DELETE' OR (to_jsonb(NEW)-ARRAY['last_seen_at','first_seen_at'])
            IS DISTINCT FROM (to_jsonb(OLD)-ARRAY['last_seen_at','first_seen_at']))
          AND EXISTS (SELECT 1 FROM provider_sync.source_links link
            JOIN feature.provider_field_active_policies active USING(feature_id)
            WHERE link.source_entity_key=OLD.source_entity_key) THEN
            RAISE EXCEPTION 'active scalar source identity mutation is unsupported' USING ERRCODE='23514';
        END IF;
        RETURN CASE WHEN TG_OP='DELETE' THEN OLD ELSE NEW END;
    END IF;
    v_feature:=CASE WHEN TG_OP='DELETE' THEN OLD.feature_id ELSE NEW.feature_id END;
    SELECT * INTO v_active FROM feature.provider_field_active_policies WHERE feature_id IN (v_feature,CASE WHEN TG_OP<>'INSERT' THEN OLD.feature_id END)
        ORDER BY feature_id LIMIT 1;
    IF NOT FOUND THEN RETURN CASE WHEN TG_OP='DELETE' THEN OLD ELSE NEW END; END IF;
    IF TG_OP<>'DELETE' AND TG_TABLE_NAME IN ('features','feature_places','feature_geocode_stamps')
       AND feature._exclusive_provider_refresh_context(v_feature) THEN
        IF TG_TABLE_NAME='feature_geocode_stamps' AND (TG_OP='INSERT'
             OR NEW.feature_id=OLD.feature_id) THEN
            RETURN NEW;
        ELSIF TG_TABLE_NAME='features' AND TG_OP='UPDATE' THEN
            SELECT coalesce(array_agg(attname::text),ARRAY[]::text[]) INTO v_generated
              FROM pg_attribute WHERE attrelid=TG_RELID AND attgenerated<>'' AND NOT attisdropped;
            IF (to_jsonb(NEW)-v_generated-ARRAY['name','category','coord','coord_precision_digits',
                'address','legal_dong_code','road_name_code','road_address_management_no',
                'admin_dong_code','sido_code','sigungu_code','urls','marker_icon','marker_color',
                'raw_refs','updated_at','row_revision']) IS NOT DISTINCT FROM
               (to_jsonb(OLD)-v_generated-ARRAY['name','category','coord','coord_precision_digits',
                'address','legal_dong_code','road_name_code','road_address_management_no',
                'admin_dong_code','sido_code','sigungu_code','urls','marker_icon','marker_color',
                'raw_refs','updated_at','row_revision']) THEN RETURN NEW; END IF;
        ELSIF TG_TABLE_NAME='feature_places' AND TG_OP='UPDATE' THEN
            -- subtype identity/place_kind는 유지한다. 다른 값은 기존 typed registry materializer다.
            IF (NEW.feature_id,NEW.kind,NEW.place_kind) IS NOT DISTINCT FROM
               (OLD.feature_id,OLD.kind,OLD.place_kind) THEN RETURN NEW; END IF;
        END IF;
    END IF;
    IF TG_OP='DELETE' OR TG_TABLE_NAME IN ('source_links','feature_geocode_stamps') THEN
        RAISE EXCEPTION 'active scalar identity or link mutation is unsupported' USING ERRCODE='23514';
    ELSIF TG_TABLE_NAME='features' THEN
        -- BEFORE row에서는 generated 열이 아직 NULL이다. 입력으로 쓸 수 없는 이 열만
        -- 제외하며 실제 좌표/주소/precision/lifecycle 열의 비교는 그대로 유지한다.
        SELECT coalesce(array_agg(attname::text),ARRAY[]::text[]) INTO v_generated
            FROM pg_attribute WHERE attrelid=TG_RELID AND attgenerated<>'' AND NOT attisdropped;
        IF TG_OP='INSERT' OR (to_jsonb(NEW)-v_generated-CASE WHEN 'core.name'=ANY(v_active.field_paths)
              THEN ARRAY['name','updated_at','row_revision'] ELSE ARRAY['updated_at','row_revision'] END)
            IS DISTINCT FROM (to_jsonb(OLD)-v_generated-CASE WHEN 'core.name'=ANY(v_active.field_paths)
              THEN ARRAY['name','updated_at','row_revision'] ELSE ARRAY['updated_at','row_revision'] END) THEN
            RAISE EXCEPTION 'Geo lifecycle and other core fields require a separate active policy' USING ERRCODE='23514';
        END IF;
    ELSIF TG_TABLE_NAME='feature_places' THEN
        -- BEFORE row에서는 generated 열이 아직 NULL이다. 입력으로 쓸 수 없는 이 열만
        -- 제외하며 실제 좌표/주소/precision/lifecycle 열의 비교는 그대로 유지한다.
        SELECT coalesce(array_agg(attname::text),ARRAY[]::text[]) INTO v_generated
            FROM pg_attribute WHERE attrelid=TG_RELID AND attgenerated<>'' AND NOT attisdropped;
        IF TG_OP='INSERT' OR (to_jsonb(NEW)-v_generated-CASE WHEN 'place.phones'=ANY(v_active.field_paths)
              THEN ARRAY['phones'] ELSE ARRAY[]::text[] END) IS DISTINCT FROM
              (to_jsonb(OLD)-v_generated-CASE WHEN 'place.phones'=ANY(v_active.field_paths)
              THEN ARRAY['phones'] ELSE ARRAY[]::text[] END) THEN
            RAISE EXCEPTION 'other place fields are outside scalar cutover' USING ERRCODE='23514';
        END IF;
    ELSIF TG_TABLE_NAME='feature_overrides' AND NOT(NEW.field_path=ANY(v_active.field_paths)) THEN
        RAISE EXCEPTION 'unsupported operator mutation on active scalar Feature' USING ERRCODE='23514';
    END IF;
    RETURN NEW;
END;
$$;
