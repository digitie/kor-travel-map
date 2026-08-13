--
-- PostgreSQL database dump
--


SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: feature; Type: SCHEMA; Schema: -; Owner: ktm_feature_schema_owner
--

CREATE SCHEMA IF NOT EXISTS feature;


ALTER SCHEMA feature OWNER TO ktm_feature_schema_owner;

--
-- Name: ops; Type: SCHEMA; Schema: -; Owner: ktm_feature_schema_owner
--

CREATE SCHEMA IF NOT EXISTS ops;


ALTER SCHEMA ops OWNER TO ktm_feature_schema_owner;

--
-- Name: provider_sync; Type: SCHEMA; Schema: -; Owner: ktm_feature_schema_owner
--

CREATE SCHEMA IF NOT EXISTS provider_sync;


ALTER SCHEMA provider_sync OWNER TO ktm_feature_schema_owner;

--
-- Name: apply_provider_feature_field_patch(text, bigint, text, text, bigint, jsonb, jsonb); Type: PROCEDURE; Schema: feature; Owner: ktm_feature_state_procedure_owner
--

CREATE PROCEDURE feature.apply_provider_feature_field_patch(IN p_feature_id text, IN p_provider_dataset_id bigint, IN p_source_entity_key text, IN p_source_record_key text, IN p_expected_row_revision bigint, IN p_values jsonb, IN p_geometry_wkt jsonb, OUT o_feature_id text, OUT o_row_revision bigint, OUT o_applied_field_count integer)
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
            feature_id, field_path, feature_uuid, provider_dataset_id,
            source_entity_key, source_record_key, source_raw_payload_hash,
            value_json, base_revision, observed_at
        ) VALUES (
            p_feature_id, v_field_path, v_feature.feature_uuid, p_provider_dataset_id,
            p_source_entity_key, p_source_record_key, v_source_hash,
            coalesce(v_value, 'null'::jsonb), v_base_revision, clock_timestamp()
        ) ON CONFLICT (feature_id, field_path) DO UPDATE
        SET feature_uuid = EXCLUDED.feature_uuid,
            provider_dataset_id = EXCLUDED.provider_dataset_id,
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
            feature_id, field_path, feature_uuid, provider_dataset_id,
            source_entity_key, source_record_key, source_raw_payload_hash,
            value_json, value_geometry, base_revision, observed_at
        ) VALUES (
            p_feature_id, v_field_path, v_feature.feature_uuid, p_provider_dataset_id,
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
        SET feature_uuid = EXCLUDED.feature_uuid,
            provider_dataset_id = EXCLUDED.provider_dataset_id,
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
            THEN p_values ->> 'core.parent_feature_id'
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


ALTER PROCEDURE feature.apply_provider_feature_field_patch(IN p_feature_id text, IN p_provider_dataset_id bigint, IN p_source_entity_key text, IN p_source_record_key text, IN p_expected_row_revision bigint, IN p_values jsonb, IN p_geometry_wkt jsonb, OUT o_feature_id text, OUT o_row_revision bigint, OUT o_applied_field_count integer) OWNER TO ktm_feature_state_procedure_owner;

--
-- Name: author_feature_field_overrides(text, bigint, text, text, bigint, jsonb, jsonb); Type: PROCEDURE; Schema: feature; Owner: ktm_feature_state_procedure_owner
--

CREATE PROCEDURE feature.author_feature_field_overrides(IN p_feature_id text, IN p_expected_row_revision bigint, IN p_principal text, IN p_reason_code text, IN p_command_id bigint, IN p_values jsonb, IN p_geometry_wkt jsonb, OUT o_feature_id text, OUT o_row_revision bigint, OUT o_command_id bigint, OUT o_applied_field_count integer)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog'
    AS $$
DECLARE
    v_feature feature.features%ROWTYPE;
    v_registry ops.feature_override_field_paths%ROWTYPE;
    v_field_path text;
    v_value jsonb;
    v_geometry_wkt text;
    v_operation text;
BEGIN
    IF p_expected_row_revision IS NULL OR p_expected_row_revision < 1
       OR p_command_id IS NULL
       OR coalesce(btrim(p_feature_id), '') = ''
       OR coalesce(btrim(p_principal), '') = ''
       OR coalesce(btrim(p_reason_code), '') = ''
       OR jsonb_typeof(p_values) <> 'object'
       OR jsonb_typeof(p_geometry_wkt) <> 'object' THEN
        RAISE EXCEPTION 'field override author has invalid arguments'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_override_command';
    END IF;
    SELECT count(*)::integer INTO o_applied_field_count
    FROM (
        SELECT key FROM jsonb_each(p_values)
        UNION ALL
        SELECT key FROM jsonb_each(p_geometry_wkt)
    ) AS supplied_path;
    IF o_applied_field_count = 0 OR EXISTS (
        SELECT 1
        FROM jsonb_object_keys(p_values) AS scalar_path(field_path)
        JOIN jsonb_object_keys(p_geometry_wkt) AS geometry_path(field_path)
          ON geometry_path.field_path = scalar_path.field_path
    ) THEN
        RAISE EXCEPTION 'field override author needs distinct scalar or geometry paths'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_override_command';
    END IF;

    SELECT command.operation INTO v_operation
    FROM ops.domain_commands AS command
    WHERE command.command_id = p_command_id
      AND command.actor = btrim(p_principal)
      AND NOT EXISTS (
          SELECT 1 FROM ops.domain_command_results AS result
          WHERE result.command_id = command.command_id
      )
    FOR SHARE;
    IF NOT FOUND OR v_operation NOT IN (
        'admin.feature.override.author', 'admin.feature.create', 'admin.feature.patch'
    ) THEN
        RAISE EXCEPTION 'field override author requires an open matching domain command'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_override_command';
    END IF;

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

    FOR v_field_path, v_value IN SELECT key, value FROM jsonb_each(p_values) LOOP
        SELECT * INTO v_registry FROM ops.feature_override_field_paths
        WHERE field_path = v_field_path;
        IF NOT FOUND OR NOT v_registry.operator_writable
           OR v_registry.value_kind = 'geometry'
           OR (v_registry.feature_kind <> '*' AND v_registry.feature_kind <> v_feature.kind) THEN
            RAISE EXCEPTION 'operator cannot override field path %', v_field_path
                USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_override_field_path';
        END IF;
        UPDATE ops.feature_overrides
        SET status = 'revoked', revoked_at = clock_timestamp(),
            revoked_by = btrim(p_principal), revoked_reason = btrim(p_reason_code)
        WHERE feature_id = p_feature_id AND field_path = v_field_path AND status = 'active';
        INSERT INTO ops.feature_overrides (
            feature_id, source_record_key, source_provider_dataset_id, source_entity_key,
            source_raw_payload_hash, field_path, source_value, override_value,
            prevent_provider_reactivation, status, reason, command_id,
            base_revision, created_by, created_at
        )
        SELECT p_feature_id, base.source_record_key, base.provider_dataset_id,
               base.source_entity_key, base.source_raw_payload_hash, v_field_path,
               base.value_json, coalesce(v_value, 'null'::jsonb), false, 'active', btrim(p_reason_code),
               p_command_id, COALESCE(base.base_revision, v_feature.row_revision),
               btrim(p_principal), clock_timestamp()
        FROM (SELECT 1) AS singleton
        LEFT JOIN feature.feature_base_field_values AS base
          ON base.feature_id = p_feature_id AND base.field_path = v_field_path;
    END LOOP;
    FOR v_field_path, v_value IN SELECT key, value FROM jsonb_each(p_geometry_wkt) LOOP
        SELECT * INTO v_registry FROM ops.feature_override_field_paths
        WHERE field_path = v_field_path;
        IF NOT FOUND OR NOT v_registry.operator_writable
           OR v_registry.value_kind <> 'geometry'
           OR (v_registry.feature_kind <> '*' AND v_registry.feature_kind <> v_feature.kind)
           OR (v_value = 'null'::jsonb AND NOT v_registry.allows_null)
           OR (v_value <> 'null'::jsonb AND (
                jsonb_typeof(v_value) <> 'string' OR coalesce(btrim(v_value #>> '{}'), '') = ''
           )) THEN
            RAISE EXCEPTION 'operator cannot override geometry field path %', v_field_path
                USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_override_field_path';
        END IF;
        UPDATE ops.feature_overrides
        SET status = 'revoked', revoked_at = clock_timestamp(),
            revoked_by = btrim(p_principal), revoked_reason = btrim(p_reason_code)
        WHERE feature_id = p_feature_id AND field_path = v_field_path AND status = 'active';
        INSERT INTO ops.feature_overrides (
            feature_id, source_record_key, source_provider_dataset_id, source_entity_key,
            source_raw_payload_hash, field_path, source_value, override_value, value_geometry,
            prevent_provider_reactivation, status, reason, command_id,
            base_revision, created_by, created_at
        )
        SELECT p_feature_id, base.source_record_key, base.provider_dataset_id,
               base.source_entity_key, base.source_raw_payload_hash, v_field_path,
               NULL, CASE WHEN v_value = 'null'::jsonb THEN 'null'::jsonb ELSE NULL END,
               CASE WHEN v_value = 'null'::jsonb THEN NULL
                    ELSE CASE v_registry.geometry_type
                      WHEN 'MULTILINESTRING' THEN x_extension.st_multi(x_extension.st_geomfromtext(v_value #>> '{}', 4326))
                      WHEN 'MULTIPOLYGON' THEN x_extension.st_multi(x_extension.st_geomfromtext(v_value #>> '{}', 4326))
                      ELSE x_extension.st_geomfromtext(v_value #>> '{}', 4326)
                 END END,
               false, 'active', btrim(p_reason_code), p_command_id,
               COALESCE(base.base_revision, v_feature.row_revision), btrim(p_principal),
               clock_timestamp()
        FROM (SELECT 1) AS singleton
        LEFT JOIN feature.feature_base_field_values AS base
          ON base.feature_id = p_feature_id AND base.field_path = v_field_path;
    END LOOP;

    UPDATE feature.features AS core
    SET name = CASE
            WHEN p_values ? 'core.name'
            THEN p_values ->> 'core.name'
            ELSE core.name
        END,
        category = CASE
            WHEN p_values ? 'core.category'
            THEN p_values ->> 'core.category'
            ELSE core.category
        END,
        coord = CASE
            WHEN p_geometry_wkt ? 'core.coord'
            THEN CASE WHEN p_geometry_wkt ->> 'core.coord' IS NULL THEN NULL ELSE x_extension.st_geomfromtext(p_geometry_wkt ->> 'core.coord', 4326) END
            ELSE core.coord
        END,
        coord_precision_digits = CASE
            WHEN p_values ? 'core.coord_precision_digits'
            THEN (p_values ->> 'core.coord_precision_digits')::smallint
            ELSE core.coord_precision_digits
        END,
        address = CASE
            WHEN p_values ? 'core.address'
            THEN p_values -> 'core.address'
            ELSE core.address
        END,
        legal_dong_code = CASE
            WHEN p_values ? 'core.legal_dong_code'
            THEN p_values ->> 'core.legal_dong_code'
            ELSE core.legal_dong_code
        END,
        road_name_code = CASE
            WHEN p_values ? 'core.road_name_code'
            THEN p_values ->> 'core.road_name_code'
            ELSE core.road_name_code
        END,
        road_address_management_no = CASE
            WHEN p_values ? 'core.road_address_management_no'
            THEN p_values ->> 'core.road_address_management_no'
            ELSE core.road_address_management_no
        END,
        admin_dong_code = CASE
            WHEN p_values ? 'core.admin_dong_code'
            THEN p_values ->> 'core.admin_dong_code'
            ELSE core.admin_dong_code
        END,
        sido_code = CASE
            WHEN p_values ? 'core.sido_code'
            THEN p_values ->> 'core.sido_code'
            ELSE core.sido_code
        END,
        sigungu_code = CASE
            WHEN p_values ? 'core.sigungu_code'
            THEN p_values ->> 'core.sigungu_code'
            ELSE core.sigungu_code
        END,
        urls = CASE
            WHEN p_values ? 'core.urls'
            THEN p_values -> 'core.urls'
            ELSE core.urls
        END,
        marker_icon = CASE
            WHEN p_values ? 'core.marker_icon'
            THEN p_values ->> 'core.marker_icon'
            ELSE core.marker_icon
        END,
        marker_color = CASE
            WHEN p_values ? 'core.marker_color'
            THEN p_values ->> 'core.marker_color'
            ELSE core.marker_color
        END,
        parent_feature_id = CASE
            WHEN p_values ? 'core.parent_feature_id'
            THEN p_values ->> 'core.parent_feature_id'
            ELSE core.parent_feature_id
        END,
        sibling_group_id = CASE
            WHEN p_values ? 'core.sibling_group_id'
            THEN NULLIF(p_values ->> 'core.sibling_group_id', '')::uuid
            ELSE core.sibling_group_id
        END,
        raw_refs = CASE
            WHEN p_values ? 'core.raw_refs'
            THEN p_values -> 'core.raw_refs'
            ELSE core.raw_refs
        END,
        updated_at = clock_timestamp()
    WHERE core.feature_id = p_feature_id
    RETURNING core.feature_id, core.row_revision INTO o_feature_id, o_row_revision;
    IF v_feature.kind = 'place' AND EXISTS (SELECT 1 FROM jsonb_object_keys(p_values) AS supplied_path(field_path) WHERE supplied_path.field_path LIKE 'place.%') THEN
        PERFORM 1 FROM feature.feature_places WHERE feature_id = p_feature_id FOR UPDATE;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'place subtype is missing'
                USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_override_subtype';
        END IF;
        UPDATE feature.feature_places AS place
        SET place_kind = CASE
            WHEN p_values ? 'place.place_kind'
            THEN p_values ->> 'place.place_kind'
            ELSE place.place_kind
        END,
            phones = CASE
            WHEN p_values ? 'place.phones'
            THEN ARRAY(SELECT jsonb_array_elements_text(p_values -> 'place.phones'))
            ELSE place.phones
        END,
            biz_number = CASE
            WHEN p_values ? 'place.biz_number'
            THEN p_values ->> 'place.biz_number'
            ELSE place.biz_number
        END,
            license_date = CASE
            WHEN p_values ? 'place.license_date'
            THEN (p_values ->> 'place.license_date')::date
            ELSE place.license_date
        END,
            business_hours = CASE
            WHEN p_values ? 'place.business_hours'
            THEN p_values -> 'place.business_hours'
            ELSE place.business_hours
        END,
            facility_info = CASE
            WHEN p_values ? 'place.facility_info'
            THEN p_values -> 'place.facility_info'
            ELSE place.facility_info
        END,
            reviews_link = CASE
            WHEN p_values ? 'place.reviews_link'
            THEN p_values -> 'place.reviews_link'
            ELSE place.reviews_link
        END,
            payload = CASE
            WHEN p_values ? 'place.payload'
            THEN p_values -> 'place.payload'
            ELSE place.payload
        END
      WHERE place.feature_id = p_feature_id;
    ELSIF v_feature.kind = 'event' AND EXISTS (SELECT 1 FROM jsonb_object_keys(p_values) AS supplied_path(field_path) WHERE supplied_path.field_path LIKE 'event.%') THEN
        PERFORM 1 FROM feature.feature_events WHERE feature_id = p_feature_id FOR UPDATE;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'event subtype is missing'
                USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_override_subtype';
        END IF;
        UPDATE feature.feature_events AS event
        SET event_kind = CASE
            WHEN p_values ? 'event.event_kind'
            THEN p_values ->> 'event.event_kind'
            ELSE event.event_kind
        END,
            starts_on = CASE
            WHEN p_values ? 'event.starts_on'
            THEN (p_values ->> 'event.starts_on')::date
            ELSE event.starts_on
        END,
            ends_on = CASE
            WHEN p_values ? 'event.ends_on'
            THEN (p_values ->> 'event.ends_on')::date
            ELSE event.ends_on
        END,
            timezone = CASE
            WHEN p_values ? 'event.timezone'
            THEN p_values ->> 'event.timezone'
            ELSE event.timezone
        END,
            opening_hours = CASE
            WHEN p_values ? 'event.opening_hours'
            THEN p_values -> 'event.opening_hours'
            ELSE event.opening_hours
        END,
            venue_name = CASE
            WHEN p_values ? 'event.venue_name'
            THEN p_values ->> 'event.venue_name'
            ELSE event.venue_name
        END,
            tel = CASE
            WHEN p_values ? 'event.tel'
            THEN p_values ->> 'event.tel'
            ELSE event.tel
        END,
            content_id = CASE
            WHEN p_values ? 'event.content_id'
            THEN p_values ->> 'event.content_id'
            ELSE event.content_id
        END,
            content_type_id = CASE
            WHEN p_values ? 'event.content_type_id'
            THEN p_values ->> 'event.content_type_id'
            ELSE event.content_type_id
        END,
            area_code = CASE
            WHEN p_values ? 'event.area_code'
            THEN p_values ->> 'event.area_code'
            ELSE event.area_code
        END,
            sigungu_code = CASE
            WHEN p_values ? 'event.sigungu_code'
            THEN p_values ->> 'event.sigungu_code'
            ELSE event.sigungu_code
        END,
            payload = CASE
            WHEN p_values ? 'event.payload'
            THEN p_values -> 'event.payload'
            ELSE event.payload
        END
      WHERE event.feature_id = p_feature_id;
    ELSIF v_feature.kind = 'notice' AND EXISTS (SELECT 1 FROM jsonb_object_keys(p_values) AS supplied_path(field_path) WHERE supplied_path.field_path LIKE 'notice.%') THEN
        PERFORM 1 FROM feature.feature_notices WHERE feature_id = p_feature_id FOR UPDATE;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'notice subtype is missing'
                USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_override_subtype';
        END IF;
        UPDATE feature.feature_notices AS notice
        SET notice_type = CASE
            WHEN p_values ? 'notice.notice_type'
            THEN p_values ->> 'notice.notice_type'
            ELSE notice.notice_type
        END,
            severity = CASE
            WHEN p_values ? 'notice.severity'
            THEN (p_values ->> 'notice.severity')::smallint
            ELSE notice.severity
        END,
            valid_start_time = CASE
            WHEN p_values ? 'notice.valid_start_time'
            THEN (p_values ->> 'notice.valid_start_time')::timestamptz
            ELSE notice.valid_start_time
        END,
            valid_end_time = CASE
            WHEN p_values ? 'notice.valid_end_time'
            THEN (p_values ->> 'notice.valid_end_time')::timestamptz
            ELSE notice.valid_end_time
        END,
            source_agency = CASE
            WHEN p_values ? 'notice.source_agency'
            THEN p_values ->> 'notice.source_agency'
            ELSE notice.source_agency
        END,
            officer_name = CASE
            WHEN p_values ? 'notice.officer_name'
            THEN p_values ->> 'notice.officer_name'
            ELSE notice.officer_name
        END,
            payload = CASE
            WHEN p_values ? 'notice.payload'
            THEN p_values -> 'notice.payload'
            ELSE notice.payload
        END
      WHERE notice.feature_id = p_feature_id;
    ELSIF v_feature.kind = 'route' AND (EXISTS (SELECT 1 FROM jsonb_object_keys(p_values) AS supplied_path(field_path) WHERE supplied_path.field_path LIKE 'route.%') OR EXISTS (SELECT 1 FROM jsonb_object_keys(p_geometry_wkt) AS supplied_path(field_path) WHERE supplied_path.field_path LIKE 'route.%')) THEN
        PERFORM 1 FROM feature.feature_routes WHERE feature_id = p_feature_id FOR UPDATE;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'route subtype is missing'
                USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_override_subtype';
        END IF;
        UPDATE feature.feature_routes AS route
        SET geom = CASE
            WHEN p_geometry_wkt ? 'route.geom'
            THEN x_extension.st_multi(x_extension.st_geomfromtext(p_geometry_wkt ->> 'route.geom', 4326))
            ELSE route.geom
        END,
            route_type = CASE
            WHEN p_values ? 'route.route_type'
            THEN p_values ->> 'route.route_type'
            ELSE route.route_type
        END,
            geometry_source = CASE
            WHEN p_values ? 'route.geometry_source'
            THEN p_values ->> 'route.geometry_source'
            ELSE route.geometry_source
        END,
            geometry_status = CASE
            WHEN p_values ? 'route.geometry_status'
            THEN p_values ->> 'route.geometry_status'
            ELSE route.geometry_status
        END,
            total_distance_meters = CASE
            WHEN p_values ? 'route.total_distance_meters'
            THEN (p_values ->> 'route.total_distance_meters')::numeric
            ELSE route.total_distance_meters
        END,
            expected_duration_minutes = CASE
            WHEN p_values ? 'route.expected_duration_minutes'
            THEN (p_values ->> 'route.expected_duration_minutes')::integer
            ELSE route.expected_duration_minutes
        END,
            difficulty = CASE
            WHEN p_values ? 'route.difficulty'
            THEN p_values ->> 'route.difficulty'
            ELSE route.difficulty
        END,
            begin_name = CASE
            WHEN p_values ? 'route.begin_name'
            THEN p_values ->> 'route.begin_name'
            ELSE route.begin_name
        END,
            begin_address = CASE
            WHEN p_values ? 'route.begin_address'
            THEN p_values ->> 'route.begin_address'
            ELSE route.begin_address
        END,
            end_name = CASE
            WHEN p_values ? 'route.end_name'
            THEN p_values ->> 'route.end_name'
            ELSE route.end_name
        END,
            end_address = CASE
            WHEN p_values ? 'route.end_address'
            THEN p_values ->> 'route.end_address'
            ELSE route.end_address
        END,
            payload = CASE
            WHEN p_values ? 'route.payload'
            THEN p_values -> 'route.payload'
            ELSE route.payload
        END
      WHERE route.feature_id = p_feature_id;
    ELSIF v_feature.kind = 'area' AND (EXISTS (SELECT 1 FROM jsonb_object_keys(p_values) AS supplied_path(field_path) WHERE supplied_path.field_path LIKE 'area.%') OR EXISTS (SELECT 1 FROM jsonb_object_keys(p_geometry_wkt) AS supplied_path(field_path) WHERE supplied_path.field_path LIKE 'area.%')) THEN
        PERFORM 1 FROM feature.feature_areas WHERE feature_id = p_feature_id FOR UPDATE;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'area subtype is missing'
                USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_override_subtype';
        END IF;
        UPDATE feature.feature_areas AS area
        SET geom = CASE
            WHEN p_geometry_wkt ? 'area.geom'
            THEN x_extension.st_multi(x_extension.st_geomfromtext(p_geometry_wkt ->> 'area.geom', 4326))
            ELSE area.geom
        END,
            area_kind = CASE
            WHEN p_values ? 'area.area_kind'
            THEN p_values ->> 'area.area_kind'
            ELSE area.area_kind
        END,
            boundary_source = CASE
            WHEN p_values ? 'area.boundary_source'
            THEN p_values ->> 'area.boundary_source'
            ELSE area.boundary_source
        END,
            area_square_meters = CASE
            WHEN p_values ? 'area.area_square_meters'
            THEN (p_values ->> 'area.area_square_meters')::numeric
            ELSE area.area_square_meters
        END,
            regulation_scope = CASE
            WHEN p_values ? 'area.regulation_scope'
            THEN p_values ->> 'area.regulation_scope'
            ELSE area.regulation_scope
        END,
            administrative_office = CASE
            WHEN p_values ? 'area.administrative_office'
            THEN p_values ->> 'area.administrative_office'
            ELSE area.administrative_office
        END,
            description = CASE
            WHEN p_values ? 'area.description'
            THEN p_values ->> 'area.description'
            ELSE area.description
        END,
            payload = CASE
            WHEN p_values ? 'area.payload'
            THEN p_values -> 'area.payload'
            ELSE area.payload
        END
      WHERE area.feature_id = p_feature_id;
    END IF;
    o_command_id := p_command_id;
END;
$$;


ALTER PROCEDURE feature.author_feature_field_overrides(IN p_feature_id text, IN p_expected_row_revision bigint, IN p_principal text, IN p_reason_code text, IN p_command_id bigint, IN p_values jsonb, IN p_geometry_wkt jsonb, OUT o_feature_id text, OUT o_row_revision bigint, OUT o_command_id bigint, OUT o_applied_field_count integer) OWNER TO ktm_feature_state_procedure_owner;

--
-- Name: author_lifecycle_override(text, text, text, boolean, text, text, bigint); Type: PROCEDURE; Schema: feature; Owner: ktm_feature_state_procedure_owner
--

CREATE PROCEDURE feature.author_lifecycle_override(IN p_feature_id text, IN p_source_lifecycle_state text, IN p_override_lifecycle_state text, IN p_prevent_provider_reactivation boolean, IN p_reason text, IN p_principal text, IN p_expected_row_revision bigint, OUT o_row_revision bigint)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog'
    AS $$
DECLARE
    v_current feature.features%ROWTYPE;
BEGIN
    IF p_source_lifecycle_state NOT IN ('active', 'retired')
       OR p_override_lifecycle_state NOT IN ('active', 'retired')
       OR p_prevent_provider_reactivation IS NULL
       OR p_expected_row_revision IS NULL OR p_expected_row_revision < 1
       OR coalesce(btrim(p_reason), '') = ''
       OR coalesce(btrim(p_principal), '') = '' THEN
        RAISE EXCEPTION 'lifecycle override has invalid typed arguments'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_lifecycle_override_command';
    END IF;

    SELECT * INTO v_current
      FROM feature.features
     WHERE feature_id = p_feature_id
     FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'feature % does not exist', p_feature_id USING ERRCODE = 'P0002';
    END IF;
    IF v_current.row_revision <> p_expected_row_revision THEN
        RAISE EXCEPTION 'feature % revision changed', p_feature_id USING ERRCODE = '40001';
    END IF;
    -- A lifecycle override can only describe the tuple that is currently
    -- authoritative.  In particular a caller cannot pre-authorize a future
    -- provider reactivation by choosing an arbitrary override value.
    IF v_current.lifecycle_state <> p_override_lifecycle_state THEN
        RAISE EXCEPTION 'lifecycle override value must equal the current lifecycle state'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_lifecycle_override_command';
    END IF;

    -- ``source_value`` is evidence, never caller-authored history.  It is
    -- either the currently observed lifecycle (for an existing retired
    -- feature) or the ``from`` side of the exact audited state transition
    -- which produced ``p_expected_row_revision``.  The latter is what allows
    -- an active -> retired lifecycle command to retain its authoritative
    -- source state without opening a generic override write boundary.
    IF p_source_lifecycle_state <> v_current.lifecycle_state
       AND NOT EXISTS (
            SELECT 1
            FROM feature.feature_state_transitions AS transition
            WHERE transition.feature_id = p_feature_id
              AND transition.row_revision = p_expected_row_revision
              AND transition.from_lifecycle_state = p_source_lifecycle_state
              AND transition.to_lifecycle_state = v_current.lifecycle_state
       ) THEN
        RAISE EXCEPTION 'lifecycle override source must match current state or exact audited transition'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_lifecycle_override_command';
    END IF;

    INSERT INTO ops.feature_overrides (
        feature_id, source_record_key, field_path,
        source_value, override_value, prevent_provider_reactivation,
        status, reason, created_by
    ) VALUES (
        p_feature_id, NULL, 'lifecycle_state',
        to_jsonb(p_source_lifecycle_state), to_jsonb(p_override_lifecycle_state),
        p_prevent_provider_reactivation,
        'active', btrim(p_reason), btrim(p_principal)
    ) ON CONFLICT (feature_id, field_path) WHERE status = 'active'
    DO UPDATE SET
        source_value = EXCLUDED.source_value,
        override_value = EXCLUDED.override_value,
        prevent_provider_reactivation = EXCLUDED.prevent_provider_reactivation,
        reason = EXCLUDED.reason,
        created_by = EXCLUDED.created_by,
        created_at = clock_timestamp();

    o_row_revision := v_current.row_revision;
END;
$$;


ALTER PROCEDURE feature.author_lifecycle_override(IN p_feature_id text, IN p_source_lifecycle_state text, IN p_override_lifecycle_state text, IN p_prevent_provider_reactivation boolean, IN p_reason text, IN p_principal text, IN p_expected_row_revision bigint, OUT o_row_revision bigint) OWNER TO ktm_feature_state_procedure_owner;

--
-- Name: create_feature_with_initial_state(jsonb, text, text, text, jsonb); Type: PROCEDURE; Schema: feature; Owner: ktm_feature_state_procedure_owner
--

CREATE PROCEDURE feature.create_feature_with_initial_state(IN p_feature jsonb, IN p_lifecycle_state text, IN p_publication_state text, IN p_quality_state text, IN p_context jsonb, OUT o_feature_id text, OUT o_feature_uuid uuid, OUT o_row_revision bigint, OUT o_inserted boolean)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog'
    AS $$
DECLARE
    v_feature_id text;
    v_feature_uuid uuid;
    v_kind text;
    v_name text;
    v_category text;
    v_coord feature.features.coord%TYPE;
BEGIN
    IF jsonb_typeof(p_feature) IS DISTINCT FROM 'object' THEN
        RAISE EXCEPTION 'feature payload must be an object'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_create_payload';
    END IF;
    IF EXISTS (
        SELECT 1 FROM jsonb_object_keys(p_feature) AS key_name(key_name)
        WHERE key_name NOT IN (
            'feature_id', 'feature_uuid', 'kind', 'name', 'category',
            'lon', 'lat', 'coord_precision_digits', 'address',
            'legal_dong_code', 'road_name_code', 'road_address_management_no',
            'admin_dong_code', 'sido_code', 'sigungu_code', 'urls',
            'marker_icon', 'marker_color', 'parent_feature_id', 'sibling_group_id',
            'raw_refs'
        )
    ) THEN
        RAISE EXCEPTION 'feature create payload contains an unknown field'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_create_payload';
    END IF;
    IF (p_feature ? 'address' AND jsonb_typeof(p_feature -> 'address') IS DISTINCT FROM 'object')
       OR (p_feature ? 'urls' AND jsonb_typeof(p_feature -> 'urls') IS DISTINCT FROM 'object')
       OR (p_feature ? 'raw_refs' AND jsonb_typeof(p_feature -> 'raw_refs') IS DISTINCT FROM 'array') THEN
        RAISE EXCEPTION 'feature create payload has an invalid JSON field shape'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_create_payload';
    END IF;
    v_feature_id := nullif(btrim(p_feature ->> 'feature_id'), '');
    v_kind := nullif(btrim(p_feature ->> 'kind'), '');
    v_name := nullif(btrim(p_feature ->> 'name'), '');
    v_category := nullif(btrim(p_feature ->> 'category'), '');
    IF v_feature_id IS NULL OR v_kind IS NULL OR v_name IS NULL OR v_category IS NULL THEN
        RAISE EXCEPTION 'feature create payload lacks required core fields'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_create_payload';
    END IF;
    IF p_feature ? 'feature_uuid' THEN
        v_feature_uuid := nullif(btrim(p_feature ->> 'feature_uuid'), '')::uuid;
    END IF;
    IF (p_feature ? 'lon') <> (p_feature ? 'lat') THEN
        RAISE EXCEPTION 'feature coordinate requires both lon and lat'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_create_payload';
    END IF;
    IF p_feature ? 'lon' THEN
        v_coord := x_extension.st_setsrid(
            x_extension.st_makepoint(
                (p_feature ->> 'lon')::double precision,
                (p_feature ->> 'lat')::double precision
            ),
            4326
        );
    END IF;

    PERFORM feature.prepare_feature_state_context(p_context, 'create');
    -- Provider source writers advance an entity head before they create/update
    -- the Feature in the same transaction.  Take the identical locked proof
    -- before this INSERT, so the initial audit can never claim a record that
    -- stopped being current before this transaction commits.
    IF p_context ->> 'transition_kind' = 'provider_sync' THEN
        PERFORM feature.lock_current_provider_source_evidence(
            (p_context ->> 'provider_dataset_id')::bigint,
            p_context ->> 'source_entity_key',
            p_context ->> 'source_record_key'
        );
    END IF;
    INSERT INTO feature.features (
        feature_id, feature_uuid, kind, name, category,
        coord, coord_precision_digits,
        address, legal_dong_code, road_name_code, road_address_management_no,
        admin_dong_code, sido_code, sigungu_code,
        urls, marker_icon, marker_color, parent_feature_id, sibling_group_id,
        raw_refs, lifecycle_state, publication_state, quality_state,
        created_at, updated_at
    ) VALUES (
        v_feature_id, v_feature_uuid, v_kind, v_name,
        v_category, v_coord, (p_feature ->> 'coord_precision_digits')::smallint,
        coalesce(p_feature -> 'address', '{}'::jsonb), p_feature ->> 'legal_dong_code',
        p_feature ->> 'road_name_code', p_feature ->> 'road_address_management_no',
        p_feature ->> 'admin_dong_code', p_feature ->> 'sido_code', p_feature ->> 'sigungu_code',
        coalesce(p_feature -> 'urls', '{}'::jsonb), p_feature ->> 'marker_icon', p_feature ->> 'marker_color',
        p_feature ->> 'parent_feature_id', nullif(p_feature ->> 'sibling_group_id', '')::uuid,
        coalesce(p_feature -> 'raw_refs', '[]'::jsonb), p_lifecycle_state,
        p_publication_state, p_quality_state,
        clock_timestamp(), clock_timestamp()
    ) ON CONFLICT (feature_id) DO NOTHING
    RETURNING feature_id, feature_uuid, row_revision
         INTO o_feature_id, o_feature_uuid, o_row_revision;

    o_inserted := FOUND;
    IF NOT o_inserted THEN
        SELECT feature_id, feature_uuid, row_revision
          INTO o_feature_id, o_feature_uuid, o_row_revision
          FROM feature.features
         WHERE feature_id = v_feature_id;
    END IF;
END;
$$;


ALTER PROCEDURE feature.create_feature_with_initial_state(IN p_feature jsonb, IN p_lifecycle_state text, IN p_publication_state text, IN p_quality_state text, IN p_context jsonb, OUT o_feature_id text, OUT o_feature_uuid uuid, OUT o_row_revision bigint, OUT o_inserted boolean) OWNER TO ktm_feature_state_procedure_owner;

--
-- Name: derive_subtype_public_ready(); Type: FUNCTION; Schema: feature; Owner: ktm_feature_state_procedure_owner
--

CREATE FUNCTION feature.derive_subtype_public_ready() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog'
    AS $$
DECLARE
    v_lifecycle_state text;
    v_publication_state text;
    v_quality_state text;
BEGIN
    IF TG_OP = 'UPDATE' THEN
        -- Reattachment would make one UPDATE hold a subtype tuple before it
        -- waits on a different parent.  No normal writer supports it, so make
        -- the 1:1 subtype identity immutable instead of inventing a broad
        -- relation lock or a retry protocol.
        IF NEW.feature_id IS DISTINCT FROM OLD.feature_id
           OR NEW.feature_uuid IS DISTINCT FROM OLD.feature_uuid
           OR NEW.kind IS DISTINCT FROM OLD.kind THEN
            RAISE EXCEPTION 'route/area subtype identity is immutable'
                USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_subtype_identity_immutable';
        END IF;

        -- Payload/geometry updates need no parent read: a core axis transition
        -- is the sole writer that changes an existing cache row.  This removes
        -- the former subtype tuple → parent tuple edge.  A direct privileged
        -- public_ready attempt is still overwritten below when it differs.
        IF NEW.public_ready IS NOT DISTINCT FROM OLD.public_ready THEN
            RETURN NEW;
        END IF;
    END IF;

    -- INSERT must serialize with a concurrent parent state transition so a
    -- newly attached route/area gets the current tuple.  An existing subtype
    -- update reaches here only for a supplied cache mutation; its lock-free
    -- parent read recomputes the DB-owned value, while core sync sees its own
    -- updated parent row in the same transaction.
    IF TG_OP = 'INSERT' THEN
        SELECT lifecycle_state, publication_state, quality_state
          INTO v_lifecycle_state, v_publication_state, v_quality_state
          FROM feature.features
         WHERE feature_id = NEW.feature_id
         FOR UPDATE;
    ELSE
        SELECT lifecycle_state, publication_state, quality_state
          INTO v_lifecycle_state, v_publication_state, v_quality_state
          FROM feature.features
         WHERE feature_id = NEW.feature_id;
    END IF;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'route/area public projection requires parent feature %', NEW.feature_id
            USING ERRCODE = '23503', CONSTRAINT = 'fk_feature_subtype_public_ready_parent';
    END IF;

    -- Never accept a caller supplied cache value, including a direct UPDATE by
    -- a privileged migration session.  Core state remains the sole source.
    NEW.public_ready := v_lifecycle_state = 'active'
        AND v_publication_state = 'published'
        AND v_quality_state = 'valid';
    RETURN NEW;
END;
$$;


ALTER FUNCTION feature.derive_subtype_public_ready() OWNER TO ktm_feature_state_procedure_owner;

--
-- Name: ensure_features_legacy_alias(); Type: FUNCTION; Schema: feature; Owner: ktm_feature_schema_owner
--

CREATE FUNCTION feature.ensure_features_legacy_alias() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog'
    AS $$
BEGIN
    INSERT INTO feature.feature_aliases (alias, feature_id, feature_uuid, alias_kind)
    VALUES (NEW.feature_id, NEW.feature_id, NEW.feature_uuid, 'legacy_feature_id')
    ON CONFLICT (alias) DO NOTHING;
    RETURN NULL;
END;
$$;


ALTER FUNCTION feature.ensure_features_legacy_alias() OWNER TO ktm_feature_schema_owner;

--
-- Name: feature_uuid_from_legacy(text); Type: FUNCTION; Schema: feature; Owner: ktm_feature_schema_owner
--

CREATE FUNCTION feature.feature_uuid_from_legacy(legacy_feature_id text) RETURNS uuid
    LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE
    SET search_path TO 'pg_catalog'
    AS $$
SELECT encode(
           set_byte(
               set_byte(
                   sha.digest16,
                   6,
                   (get_byte(sha.digest16, 6) & 15) | 80
               ),
               8,
               (get_byte(sha.digest16, 8) & 63) | 128
           ),
           'hex'
       )::uuid
FROM (
    SELECT substring(
               x_extension.digest(
                   decode('75d60e1327795b06a9206b1b892a7c84', 'hex')
                       || convert_to(legacy_feature_id, 'UTF8'),
                   'sha1'
               )
               FROM 1 FOR 16
           ) AS digest16
) AS sha
$$;


ALTER FUNCTION feature.feature_uuid_from_legacy(legacy_feature_id text) OWNER TO ktm_feature_schema_owner;

--
-- Name: fence_feature_aliases_write(); Type: FUNCTION; Schema: feature; Owner: ktm_feature_schema_owner
--

CREATE FUNCTION feature.fence_feature_aliases_write() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog'
    AS $$
BEGIN
    IF TG_OP = 'TRUNCATE' THEN
        RAISE EXCEPTION
            'T-VN-32C legacy write fence: feature_aliases TRUNCATE 금지 — '
            'alias map은 T-VN-39 removal manifest 전까지 유지한다 (ADR-068).';
    END IF;
    IF TG_OP = 'UPDATE' THEN
        RAISE EXCEPTION
            'T-VN-32C legacy write fence: feature_aliases 행은 불변입니다 '
            '(alias-map 이관·checksum 원본, ADR-068).';
    END IF;
    -- DELETE: 참조 feature가 이미 사라진 경우만(FK CASCADE 경유) 허용한다.
    IF EXISTS (
        SELECT 1 FROM feature.features WHERE feature_id = OLD.feature_id
    ) THEN
        RAISE EXCEPTION
            'T-VN-32C legacy write fence: alias 직접 DELETE 금지 — legacy '
            'alias는 T-VN-39 removal manifest 전까지 유지한다 (ADR-068).';
    END IF;
    RETURN OLD;
END;
$$;


ALTER FUNCTION feature.fence_feature_aliases_write() OWNER TO ktm_feature_schema_owner;

--
-- Name: fence_features_identity_update(); Type: FUNCTION; Schema: feature; Owner: ktm_feature_schema_owner
--

CREATE FUNCTION feature.fence_features_identity_update() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog'
    AS $$
BEGIN
    IF NEW.feature_id IS DISTINCT FROM OLD.feature_id
       OR NEW.feature_uuid IS DISTINCT FROM OLD.feature_uuid THEN
        RAISE EXCEPTION
            'T-VN-32C legacy write fence: feature identity(feature_id/'
            'feature_uuid)는 불변입니다 — 재키잉은 soft-delete + 신규 행으로 '
            '표현한다 (ADR-068).';
    END IF;
    RETURN NEW;
END;
$$;


ALTER FUNCTION feature.fence_features_identity_update() OWNER TO ktm_feature_schema_owner;

--
-- Name: fill_features_feature_uuid(); Type: FUNCTION; Schema: feature; Owner: ktm_feature_schema_owner
--

CREATE FUNCTION feature.fill_features_feature_uuid() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog'
    AS $$
BEGIN
    IF NEW.feature_uuid IS NULL THEN
        NEW.feature_uuid := feature.uuid_generate_v7();
    END IF;
    RETURN NEW;
END;
$$;


ALTER FUNCTION feature.fill_features_feature_uuid() OWNER TO ktm_feature_schema_owner;

--
-- Name: force_features_row_revision(); Type: FUNCTION; Schema: feature; Owner: ktm_feature_schema_owner
--

CREATE FUNCTION feature.force_features_row_revision() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog'
    AS $$
        BEGIN
            NEW.row_revision := OLD.row_revision + 1;
            RETURN NEW;
        END;
        $$;


ALTER FUNCTION feature.force_features_row_revision() OWNER TO ktm_feature_schema_owner;

--
-- Name: has_active_feature_override(text, text); Type: FUNCTION; Schema: feature; Owner: ktm_feature_state_procedure_owner
--

CREATE FUNCTION feature.has_active_feature_override(p_feature_id text, p_field_path text) RETURNS boolean
    LANGUAGE sql SECURITY DEFINER
    SET search_path TO 'pg_catalog'
    AS $$
    SELECT EXISTS (
        SELECT 1
        FROM ops.feature_overrides AS override
        WHERE override.feature_id = p_feature_id
          AND override.field_path = p_field_path
          AND override.status = 'active'
    );
$$;


ALTER FUNCTION feature.has_active_feature_override(p_feature_id text, p_field_path text) OWNER TO ktm_feature_state_procedure_owner;

--
-- Name: issue_curation_source_rule_decision(); Type: FUNCTION; Schema: feature; Owner: ktm_feature_schema_owner
--

CREATE FUNCTION feature.issue_curation_source_rule_decision() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog'
    AS $$
        DECLARE
            projection feature.curated_features%ROWTYPE;
            source_provider text;
            source_dataset text;
            new_decision_id uuid;
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM feature.curation_link_decisions AS existing
                WHERE existing.decision_id = NEW.accepted_link_decision_id
                  AND existing.curation_item_id = NEW.curation_item_id
                  AND existing.feature_id = NEW.feature_id
                  AND existing.decision_kind = 'accepted'
                  AND existing.match_basis <> 'legacy_unattributed'
            ) THEN
                RETURN NULL;
            END IF;

            IF EXISTS (
                SELECT 1
                FROM feature.curation_link_decisions AS revocation
                WHERE revocation.curation_item_id = NEW.curation_item_id
                  AND revocation.decision_kind = 'revoked'
                  AND NOT EXISTS (
                      SELECT 1
                      FROM feature.curation_link_decisions AS successor
                      WHERE successor.supersedes_decision_id = revocation.decision_id
                  )
            ) THEN
                RETURN NULL;
            END IF;

            SELECT * INTO projection
              FROM feature.curated_features AS cf
             WHERE cf.curated_feature_id =
                   COALESCE(NEW.legacy_projection_id, NEW.curation_item_id);
            IF NOT FOUND
               OR projection.selection_origin IS DISTINCT FROM 'source_rule'
               OR projection.feature_id IS DISTINCT FROM NEW.feature_id
               OR projection.source_record_key IS DISTINCT FROM NEW.source_record_key
            THEN
                RETURN NULL;
            END IF;

            SELECT dataset.provider, dataset.dataset_key
              INTO source_provider, source_dataset
              FROM provider_sync.source_records AS record
              JOIN provider_sync.source_entities AS entity
                ON entity.source_entity_key = record.source_entity_key
              JOIN provider_sync.provider_datasets AS dataset
                ON dataset.provider_dataset_id = entity.provider_dataset_id
             WHERE record.source_record_key = projection.source_record_key;
            IF source_provider IS NULL THEN
                RETURN NULL;
            END IF;

            INSERT INTO feature.curation_link_decisions (
                curation_item_id, feature_id, decision_kind, match_basis,
                resolver_version, evidence, actor, decided_at, supersedes_decision_id
            ) VALUES (
                NEW.curation_item_id, NEW.feature_id, 'accepted', 'source_rule',
                'source-rule-v' || projection.content_version::text,
                jsonb_build_object(
                    'writer', 'issue_curation_source_rule_decision',
                    'source_record_key', projection.source_record_key,
                    'selection_origin', projection.selection_origin,
                    'content_version', projection.content_version,
                    'provider', source_provider,
                    'dataset_key', source_dataset
                ),
                COALESCE(NULLIF(btrim(projection.selected_by), ''),
                         'source_rule:' || source_provider),
                COALESCE(NEW.updated_at, now()),
                NEW.accepted_link_decision_id
            ) RETURNING decision_id INTO new_decision_id;

            UPDATE feature.curation_items
               SET accepted_link_decision_id = new_decision_id
             WHERE curation_item_id = NEW.curation_item_id;
            RETURN NULL;
        END;
        $$;


ALTER FUNCTION feature.issue_curation_source_rule_decision() OWNER TO ktm_feature_schema_owner;

--
-- Name: lock_current_provider_feature_source_evidence(text, bigint, text, text); Type: FUNCTION; Schema: feature; Owner: ktm_feature_state_procedure_owner
--

CREATE FUNCTION feature.lock_current_provider_feature_source_evidence(p_feature_id text, p_provider_dataset_id bigint, p_source_entity_key text, p_source_record_key text) RETURNS text
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog'
    AS $$
DECLARE
    v_raw_payload_hash text;
BEGIN
    -- Match the provider bundle writer exactly: dataset/entity/record/head,
    -- then its Feature source link, then the Feature row taken by the caller.
    -- In particular, do not lock the link first: a concurrent bundle holds
    -- the entity head while it later upserts the link, which would form a
    -- head↔link cycle.
    v_raw_payload_hash := feature.lock_current_provider_source_evidence(
        p_provider_dataset_id,
        p_source_entity_key,
        p_source_record_key
    );
    PERFORM 1
      FROM provider_sync.source_links AS link
     WHERE link.feature_id = p_feature_id
       AND link.source_entity_key = p_source_entity_key
     FOR SHARE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'provider lifecycle transition requires linked source evidence'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_provider_source_provenance';
    END IF;
    RETURN v_raw_payload_hash;
END;
$$;


ALTER FUNCTION feature.lock_current_provider_feature_source_evidence(p_feature_id text, p_provider_dataset_id bigint, p_source_entity_key text, p_source_record_key text) OWNER TO ktm_feature_state_procedure_owner;

--
-- Name: lock_current_provider_source_evidence(bigint, text, text); Type: FUNCTION; Schema: feature; Owner: ktm_feature_state_procedure_owner
--

CREATE FUNCTION feature.lock_current_provider_source_evidence(p_provider_dataset_id bigint, p_source_entity_key text, p_source_record_key text) RETURNS text
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog'
    AS $$
DECLARE
    v_raw_payload_hash text;
BEGIN
    SELECT record.raw_payload_hash
      INTO v_raw_payload_hash
      FROM provider_sync.provider_datasets AS dataset
      JOIN provider_sync.source_entities AS entity
        ON entity.provider_dataset_id = dataset.provider_dataset_id
      JOIN provider_sync.source_records AS record
        ON record.source_entity_key = entity.source_entity_key
      JOIN provider_sync.source_entity_heads AS head
        ON head.source_entity_key = entity.source_entity_key
       AND head.current_source_record_key = record.source_record_key
     WHERE dataset.provider_dataset_id = p_provider_dataset_id
       AND dataset.is_active
       AND entity.source_entity_key = p_source_entity_key
       AND record.source_record_key = p_source_record_key
     FOR SHARE OF dataset, entity, record, head;
    IF v_raw_payload_hash IS NULL OR btrim(v_raw_payload_hash) = '' THEN
        RAISE EXCEPTION 'provider state transition requires current active source evidence'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_provider_source_provenance';
    END IF;
    RETURN v_raw_payload_hash;
END;
$$;


ALTER FUNCTION feature.lock_current_provider_source_evidence(p_provider_dataset_id bigint, p_source_entity_key text, p_source_record_key text) OWNER TO ktm_feature_state_procedure_owner;

--
-- Name: prepare_feature_state_context(jsonb, text); Type: FUNCTION; Schema: feature; Owner: ktm_feature_state_procedure_owner
--

CREATE FUNCTION feature.prepare_feature_state_context(p_context jsonb, p_mode text) RETURNS void
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog'
    AS $_$
DECLARE
    v_kind text;
    v_reason text;
    v_principal text;
    v_dataset_id bigint;
    v_source_entity_key text;
    v_source_record_key text;
    v_provider_receipt text;
    v_context jsonb;
BEGIN
    IF jsonb_typeof(p_context) IS DISTINCT FROM 'object' THEN
        RAISE EXCEPTION 'feature state context must be an object'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_state_transition_context';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM jsonb_object_keys(p_context) AS key_name(key_name)
        WHERE key_name NOT IN (
            'transition_kind', 'reason_code', 'principal', 'causation_ref',
            'provider_dataset_id', 'source_entity_key', 'source_record_key',
            'reactivation_evidence'
        )
    ) THEN
        RAISE EXCEPTION 'feature state context contains an unknown key'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_state_transition_context';
    END IF;

    v_kind := p_context ->> 'transition_kind';
    v_reason := p_context ->> 'reason_code';
    IF v_kind NOT IN (
        'initial', 'legacy_backfill', 'provider_sync', 'admin', 'user_request',
        'merge', 'quality_validation', 'system'
    ) OR v_reason IS NULL OR btrim(v_reason) = '' THEN
        RAISE EXCEPTION 'feature state context has invalid kind or reason'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_state_transition_context';
    END IF;

    IF (p_mode = 'create' AND v_kind NOT IN ('initial', 'legacy_backfill', 'provider_sync'))
       OR (p_mode = 'transition' AND v_kind IN ('initial', 'legacy_backfill')) THEN
        RAISE EXCEPTION 'feature state transition kind is invalid for %', p_mode
            USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_state_transition_kind';
    END IF;

    -- provider initial creation도 ``provider_sync`` kind를 보존한다. 이때도
    -- principal은 dataset에서만 파생하고 old tuple은 NULL이다.
    IF v_kind = 'provider_sync' THEN
        IF (p_context ->> 'provider_dataset_id') !~ '^[1-9][0-9]*$'
           OR p_context ? 'principal'
           OR jsonb_typeof(p_context -> 'source_entity_key') IS DISTINCT FROM 'string'
           OR btrim(p_context ->> 'source_entity_key') = ''
           OR jsonb_typeof(p_context -> 'source_record_key') IS DISTINCT FROM 'string'
           OR btrim(p_context ->> 'source_record_key') = '' THEN
                RAISE EXCEPTION 'provider state context must derive its principal from a dataset'
                USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_state_transition_context';
        END IF;
        v_dataset_id := (p_context ->> 'provider_dataset_id')::bigint;
        v_source_entity_key := btrim(p_context ->> 'source_entity_key');
        v_source_record_key := btrim(p_context ->> 'source_record_key');
        SELECT 'provider:' || dataset.provider || '/' || dataset.dataset_key
          INTO v_principal
          FROM provider_sync.provider_datasets AS dataset
         WHERE dataset.provider_dataset_id = v_dataset_id
           AND dataset.is_active;
        IF v_principal IS NULL THEN
            RAISE EXCEPTION 'active provider dataset % is required for state transition', v_dataset_id
                USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_state_transition_context';
        END IF;
        SELECT record.raw_payload_hash
          INTO v_provider_receipt
          FROM provider_sync.source_records AS record
          JOIN provider_sync.source_entities AS entity
            ON entity.source_entity_key = record.source_entity_key
          JOIN provider_sync.source_entity_heads AS head
            ON head.source_entity_key = entity.source_entity_key
           AND head.current_source_record_key = record.source_record_key
         WHERE record.source_record_key = v_source_record_key
           AND record.source_entity_key = v_source_entity_key
           AND entity.provider_dataset_id = v_dataset_id;
        IF v_provider_receipt IS NULL OR btrim(v_provider_receipt) = '' THEN
            RAISE EXCEPTION 'provider state context source does not belong to the active dataset'
                USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_provider_source_provenance';
        END IF;
    ELSE
        IF p_context ? 'provider_dataset_id'
           OR jsonb_typeof(p_context -> 'principal') IS DISTINCT FROM 'string'
           OR btrim(p_context ->> 'principal') = '' THEN
            RAISE EXCEPTION 'non-provider state context requires an authenticated principal'
                USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_state_transition_context';
        END IF;
        v_principal := btrim(p_context ->> 'principal');
    END IF;

    IF p_context ? 'causation_ref'
       AND jsonb_typeof(p_context -> 'causation_ref') NOT IN ('string', 'null') THEN
        RAISE EXCEPTION 'causation_ref must be a string or null'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_state_transition_context';
    END IF;

    v_context := jsonb_build_object(
        'transition_kind', v_kind,
        'reason_code', btrim(v_reason),
        'principal', v_principal,
        'causation_ref', p_context -> 'causation_ref'
    );
    IF v_dataset_id IS NOT NULL THEN
        v_context := v_context || jsonb_build_object(
            'provider_dataset_id', v_dataset_id,
            'source_entity_key', v_source_entity_key,
            'source_record_key', v_source_record_key,
            'provider_evidence', jsonb_build_object(
                'authoritative_receipt', v_provider_receipt
            )
        );
    END IF;
    IF p_context ? 'reactivation_evidence' THEN
        v_context := v_context || jsonb_build_object(
            'reactivation_evidence', p_context -> 'reactivation_evidence'
        );
    END IF;

    PERFORM set_config('feature.state_transition_context', v_context::text, true);
    PERFORM set_config('feature.state_procedure_definer', current_user::text, true);
END;
$_$;


ALTER FUNCTION feature.prepare_feature_state_context(p_context jsonb, p_mode text) OWNER TO ktm_feature_state_procedure_owner;

--
-- Name: reactivate_admin_feature_state(text, bigint, text, text, bigint, text, text); Type: PROCEDURE; Schema: feature; Owner: ktm_feature_state_procedure_owner
--

CREATE PROCEDURE feature.reactivate_admin_feature_state(IN p_feature_id text, IN p_provider_dataset_id bigint, IN p_source_entity_key text, IN p_source_record_key text, IN p_expected_row_revision bigint, IN p_reason_code text, IN p_principal text, OUT o_feature_id text, OUT o_row_revision bigint, OUT o_transition_id bigint)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog'
    AS $$
DECLARE
    v_current feature.features%ROWTYPE;
    v_raw_payload_hash text;
    v_causation_ref text;
BEGIN
    IF p_provider_dataset_id IS NULL
       OR coalesce(btrim(p_source_entity_key), '') = ''
       OR coalesce(btrim(p_source_record_key), '') = ''
       OR p_expected_row_revision IS NULL OR p_expected_row_revision < 1
       OR coalesce(btrim(p_reason_code), '') = ''
       OR coalesce(btrim(p_principal), '') = '' THEN
        RAISE EXCEPTION 'admin reactivation has invalid arguments'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_admin_reactivation';
    END IF;
    -- Match provider ingestion's source→Feature lock order.  This proof stays
    -- locked through the override revocation, state transition and audit.
    v_raw_payload_hash := feature.lock_current_provider_feature_source_evidence(
        p_feature_id,
        p_provider_dataset_id,
        p_source_entity_key,
        p_source_record_key
    );
    SELECT * INTO v_current FROM feature.features
     WHERE feature_id = p_feature_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'feature % does not exist', p_feature_id USING ERRCODE = 'P0002';
    END IF;
    IF v_current.row_revision <> p_expected_row_revision THEN
        RAISE EXCEPTION 'feature % revision changed', p_feature_id USING ERRCODE = '40001';
    END IF;
    IF v_current.lifecycle_state <> 'retired' THEN
        RAISE EXCEPTION 'admin reactivation requires a retired feature'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_admin_reactivation';
    END IF;
    IF EXISTS (
        SELECT 1 FROM ops.feature_overrides AS override
        WHERE override.feature_id = p_feature_id
          AND override.field_path = 'lifecycle_state'
          AND override.status = 'active'
          AND override.override_value IS DISTINCT FROM '"retired"'::jsonb
    ) THEN
        RAISE EXCEPTION 'active lifecycle override is inconsistent with retired feature'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_admin_reactivation';
    END IF;
    UPDATE ops.feature_overrides AS override
       SET status = 'superseded',
           created_by = btrim(p_principal),
           created_at = clock_timestamp()
     WHERE override.feature_id = p_feature_id
       AND override.field_path = 'lifecycle_state'
       AND override.status = 'active'
       AND override.override_value = '"retired"'::jsonb;
    v_causation_ref := jsonb_build_object(
        'provider_dataset_id', p_provider_dataset_id,
        'source_entity_key', btrim(p_source_entity_key),
        'source_record_key', btrim(p_source_record_key),
        'raw_payload_hash', v_raw_payload_hash
    )::text;
    CALL feature.transition_feature_state(
        p_feature_id, 'active', 'suppressed', v_current.quality_state,
        p_expected_row_revision,
        jsonb_build_object(
            'transition_kind', 'admin',
            'reason_code', btrim(p_reason_code),
            'principal', btrim(p_principal),
            'causation_ref', v_causation_ref,
            'reactivation_evidence', v_causation_ref::jsonb
        ),
        o_feature_id, o_row_revision
    );
    SELECT transition.transition_id INTO o_transition_id
    FROM feature.feature_state_transitions AS transition
    WHERE transition.feature_id = o_feature_id
      AND transition.row_revision = o_row_revision
      AND transition.transition_kind = 'admin'
      AND transition.reason_code = btrim(p_reason_code)
      AND transition.principal = btrim(p_principal)
      AND transition.causation_ref = v_causation_ref
    ORDER BY transition.transition_id DESC
    LIMIT 1;
    IF o_transition_id IS NULL THEN
        RAISE EXCEPTION 'admin reactivation did not write its audit transition';
    END IF;
END;
$$;


ALTER PROCEDURE feature.reactivate_admin_feature_state(IN p_feature_id text, IN p_provider_dataset_id bigint, IN p_source_entity_key text, IN p_source_record_key text, IN p_expected_row_revision bigint, IN p_reason_code text, IN p_principal text, OUT o_feature_id text, OUT o_row_revision bigint, OUT o_transition_id bigint) OWNER TO ktm_feature_state_procedure_owner;

--
-- Name: reject_curation_history_mutation(); Type: FUNCTION; Schema: feature; Owner: ktm_feature_schema_owner
--

CREATE FUNCTION feature.reject_curation_history_mutation() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
  -- merge의 legacy-conflict detach가 curation_items.curation_item_id를 재작성할 때,
  -- 위 4개 FK의 ON UPDATE CASCADE가 같은 문장 안에서 이 행의 curation_item_id만
  -- 따라오게 만든다. 그 부모-키 재작성은 이력 변경이 아니다 — curation_item_id
  -- **하나만** 바뀌었을 때만 통과시키고, 다른 컬럼이 하나라도 같이 바뀌면 여전히
  -- 거부한다.
  --
  -- 이 트리거 함수는 curation_import_batches(curation_item_id 컬럼이 없다)에도
  -- 그대로 붙는다. plpgsql에서 `NEW.curation_item_id`처럼 정적으로 필드를 참조하면
  -- 그 컬럼이 없는 테이블에 대해 함수가 실행될 때 UndefinedColumnError로 죽는다
  -- (실행해서 확인함). 그래서 `to_jsonb(NEW) ? 'curation_item_id'`로 **동적**으로
  -- 존재 여부를 먼저 확인하고, 나머지도 jsonb 경로로만 접근한다.
  IF TG_OP = 'UPDATE'
     AND to_jsonb(NEW) ? 'curation_item_id'
     AND (to_jsonb(NEW) ->> 'curation_item_id')
             IS DISTINCT FROM (to_jsonb(OLD) ->> 'curation_item_id')
     AND to_jsonb(NEW) - 'curation_item_id' = to_jsonb(OLD) - 'curation_item_id'
  THEN
    RETURN NEW;
  END IF;

  RAISE EXCEPTION 'curation import/link history is append-only'
    USING ERRCODE = '55000';
END;
$$;


ALTER FUNCTION feature.reject_curation_history_mutation() OWNER TO ktm_feature_schema_owner;

--
-- Name: reject_feature_change_request_receipt_mutation(); Type: FUNCTION; Schema: feature; Owner: ktm_feature_state_procedure_owner
--

CREATE FUNCTION feature.reject_feature_change_request_receipt_mutation() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog'
    AS $$
BEGIN
    -- A durable user receipt is the immutable applied-request binding during
    -- the T-VN-34C→T-VN-36 bridge.  Changing or deleting its request would
    -- make the receipt's feature/action/applied provenance lie.
    IF EXISTS (
        SELECT 1
        FROM feature.feature_versions AS version
        WHERE version.origin = 'user_request'
          AND version.request_id = OLD.request_id
    ) THEN
        RAISE EXCEPTION 'feature change request with a durable receipt is immutable'
            USING ERRCODE = '42501', CONSTRAINT = 'ck_feature_change_request_receipt_immutable';
    END IF;
    RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
END;
$$;


ALTER FUNCTION feature.reject_feature_change_request_receipt_mutation() OWNER TO ktm_feature_state_procedure_owner;

--
-- Name: reject_feature_state_transition_mutation(); Type: FUNCTION; Schema: feature; Owner: ktm_feature_audit_writer
--

CREATE FUNCTION feature.reject_feature_state_transition_mutation() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog'
    AS $$
BEGIN
    RAISE EXCEPTION 'feature state transitions are append-only'
        USING ERRCODE = '42501', CONSTRAINT = 'ck_feature_state_transitions_append_only';
END;
$$;


ALTER FUNCTION feature.reject_feature_state_transition_mutation() OWNER TO ktm_feature_audit_writer;

--
-- Name: reject_price_value_mutation(); Type: FUNCTION; Schema: feature; Owner: ktm_feature_schema_owner
--

CREATE FUNCTION feature.reject_price_value_mutation() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog'
    AS $$
        BEGIN
            -- parent feature cascade는 derived fact/summary 제거의 유일한 예외다.
            IF TG_OP = 'DELETE' AND NOT EXISTS (
                SELECT 1 FROM feature.features AS f WHERE f.feature_id = OLD.feature_id
            ) THEN
                RETURN OLD;
            END IF;
            RAISE EXCEPTION 'feature_price_values facts are immutable (ADR-089)'
                USING ERRCODE = '23514', CONSTRAINT = 'ck_price_values_immutable';
        END;
        $$;


ALTER FUNCTION feature.reject_price_value_mutation() OWNER TO ktm_feature_schema_owner;

--
-- Name: reject_user_feature_version_mutation(); Type: FUNCTION; Schema: feature; Owner: ktm_feature_state_procedure_owner
--

CREATE FUNCTION feature.reject_user_feature_version_mutation() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog'
    AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF NEW.origin <> 'user_request' THEN
            RETURN NEW;
        END IF;
        IF NEW.request_id IS NULL OR NOT EXISTS (
            SELECT 1 FROM ops.feature_change_requests AS request
            WHERE request.request_id = NEW.request_id
              AND request.feature_id = NEW.feature_id
              AND request.action = NEW.change_kind
              AND request.state = 'applied'
        ) THEN
            RAISE EXCEPTION 'user feature version needs its applied request binding'
                USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_user_provenance_request';
        END IF;
        RETURN NEW;
    END IF;
    IF TG_OP = 'DELETE' THEN
        IF OLD.origin = 'user_request' THEN
            RAISE EXCEPTION 'user feature version receipts are immutable'
                USING ERRCODE = '42501', CONSTRAINT = 'ck_feature_versions_user_request_immutable';
        END IF;
        RETURN OLD;
    END IF;
    IF OLD.origin = 'user_request' OR NEW.origin = 'user_request' THEN
        RAISE EXCEPTION 'user feature version receipts are immutable'
            USING ERRCODE = '42501', CONSTRAINT = 'ck_feature_versions_user_request_immutable';
    END IF;
    RETURN NEW;
END;
$$;


ALTER FUNCTION feature.reject_user_feature_version_mutation() OWNER TO ktm_feature_state_procedure_owner;

--
-- Name: reject_weather_value_mutation(); Type: FUNCTION; Schema: feature; Owner: ktm_feature_schema_owner
--

CREATE FUNCTION feature.reject_weather_value_mutation() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog'
    AS $$
        BEGIN
            IF TG_OP = 'DELETE' AND NOT EXISTS (
                SELECT 1 FROM feature.features AS f WHERE f.feature_id = OLD.feature_id
            ) THEN
                RETURN OLD;
            END IF;
            RAISE EXCEPTION 'feature_weather_values facts are immutable (ADR-089)'
                USING ERRCODE = '23514', CONSTRAINT = 'ck_weather_values_immutable';
        END;
        $$;


ALTER FUNCTION feature.reject_weather_value_mutation() OWNER TO ktm_feature_schema_owner;

--
-- Name: revoke_feature_field_overrides(text, bigint, text, text, bigint, text[]); Type: PROCEDURE; Schema: feature; Owner: ktm_feature_state_procedure_owner
--

CREATE PROCEDURE feature.revoke_feature_field_overrides(IN p_feature_id text, IN p_expected_row_revision bigint, IN p_principal text, IN p_reason_code text, IN p_command_id bigint, IN p_field_paths text[], OUT o_feature_id text, OUT o_row_revision bigint, OUT o_command_id bigint, OUT o_applied_field_count integer)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog'
    AS $$
DECLARE
    v_feature feature.features%ROWTYPE;
    v_registry ops.feature_override_field_paths%ROWTYPE;
    v_operation text;
    v_field_path text;
    v_values jsonb;
    v_geometry_wkt jsonb;
BEGIN
    IF p_expected_row_revision IS NULL OR p_expected_row_revision < 1
       OR p_command_id IS NULL
       OR coalesce(btrim(p_feature_id), '') = ''
       OR coalesce(btrim(p_principal), '') = ''
       OR coalesce(btrim(p_reason_code), '') = ''
       OR p_field_paths IS NULL OR cardinality(p_field_paths) < 1
       OR EXISTS (SELECT 1 FROM unnest(p_field_paths) AS path WHERE coalesce(btrim(path), '') = '')
       OR cardinality(p_field_paths) <> (SELECT count(DISTINCT path) FROM unnest(p_field_paths) AS path) THEN
        RAISE EXCEPTION 'field override revoke has invalid arguments'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_override_command';
    END IF;
    o_applied_field_count := cardinality(p_field_paths);

    SELECT command.operation INTO v_operation
    FROM ops.domain_commands AS command
    WHERE command.command_id = p_command_id
      AND command.actor = btrim(p_principal)
      AND NOT EXISTS (
          SELECT 1 FROM ops.domain_command_results AS result
          WHERE result.command_id = command.command_id
      )
    FOR SHARE;
    IF NOT FOUND OR v_operation <> 'admin.feature.override.revoke' THEN
        RAISE EXCEPTION 'field override revoke requires an open matching domain command'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_override_command';
    END IF;

    SELECT * INTO v_feature FROM feature.features
    WHERE feature_id = p_feature_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'feature % does not exist', p_feature_id USING ERRCODE = 'P0002';
    END IF;
    IF v_feature.row_revision <> p_expected_row_revision THEN
        RAISE EXCEPTION 'feature % revision changed', p_feature_id USING ERRCODE = '40001';
    END IF;

    FOREACH v_field_path IN ARRAY p_field_paths LOOP
        SELECT * INTO v_registry FROM ops.feature_override_field_paths
        WHERE field_path = v_field_path;
        IF NOT FOUND OR (v_registry.feature_kind <> '*' AND v_registry.feature_kind <> v_feature.kind) THEN
            RAISE EXCEPTION 'operator cannot revoke field path %', v_field_path
                USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_override_field_path';
        END IF;
        PERFORM 1 FROM ops.feature_overrides
        WHERE feature_id = p_feature_id AND field_path = v_field_path AND status = 'active'
        FOR UPDATE;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'Feature has no active field override for %', v_field_path
                USING ERRCODE = 'P0002';
        END IF;
        PERFORM 1 FROM feature.feature_base_field_values
        WHERE feature_id = p_feature_id AND field_path = v_field_path
        FOR SHARE;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'field override % has no provider base to restore', v_field_path
                USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_override_revoke_base';
        END IF;
    END LOOP;

    SELECT COALESCE(jsonb_object_agg(base.field_path, base.value_json)
                    FILTER (WHERE registry.value_kind <> 'geometry'), '{}'::jsonb),
           COALESCE(jsonb_object_agg(
                    base.field_path,
                    CASE WHEN base.value_json = 'null'::jsonb THEN 'null'::jsonb
                         ELSE to_jsonb(x_extension.st_astext(base.value_geometry)) END
                ) FILTER (WHERE registry.value_kind = 'geometry'), '{}'::jsonb)
    INTO v_values, v_geometry_wkt
    FROM feature.feature_base_field_values AS base
    JOIN ops.feature_override_field_paths AS registry USING (field_path)
    WHERE base.feature_id = p_feature_id AND base.field_path = ANY(p_field_paths);

    UPDATE ops.feature_overrides
    SET status = 'revoked', revoked_at = clock_timestamp(),
        revoked_by = btrim(p_principal), revoked_reason = btrim(p_reason_code)
    WHERE feature_id = p_feature_id AND field_path = ANY(p_field_paths) AND status = 'active';

    UPDATE feature.features AS core
    SET name = CASE
            WHEN v_values ? 'core.name'
            THEN v_values ->> 'core.name'
            ELSE core.name
        END,
        category = CASE
            WHEN v_values ? 'core.category'
            THEN v_values ->> 'core.category'
            ELSE core.category
        END,
        coord = CASE
            WHEN v_geometry_wkt ? 'core.coord'
            THEN CASE WHEN v_geometry_wkt ->> 'core.coord' IS NULL THEN NULL ELSE x_extension.st_geomfromtext(v_geometry_wkt ->> 'core.coord', 4326) END
            ELSE core.coord
        END,
        coord_precision_digits = CASE
            WHEN v_values ? 'core.coord_precision_digits'
            THEN (v_values ->> 'core.coord_precision_digits')::smallint
            ELSE core.coord_precision_digits
        END,
        address = CASE
            WHEN v_values ? 'core.address'
            THEN v_values -> 'core.address'
            ELSE core.address
        END,
        legal_dong_code = CASE
            WHEN v_values ? 'core.legal_dong_code'
            THEN v_values ->> 'core.legal_dong_code'
            ELSE core.legal_dong_code
        END,
        road_name_code = CASE
            WHEN v_values ? 'core.road_name_code'
            THEN v_values ->> 'core.road_name_code'
            ELSE core.road_name_code
        END,
        road_address_management_no = CASE
            WHEN v_values ? 'core.road_address_management_no'
            THEN v_values ->> 'core.road_address_management_no'
            ELSE core.road_address_management_no
        END,
        admin_dong_code = CASE
            WHEN v_values ? 'core.admin_dong_code'
            THEN v_values ->> 'core.admin_dong_code'
            ELSE core.admin_dong_code
        END,
        sido_code = CASE
            WHEN v_values ? 'core.sido_code'
            THEN v_values ->> 'core.sido_code'
            ELSE core.sido_code
        END,
        sigungu_code = CASE
            WHEN v_values ? 'core.sigungu_code'
            THEN v_values ->> 'core.sigungu_code'
            ELSE core.sigungu_code
        END,
        urls = CASE
            WHEN v_values ? 'core.urls'
            THEN v_values -> 'core.urls'
            ELSE core.urls
        END,
        marker_icon = CASE
            WHEN v_values ? 'core.marker_icon'
            THEN v_values ->> 'core.marker_icon'
            ELSE core.marker_icon
        END,
        marker_color = CASE
            WHEN v_values ? 'core.marker_color'
            THEN v_values ->> 'core.marker_color'
            ELSE core.marker_color
        END,
        parent_feature_id = CASE
            WHEN v_values ? 'core.parent_feature_id'
            THEN v_values ->> 'core.parent_feature_id'
            ELSE core.parent_feature_id
        END,
        sibling_group_id = CASE
            WHEN v_values ? 'core.sibling_group_id'
            THEN NULLIF(v_values ->> 'core.sibling_group_id', '')::uuid
            ELSE core.sibling_group_id
        END,
        raw_refs = CASE
            WHEN v_values ? 'core.raw_refs'
            THEN v_values -> 'core.raw_refs'
            ELSE core.raw_refs
        END,
        updated_at = clock_timestamp()
    WHERE core.feature_id = p_feature_id
    RETURNING core.feature_id, core.row_revision INTO o_feature_id, o_row_revision;
    IF v_feature.kind = 'place' AND EXISTS (SELECT 1 FROM jsonb_object_keys(v_values) AS supplied_path(field_path) WHERE supplied_path.field_path LIKE 'place.%') THEN
        PERFORM 1 FROM feature.feature_places WHERE feature_id = p_feature_id FOR UPDATE;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'place subtype is missing'
                USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_override_subtype';
        END IF;
        UPDATE feature.feature_places AS place
        SET place_kind = CASE
            WHEN v_values ? 'place.place_kind'
            THEN v_values ->> 'place.place_kind'
            ELSE place.place_kind
        END,
            phones = CASE
            WHEN v_values ? 'place.phones'
            THEN ARRAY(SELECT jsonb_array_elements_text(v_values -> 'place.phones'))
            ELSE place.phones
        END,
            biz_number = CASE
            WHEN v_values ? 'place.biz_number'
            THEN v_values ->> 'place.biz_number'
            ELSE place.biz_number
        END,
            license_date = CASE
            WHEN v_values ? 'place.license_date'
            THEN (v_values ->> 'place.license_date')::date
            ELSE place.license_date
        END,
            business_hours = CASE
            WHEN v_values ? 'place.business_hours'
            THEN v_values -> 'place.business_hours'
            ELSE place.business_hours
        END,
            facility_info = CASE
            WHEN v_values ? 'place.facility_info'
            THEN v_values -> 'place.facility_info'
            ELSE place.facility_info
        END,
            reviews_link = CASE
            WHEN v_values ? 'place.reviews_link'
            THEN v_values -> 'place.reviews_link'
            ELSE place.reviews_link
        END,
            payload = CASE
            WHEN v_values ? 'place.payload'
            THEN v_values -> 'place.payload'
            ELSE place.payload
        END
      WHERE place.feature_id = p_feature_id;
    ELSIF v_feature.kind = 'event' AND EXISTS (SELECT 1 FROM jsonb_object_keys(v_values) AS supplied_path(field_path) WHERE supplied_path.field_path LIKE 'event.%') THEN
        PERFORM 1 FROM feature.feature_events WHERE feature_id = p_feature_id FOR UPDATE;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'event subtype is missing'
                USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_override_subtype';
        END IF;
        UPDATE feature.feature_events AS event
        SET event_kind = CASE
            WHEN v_values ? 'event.event_kind'
            THEN v_values ->> 'event.event_kind'
            ELSE event.event_kind
        END,
            starts_on = CASE
            WHEN v_values ? 'event.starts_on'
            THEN (v_values ->> 'event.starts_on')::date
            ELSE event.starts_on
        END,
            ends_on = CASE
            WHEN v_values ? 'event.ends_on'
            THEN (v_values ->> 'event.ends_on')::date
            ELSE event.ends_on
        END,
            timezone = CASE
            WHEN v_values ? 'event.timezone'
            THEN v_values ->> 'event.timezone'
            ELSE event.timezone
        END,
            opening_hours = CASE
            WHEN v_values ? 'event.opening_hours'
            THEN v_values -> 'event.opening_hours'
            ELSE event.opening_hours
        END,
            venue_name = CASE
            WHEN v_values ? 'event.venue_name'
            THEN v_values ->> 'event.venue_name'
            ELSE event.venue_name
        END,
            tel = CASE
            WHEN v_values ? 'event.tel'
            THEN v_values ->> 'event.tel'
            ELSE event.tel
        END,
            content_id = CASE
            WHEN v_values ? 'event.content_id'
            THEN v_values ->> 'event.content_id'
            ELSE event.content_id
        END,
            content_type_id = CASE
            WHEN v_values ? 'event.content_type_id'
            THEN v_values ->> 'event.content_type_id'
            ELSE event.content_type_id
        END,
            area_code = CASE
            WHEN v_values ? 'event.area_code'
            THEN v_values ->> 'event.area_code'
            ELSE event.area_code
        END,
            sigungu_code = CASE
            WHEN v_values ? 'event.sigungu_code'
            THEN v_values ->> 'event.sigungu_code'
            ELSE event.sigungu_code
        END,
            payload = CASE
            WHEN v_values ? 'event.payload'
            THEN v_values -> 'event.payload'
            ELSE event.payload
        END
      WHERE event.feature_id = p_feature_id;
    ELSIF v_feature.kind = 'notice' AND EXISTS (SELECT 1 FROM jsonb_object_keys(v_values) AS supplied_path(field_path) WHERE supplied_path.field_path LIKE 'notice.%') THEN
        PERFORM 1 FROM feature.feature_notices WHERE feature_id = p_feature_id FOR UPDATE;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'notice subtype is missing'
                USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_override_subtype';
        END IF;
        UPDATE feature.feature_notices AS notice
        SET notice_type = CASE
            WHEN v_values ? 'notice.notice_type'
            THEN v_values ->> 'notice.notice_type'
            ELSE notice.notice_type
        END,
            severity = CASE
            WHEN v_values ? 'notice.severity'
            THEN (v_values ->> 'notice.severity')::smallint
            ELSE notice.severity
        END,
            valid_start_time = CASE
            WHEN v_values ? 'notice.valid_start_time'
            THEN (v_values ->> 'notice.valid_start_time')::timestamptz
            ELSE notice.valid_start_time
        END,
            valid_end_time = CASE
            WHEN v_values ? 'notice.valid_end_time'
            THEN (v_values ->> 'notice.valid_end_time')::timestamptz
            ELSE notice.valid_end_time
        END,
            source_agency = CASE
            WHEN v_values ? 'notice.source_agency'
            THEN v_values ->> 'notice.source_agency'
            ELSE notice.source_agency
        END,
            officer_name = CASE
            WHEN v_values ? 'notice.officer_name'
            THEN v_values ->> 'notice.officer_name'
            ELSE notice.officer_name
        END,
            payload = CASE
            WHEN v_values ? 'notice.payload'
            THEN v_values -> 'notice.payload'
            ELSE notice.payload
        END
      WHERE notice.feature_id = p_feature_id;
    ELSIF v_feature.kind = 'route' AND (EXISTS (SELECT 1 FROM jsonb_object_keys(v_values) AS supplied_path(field_path) WHERE supplied_path.field_path LIKE 'route.%') OR EXISTS (SELECT 1 FROM jsonb_object_keys(v_geometry_wkt) AS supplied_path(field_path) WHERE supplied_path.field_path LIKE 'route.%')) THEN
        PERFORM 1 FROM feature.feature_routes WHERE feature_id = p_feature_id FOR UPDATE;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'route subtype is missing'
                USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_override_subtype';
        END IF;
        UPDATE feature.feature_routes AS route
        SET geom = CASE
            WHEN v_geometry_wkt ? 'route.geom'
            THEN x_extension.st_multi(x_extension.st_geomfromtext(v_geometry_wkt ->> 'route.geom', 4326))
            ELSE route.geom
        END,
            route_type = CASE
            WHEN v_values ? 'route.route_type'
            THEN v_values ->> 'route.route_type'
            ELSE route.route_type
        END,
            geometry_source = CASE
            WHEN v_values ? 'route.geometry_source'
            THEN v_values ->> 'route.geometry_source'
            ELSE route.geometry_source
        END,
            geometry_status = CASE
            WHEN v_values ? 'route.geometry_status'
            THEN v_values ->> 'route.geometry_status'
            ELSE route.geometry_status
        END,
            total_distance_meters = CASE
            WHEN v_values ? 'route.total_distance_meters'
            THEN (v_values ->> 'route.total_distance_meters')::numeric
            ELSE route.total_distance_meters
        END,
            expected_duration_minutes = CASE
            WHEN v_values ? 'route.expected_duration_minutes'
            THEN (v_values ->> 'route.expected_duration_minutes')::integer
            ELSE route.expected_duration_minutes
        END,
            difficulty = CASE
            WHEN v_values ? 'route.difficulty'
            THEN v_values ->> 'route.difficulty'
            ELSE route.difficulty
        END,
            begin_name = CASE
            WHEN v_values ? 'route.begin_name'
            THEN v_values ->> 'route.begin_name'
            ELSE route.begin_name
        END,
            begin_address = CASE
            WHEN v_values ? 'route.begin_address'
            THEN v_values ->> 'route.begin_address'
            ELSE route.begin_address
        END,
            end_name = CASE
            WHEN v_values ? 'route.end_name'
            THEN v_values ->> 'route.end_name'
            ELSE route.end_name
        END,
            end_address = CASE
            WHEN v_values ? 'route.end_address'
            THEN v_values ->> 'route.end_address'
            ELSE route.end_address
        END,
            payload = CASE
            WHEN v_values ? 'route.payload'
            THEN v_values -> 'route.payload'
            ELSE route.payload
        END
      WHERE route.feature_id = p_feature_id;
    ELSIF v_feature.kind = 'area' AND (EXISTS (SELECT 1 FROM jsonb_object_keys(v_values) AS supplied_path(field_path) WHERE supplied_path.field_path LIKE 'area.%') OR EXISTS (SELECT 1 FROM jsonb_object_keys(v_geometry_wkt) AS supplied_path(field_path) WHERE supplied_path.field_path LIKE 'area.%')) THEN
        PERFORM 1 FROM feature.feature_areas WHERE feature_id = p_feature_id FOR UPDATE;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'area subtype is missing'
                USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_override_subtype';
        END IF;
        UPDATE feature.feature_areas AS area
        SET geom = CASE
            WHEN v_geometry_wkt ? 'area.geom'
            THEN x_extension.st_multi(x_extension.st_geomfromtext(v_geometry_wkt ->> 'area.geom', 4326))
            ELSE area.geom
        END,
            area_kind = CASE
            WHEN v_values ? 'area.area_kind'
            THEN v_values ->> 'area.area_kind'
            ELSE area.area_kind
        END,
            boundary_source = CASE
            WHEN v_values ? 'area.boundary_source'
            THEN v_values ->> 'area.boundary_source'
            ELSE area.boundary_source
        END,
            area_square_meters = CASE
            WHEN v_values ? 'area.area_square_meters'
            THEN (v_values ->> 'area.area_square_meters')::numeric
            ELSE area.area_square_meters
        END,
            regulation_scope = CASE
            WHEN v_values ? 'area.regulation_scope'
            THEN v_values ->> 'area.regulation_scope'
            ELSE area.regulation_scope
        END,
            administrative_office = CASE
            WHEN v_values ? 'area.administrative_office'
            THEN v_values ->> 'area.administrative_office'
            ELSE area.administrative_office
        END,
            description = CASE
            WHEN v_values ? 'area.description'
            THEN v_values ->> 'area.description'
            ELSE area.description
        END,
            payload = CASE
            WHEN v_values ? 'area.payload'
            THEN v_values -> 'area.payload'
            ELSE area.payload
        END
      WHERE area.feature_id = p_feature_id;
    END IF;
    o_command_id := p_command_id;
END;
$$;


ALTER PROCEDURE feature.revoke_feature_field_overrides(IN p_feature_id text, IN p_expected_row_revision bigint, IN p_principal text, IN p_reason_code text, IN p_command_id bigint, IN p_field_paths text[], OUT o_feature_id text, OUT o_row_revision bigint, OUT o_command_id bigint, OUT o_applied_field_count integer) OWNER TO ktm_feature_state_procedure_owner;

--
-- Name: revoke_lifecycle_override(text, text, bigint); Type: PROCEDURE; Schema: feature; Owner: ktm_feature_state_procedure_owner
--

CREATE PROCEDURE feature.revoke_lifecycle_override(IN p_feature_id text, IN p_principal text, IN p_expected_row_revision bigint, OUT o_row_revision bigint)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog'
    AS $$
DECLARE
    v_current feature.features%ROWTYPE;
BEGIN
    IF coalesce(btrim(p_principal), '') = ''
       OR p_expected_row_revision IS NULL OR p_expected_row_revision < 1 THEN
        RAISE EXCEPTION 'lifecycle override revoke has invalid typed arguments'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_lifecycle_override_command';
    END IF;

    SELECT * INTO v_current
      FROM feature.features
     WHERE feature_id = p_feature_id
     FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'feature % does not exist', p_feature_id USING ERRCODE = 'P0002';
    END IF;
    IF v_current.row_revision <> p_expected_row_revision THEN
        RAISE EXCEPTION 'feature % revision changed', p_feature_id USING ERRCODE = '40001';
    END IF;

    UPDATE ops.feature_overrides
       SET status = 'superseded',
           created_by = btrim(p_principal),
           created_at = clock_timestamp()
     WHERE feature_id = p_feature_id
       AND field_path = 'lifecycle_state'
       AND status = 'active';
    IF NOT FOUND THEN
        RAISE EXCEPTION 'feature % has no active lifecycle override', p_feature_id
            USING ERRCODE = 'P0002';
    END IF;
    o_row_revision := v_current.row_revision;
END;
$$;


ALTER PROCEDURE feature.revoke_lifecycle_override(IN p_feature_id text, IN p_principal text, IN p_expected_row_revision bigint, OUT o_row_revision bigint) OWNER TO ktm_feature_state_procedure_owner;

--
-- Name: set_curation_item_legacy_component_identity(); Type: FUNCTION; Schema: feature; Owner: ktm_feature_schema_owner
--

CREATE FUNCTION feature.set_curation_item_legacy_component_identity() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    IF NEW.legacy_projection_id IS NOT NULL
       AND NEW.external_component_id = 'primary'
    THEN
        NEW.external_component_id :=
            'legacy:' || NEW.legacy_projection_id::text;
    END IF;
    RETURN NEW;
END;
$$;


ALTER FUNCTION feature.set_curation_item_legacy_component_identity() OWNER TO ktm_feature_schema_owner;

--
-- Name: set_feature_coord_precision(); Type: FUNCTION; Schema: feature; Owner: ktm_feature_schema_owner
--

CREATE FUNCTION feature.set_feature_coord_precision() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        BEGIN
            IF NEW.coord IS NULL THEN
                NEW.coord_precision_digits := NULL;
            ELSIF NEW.coord_precision_digits IS NULL THEN
                NEW.coord_precision_digits := 6;
            END IF;
            RETURN NEW;
        END;
        $$;


ALTER FUNCTION feature.set_feature_coord_precision() OWNER TO ktm_feature_schema_owner;

--
-- Name: sync_curated_feature_collection(); Type: FUNCTION; Schema: feature; Owner: ktm_feature_schema_owner
--

CREATE FUNCTION feature.sync_curated_feature_collection() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE
    target_collection_id uuid;
    target_collection_key text;
    target_collection_base_key text;
    target_key_conflict_ordinal integer;
    target_title text;
    mapped_collection_id uuid;
    mapped_theme_id uuid;
    mapped_source_id uuid;
    mapped_title text;
    mapped_archived boolean;
    mapped_external_item_id text;
    target_external_item_id text;
    operator_change boolean;
    source_change boolean;
    source_presence_change boolean;
    item_matched boolean;
    direct_item_id uuid;
    target_identity_item_id uuid;
    target_projection_id uuid;
    target_item_id uuid;
BEGIN
    -- detach marker는 merge/trigger 내부 상태다. 일반 INSERT 또는 top-level
    -- UPDATE로 주입해 canonical sync와 공개 projection을 우회할 수 없다.
    IF TG_OP = 'INSERT'
       AND NEW.metadata @> '{"merge_projection_detached": true}'::jsonb
    THEN
        RAISE EXCEPTION
            'merge_projection_detached metadata is reserved'
            USING ERRCODE = '23514';
    END IF;
    IF TG_OP = 'UPDATE'
       AND NOT OLD.metadata @> '{"merge_projection_detached": true}'::jsonb
       AND NEW.metadata @> '{"merge_projection_detached": true}'::jsonb
       AND pg_trigger_depth() = 1
    THEN
        -- Merge가 허용받는 유일한 top-level 전이는 UUID mirror를 분리한
        -- same-theme legacy conflict 또는 저장된 collection/external identity가
        -- 같은 canonical pair의 loser를 archive하는 경우다. 호출자 토큰/GUC가
        -- 아니라 transaction 안의 물리 불변식으로 권한을 판정한다.
        IF NEW.feature_id IS DISTINCT FROM OLD.feature_id
           AND NEW.curation_status = 'archived'
           AND NEW.archived_at IS NOT NULL
           AND NEW.metadata = OLD.metadata || jsonb_build_object(
               'merge_projection_detached',
               true
           )
           AND to_jsonb(NEW) - ARRAY[
               'feature_id',
               'curation_status',
               'metadata',
               'archived_at',
               'updated_at'
           ] = to_jsonb(OLD) - ARRAY[
               'feature_id',
               'curation_status',
               'metadata',
               'archived_at',
               'updated_at'
           ]
           AND (
               (
                   NOT EXISTS (
                       SELECT 1
                       FROM feature.curation_items AS direct_item
                       WHERE (
                               direct_item.legacy_projection_id =
                               NEW.curated_feature_id
                               OR (
                                   direct_item.legacy_projection_id IS NULL
                                   AND direct_item.curation_item_id =
                                       NEW.curated_feature_id
                               )
                           )
                         AND direct_item.archived_at IS NULL
                   )
                   AND EXISTS (
                       SELECT 1
                       FROM feature.curated_features AS master_legacy
                       WHERE master_legacy.curated_feature_id <>
                             NEW.curated_feature_id
                         AND master_legacy.theme_id = NEW.theme_id
                         AND master_legacy.feature_id = NEW.feature_id
                         AND master_legacy.archived_at IS NULL
                         AND NOT master_legacy.metadata @>
                             '{"merge_projection_detached": true}'::jsonb
                   )
               )
               OR EXISTS (
                   SELECT 1
                   FROM feature.curation_items AS loser_item
                   JOIN feature.curation_items AS master_item
                     ON master_item.collection_id = loser_item.collection_id
                    AND master_item.external_item_id =
                        loser_item.external_item_id
                   WHERE master_item.feature_id = NEW.feature_id
                     AND loser_item.legacy_projection_id =
                         NEW.curated_feature_id
                     AND master_item.curation_item_id <>
                         loser_item.curation_item_id
               )
           )
        THEN
            RETURN NEW;
        END IF;
        RAISE EXCEPTION
            'merge_projection_detached metadata is reserved'
            USING ERRCODE = '23514';
    END IF;

    -- Feature merge가 충돌 해소용으로 archive한 legacy projection은 더 이상
    -- canonical membership의 source가 아니다. 이후 운영 도구가 이 projection의
    -- 설명 등을 수정하거나 삭제해도 survivor를 되감지 않는다.
    IF TG_OP = 'DELETE' THEN
        IF OLD.metadata @> '{"merge_projection_detached": true}'::jsonb THEN
            RETURN OLD;
        END IF;
    ELSE
        IF TG_OP = 'UPDATE'
           AND OLD.metadata @> '{"merge_projection_detached": true}'::jsonb
        THEN
            -- ``metadata`` PATCH가 내부 detach marker를 제거해도 즉시 복원한다.
            -- 이 UPDATE의 재진입은 NEW marker 분기에서 끝나므로 canonical에는
            -- 어떤 source/operator revision도 전파하지 않는다.
            IF NOT NEW.metadata @> '{"merge_projection_detached": true}'::jsonb
               OR NEW.curation_status <> 'archived'
               OR NEW.archived_at IS NULL
            THEN
                UPDATE feature.curated_features
                SET curation_status = 'archived',
                    metadata = NEW.metadata || jsonb_build_object(
                        'merge_projection_detached',
                        true
                    ),
                    archived_at = COALESCE(
                        NEW.archived_at,
                        OLD.archived_at,
                        clock_timestamp()
                    )
                WHERE curated_feature_id = NEW.curated_feature_id;
            END IF;
            RETURN NEW;
        END IF;
        IF NEW.metadata @> '{"merge_projection_detached": true}'::jsonb THEN
            RETURN NEW;
        END IF;
    END IF;

    IF TG_OP = 'DELETE' THEN
        UPDATE feature.curation_items AS item
        SET source_present = false,
            source_updated_at = CASE
                WHEN item.source_present THEN clock_timestamp()
                ELSE item.source_updated_at
            END,
            legacy_projection_id = NULL,
            updated_by = COALESCE(OLD.rejected_by, OLD.selected_by),
            updated_at = now()
        WHERE (
              item.legacy_projection_id = OLD.curated_feature_id
              OR (
                  item.legacy_projection_id IS NULL
                  AND item.curation_item_id = OLD.curated_feature_id
              )
          );
        RETURN OLD;
    END IF;

    IF TG_OP = 'INSERT' THEN
        operator_change := NEW.operator_updated_at IS NOT NULL;
        source_change := true;
        source_presence_change := true;
    ELSE
        operator_change :=
            NEW.operator_updated_at IS DISTINCT FROM OLD.operator_updated_at
            OR NEW.operator_updated_by IS DISTINCT FROM OLD.operator_updated_by;
        source_change :=
            NEW.theme_id IS DISTINCT FROM OLD.theme_id
            OR NEW.source_id IS DISTINCT FROM OLD.source_id
            OR NEW.feature_id IS DISTINCT FROM OLD.feature_id
            OR NEW.source_record_key IS DISTINCT FROM OLD.source_record_key
            OR NEW.rank_score IS DISTINCT FROM OLD.rank_score
            OR NEW.display_title IS DISTINCT FROM OLD.display_title
            OR NEW.display_summary IS DISTINCT FROM OLD.display_summary
            OR NEW.metadata IS DISTINCT FROM OLD.metadata;
        source_presence_change :=
            NOT operator_change
            AND NEW.archived_at IS DISTINCT FROM OLD.archived_at;
    END IF;

    target_external_item_id :=
        COALESCE(NEW.source_record_key, NEW.curated_feature_id::text);

    SELECT COALESCE(NULLIF(btrim(NEW.display_title), ''), s.source_name)
    INTO target_title
    FROM feature.curated_themes AS t
    JOIN feature.curated_sources AS s ON s.source_id = NEW.source_id
    WHERE t.theme_id = NEW.theme_id;

    target_collection_base_key :=
        'legacy:' || NEW.theme_id::text || ':' || NEW.source_id::text || ':' ||
        md5(target_title);
    target_collection_key := target_collection_base_key;
    target_key_conflict_ordinal := 0;

    -- 이미 projection과 연결된 membership은 semantic group
    -- (theme_id/source_id/title)이 같으면 collection_id가 불변 identity다.
    -- theme slug 같은 표시 필드가 바뀌어도 기존 collection을 유지한다. Item을
    -- 먼저 잠그면 canonical writer의 legacy→collection→item 순서와 역전되므로
    -- 여기서는 관계만 읽고, collection을 잠근 다음 아래에서 item을 잠근다.
    SELECT
        item.collection_id,
        collection.theme_id,
        collection.source_id,
        collection.title,
        item.archived_at IS NOT NULL,
        item.external_item_id
    INTO
        mapped_collection_id,
        mapped_theme_id,
        mapped_source_id,
        mapped_title,
        mapped_archived,
        mapped_external_item_id
    FROM feature.curation_items AS item
    JOIN feature.curation_collections AS collection
      ON collection.collection_id = item.collection_id
    WHERE (
            item.legacy_projection_id = NEW.curated_feature_id
            OR (
                item.legacy_projection_id IS NULL
                AND item.curation_item_id = NEW.curated_feature_id
            )
        )
       OR (
            collection.theme_id = NEW.theme_id
            AND collection.source_id IS NOT DISTINCT FROM NEW.source_id
            AND collection.metadata @>
                '{"migrated_from": "feature.curated_features"}'::jsonb
            AND item.source_record_key
                IS NOT DISTINCT FROM NEW.source_record_key
            AND item.feature_id IS NOT DISTINCT FROM NEW.feature_id
        )
    ORDER BY
        (item.legacy_projection_id = NEW.curated_feature_id) DESC NULLS LAST,
        (item.archived_at IS NOT NULL) DESC,
        item.operator_updated_at DESC NULLS LAST,
        item.source_updated_at DESC,
        item.curation_item_id DESC
    LIMIT 1;

    IF NEW.source_record_key IS NULL
       AND mapped_collection_id IS NOT NULL
       AND mapped_theme_id = NEW.theme_id
       AND mapped_source_id IS NOT DISTINCT FROM NEW.source_id
    THEN
        -- source_record가 없는 legacy projection도 theme/source/feature active
        -- uniqueness 아래 같은 논리 membership이다. UUID fallback을 새로 만들지
        -- 않고 durable item의 external identity를 재사용한다.
        target_external_item_id := mapped_external_item_id;
    END IF;

    IF mapped_collection_id IS NOT NULL
       AND mapped_theme_id = NEW.theme_id
       AND mapped_source_id IS NOT DISTINCT FROM NEW.source_id
       AND (mapped_title = target_title OR mapped_archived)
    THEN
        UPDATE feature.curation_collections AS collection
        SET title = CASE
                WHEN collection.updated_by IS NULL
                 AND mapped_title = target_title
                THEN target_title
                ELSE collection.title
            END,
            description = CASE
                WHEN collection.updated_by IS NULL
                 AND mapped_title = target_title
                THEN NEW.display_summary
                ELSE collection.description
            END,
            status = CASE
                WHEN collection.updated_by IS NULL
                 AND mapped_title = target_title
                THEN 'published'
                ELSE collection.status
            END,
            visibility = CASE
                WHEN collection.updated_by IS NOT NULL
                  OR mapped_title <> target_title
                THEN collection.visibility
                WHEN theme.visibility = 'public' THEN 'public'
                ELSE 'admin_only'
            END,
            updated_at = CASE
                WHEN collection.updated_by IS NULL
                 AND mapped_title = target_title
                THEN NEW.updated_at
                ELSE collection.updated_at
            END,
            archived_at = CASE
                WHEN collection.updated_by IS NULL
                 AND mapped_title = target_title
                THEN NULL
                ELSE collection.archived_at
            END
        FROM feature.curated_themes AS theme
        WHERE collection.collection_id = mapped_collection_id
          AND collection.theme_id = NEW.theme_id
          AND collection.source_id IS NOT DISTINCT FROM NEW.source_id
          AND theme.theme_id = NEW.theme_id
        RETURNING collection.collection_id INTO target_collection_id;
    ELSE
        -- migration이 보존한 base/split key 형태와 무관하게 semantic group의
        -- canonical collection을 먼저 찾는다. Admin이 base key를 선점했거나
        -- 과거 duplicate가 split key로 남아도 신규 projection이 별도 published
        -- collection을 만들어 collection-level tombstone을 우회하지 않는다.
        SELECT collection.collection_id
        INTO target_collection_id
        FROM feature.curation_collections AS collection
        WHERE collection.theme_id = NEW.theme_id
          AND collection.source_id IS NOT DISTINCT FROM NEW.source_id
          AND collection.title = target_title
          AND collection.metadata @>
              '{"migrated_from": "feature.curated_features"}'::jsonb
        ORDER BY
            EXISTS (
                SELECT 1
                FROM feature.curation_items AS grouped_item
                WHERE grouped_item.collection_id =
                      collection.collection_id
            ) DESC,
            collection.updated_at DESC,
            collection.collection_id
        LIMIT 1
        FOR UPDATE OF collection;

        IF target_collection_id IS NOT NULL THEN
            UPDATE feature.curation_collections AS collection
            SET description = CASE
                    WHEN collection.updated_by IS NULL
                    THEN NEW.display_summary
                    ELSE collection.description
                END,
                status = CASE
                    WHEN collection.updated_by IS NULL
                    THEN 'published'
                    ELSE collection.status
                END,
                visibility = CASE
                    WHEN collection.updated_by IS NULL
                     AND theme.visibility = 'public'
                    THEN 'public'
                    WHEN collection.updated_by IS NULL
                    THEN 'admin_only'
                    ELSE collection.visibility
                END,
                updated_at = CASE
                    WHEN collection.updated_by IS NULL
                    THEN NEW.updated_at
                    ELSE collection.updated_at
                END,
                archived_at = CASE
                    WHEN collection.updated_by IS NULL
                    THEN NULL
                    ELSE collection.archived_at
                END
            FROM feature.curated_themes AS theme
            WHERE collection.collection_id = target_collection_id
              AND theme.theme_id = NEW.theme_id;
        ELSE
            LOOP
            INSERT INTO feature.curation_collections (
                collection_key, theme_id, source_id, title, edition_key,
                description, status, visibility, metadata,
                created_at, updated_at, archived_at
            )
            SELECT
                target_collection_key,
                NEW.theme_id,
                NEW.source_id,
                target_title,
                '',
                NEW.display_summary,
                'published',
                CASE
                    WHEN t.visibility = 'public' THEN 'public'
                    ELSE 'admin_only'
                END,
                jsonb_build_object('migrated_from', 'feature.curated_features'),
                NEW.created_at,
                NEW.updated_at,
                NULL
            FROM feature.curated_themes AS t
            WHERE t.theme_id = NEW.theme_id
            ON CONFLICT (collection_key) DO UPDATE SET
                title = CASE
                    WHEN feature.curation_collections.updated_by IS NULL
                    THEN EXCLUDED.title
                    ELSE feature.curation_collections.title
                END,
                description = CASE
                    WHEN feature.curation_collections.updated_by IS NULL
                    THEN EXCLUDED.description
                    ELSE feature.curation_collections.description
                END,
                status = CASE
                    WHEN feature.curation_collections.updated_by IS NULL
                    THEN 'published'
                    ELSE feature.curation_collections.status
                END,
                visibility = CASE
                    WHEN feature.curation_collections.updated_by IS NULL
                    THEN EXCLUDED.visibility
                    ELSE feature.curation_collections.visibility
                END,
                updated_at = CASE
                    WHEN feature.curation_collections.updated_by IS NULL
                    THEN EXCLUDED.updated_at
                    ELSE feature.curation_collections.updated_at
                END,
                archived_at = CASE
                    WHEN feature.curation_collections.updated_by IS NULL
                    THEN NULL
                    ELSE feature.curation_collections.archived_at
                END
            WHERE feature.curation_collections.theme_id = EXCLUDED.theme_id
              AND feature.curation_collections.source_id
                  IS NOT DISTINCT FROM EXCLUDED.source_id
              AND feature.curation_collections.metadata @>
                  '{"migrated_from": "feature.curated_features"}'::jsonb
            RETURNING collection_id INTO target_collection_id;

            EXIT WHEN target_collection_id IS NOT NULL;

            -- collection_key는 admin이 임의 지정할 수 있다. 충돌 행을 덮지 않고
            -- 같은 semantic group의 모든 projection이 공유하는 다음 free
            -- legacy suffix를 찾는다. Projection UUID를 suffix로 쓰면 같은 title의
            -- row마다 collection이 분절된다.
            target_key_conflict_ordinal := target_key_conflict_ordinal + 1;
            target_collection_key :=
                target_collection_base_key || ':split:legacy' || CASE
                    WHEN target_key_conflict_ordinal = 1 THEN ''
                    ELSE ':conflict:' ||
                         (target_key_conflict_ordinal - 1)::text
                END;
            END LOOP;
        END IF;
    END IF;

    IF target_collection_id IS NULL THEN
        RAISE EXCEPTION
            'legacy collection identity conflict for theme %, source %',
            NEW.theme_id,
            NEW.source_id
            USING ERRCODE = '23505';
    END IF;

    -- UUID mirror와 stable identity target을 먼저 하나씩 잠근 뒤 갱신 대상을
    -- 단일화한다. 두 identity가 서로 다른 row를 가리키면 target owner를
    -- 덮지 않고 기존 mirror만 source-absent로 내린 뒤 legacy projection을
    -- 영구 detach한다.
    SELECT item.curation_item_id
    INTO direct_item_id
    FROM feature.curation_items AS item
    JOIN feature.curation_collections AS collection
      ON collection.collection_id = item.collection_id
    WHERE (
            item.legacy_projection_id = NEW.curated_feature_id
            OR (
                item.legacy_projection_id IS NULL
                AND item.curation_item_id = NEW.curated_feature_id
            )
        )
       OR (
            collection.theme_id = NEW.theme_id
            AND collection.source_id IS NOT DISTINCT FROM NEW.source_id
            AND collection.metadata @>
                '{"migrated_from": "feature.curated_features"}'::jsonb
            AND item.source_record_key
                IS NOT DISTINCT FROM NEW.source_record_key
            AND item.feature_id IS NOT DISTINCT FROM NEW.feature_id
        )
    ORDER BY
        (item.legacy_projection_id = NEW.curated_feature_id) DESC NULLS LAST,
        (item.archived_at IS NOT NULL) DESC,
        item.operator_updated_at DESC NULLS LAST,
        item.source_updated_at DESC,
        item.curation_item_id DESC
    LIMIT 1
    FOR UPDATE OF item;

    SELECT item.curation_item_id, item.legacy_projection_id
    INTO target_identity_item_id, target_projection_id
    FROM feature.curation_items AS item
    WHERE item.collection_id = target_collection_id
      AND item.external_item_id = target_external_item_id
      AND item.feature_id IS NOT DISTINCT FROM NEW.feature_id
    FOR UPDATE;

    IF (
           direct_item_id IS NOT NULL
           AND target_identity_item_id IS NOT NULL
           AND direct_item_id <> target_identity_item_id
       )
       OR (
           target_projection_id IS NOT NULL
           AND target_projection_id <> NEW.curated_feature_id
       )
    THEN
        UPDATE feature.curation_items
        SET source_present = false,
            source_updated_at = CASE
                WHEN source_present THEN clock_timestamp()
                ELSE source_updated_at
            END,
            legacy_projection_id = NULL,
            updated_by = COALESCE(NEW.rejected_by, NEW.selected_by),
            updated_at = NEW.updated_at
        WHERE curation_item_id = direct_item_id;

        UPDATE feature.curated_features
        SET curation_status = 'archived',
            metadata = metadata || jsonb_build_object(
                    'merge_projection_detached',
                    true
                ),
            archived_at = COALESCE(archived_at, clock_timestamp()),
            updated_at = clock_timestamp()
        WHERE curated_feature_id = NEW.curated_feature_id;
        RETURN NEW;
    END IF;

    target_item_id := COALESCE(direct_item_id, target_identity_item_id);

    UPDATE feature.curation_items AS item
    SET legacy_projection_id = NEW.curated_feature_id
    WHERE item.curation_item_id = target_item_id
      AND (
          item.legacy_projection_id IS NULL
          OR item.legacy_projection_id = NEW.curated_feature_id
      );

    -- collection owner 복구는 operator tombstone에도 적용한다. Provider 파생값은
    -- 아래 active-row UPDATE에서 보존하지만, archived item을 탈취된 public
    -- collection에 남겨 두면 stable identity 조회와 비공개 보장이 모두 깨진다.
    UPDATE feature.curation_items AS item
    SET collection_id = target_collection_id
    WHERE item.curation_item_id = target_item_id
      AND item.collection_id <> target_collection_id;

    -- Legacy writer가 제공자 파생 필드를 갱신해도 operator-owned 상태는 보존한다.
    -- UUID/stable identity 경로는 같은 projection UPDATE를 공유하며 archived
    -- tombstone은 WHERE에서 제외해 계속 우선한다.
    UPDATE feature.curation_items AS item
    SET feature_id = CASE
            WHEN source_change THEN NEW.feature_id
            ELSE item.feature_id
        END,
        source_record_key = CASE
            WHEN source_change THEN NEW.source_record_key
            ELSE item.source_record_key
        END,
        external_item_id = CASE
            WHEN source_change THEN target_external_item_id
            ELSE item.external_item_id
        END,
        place_name = CASE
            WHEN source_change THEN feature_row.name
            ELSE item.place_name
        END,
        address_hint = CASE
            WHEN source_change THEN COALESCE(
                feature_row.address ->> 'road',
                feature_row.address ->> 'legal'
            )
            ELSE item.address_hint
        END,
        source_present = CASE
            WHEN source_change OR source_presence_change
            THEN NEW.archived_at IS NULL
            ELSE item.source_present
        END,
        source_updated_at = CASE
            WHEN source_change OR source_presence_change THEN clock_timestamp()
            ELSE item.source_updated_at
        END,
        sort_order = CASE
            WHEN source_change THEN GREATEST(0, round(NEW.rank_score)::integer)
            ELSE item.sort_order
        END,
        item_summary = CASE
            WHEN source_change THEN NEW.display_summary
            ELSE item.item_summary
        END,
        status = CASE
            WHEN operator_change THEN CASE NEW.curation_status
                WHEN 'curated' THEN 'included'
                ELSE NEW.curation_status
            END
            ELSE item.status
        END,
        curation_relation = CASE
            WHEN operator_change THEN NEW.curation_relation
            ELSE item.curation_relation
        END,
        reuse_policy = CASE
            WHEN operator_change THEN NEW.reuse_policy
            ELSE item.reuse_policy
        END,
        metadata = CASE
            WHEN source_change THEN NEW.metadata || jsonb_build_object(
                'legacy_selection_origin', NEW.selection_origin,
                'legacy_content_version', NEW.content_version
            )
            ELSE item.metadata
        END,
        updated_by = COALESCE(NEW.rejected_by, NEW.selected_by),
        updated_at = NEW.updated_at,
        operator_updated_by = CASE
            WHEN operator_change
            THEN COALESCE(
                NEW.operator_updated_by,
                item.operator_updated_by
            )
            ELSE item.operator_updated_by
        END,
        operator_updated_at = CASE
            WHEN operator_change
            THEN NEW.operator_updated_at
            ELSE item.operator_updated_at
        END,
        archived_at = CASE
            WHEN operator_change THEN NEW.archived_at
            ELSE item.archived_at
        END,
        legacy_projection_id = NEW.curated_feature_id
    FROM feature.features AS feature_row
    WHERE item.curation_item_id = target_item_id
      AND item.archived_at IS NULL
      AND feature_row.feature_id = NEW.feature_id;

    item_matched := FOUND;

    -- stable identity가 기존 operator state/tombstone을 보존했다면 새 legacy
    -- UUID의 공개 projection도 같은 상태로 교정한다. depth 1에서만 역동기화하고
    -- 실제 값이 다를 때만 UPDATE해 trigger 재진입을 한 번으로 제한한다.
    IF pg_trigger_depth() = 1 THEN
        UPDATE feature.curated_features AS legacy
        SET curation_status = CASE item.status
                WHEN 'included' THEN 'curated'
                ELSE item.status
            END,
            selection_origin = CASE
                WHEN item.operator_updated_at IS NOT NULL THEN 'admin'
                ELSE legacy.selection_origin
            END,
            selected_by = CASE
                WHEN item.status = 'included' THEN item.operator_updated_by
                ELSE legacy.selected_by
            END,
            selected_at = CASE
                WHEN item.status = 'included' THEN item.operator_updated_at
                ELSE legacy.selected_at
            END,
            rejected_by = CASE
                WHEN item.status = 'rejected' THEN item.operator_updated_by
                ELSE legacy.rejected_by
            END,
            rejected_at = CASE
                WHEN item.status = 'rejected' THEN item.operator_updated_at
                ELSE legacy.rejected_at
            END,
            curation_relation = item.curation_relation,
            reuse_policy = item.reuse_policy,
            operator_updated_by = item.operator_updated_by,
            operator_updated_at = item.operator_updated_at,
            archived_at = item.archived_at,
            content_version = legacy.content_version + 1,
            updated_at = clock_timestamp()
        FROM feature.curation_items AS item
        WHERE legacy.curated_feature_id = NEW.curated_feature_id
          AND item.legacy_projection_id = NEW.curated_feature_id
          AND (
              legacy.curation_status,
              legacy.curation_relation,
              legacy.reuse_policy,
              legacy.operator_updated_by,
              legacy.operator_updated_at,
              legacy.archived_at
          ) IS DISTINCT FROM (
              CASE item.status
                  WHEN 'included' THEN 'curated'
                  ELSE item.status
              END,
              item.curation_relation,
              item.reuse_policy,
              item.operator_updated_by,
              item.operator_updated_at,
              item.archived_at
          );
    END IF;

    IF item_matched OR EXISTS (
        SELECT 1
        FROM feature.curation_items
        WHERE collection_id = target_collection_id
          AND external_item_id = target_external_item_id
          AND feature_id IS NOT DISTINCT FROM NEW.feature_id
    ) THEN
        RETURN NEW;
    END IF;

    UPDATE feature.curation_items AS item
    SET source_present = false,
        source_updated_at = CASE
            WHEN source_change OR source_presence_change THEN clock_timestamp()
            ELSE item.source_updated_at
        END,
        legacy_projection_id = NULL,
        updated_by = COALESCE(NEW.rejected_by, NEW.selected_by),
        updated_at = NEW.updated_at
    WHERE (
            item.legacy_projection_id = NEW.curated_feature_id
            OR (
                item.legacy_projection_id IS NULL
                AND item.curation_item_id = NEW.curated_feature_id
            )
        )
      AND item.archived_at IS NULL
      AND item.source_present;

    IF FOUND OR EXISTS (
        SELECT 1
        FROM feature.curation_items
        WHERE curation_item_id = NEW.curated_feature_id
    ) THEN
        RETURN NEW;
    END IF;

    INSERT INTO feature.curation_items (
        curation_item_id, collection_id, feature_id, source_record_key,
        legacy_projection_id,
        external_item_id, place_name, address_hint, source_present,
        source_updated_at,
        status, sort_order, item_title, item_summary,
        curation_relation, reuse_policy, metadata,
        created_by, updated_by, operator_updated_by, operator_updated_at,
        created_at, updated_at, archived_at
    )
    SELECT
        NEW.curated_feature_id,
        target_collection_id,
        NEW.feature_id,
        NEW.source_record_key,
        NEW.curated_feature_id,
        target_external_item_id,
        feature_row.name,
        COALESCE(feature_row.address ->> 'road', feature_row.address ->> 'legal'),
        NEW.archived_at IS NULL,
        clock_timestamp(),
        CASE NEW.curation_status
            WHEN 'curated' THEN 'included'
            ELSE NEW.curation_status
        END,
        GREATEST(0, round(NEW.rank_score)::integer),
        NULL,
        NEW.display_summary,
        NEW.curation_relation,
        NEW.reuse_policy,
        NEW.metadata || jsonb_build_object(
            'legacy_selection_origin', NEW.selection_origin,
            'legacy_content_version', NEW.content_version
        ),
        COALESCE(NEW.rejected_by, NEW.selected_by),
        COALESCE(NEW.rejected_by, NEW.selected_by),
        CASE
            WHEN operator_change THEN NEW.operator_updated_by
            ELSE NULL
        END,
        CASE
            WHEN operator_change THEN NEW.operator_updated_at
            ELSE NULL
        END,
        NEW.created_at,
        NEW.updated_at,
        NEW.archived_at
    FROM feature.features AS feature_row
    WHERE feature_row.feature_id = NEW.feature_id
      AND NOT EXISTS (
          SELECT 1
          FROM feature.curation_items AS occupied
          WHERE occupied.collection_id = target_collection_id
            AND occupied.external_item_id = target_external_item_id
            AND occupied.feature_id IS NOT DISTINCT FROM NEW.feature_id
      )
    ON CONFLICT DO NOTHING;
    RETURN NEW;
END;
$$;


ALTER FUNCTION feature.sync_curated_feature_collection() OWNER TO ktm_feature_schema_owner;

--
-- Name: sync_subtype_public_ready(); Type: FUNCTION; Schema: feature; Owner: ktm_feature_state_procedure_owner
--

CREATE FUNCTION feature.sync_subtype_public_ready() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog'
    AS $$
DECLARE
    v_public_ready boolean;
BEGIN
    -- The UPDATE which invoked this trigger already holds NEW's parent row
    -- lock.  Keep it until the two subtype cache rows have been refreshed.
    v_public_ready := NEW.lifecycle_state = 'active'
        AND NEW.publication_state = 'published'
        AND NEW.quality_state = 'valid';

    UPDATE feature.feature_routes
       SET public_ready = v_public_ready
     WHERE feature_id = NEW.feature_id
       AND public_ready IS DISTINCT FROM v_public_ready;
    UPDATE feature.feature_areas
       SET public_ready = v_public_ready
     WHERE feature_id = NEW.feature_id
       AND public_ready IS DISTINCT FROM v_public_ready;
    RETURN NULL;
END;
$$;


ALTER FUNCTION feature.sync_subtype_public_ready() OWNER TO ktm_feature_state_procedure_owner;

--
-- Name: transition_admin_feature_state(text, text, text, text, bigint, text, text, text); Type: PROCEDURE; Schema: feature; Owner: ktm_feature_state_procedure_owner
--

CREATE PROCEDURE feature.transition_admin_feature_state(IN p_feature_id text, IN p_lifecycle_state text, IN p_publication_state text, IN p_quality_state text, IN p_expected_row_revision bigint, IN p_reason_code text, IN p_principal text, IN p_action text, OUT o_feature_id text, OUT o_row_revision bigint, OUT o_transition_id bigint)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog'
    AS $$
DECLARE
    v_current feature.features%ROWTYPE;
    v_lifecycle_state text;
    v_publication_state text;
    v_quality_state text;
BEGIN
    IF p_action NOT IN ('patch', 'retire')
       OR p_expected_row_revision IS NULL OR p_expected_row_revision < 1
       OR coalesce(btrim(p_reason_code), '') = ''
       OR coalesce(btrim(p_principal), '') = '' THEN
        RAISE EXCEPTION 'admin state command has invalid arguments'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_admin_state_command';
    END IF;
    SELECT * INTO v_current FROM feature.features
     WHERE feature_id = p_feature_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'feature % does not exist', p_feature_id USING ERRCODE = 'P0002';
    END IF;
    IF v_current.row_revision <> p_expected_row_revision THEN
        RAISE EXCEPTION 'feature % revision changed', p_feature_id USING ERRCODE = '40001';
    END IF;
    IF p_action = 'patch' THEN
        IF p_lifecycle_state IS NOT NULL
           OR (p_publication_state IS NULL AND p_quality_state IS NULL)
           OR (p_publication_state IS NOT NULL
               AND p_publication_state NOT IN ('draft', 'published', 'suppressed'))
           OR (p_quality_state IS NOT NULL
               AND p_quality_state NOT IN ('valid', 'quarantined')) THEN
            RAISE EXCEPTION 'admin state patch may change only publication or quality'
                USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_admin_state_command';
        END IF;
        v_lifecycle_state := v_current.lifecycle_state;
        v_publication_state := coalesce(p_publication_state, v_current.publication_state);
        v_quality_state := coalesce(p_quality_state, v_current.quality_state);
    ELSE
        IF p_lifecycle_state IS NOT NULL
           OR p_publication_state IS NOT NULL
           OR p_quality_state IS NOT NULL THEN
            RAISE EXCEPTION 'retire action derives its complete state tuple'
                USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_admin_state_command';
        END IF;
        v_lifecycle_state := 'retired';
        v_publication_state := 'suppressed';
        v_quality_state := v_current.quality_state;
    END IF;
    CALL feature.transition_feature_state(
        p_feature_id, v_lifecycle_state, v_publication_state, v_quality_state,
        p_expected_row_revision,
        jsonb_build_object(
            'transition_kind', 'admin',
            'reason_code', btrim(p_reason_code),
            'principal', btrim(p_principal)
        ),
        o_feature_id, o_row_revision
    );
    SELECT transition.transition_id INTO o_transition_id
    FROM feature.feature_state_transitions AS transition
    WHERE transition.feature_id = o_feature_id
      AND transition.row_revision = o_row_revision
      AND transition.transition_kind = 'admin'
      AND transition.reason_code = btrim(p_reason_code)
      AND transition.principal = btrim(p_principal)
    ORDER BY transition.transition_id DESC
    LIMIT 1;
    IF o_transition_id IS NULL THEN
        RAISE EXCEPTION 'admin state command did not write its audit transition';
    END IF;
END;
$$;


ALTER PROCEDURE feature.transition_admin_feature_state(IN p_feature_id text, IN p_lifecycle_state text, IN p_publication_state text, IN p_quality_state text, IN p_expected_row_revision bigint, IN p_reason_code text, IN p_principal text, IN p_action text, OUT o_feature_id text, OUT o_row_revision bigint, OUT o_transition_id bigint) OWNER TO ktm_feature_state_procedure_owner;

--
-- Name: transition_feature_state(text, text, text, text, bigint, jsonb); Type: PROCEDURE; Schema: feature; Owner: ktm_feature_state_procedure_owner
--

CREATE PROCEDURE feature.transition_feature_state(IN p_feature_id text, IN p_lifecycle_state text, IN p_publication_state text, IN p_quality_state text, IN p_expected_row_revision bigint, IN p_context jsonb, OUT o_feature_id text, OUT o_row_revision bigint)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog'
    AS $$
DECLARE
    v_current feature.features%ROWTYPE;
    v_override_row_revision bigint;
BEGIN
    IF p_expected_row_revision IS NULL OR p_expected_row_revision < 1 THEN
        RAISE EXCEPTION 'expected feature row revision is required'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_state_expected_revision';
    END IF;
    PERFORM feature.prepare_feature_state_context(p_context, 'transition');
    -- Provider ingestion locks dataset/entity/record/current-head, then the
    -- Feature source link, then the Feature.  Do the same for every provider
    -- transition. A head advance can therefore either happen before this call
    -- (and reject stale evidence) or after this transition/audit commit,
    -- never between proof and audit.
    IF p_context ->> 'transition_kind' = 'provider_sync' THEN
        PERFORM feature.lock_current_provider_feature_source_evidence(
            p_feature_id,
            (p_context ->> 'provider_dataset_id')::bigint,
            p_context ->> 'source_entity_key',
            p_context ->> 'source_record_key'
        );
    END IF;
    SELECT * INTO v_current
      FROM feature.features
     WHERE feature_id = p_feature_id
     FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'feature % does not exist', p_feature_id USING ERRCODE = 'P0002';
    END IF;
    IF v_current.row_revision <> p_expected_row_revision THEN
        RAISE EXCEPTION 'feature % revision changed', p_feature_id USING ERRCODE = '40001';
    END IF;
    IF (v_current.lifecycle_state, v_current.publication_state, v_current.quality_state)
       IS NOT DISTINCT FROM (p_lifecycle_state, p_publication_state, p_quality_state) THEN
        RAISE EXCEPTION 'feature state transition must change at least one axis'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_state_transition_non_noop';
    END IF;
    IF v_current.lifecycle_state = 'retired' AND p_lifecycle_state = 'active' THEN
        IF p_context ->> 'transition_kind' <> 'provider_sync'
           AND (p_context ->> 'transition_kind' NOT IN ('admin', 'user_request', 'system')
           OR coalesce(btrim(p_context ->> 'reactivation_evidence'), '') = '') THEN
            RAISE EXCEPTION 'retired feature may be reactivated only by explicit reingest'
                USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_reactivation_explicit';
        END IF;
        IF EXISTS (
            SELECT 1 FROM ops.feature_overrides AS override
            WHERE override.feature_id = p_feature_id
              AND override.field_path = 'lifecycle_state'
              AND override.status = 'active'
              AND override.override_value = '"retired"'::jsonb
              AND override.prevent_provider_reactivation
        ) AND p_context ->> 'transition_kind' = 'provider_sync' THEN
            RAISE EXCEPTION 'provider reactivation is fenced by lifecycle override'
                USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_provider_reactivation_override';
        END IF;
    END IF;
    UPDATE feature.features
       SET lifecycle_state = p_lifecycle_state,
           publication_state = p_publication_state,
           quality_state = p_quality_state,
           updated_at = clock_timestamp()
     WHERE feature_id = p_feature_id
     RETURNING feature_id, row_revision INTO o_feature_id, o_row_revision;
    -- Any non-provider retirement is not a provider tombstone. Make its
    -- lifecycle override inseparable from the state transition so callers of
    -- this generic internal procedure cannot create a retired row that a
    -- later provider observation can resurrect.
    IF v_current.lifecycle_state = 'active'
       AND p_lifecycle_state = 'retired'
       AND (p_context ->> 'transition_kind') <> 'provider_sync' THEN
        CALL feature.author_lifecycle_override(
            p_feature_id,
            v_current.lifecycle_state,
            'retired',
            true,
            btrim(p_context ->> 'reason_code'),
            btrim(p_context ->> 'principal'),
            o_row_revision,
            v_override_row_revision
        );
        IF v_override_row_revision <> o_row_revision THEN
            RAISE EXCEPTION 'non-provider retirement wrote an inconsistent lifecycle override';
        END IF;
    END IF;
END;
$$;


ALTER PROCEDURE feature.transition_feature_state(IN p_feature_id text, IN p_lifecycle_state text, IN p_publication_state text, IN p_quality_state text, IN p_expected_row_revision bigint, IN p_context jsonb, OUT o_feature_id text, OUT o_row_revision bigint) OWNER TO ktm_feature_state_procedure_owner;

--
-- Name: uuid_generate_v7(); Type: FUNCTION; Schema: feature; Owner: ktm_feature_schema_owner
--

CREATE FUNCTION feature.uuid_generate_v7() RETURNS uuid
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog'
    AS $$
DECLARE
    raw bytea;
BEGIN
    -- 난수 16바이트의 상위 6바이트를 unix-ms(빅엔디안 하위 6바이트)로 교체.
    raw := overlay(
        uuid_send(x_extension.gen_random_uuid())
        PLACING substring(
            int8send((extract(epoch FROM clock_timestamp()) * 1000)::bigint)
            FROM 3 FOR 6
        )
        FROM 1 FOR 6
    );
    -- version 7: byte 6 상위 nibble = 0111 (0x70).
    raw := set_byte(raw, 6, (get_byte(raw, 6) & 15) | 112);
    -- variant RFC: byte 8 상위 2비트 = 10.
    raw := set_byte(raw, 8, (get_byte(raw, 8) & 63) | 128);
    RETURN encode(raw, 'hex')::uuid;
END;
$$;


ALTER FUNCTION feature.uuid_generate_v7() OWNER TO ktm_feature_schema_owner;

--
-- Name: validate_feature_base_field_value(); Type: FUNCTION; Schema: feature; Owner: ktm_feature_state_procedure_owner
--

CREATE FUNCTION feature.validate_feature_base_field_value() RETURNS trigger
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
     WHERE feature_id = NEW.feature_id
       AND feature_uuid = NEW.feature_uuid;
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


ALTER FUNCTION feature.validate_feature_base_field_value() OWNER TO ktm_feature_state_procedure_owner;

--
-- Name: validate_feature_override_value(); Type: FUNCTION; Schema: feature; Owner: ktm_feature_state_procedure_owner
--

CREATE FUNCTION feature.validate_feature_override_value() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog'
    AS $$
DECLARE
    v_registry ops.feature_override_field_paths%ROWTYPE;
    v_feature_kind text;
BEGIN
    -- Lifecycle is owned by the ADR-090 state procedures.  It deliberately
    -- remains outside the generic field path registry and materializer.
    IF NEW.field_path IN ('lifecycle_state', 'status') THEN
        RETURN NEW;
    END IF;
    SELECT * INTO v_registry
      FROM ops.feature_override_field_paths
     WHERE field_path = NEW.field_path;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'unknown feature override field path %', NEW.field_path
            USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_override_field_path';
    END IF;
    SELECT kind INTO v_feature_kind
      FROM feature.features
     WHERE feature_id = NEW.feature_id;
    IF NOT FOUND OR (v_registry.feature_kind <> '*' AND v_registry.feature_kind <> v_feature_kind) THEN
        RAISE EXCEPTION 'override field path % does not apply to Feature', NEW.field_path
            USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_override_field_target';
    END IF;
    IF v_registry.value_kind = 'geometry' THEN
        IF NOT (
            (NEW.override_value = 'null'::jsonb AND v_registry.allows_null
             AND NEW.value_geometry IS NULL)
            OR (
                NEW.override_value IS NULL AND NEW.value_geometry IS NOT NULL
                AND x_extension.st_srid(NEW.value_geometry) = 4326
                AND upper(x_extension.st_geometrytype(NEW.value_geometry))
                    = 'ST_' || v_registry.geometry_type
            )
        ) THEN
            RAISE EXCEPTION 'override geometry does not match registry type'
                USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_override_value';
        END IF;
    ELSIF NEW.value_geometry IS NOT NULL
       OR NEW.override_value IS NULL
       OR (NOT v_registry.allows_null AND NEW.override_value = 'null'::jsonb)
       OR (NEW.override_value <> 'null'::jsonb AND (
              (v_registry.value_kind = 'text' AND jsonb_typeof(NEW.override_value) <> 'string')
           OR (v_registry.value_kind = 'uuid' AND jsonb_typeof(NEW.override_value) <> 'string')
           OR (v_registry.value_kind = 'date' AND jsonb_typeof(NEW.override_value) <> 'string')
           OR (v_registry.value_kind = 'timestamptz' AND jsonb_typeof(NEW.override_value) <> 'string')
           OR (v_registry.value_kind = 'integer' AND jsonb_typeof(NEW.override_value) <> 'number')
           OR (v_registry.value_kind = 'numeric' AND jsonb_typeof(NEW.override_value) <> 'number')
           OR (v_registry.value_kind = 'boolean' AND jsonb_typeof(NEW.override_value) <> 'boolean')
           OR (v_registry.value_kind = 'json_object' AND jsonb_typeof(NEW.override_value) <> 'object')
           OR (v_registry.value_kind IN ('json_array', 'text_array') AND jsonb_typeof(NEW.override_value) <> 'array')
       )) THEN
        RAISE EXCEPTION 'override JSON value does not match registry type'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_override_value';
    END IF;
    IF v_registry.value_kind = 'text_array' AND NEW.override_value <> 'null'::jsonb AND EXISTS (
        SELECT 1 FROM jsonb_array_elements(NEW.override_value) AS element
        WHERE jsonb_typeof(element) <> 'string'
    ) THEN
        RAISE EXCEPTION 'override text array contains a non-string value'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_override_value';
    END IF;
    IF NOT v_registry.operator_writable AND NEW.status = 'active' THEN
        RAISE EXCEPTION 'field path % cannot be overridden by an operator', NEW.field_path
            USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_override_operator_policy';
    END IF;
    RETURN NEW;
END;
$$;


ALTER FUNCTION feature.validate_feature_override_value() OWNER TO ktm_feature_state_procedure_owner;

--
-- Name: write_feature_state_transition(); Type: FUNCTION; Schema: feature; Owner: ktm_feature_audit_writer
--

CREATE FUNCTION feature.write_feature_state_transition() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog'
    AS $$
DECLARE
    v_context_text text;
    v_context jsonb;
    v_state_definer text;
BEGIN
    IF TG_OP = 'UPDATE'
       AND OLD.lifecycle_state IS NOT DISTINCT FROM NEW.lifecycle_state
       AND OLD.publication_state IS NOT DISTINCT FROM NEW.publication_state
       AND OLD.quality_state IS NOT DISTINCT FROM NEW.quality_state THEN
        RETURN NULL;
    END IF;

    v_context_text := current_setting('feature.state_transition_context', true);
    v_state_definer := current_setting('feature.state_procedure_definer', true);
    IF v_context_text IS NULL
       OR v_state_definer <> 'ktm_feature_state_procedure_owner'
       OR current_user <> 'ktm_feature_audit_writer' THEN
        -- schema/migration owner는 runtime trust boundary 밖이다. existing DDL
        -- migration과 fixture seeding은 이 privileged identity로만 direct write를
        -- 수행할 수 있고, application runtime login은 아래 privilege fence에서
        -- 이 분기에 도달하기 전에 거부된다.
        IF EXISTS (
            SELECT 1
            FROM pg_catalog.pg_roles AS role_row
            WHERE role_row.rolname = session_user
              AND role_row.rolsuper
        ) THEN
            RETURN NULL;
        END IF;
        RAISE EXCEPTION 'feature state mutation requires the state procedure context'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_state_transition_context';
    END IF;
    v_context := v_context_text::jsonb;
    IF jsonb_typeof(v_context) IS DISTINCT FROM 'object'
       OR (v_context ->> 'transition_kind') NOT IN (
            'initial', 'legacy_backfill', 'provider_sync', 'admin', 'user_request',
            'merge', 'quality_validation', 'system'
       )
       OR coalesce(btrim(v_context ->> 'reason_code'), '') = ''
       OR coalesce(btrim(v_context ->> 'principal'), '') = '' THEN
        RAISE EXCEPTION 'feature state mutation has malformed context'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_state_transition_context';
    END IF;

    IF TG_OP = 'INSERT' AND (v_context ->> 'transition_kind') NOT IN (
        'initial', 'legacy_backfill', 'provider_sync'
    ) THEN
        RAISE EXCEPTION 'feature insert needs initial or provider-sync state transition kind'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_state_transition_kind';
    END IF;
    IF TG_OP = 'UPDATE' AND (v_context ->> 'transition_kind') IN ('initial', 'legacy_backfill') THEN
        RAISE EXCEPTION 'feature update cannot use initial state transition kind'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_state_transition_kind';
    END IF;

    INSERT INTO feature.feature_state_transitions (
        feature_id, feature_uuid,
        from_lifecycle_state, from_publication_state, from_quality_state,
        to_lifecycle_state, to_publication_state, to_quality_state,
        transition_kind, reason_code, principal, causation_ref,
        provider_dataset_id, source_entity_key, source_record_key, provider_evidence,
        occurred_at,
        row_revision, invoker_role, state_procedure_definer, audit_writer_definer
    ) VALUES (
        NEW.feature_id, NEW.feature_uuid,
        CASE WHEN TG_OP = 'INSERT' THEN NULL ELSE OLD.lifecycle_state END,
        CASE WHEN TG_OP = 'INSERT' THEN NULL ELSE OLD.publication_state END,
        CASE WHEN TG_OP = 'INSERT' THEN NULL ELSE OLD.quality_state END,
        NEW.lifecycle_state, NEW.publication_state, NEW.quality_state,
        v_context ->> 'transition_kind', v_context ->> 'reason_code',
        v_context ->> 'principal', v_context ->> 'causation_ref',
        CASE WHEN v_context ->> 'transition_kind' = 'provider_sync'
             THEN (v_context ->> 'provider_dataset_id')::bigint END,
        CASE WHEN v_context ->> 'transition_kind' = 'provider_sync'
             THEN v_context ->> 'source_entity_key' END,
        CASE WHEN v_context ->> 'transition_kind' = 'provider_sync'
             THEN v_context ->> 'source_record_key' END,
        CASE WHEN v_context ->> 'transition_kind' = 'provider_sync'
             THEN v_context -> 'provider_evidence' END,
        clock_timestamp(),
        NEW.row_revision, session_user::text, v_state_definer, current_user::text
    );
    RETURN NULL;
END;
$$;


ALTER FUNCTION feature.write_feature_state_transition() OWNER TO ktm_feature_audit_writer;

--
-- Name: assert_feature_update_job_pair(uuid); Type: FUNCTION; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE FUNCTION ops.assert_feature_update_job_pair(candidate_job_id uuid) RETURNS void
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog'
    AS $$
        DECLARE job_kind text; job_quarantined_at timestamptz;
        BEGIN
            SELECT job.kind, job.quarantined_at
              INTO job_kind, job_quarantined_at
            FROM ops.import_jobs AS job
            WHERE job.job_id = candidate_job_id;
            IF NOT FOUND
               OR job_kind IS DISTINCT FROM 'feature_update_request'
               OR job_quarantined_at IS NOT NULL THEN
                RETURN;
            END IF;

            PERFORM 1
            FROM ops.feature_update_requests AS request
            WHERE request.job_id = candidate_job_id;
            IF NOT FOUND THEN
                RAISE EXCEPTION
                    'non-quarantined canonical feature update job must have exactly one request: %',
                    candidate_job_id
                    USING ERRCODE = '23514',
                        CONSTRAINT = 'ck_import_jobs_feature_update_pair';
            END IF;
        END;
        $$;


ALTER FUNCTION ops.assert_feature_update_job_pair(candidate_job_id uuid) OWNER TO ktm_feature_schema_owner;

--
-- Name: assign_cache_target_outbox_relay_order(); Type: FUNCTION; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE FUNCTION ops.assign_cache_target_outbox_relay_order() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog', 'ops'
    AS $$
        BEGIN
          PERFORM 1
          FROM ops.poi_cache_target_streams AS stream
          WHERE stream.external_system = NEW.external_system
          FOR UPDATE OF stream;
          IF NOT FOUND THEN
            RAISE EXCEPTION 'cache target stream does not exist'
              USING ERRCODE = '23503';
          END IF;
          NEW.relay_order := nextval(
            'ops.poi_cache_target_outbox_relay_order_seq'::regclass
          );
          RETURN NEW;
        END;
        $$;


ALTER FUNCTION ops.assign_cache_target_outbox_relay_order() OWNER TO ktm_feature_schema_owner;

--
-- Name: bump_import_job_event_clock(); Type: FUNCTION; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE FUNCTION ops.bump_import_job_event_clock() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        BEGIN
          INSERT INTO ops.import_job_event_clock AS clock (
            clock_id, revision, updated_at
          ) VALUES (
            TRUE, 1, clock_timestamp()
          )
          ON CONFLICT (clock_id) DO UPDATE
             SET revision = clock.revision + 1,
                 updated_at = clock_timestamp();
          RETURN NULL;
        END;
        $$;


ALTER FUNCTION ops.bump_import_job_event_clock() OWNER TO ktm_feature_schema_owner;

--
-- Name: bump_ops_live_topic_revision(); Type: FUNCTION; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE FUNCTION ops.bump_ops_live_topic_revision() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        BEGIN
          IF TG_NARGS <> 1 OR btrim(TG_ARGV[0]) = '' THEN
            RAISE EXCEPTION 'ops live revision trigger requires one topic argument';
          END IF;
          INSERT INTO ops.ops_live_topic_revisions AS live_revision (
            topic,
            revision,
            updated_at
          )
          VALUES (TG_ARGV[0], 1, clock_timestamp())
          ON CONFLICT (topic) DO UPDATE
          SET revision = live_revision.revision + 1,
              updated_at = clock_timestamp();
          RETURN NULL;
        END;
        $$;


ALTER FUNCTION ops.bump_ops_live_topic_revision() OWNER TO ktm_feature_schema_owner;

--
-- Name: check_feature_operation_parent(); Type: FUNCTION; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE FUNCTION ops.check_feature_operation_parent() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        DECLARE
          parent_kind TEXT;
          parent_run_id TEXT;
          parent_created_at TIMESTAMPTZ;
        BEGIN
          SELECT kind, dagster_run_id, created_at
            INTO parent_kind, parent_run_id, parent_created_at
            FROM ops.import_jobs
           WHERE job_id = NEW.parent_job_id
           FOR KEY SHARE;
          IF NOT FOUND OR parent_kind <> 'provider_feature_load_run'
             OR parent_run_id IS DISTINCT FROM NEW.dagster_run_id
             OR parent_created_at IS DISTINCT FROM NEW.created_at THEN
            RAISE EXCEPTION
              'invalid provider feature operation parent/run/create time'
              USING ERRCODE = '23514';
          END IF;
          RETURN NULL;
        END;
        $$;


ALTER FUNCTION ops.check_feature_operation_parent() OWNER TO ktm_feature_schema_owner;

--
-- Name: enforce_backup_command_execution_transition(); Type: FUNCTION; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE FUNCTION ops.enforce_backup_command_execution_transition() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        BEGIN
          IF OLD.phase = 'effect_succeeded'
             OR (OLD.phase, NEW.phase) NOT IN (
               ('prepared', 'effect_started'),
               ('effect_started', 'effect_succeeded')
             ) THEN
            RAISE EXCEPTION 'invalid backup command execution transition'
              USING ERRCODE = '55000';
          END IF;
          IF (OLD.command_id, OLD.effect_kind, OLD.effect_token,
              OLD.backup_id, OLD.app_db,
              OLD.dagster_db, OLD.rustfs_volume, OLD.marker_key,
              OLD.input_digest, OLD.prepared_result, OLD.prepared_at)
             IS DISTINCT FROM
             (NEW.command_id, NEW.effect_kind, NEW.effect_token,
              NEW.backup_id, NEW.app_db,
              NEW.dagster_db, NEW.rustfs_volume, NEW.marker_key,
              NEW.input_digest, NEW.prepared_result, NEW.prepared_at) THEN
            RAISE EXCEPTION 'backup command execution identity is immutable'
              USING ERRCODE = '55000';
          END IF;
          RETURN NEW;
        END;
        $$;


ALTER FUNCTION ops.enforce_backup_command_execution_transition() OWNER TO ktm_feature_schema_owner;

--
-- Name: enforce_feature_update_job_pair(); Type: FUNCTION; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE FUNCTION ops.enforce_feature_update_job_pair() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog'
    AS $$
        BEGIN
            PERFORM ops.assert_feature_update_job_pair(NEW.job_id);
            RETURN NULL;
        END;
        $$;


ALTER FUNCTION ops.enforce_feature_update_job_pair() OWNER TO ktm_feature_schema_owner;

--
-- Name: enforce_feature_update_request_job_identity(); Type: FUNCTION; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE FUNCTION ops.enforce_feature_update_request_job_identity() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog'
    AS $$
        DECLARE linked_kind text; linked_quarantined_at timestamptz;
        BEGIN
            SELECT job.kind, job.quarantined_at
              INTO linked_kind, linked_quarantined_at
            FROM ops.import_jobs AS job
            WHERE job.job_id = NEW.job_id
            FOR KEY SHARE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'feature update request job does not exist: %', NEW.job_id
                    USING ERRCODE = '23503';
            END IF;
            IF linked_kind IS DISTINCT FROM 'feature_update_request' THEN
                RAISE EXCEPTION
                    'feature update request must link a canonical feature_update_request job'
                    USING ERRCODE = '23514',
                        CONSTRAINT = 'ck_feature_update_request_job_kind';
            END IF;
            IF linked_quarantined_at IS NOT NULL THEN
                RAISE EXCEPTION 'feature update request cannot link a quarantined import job'
                    USING ERRCODE = '23514',
                        CONSTRAINT = 'ck_feature_update_request_job_quarantine';
            END IF;
            RETURN NEW;
        END;
        $$;


ALTER FUNCTION ops.enforce_feature_update_request_job_identity() OWNER TO ktm_feature_schema_owner;

--
-- Name: enforce_offline_upload_command_execution_transition(); Type: FUNCTION; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE FUNCTION ops.enforce_offline_upload_command_execution_transition() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        BEGIN
          IF OLD.phase = 'effect_succeeded'
             OR (OLD.phase, NEW.phase) NOT IN (
               ('prepared', 'effect_started'),
               ('effect_started', 'effect_succeeded')
             ) THEN
            RAISE EXCEPTION 'invalid offline upload command execution transition'
              USING ERRCODE = '55000';
          END IF;
          IF (OLD.command_id, OLD.effect_kind, OLD.upload_id,
              OLD.storage_backend, OLD.bucket, OLD.storage_key,
              OLD.content_type, OLD.byte_size, OLD.content_sha256,
              OLD.metadata_digest, OLD.load_job_id, OLD.input_digest,
              OLD.prepared_at)
             IS DISTINCT FROM
             (NEW.command_id, NEW.effect_kind, NEW.upload_id,
              NEW.storage_backend, NEW.bucket, NEW.storage_key,
              NEW.content_type, NEW.byte_size, NEW.content_sha256,
              NEW.metadata_digest, NEW.load_job_id, NEW.input_digest,
              NEW.prepared_at) THEN
            RAISE EXCEPTION 'offline upload command execution identity is immutable'
              USING ERRCODE = '55000';
          END IF;
          RETURN NEW;
        END;
        $$;


ALTER FUNCTION ops.enforce_offline_upload_command_execution_transition() OWNER TO ktm_feature_schema_owner;

--
-- Name: force_poi_cache_target_lock_version(); Type: FUNCTION; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE FUNCTION ops.force_poi_cache_target_lock_version() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog'
    AS $$
        BEGIN
            NEW.lock_version := OLD.lock_version + 1;
            RETURN NEW;
        END;
        $$;


ALTER FUNCTION ops.force_poi_cache_target_lock_version() OWNER TO ktm_feature_schema_owner;

--
-- Name: guard_feature_update_request_mutation(); Type: FUNCTION; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE FUNCTION ops.guard_feature_update_request_mutation() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog'
    AS $$
        DECLARE linked_status text; linked_cancellation_id uuid;
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'feature update request is append-only: %', OLD.request_id
                    USING ERRCODE = '23514',
                        CONSTRAINT = 'ck_feature_update_request_append_only';
            END IF;
            IF NEW.request_id IS DISTINCT FROM OLD.request_id
               OR NEW.job_id IS DISTINCT FROM OLD.job_id
               OR NEW.scope_type IS DISTINCT FROM OLD.scope_type
               OR NEW.scope IS DISTINCT FROM OLD.scope
               OR NEW.dataset_membership_mode
                  IS DISTINCT FROM OLD.dataset_membership_mode
               OR NEW.update_policy IS DISTINCT FROM OLD.update_policy
               OR NEW.run_mode IS DISTINCT FROM OLD.run_mode
               OR NEW.priority IS DISTINCT FROM OLD.priority
               OR NEW.operator IS DISTINCT FROM OLD.operator
               OR NEW.reason IS DISTINCT FROM OLD.reason
               OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
                RAISE EXCEPTION 'feature update request input/audit identity is immutable: %',
                    OLD.request_id
                    USING ERRCODE = '23514',
                        CONSTRAINT = 'ck_feature_update_request_identity_immutable';
            END IF;
            IF NEW.generation IS DISTINCT FROM OLD.generation
               AND NEW.generation <> OLD.generation + 1 THEN
                RAISE EXCEPTION
                    'feature update request generation must increase by exactly one: %',
                    OLD.request_id
                    USING ERRCODE = '23514',
                        CONSTRAINT = 'ck_feature_update_request_generation';
            END IF;
            IF NEW.matched_scope IS DISTINCT FROM OLD.matched_scope
               OR NEW.generation IS DISTINCT FROM OLD.generation THEN
                SELECT job.status, job.cancellation_id
                  INTO linked_status, linked_cancellation_id
                FROM ops.import_jobs AS job
                WHERE job.job_id = OLD.job_id
                FOR UPDATE;
                IF NOT FOUND
                   OR linked_status NOT IN ('queued', 'running')
                   OR linked_cancellation_id IS NOT NULL THEN
                    RAISE EXCEPTION
                        'feature update request mutable fields require active unmarked job: %',
                        OLD.request_id
                        USING ERRCODE = '23514',
                            CONSTRAINT = 'ck_feature_update_request_mutable_fields';
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$;


ALTER FUNCTION ops.guard_feature_update_request_mutation() OWNER TO ktm_feature_schema_owner;

--
-- Name: guard_import_job_event_clock_mutation(); Type: FUNCTION; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE FUNCTION ops.guard_import_job_event_clock_mutation() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        BEGIN
          IF TG_OP IN ('DELETE', 'TRUNCATE') THEN
            RAISE EXCEPTION 'import job event clock singleton cannot be %', TG_OP
              USING ERRCODE = 'check_violation';
          END IF;
          IF pg_trigger_depth() < 2
             OR NEW.clock_id IS DISTINCT FROM OLD.clock_id
             OR NEW.revision IS DISTINCT FROM OLD.revision + 1 THEN
            RAISE EXCEPTION
              'import job event clock is event-trigger-owned: revision % -> %',
              OLD.revision, NEW.revision
              USING ERRCODE = 'check_violation';
          END IF;
          RETURN NEW;
        END;
        $$;


ALTER FUNCTION ops.guard_import_job_event_clock_mutation() OWNER TO ktm_feature_schema_owner;

--
-- Name: is_valid_feature_update_filter_array(text[], integer); Type: FUNCTION; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE FUNCTION ops.is_valid_feature_update_filter_array(p_values text[], p_max_items integer) RETURNS boolean
    LANGUAGE plpgsql IMMUTABLE STRICT PARALLEL SAFE
    AS $$
        DECLARE
          text_value text;
          seen_values text[] := ARRAY[]::text[];
          canonical_whitespace text := ' '
            || chr(9) || chr(10) || chr(11) || chr(12) || chr(13)
            || chr(28) || chr(29) || chr(30) || chr(31) || chr(133)
            || chr(160) || chr(5760) || chr(8192) || chr(8193) || chr(8194)
            || chr(8195) || chr(8196) || chr(8197) || chr(8198) || chr(8199)
            || chr(8200) || chr(8201) || chr(8202) || chr(8232) || chr(8233)
            || chr(8239) || chr(8287) || chr(12288);
        BEGIN
          IF p_max_items < 0
             OR COALESCE(array_ndims(p_values), 1) <> 1
             OR cardinality(p_values) > p_max_items
             OR (
               cardinality(p_values) > 0
               AND array_lower(p_values, 1) IS DISTINCT FROM 1
             ) THEN
            RETURN false;
          END IF;
          FOREACH text_value IN ARRAY p_values
          LOOP
            IF text_value IS NULL
               OR text_value <> btrim(text_value, canonical_whitespace)
               OR text_value = ''
               OR char_length(text_value) > 128 THEN
              RETURN false;
            END IF;
            IF text_value = ANY(seen_values) THEN
              RETURN false;
            END IF;
            seen_values := array_append(seen_values, text_value);
          END LOOP;
          RETURN true;
        END;
        $$;


ALTER FUNCTION ops.is_valid_feature_update_filter_array(p_values text[], p_max_items integer) OWNER TO ktm_feature_schema_owner;

--
-- Name: is_valid_feature_update_policy(jsonb); Type: FUNCTION; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE FUNCTION ops.is_valid_feature_update_policy(p_policy jsonb) RETURNS boolean
    LANGUAGE plpgsql IMMUTABLE STRICT PARALLEL SAFE
    AS $$
        DECLARE
          boolean_key text;
        BEGIN
          IF jsonb_typeof(p_policy) IS DISTINCT FROM 'object'
             OR p_policy - ARRAY[
               'mode',
               'include_inactive',
               'force_provider_call',
               'dedup_after_load',
               'consistency_check_after_load',
               'prevent_provider_reactivation'
             ]::text[] <> '{}'::jsonb THEN
            RETURN false;
          END IF;

          IF p_policy ? 'mode'
             AND (
               jsonb_typeof(p_policy->'mode') IS DISTINCT FROM 'string'
               OR p_policy->>'mode' IS DISTINCT FROM 'refresh_existing'
             ) THEN
            RETURN false;
          END IF;

          FOREACH boolean_key IN ARRAY ARRAY[
            'include_inactive',
            'force_provider_call',
            'dedup_after_load',
            'consistency_check_after_load',
            'prevent_provider_reactivation'
          ]::text[]
          LOOP
            IF p_policy ? boolean_key
               AND jsonb_typeof(p_policy->boolean_key) IS DISTINCT FROM 'boolean' THEN
              RETURN false;
            END IF;
          END LOOP;
          RETURN true;
        END;
        $$;


ALTER FUNCTION ops.is_valid_feature_update_policy(p_policy jsonb) OWNER TO ktm_feature_schema_owner;

--
-- Name: is_valid_feature_update_scope(text, jsonb); Type: FUNCTION; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE FUNCTION ops.is_valid_feature_update_scope(p_scope_type text, p_scope jsonb) RETURNS boolean
    LANGUAGE plpgsql IMMUTABLE STRICT PARALLEL SAFE
    SET search_path TO 'pg_catalog'
    AS $$
        BEGIN
          IF p_scope_type <> 'provider_dataset' THEN
            RETURN ops.is_valid_feature_update_scope_0075(p_scope_type, p_scope);
          END IF;
          IF jsonb_typeof(p_scope) IS DISTINCT FROM 'object'
             OR p_scope->>'type' IS DISTINCT FROM p_scope_type
             OR p_scope - ARRAY[
                  'type', 'provider_dataset_id', 'sync_scope', 'operation_key'
                ]::text[] <> '{}'::jsonb
             OR jsonb_typeof(p_scope->'provider_dataset_id') IS DISTINCT FROM 'number'
             OR jsonb_typeof(p_scope->'sync_scope') IS DISTINCT FROM 'string'
             OR jsonb_typeof(p_scope->'operation_key') IS DISTINCT FROM 'string' THEN
            RETURN false;
          END IF;
          IF (p_scope->>'provider_dataset_id')::numeric <= 0
             OR (p_scope->>'provider_dataset_id')::numeric
                <> trunc((p_scope->>'provider_dataset_id')::numeric)
             OR NOT provider_sync.is_valid_provider_dataset_sync_scope(
                  p_scope->>'sync_scope'
                )
             OR p_scope->>'operation_key' = ''
             OR p_scope->>'operation_key' <> btrim(p_scope->>'operation_key')
             OR char_length(p_scope->>'operation_key') > 128 THEN
            RETURN false;
          END IF;
          RETURN true;
        END;
        $$;


ALTER FUNCTION ops.is_valid_feature_update_scope(p_scope_type text, p_scope jsonb) OWNER TO ktm_feature_schema_owner;

--
-- Name: is_valid_feature_update_scope_0052(text, jsonb); Type: FUNCTION; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE FUNCTION ops.is_valid_feature_update_scope_0052(p_scope_type text, p_scope jsonb) RETURNS boolean
    LANGUAGE plpgsql IMMUTABLE STRICT PARALLEL SAFE
    AS $$
        DECLARE
          item jsonb;
          center_value jsonb;
          text_value text;
          seen_values text[] := ARRAY[]::text[];
          canonical_whitespace text := ' '
            || chr(9) || chr(10) || chr(11) || chr(12) || chr(13)
            || chr(28) || chr(29) || chr(30) || chr(31) || chr(133)
            || chr(160) || chr(5760) || chr(8192) || chr(8193) || chr(8194)
            || chr(8195) || chr(8196) || chr(8197) || chr(8198) || chr(8199)
            || chr(8200) || chr(8201) || chr(8202) || chr(8232) || chr(8233)
            || chr(8239) || chr(8287) || chr(12288);
        BEGIN
          IF jsonb_typeof(p_scope) IS DISTINCT FROM 'object'
             OR jsonb_typeof(p_scope->'type') IS DISTINCT FROM 'string'
             OR p_scope->>'type' IS DISTINCT FROM p_scope_type THEN
            RETURN false;
          END IF;

          CASE p_scope_type
            WHEN 'feature_ids' THEN
              IF p_scope - ARRAY['type', 'feature_ids']::text[] <> '{}'::jsonb
                 OR jsonb_typeof(p_scope->'feature_ids') IS DISTINCT FROM 'array' THEN
                RETURN false;
              END IF;
              IF jsonb_array_length(p_scope->'feature_ids') > 1000 THEN
                RETURN false;
              END IF;
              FOR item IN SELECT value FROM jsonb_array_elements(p_scope->'feature_ids')
              LOOP
                IF jsonb_typeof(item) IS DISTINCT FROM 'string' THEN
                  RETURN false;
                END IF;
                text_value := item #>> '{}';
                IF text_value <> btrim(text_value, canonical_whitespace)
                   OR text_value = ''
                   OR char_length(text_value) > 256 THEN
                  RETURN false;
                END IF;
                IF text_value = ANY(seen_values) THEN
                  RETURN false;
                END IF;
                seen_values := array_append(seen_values, text_value);
              END LOOP;
              RETURN true;

            WHEN 'center_radius' THEN
              IF p_scope - ARRAY['type', 'center', 'radius_km']::text[]
                   <> '{}'::jsonb
                 OR jsonb_typeof(p_scope->'center') IS DISTINCT FROM 'object'
                 OR jsonb_typeof(p_scope->'radius_km') IS DISTINCT FROM 'number' THEN
                RETURN false;
              END IF;
              center_value := p_scope->'center';
              IF center_value - ARRAY['lon', 'lat']::text[] <> '{}'::jsonb
                 OR jsonb_typeof(center_value->'lon') IS DISTINCT FROM 'number'
                 OR jsonb_typeof(center_value->'lat') IS DISTINCT FROM 'number' THEN
                RETURN false;
              END IF;
              RETURN (center_value->>'lon')::numeric BETWEEN -180 AND 180
                 AND (center_value->>'lat')::numeric BETWEEN -90 AND 90
                 AND (p_scope->>'radius_km')::numeric > 0
                 AND (p_scope->>'radius_km')::numeric <= 500;

            WHEN 'sigungu_by_radius' THEN
              IF p_scope - ARRAY['type', 'center', 'radius_km', 'match']::text[]
                   <> '{}'::jsonb
                 OR jsonb_typeof(p_scope->'center') IS DISTINCT FROM 'object'
                 OR jsonb_typeof(p_scope->'radius_km') IS DISTINCT FROM 'number'
                 OR jsonb_typeof(p_scope->'match') IS DISTINCT FROM 'string' THEN
                RETURN false;
              END IF;
              center_value := p_scope->'center';
              IF center_value - ARRAY['lon', 'lat']::text[] <> '{}'::jsonb
                 OR jsonb_typeof(center_value->'lon') IS DISTINCT FROM 'number'
                 OR jsonb_typeof(center_value->'lat') IS DISTINCT FROM 'number' THEN
                RETURN false;
              END IF;
              RETURN (center_value->>'lon')::numeric BETWEEN -180 AND 180
                 AND (center_value->>'lat')::numeric BETWEEN -90 AND 90
                 AND (p_scope->>'radius_km')::numeric > 0
                 AND (p_scope->>'radius_km')::numeric <= 500
                 AND p_scope->>'match' = 'intersects';

            WHEN 'bbox' THEN
              IF p_scope - ARRAY[
                   'type', 'min_lon', 'min_lat', 'max_lon', 'max_lat'
                 ]::text[] <> '{}'::jsonb
                 OR jsonb_typeof(p_scope->'min_lon') IS DISTINCT FROM 'number'
                 OR jsonb_typeof(p_scope->'min_lat') IS DISTINCT FROM 'number'
                 OR jsonb_typeof(p_scope->'max_lon') IS DISTINCT FROM 'number'
                 OR jsonb_typeof(p_scope->'max_lat') IS DISTINCT FROM 'number' THEN
                RETURN false;
              END IF;
              RETURN (p_scope->>'min_lon')::numeric BETWEEN -180 AND 180
                 AND (p_scope->>'max_lon')::numeric BETWEEN -180 AND 180
                 AND (p_scope->>'min_lat')::numeric BETWEEN -90 AND 90
                 AND (p_scope->>'max_lat')::numeric BETWEEN -90 AND 90
                 AND (p_scope->>'min_lon')::numeric <= (p_scope->>'max_lon')::numeric
                 AND (p_scope->>'min_lat')::numeric <= (p_scope->>'max_lat')::numeric;

            WHEN 'provider_dataset' THEN
              IF p_scope - ARRAY[
                   'type', 'provider', 'dataset_key', 'sync_scope'
                 ]::text[] <> '{}'::jsonb
                 OR jsonb_typeof(p_scope->'provider') IS DISTINCT FROM 'string'
                 OR jsonb_typeof(p_scope->'dataset_key') IS DISTINCT FROM 'string' THEN
                RETURN false;
              END IF;
              IF p_scope->>'provider' <>
                   btrim(p_scope->>'provider', canonical_whitespace)
                 OR p_scope->>'provider' = ''
                 OR char_length(p_scope->>'provider') > 128
                 OR p_scope->>'dataset_key' <>
                      btrim(p_scope->>'dataset_key', canonical_whitespace)
                 OR p_scope->>'dataset_key' = ''
                 OR char_length(p_scope->>'dataset_key') > 128 THEN
                RETURN false;
              END IF;
              IF p_scope ? 'sync_scope' THEN
                IF jsonb_typeof(p_scope->'sync_scope') IS DISTINCT FROM 'string'
                   OR p_scope->>'sync_scope' <>
                        btrim(p_scope->>'sync_scope', canonical_whitespace)
                   OR p_scope->>'sync_scope' = ''
                   OR char_length(p_scope->>'sync_scope') > 128 THEN
                  RETURN false;
                END IF;
              END IF;
              RETURN true;

            WHEN 'cache_target_keys' THEN
              IF p_scope - ARRAY[
                   'type', 'external_system', 'target_keys', 'radius_km', 'scope_mode'
                 ]::text[] <> '{}'::jsonb
                 OR jsonb_typeof(p_scope->'external_system') IS DISTINCT FROM 'string'
                 OR jsonb_typeof(p_scope->'target_keys') IS DISTINCT FROM 'array'
                 OR jsonb_typeof(p_scope->'scope_mode') IS DISTINCT FROM 'string' THEN
                RETURN false;
              END IF;
              IF jsonb_array_length(p_scope->'target_keys') > 500 THEN
                RETURN false;
              END IF;
              IF p_scope->>'external_system' <>
                   btrim(p_scope->>'external_system', canonical_whitespace)
                 OR p_scope->>'external_system' = ''
                 OR char_length(p_scope->>'external_system') > 128
                 OR p_scope->>'scope_mode' NOT IN ('center_radius', 'sigungu_by_radius') THEN
                RETURN false;
              END IF;
              IF p_scope ? 'radius_km' THEN
                IF jsonb_typeof(p_scope->'radius_km') IS DISTINCT FROM 'number' THEN
                  RETURN false;
                END IF;
                IF (p_scope->>'radius_km')::numeric <= 0
                   OR (p_scope->>'radius_km')::numeric > 500 THEN
                  RETURN false;
                END IF;
              END IF;
              FOR item IN SELECT value FROM jsonb_array_elements(p_scope->'target_keys')
              LOOP
                IF jsonb_typeof(item) IS DISTINCT FROM 'string' THEN
                  RETURN false;
                END IF;
                text_value := item #>> '{}';
                IF text_value <> btrim(text_value, canonical_whitespace)
                   OR text_value = ''
                   OR char_length(text_value) > 256 THEN
                  RETURN false;
                END IF;
                IF text_value = ANY(seen_values) THEN
                  RETURN false;
                END IF;
                seen_values := array_append(seen_values, text_value);
              END LOOP;
              RETURN true;
            ELSE
              RETURN false;
          END CASE;
        END;
        $$;


ALTER FUNCTION ops.is_valid_feature_update_scope_0052(p_scope_type text, p_scope jsonb) OWNER TO ktm_feature_schema_owner;

--
-- Name: is_valid_feature_update_scope_0074(text, jsonb); Type: FUNCTION; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE FUNCTION ops.is_valid_feature_update_scope_0074(p_scope_type text, p_scope jsonb) RETURNS boolean
    LANGUAGE sql IMMUTABLE PARALLEL SAFE
    AS $$
          SELECT ops.is_valid_feature_update_scope_0052(p_scope_type, p_scope)
             AND (
               p_scope_type <> 'cache_target_keys'
               OR char_length(p_scope->>'external_system')
                    <= 112
             )
        $$;


ALTER FUNCTION ops.is_valid_feature_update_scope_0074(p_scope_type text, p_scope jsonb) OWNER TO ktm_feature_schema_owner;

--
-- Name: is_valid_feature_update_scope_0075(text, jsonb); Type: FUNCTION; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE FUNCTION ops.is_valid_feature_update_scope_0075(p_scope_type text, p_scope jsonb) RETURNS boolean
    LANGUAGE plpgsql IMMUTABLE STRICT PARALLEL SAFE
    AS $$
        DECLARE
          item jsonb;
          text_value text;
          seen_values text[] := ARRAY[]::text[];
          canonical_whitespace text := ' '
            || chr(9) || chr(10) || chr(11) || chr(12) || chr(13)
            || chr(28) || chr(29) || chr(30) || chr(31) || chr(133)
            || chr(160) || chr(5760) || chr(8192) || chr(8193) || chr(8194)
            || chr(8195) || chr(8196) || chr(8197) || chr(8198) || chr(8199)
            || chr(8200) || chr(8201) || chr(8202) || chr(8232) || chr(8233)
            || chr(8239) || chr(8287) || chr(12288);
        BEGIN
          IF p_scope_type <> 'cache_target_keys' THEN
            RETURN ops.is_valid_feature_update_scope_0074(p_scope_type, p_scope);
          END IF;
          IF jsonb_typeof(p_scope) IS DISTINCT FROM 'object'
             OR jsonb_typeof(p_scope->'type') IS DISTINCT FROM 'string'
             OR p_scope->>'type' IS DISTINCT FROM p_scope_type
             OR p_scope - ARRAY[
                  'type', 'external_system', 'target_keys', 'radius_km', 'scope_mode'
                ]::text[] <> '{}'::jsonb
             OR jsonb_typeof(p_scope->'external_system') IS DISTINCT FROM 'string'
             OR jsonb_typeof(p_scope->'target_keys') IS DISTINCT FROM 'array'
             OR jsonb_typeof(p_scope->'scope_mode') IS DISTINCT FROM 'string'
             OR jsonb_array_length(p_scope->'target_keys') > 500 THEN
            RETURN false;
          END IF;
          text_value := p_scope->>'external_system';
          IF text_value = ''
             OR char_length(text_value) > 112
             OR text_value <> btrim(text_value, canonical_whitespace)
             OR text_value <> normalize(text_value, NFC)
             OR p_scope->>'scope_mode' NOT IN ('center_radius', 'sigungu_by_radius') THEN
            RETURN false;
          END IF;
          IF p_scope ? 'radius_km' THEN
            IF jsonb_typeof(p_scope->'radius_km') IS DISTINCT FROM 'number'
               OR (p_scope->>'radius_km')::numeric <= 0
               OR (p_scope->>'radius_km')::numeric > 500 THEN
              RETURN false;
            END IF;
          END IF;
          FOR item IN SELECT value FROM jsonb_array_elements(p_scope->'target_keys')
          LOOP
            IF jsonb_typeof(item) IS DISTINCT FROM 'string' THEN
              RETURN false;
            END IF;
            text_value := item #>> '{}';
            IF text_value = ''
               OR char_length(text_value) > 512
               OR text_value <> btrim(text_value, canonical_whitespace)
               OR text_value <> normalize(text_value, NFC)
               OR text_value = ANY(seen_values) THEN
              RETURN false;
            END IF;
            seen_values := array_append(seen_values, text_value);
          END LOOP;
          RETURN true;
        END;
        $$;


ALTER FUNCTION ops.is_valid_feature_update_scope_0075(p_scope_type text, p_scope jsonb) OWNER TO ktm_feature_schema_owner;

--
-- Name: reject_c6c_cancel_probe_event(); Type: FUNCTION; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE FUNCTION ops.reject_c6c_cancel_probe_event() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        BEGIN
          IF EXISTS (
            SELECT 1
            FROM ops.import_jobs AS job
            WHERE job.job_id = NEW.job_id
              AND job.kind = 'c6c_cancel_probe'
          ) THEN
            RAISE EXCEPTION
              'c6c cancel-probe job cannot own import job events: %', NEW.job_id
              USING ERRCODE = 'check_violation';
          END IF;
          RETURN NEW;
        END;
        $$;


ALTER FUNCTION ops.reject_c6c_cancel_probe_event() OWNER TO ktm_feature_schema_owner;

--
-- Name: reject_cache_target_history_mutation(); Type: FUNCTION; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE FUNCTION ops.reject_cache_target_history_mutation() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        BEGIN
          RAISE EXCEPTION 'cache target history is append-only'
            USING ERRCODE = '55000';
        END;
        $$;


ALTER FUNCTION ops.reject_cache_target_history_mutation() OWNER TO ktm_feature_schema_owner;

--
-- Name: reject_canonical_feature_update_job_delete(); Type: FUNCTION; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE FUNCTION ops.reject_canonical_feature_update_job_delete() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        BEGIN
          IF OLD.kind = 'feature_update_request' THEN
            RAISE EXCEPTION 'canonical feature update job is append-only: %', OLD.job_id
              USING ERRCODE = 'check_violation';
          END IF;
          RETURN OLD;
        END;
        $$;


ALTER FUNCTION ops.reject_canonical_feature_update_job_delete() OWNER TO ktm_feature_schema_owner;

--
-- Name: reject_dagster_schedule_audit_mutation(); Type: FUNCTION; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE FUNCTION ops.reject_dagster_schedule_audit_mutation() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        BEGIN
          RAISE EXCEPTION 'dagster schedule audit records are append-only'
            USING ERRCODE = '55000';
        END;
        $$;


ALTER FUNCTION ops.reject_dagster_schedule_audit_mutation() OWNER TO ktm_feature_schema_owner;

--
-- Name: reject_domain_command_history_mutation(); Type: FUNCTION; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE FUNCTION ops.reject_domain_command_history_mutation() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        BEGIN
          RAISE EXCEPTION 'domain command history is append-only'
            USING ERRCODE = '55000';
        END;
        $$;


ALTER FUNCTION ops.reject_domain_command_history_mutation() OWNER TO ktm_feature_schema_owner;

--
-- Name: reject_feature_update_request_idempotency_mutation(); Type: FUNCTION; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE FUNCTION ops.reject_feature_update_request_idempotency_mutation() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        BEGIN
          RAISE EXCEPTION 'feature update request idempotency ledger is append-only'
            USING ERRCODE = '55000';
        END;
        $$;


ALTER FUNCTION ops.reject_feature_update_request_idempotency_mutation() OWNER TO ktm_feature_schema_owner;

--
-- Name: reject_import_job_identity_change(); Type: FUNCTION; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE FUNCTION ops.reject_import_job_identity_change() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog'
    AS $$
        BEGIN
            IF NEW.kind IS DISTINCT FROM OLD.kind
               OR NEW.dataset_membership_mode
                  IS DISTINCT FROM OLD.dataset_membership_mode
               OR NEW.root_id IS DISTINCT FROM OLD.root_id
               OR NEW.root_kind IS DISTINCT FROM OLD.root_kind
               OR (
                   OLD.kind = 'feature_update_request'
                   AND NEW.payload IS DISTINCT FROM OLD.payload
               ) THEN
                RAISE EXCEPTION 'import job canonical identity is immutable: %', OLD.job_id
                    USING ERRCODE = '23514',
                        CONSTRAINT = 'ck_import_job_identity_immutable';
            END IF;
            RETURN NEW;
        END;
        $$;


ALTER FUNCTION ops.reject_import_job_identity_change() OWNER TO ktm_feature_schema_owner;

--
-- Name: reject_import_job_quarantine_mutation(); Type: FUNCTION; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE FUNCTION ops.reject_import_job_quarantine_mutation() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        BEGIN
          IF TG_OP = 'INSERT' THEN
            IF NEW.quarantined_at IS NOT NULL OR NEW.quarantine_reason IS NOT NULL THEN
              RAISE EXCEPTION
                'import job quarantine markers are migration-owned: %', NEW.job_id
                USING ERRCODE = 'check_violation';
            END IF;
          ELSIF OLD.quarantined_at IS NOT NULL THEN
            RAISE EXCEPTION 'quarantined import job is immutable: %',
              OLD.job_id
              USING ERRCODE = 'check_violation';
          ELSIF TG_OP = 'UPDATE'
             AND (
               NEW.quarantined_at IS DISTINCT FROM OLD.quarantined_at
               OR NEW.quarantine_reason IS DISTINCT FROM OLD.quarantine_reason
             ) THEN
            RAISE EXCEPTION
              'import job quarantine markers are migration-owned: %', OLD.job_id
              USING ERRCODE = 'check_violation';
          END IF;
          IF TG_OP = 'DELETE' THEN
            RETURN OLD;
          END IF;
          IF NEW.parent_job_id IS NOT NULL AND EXISTS (
            SELECT 1
            FROM ops.import_jobs AS parent
            WHERE parent.job_id = NEW.parent_job_id
              AND parent.quarantined_at IS NOT NULL
          ) THEN
            RAISE EXCEPTION 'cannot attach a job to quarantined import job: %',
              NEW.parent_job_id
              USING ERRCODE = 'check_violation';
          END IF;
          RETURN NEW;
        END;
        $$;


ALTER FUNCTION ops.reject_import_job_quarantine_mutation() OWNER TO ktm_feature_schema_owner;

--
-- Name: reject_quarantined_cancellation_member(); Type: FUNCTION; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE FUNCTION ops.reject_quarantined_cancellation_member() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        BEGIN
          IF EXISTS (
            SELECT 1
            FROM ops.import_jobs AS job
            WHERE job.job_id = NEW.job_id
              AND job.quarantined_at IS NOT NULL
          ) THEN
            RAISE EXCEPTION 'cannot cancel a quarantined import job: %', NEW.job_id
              USING ERRCODE = 'check_violation';
          END IF;
          RETURN NEW;
        END;
        $$;


ALTER FUNCTION ops.reject_quarantined_cancellation_member() OWNER TO ktm_feature_schema_owner;

--
-- Name: reject_quarantined_import_job_event_mutation(); Type: FUNCTION; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE FUNCTION ops.reject_quarantined_import_job_event_mutation() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        BEGIN
          IF TG_OP = 'INSERT' AND NEW.quarantined_at IS NOT NULL THEN
            RAISE EXCEPTION
              'import job event quarantine marker is migration-owned: %', NEW.event_id
              USING ERRCODE = 'check_violation';
          ELSIF TG_OP = 'UPDATE'
             AND NEW.quarantined_at IS DISTINCT FROM OLD.quarantined_at THEN
            RAISE EXCEPTION
              'import job event quarantine marker is migration-owned: %', OLD.event_id
              USING ERRCODE = 'check_violation';
          END IF;
          IF TG_OP <> 'INSERT' AND EXISTS (
            SELECT 1
            FROM ops.import_jobs AS job
            WHERE job.job_id = OLD.job_id
              AND job.quarantined_at IS NOT NULL
          ) THEN
            RAISE EXCEPTION 'events of a quarantined import job are immutable: %',
              OLD.job_id
              USING ERRCODE = 'check_violation';
          END IF;
          IF TG_OP <> 'DELETE' AND EXISTS (
            SELECT 1
            FROM ops.import_jobs AS job
            WHERE job.job_id = NEW.job_id
              AND job.quarantined_at IS NOT NULL
          ) THEN
            RAISE EXCEPTION 'cannot append an event to quarantined import job: %',
              NEW.job_id
              USING ERRCODE = 'check_violation';
          END IF;
          IF TG_OP = 'DELETE' THEN
            RETURN OLD;
          END IF;
          RETURN NEW;
        END;
        $$;


ALTER FUNCTION ops.reject_quarantined_import_job_event_mutation() OWNER TO ktm_feature_schema_owner;

--
-- Name: reject_terminal_current_summary_run_mutation(); Type: FUNCTION; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE FUNCTION ops.reject_terminal_current_summary_run_mutation() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog'
    AS $$
        BEGIN
            IF OLD.status IN ('succeeded', 'failed') THEN
                RAISE EXCEPTION 'terminal current summary receipt is immutable: %',
                    OLD.summary_run_id
                    USING ERRCODE = '23514',
                        CONSTRAINT = 'ck_current_summary_runs_terminal_immutable';
            END IF;
            RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
        END;
        $$;


ALTER FUNCTION ops.reject_terminal_current_summary_run_mutation() OWNER TO ktm_feature_schema_owner;

--
-- Name: stamp_import_job_root(); Type: FUNCTION; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE FUNCTION ops.stamp_import_job_root() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE
  parent_root_id uuid;
  parent_root_kind text;
  parent_is_root boolean;
BEGIN
  IF NEW.parent_job_id IS NULL THEN
    NEW.root_id := NEW.job_id;
    NEW.root_kind := CASE
      WHEN NEW.kind = 'feature_update_request' THEN 'update_request'
      ELSE 'import_job'
    END;
  ELSE
    SELECT p.root_id, p.root_kind, (p.parent_job_id IS NULL)
      INTO parent_root_id, parent_root_kind, parent_is_root
      FROM ops.import_jobs AS p
      WHERE p.job_id = NEW.parent_job_id;
    IF parent_root_id IS NULL THEN
      RAISE EXCEPTION 'import job % references missing parent %',
        NEW.job_id, NEW.parent_job_id
        USING ERRCODE = 'foreign_key_violation';
    END IF;
    IF NOT parent_is_root THEN
      RAISE EXCEPTION
        'import job lineage must be at most 2 levels: parent % of % is not a root',
        NEW.parent_job_id, NEW.job_id
        USING ERRCODE = 'check_violation';
    END IF;
    -- 양방향 lock: 자식이 되는 job은 leaf여야 한다. 이미 자식을 가진 job을
    -- (batch attach 등으로) reparent하면 3단계가 되고 손자의 root_id가 stale해진다.
    IF EXISTS (
      SELECT 1 FROM ops.import_jobs AS descendant
      WHERE descendant.parent_job_id = NEW.job_id
    ) THEN
      RAISE EXCEPTION
        'import job lineage must be at most 2 levels: job % has children and cannot become a child',
        NEW.job_id
        USING ERRCODE = 'check_violation';
    END IF;
    NEW.root_id := parent_root_id;
    NEW.root_kind := parent_root_kind;
  END IF;
  RETURN NEW;
END;
$$;


ALTER FUNCTION ops.stamp_import_job_root() OWNER TO ktm_feature_schema_owner;

--
-- Name: validate_dagster_schedule_active_claim_delete(); Type: FUNCTION; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE FUNCTION ops.validate_dagster_schedule_active_claim_delete() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        BEGIN
          IF EXISTS (
            SELECT 1
            FROM ops.dagster_schedule_audit_events AS terminal
            WHERE terminal.command_id = OLD.command_id
              AND terminal.schedule_name = OLD.schedule_name
              AND terminal.phase IN ('succeeded','failed')
              AND terminal.details ->> 'outcome_certainty' = 'confirmed'
          ) THEN
            RETURN OLD;
          END IF;
          IF EXISTS (
            SELECT 1
            FROM ops.dagster_schedule_claim_resolutions AS resolution
            WHERE resolution.command_id = OLD.command_id
              AND resolution.schedule_name = OLD.schedule_name
          ) THEN
            RETURN OLD;
          END IF;
          RAISE EXCEPTION 'active schedule claim requires confirmed outcome or resolution'
            USING ERRCODE = '23514';
        END;
        $$;


ALTER FUNCTION ops.validate_dagster_schedule_active_claim_delete() OWNER TO ktm_feature_schema_owner;

--
-- Name: validate_dagster_schedule_active_claim_insert(); Type: FUNCTION; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE FUNCTION ops.validate_dagster_schedule_active_claim_insert() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        BEGIN
          IF NOT EXISTS (
            SELECT 1
            FROM ops.dagster_schedule_audit_events AS requested
            WHERE requested.command_id = NEW.command_id
              AND requested.schedule_name = NEW.schedule_name
              AND requested.phase = 'requested'
          ) THEN
            RAISE EXCEPTION 'active schedule claim requires matching requested event'
              USING ERRCODE = '23514';
          END IF;
          IF NEW.operation_finished_at IS NOT NULL THEN
            RAISE EXCEPTION 'new active schedule claim must start in progress'
              USING ERRCODE = '23514';
          END IF;
          RETURN NEW;
        END;
        $$;


ALTER FUNCTION ops.validate_dagster_schedule_active_claim_insert() OWNER TO ktm_feature_schema_owner;

--
-- Name: validate_dagster_schedule_active_claim_update(); Type: FUNCTION; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE FUNCTION ops.validate_dagster_schedule_active_claim_update() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        BEGIN
          IF OLD.command_id IS DISTINCT FROM NEW.command_id
             OR OLD.schedule_name IS DISTINCT FROM NEW.schedule_name
             OR OLD.created_at IS DISTINCT FROM NEW.created_at
             OR OLD.resolvable_after IS DISTINCT FROM NEW.resolvable_after
             OR OLD.operation_finished_at IS NOT NULL
             OR NEW.operation_finished_at IS NULL THEN
            RAISE EXCEPTION 'active schedule claim only allows one-way operation completion'
              USING ERRCODE = '55000';
          END IF;
          RETURN NEW;
        END;
        $$;


ALTER FUNCTION ops.validate_dagster_schedule_active_claim_update() OWNER TO ktm_feature_schema_owner;

--
-- Name: validate_dagster_schedule_audit_terminal(); Type: FUNCTION; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE FUNCTION ops.validate_dagster_schedule_audit_terminal() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        BEGIN
          PERFORM 1
          FROM ops.dagster_schedule_active_claims AS claim
          WHERE claim.command_id = NEW.command_id
            AND claim.schedule_name = NEW.schedule_name
            AND claim.operation_finished_at IS NOT NULL
          FOR UPDATE;
          IF NOT FOUND THEN
            RAISE EXCEPTION 'terminal schedule audit event requires finished active claim'
              USING ERRCODE = '23514';
          END IF;
          IF NOT EXISTS (
            SELECT 1
            FROM ops.dagster_schedule_audit_events AS requested
            WHERE requested.command_id = NEW.command_id
              AND requested.phase = 'requested'
              AND requested.schedule_name = NEW.schedule_name
              AND requested.command = NEW.command
              AND requested.actor = NEW.actor
              AND requested.reason IS NOT DISTINCT FROM NEW.reason
          ) THEN
            RAISE EXCEPTION 'terminal schedule audit event does not match requested event'
              USING ERRCODE = '23514';
          END IF;
          IF NEW.details ->> 'outcome_certainty' IS NULL
             OR NEW.details ->> 'outcome_certainty' NOT IN ('confirmed','uncertain') THEN
            RAISE EXCEPTION 'terminal schedule audit event requires valid outcome certainty'
              USING ERRCODE = '23514';
          END IF;
          IF EXISTS (
            SELECT 1
            FROM ops.dagster_schedule_claim_resolutions AS resolution
            WHERE resolution.command_id = NEW.command_id
          ) THEN
            RAISE EXCEPTION 'resolved schedule claim cannot receive terminal audit event'
              USING ERRCODE = '23514';
          END IF;
          RETURN NEW;
        END;
        $$;


ALTER FUNCTION ops.validate_dagster_schedule_audit_terminal() OWNER TO ktm_feature_schema_owner;

--
-- Name: validate_dagster_schedule_claim_resolution(); Type: FUNCTION; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE FUNCTION ops.validate_dagster_schedule_claim_resolution() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        DECLARE
          claim_resolvable_after timestamptz;
        BEGIN
          SELECT claim.resolvable_after
          INTO claim_resolvable_after
          FROM ops.dagster_schedule_active_claims AS claim
          WHERE claim.command_id = NEW.command_id
            AND claim.schedule_name = NEW.schedule_name
          FOR UPDATE;
          IF NOT FOUND THEN
            RAISE EXCEPTION 'only an active uncertain schedule claim can be resolved'
              USING ERRCODE = '23514';
          END IF;
          IF clock_timestamp() < claim_resolvable_after THEN
            RAISE EXCEPTION 'uncertain schedule claim cannot be resolved before lease expires'
              USING ERRCODE = '23514';
          END IF;
          IF NOT EXISTS (
            SELECT 1
            FROM ops.dagster_schedule_audit_events AS requested
            WHERE requested.command_id = NEW.command_id
              AND requested.schedule_name = NEW.schedule_name
              AND requested.phase = 'requested'
          ) THEN
            RAISE EXCEPTION 'schedule claim resolution requires requested event'
              USING ERRCODE = '23514';
          END IF;
          IF EXISTS (
            SELECT 1
            FROM ops.dagster_schedule_audit_events AS terminal
            WHERE terminal.command_id = NEW.command_id
              AND terminal.phase IN ('succeeded','failed')
              AND (
                terminal.schedule_name <> NEW.schedule_name
                OR terminal.details ->> 'outcome_certainty' IS DISTINCT FROM 'uncertain'
              )
          ) THEN
            RAISE EXCEPTION 'confirmed schedule terminal event cannot be resolved'
              USING ERRCODE = '23514';
          END IF;
          RETURN NEW;
        END;
        $$;


ALTER FUNCTION ops.validate_dagster_schedule_claim_resolution() OWNER TO ktm_feature_schema_owner;

--
-- Name: validate_feature_update_request_idempotency_insert(); Type: FUNCTION; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE FUNCTION ops.validate_feature_update_request_idempotency_insert() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        BEGIN
          IF NOT EXISTS (
            SELECT 1
            FROM ops.feature_update_requests AS request
            WHERE request.request_id = NEW.request_id
              AND request.operator IS NOT DISTINCT FROM NEW.actor
          ) THEN
            RAISE EXCEPTION 'idempotency actor must match feature update request operator'
              USING ERRCODE = '23514';
          END IF;
          RETURN NEW;
        END;
        $$;


ALTER FUNCTION ops.validate_feature_update_request_idempotency_insert() OWNER TO ktm_feature_schema_owner;

--
-- Name: assert_active_curated_source_dataset(uuid); Type: FUNCTION; Schema: provider_sync; Owner: ktm_feature_schema_owner
--

CREATE FUNCTION provider_sync.assert_active_curated_source_dataset(source_uuid uuid) RETURNS void
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog'
    AS $$
        BEGIN
            PERFORM 1 FROM feature.curated_sources AS source
            JOIN provider_sync.provider_datasets AS dataset
              ON dataset.provider_dataset_id = source.provider_dataset_id
            WHERE source.source_id = source_uuid AND dataset.is_active
            FOR SHARE OF dataset;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'inactive provider dataset cannot receive curation rule writes'
                    USING ERRCODE = '23514', CONSTRAINT = 'ck_provider_dataset_active_write';
            END IF;
        END;
        $$;


ALTER FUNCTION provider_sync.assert_active_curated_source_dataset(source_uuid uuid) OWNER TO ktm_feature_schema_owner;

--
-- Name: assert_active_integrity_observation_scope(bigint); Type: FUNCTION; Schema: provider_sync; Owner: ktm_feature_schema_owner
--

CREATE FUNCTION provider_sync.assert_active_integrity_observation_scope(scope_id bigint) RETURNS void
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog'
    AS $$
        BEGIN
            PERFORM 1 FROM ops.integrity_observation_scopes AS scope
            JOIN provider_sync.provider_datasets AS dataset
              ON dataset.provider_dataset_id = scope.provider_dataset_id
            WHERE scope.integrity_observation_scope_id = scope_id AND dataset.is_active
            FOR SHARE OF dataset;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'inactive provider dataset cannot receive integrity writes'
                    USING ERRCODE = '23514', CONSTRAINT = 'ck_provider_dataset_active_write';
            END IF;
        END;
        $$;


ALTER FUNCTION provider_sync.assert_active_integrity_observation_scope(scope_id bigint) OWNER TO ktm_feature_schema_owner;

--
-- Name: assert_active_notice_lifecycle_scope(bigint); Type: FUNCTION; Schema: provider_sync; Owner: ktm_feature_schema_owner
--

CREATE FUNCTION provider_sync.assert_active_notice_lifecycle_scope(scope_id bigint) RETURNS void
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog'
    AS $$
        BEGIN
            PERFORM 1 FROM provider_sync.notice_lifecycle_scopes AS scope
            JOIN provider_sync.provider_datasets AS dataset
              ON dataset.provider_dataset_id = scope.provider_dataset_id
            WHERE scope.notice_lifecycle_scope_id = scope_id AND dataset.is_active
            FOR SHARE OF dataset;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'inactive provider dataset cannot receive notice lineage writes'
                    USING ERRCODE = '23514', CONSTRAINT = 'ck_provider_dataset_active_write';
            END IF;
        END;
        $$;


ALTER FUNCTION provider_sync.assert_active_notice_lifecycle_scope(scope_id bigint) OWNER TO ktm_feature_schema_owner;

--
-- Name: assert_active_provider_dataset(bigint); Type: FUNCTION; Schema: provider_sync; Owner: ktm_feature_schema_owner
--

CREATE FUNCTION provider_sync.assert_active_provider_dataset(dataset_id bigint) RETURNS void
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog'
    AS $$
        BEGIN
            IF dataset_id IS NULL THEN
                RETURN;
            END IF;
            PERFORM 1
            FROM provider_sync.provider_datasets AS dataset
            WHERE dataset.provider_dataset_id = dataset_id AND dataset.is_active
            FOR SHARE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'inactive provider dataset cannot receive normal writes'
                    USING ERRCODE = '23514',
                        CONSTRAINT = 'ck_provider_dataset_active_write';
            END IF;
        END;
        $$;


ALTER FUNCTION provider_sync.assert_active_provider_dataset(dataset_id bigint) OWNER TO ktm_feature_schema_owner;

--
-- Name: assert_active_source_entity_dataset(text); Type: FUNCTION; Schema: provider_sync; Owner: ktm_feature_schema_owner
--

CREATE FUNCTION provider_sync.assert_active_source_entity_dataset(entity_key text) RETURNS void
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog'
    AS $$
        BEGIN
            PERFORM 1
            FROM provider_sync.source_entities AS entity
            JOIN provider_sync.provider_datasets AS dataset
              ON dataset.provider_dataset_id = entity.provider_dataset_id
            WHERE entity.source_entity_key = entity_key AND dataset.is_active
            FOR SHARE OF dataset;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'inactive provider dataset cannot receive lineage writes'
                    USING ERRCODE = '23514',
                        CONSTRAINT = 'ck_provider_dataset_active_write';
            END IF;
        END;
        $$;


ALTER FUNCTION provider_sync.assert_active_source_entity_dataset(entity_key text) OWNER TO ktm_feature_schema_owner;

--
-- Name: assert_active_source_record_dataset(text); Type: FUNCTION; Schema: provider_sync; Owner: ktm_feature_schema_owner
--

CREATE FUNCTION provider_sync.assert_active_source_record_dataset(record_key text) RETURNS bigint
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog'
    AS $$
        DECLARE resolved_dataset_id bigint;
        BEGIN
            IF record_key IS NULL THEN RETURN NULL; END IF;
            SELECT entity.provider_dataset_id INTO resolved_dataset_id
            FROM provider_sync.source_records AS record
            JOIN provider_sync.source_entities AS entity
              ON entity.source_entity_key = record.source_entity_key
            WHERE record.source_record_key = record_key;
            IF NOT FOUND THEN RETURN NULL; END IF;
            PERFORM provider_sync.assert_active_provider_dataset(resolved_dataset_id);
            RETURN resolved_dataset_id;
        END;
        $$;


ALTER FUNCTION provider_sync.assert_active_source_record_dataset(record_key text) OWNER TO ktm_feature_schema_owner;

--
-- Name: assert_feature_update_request_member_available(uuid, bigint, text, text); Type: FUNCTION; Schema: provider_sync; Owner: ktm_feature_schema_owner
--

CREATE FUNCTION provider_sync.assert_feature_update_request_member_available(target_request_id uuid, target_dataset_id bigint, target_scope text, target_operation_key text) RETURNS void
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog'
    AS $$
        DECLARE target_is_active boolean;
        BEGIN
            SELECT job.status IN ('queued', 'running')
                   AND job.quarantined_at IS NULL
              INTO target_is_active
            FROM ops.feature_update_requests AS request
            JOIN ops.import_jobs AS job ON job.job_id = request.job_id
            WHERE request.request_id = target_request_id;
            IF NOT FOUND OR NOT target_is_active THEN
                RETURN;
            END IF;

            -- 같은 canonical scope의 경쟁 요청은 이 row lock으로 직렬화한다.
            -- membership pair/array shadow나 별도 lease table을 만들지 않는다.
            PERFORM 1
            FROM provider_sync.provider_dataset_operation_scopes AS scope
            WHERE scope.provider_dataset_id = target_dataset_id
              AND scope.sync_scope = target_scope
              AND scope.operation_key = target_operation_key
            FOR UPDATE;

            IF EXISTS (
                SELECT 1
                FROM ops.feature_update_request_datasets AS competing_member
                JOIN ops.feature_update_requests AS competing_request
                  ON competing_request.request_id = competing_member.request_id
                JOIN ops.import_jobs AS competing_job
                  ON competing_job.job_id = competing_request.job_id
                WHERE competing_member.provider_dataset_id = target_dataset_id
                  AND competing_member.sync_scope = target_scope
                  AND competing_member.operation_key = target_operation_key
                  AND competing_member.request_id <> target_request_id
                  AND competing_job.status IN ('queued', 'running')
                  AND competing_job.quarantined_at IS NULL
            ) THEN
                RAISE EXCEPTION
                    'active feature update already owns dataset operation (% / % / %)',
                    target_dataset_id, target_scope, target_operation_key
                    USING ERRCODE = '23505',
                        CONSTRAINT = 'uq_feature_update_request_active_member';
            END IF;
        END;
        $$;


ALTER FUNCTION provider_sync.assert_feature_update_request_member_available(target_request_id uuid, target_dataset_id bigint, target_scope text, target_operation_key text) OWNER TO ktm_feature_schema_owner;

--
-- Name: assert_feature_update_request_members_active(uuid); Type: FUNCTION; Schema: provider_sync; Owner: ktm_feature_schema_owner
--

CREATE FUNCTION provider_sync.assert_feature_update_request_members_active(target_request_id uuid) RETURNS void
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog'
    AS $$
        BEGIN
            PERFORM 1
            FROM ops.feature_update_request_datasets AS member
            JOIN provider_sync.provider_dataset_operation_scopes AS scope
              ON scope.provider_dataset_id = member.provider_dataset_id
             AND scope.sync_scope = member.sync_scope
             AND scope.operation_key = member.operation_key
            JOIN provider_sync.provider_dataset_operations AS operation
              ON operation.provider_dataset_id = scope.provider_dataset_id
             AND operation.operation_key = scope.operation_key
             AND operation.operation_kind = scope.operation_kind
            JOIN provider_sync.provider_datasets AS dataset
              ON dataset.provider_dataset_id = scope.provider_dataset_id
            WHERE member.request_id = target_request_id
            FOR SHARE OF dataset, operation;
            IF EXISTS (
                SELECT 1 FROM ops.feature_update_request_datasets AS member
                JOIN provider_sync.provider_dataset_operation_scopes AS scope
                  ON scope.provider_dataset_id = member.provider_dataset_id
                 AND scope.sync_scope = member.sync_scope
                 AND scope.operation_key = member.operation_key
                JOIN provider_sync.provider_dataset_operations AS operation
                  ON operation.provider_dataset_id = scope.provider_dataset_id
                 AND operation.operation_key = scope.operation_key
                 AND operation.operation_kind = scope.operation_kind
                JOIN provider_sync.provider_datasets AS dataset
                  ON dataset.provider_dataset_id = scope.provider_dataset_id
                WHERE member.request_id = target_request_id
                  AND (NOT dataset.is_active OR NOT operation.is_enabled)
            ) THEN
                RAISE EXCEPTION 'inactive dataset member cannot receive update request writes'
                    USING ERRCODE = '23514',
                        CONSTRAINT = 'ck_provider_dataset_active_write';
            END IF;
        END;
        $$;


ALTER FUNCTION provider_sync.assert_feature_update_request_members_active(target_request_id uuid) OWNER TO ktm_feature_schema_owner;

--
-- Name: assert_feature_update_request_membership_available(uuid); Type: FUNCTION; Schema: provider_sync; Owner: ktm_feature_schema_owner
--

CREATE FUNCTION provider_sync.assert_feature_update_request_membership_available(target_request_id uuid) RETURNS void
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog'
    AS $$
        DECLARE member_row record;
        BEGIN
            FOR member_row IN
                SELECT provider_dataset_id, sync_scope, operation_key
                FROM ops.feature_update_request_datasets
                WHERE request_id = target_request_id
                ORDER BY provider_dataset_id, sync_scope, operation_key
            LOOP
                PERFORM provider_sync.assert_feature_update_request_member_available(
                    target_request_id,
                    member_row.provider_dataset_id,
                    member_row.sync_scope,
                    member_row.operation_key
                );
            END LOOP;
        END;
        $$;


ALTER FUNCTION provider_sync.assert_feature_update_request_membership_available(target_request_id uuid) OWNER TO ktm_feature_schema_owner;

--
-- Name: assert_feature_update_request_membership_complete(); Type: FUNCTION; Schema: provider_sync; Owner: ktm_feature_schema_owner
--

CREATE FUNCTION provider_sync.assert_feature_update_request_membership_complete() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog'
    AS $$
        DECLARE target_request_id uuid := COALESCE(NEW.request_id, OLD.request_id);
            mode_value text; member_count bigint;
        BEGIN
            SELECT dataset_membership_mode INTO mode_value
            FROM ops.feature_update_requests WHERE request_id = target_request_id;
            IF NOT FOUND THEN RETURN NULL; END IF;
            SELECT count(*) INTO member_count
            FROM ops.feature_update_request_datasets WHERE request_id = target_request_id;
            IF (mode_value = 'single' AND member_count <> 1)
               OR (mode_value = 'multiple' AND member_count = 0) THEN
                RAISE EXCEPTION 'feature update request membership cardinality does not match mode'
                    USING ERRCODE = '23514',
                        CONSTRAINT = 'ck_feature_update_request_membership_complete';
            END IF;
            RETURN NULL;
        END;
        $$;


ALTER FUNCTION provider_sync.assert_feature_update_request_membership_complete() OWNER TO ktm_feature_schema_owner;

--
-- Name: assert_import_job_event_member(uuid, uuid); Type: FUNCTION; Schema: provider_sync; Owner: ktm_feature_schema_owner
--

CREATE FUNCTION provider_sync.assert_import_job_event_member(target_job_id uuid, target_member_id uuid) RETURNS void
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog'
    AS $$
        DECLARE mode_value text;
        BEGIN
            SELECT dataset_membership_mode INTO mode_value
            FROM ops.import_jobs WHERE job_id = target_job_id;
            IF target_member_id IS NULL THEN
                IF mode_value <> 'root' THEN
                    RAISE EXCEPTION 'dataset job event requires a dataset member'
                        USING ERRCODE = '23514',
                            CONSTRAINT = 'ck_import_job_event_member_required';
                END IF;
                RETURN;
            END IF;
            IF mode_value = 'root' THEN
                RAISE EXCEPTION 'root import job event cannot carry a dataset member'
                    USING ERRCODE = '23514',
                        CONSTRAINT = 'ck_import_job_event_member_root';
            END IF;
            IF EXISTS (
                SELECT 1 FROM ops.import_job_datasets
                WHERE job_id = target_job_id
                  AND import_job_dataset_id = target_member_id
            ) THEN
                PERFORM provider_sync.assert_import_job_members_active(target_job_id);
            END IF;
        END;
        $$;


ALTER FUNCTION provider_sync.assert_import_job_event_member(target_job_id uuid, target_member_id uuid) OWNER TO ktm_feature_schema_owner;

--
-- Name: assert_import_job_members_active(uuid); Type: FUNCTION; Schema: provider_sync; Owner: ktm_feature_schema_owner
--

CREATE FUNCTION provider_sync.assert_import_job_members_active(target_job_id uuid) RETURNS void
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog'
    AS $$
        BEGIN
            PERFORM 1
            FROM ops.import_job_datasets AS member
            JOIN provider_sync.provider_dataset_operation_scopes AS scope
              ON scope.provider_dataset_id = member.provider_dataset_id
             AND scope.sync_scope = member.sync_scope
             AND scope.operation_key = member.operation_key
            JOIN provider_sync.provider_dataset_operations AS operation
              ON operation.provider_dataset_id = scope.provider_dataset_id
             AND operation.operation_key = scope.operation_key
             AND operation.operation_kind = scope.operation_kind
            JOIN provider_sync.provider_datasets AS dataset
              ON dataset.provider_dataset_id = scope.provider_dataset_id
            WHERE member.job_id = target_job_id
            FOR SHARE OF dataset, operation;
            IF EXISTS (
                SELECT 1
                FROM ops.import_job_datasets AS member
                JOIN provider_sync.provider_dataset_operation_scopes AS scope
                  ON scope.provider_dataset_id = member.provider_dataset_id
                 AND scope.sync_scope = member.sync_scope
                 AND scope.operation_key = member.operation_key
                JOIN provider_sync.provider_dataset_operations AS operation
                  ON operation.provider_dataset_id = scope.provider_dataset_id
                 AND operation.operation_key = scope.operation_key
                 AND operation.operation_kind = scope.operation_kind
                JOIN provider_sync.provider_datasets AS dataset
                  ON dataset.provider_dataset_id = scope.provider_dataset_id
                WHERE member.job_id = target_job_id
                  AND (NOT dataset.is_active OR NOT operation.is_enabled)
            ) THEN
                RAISE EXCEPTION 'inactive dataset member cannot receive import job writes'
                    USING ERRCODE = '23514',
                        CONSTRAINT = 'ck_provider_dataset_active_write';
            END IF;
        END;
        $$;


ALTER FUNCTION provider_sync.assert_import_job_members_active(target_job_id uuid) OWNER TO ktm_feature_schema_owner;

--
-- Name: assert_import_job_membership_complete(); Type: FUNCTION; Schema: provider_sync; Owner: ktm_feature_schema_owner
--

CREATE FUNCTION provider_sync.assert_import_job_membership_complete() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog'
    AS $$
        DECLARE target_job_id uuid := COALESCE(NEW.job_id, OLD.job_id);
            mode_value text; member_count bigint;
        BEGIN
            SELECT dataset_membership_mode INTO mode_value
            FROM ops.import_jobs WHERE job_id = target_job_id;
            IF NOT FOUND THEN RETURN NULL; END IF;
            SELECT count(*) INTO member_count
            FROM ops.import_job_datasets WHERE job_id = target_job_id;
            IF (mode_value = 'root' AND member_count <> 0)
               OR (mode_value = 'single' AND member_count <> 1)
               OR (mode_value = 'multiple' AND member_count = 0) THEN
                RAISE EXCEPTION 'import job membership cardinality does not match mode'
                    USING ERRCODE = '23514',
                        CONSTRAINT = 'ck_import_job_membership_complete';
            END IF;
            RETURN NULL;
        END;
        $$;


ALTER FUNCTION provider_sync.assert_import_job_membership_complete() OWNER TO ktm_feature_schema_owner;

--
-- Name: assert_source_entity_head_completeness(); Type: FUNCTION; Schema: provider_sync; Owner: ktm_feature_schema_owner
--

CREATE FUNCTION provider_sync.assert_source_entity_head_completeness() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog'
    AS $$
        DECLARE
            entity_key text;
            record_count bigint;
            head_count bigint;
        BEGIN
            IF TG_OP = 'DELETE' THEN
                entity_key := OLD.source_entity_key;
            ELSE
                entity_key := NEW.source_entity_key;
            END IF;
            SELECT count(*) INTO record_count
            FROM provider_sync.source_records WHERE source_entity_key = entity_key;
            SELECT count(*) INTO head_count
            FROM provider_sync.source_entity_heads WHERE source_entity_key = entity_key;
            IF (record_count = 0 AND head_count <> 0)
               OR (record_count > 0 AND head_count <> 1) THEN
                RAISE EXCEPTION 'source entity head must exist exactly once for records'
                    USING ERRCODE = '23514',
                        CONSTRAINT = 'ck_source_entity_heads_complete';
            END IF;
            RETURN NULL;
        END;
        $$;


ALTER FUNCTION provider_sync.assert_source_entity_head_completeness() OWNER TO ktm_feature_schema_owner;

--
-- Name: enforce_source_entity_head_freshness(); Type: FUNCTION; Schema: provider_sync; Owner: ktm_feature_schema_owner
--

CREATE FUNCTION provider_sync.enforce_source_entity_head_freshness() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog'
    AS $$
        BEGIN
            IF (NEW.observed_at, NEW.current_source_record_key)
               < (OLD.observed_at, OLD.current_source_record_key) THEN
                RAISE EXCEPTION 'source entity head freshness cannot move backwards'
                    USING ERRCODE = '23514',
                        CONSTRAINT = 'ck_source_entity_heads_freshness';
            END IF;
            IF NEW.observed_at = OLD.observed_at
               AND NEW.current_source_record_key = OLD.current_source_record_key
               AND NEW.expires_at IS DISTINCT FROM OLD.expires_at THEN
                RAISE EXCEPTION 'head expiry needs a newer observation'
                    USING ERRCODE = '23514',
                        CONSTRAINT = 'ck_source_entity_heads_expiry_freshness';
            END IF;
            RETURN NEW;
        END;
        $$;


ALTER FUNCTION provider_sync.enforce_source_entity_head_freshness() OWNER TO ktm_feature_schema_owner;

--
-- Name: enforce_source_entity_identity_and_seen_at(); Type: FUNCTION; Schema: provider_sync; Owner: ktm_feature_schema_owner
--

CREATE FUNCTION provider_sync.enforce_source_entity_identity_and_seen_at() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog'
    AS $$
        BEGIN
            IF NEW.provider_dataset_id IS DISTINCT FROM OLD.provider_dataset_id
               OR NEW.source_entity_type IS DISTINCT FROM OLD.source_entity_type
               OR NEW.source_entity_id IS DISTINCT FROM OLD.source_entity_id THEN
                RAISE EXCEPTION 'source entity identity is immutable'
                    USING ERRCODE = '23514',
                        CONSTRAINT = 'ck_source_entities_identity_immutable';
            END IF;
            IF NEW.first_seen_at IS DISTINCT FROM OLD.first_seen_at
               OR NEW.last_seen_at < OLD.last_seen_at THEN
                RAISE EXCEPTION 'source entity observed time cannot move backwards'
                    USING ERRCODE = '23514',
                        CONSTRAINT = 'ck_source_entities_seen_freshness';
            END IF;
            RETURN NEW;
        END;
        $$;


ALTER FUNCTION provider_sync.enforce_source_entity_identity_and_seen_at() OWNER TO ktm_feature_schema_owner;

--
-- Name: is_valid_provider_dataset_capabilities(jsonb); Type: FUNCTION; Schema: provider_sync; Owner: ktm_feature_schema_owner
--

CREATE FUNCTION provider_sync.is_valid_provider_dataset_capabilities(value jsonb) RETURNS boolean
    LANGUAGE plpgsql IMMUTABLE
    SET search_path TO 'pg_catalog'
    AS $$
        DECLARE
            produced text;
        BEGIN
            IF jsonb_typeof(value) <> 'object'
               OR NOT (value ?& ARRAY['schema_version', 'produces', 'extensions'])
               OR (value - ARRAY['schema_version', 'produces', 'extensions']) <> '{}'::jsonb
               OR jsonb_typeof(value -> 'schema_version') IS DISTINCT FROM 'number'
               OR value -> 'schema_version' <> '1'::jsonb
               OR jsonb_typeof(value -> 'produces') IS DISTINCT FROM 'array'
               OR jsonb_typeof(value -> 'extensions') IS DISTINCT FROM 'object'
            THEN
                RETURN false;
            END IF;
            FOR produced IN SELECT jsonb_array_elements_text(value -> 'produces') LOOP
                IF produced NOT IN (
                    'place', 'event', 'notice', 'price', 'weather', 'route', 'area', 'enrichment'
                ) THEN
                    RETURN false;
                END IF;
            END LOOP;
            IF EXISTS (
                SELECT 1
                FROM jsonb_array_elements_text(value -> 'produces') AS item(value)
                GROUP BY item.value HAVING count(*) > 1
            ) THEN
                RETURN false;
            END IF;
            RETURN true;
        END;
        $$;


ALTER FUNCTION provider_sync.is_valid_provider_dataset_capabilities(value jsonb) OWNER TO ktm_feature_schema_owner;

--
-- Name: is_valid_provider_dataset_sync_scope(text); Type: FUNCTION; Schema: provider_sync; Owner: ktm_feature_schema_owner
--

CREATE FUNCTION provider_sync.is_valid_provider_dataset_sync_scope(value text) RETURNS boolean
    LANGUAGE sql IMMUTABLE
    SET search_path TO 'pg_catalog'
    AS $_$
            SELECT value IN ('dataset_wide', 'target_grids')
                OR value ~ '^external_system:[^[:space:]][^[:space:]]{0,111}$'
        $_$;


ALTER FUNCTION provider_sync.is_valid_provider_dataset_sync_scope(value text) OWNER TO ktm_feature_schema_owner;

--
-- Name: lock_feature_update_request_member_scopes(uuid); Type: FUNCTION; Schema: provider_sync; Owner: ktm_feature_schema_owner
--

CREATE FUNCTION provider_sync.lock_feature_update_request_member_scopes(target_request_id uuid) RETURNS void
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog'
    AS $$
        BEGIN
            -- terminal transition도 같은 lock을 잡아 release와 새 acquire가
            -- 같은 scope에서 선행 순서를 갖게 한다.
            PERFORM 1
            FROM provider_sync.provider_dataset_operation_scopes AS scope
            JOIN ops.feature_update_request_datasets AS member
              ON member.provider_dataset_id = scope.provider_dataset_id
             AND member.sync_scope = scope.sync_scope
             AND member.operation_key = scope.operation_key
            WHERE member.request_id = target_request_id
            ORDER BY scope.provider_dataset_id, scope.sync_scope, scope.operation_key
            FOR UPDATE OF scope;
        END;
        $$;


ALTER FUNCTION provider_sync.lock_feature_update_request_member_scopes(target_request_id uuid) OWNER TO ktm_feature_schema_owner;

SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: source_entity_heads; Type: TABLE; Schema: provider_sync; Owner: ktm_feature_schema_owner
--

CREATE TABLE provider_sync.source_entity_heads (
    source_entity_key text NOT NULL,
    current_source_record_key text NOT NULL,
    observed_at timestamp with time zone NOT NULL,
    expires_at timestamp with time zone,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    lineage_key character varying NOT NULL
);


ALTER TABLE provider_sync.source_entity_heads OWNER TO ktm_feature_schema_owner;

--
-- Name: notice_lineage_key(provider_sync.source_entity_heads); Type: FUNCTION; Schema: provider_sync; Owner: ktm_feature_schema_owner
--

CREATE FUNCTION provider_sync.notice_lineage_key(head provider_sync.source_entity_heads) RETURNS text
    LANGUAGE sql STABLE
    AS $$
            SELECT CASE
              WHEN dataset.provider = 'python-krex-api'
               AND dataset.dataset_key = 'krex_traffic_notices'
               AND entity.source_entity_type = 'traffic_notice'
              THEN COALESCE(
                NULLIF(
                  concat_ws(
                    '::',
                    NULLIF(lower(btrim(record.raw_data->>'occurred_date')), ''),
                    NULLIF(lower(btrim(record.raw_data->>'occurred_time')), ''),
                    NULLIF(lower(btrim(record.raw_data->>'route_no')), ''),
                    NULLIF(lower(btrim(record.raw_data->>'direction')), ''),
                    NULLIF(lower(btrim(record.raw_data->>'point_name')), ''),
                    NULLIF(
                      lower(btrim(record.raw_data->>'incident_type_code')), ''
                    )
                  ),
                  ''
                ),
                entity.source_entity_id
              )
              WHEN dataset.provider = 'python-kma-api'
               AND dataset.dataset_key = 'kma_weather_alerts'
               AND entity.source_entity_type = 'weather_alert'
              THEN COALESCE(
                NULLIF(
                  concat_ws(
                    '::',
                    NULLIF(btrim(record.raw_data->>'region_code'), ''),
                    NULLIF(
                      btrim(
                        COALESCE(
                          record.raw_data->>'phenomenon',
                          record.raw_data->>'alert_type'
                        )
                      ),
                      ''
                    )
                  ),
                  ''
                ),
                entity.source_entity_id
              )
              -- out-of-scope도 값을 갖는다. 읽는 쪽이
              -- COALESCE(head.lineage_key, entity.source_entity_id)로 물러나면
              -- **두 테이블에 걸친 식**이 되어 어떤 단일 인덱스도 받지 못한다.
              ELSE entity.source_entity_id
            END
            FROM provider_sync.source_entities AS entity
            JOIN provider_sync.provider_datasets AS dataset
              ON dataset.provider_dataset_id = entity.provider_dataset_id
            JOIN provider_sync.source_records AS record
              ON record.source_record_key = head.current_source_record_key
            WHERE entity.source_entity_key = head.source_entity_key
        $$;


ALTER FUNCTION provider_sync.notice_lineage_key(head provider_sync.source_entity_heads) OWNER TO ktm_feature_schema_owner;

--
-- Name: reject_active_feature_update_request_member_overlap(); Type: FUNCTION; Schema: provider_sync; Owner: ktm_feature_schema_owner
--

CREATE FUNCTION provider_sync.reject_active_feature_update_request_member_overlap() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog'
    AS $$
        BEGIN
            PERFORM provider_sync.assert_feature_update_request_member_available(
                NEW.request_id, NEW.provider_dataset_id, NEW.sync_scope, NEW.operation_key
            );
            RETURN NEW;
        END;
        $$;


ALTER FUNCTION provider_sync.reject_active_feature_update_request_member_overlap() OWNER TO ktm_feature_schema_owner;

--
-- Name: reject_feature_update_request_activation_overlap(); Type: FUNCTION; Schema: provider_sync; Owner: ktm_feature_schema_owner
--

CREATE FUNCTION provider_sync.reject_feature_update_request_activation_overlap() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog'
    AS $$
        DECLARE request_uuid uuid;
            old_is_active boolean;
            new_is_active boolean;
        BEGIN
            SELECT request.request_id INTO request_uuid
            FROM ops.feature_update_requests AS request
            WHERE request.job_id = NEW.job_id;
            IF NOT FOUND THEN
                RETURN NEW;
            END IF;

            old_is_active := OLD.status IN ('queued', 'running')
                AND OLD.quarantined_at IS NULL;
            new_is_active := NEW.status IN ('queued', 'running')
                AND NEW.quarantined_at IS NULL;
            IF old_is_active OR new_is_active THEN
                PERFORM provider_sync.lock_feature_update_request_member_scopes(request_uuid);
            END IF;
            IF new_is_active THEN
                PERFORM provider_sync.assert_feature_update_request_members_active(request_uuid);
                PERFORM provider_sync.assert_feature_update_request_membership_available(
                    request_uuid
                );
            END IF;
            RETURN NEW;
        END;
        $$;


ALTER FUNCTION provider_sync.reject_feature_update_request_activation_overlap() OWNER TO ktm_feature_schema_owner;

--
-- Name: reject_inactive_curated_source_dataset(); Type: FUNCTION; Schema: provider_sync; Owner: ktm_feature_schema_owner
--

CREATE FUNCTION provider_sync.reject_inactive_curated_source_dataset() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog'
    AS $$
        BEGIN
            IF TG_OP = 'UPDATE' AND OLD.source_id IS DISTINCT FROM NEW.source_id THEN
                RAISE EXCEPTION 'curated source ownership is immutable'
                    USING ERRCODE = '23514',
                        CONSTRAINT = 'ck_curated_source_rule_ownership_immutable';
            END IF;
            -- `source_id` has a non-deferrable ON DELETE CASCADE FK. Once the source
            -- row disappeared, this is the FK cascade, not a standalone child write.
            IF TG_OP = 'DELETE' AND NOT EXISTS (
                SELECT 1 FROM feature.curated_sources WHERE source_id = OLD.source_id
            ) THEN RETURN OLD; END IF;
            IF TG_OP <> 'INSERT' THEN
                PERFORM provider_sync.assert_active_curated_source_dataset(OLD.source_id);
            END IF;
            IF TG_OP <> 'DELETE' THEN
                PERFORM provider_sync.assert_active_curated_source_dataset(NEW.source_id);
            END IF;
            IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
            RETURN NEW;
        END;
        $$;


ALTER FUNCTION provider_sync.reject_inactive_curated_source_dataset() OWNER TO ktm_feature_schema_owner;

--
-- Name: reject_inactive_feature_update_request_dataset_membership(); Type: FUNCTION; Schema: provider_sync; Owner: ktm_feature_schema_owner
--

CREATE FUNCTION provider_sync.reject_inactive_feature_update_request_dataset_membership() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog'
    AS $$
        DECLARE target_dataset_id bigint :=
            COALESCE(NEW.provider_dataset_id, OLD.provider_dataset_id);
            target_scope text := COALESCE(NEW.sync_scope, OLD.sync_scope);
            target_operation_key text := COALESCE(NEW.operation_key, OLD.operation_key);
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM provider_sync.provider_dataset_operation_scopes AS scope
                JOIN provider_sync.provider_dataset_operations AS operation
                  ON operation.provider_dataset_id = scope.provider_dataset_id
                 AND operation.operation_key = scope.operation_key
                 AND operation.operation_kind = scope.operation_kind
                JOIN provider_sync.provider_datasets AS dataset
                  ON dataset.provider_dataset_id = scope.provider_dataset_id
                WHERE scope.provider_dataset_id = target_dataset_id
                  AND scope.sync_scope = target_scope
                  AND scope.operation_key = target_operation_key
                  AND dataset.is_active
                  AND operation.is_enabled
            ) THEN
                RAISE EXCEPTION 'inactive dataset member cannot receive update request writes'
                    USING ERRCODE = '23514',
                        CONSTRAINT = 'ck_provider_dataset_active_write';
            END IF;
            IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
            RETURN NEW;
        END;
        $$;


ALTER FUNCTION provider_sync.reject_inactive_feature_update_request_dataset_membership() OWNER TO ktm_feature_schema_owner;

--
-- Name: reject_inactive_feature_update_request_members(); Type: FUNCTION; Schema: provider_sync; Owner: ktm_feature_schema_owner
--

CREATE FUNCTION provider_sync.reject_inactive_feature_update_request_members() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog'
    AS $$
        BEGIN
            PERFORM provider_sync.assert_feature_update_request_members_active(OLD.request_id);
            IF TG_OP = 'DELETE' THEN
                RETURN OLD;
            END IF;
            RETURN NEW;
        END;
        $$;


ALTER FUNCTION provider_sync.reject_inactive_feature_update_request_members() OWNER TO ktm_feature_schema_owner;

--
-- Name: reject_inactive_import_job_dataset(); Type: FUNCTION; Schema: provider_sync; Owner: ktm_feature_schema_owner
--

CREATE FUNCTION provider_sync.reject_inactive_import_job_dataset() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog'
    AS $$
        BEGIN
            IF TG_OP = 'UPDATE'
               AND (OLD.job_id, OLD.import_job_dataset_id)
                   IS DISTINCT FROM (NEW.job_id, NEW.import_job_dataset_id) THEN
                RAISE EXCEPTION 'import job event ownership is immutable'
                    USING ERRCODE = '23514',
                        CONSTRAINT = 'ck_import_job_event_ownership_immutable';
            END IF;
            IF TG_OP <> 'INSERT' THEN
                PERFORM provider_sync.assert_import_job_event_member(
                    OLD.job_id, OLD.import_job_dataset_id
                );
            END IF;
            IF TG_OP <> 'DELETE' THEN
                PERFORM provider_sync.assert_import_job_event_member(
                    NEW.job_id, NEW.import_job_dataset_id
                );
            END IF;
            IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
            RETURN NEW;
        END;
        $$;


ALTER FUNCTION provider_sync.reject_inactive_import_job_dataset() OWNER TO ktm_feature_schema_owner;

--
-- Name: reject_inactive_import_job_dataset_membership(); Type: FUNCTION; Schema: provider_sync; Owner: ktm_feature_schema_owner
--

CREATE FUNCTION provider_sync.reject_inactive_import_job_dataset_membership() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog'
    AS $$
        DECLARE target_dataset_id bigint :=
            COALESCE(NEW.provider_dataset_id, OLD.provider_dataset_id);
            target_scope text := COALESCE(NEW.sync_scope, OLD.sync_scope);
            target_operation_key text := COALESCE(NEW.operation_key, OLD.operation_key);
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM provider_sync.provider_dataset_operation_scopes AS scope
                JOIN provider_sync.provider_dataset_operations AS operation
                  ON operation.provider_dataset_id = scope.provider_dataset_id
                 AND operation.operation_key = scope.operation_key
                 AND operation.operation_kind = scope.operation_kind
                JOIN provider_sync.provider_datasets AS dataset
                  ON dataset.provider_dataset_id = scope.provider_dataset_id
                WHERE scope.provider_dataset_id = target_dataset_id
                  AND scope.sync_scope = target_scope
                  AND scope.operation_key = target_operation_key
                  AND dataset.is_active
                  AND operation.is_enabled
            ) THEN
                RAISE EXCEPTION 'inactive dataset member cannot receive import job writes'
                    USING ERRCODE = '23514',
                        CONSTRAINT = 'ck_provider_dataset_active_write';
            END IF;
            IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
            RETURN NEW;
        END;
        $$;


ALTER FUNCTION provider_sync.reject_inactive_import_job_dataset_membership() OWNER TO ktm_feature_schema_owner;

--
-- Name: reject_inactive_import_job_members(); Type: FUNCTION; Schema: provider_sync; Owner: ktm_feature_schema_owner
--

CREATE FUNCTION provider_sync.reject_inactive_import_job_members() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog'
    AS $$
        BEGIN
            PERFORM provider_sync.assert_import_job_members_active(OLD.job_id);
            IF TG_OP = 'DELETE' THEN
                RETURN OLD;
            END IF;
            RETURN NEW;
        END;
        $$;


ALTER FUNCTION provider_sync.reject_inactive_import_job_members() OWNER TO ktm_feature_schema_owner;

--
-- Name: reject_inactive_integrity_observation_scope(); Type: FUNCTION; Schema: provider_sync; Owner: ktm_feature_schema_owner
--

CREATE FUNCTION provider_sync.reject_inactive_integrity_observation_scope() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog'
    AS $$
        BEGIN
            IF TG_OP = 'UPDATE'
               AND OLD.integrity_observation_scope_id
                   IS DISTINCT FROM NEW.integrity_observation_scope_id THEN
                RAISE EXCEPTION 'integrity observation ownership is immutable'
                    USING ERRCODE = '23514',
                        CONSTRAINT = 'ck_integrity_observation_ownership_immutable';
            END IF;
            -- See the notice lineage equivalent: the non-deferrable ON DELETE CASCADE
            -- FK makes an absent parent an unambiguous referential-action DELETE.
            IF TG_OP = 'DELETE' AND NOT EXISTS (
                SELECT 1 FROM ops.integrity_observation_scopes
                WHERE integrity_observation_scope_id = OLD.integrity_observation_scope_id
            ) THEN RETURN OLD; END IF;
            IF TG_OP <> 'INSERT' THEN
                PERFORM provider_sync.assert_active_integrity_observation_scope(
                    OLD.integrity_observation_scope_id
                );
            END IF;
            IF TG_OP <> 'DELETE' THEN
                PERFORM provider_sync.assert_active_integrity_observation_scope(
                    NEW.integrity_observation_scope_id
                );
            END IF;
            IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
            RETURN NEW;
        END;
        $$;


ALTER FUNCTION provider_sync.reject_inactive_integrity_observation_scope() OWNER TO ktm_feature_schema_owner;

--
-- Name: reject_inactive_notice_lifecycle_scope(); Type: FUNCTION; Schema: provider_sync; Owner: ktm_feature_schema_owner
--

CREATE FUNCTION provider_sync.reject_inactive_notice_lifecycle_scope() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog'
    AS $$
        BEGIN
            IF TG_OP = 'UPDATE'
               AND OLD.notice_lifecycle_scope_id
                   IS DISTINCT FROM NEW.notice_lifecycle_scope_id THEN
                RAISE EXCEPTION 'notice lineage ownership is immutable'
                    USING ERRCODE = '23514',
                        CONSTRAINT = 'ck_notice_lineage_ownership_immutable';
            END IF;
            -- The scope row has already been removed when this DELETE comes from the
            -- declared FK action. A standalone child DELETE cannot observe that
            -- state: its non-deferrable FK requires the parent to exist. Therefore a
            -- missing parent is precisely the active parent cascade path; checking it
            -- through the normal indirect lookup would misclassify it as inactive.
            IF TG_OP = 'DELETE' AND NOT EXISTS (
                SELECT 1 FROM provider_sync.notice_lifecycle_scopes
                WHERE notice_lifecycle_scope_id = OLD.notice_lifecycle_scope_id
            ) THEN RETURN OLD; END IF;
            IF TG_OP <> 'INSERT' THEN
                PERFORM provider_sync.assert_active_notice_lifecycle_scope(
                    OLD.notice_lifecycle_scope_id
                );
            END IF;
            IF TG_OP <> 'DELETE' THEN
                PERFORM provider_sync.assert_active_notice_lifecycle_scope(
                    NEW.notice_lifecycle_scope_id
                );
            END IF;
            IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
            RETURN NEW;
        END;
        $$;


ALTER FUNCTION provider_sync.reject_inactive_notice_lifecycle_scope() OWNER TO ktm_feature_schema_owner;

--
-- Name: reject_inactive_offline_upload_membership(); Type: FUNCTION; Schema: provider_sync; Owner: ktm_feature_schema_owner
--

CREATE FUNCTION provider_sync.reject_inactive_offline_upload_membership() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog'
    AS $$
        DECLARE target_dataset_id bigint :=
            COALESCE(NEW.provider_dataset_id, OLD.provider_dataset_id);
            target_scope text := COALESCE(NEW.sync_scope, OLD.sync_scope);
            target_operation_key text := COALESCE(NEW.operation_key, OLD.operation_key);
            requires_active boolean;
        BEGIN
            -- offline upload의 identity도 triple이다(operation_key NOT NULL +
            -- fk_offline_uploads_exact_operation_scope). 소유권 비교도 triple이라
            -- operation_key만 갈아끼워 **어느 실행에 결박됐는지**를 조용히 바꿀 수
            -- 없다. 이 검사는 정리 write에서도 면제하지 않는다 — 정리는 행을
            -- 없애거나 상태를 내리는 것이지 소유권을 옮기는 것이 아니다.
            IF TG_OP = 'UPDATE'
               AND (OLD.provider_dataset_id, OLD.sync_scope, OLD.operation_key)
                   IS DISTINCT FROM
                   (NEW.provider_dataset_id, NEW.sync_scope, NEW.operation_key) THEN
                RAISE EXCEPTION 'offline upload membership ownership is immutable'
                    USING ERRCODE = '23514',
                        CONSTRAINT = 'ck_provider_dataset_scope_ownership_immutable';
            END IF;
            -- 활성 검사는 **새 작업을 여는 write**에만 건다: INSERT와,
            -- 'validating', 'loading'로 들어가거나 머무는 UPDATE.
            --
            -- 0091은 이 검사를 DELETE에도 걸었다. 그래서 dataset을 비활성화하거나
            -- operation을 disable하면 그 membership에 결박된 기존 upload 행이
            -- UPDATE도 DELETE도 안 되는 상태로 굳었고, FK ``ON DELETE RESTRICT``가
            -- 상위 행 삭제까지 막아 운영자에게 탈출 경로가 없었다. 가드의 목적은
            -- 비활성 membership에 **새 실행을 거는 것**을 막는 것이지 이미 있는
            -- 행의 정리를 막는 것이 아니다.
            --
            -- 정리 UPDATE까지 함께 허용해야 하는 이유: ``deleting``으로의 전이는
            -- ``OFFLINE_UPLOAD_DELETABLE_STATES``(= 진행 중이 아닌 상태)에서만
            -- 되므로, ``validating``/``loading``/``uploading``에 있던 행은 종료
            -- 상태로 내려오지 못하면 DELETE 예외만으로는 여전히 잠긴다.
            IF TG_OP = 'INSERT' THEN
                requires_active := true;
            ELSIF TG_OP = 'UPDATE' THEN
                requires_active := NEW.status IN ('validating', 'loading');
            ELSE
                requires_active := false;
            END IF;
            IF requires_active AND NOT EXISTS (
                SELECT 1
                FROM provider_sync.provider_dataset_operation_scopes AS scope
                JOIN provider_sync.provider_dataset_operations AS operation
                  ON operation.provider_dataset_id = scope.provider_dataset_id
                 AND operation.operation_key = scope.operation_key
                 AND operation.operation_kind = scope.operation_kind
                JOIN provider_sync.provider_datasets AS dataset
                  ON dataset.provider_dataset_id = scope.provider_dataset_id
                WHERE scope.provider_dataset_id = target_dataset_id
                  AND scope.sync_scope = target_scope
                  AND scope.operation_key = target_operation_key
                  AND dataset.is_active
                  AND operation.is_enabled
            ) THEN
                RAISE EXCEPTION 'dataset scope is absent or disabled for normal writes'
                    USING ERRCODE = '23514',
                        CONSTRAINT = 'ck_provider_dataset_scope_active_write';
            END IF;
            IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
            RETURN NEW;
        END;
        $$;


ALTER FUNCTION provider_sync.reject_inactive_offline_upload_membership() OWNER TO ktm_feature_schema_owner;

--
-- Name: reject_inactive_provider_dataset(); Type: FUNCTION; Schema: provider_sync; Owner: ktm_feature_schema_owner
--

CREATE FUNCTION provider_sync.reject_inactive_provider_dataset() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog'
    AS $$
        BEGIN
            IF TG_OP = 'UPDATE'
               AND OLD.provider_dataset_id IS DISTINCT FROM NEW.provider_dataset_id THEN
                RAISE EXCEPTION 'provider dataset ownership is immutable'
                    USING ERRCODE = '23514',
                        CONSTRAINT = 'ck_provider_dataset_ownership_immutable';
            END IF;
            -- DELETE는 새 실행을 거는 write가 아니라 정리다. 행을 없애는 것이
            -- 비활성 dataset에 새 작업을 기록하지 않으므로 OLD쪽 활성 검사를
            -- 건너뛴다. 참조 무결성은 FK RESTRICT 사슬이 그대로 지킨다.
            IF TG_OP = 'UPDATE' THEN
                PERFORM provider_sync.assert_active_provider_dataset(OLD.provider_dataset_id);
            END IF;
            IF TG_OP <> 'DELETE' THEN
                PERFORM provider_sync.assert_active_provider_dataset(NEW.provider_dataset_id);
            END IF;
            IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
            RETURN NEW;
        END;
        $$;


ALTER FUNCTION provider_sync.reject_inactive_provider_dataset() OWNER TO ktm_feature_schema_owner;

--
-- Name: reject_inactive_source_entity_dataset(); Type: FUNCTION; Schema: provider_sync; Owner: ktm_feature_schema_owner
--

CREATE FUNCTION provider_sync.reject_inactive_source_entity_dataset() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog'
    AS $$
        BEGIN
            IF TG_OP = 'UPDATE'
               AND OLD.source_entity_key IS DISTINCT FROM NEW.source_entity_key THEN
                RAISE EXCEPTION 'source entity ownership is immutable'
                    USING ERRCODE = '23514',
                        CONSTRAINT = 'ck_source_entity_ownership_immutable';
            END IF;
            IF TG_OP <> 'INSERT' THEN
                PERFORM provider_sync.assert_active_source_entity_dataset(OLD.source_entity_key);
            END IF;
            IF TG_OP <> 'DELETE' THEN
                PERFORM provider_sync.assert_active_source_entity_dataset(NEW.source_entity_key);
            END IF;
            IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
            RETURN NEW;
        END;
        $$;


ALTER FUNCTION provider_sync.reject_inactive_source_entity_dataset() OWNER TO ktm_feature_schema_owner;

--
-- Name: reject_inactive_sync_state_operation(); Type: FUNCTION; Schema: provider_sync; Owner: ktm_feature_schema_owner
--

CREATE FUNCTION provider_sync.reject_inactive_sync_state_operation() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog'
    AS $$
        DECLARE target_dataset_id bigint :=
            COALESCE(NEW.provider_dataset_id, OLD.provider_dataset_id);
            target_scope text := COALESCE(NEW.sync_scope, OLD.sync_scope);
            target_operation_key text := COALESCE(NEW.operation_key, OLD.operation_key);
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM provider_sync.provider_dataset_operation_scopes AS scope
                JOIN provider_sync.provider_dataset_operations AS operation
                  ON operation.provider_dataset_id = scope.provider_dataset_id
                 AND operation.operation_key = scope.operation_key
                 AND operation.operation_kind = scope.operation_kind
                JOIN provider_sync.provider_datasets AS dataset
                  ON dataset.provider_dataset_id = scope.provider_dataset_id
                WHERE scope.provider_dataset_id = target_dataset_id
                  AND scope.sync_scope = target_scope
                  AND scope.operation_key = target_operation_key
                  AND scope.operation_kind = 'refresh'
                  AND dataset.is_active
                  AND operation.is_enabled
            ) THEN
                RAISE EXCEPTION 'inactive refresh operation cannot receive sync state writes'
                    USING ERRCODE = '23514',
                        CONSTRAINT = 'ck_provider_dataset_active_write';
            END IF;
            IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
            RETURN NEW;
        END;
        $$;


ALTER FUNCTION provider_sync.reject_inactive_sync_state_operation() OWNER TO ktm_feature_schema_owner;

--
-- Name: reject_managed_file_dataset_rebinding(); Type: FUNCTION; Schema: provider_sync; Owner: ktm_feature_schema_owner
--

CREATE FUNCTION provider_sync.reject_managed_file_dataset_rebinding() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog'
    AS $$
        BEGIN
            -- NULL -> value is the first binding, not a rebinding: the row had no
            -- owner to move away from.  file_registry._UPSERT_SQL implements that
            -- transition on re-registration, so rejecting it would freeze rows that
            -- were registered before their owning offline upload row existed.
            -- value -> other value and value -> NULL stay rejected.
            IF TG_OP = 'UPDATE'
               AND OLD.provider_dataset_id IS NOT NULL
               AND OLD.provider_dataset_id IS DISTINCT FROM NEW.provider_dataset_id THEN
                RAISE EXCEPTION 'provider dataset ownership is immutable'
                    USING ERRCODE = '23514',
                        CONSTRAINT = 'ck_provider_dataset_ownership_immutable';
            END IF;
            IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
            RETURN NEW;
        END;
        $$;


ALTER FUNCTION provider_sync.reject_managed_file_dataset_rebinding() OWNER TO ktm_feature_schema_owner;

--
-- Name: reject_provider_dataset_identity_update(); Type: FUNCTION; Schema: provider_sync; Owner: ktm_feature_schema_owner
--

CREATE FUNCTION provider_sync.reject_provider_dataset_identity_update() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog'
    AS $$
        BEGIN
            IF NEW.provider IS DISTINCT FROM OLD.provider
               OR NEW.dataset_key IS DISTINCT FROM OLD.dataset_key THEN
                RAISE EXCEPTION 'provider dataset identity is immutable (ADR-088)'
                    USING ERRCODE = 'P0001';
            END IF;
            RETURN NEW;
        END;
        $$;


ALTER FUNCTION provider_sync.reject_provider_dataset_identity_update() OWNER TO ktm_feature_schema_owner;

--
-- Name: reject_source_record_update(); Type: FUNCTION; Schema: provider_sync; Owner: ktm_feature_schema_owner
--

CREATE FUNCTION provider_sync.reject_source_record_update() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog'
    AS $$
        BEGIN
            RAISE EXCEPTION 'provider_sync.source_records is immutable (ADR-069)'
                USING ERRCODE = '23514', CONSTRAINT = 'ck_source_records_immutable';
        END;
        $$;


ALTER FUNCTION provider_sync.reject_source_record_update() OWNER TO ktm_feature_schema_owner;

--
-- Name: set_source_entity_head_lineage_key(); Type: FUNCTION; Schema: provider_sync; Owner: ktm_feature_schema_owner
--

CREATE FUNCTION provider_sync.set_source_entity_head_lineage_key() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        BEGIN
            NEW.lineage_key := provider_sync.notice_lineage_key(NEW);
            RETURN NEW;
        END
        $$;


ALTER FUNCTION provider_sync.set_source_entity_head_lineage_key() OWNER TO ktm_feature_schema_owner;

--
-- Name: touch_provider_dataset(); Type: FUNCTION; Schema: provider_sync; Owner: ktm_feature_schema_owner
--

CREATE FUNCTION provider_sync.touch_provider_dataset() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog'
    AS $$
        BEGIN
            NEW.updated_at := clock_timestamp();
            RETURN NEW;
        END;
        $$;


ALTER FUNCTION provider_sync.touch_provider_dataset() OWNER TO ktm_feature_schema_owner;

--
-- Name: touch_provider_dataset_operation(); Type: FUNCTION; Schema: provider_sync; Owner: ktm_feature_schema_owner
--

CREATE FUNCTION provider_sync.touch_provider_dataset_operation() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog'
    AS $$
        BEGIN
            NEW.updated_at := clock_timestamp();
            RETURN NEW;
        END;
        $$;


ALTER FUNCTION provider_sync.touch_provider_dataset_operation() OWNER TO ktm_feature_schema_owner;

--
-- Name: validate_data_integrity_violation_dataset(); Type: FUNCTION; Schema: provider_sync; Owner: ktm_feature_schema_owner
--

CREATE FUNCTION provider_sync.validate_data_integrity_violation_dataset() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog'
    AS $$
        DECLARE new_record_dataset_id bigint; old_record_dataset_id bigint;
        BEGIN
            -- Ownership is the dataset alone. source_record_key is a *pointer* to the
            -- record that currently exhibits the finding, and it must stay mutable:
            -- fk_data_integrity_violations_source_record_key_source_records is
            -- ON DELETE SET NULL (record purge nulls the pointer) and recurrence
            -- upserts re-point it at the newest record for the same dedupe_key.
            -- Re-parenting is still blocked because the dataset agreement check below
            -- runs on every write, so the pointer can only move inside the owning
            -- dataset (or to NULL).
            IF TG_OP = 'UPDATE'
               AND OLD.provider_dataset_id IS DISTINCT FROM NEW.provider_dataset_id THEN
                RAISE EXCEPTION 'integrity violation ownership is immutable'
                    USING ERRCODE = '23514',
                        CONSTRAINT = 'ck_data_integrity_violation_ownership_immutable';
            END IF;
            IF TG_OP <> 'INSERT' THEN
                PERFORM provider_sync.assert_active_provider_dataset(OLD.provider_dataset_id);
                old_record_dataset_id := provider_sync.assert_active_source_record_dataset(
                    OLD.source_record_key
                );
            END IF;
            IF TG_OP <> 'DELETE' THEN
                PERFORM provider_sync.assert_active_provider_dataset(NEW.provider_dataset_id);
                new_record_dataset_id := provider_sync.assert_active_source_record_dataset(
                    NEW.source_record_key
                );
                IF NEW.provider_dataset_id IS NOT NULL
                   AND new_record_dataset_id IS NOT NULL
                   AND NEW.provider_dataset_id <> new_record_dataset_id THEN
                    RAISE EXCEPTION 'integrity violation dataset must match source record dataset'
                        USING ERRCODE = '23514',
                            CONSTRAINT = 'ck_data_integrity_violations_dataset_source_record';
                END IF;
            END IF;
            IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
            RETURN NEW;
        END;
        $$;


ALTER FUNCTION provider_sync.validate_data_integrity_violation_dataset() OWNER TO ktm_feature_schema_owner;

--
-- Name: curated_feature_detail_snapshots; Type: TABLE; Schema: feature; Owner: ktm_feature_schema_owner
--

CREATE TABLE feature.curated_feature_detail_snapshots (
    curated_feature_id uuid NOT NULL,
    content_version integer NOT NULL,
    etag text NOT NULL,
    snapshot jsonb NOT NULL,
    materialized_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_curated_feature_detail_snapshots_snapshot CHECK ((jsonb_typeof(snapshot) = 'object'::text)),
    CONSTRAINT ck_curated_feature_detail_snapshots_version CHECK ((content_version >= 1))
);


ALTER TABLE feature.curated_feature_detail_snapshots OWNER TO ktm_feature_schema_owner;

--
-- Name: curated_features; Type: TABLE; Schema: feature; Owner: ktm_feature_schema_owner
--

CREATE TABLE feature.curated_features (
    curated_feature_id uuid DEFAULT x_extension.gen_random_uuid() NOT NULL,
    theme_id uuid NOT NULL,
    feature_id text NOT NULL,
    source_id uuid NOT NULL,
    source_record_key text,
    curation_status text DEFAULT 'candidate'::text NOT NULL,
    selection_origin text DEFAULT 'source_rule'::text NOT NULL,
    selected_by text,
    selected_at timestamp with time zone,
    rejected_by text,
    rejected_at timestamp with time zone,
    rejection_reason text,
    rank_score numeric(10,4) DEFAULT 0 NOT NULL,
    display_title text,
    display_summary text,
    curation_relation text DEFAULT 'nearby_option'::text NOT NULL,
    reuse_policy text DEFAULT 'manual_review'::text NOT NULL,
    content_version integer DEFAULT 1 NOT NULL,
    metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    archived_at timestamp with time zone,
    operator_updated_by text,
    operator_updated_at timestamp with time zone,
    CONSTRAINT ck_curated_features_content_version CHECK ((content_version >= 1)),
    CONSTRAINT ck_curated_features_curation_relation CHECK ((curation_relation = ANY (ARRAY['primary_stop'::text, 'food_stop'::text, 'cafe_stop'::text, 'bookstore_stop'::text, 'nearby_option'::text, 'accessibility_support'::text, 'pet_support'::text, 'family_support'::text, 'theme_area_anchor'::text]))),
    CONSTRAINT ck_curated_features_metadata CHECK ((jsonb_typeof(metadata) = 'object'::text)),
    CONSTRAINT ck_curated_features_reuse_policy CHECK ((reuse_policy = ANY (ARRAY['allowed'::text, 'blocked'::text, 'manual_review'::text]))),
    CONSTRAINT ck_curated_features_selection_origin CHECK ((selection_origin = ANY (ARRAY['source_rule'::text, 'admin'::text, 'external_api'::text]))),
    CONSTRAINT ck_curated_features_status CHECK ((curation_status = ANY (ARRAY['candidate'::text, 'curated'::text, 'rejected'::text, 'archived'::text])))
);


ALTER TABLE feature.curated_features OWNER TO ktm_feature_schema_owner;

--
-- Name: curated_source_rules; Type: TABLE; Schema: feature; Owner: ktm_feature_schema_owner
--

CREATE TABLE feature.curated_source_rules (
    rule_id uuid DEFAULT x_extension.gen_random_uuid() NOT NULL,
    theme_id uuid NOT NULL,
    source_id uuid NOT NULL,
    place_kind text,
    category text,
    region_scope jsonb DEFAULT '{}'::jsonb NOT NULL,
    default_action text DEFAULT 'candidate'::text NOT NULL,
    priority integer DEFAULT 0 NOT NULL,
    enabled boolean DEFAULT true NOT NULL,
    metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    detail_selector jsonb,
    CONSTRAINT ck_curated_source_rules_action CHECK ((default_action = ANY (ARRAY['candidate'::text, 'curated'::text, 'ignore'::text]))),
    CONSTRAINT ck_curated_source_rules_detail_selector CHECK (((detail_selector IS NULL) OR (jsonb_typeof(detail_selector) = 'object'::text))),
    CONSTRAINT ck_curated_source_rules_region_scope CHECK ((jsonb_typeof(region_scope) = 'object'::text))
);


ALTER TABLE feature.curated_source_rules OWNER TO ktm_feature_schema_owner;

--
-- Name: curated_sources; Type: TABLE; Schema: feature; Owner: ktm_feature_schema_owner
--

CREATE TABLE feature.curated_sources (
    source_id uuid DEFAULT x_extension.gen_random_uuid() NOT NULL,
    source_name text NOT NULL,
    source_url text,
    source_kind text NOT NULL,
    license text,
    update_cycle text DEFAULT 'unknown'::text NOT NULL,
    last_source_modified_at date,
    last_checked_at timestamp with time zone,
    next_expected_at date,
    row_count integer,
    freshness_note text,
    provider_status text DEFAULT 'implemented'::text NOT NULL,
    metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    provider_dataset_id bigint NOT NULL,
    CONSTRAINT ck_curated_sources_provider_status CHECK ((provider_status = ANY (ARRAY['implemented'::text, 'provider_needed'::text, 'manual_only'::text, 'deprecated'::text]))),
    CONSTRAINT ck_curated_sources_row_count CHECK (((row_count IS NULL) OR (row_count >= 0))),
    CONSTRAINT ck_curated_sources_source_kind CHECK ((source_kind = ANY (ARRAY['openapi'::text, 'filedata'::text, 'standard'::text, 'internal'::text, 'manual'::text]))),
    CONSTRAINT ck_curated_sources_update_cycle CHECK ((update_cycle = ANY (ARRAY['realtime'::text, 'daily'::text, 'weekly'::text, 'monthly'::text, 'annual'::text, 'one_time'::text, 'unknown'::text])))
);


ALTER TABLE feature.curated_sources OWNER TO ktm_feature_schema_owner;

--
-- Name: curated_themes; Type: TABLE; Schema: feature; Owner: ktm_feature_schema_owner
--

CREATE TABLE feature.curated_themes (
    theme_id uuid DEFAULT x_extension.gen_random_uuid() NOT NULL,
    theme_slug text NOT NULL,
    theme_name text NOT NULL,
    theme_description text DEFAULT ''::text NOT NULL,
    theme_group text NOT NULL,
    default_curated boolean DEFAULT false NOT NULL,
    visibility text DEFAULT 'admin_only'::text NOT NULL,
    metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_curated_themes_visibility CHECK ((visibility = ANY (ARRAY['admin_only'::text, 'public'::text])))
);


ALTER TABLE feature.curated_themes OWNER TO ktm_feature_schema_owner;

--
-- Name: curation_collections; Type: TABLE; Schema: feature; Owner: ktm_feature_schema_owner
--

CREATE TABLE feature.curation_collections (
    collection_id uuid DEFAULT x_extension.gen_random_uuid() NOT NULL,
    collection_key text NOT NULL,
    theme_id uuid NOT NULL,
    source_id uuid,
    title text NOT NULL,
    edition_key text DEFAULT ''::text NOT NULL,
    description text,
    status text DEFAULT 'draft'::text NOT NULL,
    visibility text DEFAULT 'admin_only'::text NOT NULL,
    metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_by text,
    updated_by text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    archived_at timestamp with time zone,
    CONSTRAINT ck_curation_collections_key CHECK ((btrim(collection_key) <> ''::text)),
    CONSTRAINT ck_curation_collections_metadata CHECK ((jsonb_typeof(metadata) = 'object'::text)),
    CONSTRAINT ck_curation_collections_status CHECK ((status = ANY (ARRAY['draft'::text, 'published'::text, 'archived'::text]))),
    CONSTRAINT ck_curation_collections_title CHECK ((btrim(title) <> ''::text)),
    CONSTRAINT ck_curation_collections_visibility CHECK ((visibility = ANY (ARRAY['admin_only'::text, 'public'::text])))
);


ALTER TABLE feature.curation_collections OWNER TO ktm_feature_schema_owner;

--
-- Name: curation_import_batches; Type: TABLE; Schema: feature; Owner: ktm_feature_schema_owner
--

CREATE TABLE feature.curation_import_batches (
    import_batch_id uuid DEFAULT x_extension.gen_random_uuid() NOT NULL,
    content_sha256 text NOT NULL,
    batch_kind text NOT NULL,
    row_count integer NOT NULL,
    actor text NOT NULL,
    metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
    imported_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_curation_import_batches_ck_curation_import_batches_actor CHECK (((actor = btrim(actor)) AND (actor <> ''::text))),
    CONSTRAINT ck_curation_import_batches_ck_curation_import_batches_kind CHECK ((batch_kind = ANY (ARRAY['csv_upload'::text, 'normalized_rows'::text, 'forward_recovery'::text]))),
    CONSTRAINT ck_curation_import_batches_ck_curation_import_batches_metadata CHECK ((jsonb_typeof(metadata) = 'object'::text)),
    CONSTRAINT ck_curation_import_batches_ck_curation_import_batches_row_count CHECK ((row_count >= 0)),
    CONSTRAINT ck_curation_import_batches_ck_curation_import_batches_sha256 CHECK ((content_sha256 ~ '^[0-9a-f]{64}$'::text))
);


ALTER TABLE feature.curation_import_batches OWNER TO ktm_feature_schema_owner;

--
-- Name: curation_import_rows; Type: TABLE; Schema: feature; Owner: ktm_feature_schema_owner
--

CREATE TABLE feature.curation_import_rows (
    import_row_id uuid DEFAULT x_extension.gen_random_uuid() NOT NULL,
    import_batch_id uuid NOT NULL,
    curation_item_id uuid NOT NULL,
    row_number integer NOT NULL,
    source_row_sha256 text NOT NULL,
    row_payload jsonb NOT NULL,
    provenance jsonb DEFAULT '{}'::jsonb NOT NULL,
    imported_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_curation_import_rows_ck_curation_import_rows_payload CHECK ((jsonb_typeof(row_payload) = 'object'::text)),
    CONSTRAINT ck_curation_import_rows_ck_curation_import_rows_provenance CHECK ((jsonb_typeof(provenance) = 'object'::text)),
    CONSTRAINT ck_curation_import_rows_ck_curation_import_rows_row_number CHECK ((row_number > 0)),
    CONSTRAINT ck_curation_import_rows_ck_curation_import_rows_sha256 CHECK ((source_row_sha256 ~ '^[0-9a-f]{64}$'::text))
);


ALTER TABLE feature.curation_import_rows OWNER TO ktm_feature_schema_owner;

--
-- Name: curation_items; Type: TABLE; Schema: feature; Owner: ktm_feature_schema_owner
--

CREATE TABLE feature.curation_items (
    curation_item_id uuid DEFAULT x_extension.gen_random_uuid() NOT NULL,
    collection_id uuid NOT NULL,
    feature_id text,
    source_record_key text,
    external_item_id text NOT NULL,
    place_name text NOT NULL,
    address_hint text,
    status text DEFAULT 'candidate'::text NOT NULL,
    sort_order integer DEFAULT 0 NOT NULL,
    item_title text,
    item_summary text,
    curation_relation text DEFAULT 'nearby_option'::text NOT NULL,
    reuse_policy text DEFAULT 'manual_review'::text NOT NULL,
    metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_by text,
    updated_by text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    archived_at timestamp with time zone,
    source_present boolean DEFAULT true NOT NULL,
    source_updated_at timestamp with time zone DEFAULT now() NOT NULL,
    operator_updated_by text,
    operator_updated_at timestamp with time zone,
    legacy_projection_id uuid,
    external_component_id text DEFAULT 'primary'::text NOT NULL,
    current_import_row_id uuid,
    accepted_link_decision_id uuid,
    CONSTRAINT ck_curation_items_external_component_id_canonical CHECK (((external_component_id <> ''::text) AND (external_component_id = btrim(external_component_id)))),
    CONSTRAINT ck_curation_items_external_id CHECK ((btrim(external_item_id) <> ''::text)),
    CONSTRAINT ck_curation_items_metadata CHECK ((jsonb_typeof(metadata) = 'object'::text)),
    CONSTRAINT ck_curation_items_place_name CHECK ((btrim(place_name) <> ''::text)),
    CONSTRAINT ck_curation_items_relation CHECK ((curation_relation = ANY (ARRAY['primary_stop'::text, 'food_stop'::text, 'cafe_stop'::text, 'bookstore_stop'::text, 'nearby_option'::text, 'accessibility_support'::text, 'pet_support'::text, 'family_support'::text, 'theme_area_anchor'::text]))),
    CONSTRAINT ck_curation_items_reuse_policy CHECK ((reuse_policy = ANY (ARRAY['allowed'::text, 'blocked'::text, 'manual_review'::text]))),
    CONSTRAINT ck_curation_items_sort_order CHECK ((sort_order >= 0)),
    CONSTRAINT ck_curation_items_status CHECK ((status = ANY (ARRAY['candidate'::text, 'included'::text, 'rejected'::text, 'archived'::text])))
);


ALTER TABLE feature.curation_items OWNER TO ktm_feature_schema_owner;

--
-- Name: curation_link_decisions; Type: TABLE; Schema: feature; Owner: ktm_feature_schema_owner
--

CREATE TABLE feature.curation_link_decisions (
    decision_id uuid DEFAULT x_extension.gen_random_uuid() NOT NULL,
    curation_item_id uuid NOT NULL,
    feature_id text NOT NULL,
    import_row_id uuid,
    decision_kind text NOT NULL,
    match_basis text NOT NULL,
    resolver_version text NOT NULL,
    evidence jsonb DEFAULT '{}'::jsonb NOT NULL,
    actor text NOT NULL,
    decided_at timestamp with time zone DEFAULT now() NOT NULL,
    supersedes_decision_id uuid,
    CONSTRAINT ck_curation_link_decisions_ck_curation_link_decisions_actor CHECK (((actor = btrim(actor)) AND (actor <> ''::text))),
    CONSTRAINT ck_curation_link_decisions_ck_curation_link_decisions_basis CHECK ((match_basis = ANY (ARRAY['csv_explicit_feature_id'::text, 'admin_review'::text, 'legacy_unattributed'::text, 'forward_recovery'::text, 'source_rule'::text]))),
    CONSTRAINT ck_curation_link_decisions_ck_curation_link_decisions_evidence CHECK ((jsonb_typeof(evidence) = 'object'::text)),
    CONSTRAINT ck_curation_link_decisions_ck_curation_link_decisions_kind CHECK ((decision_kind = ANY (ARRAY['accepted'::text, 'revoked'::text]))),
    CONSTRAINT ck_curation_link_decisions_ck_curation_link_decisions_n_5a74 CHECK ((supersedes_decision_id IS DISTINCT FROM decision_id)),
    CONSTRAINT ck_curation_link_decisions_ck_curation_link_decisions_resolver CHECK (((resolver_version = btrim(resolver_version)) AND (resolver_version <> ''::text)))
);


ALTER TABLE feature.curation_link_decisions OWNER TO ktm_feature_schema_owner;

--
-- Name: current_price_summary; Type: TABLE; Schema: feature; Owner: ktm_feature_schema_owner
--

CREATE TABLE feature.current_price_summary (
    feature_id text NOT NULL,
    provider_dataset_id bigint NOT NULL,
    price_domain text NOT NULL,
    product_key text NOT NULL,
    price_value_key text NOT NULL,
    summary_run_id bigint NOT NULL,
    projection_kind text DEFAULT 'price'::text NOT NULL,
    receipt_status text DEFAULT 'succeeded'::text NOT NULL,
    CONSTRAINT ck_current_price_summary_projection_kind CHECK ((projection_kind = 'price'::text)),
    CONSTRAINT ck_current_price_summary_receipt_status CHECK ((receipt_status = 'succeeded'::text))
);


ALTER TABLE feature.current_price_summary OWNER TO ktm_feature_schema_owner;

--
-- Name: current_weather_summary; Type: TABLE; Schema: feature; Owner: ktm_feature_schema_owner
--

CREATE TABLE feature.current_weather_summary (
    feature_id text NOT NULL,
    provider_dataset_id bigint NOT NULL,
    weather_domain text NOT NULL,
    forecast_style text NOT NULL,
    metric_key text NOT NULL,
    weather_value_key text NOT NULL,
    summary_run_id bigint NOT NULL,
    selected_at timestamp with time zone NOT NULL,
    refresh_after timestamp with time zone NOT NULL,
    projection_kind text DEFAULT 'weather'::text NOT NULL,
    receipt_status text DEFAULT 'succeeded'::text NOT NULL,
    CONSTRAINT ck_current_weather_summary_projection_kind CHECK ((projection_kind = 'weather'::text)),
    CONSTRAINT ck_current_weather_summary_receipt_status CHECK ((receipt_status = 'succeeded'::text)),
    CONSTRAINT ck_current_weather_summary_refresh_after CHECK ((refresh_after > selected_at))
);


ALTER TABLE feature.current_weather_summary OWNER TO ktm_feature_schema_owner;

--
-- Name: feature_aliases; Type: TABLE; Schema: feature; Owner: ktm_feature_schema_owner
--

CREATE TABLE feature.feature_aliases (
    alias text NOT NULL,
    feature_id text NOT NULL,
    feature_uuid uuid NOT NULL,
    alias_kind text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_feature_aliases_ck_feature_aliases_alias_canonical CHECK (((alias <> ''::text) AND (alias = btrim(alias)))),
    CONSTRAINT ck_feature_aliases_ck_feature_aliases_alias_kind CHECK ((alias_kind = 'legacy_feature_id'::text)),
    CONSTRAINT ck_feature_aliases_ck_feature_aliases_kind_canonical CHECK (((alias_kind <> ''::text) AND (alias_kind = btrim(alias_kind)))),
    CONSTRAINT ck_feature_aliases_legacy_identity CHECK (((alias_kind <> 'legacy_feature_id'::text) OR (alias = feature_id)))
);


ALTER TABLE feature.feature_aliases OWNER TO ktm_feature_schema_owner;

--
-- Name: feature_areas; Type: TABLE; Schema: feature; Owner: ktm_feature_schema_owner
--

CREATE TABLE feature.feature_areas (
    feature_id character varying NOT NULL,
    feature_uuid uuid NOT NULL,
    kind character varying NOT NULL,
    geom x_extension.geometry(MultiPolygon,4326) NOT NULL,
    area_kind character varying NOT NULL,
    boundary_source character varying,
    area_square_meters numeric,
    regulation_scope character varying,
    administrative_office character varying,
    description text,
    payload jsonb DEFAULT '{}'::jsonb NOT NULL,
    public_ready boolean DEFAULT false NOT NULL,
    CONSTRAINT ck_feature_areas_kind CHECK (((kind)::text = 'area'::text))
);


ALTER TABLE feature.feature_areas OWNER TO ktm_feature_schema_owner;

--
-- Name: feature_base_field_values; Type: TABLE; Schema: feature; Owner: ktm_feature_schema_owner
--

CREATE TABLE feature.feature_base_field_values (
    feature_id text NOT NULL,
    field_path text NOT NULL,
    feature_uuid uuid NOT NULL,
    provider_dataset_id bigint NOT NULL,
    source_entity_key text NOT NULL,
    source_record_key text NOT NULL,
    source_raw_payload_hash text NOT NULL,
    value_json jsonb,
    value_geometry x_extension.geometry(Geometry,4326),
    base_revision bigint NOT NULL,
    observed_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_feature_base_field_values_revision CHECK ((base_revision >= 1)),
    CONSTRAINT ck_feature_base_field_values_single_value CHECK (((value_json IS NULL) <> (value_geometry IS NULL))),
    CONSTRAINT ck_feature_base_field_values_source_hash CHECK ((btrim(source_raw_payload_hash) <> ''::text))
);


ALTER TABLE feature.feature_base_field_values OWNER TO ktm_feature_schema_owner;

--
-- Name: feature_events; Type: TABLE; Schema: feature; Owner: ktm_feature_schema_owner
--

CREATE TABLE feature.feature_events (
    feature_id character varying NOT NULL,
    feature_uuid uuid NOT NULL,
    kind character varying NOT NULL,
    event_kind character varying NOT NULL,
    starts_on date,
    ends_on date,
    timezone character varying DEFAULT 'Asia/Seoul'::character varying NOT NULL,
    opening_hours jsonb,
    venue_name character varying,
    tel character varying,
    content_id character varying,
    content_type_id character varying,
    area_code character varying,
    sigungu_code character varying,
    payload jsonb DEFAULT '{}'::jsonb NOT NULL,
    CONSTRAINT ck_feature_events_kind CHECK (((kind)::text = 'event'::text)),
    CONSTRAINT ck_feature_events_period CHECK (((starts_on IS NULL) OR (ends_on IS NULL) OR (starts_on <= ends_on)))
);


ALTER TABLE feature.feature_events OWNER TO ktm_feature_schema_owner;

--
-- Name: feature_notices; Type: TABLE; Schema: feature; Owner: ktm_feature_schema_owner
--

CREATE TABLE feature.feature_notices (
    feature_id character varying NOT NULL,
    feature_uuid uuid NOT NULL,
    kind character varying NOT NULL,
    notice_type character varying NOT NULL,
    severity smallint,
    valid_start_time timestamp with time zone,
    valid_end_time timestamp with time zone,
    source_agency character varying,
    officer_name character varying,
    payload jsonb DEFAULT '{}'::jsonb NOT NULL,
    CONSTRAINT ck_feature_notices_kind CHECK (((kind)::text = 'notice'::text)),
    CONSTRAINT ck_feature_notices_severity CHECK (((severity IS NULL) OR ((severity >= 0) AND (severity <= 5))))
);


ALTER TABLE feature.feature_notices OWNER TO ktm_feature_schema_owner;

--
-- Name: feature_places; Type: TABLE; Schema: feature; Owner: ktm_feature_schema_owner
--

CREATE TABLE feature.feature_places (
    feature_id character varying NOT NULL,
    feature_uuid uuid NOT NULL,
    kind character varying NOT NULL,
    place_kind character varying NOT NULL,
    phones text[] DEFAULT '{}'::text[] NOT NULL,
    biz_number character varying,
    license_date date,
    business_hours jsonb,
    facility_info jsonb DEFAULT '{}'::jsonb NOT NULL,
    reviews_link jsonb DEFAULT '{}'::jsonb NOT NULL,
    payload jsonb DEFAULT '{}'::jsonb NOT NULL,
    CONSTRAINT ck_feature_places_kind CHECK (((kind)::text = 'place'::text))
);


ALTER TABLE feature.feature_places OWNER TO ktm_feature_schema_owner;

--
-- Name: feature_price_values; Type: TABLE; Schema: feature; Owner: ktm_feature_schema_owner
--

CREATE TABLE feature.feature_price_values (
    price_value_key text NOT NULL,
    feature_id text NOT NULL,
    provider_dataset_id bigint NOT NULL,
    price_domain text NOT NULL,
    product_key text NOT NULL,
    product_name text,
    source_product_key text,
    source_product_name text,
    observed_at timestamp with time zone NOT NULL,
    known_at timestamp with time zone NOT NULL,
    value_number numeric(14,4) NOT NULL,
    unit text DEFAULT 'KRW'::text NOT NULL,
    normalization_version text,
    payload jsonb DEFAULT '{}'::jsonb NOT NULL,
    source_entity_key text NOT NULL,
    source_record_key text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_price_value_nonnegative CHECK ((value_number >= (0)::numeric)),
    CONSTRAINT ck_price_value_payload_object CHECK ((jsonb_typeof(payload) = 'object'::text))
);


ALTER TABLE feature.feature_price_values OWNER TO ktm_feature_schema_owner;

--
-- Name: feature_routes; Type: TABLE; Schema: feature; Owner: ktm_feature_schema_owner
--

CREATE TABLE feature.feature_routes (
    feature_id character varying NOT NULL,
    feature_uuid uuid NOT NULL,
    kind character varying NOT NULL,
    geom x_extension.geometry(MultiLineString,4326) NOT NULL,
    route_type character varying NOT NULL,
    geometry_source character varying,
    geometry_status character varying,
    total_distance_meters numeric,
    expected_duration_minutes integer,
    difficulty character varying,
    begin_name character varying,
    begin_address character varying,
    end_name character varying,
    end_address character varying,
    payload jsonb DEFAULT '{}'::jsonb NOT NULL,
    public_ready boolean DEFAULT false NOT NULL,
    CONSTRAINT ck_feature_routes_kind CHECK (((kind)::text = 'route'::text))
);


ALTER TABLE feature.feature_routes OWNER TO ktm_feature_schema_owner;

--
-- Name: feature_state_transitions; Type: TABLE; Schema: feature; Owner: ktm_feature_schema_owner
--

CREATE TABLE feature.feature_state_transitions (
    transition_id bigint NOT NULL,
    feature_id text NOT NULL,
    feature_uuid uuid NOT NULL,
    from_lifecycle_state text,
    from_publication_state text,
    from_quality_state text,
    to_lifecycle_state text NOT NULL,
    to_publication_state text NOT NULL,
    to_quality_state text NOT NULL,
    transition_kind text NOT NULL,
    reason_code text NOT NULL,
    principal text NOT NULL,
    causation_ref text,
    provider_dataset_id bigint,
    source_entity_key text,
    source_record_key text,
    provider_evidence jsonb,
    occurred_at timestamp with time zone NOT NULL,
    row_revision bigint NOT NULL,
    invoker_role text NOT NULL,
    state_procedure_definer text NOT NULL,
    audit_writer_definer text NOT NULL,
    CONSTRAINT ck_feature_state_transitions_initial_old_tuple CHECK ((((from_lifecycle_state IS NULL) AND (transition_kind = ANY (ARRAY['initial'::text, 'legacy_backfill'::text, 'provider_sync'::text]))) OR ((from_lifecycle_state IS NOT NULL) AND (transition_kind <> ALL (ARRAY['initial'::text, 'legacy_backfill'::text]))))),
    CONSTRAINT ck_feature_state_transitions_kind CHECK ((transition_kind = ANY (ARRAY['initial'::text, 'legacy_backfill'::text, 'provider_sync'::text, 'admin'::text, 'user_request'::text, 'merge'::text, 'quality_validation'::text, 'system'::text]))),
    CONSTRAINT ck_feature_state_transitions_new_tuple CHECK (((to_lifecycle_state = ANY (ARRAY['active'::text, 'retired'::text])) AND (to_publication_state = ANY (ARRAY['draft'::text, 'published'::text, 'suppressed'::text])) AND (to_quality_state = ANY (ARRAY['valid'::text, 'quarantined'::text])) AND ((to_lifecycle_state = 'active'::text) OR (to_publication_state = 'suppressed'::text)))),
    CONSTRAINT ck_feature_state_transitions_old_tuple CHECK ((((from_lifecycle_state IS NULL) AND (from_publication_state IS NULL) AND (from_quality_state IS NULL)) OR ((from_lifecycle_state = ANY (ARRAY['active'::text, 'retired'::text])) AND (from_publication_state = ANY (ARRAY['draft'::text, 'published'::text, 'suppressed'::text])) AND (from_quality_state = ANY (ARRAY['valid'::text, 'quarantined'::text])) AND ((from_lifecycle_state = 'active'::text) OR (from_publication_state = 'suppressed'::text))))),
    CONSTRAINT ck_feature_state_transitions_principal CHECK ((btrim(principal) <> ''::text)),
    CONSTRAINT ck_feature_state_transitions_provider_provenance CHECK ((((transition_kind = 'provider_sync'::text) AND (provider_dataset_id IS NOT NULL) AND (btrim(source_entity_key) <> ''::text) AND (btrim(source_record_key) <> ''::text) AND (jsonb_typeof(provider_evidence) = 'object'::text) AND (jsonb_typeof((provider_evidence -> 'authoritative_receipt'::text)) = 'string'::text) AND (btrim((provider_evidence ->> 'authoritative_receipt'::text)) <> ''::text)) OR ((transition_kind <> 'provider_sync'::text) AND (provider_dataset_id IS NULL) AND (source_entity_key IS NULL) AND (source_record_key IS NULL) AND (provider_evidence IS NULL)))),
    CONSTRAINT ck_feature_state_transitions_reason CHECK ((btrim(reason_code) <> ''::text)),
    CONSTRAINT ck_feature_state_transitions_row_revision CHECK ((row_revision >= 1))
);


ALTER TABLE feature.feature_state_transitions OWNER TO ktm_feature_schema_owner;

--
-- Name: feature_state_transitions_transition_id_seq; Type: SEQUENCE; Schema: feature; Owner: ktm_feature_schema_owner
--

ALTER TABLE feature.feature_state_transitions ALTER COLUMN transition_id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME feature.feature_state_transitions_transition_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: feature_weather_values; Type: TABLE; Schema: feature; Owner: ktm_feature_schema_owner
--

CREATE TABLE feature.feature_weather_values (
    weather_value_key text NOT NULL,
    feature_id text NOT NULL,
    provider_dataset_id bigint NOT NULL,
    weather_domain text NOT NULL,
    forecast_style text NOT NULL,
    timeline_bucket text,
    metric_key text NOT NULL,
    metric_name text,
    source_metric_key text,
    source_metric_name text,
    value_number numeric(14,4),
    value_text text,
    unit text,
    severity text,
    issued_at timestamp with time zone,
    valid_at timestamp with time zone,
    valid_during tstzrange,
    observed_at timestamp with time zone,
    target_at timestamp with time zone NOT NULL,
    known_at timestamp with time zone NOT NULL,
    normalization_version text,
    payload jsonb DEFAULT '{}'::jsonb NOT NULL,
    source_entity_key text NOT NULL,
    source_record_key text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_weather_value_bitemporal_order CHECK (((issued_at IS NULL) OR (issued_at <= known_at))),
    CONSTRAINT ck_weather_value_payload_object CHECK ((jsonb_typeof(payload) = 'object'::text)),
    CONSTRAINT ck_weather_value_present CHECK (((value_number IS NOT NULL) OR (value_text IS NOT NULL))),
    CONSTRAINT ck_weather_value_valid_during_not_empty CHECK (((valid_during IS NULL) OR (NOT isempty(valid_during))))
);


ALTER TABLE feature.feature_weather_values OWNER TO ktm_feature_schema_owner;

--
-- Name: features; Type: TABLE; Schema: feature; Owner: ktm_feature_schema_owner
--

CREATE TABLE feature.features (
    feature_id character varying NOT NULL,
    kind character varying NOT NULL,
    name character varying NOT NULL,
    category character varying NOT NULL,
    coord x_extension.geometry(Point,4326),
    coord_5179 x_extension.geometry(Point,5179) GENERATED ALWAYS AS (
CASE
    WHEN (coord IS NULL) THEN NULL::x_extension.geometry
    ELSE x_extension.st_transform(coord, 5179)
END) STORED,
    address jsonb DEFAULT '{}'::jsonb NOT NULL,
    legal_dong_code character varying(10),
    road_name_code character varying,
    road_address_management_no character varying,
    admin_dong_code character varying(10),
    sido_code character varying(2),
    sigungu_code character varying(5),
    urls jsonb DEFAULT '{}'::jsonb NOT NULL,
    marker_icon character varying,
    marker_color character varying,
    parent_feature_id character varying,
    sibling_group_id uuid,
    raw_refs jsonb DEFAULT '[]'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    coord_precision_digits smallint,
    row_revision bigint DEFAULT 1 NOT NULL,
    feature_uuid uuid NOT NULL,
    lifecycle_state text DEFAULT 'active'::text NOT NULL,
    publication_state text DEFAULT 'published'::text NOT NULL,
    quality_state text DEFAULT 'valid'::text NOT NULL,
    CONSTRAINT ck_features_ck_features_coord_pair CHECK (((coord IS NULL) OR (((x_extension.st_x(coord) >= (124.0)::double precision) AND (x_extension.st_x(coord) <= (132.0)::double precision)) AND ((x_extension.st_y(coord) >= (33.0)::double precision) AND (x_extension.st_y(coord) <= (39.5)::double precision))))),
    CONSTRAINT ck_features_ck_features_coord_precision CHECK ((((coord IS NULL) AND (coord_precision_digits IS NULL)) OR ((coord IS NOT NULL) AND ((coord_precision_digits >= 3) AND (coord_precision_digits <= 8))))),
    CONSTRAINT ck_features_ck_features_kind CHECK (((kind)::text = ANY ((ARRAY['place'::character varying, 'event'::character varying, 'notice'::character varying, 'price'::character varying, 'weather'::character varying, 'route'::character varying, 'area'::character varying])::text[]))),
    CONSTRAINT ck_features_lifecycle_state CHECK ((lifecycle_state = ANY (ARRAY['active'::text, 'retired'::text]))),
    CONSTRAINT ck_features_publication_state CHECK ((publication_state = ANY (ARRAY['draft'::text, 'published'::text, 'suppressed'::text]))),
    CONSTRAINT ck_features_quality_state CHECK ((quality_state = ANY (ARRAY['valid'::text, 'quarantined'::text]))),
    CONSTRAINT ck_features_row_revision CHECK ((row_revision >= 1)),
    CONSTRAINT ck_features_state_tuple CHECK (((lifecycle_state = 'active'::text) OR (publication_state = 'suppressed'::text)))
);


ALTER TABLE feature.features OWNER TO ktm_feature_schema_owner;

--
-- Name: public_features; Type: VIEW; Schema: feature; Owner: ktm_feature_schema_owner
--

CREATE VIEW feature.public_features AS
 SELECT core.feature_id,
    core.feature_uuid,
    core.kind,
    core.name,
    core.category,
    core.coord,
    core.coord_5179,
    core.coord_precision_digits,
    core.address,
    core.legal_dong_code,
    core.road_name_code,
    core.road_address_management_no,
    core.admin_dong_code,
    core.sido_code,
    core.sigungu_code,
    core.urls,
    core.marker_icon,
    core.marker_color,
    core.parent_feature_id,
    core.sibling_group_id,
    core.raw_refs,
    core.created_at,
    core.updated_at,
    core.row_revision,
    COALESCE(route.geom, area.geom) AS geom,
    COALESCE(
        CASE core.kind
            WHEN 'place'::text THEN
            CASE
                WHEN (place.feature_id IS NULL) THEN NULL::jsonb
                ELSE jsonb_build_object('feature_id', core.feature_id, 'place_kind', place.place_kind, 'phones', to_jsonb(place.phones), 'biz_number', place.biz_number, 'license_date', to_jsonb(place.license_date), 'business_hours', place.business_hours, 'facility_info', place.facility_info, 'reviews_link', place.reviews_link, 'payload', place.payload)
            END
            WHEN 'event'::text THEN
            CASE
                WHEN (event.feature_id IS NULL) THEN NULL::jsonb
                ELSE jsonb_build_object('feature_id', core.feature_id, 'event_kind', event.event_kind, 'starts_on', to_jsonb(event.starts_on), 'ends_on', to_jsonb(event.ends_on), 'timezone', event.timezone, 'opening_hours', event.opening_hours, 'venue_name', event.venue_name, 'tel', event.tel, 'content_id', event.content_id, 'content_type_id', event.content_type_id, 'area_code', event.area_code, 'sigungu_code', event.sigungu_code, 'payload', event.payload)
            END
            WHEN 'notice'::text THEN
            CASE
                WHEN (notice.feature_id IS NULL) THEN NULL::jsonb
                ELSE jsonb_build_object('feature_id', core.feature_id, 'notice_type', notice.notice_type, 'severity', notice.severity, 'valid_start_time', to_jsonb(to_char((notice.valid_start_time AT TIME ZONE 'Asia/Seoul'::text),
                CASE
                    WHEN (((EXTRACT(microsecond FROM notice.valid_start_time))::bigint % (1000000)::bigint) = 0) THEN 'YYYY-MM-DD"T"HH24:MI:SS"+09:00"'::text
                    ELSE 'YYYY-MM-DD"T"HH24:MI:SS.US"+09:00"'::text
                END)), 'valid_end_time', to_jsonb(to_char((notice.valid_end_time AT TIME ZONE 'Asia/Seoul'::text),
                CASE
                    WHEN (((EXTRACT(microsecond FROM notice.valid_end_time))::bigint % (1000000)::bigint) = 0) THEN 'YYYY-MM-DD"T"HH24:MI:SS"+09:00"'::text
                    ELSE 'YYYY-MM-DD"T"HH24:MI:SS.US"+09:00"'::text
                END)), 'source_agency', notice.source_agency, 'officer_name', notice.officer_name, 'payload', notice.payload)
            END
            WHEN 'route'::text THEN
            CASE
                WHEN (route.feature_id IS NULL) THEN NULL::jsonb
                ELSE jsonb_build_object('feature_id', core.feature_id, 'route_type', route.route_type, 'geometry_source', route.geometry_source, 'geometry_status', route.geometry_status, 'total_distance_meters', to_jsonb((route.total_distance_meters)::text), 'expected_duration_minutes', route.expected_duration_minutes, 'difficulty', route.difficulty, 'begin_name', route.begin_name, 'begin_address', route.begin_address, 'end_name', route.end_name, 'end_address', route.end_address, 'payload', route.payload)
            END
            WHEN 'area'::text THEN
            CASE
                WHEN (area.feature_id IS NULL) THEN NULL::jsonb
                ELSE jsonb_build_object('feature_id', core.feature_id, 'area_kind', area.area_kind, 'boundary_source', area.boundary_source, 'area_square_meters', to_jsonb((area.area_square_meters)::text), 'regulation_scope', area.regulation_scope, 'administrative_office', area.administrative_office, 'description', area.description, 'payload', area.payload)
            END
            ELSE NULL::jsonb
        END, '{}'::jsonb) AS detail
   FROM (((((feature.features core
     LEFT JOIN feature.feature_places place ON (((place.feature_id)::text = (core.feature_id)::text)))
     LEFT JOIN feature.feature_events event ON (((event.feature_id)::text = (core.feature_id)::text)))
     LEFT JOIN feature.feature_notices notice ON (((notice.feature_id)::text = (core.feature_id)::text)))
     LEFT JOIN feature.feature_routes route ON (((route.feature_id)::text = (core.feature_id)::text)))
     LEFT JOIN feature.feature_areas area ON (((area.feature_id)::text = (core.feature_id)::text)))
  WHERE ((core.lifecycle_state = 'active'::text) AND (core.publication_state = 'published'::text) AND (core.quality_state = 'valid'::text));


ALTER VIEW feature.public_features OWNER TO ktm_feature_schema_owner;

--
-- Name: admin_auth_events; Type: TABLE; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE TABLE ops.admin_auth_events (
    auth_event_id uuid DEFAULT x_extension.gen_random_uuid() NOT NULL,
    event_type text NOT NULL,
    outcome text NOT NULL,
    attempted_username text,
    actor text,
    reason text,
    next_path text,
    client_ip text,
    user_agent text,
    request_id text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT admin_auth_events_actor_check CHECK (((actor IS NULL) OR (char_length(actor) <= 120))),
    CONSTRAINT admin_auth_events_attempted_username_check CHECK (((attempted_username IS NULL) OR (char_length(attempted_username) <= 80))),
    CONSTRAINT admin_auth_events_client_ip_check CHECK (((client_ip IS NULL) OR (char_length(client_ip) <= 128))),
    CONSTRAINT admin_auth_events_event_type_check CHECK ((event_type = ANY (ARRAY['login'::text, 'logout'::text]))),
    CONSTRAINT admin_auth_events_next_path_check CHECK (((next_path IS NULL) OR (char_length(next_path) <= 2048))),
    CONSTRAINT admin_auth_events_outcome_check CHECK ((outcome = ANY (ARRAY['succeeded'::text, 'failed'::text, 'denied'::text]))),
    CONSTRAINT admin_auth_events_reason_check CHECK (((reason IS NULL) OR (char_length(reason) <= 120))),
    CONSTRAINT admin_auth_events_request_id_check CHECK (((request_id IS NULL) OR (char_length(request_id) <= 128))),
    CONSTRAINT admin_auth_events_user_agent_check CHECK (((user_agent IS NULL) OR (char_length(user_agent) <= 512)))
);


ALTER TABLE ops.admin_auth_events OWNER TO ktm_feature_schema_owner;

--
-- Name: api_call_log; Type: TABLE; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE TABLE ops.api_call_log (
    api_call_log_id uuid DEFAULT x_extension.gen_random_uuid() NOT NULL,
    method text NOT NULL,
    path text NOT NULL,
    status_code integer NOT NULL,
    duration_ms integer NOT NULL,
    request_id text,
    error_code text,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE ops.api_call_log OWNER TO ktm_feature_schema_owner;

--
-- Name: backup_command_executions; Type: TABLE; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE TABLE ops.backup_command_executions (
    command_id bigint NOT NULL,
    effect_kind text NOT NULL,
    effect_token text NOT NULL,
    phase text NOT NULL,
    backup_id text NOT NULL,
    app_db text,
    dagster_db text,
    rustfs_volume text,
    marker_key text NOT NULL,
    input_digest text NOT NULL,
    prepared_result jsonb,
    output_digest text,
    marker_sha256 text,
    prepared_at timestamp with time zone DEFAULT now() NOT NULL,
    effect_started_at timestamp with time zone,
    effect_completed_at timestamp with time zone,
    CONSTRAINT ck_backup_command_executions_delete_result CHECK (((effect_kind <> 'delete'::text) OR ((prepared_result IS NOT NULL) AND (jsonb_typeof(prepared_result) = 'object'::text)))),
    CONSTRAINT ck_backup_command_executions_effect_kind CHECK ((effect_kind = ANY (ARRAY['create'::text, 'delete'::text, 'restore'::text, 'swap'::text]))),
    CONSTRAINT ck_backup_command_executions_effect_token CHECK ((effect_token ~ '^[0-9a-f]{64}$'::text)),
    CONSTRAINT ck_backup_command_executions_input_digest CHECK ((input_digest ~ '^[0-9a-f]{64}$'::text)),
    CONSTRAINT ck_backup_command_executions_marker_key CHECK ((marker_key ~ '^[a-z0-9][a-z0-9_.-]{0,127}$'::text)),
    CONSTRAINT ck_backup_command_executions_phase CHECK ((phase = ANY (ARRAY['prepared'::text, 'effect_started'::text, 'effect_succeeded'::text]))),
    CONSTRAINT ck_backup_command_executions_phase_evidence CHECK ((((phase = 'prepared'::text) AND (effect_started_at IS NULL) AND (effect_completed_at IS NULL) AND (output_digest IS NULL) AND (marker_sha256 IS NULL)) OR ((phase = 'effect_started'::text) AND (effect_started_at IS NOT NULL) AND (effect_completed_at IS NULL) AND (output_digest IS NULL) AND (marker_sha256 IS NULL)) OR ((phase = 'effect_succeeded'::text) AND (effect_started_at IS NOT NULL) AND (effect_completed_at IS NOT NULL) AND (output_digest IS NOT NULL) AND (output_digest ~ '^[0-9a-f]{64}$'::text) AND (marker_sha256 IS NOT NULL) AND (marker_sha256 ~ '^[0-9a-f]{64}$'::text))))
);


ALTER TABLE ops.backup_command_executions OWNER TO ktm_feature_schema_owner;

--
-- Name: c6c_cancel_probe_fixtures; Type: TABLE; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE TABLE ops.c6c_cancel_probe_fixtures (
    transaction_id uuid NOT NULL,
    job_id uuid NOT NULL,
    state text NOT NULL,
    cancellation_id uuid,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    consumed_at timestamp with time zone,
    finalized_at timestamp with time zone,
    CONSTRAINT ck_c6c_cancel_probe_fixtures_ck_c6c_cancel_probe_fixtur_e283 CHECK ((((state = 'armed'::text) AND (cancellation_id IS NULL) AND (consumed_at IS NULL) AND (finalized_at IS NULL)) OR ((state = 'consumed'::text) AND (cancellation_id IS NOT NULL) AND (consumed_at IS NOT NULL) AND (finalized_at IS NULL)) OR ((state = 'finalized'::text) AND (cancellation_id IS NOT NULL) AND (consumed_at IS NOT NULL) AND (finalized_at IS NOT NULL) AND (finalized_at >= consumed_at)))),
    CONSTRAINT ck_c6c_cancel_probe_fixtures_ck_c6c_cancel_probe_fixtures_state CHECK ((state = ANY (ARRAY['armed'::text, 'consumed'::text, 'finalized'::text])))
);


ALTER TABLE ops.c6c_cancel_probe_fixtures OWNER TO ktm_feature_schema_owner;

--
-- Name: cache_target_writer_drain_instigations; Type: TABLE; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE TABLE ops.cache_target_writer_drain_instigations (
    lease_id uuid NOT NULL,
    kind text NOT NULL,
    selector_id text NOT NULL,
    state_id text NOT NULL,
    origin_id text NOT NULL,
    instigation_name text NOT NULL,
    repository_name text NOT NULL,
    repository_location_name text NOT NULL,
    was_running boolean NOT NULL,
    pause_result text DEFAULT 'pending'::text NOT NULL,
    paused_at timestamp with time zone,
    restore_result text DEFAULT 'not_requested'::text NOT NULL,
    restored_at timestamp with time zone,
    CONSTRAINT ck_cache_target_writer_drain_instigations_identity CHECK (((selector_id = btrim(selector_id)) AND (selector_id <> ''::text) AND (state_id = btrim(state_id)) AND (state_id <> ''::text) AND (origin_id = btrim(origin_id)) AND (origin_id <> ''::text) AND (instigation_name = btrim(instigation_name)) AND (instigation_name <> ''::text) AND (repository_name = btrim(repository_name)) AND (repository_name <> ''::text) AND (repository_location_name = btrim(repository_location_name)) AND (repository_location_name <> ''::text))),
    CONSTRAINT ck_cache_target_writer_drain_instigations_kind CHECK ((kind = ANY (ARRAY['schedule'::text, 'sensor'::text]))),
    CONSTRAINT ck_cache_target_writer_drain_instigations_original_state CHECK (((was_running AND (pause_result <> 'not_required'::text)) OR ((NOT was_running) AND (pause_result = 'not_required'::text) AND (restore_result = 'not_requested'::text)))),
    CONSTRAINT ck_cache_target_writer_drain_instigations_results CHECK (((pause_result = ANY (ARRAY['pending'::text, 'paused'::text, 'already_stopped'::text, 'not_required'::text])) AND (restore_result = ANY (ARRAY['not_requested'::text, 'restored'::text, 'already_running'::text]))))
);


ALTER TABLE ops.cache_target_writer_drain_instigations OWNER TO ktm_feature_schema_owner;

--
-- Name: cache_target_writer_drain_leases; Type: TABLE; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE TABLE ops.cache_target_writer_drain_leases (
    lease_id uuid DEFAULT x_extension.gen_random_uuid() NOT NULL,
    owner_kind text NOT NULL,
    owner_id uuid NOT NULL,
    state text NOT NULL,
    snapshot_sha256 text NOT NULL,
    receipt_sha256 text,
    receipt_operation text,
    receipt_prior_sha256 text,
    failure_code text,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    updated_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    restored_at timestamp with time zone,
    CONSTRAINT ck_cache_target_writer_drain_leases_failure_code CHECK (((failure_code IS NULL) OR (failure_code ~ '^[A-Z][A-Z0-9_]{0,63}$'::text))),
    CONSTRAINT ck_cache_target_writer_drain_leases_owner_kind CHECK ((owner_kind = ANY (ARRAY['diagnostic'::text, 'cutover'::text]))),
    CONSTRAINT ck_cache_target_writer_drain_leases_receipt CHECK ((((state <> 'draining'::text) = ((receipt_sha256 IS NOT NULL) AND (receipt_operation IS NOT NULL))) AND ((receipt_operation IS NULL) OR (receipt_operation = ANY (ARRAY['begin'::text, 'attest'::text, 'restore'::text]))))),
    CONSTRAINT ck_cache_target_writer_drain_leases_receipt_prior_sha256 CHECK (((receipt_prior_sha256 IS NULL) OR (receipt_prior_sha256 ~ '^[0-9a-f]{64}$'::text))),
    CONSTRAINT ck_cache_target_writer_drain_leases_receipt_sha256 CHECK (((receipt_sha256 IS NULL) OR (receipt_sha256 ~ '^[0-9a-f]{64}$'::text))),
    CONSTRAINT ck_cache_target_writer_drain_leases_restored_at CHECK (((state = 'restored'::text) = (restored_at IS NOT NULL))),
    CONSTRAINT ck_cache_target_writer_drain_leases_snapshot_sha256 CHECK ((snapshot_sha256 ~ '^[0-9a-f]{64}$'::text)),
    CONSTRAINT ck_cache_target_writer_drain_leases_state CHECK ((state = ANY (ARRAY['draining'::text, 'drained'::text, 'restoring'::text, 'restored'::text])))
);


ALTER TABLE ops.cache_target_writer_drain_leases OWNER TO ktm_feature_schema_owner;

--
-- Name: cache_target_writer_drain_runs; Type: TABLE; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE TABLE ops.cache_target_writer_drain_runs (
    lease_id uuid NOT NULL,
    dagster_run_id text NOT NULL,
    initial_status text NOT NULL,
    cancel_result text DEFAULT 'pending'::text NOT NULL,
    cancel_reserved_at timestamp with time zone,
    cancel_dispatched_at timestamp with time zone,
    terminal_status text,
    updated_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT ck_cache_target_writer_drain_runs_cancel_evidence CHECK ((((cancel_result = 'pending'::text) AND (cancel_reserved_at IS NULL) AND (cancel_dispatched_at IS NULL) AND (terminal_status IS NULL)) OR ((cancel_result = ANY (ARRAY['reserved'::text, 'outcome_uncertain'::text])) AND (cancel_reserved_at IS NOT NULL) AND (cancel_dispatched_at IS NULL) AND (terminal_status IS NULL)) OR ((cancel_result = 'dispatched'::text) AND (cancel_reserved_at IS NOT NULL) AND (cancel_dispatched_at IS NOT NULL) AND (terminal_status IS NULL)) OR ((cancel_result = 'terminal'::text) AND (terminal_status IS NOT NULL)))),
    CONSTRAINT ck_cache_target_writer_drain_runs_cancel_result CHECK ((cancel_result = ANY (ARRAY['pending'::text, 'reserved'::text, 'dispatched'::text, 'terminal'::text, 'outcome_uncertain'::text]))),
    CONSTRAINT ck_cache_target_writer_drain_runs_identity CHECK (((dagster_run_id = btrim(dagster_run_id)) AND (dagster_run_id <> ''::text) AND (initial_status = btrim(initial_status)) AND (initial_status <> ''::text))),
    CONSTRAINT ck_cache_target_writer_drain_runs_terminal_status CHECK (((terminal_status IS NULL) OR (terminal_status ~ '^[A-Z_]+$'::text)))
);


ALTER TABLE ops.cache_target_writer_drain_runs OWNER TO ktm_feature_schema_owner;

--
-- Name: current_summary_runs; Type: TABLE; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE TABLE ops.current_summary_runs (
    summary_run_id bigint NOT NULL,
    projection_kind text NOT NULL,
    run_kind text NOT NULL,
    status text NOT NULL,
    started_at timestamp with time zone DEFAULT now() NOT NULL,
    finished_at timestamp with time zone,
    input_count bigint DEFAULT 0 NOT NULL,
    inserted_count bigint DEFAULT 0 NOT NULL,
    updated_count bigint DEFAULT 0 NOT NULL,
    deleted_count bigint DEFAULT 0 NOT NULL,
    scope jsonb DEFAULT '{}'::jsonb NOT NULL,
    detail jsonb DEFAULT '{}'::jsonb NOT NULL,
    CONSTRAINT ck_current_summary_runs_counts_nonnegative CHECK (((input_count >= 0) AND (inserted_count >= 0) AND (updated_count >= 0) AND (deleted_count >= 0))),
    CONSTRAINT ck_current_summary_runs_detail_object CHECK ((jsonb_typeof(detail) = 'object'::text)),
    CONSTRAINT ck_current_summary_runs_finished_at CHECK ((((status = 'running'::text) AND (finished_at IS NULL)) OR ((status = ANY (ARRAY['succeeded'::text, 'failed'::text])) AND (finished_at >= started_at)))),
    CONSTRAINT ck_current_summary_runs_projection_kind CHECK ((projection_kind = ANY (ARRAY['weather'::text, 'price'::text]))),
    CONSTRAINT ck_current_summary_runs_run_kind CHECK ((run_kind = ANY (ARRAY['ingest'::text, 'reconcile'::text, 'backfill'::text, 'restore'::text]))),
    CONSTRAINT ck_current_summary_runs_scope_object CHECK ((jsonb_typeof(scope) = 'object'::text)),
    CONSTRAINT ck_current_summary_runs_status CHECK ((status = ANY (ARRAY['running'::text, 'succeeded'::text, 'failed'::text])))
);


ALTER TABLE ops.current_summary_runs OWNER TO ktm_feature_schema_owner;

--
-- Name: current_summary_runs_summary_run_id_seq; Type: SEQUENCE; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ops.current_summary_runs ALTER COLUMN summary_run_id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME ops.current_summary_runs_summary_run_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: dagster_schedule_active_claims; Type: TABLE; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE TABLE ops.dagster_schedule_active_claims (
    command_id uuid NOT NULL,
    schedule_name text NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    resolvable_after timestamp with time zone DEFAULT (clock_timestamp() + '00:05:00'::interval) NOT NULL,
    operation_finished_at timestamp with time zone,
    CONSTRAINT ck_dagster_schedule_active_claims_finished_after_create CHECK (((operation_finished_at IS NULL) OR (operation_finished_at >= created_at))),
    CONSTRAINT ck_dagster_schedule_active_claims_resolution_lease CHECK ((resolvable_after >= (created_at + '00:05:00'::interval))),
    CONSTRAINT ck_dagster_schedule_active_claims_schedule_name_not_blank CHECK ((btrim(schedule_name) <> ''::text))
);


ALTER TABLE ops.dagster_schedule_active_claims OWNER TO ktm_feature_schema_owner;

--
-- Name: dagster_schedule_audit_events; Type: TABLE; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE TABLE ops.dagster_schedule_audit_events (
    event_id bigint NOT NULL,
    command_id uuid NOT NULL,
    schedule_name text NOT NULL,
    command text NOT NULL,
    phase text NOT NULL,
    actor text NOT NULL,
    reason text,
    details jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_dagster_schedule_audit_events_actor CHECK (((btrim(actor) <> ''::text) AND (char_length(actor) <= 200))),
    CONSTRAINT ck_dagster_schedule_audit_events_command CHECK ((command = ANY (ARRAY['update'::text, 'default'::text, 'start'::text, 'stop'::text, 'reset'::text, 'run'::text]))),
    CONSTRAINT ck_dagster_schedule_audit_events_details_object CHECK ((jsonb_typeof(details) = 'object'::text)),
    CONSTRAINT ck_dagster_schedule_audit_events_phase CHECK ((phase = ANY (ARRAY['requested'::text, 'succeeded'::text, 'failed'::text]))),
    CONSTRAINT ck_dagster_schedule_audit_events_reason CHECK (((reason IS NULL) OR (char_length(reason) <= 500))),
    CONSTRAINT ck_dagster_schedule_audit_events_schedule_name_not_blank CHECK ((btrim(schedule_name) <> ''::text))
);


ALTER TABLE ops.dagster_schedule_audit_events OWNER TO ktm_feature_schema_owner;

--
-- Name: dagster_schedule_audit_events_event_id_seq; Type: SEQUENCE; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ops.dagster_schedule_audit_events ALTER COLUMN event_id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME ops.dagster_schedule_audit_events_event_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: dagster_schedule_claim_resolutions; Type: TABLE; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE TABLE ops.dagster_schedule_claim_resolutions (
    resolution_id bigint NOT NULL,
    command_id uuid NOT NULL,
    schedule_name text NOT NULL,
    resolution text NOT NULL,
    actor text NOT NULL,
    reason text NOT NULL,
    details jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_dagster_schedule_claim_resolutions_actor CHECK (((btrim(actor) <> ''::text) AND (char_length(actor) <= 200))),
    CONSTRAINT ck_dagster_schedule_claim_resolutions_details_object CHECK ((jsonb_typeof(details) = 'object'::text)),
    CONSTRAINT ck_dagster_schedule_claim_resolutions_reason CHECK (((btrim(reason) <> ''::text) AND (char_length(reason) <= 500))),
    CONSTRAINT ck_dagster_schedule_claim_resolutions_resolution CHECK ((resolution = ANY (ARRAY['confirmed_applied'::text, 'confirmed_not_applied'::text]))),
    CONSTRAINT ck_dagster_schedule_claim_resolutions_schedule_name_not_blank CHECK ((btrim(schedule_name) <> ''::text))
);


ALTER TABLE ops.dagster_schedule_claim_resolutions OWNER TO ktm_feature_schema_owner;

--
-- Name: dagster_schedule_claim_resolutions_resolution_id_seq; Type: SEQUENCE; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ops.dagster_schedule_claim_resolutions ALTER COLUMN resolution_id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME ops.dagster_schedule_claim_resolutions_resolution_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: dagster_schedule_overrides; Type: TABLE; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE TABLE ops.dagster_schedule_overrides (
    schedule_name text NOT NULL,
    cron_schedule text NOT NULL,
    reason text,
    updated_by text,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
    CONSTRAINT ck_dagster_schedule_overrides_ck_dagster_schedule_overr_886e CHECK ((btrim(cron_schedule) <> ''::text)),
    CONSTRAINT ck_dagster_schedule_overrides_ck_dagster_schedule_overr_ac19 CHECK ((jsonb_typeof(metadata) = 'object'::text)),
    CONSTRAINT ck_dagster_schedule_overrides_ck_dagster_schedule_overr_c709 CHECK ((btrim(schedule_name) <> ''::text))
);


ALTER TABLE ops.dagster_schedule_overrides OWNER TO ktm_feature_schema_owner;

--
-- Name: data_integrity_violations; Type: TABLE; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE TABLE ops.data_integrity_violations (
    issue_id uuid DEFAULT x_extension.gen_random_uuid() NOT NULL,
    source_record_key character varying,
    feature_id character varying,
    violation_type text NOT NULL,
    severity text NOT NULL,
    message text NOT NULL,
    payload jsonb DEFAULT '{}'::jsonb NOT NULL,
    status text DEFAULT 'open'::text NOT NULL,
    detected_at timestamp with time zone DEFAULT now() NOT NULL,
    resolved_at timestamp with time zone,
    last_seen_at timestamp with time zone DEFAULT now() NOT NULL,
    provider_dataset_id bigint,
    CONSTRAINT ck_data_integrity_violations_ck_violations_severity CHECK ((severity = ANY (ARRAY['info'::text, 'warning'::text, 'error'::text, 'critical'::text]))),
    CONSTRAINT ck_data_integrity_violations_ck_violations_status CHECK ((status = ANY (ARRAY['open'::text, 'acknowledged'::text, 'resolved'::text, 'ignored'::text])))
);


ALTER TABLE ops.data_integrity_violations OWNER TO ktm_feature_schema_owner;

--
-- Name: dedup_review_queue; Type: TABLE; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE TABLE ops.dedup_review_queue (
    review_id uuid DEFAULT x_extension.gen_random_uuid() NOT NULL,
    feature_id_a character varying NOT NULL,
    feature_id_b character varying NOT NULL,
    total_score numeric(5,2) NOT NULL,
    name_score numeric(5,2) NOT NULL,
    spatial_score numeric(5,2) NOT NULL,
    category_score numeric(5,2) NOT NULL,
    status character varying DEFAULT 'pending'::character varying NOT NULL,
    decision_reason character varying,
    reviewed_by character varying,
    reviewed_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_dedup_review_queue_ck_dedup_pair_order CHECK (((feature_id_a)::text < (feature_id_b)::text)),
    CONSTRAINT ck_dedup_review_queue_ck_dedup_scores CHECK ((((total_score >= (0)::numeric) AND (total_score <= (100)::numeric)) AND ((name_score >= (0)::numeric) AND (name_score <= (100)::numeric)) AND ((spatial_score >= (0)::numeric) AND (spatial_score <= (100)::numeric)) AND ((category_score >= (0)::numeric) AND (category_score <= (100)::numeric)))),
    CONSTRAINT ck_dedup_review_queue_ck_dedup_status CHECK (((status)::text = ANY ((ARRAY['pending'::character varying, 'accepted'::character varying, 'rejected'::character varying, 'merged'::character varying, 'ignored'::character varying])::text[])))
);


ALTER TABLE ops.dedup_review_queue OWNER TO ktm_feature_schema_owner;

--
-- Name: domain_command_results; Type: TABLE; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE TABLE ops.domain_command_results (
    command_id bigint NOT NULL,
    response_status integer NOT NULL,
    response_body jsonb NOT NULL,
    response_headers jsonb DEFAULT '{}'::jsonb NOT NULL,
    completed_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_domain_command_results_response_body CHECK ((jsonb_typeof(response_body) = 'object'::text)),
    CONSTRAINT ck_domain_command_results_response_headers CHECK ((jsonb_typeof(response_headers) = 'object'::text)),
    CONSTRAINT ck_domain_command_results_response_status CHECK (((response_status >= 200) AND (response_status <= 599)))
);


ALTER TABLE ops.domain_command_results OWNER TO ktm_feature_schema_owner;

--
-- Name: domain_commands; Type: TABLE; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE TABLE ops.domain_commands (
    command_id bigint NOT NULL,
    actor text NOT NULL,
    operation text NOT NULL,
    idempotency_key uuid NOT NULL,
    fingerprint_version integer DEFAULT 1 NOT NULL,
    request_fingerprint text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_domain_commands_actor CHECK (((btrim(actor) <> ''::text) AND (char_length(actor) <= 200))),
    CONSTRAINT ck_domain_commands_fingerprint_version CHECK ((fingerprint_version = 1)),
    CONSTRAINT ck_domain_commands_operation CHECK ((operation ~ '^[a-z][a-z0-9_.-]{0,127}$'::text)),
    CONSTRAINT ck_domain_commands_request_fingerprint CHECK ((request_fingerprint ~ '^[0-9a-f]{64}$'::text))
);


ALTER TABLE ops.domain_commands OWNER TO ktm_feature_schema_owner;

--
-- Name: domain_commands_command_id_seq; Type: SEQUENCE; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ops.domain_commands ALTER COLUMN command_id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME ops.domain_commands_command_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: enrichment_review_queue; Type: TABLE; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE TABLE ops.enrichment_review_queue (
    review_id uuid DEFAULT x_extension.gen_random_uuid() NOT NULL,
    target_feature_id character varying NOT NULL,
    source_name character varying NOT NULL,
    target_name character varying NOT NULL,
    name_score numeric(5,2) NOT NULL,
    status character varying DEFAULT 'pending'::character varying NOT NULL,
    decision_reason character varying,
    reviewed_by character varying,
    reviewed_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    source_entity_key text NOT NULL,
    source_record_key text NOT NULL,
    CONSTRAINT ck_enrichment_review_queue_ck_enrichment_review_name_score CHECK (((name_score >= (0)::numeric) AND (name_score <= (100)::numeric))),
    CONSTRAINT ck_enrichment_review_queue_ck_enrichment_review_status CHECK (((status)::text = ANY ((ARRAY['pending'::character varying, 'accepted'::character varying, 'rejected'::character varying, 'ignored'::character varying])::text[])))
);


ALTER TABLE ops.enrichment_review_queue OWNER TO ktm_feature_schema_owner;

--
-- Name: feature_consistency_reports; Type: TABLE; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE TABLE ops.feature_consistency_reports (
    report_id uuid DEFAULT x_extension.gen_random_uuid() NOT NULL,
    batch_id uuid NOT NULL,
    started_at timestamp with time zone DEFAULT now() NOT NULL,
    finished_at timestamp with time zone,
    severity_max character varying NOT NULL,
    cases jsonb NOT NULL,
    summary jsonb NOT NULL,
    CONSTRAINT ck_feature_consistency_reports_feature_consistency_repo_55c7 CHECK (((severity_max)::text = ANY ((ARRAY['OK'::character varying, 'WARN'::character varying, 'ERROR'::character varying])::text[])))
);


ALTER TABLE ops.feature_consistency_reports OWNER TO ktm_feature_schema_owner;

--
-- Name: feature_merge_history; Type: TABLE; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE TABLE ops.feature_merge_history (
    merge_id uuid DEFAULT x_extension.gen_random_uuid() NOT NULL,
    master_feature_id text NOT NULL,
    loser_feature_id text NOT NULL,
    score numeric(5,2),
    review_id uuid,
    merged_by text,
    reason text,
    merged_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_feature_merge_history_ck_merge_history_distinct CHECK ((master_feature_id <> loser_feature_id))
);


ALTER TABLE ops.feature_merge_history OWNER TO ktm_feature_schema_owner;

--
-- Name: feature_override_field_paths; Type: TABLE; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE TABLE ops.feature_override_field_paths (
    field_path text NOT NULL,
    feature_kind text NOT NULL,
    target_relation text NOT NULL,
    target_column text NOT NULL,
    value_kind text NOT NULL,
    geometry_type text,
    allows_null boolean NOT NULL,
    requires_source boolean NOT NULL,
    provider_writable boolean NOT NULL,
    operator_writable boolean NOT NULL,
    sort_order smallint NOT NULL,
    CONSTRAINT ck_feature_override_field_paths_canonical CHECK (((field_path <> ''::text) AND (field_path = btrim(field_path)))),
    CONSTRAINT ck_feature_override_field_paths_geometry_kind CHECK ((((value_kind = 'geometry'::text) AND (geometry_type IS NOT NULL)) OR ((value_kind <> 'geometry'::text) AND (geometry_type IS NULL)))),
    CONSTRAINT ck_feature_override_field_paths_geometry_type CHECK (((geometry_type IS NULL) OR (geometry_type = ANY (ARRAY['POINT'::text, 'MULTILINESTRING'::text, 'MULTIPOLYGON'::text])))),
    CONSTRAINT ck_feature_override_field_paths_kind CHECK ((feature_kind = ANY (ARRAY['*'::text, 'place'::text, 'event'::text, 'notice'::text, 'route'::text, 'area'::text]))),
    CONSTRAINT ck_feature_override_field_paths_relation CHECK ((target_relation = ANY (ARRAY['features'::text, 'feature_places'::text, 'feature_events'::text, 'feature_notices'::text, 'feature_routes'::text, 'feature_areas'::text]))),
    CONSTRAINT ck_feature_override_field_paths_value_kind CHECK ((value_kind = ANY (ARRAY['text'::text, 'integer'::text, 'numeric'::text, 'boolean'::text, 'json_object'::text, 'json_array'::text, 'text_array'::text, 'date'::text, 'timestamptz'::text, 'uuid'::text, 'geometry'::text])))
);


ALTER TABLE ops.feature_override_field_paths OWNER TO ktm_feature_schema_owner;

--
-- Name: feature_overrides; Type: TABLE; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE TABLE ops.feature_overrides (
    override_id uuid DEFAULT x_extension.gen_random_uuid() NOT NULL,
    feature_id character varying NOT NULL,
    source_record_key character varying,
    field_path text NOT NULL,
    source_value jsonb,
    override_value jsonb,
    prevent_provider_reactivation boolean DEFAULT false NOT NULL,
    status text DEFAULT 'active'::text NOT NULL,
    reason text,
    created_by text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    source_provider_dataset_id bigint,
    source_entity_key text,
    source_raw_payload_hash text,
    value_geometry x_extension.geometry(Geometry,4326),
    command_id bigint,
    base_revision bigint,
    revoked_at timestamp with time zone,
    revoked_by text,
    revoked_reason text,
    CONSTRAINT ck_feature_overrides_base_revision CHECK (((base_revision IS NULL) OR (base_revision >= 1))),
    CONSTRAINT ck_feature_overrides_ck_overrides_status CHECK ((status = ANY (ARRAY['active'::text, 'inactive'::text, 'superseded'::text, 'revoked'::text]))),
    CONSTRAINT ck_feature_overrides_lifecycle_state_value CHECK (((field_path <> 'lifecycle_state'::text) OR ((jsonb_typeof(override_value) = 'string'::text) AND ((override_value #>> '{}'::text[]) = ANY (ARRAY['active'::text, 'retired'::text]))))),
    CONSTRAINT ck_feature_overrides_revocation_pair CHECK (((status <> 'revoked'::text) OR ((revoked_at IS NOT NULL) AND (btrim(revoked_by) <> ''::text)))),
    CONSTRAINT ck_feature_overrides_value_storage CHECK (((value_geometry IS NULL) OR (override_value IS NULL)))
);


ALTER TABLE ops.feature_overrides OWNER TO ktm_feature_schema_owner;

--
-- Name: feature_update_request_datasets; Type: TABLE; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE TABLE ops.feature_update_request_datasets (
    feature_update_request_dataset_id uuid DEFAULT x_extension.gen_random_uuid() NOT NULL,
    request_id uuid NOT NULL,
    provider_dataset_id bigint NOT NULL,
    sync_scope text NOT NULL,
    operation_key text NOT NULL
);


ALTER TABLE ops.feature_update_request_datasets OWNER TO ktm_feature_schema_owner;

--
-- Name: feature_update_request_idempotency; Type: TABLE; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE TABLE ops.feature_update_request_idempotency (
    actor text NOT NULL,
    idempotency_key uuid NOT NULL,
    fingerprint_version integer DEFAULT 1 NOT NULL,
    request_fingerprint text NOT NULL,
    request_id uuid NOT NULL,
    reused_active_request boolean NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_feature_update_request_idempotency_actor CHECK (((btrim(actor) <> ''::text) AND (char_length(actor) <= 200))),
    CONSTRAINT ck_feature_update_request_idempotency_fingerprint CHECK ((request_fingerprint ~ '^[0-9a-f]{64}$'::text)),
    CONSTRAINT ck_feature_update_request_idempotency_fingerprint_version CHECK ((fingerprint_version = 1))
);


ALTER TABLE ops.feature_update_request_idempotency OWNER TO ktm_feature_schema_owner;

--
-- Name: feature_update_requests; Type: TABLE; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE TABLE ops.feature_update_requests (
    request_id uuid DEFAULT x_extension.gen_random_uuid() NOT NULL,
    scope_type text NOT NULL,
    scope jsonb NOT NULL,
    update_policy jsonb DEFAULT '{}'::jsonb NOT NULL,
    run_mode text NOT NULL,
    priority integer DEFAULT 50 NOT NULL,
    matched_scope jsonb DEFAULT '{}'::jsonb NOT NULL,
    job_id uuid NOT NULL,
    operator text,
    reason text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    generation bigint DEFAULT 1 NOT NULL,
    dataset_membership_mode text DEFAULT 'single'::text NOT NULL,
    CONSTRAINT ck_feature_update_requests_ck_feature_update_run_mode CHECK ((run_mode = ANY (ARRAY['queued'::text, 'now'::text]))),
    CONSTRAINT ck_feature_update_requests_ck_feature_update_scope CHECK ((scope_type = ANY (ARRAY['feature_ids'::text, 'center_radius'::text, 'sigungu_by_radius'::text, 'bbox'::text, 'provider_dataset'::text, 'cache_target_keys'::text]))),
    CONSTRAINT ck_feature_update_requests_generation_positive CHECK ((generation > 0)),
    CONSTRAINT ck_feature_update_requests_matched_scope_object CHECK ((jsonb_typeof(matched_scope) = 'object'::text)),
    CONSTRAINT ck_feature_update_requests_membership_mode CHECK ((dataset_membership_mode = ANY (ARRAY['single'::text, 'multiple'::text]))),
    CONSTRAINT ck_feature_update_requests_priority_range CHECK (((priority >= 0) AND (priority <= 1000))),
    CONSTRAINT ck_feature_update_requests_reason_shape CHECK (((reason IS NULL) OR ((reason <> ''::text) AND (reason = btrim(reason)) AND (reason !~ '^[[:space:]]|[[:space:]]$'::text) AND (char_length(reason) <= 500)))),
    CONSTRAINT ck_feature_update_requests_scope_shape CHECK (ops.is_valid_feature_update_scope(scope_type, scope)),
    CONSTRAINT ck_feature_update_requests_update_policy_shape CHECK (ops.is_valid_feature_update_policy(update_policy))
);


ALTER TABLE ops.feature_update_requests OWNER TO ktm_feature_schema_owner;

--
-- Name: import_job_datasets; Type: TABLE; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE TABLE ops.import_job_datasets (
    import_job_dataset_id uuid DEFAULT x_extension.gen_random_uuid() NOT NULL,
    job_id uuid NOT NULL,
    provider_dataset_id bigint NOT NULL,
    sync_scope text NOT NULL,
    operation_key text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE ops.import_job_datasets OWNER TO ktm_feature_schema_owner;

--
-- Name: import_job_event_clock; Type: TABLE; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE TABLE ops.import_job_event_clock (
    clock_id boolean DEFAULT true NOT NULL,
    revision bigint DEFAULT 0 NOT NULL,
    updated_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT ck_import_job_event_clock_revision_nonnegative CHECK ((revision >= 0)),
    CONSTRAINT ck_import_job_event_clock_singleton CHECK (clock_id)
);


ALTER TABLE ops.import_job_event_clock OWNER TO ktm_feature_schema_owner;

--
-- Name: import_job_events; Type: TABLE; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE TABLE ops.import_job_events (
    event_id uuid DEFAULT x_extension.gen_random_uuid() NOT NULL,
    job_id uuid NOT NULL,
    feature_id text,
    stage text,
    level text NOT NULL,
    code text,
    message text NOT NULL,
    payload jsonb DEFAULT '{}'::jsonb NOT NULL,
    occurred_at timestamp with time zone DEFAULT now() NOT NULL,
    quarantined_at timestamp with time zone,
    import_job_dataset_id uuid,
    CONSTRAINT ck_import_job_events_level CHECK ((level = ANY (ARRAY['debug'::text, 'info'::text, 'warning'::text, 'error'::text, 'critical'::text])))
);


ALTER TABLE ops.import_job_events OWNER TO ktm_feature_schema_owner;

--
-- Name: import_jobs; Type: TABLE; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE TABLE ops.import_jobs (
    job_id uuid DEFAULT x_extension.gen_random_uuid() NOT NULL,
    kind text NOT NULL,
    payload jsonb DEFAULT '{}'::jsonb NOT NULL,
    status text DEFAULT 'queued'::text NOT NULL,
    progress integer DEFAULT 0 NOT NULL,
    current_stage text,
    source_checksum text,
    error_message text,
    started_at timestamp with time zone,
    finished_at timestamp with time zone,
    heartbeat_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    load_batch_id uuid,
    parent_job_id uuid,
    queue_sequence bigint NOT NULL,
    dagster_run_id text,
    cancellation_id uuid,
    cancellation_requested_at timestamp with time zone,
    cancellation_requested_by text,
    cancellation_reason text,
    trigger_kind text,
    operation_key text,
    dagster_run_status text,
    quarantined_at timestamp with time zone,
    quarantine_reason text,
    dispatch_requested_at timestamp with time zone,
    root_id uuid NOT NULL,
    root_kind text NOT NULL,
    dataset_membership_mode text DEFAULT 'root'::text NOT NULL,
    CONSTRAINT ck_import_jobs_ck_import_jobs_cancellation_marker CHECK ((((cancellation_id IS NULL) AND (cancellation_requested_at IS NULL) AND (cancellation_requested_by IS NULL) AND (cancellation_reason IS NULL)) OR ((cancellation_id IS NOT NULL) AND (cancellation_requested_at IS NOT NULL) AND (cancellation_requested_by IS NOT NULL)))),
    CONSTRAINT ck_import_jobs_ck_import_jobs_dagster_run_status CHECK (((dagster_run_status IS NULL) OR ((kind = 'provider_feature_load_run'::text) AND (dagster_run_status = ANY (ARRAY['QUEUED'::text, 'NOT_STARTED'::text, 'MANAGED'::text, 'STARTING'::text, 'STARTED'::text, 'CANCELING'::text, 'SUCCESS'::text, 'FAILURE'::text, 'CANCELED'::text]))))),
    CONSTRAINT ck_import_jobs_ck_import_jobs_feature_engine_timeline CHECK (((kind <> ALL (ARRAY['provider_feature_load_run'::text, 'provider_feature_load'::text])) OR (((started_at IS NULL) OR (created_at <= started_at)) AND ((finished_at IS NULL) OR (created_at <= finished_at)) AND ((started_at IS NULL) OR (finished_at IS NULL) OR (started_at <= finished_at))))),
    CONSTRAINT ck_import_jobs_ck_import_jobs_progress CHECK (((progress >= 0) AND (progress <= 100))),
    CONSTRAINT ck_import_jobs_ck_import_jobs_registry_version_owner CHECK (((operation_key IS NULL) OR (kind = 'provider_feature_load_run'::text))),
    CONSTRAINT ck_import_jobs_ck_import_jobs_root_kind CHECK ((root_kind = ANY (ARRAY['import_job'::text, 'update_request'::text]))),
    CONSTRAINT ck_import_jobs_ck_import_jobs_state CHECK ((status = ANY (ARRAY['queued'::text, 'running'::text, 'done'::text, 'failed'::text, 'cancelled'::text]))),
    CONSTRAINT ck_import_jobs_ck_import_jobs_trigger_kind CHECK (((trigger_kind IS NULL) OR (trigger_kind = ANY (ARRAY['schedule'::text, 'manual'::text, 'sensor'::text, 'update_request'::text, 'backfill'::text, 'system'::text])))),
    CONSTRAINT ck_import_jobs_dispatch_requested_at CHECK (((dispatch_requested_at IS NULL) OR (kind = 'feature_update_request'::text))),
    CONSTRAINT ck_import_jobs_membership_mode CHECK ((dataset_membership_mode = ANY (ARRAY['root'::text, 'single'::text, 'multiple'::text]))),
    CONSTRAINT ck_import_jobs_operation_key_shape CHECK ((((kind = 'provider_feature_load_run'::text) AND (operation_key IS NOT NULL) AND (operation_key = btrim(operation_key)) AND (operation_key <> ''::text)) OR ((kind <> 'provider_feature_load_run'::text) AND (operation_key IS NULL)))),
    CONSTRAINT ck_import_jobs_quarantine_shape CHECK ((((quarantined_at IS NULL) AND (quarantine_reason IS NULL)) OR ((quarantined_at IS NOT NULL) AND (quarantine_reason = 'unlinked_feature_update_component'::text)))),
    CONSTRAINT ck_import_jobs_update_request_shape CHECK (((kind <> 'feature_update_request'::text) OR (quarantined_at IS NOT NULL) OR ((parent_job_id IS NULL) AND (load_batch_id IS NULL) AND (trigger_kind = 'update_request'::text) AND (operation_key IS NULL) AND (dagster_run_status IS NULL) AND (payload = '{}'::jsonb) AND ((dagster_run_id IS NULL) OR ((dagster_run_id = btrim(dagster_run_id)) AND (dagster_run_id <> ''::text))) AND ((status <> 'queued'::text) OR (dagster_run_id IS NULL)) AND ((status <> 'running'::text) OR (dagster_run_id IS NOT NULL)))))
);


ALTER TABLE ops.import_jobs OWNER TO ktm_feature_schema_owner;

--
-- Name: import_jobs_queue_sequence_seq; Type: SEQUENCE; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE SEQUENCE ops.import_jobs_queue_sequence_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE ops.import_jobs_queue_sequence_seq OWNER TO ktm_feature_schema_owner;

--
-- Name: import_jobs_queue_sequence_seq; Type: SEQUENCE OWNED BY; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER SEQUENCE ops.import_jobs_queue_sequence_seq OWNED BY ops.import_jobs.queue_sequence;


--
-- Name: integrity_finding_observations; Type: TABLE; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE TABLE ops.integrity_finding_observations (
    observation_run_id bigint NOT NULL,
    dedupe_key text NOT NULL,
    observed_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_integrity_finding_observations_ck_integrity_finding__49d3 CHECK ((dedupe_key ~ '^av2_[0-9a-f]{64}$'::text))
);


ALTER TABLE ops.integrity_finding_observations OWNER TO ktm_feature_schema_owner;

--
-- Name: integrity_observation_runs; Type: TABLE; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE TABLE ops.integrity_observation_runs (
    observation_run_id bigint NOT NULL,
    generation bigint NOT NULL,
    external_run_id text NOT NULL,
    status text DEFAULT 'collecting'::text NOT NULL,
    source_observations bigint DEFAULT 0 NOT NULL,
    findings_observed bigint DEFAULT 0 NOT NULL,
    findings_unique bigint DEFAULT 0 NOT NULL,
    findings_upserted bigint DEFAULT 0 NOT NULL,
    started_at timestamp with time zone DEFAULT now() NOT NULL,
    completed_at timestamp with time zone,
    integrity_observation_scope_id bigint NOT NULL,
    CONSTRAINT ck_integrity_observation_runs_ck_integrity_observation__0779 CHECK (((source_observations >= 0) AND (findings_observed >= 0) AND (findings_unique >= 0) AND (findings_upserted >= 0) AND (findings_unique <= findings_observed) AND (findings_upserted <= findings_unique))),
    CONSTRAINT ck_integrity_observation_runs_ck_integrity_observation__5835 CHECK ((status = ANY (ARRAY['collecting'::text, 'authoritative'::text, 'superseded'::text]))),
    CONSTRAINT ck_integrity_observation_runs_ck_integrity_observation__b773 CHECK ((generation > 0)),
    CONSTRAINT ck_integrity_observation_runs_ck_integrity_observation__b94e CHECK ((((status = 'collecting'::text) AND (completed_at IS NULL)) OR ((status = ANY (ARRAY['authoritative'::text, 'superseded'::text])) AND (completed_at IS NOT NULL)))),
    CONSTRAINT ck_integrity_observation_runs_ck_integrity_observation__c764 CHECK (((external_run_id = btrim(external_run_id)) AND (external_run_id <> ''::text)))
);


ALTER TABLE ops.integrity_observation_runs OWNER TO ktm_feature_schema_owner;

--
-- Name: integrity_observation_runs_observation_run_id_seq; Type: SEQUENCE; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ops.integrity_observation_runs ALTER COLUMN observation_run_id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME ops.integrity_observation_runs_observation_run_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: integrity_observation_scopes; Type: TABLE; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE TABLE ops.integrity_observation_scopes (
    latest_generation bigint DEFAULT 0 NOT NULL,
    latest_authoritative_generation bigint DEFAULT 0 NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    integrity_observation_scope_id bigint NOT NULL,
    provider_dataset_id bigint NOT NULL,
    CONSTRAINT ck_integrity_observation_scopes_ck_integrity_observatio_2e27 CHECK (((latest_generation >= 0) AND (latest_authoritative_generation >= 0) AND (latest_authoritative_generation <= latest_generation)))
);


ALTER TABLE ops.integrity_observation_scopes OWNER TO ktm_feature_schema_owner;

--
-- Name: integrity_observation_scopes_integrity_observation_scope_id_seq; Type: SEQUENCE; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ops.integrity_observation_scopes ALTER COLUMN integrity_observation_scope_id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME ops.integrity_observation_scopes_integrity_observation_scope_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: managed_file_events; Type: TABLE; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE TABLE ops.managed_file_events (
    event_id bigint NOT NULL,
    file_id bigint NOT NULL,
    event_kind text NOT NULL,
    occurred_at timestamp with time zone DEFAULT now() NOT NULL,
    import_job_id uuid,
    dagster_run_id text,
    actor text,
    detail jsonb DEFAULT '{}'::jsonb NOT NULL,
    CONSTRAINT ck_managed_file_events_ck_managed_file_events_detail_object CHECK ((jsonb_typeof(detail) = 'object'::text)),
    CONSTRAINT ck_managed_file_events_ck_managed_file_events_event_kind CHECK ((event_kind = ANY (ARRAY['registered'::text, 'downloaded'::text, 'validated'::text, 'loaded'::text, 'restored'::text, 'marked_orphan'::text, 'marked_missing'::text, 'reappeared'::text, 'deleted'::text, 'delete_failed'::text, 'purged'::text])))
);


ALTER TABLE ops.managed_file_events OWNER TO ktm_feature_schema_owner;

--
-- Name: managed_file_events_event_id_seq; Type: SEQUENCE; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ops.managed_file_events ALTER COLUMN event_id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME ops.managed_file_events_event_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: managed_files; Type: TABLE; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE TABLE ops.managed_files (
    file_id bigint NOT NULL,
    storage_backend text NOT NULL,
    location text NOT NULL,
    path text NOT NULL,
    is_directory boolean DEFAULT false NOT NULL,
    kind text NOT NULL,
    status text DEFAULT 'active'::text NOT NULL,
    orphan_reason text,
    registered_by text NOT NULL,
    byte_size bigint,
    checksum_sha256 text,
    upload_id uuid,
    origin_import_job_id uuid,
    origin_dagster_run_id text,
    downloaded_at timestamp with time zone,
    last_loaded_at timestamp with time zone,
    last_seen_at timestamp with time zone,
    deleted_at timestamp with time zone,
    meta jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    provider_dataset_id bigint,
    provider_name text,
    CONSTRAINT ck_managed_files_ck_managed_files_byte_size CHECK ((byte_size >= 0)),
    CONSTRAINT ck_managed_files_ck_managed_files_checksum_sha256 CHECK (((checksum_sha256 IS NULL) OR (checksum_sha256 ~ '^[0-9a-f]{64}$'::text))),
    CONSTRAINT ck_managed_files_ck_managed_files_kind CHECK ((kind = ANY (ARRAY['provider_download'::text, 'backup'::text, 'upload'::text, 'feature_file'::text, 'report'::text, 'temp'::text, 'other'::text]))),
    CONSTRAINT ck_managed_files_ck_managed_files_meta_object CHECK ((jsonb_typeof(meta) = 'object'::text)),
    CONSTRAINT ck_managed_files_ck_managed_files_orphan_reason CHECK (((orphan_reason IS NULL) OR (orphan_reason = ANY (ARRAY['zombie_object'::text, 'owner_row_deleted'::text, 'manifest_missing'::text, 'e2e_backup_expired'::text, 'scan_unregistered'::text, 'temp_expired'::text])))),
    CONSTRAINT ck_managed_files_ck_managed_files_registered_by CHECK ((registered_by = ANY (ARRAY['hook'::text, 'scan'::text, 'backfill'::text]))),
    CONSTRAINT ck_managed_files_ck_managed_files_status CHECK ((status = ANY (ARRAY['active'::text, 'orphan'::text, 'missing'::text, 'deleted'::text]))),
    CONSTRAINT ck_managed_files_ck_managed_files_storage_backend CHECK ((storage_backend = ANY (ARRAY['filesystem'::text, 's3'::text]))),
    CONSTRAINT ck_managed_files_owner_v2 CHECK ((((provider_dataset_id IS NOT NULL) AND (provider_name IS NULL)) OR ((provider_dataset_id IS NULL) AND (provider_name IS NOT NULL)) OR ((provider_dataset_id IS NULL) AND (provider_name IS NULL))))
)
WITH (fillfactor='90');


ALTER TABLE ops.managed_files OWNER TO ktm_feature_schema_owner;

--
-- Name: managed_files_file_id_seq; Type: SEQUENCE; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ops.managed_files ALTER COLUMN file_id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME ops.managed_files_file_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: offline_upload_command_executions; Type: TABLE; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE TABLE ops.offline_upload_command_executions (
    command_id bigint NOT NULL,
    effect_kind text NOT NULL,
    phase text NOT NULL,
    upload_id uuid NOT NULL,
    storage_backend text,
    bucket text,
    storage_key text,
    content_type text,
    byte_size bigint,
    content_sha256 text,
    metadata_digest text,
    load_job_id uuid,
    dagster_run_id text,
    input_digest text NOT NULL,
    output_digest text,
    prepared_at timestamp with time zone DEFAULT now() NOT NULL,
    effect_started_at timestamp with time zone,
    effect_completed_at timestamp with time zone,
    CONSTRAINT ck_offline_upload_command_executions_create_identity CHECK (((effect_kind <> 'create'::text) OR ((storage_backend IS NOT NULL) AND (btrim(storage_backend) <> ''::text) AND (bucket IS NOT NULL) AND (btrim(bucket) <> ''::text) AND (storage_key IS NOT NULL) AND (btrim(storage_key) <> ''::text) AND (content_type IS NOT NULL) AND (btrim(content_type) <> ''::text) AND (byte_size IS NOT NULL) AND (byte_size > 0) AND (content_sha256 IS NOT NULL) AND (content_sha256 ~ '^[0-9a-f]{64}$'::text) AND (metadata_digest IS NOT NULL) AND (metadata_digest ~ '^[0-9a-f]{64}$'::text)))),
    CONSTRAINT ck_offline_upload_command_executions_effect_kind CHECK ((effect_kind = ANY (ARRAY['create'::text, 'delete'::text, 'load'::text]))),
    CONSTRAINT ck_offline_upload_command_executions_input_digest CHECK ((input_digest ~ '^[0-9a-f]{64}$'::text)),
    CONSTRAINT ck_offline_upload_command_executions_load_proof CHECK (((effect_kind <> 'load'::text) OR (phase <> 'effect_succeeded'::text) OR ((load_job_id IS NOT NULL) AND (dagster_run_id IS NOT NULL) AND (btrim(dagster_run_id) <> ''::text)))),
    CONSTRAINT ck_offline_upload_command_executions_phase CHECK ((phase = ANY (ARRAY['prepared'::text, 'effect_started'::text, 'effect_succeeded'::text]))),
    CONSTRAINT ck_offline_upload_command_executions_phase_evidence CHECK ((((phase = 'prepared'::text) AND (effect_started_at IS NULL) AND (effect_completed_at IS NULL) AND (output_digest IS NULL) AND (dagster_run_id IS NULL)) OR ((phase = 'effect_started'::text) AND (effect_started_at IS NOT NULL) AND (effect_completed_at IS NULL) AND (output_digest IS NULL) AND (dagster_run_id IS NULL)) OR ((phase = 'effect_succeeded'::text) AND (effect_started_at IS NOT NULL) AND (effect_completed_at IS NOT NULL) AND (output_digest IS NOT NULL) AND (output_digest ~ '^[0-9a-f]{64}$'::text))))
);


ALTER TABLE ops.offline_upload_command_executions OWNER TO ktm_feature_schema_owner;

--
-- Name: offline_uploads; Type: TABLE; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE TABLE ops.offline_uploads (
    upload_id uuid DEFAULT x_extension.gen_random_uuid() NOT NULL,
    sync_scope text DEFAULT 'dataset_wide'::text NOT NULL,
    original_filename text NOT NULL,
    storage_backend text NOT NULL,
    storage_key text NOT NULL,
    byte_size bigint NOT NULL,
    checksum_sha256 character varying(64) NOT NULL,
    detected_format text,
    detected_encoding text,
    status text DEFAULT 'uploaded'::text NOT NULL,
    validation_job_id uuid,
    load_job_id uuid,
    created_by text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    delete_command_id bigint,
    provider_dataset_id bigint NOT NULL,
    operation_key text NOT NULL,
    CONSTRAINT ck_offline_uploads_ck_offline_uploads_byte_size CHECK ((byte_size >= 0)),
    CONSTRAINT ck_offline_uploads_ck_offline_uploads_checksum_sha256 CHECK (((checksum_sha256)::text ~ '^[0-9a-f]{64}$'::text)),
    CONSTRAINT ck_offline_uploads_ck_offline_uploads_delete_owner CHECK (((status = 'deleting'::text) = (delete_command_id IS NOT NULL))),
    CONSTRAINT ck_offline_uploads_ck_offline_uploads_status CHECK ((status = ANY (ARRAY['uploading'::text, 'uploaded'::text, 'validating'::text, 'validated'::text, 'validation_failed'::text, 'loading'::text, 'loaded'::text, 'load_failed'::text, 'deleting'::text, 'cancelled'::text])))
);


ALTER TABLE ops.offline_uploads OWNER TO ktm_feature_schema_owner;

--
-- Name: ops_live_ticket_claims; Type: TABLE; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE TABLE ops.ops_live_ticket_claims (
    nonce_hash bytea NOT NULL,
    actor text NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    claimed_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT ck_ops_live_ticket_claims_actor_length CHECK (((char_length(actor) >= 1) AND (char_length(actor) <= 80))),
    CONSTRAINT ck_ops_live_ticket_claims_nonce_hash_length CHECK ((octet_length(nonce_hash) = 32))
);


ALTER TABLE ops.ops_live_ticket_claims OWNER TO ktm_feature_schema_owner;

--
-- Name: ops_live_topic_revisions; Type: TABLE; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE TABLE ops.ops_live_topic_revisions (
    topic text NOT NULL,
    revision bigint DEFAULT 0 NOT NULL,
    updated_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT ck_ops_live_topic_revisions_revision CHECK ((revision >= 0)),
    CONSTRAINT ck_ops_live_topic_revisions_topic CHECK (((btrim(topic) <> ''::text) AND (char_length(topic) <= 100)))
);


ALTER TABLE ops.ops_live_topic_revisions OWNER TO ktm_feature_schema_owner;

--
-- Name: pipeline_cancellation_members; Type: TABLE; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE TABLE ops.pipeline_cancellation_members (
    cancellation_id uuid NOT NULL,
    job_id uuid NOT NULL,
    dagster_run_id text,
    initial_status text NOT NULL,
    result text DEFAULT 'pending'::text NOT NULL,
    terminal_status text,
    error jsonb,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    operation_kind text,
    requires_run_termination boolean DEFAULT false NOT NULL,
    CONSTRAINT ck_pipeline_cancellation_members_ck_pipeline_cancellati_36d3 CHECK ((((result = 'pending'::text) AND (terminal_status IS NULL) AND (error IS NULL)) OR ((result = 'cancelled'::text) AND (terminal_status = 'cancelled'::text) AND (error IS NULL)) OR ((result = 'already_terminal'::text) AND (terminal_status = ANY (ARRAY['done'::text, 'failed'::text, 'cancelled'::text])) AND (error IS NULL)) OR ((result = 'cancel_failed'::text) AND (terminal_status IS NULL) AND (error IS NOT NULL) AND (jsonb_typeof(error) = 'object'::text)))),
    CONSTRAINT ck_pipeline_cancellation_members_ck_pipeline_cancellati_c38b CHECK ((requires_run_termination = ((dagster_run_id IS NOT NULL) AND ((initial_status = 'running'::text) OR ((initial_status = 'queued'::text) AND COALESCE((operation_kind = ANY (ARRAY['provider_feature_load_run'::text, 'provider_feature_load'::text])), false)))))),
    CONSTRAINT ck_pipeline_cancellation_members_ck_pipeline_cancellati_e484 CHECK ((result = ANY (ARRAY['pending'::text, 'cancelled'::text, 'already_terminal'::text, 'cancel_failed'::text]))),
    CONSTRAINT ck_pipeline_cancellation_members_operation_kind CHECK (((operation_kind IS NULL) OR ((operation_kind = btrim(operation_kind)) AND (operation_kind <> ''::text))))
);


ALTER TABLE ops.pipeline_cancellation_members OWNER TO ktm_feature_schema_owner;

--
-- Name: pipeline_cancellation_runs; Type: TABLE; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE TABLE ops.pipeline_cancellation_runs (
    cancellation_id uuid NOT NULL,
    dagster_run_id text NOT NULL,
    initial_status text,
    termination_reserved_at timestamp with time zone,
    result text DEFAULT 'pending'::text NOT NULL,
    terminal_status text,
    error jsonb,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    engine_started_at timestamp with time zone,
    engine_finished_at timestamp with time zone,
    CONSTRAINT ck_pipeline_cancellation_runs_ck_pipeline_cancellation__3296 CHECK ((((engine_started_at IS NULL) AND (engine_finished_at IS NULL)) OR ((result = ANY (ARRAY['cancelled'::text, 'already_terminal'::text])) AND (engine_finished_at IS NOT NULL) AND ((engine_started_at IS NULL) OR (engine_started_at <= engine_finished_at))))),
    CONSTRAINT ck_pipeline_cancellation_runs_ck_pipeline_cancellation__5a49 CHECK ((result = ANY (ARRAY['pending'::text, 'cancelled'::text, 'already_terminal'::text, 'cancel_failed'::text]))),
    CONSTRAINT ck_pipeline_cancellation_runs_ck_pipeline_cancellation__83d7 CHECK ((((termination_reserved_at IS NULL) OR (initial_status IS NOT NULL)) AND (((result = 'pending'::text) AND (terminal_status IS NULL) AND (error IS NULL)) OR ((result = 'cancelled'::text) AND (terminal_status = 'CANCELED'::text) AND (error IS NULL)) OR ((result = 'already_terminal'::text) AND ((terminal_status IS NULL) OR (terminal_status = ANY (ARRAY['SUCCESS'::text, 'FAILURE'::text]))) AND (error IS NULL)) OR ((result = 'cancel_failed'::text) AND (terminal_status IS NULL) AND (error IS NOT NULL) AND (jsonb_typeof(error) = 'object'::text)))))
);


ALTER TABLE ops.pipeline_cancellation_runs OWNER TO ktm_feature_schema_owner;

--
-- Name: pipeline_cancellations; Type: TABLE; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE TABLE ops.pipeline_cancellations (
    cancellation_id uuid DEFAULT x_extension.gen_random_uuid() NOT NULL,
    previous_cancellation_id uuid,
    root_kind text NOT NULL,
    root_id uuid NOT NULL,
    status text DEFAULT 'in_progress'::text NOT NULL,
    requested_by text NOT NULL,
    reason text,
    error jsonb,
    requested_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    finished_at timestamp with time zone,
    CONSTRAINT ck_pipeline_cancellations_ck_pipeline_cancellations_error_shape CHECK ((((status = ANY (ARRAY['in_progress'::text, 'completed'::text])) AND (error IS NULL)) OR ((status = ANY (ARRAY['retryable'::text, 'failed'::text])) AND (error IS NOT NULL) AND (jsonb_typeof(error) = 'object'::text)))),
    CONSTRAINT ck_pipeline_cancellations_ck_pipeline_cancellations_finished CHECK ((((status = 'in_progress'::text) AND (finished_at IS NULL)) OR ((status <> 'in_progress'::text) AND (finished_at IS NOT NULL)))),
    CONSTRAINT ck_pipeline_cancellations_ck_pipeline_cancellations_previous CHECK (((previous_cancellation_id IS NULL) OR (previous_cancellation_id <> cancellation_id))),
    CONSTRAINT ck_pipeline_cancellations_ck_pipeline_cancellations_root_kind CHECK ((root_kind = ANY (ARRAY['import_job'::text, 'update_request'::text]))),
    CONSTRAINT ck_pipeline_cancellations_ck_pipeline_cancellations_status CHECK ((status = ANY (ARRAY['in_progress'::text, 'retryable'::text, 'completed'::text, 'failed'::text])))
);


ALTER TABLE ops.pipeline_cancellations OWNER TO ktm_feature_schema_owner;

--
-- Name: poi_cache_target_feature_links; Type: TABLE; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE TABLE ops.poi_cache_target_feature_links (
    target_id uuid NOT NULL,
    feature_id character varying NOT NULL,
    distance_m numeric(12,2),
    relation text DEFAULT 'within_radius'::text NOT NULL,
    active boolean DEFAULT true NOT NULL,
    first_seen_at timestamp with time zone DEFAULT now() NOT NULL,
    last_seen_at timestamp with time zone DEFAULT now() NOT NULL,
    last_refreshed_at timestamp with time zone,
    provider_dataset_id bigint,
    CONSTRAINT ck_poi_cache_target_feature_links_ck_poi_cache_link_relation CHECK ((relation = ANY (ARRAY['within_radius'::text, 'same_sigungu'::text, 'manual'::text])))
);


ALTER TABLE ops.poi_cache_target_feature_links OWNER TO ktm_feature_schema_owner;

--
-- Name: poi_cache_target_outbox_claim_events; Type: TABLE; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE TABLE ops.poi_cache_target_outbox_claim_events (
    claim_id uuid NOT NULL,
    event_id uuid NOT NULL,
    relay_order bigint NOT NULL,
    "position" integer NOT NULL,
    consumer_applied_at timestamp with time zone,
    prefix_acked_at timestamp with time zone,
    ack_payload_fingerprint text,
    CONSTRAINT ck_poi_cache_target_outbox_claim_events_ck_cache_target_49fc CHECK (((relay_order > 0) AND ("position" > 0))),
    CONSTRAINT ck_poi_cache_target_outbox_claim_events_ck_cache_target_7a05 CHECK (((ack_payload_fingerprint IS NULL) OR (ack_payload_fingerprint ~ '^[0-9a-f]{64}$'::text))),
    CONSTRAINT ck_poi_cache_target_outbox_claim_events_ck_cache_target_e719 CHECK (((prefix_acked_at IS NULL) OR (consumer_applied_at IS NOT NULL)))
);


ALTER TABLE ops.poi_cache_target_outbox_claim_events OWNER TO ktm_feature_schema_owner;

--
-- Name: poi_cache_target_outbox_claims; Type: TABLE; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE TABLE ops.poi_cache_target_outbox_claims (
    claim_id uuid NOT NULL,
    external_system text NOT NULL,
    consumer_id text NOT NULL,
    idempotency_key uuid NOT NULL,
    request_fingerprint text NOT NULL,
    lease_token uuid NOT NULL,
    status text NOT NULL,
    first_relay_order bigint NOT NULL,
    last_relay_order bigint NOT NULL,
    acked_through_relay_order bigint,
    lease_expires_at timestamp with time zone NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    completed_at timestamp with time zone,
    CONSTRAINT ck_poi_cache_target_outbox_claims_ck_cache_target_outbo_0bdb CHECK (((acked_through_relay_order IS NULL) OR ((acked_through_relay_order >= first_relay_order) AND (acked_through_relay_order <= last_relay_order)))),
    CONSTRAINT ck_poi_cache_target_outbox_claims_ck_cache_target_outbo_40df CHECK ((request_fingerprint ~ '^[0-9a-f]{64}$'::text)),
    CONSTRAINT ck_poi_cache_target_outbox_claims_ck_cache_target_outbo_6de5 CHECK ((((status = 'active'::text) AND (completed_at IS NULL)) OR ((status <> 'active'::text) AND (completed_at IS NOT NULL)))),
    CONSTRAINT ck_poi_cache_target_outbox_claims_ck_cache_target_outbo_ac7d CHECK ((status = ANY (ARRAY['active'::text, 'acked'::text, 'expired'::text, 'invalidated'::text]))),
    CONSTRAINT ck_poi_cache_target_outbox_claims_ck_cache_target_outbo_d094 CHECK (((first_relay_order > 0) AND (last_relay_order >= first_relay_order)))
);


ALTER TABLE ops.poi_cache_target_outbox_claims OWNER TO ktm_feature_schema_owner;

--
-- Name: poi_cache_target_outbox_deliveries; Type: TABLE; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE TABLE ops.poi_cache_target_outbox_deliveries (
    event_id uuid NOT NULL,
    status text NOT NULL,
    delivery_version bigint DEFAULT 1 NOT NULL,
    attempt_count integer DEFAULT 0 NOT NULL,
    available_at timestamp with time zone DEFAULT now() NOT NULL,
    claim_id uuid,
    lease_token uuid,
    lease_expires_at timestamp with time zone,
    error_class text,
    error_code text,
    error_fingerprint text,
    delivered_at timestamp with time zone,
    superseded_at timestamp with time zone,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_poi_cache_target_outbox_deliveries_ck_cache_target_o_15f4 CHECK ((status = ANY (ARRAY['pending'::text, 'leased'::text, 'retry'::text, 'dead'::text, 'delivered'::text, 'superseded'::text]))),
    CONSTRAINT ck_poi_cache_target_outbox_deliveries_ck_cache_target_o_1c8f CHECK (((status = 'superseded'::text) = (superseded_at IS NOT NULL))),
    CONSTRAINT ck_poi_cache_target_outbox_deliveries_ck_cache_target_o_28fa CHECK (((error_class IS NULL) OR (error_class = ANY (ARRAY['transient'::text, 'permanent'::text])))),
    CONSTRAINT ck_poi_cache_target_outbox_deliveries_ck_cache_target_o_59b7 CHECK (((delivery_version > 0) AND (attempt_count >= 0))),
    CONSTRAINT ck_poi_cache_target_outbox_deliveries_ck_cache_target_o_5f5e CHECK (((status = 'delivered'::text) = (delivered_at IS NOT NULL))),
    CONSTRAINT ck_poi_cache_target_outbox_deliveries_ck_cache_target_o_a10f CHECK (((status = 'leased'::text) = ((claim_id IS NOT NULL) AND (lease_token IS NOT NULL) AND (lease_expires_at IS NOT NULL)))),
    CONSTRAINT ck_poi_cache_target_outbox_deliveries_ck_cache_target_o_d009 CHECK (((error_fingerprint IS NULL) OR (error_fingerprint ~ '^[0-9a-f]{64}$'::text)))
);


ALTER TABLE ops.poi_cache_target_outbox_deliveries OWNER TO ktm_feature_schema_owner;

--
-- Name: poi_cache_target_outbox_events; Type: TABLE; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE TABLE ops.poi_cache_target_outbox_events (
    event_id uuid NOT NULL,
    relay_order bigint NOT NULL,
    event_type text NOT NULL,
    event_scope text NOT NULL,
    external_system text NOT NULL,
    target_key text,
    target_id uuid,
    restore_epoch bigint NOT NULL,
    source_generation bigint,
    target_sequence bigint,
    source_payload_fingerprint text NOT NULL,
    payload_fingerprint text NOT NULL,
    payload jsonb NOT NULL,
    source_event_id uuid,
    refresh_request_id uuid,
    job_id uuid,
    domain_command_id bigint,
    reconciliation_request_id uuid,
    occurred_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_poi_cache_target_outbox_events_ck_cache_target_outbo_400d CHECK ((source_payload_fingerprint ~ '^[0-9a-f]{64}$'::text)),
    CONSTRAINT ck_poi_cache_target_outbox_events_ck_cache_target_outbo_6652 CHECK (((restore_epoch > 0) AND (((event_scope = 'target'::text) AND (target_key IS NOT NULL) AND (target_id IS NOT NULL) AND (source_generation > 0) AND (target_sequence > 0) AND (event_type <> 'cache_target.reconciled'::text)) OR ((event_scope = 'stream'::text) AND (target_key IS NULL) AND (target_id IS NULL) AND (source_generation IS NULL) AND (target_sequence IS NULL) AND (event_type = 'cache_target.reconciled'::text) AND (reconciliation_request_id IS NOT NULL))))),
    CONSTRAINT ck_poi_cache_target_outbox_events_ck_cache_target_outbo_885c CHECK ((jsonb_typeof(payload) = 'object'::text)),
    CONSTRAINT ck_poi_cache_target_outbox_events_ck_cache_target_outbo_9411 CHECK ((payload_fingerprint ~ '^[0-9a-f]{64}$'::text)),
    CONSTRAINT ck_poi_cache_target_outbox_events_ck_cache_target_outbo_c9fd CHECK ((event_type = ANY (ARRAY['cache_target.state_applied'::text, 'cache_target.links_reconciled'::text, 'refresh_request.status_changed'::text, 'cache_target.reconciled'::text]))),
    CONSTRAINT ck_poi_cache_target_outbox_events_ck_cache_target_outbox_scope CHECK ((event_scope = ANY (ARRAY['target'::text, 'stream'::text])))
);


ALTER TABLE ops.poi_cache_target_outbox_events OWNER TO ktm_feature_schema_owner;

--
-- Name: poi_cache_target_outbox_relay_order_seq; Type: SEQUENCE; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE SEQUENCE ops.poi_cache_target_outbox_relay_order_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE ops.poi_cache_target_outbox_relay_order_seq OWNER TO ktm_feature_schema_owner;

--
-- Name: poi_cache_target_reconciliation_requests; Type: TABLE; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE TABLE ops.poi_cache_target_reconciliation_requests (
    request_id uuid DEFAULT x_extension.gen_random_uuid() NOT NULL,
    external_system text NOT NULL,
    command_id bigint NOT NULL,
    reason text NOT NULL,
    status text DEFAULT 'preparing'::text NOT NULL,
    phase_version bigint DEFAULT 1 NOT NULL,
    snapshot_id uuid,
    expected_merkle_root text,
    actual_merkle_root text,
    error_code text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    started_at timestamp with time zone,
    completed_at timestamp with time zone,
    CONSTRAINT ck_cache_target_reconciliation_requests_actual_root CHECK (((actual_merkle_root IS NULL) OR (actual_merkle_root ~ '^[0-9a-f]{64}$'::text))),
    CONSTRAINT ck_cache_target_reconciliation_requests_expected_root CHECK (((expected_merkle_root IS NULL) OR (expected_merkle_root ~ '^[0-9a-f]{64}$'::text))),
    CONSTRAINT ck_cache_target_reconciliation_requests_lifecycle CHECK ((((status = 'preparing'::text) AND (started_at IS NOT NULL) AND (completed_at IS NULL) AND (snapshot_id IS NULL) AND (expected_merkle_root IS NULL) AND (actual_merkle_root IS NULL) AND (error_code IS NULL)) OR ((status = 'running'::text) AND (started_at IS NOT NULL) AND (completed_at IS NULL) AND (snapshot_id IS NOT NULL) AND (expected_merkle_root IS NOT NULL) AND (actual_merkle_root IS NULL) AND (error_code IS NULL)) OR ((status = 'succeeded'::text) AND (started_at IS NOT NULL) AND (completed_at IS NOT NULL) AND (snapshot_id IS NOT NULL) AND (expected_merkle_root IS NOT NULL) AND (actual_merkle_root IS NOT NULL) AND (error_code IS NULL)) OR ((status = 'failed'::text) AND (started_at IS NOT NULL) AND (completed_at IS NOT NULL) AND (snapshot_id IS NOT NULL) AND (expected_merkle_root IS NOT NULL) AND (actual_merkle_root IS NOT NULL) AND (error_code IS NOT NULL)) OR ((status = 'superseded'::text) AND (started_at IS NOT NULL) AND (completed_at IS NOT NULL) AND (actual_merkle_root IS NULL) AND (error_code = 'restore_fenced'::text) AND (((snapshot_id IS NULL) AND (expected_merkle_root IS NULL)) OR ((snapshot_id IS NOT NULL) AND (expected_merkle_root IS NOT NULL)))))),
    CONSTRAINT ck_cache_target_reconciliation_requests_phase_version CHECK ((phase_version > 0)),
    CONSTRAINT ck_cache_target_reconciliation_requests_reason CHECK (((btrim(reason) <> ''::text) AND (char_length(reason) <= 1000))),
    CONSTRAINT ck_cache_target_reconciliation_requests_status CHECK ((status = ANY (ARRAY['preparing'::text, 'running'::text, 'succeeded'::text, 'failed'::text, 'superseded'::text])))
);


ALTER TABLE ops.poi_cache_target_reconciliation_requests OWNER TO ktm_feature_schema_owner;

--
-- Name: poi_cache_target_refresh_members; Type: TABLE; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE TABLE ops.poi_cache_target_refresh_members (
    request_id uuid NOT NULL,
    target_id uuid NOT NULL,
    external_system text NOT NULL,
    target_key text NOT NULL,
    restore_epoch bigint NOT NULL,
    source_generation bigint NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_poi_cache_target_refresh_members_ck_cache_target_ref_d752 CHECK (((restore_epoch > 0) AND (source_generation > 0)))
);


ALTER TABLE ops.poi_cache_target_refresh_members OWNER TO ktm_feature_schema_owner;

--
-- Name: poi_cache_target_restore_fences; Type: TABLE; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE TABLE ops.poi_cache_target_restore_fences (
    fence_id uuid DEFAULT x_extension.gen_random_uuid() NOT NULL,
    external_system text NOT NULL,
    consumer_id text NOT NULL,
    command_id bigint NOT NULL,
    previous_restore_epoch bigint NOT NULL,
    restore_epoch bigint NOT NULL,
    previous_control_version bigint NOT NULL,
    control_version bigint NOT NULL,
    invalidated_claim_count bigint NOT NULL,
    superseded_delivery_count bigint NOT NULL,
    superseded_reconciliation_count bigint NOT NULL,
    superseded_reconciliation_request_id uuid,
    reason text NOT NULL,
    request_fingerprint text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_poi_cache_target_restore_fences_ck_cache_target_rest_322d CHECK ((request_fingerprint ~ '^[0-9a-f]{64}$'::text)),
    CONSTRAINT ck_poi_cache_target_restore_fences_ck_cache_target_rest_3328 CHECK (((btrim(reason) <> ''::text) AND (char_length(reason) <= 1000))),
    CONSTRAINT ck_poi_cache_target_restore_fences_ck_cache_target_rest_49d3 CHECK ((restore_epoch = (previous_restore_epoch + 1))),
    CONSTRAINT ck_poi_cache_target_restore_fences_ck_cache_target_rest_62e5 CHECK ((control_version = (previous_control_version + 1))),
    CONSTRAINT ck_poi_cache_target_restore_fences_ck_cache_target_rest_6e67 CHECK ((((superseded_reconciliation_count = 0) AND (superseded_reconciliation_request_id IS NULL)) OR ((superseded_reconciliation_count = 1) AND (superseded_reconciliation_request_id IS NOT NULL)))),
    CONSTRAINT ck_poi_cache_target_restore_fences_ck_cache_target_rest_9c5b CHECK ((superseded_delivery_count >= 0)),
    CONSTRAINT ck_poi_cache_target_restore_fences_ck_cache_target_rest_e080 CHECK ((invalidated_claim_count >= 0))
);


ALTER TABLE ops.poi_cache_target_restore_fences OWNER TO ktm_feature_schema_owner;

--
-- Name: poi_cache_target_snapshot_gc_observations; Type: TABLE; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE TABLE ops.poi_cache_target_snapshot_gc_observations (
    observation_id bigint NOT NULL,
    dagster_run_id text NOT NULL,
    observed_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    referenced_items bigint NOT NULL,
    referenced_headers bigint NOT NULL,
    previous_observation_run_id text,
    previous_observed_at timestamp with time zone,
    previous_referenced_items bigint,
    previous_referenced_headers bigint,
    growth_baseline_run_id text,
    growth_baseline_observed_at timestamp with time zone,
    growth_baseline_referenced_items bigint,
    growth_baseline_referenced_headers bigint,
    growth_baseline_eligible boolean NOT NULL,
    growth_min_interval_seconds bigint NOT NULL,
    CONSTRAINT ck_cache_target_snapshot_gc_observations_counts CHECK (((referenced_items >= 0) AND (referenced_headers >= 0))),
    CONSTRAINT ck_cache_target_snapshot_gc_observations_eligibility CHECK ((((growth_baseline_run_id IS NULL) AND (growth_baseline_eligible = ((previous_observation_run_id IS NULL) OR (observed_at > previous_observed_at)))) OR ((growth_baseline_run_id IS NOT NULL) AND (growth_baseline_eligible = ((observed_at > growth_baseline_observed_at) AND ((previous_observation_run_id IS NULL) OR (observed_at > previous_observed_at)) AND (EXTRACT(epoch FROM (observed_at - growth_baseline_observed_at)) >= (growth_min_interval_seconds)::numeric)))))),
    CONSTRAINT ck_cache_target_snapshot_gc_observations_growth_baseline CHECK ((((growth_baseline_run_id IS NULL) AND (growth_baseline_observed_at IS NULL) AND (growth_baseline_referenced_items IS NULL) AND (growth_baseline_referenced_headers IS NULL)) OR ((growth_baseline_run_id IS NOT NULL) AND (growth_baseline_run_id = btrim(growth_baseline_run_id)) AND (growth_baseline_run_id <> ''::text) AND (length(growth_baseline_run_id) <= 255) AND (growth_baseline_run_id <> dagster_run_id) AND (growth_baseline_observed_at IS NOT NULL) AND (growth_baseline_referenced_items IS NOT NULL) AND (growth_baseline_referenced_items >= 0) AND (growth_baseline_referenced_headers IS NOT NULL) AND (growth_baseline_referenced_headers >= 0)))),
    CONSTRAINT ck_cache_target_snapshot_gc_observations_growth_interval CHECK (((growth_min_interval_seconds >= 1) AND (growth_min_interval_seconds <= 86400))),
    CONSTRAINT ck_cache_target_snapshot_gc_observations_previous CHECK ((((previous_observation_run_id IS NULL) AND (previous_observed_at IS NULL) AND (previous_referenced_items IS NULL) AND (previous_referenced_headers IS NULL)) OR ((previous_observation_run_id IS NOT NULL) AND (previous_observation_run_id = btrim(previous_observation_run_id)) AND (previous_observation_run_id <> ''::text) AND (length(previous_observation_run_id) <= 255) AND (previous_observation_run_id <> dagster_run_id) AND (previous_observed_at IS NOT NULL) AND (previous_referenced_items IS NOT NULL) AND (previous_referenced_items >= 0) AND (previous_referenced_headers IS NOT NULL) AND (previous_referenced_headers >= 0)))),
    CONSTRAINT ck_cache_target_snapshot_gc_observations_run_id CHECK (((dagster_run_id = btrim(dagster_run_id)) AND (dagster_run_id <> ''::text) AND (length(dagster_run_id) <= 255)))
);


ALTER TABLE ops.poi_cache_target_snapshot_gc_observations OWNER TO ktm_feature_schema_owner;

--
-- Name: poi_cache_target_snapshot_gc_observations_observation_id_seq; Type: SEQUENCE; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ops.poi_cache_target_snapshot_gc_observations ALTER COLUMN observation_id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME ops.poi_cache_target_snapshot_gc_observations_observation_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: poi_cache_target_snapshot_items; Type: TABLE; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE TABLE ops.poi_cache_target_snapshot_items (
    snapshot_id uuid NOT NULL,
    row_number bigint NOT NULL,
    external_system text NOT NULL,
    target_key text NOT NULL,
    state text NOT NULL,
    source_generation bigint NOT NULL,
    source_payload_fingerprint text NOT NULL,
    CONSTRAINT ck_poi_cache_target_snapshot_items_ck_cache_target_snap_0ba2 CHECK (((row_number > 0) AND (source_generation > 0))),
    CONSTRAINT ck_poi_cache_target_snapshot_items_ck_cache_target_snap_879d CHECK ((source_payload_fingerprint ~ '^[0-9a-f]{64}$'::text)),
    CONSTRAINT ck_poi_cache_target_snapshot_items_ck_cache_target_snap_96c2 CHECK ((state = ANY (ARRAY['active'::text, 'deleted'::text])))
);


ALTER TABLE ops.poi_cache_target_snapshot_items OWNER TO ktm_feature_schema_owner;

--
-- Name: poi_cache_target_snapshots; Type: TABLE; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE TABLE ops.poi_cache_target_snapshots (
    snapshot_id uuid DEFAULT x_extension.gen_random_uuid() NOT NULL,
    external_system text NOT NULL,
    restore_epoch bigint NOT NULL,
    high_watermark_relay_order bigint NOT NULL,
    material_high_watermark_relay_order bigint NOT NULL,
    item_count bigint NOT NULL,
    merkle_root text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_poi_cache_target_snapshots_ck_cache_target_snapshots_0ecd CHECK ((merkle_root ~ '^[0-9a-f]{64}$'::text)),
    CONSTRAINT ck_poi_cache_target_snapshots_ck_cache_target_snapshots_counts CHECK (((restore_epoch > 0) AND (high_watermark_relay_order >= 0) AND (material_high_watermark_relay_order >= 0) AND (high_watermark_relay_order >= material_high_watermark_relay_order) AND (item_count >= 0))),
    CONSTRAINT ck_poi_cache_target_snapshots_ck_cache_target_snapshots_expiry CHECK ((expires_at > created_at))
);


ALTER TABLE ops.poi_cache_target_snapshots OWNER TO ktm_feature_schema_owner;

--
-- Name: poi_cache_target_source_events; Type: TABLE; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE TABLE ops.poi_cache_target_source_events (
    event_id uuid NOT NULL,
    external_system text NOT NULL,
    target_key text NOT NULL,
    idempotency_key uuid NOT NULL,
    operation text NOT NULL,
    restore_epoch bigint NOT NULL,
    source_generation bigint NOT NULL,
    request_fingerprint text NOT NULL,
    source_payload_fingerprint text NOT NULL,
    outcome text NOT NULL,
    target_id uuid,
    refresh_request_id uuid,
    job_id uuid,
    domain_command_id bigint,
    occurred_at timestamp with time zone NOT NULL,
    recorded_at timestamp with time zone DEFAULT now() NOT NULL,
    target_lock_version bigint,
    CONSTRAINT ck_cache_target_source_events_applied_target_receipt CHECK (((outcome <> 'applied'::text) OR ((target_id IS NOT NULL) AND (target_lock_version IS NOT NULL)))),
    CONSTRAINT ck_cache_target_source_events_target_lock_version CHECK (((target_lock_version IS NULL) OR (target_lock_version > 0))),
    CONSTRAINT ck_poi_cache_target_source_events_ck_cache_target_sourc_0ce9 CHECK (((restore_epoch > 0) AND (source_generation > 0))),
    CONSTRAINT ck_poi_cache_target_source_events_ck_cache_target_sourc_160e CHECK ((source_payload_fingerprint ~ '^[0-9a-f]{64}$'::text)),
    CONSTRAINT ck_poi_cache_target_source_events_ck_cache_target_sourc_7859 CHECK ((outcome = ANY (ARRAY['applied'::text, 'stale'::text]))),
    CONSTRAINT ck_poi_cache_target_source_events_ck_cache_target_sourc_986c CHECK ((operation = ANY (ARRAY['upsert'::text, 'delete'::text]))),
    CONSTRAINT ck_poi_cache_target_source_events_ck_cache_target_sourc_fd1e CHECK ((request_fingerprint ~ '^[0-9a-f]{64}$'::text))
);


ALTER TABLE ops.poi_cache_target_source_events OWNER TO ktm_feature_schema_owner;

--
-- Name: poi_cache_target_source_heads; Type: TABLE; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE TABLE ops.poi_cache_target_source_heads (
    external_system text NOT NULL,
    target_key text NOT NULL,
    target_id uuid,
    state text NOT NULL,
    restore_epoch bigint NOT NULL,
    source_generation bigint NOT NULL,
    source_payload_fingerprint text NOT NULL,
    last_source_event_id uuid,
    target_sequence bigint DEFAULT 0 NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_poi_cache_target_source_heads_ck_cache_target_source_0235 CHECK (((state <> 'active'::text) OR (target_id IS NOT NULL))),
    CONSTRAINT ck_poi_cache_target_source_heads_ck_cache_target_source_b31f CHECK ((state = ANY (ARRAY['active'::text, 'deleted'::text]))),
    CONSTRAINT ck_poi_cache_target_source_heads_ck_cache_target_source_b73c CHECK (((target_key <> ''::text) AND (char_length(target_key) <= 512) AND (target_key = btrim(target_key, ((((((((((((((((((((((((((((' '::text || chr(9)) || chr(10)) || chr(11)) || chr(12)) || chr(13)) || chr(28)) || chr(29)) || chr(30)) || chr(31)) || chr(133)) || chr(160)) || chr(5760)) || chr(8192)) || chr(8193)) || chr(8194)) || chr(8195)) || chr(8196)) || chr(8197)) || chr(8198)) || chr(8199)) || chr(8200)) || chr(8201)) || chr(8202)) || chr(8232)) || chr(8233)) || chr(8239)) || chr(8287)) || chr(12288)))) AND (target_key = NORMALIZE(target_key, NFC)))),
    CONSTRAINT ck_poi_cache_target_source_heads_ck_cache_target_source_b79b CHECK ((source_payload_fingerprint ~ '^[0-9a-f]{64}$'::text)),
    CONSTRAINT ck_poi_cache_target_source_heads_ck_cache_target_source_ebce CHECK (((restore_epoch > 0) AND (source_generation > 0) AND (target_sequence >= 0)))
);


ALTER TABLE ops.poi_cache_target_source_heads OWNER TO ktm_feature_schema_owner;

--
-- Name: poi_cache_target_streams; Type: TABLE; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE TABLE ops.poi_cache_target_streams (
    external_system text NOT NULL,
    consumer_id text NOT NULL,
    restore_epoch bigint NOT NULL,
    control_version bigint DEFAULT 1 NOT NULL,
    status text DEFAULT 'fenced'::text NOT NULL,
    blocked_event_id uuid,
    last_barrier_command_id bigint,
    consumer_enabled boolean DEFAULT false NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_poi_cache_target_streams_ck_cache_target_streams_blocked CHECK (((status = 'blocked'::text) = (blocked_event_id IS NOT NULL))),
    CONSTRAINT ck_poi_cache_target_streams_ck_cache_target_streams_consumer CHECK (((btrim(consumer_id) <> ''::text) AND (char_length(consumer_id) <= 128))),
    CONSTRAINT ck_poi_cache_target_streams_ck_cache_target_streams_ext_40b1 CHECK (((external_system <> ''::text) AND (char_length(external_system) <= 112) AND (external_system = btrim(external_system, ((((((((((((((((((((((((((((' '::text || chr(9)) || chr(10)) || chr(11)) || chr(12)) || chr(13)) || chr(28)) || chr(29)) || chr(30)) || chr(31)) || chr(133)) || chr(160)) || chr(5760)) || chr(8192)) || chr(8193)) || chr(8194)) || chr(8195)) || chr(8196)) || chr(8197)) || chr(8198)) || chr(8199)) || chr(8200)) || chr(8201)) || chr(8202)) || chr(8232)) || chr(8233)) || chr(8239)) || chr(8287)) || chr(12288)))) AND (external_system = NORMALIZE(external_system, NFC)))),
    CONSTRAINT ck_poi_cache_target_streams_ck_cache_target_streams_status CHECK ((status = ANY (ARRAY['ready'::text, 'fenced'::text, 'blocked'::text]))),
    CONSTRAINT ck_poi_cache_target_streams_ck_cache_target_streams_versions CHECK (((restore_epoch > 0) AND (control_version > 0)))
);


ALTER TABLE ops.poi_cache_target_streams OWNER TO ktm_feature_schema_owner;

--
-- Name: poi_cache_targets; Type: TABLE; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE TABLE ops.poi_cache_targets (
    target_id uuid DEFAULT x_extension.gen_random_uuid() NOT NULL,
    external_system text NOT NULL,
    target_key text NOT NULL,
    name text,
    lon numeric(12,8) NOT NULL,
    lat numeric(12,8) NOT NULL,
    coord x_extension.geometry(Point,4326) NOT NULL,
    coord_5179 x_extension.geometry(Point,5179) GENERATED ALWAYS AS (x_extension.st_transform(coord, 5179)) STORED,
    coord_precision_digits smallint DEFAULT 6 NOT NULL,
    coord_key text NOT NULL,
    radius_km numeric(8,3) NOT NULL,
    scope_mode text DEFAULT 'center_radius'::text NOT NULL,
    update_enabled boolean DEFAULT true NOT NULL,
    refresh_policy text DEFAULT 'provider_default'::text NOT NULL,
    provider_overrides jsonb DEFAULT '{}'::jsonb NOT NULL,
    metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
    last_seen_at timestamp with time zone DEFAULT now() NOT NULL,
    last_requested_at timestamp with time zone,
    last_refreshed_at timestamp with time zone,
    last_failed_at timestamp with time zone,
    next_eligible_refresh_at timestamp with time zone,
    deleted_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    lock_version bigint DEFAULT 1 NOT NULL,
    CONSTRAINT ck_poi_cache_targets_ck_poi_cache_targets_coord CHECK ((((x_extension.st_x(coord) >= (124.0)::double precision) AND (x_extension.st_x(coord) <= (132.0)::double precision)) AND ((x_extension.st_y(coord) >= (33.0)::double precision) AND (x_extension.st_y(coord) <= (39.5)::double precision)))),
    CONSTRAINT ck_poi_cache_targets_ck_poi_cache_targets_lock_version CHECK ((lock_version >= 1)),
    CONSTRAINT ck_poi_cache_targets_ck_poi_cache_targets_precision CHECK (((coord_precision_digits >= 3) AND (coord_precision_digits <= 8))),
    CONSTRAINT ck_poi_cache_targets_ck_poi_cache_targets_radius CHECK (((radius_km > (0)::numeric) AND (radius_km <= (100)::numeric))),
    CONSTRAINT ck_poi_cache_targets_ck_poi_cache_targets_refresh_policy CHECK ((refresh_policy = ANY (ARRAY['provider_default'::text, 'follow_system'::text, 'allow_targeted'::text, 'disabled'::text]))),
    CONSTRAINT ck_poi_cache_targets_ck_poi_cache_targets_scope_mode CHECK ((scope_mode = ANY (ARRAY['center_radius'::text, 'sigungu_by_radius'::text]))),
    CONSTRAINT ck_poi_cache_targets_external_system_identity CHECK (((external_system <> ''::text) AND (char_length(external_system) <= 112) AND (external_system = btrim(external_system, ((((((((((((((((((((((((((((' '::text || chr(9)) || chr(10)) || chr(11)) || chr(12)) || chr(13)) || chr(28)) || chr(29)) || chr(30)) || chr(31)) || chr(133)) || chr(160)) || chr(5760)) || chr(8192)) || chr(8193)) || chr(8194)) || chr(8195)) || chr(8196)) || chr(8197)) || chr(8198)) || chr(8199)) || chr(8200)) || chr(8201)) || chr(8202)) || chr(8232)) || chr(8233)) || chr(8239)) || chr(8287)) || chr(12288)))) AND (external_system = NORMALIZE(external_system, NFC)))),
    CONSTRAINT ck_poi_cache_targets_target_key_identity CHECK (((target_key <> ''::text) AND (char_length(target_key) <= 512) AND (target_key = btrim(target_key, ((((((((((((((((((((((((((((' '::text || chr(9)) || chr(10)) || chr(11)) || chr(12)) || chr(13)) || chr(28)) || chr(29)) || chr(30)) || chr(31)) || chr(133)) || chr(160)) || chr(5760)) || chr(8192)) || chr(8193)) || chr(8194)) || chr(8195)) || chr(8196)) || chr(8197)) || chr(8198)) || chr(8199)) || chr(8200)) || chr(8201)) || chr(8202)) || chr(8232)) || chr(8233)) || chr(8239)) || chr(8287)) || chr(12288)))) AND (target_key = NORMALIZE(target_key, NFC))))
);


ALTER TABLE ops.poi_cache_targets OWNER TO ktm_feature_schema_owner;

--
-- Name: provider_refresh_policies; Type: TABLE; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE TABLE ops.provider_refresh_policies (
    source_kind text NOT NULL,
    targeted_policy text DEFAULT 'follow_system'::text NOT NULL,
    system_interval_seconds integer,
    optimal_interval_seconds integer,
    min_interval_seconds integer,
    max_requests_per_minute integer,
    max_requests_per_hour integer,
    max_requests_per_day integer,
    max_concurrent integer DEFAULT 1 NOT NULL,
    burst_size integer,
    rate_limit_source jsonb DEFAULT '{}'::jsonb NOT NULL,
    config_source text DEFAULT 'db'::text NOT NULL,
    enabled boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    stale_after_minutes integer,
    revision bigint DEFAULT 1 NOT NULL,
    provider_dataset_id bigint NOT NULL,
    CONSTRAINT ck_provider_refresh_policies_ck_provider_refresh_burst CHECK (((burst_size IS NULL) OR (burst_size > 0))),
    CONSTRAINT ck_provider_refresh_policies_ck_provider_refresh_max_concurrent CHECK ((max_concurrent > 0)),
    CONSTRAINT ck_provider_refresh_policies_ck_provider_refresh_min_interval CHECK (((min_interval_seconds IS NULL) OR (min_interval_seconds > 0))),
    CONSTRAINT ck_provider_refresh_policies_ck_provider_refresh_optima_98bf CHECK (((optimal_interval_seconds IS NULL) OR (optimal_interval_seconds > 0))),
    CONSTRAINT ck_provider_refresh_policies_ck_provider_refresh_revision CHECK (((revision >= 1) AND (revision <= '9223372036854775807'::bigint))),
    CONSTRAINT ck_provider_refresh_policies_ck_provider_refresh_rpd CHECK (((max_requests_per_day IS NULL) OR (max_requests_per_day > 0))),
    CONSTRAINT ck_provider_refresh_policies_ck_provider_refresh_rph CHECK (((max_requests_per_hour IS NULL) OR (max_requests_per_hour > 0))),
    CONSTRAINT ck_provider_refresh_policies_ck_provider_refresh_rpm CHECK (((max_requests_per_minute IS NULL) OR (max_requests_per_minute > 0))),
    CONSTRAINT ck_provider_refresh_policies_ck_provider_refresh_source_kind CHECK ((source_kind = ANY (ARRAY['openapi'::text, 'filedata'::text, 'manual'::text, 'system'::text]))),
    CONSTRAINT ck_provider_refresh_policies_ck_provider_refresh_stale_after CHECK (((stale_after_minutes IS NULL) OR (stale_after_minutes > 0))),
    CONSTRAINT ck_provider_refresh_policies_ck_provider_refresh_system_3f4b CHECK (((system_interval_seconds IS NULL) OR (system_interval_seconds > 0))),
    CONSTRAINT ck_provider_refresh_policies_ck_provider_refresh_target_9acf CHECK ((targeted_policy = ANY (ARRAY['follow_system'::text, 'allow_targeted'::text, 'disabled'::text])))
);


ALTER TABLE ops.provider_refresh_policies OWNER TO ktm_feature_schema_owner;

--
-- Name: public_api_keys; Type: TABLE; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE TABLE ops.public_api_keys (
    public_api_key_id uuid DEFAULT x_extension.gen_random_uuid() NOT NULL,
    key_hash text NOT NULL,
    key_hint text NOT NULL,
    label text,
    state text DEFAULT 'active'::text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    created_by text,
    revoked_at timestamp with time zone,
    revoked_by text,
    CONSTRAINT public_api_keys_check CHECK ((((state = 'active'::text) AND (revoked_at IS NULL) AND (revoked_by IS NULL)) OR ((state = 'revoked'::text) AND (revoked_at IS NOT NULL)))),
    CONSTRAINT public_api_keys_key_hash_check CHECK ((key_hash ~ '^[0-9a-f]{64}$'::text)),
    CONSTRAINT public_api_keys_key_hint_check CHECK (((char_length(key_hint) >= 6) AND (char_length(key_hint) <= 12))),
    CONSTRAINT public_api_keys_label_check CHECK (((label IS NULL) OR ((char_length(label) >= 1) AND (char_length(label) <= 80)))),
    CONSTRAINT public_api_keys_state_check CHECK ((state = ANY (ARRAY['active'::text, 'revoked'::text])))
);


ALTER TABLE ops.public_api_keys OWNER TO ktm_feature_schema_owner;

--
-- Name: system_log; Type: TABLE; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE TABLE ops.system_log (
    system_log_id uuid DEFAULT x_extension.gen_random_uuid() NOT NULL,
    level text NOT NULL,
    source text NOT NULL,
    event text NOT NULL,
    message text NOT NULL,
    detail jsonb DEFAULT '{}'::jsonb NOT NULL,
    request_id text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_system_log_level CHECK ((level = ANY (ARRAY['debug'::text, 'info'::text, 'warning'::text, 'error'::text, 'critical'::text])))
);


ALTER TABLE ops.system_log OWNER TO ktm_feature_schema_owner;

--
-- Name: tvn36_legacy_freeze_preflight_manifest; Type: TABLE; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE TABLE ops.tvn36_legacy_freeze_preflight_manifest (
    feature_id text NOT NULL,
    request_id uuid,
    violation_code text NOT NULL,
    detail text NOT NULL,
    recorded_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL
);


ALTER TABLE ops.tvn36_legacy_freeze_preflight_manifest OWNER TO ktm_feature_schema_owner;

--
-- Name: notice_lifecycle_scopes; Type: TABLE; Schema: provider_sync; Owner: ktm_feature_schema_owner
--

CREATE TABLE provider_sync.notice_lifecycle_scopes (
    source_entity_type text NOT NULL,
    mode text NOT NULL,
    applied_at timestamp with time zone NOT NULL,
    state_fingerprint text NOT NULL,
    notice_lifecycle_scope_id bigint NOT NULL,
    provider_dataset_id bigint NOT NULL,
    CONSTRAINT ck_notice_lifecycle_scopes_mode CHECK ((mode = ANY (ARRAY['snapshot'::text, 'event'::text])))
);


ALTER TABLE provider_sync.notice_lifecycle_scopes OWNER TO ktm_feature_schema_owner;

--
-- Name: notice_lifecycle_scopes_notice_lifecycle_scope_id_seq; Type: SEQUENCE; Schema: provider_sync; Owner: ktm_feature_schema_owner
--

ALTER TABLE provider_sync.notice_lifecycle_scopes ALTER COLUMN notice_lifecycle_scope_id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME provider_sync.notice_lifecycle_scopes_notice_lifecycle_scope_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: notice_lineage_states; Type: TABLE; Schema: provider_sync; Owner: ktm_feature_schema_owner
--

CREATE TABLE provider_sync.notice_lineage_states (
    lineage_key text NOT NULL,
    present boolean NOT NULL,
    changed_at timestamp with time zone NOT NULL,
    valid_until timestamp with time zone,
    notice_lifecycle_scope_id bigint NOT NULL
);


ALTER TABLE provider_sync.notice_lineage_states OWNER TO ktm_feature_schema_owner;

--
-- Name: provider_dataset_operation_scopes; Type: TABLE; Schema: provider_sync; Owner: ktm_feature_schema_owner
--

CREATE TABLE provider_sync.provider_dataset_operation_scopes (
    provider_dataset_id bigint NOT NULL,
    sync_scope text NOT NULL,
    operation_key text NOT NULL,
    operation_kind text DEFAULT 'refresh'::text NOT NULL,
    CONSTRAINT ck_provider_dataset_operation_scopes_refresh_only CHECK ((operation_kind = 'refresh'::text)),
    CONSTRAINT ck_provider_dataset_operation_scopes_syntax CHECK (provider_sync.is_valid_provider_dataset_sync_scope(sync_scope))
);


ALTER TABLE provider_sync.provider_dataset_operation_scopes OWNER TO ktm_feature_schema_owner;

--
-- Name: provider_dataset_operations; Type: TABLE; Schema: provider_sync; Owner: ktm_feature_schema_owner
--

CREATE TABLE provider_sync.provider_dataset_operations (
    provider_dataset_id bigint NOT NULL,
    operation_key text NOT NULL,
    operation_kind text NOT NULL,
    is_enabled boolean DEFAULT true NOT NULL,
    config jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_provider_dataset_operations_config CHECK ((jsonb_typeof(config) = 'object'::text)),
    CONSTRAINT ck_provider_dataset_operations_key_canonical CHECK (((operation_key <> ''::text) AND (operation_key = btrim(operation_key)) AND (operation_key = NORMALIZE(operation_key, NFC)) AND (length(operation_key) <= 128))),
    CONSTRAINT ck_provider_dataset_operations_kind CHECK ((operation_kind = ANY (ARRAY['feature_load'::text, 'refresh'::text, 'preview'::text])))
);


ALTER TABLE provider_sync.provider_dataset_operations OWNER TO ktm_feature_schema_owner;

--
-- Name: provider_datasets; Type: TABLE; Schema: provider_sync; Owner: ktm_feature_schema_owner
--

CREATE TABLE provider_sync.provider_datasets (
    provider_dataset_id bigint NOT NULL,
    provider text NOT NULL,
    dataset_key text NOT NULL,
    display_name text NOT NULL,
    source_kind text NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    capabilities jsonb DEFAULT '{"produces": [], "extensions": {}, "schema_version": 1}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_provider_datasets_capabilities CHECK (provider_sync.is_valid_provider_dataset_capabilities(capabilities)),
    CONSTRAINT ck_provider_datasets_dataset_key_canonical CHECK (((dataset_key <> ''::text) AND (dataset_key = btrim(dataset_key)) AND (dataset_key = NORMALIZE(dataset_key, NFC)) AND (length(dataset_key) <= 112))),
    CONSTRAINT ck_provider_datasets_display_name_canonical CHECK (((display_name <> ''::text) AND (display_name = btrim(display_name)) AND (display_name = NORMALIZE(display_name, NFC)) AND (length(display_name) <= 256))),
    CONSTRAINT ck_provider_datasets_provider_canonical CHECK (((provider <> ''::text) AND (provider = btrim(provider)) AND (provider = NORMALIZE(provider, NFC)) AND (length(provider) <= 112))),
    CONSTRAINT ck_provider_datasets_source_kind CHECK ((source_kind = ANY (ARRAY['openapi'::text, 'filedata'::text, 'manual'::text, 'system'::text, 'standard'::text, 'internal'::text])))
);


ALTER TABLE provider_sync.provider_datasets OWNER TO ktm_feature_schema_owner;

--
-- Name: provider_datasets_provider_dataset_id_seq; Type: SEQUENCE; Schema: provider_sync; Owner: ktm_feature_schema_owner
--

ALTER TABLE provider_sync.provider_datasets ALTER COLUMN provider_dataset_id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME provider_sync.provider_datasets_provider_dataset_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: provider_sync_state; Type: TABLE; Schema: provider_sync; Owner: ktm_feature_schema_owner
--

CREATE TABLE provider_sync.provider_sync_state (
    sync_scope character varying NOT NULL,
    status character varying DEFAULT 'active'::character varying NOT NULL,
    cursor jsonb DEFAULT '{}'::jsonb NOT NULL,
    last_success_at timestamp with time zone,
    last_failure_at timestamp with time zone,
    consecutive_failures integer DEFAULT 0 NOT NULL,
    next_run_after timestamp with time zone,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    provider_dataset_id bigint NOT NULL,
    operation_key text NOT NULL,
    CONSTRAINT ck_provider_sync_state_ck_provider_sync_state_status CHECK (((status)::text = ANY ((ARRAY['active'::character varying, 'paused'::character varying, 'disabled'::character varying, 'failed'::character varying])::text[])))
);


ALTER TABLE provider_sync.provider_sync_state OWNER TO ktm_feature_schema_owner;

--
-- Name: source_entities; Type: TABLE; Schema: provider_sync; Owner: ktm_feature_schema_owner
--

CREATE TABLE provider_sync.source_entities (
    source_entity_key text NOT NULL,
    source_entity_type text NOT NULL,
    source_entity_id text NOT NULL,
    first_seen_at timestamp with time zone NOT NULL,
    last_seen_at timestamp with time zone NOT NULL,
    provider_dataset_id bigint NOT NULL,
    CONSTRAINT ck_source_entities_seen_order CHECK ((first_seen_at <= last_seen_at))
);


ALTER TABLE provider_sync.source_entities OWNER TO ktm_feature_schema_owner;

--
-- Name: source_links; Type: TABLE; Schema: provider_sync; Owner: ktm_feature_schema_owner
--

CREATE TABLE provider_sync.source_links (
    feature_id character varying NOT NULL,
    source_role character varying DEFAULT 'enrichment'::character varying NOT NULL,
    match_method character varying NOT NULL,
    confidence integer NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    source_entity_key text NOT NULL,
    CONSTRAINT ck_source_links_ck_source_links_confidence CHECK (((confidence >= 0) AND (confidence <= 100))),
    CONSTRAINT ck_source_links_ck_source_links_role CHECK (((source_role)::text = ANY ((ARRAY['primary'::character varying, 'base_address'::character varying, 'base_coordinate'::character varying, 'enrichment'::character varying, 'correction'::character varying, 'duplicate_candidate'::character varying, 'media'::character varying, 'weather_context'::character varying])::text[])))
);


ALTER TABLE provider_sync.source_links OWNER TO ktm_feature_schema_owner;

--
-- Name: source_records; Type: TABLE; Schema: provider_sync; Owner: ktm_feature_schema_owner
--

CREATE TABLE provider_sync.source_records (
    source_record_key character varying NOT NULL,
    raw_data jsonb DEFAULT '{}'::jsonb NOT NULL,
    raw_payload_hash character varying NOT NULL,
    fetched_at timestamp with time zone NOT NULL,
    imported_at timestamp with time zone DEFAULT now() NOT NULL,
    source_entity_key text NOT NULL,
    CONSTRAINT ck_source_records_payload_hash_canonical CHECK (((raw_payload_hash)::text ~ '^[0-9a-f]{1,64}$'::text)),
    CONSTRAINT ck_source_records_raw_data_object CHECK ((jsonb_typeof(raw_data) = 'object'::text))
);


ALTER TABLE provider_sync.source_records OWNER TO ktm_feature_schema_owner;

--
-- Name: import_jobs queue_sequence; Type: DEFAULT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.import_jobs ALTER COLUMN queue_sequence SET DEFAULT nextval('ops.import_jobs_queue_sequence_seq'::regclass);


--
-- Name: curated_features curated_features_pkey; Type: CONSTRAINT; Schema: feature; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY feature.curated_features
    ADD CONSTRAINT curated_features_pkey PRIMARY KEY (curated_feature_id);


--
-- Name: curated_source_rules curated_source_rules_pkey; Type: CONSTRAINT; Schema: feature; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY feature.curated_source_rules
    ADD CONSTRAINT curated_source_rules_pkey PRIMARY KEY (rule_id);


--
-- Name: curated_sources curated_sources_pkey; Type: CONSTRAINT; Schema: feature; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY feature.curated_sources
    ADD CONSTRAINT curated_sources_pkey PRIMARY KEY (source_id);


--
-- Name: curated_themes curated_themes_pkey; Type: CONSTRAINT; Schema: feature; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY feature.curated_themes
    ADD CONSTRAINT curated_themes_pkey PRIMARY KEY (theme_id);


--
-- Name: curated_themes curated_themes_theme_slug_key; Type: CONSTRAINT; Schema: feature; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY feature.curated_themes
    ADD CONSTRAINT curated_themes_theme_slug_key UNIQUE (theme_slug);


--
-- Name: curated_feature_detail_snapshots curated_tripmate_copy_snapshots_pkey; Type: CONSTRAINT; Schema: feature; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY feature.curated_feature_detail_snapshots
    ADD CONSTRAINT curated_tripmate_copy_snapshots_pkey PRIMARY KEY (curated_feature_id);


--
-- Name: curation_collections curation_collections_pkey; Type: CONSTRAINT; Schema: feature; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY feature.curation_collections
    ADD CONSTRAINT curation_collections_pkey PRIMARY KEY (collection_id);


--
-- Name: curation_items curation_items_pkey; Type: CONSTRAINT; Schema: feature; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY feature.curation_items
    ADD CONSTRAINT curation_items_pkey PRIMARY KEY (curation_item_id);


--
-- Name: feature_price_values feature_price_values_pkey; Type: CONSTRAINT; Schema: feature; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY feature.feature_price_values
    ADD CONSTRAINT feature_price_values_pkey PRIMARY KEY (price_value_key);


--
-- Name: feature_state_transitions feature_state_transitions_pkey; Type: CONSTRAINT; Schema: feature; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY feature.feature_state_transitions
    ADD CONSTRAINT feature_state_transitions_pkey PRIMARY KEY (transition_id);


--
-- Name: feature_weather_values feature_weather_values_pkey; Type: CONSTRAINT; Schema: feature; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY feature.feature_weather_values
    ADD CONSTRAINT feature_weather_values_pkey PRIMARY KEY (weather_value_key);


--
-- Name: curation_import_batches pk_curation_import_batches; Type: CONSTRAINT; Schema: feature; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY feature.curation_import_batches
    ADD CONSTRAINT pk_curation_import_batches PRIMARY KEY (import_batch_id);


--
-- Name: curation_import_rows pk_curation_import_rows; Type: CONSTRAINT; Schema: feature; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY feature.curation_import_rows
    ADD CONSTRAINT pk_curation_import_rows PRIMARY KEY (import_row_id);


--
-- Name: curation_link_decisions pk_curation_link_decisions; Type: CONSTRAINT; Schema: feature; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY feature.curation_link_decisions
    ADD CONSTRAINT pk_curation_link_decisions PRIMARY KEY (decision_id);


--
-- Name: current_price_summary pk_current_price_summary; Type: CONSTRAINT; Schema: feature; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY feature.current_price_summary
    ADD CONSTRAINT pk_current_price_summary PRIMARY KEY (feature_id, provider_dataset_id, price_domain, product_key);


--
-- Name: current_weather_summary pk_current_weather_summary; Type: CONSTRAINT; Schema: feature; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY feature.current_weather_summary
    ADD CONSTRAINT pk_current_weather_summary PRIMARY KEY (feature_id, provider_dataset_id, weather_domain, forecast_style, metric_key);


--
-- Name: feature_aliases pk_feature_aliases; Type: CONSTRAINT; Schema: feature; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY feature.feature_aliases
    ADD CONSTRAINT pk_feature_aliases PRIMARY KEY (alias);


--
-- Name: feature_areas pk_feature_areas; Type: CONSTRAINT; Schema: feature; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY feature.feature_areas
    ADD CONSTRAINT pk_feature_areas PRIMARY KEY (feature_id);


--
-- Name: feature_base_field_values pk_feature_base_field_values; Type: CONSTRAINT; Schema: feature; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY feature.feature_base_field_values
    ADD CONSTRAINT pk_feature_base_field_values PRIMARY KEY (feature_id, field_path);


--
-- Name: feature_events pk_feature_events; Type: CONSTRAINT; Schema: feature; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY feature.feature_events
    ADD CONSTRAINT pk_feature_events PRIMARY KEY (feature_id);


--
-- Name: feature_notices pk_feature_notices; Type: CONSTRAINT; Schema: feature; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY feature.feature_notices
    ADD CONSTRAINT pk_feature_notices PRIMARY KEY (feature_id);


--
-- Name: feature_places pk_feature_places; Type: CONSTRAINT; Schema: feature; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY feature.feature_places
    ADD CONSTRAINT pk_feature_places PRIMARY KEY (feature_id);


--
-- Name: feature_routes pk_feature_routes; Type: CONSTRAINT; Schema: feature; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY feature.feature_routes
    ADD CONSTRAINT pk_feature_routes PRIMARY KEY (feature_id);


--
-- Name: features pk_features; Type: CONSTRAINT; Schema: feature; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY feature.features
    ADD CONSTRAINT pk_features PRIMARY KEY (feature_id);


--
-- Name: curated_sources uq_curated_sources_dataset; Type: CONSTRAINT; Schema: feature; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY feature.curated_sources
    ADD CONSTRAINT uq_curated_sources_dataset UNIQUE (provider_dataset_id);


--
-- Name: curation_collections uq_curation_collections_collection_key; Type: CONSTRAINT; Schema: feature; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY feature.curation_collections
    ADD CONSTRAINT uq_curation_collections_collection_key UNIQUE (collection_key);


--
-- Name: curation_import_rows uq_curation_import_rows_batch_row; Type: CONSTRAINT; Schema: feature; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY feature.curation_import_rows
    ADD CONSTRAINT uq_curation_import_rows_batch_row UNIQUE (import_batch_id, row_number);


--
-- Name: curation_import_rows uq_curation_import_rows_item_pointer; Type: CONSTRAINT; Schema: feature; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY feature.curation_import_rows
    ADD CONSTRAINT uq_curation_import_rows_item_pointer UNIQUE (import_row_id, curation_item_id);


--
-- Name: curation_items uq_curation_items_component_identity; Type: CONSTRAINT; Schema: feature; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY feature.curation_items
    ADD CONSTRAINT uq_curation_items_component_identity UNIQUE (collection_id, external_item_id, external_component_id);


--
-- Name: curation_link_decisions uq_curation_link_decisions_item_pointer; Type: CONSTRAINT; Schema: feature; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY feature.curation_link_decisions
    ADD CONSTRAINT uq_curation_link_decisions_item_pointer UNIQUE (decision_id, curation_item_id);


--
-- Name: curation_link_decisions uq_curation_link_decisions_item_target; Type: CONSTRAINT; Schema: feature; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY feature.curation_link_decisions
    ADD CONSTRAINT uq_curation_link_decisions_item_target UNIQUE (decision_id, curation_item_id, feature_id);


--
-- Name: features uq_features_feature_uuid; Type: CONSTRAINT; Schema: feature; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY feature.features
    ADD CONSTRAINT uq_features_feature_uuid UNIQUE (feature_uuid);


--
-- Name: features uq_features_identity_kind; Type: CONSTRAINT; Schema: feature; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY feature.features
    ADD CONSTRAINT uq_features_identity_kind UNIQUE (feature_id, kind);


--
-- Name: features uq_features_identity_pair; Type: CONSTRAINT; Schema: feature; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY feature.features
    ADD CONSTRAINT uq_features_identity_pair UNIQUE (feature_id, feature_uuid);


--
-- Name: feature_price_values uq_price_value_identity; Type: CONSTRAINT; Schema: feature; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY feature.feature_price_values
    ADD CONSTRAINT uq_price_value_identity UNIQUE (feature_id, provider_dataset_id, price_domain, product_key, observed_at, source_record_key);


--
-- Name: feature_weather_values uq_weather_value_identity; Type: CONSTRAINT; Schema: feature; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY feature.feature_weather_values
    ADD CONSTRAINT uq_weather_value_identity UNIQUE (feature_id, provider_dataset_id, weather_domain, forecast_style, metric_key, target_at, source_record_key);


--
-- Name: admin_auth_events admin_auth_events_pkey; Type: CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.admin_auth_events
    ADD CONSTRAINT admin_auth_events_pkey PRIMARY KEY (auth_event_id);


--
-- Name: api_call_log api_call_log_pkey; Type: CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.api_call_log
    ADD CONSTRAINT api_call_log_pkey PRIMARY KEY (api_call_log_id);


--
-- Name: current_summary_runs current_summary_runs_pkey; Type: CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.current_summary_runs
    ADD CONSTRAINT current_summary_runs_pkey PRIMARY KEY (summary_run_id);


--
-- Name: feature_override_field_paths feature_override_field_paths_pkey; Type: CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.feature_override_field_paths
    ADD CONSTRAINT feature_override_field_paths_pkey PRIMARY KEY (field_path);


--
-- Name: import_job_events import_job_events_pkey; Type: CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.import_job_events
    ADD CONSTRAINT import_job_events_pkey PRIMARY KEY (event_id);


--
-- Name: backup_command_executions pk_backup_command_executions; Type: CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.backup_command_executions
    ADD CONSTRAINT pk_backup_command_executions PRIMARY KEY (command_id);


--
-- Name: c6c_cancel_probe_fixtures pk_c6c_cancel_probe_fixtures; Type: CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.c6c_cancel_probe_fixtures
    ADD CONSTRAINT pk_c6c_cancel_probe_fixtures PRIMARY KEY (transaction_id);


--
-- Name: poi_cache_target_snapshot_gc_observations pk_cache_target_snapshot_gc_observations; Type: CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.poi_cache_target_snapshot_gc_observations
    ADD CONSTRAINT pk_cache_target_snapshot_gc_observations PRIMARY KEY (observation_id);


--
-- Name: cache_target_writer_drain_instigations pk_cache_target_writer_drain_instigations; Type: CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.cache_target_writer_drain_instigations
    ADD CONSTRAINT pk_cache_target_writer_drain_instigations PRIMARY KEY (lease_id, kind, selector_id);


--
-- Name: cache_target_writer_drain_leases pk_cache_target_writer_drain_leases; Type: CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.cache_target_writer_drain_leases
    ADD CONSTRAINT pk_cache_target_writer_drain_leases PRIMARY KEY (lease_id);


--
-- Name: cache_target_writer_drain_runs pk_cache_target_writer_drain_runs; Type: CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.cache_target_writer_drain_runs
    ADD CONSTRAINT pk_cache_target_writer_drain_runs PRIMARY KEY (lease_id, dagster_run_id);


--
-- Name: dagster_schedule_active_claims pk_dagster_schedule_active_claims; Type: CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.dagster_schedule_active_claims
    ADD CONSTRAINT pk_dagster_schedule_active_claims PRIMARY KEY (command_id);


--
-- Name: dagster_schedule_audit_events pk_dagster_schedule_audit_events; Type: CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.dagster_schedule_audit_events
    ADD CONSTRAINT pk_dagster_schedule_audit_events PRIMARY KEY (event_id);


--
-- Name: dagster_schedule_claim_resolutions pk_dagster_schedule_claim_resolutions; Type: CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.dagster_schedule_claim_resolutions
    ADD CONSTRAINT pk_dagster_schedule_claim_resolutions PRIMARY KEY (resolution_id);


--
-- Name: dagster_schedule_overrides pk_dagster_schedule_overrides; Type: CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.dagster_schedule_overrides
    ADD CONSTRAINT pk_dagster_schedule_overrides PRIMARY KEY (schedule_name);


--
-- Name: data_integrity_violations pk_data_integrity_violations; Type: CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.data_integrity_violations
    ADD CONSTRAINT pk_data_integrity_violations PRIMARY KEY (issue_id);


--
-- Name: dedup_review_queue pk_dedup_review_queue; Type: CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.dedup_review_queue
    ADD CONSTRAINT pk_dedup_review_queue PRIMARY KEY (review_id);


--
-- Name: domain_command_results pk_domain_command_results; Type: CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.domain_command_results
    ADD CONSTRAINT pk_domain_command_results PRIMARY KEY (command_id);


--
-- Name: domain_commands pk_domain_commands; Type: CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.domain_commands
    ADD CONSTRAINT pk_domain_commands PRIMARY KEY (command_id);


--
-- Name: enrichment_review_queue pk_enrichment_review_queue; Type: CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.enrichment_review_queue
    ADD CONSTRAINT pk_enrichment_review_queue PRIMARY KEY (review_id);


--
-- Name: feature_consistency_reports pk_feature_consistency_reports; Type: CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.feature_consistency_reports
    ADD CONSTRAINT pk_feature_consistency_reports PRIMARY KEY (report_id);


--
-- Name: feature_merge_history pk_feature_merge_history; Type: CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.feature_merge_history
    ADD CONSTRAINT pk_feature_merge_history PRIMARY KEY (merge_id);


--
-- Name: feature_overrides pk_feature_overrides; Type: CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.feature_overrides
    ADD CONSTRAINT pk_feature_overrides PRIMARY KEY (override_id);


--
-- Name: feature_update_request_datasets pk_feature_update_request_datasets; Type: CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.feature_update_request_datasets
    ADD CONSTRAINT pk_feature_update_request_datasets PRIMARY KEY (feature_update_request_dataset_id);


--
-- Name: feature_update_request_idempotency pk_feature_update_request_idempotency; Type: CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.feature_update_request_idempotency
    ADD CONSTRAINT pk_feature_update_request_idempotency PRIMARY KEY (actor, idempotency_key);


--
-- Name: feature_update_requests pk_feature_update_requests; Type: CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.feature_update_requests
    ADD CONSTRAINT pk_feature_update_requests PRIMARY KEY (request_id);


--
-- Name: import_job_datasets pk_import_job_datasets; Type: CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.import_job_datasets
    ADD CONSTRAINT pk_import_job_datasets PRIMARY KEY (import_job_dataset_id);


--
-- Name: import_job_event_clock pk_import_job_event_clock; Type: CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.import_job_event_clock
    ADD CONSTRAINT pk_import_job_event_clock PRIMARY KEY (clock_id);


--
-- Name: import_jobs pk_import_jobs; Type: CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.import_jobs
    ADD CONSTRAINT pk_import_jobs PRIMARY KEY (job_id);


--
-- Name: integrity_finding_observations pk_integrity_finding_observations; Type: CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.integrity_finding_observations
    ADD CONSTRAINT pk_integrity_finding_observations PRIMARY KEY (observation_run_id, dedupe_key);


--
-- Name: integrity_observation_runs pk_integrity_observation_runs; Type: CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.integrity_observation_runs
    ADD CONSTRAINT pk_integrity_observation_runs PRIMARY KEY (observation_run_id);


--
-- Name: integrity_observation_scopes pk_integrity_observation_scopes; Type: CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.integrity_observation_scopes
    ADD CONSTRAINT pk_integrity_observation_scopes PRIMARY KEY (integrity_observation_scope_id);


--
-- Name: managed_file_events pk_managed_file_events; Type: CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.managed_file_events
    ADD CONSTRAINT pk_managed_file_events PRIMARY KEY (event_id);


--
-- Name: managed_files pk_managed_files; Type: CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.managed_files
    ADD CONSTRAINT pk_managed_files PRIMARY KEY (file_id);


--
-- Name: offline_upload_command_executions pk_offline_upload_command_executions; Type: CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.offline_upload_command_executions
    ADD CONSTRAINT pk_offline_upload_command_executions PRIMARY KEY (command_id);


--
-- Name: offline_uploads pk_offline_uploads; Type: CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.offline_uploads
    ADD CONSTRAINT pk_offline_uploads PRIMARY KEY (upload_id);


--
-- Name: ops_live_ticket_claims pk_ops_live_ticket_claims; Type: CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.ops_live_ticket_claims
    ADD CONSTRAINT pk_ops_live_ticket_claims PRIMARY KEY (nonce_hash);


--
-- Name: ops_live_topic_revisions pk_ops_live_topic_revisions; Type: CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.ops_live_topic_revisions
    ADD CONSTRAINT pk_ops_live_topic_revisions PRIMARY KEY (topic);


--
-- Name: pipeline_cancellation_members pk_pipeline_cancellation_members; Type: CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.pipeline_cancellation_members
    ADD CONSTRAINT pk_pipeline_cancellation_members PRIMARY KEY (cancellation_id, job_id);


--
-- Name: pipeline_cancellation_runs pk_pipeline_cancellation_runs; Type: CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.pipeline_cancellation_runs
    ADD CONSTRAINT pk_pipeline_cancellation_runs PRIMARY KEY (cancellation_id, dagster_run_id);


--
-- Name: pipeline_cancellations pk_pipeline_cancellations; Type: CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.pipeline_cancellations
    ADD CONSTRAINT pk_pipeline_cancellations PRIMARY KEY (cancellation_id);


--
-- Name: poi_cache_target_feature_links pk_poi_cache_target_feature_links; Type: CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.poi_cache_target_feature_links
    ADD CONSTRAINT pk_poi_cache_target_feature_links PRIMARY KEY (target_id, feature_id);


--
-- Name: poi_cache_target_outbox_claim_events pk_poi_cache_target_outbox_claim_events; Type: CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.poi_cache_target_outbox_claim_events
    ADD CONSTRAINT pk_poi_cache_target_outbox_claim_events PRIMARY KEY (claim_id, event_id);


--
-- Name: poi_cache_target_outbox_claims pk_poi_cache_target_outbox_claims; Type: CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.poi_cache_target_outbox_claims
    ADD CONSTRAINT pk_poi_cache_target_outbox_claims PRIMARY KEY (claim_id);


--
-- Name: poi_cache_target_outbox_deliveries pk_poi_cache_target_outbox_deliveries; Type: CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.poi_cache_target_outbox_deliveries
    ADD CONSTRAINT pk_poi_cache_target_outbox_deliveries PRIMARY KEY (event_id);


--
-- Name: poi_cache_target_outbox_events pk_poi_cache_target_outbox_events; Type: CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.poi_cache_target_outbox_events
    ADD CONSTRAINT pk_poi_cache_target_outbox_events PRIMARY KEY (event_id);


--
-- Name: poi_cache_target_reconciliation_requests pk_poi_cache_target_reconciliation_requests; Type: CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.poi_cache_target_reconciliation_requests
    ADD CONSTRAINT pk_poi_cache_target_reconciliation_requests PRIMARY KEY (request_id);


--
-- Name: poi_cache_target_refresh_members pk_poi_cache_target_refresh_members; Type: CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.poi_cache_target_refresh_members
    ADD CONSTRAINT pk_poi_cache_target_refresh_members PRIMARY KEY (request_id, target_id);


--
-- Name: poi_cache_target_restore_fences pk_poi_cache_target_restore_fences; Type: CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.poi_cache_target_restore_fences
    ADD CONSTRAINT pk_poi_cache_target_restore_fences PRIMARY KEY (fence_id);


--
-- Name: poi_cache_target_snapshot_items pk_poi_cache_target_snapshot_items; Type: CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.poi_cache_target_snapshot_items
    ADD CONSTRAINT pk_poi_cache_target_snapshot_items PRIMARY KEY (snapshot_id, row_number);


--
-- Name: poi_cache_target_snapshots pk_poi_cache_target_snapshots; Type: CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.poi_cache_target_snapshots
    ADD CONSTRAINT pk_poi_cache_target_snapshots PRIMARY KEY (snapshot_id);


--
-- Name: poi_cache_target_source_events pk_poi_cache_target_source_events; Type: CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.poi_cache_target_source_events
    ADD CONSTRAINT pk_poi_cache_target_source_events PRIMARY KEY (event_id);


--
-- Name: poi_cache_target_source_heads pk_poi_cache_target_source_heads; Type: CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.poi_cache_target_source_heads
    ADD CONSTRAINT pk_poi_cache_target_source_heads PRIMARY KEY (external_system, target_key);


--
-- Name: poi_cache_target_streams pk_poi_cache_target_streams; Type: CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.poi_cache_target_streams
    ADD CONSTRAINT pk_poi_cache_target_streams PRIMARY KEY (external_system);


--
-- Name: poi_cache_targets pk_poi_cache_targets; Type: CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.poi_cache_targets
    ADD CONSTRAINT pk_poi_cache_targets PRIMARY KEY (target_id);


--
-- Name: provider_refresh_policies pk_provider_refresh_policies; Type: CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.provider_refresh_policies
    ADD CONSTRAINT pk_provider_refresh_policies PRIMARY KEY (provider_dataset_id);


--
-- Name: public_api_keys public_api_keys_key_hash_key; Type: CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.public_api_keys
    ADD CONSTRAINT public_api_keys_key_hash_key UNIQUE (key_hash);


--
-- Name: public_api_keys public_api_keys_pkey; Type: CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.public_api_keys
    ADD CONSTRAINT public_api_keys_pkey PRIMARY KEY (public_api_key_id);


--
-- Name: system_log system_log_pkey; Type: CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.system_log
    ADD CONSTRAINT system_log_pkey PRIMARY KEY (system_log_id);


--
-- Name: tvn36_legacy_freeze_preflight_manifest tvn36_legacy_freeze_preflight_manifest_pkey; Type: CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.tvn36_legacy_freeze_preflight_manifest
    ADD CONSTRAINT tvn36_legacy_freeze_preflight_manifest_pkey PRIMARY KEY (feature_id, violation_code, detail);


--
-- Name: c6c_cancel_probe_fixtures uq_c6c_cancel_probe_fixtures_cancellation; Type: CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.c6c_cancel_probe_fixtures
    ADD CONSTRAINT uq_c6c_cancel_probe_fixtures_cancellation UNIQUE (cancellation_id);


--
-- Name: c6c_cancel_probe_fixtures uq_c6c_cancel_probe_fixtures_job; Type: CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.c6c_cancel_probe_fixtures
    ADD CONSTRAINT uq_c6c_cancel_probe_fixtures_job UNIQUE (job_id);


--
-- Name: poi_cache_target_outbox_claim_events uq_cache_target_claim_events_order; Type: CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.poi_cache_target_outbox_claim_events
    ADD CONSTRAINT uq_cache_target_claim_events_order UNIQUE (claim_id, relay_order);


--
-- Name: poi_cache_target_outbox_claim_events uq_cache_target_claim_events_position; Type: CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.poi_cache_target_outbox_claim_events
    ADD CONSTRAINT uq_cache_target_claim_events_position UNIQUE (claim_id, "position");


--
-- Name: poi_cache_target_outbox_claims uq_cache_target_outbox_claims_idempotency; Type: CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.poi_cache_target_outbox_claims
    ADD CONSTRAINT uq_cache_target_outbox_claims_idempotency UNIQUE (external_system, idempotency_key);


--
-- Name: poi_cache_target_outbox_events uq_cache_target_outbox_relay_order; Type: CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.poi_cache_target_outbox_events
    ADD CONSTRAINT uq_cache_target_outbox_relay_order UNIQUE (relay_order);


--
-- Name: poi_cache_target_outbox_events uq_cache_target_outbox_semantic_order; Type: CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.poi_cache_target_outbox_events
    ADD CONSTRAINT uq_cache_target_outbox_semantic_order UNIQUE (external_system, target_key, restore_epoch, source_generation, target_sequence);


--
-- Name: poi_cache_target_reconciliation_requests uq_cache_target_reconciliation_requests_command; Type: CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.poi_cache_target_reconciliation_requests
    ADD CONSTRAINT uq_cache_target_reconciliation_requests_command UNIQUE (command_id);


--
-- Name: poi_cache_target_reconciliation_requests uq_cache_target_reconciliation_requests_stream_request; Type: CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.poi_cache_target_reconciliation_requests
    ADD CONSTRAINT uq_cache_target_reconciliation_requests_stream_request UNIQUE (external_system, request_id);


--
-- Name: poi_cache_target_restore_fences uq_cache_target_restore_fences_command; Type: CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.poi_cache_target_restore_fences
    ADD CONSTRAINT uq_cache_target_restore_fences_command UNIQUE (command_id);


--
-- Name: poi_cache_target_restore_fences uq_cache_target_restore_fences_epoch; Type: CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.poi_cache_target_restore_fences
    ADD CONSTRAINT uq_cache_target_restore_fences_epoch UNIQUE (external_system, restore_epoch);


--
-- Name: poi_cache_target_snapshot_gc_observations uq_cache_target_snapshot_gc_observations_run_id; Type: CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.poi_cache_target_snapshot_gc_observations
    ADD CONSTRAINT uq_cache_target_snapshot_gc_observations_run_id UNIQUE (dagster_run_id);


--
-- Name: poi_cache_target_snapshot_items uq_cache_target_snapshot_items_key; Type: CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.poi_cache_target_snapshot_items
    ADD CONSTRAINT uq_cache_target_snapshot_items_key UNIQUE (snapshot_id, external_system, target_key);


--
-- Name: poi_cache_target_snapshots uq_cache_target_snapshots_stream; Type: CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.poi_cache_target_snapshots
    ADD CONSTRAINT uq_cache_target_snapshots_stream UNIQUE (snapshot_id, external_system);


--
-- Name: poi_cache_target_source_events uq_cache_target_source_events_generation; Type: CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.poi_cache_target_source_events
    ADD CONSTRAINT uq_cache_target_source_events_generation UNIQUE (external_system, target_key, restore_epoch, source_generation);


--
-- Name: poi_cache_target_source_events uq_cache_target_source_events_idempotency; Type: CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.poi_cache_target_source_events
    ADD CONSTRAINT uq_cache_target_source_events_idempotency UNIQUE (external_system, idempotency_key);


--
-- Name: cache_target_writer_drain_leases uq_cache_target_writer_drain_leases_owner; Type: CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.cache_target_writer_drain_leases
    ADD CONSTRAINT uq_cache_target_writer_drain_leases_owner UNIQUE (owner_kind, owner_id);


--
-- Name: current_summary_runs uq_current_summary_runs_receipt_state; Type: CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.current_summary_runs
    ADD CONSTRAINT uq_current_summary_runs_receipt_state UNIQUE (summary_run_id, projection_kind, status);


--
-- Name: dagster_schedule_active_claims uq_dagster_schedule_active_claims_schedule_name; Type: CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.dagster_schedule_active_claims
    ADD CONSTRAINT uq_dagster_schedule_active_claims_schedule_name UNIQUE (schedule_name);


--
-- Name: dagster_schedule_claim_resolutions uq_dagster_schedule_claim_resolutions_command_id; Type: CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.dagster_schedule_claim_resolutions
    ADD CONSTRAINT uq_dagster_schedule_claim_resolutions_command_id UNIQUE (command_id);


--
-- Name: dedup_review_queue uq_dedup_pair; Type: CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.dedup_review_queue
    ADD CONSTRAINT uq_dedup_pair UNIQUE (feature_id_a, feature_id_b);


--
-- Name: domain_commands uq_domain_commands_actor_operation_key; Type: CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.domain_commands
    ADD CONSTRAINT uq_domain_commands_actor_operation_key UNIQUE (actor, operation, idempotency_key);


--
-- Name: enrichment_review_queue uq_enrichment_review_candidate; Type: CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.enrichment_review_queue
    ADD CONSTRAINT uq_enrichment_review_candidate UNIQUE (target_feature_id, source_entity_key);


--
-- Name: feature_override_field_paths uq_feature_override_field_paths_target; Type: CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.feature_override_field_paths
    ADD CONSTRAINT uq_feature_override_field_paths_target UNIQUE (feature_kind, target_relation, target_column);


--
-- Name: feature_update_request_datasets uq_feature_update_request_datasets_identity; Type: CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.feature_update_request_datasets
    ADD CONSTRAINT uq_feature_update_request_datasets_identity UNIQUE (request_id, provider_dataset_id, sync_scope, operation_key);


--
-- Name: feature_update_requests uq_feature_update_requests_job_id; Type: CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.feature_update_requests
    ADD CONSTRAINT uq_feature_update_requests_job_id UNIQUE (job_id);


--
-- Name: import_job_datasets uq_import_job_datasets_exact_identity; Type: CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.import_job_datasets
    ADD CONSTRAINT uq_import_job_datasets_exact_identity UNIQUE (job_id, provider_dataset_id, sync_scope, operation_key);


--
-- Name: import_job_datasets uq_import_job_datasets_job_member; Type: CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.import_job_datasets
    ADD CONSTRAINT uq_import_job_datasets_job_member UNIQUE (job_id, import_job_dataset_id);


--
-- Name: integrity_observation_runs uq_integrity_observation_runs_external_run_v2; Type: CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.integrity_observation_runs
    ADD CONSTRAINT uq_integrity_observation_runs_external_run_v2 UNIQUE (integrity_observation_scope_id, external_run_id);


--
-- Name: integrity_observation_runs uq_integrity_observation_runs_generation_v2; Type: CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.integrity_observation_runs
    ADD CONSTRAINT uq_integrity_observation_runs_generation_v2 UNIQUE (integrity_observation_scope_id, generation);


--
-- Name: integrity_observation_scopes uq_integrity_observation_scopes_dataset; Type: CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.integrity_observation_scopes
    ADD CONSTRAINT uq_integrity_observation_scopes_dataset UNIQUE (provider_dataset_id);


--
-- Name: managed_files uq_managed_files_backend_location_path; Type: CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.managed_files
    ADD CONSTRAINT uq_managed_files_backend_location_path UNIQUE (storage_backend, location, path);


--
-- Name: offline_uploads uq_offline_uploads_dataset_scope_checksum; Type: CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.offline_uploads
    ADD CONSTRAINT uq_offline_uploads_dataset_scope_checksum UNIQUE (provider_dataset_id, sync_scope, operation_key, checksum_sha256);


--
-- Name: notice_lifecycle_scopes pk_notice_lifecycle_scopes; Type: CONSTRAINT; Schema: provider_sync; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY provider_sync.notice_lifecycle_scopes
    ADD CONSTRAINT pk_notice_lifecycle_scopes PRIMARY KEY (notice_lifecycle_scope_id);


--
-- Name: notice_lineage_states pk_notice_lineage_states; Type: CONSTRAINT; Schema: provider_sync; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY provider_sync.notice_lineage_states
    ADD CONSTRAINT pk_notice_lineage_states PRIMARY KEY (notice_lifecycle_scope_id, lineage_key);


--
-- Name: provider_dataset_operation_scopes pk_provider_dataset_operation_scopes; Type: CONSTRAINT; Schema: provider_sync; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY provider_sync.provider_dataset_operation_scopes
    ADD CONSTRAINT pk_provider_dataset_operation_scopes PRIMARY KEY (provider_dataset_id, sync_scope, operation_key);


--
-- Name: provider_dataset_operations pk_provider_dataset_operations; Type: CONSTRAINT; Schema: provider_sync; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY provider_sync.provider_dataset_operations
    ADD CONSTRAINT pk_provider_dataset_operations PRIMARY KEY (provider_dataset_id, operation_key);


--
-- Name: provider_datasets pk_provider_datasets; Type: CONSTRAINT; Schema: provider_sync; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY provider_sync.provider_datasets
    ADD CONSTRAINT pk_provider_datasets PRIMARY KEY (provider_dataset_id);


--
-- Name: provider_sync_state pk_provider_sync_state; Type: CONSTRAINT; Schema: provider_sync; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY provider_sync.provider_sync_state
    ADD CONSTRAINT pk_provider_sync_state PRIMARY KEY (provider_dataset_id, sync_scope, operation_key);


--
-- Name: source_entity_heads pk_source_entity_heads; Type: CONSTRAINT; Schema: provider_sync; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY provider_sync.source_entity_heads
    ADD CONSTRAINT pk_source_entity_heads PRIMARY KEY (source_entity_key);


--
-- Name: source_links pk_source_links; Type: CONSTRAINT; Schema: provider_sync; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY provider_sync.source_links
    ADD CONSTRAINT pk_source_links PRIMARY KEY (feature_id, source_entity_key);


--
-- Name: source_records pk_source_records; Type: CONSTRAINT; Schema: provider_sync; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY provider_sync.source_records
    ADD CONSTRAINT pk_source_records PRIMARY KEY (source_record_key);


--
-- Name: source_entities source_entities_pkey; Type: CONSTRAINT; Schema: provider_sync; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY provider_sync.source_entities
    ADD CONSTRAINT source_entities_pkey PRIMARY KEY (source_entity_key);


--
-- Name: notice_lifecycle_scopes uq_notice_lifecycle_scopes_identity; Type: CONSTRAINT; Schema: provider_sync; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY provider_sync.notice_lifecycle_scopes
    ADD CONSTRAINT uq_notice_lifecycle_scopes_identity UNIQUE (provider_dataset_id, source_entity_type);


--
-- Name: provider_dataset_operations uq_provider_dataset_operations_kind; Type: CONSTRAINT; Schema: provider_sync; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY provider_sync.provider_dataset_operations
    ADD CONSTRAINT uq_provider_dataset_operations_kind UNIQUE (provider_dataset_id, operation_key, operation_kind);


--
-- Name: provider_datasets uq_provider_datasets_identity; Type: CONSTRAINT; Schema: provider_sync; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY provider_sync.provider_datasets
    ADD CONSTRAINT uq_provider_datasets_identity UNIQUE (provider, dataset_key);


--
-- Name: source_entities uq_source_entities_key_dataset; Type: CONSTRAINT; Schema: provider_sync; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY provider_sync.source_entities
    ADD CONSTRAINT uq_source_entities_key_dataset UNIQUE (source_entity_key, provider_dataset_id);


--
-- Name: source_entities uq_source_entities_provider_identity; Type: CONSTRAINT; Schema: provider_sync; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY provider_sync.source_entities
    ADD CONSTRAINT uq_source_entities_provider_identity UNIQUE (provider_dataset_id, source_entity_type, source_entity_id);


--
-- Name: source_records uq_source_records_entity_payload; Type: CONSTRAINT; Schema: provider_sync; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY provider_sync.source_records
    ADD CONSTRAINT uq_source_records_entity_payload UNIQUE (source_entity_key, raw_payload_hash);


--
-- Name: source_records uq_source_records_entity_record; Type: CONSTRAINT; Schema: provider_sync; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY provider_sync.source_records
    ADD CONSTRAINT uq_source_records_entity_record UNIQUE (source_entity_key, source_record_key);


--
-- Name: source_records uq_source_records_record_entity_fetched; Type: CONSTRAINT; Schema: provider_sync; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY provider_sync.source_records
    ADD CONSTRAINT uq_source_records_record_entity_fetched UNIQUE (source_record_key, source_entity_key, fetched_at);


--
-- Name: idx_curated_feature_detail_snapshots_etag; Type: INDEX; Schema: feature; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_curated_feature_detail_snapshots_etag ON feature.curated_feature_detail_snapshots USING btree (etag);


--
-- Name: idx_curated_feature_detail_snapshots_updated; Type: INDEX; Schema: feature; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_curated_feature_detail_snapshots_updated ON feature.curated_feature_detail_snapshots USING btree (updated_at DESC, curated_feature_id DESC);


--
-- Name: idx_curated_features_feature; Type: INDEX; Schema: feature; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_curated_features_feature ON feature.curated_features USING btree (feature_id);


--
-- Name: idx_curated_features_source_status; Type: INDEX; Schema: feature; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_curated_features_source_status ON feature.curated_features USING btree (source_id, curation_status);


--
-- Name: idx_curated_features_status_keyset; Type: INDEX; Schema: feature; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_curated_features_status_keyset ON feature.curated_features USING btree (curation_status, updated_at DESC, curated_feature_id DESC);


--
-- Name: idx_curated_features_theme_status_score; Type: INDEX; Schema: feature; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_curated_features_theme_status_score ON feature.curated_features USING btree (theme_id, curation_status, rank_score DESC, curated_feature_id DESC);


--
-- Name: idx_curated_source_rules_enabled; Type: INDEX; Schema: feature; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_curated_source_rules_enabled ON feature.curated_source_rules USING btree (enabled, source_id, priority DESC);


--
-- Name: idx_curated_source_rules_theme; Type: INDEX; Schema: feature; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_curated_source_rules_theme ON feature.curated_source_rules USING btree (theme_id, enabled, priority DESC);


--
-- Name: idx_curated_sources_status; Type: INDEX; Schema: feature; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_curated_sources_status ON feature.curated_sources USING btree (provider_status, updated_at DESC, source_id DESC);


--
-- Name: idx_curated_themes_group_visibility; Type: INDEX; Schema: feature; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_curated_themes_group_visibility ON feature.curated_themes USING btree (theme_group, visibility, theme_slug);


--
-- Name: idx_curation_collections_source_status; Type: INDEX; Schema: feature; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_curation_collections_source_status ON feature.curation_collections USING btree (source_id, status, collection_id);


--
-- Name: idx_curation_collections_theme_status_edition; Type: INDEX; Schema: feature; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_curation_collections_theme_status_edition ON feature.curation_collections USING btree (theme_id, status, edition_key, collection_id);


--
-- Name: idx_curation_import_batches_sha_time; Type: INDEX; Schema: feature; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_curation_import_batches_sha_time ON feature.curation_import_batches USING btree (content_sha256, imported_at DESC, import_batch_id);


--
-- Name: idx_curation_import_rows_item_time; Type: INDEX; Schema: feature; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_curation_import_rows_item_time ON feature.curation_import_rows USING btree (curation_item_id, imported_at DESC, import_row_id);


--
-- Name: idx_curation_items_collection_status_order; Type: INDEX; Schema: feature; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_curation_items_collection_status_order ON feature.curation_items USING btree (collection_id, source_present, status, sort_order, curation_item_id);


--
-- Name: idx_curation_items_feature_status_collection; Type: INDEX; Schema: feature; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_curation_items_feature_status_collection ON feature.curation_items USING btree (feature_id, source_present, status, collection_id);


--
-- Name: idx_curation_link_decisions_basis_time; Type: INDEX; Schema: feature; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_curation_link_decisions_basis_time ON feature.curation_link_decisions USING btree (match_basis, decided_at DESC, decision_id);


--
-- Name: idx_curation_link_decisions_item_time; Type: INDEX; Schema: feature; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_curation_link_decisions_item_time ON feature.curation_link_decisions USING btree (curation_item_id, decided_at DESC, decision_id);


--
-- Name: idx_current_price_summary_fact; Type: INDEX; Schema: feature; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_current_price_summary_fact ON feature.current_price_summary USING btree (price_value_key);


--
-- Name: idx_current_weather_summary_fact; Type: INDEX; Schema: feature; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_current_weather_summary_fact ON feature.current_weather_summary USING btree (weather_value_key);


--
-- Name: idx_feature_aliases_alias_c; Type: INDEX; Schema: feature; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_feature_aliases_alias_c ON feature.feature_aliases USING btree (alias COLLATE "C");


--
-- Name: idx_feature_aliases_feature; Type: INDEX; Schema: feature; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_feature_aliases_feature ON feature.feature_aliases USING btree (feature_id);


--
-- Name: idx_feature_aliases_feature_uuid; Type: INDEX; Schema: feature; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_feature_aliases_feature_uuid ON feature.feature_aliases USING btree (feature_uuid);


--
-- Name: idx_feature_areas_geom_gist; Type: INDEX; Schema: feature; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_feature_areas_geom_gist ON feature.feature_areas USING gist (geom) WHERE public_ready;


--
-- Name: idx_feature_base_field_values_source; Type: INDEX; Schema: feature; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_feature_base_field_values_source ON feature.feature_base_field_values USING btree (provider_dataset_id, source_entity_key, source_record_key);


--
-- Name: idx_feature_events_opening_hours; Type: INDEX; Schema: feature; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_feature_events_opening_hours ON feature.feature_events USING btree (feature_id) WHERE (opening_hours IS NOT NULL);


--
-- Name: idx_feature_events_period; Type: INDEX; Schema: feature; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_feature_events_period ON feature.feature_events USING btree (starts_on, ends_on);


--
-- Name: idx_feature_notices_validity; Type: INDEX; Schema: feature; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_feature_notices_validity ON feature.feature_notices USING btree (valid_end_time, valid_start_time);


--
-- Name: idx_feature_places_opening_hours; Type: INDEX; Schema: feature; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_feature_places_opening_hours ON feature.feature_places USING btree (feature_id) WHERE (business_hours IS NOT NULL);


--
-- Name: idx_feature_routes_geom_gist; Type: INDEX; Schema: feature; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_feature_routes_geom_gist ON feature.feature_routes USING gist (geom) WHERE public_ready;


--
-- Name: idx_feature_state_transitions_feature_occurred; Type: INDEX; Schema: feature; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_feature_state_transitions_feature_occurred ON feature.feature_state_transitions USING btree (feature_id, occurred_at, transition_id);


--
-- Name: idx_features_admin_created_keyset; Type: INDEX; Schema: feature; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_features_admin_created_keyset ON feature.features USING btree (created_at DESC, feature_id DESC);


--
-- Name: idx_features_admin_lower_name_keyset; Type: INDEX; Schema: feature; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_features_admin_lower_name_keyset ON feature.features USING btree (lower((name)::text), feature_id);


--
-- Name: idx_features_admin_updated_keyset; Type: INDEX; Schema: feature; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_features_admin_updated_keyset ON feature.features USING btree (updated_at DESC, feature_id DESC);


--
-- Name: idx_features_coord_5179_gist; Type: INDEX; Schema: feature; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_features_coord_5179_gist ON feature.features USING gist (coord_5179) WHERE ((lifecycle_state = 'active'::text) AND (publication_state = 'published'::text) AND (quality_state = 'valid'::text));


--
-- Name: idx_features_coord_gist; Type: INDEX; Schema: feature; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_features_coord_gist ON feature.features USING gist (coord) WHERE ((lifecycle_state = 'active'::text) AND (publication_state = 'published'::text) AND (quality_state = 'valid'::text));


--
-- Name: idx_features_kind_category; Type: INDEX; Schema: feature; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_features_kind_category ON feature.features USING btree (kind, category) WHERE ((lifecycle_state = 'active'::text) AND (publication_state = 'published'::text) AND (quality_state = 'valid'::text));


--
-- Name: idx_features_legal_dong_code; Type: INDEX; Schema: feature; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_features_legal_dong_code ON feature.features USING btree (legal_dong_code);


--
-- Name: idx_features_lower_name_keyset; Type: INDEX; Schema: feature; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_features_lower_name_keyset ON feature.features USING btree (lower((name)::text), feature_id) WHERE ((lifecycle_state = 'active'::text) AND (publication_state = 'published'::text) AND (quality_state = 'valid'::text));


--
-- Name: idx_features_name_trgm; Type: INDEX; Schema: feature; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_features_name_trgm ON feature.features USING gin (name x_extension.gin_trgm_ops) WHERE ((lifecycle_state = 'active'::text) AND (publication_state = 'published'::text) AND (quality_state = 'valid'::text));


--
-- Name: idx_features_parent; Type: INDEX; Schema: feature; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_features_parent ON feature.features USING btree (parent_feature_id) WHERE (parent_feature_id IS NOT NULL);


--
-- Name: idx_features_public_weather_coord_5179_gist; Type: INDEX; Schema: feature; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_features_public_weather_coord_5179_gist ON feature.features USING gist (coord_5179) WHERE ((lifecycle_state = 'active'::text) AND (publication_state = 'published'::text) AND (quality_state = 'valid'::text) AND ((kind)::text = 'weather'::text) AND (coord_5179 IS NOT NULL));


--
-- Name: idx_features_sibling; Type: INDEX; Schema: feature; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_features_sibling ON feature.features USING btree (sibling_group_id) WHERE (sibling_group_id IS NOT NULL);


--
-- Name: idx_features_sigungu; Type: INDEX; Schema: feature; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_features_sigungu ON feature.features USING btree (sigungu_code, kind) WHERE ((lifecycle_state = 'active'::text) AND (publication_state = 'published'::text) AND (quality_state = 'valid'::text) AND (sigungu_code IS NOT NULL));


--
-- Name: idx_features_updated_keyset; Type: INDEX; Schema: feature; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_features_updated_keyset ON feature.features USING btree (updated_at DESC, feature_id DESC) WHERE ((lifecycle_state = 'active'::text) AND (publication_state = 'published'::text) AND (quality_state = 'valid'::text));


--
-- Name: idx_price_values_feature_observed_identity; Type: INDEX; Schema: feature; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_price_values_feature_observed_identity ON feature.feature_price_values USING btree (feature_id, observed_at DESC, known_at DESC, provider_dataset_id, price_domain, product_key);


--
-- Name: idx_weather_values_feature_target_known; Type: INDEX; Schema: feature; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_weather_values_feature_target_known ON feature.feature_weather_values USING btree (feature_id, target_at DESC, known_at DESC);


--
-- Name: uq_curated_features_theme_feature_active; Type: INDEX; Schema: feature; Owner: ktm_feature_schema_owner
--

CREATE UNIQUE INDEX uq_curated_features_theme_feature_active ON feature.curated_features USING btree (theme_id, feature_id) WHERE (archived_at IS NULL);


--
-- Name: uq_curation_items_active_source_feature; Type: INDEX; Schema: feature; Owner: ktm_feature_schema_owner
--

CREATE UNIQUE INDEX uq_curation_items_active_source_feature ON feature.curation_items USING btree (collection_id, external_item_id, feature_id) WHERE (source_present AND (archived_at IS NULL) AND (feature_id IS NOT NULL));


--
-- Name: uq_curation_items_legacy_projection_id; Type: INDEX; Schema: feature; Owner: ktm_feature_schema_owner
--

CREATE UNIQUE INDEX uq_curation_items_legacy_projection_id ON feature.curation_items USING btree (legacy_projection_id) WHERE (legacy_projection_id IS NOT NULL);


--
-- Name: uq_price_value_summary_reference; Type: INDEX; Schema: feature; Owner: ktm_feature_schema_owner
--

CREATE UNIQUE INDEX uq_price_value_summary_reference ON feature.feature_price_values USING btree (price_value_key, feature_id, provider_dataset_id, price_domain, product_key);


--
-- Name: uq_weather_value_summary_reference; Type: INDEX; Schema: feature; Owner: ktm_feature_schema_owner
--

CREATE UNIQUE INDEX uq_weather_value_summary_reference ON feature.feature_weather_values USING btree (weather_value_key, feature_id, provider_dataset_id, weather_domain, forecast_style, metric_key);


--
-- Name: idx_admin_auth_events_created_at; Type: INDEX; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_admin_auth_events_created_at ON ops.admin_auth_events USING btree (created_at DESC, auth_event_id DESC);


--
-- Name: idx_admin_auth_events_outcome_time; Type: INDEX; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_admin_auth_events_outcome_time ON ops.admin_auth_events USING btree (outcome, created_at DESC, auth_event_id DESC);


--
-- Name: idx_api_call_log_keyset; Type: INDEX; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_api_call_log_keyset ON ops.api_call_log USING btree (created_at DESC, api_call_log_id DESC);


--
-- Name: idx_api_call_log_status; Type: INDEX; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_api_call_log_status ON ops.api_call_log USING btree (status_code, created_at DESC);


--
-- Name: idx_cache_target_claim_events_applied_gap; Type: INDEX; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_cache_target_claim_events_applied_gap ON ops.poi_cache_target_outbox_claim_events USING btree (claim_id, relay_order) WHERE ((consumer_applied_at IS NOT NULL) AND (prefix_acked_at IS NULL));


--
-- Name: idx_cache_target_outbox_claims_lease; Type: INDEX; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_cache_target_outbox_claims_lease ON ops.poi_cache_target_outbox_claims USING btree (lease_expires_at, external_system) WHERE (status = 'active'::text);


--
-- Name: idx_cache_target_outbox_deliveries_claim; Type: INDEX; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_cache_target_outbox_deliveries_claim ON ops.poi_cache_target_outbox_deliveries USING btree (claim_id, event_id) WHERE (claim_id IS NOT NULL);


--
-- Name: idx_cache_target_outbox_deliveries_due; Type: INDEX; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_cache_target_outbox_deliveries_due ON ops.poi_cache_target_outbox_deliveries USING btree (available_at, event_id) WHERE (status = ANY (ARRAY['pending'::text, 'retry'::text]));


--
-- Name: idx_cache_target_outbox_state_material_order; Type: INDEX; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_cache_target_outbox_state_material_order ON ops.poi_cache_target_outbox_events USING btree (external_system, relay_order DESC) WHERE (event_type = 'cache_target.state_applied'::text);


--
-- Name: idx_cache_target_outbox_stream_order; Type: INDEX; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_cache_target_outbox_stream_order ON ops.poi_cache_target_outbox_events USING btree (external_system, relay_order);


--
-- Name: idx_cache_target_reconciliation_requests_snapshot_status; Type: INDEX; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_cache_target_reconciliation_requests_snapshot_status ON ops.poi_cache_target_reconciliation_requests USING btree (snapshot_id, status) WHERE (snapshot_id IS NOT NULL);


--
-- Name: idx_cache_target_reconciliation_requests_stream_status; Type: INDEX; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_cache_target_reconciliation_requests_stream_status ON ops.poi_cache_target_reconciliation_requests USING btree (external_system, status, created_at DESC, request_id);


--
-- Name: idx_cache_target_refresh_members_target; Type: INDEX; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_cache_target_refresh_members_target ON ops.poi_cache_target_refresh_members USING btree (target_id, request_id);


--
-- Name: idx_cache_target_snapshot_gc_observations_growth_baseline; Type: INDEX; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_cache_target_snapshot_gc_observations_growth_baseline ON ops.poi_cache_target_snapshot_gc_observations USING btree (observation_id) WHERE growth_baseline_eligible;


--
-- Name: idx_cache_target_snapshot_gc_observations_time; Type: INDEX; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_cache_target_snapshot_gc_observations_time ON ops.poi_cache_target_snapshot_gc_observations USING btree (observed_at);


--
-- Name: idx_cache_target_snapshots_expiry; Type: INDEX; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_cache_target_snapshots_expiry ON ops.poi_cache_target_snapshots USING btree (expires_at, snapshot_id);


--
-- Name: idx_cache_target_snapshots_stream_expiry; Type: INDEX; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_cache_target_snapshots_stream_expiry ON ops.poi_cache_target_snapshots USING btree (external_system, expires_at, snapshot_id);


--
-- Name: idx_cache_target_snapshots_stream_time; Type: INDEX; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_cache_target_snapshots_stream_time ON ops.poi_cache_target_snapshots USING btree (external_system, created_at DESC, snapshot_id);


--
-- Name: idx_cache_target_source_events_head_time; Type: INDEX; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_cache_target_source_events_head_time ON ops.poi_cache_target_source_events USING btree (external_system, target_key, recorded_at DESC, event_id);


--
-- Name: idx_cache_target_source_heads_target; Type: INDEX; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE UNIQUE INDEX idx_cache_target_source_heads_target ON ops.poi_cache_target_source_heads USING btree (target_id) WHERE (target_id IS NOT NULL);


--
-- Name: idx_cache_target_writer_drain_instigations_lease; Type: INDEX; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_cache_target_writer_drain_instigations_lease ON ops.cache_target_writer_drain_instigations USING btree (lease_id);


--
-- Name: idx_cache_target_writer_drain_leases_owner_history; Type: INDEX; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_cache_target_writer_drain_leases_owner_history ON ops.cache_target_writer_drain_leases USING btree (owner_kind, owner_id, created_at DESC);


--
-- Name: idx_cache_target_writer_drain_runs_lease; Type: INDEX; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_cache_target_writer_drain_runs_lease ON ops.cache_target_writer_drain_runs USING btree (lease_id);


--
-- Name: idx_current_summary_runs_projection_finished; Type: INDEX; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_current_summary_runs_projection_finished ON ops.current_summary_runs USING btree (projection_kind, finished_at DESC) WHERE (status = 'succeeded'::text);


--
-- Name: idx_dagster_schedule_audit_command; Type: INDEX; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_dagster_schedule_audit_command ON ops.dagster_schedule_audit_events USING btree (command_id, event_id);


--
-- Name: idx_dagster_schedule_audit_schedule_created; Type: INDEX; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_dagster_schedule_audit_schedule_created ON ops.dagster_schedule_audit_events USING btree (schedule_name, created_at DESC, event_id DESC);


--
-- Name: idx_dagster_schedule_claim_resolutions_schedule_created; Type: INDEX; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_dagster_schedule_claim_resolutions_schedule_created ON ops.dagster_schedule_claim_resolutions USING btree (schedule_name, created_at DESC, resolution_id DESC);


--
-- Name: idx_data_integrity_violations_dataset_status; Type: INDEX; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_data_integrity_violations_dataset_status ON ops.data_integrity_violations USING btree (provider_dataset_id, status, last_seen_at DESC) WHERE (provider_dataset_id IS NOT NULL);


--
-- Name: idx_dedup_status_score; Type: INDEX; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_dedup_status_score ON ops.dedup_review_queue USING btree (status, total_score DESC, review_id DESC);


--
-- Name: idx_enrichment_review_queue_source_entity_record; Type: INDEX; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_enrichment_review_queue_source_entity_record ON ops.enrichment_review_queue USING btree (source_entity_key, source_record_key);


--
-- Name: idx_enrichment_review_status_score; Type: INDEX; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_enrichment_review_status_score ON ops.enrichment_review_queue USING btree (status, name_score DESC, review_id DESC);


--
-- Name: idx_feature_update_created; Type: INDEX; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_feature_update_created ON ops.feature_update_requests USING btree (created_at DESC, request_id DESC);


--
-- Name: idx_feature_update_priority; Type: INDEX; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_feature_update_priority ON ops.feature_update_requests USING btree (priority DESC, created_at, request_id);


--
-- Name: idx_feature_update_request_datasets_dataset_request; Type: INDEX; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_feature_update_request_datasets_dataset_request ON ops.feature_update_request_datasets USING btree (provider_dataset_id, request_id);


--
-- Name: idx_feature_update_request_idempotency_request; Type: INDEX; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_feature_update_request_idempotency_request ON ops.feature_update_request_idempotency USING btree (request_id);


--
-- Name: idx_import_job_datasets_exact_operation_job; Type: INDEX; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_import_job_datasets_exact_operation_job ON ops.import_job_datasets USING btree (provider_dataset_id, sync_scope, operation_key, job_id);


--
-- Name: idx_import_job_events_job_time; Type: INDEX; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_import_job_events_job_time ON ops.import_job_events USING btree (job_id, occurred_at DESC, event_id DESC) WHERE (quarantined_at IS NULL);


--
-- Name: idx_import_job_events_level_time; Type: INDEX; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_import_job_events_level_time ON ops.import_job_events USING btree (level, occurred_at DESC, event_id DESC) WHERE (quarantined_at IS NULL);


--
-- Name: idx_import_job_events_member_time; Type: INDEX; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_import_job_events_member_time ON ops.import_job_events USING btree (import_job_dataset_id, occurred_at DESC, event_id DESC) INCLUDE (level) WHERE ((import_job_dataset_id IS NOT NULL) AND (quarantined_at IS NULL));


--
-- Name: idx_import_job_events_time; Type: INDEX; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_import_job_events_time ON ops.import_job_events USING btree (occurred_at DESC, event_id DESC) WHERE (quarantined_at IS NULL);


--
-- Name: idx_import_jobs_cancellation_id; Type: INDEX; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_import_jobs_cancellation_id ON ops.import_jobs USING btree (cancellation_id);


--
-- Name: idx_import_jobs_created_keyset; Type: INDEX; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_import_jobs_created_keyset ON ops.import_jobs USING btree (created_at DESC, job_id DESC);


--
-- Name: idx_import_jobs_dagster_run_id; Type: INDEX; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_import_jobs_dagster_run_id ON ops.import_jobs USING btree (dagster_run_id) WHERE (dagster_run_id IS NOT NULL);


--
-- Name: idx_import_jobs_feature_update_queue; Type: INDEX; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_import_jobs_feature_update_queue ON ops.import_jobs USING btree (job_id) WHERE ((kind = 'feature_update_request'::text) AND (status = 'queued'::text) AND (cancellation_id IS NULL));


--
-- Name: idx_import_jobs_heartbeat; Type: INDEX; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_import_jobs_heartbeat ON ops.import_jobs USING btree (heartbeat_at) WHERE (status = 'running'::text);


--
-- Name: idx_import_jobs_kind_status; Type: INDEX; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_import_jobs_kind_status ON ops.import_jobs USING btree (kind, status, created_at DESC, job_id DESC);


--
-- Name: idx_import_jobs_load_batch_created; Type: INDEX; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_import_jobs_load_batch_created ON ops.import_jobs USING btree (load_batch_id, created_at DESC, job_id DESC) WHERE (load_batch_id IS NOT NULL);


--
-- Name: idx_import_jobs_parent_created; Type: INDEX; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_import_jobs_parent_created ON ops.import_jobs USING btree (parent_job_id, created_at DESC, job_id DESC) WHERE (parent_job_id IS NOT NULL);


--
-- Name: idx_import_jobs_quarantined; Type: INDEX; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_import_jobs_quarantined ON ops.import_jobs USING btree (quarantined_at DESC, job_id DESC) WHERE (quarantined_at IS NOT NULL);


--
-- Name: idx_import_jobs_root; Type: INDEX; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_import_jobs_root ON ops.import_jobs USING btree (root_id, root_kind);


--
-- Name: idx_import_jobs_status; Type: INDEX; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_import_jobs_status ON ops.import_jobs USING btree (status, created_at, queue_sequence);


--
-- Name: idx_integrity_finding_observations_key_run; Type: INDEX; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_integrity_finding_observations_key_run ON ops.integrity_finding_observations USING btree (dedupe_key, observation_run_id);


--
-- Name: idx_integrity_observation_runs_scope_status; Type: INDEX; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_integrity_observation_runs_scope_status ON ops.integrity_observation_runs USING btree (integrity_observation_scope_id, status, generation DESC);


--
-- Name: idx_managed_file_events_file; Type: INDEX; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_managed_file_events_file ON ops.managed_file_events USING btree (file_id, occurred_at DESC);


--
-- Name: idx_managed_file_events_job; Type: INDEX; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_managed_file_events_job ON ops.managed_file_events USING btree (import_job_id) WHERE (import_job_id IS NOT NULL);


--
-- Name: idx_managed_files_kind_downloaded; Type: INDEX; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_managed_files_kind_downloaded ON ops.managed_files USING btree (kind, downloaded_at DESC);


--
-- Name: idx_managed_files_origin_job; Type: INDEX; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_managed_files_origin_job ON ops.managed_files USING btree (origin_import_job_id) WHERE (origin_import_job_id IS NOT NULL);


--
-- Name: idx_managed_files_provider_dataset; Type: INDEX; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_managed_files_provider_dataset ON ops.managed_files USING btree (provider_dataset_id) WHERE (provider_dataset_id IS NOT NULL);


--
-- Name: idx_managed_files_provider_name; Type: INDEX; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_managed_files_provider_name ON ops.managed_files USING btree (provider_name) WHERE (provider_name IS NOT NULL);


--
-- Name: idx_managed_files_status_kind; Type: INDEX; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_managed_files_status_kind ON ops.managed_files USING btree (status, kind, updated_at DESC);


--
-- Name: idx_managed_files_upload; Type: INDEX; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_managed_files_upload ON ops.managed_files USING btree (upload_id) WHERE (upload_id IS NOT NULL);


--
-- Name: idx_merge_history_loser; Type: INDEX; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_merge_history_loser ON ops.feature_merge_history USING btree (loser_feature_id);


--
-- Name: idx_merge_history_master; Type: INDEX; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_merge_history_master ON ops.feature_merge_history USING btree (master_feature_id, merged_at DESC);


--
-- Name: idx_offline_uploads_dataset_created; Type: INDEX; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_offline_uploads_dataset_created ON ops.offline_uploads USING btree (provider_dataset_id, created_at DESC);


--
-- Name: idx_offline_uploads_status; Type: INDEX; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_offline_uploads_status ON ops.offline_uploads USING btree (status, created_at DESC);


--
-- Name: idx_overrides_feature; Type: INDEX; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_overrides_feature ON ops.feature_overrides USING btree (feature_id, status);


--
-- Name: idx_overrides_field; Type: INDEX; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_overrides_field ON ops.feature_overrides USING btree (field_path);


--
-- Name: idx_overrides_prevent_reactivation; Type: INDEX; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_overrides_prevent_reactivation ON ops.feature_overrides USING btree (feature_id, field_path) WHERE ((status = 'active'::text) AND prevent_provider_reactivation);


--
-- Name: idx_pipeline_cancellation_members_job; Type: INDEX; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_pipeline_cancellation_members_job ON ops.pipeline_cancellation_members USING btree (job_id, updated_at DESC, cancellation_id DESC);


--
-- Name: idx_pipeline_cancellation_members_run; Type: INDEX; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_pipeline_cancellation_members_run ON ops.pipeline_cancellation_members USING btree (cancellation_id, dagster_run_id);


--
-- Name: idx_pipeline_cancellations_previous; Type: INDEX; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_pipeline_cancellations_previous ON ops.pipeline_cancellations USING btree (previous_cancellation_id);


--
-- Name: idx_pipeline_cancellations_root_history; Type: INDEX; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_pipeline_cancellations_root_history ON ops.pipeline_cancellations USING btree (root_kind, root_id, requested_at DESC, cancellation_id DESC);


--
-- Name: idx_poi_cache_links_feature; Type: INDEX; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_poi_cache_links_feature ON ops.poi_cache_target_feature_links USING btree (feature_id) WHERE active;


--
-- Name: idx_poi_cache_target_feature_links_dataset; Type: INDEX; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_poi_cache_target_feature_links_dataset ON ops.poi_cache_target_feature_links USING btree (provider_dataset_id) WHERE (active AND (provider_dataset_id IS NOT NULL));


--
-- Name: idx_poi_cache_targets_coord_5179; Type: INDEX; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_poi_cache_targets_coord_5179 ON ops.poi_cache_targets USING gist (coord_5179) WHERE (deleted_at IS NULL);


--
-- Name: idx_poi_cache_targets_next_refresh; Type: INDEX; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_poi_cache_targets_next_refresh ON ops.poi_cache_targets USING btree (next_eligible_refresh_at) WHERE ((deleted_at IS NULL) AND update_enabled);


--
-- Name: idx_provider_refresh_enabled; Type: INDEX; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_provider_refresh_enabled ON ops.provider_refresh_policies USING btree (enabled, provider_dataset_id);


--
-- Name: idx_provider_refresh_source_kind; Type: INDEX; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_provider_refresh_source_kind ON ops.provider_refresh_policies USING btree (source_kind);


--
-- Name: idx_public_api_keys_active_hash; Type: INDEX; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_public_api_keys_active_hash ON ops.public_api_keys USING btree (key_hash) WHERE (state = 'active'::text);


--
-- Name: idx_public_api_keys_created_at; Type: INDEX; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_public_api_keys_created_at ON ops.public_api_keys USING btree (created_at DESC, public_api_key_id DESC);


--
-- Name: idx_reports_batch; Type: INDEX; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_reports_batch ON ops.feature_consistency_reports USING btree (batch_id);


--
-- Name: idx_reports_severity_started; Type: INDEX; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_reports_severity_started ON ops.feature_consistency_reports USING btree (severity_max, started_at DESC, report_id DESC);


--
-- Name: idx_reports_started; Type: INDEX; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_reports_started ON ops.feature_consistency_reports USING btree (started_at DESC, report_id DESC);


--
-- Name: idx_system_log_keyset; Type: INDEX; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_system_log_keyset ON ops.system_log USING btree (created_at DESC, system_log_id DESC);


--
-- Name: idx_system_log_level; Type: INDEX; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_system_log_level ON ops.system_log USING btree (level, created_at DESC);


--
-- Name: idx_system_log_source; Type: INDEX; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_system_log_source ON ops.system_log USING btree (source, created_at DESC);


--
-- Name: idx_violations_detected_brin; Type: INDEX; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_violations_detected_brin ON ops.data_integrity_violations USING brin (detected_at);


--
-- Name: idx_violations_feature; Type: INDEX; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_violations_feature ON ops.data_integrity_violations USING btree (feature_id) WHERE (feature_id IS NOT NULL);


--
-- Name: idx_violations_feature_seen; Type: INDEX; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_violations_feature_seen ON ops.data_integrity_violations USING btree (feature_id, last_seen_at DESC, issue_id DESC) WHERE (feature_id IS NOT NULL);


--
-- Name: idx_violations_source_record; Type: INDEX; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_violations_source_record ON ops.data_integrity_violations USING btree (source_record_key) WHERE (source_record_key IS NOT NULL);


--
-- Name: idx_violations_status_seen; Type: INDEX; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_violations_status_seen ON ops.data_integrity_violations USING btree (status, last_seen_at DESC, issue_id DESC);


--
-- Name: idx_violations_type_status; Type: INDEX; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_violations_type_status ON ops.data_integrity_violations USING btree (violation_type, status);


--
-- Name: ix_ops_live_ticket_claims_expires_at; Type: INDEX; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE INDEX ix_ops_live_ticket_claims_expires_at ON ops.ops_live_ticket_claims USING btree (expires_at);


--
-- Name: uq_cache_target_outbox_claims_active_stream; Type: INDEX; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE UNIQUE INDEX uq_cache_target_outbox_claims_active_stream ON ops.poi_cache_target_outbox_claims USING btree (external_system) WHERE (status = 'active'::text);


--
-- Name: uq_cache_target_reconciliation_requests_active_stream; Type: INDEX; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE UNIQUE INDEX uq_cache_target_reconciliation_requests_active_stream ON ops.poi_cache_target_reconciliation_requests USING btree (external_system) WHERE (status = ANY (ARRAY['preparing'::text, 'running'::text]));


--
-- Name: uq_cache_target_writer_drain_leases_active; Type: INDEX; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE UNIQUE INDEX uq_cache_target_writer_drain_leases_active ON ops.cache_target_writer_drain_leases USING btree ((1)) WHERE (state = ANY (ARRAY['draining'::text, 'drained'::text, 'restoring'::text]));


--
-- Name: uq_dagster_schedule_audit_requested_command; Type: INDEX; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE UNIQUE INDEX uq_dagster_schedule_audit_requested_command ON ops.dagster_schedule_audit_events USING btree (command_id) WHERE (phase = 'requested'::text);


--
-- Name: uq_dagster_schedule_audit_terminal_command; Type: INDEX; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE UNIQUE INDEX uq_dagster_schedule_audit_terminal_command ON ops.dagster_schedule_audit_events USING btree (command_id) WHERE (phase = ANY (ARRAY['succeeded'::text, 'failed'::text]));


--
-- Name: uq_import_jobs_feature_run; Type: INDEX; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE UNIQUE INDEX uq_import_jobs_feature_run ON ops.import_jobs USING btree (dagster_run_id) WHERE ((kind = 'provider_feature_load_run'::text) AND (parent_job_id IS NULL));


--
-- Name: uq_managed_file_events_run_dedupe; Type: INDEX; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE UNIQUE INDEX uq_managed_file_events_run_dedupe ON ops.managed_file_events USING btree (file_id, event_kind, dagster_run_id) WHERE (dagster_run_id IS NOT NULL);


--
-- Name: uq_overrides_active_feature_field; Type: INDEX; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE UNIQUE INDEX uq_overrides_active_feature_field ON ops.feature_overrides USING btree (feature_id, field_path) WHERE (status = 'active'::text);


--
-- Name: uq_pipeline_cancellations_active_root; Type: INDEX; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE UNIQUE INDEX uq_pipeline_cancellations_active_root ON ops.pipeline_cancellations USING btree (root_kind, root_id) WHERE (status = 'in_progress'::text);


--
-- Name: uq_poi_cache_targets_active_key; Type: INDEX; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE UNIQUE INDEX uq_poi_cache_targets_active_key ON ops.poi_cache_targets USING btree (external_system, target_key) WHERE (deleted_at IS NULL);


--
-- Name: uq_poi_cache_targets_source_identity; Type: INDEX; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE UNIQUE INDEX uq_poi_cache_targets_source_identity ON ops.poi_cache_targets USING btree (target_id, external_system, target_key);


--
-- Name: uq_violations_open_dedupe_key; Type: INDEX; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE UNIQUE INDEX uq_violations_open_dedupe_key ON ops.data_integrity_violations USING btree (((payload ->> 'dedupe_key'::text))) WHERE ((status = ANY (ARRAY['open'::text, 'acknowledged'::text])) AND (payload ? 'dedupe_key'::text));


--
-- Name: idx_notice_lineage_states_scope_present; Type: INDEX; Schema: provider_sync; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_notice_lineage_states_scope_present ON provider_sync.notice_lineage_states USING btree (notice_lifecycle_scope_id, present, changed_at DESC);


--
-- Name: idx_provider_dataset_operation_scopes_operation; Type: INDEX; Schema: provider_sync; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_provider_dataset_operation_scopes_operation ON provider_sync.provider_dataset_operation_scopes USING btree (provider_dataset_id, operation_key);


--
-- Name: idx_provider_dataset_operations_enabled; Type: INDEX; Schema: provider_sync; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_provider_dataset_operations_enabled ON provider_sync.provider_dataset_operations USING btree (provider_dataset_id, operation_key) WHERE is_enabled;


--
-- Name: idx_provider_sync_state_next_run; Type: INDEX; Schema: provider_sync; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_provider_sync_state_next_run ON provider_sync.provider_sync_state USING btree (next_run_after) WHERE ((status)::text = 'active'::text);


--
-- Name: idx_source_entities_provider_dataset; Type: INDEX; Schema: provider_sync; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_source_entities_provider_dataset ON provider_sync.source_entities USING btree (provider_dataset_id);


--
-- Name: idx_source_entity_heads_lineage; Type: INDEX; Schema: provider_sync; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_source_entity_heads_lineage ON provider_sync.source_entity_heads USING btree (lineage_key, observed_at DESC, current_source_record_key DESC);


--
-- Name: idx_source_links_entity; Type: INDEX; Schema: provider_sync; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_source_links_entity ON provider_sync.source_links USING btree (source_entity_key);


--
-- Name: idx_source_links_primary; Type: INDEX; Schema: provider_sync; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_source_links_primary ON provider_sync.source_links USING btree (feature_id) WHERE ((source_role)::text = 'primary'::text);


--
-- Name: idx_source_links_role; Type: INDEX; Schema: provider_sync; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_source_links_role ON provider_sync.source_links USING btree (source_role);


--
-- Name: idx_source_records_entity_history; Type: INDEX; Schema: provider_sync; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_source_records_entity_history ON provider_sync.source_records USING btree (source_entity_key, fetched_at DESC, imported_at DESC, source_record_key DESC);


--
-- Name: idx_source_records_fetched_at_brin; Type: INDEX; Schema: provider_sync; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_source_records_fetched_at_brin ON provider_sync.source_records USING brin (fetched_at);


--
-- Name: idx_source_records_imported_at_brin; Type: INDEX; Schema: provider_sync; Owner: ktm_feature_schema_owner
--

CREATE INDEX idx_source_records_imported_at_brin ON provider_sync.source_records USING brin (imported_at);


--
-- Name: curated_source_rules trg_curated_source_rules_active_dataset_write; Type: TRIGGER; Schema: feature; Owner: ktm_feature_schema_owner
--

CREATE TRIGGER trg_curated_source_rules_active_dataset_write BEFORE INSERT OR DELETE OR UPDATE ON feature.curated_source_rules FOR EACH ROW EXECUTE FUNCTION provider_sync.reject_inactive_curated_source_dataset();


--
-- Name: curated_sources trg_curated_sources_active_dataset_write; Type: TRIGGER; Schema: feature; Owner: ktm_feature_schema_owner
--

CREATE TRIGGER trg_curated_sources_active_dataset_write BEFORE INSERT OR DELETE OR UPDATE ON feature.curated_sources FOR EACH ROW EXECUTE FUNCTION provider_sync.reject_inactive_provider_dataset();


--
-- Name: curation_import_batches trg_curation_import_batches_append_only; Type: TRIGGER; Schema: feature; Owner: ktm_feature_schema_owner
--

CREATE TRIGGER trg_curation_import_batches_append_only BEFORE DELETE OR UPDATE ON feature.curation_import_batches FOR EACH ROW EXECUTE FUNCTION feature.reject_curation_history_mutation();


--
-- Name: curation_import_batches trg_curation_import_batches_no_truncate; Type: TRIGGER; Schema: feature; Owner: ktm_feature_schema_owner
--

CREATE TRIGGER trg_curation_import_batches_no_truncate BEFORE TRUNCATE ON feature.curation_import_batches FOR EACH STATEMENT EXECUTE FUNCTION feature.reject_curation_history_mutation();


--
-- Name: curation_import_rows trg_curation_import_rows_append_only; Type: TRIGGER; Schema: feature; Owner: ktm_feature_schema_owner
--

CREATE TRIGGER trg_curation_import_rows_append_only BEFORE DELETE OR UPDATE ON feature.curation_import_rows FOR EACH ROW EXECUTE FUNCTION feature.reject_curation_history_mutation();


--
-- Name: curation_import_rows trg_curation_import_rows_no_truncate; Type: TRIGGER; Schema: feature; Owner: ktm_feature_schema_owner
--

CREATE TRIGGER trg_curation_import_rows_no_truncate BEFORE TRUNCATE ON feature.curation_import_rows FOR EACH STATEMENT EXECUTE FUNCTION feature.reject_curation_history_mutation();


--
-- Name: curation_items trg_curation_items_legacy_component_identity; Type: TRIGGER; Schema: feature; Owner: ktm_feature_schema_owner
--

CREATE TRIGGER trg_curation_items_legacy_component_identity BEFORE INSERT ON feature.curation_items FOR EACH ROW EXECUTE FUNCTION feature.set_curation_item_legacy_component_identity();


--
-- Name: curation_items trg_curation_items_source_rule_decision; Type: TRIGGER; Schema: feature; Owner: ktm_feature_schema_owner
--

CREATE TRIGGER trg_curation_items_source_rule_decision AFTER INSERT OR UPDATE ON feature.curation_items FOR EACH ROW WHEN (((new.feature_id IS NOT NULL) AND (new.source_record_key IS NOT NULL))) EXECUTE FUNCTION feature.issue_curation_source_rule_decision();


--
-- Name: curation_link_decisions trg_curation_link_decisions_append_only; Type: TRIGGER; Schema: feature; Owner: ktm_feature_schema_owner
--

CREATE TRIGGER trg_curation_link_decisions_append_only BEFORE DELETE OR UPDATE ON feature.curation_link_decisions FOR EACH ROW EXECUTE FUNCTION feature.reject_curation_history_mutation();


--
-- Name: curation_link_decisions trg_curation_link_decisions_no_truncate; Type: TRIGGER; Schema: feature; Owner: ktm_feature_schema_owner
--

CREATE TRIGGER trg_curation_link_decisions_no_truncate BEFORE TRUNCATE ON feature.curation_link_decisions FOR EACH STATEMENT EXECUTE FUNCTION feature.reject_curation_history_mutation();


--
-- Name: current_price_summary trg_current_price_summary_active_dataset_write; Type: TRIGGER; Schema: feature; Owner: ktm_feature_schema_owner
--

CREATE TRIGGER trg_current_price_summary_active_dataset_write BEFORE INSERT OR UPDATE ON feature.current_price_summary FOR EACH ROW EXECUTE FUNCTION provider_sync.reject_inactive_provider_dataset();


--
-- Name: current_weather_summary trg_current_weather_summary_active_dataset_write; Type: TRIGGER; Schema: feature; Owner: ktm_feature_schema_owner
--

CREATE TRIGGER trg_current_weather_summary_active_dataset_write BEFORE INSERT OR UPDATE ON feature.current_weather_summary FOR EACH ROW EXECUTE FUNCTION provider_sync.reject_inactive_provider_dataset();


--
-- Name: feature_aliases trg_feature_aliases_delete_fence; Type: TRIGGER; Schema: feature; Owner: ktm_feature_schema_owner
--

CREATE TRIGGER trg_feature_aliases_delete_fence BEFORE DELETE ON feature.feature_aliases FOR EACH ROW EXECUTE FUNCTION feature.fence_feature_aliases_write();


--
-- Name: feature_aliases trg_feature_aliases_no_truncate; Type: TRIGGER; Schema: feature; Owner: ktm_feature_schema_owner
--

CREATE TRIGGER trg_feature_aliases_no_truncate BEFORE TRUNCATE ON feature.feature_aliases FOR EACH STATEMENT EXECUTE FUNCTION feature.fence_feature_aliases_write();


--
-- Name: feature_aliases trg_feature_aliases_update_fence; Type: TRIGGER; Schema: feature; Owner: ktm_feature_schema_owner
--

CREATE TRIGGER trg_feature_aliases_update_fence BEFORE UPDATE ON feature.feature_aliases FOR EACH ROW EXECUTE FUNCTION feature.fence_feature_aliases_write();


--
-- Name: feature_areas trg_feature_areas_public_ready; Type: TRIGGER; Schema: feature; Owner: ktm_feature_schema_owner
--

CREATE TRIGGER trg_feature_areas_public_ready BEFORE INSERT OR UPDATE ON feature.feature_areas FOR EACH ROW EXECUTE FUNCTION feature.derive_subtype_public_ready();


--
-- Name: feature_base_field_values trg_feature_base_field_values_validate; Type: TRIGGER; Schema: feature; Owner: ktm_feature_schema_owner
--

CREATE TRIGGER trg_feature_base_field_values_validate BEFORE INSERT OR UPDATE ON feature.feature_base_field_values FOR EACH ROW EXECUTE FUNCTION feature.validate_feature_base_field_value();


--
-- Name: feature_price_values trg_feature_price_values_active_dataset_write; Type: TRIGGER; Schema: feature; Owner: ktm_feature_schema_owner
--

CREATE TRIGGER trg_feature_price_values_active_dataset_write BEFORE INSERT ON feature.feature_price_values FOR EACH ROW EXECUTE FUNCTION provider_sync.reject_inactive_provider_dataset();


--
-- Name: feature_price_values trg_feature_price_values_immutable; Type: TRIGGER; Schema: feature; Owner: ktm_feature_schema_owner
--

CREATE TRIGGER trg_feature_price_values_immutable BEFORE DELETE OR UPDATE ON feature.feature_price_values FOR EACH ROW EXECUTE FUNCTION feature.reject_price_value_mutation();


--
-- Name: feature_routes trg_feature_routes_public_ready; Type: TRIGGER; Schema: feature; Owner: ktm_feature_schema_owner
--

CREATE TRIGGER trg_feature_routes_public_ready BEFORE INSERT OR UPDATE ON feature.feature_routes FOR EACH ROW EXECUTE FUNCTION feature.derive_subtype_public_ready();


--
-- Name: feature_state_transitions trg_feature_state_transitions_append_only_row; Type: TRIGGER; Schema: feature; Owner: ktm_feature_schema_owner
--

CREATE TRIGGER trg_feature_state_transitions_append_only_row BEFORE DELETE OR UPDATE ON feature.feature_state_transitions FOR EACH ROW EXECUTE FUNCTION feature.reject_feature_state_transition_mutation();


--
-- Name: feature_state_transitions trg_feature_state_transitions_append_only_truncate; Type: TRIGGER; Schema: feature; Owner: ktm_feature_schema_owner
--

CREATE TRIGGER trg_feature_state_transitions_append_only_truncate BEFORE TRUNCATE ON feature.feature_state_transitions FOR EACH STATEMENT EXECUTE FUNCTION feature.reject_feature_state_transition_mutation();


--
-- Name: feature_weather_values trg_feature_weather_values_active_dataset_write; Type: TRIGGER; Schema: feature; Owner: ktm_feature_schema_owner
--

CREATE TRIGGER trg_feature_weather_values_active_dataset_write BEFORE INSERT ON feature.feature_weather_values FOR EACH ROW EXECUTE FUNCTION provider_sync.reject_inactive_provider_dataset();


--
-- Name: feature_weather_values trg_feature_weather_values_immutable; Type: TRIGGER; Schema: feature; Owner: ktm_feature_schema_owner
--

CREATE TRIGGER trg_feature_weather_values_immutable BEFORE DELETE OR UPDATE ON feature.feature_weather_values FOR EACH ROW EXECUTE FUNCTION feature.reject_weather_value_mutation();


--
-- Name: features trg_features_coord_precision; Type: TRIGGER; Schema: feature; Owner: ktm_feature_schema_owner
--

CREATE TRIGGER trg_features_coord_precision BEFORE INSERT OR UPDATE OF coord, coord_precision_digits ON feature.features FOR EACH ROW EXECUTE FUNCTION feature.set_feature_coord_precision();


--
-- Name: features trg_features_feature_uuid_fill; Type: TRIGGER; Schema: feature; Owner: ktm_feature_schema_owner
--

CREATE TRIGGER trg_features_feature_uuid_fill BEFORE INSERT ON feature.features FOR EACH ROW EXECUTE FUNCTION feature.fill_features_feature_uuid();


--
-- Name: features trg_features_identity_fence; Type: TRIGGER; Schema: feature; Owner: ktm_feature_schema_owner
--

CREATE TRIGGER trg_features_identity_fence BEFORE UPDATE OF feature_id, feature_uuid ON feature.features FOR EACH ROW EXECUTE FUNCTION feature.fence_features_identity_update();


--
-- Name: features trg_features_legacy_alias; Type: TRIGGER; Schema: feature; Owner: ktm_feature_schema_owner
--

CREATE TRIGGER trg_features_legacy_alias AFTER INSERT ON feature.features FOR EACH ROW EXECUTE FUNCTION feature.ensure_features_legacy_alias();


--
-- Name: features trg_features_row_revision; Type: TRIGGER; Schema: feature; Owner: ktm_feature_schema_owner
--

CREATE TRIGGER trg_features_row_revision BEFORE UPDATE ON feature.features FOR EACH ROW EXECUTE FUNCTION feature.force_features_row_revision();


--
-- Name: features trg_features_state_transition_audit; Type: TRIGGER; Schema: feature; Owner: ktm_feature_schema_owner
--

CREATE TRIGGER trg_features_state_transition_audit AFTER INSERT OR UPDATE OF lifecycle_state, publication_state, quality_state ON feature.features FOR EACH ROW EXECUTE FUNCTION feature.write_feature_state_transition();


--
-- Name: features trg_features_sync_subtype_public_ready; Type: TRIGGER; Schema: feature; Owner: ktm_feature_schema_owner
--

CREATE TRIGGER trg_features_sync_subtype_public_ready AFTER UPDATE OF lifecycle_state, publication_state, quality_state ON feature.features FOR EACH ROW WHEN (((old.lifecycle_state IS DISTINCT FROM new.lifecycle_state) OR (old.publication_state IS DISTINCT FROM new.publication_state) OR (old.quality_state IS DISTINCT FROM new.quality_state))) EXECUTE FUNCTION feature.sync_subtype_public_ready();


--
-- Name: curated_features trg_sync_curated_feature_collection; Type: TRIGGER; Schema: feature; Owner: ktm_feature_schema_owner
--

CREATE TRIGGER trg_sync_curated_feature_collection AFTER INSERT OR DELETE OR UPDATE ON feature.curated_features FOR EACH ROW EXECUTE FUNCTION feature.sync_curated_feature_collection();


--
-- Name: import_jobs ck_import_jobs_feature_operation_parent; Type: TRIGGER; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE CONSTRAINT TRIGGER ck_import_jobs_feature_operation_parent AFTER INSERT OR UPDATE OF kind, parent_job_id, dagster_run_id, created_at ON ops.import_jobs DEFERRABLE INITIALLY IMMEDIATE FOR EACH ROW WHEN ((new.kind = 'provider_feature_load'::text)) EXECUTE FUNCTION ops.check_feature_operation_parent();


--
-- Name: backup_command_executions trg_backup_command_execution_transition; Type: TRIGGER; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE TRIGGER trg_backup_command_execution_transition BEFORE UPDATE ON ops.backup_command_executions FOR EACH ROW EXECUTE FUNCTION ops.enforce_backup_command_execution_transition();


--
-- Name: backup_command_executions trg_backup_command_executions_no_delete; Type: TRIGGER; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE TRIGGER trg_backup_command_executions_no_delete BEFORE DELETE OR TRUNCATE ON ops.backup_command_executions FOR EACH STATEMENT EXECUTE FUNCTION ops.reject_domain_command_history_mutation();


--
-- Name: poi_cache_target_outbox_events trg_cache_target_outbox_assign_relay_order; Type: TRIGGER; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE TRIGGER trg_cache_target_outbox_assign_relay_order BEFORE INSERT ON ops.poi_cache_target_outbox_events FOR EACH ROW EXECUTE FUNCTION ops.assign_cache_target_outbox_relay_order();


--
-- Name: current_summary_runs trg_current_summary_runs_terminal_immutable; Type: TRIGGER; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE TRIGGER trg_current_summary_runs_terminal_immutable BEFORE DELETE OR UPDATE ON ops.current_summary_runs FOR EACH ROW EXECUTE FUNCTION ops.reject_terminal_current_summary_run_mutation();


--
-- Name: dagster_schedule_active_claims trg_dagster_schedule_active_claim_delete_valid; Type: TRIGGER; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE TRIGGER trg_dagster_schedule_active_claim_delete_valid BEFORE DELETE ON ops.dagster_schedule_active_claims FOR EACH ROW EXECUTE FUNCTION ops.validate_dagster_schedule_active_claim_delete();


--
-- Name: dagster_schedule_active_claims trg_dagster_schedule_active_claim_insert_valid; Type: TRIGGER; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE TRIGGER trg_dagster_schedule_active_claim_insert_valid BEFORE INSERT ON ops.dagster_schedule_active_claims FOR EACH ROW EXECUTE FUNCTION ops.validate_dagster_schedule_active_claim_insert();


--
-- Name: dagster_schedule_active_claims trg_dagster_schedule_active_claim_no_truncate; Type: TRIGGER; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE TRIGGER trg_dagster_schedule_active_claim_no_truncate BEFORE TRUNCATE ON ops.dagster_schedule_active_claims FOR EACH STATEMENT EXECUTE FUNCTION ops.reject_dagster_schedule_audit_mutation();


--
-- Name: dagster_schedule_active_claims trg_dagster_schedule_active_claim_update_valid; Type: TRIGGER; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE TRIGGER trg_dagster_schedule_active_claim_update_valid BEFORE UPDATE ON ops.dagster_schedule_active_claims FOR EACH ROW EXECUTE FUNCTION ops.validate_dagster_schedule_active_claim_update();


--
-- Name: dagster_schedule_audit_events trg_dagster_schedule_audit_append_only; Type: TRIGGER; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE TRIGGER trg_dagster_schedule_audit_append_only BEFORE DELETE OR UPDATE ON ops.dagster_schedule_audit_events FOR EACH ROW EXECUTE FUNCTION ops.reject_dagster_schedule_audit_mutation();


--
-- Name: dagster_schedule_audit_events trg_dagster_schedule_audit_no_truncate; Type: TRIGGER; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE TRIGGER trg_dagster_schedule_audit_no_truncate BEFORE TRUNCATE ON ops.dagster_schedule_audit_events FOR EACH STATEMENT EXECUTE FUNCTION ops.reject_dagster_schedule_audit_mutation();


--
-- Name: dagster_schedule_audit_events trg_dagster_schedule_audit_ops_live_revision; Type: TRIGGER; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE TRIGGER trg_dagster_schedule_audit_ops_live_revision AFTER INSERT ON ops.dagster_schedule_audit_events FOR EACH STATEMENT EXECUTE FUNCTION ops.bump_ops_live_topic_revision('dagster_schedules');


--
-- Name: dagster_schedule_audit_events trg_dagster_schedule_audit_terminal_matches_request; Type: TRIGGER; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE TRIGGER trg_dagster_schedule_audit_terminal_matches_request BEFORE INSERT ON ops.dagster_schedule_audit_events FOR EACH ROW WHEN ((new.phase = ANY (ARRAY['succeeded'::text, 'failed'::text]))) EXECUTE FUNCTION ops.validate_dagster_schedule_audit_terminal();


--
-- Name: dagster_schedule_claim_resolutions trg_dagster_schedule_claim_resolution_append_only; Type: TRIGGER; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE TRIGGER trg_dagster_schedule_claim_resolution_append_only BEFORE DELETE OR UPDATE ON ops.dagster_schedule_claim_resolutions FOR EACH ROW EXECUTE FUNCTION ops.reject_dagster_schedule_audit_mutation();


--
-- Name: dagster_schedule_claim_resolutions trg_dagster_schedule_claim_resolution_no_truncate; Type: TRIGGER; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE TRIGGER trg_dagster_schedule_claim_resolution_no_truncate BEFORE TRUNCATE ON ops.dagster_schedule_claim_resolutions FOR EACH STATEMENT EXECUTE FUNCTION ops.reject_dagster_schedule_audit_mutation();


--
-- Name: dagster_schedule_claim_resolutions trg_dagster_schedule_claim_resolution_ops_live_revision; Type: TRIGGER; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE TRIGGER trg_dagster_schedule_claim_resolution_ops_live_revision AFTER INSERT ON ops.dagster_schedule_claim_resolutions FOR EACH STATEMENT EXECUTE FUNCTION ops.bump_ops_live_topic_revision('dagster_schedules');


--
-- Name: dagster_schedule_claim_resolutions trg_dagster_schedule_claim_resolution_valid; Type: TRIGGER; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE TRIGGER trg_dagster_schedule_claim_resolution_valid BEFORE INSERT ON ops.dagster_schedule_claim_resolutions FOR EACH ROW EXECUTE FUNCTION ops.validate_dagster_schedule_claim_resolution();


--
-- Name: dagster_schedule_overrides trg_dagster_schedule_overrides_ops_live_revision; Type: TRIGGER; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE TRIGGER trg_dagster_schedule_overrides_ops_live_revision AFTER INSERT OR DELETE OR UPDATE OR TRUNCATE ON ops.dagster_schedule_overrides FOR EACH STATEMENT EXECUTE FUNCTION ops.bump_ops_live_topic_revision('dagster_schedules');


--
-- Name: data_integrity_violations trg_data_integrity_violations_dataset_source_record; Type: TRIGGER; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE TRIGGER trg_data_integrity_violations_dataset_source_record BEFORE INSERT OR DELETE OR UPDATE ON ops.data_integrity_violations FOR EACH ROW EXECUTE FUNCTION provider_sync.validate_data_integrity_violation_dataset();


--
-- Name: data_integrity_violations trg_data_integrity_violations_ops_live_revision; Type: TRIGGER; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE TRIGGER trg_data_integrity_violations_ops_live_revision AFTER INSERT OR DELETE OR UPDATE OR TRUNCATE ON ops.data_integrity_violations FOR EACH STATEMENT EXECUTE FUNCTION ops.bump_ops_live_topic_revision('dataset_projection');


--
-- Name: domain_command_results trg_domain_command_results_append_only; Type: TRIGGER; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE TRIGGER trg_domain_command_results_append_only BEFORE DELETE OR UPDATE ON ops.domain_command_results FOR EACH ROW EXECUTE FUNCTION ops.reject_domain_command_history_mutation();


--
-- Name: domain_command_results trg_domain_command_results_no_truncate; Type: TRIGGER; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE TRIGGER trg_domain_command_results_no_truncate BEFORE TRUNCATE ON ops.domain_command_results FOR EACH STATEMENT EXECUTE FUNCTION ops.reject_domain_command_history_mutation();


--
-- Name: domain_commands trg_domain_commands_append_only; Type: TRIGGER; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE TRIGGER trg_domain_commands_append_only BEFORE DELETE OR UPDATE ON ops.domain_commands FOR EACH ROW EXECUTE FUNCTION ops.reject_domain_command_history_mutation();


--
-- Name: domain_commands trg_domain_commands_no_truncate; Type: TRIGGER; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE TRIGGER trg_domain_commands_no_truncate BEFORE TRUNCATE ON ops.domain_commands FOR EACH STATEMENT EXECUTE FUNCTION ops.reject_domain_command_history_mutation();


--
-- Name: enrichment_review_queue trg_enrichment_review_queue_active_dataset_write; Type: TRIGGER; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE TRIGGER trg_enrichment_review_queue_active_dataset_write BEFORE INSERT OR DELETE OR UPDATE ON ops.enrichment_review_queue FOR EACH ROW EXECUTE FUNCTION provider_sync.reject_inactive_source_entity_dataset();


--
-- Name: feature_overrides trg_feature_overrides_validate; Type: TRIGGER; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE TRIGGER trg_feature_overrides_validate BEFORE INSERT OR UPDATE ON ops.feature_overrides FOR EACH ROW EXECUTE FUNCTION feature.validate_feature_override_value();


--
-- Name: feature_update_request_datasets trg_feature_update_request_datasets_active_dataset_write; Type: TRIGGER; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE TRIGGER trg_feature_update_request_datasets_active_dataset_write BEFORE INSERT OR DELETE OR UPDATE ON ops.feature_update_request_datasets FOR EACH ROW EXECUTE FUNCTION provider_sync.reject_inactive_feature_update_request_dataset_membership();


--
-- Name: feature_update_request_datasets trg_feature_update_request_datasets_membership_complete; Type: TRIGGER; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE CONSTRAINT TRIGGER trg_feature_update_request_datasets_membership_complete AFTER INSERT OR DELETE OR UPDATE ON ops.feature_update_request_datasets DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION provider_sync.assert_feature_update_request_membership_complete();


--
-- Name: feature_update_request_idempotency trg_feature_update_request_idempotency_append_only; Type: TRIGGER; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE TRIGGER trg_feature_update_request_idempotency_append_only BEFORE DELETE OR UPDATE ON ops.feature_update_request_idempotency FOR EACH ROW EXECUTE FUNCTION ops.reject_feature_update_request_idempotency_mutation();


--
-- Name: feature_update_request_idempotency trg_feature_update_request_idempotency_insert_valid; Type: TRIGGER; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE TRIGGER trg_feature_update_request_idempotency_insert_valid BEFORE INSERT ON ops.feature_update_request_idempotency FOR EACH ROW EXECUTE FUNCTION ops.validate_feature_update_request_idempotency_insert();


--
-- Name: feature_update_request_idempotency trg_feature_update_request_idempotency_no_truncate; Type: TRIGGER; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE TRIGGER trg_feature_update_request_idempotency_no_truncate BEFORE TRUNCATE ON ops.feature_update_request_idempotency FOR EACH STATEMENT EXECUTE FUNCTION ops.reject_feature_update_request_idempotency_mutation();


--
-- Name: feature_update_request_datasets trg_feature_update_request_membership_overlap; Type: TRIGGER; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE TRIGGER trg_feature_update_request_membership_overlap BEFORE INSERT OR UPDATE OF request_id, provider_dataset_id, sync_scope, operation_key ON ops.feature_update_request_datasets FOR EACH ROW EXECUTE FUNCTION provider_sync.reject_active_feature_update_request_member_overlap();


--
-- Name: feature_update_requests trg_feature_update_requests_active_member_write; Type: TRIGGER; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE TRIGGER trg_feature_update_requests_active_member_write BEFORE DELETE OR UPDATE ON ops.feature_update_requests FOR EACH ROW EXECUTE FUNCTION provider_sync.reject_inactive_feature_update_request_members();


--
-- Name: feature_update_requests trg_feature_update_requests_job_identity; Type: TRIGGER; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE TRIGGER trg_feature_update_requests_job_identity BEFORE INSERT ON ops.feature_update_requests FOR EACH ROW EXECUTE FUNCTION ops.enforce_feature_update_request_job_identity();


--
-- Name: feature_update_requests trg_feature_update_requests_membership_complete; Type: TRIGGER; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE CONSTRAINT TRIGGER trg_feature_update_requests_membership_complete AFTER INSERT OR DELETE OR UPDATE OF dataset_membership_mode ON ops.feature_update_requests DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION provider_sync.assert_feature_update_request_membership_complete();


--
-- Name: feature_update_requests trg_feature_update_requests_mutation_guard; Type: TRIGGER; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE TRIGGER trg_feature_update_requests_mutation_guard BEFORE DELETE OR UPDATE ON ops.feature_update_requests FOR EACH ROW EXECUTE FUNCTION ops.guard_feature_update_request_mutation();


--
-- Name: import_job_datasets trg_import_job_datasets_active_dataset_write; Type: TRIGGER; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE TRIGGER trg_import_job_datasets_active_dataset_write BEFORE INSERT OR DELETE OR UPDATE ON ops.import_job_datasets FOR EACH ROW EXECUTE FUNCTION provider_sync.reject_inactive_import_job_dataset_membership();


--
-- Name: import_job_datasets trg_import_job_datasets_membership_complete; Type: TRIGGER; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE CONSTRAINT TRIGGER trg_import_job_datasets_membership_complete AFTER INSERT OR DELETE OR UPDATE ON ops.import_job_datasets DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION provider_sync.assert_import_job_membership_complete();


--
-- Name: import_job_event_clock trg_import_job_event_clock_mutation_guard; Type: TRIGGER; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE TRIGGER trg_import_job_event_clock_mutation_guard BEFORE DELETE OR UPDATE ON ops.import_job_event_clock FOR EACH ROW EXECUTE FUNCTION ops.guard_import_job_event_clock_mutation();


--
-- Name: import_job_event_clock trg_import_job_event_clock_truncate_guard; Type: TRIGGER; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE TRIGGER trg_import_job_event_clock_truncate_guard BEFORE TRUNCATE ON ops.import_job_event_clock FOR EACH STATEMENT EXECUTE FUNCTION ops.guard_import_job_event_clock_mutation();


--
-- Name: import_job_events trg_import_job_events_active_dataset_write; Type: TRIGGER; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE TRIGGER trg_import_job_events_active_dataset_write BEFORE INSERT OR DELETE OR UPDATE ON ops.import_job_events FOR EACH ROW EXECUTE FUNCTION provider_sync.reject_inactive_import_job_dataset();


--
-- Name: import_job_events trg_import_job_events_clock; Type: TRIGGER; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE TRIGGER trg_import_job_events_clock AFTER INSERT OR DELETE OR UPDATE OR TRUNCATE ON ops.import_job_events FOR EACH STATEMENT EXECUTE FUNCTION ops.bump_import_job_event_clock();


--
-- Name: import_job_events trg_import_job_events_quarantine_immutable; Type: TRIGGER; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE TRIGGER trg_import_job_events_quarantine_immutable BEFORE INSERT OR DELETE OR UPDATE ON ops.import_job_events FOR EACH ROW EXECUTE FUNCTION ops.reject_quarantined_import_job_event_mutation();


--
-- Name: import_job_events trg_import_job_events_reject_c6c_cancel_probe; Type: TRIGGER; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE TRIGGER trg_import_job_events_reject_c6c_cancel_probe BEFORE INSERT ON ops.import_job_events FOR EACH ROW EXECUTE FUNCTION ops.reject_c6c_cancel_probe_event();


--
-- Name: import_jobs trg_import_jobs_active_member_write; Type: TRIGGER; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE TRIGGER trg_import_jobs_active_member_write BEFORE DELETE OR UPDATE ON ops.import_jobs FOR EACH ROW EXECUTE FUNCTION provider_sync.reject_inactive_import_job_members();


--
-- Name: import_jobs trg_import_jobs_feature_update_activation_overlap; Type: TRIGGER; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE TRIGGER trg_import_jobs_feature_update_activation_overlap BEFORE UPDATE OF status, quarantined_at ON ops.import_jobs FOR EACH ROW EXECUTE FUNCTION provider_sync.reject_feature_update_request_activation_overlap();


--
-- Name: import_jobs trg_import_jobs_feature_update_append_only; Type: TRIGGER; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE TRIGGER trg_import_jobs_feature_update_append_only BEFORE DELETE ON ops.import_jobs FOR EACH ROW EXECUTE FUNCTION ops.reject_canonical_feature_update_job_delete();


--
-- Name: import_jobs trg_import_jobs_feature_update_pair; Type: TRIGGER; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE CONSTRAINT TRIGGER trg_import_jobs_feature_update_pair AFTER INSERT ON ops.import_jobs DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION ops.enforce_feature_update_job_pair();


--
-- Name: import_jobs trg_import_jobs_identity_immutable; Type: TRIGGER; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE TRIGGER trg_import_jobs_identity_immutable BEFORE UPDATE OF kind, dataset_membership_mode, root_id, root_kind, payload ON ops.import_jobs FOR EACH ROW EXECUTE FUNCTION ops.reject_import_job_identity_change();


--
-- Name: import_jobs trg_import_jobs_membership_complete; Type: TRIGGER; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE CONSTRAINT TRIGGER trg_import_jobs_membership_complete AFTER INSERT OR DELETE OR UPDATE OF dataset_membership_mode ON ops.import_jobs DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION provider_sync.assert_import_job_membership_complete();


--
-- Name: import_jobs trg_import_jobs_quarantine_immutable; Type: TRIGGER; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE TRIGGER trg_import_jobs_quarantine_immutable BEFORE INSERT OR DELETE OR UPDATE ON ops.import_jobs FOR EACH ROW EXECUTE FUNCTION ops.reject_import_job_quarantine_mutation();


--
-- Name: import_jobs trg_import_jobs_stamp_root; Type: TRIGGER; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE TRIGGER trg_import_jobs_stamp_root BEFORE INSERT OR UPDATE OF parent_job_id ON ops.import_jobs FOR EACH ROW EXECUTE FUNCTION ops.stamp_import_job_root();


--
-- Name: integrity_observation_runs trg_integrity_observation_runs_active_dataset_write; Type: TRIGGER; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE TRIGGER trg_integrity_observation_runs_active_dataset_write BEFORE INSERT OR DELETE OR UPDATE ON ops.integrity_observation_runs FOR EACH ROW EXECUTE FUNCTION provider_sync.reject_inactive_integrity_observation_scope();


--
-- Name: integrity_observation_scopes trg_integrity_observation_scopes_active_dataset_write; Type: TRIGGER; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE TRIGGER trg_integrity_observation_scopes_active_dataset_write BEFORE INSERT OR DELETE OR UPDATE ON ops.integrity_observation_scopes FOR EACH ROW EXECUTE FUNCTION provider_sync.reject_inactive_provider_dataset();


--
-- Name: managed_files trg_managed_files_dataset_ownership; Type: TRIGGER; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE TRIGGER trg_managed_files_dataset_ownership BEFORE INSERT OR DELETE OR UPDATE ON ops.managed_files FOR EACH ROW EXECUTE FUNCTION provider_sync.reject_managed_file_dataset_rebinding();


--
-- Name: offline_upload_command_executions trg_offline_upload_command_execution_transition; Type: TRIGGER; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE TRIGGER trg_offline_upload_command_execution_transition BEFORE UPDATE ON ops.offline_upload_command_executions FOR EACH ROW EXECUTE FUNCTION ops.enforce_offline_upload_command_execution_transition();


--
-- Name: offline_upload_command_executions trg_offline_upload_command_executions_no_delete; Type: TRIGGER; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE TRIGGER trg_offline_upload_command_executions_no_delete BEFORE DELETE OR TRUNCATE ON ops.offline_upload_command_executions FOR EACH STATEMENT EXECUTE FUNCTION ops.reject_domain_command_history_mutation();


--
-- Name: offline_uploads trg_offline_uploads_active_dataset_write; Type: TRIGGER; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE TRIGGER trg_offline_uploads_active_dataset_write BEFORE INSERT OR DELETE OR UPDATE ON ops.offline_uploads FOR EACH ROW EXECUTE FUNCTION provider_sync.reject_inactive_offline_upload_membership();


--
-- Name: pipeline_cancellation_members trg_pipeline_cancellation_members_reject_quarantine; Type: TRIGGER; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE TRIGGER trg_pipeline_cancellation_members_reject_quarantine BEFORE INSERT OR UPDATE OF job_id ON ops.pipeline_cancellation_members FOR EACH ROW EXECUTE FUNCTION ops.reject_quarantined_cancellation_member();


--
-- Name: poi_cache_target_feature_links trg_poi_cache_target_feature_links_active_dataset_write; Type: TRIGGER; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE TRIGGER trg_poi_cache_target_feature_links_active_dataset_write BEFORE INSERT OR DELETE OR UPDATE ON ops.poi_cache_target_feature_links FOR EACH ROW EXECUTE FUNCTION provider_sync.reject_inactive_provider_dataset();


--
-- Name: poi_cache_target_outbox_events trg_poi_cache_target_outbox_events_append_only; Type: TRIGGER; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE TRIGGER trg_poi_cache_target_outbox_events_append_only BEFORE DELETE OR UPDATE ON ops.poi_cache_target_outbox_events FOR EACH ROW EXECUTE FUNCTION ops.reject_cache_target_history_mutation();


--
-- Name: poi_cache_target_outbox_events trg_poi_cache_target_outbox_events_no_truncate; Type: TRIGGER; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE TRIGGER trg_poi_cache_target_outbox_events_no_truncate BEFORE TRUNCATE ON ops.poi_cache_target_outbox_events FOR EACH STATEMENT EXECUTE FUNCTION ops.reject_cache_target_history_mutation();


--
-- Name: poi_cache_target_refresh_members trg_poi_cache_target_refresh_members_append_only; Type: TRIGGER; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE TRIGGER trg_poi_cache_target_refresh_members_append_only BEFORE DELETE OR UPDATE ON ops.poi_cache_target_refresh_members FOR EACH ROW EXECUTE FUNCTION ops.reject_cache_target_history_mutation();


--
-- Name: poi_cache_target_refresh_members trg_poi_cache_target_refresh_members_no_truncate; Type: TRIGGER; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE TRIGGER trg_poi_cache_target_refresh_members_no_truncate BEFORE TRUNCATE ON ops.poi_cache_target_refresh_members FOR EACH STATEMENT EXECUTE FUNCTION ops.reject_cache_target_history_mutation();


--
-- Name: poi_cache_target_restore_fences trg_poi_cache_target_restore_fences_append_only; Type: TRIGGER; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE TRIGGER trg_poi_cache_target_restore_fences_append_only BEFORE DELETE OR UPDATE ON ops.poi_cache_target_restore_fences FOR EACH ROW EXECUTE FUNCTION ops.reject_cache_target_history_mutation();


--
-- Name: poi_cache_target_restore_fences trg_poi_cache_target_restore_fences_no_truncate; Type: TRIGGER; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE TRIGGER trg_poi_cache_target_restore_fences_no_truncate BEFORE TRUNCATE ON ops.poi_cache_target_restore_fences FOR EACH STATEMENT EXECUTE FUNCTION ops.reject_cache_target_history_mutation();


--
-- Name: poi_cache_target_snapshot_items trg_poi_cache_target_snapshot_items_append_only; Type: TRIGGER; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE TRIGGER trg_poi_cache_target_snapshot_items_append_only BEFORE UPDATE ON ops.poi_cache_target_snapshot_items FOR EACH ROW EXECUTE FUNCTION ops.reject_cache_target_history_mutation();


--
-- Name: poi_cache_target_snapshot_items trg_poi_cache_target_snapshot_items_no_truncate; Type: TRIGGER; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE TRIGGER trg_poi_cache_target_snapshot_items_no_truncate BEFORE TRUNCATE ON ops.poi_cache_target_snapshot_items FOR EACH STATEMENT EXECUTE FUNCTION ops.reject_cache_target_history_mutation();


--
-- Name: poi_cache_target_snapshots trg_poi_cache_target_snapshots_append_only; Type: TRIGGER; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE TRIGGER trg_poi_cache_target_snapshots_append_only BEFORE UPDATE ON ops.poi_cache_target_snapshots FOR EACH ROW EXECUTE FUNCTION ops.reject_cache_target_history_mutation();


--
-- Name: poi_cache_target_snapshots trg_poi_cache_target_snapshots_no_truncate; Type: TRIGGER; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE TRIGGER trg_poi_cache_target_snapshots_no_truncate BEFORE TRUNCATE ON ops.poi_cache_target_snapshots FOR EACH STATEMENT EXECUTE FUNCTION ops.reject_cache_target_history_mutation();


--
-- Name: poi_cache_target_source_events trg_poi_cache_target_source_events_append_only; Type: TRIGGER; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE TRIGGER trg_poi_cache_target_source_events_append_only BEFORE DELETE OR UPDATE ON ops.poi_cache_target_source_events FOR EACH ROW EXECUTE FUNCTION ops.reject_cache_target_history_mutation();


--
-- Name: poi_cache_target_source_events trg_poi_cache_target_source_events_no_truncate; Type: TRIGGER; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE TRIGGER trg_poi_cache_target_source_events_no_truncate BEFORE TRUNCATE ON ops.poi_cache_target_source_events FOR EACH STATEMENT EXECUTE FUNCTION ops.reject_cache_target_history_mutation();


--
-- Name: poi_cache_targets trg_poi_cache_targets_lock_version; Type: TRIGGER; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE TRIGGER trg_poi_cache_targets_lock_version BEFORE UPDATE ON ops.poi_cache_targets FOR EACH ROW EXECUTE FUNCTION ops.force_poi_cache_target_lock_version();


--
-- Name: poi_cache_targets trg_poi_cache_targets_ops_live_revision; Type: TRIGGER; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE TRIGGER trg_poi_cache_targets_ops_live_revision AFTER INSERT OR DELETE OR UPDATE OR TRUNCATE ON ops.poi_cache_targets FOR EACH STATEMENT EXECUTE FUNCTION ops.bump_ops_live_topic_revision('dataset_projection');


--
-- Name: provider_refresh_policies trg_provider_refresh_policies_active_dataset_write; Type: TRIGGER; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE TRIGGER trg_provider_refresh_policies_active_dataset_write BEFORE INSERT OR DELETE OR UPDATE ON ops.provider_refresh_policies FOR EACH ROW EXECUTE FUNCTION provider_sync.reject_inactive_provider_dataset();


--
-- Name: provider_refresh_policies trg_provider_refresh_policies_ops_live_revision; Type: TRIGGER; Schema: ops; Owner: ktm_feature_schema_owner
--

CREATE TRIGGER trg_provider_refresh_policies_ops_live_revision AFTER INSERT OR DELETE OR UPDATE OR TRUNCATE ON ops.provider_refresh_policies FOR EACH STATEMENT EXECUTE FUNCTION ops.bump_ops_live_topic_revision('provider_sync');


--
-- Name: notice_lifecycle_scopes trg_notice_lifecycle_scopes_active_dataset_write; Type: TRIGGER; Schema: provider_sync; Owner: ktm_feature_schema_owner
--

CREATE TRIGGER trg_notice_lifecycle_scopes_active_dataset_write BEFORE INSERT OR DELETE OR UPDATE ON provider_sync.notice_lifecycle_scopes FOR EACH ROW EXECUTE FUNCTION provider_sync.reject_inactive_provider_dataset();


--
-- Name: notice_lineage_states trg_notice_lineage_states_active_dataset_write; Type: TRIGGER; Schema: provider_sync; Owner: ktm_feature_schema_owner
--

CREATE TRIGGER trg_notice_lineage_states_active_dataset_write BEFORE INSERT OR DELETE OR UPDATE ON provider_sync.notice_lineage_states FOR EACH ROW EXECUTE FUNCTION provider_sync.reject_inactive_notice_lifecycle_scope();


--
-- Name: provider_datasets trg_provider_dataset_identity_immutable; Type: TRIGGER; Schema: provider_sync; Owner: ktm_feature_schema_owner
--

CREATE TRIGGER trg_provider_dataset_identity_immutable BEFORE UPDATE ON provider_sync.provider_datasets FOR EACH ROW EXECUTE FUNCTION provider_sync.reject_provider_dataset_identity_update();


--
-- Name: provider_dataset_operation_scopes trg_provider_dataset_operation_scopes_active_dataset_write; Type: TRIGGER; Schema: provider_sync; Owner: ktm_feature_schema_owner
--

CREATE TRIGGER trg_provider_dataset_operation_scopes_active_dataset_write BEFORE INSERT OR DELETE OR UPDATE ON provider_sync.provider_dataset_operation_scopes FOR EACH ROW EXECUTE FUNCTION provider_sync.reject_inactive_provider_dataset();


--
-- Name: provider_dataset_operations trg_provider_dataset_operations_active_write; Type: TRIGGER; Schema: provider_sync; Owner: ktm_feature_schema_owner
--

CREATE TRIGGER trg_provider_dataset_operations_active_write BEFORE INSERT OR DELETE OR UPDATE ON provider_sync.provider_dataset_operations FOR EACH ROW EXECUTE FUNCTION provider_sync.reject_inactive_provider_dataset();


--
-- Name: provider_dataset_operations trg_provider_dataset_operations_touch; Type: TRIGGER; Schema: provider_sync; Owner: ktm_feature_schema_owner
--

CREATE TRIGGER trg_provider_dataset_operations_touch BEFORE UPDATE ON provider_sync.provider_dataset_operations FOR EACH ROW EXECUTE FUNCTION provider_sync.touch_provider_dataset_operation();


--
-- Name: provider_datasets trg_provider_dataset_touch; Type: TRIGGER; Schema: provider_sync; Owner: ktm_feature_schema_owner
--

CREATE TRIGGER trg_provider_dataset_touch BEFORE UPDATE ON provider_sync.provider_datasets FOR EACH ROW EXECUTE FUNCTION provider_sync.touch_provider_dataset();


--
-- Name: provider_sync_state trg_provider_sync_state_active_dataset_write; Type: TRIGGER; Schema: provider_sync; Owner: ktm_feature_schema_owner
--

CREATE TRIGGER trg_provider_sync_state_active_dataset_write BEFORE INSERT OR DELETE OR UPDATE ON provider_sync.provider_sync_state FOR EACH ROW EXECUTE FUNCTION provider_sync.reject_inactive_sync_state_operation();


--
-- Name: provider_sync_state trg_provider_sync_state_ops_live_revision; Type: TRIGGER; Schema: provider_sync; Owner: ktm_feature_schema_owner
--

CREATE TRIGGER trg_provider_sync_state_ops_live_revision AFTER INSERT OR DELETE OR UPDATE OR TRUNCATE ON provider_sync.provider_sync_state FOR EACH STATEMENT EXECUTE FUNCTION ops.bump_ops_live_topic_revision('provider_sync');


--
-- Name: source_entities trg_source_entities_active_dataset_write; Type: TRIGGER; Schema: provider_sync; Owner: ktm_feature_schema_owner
--

CREATE TRIGGER trg_source_entities_active_dataset_write BEFORE INSERT OR DELETE OR UPDATE ON provider_sync.source_entities FOR EACH ROW EXECUTE FUNCTION provider_sync.reject_inactive_provider_dataset();


--
-- Name: source_entities trg_source_entities_identity_and_seen_at; Type: TRIGGER; Schema: provider_sync; Owner: ktm_feature_schema_owner
--

CREATE TRIGGER trg_source_entities_identity_and_seen_at BEFORE UPDATE ON provider_sync.source_entities FOR EACH ROW EXECUTE FUNCTION provider_sync.enforce_source_entity_identity_and_seen_at();


--
-- Name: source_entity_heads trg_source_entity_head_lineage_key; Type: TRIGGER; Schema: provider_sync; Owner: ktm_feature_schema_owner
--

CREATE TRIGGER trg_source_entity_head_lineage_key BEFORE INSERT OR UPDATE OF current_source_record_key, lineage_key ON provider_sync.source_entity_heads FOR EACH ROW EXECUTE FUNCTION provider_sync.set_source_entity_head_lineage_key();

ALTER TABLE provider_sync.source_entity_heads ENABLE ALWAYS TRIGGER trg_source_entity_head_lineage_key;


--
-- Name: source_entity_heads trg_source_entity_heads_active_dataset_write; Type: TRIGGER; Schema: provider_sync; Owner: ktm_feature_schema_owner
--

CREATE TRIGGER trg_source_entity_heads_active_dataset_write BEFORE INSERT OR DELETE OR UPDATE ON provider_sync.source_entity_heads FOR EACH ROW EXECUTE FUNCTION provider_sync.reject_inactive_source_entity_dataset();


--
-- Name: source_entity_heads trg_source_entity_heads_completeness; Type: TRIGGER; Schema: provider_sync; Owner: ktm_feature_schema_owner
--

CREATE CONSTRAINT TRIGGER trg_source_entity_heads_completeness AFTER INSERT OR DELETE OR UPDATE ON provider_sync.source_entity_heads DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION provider_sync.assert_source_entity_head_completeness();


--
-- Name: source_entity_heads trg_source_entity_heads_freshness; Type: TRIGGER; Schema: provider_sync; Owner: ktm_feature_schema_owner
--

CREATE TRIGGER trg_source_entity_heads_freshness BEFORE UPDATE ON provider_sync.source_entity_heads FOR EACH ROW EXECUTE FUNCTION provider_sync.enforce_source_entity_head_freshness();


--
-- Name: source_links trg_source_links_active_dataset_write; Type: TRIGGER; Schema: provider_sync; Owner: ktm_feature_schema_owner
--

CREATE TRIGGER trg_source_links_active_dataset_write BEFORE INSERT OR DELETE OR UPDATE ON provider_sync.source_links FOR EACH ROW EXECUTE FUNCTION provider_sync.reject_inactive_source_entity_dataset();


--
-- Name: source_records trg_source_records_active_dataset_write; Type: TRIGGER; Schema: provider_sync; Owner: ktm_feature_schema_owner
--

CREATE TRIGGER trg_source_records_active_dataset_write BEFORE INSERT OR DELETE ON provider_sync.source_records FOR EACH ROW EXECUTE FUNCTION provider_sync.reject_inactive_source_entity_dataset();


--
-- Name: source_records trg_source_records_head_completeness; Type: TRIGGER; Schema: provider_sync; Owner: ktm_feature_schema_owner
--

CREATE CONSTRAINT TRIGGER trg_source_records_head_completeness AFTER INSERT OR DELETE OR UPDATE ON provider_sync.source_records DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION provider_sync.assert_source_entity_head_completeness();


--
-- Name: source_records trg_source_records_immutable; Type: TRIGGER; Schema: provider_sync; Owner: ktm_feature_schema_owner
--

CREATE TRIGGER trg_source_records_immutable BEFORE UPDATE ON provider_sync.source_records FOR EACH ROW EXECUTE FUNCTION provider_sync.reject_source_record_update();


--
-- Name: curated_features curated_features_feature_id_fkey; Type: FK CONSTRAINT; Schema: feature; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY feature.curated_features
    ADD CONSTRAINT curated_features_feature_id_fkey FOREIGN KEY (feature_id) REFERENCES feature.features(feature_id) ON DELETE CASCADE;


--
-- Name: curated_features curated_features_source_id_fkey; Type: FK CONSTRAINT; Schema: feature; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY feature.curated_features
    ADD CONSTRAINT curated_features_source_id_fkey FOREIGN KEY (source_id) REFERENCES feature.curated_sources(source_id) ON DELETE RESTRICT;


--
-- Name: curated_features curated_features_source_record_key_fkey; Type: FK CONSTRAINT; Schema: feature; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY feature.curated_features
    ADD CONSTRAINT curated_features_source_record_key_fkey FOREIGN KEY (source_record_key) REFERENCES provider_sync.source_records(source_record_key) ON DELETE SET NULL;


--
-- Name: curated_features curated_features_theme_id_fkey; Type: FK CONSTRAINT; Schema: feature; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY feature.curated_features
    ADD CONSTRAINT curated_features_theme_id_fkey FOREIGN KEY (theme_id) REFERENCES feature.curated_themes(theme_id) ON DELETE CASCADE;


--
-- Name: curated_source_rules curated_source_rules_source_id_fkey; Type: FK CONSTRAINT; Schema: feature; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY feature.curated_source_rules
    ADD CONSTRAINT curated_source_rules_source_id_fkey FOREIGN KEY (source_id) REFERENCES feature.curated_sources(source_id) ON DELETE CASCADE;


--
-- Name: curated_source_rules curated_source_rules_theme_id_fkey; Type: FK CONSTRAINT; Schema: feature; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY feature.curated_source_rules
    ADD CONSTRAINT curated_source_rules_theme_id_fkey FOREIGN KEY (theme_id) REFERENCES feature.curated_themes(theme_id) ON DELETE CASCADE;


--
-- Name: curated_feature_detail_snapshots curated_tripmate_copy_snapshots_curated_feature_id_fkey; Type: FK CONSTRAINT; Schema: feature; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY feature.curated_feature_detail_snapshots
    ADD CONSTRAINT curated_tripmate_copy_snapshots_curated_feature_id_fkey FOREIGN KEY (curated_feature_id) REFERENCES feature.curated_features(curated_feature_id) ON DELETE CASCADE;


--
-- Name: curation_collections curation_collections_source_id_fkey; Type: FK CONSTRAINT; Schema: feature; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY feature.curation_collections
    ADD CONSTRAINT curation_collections_source_id_fkey FOREIGN KEY (source_id) REFERENCES feature.curated_sources(source_id) ON DELETE SET NULL;


--
-- Name: curation_collections curation_collections_theme_id_fkey; Type: FK CONSTRAINT; Schema: feature; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY feature.curation_collections
    ADD CONSTRAINT curation_collections_theme_id_fkey FOREIGN KEY (theme_id) REFERENCES feature.curated_themes(theme_id) ON DELETE RESTRICT;


--
-- Name: curation_items curation_items_collection_id_fkey; Type: FK CONSTRAINT; Schema: feature; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY feature.curation_items
    ADD CONSTRAINT curation_items_collection_id_fkey FOREIGN KEY (collection_id) REFERENCES feature.curation_collections(collection_id) ON DELETE CASCADE;


--
-- Name: curation_items curation_items_feature_id_fkey; Type: FK CONSTRAINT; Schema: feature; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY feature.curation_items
    ADD CONSTRAINT curation_items_feature_id_fkey FOREIGN KEY (feature_id) REFERENCES feature.features(feature_id) ON DELETE SET NULL;


--
-- Name: curation_items curation_items_source_record_key_fkey; Type: FK CONSTRAINT; Schema: feature; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY feature.curation_items
    ADD CONSTRAINT curation_items_source_record_key_fkey FOREIGN KEY (source_record_key) REFERENCES provider_sync.source_records(source_record_key) ON DELETE SET NULL;


--
-- Name: current_price_summary current_price_summary_feature_id_fkey; Type: FK CONSTRAINT; Schema: feature; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY feature.current_price_summary
    ADD CONSTRAINT current_price_summary_feature_id_fkey FOREIGN KEY (feature_id) REFERENCES feature.features(feature_id) ON DELETE CASCADE;


--
-- Name: current_price_summary current_price_summary_provider_dataset_id_fkey; Type: FK CONSTRAINT; Schema: feature; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY feature.current_price_summary
    ADD CONSTRAINT current_price_summary_provider_dataset_id_fkey FOREIGN KEY (provider_dataset_id) REFERENCES provider_sync.provider_datasets(provider_dataset_id);


--
-- Name: current_weather_summary current_weather_summary_feature_id_fkey; Type: FK CONSTRAINT; Schema: feature; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY feature.current_weather_summary
    ADD CONSTRAINT current_weather_summary_feature_id_fkey FOREIGN KEY (feature_id) REFERENCES feature.features(feature_id) ON DELETE CASCADE;


--
-- Name: current_weather_summary current_weather_summary_provider_dataset_id_fkey; Type: FK CONSTRAINT; Schema: feature; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY feature.current_weather_summary
    ADD CONSTRAINT current_weather_summary_provider_dataset_id_fkey FOREIGN KEY (provider_dataset_id) REFERENCES provider_sync.provider_datasets(provider_dataset_id);


--
-- Name: feature_price_values feature_price_values_feature_id_fkey; Type: FK CONSTRAINT; Schema: feature; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY feature.feature_price_values
    ADD CONSTRAINT feature_price_values_feature_id_fkey FOREIGN KEY (feature_id) REFERENCES feature.features(feature_id) ON DELETE CASCADE;


--
-- Name: feature_price_values feature_price_values_provider_dataset_id_fkey; Type: FK CONSTRAINT; Schema: feature; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY feature.feature_price_values
    ADD CONSTRAINT feature_price_values_provider_dataset_id_fkey FOREIGN KEY (provider_dataset_id) REFERENCES provider_sync.provider_datasets(provider_dataset_id);


--
-- Name: feature_weather_values feature_weather_values_feature_id_fkey; Type: FK CONSTRAINT; Schema: feature; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY feature.feature_weather_values
    ADD CONSTRAINT feature_weather_values_feature_id_fkey FOREIGN KEY (feature_id) REFERENCES feature.features(feature_id) ON DELETE CASCADE;


--
-- Name: feature_weather_values feature_weather_values_provider_dataset_id_fkey; Type: FK CONSTRAINT; Schema: feature; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY feature.feature_weather_values
    ADD CONSTRAINT feature_weather_values_provider_dataset_id_fkey FOREIGN KEY (provider_dataset_id) REFERENCES provider_sync.provider_datasets(provider_dataset_id);


--
-- Name: curated_sources fk_curated_sources_dataset; Type: FK CONSTRAINT; Schema: feature; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY feature.curated_sources
    ADD CONSTRAINT fk_curated_sources_dataset FOREIGN KEY (provider_dataset_id) REFERENCES provider_sync.provider_datasets(provider_dataset_id);


--
-- Name: curation_import_rows fk_curation_import_rows_batch; Type: FK CONSTRAINT; Schema: feature; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY feature.curation_import_rows
    ADD CONSTRAINT fk_curation_import_rows_batch FOREIGN KEY (import_batch_id) REFERENCES feature.curation_import_batches(import_batch_id) ON DELETE RESTRICT;


--
-- Name: curation_import_rows fk_curation_import_rows_item; Type: FK CONSTRAINT; Schema: feature; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY feature.curation_import_rows
    ADD CONSTRAINT fk_curation_import_rows_item FOREIGN KEY (curation_item_id) REFERENCES feature.curation_items(curation_item_id) ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: curation_items fk_curation_items_accepted_link_decision; Type: FK CONSTRAINT; Schema: feature; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY feature.curation_items
    ADD CONSTRAINT fk_curation_items_accepted_link_decision FOREIGN KEY (accepted_link_decision_id, curation_item_id, feature_id) REFERENCES feature.curation_link_decisions(decision_id, curation_item_id, feature_id) ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED;


--
-- Name: curation_items fk_curation_items_current_import_row; Type: FK CONSTRAINT; Schema: feature; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY feature.curation_items
    ADD CONSTRAINT fk_curation_items_current_import_row FOREIGN KEY (current_import_row_id, curation_item_id) REFERENCES feature.curation_import_rows(import_row_id, curation_item_id) ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED;


--
-- Name: curation_items fk_curation_items_legacy_projection_id_curated_features; Type: FK CONSTRAINT; Schema: feature; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY feature.curation_items
    ADD CONSTRAINT fk_curation_items_legacy_projection_id_curated_features FOREIGN KEY (legacy_projection_id) REFERENCES feature.curated_features(curated_feature_id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: curation_link_decisions fk_curation_link_decisions_import_row; Type: FK CONSTRAINT; Schema: feature; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY feature.curation_link_decisions
    ADD CONSTRAINT fk_curation_link_decisions_import_row FOREIGN KEY (import_row_id, curation_item_id) REFERENCES feature.curation_import_rows(import_row_id, curation_item_id) ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: curation_link_decisions fk_curation_link_decisions_item; Type: FK CONSTRAINT; Schema: feature; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY feature.curation_link_decisions
    ADD CONSTRAINT fk_curation_link_decisions_item FOREIGN KEY (curation_item_id) REFERENCES feature.curation_items(curation_item_id) ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: curation_link_decisions fk_curation_link_decisions_supersedes; Type: FK CONSTRAINT; Schema: feature; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY feature.curation_link_decisions
    ADD CONSTRAINT fk_curation_link_decisions_supersedes FOREIGN KEY (supersedes_decision_id, curation_item_id) REFERENCES feature.curation_link_decisions(decision_id, curation_item_id) ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: current_price_summary fk_current_price_summary_fact; Type: FK CONSTRAINT; Schema: feature; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY feature.current_price_summary
    ADD CONSTRAINT fk_current_price_summary_fact FOREIGN KEY (price_value_key, feature_id, provider_dataset_id, price_domain, product_key) REFERENCES feature.feature_price_values(price_value_key, feature_id, provider_dataset_id, price_domain, product_key) ON DELETE CASCADE;


--
-- Name: current_price_summary fk_current_price_summary_successful_run; Type: FK CONSTRAINT; Schema: feature; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY feature.current_price_summary
    ADD CONSTRAINT fk_current_price_summary_successful_run FOREIGN KEY (summary_run_id, projection_kind, receipt_status) REFERENCES ops.current_summary_runs(summary_run_id, projection_kind, status);


--
-- Name: current_weather_summary fk_current_weather_summary_fact; Type: FK CONSTRAINT; Schema: feature; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY feature.current_weather_summary
    ADD CONSTRAINT fk_current_weather_summary_fact FOREIGN KEY (weather_value_key, feature_id, provider_dataset_id, weather_domain, forecast_style, metric_key) REFERENCES feature.feature_weather_values(weather_value_key, feature_id, provider_dataset_id, weather_domain, forecast_style, metric_key) ON DELETE CASCADE;


--
-- Name: current_weather_summary fk_current_weather_summary_successful_run; Type: FK CONSTRAINT; Schema: feature; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY feature.current_weather_summary
    ADD CONSTRAINT fk_current_weather_summary_successful_run FOREIGN KEY (summary_run_id, projection_kind, receipt_status) REFERENCES ops.current_summary_runs(summary_run_id, projection_kind, status);


--
-- Name: feature_aliases fk_feature_aliases_feature; Type: FK CONSTRAINT; Schema: feature; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY feature.feature_aliases
    ADD CONSTRAINT fk_feature_aliases_feature FOREIGN KEY (feature_id) REFERENCES feature.features(feature_id) ON DELETE CASCADE;


--
-- Name: feature_aliases fk_feature_aliases_identity_pair; Type: FK CONSTRAINT; Schema: feature; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY feature.feature_aliases
    ADD CONSTRAINT fk_feature_aliases_identity_pair FOREIGN KEY (feature_id, feature_uuid) REFERENCES feature.features(feature_id, feature_uuid) ON DELETE CASCADE;


--
-- Name: feature_areas fk_feature_areas_feature_kind; Type: FK CONSTRAINT; Schema: feature; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY feature.feature_areas
    ADD CONSTRAINT fk_feature_areas_feature_kind FOREIGN KEY (feature_id, kind) REFERENCES feature.features(feature_id, kind) ON DELETE CASCADE;


--
-- Name: feature_areas fk_feature_areas_identity_pair; Type: FK CONSTRAINT; Schema: feature; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY feature.feature_areas
    ADD CONSTRAINT fk_feature_areas_identity_pair FOREIGN KEY (feature_id, feature_uuid) REFERENCES feature.features(feature_id, feature_uuid) ON DELETE CASCADE;


--
-- Name: feature_base_field_values fk_feature_base_field_values_dataset; Type: FK CONSTRAINT; Schema: feature; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY feature.feature_base_field_values
    ADD CONSTRAINT fk_feature_base_field_values_dataset FOREIGN KEY (provider_dataset_id) REFERENCES provider_sync.provider_datasets(provider_dataset_id) ON DELETE RESTRICT;


--
-- Name: feature_base_field_values fk_feature_base_field_values_entity; Type: FK CONSTRAINT; Schema: feature; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY feature.feature_base_field_values
    ADD CONSTRAINT fk_feature_base_field_values_entity FOREIGN KEY (source_entity_key) REFERENCES provider_sync.source_entities(source_entity_key) ON DELETE RESTRICT;


--
-- Name: feature_base_field_values fk_feature_base_field_values_feature_identity; Type: FK CONSTRAINT; Schema: feature; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY feature.feature_base_field_values
    ADD CONSTRAINT fk_feature_base_field_values_feature_identity FOREIGN KEY (feature_id, feature_uuid) REFERENCES feature.features(feature_id, feature_uuid) ON DELETE CASCADE;


--
-- Name: feature_base_field_values fk_feature_base_field_values_field_path; Type: FK CONSTRAINT; Schema: feature; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY feature.feature_base_field_values
    ADD CONSTRAINT fk_feature_base_field_values_field_path FOREIGN KEY (field_path) REFERENCES ops.feature_override_field_paths(field_path) ON DELETE RESTRICT;


--
-- Name: feature_base_field_values fk_feature_base_field_values_record; Type: FK CONSTRAINT; Schema: feature; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY feature.feature_base_field_values
    ADD CONSTRAINT fk_feature_base_field_values_record FOREIGN KEY (source_record_key) REFERENCES provider_sync.source_records(source_record_key) ON DELETE RESTRICT;


--
-- Name: feature_events fk_feature_events_feature_kind; Type: FK CONSTRAINT; Schema: feature; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY feature.feature_events
    ADD CONSTRAINT fk_feature_events_feature_kind FOREIGN KEY (feature_id, kind) REFERENCES feature.features(feature_id, kind) ON DELETE CASCADE;


--
-- Name: feature_events fk_feature_events_identity_pair; Type: FK CONSTRAINT; Schema: feature; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY feature.feature_events
    ADD CONSTRAINT fk_feature_events_identity_pair FOREIGN KEY (feature_id, feature_uuid) REFERENCES feature.features(feature_id, feature_uuid) ON DELETE CASCADE;


--
-- Name: feature_notices fk_feature_notices_feature_kind; Type: FK CONSTRAINT; Schema: feature; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY feature.feature_notices
    ADD CONSTRAINT fk_feature_notices_feature_kind FOREIGN KEY (feature_id, kind) REFERENCES feature.features(feature_id, kind) ON DELETE CASCADE;


--
-- Name: feature_notices fk_feature_notices_identity_pair; Type: FK CONSTRAINT; Schema: feature; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY feature.feature_notices
    ADD CONSTRAINT fk_feature_notices_identity_pair FOREIGN KEY (feature_id, feature_uuid) REFERENCES feature.features(feature_id, feature_uuid) ON DELETE CASCADE;


--
-- Name: feature_places fk_feature_places_feature_kind; Type: FK CONSTRAINT; Schema: feature; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY feature.feature_places
    ADD CONSTRAINT fk_feature_places_feature_kind FOREIGN KEY (feature_id, kind) REFERENCES feature.features(feature_id, kind) ON DELETE CASCADE;


--
-- Name: feature_places fk_feature_places_identity_pair; Type: FK CONSTRAINT; Schema: feature; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY feature.feature_places
    ADD CONSTRAINT fk_feature_places_identity_pair FOREIGN KEY (feature_id, feature_uuid) REFERENCES feature.features(feature_id, feature_uuid) ON DELETE CASCADE;


--
-- Name: feature_routes fk_feature_routes_feature_kind; Type: FK CONSTRAINT; Schema: feature; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY feature.feature_routes
    ADD CONSTRAINT fk_feature_routes_feature_kind FOREIGN KEY (feature_id, kind) REFERENCES feature.features(feature_id, kind) ON DELETE CASCADE;


--
-- Name: feature_routes fk_feature_routes_identity_pair; Type: FK CONSTRAINT; Schema: feature; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY feature.feature_routes
    ADD CONSTRAINT fk_feature_routes_identity_pair FOREIGN KEY (feature_id, feature_uuid) REFERENCES feature.features(feature_id, feature_uuid) ON DELETE CASCADE;


--
-- Name: features fk_features_parent_feature_id_features; Type: FK CONSTRAINT; Schema: feature; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY feature.features
    ADD CONSTRAINT fk_features_parent_feature_id_features FOREIGN KEY (parent_feature_id) REFERENCES feature.features(feature_id) ON DELETE SET NULL;


--
-- Name: feature_price_values fk_price_value_source_dataset; Type: FK CONSTRAINT; Schema: feature; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY feature.feature_price_values
    ADD CONSTRAINT fk_price_value_source_dataset FOREIGN KEY (source_entity_key, provider_dataset_id) REFERENCES provider_sync.source_entities(source_entity_key, provider_dataset_id) ON DELETE RESTRICT;


--
-- Name: feature_price_values fk_price_value_source_lineage; Type: FK CONSTRAINT; Schema: feature; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY feature.feature_price_values
    ADD CONSTRAINT fk_price_value_source_lineage FOREIGN KEY (source_record_key, source_entity_key, known_at) REFERENCES provider_sync.source_records(source_record_key, source_entity_key, fetched_at) ON DELETE RESTRICT;


--
-- Name: feature_weather_values fk_weather_value_source_dataset; Type: FK CONSTRAINT; Schema: feature; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY feature.feature_weather_values
    ADD CONSTRAINT fk_weather_value_source_dataset FOREIGN KEY (source_entity_key, provider_dataset_id) REFERENCES provider_sync.source_entities(source_entity_key, provider_dataset_id) ON DELETE RESTRICT;


--
-- Name: feature_weather_values fk_weather_value_source_lineage; Type: FK CONSTRAINT; Schema: feature; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY feature.feature_weather_values
    ADD CONSTRAINT fk_weather_value_source_lineage FOREIGN KEY (source_record_key, source_entity_key, known_at) REFERENCES provider_sync.source_records(source_record_key, source_entity_key, fetched_at) ON DELETE RESTRICT;


--
-- Name: backup_command_executions fk_backup_command_executions_command; Type: FK CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.backup_command_executions
    ADD CONSTRAINT fk_backup_command_executions_command FOREIGN KEY (command_id) REFERENCES ops.domain_commands(command_id) ON DELETE RESTRICT;


--
-- Name: c6c_cancel_probe_fixtures fk_c6c_cancel_probe_fixtures_cancellation; Type: FK CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.c6c_cancel_probe_fixtures
    ADD CONSTRAINT fk_c6c_cancel_probe_fixtures_cancellation FOREIGN KEY (cancellation_id) REFERENCES ops.pipeline_cancellations(cancellation_id) ON DELETE RESTRICT;


--
-- Name: c6c_cancel_probe_fixtures fk_c6c_cancel_probe_fixtures_job; Type: FK CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.c6c_cancel_probe_fixtures
    ADD CONSTRAINT fk_c6c_cancel_probe_fixtures_job FOREIGN KEY (job_id) REFERENCES ops.import_jobs(job_id) ON DELETE RESTRICT;


--
-- Name: poi_cache_target_outbox_claim_events fk_cache_target_claim_events_claim; Type: FK CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.poi_cache_target_outbox_claim_events
    ADD CONSTRAINT fk_cache_target_claim_events_claim FOREIGN KEY (claim_id) REFERENCES ops.poi_cache_target_outbox_claims(claim_id) ON DELETE RESTRICT;


--
-- Name: poi_cache_target_outbox_claim_events fk_cache_target_claim_events_event; Type: FK CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.poi_cache_target_outbox_claim_events
    ADD CONSTRAINT fk_cache_target_claim_events_event FOREIGN KEY (event_id) REFERENCES ops.poi_cache_target_outbox_events(event_id) ON DELETE RESTRICT;


--
-- Name: poi_cache_target_outbox_claims fk_cache_target_outbox_claims_stream; Type: FK CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.poi_cache_target_outbox_claims
    ADD CONSTRAINT fk_cache_target_outbox_claims_stream FOREIGN KEY (external_system) REFERENCES ops.poi_cache_target_streams(external_system) ON DELETE RESTRICT;


--
-- Name: poi_cache_target_outbox_deliveries fk_cache_target_outbox_deliveries_claim; Type: FK CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.poi_cache_target_outbox_deliveries
    ADD CONSTRAINT fk_cache_target_outbox_deliveries_claim FOREIGN KEY (claim_id) REFERENCES ops.poi_cache_target_outbox_claims(claim_id) ON DELETE RESTRICT;


--
-- Name: poi_cache_target_outbox_deliveries fk_cache_target_outbox_deliveries_event; Type: FK CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.poi_cache_target_outbox_deliveries
    ADD CONSTRAINT fk_cache_target_outbox_deliveries_event FOREIGN KEY (event_id) REFERENCES ops.poi_cache_target_outbox_events(event_id) ON DELETE RESTRICT;


--
-- Name: poi_cache_target_outbox_events fk_cache_target_outbox_domain_command; Type: FK CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.poi_cache_target_outbox_events
    ADD CONSTRAINT fk_cache_target_outbox_domain_command FOREIGN KEY (domain_command_id) REFERENCES ops.domain_commands(command_id) ON DELETE RESTRICT;


--
-- Name: poi_cache_target_outbox_events fk_cache_target_outbox_head; Type: FK CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.poi_cache_target_outbox_events
    ADD CONSTRAINT fk_cache_target_outbox_head FOREIGN KEY (external_system, target_key) REFERENCES ops.poi_cache_target_source_heads(external_system, target_key) ON DELETE RESTRICT;


--
-- Name: poi_cache_target_outbox_events fk_cache_target_outbox_job; Type: FK CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.poi_cache_target_outbox_events
    ADD CONSTRAINT fk_cache_target_outbox_job FOREIGN KEY (job_id) REFERENCES ops.import_jobs(job_id) ON DELETE RESTRICT;


--
-- Name: poi_cache_target_outbox_events fk_cache_target_outbox_reconciliation_request; Type: FK CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.poi_cache_target_outbox_events
    ADD CONSTRAINT fk_cache_target_outbox_reconciliation_request FOREIGN KEY (reconciliation_request_id) REFERENCES ops.poi_cache_target_reconciliation_requests(request_id) ON DELETE RESTRICT;


--
-- Name: poi_cache_target_outbox_events fk_cache_target_outbox_refresh_request; Type: FK CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.poi_cache_target_outbox_events
    ADD CONSTRAINT fk_cache_target_outbox_refresh_request FOREIGN KEY (refresh_request_id) REFERENCES ops.feature_update_requests(request_id) ON DELETE RESTRICT;


--
-- Name: poi_cache_target_outbox_events fk_cache_target_outbox_source_event; Type: FK CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.poi_cache_target_outbox_events
    ADD CONSTRAINT fk_cache_target_outbox_source_event FOREIGN KEY (source_event_id) REFERENCES ops.poi_cache_target_source_events(event_id) ON DELETE RESTRICT;


--
-- Name: poi_cache_target_outbox_events fk_cache_target_outbox_target; Type: FK CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.poi_cache_target_outbox_events
    ADD CONSTRAINT fk_cache_target_outbox_target FOREIGN KEY (target_id) REFERENCES ops.poi_cache_targets(target_id) ON DELETE RESTRICT;


--
-- Name: poi_cache_target_reconciliation_requests fk_cache_target_reconciliation_requests_command; Type: FK CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.poi_cache_target_reconciliation_requests
    ADD CONSTRAINT fk_cache_target_reconciliation_requests_command FOREIGN KEY (command_id) REFERENCES ops.domain_commands(command_id) ON DELETE RESTRICT;


--
-- Name: poi_cache_target_reconciliation_requests fk_cache_target_reconciliation_requests_snapshot; Type: FK CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.poi_cache_target_reconciliation_requests
    ADD CONSTRAINT fk_cache_target_reconciliation_requests_snapshot FOREIGN KEY (snapshot_id) REFERENCES ops.poi_cache_target_snapshots(snapshot_id) ON DELETE RESTRICT;


--
-- Name: poi_cache_target_reconciliation_requests fk_cache_target_reconciliation_requests_stream; Type: FK CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.poi_cache_target_reconciliation_requests
    ADD CONSTRAINT fk_cache_target_reconciliation_requests_stream FOREIGN KEY (external_system) REFERENCES ops.poi_cache_target_streams(external_system) ON DELETE RESTRICT;


--
-- Name: poi_cache_target_refresh_members fk_cache_target_refresh_members_head; Type: FK CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.poi_cache_target_refresh_members
    ADD CONSTRAINT fk_cache_target_refresh_members_head FOREIGN KEY (external_system, target_key) REFERENCES ops.poi_cache_target_source_heads(external_system, target_key) ON DELETE RESTRICT;


--
-- Name: poi_cache_target_refresh_members fk_cache_target_refresh_members_request; Type: FK CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.poi_cache_target_refresh_members
    ADD CONSTRAINT fk_cache_target_refresh_members_request FOREIGN KEY (request_id) REFERENCES ops.feature_update_requests(request_id) ON DELETE RESTRICT;


--
-- Name: poi_cache_target_refresh_members fk_cache_target_refresh_members_target; Type: FK CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.poi_cache_target_refresh_members
    ADD CONSTRAINT fk_cache_target_refresh_members_target FOREIGN KEY (target_id) REFERENCES ops.poi_cache_targets(target_id) ON DELETE RESTRICT;


--
-- Name: poi_cache_target_restore_fences fk_cache_target_restore_fences_command; Type: FK CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.poi_cache_target_restore_fences
    ADD CONSTRAINT fk_cache_target_restore_fences_command FOREIGN KEY (command_id) REFERENCES ops.domain_commands(command_id) ON DELETE RESTRICT;


--
-- Name: poi_cache_target_restore_fences fk_cache_target_restore_fences_stream; Type: FK CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.poi_cache_target_restore_fences
    ADD CONSTRAINT fk_cache_target_restore_fences_stream FOREIGN KEY (external_system) REFERENCES ops.poi_cache_target_streams(external_system) ON DELETE RESTRICT;


--
-- Name: poi_cache_target_restore_fences fk_cache_target_restore_fences_superseded_reconciliation; Type: FK CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.poi_cache_target_restore_fences
    ADD CONSTRAINT fk_cache_target_restore_fences_superseded_reconciliation FOREIGN KEY (external_system, superseded_reconciliation_request_id) REFERENCES ops.poi_cache_target_reconciliation_requests(external_system, request_id) ON DELETE RESTRICT;


--
-- Name: poi_cache_target_snapshot_items fk_cache_target_snapshot_items_snapshot; Type: FK CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.poi_cache_target_snapshot_items
    ADD CONSTRAINT fk_cache_target_snapshot_items_snapshot FOREIGN KEY (snapshot_id, external_system) REFERENCES ops.poi_cache_target_snapshots(snapshot_id, external_system) ON DELETE CASCADE;


--
-- Name: poi_cache_target_snapshots fk_cache_target_snapshots_stream; Type: FK CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.poi_cache_target_snapshots
    ADD CONSTRAINT fk_cache_target_snapshots_stream FOREIGN KEY (external_system) REFERENCES ops.poi_cache_target_streams(external_system) ON DELETE RESTRICT;


--
-- Name: poi_cache_target_source_events fk_cache_target_source_events_domain_command; Type: FK CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.poi_cache_target_source_events
    ADD CONSTRAINT fk_cache_target_source_events_domain_command FOREIGN KEY (domain_command_id) REFERENCES ops.domain_commands(command_id) ON DELETE RESTRICT;


--
-- Name: poi_cache_target_source_events fk_cache_target_source_events_head; Type: FK CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.poi_cache_target_source_events
    ADD CONSTRAINT fk_cache_target_source_events_head FOREIGN KEY (external_system, target_key) REFERENCES ops.poi_cache_target_source_heads(external_system, target_key) ON DELETE RESTRICT;


--
-- Name: poi_cache_target_source_events fk_cache_target_source_events_job; Type: FK CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.poi_cache_target_source_events
    ADD CONSTRAINT fk_cache_target_source_events_job FOREIGN KEY (job_id) REFERENCES ops.import_jobs(job_id) ON DELETE RESTRICT;


--
-- Name: poi_cache_target_source_events fk_cache_target_source_events_refresh_request; Type: FK CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.poi_cache_target_source_events
    ADD CONSTRAINT fk_cache_target_source_events_refresh_request FOREIGN KEY (refresh_request_id) REFERENCES ops.feature_update_requests(request_id) ON DELETE RESTRICT;


--
-- Name: poi_cache_target_source_events fk_cache_target_source_events_target; Type: FK CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.poi_cache_target_source_events
    ADD CONSTRAINT fk_cache_target_source_events_target FOREIGN KEY (target_id) REFERENCES ops.poi_cache_targets(target_id) ON DELETE RESTRICT;


--
-- Name: poi_cache_target_source_heads fk_cache_target_source_heads_last_event; Type: FK CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.poi_cache_target_source_heads
    ADD CONSTRAINT fk_cache_target_source_heads_last_event FOREIGN KEY (last_source_event_id) REFERENCES ops.poi_cache_target_source_events(event_id) ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED;


--
-- Name: poi_cache_target_source_heads fk_cache_target_source_heads_stream; Type: FK CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.poi_cache_target_source_heads
    ADD CONSTRAINT fk_cache_target_source_heads_stream FOREIGN KEY (external_system) REFERENCES ops.poi_cache_target_streams(external_system) ON DELETE RESTRICT;


--
-- Name: poi_cache_target_source_heads fk_cache_target_source_heads_target; Type: FK CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.poi_cache_target_source_heads
    ADD CONSTRAINT fk_cache_target_source_heads_target FOREIGN KEY (target_id, external_system, target_key) REFERENCES ops.poi_cache_targets(target_id, external_system, target_key) ON DELETE RESTRICT;


--
-- Name: poi_cache_target_streams fk_cache_target_streams_barrier_command; Type: FK CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.poi_cache_target_streams
    ADD CONSTRAINT fk_cache_target_streams_barrier_command FOREIGN KEY (last_barrier_command_id) REFERENCES ops.domain_commands(command_id) ON DELETE RESTRICT;


--
-- Name: poi_cache_target_streams fk_cache_target_streams_blocked_event; Type: FK CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.poi_cache_target_streams
    ADD CONSTRAINT fk_cache_target_streams_blocked_event FOREIGN KEY (blocked_event_id) REFERENCES ops.poi_cache_target_outbox_events(event_id) ON DELETE RESTRICT;


--
-- Name: cache_target_writer_drain_instigations fk_cache_target_writer_drain_instigations_lease; Type: FK CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.cache_target_writer_drain_instigations
    ADD CONSTRAINT fk_cache_target_writer_drain_instigations_lease FOREIGN KEY (lease_id) REFERENCES ops.cache_target_writer_drain_leases(lease_id) ON DELETE RESTRICT;


--
-- Name: cache_target_writer_drain_runs fk_cache_target_writer_drain_runs_lease; Type: FK CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.cache_target_writer_drain_runs
    ADD CONSTRAINT fk_cache_target_writer_drain_runs_lease FOREIGN KEY (lease_id) REFERENCES ops.cache_target_writer_drain_leases(lease_id) ON DELETE RESTRICT;


--
-- Name: data_integrity_violations fk_data_integrity_violations_dataset; Type: FK CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.data_integrity_violations
    ADD CONSTRAINT fk_data_integrity_violations_dataset FOREIGN KEY (provider_dataset_id) REFERENCES provider_sync.provider_datasets(provider_dataset_id);


--
-- Name: data_integrity_violations fk_data_integrity_violations_feature_id_features; Type: FK CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.data_integrity_violations
    ADD CONSTRAINT fk_data_integrity_violations_feature_id_features FOREIGN KEY (feature_id) REFERENCES feature.features(feature_id) ON DELETE SET NULL;


--
-- Name: data_integrity_violations fk_data_integrity_violations_source_record_key_source_records; Type: FK CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.data_integrity_violations
    ADD CONSTRAINT fk_data_integrity_violations_source_record_key_source_records FOREIGN KEY (source_record_key) REFERENCES provider_sync.source_records(source_record_key) ON DELETE SET NULL;


--
-- Name: dedup_review_queue fk_dedup_review_queue_feature_id_a_features; Type: FK CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.dedup_review_queue
    ADD CONSTRAINT fk_dedup_review_queue_feature_id_a_features FOREIGN KEY (feature_id_a) REFERENCES feature.features(feature_id) ON DELETE CASCADE;


--
-- Name: dedup_review_queue fk_dedup_review_queue_feature_id_b_features; Type: FK CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.dedup_review_queue
    ADD CONSTRAINT fk_dedup_review_queue_feature_id_b_features FOREIGN KEY (feature_id_b) REFERENCES feature.features(feature_id) ON DELETE CASCADE;


--
-- Name: domain_command_results fk_domain_command_results_command; Type: FK CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.domain_command_results
    ADD CONSTRAINT fk_domain_command_results_command FOREIGN KEY (command_id) REFERENCES ops.domain_commands(command_id) ON DELETE RESTRICT;


--
-- Name: enrichment_review_queue fk_enrichment_review_queue_source_entity; Type: FK CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.enrichment_review_queue
    ADD CONSTRAINT fk_enrichment_review_queue_source_entity FOREIGN KEY (source_entity_key) REFERENCES provider_sync.source_entities(source_entity_key) ON DELETE RESTRICT;


--
-- Name: enrichment_review_queue fk_enrichment_review_queue_source_record; Type: FK CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.enrichment_review_queue
    ADD CONSTRAINT fk_enrichment_review_queue_source_record FOREIGN KEY (source_entity_key, source_record_key) REFERENCES provider_sync.source_records(source_entity_key, source_record_key) ON DELETE RESTRICT;


--
-- Name: enrichment_review_queue fk_enrichment_review_queue_target_feature_id_features; Type: FK CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.enrichment_review_queue
    ADD CONSTRAINT fk_enrichment_review_queue_target_feature_id_features FOREIGN KEY (target_feature_id) REFERENCES feature.features(feature_id) ON DELETE CASCADE;


--
-- Name: feature_merge_history fk_feature_merge_history_loser_feature_id_features; Type: FK CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.feature_merge_history
    ADD CONSTRAINT fk_feature_merge_history_loser_feature_id_features FOREIGN KEY (loser_feature_id) REFERENCES feature.features(feature_id) ON DELETE CASCADE;


--
-- Name: feature_merge_history fk_feature_merge_history_master_feature_id_features; Type: FK CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.feature_merge_history
    ADD CONSTRAINT fk_feature_merge_history_master_feature_id_features FOREIGN KEY (master_feature_id) REFERENCES feature.features(feature_id) ON DELETE CASCADE;


--
-- Name: feature_merge_history fk_feature_merge_history_review_key_dedup_review_queue; Type: FK CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.feature_merge_history
    ADD CONSTRAINT fk_feature_merge_history_review_key_dedup_review_queue FOREIGN KEY (review_id) REFERENCES ops.dedup_review_queue(review_id) ON DELETE SET NULL;


--
-- Name: feature_overrides fk_feature_overrides_command; Type: FK CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.feature_overrides
    ADD CONSTRAINT fk_feature_overrides_command FOREIGN KEY (command_id) REFERENCES ops.domain_commands(command_id) ON DELETE RESTRICT;


--
-- Name: feature_overrides fk_feature_overrides_feature_id_features; Type: FK CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.feature_overrides
    ADD CONSTRAINT fk_feature_overrides_feature_id_features FOREIGN KEY (feature_id) REFERENCES feature.features(feature_id) ON DELETE CASCADE;


--
-- Name: feature_overrides fk_feature_overrides_source_dataset; Type: FK CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.feature_overrides
    ADD CONSTRAINT fk_feature_overrides_source_dataset FOREIGN KEY (source_provider_dataset_id) REFERENCES provider_sync.provider_datasets(provider_dataset_id) ON DELETE SET NULL;


--
-- Name: feature_overrides fk_feature_overrides_source_entity; Type: FK CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.feature_overrides
    ADD CONSTRAINT fk_feature_overrides_source_entity FOREIGN KEY (source_entity_key) REFERENCES provider_sync.source_entities(source_entity_key) ON DELETE SET NULL;


--
-- Name: feature_overrides fk_feature_overrides_source_record_key_source_records; Type: FK CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.feature_overrides
    ADD CONSTRAINT fk_feature_overrides_source_record_key_source_records FOREIGN KEY (source_record_key) REFERENCES provider_sync.source_records(source_record_key) ON DELETE SET NULL;


--
-- Name: feature_update_request_datasets fk_feature_update_request_datasets_exact_operation_scope; Type: FK CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.feature_update_request_datasets
    ADD CONSTRAINT fk_feature_update_request_datasets_exact_operation_scope FOREIGN KEY (provider_dataset_id, sync_scope, operation_key) REFERENCES provider_sync.provider_dataset_operation_scopes(provider_dataset_id, sync_scope, operation_key) ON DELETE RESTRICT;


--
-- Name: feature_update_request_datasets fk_feature_update_request_datasets_request; Type: FK CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.feature_update_request_datasets
    ADD CONSTRAINT fk_feature_update_request_datasets_request FOREIGN KEY (request_id) REFERENCES ops.feature_update_requests(request_id) ON DELETE CASCADE;


--
-- Name: feature_update_request_idempotency fk_feature_update_request_idempotency_request_id_featur_93ec; Type: FK CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.feature_update_request_idempotency
    ADD CONSTRAINT fk_feature_update_request_idempotency_request_id_featur_93ec FOREIGN KEY (request_id) REFERENCES ops.feature_update_requests(request_id) ON DELETE RESTRICT;


--
-- Name: feature_update_requests fk_feature_update_requests_job_id_import_jobs; Type: FK CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.feature_update_requests
    ADD CONSTRAINT fk_feature_update_requests_job_id_import_jobs FOREIGN KEY (job_id) REFERENCES ops.import_jobs(job_id) ON DELETE RESTRICT;


--
-- Name: import_job_datasets fk_import_job_datasets_exact_operation_scope; Type: FK CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.import_job_datasets
    ADD CONSTRAINT fk_import_job_datasets_exact_operation_scope FOREIGN KEY (provider_dataset_id, sync_scope, operation_key) REFERENCES provider_sync.provider_dataset_operation_scopes(provider_dataset_id, sync_scope, operation_key) ON DELETE RESTRICT;


--
-- Name: import_job_datasets fk_import_job_datasets_job; Type: FK CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.import_job_datasets
    ADD CONSTRAINT fk_import_job_datasets_job FOREIGN KEY (job_id) REFERENCES ops.import_jobs(job_id) ON DELETE CASCADE;


--
-- Name: import_job_events fk_import_job_events_job_member; Type: FK CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.import_job_events
    ADD CONSTRAINT fk_import_job_events_job_member FOREIGN KEY (job_id, import_job_dataset_id) REFERENCES ops.import_job_datasets(job_id, import_job_dataset_id) ON DELETE RESTRICT;


--
-- Name: import_jobs fk_import_jobs_cancellation; Type: FK CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.import_jobs
    ADD CONSTRAINT fk_import_jobs_cancellation FOREIGN KEY (cancellation_id) REFERENCES ops.pipeline_cancellations(cancellation_id) ON DELETE RESTRICT;


--
-- Name: import_jobs fk_import_jobs_parent_job_id; Type: FK CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.import_jobs
    ADD CONSTRAINT fk_import_jobs_parent_job_id FOREIGN KEY (parent_job_id) REFERENCES ops.import_jobs(job_id) ON DELETE SET NULL;


--
-- Name: integrity_finding_observations fk_integrity_finding_observations_run; Type: FK CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.integrity_finding_observations
    ADD CONSTRAINT fk_integrity_finding_observations_run FOREIGN KEY (observation_run_id) REFERENCES ops.integrity_observation_runs(observation_run_id) ON DELETE CASCADE;


--
-- Name: integrity_observation_runs fk_integrity_observation_runs_scope; Type: FK CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.integrity_observation_runs
    ADD CONSTRAINT fk_integrity_observation_runs_scope FOREIGN KEY (integrity_observation_scope_id) REFERENCES ops.integrity_observation_scopes(integrity_observation_scope_id) ON DELETE CASCADE;


--
-- Name: integrity_observation_scopes fk_integrity_observation_scopes_dataset; Type: FK CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.integrity_observation_scopes
    ADD CONSTRAINT fk_integrity_observation_scopes_dataset FOREIGN KEY (provider_dataset_id) REFERENCES provider_sync.provider_datasets(provider_dataset_id);


--
-- Name: managed_file_events fk_managed_file_events_file_id_managed_files; Type: FK CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.managed_file_events
    ADD CONSTRAINT fk_managed_file_events_file_id_managed_files FOREIGN KEY (file_id) REFERENCES ops.managed_files(file_id) ON DELETE CASCADE;


--
-- Name: managed_file_events fk_managed_file_events_import_job_id_import_jobs; Type: FK CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.managed_file_events
    ADD CONSTRAINT fk_managed_file_events_import_job_id_import_jobs FOREIGN KEY (import_job_id) REFERENCES ops.import_jobs(job_id) ON DELETE SET NULL;


--
-- Name: managed_files fk_managed_files_dataset; Type: FK CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.managed_files
    ADD CONSTRAINT fk_managed_files_dataset FOREIGN KEY (provider_dataset_id) REFERENCES provider_sync.provider_datasets(provider_dataset_id);


--
-- Name: managed_files fk_managed_files_origin_import_job_id_import_jobs; Type: FK CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.managed_files
    ADD CONSTRAINT fk_managed_files_origin_import_job_id_import_jobs FOREIGN KEY (origin_import_job_id) REFERENCES ops.import_jobs(job_id) ON DELETE SET NULL;


--
-- Name: offline_upload_command_executions fk_offline_upload_command_executions_command; Type: FK CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.offline_upload_command_executions
    ADD CONSTRAINT fk_offline_upload_command_executions_command FOREIGN KEY (command_id) REFERENCES ops.domain_commands(command_id) ON DELETE RESTRICT;


--
-- Name: offline_uploads fk_offline_uploads_delete_command_id_domain_commands; Type: FK CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.offline_uploads
    ADD CONSTRAINT fk_offline_uploads_delete_command_id_domain_commands FOREIGN KEY (delete_command_id) REFERENCES ops.domain_commands(command_id) ON DELETE RESTRICT;


--
-- Name: offline_uploads fk_offline_uploads_exact_operation_scope; Type: FK CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.offline_uploads
    ADD CONSTRAINT fk_offline_uploads_exact_operation_scope FOREIGN KEY (provider_dataset_id, sync_scope, operation_key) REFERENCES provider_sync.provider_dataset_operation_scopes(provider_dataset_id, sync_scope, operation_key) ON DELETE RESTRICT;


--
-- Name: offline_uploads fk_offline_uploads_load_job_id_import_jobs; Type: FK CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.offline_uploads
    ADD CONSTRAINT fk_offline_uploads_load_job_id_import_jobs FOREIGN KEY (load_job_id) REFERENCES ops.import_jobs(job_id) ON DELETE SET NULL;


--
-- Name: offline_uploads fk_offline_uploads_validation_job_id_import_jobs; Type: FK CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.offline_uploads
    ADD CONSTRAINT fk_offline_uploads_validation_job_id_import_jobs FOREIGN KEY (validation_job_id) REFERENCES ops.import_jobs(job_id) ON DELETE SET NULL;


--
-- Name: pipeline_cancellation_members fk_pipeline_cancellation_members_attempt; Type: FK CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.pipeline_cancellation_members
    ADD CONSTRAINT fk_pipeline_cancellation_members_attempt FOREIGN KEY (cancellation_id) REFERENCES ops.pipeline_cancellations(cancellation_id) ON DELETE RESTRICT;


--
-- Name: pipeline_cancellation_members fk_pipeline_cancellation_members_job; Type: FK CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.pipeline_cancellation_members
    ADD CONSTRAINT fk_pipeline_cancellation_members_job FOREIGN KEY (job_id) REFERENCES ops.import_jobs(job_id) ON DELETE RESTRICT;


--
-- Name: pipeline_cancellation_members fk_pipeline_cancellation_members_run; Type: FK CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.pipeline_cancellation_members
    ADD CONSTRAINT fk_pipeline_cancellation_members_run FOREIGN KEY (cancellation_id, dagster_run_id) REFERENCES ops.pipeline_cancellation_runs(cancellation_id, dagster_run_id) ON DELETE RESTRICT;


--
-- Name: pipeline_cancellation_runs fk_pipeline_cancellation_runs_attempt; Type: FK CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.pipeline_cancellation_runs
    ADD CONSTRAINT fk_pipeline_cancellation_runs_attempt FOREIGN KEY (cancellation_id) REFERENCES ops.pipeline_cancellations(cancellation_id) ON DELETE RESTRICT;


--
-- Name: pipeline_cancellations fk_pipeline_cancellations_previous; Type: FK CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.pipeline_cancellations
    ADD CONSTRAINT fk_pipeline_cancellations_previous FOREIGN KEY (previous_cancellation_id) REFERENCES ops.pipeline_cancellations(cancellation_id) ON DELETE RESTRICT;


--
-- Name: poi_cache_target_feature_links fk_poi_cache_target_feature_links_dataset; Type: FK CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.poi_cache_target_feature_links
    ADD CONSTRAINT fk_poi_cache_target_feature_links_dataset FOREIGN KEY (provider_dataset_id) REFERENCES provider_sync.provider_datasets(provider_dataset_id);


--
-- Name: poi_cache_target_feature_links fk_poi_cache_target_feature_links_feature_id_features; Type: FK CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.poi_cache_target_feature_links
    ADD CONSTRAINT fk_poi_cache_target_feature_links_feature_id_features FOREIGN KEY (feature_id) REFERENCES feature.features(feature_id) ON DELETE CASCADE;


--
-- Name: poi_cache_target_feature_links fk_poi_cache_target_feature_links_target_id_poi_cache_targets; Type: FK CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.poi_cache_target_feature_links
    ADD CONSTRAINT fk_poi_cache_target_feature_links_target_id_poi_cache_targets FOREIGN KEY (target_id) REFERENCES ops.poi_cache_targets(target_id) ON DELETE CASCADE;


--
-- Name: provider_refresh_policies fk_provider_refresh_policies_dataset; Type: FK CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.provider_refresh_policies
    ADD CONSTRAINT fk_provider_refresh_policies_dataset FOREIGN KEY (provider_dataset_id) REFERENCES provider_sync.provider_datasets(provider_dataset_id);


--
-- Name: import_job_events import_job_events_job_id_fkey; Type: FK CONSTRAINT; Schema: ops; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY ops.import_job_events
    ADD CONSTRAINT import_job_events_job_id_fkey FOREIGN KEY (job_id) REFERENCES ops.import_jobs(job_id) ON DELETE CASCADE;


--
-- Name: notice_lifecycle_scopes fk_notice_lifecycle_scopes_dataset; Type: FK CONSTRAINT; Schema: provider_sync; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY provider_sync.notice_lifecycle_scopes
    ADD CONSTRAINT fk_notice_lifecycle_scopes_dataset FOREIGN KEY (provider_dataset_id) REFERENCES provider_sync.provider_datasets(provider_dataset_id);


--
-- Name: notice_lineage_states fk_notice_lineage_states_scope; Type: FK CONSTRAINT; Schema: provider_sync; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY provider_sync.notice_lineage_states
    ADD CONSTRAINT fk_notice_lineage_states_scope FOREIGN KEY (notice_lifecycle_scope_id) REFERENCES provider_sync.notice_lifecycle_scopes(notice_lifecycle_scope_id) ON DELETE CASCADE;


--
-- Name: provider_dataset_operation_scopes fk_provider_dataset_operation_scopes_operation; Type: FK CONSTRAINT; Schema: provider_sync; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY provider_sync.provider_dataset_operation_scopes
    ADD CONSTRAINT fk_provider_dataset_operation_scopes_operation FOREIGN KEY (provider_dataset_id, operation_key, operation_kind) REFERENCES provider_sync.provider_dataset_operations(provider_dataset_id, operation_key, operation_kind) ON DELETE RESTRICT;


--
-- Name: provider_dataset_operations fk_provider_dataset_operations_dataset; Type: FK CONSTRAINT; Schema: provider_sync; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY provider_sync.provider_dataset_operations
    ADD CONSTRAINT fk_provider_dataset_operations_dataset FOREIGN KEY (provider_dataset_id) REFERENCES provider_sync.provider_datasets(provider_dataset_id);


--
-- Name: provider_sync_state fk_provider_sync_state_exact_operation_scope; Type: FK CONSTRAINT; Schema: provider_sync; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY provider_sync.provider_sync_state
    ADD CONSTRAINT fk_provider_sync_state_exact_operation_scope FOREIGN KEY (provider_dataset_id, sync_scope, operation_key) REFERENCES provider_sync.provider_dataset_operation_scopes(provider_dataset_id, sync_scope, operation_key) ON DELETE RESTRICT;


--
-- Name: source_entities fk_source_entities_provider_dataset; Type: FK CONSTRAINT; Schema: provider_sync; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY provider_sync.source_entities
    ADD CONSTRAINT fk_source_entities_provider_dataset FOREIGN KEY (provider_dataset_id) REFERENCES provider_sync.provider_datasets(provider_dataset_id);


--
-- Name: source_entity_heads fk_source_entity_heads_entity; Type: FK CONSTRAINT; Schema: provider_sync; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY provider_sync.source_entity_heads
    ADD CONSTRAINT fk_source_entity_heads_entity FOREIGN KEY (source_entity_key) REFERENCES provider_sync.source_entities(source_entity_key) ON DELETE CASCADE;


--
-- Name: source_entity_heads fk_source_entity_heads_record; Type: FK CONSTRAINT; Schema: provider_sync; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY provider_sync.source_entity_heads
    ADD CONSTRAINT fk_source_entity_heads_record FOREIGN KEY (source_entity_key, current_source_record_key) REFERENCES provider_sync.source_records(source_entity_key, source_record_key) ON DELETE RESTRICT;


--
-- Name: source_links fk_source_links_feature_id_features; Type: FK CONSTRAINT; Schema: provider_sync; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY provider_sync.source_links
    ADD CONSTRAINT fk_source_links_feature_id_features FOREIGN KEY (feature_id) REFERENCES feature.features(feature_id) ON DELETE CASCADE;


--
-- Name: source_links fk_source_links_source_entity_key_source_entities; Type: FK CONSTRAINT; Schema: provider_sync; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY provider_sync.source_links
    ADD CONSTRAINT fk_source_links_source_entity_key_source_entities FOREIGN KEY (source_entity_key) REFERENCES provider_sync.source_entities(source_entity_key) ON DELETE RESTRICT;


--
-- Name: source_records fk_source_records_source_entity_key_source_entities; Type: FK CONSTRAINT; Schema: provider_sync; Owner: ktm_feature_schema_owner
--

ALTER TABLE ONLY provider_sync.source_records
    ADD CONSTRAINT fk_source_records_source_entity_key_source_entities FOREIGN KEY (source_entity_key) REFERENCES provider_sync.source_entities(source_entity_key) ON DELETE RESTRICT;


--
-- Name: SCHEMA feature; Type: ACL; Schema: -; Owner: ktm_feature_schema_owner
--

GRANT ALL ON SCHEMA feature TO ktm_feature_state_procedure_owner;
GRANT ALL ON SCHEMA feature TO ktm_feature_audit_writer;
GRANT USAGE ON SCHEMA feature TO ktm_feature_runtime;


--
-- Name: SCHEMA ops; Type: ACL; Schema: -; Owner: ktm_feature_schema_owner
--

GRANT USAGE ON SCHEMA ops TO ktm_feature_runtime;
GRANT USAGE ON SCHEMA ops TO ktm_feature_state_procedure_owner;
GRANT USAGE ON SCHEMA ops TO ktm_feature_audit_writer;


--
-- Name: SCHEMA provider_sync; Type: ACL; Schema: -; Owner: ktm_feature_schema_owner
--

GRANT USAGE ON SCHEMA provider_sync TO ktm_feature_runtime;
GRANT USAGE ON SCHEMA provider_sync TO ktm_feature_state_procedure_owner;
GRANT USAGE ON SCHEMA provider_sync TO ktm_feature_audit_writer;


--
-- Name: PROCEDURE apply_provider_feature_field_patch(IN p_feature_id text, IN p_provider_dataset_id bigint, IN p_source_entity_key text, IN p_source_record_key text, IN p_expected_row_revision bigint, IN p_values jsonb, IN p_geometry_wkt jsonb, OUT o_feature_id text, OUT o_row_revision bigint, OUT o_applied_field_count integer); Type: ACL; Schema: feature; Owner: ktm_feature_state_procedure_owner
--

REVOKE ALL ON PROCEDURE feature.apply_provider_feature_field_patch(IN p_feature_id text, IN p_provider_dataset_id bigint, IN p_source_entity_key text, IN p_source_record_key text, IN p_expected_row_revision bigint, IN p_values jsonb, IN p_geometry_wkt jsonb, OUT o_feature_id text, OUT o_row_revision bigint, OUT o_applied_field_count integer) FROM PUBLIC;
GRANT ALL ON PROCEDURE feature.apply_provider_feature_field_patch(IN p_feature_id text, IN p_provider_dataset_id bigint, IN p_source_entity_key text, IN p_source_record_key text, IN p_expected_row_revision bigint, IN p_values jsonb, IN p_geometry_wkt jsonb, OUT o_feature_id text, OUT o_row_revision bigint, OUT o_applied_field_count integer) TO ktm_feature_runtime;


--
-- Name: PROCEDURE author_feature_field_overrides(IN p_feature_id text, IN p_expected_row_revision bigint, IN p_principal text, IN p_reason_code text, IN p_command_id bigint, IN p_values jsonb, IN p_geometry_wkt jsonb, OUT o_feature_id text, OUT o_row_revision bigint, OUT o_command_id bigint, OUT o_applied_field_count integer); Type: ACL; Schema: feature; Owner: ktm_feature_state_procedure_owner
--

REVOKE ALL ON PROCEDURE feature.author_feature_field_overrides(IN p_feature_id text, IN p_expected_row_revision bigint, IN p_principal text, IN p_reason_code text, IN p_command_id bigint, IN p_values jsonb, IN p_geometry_wkt jsonb, OUT o_feature_id text, OUT o_row_revision bigint, OUT o_command_id bigint, OUT o_applied_field_count integer) FROM PUBLIC;
GRANT ALL ON PROCEDURE feature.author_feature_field_overrides(IN p_feature_id text, IN p_expected_row_revision bigint, IN p_principal text, IN p_reason_code text, IN p_command_id bigint, IN p_values jsonb, IN p_geometry_wkt jsonb, OUT o_feature_id text, OUT o_row_revision bigint, OUT o_command_id bigint, OUT o_applied_field_count integer) TO ktm_feature_runtime;


--
-- Name: FUNCTION has_active_feature_override(p_feature_id text, p_field_path text); Type: ACL; Schema: feature; Owner: ktm_feature_state_procedure_owner
--

REVOKE ALL ON FUNCTION feature.has_active_feature_override(p_feature_id text, p_field_path text) FROM PUBLIC;


--
-- Name: PROCEDURE reactivate_admin_feature_state(IN p_feature_id text, IN p_provider_dataset_id bigint, IN p_source_entity_key text, IN p_source_record_key text, IN p_expected_row_revision bigint, IN p_reason_code text, IN p_principal text, OUT o_feature_id text, OUT o_row_revision bigint, OUT o_transition_id bigint); Type: ACL; Schema: feature; Owner: ktm_feature_state_procedure_owner
--

REVOKE ALL ON PROCEDURE feature.reactivate_admin_feature_state(IN p_feature_id text, IN p_provider_dataset_id bigint, IN p_source_entity_key text, IN p_source_record_key text, IN p_expected_row_revision bigint, IN p_reason_code text, IN p_principal text, OUT o_feature_id text, OUT o_row_revision bigint, OUT o_transition_id bigint) FROM PUBLIC;
GRANT ALL ON PROCEDURE feature.reactivate_admin_feature_state(IN p_feature_id text, IN p_provider_dataset_id bigint, IN p_source_entity_key text, IN p_source_record_key text, IN p_expected_row_revision bigint, IN p_reason_code text, IN p_principal text, OUT o_feature_id text, OUT o_row_revision bigint, OUT o_transition_id bigint) TO ktm_feature_runtime;


--
-- Name: FUNCTION reject_feature_change_request_receipt_mutation(); Type: ACL; Schema: feature; Owner: ktm_feature_state_procedure_owner
--

REVOKE ALL ON FUNCTION feature.reject_feature_change_request_receipt_mutation() FROM PUBLIC;
GRANT ALL ON FUNCTION feature.reject_feature_change_request_receipt_mutation() TO ktm_feature_schema_owner;


--
-- Name: FUNCTION reject_user_feature_version_mutation(); Type: ACL; Schema: feature; Owner: ktm_feature_state_procedure_owner
--

REVOKE ALL ON FUNCTION feature.reject_user_feature_version_mutation() FROM PUBLIC;
GRANT ALL ON FUNCTION feature.reject_user_feature_version_mutation() TO ktm_feature_schema_owner;


--
-- Name: PROCEDURE revoke_feature_field_overrides(IN p_feature_id text, IN p_expected_row_revision bigint, IN p_principal text, IN p_reason_code text, IN p_command_id bigint, IN p_field_paths text[], OUT o_feature_id text, OUT o_row_revision bigint, OUT o_command_id bigint, OUT o_applied_field_count integer); Type: ACL; Schema: feature; Owner: ktm_feature_state_procedure_owner
--

REVOKE ALL ON PROCEDURE feature.revoke_feature_field_overrides(IN p_feature_id text, IN p_expected_row_revision bigint, IN p_principal text, IN p_reason_code text, IN p_command_id bigint, IN p_field_paths text[], OUT o_feature_id text, OUT o_row_revision bigint, OUT o_command_id bigint, OUT o_applied_field_count integer) FROM PUBLIC;
GRANT ALL ON PROCEDURE feature.revoke_feature_field_overrides(IN p_feature_id text, IN p_expected_row_revision bigint, IN p_principal text, IN p_reason_code text, IN p_command_id bigint, IN p_field_paths text[], OUT o_feature_id text, OUT o_row_revision bigint, OUT o_command_id bigint, OUT o_applied_field_count integer) TO ktm_feature_runtime;


--
-- Name: PROCEDURE transition_admin_feature_state(IN p_feature_id text, IN p_lifecycle_state text, IN p_publication_state text, IN p_quality_state text, IN p_expected_row_revision bigint, IN p_reason_code text, IN p_principal text, IN p_action text, OUT o_feature_id text, OUT o_row_revision bigint, OUT o_transition_id bigint); Type: ACL; Schema: feature; Owner: ktm_feature_state_procedure_owner
--

REVOKE ALL ON PROCEDURE feature.transition_admin_feature_state(IN p_feature_id text, IN p_lifecycle_state text, IN p_publication_state text, IN p_quality_state text, IN p_expected_row_revision bigint, IN p_reason_code text, IN p_principal text, IN p_action text, OUT o_feature_id text, OUT o_row_revision bigint, OUT o_transition_id bigint) FROM PUBLIC;
GRANT ALL ON PROCEDURE feature.transition_admin_feature_state(IN p_feature_id text, IN p_lifecycle_state text, IN p_publication_state text, IN p_quality_state text, IN p_expected_row_revision bigint, IN p_reason_code text, IN p_principal text, IN p_action text, OUT o_feature_id text, OUT o_row_revision bigint, OUT o_transition_id bigint) TO ktm_feature_runtime;


--
-- Name: FUNCTION validate_feature_base_field_value(); Type: ACL; Schema: feature; Owner: ktm_feature_state_procedure_owner
--

REVOKE ALL ON FUNCTION feature.validate_feature_base_field_value() FROM PUBLIC;
GRANT ALL ON FUNCTION feature.validate_feature_base_field_value() TO ktm_feature_schema_owner;


--
-- Name: FUNCTION validate_feature_override_value(); Type: ACL; Schema: feature; Owner: ktm_feature_state_procedure_owner
--

REVOKE ALL ON FUNCTION feature.validate_feature_override_value() FROM PUBLIC;
GRANT ALL ON FUNCTION feature.validate_feature_override_value() TO ktm_feature_schema_owner;


--
-- Name: TABLE source_entity_heads; Type: ACL; Schema: provider_sync; Owner: ktm_feature_schema_owner
--

GRANT SELECT ON TABLE provider_sync.source_entity_heads TO ktm_feature_state_procedure_owner;


--
-- Name: COLUMN source_entity_heads.source_entity_key; Type: ACL; Schema: provider_sync; Owner: ktm_feature_schema_owner
--

GRANT UPDATE(source_entity_key) ON TABLE provider_sync.source_entity_heads TO ktm_feature_state_procedure_owner;


--
-- Name: TABLE feature_aliases; Type: ACL; Schema: feature; Owner: ktm_feature_schema_owner
--

GRANT SELECT,INSERT ON TABLE feature.feature_aliases TO ktm_feature_state_procedure_owner;


--
-- Name: TABLE feature_areas; Type: ACL; Schema: feature; Owner: ktm_feature_schema_owner
--

GRANT SELECT ON TABLE feature.feature_areas TO ktm_feature_runtime;
GRANT SELECT ON TABLE feature.feature_areas TO ktm_feature_state_procedure_owner;


--
-- Name: COLUMN feature_areas.feature_id; Type: ACL; Schema: feature; Owner: ktm_feature_schema_owner
--

GRANT INSERT(feature_id) ON TABLE feature.feature_areas TO ktm_feature_runtime;
GRANT SELECT(feature_id),UPDATE(feature_id) ON TABLE feature.feature_areas TO ktm_feature_state_procedure_owner;


--
-- Name: COLUMN feature_areas.feature_uuid; Type: ACL; Schema: feature; Owner: ktm_feature_schema_owner
--

GRANT INSERT(feature_uuid) ON TABLE feature.feature_areas TO ktm_feature_runtime;


--
-- Name: COLUMN feature_areas.kind; Type: ACL; Schema: feature; Owner: ktm_feature_schema_owner
--

GRANT INSERT(kind) ON TABLE feature.feature_areas TO ktm_feature_runtime;


--
-- Name: COLUMN feature_areas.geom; Type: ACL; Schema: feature; Owner: ktm_feature_schema_owner
--

GRANT INSERT(geom),UPDATE(geom) ON TABLE feature.feature_areas TO ktm_feature_runtime;
GRANT UPDATE(geom) ON TABLE feature.feature_areas TO ktm_feature_state_procedure_owner;


--
-- Name: COLUMN feature_areas.area_kind; Type: ACL; Schema: feature; Owner: ktm_feature_schema_owner
--

GRANT INSERT(area_kind),UPDATE(area_kind) ON TABLE feature.feature_areas TO ktm_feature_runtime;
GRANT UPDATE(area_kind) ON TABLE feature.feature_areas TO ktm_feature_state_procedure_owner;


--
-- Name: COLUMN feature_areas.boundary_source; Type: ACL; Schema: feature; Owner: ktm_feature_schema_owner
--

GRANT INSERT(boundary_source),UPDATE(boundary_source) ON TABLE feature.feature_areas TO ktm_feature_runtime;
GRANT UPDATE(boundary_source) ON TABLE feature.feature_areas TO ktm_feature_state_procedure_owner;


--
-- Name: COLUMN feature_areas.area_square_meters; Type: ACL; Schema: feature; Owner: ktm_feature_schema_owner
--

GRANT INSERT(area_square_meters),UPDATE(area_square_meters) ON TABLE feature.feature_areas TO ktm_feature_runtime;
GRANT UPDATE(area_square_meters) ON TABLE feature.feature_areas TO ktm_feature_state_procedure_owner;


--
-- Name: COLUMN feature_areas.regulation_scope; Type: ACL; Schema: feature; Owner: ktm_feature_schema_owner
--

GRANT INSERT(regulation_scope),UPDATE(regulation_scope) ON TABLE feature.feature_areas TO ktm_feature_runtime;
GRANT UPDATE(regulation_scope) ON TABLE feature.feature_areas TO ktm_feature_state_procedure_owner;


--
-- Name: COLUMN feature_areas.administrative_office; Type: ACL; Schema: feature; Owner: ktm_feature_schema_owner
--

GRANT INSERT(administrative_office),UPDATE(administrative_office) ON TABLE feature.feature_areas TO ktm_feature_runtime;
GRANT UPDATE(administrative_office) ON TABLE feature.feature_areas TO ktm_feature_state_procedure_owner;


--
-- Name: COLUMN feature_areas.description; Type: ACL; Schema: feature; Owner: ktm_feature_schema_owner
--

GRANT INSERT(description),UPDATE(description) ON TABLE feature.feature_areas TO ktm_feature_runtime;
GRANT UPDATE(description) ON TABLE feature.feature_areas TO ktm_feature_state_procedure_owner;


--
-- Name: COLUMN feature_areas.payload; Type: ACL; Schema: feature; Owner: ktm_feature_schema_owner
--

GRANT INSERT(payload),UPDATE(payload) ON TABLE feature.feature_areas TO ktm_feature_runtime;
GRANT UPDATE(payload) ON TABLE feature.feature_areas TO ktm_feature_state_procedure_owner;


--
-- Name: COLUMN feature_areas.public_ready; Type: ACL; Schema: feature; Owner: ktm_feature_schema_owner
--

GRANT SELECT(public_ready),UPDATE(public_ready) ON TABLE feature.feature_areas TO ktm_feature_state_procedure_owner;


--
-- Name: TABLE feature_base_field_values; Type: ACL; Schema: feature; Owner: ktm_feature_schema_owner
--

GRANT SELECT,INSERT,UPDATE ON TABLE feature.feature_base_field_values TO ktm_feature_state_procedure_owner;


--
-- Name: TABLE feature_events; Type: ACL; Schema: feature; Owner: ktm_feature_schema_owner
--

GRANT SELECT ON TABLE feature.feature_events TO ktm_feature_state_procedure_owner;


--
-- Name: COLUMN feature_events.feature_id; Type: ACL; Schema: feature; Owner: ktm_feature_schema_owner
--

GRANT UPDATE(feature_id) ON TABLE feature.feature_events TO ktm_feature_state_procedure_owner;


--
-- Name: COLUMN feature_events.event_kind; Type: ACL; Schema: feature; Owner: ktm_feature_schema_owner
--

GRANT UPDATE(event_kind) ON TABLE feature.feature_events TO ktm_feature_state_procedure_owner;


--
-- Name: COLUMN feature_events.starts_on; Type: ACL; Schema: feature; Owner: ktm_feature_schema_owner
--

GRANT UPDATE(starts_on) ON TABLE feature.feature_events TO ktm_feature_state_procedure_owner;


--
-- Name: COLUMN feature_events.ends_on; Type: ACL; Schema: feature; Owner: ktm_feature_schema_owner
--

GRANT UPDATE(ends_on) ON TABLE feature.feature_events TO ktm_feature_state_procedure_owner;


--
-- Name: COLUMN feature_events.timezone; Type: ACL; Schema: feature; Owner: ktm_feature_schema_owner
--

GRANT UPDATE(timezone) ON TABLE feature.feature_events TO ktm_feature_state_procedure_owner;


--
-- Name: COLUMN feature_events.opening_hours; Type: ACL; Schema: feature; Owner: ktm_feature_schema_owner
--

GRANT UPDATE(opening_hours) ON TABLE feature.feature_events TO ktm_feature_state_procedure_owner;


--
-- Name: COLUMN feature_events.venue_name; Type: ACL; Schema: feature; Owner: ktm_feature_schema_owner
--

GRANT UPDATE(venue_name) ON TABLE feature.feature_events TO ktm_feature_state_procedure_owner;


--
-- Name: COLUMN feature_events.tel; Type: ACL; Schema: feature; Owner: ktm_feature_schema_owner
--

GRANT UPDATE(tel) ON TABLE feature.feature_events TO ktm_feature_state_procedure_owner;


--
-- Name: COLUMN feature_events.content_id; Type: ACL; Schema: feature; Owner: ktm_feature_schema_owner
--

GRANT UPDATE(content_id) ON TABLE feature.feature_events TO ktm_feature_state_procedure_owner;


--
-- Name: COLUMN feature_events.content_type_id; Type: ACL; Schema: feature; Owner: ktm_feature_schema_owner
--

GRANT UPDATE(content_type_id) ON TABLE feature.feature_events TO ktm_feature_state_procedure_owner;


--
-- Name: COLUMN feature_events.area_code; Type: ACL; Schema: feature; Owner: ktm_feature_schema_owner
--

GRANT UPDATE(area_code) ON TABLE feature.feature_events TO ktm_feature_state_procedure_owner;


--
-- Name: COLUMN feature_events.sigungu_code; Type: ACL; Schema: feature; Owner: ktm_feature_schema_owner
--

GRANT UPDATE(sigungu_code) ON TABLE feature.feature_events TO ktm_feature_state_procedure_owner;


--
-- Name: COLUMN feature_events.payload; Type: ACL; Schema: feature; Owner: ktm_feature_schema_owner
--

GRANT UPDATE(payload) ON TABLE feature.feature_events TO ktm_feature_state_procedure_owner;


--
-- Name: TABLE feature_notices; Type: ACL; Schema: feature; Owner: ktm_feature_schema_owner
--

GRANT SELECT ON TABLE feature.feature_notices TO ktm_feature_state_procedure_owner;


--
-- Name: COLUMN feature_notices.feature_id; Type: ACL; Schema: feature; Owner: ktm_feature_schema_owner
--

GRANT UPDATE(feature_id) ON TABLE feature.feature_notices TO ktm_feature_state_procedure_owner;


--
-- Name: COLUMN feature_notices.notice_type; Type: ACL; Schema: feature; Owner: ktm_feature_schema_owner
--

GRANT UPDATE(notice_type) ON TABLE feature.feature_notices TO ktm_feature_state_procedure_owner;


--
-- Name: COLUMN feature_notices.severity; Type: ACL; Schema: feature; Owner: ktm_feature_schema_owner
--

GRANT UPDATE(severity) ON TABLE feature.feature_notices TO ktm_feature_state_procedure_owner;


--
-- Name: COLUMN feature_notices.valid_start_time; Type: ACL; Schema: feature; Owner: ktm_feature_schema_owner
--

GRANT UPDATE(valid_start_time) ON TABLE feature.feature_notices TO ktm_feature_state_procedure_owner;


--
-- Name: COLUMN feature_notices.valid_end_time; Type: ACL; Schema: feature; Owner: ktm_feature_schema_owner
--

GRANT UPDATE(valid_end_time) ON TABLE feature.feature_notices TO ktm_feature_state_procedure_owner;


--
-- Name: COLUMN feature_notices.source_agency; Type: ACL; Schema: feature; Owner: ktm_feature_schema_owner
--

GRANT UPDATE(source_agency) ON TABLE feature.feature_notices TO ktm_feature_state_procedure_owner;


--
-- Name: COLUMN feature_notices.officer_name; Type: ACL; Schema: feature; Owner: ktm_feature_schema_owner
--

GRANT UPDATE(officer_name) ON TABLE feature.feature_notices TO ktm_feature_state_procedure_owner;


--
-- Name: COLUMN feature_notices.payload; Type: ACL; Schema: feature; Owner: ktm_feature_schema_owner
--

GRANT UPDATE(payload) ON TABLE feature.feature_notices TO ktm_feature_state_procedure_owner;


--
-- Name: TABLE feature_places; Type: ACL; Schema: feature; Owner: ktm_feature_schema_owner
--

GRANT SELECT ON TABLE feature.feature_places TO ktm_feature_state_procedure_owner;


--
-- Name: COLUMN feature_places.feature_id; Type: ACL; Schema: feature; Owner: ktm_feature_schema_owner
--

GRANT UPDATE(feature_id) ON TABLE feature.feature_places TO ktm_feature_state_procedure_owner;


--
-- Name: COLUMN feature_places.place_kind; Type: ACL; Schema: feature; Owner: ktm_feature_schema_owner
--

GRANT UPDATE(place_kind) ON TABLE feature.feature_places TO ktm_feature_state_procedure_owner;


--
-- Name: COLUMN feature_places.phones; Type: ACL; Schema: feature; Owner: ktm_feature_schema_owner
--

GRANT UPDATE(phones) ON TABLE feature.feature_places TO ktm_feature_state_procedure_owner;


--
-- Name: COLUMN feature_places.biz_number; Type: ACL; Schema: feature; Owner: ktm_feature_schema_owner
--

GRANT UPDATE(biz_number) ON TABLE feature.feature_places TO ktm_feature_state_procedure_owner;


--
-- Name: COLUMN feature_places.license_date; Type: ACL; Schema: feature; Owner: ktm_feature_schema_owner
--

GRANT UPDATE(license_date) ON TABLE feature.feature_places TO ktm_feature_state_procedure_owner;


--
-- Name: COLUMN feature_places.business_hours; Type: ACL; Schema: feature; Owner: ktm_feature_schema_owner
--

GRANT UPDATE(business_hours) ON TABLE feature.feature_places TO ktm_feature_state_procedure_owner;


--
-- Name: COLUMN feature_places.facility_info; Type: ACL; Schema: feature; Owner: ktm_feature_schema_owner
--

GRANT UPDATE(facility_info) ON TABLE feature.feature_places TO ktm_feature_state_procedure_owner;


--
-- Name: COLUMN feature_places.reviews_link; Type: ACL; Schema: feature; Owner: ktm_feature_schema_owner
--

GRANT UPDATE(reviews_link) ON TABLE feature.feature_places TO ktm_feature_state_procedure_owner;


--
-- Name: COLUMN feature_places.payload; Type: ACL; Schema: feature; Owner: ktm_feature_schema_owner
--

GRANT UPDATE(payload) ON TABLE feature.feature_places TO ktm_feature_state_procedure_owner;


--
-- Name: TABLE feature_routes; Type: ACL; Schema: feature; Owner: ktm_feature_schema_owner
--

GRANT SELECT ON TABLE feature.feature_routes TO ktm_feature_runtime;
GRANT SELECT ON TABLE feature.feature_routes TO ktm_feature_state_procedure_owner;


--
-- Name: COLUMN feature_routes.feature_id; Type: ACL; Schema: feature; Owner: ktm_feature_schema_owner
--

GRANT INSERT(feature_id) ON TABLE feature.feature_routes TO ktm_feature_runtime;
GRANT SELECT(feature_id),UPDATE(feature_id) ON TABLE feature.feature_routes TO ktm_feature_state_procedure_owner;


--
-- Name: COLUMN feature_routes.feature_uuid; Type: ACL; Schema: feature; Owner: ktm_feature_schema_owner
--

GRANT INSERT(feature_uuid) ON TABLE feature.feature_routes TO ktm_feature_runtime;


--
-- Name: COLUMN feature_routes.kind; Type: ACL; Schema: feature; Owner: ktm_feature_schema_owner
--

GRANT INSERT(kind) ON TABLE feature.feature_routes TO ktm_feature_runtime;


--
-- Name: COLUMN feature_routes.geom; Type: ACL; Schema: feature; Owner: ktm_feature_schema_owner
--

GRANT INSERT(geom),UPDATE(geom) ON TABLE feature.feature_routes TO ktm_feature_runtime;
GRANT UPDATE(geom) ON TABLE feature.feature_routes TO ktm_feature_state_procedure_owner;


--
-- Name: COLUMN feature_routes.route_type; Type: ACL; Schema: feature; Owner: ktm_feature_schema_owner
--

GRANT INSERT(route_type),UPDATE(route_type) ON TABLE feature.feature_routes TO ktm_feature_runtime;
GRANT UPDATE(route_type) ON TABLE feature.feature_routes TO ktm_feature_state_procedure_owner;


--
-- Name: COLUMN feature_routes.geometry_source; Type: ACL; Schema: feature; Owner: ktm_feature_schema_owner
--

GRANT INSERT(geometry_source),UPDATE(geometry_source) ON TABLE feature.feature_routes TO ktm_feature_runtime;
GRANT UPDATE(geometry_source) ON TABLE feature.feature_routes TO ktm_feature_state_procedure_owner;


--
-- Name: COLUMN feature_routes.geometry_status; Type: ACL; Schema: feature; Owner: ktm_feature_schema_owner
--

GRANT INSERT(geometry_status),UPDATE(geometry_status) ON TABLE feature.feature_routes TO ktm_feature_runtime;
GRANT UPDATE(geometry_status) ON TABLE feature.feature_routes TO ktm_feature_state_procedure_owner;


--
-- Name: COLUMN feature_routes.total_distance_meters; Type: ACL; Schema: feature; Owner: ktm_feature_schema_owner
--

GRANT INSERT(total_distance_meters),UPDATE(total_distance_meters) ON TABLE feature.feature_routes TO ktm_feature_runtime;
GRANT UPDATE(total_distance_meters) ON TABLE feature.feature_routes TO ktm_feature_state_procedure_owner;


--
-- Name: COLUMN feature_routes.expected_duration_minutes; Type: ACL; Schema: feature; Owner: ktm_feature_schema_owner
--

GRANT INSERT(expected_duration_minutes),UPDATE(expected_duration_minutes) ON TABLE feature.feature_routes TO ktm_feature_runtime;
GRANT UPDATE(expected_duration_minutes) ON TABLE feature.feature_routes TO ktm_feature_state_procedure_owner;


--
-- Name: COLUMN feature_routes.difficulty; Type: ACL; Schema: feature; Owner: ktm_feature_schema_owner
--

GRANT INSERT(difficulty),UPDATE(difficulty) ON TABLE feature.feature_routes TO ktm_feature_runtime;
GRANT UPDATE(difficulty) ON TABLE feature.feature_routes TO ktm_feature_state_procedure_owner;


--
-- Name: COLUMN feature_routes.begin_name; Type: ACL; Schema: feature; Owner: ktm_feature_schema_owner
--

GRANT INSERT(begin_name),UPDATE(begin_name) ON TABLE feature.feature_routes TO ktm_feature_runtime;
GRANT UPDATE(begin_name) ON TABLE feature.feature_routes TO ktm_feature_state_procedure_owner;


--
-- Name: COLUMN feature_routes.begin_address; Type: ACL; Schema: feature; Owner: ktm_feature_schema_owner
--

GRANT INSERT(begin_address),UPDATE(begin_address) ON TABLE feature.feature_routes TO ktm_feature_runtime;
GRANT UPDATE(begin_address) ON TABLE feature.feature_routes TO ktm_feature_state_procedure_owner;


--
-- Name: COLUMN feature_routes.end_name; Type: ACL; Schema: feature; Owner: ktm_feature_schema_owner
--

GRANT INSERT(end_name),UPDATE(end_name) ON TABLE feature.feature_routes TO ktm_feature_runtime;
GRANT UPDATE(end_name) ON TABLE feature.feature_routes TO ktm_feature_state_procedure_owner;


--
-- Name: COLUMN feature_routes.end_address; Type: ACL; Schema: feature; Owner: ktm_feature_schema_owner
--

GRANT INSERT(end_address),UPDATE(end_address) ON TABLE feature.feature_routes TO ktm_feature_runtime;
GRANT UPDATE(end_address) ON TABLE feature.feature_routes TO ktm_feature_state_procedure_owner;


--
-- Name: COLUMN feature_routes.payload; Type: ACL; Schema: feature; Owner: ktm_feature_schema_owner
--

GRANT INSERT(payload),UPDATE(payload) ON TABLE feature.feature_routes TO ktm_feature_runtime;
GRANT UPDATE(payload) ON TABLE feature.feature_routes TO ktm_feature_state_procedure_owner;


--
-- Name: COLUMN feature_routes.public_ready; Type: ACL; Schema: feature; Owner: ktm_feature_schema_owner
--

GRANT SELECT(public_ready),UPDATE(public_ready) ON TABLE feature.feature_routes TO ktm_feature_state_procedure_owner;


--
-- Name: TABLE feature_state_transitions; Type: ACL; Schema: feature; Owner: ktm_feature_schema_owner
--

GRANT SELECT ON TABLE feature.feature_state_transitions TO ktm_feature_state_procedure_owner;
GRANT INSERT ON TABLE feature.feature_state_transitions TO ktm_feature_audit_writer;
GRANT SELECT ON TABLE feature.feature_state_transitions TO ktm_feature_runtime;


--
-- Name: SEQUENCE feature_state_transitions_transition_id_seq; Type: ACL; Schema: feature; Owner: ktm_feature_schema_owner
--

GRANT SELECT,USAGE ON SEQUENCE feature.feature_state_transitions_transition_id_seq TO ktm_feature_audit_writer;


--
-- Name: TABLE features; Type: ACL; Schema: feature; Owner: ktm_feature_schema_owner
--

GRANT SELECT,INSERT ON TABLE feature.features TO ktm_feature_state_procedure_owner;
GRANT SELECT ON TABLE feature.features TO ktm_feature_runtime;


--
-- Name: COLUMN features.kind; Type: ACL; Schema: feature; Owner: ktm_feature_schema_owner
--

GRANT UPDATE(kind) ON TABLE feature.features TO ktm_feature_runtime;
GRANT UPDATE(kind) ON TABLE feature.features TO ktm_feature_state_procedure_owner;


--
-- Name: COLUMN features.name; Type: ACL; Schema: feature; Owner: ktm_feature_schema_owner
--

GRANT UPDATE(name) ON TABLE feature.features TO ktm_feature_runtime;
GRANT UPDATE(name) ON TABLE feature.features TO ktm_feature_state_procedure_owner;


--
-- Name: COLUMN features.category; Type: ACL; Schema: feature; Owner: ktm_feature_schema_owner
--

GRANT UPDATE(category) ON TABLE feature.features TO ktm_feature_runtime;
GRANT UPDATE(category) ON TABLE feature.features TO ktm_feature_state_procedure_owner;


--
-- Name: COLUMN features.coord; Type: ACL; Schema: feature; Owner: ktm_feature_schema_owner
--

GRANT UPDATE(coord) ON TABLE feature.features TO ktm_feature_runtime;
GRANT UPDATE(coord) ON TABLE feature.features TO ktm_feature_state_procedure_owner;


--
-- Name: COLUMN features.address; Type: ACL; Schema: feature; Owner: ktm_feature_schema_owner
--

GRANT UPDATE(address) ON TABLE feature.features TO ktm_feature_runtime;
GRANT UPDATE(address) ON TABLE feature.features TO ktm_feature_state_procedure_owner;


--
-- Name: COLUMN features.legal_dong_code; Type: ACL; Schema: feature; Owner: ktm_feature_schema_owner
--

GRANT UPDATE(legal_dong_code) ON TABLE feature.features TO ktm_feature_runtime;
GRANT UPDATE(legal_dong_code) ON TABLE feature.features TO ktm_feature_state_procedure_owner;


--
-- Name: COLUMN features.road_name_code; Type: ACL; Schema: feature; Owner: ktm_feature_schema_owner
--

GRANT UPDATE(road_name_code) ON TABLE feature.features TO ktm_feature_runtime;
GRANT UPDATE(road_name_code) ON TABLE feature.features TO ktm_feature_state_procedure_owner;


--
-- Name: COLUMN features.road_address_management_no; Type: ACL; Schema: feature; Owner: ktm_feature_schema_owner
--

GRANT UPDATE(road_address_management_no) ON TABLE feature.features TO ktm_feature_runtime;
GRANT UPDATE(road_address_management_no) ON TABLE feature.features TO ktm_feature_state_procedure_owner;


--
-- Name: COLUMN features.admin_dong_code; Type: ACL; Schema: feature; Owner: ktm_feature_schema_owner
--

GRANT UPDATE(admin_dong_code) ON TABLE feature.features TO ktm_feature_runtime;
GRANT UPDATE(admin_dong_code) ON TABLE feature.features TO ktm_feature_state_procedure_owner;


--
-- Name: COLUMN features.sido_code; Type: ACL; Schema: feature; Owner: ktm_feature_schema_owner
--

GRANT UPDATE(sido_code) ON TABLE feature.features TO ktm_feature_runtime;
GRANT UPDATE(sido_code) ON TABLE feature.features TO ktm_feature_state_procedure_owner;


--
-- Name: COLUMN features.sigungu_code; Type: ACL; Schema: feature; Owner: ktm_feature_schema_owner
--

GRANT UPDATE(sigungu_code) ON TABLE feature.features TO ktm_feature_runtime;
GRANT UPDATE(sigungu_code) ON TABLE feature.features TO ktm_feature_state_procedure_owner;


--
-- Name: COLUMN features.urls; Type: ACL; Schema: feature; Owner: ktm_feature_schema_owner
--

GRANT UPDATE(urls) ON TABLE feature.features TO ktm_feature_runtime;
GRANT UPDATE(urls) ON TABLE feature.features TO ktm_feature_state_procedure_owner;


--
-- Name: COLUMN features.marker_icon; Type: ACL; Schema: feature; Owner: ktm_feature_schema_owner
--

GRANT UPDATE(marker_icon) ON TABLE feature.features TO ktm_feature_runtime;
GRANT UPDATE(marker_icon) ON TABLE feature.features TO ktm_feature_state_procedure_owner;


--
-- Name: COLUMN features.marker_color; Type: ACL; Schema: feature; Owner: ktm_feature_schema_owner
--

GRANT UPDATE(marker_color) ON TABLE feature.features TO ktm_feature_runtime;
GRANT UPDATE(marker_color) ON TABLE feature.features TO ktm_feature_state_procedure_owner;


--
-- Name: COLUMN features.parent_feature_id; Type: ACL; Schema: feature; Owner: ktm_feature_schema_owner
--

GRANT UPDATE(parent_feature_id) ON TABLE feature.features TO ktm_feature_runtime;
GRANT UPDATE(parent_feature_id) ON TABLE feature.features TO ktm_feature_state_procedure_owner;


--
-- Name: COLUMN features.sibling_group_id; Type: ACL; Schema: feature; Owner: ktm_feature_schema_owner
--

GRANT UPDATE(sibling_group_id) ON TABLE feature.features TO ktm_feature_runtime;
GRANT UPDATE(sibling_group_id) ON TABLE feature.features TO ktm_feature_state_procedure_owner;


--
-- Name: COLUMN features.raw_refs; Type: ACL; Schema: feature; Owner: ktm_feature_schema_owner
--

GRANT UPDATE(raw_refs) ON TABLE feature.features TO ktm_feature_runtime;
GRANT UPDATE(raw_refs) ON TABLE feature.features TO ktm_feature_state_procedure_owner;


--
-- Name: COLUMN features.created_at; Type: ACL; Schema: feature; Owner: ktm_feature_schema_owner
--

GRANT UPDATE(created_at) ON TABLE feature.features TO ktm_feature_runtime;


--
-- Name: COLUMN features.updated_at; Type: ACL; Schema: feature; Owner: ktm_feature_schema_owner
--

GRANT UPDATE(updated_at) ON TABLE feature.features TO ktm_feature_state_procedure_owner;
GRANT UPDATE(updated_at) ON TABLE feature.features TO ktm_feature_runtime;


--
-- Name: COLUMN features.coord_precision_digits; Type: ACL; Schema: feature; Owner: ktm_feature_schema_owner
--

GRANT UPDATE(coord_precision_digits) ON TABLE feature.features TO ktm_feature_runtime;
GRANT UPDATE(coord_precision_digits) ON TABLE feature.features TO ktm_feature_state_procedure_owner;


--
-- Name: COLUMN features.lifecycle_state; Type: ACL; Schema: feature; Owner: ktm_feature_schema_owner
--

GRANT UPDATE(lifecycle_state) ON TABLE feature.features TO ktm_feature_state_procedure_owner;


--
-- Name: COLUMN features.publication_state; Type: ACL; Schema: feature; Owner: ktm_feature_schema_owner
--

GRANT UPDATE(publication_state) ON TABLE feature.features TO ktm_feature_state_procedure_owner;


--
-- Name: COLUMN features.quality_state; Type: ACL; Schema: feature; Owner: ktm_feature_schema_owner
--

GRANT UPDATE(quality_state) ON TABLE feature.features TO ktm_feature_state_procedure_owner;


--
-- Name: TABLE public_features; Type: ACL; Schema: feature; Owner: ktm_feature_schema_owner
--

GRANT SELECT ON TABLE feature.public_features TO ktm_feature_runtime;


--
-- Name: TABLE domain_command_results; Type: ACL; Schema: ops; Owner: ktm_feature_schema_owner
--

GRANT SELECT ON TABLE ops.domain_command_results TO ktm_feature_state_procedure_owner;


--
-- Name: TABLE domain_commands; Type: ACL; Schema: ops; Owner: ktm_feature_schema_owner
--

GRANT SELECT ON TABLE ops.domain_commands TO ktm_feature_state_procedure_owner;


--
-- Name: COLUMN domain_commands.command_id; Type: ACL; Schema: ops; Owner: ktm_feature_schema_owner
--

GRANT UPDATE(command_id) ON TABLE ops.domain_commands TO ktm_feature_state_procedure_owner;


--
-- Name: TABLE feature_override_field_paths; Type: ACL; Schema: ops; Owner: ktm_feature_schema_owner
--

GRANT SELECT ON TABLE ops.feature_override_field_paths TO ktm_feature_state_procedure_owner;
GRANT SELECT ON TABLE ops.feature_override_field_paths TO ktm_feature_runtime;


--
-- Name: TABLE feature_overrides; Type: ACL; Schema: ops; Owner: ktm_feature_schema_owner
--

GRANT SELECT,INSERT ON TABLE ops.feature_overrides TO ktm_feature_state_procedure_owner;
GRANT SELECT ON TABLE ops.feature_overrides TO ktm_feature_runtime;


--
-- Name: COLUMN feature_overrides.source_record_key; Type: ACL; Schema: ops; Owner: ktm_feature_schema_owner
--

GRANT UPDATE(source_record_key) ON TABLE ops.feature_overrides TO ktm_feature_state_procedure_owner;


--
-- Name: COLUMN feature_overrides.source_value; Type: ACL; Schema: ops; Owner: ktm_feature_schema_owner
--

GRANT UPDATE(source_value) ON TABLE ops.feature_overrides TO ktm_feature_state_procedure_owner;


--
-- Name: COLUMN feature_overrides.override_value; Type: ACL; Schema: ops; Owner: ktm_feature_schema_owner
--

GRANT UPDATE(override_value) ON TABLE ops.feature_overrides TO ktm_feature_state_procedure_owner;


--
-- Name: COLUMN feature_overrides.prevent_provider_reactivation; Type: ACL; Schema: ops; Owner: ktm_feature_schema_owner
--

GRANT UPDATE(prevent_provider_reactivation) ON TABLE ops.feature_overrides TO ktm_feature_state_procedure_owner;


--
-- Name: COLUMN feature_overrides.status; Type: ACL; Schema: ops; Owner: ktm_feature_schema_owner
--

GRANT UPDATE(status) ON TABLE ops.feature_overrides TO ktm_feature_state_procedure_owner;


--
-- Name: COLUMN feature_overrides.reason; Type: ACL; Schema: ops; Owner: ktm_feature_schema_owner
--

GRANT UPDATE(reason) ON TABLE ops.feature_overrides TO ktm_feature_state_procedure_owner;


--
-- Name: COLUMN feature_overrides.created_by; Type: ACL; Schema: ops; Owner: ktm_feature_schema_owner
--

GRANT UPDATE(created_by) ON TABLE ops.feature_overrides TO ktm_feature_state_procedure_owner;


--
-- Name: COLUMN feature_overrides.created_at; Type: ACL; Schema: ops; Owner: ktm_feature_schema_owner
--

GRANT UPDATE(created_at) ON TABLE ops.feature_overrides TO ktm_feature_state_procedure_owner;


--
-- Name: COLUMN feature_overrides.source_provider_dataset_id; Type: ACL; Schema: ops; Owner: ktm_feature_schema_owner
--

GRANT UPDATE(source_provider_dataset_id) ON TABLE ops.feature_overrides TO ktm_feature_state_procedure_owner;


--
-- Name: COLUMN feature_overrides.source_entity_key; Type: ACL; Schema: ops; Owner: ktm_feature_schema_owner
--

GRANT UPDATE(source_entity_key) ON TABLE ops.feature_overrides TO ktm_feature_state_procedure_owner;


--
-- Name: COLUMN feature_overrides.source_raw_payload_hash; Type: ACL; Schema: ops; Owner: ktm_feature_schema_owner
--

GRANT UPDATE(source_raw_payload_hash) ON TABLE ops.feature_overrides TO ktm_feature_state_procedure_owner;


--
-- Name: COLUMN feature_overrides.value_geometry; Type: ACL; Schema: ops; Owner: ktm_feature_schema_owner
--

GRANT UPDATE(value_geometry) ON TABLE ops.feature_overrides TO ktm_feature_state_procedure_owner;


--
-- Name: COLUMN feature_overrides.command_id; Type: ACL; Schema: ops; Owner: ktm_feature_schema_owner
--

GRANT UPDATE(command_id) ON TABLE ops.feature_overrides TO ktm_feature_state_procedure_owner;


--
-- Name: COLUMN feature_overrides.base_revision; Type: ACL; Schema: ops; Owner: ktm_feature_schema_owner
--

GRANT UPDATE(base_revision) ON TABLE ops.feature_overrides TO ktm_feature_state_procedure_owner;


--
-- Name: COLUMN feature_overrides.revoked_at; Type: ACL; Schema: ops; Owner: ktm_feature_schema_owner
--

GRANT UPDATE(revoked_at) ON TABLE ops.feature_overrides TO ktm_feature_state_procedure_owner;


--
-- Name: COLUMN feature_overrides.revoked_by; Type: ACL; Schema: ops; Owner: ktm_feature_schema_owner
--

GRANT UPDATE(revoked_by) ON TABLE ops.feature_overrides TO ktm_feature_state_procedure_owner;


--
-- Name: COLUMN feature_overrides.revoked_reason; Type: ACL; Schema: ops; Owner: ktm_feature_schema_owner
--

GRANT UPDATE(revoked_reason) ON TABLE ops.feature_overrides TO ktm_feature_state_procedure_owner;


--
-- Name: TABLE tvn36_legacy_freeze_preflight_manifest; Type: ACL; Schema: ops; Owner: ktm_feature_schema_owner
--

GRANT SELECT,INSERT,DELETE ON TABLE ops.tvn36_legacy_freeze_preflight_manifest TO ktm_feature_state_procedure_owner;


--
-- Name: TABLE provider_datasets; Type: ACL; Schema: provider_sync; Owner: ktm_feature_schema_owner
--

GRANT SELECT ON TABLE provider_sync.provider_datasets TO ktm_feature_state_procedure_owner;


--
-- Name: COLUMN provider_datasets.provider_dataset_id; Type: ACL; Schema: provider_sync; Owner: ktm_feature_schema_owner
--

GRANT UPDATE(provider_dataset_id) ON TABLE provider_sync.provider_datasets TO ktm_feature_state_procedure_owner;


--
-- Name: TABLE source_entities; Type: ACL; Schema: provider_sync; Owner: ktm_feature_schema_owner
--

GRANT SELECT ON TABLE provider_sync.source_entities TO ktm_feature_state_procedure_owner;


--
-- Name: COLUMN source_entities.source_entity_key; Type: ACL; Schema: provider_sync; Owner: ktm_feature_schema_owner
--

GRANT UPDATE(source_entity_key) ON TABLE provider_sync.source_entities TO ktm_feature_state_procedure_owner;


--
-- Name: TABLE source_links; Type: ACL; Schema: provider_sync; Owner: ktm_feature_schema_owner
--

GRANT SELECT ON TABLE provider_sync.source_links TO ktm_feature_state_procedure_owner;


--
-- Name: COLUMN source_links.source_entity_key; Type: ACL; Schema: provider_sync; Owner: ktm_feature_schema_owner
--

GRANT UPDATE(source_entity_key) ON TABLE provider_sync.source_links TO ktm_feature_state_procedure_owner;


--
-- Name: TABLE source_records; Type: ACL; Schema: provider_sync; Owner: ktm_feature_schema_owner
--

GRANT SELECT ON TABLE provider_sync.source_records TO ktm_feature_state_procedure_owner;


--
-- Name: COLUMN source_records.source_entity_key; Type: ACL; Schema: provider_sync; Owner: ktm_feature_schema_owner
--

GRANT UPDATE(source_entity_key) ON TABLE provider_sync.source_records TO ktm_feature_state_procedure_owner;


--
-- PostgreSQL database dump complete
--
