-- 비활성 Feature도 target 검사를 생략하지 않는다. 기존 scalar/SI/typed 검사는 뒤에 남는다.
CREATE FUNCTION feature._strict_sh_feature_row_guard()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path TO pg_catalog AS $$
DECLARE
    v_attempt uuid;
    v_feature uuid;
    v_dataset bigint;
BEGIN
    v_attempt:=feature._strict_sh_data_context(true);
    IF v_attempt IS NULL THEN
        IF TG_OP='DELETE' THEN RETURN OLD; END IF;
        RETURN NEW;
    END IF;
    IF TG_TABLE_SCHEMA<>'feature' OR TG_TABLE_NAME NOT IN
       ('features','feature_places','feature_base_field_values',
        'provider_field_shadow_candidates','feature_geocode_stamps') THEN
        RAISE EXCEPTION 'unknown strict Feature relation'
            USING ERRCODE='23514',CONSTRAINT='ck_strict_data_guard_profile';
    END IF;
    IF TG_OP='DELETE' OR (TG_OP='INSERT' AND TG_TABLE_NAME IN
        ('features','feature_places','feature_geocode_stamps')) THEN
        RAISE EXCEPTION 'shared Feature topology mutation is unsupported'
            USING ERRCODE='23514',CONSTRAINT='ck_strict_data_feature_target';
    END IF;
    v_feature:=NEW.feature_id;
    PERFORM feature.assert_scoped_candidate_write(v_attempt,v_feature);
    IF TG_OP='UPDATE' THEN
        PERFORM feature.assert_scoped_candidate_write(v_attempt,OLD.feature_id);
        IF OLD.feature_id IS DISTINCT FROM v_feature THEN
            RAISE EXCEPTION 'shared Feature identity cannot change'
                USING ERRCODE='23514',CONSTRAINT='ck_strict_data_feature_target';
        END IF;
    END IF;
    IF TG_TABLE_NAME IN ('feature_base_field_values','provider_field_shadow_candidates') THEN
        SELECT provider_dataset_id INTO STRICT v_dataset FROM ops.feature_write_attempts
         WHERE attempt_id=v_attempt;
        IF NEW.provider_dataset_id IS DISTINCT FROM v_dataset
           OR NOT EXISTS (SELECT 1 FROM provider_sync.source_entities entity
               JOIN provider_sync.source_links link USING(source_entity_key)
               WHERE entity.source_entity_key=NEW.source_entity_key
                 AND entity.provider_dataset_id=v_dataset
                 AND link.feature_id=v_feature AND link.source_role='primary')
           OR NOT EXISTS (SELECT 1 FROM ops.feature_write_manifests
               WHERE attempt_id=v_attempt AND dependency_kind='source_head'
                 AND dependency_key=NEW.source_entity_key) THEN
            RAISE EXCEPTION 'shared derived value is outside its own primary source target'
                USING ERRCODE='23514',CONSTRAINT='ck_strict_data_feature_target';
        END IF;
        IF TG_OP='UPDATE' AND (OLD.provider_dataset_id IS DISTINCT FROM NEW.provider_dataset_id
           OR OLD.source_entity_key IS DISTINCT FROM NEW.source_entity_key) THEN
            RAISE EXCEPTION 'shared derived value cannot change provider identity'
                USING ERRCODE='23514',CONSTRAINT='ck_strict_data_feature_target';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;
