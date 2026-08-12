"""T-VN-36B nullable geometry를 base/effective lineage에 보존한다.

Revision ID: 0102_tvn36_null_geometry
Revises: 0101_tvn36_patch_hardening

registry에서 ``core.coord``는 nullable geometry다. JSON ``null``을 input에서
누락으로 취급하면 provider가 좌표를 제거한 observation이 이전 effective 값에
남는다. 이 revision은 geometry base/override에도 JSON ``null``을 명시 값으로
저장하고, fixed assignment가 실제 typed column을 NULL로 materialize하게 한다.
"""

from __future__ import annotations

import hashlib
import importlib.util
from collections.abc import Sequence
from pathlib import Path
from types import ModuleType
from typing import Any, cast

from alembic import op

# DDL source는 byte-exact SQL 조각을 보존한다.
# ruff: noqa: E501

revision: str = "0102_tvn36_null_geometry"
down_revision: str | Sequence[str] | None = "0101_tvn36_patch_hardening"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_LINEAGE_SPINE_SHA256 = "9bb4a71a6d9b0e8718eee6e243d1518ad4696afb4496c3d32202509695e776e8"
_PROVIDER_PATCH_SHA256 = "60875bfded9f56c08aba607b7b404fff288ffd1d036a682af16a2f6d15535deb"
_OVERRIDE_COMMANDS_SHA256 = "355b42c734fcd77bc4f7c5ec9908906a08a2fa1added2ba74b8df5c413254f99"


