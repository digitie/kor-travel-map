-- 공개 reader: 동일 STABLE snapshot의 내부 metadata→bounded payload→전체 입력 검증.
CREATE FUNCTION feature.read_transport_rest_snapshot_evidence(p_dataset bigint)
RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path TO pg_catalog AS $$
DECLARE
    p_entities text[]; v_scope record; v_scope_count integer:=0;
    v_scope_bytes bigint:=0; v_scope_refs jsonb:='[]';
    v_inv jsonb; v_data jsonb:='{}'; v_lookup jsonb; v_rows jsonb; v_reason text;
    v_key text; v_entity jsonb; v_link jsonb; v_feature jsonb; v_active jsonb;
    v_policy jsonb; v_candidate jsonb; v_phones jsonb; v_phones_base jsonb; v_head jsonb; v_stamp jsonb; v_claim jsonb;
    v_record jsonb; v_current_record jsonb; v_value_record jsonb; v_phones_record jsonb; v_base_record jsonb;
    v_row jsonb; v_name_base jsonb; v_base jsonb; v_base_rows jsonb; v_fields jsonb;
    v_coord_json jsonb; v_geometry x_extension.geometry; v_base_key text;
    v_item_rows jsonb[]:='{}';
    v_items jsonb:='[]'; v_item jsonb; v_result jsonb; v_rank numeric;
    v_epoch bigint; v_count integer; v_bytes bigint:=0;
