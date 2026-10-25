-- 동일 statement snapshot의 현재 capture를 제한한다. 호출자/SH는 연결하지 않는다.
CREATE FUNCTION feature._bounded_provider_curation_input_set(p_provider_dataset_id bigint)
RETURNS TABLE(
    capture_complete boolean, reason text, source_entity_count bigint,
    input_member_count bigint, last_source_modified_at date, source_input_set_hash text
) LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path TO pg_catalog AS $$
DECLARE
    v_entity_ref record;
    v_meta record;
    v_link_ref record;
    v_link record;
    v_core record;
    v_place record;
    v_capture record;
    v_key text;
    v_record_key text;
    v_feature_id uuid;
    v_raw_hash text;
    v_phone text;
    v_bytes bigint := 0;
    v_encoded bigint := 0;
    v_count integer := 0;
    v_expected_count integer;
    v_links integer;
    v_row_bytes integer;
    v_catalog text[];
BEGIN
    capture_complete := false;
    reason := 'scope_unsupported';
    IF p_provider_dataset_id IS NULL OR p_provider_dataset_id < 1 THEN
        RETURN NEXT; RETURN;
    END IF;

    -- WHERE false로 payload 없이 관계를 열어 열 변경의 ACCESS EXCLUSIVE와 경합한다.
    PERFORM 1 FROM ONLY provider_sync.source_entities, ONLY provider_sync.source_entity_heads,
        ONLY provider_sync.source_records, ONLY provider_sync.source_links,
        ONLY feature.features, ONLY feature.feature_places, ONLY feature.feature_events,
        ONLY feature.feature_notices, ONLY feature.feature_routes,
        ONLY feature.feature_route_geometries, ONLY feature.feature_areas,
        ONLY ops.feature_overrides WHERE false;
    IF EXISTS (
        SELECT 1 FROM pg_class AS c
        WHERE c.oid = ANY(ARRAY[
            'provider_sync.source_entities'::regclass,'provider_sync.source_entity_heads'::regclass,
            'provider_sync.source_records'::regclass,'provider_sync.source_links'::regclass,
            'feature.features'::regclass,'feature.feature_places'::regclass,
            'feature.feature_events'::regclass,'feature.feature_notices'::regclass,
            'feature.feature_routes'::regclass,'feature.feature_route_geometries'::regclass,
            'feature.feature_areas'::regclass,'ops.feature_overrides'::regclass
        ]) AND (c.relkind <> 'r' OR EXISTS(
            SELECT 1 FROM pg_inherits AS i WHERE i.inhparent=c.oid OR i.inhrelid=c.oid
        ))
    ) THEN
        reason := 'storage_unsupported'; RETURN NEXT; RETURN;
    END IF;
    SELECT array_agg(a.attname::text || ':' || a.atttypid::text || ':' ||
        a.attndims::text || ':' || a.atttypmod::text ORDER BY a.attnum)
    INTO v_catalog FROM pg_attribute AS a
    WHERE a.attrelid='feature.feature_places'::regclass AND a.attnum>0 AND NOT a.attisdropped;
    IF v_catalog IS DISTINCT FROM ARRAY[
        'feature_id:2950:0:-1','kind:1043:0:-1','place_kind:1043:0:-1',
        'phones:1009:1:-1','biz_number:1043:0:-1','license_date:1082:0:-1',
        'business_hours:3802:0:-1','facility_info:3802:0:-1',
        'reviews_link:3802:0:-1','payload:3802:0:-1'
    ]::text[] THEN
        reason := 'storage_unsupported'; RETURN NEXT; RETURN;
    END IF;

    -- 수량만 MAX+1 조사한다. 키 정렬/본문/이력 표를 먼저 읽지 않는다.
    SELECT count(*) INTO v_expected_count FROM (
        SELECT 1 FROM ONLY provider_sync.source_entities
        WHERE provider_dataset_id=p_provider_dataset_id LIMIT 2731
    ) AS bounded_entities;
    IF v_expected_count=0 THEN reason := 'scope_unsupported'; RETURN NEXT; RETURN; END IF;
    IF v_expected_count>2730 THEN reason := 'budget_exceeded'; RETURN NEXT; RETURN; END IF;

    FOR v_entity_ref IN
        SELECT t.ctid AS row_tid, feature._heritage_evidence_metadata_bytes(ARRAY[pg_column_size(t.source_entity_key)::bigint]::bigint[], ARRAY[(pg_column_compression(t.source_entity_key) IS NOT NULL)]::boolean[], ARRAY[256]::integer[], ARRAY[false]::boolean[]) AS bytes
        FROM ONLY provider_sync.source_entities AS t
        WHERE t.provider_dataset_id=p_provider_dataset_id LIMIT 2731
    LOOP
        v_count := v_count+1;
        IF v_count>2730 THEN
            reason := 'budget_exceeded'; RETURN NEXT; RETURN;
        END IF;
        IF v_entity_ref.bytes<0 THEN
            reason := 'storage_unsupported'; RETURN NEXT; RETURN;
        END IF;
        v_bytes := v_bytes+v_entity_ref.bytes;
        IF v_bytes>262144 THEN
            reason := 'budget_exceeded'; RETURN NEXT; RETURN;
        END IF;
        SELECT t.source_entity_key INTO STRICT v_key
        FROM ONLY provider_sync.source_entities AS t WHERE t.ctid=v_entity_ref.row_tid;

        SELECT feature._heritage_evidence_metadata_bytes(ARRAY[pg_column_size(t.source_entity_key)::bigint, pg_column_size(t.current_source_record_key)::bigint]::bigint[], ARRAY[(pg_column_compression(t.source_entity_key) IS NOT NULL), (pg_column_compression(t.current_source_record_key) IS NOT NULL)]::boolean[], ARRAY[256, 256]::integer[], ARRAY[false, false]::boolean[]) AS bytes INTO v_meta
        FROM ONLY provider_sync.source_entity_heads AS t WHERE t.source_entity_key=v_key;
        IF NOT FOUND THEN
            reason := 'lineage_incomplete'; RETURN NEXT; RETURN;
        END IF;
        IF v_meta.bytes<0 THEN
            reason := 'storage_unsupported'; RETURN NEXT; RETURN;
        END IF;
        v_bytes := v_bytes+v_meta.bytes;
        IF v_bytes>262144 THEN reason := 'budget_exceeded'; RETURN NEXT; RETURN; END IF;
        SELECT t.current_source_record_key INTO STRICT v_record_key
        FROM ONLY provider_sync.source_entity_heads AS t WHERE t.source_entity_key=v_key;

        SELECT feature._heritage_evidence_metadata_bytes(ARRAY[pg_column_size(t.source_entity_key)::bigint, pg_column_size(t.source_record_key)::bigint, pg_column_size(t.raw_payload_hash)::bigint]::bigint[], ARRAY[(pg_column_compression(t.source_entity_key) IS NOT NULL), (pg_column_compression(t.source_record_key) IS NOT NULL), (pg_column_compression(t.raw_payload_hash) IS NOT NULL)]::boolean[], ARRAY[256, 256, 256]::integer[], ARRAY[false, false, false]::boolean[]) AS bytes INTO v_meta
        FROM ONLY provider_sync.source_records AS t
        WHERE t.source_record_key=v_record_key AND t.source_entity_key=v_key;
        IF NOT FOUND THEN
            reason := 'lineage_incomplete'; RETURN NEXT; RETURN;
        END IF;
        IF v_meta.bytes<0 THEN reason := 'storage_unsupported'; RETURN NEXT; RETURN; END IF;
        v_bytes := v_bytes+v_meta.bytes;
        IF v_bytes>262144 THEN reason := 'budget_exceeded'; RETURN NEXT; RETURN; END IF;
        SELECT t.raw_payload_hash INTO STRICT v_raw_hash FROM ONLY provider_sync.source_records AS t
        WHERE t.source_record_key=v_record_key AND t.source_entity_key=v_key;

        v_links := 0;
        FOR v_link_ref IN
            SELECT t.feature_id, feature._heritage_evidence_metadata_bytes(ARRAY[pg_column_size(t.source_entity_key)::bigint, pg_column_size(t.source_role)::bigint, pg_column_size(t.match_method)::bigint]::bigint[], ARRAY[(pg_column_compression(t.source_entity_key) IS NOT NULL), (pg_column_compression(t.source_role) IS NOT NULL), (pg_column_compression(t.match_method) IS NOT NULL)]::boolean[], ARRAY[256, 256, 256]::integer[], ARRAY[false, false, false]::boolean[]) AS bytes
            FROM ONLY provider_sync.source_links AS t WHERE t.source_entity_key=v_key LIMIT 2
        LOOP
            v_links := v_links+1;
            IF v_links>1 THEN reason := 'membership_unsupported'; RETURN NEXT; RETURN; END IF;
            IF v_link_ref.bytes<0 THEN reason := 'storage_unsupported'; RETURN NEXT; RETURN; END IF;
            v_bytes := v_bytes+v_link_ref.bytes;
            IF v_bytes>262144 THEN reason := 'budget_exceeded'; RETURN NEXT; RETURN; END IF;
            v_feature_id := v_link_ref.feature_id;
        END LOOP;
        IF v_links<>1 THEN reason := 'membership_unsupported'; RETURN NEXT; RETURN; END IF;
        SELECT t.source_role,t.match_method,t.confidence INTO STRICT v_link
        FROM ONLY provider_sync.source_links AS t WHERE t.source_entity_key=v_key;
        IF v_link.source_role IS DISTINCT FROM 'primary' OR
            (SELECT count(*) FROM (
                SELECT 1 FROM ONLY provider_sync.source_links WHERE feature_id=v_feature_id LIMIT 2
            ) AS bounded_links)<>1 THEN
            reason := 'membership_unsupported'; RETURN NEXT; RETURN;
        END IF;
        IF EXISTS(SELECT 1 FROM ONLY ops.feature_overrides WHERE feature_id=v_feature_id LIMIT 1)
           OR EXISTS(SELECT 1 FROM ONLY feature.feature_events WHERE feature_id=v_feature_id LIMIT 1)
           OR EXISTS(SELECT 1 FROM ONLY feature.feature_notices WHERE feature_id=v_feature_id LIMIT 1)
           OR EXISTS(SELECT 1 FROM ONLY feature.feature_routes WHERE feature_id=v_feature_id LIMIT 1)
           OR EXISTS(SELECT 1 FROM ONLY feature.feature_route_geometries WHERE feature_id=v_feature_id LIMIT 1)
           OR EXISTS(SELECT 1 FROM ONLY feature.feature_areas WHERE feature_id=v_feature_id LIMIT 1) THEN
            reason := 'membership_unsupported'; RETURN NEXT; RETURN;
        END IF;

        SELECT feature._heritage_evidence_metadata_bytes(ARRAY[pg_column_size(t.kind)::bigint, pg_column_size(t.lifecycle_state)::bigint, pg_column_size(t.publication_state)::bigint, pg_column_size(t.quality_state)::bigint]::bigint[], ARRAY[(pg_column_compression(t.kind) IS NOT NULL), (pg_column_compression(t.lifecycle_state) IS NOT NULL), (pg_column_compression(t.publication_state) IS NOT NULL), (pg_column_compression(t.quality_state) IS NOT NULL)]::boolean[], ARRAY[256, 256, 256, 256]::integer[], ARRAY[false, false, false, false]::boolean[]) AS bytes INTO v_meta FROM ONLY feature.features AS t
        WHERE t.feature_id=v_feature_id;
        IF NOT FOUND THEN reason := 'lineage_incomplete'; RETURN NEXT; RETURN; END IF;
        IF v_meta.bytes<0 THEN reason := 'storage_unsupported'; RETURN NEXT; RETURN; END IF;
        v_bytes := v_bytes+v_meta.bytes;
        IF v_bytes>262144 THEN reason := 'budget_exceeded'; RETURN NEXT; RETURN; END IF;
        SELECT t.kind,t.row_revision,t.lifecycle_state,t.publication_state,t.quality_state INTO STRICT v_core
        FROM ONLY feature.features AS t WHERE t.feature_id=v_feature_id;
        IF v_core.kind IS DISTINCT FROM 'place' OR v_core.lifecycle_state IS DISTINCT FROM 'active' THEN
            reason := 'membership_unsupported'; RETURN NEXT; RETURN;
        END IF;
        SELECT feature._heritage_evidence_metadata_bytes(ARRAY[pg_column_size(t.kind)::bigint, pg_column_size(t.place_kind)::bigint, pg_column_size(t.phones)::bigint, pg_column_size(t.biz_number)::bigint, pg_column_size(t.business_hours)::bigint, pg_column_size(t.facility_info)::bigint, pg_column_size(t.reviews_link)::bigint, pg_column_size(t.payload)::bigint]::bigint[], ARRAY[(pg_column_compression(t.kind) IS NOT NULL), (pg_column_compression(t.place_kind) IS NOT NULL), (pg_column_compression(t.phones) IS NOT NULL), (pg_column_compression(t.biz_number) IS NOT NULL), (pg_column_compression(t.business_hours) IS NOT NULL), (pg_column_compression(t.facility_info) IS NOT NULL), (pg_column_compression(t.reviews_link) IS NOT NULL), (pg_column_compression(t.payload) IS NOT NULL)]::boolean[], ARRAY[256, 256, 8192, 256, 8192, 8192, 8192, 8192]::integer[], ARRAY[false, false, false, true, true, false, false, false]::boolean[]) AS bytes INTO v_meta FROM ONLY feature.feature_places AS t
        WHERE t.feature_id=v_feature_id;
        IF NOT FOUND THEN reason := 'lineage_incomplete'; RETURN NEXT; RETURN; END IF;
        IF v_meta.bytes<0 THEN reason := 'storage_unsupported'; RETURN NEXT; RETURN; END IF;
        v_bytes := v_bytes+v_meta.bytes;
        IF v_bytes>262144 THEN reason := 'budget_exceeded'; RETURN NEXT; RETURN; END IF;
        SELECT t.* INTO STRICT v_place FROM ONLY feature.feature_places AS t
        WHERE t.feature_id=v_feature_id;
        IF v_place.kind IS DISTINCT FROM 'place' OR v_place.business_hours IS NOT NULL
            OR v_place.phones IS NULL THEN
            reason := 'shape_unsupported'; RETURN NEXT; RETURN;
        END IF;
        IF cardinality(v_place.phones)>0 THEN
            IF cardinality(v_place.phones)>32 OR array_ndims(v_place.phones) IS DISTINCT FROM 1
               OR array_lower(v_place.phones,1) IS DISTINCT FROM 1 THEN
                reason := 'shape_unsupported'; RETURN NEXT; RETURN;
            END IF;
            FOREACH v_phone IN ARRAY v_place.phones LOOP
                IF v_phone IS NULL OR octet_length(v_phone)>256 THEN
                    reason := 'shape_unsupported'; RETURN NEXT; RETURN;
                END IF;
            END LOOP;
        END IF;
        IF NOT feature._bounded_curation_string_object(v_place.facility_info)
           OR NOT feature._bounded_curation_string_object(v_place.reviews_link)
           OR NOT feature._bounded_curation_string_object(v_place.payload) THEN
            reason := 'shape_unsupported'; RETURN NEXT; RETURN;
        END IF;
        -- 기존 canonical 행을 개별 생성한다. 전체 aggregate를 먼저 만들지 않는다.
        v_row_bytes := octet_length(convert_to(jsonb_build_array(
            v_key,v_record_key,v_raw_hash,v_feature_id,v_link.source_role,
            v_link.match_method,v_link.confidence,v_core.row_revision,
            v_core.lifecycle_state,v_core.publication_state,v_core.quality_state,
            to_jsonb(v_place),'[]'::jsonb
        )::text,'UTF8'));
        IF v_row_bytes>262144 THEN reason := 'budget_exceeded'; RETURN NEXT; RETURN; END IF;
        v_encoded := v_encoded+v_row_bytes;
        IF v_encoded>1048576 THEN reason := 'budget_exceeded'; RETURN NEXT; RETURN; END IF;
    END LOOP;
    IF v_count IS DISTINCT FROM v_expected_count THEN
        reason := 'membership_unsupported'; RETURN NEXT; RETURN;
    END IF;

    -- STABLE의 동일 snapshot이다. 기존4aggregate/hash/정렬/date를 보존한다.
    SELECT * INTO STRICT v_capture FROM feature.current_provider_curation_input_set(p_provider_dataset_id);
    IF v_capture.source_entity_count IS DISTINCT FROM v_count::bigint
       OR v_capture.input_member_count IS DISTINCT FROM v_count::bigint THEN
        reason := 'membership_unsupported'; RETURN NEXT; RETURN;
    END IF;
    capture_complete := true;
    reason := NULL;
    source_entity_count := v_capture.source_entity_count;
    input_member_count := v_capture.input_member_count;
    last_source_modified_at := v_capture.last_source_modified_at;
    source_input_set_hash := v_capture.source_input_set_hash;
    RETURN NEXT;
END;
$$;