def _load(name: str, expected_sha256: str) -> ModuleType:
    path = Path(__file__).with_name(name)
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected_sha256:
        raise RuntimeError(f"{name} immutable T-VN-36 input changed")
    spec = importlib.util.spec_from_file_location(f"_tvn36_{path.stem}", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_lineage = _load("0098_tvn36_override_lineage_spine.py", _LINEAGE_SPINE_SHA256)
_provider = _load("0099_tvn36_provider_field_patch.py", _PROVIDER_PATCH_SHA256)
_commands = _load("0100_tvn36_field_override_commands.py", _OVERRIDE_COMMANDS_SHA256)

_BASE_GEOMETRY_VALIDATION = """    IF v_registry.value_kind = 'geometry' THEN
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
    ELSIF"""
_BASE_GEOMETRY_OLD = """    IF v_registry.value_kind = 'geometry' THEN
        IF NEW.value_geometry IS NULL OR NEW.value_json IS NOT NULL
           OR x_extension.st_srid(NEW.value_geometry) <> 4326
           OR upper(x_extension.st_geometrytype(NEW.value_geometry))
              <> 'ST_' || v_registry.geometry_type THEN
            RAISE EXCEPTION 'base geometry does not match registry type'
                USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_base_field_value';
        END IF;
    ELSIF"""
_OVERRIDE_GEOMETRY_VALIDATION = """    IF v_registry.value_kind = 'geometry' THEN
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
    ELSIF"""
_OVERRIDE_GEOMETRY_OLD = """    IF v_registry.value_kind = 'geometry' THEN
        IF NEW.value_geometry IS NULL OR NEW.override_value IS NOT NULL
           OR x_extension.st_srid(NEW.value_geometry) <> 4326
           OR upper(x_extension.st_geometrytype(NEW.value_geometry))
              <> 'ST_' || v_registry.geometry_type THEN
            RAISE EXCEPTION 'override geometry does not match registry type'
                USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_override_value';
        END IF;
    ELSIF"""

_BASE_VALIDATOR_SQL = (
    cast(Any, _lineage._VALIDATE_BASE_VALUE_FUNCTION_SQL)
    .replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1)
    .replace(_BASE_GEOMETRY_OLD, _BASE_GEOMETRY_VALIDATION, 1)
    .replace(
        "       OR (v_registry.value_kind = 'text' AND jsonb_typeof(NEW.value_json) <> 'string')\n"
        "       OR (v_registry.value_kind = 'uuid' AND jsonb_typeof(NEW.value_json) <> 'string')\n"
        "       OR (v_registry.value_kind = 'date' AND jsonb_typeof(NEW.value_json) <> 'string')\n"
        "       OR (v_registry.value_kind = 'timestamptz' AND jsonb_typeof(NEW.value_json) <> 'string')\n"
        "       OR (v_registry.value_kind = 'integer' AND jsonb_typeof(NEW.value_json) <> 'number')\n"
        "       OR (v_registry.value_kind = 'numeric' AND jsonb_typeof(NEW.value_json) <> 'number')\n"
        "       OR (v_registry.value_kind = 'boolean' AND jsonb_typeof(NEW.value_json) <> 'boolean')\n"
        "       OR (v_registry.value_kind = 'json_object' AND jsonb_typeof(NEW.value_json) <> 'object')\n"
        "       OR (v_registry.value_kind IN ('json_array', 'text_array') AND jsonb_typeof(NEW.value_json) <> 'array') THEN",
        "       OR (NEW.value_json <> 'null'::jsonb AND (\n"
        "              (v_registry.value_kind = 'text' AND jsonb_typeof(NEW.value_json) <> 'string')\n"
        "           OR (v_registry.value_kind = 'uuid' AND jsonb_typeof(NEW.value_json) <> 'string')\n"
        "           OR (v_registry.value_kind = 'date' AND jsonb_typeof(NEW.value_json) <> 'string')\n"
        "           OR (v_registry.value_kind = 'timestamptz' AND jsonb_typeof(NEW.value_json) <> 'string')\n"
        "           OR (v_registry.value_kind = 'integer' AND jsonb_typeof(NEW.value_json) <> 'number')\n"
        "           OR (v_registry.value_kind = 'numeric' AND jsonb_typeof(NEW.value_json) <> 'number')\n"
        "           OR (v_registry.value_kind = 'boolean' AND jsonb_typeof(NEW.value_json) <> 'boolean')\n"
        "           OR (v_registry.value_kind = 'json_object' AND jsonb_typeof(NEW.value_json) <> 'object')\n"
        "           OR (v_registry.value_kind IN ('json_array', 'text_array') AND jsonb_typeof(NEW.value_json) <> 'array')\n"
        "       )) THEN",
        1,
    )
    .replace(
        "IF v_registry.value_kind = 'text_array' AND EXISTS (",
        "IF v_registry.value_kind = 'text_array' AND NEW.value_json <> 'null'::jsonb AND EXISTS (",
        1,
    )
)
_OVERRIDE_VALIDATOR_SQL = (
    cast(Any, _lineage._VALIDATE_OVERRIDE_VALUE_FUNCTION_SQL)
    .replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1)
    .replace(_OVERRIDE_GEOMETRY_OLD, _OVERRIDE_GEOMETRY_VALIDATION, 1)
    .replace(
        "       OR (v_registry.value_kind = 'text' AND jsonb_typeof(NEW.override_value) <> 'string')\n"
        "       OR (v_registry.value_kind = 'uuid' AND jsonb_typeof(NEW.override_value) <> 'string')\n"
        "       OR (v_registry.value_kind = 'date' AND jsonb_typeof(NEW.override_value) <> 'string')\n"
        "       OR (v_registry.value_kind = 'timestamptz' AND jsonb_typeof(NEW.override_value) <> 'string')\n"
        "       OR (v_registry.value_kind = 'integer' AND jsonb_typeof(NEW.override_value) <> 'number')\n"
        "       OR (v_registry.value_kind = 'numeric' AND jsonb_typeof(NEW.override_value) <> 'number')\n"
        "       OR (v_registry.value_kind = 'boolean' AND jsonb_typeof(NEW.override_value) <> 'boolean')\n"
        "       OR (v_registry.value_kind = 'json_object' AND jsonb_typeof(NEW.override_value) <> 'object')\n"
        "       OR (v_registry.value_kind IN ('json_array', 'text_array') AND jsonb_typeof(NEW.override_value) <> 'array') THEN",
        "       OR (NEW.override_value <> 'null'::jsonb AND (\n"
        "              (v_registry.value_kind = 'text' AND jsonb_typeof(NEW.override_value) <> 'string')\n"
        "           OR (v_registry.value_kind = 'uuid' AND jsonb_typeof(NEW.override_value) <> 'string')\n"
        "           OR (v_registry.value_kind = 'date' AND jsonb_typeof(NEW.override_value) <> 'string')\n"
        "           OR (v_registry.value_kind = 'timestamptz' AND jsonb_typeof(NEW.override_value) <> 'string')\n"
        "           OR (v_registry.value_kind = 'integer' AND jsonb_typeof(NEW.override_value) <> 'number')\n"
        "           OR (v_registry.value_kind = 'numeric' AND jsonb_typeof(NEW.override_value) <> 'number')\n"
        "           OR (v_registry.value_kind = 'boolean' AND jsonb_typeof(NEW.override_value) <> 'boolean')\n"
        "           OR (v_registry.value_kind = 'json_object' AND jsonb_typeof(NEW.override_value) <> 'object')\n"
        "           OR (v_registry.value_kind IN ('json_array', 'text_array') AND jsonb_typeof(NEW.override_value) <> 'array')\n"
        "       )) THEN",
        1,
    )
    .replace(
        "IF v_registry.value_kind = 'text_array' AND EXISTS (",
        "IF v_registry.value_kind = 'text_array' AND NEW.override_value <> 'null'::jsonb AND EXISTS (",
        1,
    )
)