BEGIN
    -- 요청 subset이 아니라 DB의 현재 dataset 전체 집합을 metadata부터 닫는다.
    IF p_dataset IS NULL OR p_dataset<1 THEN
        RAISE EXCEPTION 'invalid rest-area evidence dataset' USING ERRCODE='22023';
    END IF;
    IF EXISTS(SELECT 1 FROM pg_inherits
              WHERE inhparent='provider_sync.source_entities'::regclass
                 OR inhrelid='provider_sync.source_entities'::regclass)
       OR EXISTS(SELECT 1 FROM pg_class
                 WHERE oid='provider_sync.source_entities'::regclass AND relkind<>'r') THEN
        RETURN jsonb_build_object('version',1,'evidence_complete',false,'db_scope_eof',false,
            'reason','scope_unsupported','dataset_id',p_dataset,'policy_epoch',NULL,'items','[]'::jsonb);
    END IF;
    FOR v_scope IN
        SELECT e.tableoid AS relation_oid,e.ctid AS row_tid,
               feature._heritage_evidence_metadata_bytes(
                   ARRAY[pg_column_size(e.source_entity_key)::bigint],
                   ARRAY[pg_column_compression(e.source_entity_key) IS NOT NULL],
                   ARRAY[128],ARRAY[false]) AS bytes
        FROM provider_sync.source_entities e WHERE e.provider_dataset_id=p_dataset LIMIT 257
    LOOP
        v_scope_count:=v_scope_count+1;
        IF v_scope_count>256 THEN
            RETURN jsonb_build_object('version',1,'evidence_complete',false,'db_scope_eof',false,
                'reason','budget_exceeded','dataset_id',p_dataset,'policy_epoch',NULL,'items','[]'::jsonb);
        END IF;
        IF v_scope.bytes<0 THEN
            RETURN jsonb_build_object('version',1,'evidence_complete',false,'db_scope_eof',false,
                'reason','storage_unsupported','dataset_id',p_dataset,'policy_epoch',NULL,'items','[]'::jsonb);
        END IF;
        v_scope_bytes:=v_scope_bytes+v_scope.bytes+256;
        IF v_scope_bytes>4194304 THEN
            RETURN jsonb_build_object('version',1,'evidence_complete',false,'db_scope_eof',false,
                'reason','budget_exceeded','dataset_id',p_dataset,'policy_epoch',NULL,'items','[]'::jsonb);
        END IF;
        -- 고정폭 물리 ref만 저장한다. key/배열/정렬은 global metadata 성공 뒤다.
        v_scope_refs:=v_scope_refs||jsonb_build_array(jsonb_build_object(
            'relation',v_scope.relation_oid,'tid',v_scope.row_tid::text));
    END LOOP;
    IF v_scope_count=0 THEN
        RETURN jsonb_build_object('version',1,'evidence_complete',false,'db_scope_eof',false,
            'reason','empty_scope','dataset_id',p_dataset,'policy_epoch',NULL,'items','[]'::jsonb);
    END IF;
    SELECT array_agg(e.source_entity_key ORDER BY e.source_entity_key COLLATE "C")
      INTO p_entities FROM provider_sync.source_entities e
      JOIN jsonb_to_recordset(v_scope_refs) AS r(relation oid,tid tid)
        ON e.tableoid=r.relation AND e.ctid=r.tid;
    IF cardinality(p_entities) IS DISTINCT FROM v_scope_count THEN
        RAISE EXCEPTION 'rest-area physical scope changed within snapshot' USING ERRCODE='55000';
    END IF;
    -- DB에서 조립한 내부 key도 형식 위반이면 알려진 전체 거부다.
    FOREACH v_key IN ARRAY p_entities LOOP
        IF octet_length(v_key)<>67 OR v_key !~ '^se_[0-9a-f]{64}$' THEN
            RETURN jsonb_build_object('version',1,'evidence_complete',false,'db_scope_eof',false,
                'reason','scope_unsupported','dataset_id',p_dataset,'policy_epoch',NULL,'items','[]'::jsonb);
        END IF;
    END LOOP;
    v_inv:=feature._transport_rest_evidence_inventory(p_dataset,p_entities);
    IF (v_inv->>'metadata_complete')::boolean IS DISTINCT FROM true THEN
        RETURN jsonb_build_object('version',1,'evidence_complete',false,'db_scope_eof',false,
            'reason',v_inv->'reason','dataset_id',p_dataset,'policy_epoch',NULL,'items','[]'::jsonb);
    END IF;
    -- 전체 DB entity를 입력으로 삼으며 target 전부의 active/place/단일 primary를
    -- 아래 targets 단계에서 검사한다. Heritage 전용 retire 술어를 재사용하지 않는다.
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
    SELECT COALESCE(jsonb_agg(jsonb_build_object('feature_id',t.feature_id,'kind',t.kind,'lifecycle_state',t.lifecycle_state,'publication_state',t.publication_state,'quality_state',t.quality_state,'row_revision',t.row_revision,'coord_precision_digits',t.coord_precision_digits,'geometry_ewkb',encode(x_extension.st_asewkb(t.coord,'NDR'),'hex'),'coord_sql_null',t.coord IS NULL,'address',t.address,'legal_dong_code',t.legal_dong_code,'road_name_code',t.road_name_code,'road_address_management_no',t.road_address_management_no,'admin_dong_code',t.admin_dong_code,'sido_code',t.sido_code,'sigungu_code',t.sigungu_code)),'[]'::jsonb)
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
    SELECT COALESCE(jsonb_agg(jsonb_build_object('feature_id',t.feature_id,'policy_revision',t.policy_revision,'provider_dataset_id',t.provider_dataset_id,'field_path',t.field_path,'source_entity_key',t.source_entity_key,'value_source_record_key',t.value_source_record_key,'value_source_hash',t.value_source_hash,'validated_source_record_key',t.validated_source_record_key,'validated_source_hash',t.validated_source_hash,'value_json',t.value_json,'availability',t.availability,'reason',t.reason,'value_observed_at',t.value_observed_at,'validated_at',t.validated_at,'normalizer_revision',t.normalizer_revision,'value_json_sql_null',t.value_json IS NULL,'value_geometry_sql_null',t.value_geometry IS NULL,'geometry_ewkb',encode(x_extension.st_asewkb(t.value_geometry,'NDR'),'hex'))),'[]'::jsonb)
      INTO v_rows FROM feature.provider_field_shadow_candidates t
      JOIN jsonb_to_recordset(v_inv->'refs') AS r(relation oid,tid tid,kind text)
        ON t.tableoid=r.relation AND t.ctid=r.tid
      WHERE r.kind='provider_field_shadow_candidates';
    v_data:=jsonb_set(v_data,ARRAY['provider_field_shadow_candidates'],v_rows);
    -- 이 bulk는 모든 관계 metadata 합계가 성공한 뒤에만 실행한다.
    SELECT COALESCE(jsonb_agg(jsonb_build_object('feature_id',t.feature_id,'field_path',t.field_path,'provider_dataset_id',t.provider_dataset_id,'source_entity_key',t.source_entity_key,'source_record_key',t.source_record_key,'source_raw_payload_hash',t.source_raw_payload_hash,'value_json',t.value_json,'base_revision',t.base_revision,'observed_at',t.observed_at,'value_json_sql_null',t.value_json IS NULL,'value_geometry_sql_null',t.value_geometry IS NULL,'geometry_ewkb',encode(x_extension.st_asewkb(t.value_geometry,'NDR'),'hex'))),'[]'::jsonb)
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
    -- 동일 bounded payload를 key별 배열로 한 번 묶는다. 행을 덮어쓰지 않고
    -- 원 ordinal을 보존하여 아래 count/첫 행/중복/NULL 검사는 그대로 수행한다.
    SELECT COALESCE(jsonb_object_agg(g.index_name,g.entries),'{}'::jsonb)
      INTO v_lookup
      FROM (
        SELECT r.index_name,jsonb_object_agg(r.lookup_key,r.rows) AS entries
        FROM (
          SELECT k.index_name,
            CASE WHEN k.key_mode='text' THEN x.value->>k.key_field
                 ELSE (x.value->k.key_field)::text END AS lookup_key,
            jsonb_agg(x.value ORDER BY x.ordinality) AS rows
          FROM (VALUES
            ('source_entities','source_entities','source_entity_key','text'),
            ('source_entity_heads','source_entity_heads','source_entity_key','text'),
            ('source_links','source_links','source_entity_key','text'),
            ('features','features','feature_id','json'),
            ('provider_field_active_policies','provider_field_active_policies','feature_id','json'),
            ('provider_field_shadow_policies','provider_field_shadow_policies','policy_revision','json'),
            ('provider_field_shadow_candidates','provider_field_shadow_candidates','feature_id','json'),
            ('source_records_json','source_records','source_record_key','json'),
            ('source_records_text','source_records','source_record_key','text'),
            ('provider_feature_identities','provider_feature_identities','feature_id','json'),
            ('feature_base_field_values','feature_base_field_values','feature_id','json'),
            ('feature_geocode_stamps','feature_geocode_stamps','feature_id','json')
          ) AS k(index_name,relation_name,key_field,key_mode)
          CROSS JOIN LATERAL jsonb_array_elements(v_data->k.relation_name)
            WITH ORDINALITY AS x(value,ordinality)
          GROUP BY k.index_name,lookup_key
        ) r
        WHERE r.lookup_key IS NOT NULL
        GROUP BY r.index_name
      ) g;
    -- 이후에는 그룹만 읽는다. 원 관계 배열의 장기 중복 보관을 피한다.
    v_data:='{}';
    <<targets>>
    FOREACH v_key IN ARRAY p_entities LOOP
        v_reason:=NULL; v_phones_base:=NULL;
        SELECT x INTO v_entity FROM jsonb_array_elements(COALESCE(v_lookup->'source_entities'->(v_key),'[]'::jsonb)) x
          WHERE x->>'source_entity_key'=v_key;
        SELECT x INTO v_head FROM jsonb_array_elements(COALESCE(v_lookup->'source_entity_heads'->(v_key),'[]'::jsonb)) x
          WHERE x->>'source_entity_key'=v_key;
        IF (SELECT count(*) FROM jsonb_array_elements(COALESCE(v_lookup->'source_links'->(v_key),'[]'::jsonb)) x WHERE x->>'source_entity_key'=v_key)<>1 THEN
            v_reason:='unsupported_membership'; EXIT targets;
        END IF;
        SELECT x INTO v_link FROM jsonb_array_elements(COALESCE(v_lookup->'source_links'->(v_key),'[]'::jsonb)) x
          WHERE x->>'source_entity_key'=v_key;
        IF v_entity IS NULL OR v_head IS NULL OR v_link IS NULL THEN
            v_reason:='missing_source'; EXIT targets;
        END IF;
        SELECT x INTO v_feature FROM jsonb_array_elements(COALESCE(v_lookup->'features'->((v_link->'feature_id')::text),'[]'::jsonb)) x
          WHERE x->'feature_id'=v_link->'feature_id';
        IF v_feature IS NULL OR v_feature->>'kind' IS DISTINCT FROM 'place'
           OR v_feature->>'lifecycle_state' IS DISTINCT FROM 'active' THEN
            v_reason:='inactive_feature'; EXIT targets;
        END IF;
        SELECT x INTO v_active FROM jsonb_array_elements(COALESCE(v_lookup->'provider_field_active_policies'->((v_link->'feature_id')::text),'[]'::jsonb)) x
          WHERE x->'feature_id'=v_link->'feature_id';
        IF v_active IS NULL OR v_active->'field_paths' IS DISTINCT FROM '["core.name","place.phones"]'::jsonb THEN
            v_reason:='policy_unsupported'; EXIT targets;
        END IF;
        SELECT x INTO v_policy FROM jsonb_array_elements(COALESCE(v_lookup->'provider_field_shadow_policies'->((v_active->'policy_revision')::text),'[]'::jsonb)) x
          WHERE x->'policy_revision'=v_active->'policy_revision';
        IF v_policy IS NULL OR v_policy->>'normalizer_revision' IS DISTINCT FROM 'transport-rest-area-name-phones-v1'
           OR jsonb_typeof(v_policy->'fields') IS DISTINCT FROM 'array' THEN
            v_reason:='policy_unsupported'; EXIT targets;
        END IF;
        IF jsonb_array_length(v_policy->'fields')<>2 OR
           (SELECT jsonb_agg(x->>'field_path' ORDER BY (x->>'field_path') COLLATE "C")
            FROM jsonb_array_elements(v_policy->'fields') x)
              IS DISTINCT FROM '["core.name","place.phones"]'::jsonb THEN
            v_reason:='policy_unsupported'; EXIT targets;
        END IF;
        FOR v_fields IN SELECT value FROM jsonb_array_elements(v_policy->'fields') LOOP
            IF jsonb_typeof(v_fields) IS DISTINCT FROM 'object' THEN
                v_reason:='policy_unsupported'; EXIT targets;
            END IF;
            IF (SELECT count(*) FROM jsonb_object_keys(v_fields))<>4
               OR v_fields->>'omitted_policy' IS DISTINCT FROM 'carry_forward'
               OR v_fields->>'null_policy' IS DISTINCT FROM 'value'
               OR jsonb_typeof(v_fields->'provider_rank') IS DISTINCT FROM 'number' THEN
                v_reason:='policy_unsupported'; EXIT targets;
            END IF;
            v_rank:=(v_fields->'provider_rank')::numeric;
            IF scale(v_rank)<>0 OR v_rank<0 OR v_rank>2147483647 THEN
                v_reason:='policy_unsupported'; EXIT targets;
            END IF;
        END LOOP;
        IF (SELECT count(*) FROM jsonb_array_elements(COALESCE(v_lookup->'provider_field_shadow_candidates'->((v_link->'feature_id')::text),'[]'::jsonb)) x WHERE x->'feature_id'=v_link->'feature_id' AND x->'policy_revision'=v_active->'policy_revision')<>2 THEN
            v_reason:='policy_unsupported'; EXIT targets;
        END IF;
        SELECT x INTO v_candidate FROM jsonb_array_elements(COALESCE(v_lookup->'provider_field_shadow_candidates'->((v_link->'feature_id')::text),'[]'::jsonb)) x
          WHERE x->'feature_id'=v_link->'feature_id' AND x->'policy_revision'=v_active->'policy_revision' AND x->>'field_path'='core.name';
        IF v_candidate IS NULL OR v_candidate->>'field_path' IS DISTINCT FROM 'core.name'
           OR v_candidate->>'source_entity_key' IS DISTINCT FROM v_key
           OR v_candidate->'provider_dataset_id' IS DISTINCT FROM to_jsonb(p_dataset)
           OR v_candidate->>'normalizer_revision' IS DISTINCT FROM 'transport-rest-area-name-phones-v1'
           OR v_candidate->>'availability' IS DISTINCT FROM 'value'
           OR v_candidate->>'reason' NOT IN ('supplied','omitted_carry')
           OR v_candidate->'value_geometry_sql_null' IS DISTINCT FROM 'true'::jsonb
           OR v_candidate->'value_json_sql_null' IS DISTINCT FROM 'false'::jsonb
           OR jsonb_typeof(v_candidate->'value_json') IS DISTINCT FROM 'string'
           OR v_head->'expires_at' IS DISTINCT FROM 'null'::jsonb THEN
            v_reason:='lineage_incomplete'; EXIT targets;
        END IF;
        SELECT x INTO v_phones FROM jsonb_array_elements(COALESCE(v_lookup->'provider_field_shadow_candidates'->((v_link->'feature_id')::text),'[]'::jsonb)) x
          WHERE x->'feature_id'=v_link->'feature_id' AND x->'policy_revision'=v_active->'policy_revision'
            AND x->>'field_path'='place.phones';
        IF v_phones IS NULL OR v_phones->>'source_entity_key' IS DISTINCT FROM v_key
           OR v_phones->'provider_dataset_id' IS DISTINCT FROM to_jsonb(p_dataset)
           OR v_phones->>'normalizer_revision' IS DISTINCT FROM 'transport-rest-area-name-phones-v1'
           OR v_phones->>'availability' IS DISTINCT FROM 'value'
           OR v_phones->>'reason' NOT IN ('supplied','omitted_carry')
           OR v_phones->'value_geometry_sql_null' IS DISTINCT FROM 'true'::jsonb
           OR v_phones->'value_json_sql_null' IS DISTINCT FROM 'false'::jsonb
           OR jsonb_typeof(v_phones->'value_json') IS DISTINCT FROM 'array' THEN
            v_reason:='lineage_incomplete'; EXIT targets;
        END IF;
        IF jsonb_array_length(v_phones->'value_json')>1 OR EXISTS(
            SELECT 1 FROM jsonb_array_elements(v_phones->'value_json') x
            WHERE jsonb_typeof(x) IS DISTINCT FROM 'string') THEN
            v_reason:='shape_unsupported'; EXIT targets;
        END IF;
        -- 첫 명시 profile은 name/phones의 서로 다른 값 이력을 전행 거부한다.
        IF v_phones->'value_source_record_key' IS DISTINCT FROM v_candidate->'value_source_record_key'
           OR v_phones->'value_source_hash' IS DISTINCT FROM v_candidate->'value_source_hash' THEN
            v_reason:='mixed_scalar_lineage'; EXIT targets;
        END IF;
        SELECT x INTO v_current_record FROM jsonb_array_elements(COALESCE(v_lookup->'source_records_json'->((v_head->'current_source_record_key')::text),'[]'::jsonb)) x
          WHERE x->'source_record_key'=v_head->'current_source_record_key';
        SELECT x INTO v_value_record FROM jsonb_array_elements(COALESCE(v_lookup->'source_records_json'->((v_candidate->'value_source_record_key')::text),'[]'::jsonb)) x
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
        v_phones_record:=v_value_record;
        IF v_phones->'validated_source_record_key' IS DISTINCT FROM v_current_record->'source_record_key'
           OR v_phones->'validated_source_hash' IS DISTINCT FROM v_current_record->'raw_payload_hash'
           OR v_phones->'validated_at' IS DISTINCT FROM v_head->'observed_at'
           OR v_phones->'value_observed_at' IS DISTINCT FROM v_phones_record->'fetched_at' THEN
            v_reason:='lineage_incomplete'; EXIT targets;
        END IF;
        IF (SELECT count(*) FROM jsonb_array_elements(COALESCE(v_lookup->'provider_feature_identities'->((v_link->'feature_id')::text),'[]'::jsonb)) x WHERE x->'feature_id'=v_link->'feature_id')<>1 THEN
            v_reason:='lineage_incomplete'; EXIT targets;
        END IF;
        SELECT x INTO v_claim FROM jsonb_array_elements(COALESCE(v_lookup->'provider_feature_identities'->((v_link->'feature_id')::text),'[]'::jsonb)) x
          WHERE x->'feature_id'=v_link->'feature_id';
        IF v_claim IS NULL OR v_claim->>'feature_kind' IS DISTINCT FROM 'place'
           OR v_claim->'provider_dataset_id' IS DISTINCT FROM to_jsonb(p_dataset)
           OR v_claim->'natural_key' IS DISTINCT FROM v_entity->'source_entity_id' THEN
            v_reason:='lineage_incomplete'; EXIT targets;
        END IF;
        v_base:='{}'; v_base_rows:='[]'; v_base_key:=NULL; v_name_base:=NULL;
        v_coord_json:=NULL; v_geometry:=NULL; v_count:=0;
        FOR v_row IN SELECT x FROM jsonb_array_elements(COALESCE(v_lookup->'feature_base_field_values'->((v_link->'feature_id')::text),'[]'::jsonb)) x
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
            IF v_row->>'field_path'='place.phones' THEN
                IF v_row->'source_record_key' IS DISTINCT FROM v_phones->'value_source_record_key'
                   OR v_row->'source_raw_payload_hash' IS DISTINCT FROM v_phones->'value_source_hash'
                   OR v_row->'value_json' IS DISTINCT FROM v_phones->'value_json'
                   OR v_row->'value_json_sql_null' IS DISTINCT FROM 'false'::jsonb
                   OR v_row->'value_geometry_sql_null' IS DISTINCT FROM 'true'::jsonb THEN
                    v_reason:='lineage_incomplete'; EXIT targets;
                END IF;
                v_phones_base:=v_row;
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
        IF v_count<>25 OR jsonb_array_length(v_base_rows)<>23 OR v_base_key IS NULL OR v_phones_base IS NULL THEN
            v_reason:='lineage_incomplete'; EXIT targets;
        END IF;
        SELECT x INTO v_base_record FROM jsonb_array_elements(COALESCE(v_lookup->'source_records_text'->(v_base_key),'[]'::jsonb)) x
          WHERE x->>'source_record_key'=v_base_key;
        IF v_base_record IS NULL OR v_base_record->>'source_entity_key' IS DISTINCT FROM v_key THEN
            v_reason:='lineage_incomplete'; EXIT targets;
        END IF;
        FOR v_row IN SELECT x FROM jsonb_array_elements(v_base_rows) x LOOP
            IF v_row->'source_raw_payload_hash' IS DISTINCT FROM v_base_record->'raw_payload_hash' THEN
                v_reason:='lineage_incomplete'; EXIT targets;
            END IF;
        END LOOP;
        IF feature._transport_rest_evidence_shape(v_base_record->'raw_data',v_base,v_coord_json,v_geometry)
                IS DISTINCT FROM true
           OR feature._heritage_evidence_string_object(v_current_record->'raw_data',ARRAY[
                'natural_key','name','route_name','direction','lon','lat','phone_number']) IS DISTINCT FROM true
           OR feature._heritage_evidence_string_object(v_value_record->'raw_data',ARRAY[
                'natural_key','name','route_name','direction','lon','lat','phone_number']) IS DISTINCT FROM true THEN
            v_reason:='shape_unsupported'; EXIT targets;
        END IF;
        -- provider base와 실제 materialized Geo를 혼동하여 재사용하지 않는다.
        IF feature._heritage_evidence_string_object(v_feature->'address',ARRAY[
            'road','legal','admin','bjd_code','admin_dong_code','sigungu_code','sido_code',
            'road_name_code','road_address_management_no','zipcode','sido_name','sigungu_name'
        ]) IS DISTINCT FROM true THEN
            v_reason:='geo_evidence_unsupported'; EXIT targets;
        END IF;
        IF v_feature->'address' IS DISTINCT FROM v_base->'core.address'
           OR v_feature->'coord_precision_digits' IS DISTINCT FROM v_base->'core.coord_precision_digits'
           OR v_feature->'legal_dong_code' IS DISTINCT FROM v_base->'core.legal_dong_code'
           OR v_feature->'road_name_code' IS DISTINCT FROM v_base->'core.road_name_code'
           OR v_feature->'road_address_management_no' IS DISTINCT FROM v_base->'core.road_address_management_no'
           OR v_feature->'admin_dong_code' IS DISTINCT FROM v_base->'core.admin_dong_code'
           OR v_feature->'sido_code' IS DISTINCT FROM v_base->'core.sido_code'
           OR v_feature->'sigungu_code' IS DISTINCT FROM v_base->'core.sigungu_code'
           OR (v_feature->'coord_sql_null'='true'::jsonb) IS DISTINCT FROM (v_geometry IS NULL)
           OR v_feature->>'geometry_ewkb' IS DISTINCT FROM encode(x_extension.st_asewkb(v_geometry,'NDR'),'hex') THEN
            v_reason:='geo_evidence_unsupported'; EXIT targets;
        END IF;
        SELECT x INTO v_stamp FROM jsonb_array_elements(COALESCE(v_lookup->'feature_geocode_stamps'->((v_link->'feature_id')::text),'[]'::jsonb)) x
          WHERE x->'feature_id'=v_link->'feature_id';
        v_item:=jsonb_build_object('source_entity',v_entity,'source_head',v_head,
            'feature',v_feature,'claim',v_claim,'membership',v_link,'active_policy',v_active,
            'policy',v_policy,'name_candidate',v_candidate,'name_base',v_name_base,
            'phones_candidate',v_phones,'phones_base',v_phones_base,'non_scalar_base',v_base_rows,
            'base_record',v_base_record,'name_value_record',v_value_record,'phones_value_record',v_phones_record,
            'current_record',v_current_record,'geocode_stamp',v_stamp);
        -- 여기까지 허용된 numeric은 작은 고정 정수뿐이다.
        IF octet_length(convert_to(v_item::text,'UTF8'))>131072 THEN
            v_reason:='budget_exceeded'; EXIT targets;
        END IF;
        v_bytes:=v_bytes+octet_length(convert_to(v_item::text,'UTF8'));
        IF v_bytes>4190000 THEN v_reason:='budget_exceeded'; EXIT targets; END IF;
        v_item_rows:=array_append(v_item_rows,v_item);
    END LOOP targets;
    IF v_reason IS NOT NULL THEN
        RETURN jsonb_build_object('version',1,'evidence_complete',false,'db_scope_eof',false,'reason',v_reason,
            'dataset_id',p_dataset,'policy_epoch',NULL,'items','[]'::jsonb);
    END IF;
    -- 누적 byte/전체 거부 검사를 통과한 원 순서의 item만 한 번 JSON으로 만든다.
    v_items:=to_jsonb(v_item_rows);
    v_result:=jsonb_build_object('version',1,'evidence_complete',true,'db_scope_eof',true,'reason',NULL,
        'dataset_id',p_dataset,'policy_epoch',v_epoch,'items',v_items);
    IF octet_length(convert_to(v_result::text,'UTF8'))>4194304 THEN
        RETURN jsonb_build_object('version',1,'evidence_complete',false,'db_scope_eof',false,'reason','budget_exceeded',
            'dataset_id',p_dataset,'policy_epoch',NULL,'items','[]'::jsonb);
    END IF;
    RETURN v_result;
END;
$$;
