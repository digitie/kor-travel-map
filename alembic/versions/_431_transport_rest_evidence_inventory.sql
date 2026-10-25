-- 비공개 metadata 단계: 증거 완결성/쓰기 권한을 반환하지 않는다.
-- payload SELECT 이전에 모든 관계의 direct stored datum 예산과 row 수를 확인한다.
CREATE FUNCTION feature._transport_rest_evidence_inventory(p_dataset bigint,p_entities text[])
RETURNS jsonb LANGUAGE plpgsql STABLE SET search_path TO pg_catalog AS $$
DECLARE
    v_row record; v_relation regclass; v_key text; v_total bigint:=0;
    v_count integer; v_keys text[]:='{}'; v_features uuid[]:='{}';
    v_ref_key text; v_seen jsonb:='{}'; v_record_keys text[]:='{}'; v_revisions bigint[]:='{}'; v_revision bigint; v_refs jsonb:='[]'; v_feature uuid;
BEGIN
    -- 배열의 caller/wire 생성 메모리는 이 함수의 보장 범위가 아니다.
    IF p_dataset IS NULL OR p_dataset<1 OR p_entities IS NULL THEN
        RAISE EXCEPTION 'invalid rest-area evidence request' USING ERRCODE='22023';
    END IF;
    IF pg_column_compression(p_entities) IS NOT NULL
       OR pg_column_size(p_entities)>262144 THEN
        RETURN jsonb_build_object('metadata_complete',false,'reason','budget_exceeded');
    END IF;
    IF array_ndims(p_entities) IS DISTINCT FROM 1
       OR array_lower(p_entities,1) IS DISTINCT FROM 1
       OR cardinality(p_entities) NOT BETWEEN 1 AND 256 THEN
        RAISE EXCEPTION 'invalid rest-area evidence target count' USING ERRCODE='22023';
    END IF;
    -- 작은 입력 배열의 원소를 format/중복 검사 전에 각각 검사한다.
    FOREACH v_key IN ARRAY p_entities LOOP
        IF v_key IS NULL OR pg_column_compression(v_key) IS NOT NULL
           OR pg_column_size(v_key)>128 THEN
            RAISE EXCEPTION 'invalid rest-area evidence key' USING ERRCODE='22023';
        END IF;
        IF octet_length(v_key)<>67 OR v_key !~ '^se_[0-9a-f]{64}$'
           OR v_key=ANY(v_keys) THEN
            RAISE EXCEPTION 'invalid rest-area evidence key' USING ERRCODE='22023';
        END IF;
        v_keys:=array_append(v_keys,v_key);
    END LOOP;
    v_keys:='{}';
    -- ctid는 테이블별 값이다. 상속/partition이 생기면 관계 전체를 거부한다.
    FOREACH v_relation IN ARRAY ARRAY['provider_sync.provider_datasets'::regclass,'provider_sync.source_entities'::regclass,'provider_sync.source_entity_heads'::regclass,'provider_sync.source_records'::regclass,'provider_sync.source_links'::regclass,'provider_sync.provider_feature_identities'::regclass,'feature.features'::regclass,'feature.provider_field_active_policies'::regclass,'feature.provider_field_shadow_policies'::regclass,'feature.provider_field_shadow_candidates'::regclass,'feature.feature_base_field_values'::regclass,'feature.feature_geocode_stamps'::regclass,'feature.provider_field_policy_epoch'::regclass,'feature.feature_areas'::regclass,'ops.feature_overrides'::regclass] LOOP
        IF EXISTS(SELECT 1 FROM pg_inherits WHERE inhparent=v_relation OR inhrelid=v_relation)
           OR EXISTS(SELECT 1 FROM pg_class WHERE oid=v_relation AND relkind<>'r') THEN
            RETURN jsonb_build_object('metadata_complete',false,'reason','scope_unsupported');
        END IF;
    END LOOP;

    v_count:=0;
    FOR v_row IN
        SELECT t.tableoid AS relation_oid,t.ctid AS row_tid,feature._heritage_evidence_metadata_bytes(ARRAY[pg_column_size(t.provider)::bigint,pg_column_size(t.dataset_key)::bigint]::bigint[],ARRAY[(pg_column_compression(t.provider) IS NOT NULL),(pg_column_compression(t.dataset_key) IS NOT NULL)]::boolean[],ARRAY[512,512]::integer[],ARRAY[false,false]::boolean[]) AS bytes
        FROM provider_sync.provider_datasets t WHERE t.provider_dataset_id=p_dataset LIMIT 2
    LOOP
        v_count:=v_count+1;
        IF v_count>1 THEN
            RETURN jsonb_build_object('metadata_complete',false,'reason','budget_exceeded');
        END IF;
        IF v_row.bytes<0 THEN
            RETURN jsonb_build_object('metadata_complete',false,'reason','storage_unsupported');
        END IF;
        -- descriptor/고정 길이 열/JSON envelope 여유도 함께 누적한다.
        v_total:=v_total+v_row.bytes+256;
        IF v_total>4194304 THEN
            RETURN jsonb_build_object('metadata_complete',false,'reason','budget_exceeded');
        END IF;
        v_ref_key:=v_row.relation_oid::text||':'||v_row.row_tid::text;
        IF NOT(v_seen ? v_ref_key) THEN
            v_refs:=v_refs||jsonb_build_array(jsonb_build_object(
                'relation',v_row.relation_oid,'tid',v_row.row_tid::text,'kind','provider_datasets'));
            v_seen:=v_seen||jsonb_build_object(v_ref_key,true);
        END IF;
        IF NOT EXISTS(SELECT 1 FROM provider_sync.provider_datasets t
            WHERE t.tableoid=v_row.relation_oid AND t.ctid=v_row.row_tid
              AND t.provider='kor-travel-transport'
              AND t.dataset_key='transport_rest_areas' AND t.is_active) THEN
            RETURN jsonb_build_object('metadata_complete',false,'reason','scope_unsupported');
        END IF;
    END LOOP;
    IF v_count<>1 THEN RETURN jsonb_build_object('metadata_complete',false,'reason','scope_unsupported'); END IF;

    v_count:=0;
    FOR v_row IN
        SELECT t.tableoid AS relation_oid,t.ctid AS row_tid,feature._heritage_evidence_metadata_bytes(ARRAY[pg_column_size(t.source_entity_key)::bigint,pg_column_size(t.source_entity_type)::bigint,pg_column_size(t.source_entity_id)::bigint]::bigint[],ARRAY[(pg_column_compression(t.source_entity_key) IS NOT NULL),(pg_column_compression(t.source_entity_type) IS NOT NULL),(pg_column_compression(t.source_entity_id) IS NOT NULL)]::boolean[],ARRAY[128,64,128]::integer[],ARRAY[false,false,false]::boolean[]) AS bytes
        FROM provider_sync.source_entities t WHERE t.provider_dataset_id=p_dataset AND (CASE WHEN pg_catalog.octet_length(t.source_entity_key::text)<=256 THEN t.source_entity_key::text ELSE NULL::text END)=ANY(p_entities) LIMIT 257
    LOOP
        v_count:=v_count+1;
        IF v_count>256 THEN
            RETURN jsonb_build_object('metadata_complete',false,'reason','budget_exceeded');
        END IF;
        IF v_row.bytes<0 THEN
            RETURN jsonb_build_object('metadata_complete',false,'reason','storage_unsupported');
        END IF;
        -- descriptor/고정 길이 열/JSON envelope 여유도 함께 누적한다.
        v_total:=v_total+v_row.bytes+256;
        IF v_total>4194304 THEN
            RETURN jsonb_build_object('metadata_complete',false,'reason','budget_exceeded');
        END IF;
        v_ref_key:=v_row.relation_oid::text||':'||v_row.row_tid::text;
        IF NOT(v_seen ? v_ref_key) THEN
            v_refs:=v_refs||jsonb_build_array(jsonb_build_object(
                'relation',v_row.relation_oid,'tid',v_row.row_tid::text,'kind','source_entities'));
            v_seen:=v_seen||jsonb_build_object(v_ref_key,true);
        END IF;
        SELECT t.source_entity_key INTO v_key FROM provider_sync.source_entities t
          WHERE t.tableoid=v_row.relation_oid AND t.ctid=v_row.row_tid;
        v_keys:=array_append(v_keys,v_key);
        IF NOT EXISTS(SELECT 1 FROM provider_sync.source_entities t
          WHERE t.tableoid=v_row.relation_oid AND t.ctid=v_row.row_tid
            AND t.source_entity_type='rest_area') THEN
            RETURN jsonb_build_object('metadata_complete',false,'reason','scope_unsupported');
        END IF;
    END LOOP;
    IF v_count<>cardinality(p_entities) THEN RETURN jsonb_build_object('metadata_complete',false,'reason','missing_source'); END IF;

    v_count:=0;
    FOR v_row IN
        SELECT t.tableoid AS relation_oid,t.ctid AS row_tid,feature._heritage_evidence_metadata_bytes(ARRAY[pg_column_size(t.source_entity_key)::bigint,pg_column_size(t.current_source_record_key)::bigint,pg_column_size(t.lineage_key)::bigint]::bigint[],ARRAY[(pg_column_compression(t.source_entity_key) IS NOT NULL),(pg_column_compression(t.current_source_record_key) IS NOT NULL),(pg_column_compression(t.lineage_key) IS NOT NULL)]::boolean[],ARRAY[128,64,1024]::integer[],ARRAY[false,false,false]::boolean[]) AS bytes
        FROM provider_sync.source_entity_heads t WHERE (CASE WHEN pg_catalog.octet_length(t.source_entity_key::text)<=256 THEN t.source_entity_key::text ELSE NULL::text END)=ANY(v_keys) LIMIT 257
    LOOP
        v_count:=v_count+1;
        IF v_count>256 THEN
            RETURN jsonb_build_object('metadata_complete',false,'reason','budget_exceeded');
        END IF;
        IF v_row.bytes<0 THEN
            RETURN jsonb_build_object('metadata_complete',false,'reason','storage_unsupported');
        END IF;
        -- descriptor/고정 길이 열/JSON envelope 여유도 함께 누적한다.
        v_total:=v_total+v_row.bytes+256;
        IF v_total>4194304 THEN
            RETURN jsonb_build_object('metadata_complete',false,'reason','budget_exceeded');
        END IF;
        v_ref_key:=v_row.relation_oid::text||':'||v_row.row_tid::text;
        IF NOT(v_seen ? v_ref_key) THEN
            v_refs:=v_refs||jsonb_build_array(jsonb_build_object(
                'relation',v_row.relation_oid,'tid',v_row.row_tid::text,'kind','source_entity_heads'));
            v_seen:=v_seen||jsonb_build_object(v_ref_key,true);
        END IF;
        SELECT t.current_source_record_key INTO v_key FROM provider_sync.source_entity_heads t
          WHERE t.tableoid=v_row.relation_oid AND t.ctid=v_row.row_tid;
        IF v_key IS NULL OR octet_length(v_key)<>23 OR v_key !~ '^sr_[0-9a-f]{20}$' THEN
            RETURN jsonb_build_object('metadata_complete',false,'reason','lineage_incomplete');
        END IF;
        IF NOT(v_key=ANY(v_record_keys)) THEN v_record_keys:=array_append(v_record_keys,v_key); END IF;
    END LOOP;
    IF v_count<>cardinality(p_entities) THEN RETURN jsonb_build_object('metadata_complete',false,'reason','missing_source'); END IF;

    v_count:=0;
    FOR v_row IN
        SELECT t.tableoid AS relation_oid,t.ctid AS row_tid,feature._heritage_evidence_metadata_bytes(ARRAY[pg_column_size(t.source_entity_key)::bigint,pg_column_size(t.source_role)::bigint]::bigint[],ARRAY[(pg_column_compression(t.source_entity_key) IS NOT NULL),(pg_column_compression(t.source_role) IS NOT NULL)]::boolean[],ARRAY[128,64]::integer[],ARRAY[false,false]::boolean[]) AS bytes
        FROM provider_sync.source_links t WHERE (CASE WHEN pg_catalog.octet_length(t.source_entity_key::text)<=256 THEN t.source_entity_key::text ELSE NULL::text END)=ANY(v_keys) LIMIT 257
    LOOP
        v_count:=v_count+1;
        IF v_count>256 THEN
            RETURN jsonb_build_object('metadata_complete',false,'reason','budget_exceeded');
        END IF;
        IF v_row.bytes<0 THEN
            RETURN jsonb_build_object('metadata_complete',false,'reason','storage_unsupported');
        END IF;
        -- descriptor/고정 길이 열/JSON envelope 여유도 함께 누적한다.
        v_total:=v_total+v_row.bytes+256;
        IF v_total>4194304 THEN
            RETURN jsonb_build_object('metadata_complete',false,'reason','budget_exceeded');
        END IF;
        v_ref_key:=v_row.relation_oid::text||':'||v_row.row_tid::text;
        IF NOT(v_seen ? v_ref_key) THEN
            v_refs:=v_refs||jsonb_build_array(jsonb_build_object(
                'relation',v_row.relation_oid,'tid',v_row.row_tid::text,'kind','source_links'));
            v_seen:=v_seen||jsonb_build_object(v_ref_key,true);
        END IF;
        SELECT t.feature_id INTO v_feature FROM provider_sync.source_links t
          WHERE t.tableoid=v_row.relation_oid AND t.ctid=v_row.row_tid;
        IF v_feature=ANY(v_features) OR NOT EXISTS(SELECT 1 FROM provider_sync.source_links t
            WHERE t.tableoid=v_row.relation_oid AND t.ctid=v_row.row_tid AND t.source_role='primary') THEN
            RETURN jsonb_build_object('metadata_complete',false,'reason','unsupported_membership');
        END IF;
        v_features:=array_append(v_features,v_feature);
    END LOOP;
    IF v_count<>cardinality(p_entities) THEN RETURN jsonb_build_object('metadata_complete',false,'reason','unsupported_membership'); END IF;

    v_count:=0;
    FOR v_row IN
        SELECT t.tableoid AS relation_oid,t.ctid AS row_tid,feature._heritage_evidence_metadata_bytes(ARRAY[pg_column_size(t.source_entity_key)::bigint,pg_column_size(t.source_role)::bigint]::bigint[],ARRAY[(pg_column_compression(t.source_entity_key) IS NOT NULL),(pg_column_compression(t.source_role) IS NOT NULL)]::boolean[],ARRAY[128,64]::integer[],ARRAY[false,false]::boolean[]) AS bytes
        FROM provider_sync.source_links t WHERE t.feature_id=ANY(v_features) LIMIT 257
    LOOP
        v_count:=v_count+1;
        IF v_count>256 THEN
            RETURN jsonb_build_object('metadata_complete',false,'reason','budget_exceeded');
        END IF;
        IF v_row.bytes<0 THEN
            RETURN jsonb_build_object('metadata_complete',false,'reason','storage_unsupported');
        END IF;
        -- descriptor/고정 길이 열/JSON envelope 여유도 함께 누적한다.
        v_total:=v_total+v_row.bytes+256;
        IF v_total>4194304 THEN
            RETURN jsonb_build_object('metadata_complete',false,'reason','budget_exceeded');
        END IF;
        v_ref_key:=v_row.relation_oid::text||':'||v_row.row_tid::text;
        IF NOT(v_seen ? v_ref_key) THEN
            v_refs:=v_refs||jsonb_build_array(jsonb_build_object(
                'relation',v_row.relation_oid,'tid',v_row.row_tid::text,'kind','source_links'));
            v_seen:=v_seen||jsonb_build_object(v_ref_key,true);
        END IF;

    END LOOP;
    IF v_count<>cardinality(p_entities) THEN RETURN jsonb_build_object('metadata_complete',false,'reason','unsupported_membership'); END IF;

    v_count:=0;
    FOR v_row IN
        SELECT t.tableoid AS relation_oid,t.ctid AS row_tid,feature._heritage_evidence_metadata_bytes(ARRAY[pg_column_size(t.kind)::bigint,pg_column_size(t.lifecycle_state)::bigint,pg_column_size(t.publication_state)::bigint,pg_column_size(t.quality_state)::bigint,pg_column_size(t.coord)::bigint,pg_column_size(t.address)::bigint,pg_column_size(t.legal_dong_code)::bigint,pg_column_size(t.road_name_code)::bigint,pg_column_size(t.road_address_management_no)::bigint,pg_column_size(t.admin_dong_code)::bigint,pg_column_size(t.sido_code)::bigint,pg_column_size(t.sigungu_code)::bigint]::bigint[],ARRAY[(pg_column_compression(t.kind) IS NOT NULL),(pg_column_compression(t.lifecycle_state) IS NOT NULL),(pg_column_compression(t.publication_state) IS NOT NULL),(pg_column_compression(t.quality_state) IS NOT NULL),(pg_column_compression(t.coord) IS NOT NULL),(pg_column_compression(t.address) IS NOT NULL),(pg_column_compression(t.legal_dong_code) IS NOT NULL),(pg_column_compression(t.road_name_code) IS NOT NULL),(pg_column_compression(t.road_address_management_no) IS NOT NULL),(pg_column_compression(t.admin_dong_code) IS NOT NULL),(pg_column_compression(t.sido_code) IS NOT NULL),(pg_column_compression(t.sigungu_code) IS NOT NULL)]::boolean[],ARRAY[64,64,64,64,128,8192,64,256,256,64,64,64]::integer[],ARRAY[false,false,false,false,true,false,true,true,true,true,true,true]::boolean[]) AS bytes
        FROM feature.features t WHERE t.feature_id=ANY(v_features) LIMIT 257
    LOOP
        v_count:=v_count+1;
        IF v_count>256 THEN
            RETURN jsonb_build_object('metadata_complete',false,'reason','budget_exceeded');
        END IF;
        IF v_row.bytes<0 THEN
            RETURN jsonb_build_object('metadata_complete',false,'reason','storage_unsupported');
        END IF;
        -- descriptor/고정 길이 열/JSON envelope 여유도 함께 누적한다.
        v_total:=v_total+v_row.bytes+256;
        IF v_total>4194304 THEN
            RETURN jsonb_build_object('metadata_complete',false,'reason','budget_exceeded');
        END IF;
        v_ref_key:=v_row.relation_oid::text||':'||v_row.row_tid::text;
        IF NOT(v_seen ? v_ref_key) THEN
            v_refs:=v_refs||jsonb_build_array(jsonb_build_object(
                'relation',v_row.relation_oid,'tid',v_row.row_tid::text,'kind','features'));
            v_seen:=v_seen||jsonb_build_object(v_ref_key,true);
        END IF;

    END LOOP;

    -- area payload는 읽지 않고 UUID 존재만 조사한다. 첫 범위는 place-only다.
    IF EXISTS(SELECT 1 FROM feature.feature_areas t WHERE t.feature_id=ANY(v_features)) THEN
        RETURN jsonb_build_object('metadata_complete',false,'reason','unsupported_membership');
    END IF;

    -- 첫 휴게소 reader는 사람 override가 있는 모든 target을 전체 EX로 보낸다.
    -- status/field_path/JSON/geometry는 읽지 않고 고정 UUID 존재만 확인한다.
    IF EXISTS(SELECT 1 FROM ops.feature_overrides t WHERE t.feature_id=ANY(v_features)) THEN
        RETURN jsonb_build_object('metadata_complete',false,'reason','override_unsupported');
    END IF;

    v_count:=0;
    FOR v_row IN
        SELECT t.tableoid AS relation_oid,t.ctid AS row_tid,feature._heritage_evidence_metadata_bytes(ARRAY[pg_column_size(t.feature_kind)::bigint,pg_column_size(t.natural_key)::bigint]::bigint[],ARRAY[(pg_column_compression(t.feature_kind) IS NOT NULL),(pg_column_compression(t.natural_key) IS NOT NULL)]::boolean[],ARRAY[64,128]::integer[],ARRAY[false,false]::boolean[]) AS bytes
        FROM provider_sync.provider_feature_identities t WHERE t.feature_id=ANY(v_features) LIMIT 257
    LOOP
        v_count:=v_count+1;
        IF v_count>256 THEN
            RETURN jsonb_build_object('metadata_complete',false,'reason','budget_exceeded');
        END IF;
        IF v_row.bytes<0 THEN
            RETURN jsonb_build_object('metadata_complete',false,'reason','storage_unsupported');
        END IF;
        -- descriptor/고정 길이 열/JSON envelope 여유도 함께 누적한다.
        v_total:=v_total+v_row.bytes+256;
        IF v_total>4194304 THEN
            RETURN jsonb_build_object('metadata_complete',false,'reason','budget_exceeded');
        END IF;
        v_ref_key:=v_row.relation_oid::text||':'||v_row.row_tid::text;
        IF NOT(v_seen ? v_ref_key) THEN
            v_refs:=v_refs||jsonb_build_array(jsonb_build_object(
                'relation',v_row.relation_oid,'tid',v_row.row_tid::text,'kind','provider_feature_identities'));
            v_seen:=v_seen||jsonb_build_object(v_ref_key,true);
        END IF;

    END LOOP;

    v_count:=0;
    FOR v_row IN
        SELECT t.tableoid AS relation_oid,t.ctid AS row_tid,feature._heritage_evidence_metadata_bytes(ARRAY[pg_column_size(t.field_paths)::bigint]::bigint[],ARRAY[(pg_column_compression(t.field_paths) IS NOT NULL)]::boolean[],ARRAY[512]::integer[],ARRAY[false]::boolean[]) AS bytes
        FROM feature.provider_field_active_policies t WHERE t.feature_id=ANY(v_features) LIMIT 257
    LOOP
        v_count:=v_count+1;
        IF v_count>256 THEN
            RETURN jsonb_build_object('metadata_complete',false,'reason','budget_exceeded');
        END IF;
        IF v_row.bytes<0 THEN
            RETURN jsonb_build_object('metadata_complete',false,'reason','storage_unsupported');
        END IF;
        -- descriptor/고정 길이 열/JSON envelope 여유도 함께 누적한다.
        v_total:=v_total+v_row.bytes+256;
        IF v_total>4194304 THEN
            RETURN jsonb_build_object('metadata_complete',false,'reason','budget_exceeded');
        END IF;
        v_ref_key:=v_row.relation_oid::text||':'||v_row.row_tid::text;
        IF NOT(v_seen ? v_ref_key) THEN
            v_refs:=v_refs||jsonb_build_array(jsonb_build_object(
                'relation',v_row.relation_oid,'tid',v_row.row_tid::text,'kind','provider_field_active_policies'));
            v_seen:=v_seen||jsonb_build_object(v_ref_key,true);
        END IF;
        SELECT t.policy_revision INTO v_revision FROM feature.provider_field_active_policies t
          WHERE t.tableoid=v_row.relation_oid AND t.ctid=v_row.row_tid;
        IF NOT(v_revision=ANY(v_revisions)) THEN v_revisions:=array_append(v_revisions,v_revision); END IF;
    END LOOP;

    v_count:=0;
    FOR v_row IN
        SELECT t.tableoid AS relation_oid,t.ctid AS row_tid,feature._heritage_evidence_metadata_bytes(ARRAY[pg_column_size(t.normalizer_revision)::bigint,pg_column_size(t.fields)::bigint]::bigint[],ARRAY[(pg_column_compression(t.normalizer_revision) IS NOT NULL),(pg_column_compression(t.fields) IS NOT NULL)]::boolean[],ARRAY[1024,8192]::integer[],ARRAY[false,false]::boolean[]) AS bytes
        FROM feature.provider_field_shadow_policies t WHERE t.provider_dataset_id=p_dataset AND t.policy_revision=ANY(v_revisions) LIMIT 257
    LOOP
        v_count:=v_count+1;
        IF v_count>256 THEN
            RETURN jsonb_build_object('metadata_complete',false,'reason','budget_exceeded');
        END IF;
        IF v_row.bytes<0 THEN
            RETURN jsonb_build_object('metadata_complete',false,'reason','storage_unsupported');
        END IF;
        -- descriptor/고정 길이 열/JSON envelope 여유도 함께 누적한다.
        v_total:=v_total+v_row.bytes+256;
        IF v_total>4194304 THEN
            RETURN jsonb_build_object('metadata_complete',false,'reason','budget_exceeded');
        END IF;
        v_ref_key:=v_row.relation_oid::text||':'||v_row.row_tid::text;
        IF NOT(v_seen ? v_ref_key) THEN
            v_refs:=v_refs||jsonb_build_array(jsonb_build_object(
                'relation',v_row.relation_oid,'tid',v_row.row_tid::text,'kind','provider_field_shadow_policies'));
            v_seen:=v_seen||jsonb_build_object(v_ref_key,true);
        END IF;

    END LOOP;

    v_count:=0;
    FOR v_row IN
        SELECT t.tableoid AS relation_oid,t.ctid AS row_tid,feature._heritage_evidence_metadata_bytes(ARRAY[pg_column_size(t.field_path)::bigint,pg_column_size(t.source_entity_key)::bigint,pg_column_size(t.value_source_record_key)::bigint,pg_column_size(t.value_source_hash)::bigint,pg_column_size(t.validated_source_record_key)::bigint,pg_column_size(t.validated_source_hash)::bigint,pg_column_size(t.value_json)::bigint,pg_column_size(t.value_geometry)::bigint,pg_column_size(t.availability)::bigint,pg_column_size(t.reason)::bigint,pg_column_size(t.normalizer_revision)::bigint]::bigint[],ARRAY[(pg_column_compression(t.field_path) IS NOT NULL),(pg_column_compression(t.source_entity_key) IS NOT NULL),(pg_column_compression(t.value_source_record_key) IS NOT NULL),(pg_column_compression(t.value_source_hash) IS NOT NULL),(pg_column_compression(t.validated_source_record_key) IS NOT NULL),(pg_column_compression(t.validated_source_hash) IS NOT NULL),(pg_column_compression(t.value_json) IS NOT NULL),(pg_column_compression(t.value_geometry) IS NOT NULL),(pg_column_compression(t.availability) IS NOT NULL),(pg_column_compression(t.reason) IS NOT NULL),(pg_column_compression(t.normalizer_revision) IS NOT NULL)]::boolean[],ARRAY[128,128,64,128,64,128,8192,128,64,64,1024]::integer[],ARRAY[false,false,true,true,false,false,true,true,false,false,true]::boolean[]) AS bytes
        FROM feature.provider_field_shadow_candidates t WHERE t.feature_id=ANY(v_features) AND EXISTS(SELECT 1 FROM feature.provider_field_active_policies a WHERE a.feature_id=t.feature_id AND a.policy_revision=t.policy_revision) LIMIT 513
    LOOP
        v_count:=v_count+1;
        IF v_count>512 THEN
            RETURN jsonb_build_object('metadata_complete',false,'reason','budget_exceeded');
        END IF;
        IF v_row.bytes<0 THEN
            RETURN jsonb_build_object('metadata_complete',false,'reason','storage_unsupported');
        END IF;
        -- descriptor/고정 길이 열/JSON envelope 여유도 함께 누적한다.
        v_total:=v_total+v_row.bytes+256;
        IF v_total>4194304 THEN
            RETURN jsonb_build_object('metadata_complete',false,'reason','budget_exceeded');
        END IF;
        v_ref_key:=v_row.relation_oid::text||':'||v_row.row_tid::text;
        IF NOT(v_seen ? v_ref_key) THEN
            v_refs:=v_refs||jsonb_build_array(jsonb_build_object(
                'relation',v_row.relation_oid,'tid',v_row.row_tid::text,'kind','provider_field_shadow_candidates'));
            v_seen:=v_seen||jsonb_build_object(v_ref_key,true);
        END IF;
        SELECT t.value_source_record_key INTO v_key FROM feature.provider_field_shadow_candidates t
          WHERE t.tableoid=v_row.relation_oid AND t.ctid=v_row.row_tid;
        IF v_key IS NOT NULL AND NOT(v_key=ANY(v_record_keys)) THEN v_record_keys:=array_append(v_record_keys,v_key); END IF;
    END LOOP;

    v_count:=0;
    FOR v_row IN
        SELECT t.tableoid AS relation_oid,t.ctid AS row_tid,feature._heritage_evidence_metadata_bytes(ARRAY[pg_column_size(t.field_path)::bigint,pg_column_size(t.source_entity_key)::bigint,pg_column_size(t.source_record_key)::bigint,pg_column_size(t.source_raw_payload_hash)::bigint,pg_column_size(t.value_json)::bigint,pg_column_size(t.value_geometry)::bigint]::bigint[],ARRAY[(pg_column_compression(t.field_path) IS NOT NULL),(pg_column_compression(t.source_entity_key) IS NOT NULL),(pg_column_compression(t.source_record_key) IS NOT NULL),(pg_column_compression(t.source_raw_payload_hash) IS NOT NULL),(pg_column_compression(t.value_json) IS NOT NULL),(pg_column_compression(t.value_geometry) IS NOT NULL)]::boolean[],ARRAY[128,128,64,128,8192,128]::integer[],ARRAY[false,false,false,false,true,true]::boolean[]) AS bytes
        FROM feature.feature_base_field_values t WHERE t.feature_id=ANY(v_features) LIMIT 6401
    LOOP
        v_count:=v_count+1;
        IF v_count>6400 THEN
            RETURN jsonb_build_object('metadata_complete',false,'reason','budget_exceeded');
        END IF;
        IF v_row.bytes<0 THEN
            RETURN jsonb_build_object('metadata_complete',false,'reason','storage_unsupported');
        END IF;
        -- descriptor/고정 길이 열/JSON envelope 여유도 함께 누적한다.
        v_total:=v_total+v_row.bytes+256;
        IF v_total>4194304 THEN
            RETURN jsonb_build_object('metadata_complete',false,'reason','budget_exceeded');
        END IF;
        v_ref_key:=v_row.relation_oid::text||':'||v_row.row_tid::text;
        IF NOT(v_seen ? v_ref_key) THEN
            v_refs:=v_refs||jsonb_build_array(jsonb_build_object(
                'relation',v_row.relation_oid,'tid',v_row.row_tid::text,'kind','feature_base_field_values'));
            v_seen:=v_seen||jsonb_build_object(v_ref_key,true);
        END IF;
        SELECT t.source_record_key INTO v_key FROM feature.feature_base_field_values t
          WHERE t.tableoid=v_row.relation_oid AND t.ctid=v_row.row_tid;
        IF v_key IS NULL OR octet_length(v_key)<>23 OR v_key !~ '^sr_[0-9a-f]{20}$' THEN
            RETURN jsonb_build_object('metadata_complete',false,'reason','lineage_incomplete');
        END IF;
        IF NOT(v_key=ANY(v_record_keys)) THEN v_record_keys:=array_append(v_record_keys,v_key); END IF;
    END LOOP;

    v_count:=0;
    FOR v_row IN
        SELECT t.tableoid AS relation_oid,t.ctid AS row_tid,feature._heritage_evidence_metadata_bytes(ARRAY[pg_column_size(t.geo_version_token)::bigint,pg_column_size(t.geo_data_token)::bigint,pg_column_size(t.reverse_outcome)::bigint]::bigint[],ARRAY[(pg_column_compression(t.geo_version_token) IS NOT NULL),(pg_column_compression(t.geo_data_token) IS NOT NULL),(pg_column_compression(t.reverse_outcome) IS NOT NULL)]::boolean[],ARRAY[260,260,64]::integer[],ARRAY[false,false,false]::boolean[]) AS bytes
        FROM feature.feature_geocode_stamps t WHERE t.feature_id=ANY(v_features) LIMIT 257
    LOOP
        v_count:=v_count+1;
        IF v_count>256 THEN
            RETURN jsonb_build_object('metadata_complete',false,'reason','budget_exceeded');
        END IF;
        IF v_row.bytes<0 THEN
            RETURN jsonb_build_object('metadata_complete',false,'reason','storage_unsupported');
        END IF;
        -- descriptor/고정 길이 열/JSON envelope 여유도 함께 누적한다.
        v_total:=v_total+v_row.bytes+256;
        IF v_total>4194304 THEN
            RETURN jsonb_build_object('metadata_complete',false,'reason','budget_exceeded');
        END IF;
        v_ref_key:=v_row.relation_oid::text||':'||v_row.row_tid::text;
        IF NOT(v_seen ? v_ref_key) THEN
            v_refs:=v_refs||jsonb_build_array(jsonb_build_object(
                'relation',v_row.relation_oid,'tid',v_row.row_tid::text,'kind','feature_geocode_stamps'));
            v_seen:=v_seen||jsonb_build_object(v_ref_key,true);
        END IF;

    END LOOP;

    v_count:=0;
    FOR v_row IN
        SELECT t.tableoid AS relation_oid,t.ctid AS row_tid,feature._heritage_evidence_metadata_bytes(ARRAY[pg_column_size(t.source_record_key)::bigint,pg_column_size(t.source_entity_key)::bigint,pg_column_size(t.raw_payload_hash)::bigint,pg_column_size(t.raw_data)::bigint]::bigint[],ARRAY[(pg_column_compression(t.source_record_key) IS NOT NULL),(pg_column_compression(t.source_entity_key) IS NOT NULL),(pg_column_compression(t.raw_payload_hash) IS NOT NULL),(pg_column_compression(t.raw_data) IS NOT NULL)]::boolean[],ARRAY[64,128,128,8192]::integer[],ARRAY[false,false,false,false]::boolean[]) AS bytes
        FROM provider_sync.source_records t WHERE (CASE WHEN pg_catalog.octet_length(t.source_record_key::text)<=256 THEN t.source_record_key::text ELSE NULL::text END)=ANY(v_record_keys) LIMIT 769
    LOOP
        v_count:=v_count+1;
        IF v_count>768 THEN
            RETURN jsonb_build_object('metadata_complete',false,'reason','budget_exceeded');
        END IF;
        IF v_row.bytes<0 THEN
            RETURN jsonb_build_object('metadata_complete',false,'reason','storage_unsupported');
        END IF;
        -- descriptor/고정 길이 열/JSON envelope 여유도 함께 누적한다.
        v_total:=v_total+v_row.bytes+256;
        IF v_total>4194304 THEN
            RETURN jsonb_build_object('metadata_complete',false,'reason','budget_exceeded');
        END IF;
        v_ref_key:=v_row.relation_oid::text||':'||v_row.row_tid::text;
        IF NOT(v_seen ? v_ref_key) THEN
            v_refs:=v_refs||jsonb_build_array(jsonb_build_object(
                'relation',v_row.relation_oid,'tid',v_row.row_tid::text,'kind','source_records'));
            v_seen:=v_seen||jsonb_build_object(v_ref_key,true);
        END IF;

    END LOOP;
    IF v_count<>cardinality(v_record_keys) THEN
        RETURN jsonb_build_object('metadata_complete',false,'reason','lineage_incomplete');
    END IF;
    -- 내부 참조만 반환한다. 공개 response/manifest/다음 호출에 재사용하지 않는다.
    RETURN jsonb_build_object('metadata_complete',true,'binary_bytes',v_total,
        'refs',v_refs,'feature_ids',to_jsonb(v_features));
END;
$$;
