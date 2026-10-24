"""EX context의 후보 조회만 한 번으로 합치고 기존 검증 순서는 보존한다."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Final

from sqlalchemy import text

from alembic import op

revision: str = "423_exclusive_context_select"
down_revision: str | None = "422_heritage_evidence_reader"
branch_labels: str | None = None
depends_on: str | None = None

_EXPECTED_BODY_SHA256: Final = "3dd92fbb11e8d8c8cdfdf3fb5e90f0a04a19b80d7d89ae95505a0733edfc2361"
_EXPECTED_SIGNATURE_SHA256: Final = (
    "f196d4bc4c5f26d0c4b79d59e2fd2988958ffa72f4973c5708f1c9cfeecec2eb"
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
        '423_exclusive_context_select'
    ))
"""
_UPGRADE_STATEMENTS: Final[tuple[str, ...]] = (
    "SET ROLE ktm_feature_schema_owner",
    "SET ROLE ktm_feature_state_procedure_owner",
    _sidecar("_423_exclusive_refresh_context.sql"),
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
        pg_get_function_identity_arguments(p.oid) AS signature,
        r.rolname AS owner,p.prokind::text AS kind,p.prosecdef,
        l.lanname AS language,p.provolatile::text AS volatility,
        p.proconfig,pg_get_function_result(p.oid) AS result
        FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
        JOIN pg_roles r ON r.oid=p.proowner JOIN pg_language l ON l.oid=p.prolang
        WHERE n.nspname='feature' AND p.proname='_exclusive_provider_refresh_context'
    """)
        )
        .mappings()
        .all()
    )
    if len(rows) != 1:
        raise RuntimeError("exclusive context routine inventory differs from revision 422")
    row = rows[0]
    if (
        row["owner"] != "ktm_feature_state_procedure_owner"
        or row["kind"] != "f"
        or not row["prosecdef"]
        or row["language"] != "plpgsql"
        or row["volatility"] != "v"
        or row["proconfig"] != ["search_path=pg_catalog"]
        or row["result"] != "boolean"
        or hashlib.sha256(row["body"].encode()).hexdigest() != _EXPECTED_BODY_SHA256
        or hashlib.sha256(row["signature"].encode()).hexdigest() != _EXPECTED_SIGNATURE_SHA256
    ):
        raise RuntimeError("exclusive context owner or definition changed")
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
