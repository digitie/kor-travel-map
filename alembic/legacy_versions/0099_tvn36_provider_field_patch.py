"""T-VN-36B provider field patch와 static effective materializer.

Revision ID: 0099_tvn36_provider_field_patch
Revises: 0098_tvn36_override_lineage

provider의 현재 source evidence를 잠근 뒤 base ledger를 갱신하고, active
override가 없는 field만 typed effective core/subtype에 materialize한다. registry
문자열은 SQL 식별자로 실행하지 않는다. 이 migration 안의 static assignment만
물리 column을 결정한다.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# This migration deliberately keeps its static field-to-column assignments readable.
# ruff: noqa: E501

revision: str = "0099_tvn36_provider_field_patch"
down_revision: str | Sequence[str] | None = "0098_tvn36_override_lineage"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _assignment(
    *,
    alias: str,
    column: str,
    field_path: str,
    expression: str,
    source: str = "p_values",
) -> str:
    """고정 registry path만 materializer SQL의 assignment로 compile한다."""

    return f"""{column} = CASE
            WHEN {source} ? '{field_path}'
             AND NOT feature.has_active_feature_override(p_feature_id, '{field_path}')
            THEN {expression}
            ELSE {alias}.{column}
        END"""


_CORE_ASSIGNMENTS = (
    _assignment(alias="core", column="name", field_path="core.name", expression="p_values ->> 'core.name'"),
    _assignment(alias="core", column="category", field_path="core.category", expression="p_values ->> 'core.category'"),
    _assignment(
        alias="core",
        column="coord",
        field_path="core.coord",
        source="p_geometry_wkt",
        expression="CASE WHEN p_geometry_wkt ->> 'core.coord' IS NULL THEN NULL ELSE x_extension.st_geomfromtext(p_geometry_wkt ->> 'core.coord', 4326) END",
    ),
    _assignment(alias="core", column="coord_precision_digits", field_path="core.coord_precision_digits", expression="(p_values ->> 'core.coord_precision_digits')::smallint"),
    _assignment(alias="core", column="address", field_path="core.address", expression="p_values -> 'core.address'"),
    _assignment(alias="core", column="legal_dong_code", field_path="core.legal_dong_code", expression="p_values ->> 'core.legal_dong_code'"),
    _assignment(alias="core", column="road_name_code", field_path="core.road_name_code", expression="p_values ->> 'core.road_name_code'"),
    _assignment(alias="core", column="road_address_management_no", field_path="core.road_address_management_no", expression="p_values ->> 'core.road_address_management_no'"),
    _assignment(alias="core", column="admin_dong_code", field_path="core.admin_dong_code", expression="p_values ->> 'core.admin_dong_code'"),
    _assignment(alias="core", column="sido_code", field_path="core.sido_code", expression="p_values ->> 'core.sido_code'"),
    _assignment(alias="core", column="sigungu_code", field_path="core.sigungu_code", expression="p_values ->> 'core.sigungu_code'"),
    _assignment(alias="core", column="urls", field_path="core.urls", expression="p_values -> 'core.urls'"),
    _assignment(alias="core", column="marker_icon", field_path="core.marker_icon", expression="p_values ->> 'core.marker_icon'"),
    _assignment(alias="core", column="marker_color", field_path="core.marker_color", expression="p_values ->> 'core.marker_color'"),
    _assignment(alias="core", column="parent_feature_id", field_path="core.parent_feature_id", expression="p_values ->> 'core.parent_feature_id'"),
    _assignment(alias="core", column="sibling_group_id", field_path="core.sibling_group_id", expression="NULLIF(p_values ->> 'core.sibling_group_id', '')::uuid"),
    _assignment(alias="core", column="raw_refs", field_path="core.raw_refs", expression="p_values -> 'core.raw_refs'"),
)

_PLACE_ASSIGNMENTS = (
    _assignment(alias="place", column="place_kind", field_path="place.place_kind", expression="p_values ->> 'place.place_kind'"),
    _assignment(alias="place", column="phones", field_path="place.phones", expression="ARRAY(SELECT jsonb_array_elements_text(p_values -> 'place.phones'))"),
    _assignment(alias="place", column="biz_number", field_path="place.biz_number", expression="p_values ->> 'place.biz_number'"),
    _assignment(alias="place", column="license_date", field_path="place.license_date", expression="(p_values ->> 'place.license_date')::date"),
    _assignment(alias="place", column="business_hours", field_path="place.business_hours", expression="p_values -> 'place.business_hours'"),
    _assignment(alias="place", column="facility_info", field_path="place.facility_info", expression="p_values -> 'place.facility_info'"),
    _assignment(alias="place", column="reviews_link", field_path="place.reviews_link", expression="p_values -> 'place.reviews_link'"),
    _assignment(alias="place", column="payload", field_path="place.payload", expression="p_values -> 'place.payload'"),
)

_EVENT_ASSIGNMENTS = (
    _assignment(alias="event", column="event_kind", field_path="event.event_kind", expression="p_values ->> 'event.event_kind'"),
    _assignment(alias="event", column="starts_on", field_path="event.starts_on", expression="(p_values ->> 'event.starts_on')::date"),
    _assignment(alias="event", column="ends_on", field_path="event.ends_on", expression="(p_values ->> 'event.ends_on')::date"),
    _assignment(alias="event", column="timezone", field_path="event.timezone", expression="p_values ->> 'event.timezone'"),
    _assignment(alias="event", column="opening_hours", field_path="event.opening_hours", expression="p_values -> 'event.opening_hours'"),
    _assignment(alias="event", column="venue_name", field_path="event.venue_name", expression="p_values ->> 'event.venue_name'"),
    _assignment(alias="event", column="tel", field_path="event.tel", expression="p_values ->> 'event.tel'"),
    _assignment(alias="event", column="content_id", field_path="event.content_id", expression="p_values ->> 'event.content_id'"),
    _assignment(alias="event", column="content_type_id", field_path="event.content_type_id", expression="p_values ->> 'event.content_type_id'"),
    _assignment(alias="event", column="area_code", field_path="event.area_code", expression="p_values ->> 'event.area_code'"),
    _assignment(alias="event", column="sigungu_code", field_path="event.sigungu_code", expression="p_values ->> 'event.sigungu_code'"),
    _assignment(alias="event", column="payload", field_path="event.payload", expression="p_values -> 'event.payload'"),
)

_NOTICE_ASSIGNMENTS = (
    _assignment(alias="notice", column="notice_type", field_path="notice.notice_type", expression="p_values ->> 'notice.notice_type'"),
    _assignment(alias="notice", column="severity", field_path="notice.severity", expression="(p_values ->> 'notice.severity')::smallint"),
    _assignment(alias="notice", column="valid_start_time", field_path="notice.valid_start_time", expression="(p_values ->> 'notice.valid_start_time')::timestamptz"),
    _assignment(alias="notice", column="valid_end_time", field_path="notice.valid_end_time", expression="(p_values ->> 'notice.valid_end_time')::timestamptz"),
    _assignment(alias="notice", column="source_agency", field_path="notice.source_agency", expression="p_values ->> 'notice.source_agency'"),
    _assignment(alias="notice", column="officer_name", field_path="notice.officer_name", expression="p_values ->> 'notice.officer_name'"),
    _assignment(alias="notice", column="payload", field_path="notice.payload", expression="p_values -> 'notice.payload'"),
)

_ROUTE_ASSIGNMENTS = (
    _assignment(alias="route", column="geom", field_path="route.geom", source="p_geometry_wkt", expression="x_extension.st_geomfromtext(p_geometry_wkt ->> 'route.geom', 4326)"),
    _assignment(alias="route", column="route_type", field_path="route.route_type", expression="p_values ->> 'route.route_type'"),
    _assignment(alias="route", column="geometry_source", field_path="route.geometry_source", expression="p_values ->> 'route.geometry_source'"),
    _assignment(alias="route", column="geometry_status", field_path="route.geometry_status", expression="p_values ->> 'route.geometry_status'"),
    _assignment(alias="route", column="total_distance_meters", field_path="route.total_distance_meters", expression="(p_values ->> 'route.total_distance_meters')::numeric"),
    _assignment(alias="route", column="expected_duration_minutes", field_path="route.expected_duration_minutes", expression="(p_values ->> 'route.expected_duration_minutes')::integer"),
    _assignment(alias="route", column="difficulty", field_path="route.difficulty", expression="p_values ->> 'route.difficulty'"),
    _assignment(alias="route", column="begin_name", field_path="route.begin_name", expression="p_values ->> 'route.begin_name'"),
    _assignment(alias="route", column="begin_address", field_path="route.begin_address", expression="p_values ->> 'route.begin_address'"),
    _assignment(alias="route", column="end_name", field_path="route.end_name", expression="p_values ->> 'route.end_name'"),
    _assignment(alias="route", column="end_address", field_path="route.end_address", expression="p_values ->> 'route.end_address'"),
    _assignment(alias="route", column="payload", field_path="route.payload", expression="p_values -> 'route.payload'"),
)

_AREA_ASSIGNMENTS = (
    _assignment(alias="area", column="geom", field_path="area.geom", source="p_geometry_wkt", expression="x_extension.st_geomfromtext(p_geometry_wkt ->> 'area.geom', 4326)"),
    _assignment(alias="area", column="area_kind", field_path="area.area_kind", expression="p_values ->> 'area.area_kind'"),
    _assignment(alias="area", column="boundary_source", field_path="area.boundary_source", expression="p_values ->> 'area.boundary_source'"),
    _assignment(alias="area", column="area_square_meters", field_path="area.area_square_meters", expression="(p_values ->> 'area.area_square_meters')::numeric"),
    _assignment(alias="area", column="regulation_scope", field_path="area.regulation_scope", expression="p_values ->> 'area.regulation_scope'"),
    _assignment(alias="area", column="administrative_office", field_path="area.administrative_office", expression="p_values ->> 'area.administrative_office'"),
    _assignment(alias="area", column="description", field_path="area.description", expression="p_values ->> 'area.description'"),
    _assignment(alias="area", column="payload", field_path="area.payload", expression="p_values -> 'area.payload'"),
)


def _render_update(relation: str, alias: str, assignments: tuple[str, ...]) -> str:
    rendered_assignments = ",\n            ".join(assignments)
    return f"""UPDATE feature.{relation} AS {alias}
        SET {rendered_assignments}
      WHERE {alias}.feature_id = p_feature_id;"""


_HAS_ACTIVE_OVERRIDE_FUNCTION_SQL = """
CREATE OR REPLACE FUNCTION feature.has_active_feature_override(
    p_feature_id text,
    p_field_path text
) RETURNS boolean
LANGUAGE sql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
    SELECT EXISTS (
        SELECT 1
        FROM ops.feature_overrides AS override
        WHERE override.feature_id = p_feature_id
          AND override.field_path = p_field_path
          AND override.status = 'active'
    );
