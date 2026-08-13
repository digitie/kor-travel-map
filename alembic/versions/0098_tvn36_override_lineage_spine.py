# ruff: noqa: E501
"""T-VN-36A field override registry and provider-base lineage spine.

Revision ID: 0098_tvn36_override_lineage
Revises: 0097_tvn34c_final_cutover

T-VN-34C가 남긴 ``data_origin``/``data_version``과 version receipt는 T-VN-36D
전까지의 input bridge다. 이 revision은 그 bridge를 다시 넓히지 않고, provider
base와 operator intent를 분리할 registry/ledger와 DB validation boundary를 만든다.
후속 B–D revision은 같은 Draft PR/release 안에서 writer와 destructive fence를
완성한다. 중간 head를 서비스 binary에 배포하지 않는다.
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import column, table

from alembic import op

revision: str = "0098_tvn36_override_lineage"
down_revision: str | Sequence[str] | None = "0098_admin_scope_indexes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# ``field_path``는 입력 식별자가 아니라 migration이 소유하는 allow-list다. B의
# materializer는 이 목록을 SQL 식별자로 interpolating하지 않고, 정적 CASE assignment로
# 해석한다. `sort_order`는 한 multi-field command의 deterministic apply order다.
_FIELD_PATH_ROWS: tuple[tuple[object, ...], ...] = (
    ("core.name", "*", "features", "name", "text", None, False, True, True, True, 10),
    ("core.category", "*", "features", "category", "text", None, False, True, True, True, 20),
    ("core.coord", "*", "features", "coord", "geometry", "POINT", True, True, True, True, 30),
    ("core.coord_precision_digits", "*", "features", "coord_precision_digits", "integer", None, True, True, True, True, 40),
    ("core.address", "*", "features", "address", "json_object", None, False, True, True, True, 50),
    ("core.legal_dong_code", "*", "features", "legal_dong_code", "text", None, True, True, True, True, 60),
    ("core.road_name_code", "*", "features", "road_name_code", "text", None, True, True, True, True, 70),
    ("core.road_address_management_no", "*", "features", "road_address_management_no", "text", None, True, True, True, True, 80),
    ("core.admin_dong_code", "*", "features", "admin_dong_code", "text", None, True, True, True, True, 90),
    ("core.sido_code", "*", "features", "sido_code", "text", None, True, True, True, True, 100),
    ("core.sigungu_code", "*", "features", "sigungu_code", "text", None, True, True, True, True, 110),
    ("core.urls", "*", "features", "urls", "json_object", None, False, True, True, True, 120),
    ("core.marker_icon", "*", "features", "marker_icon", "text", None, True, True, True, True, 130),
    ("core.marker_color", "*", "features", "marker_color", "text", None, True, True, True, True, 140),
    ("core.parent_feature_id", "*", "features", "parent_feature_id", "text", None, True, True, True, True, 150),
    ("core.sibling_group_id", "*", "features", "sibling_group_id", "uuid", None, True, True, True, True, 160),
    ("core.raw_refs", "*", "features", "raw_refs", "json_array", None, False, True, True, False, 170),
    ("place.place_kind", "place", "feature_places", "place_kind", "text", None, False, True, True, True, 210),
    ("place.phones", "place", "feature_places", "phones", "text_array", None, False, True, True, True, 220),
    ("place.biz_number", "place", "feature_places", "biz_number", "text", None, True, True, True, True, 230),
    ("place.license_date", "place", "feature_places", "license_date", "date", None, True, True, True, True, 240),
    ("place.business_hours", "place", "feature_places", "business_hours", "json_object", None, True, True, True, True, 250),
    ("place.facility_info", "place", "feature_places", "facility_info", "json_object", None, False, True, True, True, 260),
    ("place.reviews_link", "place", "feature_places", "reviews_link", "json_object", None, False, True, True, True, 270),
    ("place.payload", "place", "feature_places", "payload", "json_object", None, False, True, True, False, 280),
    ("event.event_kind", "event", "feature_events", "event_kind", "text", None, False, True, True, True, 310),
    ("event.starts_on", "event", "feature_events", "starts_on", "date", None, True, True, True, True, 320),
    ("event.ends_on", "event", "feature_events", "ends_on", "date", None, True, True, True, True, 330),
    ("event.timezone", "event", "feature_events", "timezone", "text", None, False, True, True, True, 340),
    ("event.opening_hours", "event", "feature_events", "opening_hours", "json_object", None, True, True, True, True, 350),
    ("event.venue_name", "event", "feature_events", "venue_name", "text", None, True, True, True, True, 360),
    ("event.tel", "event", "feature_events", "tel", "text", None, True, True, True, True, 370),
    ("event.content_id", "event", "feature_events", "content_id", "text", None, True, True, True, False, 380),
    ("event.content_type_id", "event", "feature_events", "content_type_id", "text", None, True, True, True, False, 390),
    ("event.area_code", "event", "feature_events", "area_code", "text", None, True, True, True, True, 400),
    ("event.sigungu_code", "event", "feature_events", "sigungu_code", "text", None, True, True, True, True, 410),
    ("event.payload", "event", "feature_events", "payload", "json_object", None, False, True, True, False, 420),
    ("notice.notice_type", "notice", "feature_notices", "notice_type", "text", None, False, True, True, True, 510),
    ("notice.severity", "notice", "feature_notices", "severity", "integer", None, True, True, True, True, 520),
    ("notice.valid_start_time", "notice", "feature_notices", "valid_start_time", "timestamptz", None, True, True, True, True, 530),
    ("notice.valid_end_time", "notice", "feature_notices", "valid_end_time", "timestamptz", None, True, True, True, True, 540),
    ("notice.source_agency", "notice", "feature_notices", "source_agency", "text", None, True, True, True, True, 550),
    ("notice.officer_name", "notice", "feature_notices", "officer_name", "text", None, True, True, True, True, 560),
    ("notice.payload", "notice", "feature_notices", "payload", "json_object", None, False, True, True, False, 570),
    ("route.geom", "route", "feature_routes", "geom", "geometry", "MULTILINESTRING", False, True, True, True, 610),
    ("route.route_type", "route", "feature_routes", "route_type", "text", None, False, True, True, True, 620),
    ("route.geometry_source", "route", "feature_routes", "geometry_source", "text", None, True, True, True, False, 630),
    ("route.geometry_status", "route", "feature_routes", "geometry_status", "text", None, True, True, True, True, 640),
    ("route.total_distance_meters", "route", "feature_routes", "total_distance_meters", "numeric", None, True, True, True, True, 650),
    ("route.expected_duration_minutes", "route", "feature_routes", "expected_duration_minutes", "integer", None, True, True, True, True, 660),
    ("route.difficulty", "route", "feature_routes", "difficulty", "text", None, True, True, True, True, 670),
    ("route.begin_name", "route", "feature_routes", "begin_name", "text", None, True, True, True, True, 680),
    ("route.begin_address", "route", "feature_routes", "begin_address", "text", None, True, True, True, True, 690),
    ("route.end_name", "route", "feature_routes", "end_name", "text", None, True, True, True, True, 700),
    ("route.end_address", "route", "feature_routes", "end_address", "text", None, True, True, True, True, 710),
    ("route.payload", "route", "feature_routes", "payload", "json_object", None, False, True, True, False, 720),
    ("area.geom", "area", "feature_areas", "geom", "geometry", "MULTIPOLYGON", False, True, True, True, 810),
    ("area.area_kind", "area", "feature_areas", "area_kind", "text", None, False, True, True, True, 820),
    ("area.boundary_source", "area", "feature_areas", "boundary_source", "text", None, True, True, True, False, 830),
    ("area.area_square_meters", "area", "feature_areas", "area_square_meters", "numeric", None, True, True, True, True, 840),
    ("area.regulation_scope", "area", "feature_areas", "regulation_scope", "text", None, True, True, True, True, 850),
    ("area.administrative_office", "area", "feature_areas", "administrative_office", "text", None, True, True, True, True, 860),
    ("area.description", "area", "feature_areas", "description", "text", None, True, True, True, True, 870),
    ("area.payload", "area", "feature_areas", "payload", "json_object", None, False, True, True, False, 880),
)


_VALIDATE_BASE_VALUE_FUNCTION_SQL = r"""
CREATE FUNCTION feature.validate_feature_base_field_value()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
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
        IF NEW.value_geometry IS NULL OR NEW.value_json IS NOT NULL
           OR x_extension.st_srid(NEW.value_geometry) <> 4326
           OR upper(x_extension.st_geometrytype(NEW.value_geometry))
              <> 'ST_' || v_registry.geometry_type THEN
            RAISE EXCEPTION 'base geometry does not match registry type'
                USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_base_field_value';
        END IF;
    ELSIF NEW.value_geometry IS NOT NULL
       OR NEW.value_json IS NULL
       OR (NOT v_registry.allows_null AND NEW.value_json = 'null'::jsonb)
       OR (v_registry.value_kind = 'text' AND jsonb_typeof(NEW.value_json) <> 'string')
       OR (v_registry.value_kind = 'uuid' AND jsonb_typeof(NEW.value_json) <> 'string')
       OR (v_registry.value_kind = 'date' AND jsonb_typeof(NEW.value_json) <> 'string')
       OR (v_registry.value_kind = 'timestamptz' AND jsonb_typeof(NEW.value_json) <> 'string')
       OR (v_registry.value_kind = 'integer' AND jsonb_typeof(NEW.value_json) <> 'number')
       OR (v_registry.value_kind = 'numeric' AND jsonb_typeof(NEW.value_json) <> 'number')
       OR (v_registry.value_kind = 'boolean' AND jsonb_typeof(NEW.value_json) <> 'boolean')
       OR (v_registry.value_kind = 'json_object' AND jsonb_typeof(NEW.value_json) <> 'object')
       OR (v_registry.value_kind IN ('json_array', 'text_array') AND jsonb_typeof(NEW.value_json) <> 'array') THEN
        RAISE EXCEPTION 'base JSON value does not match registry type'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_base_field_value';
    END IF;
    IF v_registry.value_kind = 'text_array' AND EXISTS (
        SELECT 1 FROM jsonb_array_elements(NEW.value_json) AS element
        WHERE jsonb_typeof(element) <> 'string'
    ) THEN
        RAISE EXCEPTION 'base text array contains a non-string value'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_base_field_value';
    END IF;
    RETURN NEW;
