-- private helper만 추가한다. 이 파일은 metadata 전체 예산 통과 뒤에만 호출된다.
-- JSONB payload를 metadata helper 인자로 넘기거나 text로 먼저 변환하지 않는다.
CREATE FUNCTION feature._heritage_evidence_string_object(p_value jsonb,p_keys text[])
RETURNS boolean LANGUAGE plpgsql IMMUTABLE SET search_path TO pg_catalog AS $$
DECLARE v_key text; v_value jsonb; v_count integer:=0;
BEGIN
    IF p_value IS NULL OR jsonb_typeof(p_value) IS DISTINCT FROM 'object' THEN
        RETURN false;
    END IF;
    FOR v_key,v_value IN SELECT key,value FROM jsonb_each(p_value) LOOP
        v_count:=v_count+1;
        IF NOT(v_key=ANY(p_keys)) OR jsonb_typeof(v_value) NOT IN ('string','null') THEN
            RETURN false;
        END IF;
    END LOOP;
    RETURN v_count=cardinality(p_keys);
END;
$$;
REVOKE ALL ON FUNCTION feature._heritage_evidence_string_object(jsonb,text[])
FROM PUBLIC,ktm_feature_runtime;

CREATE FUNCTION feature._heritage_evidence_shape(
    p_raw jsonb,p_base jsonb,p_coord_json jsonb,p_geometry x_extension.geometry
) RETURNS boolean LANGUAGE plpgsql IMMUTABLE SET search_path TO pg_catalog AS $$
DECLARE v_key text; v_value jsonb; v_count integer:=0; v_precision numeric;
BEGIN
    -- 각 JSON은 직접 저장 metadata 검사/전체 binary 예산 뒤에만 여기에 온다.
    IF NOT feature._heritage_evidence_string_object(p_raw,ARRAY[
        'ccba_kdcd','ccba_asno','ccba_ctcd','name_ko','category','region','sigungu',
        'longitude','latitude','location_text','designated_at','manager','image_url'
    ]) THEN RETURN false; END IF;
    FOREACH v_key IN ARRAY ARRAY['ccba_kdcd','ccba_asno','ccba_ctcd'] LOOP
        -- string/null shape를 먼저 검사했으므로 numeric text 팽창은 없다.
        IF jsonb_typeof(p_raw->v_key) IS DISTINCT FROM 'string'
           OR length(p_raw->>v_key) NOT BETWEEN 1 AND 32
           OR (p_raw->>v_key) !~ '^[0-9]+$' THEN RETURN false; END IF;
    END LOOP;
    IF jsonb_typeof(p_raw->'name_ko') IS DISTINCT FROM 'string'
       OR p_raw->>'name_ko'='' THEN RETURN false; END IF;
    -- 첫 reader는 file_sources 의무를 추가하지 않는다. image가 있으면 전체 EX다.
    IF p_raw->'image_url' IS DISTINCT FROM 'null'::jsonb THEN RETURN false; END IF;
    IF (p_raw->'longitude'='null'::jsonb) IS DISTINCT FROM
       (p_raw->'latitude'='null'::jsonb) THEN RETURN false; END IF;
    -- Decimal/provider 의미 판정은 공개 SDK/A1이 계속 소유한다. 여기서는 재구현하지 않는다.
    IF p_base IS NULL OR jsonb_typeof(p_base) IS DISTINCT FROM 'object' THEN
        RETURN false;
    END IF;
    FOR v_key,v_value IN SELECT key,value FROM jsonb_each(p_base) LOOP
        v_count:=v_count+1;
        IF NOT(v_key=ANY(ARRAY[
            'core.category','core.coord_precision_digits','core.address',
            'core.legal_dong_code','core.road_name_code','core.road_address_management_no',
            'core.admin_dong_code','core.sido_code','core.sigungu_code','core.urls',
            'core.marker_icon','core.marker_color','core.parent_feature_id',
            'core.sibling_group_id','core.raw_refs','place.place_kind','place.phones',
            'place.biz_number','place.license_date','place.business_hours',
            'place.facility_info','place.reviews_link','place.payload'
        ])) THEN RETURN false; END IF;
    END LOOP;
    IF v_count<>23 THEN RETURN false; END IF;
    FOREACH v_key IN ARRAY ARRAY[
        'core.category','core.legal_dong_code','core.road_name_code',
        'core.road_address_management_no','core.admin_dong_code','core.sido_code',
        'core.sigungu_code','core.marker_icon','core.marker_color','place.place_kind'
    ] LOOP
        IF jsonb_typeof(p_base->v_key) NOT IN ('string','null') THEN RETURN false; END IF;
    END LOOP;
    IF jsonb_typeof(p_base->'core.category') IS DISTINCT FROM 'string'
       OR jsonb_typeof(p_base->'place.place_kind') IS DISTINCT FROM 'string'
       OR NOT feature._heritage_evidence_string_object(p_base->'core.address',ARRAY[
           'road','legal','admin','bjd_code','admin_dong_code','sigungu_code','sido_code',
           'road_name_code','road_address_management_no','zipcode','sido_name','sigungu_name'
       ])
       OR NOT feature._heritage_evidence_string_object(p_base->'place.payload',ARRAY[
           'heritage_kind_code','heritage_type','designated_date','manager'
       ]) THEN RETURN false; END IF;
    IF p_base->'core.urls' IS DISTINCT FROM jsonb_build_object(
        'homepage',NULL,'sns1',NULL,'sns2',NULL,'review_naver',NULL,
        'review_kakao',NULL,'review_google',NULL)
       OR p_base->'core.raw_refs' IS DISTINCT FROM '[]'::jsonb
       OR p_base->'place.phones' IS DISTINCT FROM '[]'::jsonb
       OR p_base->'place.facility_info' IS DISTINCT FROM '{}'::jsonb
       OR p_base->'place.reviews_link' IS DISTINCT FROM '{}'::jsonb THEN
        RETURN false;
    END IF;
    FOREACH v_key IN ARRAY ARRAY[
        'core.parent_feature_id','core.sibling_group_id','place.biz_number',
        'place.license_date','place.business_hours'
    ] LOOP
        IF p_base->v_key IS DISTINCT FROM 'null'::jsonb THEN RETURN false; END IF;
    END LOOP;
    -- Geometry의 SQL NULL과 JSON null을 합치지 않는다.
    IF p_geometry IS NULL THEN
        RETURN p_coord_json IS NOT NULL AND p_coord_json='null'::jsonb
           AND p_base->'core.coord_precision_digits'='null'::jsonb;
    END IF;
    IF p_coord_json IS NOT NULL THEN RETURN false; END IF;
    IF x_extension.st_geometrytype(p_geometry) IS DISTINCT FROM 'ST_Point'
       OR x_extension.st_srid(p_geometry)<>4326
       OR x_extension.st_ndims(p_geometry)<>2
       OR x_extension.st_isempty(p_geometry) THEN RETURN false; END IF;
    IF NOT(x_extension.st_x(p_geometry) BETWEEN 124 AND 132)
       OR NOT(x_extension.st_y(p_geometry) BETWEEN 33 AND 39.5) THEN RETURN false; END IF;
    IF jsonb_typeof(p_base->'core.coord_precision_digits') IS DISTINCT FROM 'number' THEN
        RETURN false;
    END IF;
    -- JSONB numeric의 binary 복사/scale/범위 검사를 text 직렬화보다 먼저 한다.
    v_precision:=(p_base->'core.coord_precision_digits')::numeric;
    IF scale(v_precision) IS DISTINCT FROM 0 OR v_precision<3 OR v_precision>8 THEN
        RETURN false;
    END IF;
    -- 현재 공개 Heritage converter의 유좌표 default6만 최초 subset으로 지원한다.
    RETURN v_precision=6;
END;
$$;
REVOKE ALL ON FUNCTION feature._heritage_evidence_shape(
    jsonb,jsonb,jsonb,x_extension.geometry
) FROM PUBLIC,ktm_feature_runtime;
