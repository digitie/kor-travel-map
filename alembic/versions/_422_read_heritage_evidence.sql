-- 공개 reader: 동일 STABLE snapshot의 내부 metadata→bounded payload→전체 입력 검증.
CREATE FUNCTION feature.read_heritage_name_refresh_evidence(p_dataset bigint,p_entities text[])
RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path TO pg_catalog AS $$
DECLARE
    v_inv jsonb; v_data jsonb:='{}'; v_rows jsonb; v_reason text;
    v_key text; v_entity jsonb; v_link jsonb; v_feature jsonb; v_active jsonb;
    v_policy jsonb; v_candidate jsonb; v_head jsonb; v_stamp jsonb; v_claim jsonb;
    v_record jsonb; v_current_record jsonb; v_value_record jsonb; v_base_record jsonb;
    v_row jsonb; v_name_base jsonb; v_base jsonb; v_base_rows jsonb; v_fields jsonb;
    v_coord_json jsonb; v_geometry x_extension.geometry; v_base_key text;
    v_items jsonb:='[]'; v_item jsonb; v_result jsonb; v_rank numeric;
    v_epoch bigint; v_count integer; v_bytes bigint:=0;
BEGIN
    v_inv:=feature._heritage_evidence_inventory(p_dataset,p_entities);
    IF (v_inv->>'metadata_complete')::boolean IS DISTINCT FROM true THEN
        RETURN jsonb_build_object('version',1,'evidence_complete',false,
            'reason',v_inv->'reason','dataset_id',p_dataset,'policy_epoch',NULL,'items','[]'::jsonb);
    END IF;
    IF feature._heritage_evidence_retire0(p_dataset) IS DISTINCT FROM true THEN
        RETURN jsonb_build_object('version',1,'evidence_complete',false,
            'reason','retire_required','dataset_id',p_dataset,'policy_epoch',NULL,'items','[]'::jsonb);
    END IF;
    SELECT epoch INTO v_epoch FROM feature.provider_field_policy_epoch WHERE singleton;
    IF v_epoch IS NULL THEN RAISE EXCEPTION 'missing policy epoch' USING ERRCODE='55000'; END IF;
    -- 이 bulk는 모든 관계 metadata 합계가 성공한 뒤에만 실행한다.
    SELECT COALESCE(jsonb_agg(jsonb_build_object('provider_dataset_id',t.provider_dataset_id,'provider',t.provider,'dataset_key',t.dataset_key,'is_active',t.is_active)),'[]'::jsonb)
      INTO v_rows FROM provider_sync.provider_datasets t
      JOIN jsonb_to_recordset(v_inv->'refs') AS r(relation oid,tid tid,kind text)
        ON t.tableoid=r.relation AND t.ctid=r.tid
      WHERE r.kind='provider_datasets';
    v_data:=jsonb_set(v_data,ARRAY['provider_datasets'],v_rows);
    -- 이 bulk는 모든 관계 metadata 합계가 성공한 뒤에만 실행한다.
    SELECT COALESCE(jsonb_agg(jsonb_build_object('source_entity_key',t.source_entity_key,'source_entity_type',t.source_entity_type,'source_entity_id',t.source_entity_id,'provider_dataset_id',t.provider_dataset_id,'first_seen_at',t.first_seen_at,'last_seen_at',t.last_seen_at)),'[]'::jsonb)
      INTO v_rows FROM provider_sync.source_entities t
      JOIN jsonb_to_recordset(v_inv->'refs') AS r(relation oid,tid tid,kind text)
        ON t.tableoid=r.relation AND t.ctid=r.tid
      WHERE r.kind='source_entities';
    v_data:=jsonb_set(v_data,ARRAY['source_entities'],v_rows);
    -- 이 bulk는 모든 관계 metadata 합계가 성공한 뒤에만 실행한다.
    SELECT COALESCE(jsonb_agg(jsonb_build_object('source_entity_key',t.source_entity_key,'current_source_record_key',t.current_source_record_key,'lineage_key',t.lineage_key,'observed_at',t.observed_at,'expires_at',t.expires_at)),'[]'::jsonb)
      INTO v_rows FROM provider_sync.source_entity_heads t
      JOIN jsonb_to_recordset(v_inv->'refs') AS r(relation oid,tid tid,kind text)
        ON t.tableoid=r.relation AND t.ctid=r.tid
      WHERE r.kind='source_entity_heads';
    v_data:=jsonb_set(v_data,ARRAY['source_entity_heads'],v_rows);
    -- 이 bulk는 모든 관계 metadata 합계가 성공한 뒤에만 실행한다.
    SELECT COALESCE(jsonb_agg(jsonb_build_object('source_record_key',t.source_record_key,'source_entity_key',t.source_entity_key,'raw_payload_hash',t.raw_payload_hash,'raw_data',t.raw_data,'fetched_at',t.fetched_at,'imported_at',t.imported_at)),'[]'::jsonb)
      INTO v_rows FROM provider_sync.source_records t
      JOIN jsonb_to_recordset(v_inv->'refs') AS r(relation oid,tid tid,kind text)
        ON t.tableoid=r.relation AND t.ctid=r.tid
      WHERE r.kind='source_records';
    v_data:=jsonb_set(v_data,ARRAY['source_records'],v_rows);
    -- 이 bulk는 모든 관계 metadata 합계가 성공한 뒤에만 실행한다.
    SELECT COALESCE(jsonb_agg(jsonb_build_object('feature_id',t.feature_id,'source_entity_key',t.source_entity_key,'source_role',t.source_role)),'[]'::jsonb)
      INTO v_rows FROM provider_sync.source_links t
      JOIN jsonb_to_recordset(v_inv->'refs') AS r(relation oid,tid tid,kind text)
        ON t.tableoid=r.relation AND t.ctid=r.tid
      WHERE r.kind='source_links';
    v_data:=jsonb_set(v_data,ARRAY['source_links'],v_rows);
    -- 이 bulk는 모든 관계 metadata 합계가 성공한 뒤에만 실행한다.
    SELECT COALESCE(jsonb_agg(jsonb_build_object('feature_id',t.feature_id,'provider_dataset_id',t.provider_dataset_id,'feature_kind',t.feature_kind,'natural_key',t.natural_key)),'[]'::jsonb)
      INTO v_rows FROM provider_sync.provider_feature_identities t
      JOIN jsonb_to_recordset(v_inv->'refs') AS r(relation oid,tid tid,kind text)
        ON t.tableoid=r.relation AND t.ctid=r.tid
      WHERE r.kind='provider_feature_identities';
    v_data:=jsonb_set(v_data,ARRAY['provider_feature_identities'],v_rows);
    -- 이 bulk는 모든 관계 metadata 합계가 성공한 뒤에만 실행한다.
    SELECT COALESCE(jsonb_agg(jsonb_build_object('feature_id',t.feature_id,'kind',t.kind,'lifecycle_state',t.lifecycle_state,'publication_state',t.publication_state,'quality_state',t.quality_state,'row_revision',t.row_revision)),'[]'::jsonb)
      INTO v_rows FROM feature.features t
      JOIN jsonb_to_recordset(v_inv->'refs') AS r(relation oid,tid tid,kind text)
        ON t.tableoid=r.relation AND t.ctid=r.tid
      WHERE r.kind='features';
    v_data:=jsonb_set(v_data,ARRAY['features'],v_rows);
    -- 이 bulk는 모든 관계 metadata 합계가 성공한 뒤에만 실행한다.
    SELECT COALESCE(jsonb_agg(jsonb_build_object('feature_id',t.feature_id,'policy_revision',t.policy_revision,'field_paths',t.field_paths)),'[]'::jsonb)
      INTO v_rows FROM feature.provider_field_active_policies t
      JOIN jsonb_to_recordset(v_inv->'refs') AS r(relation oid,tid tid,kind text)
        ON t.tableoid=r.relation AND t.ctid=r.tid
      WHERE r.kind='provider_field_active_policies';
    v_data:=jsonb_set(v_data,ARRAY['provider_field_active_policies'],v_rows);
    -- 이 bulk는 모든 관계 metadata 합계가 성공한 뒤에만 실행한다.
    SELECT COALESCE(jsonb_agg(jsonb_build_object('provider_dataset_id',t.provider_dataset_id,'policy_revision',t.policy_revision,'normalizer_revision',t.normalizer_revision,'fields',t.fields)),'[]'::jsonb)
      INTO v_rows FROM feature.provider_field_shadow_policies t
      JOIN jsonb_to_recordset(v_inv->'refs') AS r(relation oid,tid tid,kind text)
        ON t.tableoid=r.relation AND t.ctid=r.tid
      WHERE r.kind='provider_field_shadow_policies';
    v_data:=jsonb_set(v_data,ARRAY['provider_field_shadow_policies'],v_rows);
    -- 이 bulk는 모든 관계 metadata 합계가 성공한 뒤에만 실행한다.
    SELECT COALESCE(jsonb_agg(jsonb_build_object('feature_id',t.feature_id,'policy_revision',t.policy_revision,'provider_dataset_id',t.provider_dataset_id,'field_path',t.field_path,'source_entity_key',t.source_entity_key,'value_source_record_key',t.value_source_record_key,'value_source_hash',t.value_source_hash,'validated_source_record_key',t.validated_source_record_key,'validated_source_hash',t.validated_source_hash,'value_json',t.value_json,'availability',t.availability,'reason',t.reason,'value_observed_at',t.value_observed_at,'validated_at',t.validated_at,'normalizer_revision',t.normalizer_revision,'value_json_sql_null',t.value_json IS NULL,'value_geometry_sql_null',t.value_geometry IS NULL,'geometry_ewkb',encode(x_extension.st_asewkb(t.value_geometry),'hex'))),'[]'::jsonb)
      INTO v_rows FROM feature.provider_field_shadow_candidates t
      JOIN jsonb_to_recordset(v_inv->'refs') AS r(relation oid,tid tid,kind text)
        ON t.tableoid=r.relation AND t.ctid=r.tid
      WHERE r.kind='provider_field_shadow_candidates';
    v_data:=jsonb_set(v_data,ARRAY['provider_field_shadow_candidates'],v_rows);
    -- 이 bulk는 모든 관계 metadata 합계가 성공한 뒤에만 실행한다.
    SELECT COALESCE(jsonb_agg(jsonb_build_object('feature_id',t.feature_id,'field_path',t.field_path,'provider_dataset_id',t.provider_dataset_id,'source_entity_key',t.source_entity_key,'source_record_key',t.source_record_key,'source_raw_payload_hash',t.source_raw_payload_hash,'value_json',t.value_json,'base_revision',t.base_revision,'observed_at',t.observed_at,'value_json_sql_null',t.value_json IS NULL,'value_geometry_sql_null',t.value_geometry IS NULL,'geometry_ewkb',encode(x_extension.st_asewkb(t.value_geometry),'hex'))),'[]'::jsonb)
      INTO v_rows FROM feature.feature_base_field_values t
      JOIN jsonb_to_recordset(v_inv->'refs') AS r(relation oid,tid tid,kind text)
        ON t.tableoid=r.relation AND t.ctid=r.tid
      WHERE r.kind='feature_base_field_values';
    v_data:=jsonb_set(v_data,ARRAY['feature_base_field_values'],v_rows);
    -- 이 bulk는 모든 관계 metadata 합계가 성공한 뒤에만 실행한다.
    SELECT COALESCE(jsonb_agg(jsonb_build_object('feature_id',t.feature_id,'geo_version_token',t.geo_version_token,'geo_data_token',t.geo_data_token,'reverse_outcome',t.reverse_outcome,'stamped_at',t.stamped_at)),'[]'::jsonb)
      INTO v_rows FROM feature.feature_geocode_stamps t
      JOIN jsonb_to_recordset(v_inv->'refs') AS r(relation oid,tid tid,kind text)
        ON t.tableoid=r.relation AND t.ctid=r.tid
      WHERE r.kind='feature_geocode_stamps';
    v_data:=jsonb_set(v_data,ARRAY['feature_geocode_stamps'],v_rows);
    <<targets>>
    FOREACH v_key IN ARRAY p_entities LOOP
        v_reason:=NULL;
        SELECT x INTO v_entity FROM jsonb_array_elements(v_data->'source_entities') x
          WHERE x->>'source_entity_key'=v_key;
        SELECT x INTO v_head FROM jsonb_array_elements(v_data->'source_entity_heads') x
          WHERE x->>'source_entity_key'=v_key;
        IF (SELECT count(*) FROM jsonb_array_elements(v_data->'source_links') x WHERE x->>'source_entity_key'=v_key)<>1 THEN
            v_reason:='unsupported_membership'; EXIT targets;
        END IF;
        SELECT x INTO v_link FROM jsonb_array_elements(v_data->'source_links') x
          WHERE x->>'source_entity_key'=v_key;
        IF v_entity IS NULL OR v_head IS NULL OR v_link IS NULL THEN
            v_reason:='missing_source'; EXIT targets;
        END IF;
        SELECT x INTO v_feature FROM jsonb_array_elements(v_data->'features') x
          WHERE x->'feature_id'=v_link->'feature_id';
        IF v_feature IS NULL OR v_feature->>'kind' IS DISTINCT FROM 'place'
           OR v_feature->>'lifecycle_state' IS DISTINCT FROM 'active' THEN
            v_reason:='inactive_feature'; EXIT targets;
        END IF;
        SELECT x INTO v_active FROM jsonb_array_elements(v_data->'provider_field_active_policies') x
          WHERE x->'feature_id'=v_link->'feature_id';
        IF v_active IS NULL OR v_active->'field_paths' IS DISTINCT FROM '["core.name"]'::jsonb THEN
            v_reason:='policy_unsupported'; EXIT targets;
        END IF;
        SELECT x INTO v_policy FROM jsonb_array_elements(v_data->'provider_field_shadow_policies') x
          WHERE x->'policy_revision'=v_active->'policy_revision';
        IF v_policy IS NULL OR v_policy->>'normalizer_revision' IS DISTINCT FROM 'krheritage-name-v1'
           OR jsonb_typeof(v_policy->'fields') IS DISTINCT FROM 'array' THEN
            v_reason:='policy_unsupported'; EXIT targets;
        END IF;
        IF jsonb_array_length(v_policy->'fields')<>1 THEN
            v_reason:='policy_unsupported'; EXIT targets;
        END IF;
        v_fields:=v_policy->'fields'->0;
        IF jsonb_typeof(v_fields) IS DISTINCT FROM 'object' THEN
            v_reason:='policy_unsupported'; EXIT targets;
        END IF;
        IF (SELECT count(*) FROM jsonb_object_keys(v_fields))<>4
           OR v_fields->>'field_path' IS DISTINCT FROM 'core.name'
           OR v_fields->>'omitted_policy' IS DISTINCT FROM 'carry_forward'
           OR v_fields->>'null_policy' IS DISTINCT FROM 'value'
           OR jsonb_typeof(v_fields->'provider_rank') IS DISTINCT FROM 'number' THEN
            v_reason:='policy_unsupported'; EXIT targets;
        END IF;
        -- numeric text 변환 전에 binary numeric의 scale/범위를 닫는다.
        v_rank:=(v_fields->'provider_rank')::numeric;
        IF scale(v_rank)<>0 OR v_rank<0 OR v_rank>2147483647 THEN
            v_reason:='policy_unsupported'; EXIT targets;
        END IF;
        IF (SELECT count(*) FROM jsonb_array_elements(v_data->'provider_field_shadow_candidates') x WHERE x->'feature_id'=v_link->'feature_id' AND x->'policy_revision'=v_active->'policy_revision')<>1 THEN
            v_reason:='policy_unsupported'; EXIT targets;
        END IF;
        SELECT x INTO v_candidate FROM jsonb_array_elements(v_data->'provider_field_shadow_candidates') x
          WHERE x->'feature_id'=v_link->'feature_id' AND x->'policy_revision'=v_active->'policy_revision';
        IF v_candidate IS NULL OR v_candidate->>'field_path' IS DISTINCT FROM 'core.name'
           OR v_candidate->>'source_entity_key' IS DISTINCT FROM v_key
           OR v_candidate->'provider_dataset_id' IS DISTINCT FROM to_jsonb(p_dataset)
           OR v_candidate->>'normalizer_revision' IS DISTINCT FROM 'krheritage-name-v1'
           OR v_candidate->>'availability' IS DISTINCT FROM 'value'
           OR v_candidate->>'reason' NOT IN ('supplied','omitted_carry')
           OR v_candidate->'value_geometry_sql_null' IS DISTINCT FROM 'true'::jsonb
           OR v_candidate->'value_json_sql_null' IS DISTINCT FROM 'false'::jsonb
           OR jsonb_typeof(v_candidate->'value_json') IS DISTINCT FROM 'string'
           OR v_head->'expires_at' IS DISTINCT FROM 'null'::jsonb THEN
            v_reason:='lineage_incomplete'; EXIT targets;
        END IF;
        SELECT x INTO v_current_record FROM jsonb_array_elements(v_data->'source_records') x
          WHERE x->'source_record_key'=v_head->'current_source_record_key';
        SELECT x INTO v_value_record FROM jsonb_array_elements(v_data->'source_records') x
          WHERE x->'source_record_key'=v_candidate->'value_source_record_key';
        IF v_current_record IS NULL OR v_value_record IS NULL
           OR v_current_record->>'source_entity_key' IS DISTINCT FROM v_key
           OR v_value_record->>'source_entity_key' IS DISTINCT FROM v_key
           OR v_candidate->'validated_source_record_key' IS DISTINCT FROM v_current_record->'source_record_key'
           OR v_candidate->'validated_source_hash' IS DISTINCT FROM v_current_record->'raw_payload_hash'
           OR v_candidate->'value_source_hash' IS DISTINCT FROM v_value_record->'raw_payload_hash'
           OR v_candidate->'validated_at' IS DISTINCT FROM v_head->'observed_at'
           OR v_candidate->'value_observed_at' IS DISTINCT FROM v_value_record->'fetched_at' THEN
            v_reason:='lineage_incomplete'; EXIT targets;
        END IF;
        IF (SELECT count(*) FROM jsonb_array_elements(v_data->'provider_feature_identities') x WHERE x->'feature_id'=v_link->'feature_id')<>1 THEN
            v_reason:='lineage_incomplete'; EXIT targets;
        END IF;
        SELECT x INTO v_claim FROM jsonb_array_elements(v_data->'provider_feature_identities') x
          WHERE x->'feature_id'=v_link->'feature_id';
        IF v_claim IS NULL OR v_claim->>'feature_kind' IS DISTINCT FROM 'place'
           OR v_claim->'provider_dataset_id' IS DISTINCT FROM to_jsonb(p_dataset)
           OR v_claim->'natural_key' IS DISTINCT FROM v_entity->'source_entity_id' THEN
            v_reason:='lineage_incomplete'; EXIT targets;
        END IF;
        v_base:='{}'; v_base_rows:='[]'; v_base_key:=NULL; v_name_base:=NULL;
        v_coord_json:=NULL; v_geometry:=NULL; v_count:=0;
        FOR v_row IN SELECT x FROM jsonb_array_elements(v_data->'feature_base_field_values') x
          WHERE x->'feature_id'=v_link->'feature_id'
        LOOP
            v_count:=v_count+1;
            IF v_row->'provider_dataset_id' IS DISTINCT FROM to_jsonb(p_dataset)
               OR v_row->>'source_entity_key' IS DISTINCT FROM v_key THEN
                v_reason:='lineage_incomplete'; EXIT targets;
            END IF;
            IF v_row->>'field_path'='core.name' THEN
                IF v_row->'source_record_key' IS DISTINCT FROM v_candidate->'value_source_record_key'
                   OR v_row->'source_raw_payload_hash' IS DISTINCT FROM v_candidate->'value_source_hash'
                   OR v_row->'value_json' IS DISTINCT FROM v_candidate->'value_json'
                   OR v_row->'value_json_sql_null' IS DISTINCT FROM 'false'::jsonb
                   OR v_row->'value_geometry_sql_null' IS DISTINCT FROM 'true'::jsonb THEN
                    v_reason:='lineage_incomplete'; EXIT targets;
                END IF;
                v_name_base:=v_row;
                CONTINUE;
            END IF;
            IF v_base_key IS NULL THEN v_base_key:=v_row->>'source_record_key'; END IF;
            IF v_row->>'source_record_key' IS DISTINCT FROM v_base_key THEN
                v_reason:='mixed_base_lineage'; EXIT targets;
            END IF;
            IF v_row->>'field_path'='core.coord' THEN
                IF v_row->'value_json_sql_null'='true'::jsonb THEN
                    IF v_row->'value_geometry_sql_null' IS DISTINCT FROM 'false'::jsonb THEN
                        v_reason:='shape_unsupported'; EXIT targets;
                    END IF;
                    v_geometry:=x_extension.st_geomfromewkb(decode(v_row->>'geometry_ewkb','hex'));
                ELSE
                    IF v_row->'value_geometry_sql_null' IS DISTINCT FROM 'true'::jsonb THEN
                        v_reason:='shape_unsupported'; EXIT targets;
                    END IF;
                    v_coord_json:=v_row->'value_json';
                END IF;
            ELSE
                IF v_row->'value_json_sql_null' IS DISTINCT FROM 'false'::jsonb
                   OR v_row->'value_geometry_sql_null' IS DISTINCT FROM 'true'::jsonb
                   OR v_base ? (v_row->>'field_path') THEN
                    v_reason:='shape_unsupported'; EXIT targets;
                END IF;
                v_base:=v_base||jsonb_build_object(v_row->>'field_path',v_row->'value_json');
            END IF;
            v_base_rows:=v_base_rows||jsonb_build_array(v_row);
        END LOOP;
        IF v_count<>25 OR jsonb_array_length(v_base_rows)<>24 OR v_base_key IS NULL THEN
            v_reason:='lineage_incomplete'; EXIT targets;
        END IF;
        SELECT x INTO v_base_record FROM jsonb_array_elements(v_data->'source_records') x
          WHERE x->>'source_record_key'=v_base_key;
        IF v_base_record IS NULL OR v_base_record->>'source_entity_key' IS DISTINCT FROM v_key THEN
            v_reason:='lineage_incomplete'; EXIT targets;
        END IF;
        FOR v_row IN SELECT x FROM jsonb_array_elements(v_base_rows) x LOOP
            IF v_row->'source_raw_payload_hash' IS DISTINCT FROM v_base_record->'raw_payload_hash' THEN
                v_reason:='lineage_incomplete'; EXIT targets;
            END IF;
        END LOOP;
        IF feature._heritage_evidence_shape(v_base_record->'raw_data',v_base,v_coord_json,v_geometry)
                IS DISTINCT FROM true
           OR feature._heritage_evidence_string_object(v_current_record->'raw_data',ARRAY[
                'ccba_kdcd','ccba_asno','ccba_ctcd','name_ko','category','region','sigungu',
                'longitude','latitude','location_text','designated_at','manager','image_url']) IS DISTINCT FROM true
           OR feature._heritage_evidence_string_object(v_value_record->'raw_data',ARRAY[
                'ccba_kdcd','ccba_asno','ccba_ctcd','name_ko','category','region','sigungu',
                'longitude','latitude','location_text','designated_at','manager','image_url']) IS DISTINCT FROM true THEN
            v_reason:='shape_unsupported'; EXIT targets;
        END IF;
        SELECT x INTO v_stamp FROM jsonb_array_elements(v_data->'feature_geocode_stamps') x
          WHERE x->'feature_id'=v_link->'feature_id';
        v_item:=jsonb_build_object('source_entity',v_entity,'source_head',v_head,
            'feature',v_feature,'claim',v_claim,'membership',v_link,'active_policy',v_active,
            'policy',v_policy,'name_candidate',v_candidate,'name_base',v_name_base,'non_name_base',v_base_rows,
            'base_record',v_base_record,'name_value_record',v_value_record,
            'current_record',v_current_record,'geocode_stamp',v_stamp);
        -- 여기까지 허용된 numeric은 작은 고정 정수뿐이다.
        IF octet_length(convert_to(v_item::text,'UTF8'))>131072 THEN
            v_reason:='budget_exceeded'; EXIT targets;
        END IF;
        v_bytes:=v_bytes+octet_length(convert_to(v_item::text,'UTF8'));
        IF v_bytes>1040000 THEN v_reason:='budget_exceeded'; EXIT targets; END IF;
        v_items:=v_items||jsonb_build_array(v_item);
    END LOOP targets;
    IF v_reason IS NOT NULL THEN
        RETURN jsonb_build_object('version',1,'evidence_complete',false,'reason',v_reason,
            'dataset_id',p_dataset,'policy_epoch',NULL,'items','[]'::jsonb);
    END IF;
    v_result:=jsonb_build_object('version',1,'evidence_complete',true,'reason',NULL,
        'dataset_id',p_dataset,'policy_epoch',v_epoch,'items',v_items);
    IF octet_length(convert_to(v_result::text,'UTF8'))>1048576 THEN
        RETURN jsonb_build_object('version',1,'evidence_complete',false,'reason','budget_exceeded',
            'dataset_id',p_dataset,'policy_epoch',NULL,'items','[]'::jsonb);
    END IF;
    RETURN v_result;
END;
$$;
