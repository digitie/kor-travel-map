# ruff: noqa: E501
"""T-VN-34C final typed projection·legacy state cutover.

Revision ID: 0097_tvn34c_final_cutover
Revises: 0096_tvn34_public_projection

`features_detailed`는 0087의 임시 read bridge였다. 이 final migration은
public projection과 security-definer snapshot writer를 typed core+subtype 직접
assembly로 먼저 옮기고, durable user request receipt를 만든 뒤에만 bridge와
legacy Feature state/provenance 열을 물리 제거한다. `data_origin` /
`data_version`과 version materializer는 T-VN-36 입력이므로 남긴다.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0097_tvn34c_final_cutover"
down_revision: str | Sequence[str] | None = "0096_tvn34_public_projection"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Reused only to render three explicit core+subtype SQL statements below.
# No database-side private view/function replaces the detail bridge.
_TYPED_DETAIL_EXPRESSION = r"""
COALESCE(
        (
            CASE core.kind
                WHEN 'place' THEN CASE WHEN place.feature_id IS NULL THEN NULL ELSE jsonb_build_object(
                    'feature_id', core.feature_id,
                    'place_kind', place.place_kind,
                    'phones', to_jsonb(place.phones),
                    'biz_number', place.biz_number,
                    'license_date', to_jsonb(place.license_date),
                    'business_hours', place.business_hours,
                    'facility_info', place.facility_info,
                    'reviews_link', place.reviews_link,
                    'payload', place.payload
                ) END
                WHEN 'event' THEN CASE WHEN event.feature_id IS NULL THEN NULL ELSE jsonb_build_object(
                    'feature_id', core.feature_id,
                    'event_kind', event.event_kind,
                    'starts_on', to_jsonb(event.starts_on),
                    'ends_on', to_jsonb(event.ends_on),
                    'timezone', event.timezone,
                    'opening_hours', event.opening_hours,
                    'venue_name', event.venue_name,
                    'tel', event.tel,
                    'content_id', event.content_id,
                    'content_type_id', event.content_type_id,
                    'area_code', event.area_code,
                    'sigungu_code', event.sigungu_code,
                    'payload', event.payload
                ) END
                WHEN 'notice' THEN CASE WHEN notice.feature_id IS NULL THEN NULL ELSE jsonb_build_object(
                    'feature_id', core.feature_id,
                    'notice_type', notice.notice_type,
                    'severity', notice.severity,
                    -- timestamptz를 그냥 to_jsonb 하면 문자열이 **세션 TimeZone
                    -- GUC에 의존**한다(실측: 같은 행이 Asia/Seoul 세션에서
                    -- '...+09:00', UTC 세션에서 '...+00:00'). 서버 설정이 다른
                    -- 인스턴스가 같은 공지에 다른 문자열을 돌려주게 된다.
                    -- KST 고정 렌더로 세션 비의존을 만든다(SKILL.md 규칙 17 —
                    -- 모든 datetime은 KST aware). 마이크로초가 0이면 생략해
                    -- Python ``datetime.isoformat()``과 바이트까지 같다(prod
                    -- valid_start_time 145/145 무변경).
                    'valid_start_time', to_jsonb(
                        to_char(
                            notice.valid_start_time AT TIME ZONE 'Asia/Seoul',
                            CASE
                                WHEN EXTRACT(microsecond FROM notice.valid_start_time)::bigint
                                     % 1000000 = 0
                                THEN 'YYYY-MM-DD"T"HH24:MI:SS"+09:00"'
                                ELSE 'YYYY-MM-DD"T"HH24:MI:SS.US"+09:00"'
                            END
                        )
                    ),
                    'valid_end_time', to_jsonb(
                        to_char(
                            notice.valid_end_time AT TIME ZONE 'Asia/Seoul',
                            CASE
                                WHEN EXTRACT(microsecond FROM notice.valid_end_time)::bigint
                                     % 1000000 = 0
                                THEN 'YYYY-MM-DD"T"HH24:MI:SS"+09:00"'
                                ELSE 'YYYY-MM-DD"T"HH24:MI:SS.US"+09:00"'
                            END
                        )
                    ),
                    'source_agency', notice.source_agency,
                    'officer_name', notice.officer_name,
                    'payload', notice.payload
                ) END
                WHEN 'route' THEN CASE WHEN route.feature_id IS NULL THEN NULL ELSE jsonb_build_object(
                    'feature_id', core.feature_id,
                    'route_type', route.route_type,
                    'geometry_source', route.geometry_source,
                    'geometry_status', route.geometry_status,
                    'total_distance_meters', to_jsonb(route.total_distance_meters::text),
                    'expected_duration_minutes', route.expected_duration_minutes,
                    'difficulty', route.difficulty,
                    'begin_name', route.begin_name,
                    'begin_address', route.begin_address,
                    'end_name', route.end_name,
                    'end_address', route.end_address,
                    'payload', route.payload
                ) END
                WHEN 'area' THEN CASE WHEN area.feature_id IS NULL THEN NULL ELSE jsonb_build_object(
                    'feature_id', core.feature_id,
                    'area_kind', area.area_kind,
                    'boundary_source', area.boundary_source,
                    'area_square_meters', to_jsonb(area.area_square_meters::text),
                    'regulation_scope', area.regulation_scope,
                    'administrative_office', area.administrative_office,
                    'description', area.description,
                    'payload', area.payload
                ) END
            END
        ),
        '{}'::jsonb
    )
