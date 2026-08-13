"""T-VN-36A legacy whole-row freeze의 fail-closed field replay.

Revision ID: 0103_tvn36_freeze_replay
Revises: 0102_tvn36_null_geometry

``data_origin = 'user_request'``는 이미 provider base와 user intent를 한 row에
섞어 둔 bridge다. 이 revision은 immutable applied request receipt를 순서대로
읽어 field path별 override history로 옮긴다. payload를 추측하거나 현재 effective
값으로 history를 재작성하지 않는다. mapping할 수 없는 행은 manifest에 남기고
transaction을 fail-close한다.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# ruff: noqa: E501

revision: str = "0103_tvn36_freeze_replay"
down_revision: str | Sequence[str] | None = "0102_tvn36_null_geometry"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# payload key는 과거 ``ops.feature_change_requests.payload``의 stable public
# spelling이다. target column/path는 registry에서 다시 검증하므로 이 목록을 SQL
# identifier로 실행하지 않는다.
_CORE_PAYLOAD_FIELDS: tuple[tuple[str, str], ...] = (
    ("core.name", "name"),
    ("core.category", "category"),
    ("core.coord_precision_digits", "coord_precision_digits"),
    ("core.address", "address"),
    ("core.legal_dong_code", "legal_dong_code"),
    ("core.road_name_code", "road_name_code"),
    ("core.road_address_management_no", "road_address_management_no"),
    ("core.admin_dong_code", "admin_dong_code"),
    ("core.sido_code", "sido_code"),
    ("core.sigungu_code", "sigungu_code"),
    ("core.urls", "urls"),
    ("core.marker_icon", "marker_icon"),
    ("core.marker_color", "marker_color"),
    ("core.parent_feature_id", "parent_feature_id"),
    ("core.sibling_group_id", "sibling_group_id"),
    ("core.raw_refs", "raw_refs"),
)
_SUBTYPE_PAYLOAD_FIELDS: tuple[tuple[str, str, str], ...] = (
    ("place", "place.place_kind", "place_kind"),
    ("place", "place.phones", "phones"),
    ("place", "place.biz_number", "biz_number"),
    ("place", "place.license_date", "license_date"),
    ("place", "place.business_hours", "business_hours"),
    ("place", "place.facility_info", "facility_info"),
    ("place", "place.reviews_link", "reviews_link"),
    ("place", "place.payload", "payload"),
    ("event", "event.event_kind", "event_kind"),
    ("event", "event.starts_on", "starts_on"),
    ("event", "event.ends_on", "ends_on"),
    ("event", "event.timezone", "timezone"),
    ("event", "event.opening_hours", "opening_hours"),
    ("event", "event.venue_name", "venue_name"),
    ("event", "event.tel", "tel"),
    ("event", "event.content_id", "content_id"),
    ("event", "event.content_type_id", "content_type_id"),
    ("event", "event.area_code", "area_code"),
    ("event", "event.sigungu_code", "sigungu_code"),
    ("event", "event.payload", "payload"),
    ("notice", "notice.notice_type", "notice_type"),
    ("notice", "notice.severity", "severity"),
    ("notice", "notice.valid_start_time", "valid_start_time"),
    ("notice", "notice.valid_end_time", "valid_end_time"),
    ("notice", "notice.source_agency", "source_agency"),
    ("notice", "notice.officer_name", "officer_name"),
    ("notice", "notice.payload", "payload"),
    ("route", "route.route_type", "route_type"),
    ("route", "route.geometry_source", "geometry_source"),
    ("route", "route.geometry_status", "geometry_status"),
    ("route", "route.total_distance_meters", "total_distance_meters"),
    ("route", "route.expected_duration_minutes", "expected_duration_minutes"),
    ("route", "route.difficulty", "difficulty"),
    ("route", "route.begin_name", "begin_name"),
    ("route", "route.begin_address", "begin_address"),
    ("route", "route.end_name", "end_name"),
    ("route", "route.payload", "payload"),
    ("area", "area.area_kind", "area_kind"),
    ("area", "area.boundary_source", "boundary_source"),
    ("area", "area.area_square_meters", "area_square_meters"),
    ("area", "area.regulation_scope", "regulation_scope"),
    ("area", "area.administrative_office", "administrative_office"),
    ("area", "area.description", "description"),
    ("area", "area.payload", "payload"),
)


def _values_sql() -> str:
    rows: list[str] = [
        "('core.coord', 'core', 'coord', NULL, true)",
        "('route.geom', 'route', 'geom', NULL, true)",
        "('area.geom', 'area', 'geom', NULL, true)",
    ]
    rows.extend(
        f"('{path}', 'core', '{key}', NULL, false)"
        for path, key in _CORE_PAYLOAD_FIELDS
    )
    rows.extend(
        f"('{path}', 'detail', '{key}', '{kind}', false)"
        for kind, path, key in _SUBTYPE_PAYLOAD_FIELDS
    )
    return ",\n                ".join(rows)


_FIELD_INPUT_VALUES = _values_sql()


_REPLAY_PROCEDURE_SQL = f"""
CREATE OR REPLACE PROCEDURE feature.replay_legacy_whole_row_freezes(
    IN p_apply boolean
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
DECLARE
    v_manifest_count integer;
BEGIN
    DELETE FROM ops.tvn36_legacy_freeze_preflight_manifest;

    -- A feature fence without exactly one applied immutable receipt is not
    -- reconstructable. The migration never guesses the author or changed path.
    INSERT INTO ops.tvn36_legacy_freeze_preflight_manifest (
        feature_id, request_id, violation_code, detail
    )
    SELECT core.feature_id, NULL, 'missing_applied_receipt',
           'data_origin=user_request has no applied immutable user receipt'
    FROM feature.features AS core
    WHERE core.data_origin = 'user_request'
      AND NOT EXISTS (
          SELECT 1
          FROM feature.feature_versions AS version
          JOIN ops.feature_change_requests AS request
            ON request.request_id = version.request_id
          WHERE version.feature_id = core.feature_id
            AND version.origin = 'user_request'
            AND request.feature_id = core.feature_id
            AND request.state = 'applied'
      );

    -- Older payloads are only accepted if every requested field has an exact
    -- registry mapping for this Feature kind. provider-owned fields cannot be
    -- silently promoted to operator intent.
    WITH receipts AS (
        SELECT version.feature_id, version.request_id, request.payload,
               core.kind, request.action
        FROM feature.feature_versions AS version
        JOIN feature.features AS core ON core.feature_id = version.feature_id
        JOIN ops.feature_change_requests AS request
          ON request.request_id = version.request_id
        WHERE core.data_origin = 'user_request'
          AND version.origin = 'user_request'
          AND request.state = 'applied'
          AND request.action <> 'delete'
    ), supplied AS (
        SELECT receipt.feature_id, receipt.request_id, receipt.kind,
               key AS payload_key, false AS is_detail
        FROM receipts AS receipt, jsonb_object_keys(receipt.payload) AS key
        WHERE key NOT IN (
            'feature_id', 'kind', 'detail', 'coord', 'lifecycle_state',
            'publication_state', 'quality_state', 'row_revision'
        )
        UNION ALL
        SELECT receipt.feature_id, receipt.request_id, receipt.kind,
               key AS payload_key, true AS is_detail
        FROM receipts AS receipt, jsonb_object_keys(
            coalesce(receipt.payload -> 'detail', '{{}}'::jsonb)
        ) AS key
    )
    INSERT INTO ops.tvn36_legacy_freeze_preflight_manifest (
        feature_id, request_id, violation_code, detail
    )
    SELECT supplied.feature_id, supplied.request_id, 'unmapped_payload_path',
           CASE WHEN supplied.is_detail
                THEN 'detail.' || supplied.payload_key
                ELSE supplied.payload_key END
    FROM supplied
    WHERE NOT EXISTS (
        SELECT 1
        FROM (VALUES
                {_FIELD_INPUT_VALUES}
        ) AS mapping(field_path, source_scope, payload_key, subtype_kind, is_geometry)
        JOIN ops.feature_override_field_paths AS registry
          ON registry.field_path = mapping.field_path
        WHERE mapping.payload_key = supplied.payload_key
          AND (mapping.subtype_kind IS NULL OR mapping.subtype_kind = supplied.kind)
          AND (mapping.source_scope = CASE WHEN supplied.is_detail THEN 'detail' ELSE 'core' END)
          AND registry.operator_writable
    );

    INSERT INTO ops.tvn36_legacy_freeze_preflight_manifest (
        feature_id, request_id, violation_code, detail
    )
    SELECT receipt.feature_id, request.request_id, 'invalid_coordinate_payload',
           'coord must be null or lon/lat object'
    FROM feature.feature_versions AS version
    JOIN feature.features AS receipt ON receipt.feature_id = version.feature_id
    JOIN ops.feature_change_requests AS request
      ON request.request_id = version.request_id
    WHERE receipt.data_origin = 'user_request'
      AND version.origin = 'user_request'
      AND request.state = 'applied'
      AND request.payload ? 'coord'
      AND NOT (
          request.payload -> 'coord' = 'null'::jsonb
          OR (
              jsonb_typeof(request.payload -> 'coord') = 'object'
              AND request.payload -> 'coord' ? 'lon'
              AND request.payload -> 'coord' ? 'lat'
              AND jsonb_typeof(request.payload -> 'coord' -> 'lon') = 'number'
              AND jsonb_typeof(request.payload -> 'coord' -> 'lat') = 'number'
          )
      );

    SELECT count(*)::integer INTO v_manifest_count
    FROM ops.tvn36_legacy_freeze_preflight_manifest;
    IF v_manifest_count <> 0 AND p_apply THEN
        RAISE EXCEPTION 'T-VN-36 legacy freeze replay has % unmappable row(s)', v_manifest_count
            USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn36_legacy_freeze_replay';
    END IF;
    IF NOT p_apply THEN
        RETURN;
    END IF;

    -- Preserve all immutable request attempts. Only the last value for a
    -- (feature,path) stays active; earlier intent remains superseded history.
    WITH receipts AS (
        SELECT version.feature_id, version.request_id, version.version,
               request.action, request.payload, request.requested_by,
               request.reason, core.kind, core.feature_uuid, core.row_revision,
               version.created_by
        FROM feature.feature_versions AS version
        JOIN feature.features AS core ON core.feature_id = version.feature_id
        JOIN ops.feature_change_requests AS request
          ON request.request_id = version.request_id
        WHERE core.data_origin = 'user_request'
          AND version.origin = 'user_request'
          AND request.state = 'applied'
          AND request.action <> 'delete'
    ), mapped AS (
        SELECT receipt.*, mapping.field_path, mapping.is_geometry,
               CASE WHEN mapping.source_scope = 'core'
                    THEN receipt.payload -> mapping.payload_key
                    ELSE receipt.payload -> 'detail' -> mapping.payload_key END AS override_value,
               row_number() OVER (
                   PARTITION BY receipt.feature_id, mapping.field_path
                   ORDER BY receipt.version DESC, receipt.request_id DESC
               ) AS path_rank
        FROM receipts AS receipt
        JOIN (VALUES
                {_FIELD_INPUT_VALUES}
        ) AS mapping(field_path, source_scope, payload_key, subtype_kind, is_geometry)
          ON (
              (mapping.source_scope = 'core' AND receipt.payload ? mapping.payload_key)
              OR (mapping.source_scope = 'detail'
                  AND receipt.payload ? 'detail'
                  AND receipt.payload -> 'detail' ? mapping.payload_key)
          )
        JOIN ops.feature_override_field_paths AS registry
          ON registry.field_path = mapping.field_path
         AND registry.operator_writable
         AND (registry.feature_kind = '*' OR registry.feature_kind = receipt.kind)
        WHERE (mapping.subtype_kind IS NULL OR mapping.subtype_kind = receipt.kind)
    ), scalar_rows AS (
        SELECT mapped.*
        FROM mapped
        WHERE NOT mapped.is_geometry
    ), geometry_rows AS (
        SELECT mapped.*,
               CASE mapped.field_path
                 WHEN 'core.coord' THEN CASE
                    WHEN mapped.override_value = 'null'::jsonb THEN NULL
                    ELSE x_extension.ST_SetSRID(x_extension.ST_MakePoint(
                        (mapped.override_value ->> 'lon')::double precision,
                        (mapped.override_value ->> 'lat')::double precision
                    ), 4326) END
                 WHEN 'route.geom' THEN x_extension.ST_Multi(
                    x_extension.ST_GeomFromText(mapped.override_value #>> '{{}}', 4326)
                 )
                 WHEN 'area.geom' THEN x_extension.ST_Multi(
                    x_extension.ST_GeomFromText(mapped.override_value #>> '{{}}', 4326)
                 )
               END AS geometry_value
        FROM mapped
        WHERE mapped.is_geometry
    )
    INSERT INTO ops.feature_overrides (
        feature_id, field_path, source_record_key, source_provider_dataset_id,
        source_entity_key, source_raw_payload_hash, source_value, override_value,
        value_geometry, prevent_provider_reactivation, status, reason, request_id,
        base_revision, created_by, created_at
    )
    SELECT row.feature_id, row.field_path, base.source_record_key,
           base.provider_dataset_id, base.source_entity_key,
           base.source_raw_payload_hash, base.value_json, row.override_value,
           NULL, false,
           CASE WHEN row.path_rank = 1 THEN 'active' ELSE 'superseded' END,
           coalesce(nullif(btrim(row.reason), ''), 'legacy_whole_row_freeze_replay'),
           row.request_id, coalesce(base.base_revision, row.row_revision),
           coalesce(nullif(btrim(row.created_by), ''),
                    nullif(btrim(row.requested_by), ''), 'legacy-backfill'),
           clock_timestamp()
    FROM scalar_rows AS row
    LEFT JOIN feature.feature_base_field_values AS base
      ON base.feature_id = row.feature_id AND base.field_path = row.field_path
    UNION ALL
    SELECT row.feature_id, row.field_path, base.source_record_key,
           base.provider_dataset_id, base.source_entity_key,
           base.source_raw_payload_hash, NULL,
           CASE WHEN row.geometry_value IS NULL THEN 'null'::jsonb ELSE NULL END,
           row.geometry_value, false,
           CASE WHEN row.path_rank = 1 THEN 'active' ELSE 'superseded' END,
           coalesce(nullif(btrim(row.reason), ''), 'legacy_whole_row_freeze_replay'),
           row.request_id, coalesce(base.base_revision, row.row_revision),
           coalesce(nullif(btrim(row.created_by), ''),
                    nullif(btrim(row.requested_by), ''), 'legacy-backfill'),
           clock_timestamp()
    FROM geometry_rows AS row
    LEFT JOIN feature.feature_base_field_values AS base
      ON base.feature_id = row.feature_id AND base.field_path = row.field_path
    ORDER BY 1, 2, 13;
END;
$$;
"""


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS ops.tvn36_legacy_freeze_preflight_manifest (
            feature_id text NOT NULL,
            request_id uuid,
            violation_code text NOT NULL,
            detail text NOT NULL,
            recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            PRIMARY KEY (feature_id, violation_code, detail)
        )
        """
    )
    op.execute(
        "GRANT SELECT, INSERT, DELETE ON ops.tvn36_legacy_freeze_preflight_manifest "
        "TO ktm_feature_state_procedure_owner"
    )
    op.execute("SET ROLE ktm_feature_state_procedure_owner")
    op.execute(_REPLAY_PROCEDURE_SQL)
    op.execute(
        "ALTER PROCEDURE feature.replay_legacy_whole_row_freezes(boolean) "
        "OWNER TO ktm_feature_state_procedure_owner"
    )
    op.execute(
        "REVOKE ALL ON PROCEDURE feature.replay_legacy_whole_row_freezes(boolean) "
        "FROM PUBLIC, ktm_feature_runtime"
    )
    # Preflight diagnostics must survive the intentionally failed Alembic
    # upgrade. An autocommit boundary preserves the manifest while the
    # revision itself remains unapplied and therefore fail-closed.
    with op.get_context().autocommit_block():
        op.execute("CALL feature.replay_legacy_whole_row_freezes(false)")
        invalid_count = int(
            op.get_bind()
            .exec_driver_sql(
                "SELECT count(*) FROM ops.tvn36_legacy_freeze_preflight_manifest"
            )
            .scalar_one()
        )
    if invalid_count:
        raise RuntimeError(
            "T-VN-36 legacy freeze preflight failed; "
            "inspect ops.tvn36_legacy_freeze_preflight_manifest"
        )
    op.execute("CALL feature.replay_legacy_whole_row_freezes(true)")
    op.execute("SET ROLE ktm_feature_schema_owner")


def downgrade() -> None:
    raise RuntimeError("0103 is forward-only; rebuild with the T-VN-36 release head")