END;
$$;
"""


_VALIDATE_OVERRIDE_VALUE_FUNCTION_SQL = r"""
CREATE FUNCTION feature.validate_feature_override_value()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
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
        IF NEW.value_geometry IS NULL OR NEW.override_value IS NOT NULL
           OR x_extension.st_srid(NEW.value_geometry) <> 4326
           OR upper(x_extension.st_geometrytype(NEW.value_geometry))
              <> 'ST_' || v_registry.geometry_type THEN
            RAISE EXCEPTION 'override geometry does not match registry type'
                USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_override_value';
        END IF;
    ELSIF NEW.value_geometry IS NOT NULL
       OR NEW.override_value IS NULL
       OR (NOT v_registry.allows_null AND NEW.override_value = 'null'::jsonb)
       OR (v_registry.value_kind = 'text' AND jsonb_typeof(NEW.override_value) <> 'string')
       OR (v_registry.value_kind = 'uuid' AND jsonb_typeof(NEW.override_value) <> 'string')
       OR (v_registry.value_kind = 'date' AND jsonb_typeof(NEW.override_value) <> 'string')
       OR (v_registry.value_kind = 'timestamptz' AND jsonb_typeof(NEW.override_value) <> 'string')
       OR (v_registry.value_kind = 'integer' AND jsonb_typeof(NEW.override_value) <> 'number')
       OR (v_registry.value_kind = 'numeric' AND jsonb_typeof(NEW.override_value) <> 'number')
       OR (v_registry.value_kind = 'boolean' AND jsonb_typeof(NEW.override_value) <> 'boolean')
       OR (v_registry.value_kind = 'json_object' AND jsonb_typeof(NEW.override_value) <> 'object')
       OR (v_registry.value_kind IN ('json_array', 'text_array') AND jsonb_typeof(NEW.override_value) <> 'array') THEN
        RAISE EXCEPTION 'override JSON value does not match registry type'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_override_value';
    END IF;
    IF v_registry.value_kind = 'text_array' AND EXISTS (
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
"""


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE ops.feature_override_field_paths (
            field_path text PRIMARY KEY,
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
            CONSTRAINT ck_feature_override_field_paths_canonical
                CHECK (field_path <> '' AND field_path = btrim(field_path)),
            CONSTRAINT ck_feature_override_field_paths_kind
                CHECK (feature_kind IN ('*','place','event','notice','route','area')),
            CONSTRAINT ck_feature_override_field_paths_relation
                CHECK (target_relation IN ('features','feature_places','feature_events',
                                           'feature_notices','feature_routes','feature_areas')),
            CONSTRAINT ck_feature_override_field_paths_value_kind
                CHECK (value_kind IN ('text','integer','numeric','boolean','json_object',
                                     'json_array','text_array','date','timestamptz','uuid','geometry')),
            CONSTRAINT ck_feature_override_field_paths_geometry_type
                CHECK (geometry_type IS NULL OR geometry_type IN ('POINT','MULTILINESTRING','MULTIPOLYGON')),
            CONSTRAINT ck_feature_override_field_paths_geometry_kind
                CHECK ((value_kind = 'geometry' AND geometry_type IS NOT NULL)
                    OR (value_kind <> 'geometry' AND geometry_type IS NULL)),
            CONSTRAINT uq_feature_override_field_paths_target
                UNIQUE (feature_kind, target_relation, target_column)
        )
        """
    )
    op.bulk_insert(
        table(
            "feature_override_field_paths",
            *[
                column(name)
                for name in (
                    "field_path", "feature_kind", "target_relation", "target_column",
                    "value_kind", "geometry_type", "allows_null", "requires_source",
                    "provider_writable", "operator_writable", "sort_order",
                )
            ],
            schema="ops",
        ),
        [
            dict(zip(("field_path", "feature_kind", "target_relation", "target_column", "value_kind", "geometry_type", "allows_null", "requires_source", "provider_writable", "operator_writable", "sort_order"), row, strict=True))
            for row in _FIELD_PATH_ROWS
        ],
    )
    op.execute(
        """
        CREATE TABLE feature.feature_base_field_values (
            feature_id text NOT NULL,
            field_path text NOT NULL,
            feature_uuid uuid NOT NULL,
            provider_dataset_id bigint NOT NULL,
            source_entity_key text NOT NULL,
            source_record_key text NOT NULL,
            source_raw_payload_hash text NOT NULL,
            value_json jsonb,
            value_geometry x_extension.geometry(GEOMETRY, 4326),
            base_revision bigint NOT NULL,
            observed_at timestamptz NOT NULL,
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT pk_feature_base_field_values PRIMARY KEY (feature_id, field_path),
            CONSTRAINT fk_feature_base_field_values_feature_identity
                FOREIGN KEY (feature_id, feature_uuid)
                REFERENCES feature.features (feature_id, feature_uuid) ON DELETE CASCADE,
            CONSTRAINT fk_feature_base_field_values_field_path
                FOREIGN KEY (field_path) REFERENCES ops.feature_override_field_paths (field_path)
                ON DELETE RESTRICT,
            CONSTRAINT fk_feature_base_field_values_dataset
                FOREIGN KEY (provider_dataset_id)
                REFERENCES provider_sync.provider_datasets (provider_dataset_id) ON DELETE RESTRICT,
            CONSTRAINT fk_feature_base_field_values_entity
                FOREIGN KEY (source_entity_key)
                REFERENCES provider_sync.source_entities (source_entity_key) ON DELETE RESTRICT,
            CONSTRAINT fk_feature_base_field_values_record
                FOREIGN KEY (source_record_key)
                REFERENCES provider_sync.source_records (source_record_key) ON DELETE RESTRICT,
            CONSTRAINT ck_feature_base_field_values_revision CHECK (base_revision >= 1),
            CONSTRAINT ck_feature_base_field_values_single_value
                CHECK ((value_json IS NULL) <> (value_geometry IS NULL)),
            CONSTRAINT ck_feature_base_field_values_source_hash
                CHECK (btrim(source_raw_payload_hash) <> '')
        )
        """
    )
    op.execute(
        """
        CREATE INDEX idx_feature_base_field_values_source
            ON feature.feature_base_field_values (
                provider_dataset_id, source_entity_key, source_record_key
            )
        """
    )
    for statement in (
        "ALTER TABLE ops.feature_overrides ADD COLUMN source_provider_dataset_id bigint",
        "ALTER TABLE ops.feature_overrides ADD COLUMN source_entity_key text",
        "ALTER TABLE ops.feature_overrides ADD COLUMN source_raw_payload_hash text",
        "ALTER TABLE ops.feature_overrides ADD COLUMN value_geometry x_extension.geometry(GEOMETRY, 4326)",
        "ALTER TABLE ops.feature_overrides ADD COLUMN command_id bigint",
        "ALTER TABLE ops.feature_overrides ADD COLUMN request_id uuid",
        "ALTER TABLE ops.feature_overrides ADD COLUMN base_revision bigint",
        "ALTER TABLE ops.feature_overrides ADD COLUMN revoked_at timestamptz",
        "ALTER TABLE ops.feature_overrides ADD COLUMN revoked_by text",
        "ALTER TABLE ops.feature_overrides ADD COLUMN revoked_reason text",
        # The original 0010 table was created through Alembic metadata with
        # the repository naming convention, so a fresh DB owns the physical
        # name ``ck_feature_overrides_ck_overrides_status``.  Keep the bare
        # fallback for databases made before that convention was applied.
        "ALTER TABLE ops.feature_overrides DROP CONSTRAINT IF EXISTS ck_overrides_status",
        "ALTER TABLE ops.feature_overrides DROP CONSTRAINT IF EXISTS ck_feature_overrides_ck_overrides_status",
        "ALTER TABLE ops.feature_overrides ADD CONSTRAINT ck_feature_overrides_ck_overrides_status CHECK (status IN ('active','inactive','superseded','revoked'))",
        "ALTER TABLE ops.feature_overrides ADD CONSTRAINT ck_feature_overrides_value_storage CHECK (value_geometry IS NULL OR override_value IS NULL)",
        "ALTER TABLE ops.feature_overrides ADD CONSTRAINT fk_feature_overrides_source_dataset FOREIGN KEY (source_provider_dataset_id) REFERENCES provider_sync.provider_datasets (provider_dataset_id) ON DELETE SET NULL",
        "ALTER TABLE ops.feature_overrides ADD CONSTRAINT fk_feature_overrides_source_entity FOREIGN KEY (source_entity_key) REFERENCES provider_sync.source_entities (source_entity_key) ON DELETE SET NULL",
        "ALTER TABLE ops.feature_overrides ADD CONSTRAINT fk_feature_overrides_command FOREIGN KEY (command_id) REFERENCES ops.domain_commands (command_id) ON DELETE RESTRICT",
        "ALTER TABLE ops.feature_overrides ADD CONSTRAINT fk_feature_overrides_request FOREIGN KEY (request_id) REFERENCES ops.feature_change_requests (request_id) ON DELETE RESTRICT",
        "ALTER TABLE ops.feature_overrides ADD CONSTRAINT ck_feature_overrides_base_revision CHECK (base_revision IS NULL OR base_revision >= 1)",
        "ALTER TABLE ops.feature_overrides ADD CONSTRAINT ck_feature_overrides_revocation_pair CHECK ((status <> 'revoked') OR (revoked_at IS NOT NULL AND btrim(revoked_by) <> ''))",
    ):
        op.execute(statement)

    op.execute("SET ROLE ktm_feature_state_procedure_owner")
    for statement in (
        _VALIDATE_BASE_VALUE_FUNCTION_SQL,
        _VALIDATE_OVERRIDE_VALUE_FUNCTION_SQL,
        "REVOKE ALL ON FUNCTION feature.validate_feature_base_field_value() FROM PUBLIC, ktm_feature_runtime",
        "REVOKE ALL ON FUNCTION feature.validate_feature_override_value() FROM PUBLIC, ktm_feature_runtime",
        "GRANT EXECUTE ON FUNCTION feature.validate_feature_base_field_value() TO ktm_feature_schema_owner",
        "GRANT EXECUTE ON FUNCTION feature.validate_feature_override_value() TO ktm_feature_schema_owner",
    ):
        op.execute(statement)
    op.execute("SET ROLE ktm_feature_schema_owner")
    for statement in (
        "CREATE TRIGGER trg_feature_base_field_values_validate BEFORE INSERT OR UPDATE ON feature.feature_base_field_values FOR EACH ROW EXECUTE FUNCTION feature.validate_feature_base_field_value()",
        "CREATE TRIGGER trg_feature_overrides_validate BEFORE INSERT OR UPDATE ON ops.feature_overrides FOR EACH ROW EXECUTE FUNCTION feature.validate_feature_override_value()",
        "GRANT SELECT, INSERT, UPDATE ON feature.feature_base_field_values TO ktm_feature_state_procedure_owner",
        "GRANT SELECT ON ops.feature_override_field_paths TO ktm_feature_state_procedure_owner",
        "GRANT SELECT, INSERT, UPDATE (source_provider_dataset_id, source_entity_key, source_record_key, source_raw_payload_hash, override_value, value_geometry, prevent_provider_reactivation, status, reason, command_id, request_id, base_revision, created_by, created_at, revoked_at, revoked_by, revoked_reason) ON ops.feature_overrides TO ktm_feature_state_procedure_owner",
        "REVOKE ALL ON feature.feature_base_field_values FROM PUBLIC, ktm_feature_runtime",
        "REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON ops.feature_override_field_paths, ops.feature_overrides FROM ktm_feature_runtime",
        "GRANT SELECT ON ops.feature_override_field_paths, ops.feature_overrides TO ktm_feature_runtime",
    ):
        op.execute(statement)


def downgrade() -> None:
    raise RuntimeError("0098 is forward-only; rebuild with the T-VN-36 release head")