_PROVIDER_GEOMETRY_OLD = """    FOR v_field_path, v_geometry_wkt IN SELECT key, value FROM jsonb_each_text(p_geometry_wkt) LOOP
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
    END LOOP;"""
_PROVIDER_GEOMETRY_NEW = """    FOR v_field_path, v_value IN SELECT key, value FROM jsonb_each(p_geometry_wkt) LOOP
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
                 ELSE x_extension.st_geomfromtext(v_value #>> '{}', 4326) END,
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
    END LOOP;"""
_PROVIDER_PATCH_SQL = (
    cast(Any, _provider._PROVIDER_PATCH_PROCEDURE_SQL)
    .replace("CREATE PROCEDURE", "CREATE OR REPLACE PROCEDURE", 1)
    .replace(
        "    v_base_revision bigint;\n",
        "    v_base_revision bigint;\n    v_preserved_notice_start jsonb;\n",
        1,
    )
    .replace(
        "    v_base_revision := v_feature.row_revision + 1;\n\n"
        "    FOR v_field_path, v_value IN SELECT key, value FROM jsonb_each(p_values) LOOP",
        "    v_base_revision := v_feature.row_revision + 1;\n"
        "    IF v_feature.kind = 'notice'\n"
        "       AND p_values -> 'notice.payload' ->> 'valid_start_origin' = 'first_probe'\n"
        "       AND p_values ? 'notice.valid_start_time' THEN\n"
        "        SELECT to_jsonb(valid_start_time) INTO v_preserved_notice_start\n"
        "        FROM feature.feature_notices\n"
        "        WHERE feature_id = p_feature_id AND valid_start_time IS NOT NULL\n"
        "        FOR SHARE;\n"
        "        IF FOUND THEN\n"
        "            p_values := jsonb_set(\n"
        "                p_values, ARRAY['notice.valid_start_time'], v_preserved_notice_start, true\n"
        "            );\n"
        "        END IF;\n"
        "    END IF;\n\n"
        "    FOR v_field_path, v_value IN SELECT key, value FROM jsonb_each(p_values) LOOP",
        1,
    )
    .replace(
        "            v_value, v_base_revision, clock_timestamp()",
        "            coalesce(v_value, 'null'::jsonb), v_base_revision, clock_timestamp()",
        1,
    )
    .replace(_PROVIDER_GEOMETRY_OLD, _PROVIDER_GEOMETRY_NEW, 1)
    .replace(
        "ELSE x_extension.st_geomfromtext(v_value #>> '{}', 4326) END",
        "ELSE CASE v_registry.geometry_type\n"
        "                      WHEN 'MULTILINESTRING' THEN x_extension.st_multi(x_extension.st_geomfromtext(v_value #>> '{}', 4326))\n"
        "                      WHEN 'MULTIPOLYGON' THEN x_extension.st_multi(x_extension.st_geomfromtext(v_value #>> '{}', 4326))\n"
        "                      ELSE x_extension.st_geomfromtext(v_value #>> '{}', 4326)\n"
        "                 END END",
        1,
    )
    .replace(
        "x_extension.st_geomfromtext(p_geometry_wkt ->> 'route.geom', 4326)",
        "x_extension.st_multi(x_extension.st_geomfromtext(p_geometry_wkt ->> 'route.geom', 4326))",
    )
    .replace(
        "x_extension.st_geomfromtext(p_geometry_wkt ->> 'area.geom', 4326)",
        "x_extension.st_multi(x_extension.st_geomfromtext(p_geometry_wkt ->> 'area.geom', 4326))",
    )
)

