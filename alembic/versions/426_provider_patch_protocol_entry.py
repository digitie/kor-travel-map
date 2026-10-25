"""공개 legacy provider patch는 source·Feature 잠금 전에 protocol EX로 진입한다."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Final

from sqlalchemy import text

from alembic import op

revision: str = "426_provider_patch_protocol"
down_revision: str | None = "425_provider_base_update_first"
branch_labels: str | None = None
depends_on: str | None = None

_EXPECTED_BODY_SHA256: Final = "704a2a4f39dac29d4b05e259b2b55b4b84bc15f585aaa478d1068f4dbb452594"
_EXPECTED_ARGUMENT_NAMES: Final = [
    "p_feature_id",
    "p_provider_dataset_id",
    "p_source_entity_key",
    "p_source_record_key",
    "p_expected_row_revision",
    "p_values",
    "p_geometry_wkt",
    "o_feature_id",
    "o_row_revision",
    "o_applied_field_count",
]
_EXPECTED_ARGUMENT_TYPES: Final = [
    "uuid",
    "bigint",
    "text",
    "text",
    "bigint",
    "jsonb",
    "jsonb",
    "uuid",
    "bigint",
    "integer",
]


def _sidecar(name: str) -> str:
    return Path(__file__).with_name(name).read_text(encoding="utf-8")


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
        '424_tracking_protocol_prefix',
        '425_provider_base_update_first',
        '426_provider_patch_protocol'
    ))
"""
_UPGRADE_STATEMENTS: Final[tuple[str, ...]] = (
    "SET ROLE ktm_feature_schema_owner",
    "SET ROLE ktm_feature_state_procedure_owner",
    _sidecar("_426_provider_patch_protocol_entry.sql"),
    "SET ROLE ktm_feature_schema_owner",
    _RECEIPT_HEAD_CHECK_SQL,
)


def upgrade() -> None:
    bind = op.get_bind()
    settings: dict[str, str] = {
        str(name): str(value)
        for name, value in bind.execute(
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
    rows = (
        bind.execute(
            text("""SELECT p.prosrc AS body,
        p.proargnames AS argument_names,
        ARRAY(SELECT arg::text FROM unnest(p.proargmodes) AS arg) AS argument_modes,
        ARRAY(SELECT format_type(arg,NULL) FROM unnest(p.proallargtypes) AS arg) AS argument_types,
        r.rolname AS owner,p.prokind::text AS kind,p.prosecdef,
        l.lanname AS language,p.provolatile::text AS volatility,
        p.proconfig
        FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
        JOIN pg_roles r ON r.oid=p.proowner JOIN pg_language l ON l.oid=p.prolang
        WHERE n.nspname='feature' AND p.proname='apply_provider_feature_field_patch'
    """)
        )
        .mappings()
        .all()
    )
    if len(rows) != 1:
        raise RuntimeError("provider patch routine inventory differs from revision 425")
    row = rows[0]
    if (
        row["owner"] != "ktm_feature_state_procedure_owner"
        or row["kind"] != "p"
        or not row["prosecdef"]
        or row["language"] != "plpgsql"
        or row["volatility"] != "v"
        or row["proconfig"] != ["search_path=pg_catalog"]
        or hashlib.sha256(row["body"].encode()).hexdigest() != _EXPECTED_BODY_SHA256
        or row["argument_names"] != _EXPECTED_ARGUMENT_NAMES
        or row["argument_modes"] != ["i"] * 7 + ["o"] * 3
        or row["argument_types"] != _EXPECTED_ARGUMENT_TYPES
    ):
        raise RuntimeError("provider patch owner or definition changed")
    bind.execute(text("SET ROLE ktm_feature_schema_owner"))
    prior_create = bool(
        bind.scalar(
            text(
                "SELECT has_schema_privilege('ktm_feature_state_procedure_owner',"
                "'feature','CREATE')"
            )
        )
    )
    if not prior_create:
        bind.execute(text("GRANT CREATE ON SCHEMA feature TO ktm_feature_state_procedure_owner"))
    for statement in _UPGRADE_STATEMENTS:
        bind.execute(text(statement))
    if not prior_create:
        bind.execute(text("REVOKE CREATE ON SCHEMA feature FROM ktm_feature_state_procedure_owner"))
    for name, value in settings.items():
        bind.execute(text("SELECT set_config(:name,:value,true)"), {"name": name, "value": value})
    bind.execute(text("SET ROLE ktm_feature_schema_owner"))


def downgrade() -> None:
    raise RuntimeError("forward-only migration")
