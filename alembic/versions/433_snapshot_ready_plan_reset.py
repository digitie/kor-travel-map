"""현재 executor의 rollback된 bound READY plan 재계획만 추가한다. profile은 활성화하지 않는다."""

from __future__ import annotations

from pathlib import Path
from typing import Final

from sqlalchemy import text

from alembic import op

revision: str = "433_snapshot_ready_plan_reset"
down_revision: str | None = "432_rest_snapshot_atomic"
branch_labels: str | None = None
depends_on: str | None = None

_SCHEMA_OWNER: Final = "ktm_feature_schema_owner"
_COMMAND_OWNER: Final = "ktm_curation_command_owner"
_RESTRICTED: Final = "PUBLIC,ktm_feature_runtime,ktm_feature_service,ktm_curation_provider_executor"
_SIGNATURE: Final = "ops.reset_ready_provider_snapshot_plan(uuid,bigint,uuid,uuid,uuid,text)"
_READY_RESET_SQL: Final = (
    Path(__file__).with_name("_433_snapshot_ready_plan_reset.sql").read_text(encoding="utf-8")
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
        '424_tracking_protocol_prefix',
        '425_provider_base_update_first',
        '426_provider_patch_protocol',
        '427_transport_airport_reader',
        '428_bounded_curation_capture',
        '429_strict_sh_data_guards',
        '430_provider_snapshot_recovery',
        '431_transport_rest_reader',
        '432_rest_snapshot_atomic',
        '433_snapshot_ready_plan_reset'
    ))
"""

_UPGRADE_STATEMENTS: Final[tuple[str, ...]] = (
    "SET ROLE ktm_curation_command_owner",
    _READY_RESET_SQL,
    "REVOKE ALL ON FUNCTION " + _SIGNATURE + " FROM " + _RESTRICTED,
    "GRANT EXECUTE ON FUNCTION " + _SIGNATURE + " TO ktm_curation_provider_executor",
    "SET ROLE ktm_feature_schema_owner",
    _RECEIPT_HEAD_CHECK_SQL,
)


def upgrade() -> None:
    bind = op.get_bind()
    settings = {
        str(name): str(value)
        for name, value in bind.execute(
            text(
                "SELECT name,setting FROM pg_settings WHERE name IN "
                "('lock_timeout','statement_timeout')"
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
    bind.execute(text("SET ROLE " + _SCHEMA_OWNER))
    had_create = bool(
        bind.scalar(
            text("SELECT has_schema_privilege(:owner,'ops','CREATE')"),
            {"owner": _COMMAND_OWNER},
        )
    )
    if not had_create:
        bind.execute(text("GRANT CREATE ON SCHEMA ops TO " + _COMMAND_OWNER))
    for statement in _UPGRADE_STATEMENTS:
        bind.execute(text(statement))
    if not had_create:
        bind.execute(text("REVOKE CREATE ON SCHEMA ops FROM " + _COMMAND_OWNER))
    for name, value in settings.items():
        bind.execute(text("SELECT set_config(:name,:value,true)"), {"name": name, "value": value})
    bind.execute(text("SET ROLE " + _SCHEMA_OWNER))


def downgrade() -> None:
    raise RuntimeError("forward-only migration")
