"""종결 P→L과 nonterminal/event leaf L 진입 순서만 고정한다."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Final

from sqlalchemy import text

from alembic import op

revision: str = "424_tracking_protocol_prefix"
down_revision: str | None = "423_exclusive_context_select"
branch_labels: str | None = None
depends_on: str | None = None
_OWNER: Final = "ktm_curation_command_owner"
_EXPECTED: Final[dict[str, dict[str, Any]]] = {
    "feature.finalize_provider_curation_root": {
        "body_sha256": "89e903862fa3e797f3b87d7e9539d6abd90474890c8d09401773de2e7f0a6f35",
        "config": ["search_path=pg_catalog, feature, provider_sync, ops, x_extension"],
        "finalizing": True,
        "kind": "p",
        "modes": ["i", "o", "o", "o", "o"],
        "names": [
            "p_root_job_id",
            "o_generation_count",
            "o_generation_set_hash",
            "o_replayed",
            "o_stale_input",
        ],
        "types": ["uuid", "bigint", "text", "boolean", "boolean"],
    },
    "feature.seal_provider_curation_snapshot_receipt": {
        "body_sha256": "7ec8b23baa6d7b0ed27e5d74978f0fdb0ab71cc9926beb0b63c386fda56362c9",
        "config": ["search_path=pg_catalog, feature, provider_sync, ops, x_extension"],
        "finalizing": True,
        "kind": "p",
        "modes": ["i", "i", "i", "i", "i", "i", "o", "o", "o", "o"],
        "names": [
            "p_root_job_id",
            "p_provider_dataset_id",
            "p_sync_scope",
            "p_operation_key",
            "p_expected_input_member_count",
            "p_expected_input_set_hash",
            "o_source_job_id",
            "o_observed_at",
            "o_source_entity_count",
            "o_source_input_set_hash",
        ],
        "types": [
            "uuid",
            "bigint",
            "text",
            "text",
            "bigint",
            "text",
            "uuid",
            "timestamp with time zone",
            "bigint",
            "text",
        ],
    },
    "ops.append_provider_feature_attempt_event_command": {
        "body_sha256": "3f883c7e0daac5f5a07060278784be726020872a88d483a457d1849e9948b2be",
        "config": ["search_path=pg_catalog, ops"],
        "finalizing": False,
        "kind": "p",
        "modes": ["i", "i", "i", "i", "i", "i", "i", "o", "o", "o", "o", "o", "o", "o", "o", "o"],
        "names": [
            "p_dagster_run_id",
            "p_provider_dataset_id",
            "p_sync_scope",
            "p_operation_key",
            "p_attempt_number",
            "p_outcome",
            "p_error",
            "o_event_id",
            "o_job_id",
            "o_import_job_dataset_id",
            "o_stage",
            "o_level",
            "o_code",
            "o_message",
            "o_payload",
            "o_occurred_at",
        ],
        "types": [
            "text",
            "bigint",
            "text",
            "text",
            "integer",
            "text",
            "jsonb",
            "uuid",
            "uuid",
            "uuid",
            "text",
            "text",
            "text",
            "text",
            "jsonb",
            "timestamp with time zone",
        ],
    },
    "ops.ensure_provider_feature_operation_command": {
        "body_sha256": "1b7415f2d552d247fe499f67c79d497b7f083dfb373eb8d8b0fde09d4c85ecf4",
        "config": ["search_path=pg_catalog, ops, provider_sync"],
        "finalizing": False,
        "kind": "p",
        "modes": ["i", "i", "i", "i", "i", "i", "i", "o", "o", "o"],
        "names": [
            "p_dagster_run_id",
            "p_trigger_kind",
            "p_operation_key",
            "p_memberships",
            "p_created_at",
            "p_started_at",
            "p_observed_status",
            "o_root_job_id",
            "o_inserted",
            "o_changed",
        ],
        "types": [
            "text",
            "text",
            "text",
            "jsonb",
            "timestamp with time zone",
            "timestamp with time zone",
            "text",
            "uuid",
            "boolean",
            "boolean",
        ],
    },
    "ops.fill_provider_cancellation_starts_command": {
        "body_sha256": "fa5083c30e9cfda2a1a8ff60004a05e005e08f82d1b839202bdf8df13447e8d4",
        "config": ["search_path=pg_catalog, ops"],
        "finalizing": True,
        "kind": "f",
        "modes": ["i", "i", "i", "t", "t", "t"],
        "names": [
            "p_cancellation_id",
            "p_dagster_run_id",
            "p_engine_started_at",
            "expected_count",
            "owned_count",
            "updated_job_ids",
        ],
        "types": ["uuid", "text", "timestamp with time zone", "bigint", "bigint", "uuid[]"],
    },
    "ops.finish_provider_feature_membership_command": {
        "body_sha256": "733845a3c68790a4ea145c261a364791e06d7566d9aa2e88fa901df27ba87209",
        "config": ["search_path=pg_catalog, ops"],
        "finalizing": True,
        "kind": "p",
        "modes": ["i", "i", "i", "i", "i", "i", "o"],
        "names": [
            "p_root_job_id",
            "p_provider_dataset_id",
            "p_sync_scope",
            "p_operation_key",
            "p_authoritative_snapshot_complete",
            "p_finished_at",
            "o_changed",
        ],
        "types": [
            "uuid",
            "bigint",
            "text",
            "text",
            "boolean",
            "timestamp with time zone",
            "boolean",
        ],
    },
    "ops.transition_provider_cancellation_job_command": {
        "body_sha256": "84b850c2a5ccc3f8ca659e8c8914d575c5044410ec56798b7684f7abf1a5d4fd",
        "config": ["search_path=pg_catalog, ops"],
        "finalizing": True,
        "kind": "f",
        "modes": None,
        "names": [
            "p_cancellation_id",
            "p_job_id",
            "p_dagster_run_id",
            "p_expected_statuses",
            "p_target_status",
            "p_error_message",
            "p_dagster_terminal_status",
            "p_engine_started_at",
            "p_engine_finished_at",
            "p_success_tracking_invariant",
            "p_result",
            "p_expected_member_results",
        ],
        "types": [
            "uuid",
            "uuid",
            "text",
            "text[]",
            "text",
            "text",
            "text",
            "timestamp with time zone",
            "timestamp with time zone",
            "boolean",
            "text",
            "text[]",
        ],
    },
    "ops.transition_provider_feature_operation_terminal_command": {
        "body_sha256": "bd935a497c90a90a41b4458ba453a35ac505f871bf5f08e36d6d45df3dba1f3e",
        "config": ["search_path=pg_catalog, ops"],
        "finalizing": True,
        "kind": "p",
        "modes": ["i", "i", "i", "i", "i", "i", "i", "i", "o"],
        "names": [
            "p_root_job_id",
            "p_target_status",
            "p_dagster_terminal_status",
            "p_stage",
            "p_error_message",
            "p_started_at",
            "p_finished_at",
            "p_update_members",
            "o_changed",
        ],
        "types": [
            "uuid",
            "text",
            "text",
            "text",
            "text",
            "timestamp with time zone",
            "timestamp with time zone",
            "boolean",
            "boolean",
        ],
    },
}


def _with_prefix(body: str, *, finalizing: bool) -> str:
    """첫 BEGIN만 변경하고 기존 isolation/검증/hash 본문을 보존한다."""
    if "lock_provider_feature_tracking_protocol" in body:
        raise RuntimeError("tracking prefix definition already changed")
    before, separator, after = body.partition("\nBEGIN\n")
    if not separator:
        raise RuntimeError("tracking routine shape changed")
    mode = "true" if finalizing else "false"
    return (
        before
        + separator
        + "  PERFORM ops.lock_provider_feature_tracking_protocol("
        + mode
        + ");\n"
        + after
    )


_RECEIPT_HEAD_CHECK_SQL: Final[str] = """
ALTER TABLE ops.application_schema_operation_receipts
    DROP CONSTRAINT ck_application_schema_operation_receipts_head,
    ADD CONSTRAINT ck_application_schema_operation_receipts_head CHECK(destination_head IN (
        '300',
        '301_m03_import_children',
        '302_m03_child_issuance',
        '303_m05_payload_hash_domain',
        '304_m05_detector_manuals',
        '305_m05_relitigation_fence',
        '306_m02_manual_feature_purge',
        '307_m02_truncate_fence',
        '308_t39_provider_identities',
        '309_t39_feature_id_rekey',
        '310_seoul_source_move',
        '311_seal_member_digest',
        '312_route_geometry_sidecar',
        '313_single_service_role',
        '400',
        '401_retire_map_kma_refresh',
        '402_remove_map_weather_data',
        '403_drop_kma_notice_lineage',
        '404_transport_provider_identity',
        '405_mois_freshness_sla',
        '406_feature_write_gate',
        '407_feature_geocode_stamps',
        '408_kor_travel_geo_releases',
        '409_geo_release_item_reasons',
        '410_provider_field_shadow',
        '411_scoped_feature_write_kernel',
        '412_provider_scalar_projection',
        '413_legacy_sql_protocol_entry',
        '414_manual_dedup_protocol',
        '415_state_lifecycle_protocol',
        '416_field_override_protocol',
        '417_protocol_ex_reentry',
        '418_creation_protocol',
        '419_retire_pg_transport_values',
        '420_exclusive_provider_refresh',
        '421_stamp_writer_boundary',
        '422_heritage_evidence_reader',
        '423_exclusive_context_select',
        '424_tracking_protocol_prefix'
    ))
