CREATE OR REPLACE FUNCTION feature.validate_feature_base_field_value() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog'
    AS $$
DECLARE
    v_registry ops.feature_override_field_paths%ROWTYPE;
    v_feature_kind text;
    v_source_hash text;
BEGIN
    SELECT * INTO v_registry
      FROM ops.feature_override_field_paths
     WHERE field_path = NEW.field_path;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'unknown provider base field path %', NEW.field_path
            USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_base_field_path';
    END IF;
    SELECT kind INTO v_feature_kind
      FROM feature.features
     WHERE feature_id = NEW.feature_id;
    IF NOT FOUND OR (v_registry.feature_kind <> '*' AND v_registry.feature_kind <> v_feature_kind) THEN
        RAISE EXCEPTION 'base field path % does not apply to Feature', NEW.field_path
            USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_base_field_target';
    END IF;
    SELECT record.raw_payload_hash INTO v_source_hash
      FROM provider_sync.provider_datasets AS dataset
      JOIN provider_sync.source_entities AS entity
        ON entity.provider_dataset_id = dataset.provider_dataset_id
      JOIN provider_sync.source_records AS record
        ON record.source_entity_key = entity.source_entity_key
      JOIN provider_sync.source_entity_heads AS head
        ON head.source_entity_key = entity.source_entity_key
       AND head.current_source_record_key = record.source_record_key
     WHERE dataset.provider_dataset_id = NEW.provider_dataset_id
       AND entity.source_entity_key = NEW.source_entity_key
       AND record.source_record_key = NEW.source_record_key;
    IF v_source_hash IS NULL OR v_source_hash IS DISTINCT FROM NEW.source_raw_payload_hash THEN
        RAISE EXCEPTION 'base field requires the current canonical source record'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_base_field_source';
    END IF;
    IF v_registry.value_kind = 'geometry' THEN
        IF NOT (
            (NEW.value_json = 'null'::jsonb AND v_registry.allows_null
             AND NEW.value_geometry IS NULL)
            OR (
                NEW.value_json IS NULL AND NEW.value_geometry IS NOT NULL
                AND x_extension.st_srid(NEW.value_geometry) = 4326
                AND upper(x_extension.st_geometrytype(NEW.value_geometry))
                    = 'ST_' || v_registry.geometry_type
            )
        ) THEN
            RAISE EXCEPTION 'base geometry does not match registry type'
                USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_base_field_value';
        END IF;
    ELSIF NEW.value_geometry IS NOT NULL
       OR NEW.value_json IS NULL
       OR (NOT v_registry.allows_null AND NEW.value_json = 'null'::jsonb)
       OR (NEW.value_json <> 'null'::jsonb AND (
              (v_registry.value_kind = 'text' AND jsonb_typeof(NEW.value_json) <> 'string')
           OR (v_registry.value_kind = 'uuid' AND jsonb_typeof(NEW.value_json) <> 'string')
           OR (v_registry.value_kind = 'date' AND jsonb_typeof(NEW.value_json) <> 'string')
           OR (v_registry.value_kind = 'timestamptz' AND jsonb_typeof(NEW.value_json) <> 'string')
           OR (v_registry.value_kind = 'integer' AND jsonb_typeof(NEW.value_json) <> 'number')
           OR (v_registry.value_kind = 'numeric' AND jsonb_typeof(NEW.value_json) <> 'number')
           OR (v_registry.value_kind = 'boolean' AND jsonb_typeof(NEW.value_json) <> 'boolean')
           OR (v_registry.value_kind = 'json_object' AND jsonb_typeof(NEW.value_json) <> 'object')
           OR (v_registry.value_kind IN ('json_array', 'text_array') AND jsonb_typeof(NEW.value_json) <> 'array')
       )) THEN
        RAISE EXCEPTION 'base JSON value does not match registry type'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_base_field_value';
    END IF;
    IF v_registry.value_kind = 'text_array' AND NEW.value_json <> 'null'::jsonb AND EXISTS (
        SELECT 1 FROM jsonb_array_elements(NEW.value_json) AS element
        WHERE jsonb_typeof(element) <> 'string'
    ) THEN
        RAISE EXCEPTION 'base text array contains a non-string value'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_base_field_value';
    END IF;
    RETURN NEW;
END;
$$;