""".strip()

_TYPED_SUBTYPE_JOINS = """
LEFT JOIN feature.feature_places AS place ON place.feature_id = core.feature_id
LEFT JOIN feature.feature_events AS event ON event.feature_id = core.feature_id
LEFT JOIN feature.feature_notices AS notice ON notice.feature_id = core.feature_id
LEFT JOIN feature.feature_routes AS route ON route.feature_id = core.feature_id
LEFT JOIN feature.feature_areas AS area ON area.feature_id = core.feature_id
""".strip()


def _snapshot_json_expression() -> str:
    """locked core+typed subtype snapshot payload; caller JSON is never trusted."""

    return f"""
jsonb_build_object(
    'feature_id', core.feature_id,
    'feature_uuid', core.feature_uuid,
    'kind', core.kind,
    'name', core.name,
    'category', core.category,
    'lon', x_extension.ST_X(core.coord),
    'lat', x_extension.ST_Y(core.coord),
    'coord_precision_digits', core.coord_precision_digits,
    'address', core.address,
    'legal_dong_code', core.legal_dong_code,
    'road_name_code', core.road_name_code,
    'road_address_management_no', core.road_address_management_no,
    'admin_dong_code', core.admin_dong_code,
    'sido_code', core.sido_code,
    'sigungu_code', core.sigungu_code,
    'urls', core.urls,
    'marker_icon', core.marker_icon,
    'marker_color', core.marker_color,
    'parent_feature_id', core.parent_feature_id,
    'sibling_group_id', core.sibling_group_id,
    'raw_refs', core.raw_refs,
    'row_revision', core.row_revision,
    'detail', {_TYPED_DETAIL_EXPRESSION},
    'lifecycle_state', core.lifecycle_state,
    'publication_state', core.publication_state,
    'quality_state', core.quality_state,
    'data_origin', core.data_origin,
    'data_version', core.data_version,
    'created_at', core.created_at,
    'updated_at', core.updated_at
)
""".strip()


def _typed_snapshot_select(*, feature_filter: str) -> str:
    """same direct assembly as the two materializers after explicit row locks."""

    return f"""
SELECT
    core.feature_id,
    {_snapshot_json_expression()} AS payload
FROM feature.features AS core
{_TYPED_SUBTYPE_JOINS}
WHERE {feature_filter}
""".strip()


_LOCK_TYPED_SUBTYPES_SQL = """
    -- PostgreSQL forbids `FOR SHARE OF` a nullable LEFT JOIN side.  Materializers
    -- already own the core `FOR UPDATE`; acquire each optional subtype lock as
    -- an independent relation before its direct assembly snapshot instead.
    PERFORM 1 FROM feature.feature_places WHERE feature_id = p_feature_id FOR SHARE;
    PERFORM 1 FROM feature.feature_events WHERE feature_id = p_feature_id FOR SHARE;
    PERFORM 1 FROM feature.feature_notices WHERE feature_id = p_feature_id FOR SHARE;
    PERFORM 1 FROM feature.feature_routes WHERE feature_id = p_feature_id FOR SHARE;
    PERFORM 1 FROM feature.feature_areas WHERE feature_id = p_feature_id FOR SHARE;
""".strip()


_PUBLIC_FEATURES_VIEW_SQL = f"""
CREATE OR REPLACE VIEW feature.public_features AS
SELECT
    core.feature_id,
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
    {_TYPED_DETAIL_EXPRESSION} AS detail