"""
_UPGRADE_STATEMENTS: Final[tuple[str, ...]] = (
    "SET ROLE ktm_curation_command_owner",
    Path(__file__).with_name("_424_tracking_prefix.sql").read_text(encoding="utf-8"),
    "REVOKE ALL ON FUNCTION ops.lock_provider_feature_tracking_protocol(boolean) FROM PUBLIC",
    "GRANT EXECUTE ON FUNCTION ops.lock_provider_feature_tracking_protocol(boolean) "
    "TO ktm_feature_runtime",
    "SET ROLE ktm_feature_schema_owner",
    _RECEIPT_HEAD_CHECK_SQL,
)

_CATALOG_SQL: Final = """SELECT n.nspname||'.'||p.proname AS name,p.oid::bigint AS oid,
 r.rolname AS owner,p.prokind::text AS kind,p.prosecdef,l.lanname AS language,
 p.provolatile::text AS volatility,p.proconfig AS config,p.proacl::text[] AS acl,
 p.prosrc AS body,pg_get_functiondef(p.oid) AS definition,
 pg_get_expr(p.proargdefaults,0) AS defaults,p.proargnames AS names,p.proargmodes::text[] AS modes,
 ARRAY(SELECT format_type(t,NULL)
       FROM unnest(COALESCE(p.proallargtypes,p.proargtypes::oid[])) WITH ORDINALITY AS x(t,ord)
       ORDER BY ord) AS types
 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
 JOIN pg_roles r ON r.oid=p.proowner JOIN pg_language l ON l.oid=p.prolang
 WHERE n.nspname||'.'||p.proname=ANY(CAST(:names AS text[]))
 ORDER BY n.nspname COLLATE "C",p.proname COLLATE "C"
