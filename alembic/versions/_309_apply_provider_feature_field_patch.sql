-- ─────────────────────────────────────────────────────────────────────────
-- feature.apply_provider_feature_field_patch
--   p_feature_id / o_feature_id : text → uuid
--     (feature.features.feature_id 가 uuid 이고, 두 callee
--      lock_current_provider_feature_source_evidence · has_active_feature_override
--      가 이미 uuid 를 받는다. infra/feature_repo.py 도 이미 uuid 캐스트로
--      부른다 — 이 프로시저만 text 로 남아 있었다.)
--   p_source_entity_key / p_source_record_key : text 그대로 (Feature id 가 아니다)
--   feature.feature_base_field_values.feature_uuid : 309 _SHADOW_DROP 이 지운다.
--     INSERT 컬럼 목록과 ON CONFLICT SET 에서 함께 뺀다 — feature_id 가 그 값이다.
--   features.parent_feature_id : uuid 로 재타입된다. CASE 두 갈래 타입을 맞추려면
--     캐스트가 필요하다. 형제 루틴 author_feature_field_overrides ·
--     revoke_feature_field_overrides 와 같은 모양을 쓴다.
--   첫머리 DROP 은 **옛** 프로시저를 지운다 — 옛 타입 그대로 둔다.
-- ─────────────────────────────────────────────────────────────────────────
SET ROLE ktm_feature_state_procedure_owner;

DROP PROCEDURE feature.apply_provider_feature_field_patch(text, bigint, text, text, bigint, jsonb, jsonb);

CREATE PROCEDURE feature.apply_provider_feature_field_patch(IN p_feature_id uuid, IN p_provider_dataset_id bigint, IN p_source_entity_key text, IN p_source_record_key text, IN p_expected_row_revision bigint, IN p_values jsonb, IN p_geometry_wkt jsonb, OUT o_feature_id uuid, OUT o_row_revision bigint, OUT o_applied_field_count integer)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog'
    AS $$
DECLARE
    v_feature feature.features%ROWTYPE;
    v_registry ops.feature_override_field_paths%ROWTYPE;
    v_source_hash text;
    v_field_path text;
    v_value jsonb;
    v_geometry_wkt text;
    v_base_revision bigint;
    v_preserved_notice_start jsonb;
