-- 430 strict guard와 기존 scalar projector의 실제 no-op를 맞춘다. 권한/정책 의미는 보존한다.
CREATE OR REPLACE FUNCTION feature._project_provider_field_candidates(p_feature uuid)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path TO pg_catalog AS $$
DECLARE v_active feature.provider_field_active_policies%ROWTYPE; v_winner record;
BEGIN
    SELECT * INTO STRICT v_active FROM feature.provider_field_active_policies WHERE feature_id=p_feature;
    FOR v_winner IN SELECT * FROM feature.provider_field_scalar_winners(
        p_feature,v_active.policy_revision,v_active.field_paths) LOOP
        -- ON CONFLICT의 WHERE보다 BEFORE INSERT가 먼저 실행된다. 완전히 같은
        -- winner base에는 IUD 자체를 하지 않아 외부 provider의 불필요한 trigger를 피한다.
        -- 실제 값/출처/시각 변경은 원 UPSERT와 strict target guard를 그대로 지난다.
        IF NOT EXISTS (
            SELECT 1 FROM feature.feature_base_field_values base
            WHERE base.feature_id=p_feature AND base.field_path=v_winner.field_path
              AND (base.provider_dataset_id,base.source_entity_key,base.source_record_key,
                   base.source_raw_payload_hash,base.value_json,base.value_geometry,base.observed_at)
                IS NOT DISTINCT FROM
                  (v_winner.provider_dataset_id,v_winner.source_entity_key,
                   v_winner.value_source_record_key,v_winner.value_source_hash,
                   v_winner.value_json,NULL,v_winner.value_observed_at)
        ) THEN
            INSERT INTO feature.feature_base_field_values AS base(
                feature_id,field_path,provider_dataset_id,source_entity_key,source_record_key,
                source_raw_payload_hash,value_json,value_geometry,base_revision,observed_at,updated_at)
            VALUES(p_feature,v_winner.field_path,v_winner.provider_dataset_id,v_winner.source_entity_key,
                v_winner.value_source_record_key,v_winner.value_source_hash,v_winner.value_json,NULL,
                1,v_winner.value_observed_at,clock_timestamp())
            ON CONFLICT(feature_id,field_path) DO UPDATE SET
                provider_dataset_id=EXCLUDED.provider_dataset_id,source_entity_key=EXCLUDED.source_entity_key,
                source_record_key=EXCLUDED.source_record_key,source_raw_payload_hash=EXCLUDED.source_raw_payload_hash,
                value_json=EXCLUDED.value_json,value_geometry=NULL,base_revision=base.base_revision+1,
                observed_at=EXCLUDED.observed_at,updated_at=EXCLUDED.updated_at
            WHERE (base.provider_dataset_id,base.source_entity_key,base.source_record_key,
                   base.source_raw_payload_hash,base.value_json,base.value_geometry,base.observed_at)
              IS DISTINCT FROM (EXCLUDED.provider_dataset_id,EXCLUDED.source_entity_key,EXCLUDED.source_record_key,
                   EXCLUDED.source_raw_payload_hash,EXCLUDED.value_json,NULL,EXCLUDED.observed_at);
        END IF;
        IF NOT feature.has_active_feature_override(p_feature,v_winner.field_path) THEN
            IF v_winner.field_path='core.name' THEN
                UPDATE feature.features SET name=v_winner.value_json #>> '{}',updated_at=clock_timestamp()
                  WHERE feature_id=p_feature AND name IS DISTINCT FROM (v_winner.value_json #>> '{}');
            ELSE
                UPDATE feature.feature_places SET phones=ARRAY(SELECT jsonb_array_elements_text(v_winner.value_json))
                  WHERE feature_id=p_feature AND to_jsonb(phones) IS DISTINCT FROM v_winner.value_json;
                IF FOUND THEN
                    UPDATE feature.features SET updated_at=clock_timestamp() WHERE feature_id=p_feature;
                END IF;
            END IF;
        END IF;
    END LOOP;
END;
$$;