"""


def upgrade() -> None:
    bind = op.get_bind()
    settings = {
        str(k): str(v)
        for k, v in bind.execute(
            text(
                "SELECT name,setting FROM pg_settings "
                "WHERE name IN ('lock_timeout','statement_timeout')"
            )
        ).all()
    }
    for name, cap in (("lock_timeout", 1000), ("statement_timeout", 30000)):
        prior = int(settings[name])
        bind.execute(
            text("SELECT set_config(:name,:value,true)"),
            {"name": name, "value": str(min(prior, cap) if prior else cap)},
        )
    bind.execute(text("SET ROLE ktm_feature_state_procedure_owner"))
    bind.execute(text("SELECT ops.lock_scoped_feature_write_protocol(true)"))
    bind.execute(text("SELECT pg_advisory_xact_lock(6832465333779826081::bigint)"))
    rows = bind.execute(text(_CATALOG_SQL), {"names": list(_EXPECTED)}).mappings().all()
    if len(rows) != len(_EXPECTED) or {r["name"] for r in rows} != set(_EXPECTED):
        raise RuntimeError("tracking routine inventory differs from revision 423")
    replacements: list[tuple[str, str]] = []
    for row in rows:
        expected = _EXPECTED[row["name"]]
        if (
            row["owner"] != _OWNER
            or row["kind"] != expected["kind"]
            or not row["prosecdef"]
            or row["language"] != "plpgsql"
            or row["volatility"] != "v"
            or row["definition"].count(row["body"]) != 1
            or hashlib.sha256(row["body"].encode()).hexdigest() != expected["body_sha256"]
            or row["names"] != expected["names"]
            or row["modes"] != expected["modes"]
            or row["types"] != expected["types"]
            or row["config"] != expected["config"]
        ):
            raise RuntimeError("tracking owner/signature/body/config changed: " + row["name"])
        changed = _with_prefix(row["body"], finalizing=expected["finalizing"])
        replacements.append((row["name"], row["definition"].replace(row["body"], changed, 1)))
    bind.execute(text("SET ROLE ktm_feature_schema_owner"))
    prior_create = {
        schema: bool(
            bind.scalar(
                text("SELECT has_schema_privilege(:owner,:schema,'CREATE')"),
                {"owner": _OWNER, "schema": schema},
            )
        )
        for schema in ("feature", "ops")
    }
    for schema, had_create in prior_create.items():
        if not had_create:
            bind.execute(text("GRANT CREATE ON SCHEMA " + schema + " TO " + _OWNER))
    for statement in _UPGRADE_STATEMENTS:
        bind.execute(text(statement))
    bind.execute(text("SET ROLE ktm_curation_command_owner"))
    for _name, definition in replacements:
        bind.execute(text(definition))
    after = bind.execute(text(_CATALOG_SQL), {"names": list(_EXPECTED)}).mappings().all()
    if len(after) != len(rows):
        raise RuntimeError("tracking replacement inventory changed")
    for prior_row, updated_row in zip(rows, after, strict=True):
        for key in (
            "name",
            "oid",
            "owner",
            "kind",
            "prosecdef",
            "language",
            "volatility",
            "config",
            "acl",
            "defaults",
            "names",
            "modes",
            "types",
        ):
            if prior_row[key] != updated_row[key]:
                raise RuntimeError("tracking replacement metadata changed: " + key)
    bind.execute(text("SET ROLE ktm_feature_schema_owner"))
    for schema, had_create in prior_create.items():
        if not had_create:
            bind.execute(text("REVOKE CREATE ON SCHEMA " + schema + " FROM " + _OWNER))
    for name, value in settings.items():
        bind.execute(text("SELECT set_config(:name,:value,true)"), {"name": name, "value": value})
    bind.execute(text("SET ROLE ktm_feature_schema_owner"))


def downgrade() -> None:
    raise RuntimeError("forward-only migration")
