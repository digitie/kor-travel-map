"""공항의 제한된 전체 DB 증거 reader만 추가한다. 수집/SH 활성화는 하지 않는다."""

from __future__ import annotations

from pathlib import Path
from typing import Final

from sqlalchemy import text

from alembic import op

revision: str = "427_transport_airport_reader"
down_revision: str | None = "426_provider_patch_protocol"
branch_labels: str | None = None
depends_on: str | None = None


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
        '426_provider_patch_protocol',
        '427_transport_airport_reader'
    ))
"""
_UPGRADE_STATEMENTS: Final[tuple[str, ...]] = (
    "SET ROLE ktm_feature_schema_owner",
    "CREATE INDEX ix_source_entity_heads_bounded_evidence_key ON provider_sync.source_entity_heads "
    "((CASE WHEN pg_catalog.octet_length(source_entity_key::text)<=256 "
    "THEN source_entity_key::text ELSE NULL::text END))",
    "CREATE INDEX ix_source_records_bounded_evidence_key ON provider_sync.source_records "
    "((CASE WHEN pg_catalog.octet_length(source_record_key::text)<=256 "
    "THEN source_record_key::text ELSE NULL::text END))",
    "CREATE INDEX ix_source_links_bounded_evidence_key ON provider_sync.source_links "
    "((CASE WHEN pg_catalog.octet_length(source_entity_key::text)<=256 "
    "THEN source_entity_key::text ELSE NULL::text END))",
    "SET ROLE ktm_feature_state_procedure_owner",
    _sidecar("_427_transport_airport_evidence_shape.sql"),
    "REVOKE ALL ON FUNCTION feature._transport_airport_evidence_shape("
    "jsonb,jsonb,jsonb,x_extension.geometry) FROM PUBLIC,ktm_feature_runtime",
    _sidecar("_427_transport_airport_evidence_inventory.sql"),
    "REVOKE ALL ON FUNCTION feature._transport_airport_evidence_inventory(bigint,text[]) "
    "FROM PUBLIC,ktm_feature_runtime",
    _sidecar("_427_read_transport_airport_evidence.sql"),
    "REVOKE ALL ON FUNCTION feature.read_transport_airport_snapshot_evidence(bigint) "
    "FROM PUBLIC,ktm_feature_runtime",
    "GRANT EXECUTE ON FUNCTION feature.read_transport_airport_snapshot_evidence(bigint) "
    "TO ktm_feature_runtime",
    "SET ROLE ktm_feature_schema_owner",
    _RECEIPT_HEAD_CHECK_SQL,
)


def upgrade() -> None:
    bind = op.get_bind()
    prior: dict[str, str] = {
        str(name): str(value)
        for name, value in bind.execute(
            text(
                "SELECT name,setting FROM pg_settings WHERE name IN "
                "('lock_timeout','statement_timeout')"
            )
        ).all()
    }
    for name, cap in (("lock_timeout", 1000), ("statement_timeout", 30000)):
        value = int(prior[name])
        bind.execute(
            text("SELECT set_config(:name,:value,true)"),
            {"name": name, "value": str(min(value, cap) if value else cap)},
        )
    bind.execute(text("SET ROLE ktm_feature_state_procedure_owner"))
    bind.execute(text("SELECT ops.lock_scoped_feature_write_protocol(true)"))
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
    for name, restored in prior.items():
        bind.execute(
            text("SELECT set_config(:name,:value,true)"), {"name": name, "value": restored}
        )
    bind.execute(text("SET ROLE ktm_feature_schema_owner"))


def downgrade() -> None:
    raise RuntimeError("forward-only migration")