$$;
"""


_CORE_ASSIGNMENTS_SQL = ",\n        ".join(_CORE_ASSIGNMENTS)


_PROVIDER_PATCH_PROCEDURE_SQL = f"""
CREATE PROCEDURE feature.apply_provider_feature_field_patch(
    IN p_feature_id text,
    IN p_provider_dataset_id bigint,
    IN p_source_entity_key text,
    IN p_source_record_key text,
    IN p_expected_row_revision bigint,
    IN p_values jsonb,
    IN p_geometry_wkt jsonb,
    OUT o_feature_id text,
    OUT o_row_revision bigint,
    OUT o_applied_field_count integer
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
DECLARE
    v_feature feature.features%ROWTYPE;
    v_registry ops.feature_override_field_paths%ROWTYPE;
    v_source_hash text;
    v_field_path text;
    v_value jsonb;
    v_geometry_wkt text;
    v_base_revision bigint;
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
            v_value, v_base_revision, clock_timestamp()
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
    FOR v_field_path, v_geometry_wkt IN SELECT key, value FROM jsonb_each_text(p_geometry_wkt) LOOP
        SELECT * INTO v_registry
        FROM ops.feature_override_field_paths
        WHERE field_path = v_field_path;
        IF NOT FOUND OR NOT v_registry.provider_writable
           OR v_registry.value_kind <> 'geometry'
           OR (v_registry.feature_kind <> '*' AND v_registry.feature_kind <> v_feature.kind)
           OR coalesce(btrim(v_geometry_wkt), '') = '' THEN
            RAISE EXCEPTION 'provider cannot write geometry field path %', v_field_path
                USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_provider_field_path';
        END IF;
        INSERT INTO feature.feature_base_field_values (
            feature_id, field_path, feature_uuid, provider_dataset_id,
            source_entity_key, source_record_key, source_raw_payload_hash,
            value_geometry, base_revision, observed_at
        ) VALUES (
            p_feature_id, v_field_path, v_feature.feature_uuid, p_provider_dataset_id,
            p_source_entity_key, p_source_record_key, v_source_hash,
            x_extension.st_geomfromtext(v_geometry_wkt, 4326), v_base_revision,
            clock_timestamp()
        ) ON CONFLICT (feature_id, field_path) DO UPDATE
        SET feature_uuid = EXCLUDED.feature_uuid,
            provider_dataset_id = EXCLUDED.provider_dataset_id,
            source_entity_key = EXCLUDED.source_entity_key,
            source_record_key = EXCLUDED.source_record_key,
            source_raw_payload_hash = EXCLUDED.source_raw_payload_hash,
            value_json = NULL,
            value_geometry = EXCLUDED.value_geometry,
            base_revision = EXCLUDED.base_revision,
            observed_at = EXCLUDED.observed_at,
            updated_at = clock_timestamp();
    END LOOP;

    UPDATE feature.features AS core
    SET {_CORE_ASSIGNMENTS_SQL},
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
        {_render_update('feature_places', 'place', _PLACE_ASSIGNMENTS)}
    ELSIF v_feature.kind = 'event' AND EXISTS (
        SELECT 1
        FROM jsonb_object_keys(p_values) AS supplied_path(field_path)
        WHERE supplied_path.field_path LIKE 'event.%'
    ) THEN
        PERFORM 1 FROM feature.feature_events WHERE feature_id = p_feature_id FOR UPDATE;
        IF NOT FOUND THEN RAISE EXCEPTION 'event subtype is missing' USING ERRCODE = '23514'; END IF;
        {_render_update('feature_events', 'event', _EVENT_ASSIGNMENTS)}
    ELSIF v_feature.kind = 'notice' AND EXISTS (
        SELECT 1
        FROM jsonb_object_keys(p_values) AS supplied_path(field_path)
        WHERE supplied_path.field_path LIKE 'notice.%'
    ) THEN
        PERFORM 1 FROM feature.feature_notices WHERE feature_id = p_feature_id FOR UPDATE;
        IF NOT FOUND THEN RAISE EXCEPTION 'notice subtype is missing' USING ERRCODE = '23514'; END IF;
        {_render_update('feature_notices', 'notice', _NOTICE_ASSIGNMENTS)}
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
        {_render_update('feature_routes', 'route', _ROUTE_ASSIGNMENTS)}
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
        {_render_update('feature_areas', 'area', _AREA_ASSIGNMENTS)}
    END IF;
END;
$$;
"""


def upgrade() -> None:
    op.execute("SET ROLE ktm_feature_state_procedure_owner")
    for statement in (
        _HAS_ACTIVE_OVERRIDE_FUNCTION_SQL,
        _PROVIDER_PATCH_PROCEDURE_SQL,
        "ALTER FUNCTION feature.has_active_feature_override(text, text) OWNER TO ktm_feature_state_procedure_owner",
        "ALTER PROCEDURE feature.apply_provider_feature_field_patch(text, bigint, text, text, bigint, jsonb, jsonb) OWNER TO ktm_feature_state_procedure_owner",
        "REVOKE ALL ON FUNCTION feature.has_active_feature_override(text, text) FROM PUBLIC, ktm_feature_runtime",
        "REVOKE ALL ON PROCEDURE feature.apply_provider_feature_field_patch(text, bigint, text, text, bigint, jsonb, jsonb) FROM PUBLIC",
        "GRANT EXECUTE ON PROCEDURE feature.apply_provider_feature_field_patch(text, bigint, text, text, bigint, jsonb, jsonb) TO ktm_feature_runtime",
    ):
        op.execute(statement)
    op.execute("SET ROLE ktm_feature_schema_owner")
    for statement in (
        "GRANT UPDATE (kind, name, category, coord, coord_precision_digits, address, legal_dong_code, road_name_code, road_address_management_no, admin_dong_code, sido_code, sigungu_code, urls, marker_icon, marker_color, parent_feature_id, sibling_group_id, raw_refs, updated_at) ON feature.features TO ktm_feature_state_procedure_owner",
        "GRANT SELECT, UPDATE (place_kind, phones, biz_number, license_date, business_hours, facility_info, reviews_link, payload) ON feature.feature_places TO ktm_feature_state_procedure_owner",
        "GRANT SELECT, UPDATE (event_kind, starts_on, ends_on, timezone, opening_hours, venue_name, tel, content_id, content_type_id, area_code, sigungu_code, payload) ON feature.feature_events TO ktm_feature_state_procedure_owner",
        "GRANT SELECT, UPDATE (notice_type, severity, valid_start_time, valid_end_time, source_agency, officer_name, payload) ON feature.feature_notices TO ktm_feature_state_procedure_owner",
        "GRANT SELECT, UPDATE (geom, route_type, geometry_source, geometry_status, total_distance_meters, expected_duration_minutes, difficulty, begin_name, begin_address, end_name, end_address, payload) ON feature.feature_routes TO ktm_feature_state_procedure_owner",
        "GRANT SELECT, UPDATE (geom, area_kind, boundary_source, area_square_meters, regulation_scope, administrative_office, description, payload) ON feature.feature_areas TO ktm_feature_state_procedure_owner",
    ):
        op.execute(statement)


def downgrade() -> None:
    raise RuntimeError("0099 is forward-only; rebuild with the T-VN-36 release head")
