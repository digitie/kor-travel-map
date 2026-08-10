"""T-VN-36B operator field override author/revoke commands.

Revision ID: 0100_tvn36_override_cmds
Revises: 0099_tvn36_provider_field_patch

Operator/user field override는 ADR-074 domain command claim, Feature revision, typed
registry, 그리고 static effective assignment를 하나의 transaction에 결박한다.
``0099``의 immutable static assignment만 재사용하며 registry row를 SQL 식별자로
실행하지 않는다.
"""

from __future__ import annotations

import hashlib
import importlib.util
import re
from collections.abc import Sequence
from pathlib import Path
from types import ModuleType
from typing import Any, cast

from alembic import op

# This migration deliberately keeps long static SQL expressions readable.
# ruff: noqa: E501

revision: str = "0100_tvn36_override_cmds"
down_revision: str | Sequence[str] | None = "0099_tvn36_provider_field_patch"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PROVIDER_PATCH_SHA256 = "60875bfded9f56c08aba607b7b404fff288ffd1d036a682af16a2f6d15535deb"


def _load_immutable_provider_assignments() -> ModuleType:
    """0099가 고정한 column allow-list를 runtime registry와 분리해 재사용한다.

    0100은 0099의 후속 revision이므로 해당 source는 migration chain의 immutable
    입력이다. byte hash가 다르면 partial/squashed source에서 unsafe한 DDL을 만들지
    않고 migration을 fail-closed한다.
    """

    path = Path(__file__).with_name("0099_tvn36_provider_field_patch.py")
    source = path.read_bytes()
    if hashlib.sha256(source).hexdigest() != _PROVIDER_PATCH_SHA256:
        raise RuntimeError("0099 static provider field assignment source changed")
    spec = importlib.util.spec_from_file_location("_tvn36_provider_patch", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load immutable 0099 provider field assignments")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_provider_patch = _load_immutable_provider_assignments()
_render_update = cast(Any, _provider_patch._render_update)


def _operator_assignment(provider_assignment: str, *, values_name: str = "p_values", geometry_name: str = "p_geometry_wkt") -> str:
    """Provider의 active-override guard를 제거한 static operator assignment다."""

    without_guard = re.sub(
        r"\n             AND NOT feature\.has_active_feature_override\([^\n]+\)",
        "",
        provider_assignment,
    )
    return (
        without_guard.replace("p_values", values_name)
        .replace("p_geometry_wkt", geometry_name)
    )


_CORE_ASSIGNMENTS = tuple(
    _operator_assignment(value)
    for value in cast(tuple[str, ...], _provider_patch._CORE_ASSIGNMENTS)
)
_PLACE_ASSIGNMENTS = tuple(
    _operator_assignment(value)
    for value in cast(tuple[str, ...], _provider_patch._PLACE_ASSIGNMENTS)
)
_EVENT_ASSIGNMENTS = tuple(
    _operator_assignment(value)
    for value in cast(tuple[str, ...], _provider_patch._EVENT_ASSIGNMENTS)
)
_NOTICE_ASSIGNMENTS = tuple(
    _operator_assignment(value)
    for value in cast(tuple[str, ...], _provider_patch._NOTICE_ASSIGNMENTS)
)
_ROUTE_ASSIGNMENTS = tuple(
    _operator_assignment(value)
    for value in cast(tuple[str, ...], _provider_patch._ROUTE_ASSIGNMENTS)
)
_AREA_ASSIGNMENTS = tuple(
    _operator_assignment(value)
    for value in cast(tuple[str, ...], _provider_patch._AREA_ASSIGNMENTS)
)

_REVOKE_CORE_ASSIGNMENTS = tuple(
    _operator_assignment(value, values_name="v_values", geometry_name="v_geometry_wkt")
    for value in cast(tuple[str, ...], _provider_patch._CORE_ASSIGNMENTS)
)
_REVOKE_PLACE_ASSIGNMENTS = tuple(
    _operator_assignment(value, values_name="v_values", geometry_name="v_geometry_wkt")
    for value in cast(tuple[str, ...], _provider_patch._PLACE_ASSIGNMENTS)
)
_REVOKE_EVENT_ASSIGNMENTS = tuple(
    _operator_assignment(value, values_name="v_values", geometry_name="v_geometry_wkt")
    for value in cast(tuple[str, ...], _provider_patch._EVENT_ASSIGNMENTS)
)
_REVOKE_NOTICE_ASSIGNMENTS = tuple(
    _operator_assignment(value, values_name="v_values", geometry_name="v_geometry_wkt")
    for value in cast(tuple[str, ...], _provider_patch._NOTICE_ASSIGNMENTS)
)
_REVOKE_ROUTE_ASSIGNMENTS = tuple(
    _operator_assignment(value, values_name="v_values", geometry_name="v_geometry_wkt")
    for value in cast(tuple[str, ...], _provider_patch._ROUTE_ASSIGNMENTS)
)
_REVOKE_AREA_ASSIGNMENTS = tuple(
    _operator_assignment(value, values_name="v_values", geometry_name="v_geometry_wkt")
    for value in cast(tuple[str, ...], _provider_patch._AREA_ASSIGNMENTS)
)

_CORE_SQL = ",\n        ".join(_CORE_ASSIGNMENTS)
_REVOKE_CORE_SQL = ",\n        ".join(_REVOKE_CORE_ASSIGNMENTS)


def _subtype_apply_blocks(
    *,
    values_name: str,
    geometry_name: str,
    assignments: tuple[tuple[str, str, tuple[str, ...]], ...],
    source_field_predicate: str,
) -> str:
    """Feature kind별 static subtype assignment와 missing-subtype fence를 만든다."""

    blocks: list[str] = []
    for index, (kind, relation, relation_assignments) in enumerate(assignments):
        condition = (
            f"EXISTS (SELECT 1 FROM jsonb_object_keys({values_name}) AS supplied_path(field_path) "
            f"WHERE supplied_path.field_path LIKE '{kind}.%')"
        )
        if kind in {"route", "area"}:
            condition = (
                f"({condition} OR EXISTS (SELECT 1 FROM jsonb_object_keys({geometry_name}) "
                f"AS supplied_path(field_path) WHERE supplied_path.field_path LIKE '{kind}.%'))"
            )
        keyword = "IF" if index == 0 else "ELSIF"
        blocks.append(
            f"""    {keyword} v_feature.kind = '{kind}' AND {condition} THEN
        PERFORM 1 FROM feature.{relation} WHERE feature_id = p_feature_id FOR UPDATE;
        IF NOT FOUND THEN
            RAISE EXCEPTION '{kind} subtype is missing'
                USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_override_subtype';
        END IF;
        {_render_update(relation, kind, relation_assignments)}"""
        )
    blocks.append("    END IF;")
    return "\n".join(blocks)


_AUTHOR_SUBTYPE_BLOCKS = _subtype_apply_blocks(
    values_name="p_values",
    geometry_name="p_geometry_wkt",
    assignments=(
        ("place", "feature_places", _PLACE_ASSIGNMENTS),
        ("event", "feature_events", _EVENT_ASSIGNMENTS),
        ("notice", "feature_notices", _NOTICE_ASSIGNMENTS),
        ("route", "feature_routes", _ROUTE_ASSIGNMENTS),
        ("area", "feature_areas", _AREA_ASSIGNMENTS),
    ),
    source_field_predicate="",
)
_REVOKE_SUBTYPE_BLOCKS = _subtype_apply_blocks(
    values_name="v_values",
    geometry_name="v_geometry_wkt",
    assignments=(
        ("place", "feature_places", _REVOKE_PLACE_ASSIGNMENTS),
        ("event", "feature_events", _REVOKE_EVENT_ASSIGNMENTS),
        ("notice", "feature_notices", _REVOKE_NOTICE_ASSIGNMENTS),
        ("route", "feature_routes", _REVOKE_ROUTE_ASSIGNMENTS),
        ("area", "feature_areas", _REVOKE_AREA_ASSIGNMENTS),
    ),
    source_field_predicate="",
)


_AUTHOR_PROCEDURE_SQL = f"""
CREATE PROCEDURE feature.author_feature_field_overrides(
    IN p_feature_id text,
    IN p_expected_row_revision bigint,
    IN p_principal text,
    IN p_reason_code text,
    IN p_command_id bigint,
    IN p_request_id uuid,
    IN p_values jsonb,
    IN p_geometry_wkt jsonb,
    OUT o_feature_id text,
    OUT o_row_revision bigint,
    OUT o_command_id bigint,
    OUT o_applied_field_count integer
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
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
    IF NOT FOUND OR v_operation NOT IN ('admin.feature.override.author', 'user.feature.override.author') THEN
        RAISE EXCEPTION 'field override author requires an open matching domain command'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_override_command';
    END IF;
    IF (v_operation LIKE 'user.%') <> (p_request_id IS NOT NULL) THEN
        RAISE EXCEPTION 'user override author requires exactly one request receipt'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_override_request';
    END IF;
    IF p_request_id IS NOT NULL AND NOT EXISTS (
        SELECT 1
        FROM ops.feature_change_requests AS request
        WHERE request.request_id = p_request_id
          AND request.feature_id = p_feature_id
          AND request.state = 'applied'
        FOR SHARE
    ) THEN
        RAISE EXCEPTION 'override request receipt is not an applied request for Feature'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_override_request';
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
            prevent_provider_reactivation, status, reason, command_id, request_id,
            base_revision, created_by, created_at
        )
        SELECT p_feature_id, base.source_record_key, base.provider_dataset_id,
               base.source_entity_key, base.source_raw_payload_hash, v_field_path,
               base.value_json, v_value, false, 'active', btrim(p_reason_code),
               p_command_id, p_request_id, COALESCE(base.base_revision, v_feature.row_revision),
               btrim(p_principal), clock_timestamp()
        FROM (SELECT 1) AS singleton
        LEFT JOIN feature.feature_base_field_values AS base
          ON base.feature_id = p_feature_id AND base.field_path = v_field_path;
    END LOOP;
    FOR v_field_path, v_geometry_wkt IN SELECT key, value FROM jsonb_each_text(p_geometry_wkt) LOOP
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
    END LOOP;

    UPDATE feature.features AS core
    SET {_CORE_SQL},
        updated_at = clock_timestamp()
    WHERE core.feature_id = p_feature_id
    RETURNING core.feature_id, core.row_revision INTO o_feature_id, o_row_revision;
{_AUTHOR_SUBTYPE_BLOCKS}
    o_command_id := p_command_id;
END;
$$;
"""


_REVOKE_PROCEDURE_SQL = f"""
CREATE PROCEDURE feature.revoke_feature_field_overrides(
    IN p_feature_id text,
    IN p_expected_row_revision bigint,
    IN p_principal text,
    IN p_reason_code text,
    IN p_command_id bigint,
    IN p_request_id uuid,
    IN p_field_paths text[],
    OUT o_feature_id text,
    OUT o_row_revision bigint,
    OUT o_command_id bigint,
    OUT o_applied_field_count integer
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
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
    IF NOT FOUND OR v_operation NOT IN ('admin.feature.override.revoke', 'user.feature.override.revoke') THEN
        RAISE EXCEPTION 'field override revoke requires an open matching domain command'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_override_command';
    END IF;
    IF (v_operation LIKE 'user.%') <> (p_request_id IS NOT NULL) THEN
        RAISE EXCEPTION 'user override revoke requires exactly one request receipt'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_override_request';
    END IF;
    IF p_request_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM ops.feature_change_requests AS request
        WHERE request.request_id = p_request_id
          AND request.feature_id = p_feature_id
          AND request.state = 'applied'
        FOR SHARE
    ) THEN
        RAISE EXCEPTION 'override request receipt is not an applied request for Feature'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_override_request';
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
                    FILTER (WHERE base.value_json IS NOT NULL), '{{}}'::jsonb),
           COALESCE(jsonb_object_agg(base.field_path, x_extension.st_astext(base.value_geometry))
                    FILTER (WHERE base.value_geometry IS NOT NULL), '{{}}'::jsonb)
    INTO v_values, v_geometry_wkt
    FROM feature.feature_base_field_values AS base
    WHERE base.feature_id = p_feature_id AND base.field_path = ANY(p_field_paths);

    UPDATE ops.feature_overrides
    SET status = 'revoked', revoked_at = clock_timestamp(),
        revoked_by = btrim(p_principal), revoked_reason = btrim(p_reason_code)
    WHERE feature_id = p_feature_id AND field_path = ANY(p_field_paths) AND status = 'active';

    UPDATE feature.features AS core
    SET {_REVOKE_CORE_SQL},
        updated_at = clock_timestamp()
    WHERE core.feature_id = p_feature_id
    RETURNING core.feature_id, core.row_revision INTO o_feature_id, o_row_revision;
{_REVOKE_SUBTYPE_BLOCKS}
    o_command_id := p_command_id;
END;
$$;
"""


def upgrade() -> None:
    op.execute("SET ROLE ktm_feature_state_procedure_owner")
    for statement in (
        _AUTHOR_PROCEDURE_SQL,
        _REVOKE_PROCEDURE_SQL,
        "ALTER PROCEDURE feature.author_feature_field_overrides(text, bigint, text, text, bigint, uuid, jsonb, jsonb) OWNER TO ktm_feature_state_procedure_owner",
        "ALTER PROCEDURE feature.revoke_feature_field_overrides(text, bigint, text, text, bigint, uuid, text[]) OWNER TO ktm_feature_state_procedure_owner",
        "REVOKE ALL ON PROCEDURE feature.author_feature_field_overrides(text, bigint, text, text, bigint, uuid, jsonb, jsonb) FROM PUBLIC",
        "REVOKE ALL ON PROCEDURE feature.revoke_feature_field_overrides(text, bigint, text, text, bigint, uuid, text[]) FROM PUBLIC",
        "GRANT EXECUTE ON PROCEDURE feature.author_feature_field_overrides(text, bigint, text, text, bigint, uuid, jsonb, jsonb) TO ktm_feature_runtime",
        "GRANT EXECUTE ON PROCEDURE feature.revoke_feature_field_overrides(text, bigint, text, text, bigint, uuid, text[]) TO ktm_feature_runtime",
    ):
        op.execute(statement)
    op.execute("SET ROLE ktm_feature_schema_owner")
    for statement in (
        "GRANT SELECT, UPDATE (command_id) ON ops.domain_commands TO ktm_feature_state_procedure_owner",
        "GRANT SELECT ON ops.domain_command_results TO ktm_feature_state_procedure_owner",
        "GRANT UPDATE (request_id) ON ops.feature_change_requests TO ktm_feature_state_procedure_owner",
    ):
        op.execute(statement)


def downgrade() -> None:
    raise RuntimeError("0100 is forward-only; rebuild with the T-VN-36 release head")
