CREATE FUNCTION feature.reject_unsupported_active_scalar_mutation() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path TO pg_catalog AS $$
DECLARE v_feature uuid; v_active feature.provider_field_active_policies%ROWTYPE;
BEGIN
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
    SELECT * INTO v_active FROM feature.provider_field_active_policies WHERE feature_id=v_feature;
    IF NOT FOUND THEN RETURN CASE WHEN TG_OP='DELETE' THEN OLD ELSE NEW END; END IF;
    IF TG_OP='DELETE' OR TG_TABLE_NAME IN ('source_links','feature_geocode_stamps') THEN
        RAISE EXCEPTION 'active scalar identity or link mutation is unsupported' USING ERRCODE='23514';
    ELSIF TG_TABLE_NAME='features' THEN
        IF TG_OP='INSERT' OR (to_jsonb(NEW)-CASE WHEN 'core.name'=ANY(v_active.field_paths)
              THEN ARRAY['name','updated_at','row_revision'] ELSE ARRAY['updated_at','row_revision'] END)
            IS DISTINCT FROM (to_jsonb(OLD)-CASE WHEN 'core.name'=ANY(v_active.field_paths)
              THEN ARRAY['name','updated_at','row_revision'] ELSE ARRAY['updated_at','row_revision'] END) THEN
            RAISE EXCEPTION 'Geo lifecycle and other core fields require a separate active policy' USING ERRCODE='23514';
        END IF;
    ELSIF TG_TABLE_NAME='feature_places' THEN
        IF TG_OP='INSERT' OR (to_jsonb(NEW)-CASE WHEN 'place.phones'=ANY(v_active.field_paths)
              THEN ARRAY['phones'] ELSE ARRAY[]::text[] END) IS DISTINCT FROM
              (to_jsonb(OLD)-CASE WHEN 'place.phones'=ANY(v_active.field_paths)
              THEN ARRAY['phones'] ELSE ARRAY[]::text[] END) THEN
            RAISE EXCEPTION 'other place fields are outside scalar cutover' USING ERRCODE='23514';
        END IF;
    ELSIF TG_TABLE_NAME='feature_overrides' AND NOT(NEW.field_path=ANY(v_active.field_paths)) THEN
        RAISE EXCEPTION 'unsupported operator mutation on active scalar Feature' USING ERRCODE='23514';
    END IF;
    RETURN NEW;
END;
$$;