_AUTHOR_GEOMETRY_OLD = """    FOR v_field_path, v_geometry_wkt IN SELECT key, value FROM jsonb_each_text(p_geometry_wkt) LOOP
        SELECT * INTO v_registry FROM ops.feature_override_field_paths
        WHERE field_path = v_field_path;
        IF NOT FOUND OR NOT v_registry.operator_writable
           OR v_registry.value_kind <> 'geometry'
           OR (v_registry.feature_kind <> '*' AND v_registry.feature_kind <> v_feature.kind)
           OR coalesce(btrim(v_geometry_wkt), '') = '' THEN
            RAISE EXCEPTION 'operator cannot override geometry field path %', v_field_path
                USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_override_field_path';
        END IF;
        UPDATE ops.feature_overrides
        SET status = 'revoked', revoked_at = clock_timestamp(),
            revoked_by = btrim(p_principal), revoked_reason = btrim(p_reason_code)
        WHERE feature_id = p_feature_id AND field_path = v_field_path AND status = 'active';
        INSERT INTO ops.feature_overrides (
            feature_id, source_record_key, source_provider_dataset_id, source_entity_key,
            source_raw_payload_hash, field_path, source_value, value_geometry,
            prevent_provider_reactivation, status, reason, command_id, request_id,
            base_revision, created_by, created_at
        )
        SELECT p_feature_id, base.source_record_key, base.provider_dataset_id,
               base.source_entity_key, base.source_raw_payload_hash, v_field_path,
               NULL, x_extension.st_geomfromtext(v_geometry_wkt, 4326), false, 'active',
               btrim(p_reason_code), p_command_id, p_request_id,
               COALESCE(base.base_revision, v_feature.row_revision), btrim(p_principal),
               clock_timestamp()
        FROM (SELECT 1) AS singleton
        LEFT JOIN feature.feature_base_field_values AS base
          ON base.feature_id = p_feature_id AND base.field_path = v_field_path;
    END LOOP;"""
_AUTHOR_GEOMETRY_NEW = """    FOR v_field_path, v_value IN SELECT key, value FROM jsonb_each(p_geometry_wkt) LOOP
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
            prevent_provider_reactivation, status, reason, command_id, request_id,
            base_revision, created_by, created_at
        )
        SELECT p_feature_id, base.source_record_key, base.provider_dataset_id,
               base.source_entity_key, base.source_raw_payload_hash, v_field_path,
               NULL, CASE WHEN v_value = 'null'::jsonb THEN 'null'::jsonb ELSE NULL END,
               CASE WHEN v_value = 'null'::jsonb THEN NULL
                    ELSE x_extension.st_geomfromtext(v_value #>> '{}', 4326) END,
               false, 'active', btrim(p_reason_code), p_command_id, p_request_id,
               COALESCE(base.base_revision, v_feature.row_revision), btrim(p_principal),
               clock_timestamp()
        FROM (SELECT 1) AS singleton
        LEFT JOIN feature.feature_base_field_values AS base
          ON base.feature_id = p_feature_id AND base.field_path = v_field_path;
    END LOOP;"""