BEGIN
    IF p_expected_row_revision IS NULL OR p_expected_row_revision < 1
       OR p_provider_dataset_id IS NULL
       OR coalesce(btrim(p_source_entity_key), '') = ''
       OR coalesce(btrim(p_source_record_key), '') = ''
       OR jsonb_typeof(p_values) <> 'object'
       OR jsonb_typeof(p_geometry_wkt) <> 'object' THEN
        RAISE EXCEPTION 'provider field patch has invalid arguments'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_provider_field_patch';
    END IF;
    SELECT count(*)::integer INTO o_applied_field_count
    FROM (
        SELECT key FROM jsonb_each(p_values)
        UNION ALL
        SELECT key FROM jsonb_each(p_geometry_wkt)
    ) AS supplied_path;
    IF o_applied_field_count = 0 THEN
        RAISE EXCEPTION 'provider field patch must contain at least one field'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_provider_field_patch';
    END IF;
    IF EXISTS (
        SELECT 1
        FROM jsonb_object_keys(p_values) AS scalar_path(field_path)
        JOIN jsonb_object_keys(p_geometry_wkt) AS geometry_path(field_path)
          ON geometry_path.field_path = scalar_path.field_path
    ) THEN
        RAISE EXCEPTION 'a provider field path cannot contain scalar and geometry values'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_provider_field_patch';
    END IF;

    -- Provider writer와 같은 source → link → Feature 순서다. source head는 이
    -- transaction이 끝날 때까지 SHARE lock으로 current evidence를 보존한다.
    v_source_hash := feature.lock_current_provider_feature_source_evidence(
        p_feature_id,
        p_provider_dataset_id,
        p_source_entity_key,
        p_source_record_key
    );
    SELECT * INTO v_feature
    FROM feature.features
    WHERE feature_id = p_feature_id
    FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'feature % does not exist', p_feature_id USING ERRCODE = 'P0002';
    END IF;
    IF v_feature.row_revision <> p_expected_row_revision THEN
        RAISE EXCEPTION 'feature % revision changed', p_feature_id USING ERRCODE = '40001';
    END IF;
    v_base_revision := v_feature.row_revision + 1;
    IF v_feature.kind = 'notice'
       AND p_values -> 'notice.payload' ->> 'valid_start_origin' = 'first_probe'
       AND p_values ? 'notice.valid_start_time' THEN
        SELECT base.value_json INTO v_preserved_notice_start
        FROM feature.feature_base_field_values AS base
        WHERE base.feature_id = p_feature_id
          AND base.field_path = 'notice.valid_start_time'
          AND base.value_json IS NOT NULL
          AND base.value_json <> 'null'::jsonb
        FOR SHARE;
        IF FOUND THEN
            p_values := jsonb_set(
                p_values, ARRAY['notice.valid_start_time'], v_preserved_notice_start, true
            );
        END IF;
    END IF;

    FOR v_field_path, v_value IN SELECT key, value FROM jsonb_each(p_values) LOOP
        SELECT * INTO v_registry
        FROM ops.feature_override_field_paths
        WHERE field_path = v_field_path;
        IF NOT FOUND OR NOT v_registry.provider_writable
           OR v_registry.value_kind = 'geometry'
           OR (v_registry.feature_kind <> '*' AND v_registry.feature_kind <> v_feature.kind) THEN
            RAISE EXCEPTION 'provider cannot write field path %', v_field_path
                USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_provider_field_path';
        END IF;
        INSERT INTO feature.feature_base_field_values (
            feature_id, field_path, provider_dataset_id,
            source_entity_key, source_record_key, source_raw_payload_hash,
            value_json, base_revision, observed_at
        ) VALUES (
            p_feature_id, v_field_path, p_provider_dataset_id,
            p_source_entity_key, p_source_record_key, v_source_hash,
            coalesce(v_value, 'null'::jsonb), v_base_revision, clock_timestamp()
        ) ON CONFLICT (feature_id, field_path) DO UPDATE
        SET provider_dataset_id = EXCLUDED.provider_dataset_id,
            source_entity_key = EXCLUDED.source_entity_key,
            source_record_key = EXCLUDED.source_record_key,
            source_raw_payload_hash = EXCLUDED.source_raw_payload_hash,
            value_json = EXCLUDED.value_json,
            value_geometry = NULL,
            base_revision = EXCLUDED.base_revision,
            observed_at = EXCLUDED.observed_at,
            updated_at = clock_timestamp();
    END LOOP;
    FOR v_field_path, v_value IN SELECT key, value FROM jsonb_each(p_geometry_wkt) LOOP
        SELECT * INTO v_registry
        FROM ops.feature_override_field_paths
        WHERE field_path = v_field_path;
        IF NOT FOUND OR NOT v_registry.provider_writable
           OR v_registry.value_kind <> 'geometry'
           OR (v_registry.feature_kind <> '*' AND v_registry.feature_kind <> v_feature.kind)
           OR (v_value = 'null'::jsonb AND NOT v_registry.allows_null)
           OR (v_value <> 'null'::jsonb AND (
                jsonb_typeof(v_value) <> 'string' OR coalesce(btrim(v_value #>> '{}'), '') = ''
           )) THEN
            RAISE EXCEPTION 'provider cannot write geometry field path %', v_field_path
                USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_provider_field_path';
        END IF;
        INSERT INTO feature.feature_base_field_values (
            feature_id, field_path, provider_dataset_id,
            source_entity_key, source_record_key, source_raw_payload_hash,
            value_json, value_geometry, base_revision, observed_at
        ) VALUES (
            p_feature_id, v_field_path, p_provider_dataset_id,
            p_source_entity_key, p_source_record_key, v_source_hash,
            CASE WHEN v_value = 'null'::jsonb THEN 'null'::jsonb ELSE NULL END,
            CASE WHEN v_value = 'null'::jsonb THEN NULL
                 ELSE CASE v_registry.geometry_type
                      WHEN 'MULTILINESTRING' THEN x_extension.st_multi(x_extension.st_geomfromtext(v_value #>> '{}', 4326))
                      WHEN 'MULTIPOLYGON' THEN x_extension.st_multi(x_extension.st_geomfromtext(v_value #>> '{}', 4326))
                      ELSE x_extension.st_geomfromtext(v_value #>> '{}', 4326)
                 END END,
            v_base_revision, clock_timestamp()
        ) ON CONFLICT (feature_id, field_path) DO UPDATE
        SET provider_dataset_id = EXCLUDED.provider_dataset_id,
            source_entity_key = EXCLUDED.source_entity_key,
            source_record_key = EXCLUDED.source_record_key,
            source_raw_payload_hash = EXCLUDED.source_raw_payload_hash,
            value_json = EXCLUDED.value_json,
            value_geometry = EXCLUDED.value_geometry,
            base_revision = EXCLUDED.base_revision,
            observed_at = EXCLUDED.observed_at,
            updated_at = clock_timestamp();
    END LOOP;

    UPDATE feature.features AS core
    SET name = CASE
            WHEN p_values ? 'core.name'
             AND NOT feature.has_active_feature_override(p_feature_id, 'core.name')
            THEN p_values ->> 'core.name'
            ELSE core.name
        END,
        category = CASE
            WHEN p_values ? 'core.category'
             AND NOT feature.has_active_feature_override(p_feature_id, 'core.category')
            THEN p_values ->> 'core.category'
            ELSE core.category
        END,
        coord = CASE
            WHEN p_geometry_wkt ? 'core.coord'
             AND NOT feature.has_active_feature_override(p_feature_id, 'core.coord')
            THEN CASE WHEN p_geometry_wkt ->> 'core.coord' IS NULL THEN NULL ELSE x_extension.st_geomfromtext(p_geometry_wkt ->> 'core.coord', 4326) END
            ELSE core.coord
        END,
        coord_precision_digits = CASE
            WHEN p_values ? 'core.coord_precision_digits'
             AND NOT feature.has_active_feature_override(p_feature_id, 'core.coord_precision_digits')
            THEN (p_values ->> 'core.coord_precision_digits')::smallint
            ELSE core.coord_precision_digits
        END,
        address = CASE
            WHEN p_values ? 'core.address'
             AND NOT feature.has_active_feature_override(p_feature_id, 'core.address')
            THEN p_values -> 'core.address'
            ELSE core.address
        END,
        legal_dong_code = CASE
            WHEN p_values ? 'core.legal_dong_code'
             AND NOT feature.has_active_feature_override(p_feature_id, 'core.legal_dong_code')
            THEN p_values ->> 'core.legal_dong_code'
            ELSE core.legal_dong_code
        END,
        road_name_code = CASE
            WHEN p_values ? 'core.road_name_code'
             AND NOT feature.has_active_feature_override(p_feature_id, 'core.road_name_code')
            THEN p_values ->> 'core.road_name_code'
            ELSE core.road_name_code
        END,
        road_address_management_no = CASE
            WHEN p_values ? 'core.road_address_management_no'
             AND NOT feature.has_active_feature_override(p_feature_id, 'core.road_address_management_no')
            THEN p_values ->> 'core.road_address_management_no'
            ELSE core.road_address_management_no
        END,
        admin_dong_code = CASE
            WHEN p_values ? 'core.admin_dong_code'
             AND NOT feature.has_active_feature_override(p_feature_id, 'core.admin_dong_code')
            THEN p_values ->> 'core.admin_dong_code'
            ELSE core.admin_dong_code
        END,
        sido_code = CASE
            WHEN p_values ? 'core.sido_code'
             AND NOT feature.has_active_feature_override(p_feature_id, 'core.sido_code')
            THEN p_values ->> 'core.sido_code'
            ELSE core.sido_code
        END,
        sigungu_code = CASE
            WHEN p_values ? 'core.sigungu_code'
             AND NOT feature.has_active_feature_override(p_feature_id, 'core.sigungu_code')
            THEN p_values ->> 'core.sigungu_code'
            ELSE core.sigungu_code
        END,
        urls = CASE
            WHEN p_values ? 'core.urls'
             AND NOT feature.has_active_feature_override(p_feature_id, 'core.urls')
            THEN p_values -> 'core.urls'
            ELSE core.urls
        END,
        marker_icon = CASE
            WHEN p_values ? 'core.marker_icon'
             AND NOT feature.has_active_feature_override(p_feature_id, 'core.marker_icon')
            THEN p_values ->> 'core.marker_icon'
            ELSE core.marker_icon
        END,
        marker_color = CASE
            WHEN p_values ? 'core.marker_color'
             AND NOT feature.has_active_feature_override(p_feature_id, 'core.marker_color')
            THEN p_values ->> 'core.marker_color'
            ELSE core.marker_color
        END,
        parent_feature_id = CASE
            WHEN p_values ? 'core.parent_feature_id'
             AND NOT feature.has_active_feature_override(p_feature_id, 'core.parent_feature_id')
            THEN NULLIF(p_values ->> 'core.parent_feature_id', '')::uuid
            ELSE core.parent_feature_id
        END,
        sibling_group_id = CASE
            WHEN p_values ? 'core.sibling_group_id'
             AND NOT feature.has_active_feature_override(p_feature_id, 'core.sibling_group_id')
            THEN NULLIF(p_values ->> 'core.sibling_group_id', '')::uuid
            ELSE core.sibling_group_id
        END,
        raw_refs = CASE
            WHEN p_values ? 'core.raw_refs'
             AND NOT feature.has_active_feature_override(p_feature_id, 'core.raw_refs')
            THEN p_values -> 'core.raw_refs'
            ELSE core.raw_refs
        END,
        updated_at = clock_timestamp()
    WHERE core.feature_id = p_feature_id
    RETURNING core.feature_id, core.row_revision INTO o_feature_id, o_row_revision;

    IF v_feature.kind = 'place' AND EXISTS (
        SELECT 1
        FROM jsonb_object_keys(p_values) AS supplied_path(field_path)
        WHERE supplied_path.field_path LIKE 'place.%'
    ) THEN
        PERFORM 1 FROM feature.feature_places WHERE feature_id = p_feature_id FOR UPDATE;
        IF NOT FOUND THEN RAISE EXCEPTION 'place subtype is missing' USING ERRCODE = '23514'; END IF;
        UPDATE feature.feature_places AS place
        SET place_kind = CASE
            WHEN p_values ? 'place.place_kind'
             AND NOT feature.has_active_feature_override(p_feature_id, 'place.place_kind')
            THEN p_values ->> 'place.place_kind'
            ELSE place.place_kind
        END,
            phones = CASE
            WHEN p_values ? 'place.phones'
             AND NOT feature.has_active_feature_override(p_feature_id, 'place.phones')
            THEN ARRAY(SELECT jsonb_array_elements_text(p_values -> 'place.phones'))
            ELSE place.phones
        END,
            biz_number = CASE
            WHEN p_values ? 'place.biz_number'
             AND NOT feature.has_active_feature_override(p_feature_id, 'place.biz_number')
            THEN p_values ->> 'place.biz_number'
            ELSE place.biz_number
        END,
            license_date = CASE
            WHEN p_values ? 'place.license_date'
             AND NOT feature.has_active_feature_override(p_feature_id, 'place.license_date')
            THEN (p_values ->> 'place.license_date')::date
            ELSE place.license_date
        END,
            business_hours = CASE
            WHEN p_values ? 'place.business_hours'
             AND NOT feature.has_active_feature_override(p_feature_id, 'place.business_hours')
            THEN p_values -> 'place.business_hours'
            ELSE place.business_hours
        END,
            facility_info = CASE
            WHEN p_values ? 'place.facility_info'
             AND NOT feature.has_active_feature_override(p_feature_id, 'place.facility_info')
            THEN p_values -> 'place.facility_info'
            ELSE place.facility_info
        END,
            reviews_link = CASE
            WHEN p_values ? 'place.reviews_link'
             AND NOT feature.has_active_feature_override(p_feature_id, 'place.reviews_link')
            THEN p_values -> 'place.reviews_link'
            ELSE place.reviews_link
        END,
            payload = CASE
            WHEN p_values ? 'place.payload'
             AND NOT feature.has_active_feature_override(p_feature_id, 'place.payload')
            THEN p_values -> 'place.payload'
            ELSE place.payload
        END
      WHERE place.feature_id = p_feature_id;
    ELSIF v_feature.kind = 'event' AND EXISTS (
        SELECT 1
        FROM jsonb_object_keys(p_values) AS supplied_path(field_path)
        WHERE supplied_path.field_path LIKE 'event.%'
    ) THEN
        PERFORM 1 FROM feature.feature_events WHERE feature_id = p_feature_id FOR UPDATE;
        IF NOT FOUND THEN RAISE EXCEPTION 'event subtype is missing' USING ERRCODE = '23514'; END IF;
        UPDATE feature.feature_events AS event
        SET event_kind = CASE
            WHEN p_values ? 'event.event_kind'
             AND NOT feature.has_active_feature_override(p_feature_id, 'event.event_kind')
            THEN p_values ->> 'event.event_kind'
            ELSE event.event_kind
        END,
            starts_on = CASE
            WHEN p_values ? 'event.starts_on'
             AND NOT feature.has_active_feature_override(p_feature_id, 'event.starts_on')
            THEN (p_values ->> 'event.starts_on')::date
            ELSE event.starts_on
        END,
            ends_on = CASE
            WHEN p_values ? 'event.ends_on'
             AND NOT feature.has_active_feature_override(p_feature_id, 'event.ends_on')
            THEN (p_values ->> 'event.ends_on')::date
            ELSE event.ends_on
        END,
            timezone = CASE
            WHEN p_values ? 'event.timezone'
             AND NOT feature.has_active_feature_override(p_feature_id, 'event.timezone')
            THEN p_values ->> 'event.timezone'
            ELSE event.timezone
        END,
            opening_hours = CASE
            WHEN p_values ? 'event.opening_hours'
             AND NOT feature.has_active_feature_override(p_feature_id, 'event.opening_hours')
            THEN p_values -> 'event.opening_hours'
            ELSE event.opening_hours
        END,
            venue_name = CASE
            WHEN p_values ? 'event.venue_name'
             AND NOT feature.has_active_feature_override(p_feature_id, 'event.venue_name')
            THEN p_values ->> 'event.venue_name'
            ELSE event.venue_name
        END,
            tel = CASE
            WHEN p_values ? 'event.tel'
             AND NOT feature.has_active_feature_override(p_feature_id, 'event.tel')
            THEN p_values ->> 'event.tel'
            ELSE event.tel
        END,
            content_id = CASE
            WHEN p_values ? 'event.content_id'
             AND NOT feature.has_active_feature_override(p_feature_id, 'event.content_id')
            THEN p_values ->> 'event.content_id'
            ELSE event.content_id
        END,
            content_type_id = CASE
            WHEN p_values ? 'event.content_type_id'
             AND NOT feature.has_active_feature_override(p_feature_id, 'event.content_type_id')
            THEN p_values ->> 'event.content_type_id'
            ELSE event.content_type_id
        END,
            area_code = CASE
            WHEN p_values ? 'event.area_code'
             AND NOT feature.has_active_feature_override(p_feature_id, 'event.area_code')
            THEN p_values ->> 'event.area_code'
            ELSE event.area_code
        END,
            sigungu_code = CASE
            WHEN p_values ? 'event.sigungu_code'
             AND NOT feature.has_active_feature_override(p_feature_id, 'event.sigungu_code')
            THEN p_values ->> 'event.sigungu_code'
            ELSE event.sigungu_code
        END,
            payload = CASE
            WHEN p_values ? 'event.payload'
             AND NOT feature.has_active_feature_override(p_feature_id, 'event.payload')
            THEN p_values -> 'event.payload'
            ELSE event.payload
        END
      WHERE event.feature_id = p_feature_id;
    ELSIF v_feature.kind = 'notice' AND EXISTS (
        SELECT 1
        FROM jsonb_object_keys(p_values) AS supplied_path(field_path)
        WHERE supplied_path.field_path LIKE 'notice.%'
    ) THEN
        PERFORM 1 FROM feature.feature_notices WHERE feature_id = p_feature_id FOR UPDATE;
        IF NOT FOUND THEN RAISE EXCEPTION 'notice subtype is missing' USING ERRCODE = '23514'; END IF;
        UPDATE feature.feature_notices AS notice
        SET notice_type = CASE
            WHEN p_values ? 'notice.notice_type'
             AND NOT feature.has_active_feature_override(p_feature_id, 'notice.notice_type')
            THEN p_values ->> 'notice.notice_type'
            ELSE notice.notice_type
        END,
            severity = CASE
            WHEN p_values ? 'notice.severity'
             AND NOT feature.has_active_feature_override(p_feature_id, 'notice.severity')
            THEN (p_values ->> 'notice.severity')::smallint
            ELSE notice.severity
        END,
            valid_start_time = CASE
            WHEN p_values ? 'notice.valid_start_time'
             AND NOT feature.has_active_feature_override(p_feature_id, 'notice.valid_start_time')
            THEN (p_values ->> 'notice.valid_start_time')::timestamptz
            ELSE notice.valid_start_time
        END,
            valid_end_time = CASE
            WHEN p_values ? 'notice.valid_end_time'
             AND NOT feature.has_active_feature_override(p_feature_id, 'notice.valid_end_time')
            THEN (p_values ->> 'notice.valid_end_time')::timestamptz
            ELSE notice.valid_end_time
        END,
            source_agency = CASE
            WHEN p_values ? 'notice.source_agency'
             AND NOT feature.has_active_feature_override(p_feature_id, 'notice.source_agency')
            THEN p_values ->> 'notice.source_agency'
            ELSE notice.source_agency
        END,
            officer_name = CASE
            WHEN p_values ? 'notice.officer_name'
             AND NOT feature.has_active_feature_override(p_feature_id, 'notice.officer_name')
            THEN p_values ->> 'notice.officer_name'
            ELSE notice.officer_name
        END,
            payload = CASE
            WHEN p_values ? 'notice.payload'
             AND NOT feature.has_active_feature_override(p_feature_id, 'notice.payload')
            THEN p_values -> 'notice.payload'
            ELSE notice.payload
        END
      WHERE notice.feature_id = p_feature_id;
    ELSIF v_feature.kind = 'route' AND (
        EXISTS (
            SELECT 1
            FROM jsonb_object_keys(p_values) AS supplied_path(field_path)
            WHERE supplied_path.field_path LIKE 'route.%'
        )
        OR EXISTS (
            SELECT 1
            FROM jsonb_object_keys(p_geometry_wkt) AS supplied_path(field_path)
            WHERE supplied_path.field_path LIKE 'route.%'
        )
    ) THEN
        PERFORM 1 FROM feature.feature_routes WHERE feature_id = p_feature_id FOR UPDATE;
        IF NOT FOUND THEN RAISE EXCEPTION 'route subtype is missing' USING ERRCODE = '23514'; END IF;
        UPDATE feature.feature_routes AS route
        SET geom = CASE
            WHEN p_geometry_wkt ? 'route.geom'
             AND NOT feature.has_active_feature_override(p_feature_id, 'route.geom')
            THEN x_extension.st_multi(x_extension.st_geomfromtext(p_geometry_wkt ->> 'route.geom', 4326))
            ELSE route.geom
        END,
            route_type = CASE
            WHEN p_values ? 'route.route_type'
             AND NOT feature.has_active_feature_override(p_feature_id, 'route.route_type')
            THEN p_values ->> 'route.route_type'
            ELSE route.route_type
        END,
            geometry_source = CASE
            WHEN p_values ? 'route.geometry_source'
             AND NOT feature.has_active_feature_override(p_feature_id, 'route.geometry_source')
            THEN p_values ->> 'route.geometry_source'
            ELSE route.geometry_source
        END,
            geometry_status = CASE
            WHEN p_values ? 'route.geometry_status'
             AND NOT feature.has_active_feature_override(p_feature_id, 'route.geometry_status')
            THEN p_values ->> 'route.geometry_status'
            ELSE route.geometry_status
        END,
            total_distance_meters = CASE
            WHEN p_values ? 'route.total_distance_meters'
             AND NOT feature.has_active_feature_override(p_feature_id, 'route.total_distance_meters')
            THEN (p_values ->> 'route.total_distance_meters')::numeric
            ELSE route.total_distance_meters
        END,
            expected_duration_minutes = CASE
            WHEN p_values ? 'route.expected_duration_minutes'
             AND NOT feature.has_active_feature_override(p_feature_id, 'route.expected_duration_minutes')
            THEN (p_values ->> 'route.expected_duration_minutes')::integer
            ELSE route.expected_duration_minutes
        END,
            difficulty = CASE
            WHEN p_values ? 'route.difficulty'
             AND NOT feature.has_active_feature_override(p_feature_id, 'route.difficulty')
            THEN p_values ->> 'route.difficulty'
            ELSE route.difficulty
        END,
            begin_name = CASE
            WHEN p_values ? 'route.begin_name'
             AND NOT feature.has_active_feature_override(p_feature_id, 'route.begin_name')
            THEN p_values ->> 'route.begin_name'
            ELSE route.begin_name
        END,
            begin_address = CASE
            WHEN p_values ? 'route.begin_address'
             AND NOT feature.has_active_feature_override(p_feature_id, 'route.begin_address')
            THEN p_values ->> 'route.begin_address'
            ELSE route.begin_address
        END,
            end_name = CASE
            WHEN p_values ? 'route.end_name'
             AND NOT feature.has_active_feature_override(p_feature_id, 'route.end_name')
            THEN p_values ->> 'route.end_name'
            ELSE route.end_name
        END,
            end_address = CASE
            WHEN p_values ? 'route.end_address'
             AND NOT feature.has_active_feature_override(p_feature_id, 'route.end_address')
            THEN p_values ->> 'route.end_address'
            ELSE route.end_address
        END,
            payload = CASE
            WHEN p_values ? 'route.payload'
             AND NOT feature.has_active_feature_override(p_feature_id, 'route.payload')
            THEN p_values -> 'route.payload'
            ELSE route.payload
        END
      WHERE route.feature_id = p_feature_id;
    ELSIF v_feature.kind = 'area' AND (
        EXISTS (
            SELECT 1
            FROM jsonb_object_keys(p_values) AS supplied_path(field_path)
            WHERE supplied_path.field_path LIKE 'area.%'
        )
        OR EXISTS (
            SELECT 1
            FROM jsonb_object_keys(p_geometry_wkt) AS supplied_path(field_path)
            WHERE supplied_path.field_path LIKE 'area.%'
        )
    ) THEN
        PERFORM 1 FROM feature.feature_areas WHERE feature_id = p_feature_id FOR UPDATE;
        IF NOT FOUND THEN RAISE EXCEPTION 'area subtype is missing' USING ERRCODE = '23514'; END IF;
        UPDATE feature.feature_areas AS area
        SET geom = CASE
            WHEN p_geometry_wkt ? 'area.geom'
             AND NOT feature.has_active_feature_override(p_feature_id, 'area.geom')
            THEN x_extension.st_multi(x_extension.st_geomfromtext(p_geometry_wkt ->> 'area.geom', 4326))
            ELSE area.geom
        END,
            area_kind = CASE
            WHEN p_values ? 'area.area_kind'
             AND NOT feature.has_active_feature_override(p_feature_id, 'area.area_kind')
            THEN p_values ->> 'area.area_kind'
            ELSE area.area_kind
        END,
            boundary_source = CASE
            WHEN p_values ? 'area.boundary_source'
             AND NOT feature.has_active_feature_override(p_feature_id, 'area.boundary_source')
            THEN p_values ->> 'area.boundary_source'
            ELSE area.boundary_source
        END,
            area_square_meters = CASE
            WHEN p_values ? 'area.area_square_meters'
             AND NOT feature.has_active_feature_override(p_feature_id, 'area.area_square_meters')
            THEN (p_values ->> 'area.area_square_meters')::numeric
            ELSE area.area_square_meters
        END,
            regulation_scope = CASE
            WHEN p_values ? 'area.regulation_scope'
             AND NOT feature.has_active_feature_override(p_feature_id, 'area.regulation_scope')
            THEN p_values ->> 'area.regulation_scope'
            ELSE area.regulation_scope
        END,
            administrative_office = CASE
            WHEN p_values ? 'area.administrative_office'
             AND NOT feature.has_active_feature_override(p_feature_id, 'area.administrative_office')
            THEN p_values ->> 'area.administrative_office'
            ELSE area.administrative_office
        END,
            description = CASE
            WHEN p_values ? 'area.description'
             AND NOT feature.has_active_feature_override(p_feature_id, 'area.description')
            THEN p_values ->> 'area.description'
            ELSE area.description
        END,
            payload = CASE
            WHEN p_values ? 'area.payload'
             AND NOT feature.has_active_feature_override(p_feature_id, 'area.payload')
            THEN p_values -> 'area.payload'
            ELSE area.payload
        END
      WHERE area.feature_id = p_feature_id;
    END IF;
END;
$$;

ALTER PROCEDURE feature.apply_provider_feature_field_patch(IN p_feature_id uuid, IN p_provider_dataset_id bigint, IN p_source_entity_key text, IN p_source_record_key text, IN p_expected_row_revision bigint, IN p_values jsonb, IN p_geometry_wkt jsonb, OUT o_feature_id uuid, OUT o_row_revision bigint, OUT o_applied_field_count integer) OWNER TO ktm_feature_state_procedure_owner;

REVOKE ALL ON PROCEDURE feature.apply_provider_feature_field_patch(IN p_feature_id uuid, IN p_provider_dataset_id bigint, IN p_source_entity_key text, IN p_source_record_key text, IN p_expected_row_revision bigint, IN p_values jsonb, IN p_geometry_wkt jsonb, OUT o_feature_id uuid, OUT o_row_revision bigint, OUT o_applied_field_count integer) FROM PUBLIC;
GRANT ALL ON PROCEDURE feature.apply_provider_feature_field_patch(IN p_feature_id uuid, IN p_provider_dataset_id bigint, IN p_source_entity_key text, IN p_source_record_key text, IN p_expected_row_revision bigint, IN p_values jsonb, IN p_geometry_wkt jsonb, OUT o_feature_id uuid, OUT o_row_revision bigint, OUT o_applied_field_count integer) TO ktm_feature_runtime;

SET ROLE ktm_feature_schema_owner;
