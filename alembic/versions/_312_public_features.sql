-- feature.public_features — route geometry를 보조 relation에서 읽는다.
--
-- 판정: 교체(geom 컬럼과 조인 한정)
--
-- 312가 `feature_routes.geom`을 `feature.feature_route_geometries`로 옮기므로,
-- 이 뷰의 `COALESCE(route.geom, area.geom)`이 가리키는 곳도 함께 옮긴다.
-- 본문은 `alembic/head-schema.sql`의 정의에서 **추출해** 그 두 자리만 바꿨다.
--
-- 출력 컬럼의 이름·순서·타입이 변하지 않으므로 `CREATE OR REPLACE VIEW`가 성립하고
-- ADR-067 공개 projection 계약도 그대로다. 늘어나는 것은 PK↔PK LEFT JOIN 하나다.
--
-- `route` 별칭은 **그대로 둔다** — `geometry_source`/`geometry_status` 같은 비-공간
-- 컬럼은 여전히 `feature_routes`에 있다.

SET ROLE ktm_feature_schema_owner;

CREATE OR REPLACE VIEW feature.public_features AS
 SELECT core.feature_id,
    (core.feature_id)::text AS feature_uuid,
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
    COALESCE(route_geom.geom, area.geom) AS geom,
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
   FROM ((((((feature.features core
     LEFT JOIN feature.feature_places place ON ((place.feature_id = core.feature_id)))
     LEFT JOIN feature.feature_events event ON ((event.feature_id = core.feature_id)))
     LEFT JOIN feature.feature_notices notice ON ((notice.feature_id = core.feature_id)))
     LEFT JOIN feature.feature_routes route ON ((route.feature_id = core.feature_id)))
     LEFT JOIN feature.feature_route_geometries route_geom ON ((route_geom.feature_id = core.feature_id)))
     LEFT JOIN feature.feature_areas area ON ((area.feature_id = core.feature_id)))
  WHERE ((core.lifecycle_state = 'active'::text) AND (core.publication_state = 'published'::text) AND (core.quality_state = 'valid'::text));
