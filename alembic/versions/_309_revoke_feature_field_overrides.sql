-- 이 사이드카는 자기 역할 창을 스스로 연다.
--
-- 바깥에서 `SET ROLE`로 묶으면 순서에 결박된다 — 자기 창을 가진 사이드카가 끝에서
-- 스키마 소유자로 되돌리는 순간, 뒤따르는 파일은 바깥 그룹이 지정한 롤이 아니라
-- 스키마 소유자로 실행된다. 2026-09-09 n150 실행이 그것을 잡았다
-- (`must be owner of function derive_subtype_public_ready`).
--
-- 롤은 NOINHERIT라 멤버십만으로는 소유자 검사를 통과하지 못한다. `feature` 스키마는
-- 모든 소유자 롤이 `ALL`을 가지므로(alembic/head-schema.sql:24731-24737) 이 창 안에서
-- DROP·CREATE·GRANT가 모두 성립한다.
SET ROLE ktm_feature_state_procedure_owner;

-- OUT 목록이 바뀌면 반환 record 타입이 바뀌므로 CREATE OR REPLACE가 거부한다.
DROP PROCEDURE feature.revoke_feature_field_overrides(text, bigint, text, text, bigint, text[]);

CREATE PROCEDURE feature.revoke_feature_field_overrides(IN p_feature_id uuid, IN p_expected_row_revision bigint, IN p_principal text, IN p_reason_code text, IN p_command_id bigint, IN p_field_paths text[], OUT o_feature_id uuid, OUT o_row_revision bigint, OUT o_command_id bigint, OUT o_applied_field_count integer)
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
       OR p_feature_id IS NULL
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
            THEN NULLIF(v_values ->> 'core.parent_feature_id', '')::uuid
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


DO $t39_owner$
DECLARE
    had_create boolean;
BEGIN
    -- 소유권 이전은 새 소유자가 담는 스키마의 CREATE 권한을 요구한다.
    -- 302_m03_child_issuance.py:324-330이 `ops`에서 같은 함정을 만났다. 다만 그
    -- 형태는 이미 CREATE를 가진 롤에서 권한을 빼앗으므로, 여기서는 **자기 상태를
    -- 보고** 되돌린다. 2026-09-09 n150 첫 실행이 이것을 잡았다
    -- (`permission denied for schema ops`).
    had_create := has_schema_privilege('ktm_feature_state_procedure_owner', 'feature', 'CREATE');
    IF NOT had_create THEN
        EXECUTE 'GRANT CREATE ON SCHEMA feature TO ktm_feature_state_procedure_owner';
    END IF;
    EXECUTE 'ALTER PROCEDURE feature.revoke_feature_field_overrides(IN p_feature_id uuid, IN p_expected_row_revision bigint, IN p_principal text, IN p_reason_code text, IN p_command_id bigint, IN p_field_paths text[], OUT o_feature_id uuid, OUT o_row_revision bigint, OUT o_command_id bigint, OUT o_applied_field_count integer) OWNER TO ktm_feature_state_procedure_owner';
    IF NOT had_create THEN
        EXECUTE 'REVOKE CREATE ON SCHEMA feature FROM ktm_feature_state_procedure_owner';
    END IF;
END
$t39_owner$;

-- DROP PROCEDURE가 명시 ACL을 통째로 버린다. head-schema.sql:25296-25297의 두 문장을
-- 새 시그니처로 되살린다.
REVOKE ALL ON PROCEDURE feature.revoke_feature_field_overrides(IN p_feature_id uuid, IN p_expected_row_revision bigint, IN p_principal text, IN p_reason_code text, IN p_command_id bigint, IN p_field_paths text[], OUT o_feature_id uuid, OUT o_row_revision bigint, OUT o_command_id bigint, OUT o_applied_field_count integer) FROM PUBLIC;
GRANT ALL ON PROCEDURE feature.revoke_feature_field_overrides(IN p_feature_id uuid, IN p_expected_row_revision bigint, IN p_principal text, IN p_reason_code text, IN p_command_id bigint, IN p_field_paths text[], OUT o_feature_id uuid, OUT o_row_revision bigint, OUT o_command_id bigint, OUT o_applied_field_count integer) TO ktm_feature_runtime;

SET ROLE ktm_feature_schema_owner;