FROM feature.features AS core
{_TYPED_SUBTYPE_JOINS}
WHERE core.lifecycle_state = 'active'
  AND core.publication_state = 'published'
  AND core.quality_state = 'valid'
"""


_CREATE_PROCEDURE_SQL = r"""
CREATE OR REPLACE PROCEDURE feature.create_feature_with_initial_state(
    IN p_feature jsonb,
    IN p_lifecycle_state text,
    IN p_publication_state text,
    IN p_quality_state text,
    IN p_context jsonb,
    OUT o_feature_id text,
    OUT o_feature_uuid uuid,
    OUT o_row_revision bigint,
    OUT o_inserted boolean
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
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
    INSERT INTO feature.features (
        feature_id, feature_uuid, kind, name, category,
        coord, coord_precision_digits,
        address, legal_dong_code, road_name_code, road_address_management_no,
        admin_dong_code, sido_code, sigungu_code,
        urls, marker_icon, marker_color, parent_feature_id, sibling_group_id,
        raw_refs, lifecycle_state, publication_state, quality_state,
        data_origin, data_version, created_at, updated_at
    ) VALUES (
        v_feature_id, v_feature_uuid, v_kind, v_name,
        v_category, v_coord, (p_feature ->> 'coord_precision_digits')::smallint,
        coalesce(p_feature -> 'address', '{}'::jsonb), p_feature ->> 'legal_dong_code',
        p_feature ->> 'road_name_code', p_feature ->> 'road_address_management_no',
        p_feature ->> 'admin_dong_code', p_feature ->> 'sido_code', p_feature ->> 'sigungu_code',
        coalesce(p_feature -> 'urls', '{}'::jsonb), p_feature ->> 'marker_icon', p_feature ->> 'marker_color',
        p_feature ->> 'parent_feature_id', nullif(p_feature ->> 'sibling_group_id', '')::uuid,
        coalesce(p_feature -> 'raw_refs', '[]'::jsonb), p_lifecycle_state,
        p_publication_state, p_quality_state, 'provider', 0,
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
"""


_TRANSITION_PROCEDURE_SQL = r"""
CREATE OR REPLACE PROCEDURE feature.transition_feature_state(
    IN p_feature_id text,
    IN p_lifecycle_state text,
    IN p_publication_state text,
    IN p_quality_state text,
    IN p_expected_row_revision bigint,
    IN p_context jsonb,
    OUT o_feature_id text,
    OUT o_row_revision bigint
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
DECLARE
    v_current feature.features%ROWTYPE;
BEGIN
    IF p_expected_row_revision IS NULL OR p_expected_row_revision < 1 THEN
        RAISE EXCEPTION 'expected feature row revision is required'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_state_expected_revision';
    END IF;
    PERFORM feature.prepare_feature_state_context(p_context, 'transition');
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
    IF p_context ->> 'transition_kind' = 'provider_sync'
       AND (
            (v_current.lifecycle_state = 'active' AND p_lifecycle_state = 'retired')
            OR (v_current.lifecycle_state = 'retired' AND p_lifecycle_state = 'active')
       )
       AND NOT EXISTS (
            SELECT 1
            FROM provider_sync.source_links AS link
            JOIN provider_sync.source_entities AS entity
              ON entity.source_entity_key = link.source_entity_key
            JOIN provider_sync.source_records AS record
              ON record.source_entity_key = entity.source_entity_key
            JOIN provider_sync.source_entity_heads AS head
              ON head.source_entity_key = entity.source_entity_key
             AND head.current_source_record_key = record.source_record_key
            WHERE link.feature_id = p_feature_id
              AND link.source_entity_key = p_context ->> 'source_entity_key'
              AND entity.provider_dataset_id = (p_context ->> 'provider_dataset_id')::bigint
              AND record.source_record_key = p_context ->> 'source_record_key'
       ) THEN
        RAISE EXCEPTION 'provider lifecycle transition requires linked authoritative source evidence'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_provider_source_provenance';
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
END;
$$;
"""


_ADMIN_TRANSITION_PROCEDURE_SQL = r"""
CREATE PROCEDURE feature.transition_admin_feature_state(
    IN p_feature_id text,
    IN p_lifecycle_state text,
    IN p_publication_state text,
    IN p_quality_state text,
    IN p_expected_row_revision bigint,
    IN p_reason_code text,
    IN p_principal text,
    IN p_action text,
    OUT o_feature_id text,
    OUT o_row_revision bigint,
    OUT o_transition_id bigint
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
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
"""


_REACTIVATE_ADMIN_PROCEDURE_SQL = r"""
CREATE PROCEDURE feature.reactivate_admin_feature_state(
    IN p_feature_id text,
    IN p_provider_dataset_id bigint,
    IN p_source_entity_key text,
    IN p_source_record_key text,
    IN p_expected_row_revision bigint,
    IN p_reason_code text,
    IN p_principal text,
    OUT o_feature_id text,
    OUT o_row_revision bigint,
    OUT o_transition_id bigint
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
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
    SELECT record.raw_payload_hash INTO v_raw_payload_hash
    FROM provider_sync.source_links AS link
    JOIN provider_sync.source_entities AS entity
      ON entity.source_entity_key = link.source_entity_key
    JOIN provider_sync.provider_datasets AS dataset
      ON dataset.provider_dataset_id = entity.provider_dataset_id
     AND dataset.is_active
    JOIN provider_sync.source_records AS record
      ON record.source_entity_key = entity.source_entity_key
     AND record.source_record_key = p_source_record_key
    JOIN provider_sync.source_entity_heads AS head
      ON head.source_entity_key = entity.source_entity_key
     AND head.current_source_record_key = record.source_record_key
    WHERE link.feature_id = p_feature_id
      AND link.source_entity_key = p_source_entity_key
      AND entity.provider_dataset_id = p_provider_dataset_id;
    IF v_raw_payload_hash IS NULL OR btrim(v_raw_payload_hash) = '' THEN
        RAISE EXCEPTION 'admin reactivation requires current linked active source evidence'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_provider_source_provenance';
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
"""


_USER_RECEIPT_GUARD_SQL = r"""
CREATE FUNCTION feature.reject_user_feature_version_mutation()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
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
"""


_USER_PROVENANCE_PROCEDURE_SQL = f"""
CREATE OR REPLACE PROCEDURE feature.materialize_user_feature_change_provenance(
    IN p_feature_id text,
    IN p_change_kind text,
    IN p_request_id uuid,
    IN p_reason text,
    IN p_operator text,
    IN p_expected_row_revision bigint,
    OUT o_feature_id text,
    OUT o_row_revision bigint
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
DECLARE
    v_current feature.features%ROWTYPE;
    v_receipt_revision bigint;
    v_next_version integer;
BEGIN
    IF p_change_kind NOT IN ('add', 'update', 'delete')
       OR p_request_id IS NULL
       OR p_expected_row_revision IS NULL OR p_expected_row_revision < 1
       OR coalesce(btrim(p_reason), '') = ''
       OR coalesce(btrim(p_operator), '') = '' THEN
        RAISE EXCEPTION 'user feature provenance has invalid typed arguments'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_user_provenance';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM ops.feature_change_requests AS request
        WHERE request.request_id = p_request_id
          AND request.feature_id = p_feature_id
          AND request.action = p_change_kind
          AND request.state = 'applied'
    ) THEN
        RAISE EXCEPTION 'user feature provenance needs an applied request for this feature/action'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_user_provenance_request';
    END IF;
    SELECT nullif(version.payload ->> 'row_revision', '')::bigint
      INTO v_receipt_revision
      FROM feature.feature_versions AS version
     WHERE version.feature_id = p_feature_id
       AND version.origin = 'user_request'
       AND version.request_id = p_request_id;
    IF FOUND THEN
        o_feature_id := p_feature_id;
        o_row_revision := v_receipt_revision;
        RETURN;
    END IF;

    SELECT * INTO v_current
      FROM feature.features
     WHERE feature_id = p_feature_id
     FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'feature % does not exist', p_feature_id USING ERRCODE = 'P0002';
    END IF;
    -- Check once more after serializing a concurrent first materialization.
    SELECT nullif(version.payload ->> 'row_revision', '')::bigint
      INTO v_receipt_revision
      FROM feature.feature_versions AS version
     WHERE version.feature_id = p_feature_id
       AND version.origin = 'user_request'
       AND version.request_id = p_request_id;
    IF FOUND THEN
        o_feature_id := p_feature_id;
        o_row_revision := v_receipt_revision;
        RETURN;
    END IF;
    IF v_current.row_revision <> p_expected_row_revision THEN
        RAISE EXCEPTION 'feature % revision changed', p_feature_id USING ERRCODE = '40001';
    END IF;
    {_LOCK_TYPED_SUBTYPES_SQL}
    IF p_change_kind = 'delete'
       AND (v_current.lifecycle_state <> 'retired'
            OR v_current.publication_state <> 'suppressed') THEN
        RAISE EXCEPTION 'delete provenance requires a retired suppressed feature'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_user_provenance_delete_state';
    END IF;
    SELECT greatest(
        v_current.data_version,
        coalesce((SELECT max(version) + 1
                  FROM feature.feature_versions AS version
                 WHERE version.feature_id = p_feature_id), 1)
    )::integer INTO v_next_version;
    UPDATE feature.features
       SET data_origin = 'user_request',
           data_version = v_next_version,
           updated_at = clock_timestamp()
     WHERE feature_id = p_feature_id
     RETURNING feature_id, row_revision INTO o_feature_id, o_row_revision;

    INSERT INTO feature.feature_versions (
        feature_id, version, origin, change_kind, payload, request_id, created_by
    )
    SELECT snapshot.feature_id, v_next_version, 'user_request', p_change_kind,
           snapshot.payload, p_request_id, btrim(p_operator)
    FROM (
        {_typed_snapshot_select(feature_filter="core.feature_id = p_feature_id")}
    ) AS snapshot;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'feature % has no typed snapshot', p_feature_id USING ERRCODE = 'P0002';
    END IF;
END;
$$;
"""


_PROVIDER_VERSION_PROCEDURE_SQL = f"""
CREATE OR REPLACE PROCEDURE feature.materialize_provider_feature_version(
    IN p_feature_id text
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
DECLARE
    v_current feature.features%ROWTYPE;
BEGIN
    SELECT * INTO v_current
      FROM feature.features
     WHERE feature_id = p_feature_id
     FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'feature % does not exist', p_feature_id USING ERRCODE = 'P0002';
    END IF;
    {_LOCK_TYPED_SUBTYPES_SQL}
    INSERT INTO feature.feature_versions (
        feature_id, version, origin, change_kind, payload, request_id, created_by
    )
    SELECT snapshot.feature_id, 0, 'provider', 'load', snapshot.payload, NULL, 'provider'
    FROM (
        {_typed_snapshot_select(feature_filter="core.feature_id = p_feature_id")}
    ) AS snapshot
    ON CONFLICT (feature_id, version) DO UPDATE SET
        payload = EXCLUDED.payload,
        origin = EXCLUDED.origin,
        change_kind = EXCLUDED.change_kind,
        request_id = EXCLUDED.request_id,
        created_by = EXCLUDED.created_by,
        created_at = clock_timestamp();
    IF NOT FOUND THEN
        RAISE EXCEPTION 'feature % has no typed snapshot', p_feature_id USING ERRCODE = 'P0002';
    END IF;
END;
$$;
"""


def upgrade() -> None:
    # A historical receipt has the former legacy snapshot shape.  Do not invent
    # false evidence by rewriting it; final cutover requires fresh provider ETL.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM feature.feature_versions WHERE origin = 'user_request'
            ) THEN
                RAISE EXCEPTION
                    'T-VN-34C requires fresh Feature rebuild when pre-cutover user receipts exist'
                    USING HINT = 'Reset/reload provider data, then apply the final cutover.';
            END IF;
        END;
        $$
        """
    )
    # 0095 transferred these routines to a dedicated NOLOGIN owner.  Alembic
    # runs as the schema owner, so it must deliberately assume that owner to
    # replace their bodies; CREATE OR REPLACE otherwise fails before DDL can
    # reach the bridge drop.
    op.execute("SET ROLE ktm_feature_state_procedure_owner")
    for statement in (
        _CREATE_PROCEDURE_SQL,
        _TRANSITION_PROCEDURE_SQL,
        _USER_RECEIPT_GUARD_SQL,
        _USER_PROVENANCE_PROCEDURE_SQL,
        _PROVIDER_VERSION_PROCEDURE_SQL,
        _ADMIN_TRANSITION_PROCEDURE_SQL,
        _REACTIVATE_ADMIN_PROCEDURE_SQL,
        "REVOKE ALL ON PROCEDURE feature.transition_admin_feature_state("
        "text, text, text, text, bigint, text, text, text) FROM PUBLIC",
        "REVOKE ALL ON PROCEDURE feature.reactivate_admin_feature_state("
        "text, bigint, text, text, bigint, text, text) FROM PUBLIC",
        "GRANT EXECUTE ON PROCEDURE feature.transition_admin_feature_state("
        "text, text, text, text, bigint, text, text, text) TO ktm_feature_runtime",
        "GRANT EXECUTE ON PROCEDURE feature.reactivate_admin_feature_state("
        "text, bigint, text, text, bigint, text, text) TO ktm_feature_runtime",
        # A trigger is attached by the table owner after the state-owner
        # function is installed.  This narrowly permits that DDL dependency;
        # runtime remains unable to invoke the guard directly.
        "GRANT EXECUTE ON FUNCTION feature.reject_user_feature_version_mutation() "
        "TO ktm_feature_schema_owner",
        "REVOKE ALL ON FUNCTION feature.reject_user_feature_version_mutation() "
        "FROM PUBLIC, ktm_feature_runtime",
    ):
        op.execute(statement)

    # Alembic's session user is the migrator login.  ``RESET ROLE`` would go
    # back to that login (which deliberately has no feature schema DDL), not
    # to the schema owner that entered this migration.
    op.execute("SET ROLE ktm_feature_schema_owner")
    for statement in (
        # CREATE OR REPLACE cannot remove the historic read columns.  There
        # are deliberately no consumers of this internal projection at C, so
        # replace it atomically within the migration transaction instead.
        "DROP VIEW feature.public_features RESTRICT",
        _PUBLIC_FEATURES_VIEW_SQL.replace("CREATE OR REPLACE VIEW", "CREATE VIEW"),
        "REVOKE ALL ON feature.public_features FROM PUBLIC",
        "GRANT SELECT ON feature.public_features TO ktm_feature_runtime",
        "CREATE UNIQUE INDEX uq_feature_versions_user_request_receipt "
        "ON feature.feature_versions (feature_id, request_id) "
        "WHERE origin = 'user_request' AND request_id IS NOT NULL",
        "CREATE TRIGGER trg_feature_versions_user_request_immutable "
        "BEFORE INSERT OR UPDATE OR DELETE ON feature.feature_versions "
        "FOR EACH ROW EXECUTE FUNCTION feature.reject_user_feature_version_mutation()",
        "GRANT SELECT ON feature.features, feature.feature_places, feature.feature_events, "
        "feature.feature_notices, feature.feature_routes, feature.feature_areas "
        "TO ktm_feature_state_procedure_owner",
        # Row-level FOR SHARE on a subtype requires UPDATE privilege in
        # PostgreSQL.  Limit it to the immutable identity column; the
        # SECURITY DEFINER routines only lock it and never issue subtype DML.
        "GRANT UPDATE (feature_id) ON feature.feature_places, feature.feature_events, "
        "feature.feature_notices, feature.feature_routes, feature.feature_areas "
        "TO ktm_feature_state_procedure_owner",
        "GRANT UPDATE (lifecycle_state, publication_state, quality_state, data_origin, "
        "data_version, updated_at) ON feature.features TO ktm_feature_state_procedure_owner",
        "GRANT SELECT, INSERT, UPDATE ON feature.feature_versions "
        "TO ktm_feature_state_procedure_owner",
        "REVOKE SELECT ON feature.features_detailed "
        "FROM ktm_feature_runtime, ktm_feature_state_procedure_owner",
        "REVOKE ALL ON feature.features_detailed FROM PUBLIC",
    ):
        op.execute(statement)

    op.execute("DROP VIEW feature.features_detailed RESTRICT")
    for statement in (
        "DROP INDEX IF EXISTS feature.idx_features_status_updated",
        "DROP INDEX IF EXISTS feature.idx_features_user_deleted",
        "ALTER TABLE feature.features DROP CONSTRAINT IF EXISTS ck_features_status",
        "ALTER TABLE feature.features DROP CONSTRAINT IF EXISTS ck_features_user_change_kind",
        "ALTER TABLE feature.features DROP CONSTRAINT IF EXISTS ck_features_user_change_status",
        "ALTER TABLE feature.features DROP COLUMN status",
        "ALTER TABLE feature.features DROP COLUMN deleted_at",
        "ALTER TABLE feature.features DROP COLUMN user_deleted_at",
        "ALTER TABLE feature.features DROP COLUMN user_deleted_by",
        "ALTER TABLE feature.features DROP COLUMN user_change_kind",
        "ALTER TABLE feature.features DROP COLUMN user_change_status",
        "ALTER TABLE feature.features DROP COLUMN user_change_request_id",
        "ALTER TABLE feature.features DROP COLUMN user_change_reason",
    ):
        op.execute(statement)


def downgrade() -> None:
    raise RuntimeError("0097 is final and forward-only; rebuild with provider ETL")
