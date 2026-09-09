-- OUT 목록이 바뀌면 반환 record 타입이 바뀌므로 CREATE OR REPLACE가 거부한다.
DROP PROCEDURE feature.author_feature_field_overrides(text, bigint, text, text, bigint, jsonb, jsonb);

CREATE PROCEDURE feature.author_feature_field_overrides(IN p_feature_id uuid, IN p_expected_row_revision bigint, IN p_principal text, IN p_reason_code text, IN p_command_id bigint, IN p_values jsonb, IN p_geometry_wkt jsonb, OUT o_feature_id uuid, OUT o_row_revision bigint, OUT o_command_id bigint, OUT o_applied_field_count integer)
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
       OR p_feature_id IS NULL
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
        'admin.feature.override.author', 'admin.feature.create.manual-v1', 'admin.feature.patch'
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
            THEN NULLIF(p_values ->> 'core.parent_feature_id', '')::uuid
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


ALTER PROCEDURE feature.author_feature_field_overrides(IN p_feature_id uuid, IN p_expected_row_revision bigint, IN p_principal text, IN p_reason_code text, IN p_command_id bigint, IN p_values jsonb, IN p_geometry_wkt jsonb, OUT o_feature_id uuid, OUT o_row_revision bigint, OUT o_command_id bigint, OUT o_applied_field_count integer) OWNER TO ktm_feature_state_procedure_owner;

-- DROP PROCEDURE가 명시 ACL을 통째로 버린다. head-schema.sql:24864-24865의 두 문장을
-- 새 시그니처로 되살린다. REVOKE를 빠뜨리면 CREATE가 되돌린 PUBLIC EXECUTE 때문에
-- src/kortravelmap/infra/db.py startup preflight가 배포를 막는다.
REVOKE ALL ON PROCEDURE feature.author_feature_field_overrides(IN p_feature_id uuid, IN p_expected_row_revision bigint, IN p_principal text, IN p_reason_code text, IN p_command_id bigint, IN p_values jsonb, IN p_geometry_wkt jsonb, OUT o_feature_id uuid, OUT o_row_revision bigint, OUT o_command_id bigint, OUT o_applied_field_count integer) FROM PUBLIC;
GRANT ALL ON PROCEDURE feature.author_feature_field_overrides(IN p_feature_id uuid, IN p_expected_row_revision bigint, IN p_principal text, IN p_reason_code text, IN p_command_id bigint, IN p_values jsonb, IN p_geometry_wkt jsonb, OUT o_feature_id uuid, OUT o_row_revision bigint, OUT o_command_id bigint, OUT o_applied_field_count integer) TO ktm_feature_runtime;