_AUTHOR_OVERRIDE_SQL = (
    cast(Any, _commands._AUTHOR_PROCEDURE_SQL)
    .replace("CREATE PROCEDURE", "CREATE OR REPLACE PROCEDURE", 1)
    .replace(
        "               base.value_json, v_value, false, 'active', btrim(p_reason_code),",
        "               base.value_json, coalesce(v_value, 'null'::jsonb), false, 'active', btrim(p_reason_code),",
        1,
    )
    .replace(_AUTHOR_GEOMETRY_OLD, _AUTHOR_GEOMETRY_NEW, 1)
    .replace(
        "ELSE x_extension.st_geomfromtext(v_value #>> '{}', 4326) END",
        "ELSE CASE v_registry.geometry_type\n"
        "                      WHEN 'MULTILINESTRING' THEN x_extension.st_multi(x_extension.st_geomfromtext(v_value #>> '{}', 4326))\n"
        "                      WHEN 'MULTIPOLYGON' THEN x_extension.st_multi(x_extension.st_geomfromtext(v_value #>> '{}', 4326))\n"
        "                      ELSE x_extension.st_geomfromtext(v_value #>> '{}', 4326)\n"
        "                 END END",
        1,
    )
    .replace(
        "x_extension.st_geomfromtext(p_geometry_wkt ->> 'route.geom', 4326)",
        "x_extension.st_multi(x_extension.st_geomfromtext(p_geometry_wkt ->> 'route.geom', 4326))",
    )
    .replace(
        "x_extension.st_geomfromtext(p_geometry_wkt ->> 'area.geom', 4326)",
        "x_extension.st_multi(x_extension.st_geomfromtext(p_geometry_wkt ->> 'area.geom', 4326))",
    )
)
_REVOKE_AGGREGATE_OLD = """    SELECT COALESCE(jsonb_object_agg(base.field_path, base.value_json)
                    FILTER (WHERE base.value_json IS NOT NULL), '{{}}'::jsonb),
           COALESCE(jsonb_object_agg(base.field_path, x_extension.st_astext(base.value_geometry))
                    FILTER (WHERE base.value_geometry IS NOT NULL), '{{}}'::jsonb)
    INTO v_values, v_geometry_wkt
    FROM feature.feature_base_field_values AS base
    WHERE base.feature_id = p_feature_id AND base.field_path = ANY(p_field_paths);"""
_REVOKE_AGGREGATE_NEW = """    SELECT COALESCE(jsonb_object_agg(base.field_path, base.value_json)
                    FILTER (WHERE registry.value_kind <> 'geometry'), '{{}}'::jsonb),
           COALESCE(jsonb_object_agg(
                    base.field_path,
                    CASE WHEN base.value_json = 'null'::jsonb THEN 'null'::jsonb
                         ELSE to_jsonb(x_extension.st_astext(base.value_geometry)) END
                ) FILTER (WHERE registry.value_kind = 'geometry'), '{{}}'::jsonb)
    INTO v_values, v_geometry_wkt
    FROM feature.feature_base_field_values AS base
    JOIN ops.feature_override_field_paths AS registry USING (field_path)
    WHERE base.feature_id = p_feature_id AND base.field_path = ANY(p_field_paths);"""
_REVOKE_OVERRIDE_SQL = (
    cast(Any, _commands._REVOKE_PROCEDURE_SQL)
    .replace("CREATE PROCEDURE", "CREATE OR REPLACE PROCEDURE", 1)
    .replace(_REVOKE_AGGREGATE_OLD, _REVOKE_AGGREGATE_NEW, 1)
    .replace(
        "x_extension.st_geomfromtext(v_geometry_wkt ->> 'route.geom', 4326)",
        "x_extension.st_multi(x_extension.st_geomfromtext(v_geometry_wkt ->> 'route.geom', 4326))",
    )
    .replace(
        "x_extension.st_geomfromtext(v_geometry_wkt ->> 'area.geom', 4326)",
        "x_extension.st_multi(x_extension.st_geomfromtext(v_geometry_wkt ->> 'area.geom', 4326))",
    )
)


def upgrade() -> None:
    op.execute("SET ROLE ktm_feature_state_procedure_owner")
    for statement in (
        _BASE_VALIDATOR_SQL,
        _OVERRIDE_VALIDATOR_SQL,
        _PROVIDER_PATCH_SQL,
        _AUTHOR_OVERRIDE_SQL,
        _REVOKE_OVERRIDE_SQL,
    ):
        op.execute(statement)
    op.execute("SET ROLE ktm_feature_schema_owner")


def downgrade() -> None:
    raise RuntimeError("0102 is forward-only; rebuild with the T-VN-36 release head")
