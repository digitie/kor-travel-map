"""제한된 현재 curation capture만 추가한다. 기존 호출자/SH/격리 수준은 바꾸지 않는다."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Final

from sqlalchemy import text

from alembic import op

revision: str = "428_bounded_curation_capture"
down_revision: str | None = "427_transport_airport_reader"
branch_labels: str | None = None
depends_on: str | None = None

_EXPECTED_CANONICAL_BODY_SHA256: Final[str] = (
    "86bce78e9f40874f6a8312ff6e4e5f6aceaf836fa1cd07648637630083a2e5e0"
)
_EXPECTED_METADATA_BODY_SHA256: Final[str] = (
    "0c0014e0ba07fc785d81846d58efcbb8fc56674d0f321b4616574c5057fea264"
)


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
        '427_transport_airport_reader',
        '428_bounded_curation_capture'
    ))
"""
_UPGRADE_STATEMENTS: Final[tuple[str, ...]] = (
    "SET ROLE ktm_feature_state_procedure_owner",
    "GRANT EXECUTE ON FUNCTION feature._heritage_evidence_metadata_bytes("
    "bigint[],boolean[],integer[],boolean[]) TO ktm_feature_schema_owner",
    "SET ROLE ktm_feature_schema_owner",
    _sidecar("_428_bounded_curation_string_object.sql"),
    "REVOKE ALL ON FUNCTION feature._bounded_curation_string_object(jsonb) "
    "FROM PUBLIC,ktm_feature_runtime,ktm_feature_service",
    _sidecar("_428_bounded_provider_curation_input_set.sql"),
    "REVOKE ALL ON FUNCTION feature._bounded_provider_curation_input_set(bigint) "
    "FROM PUBLIC,ktm_feature_runtime,ktm_feature_service,ktm_curation_provider_executor",
    "GRANT EXECUTE ON FUNCTION feature._bounded_provider_curation_input_set(bigint) "
    "TO ktm_curation_command_owner",
    _RECEIPT_HEAD_CHECK_SQL,
)


def upgrade() -> None:
    bind = op.get_bind()
    settings = {
        str(name): str(value)
        for name, value in bind.execute(
            text(
                "SELECT name,setting FROM pg_settings WHERE "
                "name IN ('lock_timeout','statement_timeout')"
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
    rows = bind.execute(
        text("""SELECT p.proname,p.prosrc,p.prosecdef,p.provolatile::text,
        p.proconfig,r.rolname,p.prokind::text
        FROM pg_proc p JOIN pg_roles r ON r.oid=p.proowner
        WHERE p.oid IN (
          'feature.current_provider_curation_input_set(bigint)'::regprocedure,
          'feature._heritage_evidence_metadata_bytes(bigint[],boolean[],integer[],boolean[])'::regprocedure
        )""")
    ).all()
    expected = {
        "current_provider_curation_input_set": (
            _EXPECTED_CANONICAL_BODY_SHA256,
            True,
            "s",
            ["search_path=pg_catalog, feature, provider_sync, ops, x_extension"],
            "ktm_feature_schema_owner",
        ),
        "_heritage_evidence_metadata_bytes": (
            _EXPECTED_METADATA_BODY_SHA256,
            False,
            "i",
            ["search_path=pg_catalog"],
            "ktm_feature_state_procedure_owner",
        ),
    }
    if len(rows) != 2 or {row[0] for row in rows} != set(expected):
        raise RuntimeError("bounded capture dependency inventory changed")
    for name, body, secure, volatility, config, owner, kind in rows:
        if (
            kind != "f"
            or (hashlib.sha256(body.encode()).hexdigest(), secure, volatility, config, owner)
            != expected[name]
        ):
            raise RuntimeError("bounded capture dependency definition changed")
    for statement in _UPGRADE_STATEMENTS:
        bind.execute(text(statement))
    for name, value in settings.items():
        bind.execute(text("SELECT set_config(:name,:value,true)"), {"name": name, "value": value})
    bind.execute(text("SET ROLE ktm_feature_schema_owner"))


def downgrade() -> None:
    raise RuntimeError("forward-only migration")
