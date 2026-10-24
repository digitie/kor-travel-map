"""기존 applying EX manifest로 제한 primary place의 legacy 비활성 필드를 허용한다."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Final

from sqlalchemy import text

from alembic import op

revision: str = "419_exclusive_provider_refresh"
down_revision: str | None = "418_creation_protocol"
branch_labels: str | None = None
depends_on: str | None = None
_EXPECTED: Final[dict[str, str]] = {
    "reject_unsupported_active_scalar_mutation": (
        "877a8b4e501554fe9aa8831f96d8a342193c19641c358c24d4fad02bbd643b05"
    ),
    "validate_active_provider_base_field_value": (
        "0f3feaeaa5597dc97e66e63f1c78095f78f394b86d0aa20a307756153de965aa"
    ),
}
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
        '419_exclusive_provider_refresh'
    ))
"""

_UPGRADE_STATEMENTS: Final[tuple[str, ...]] = (
    "SET ROLE ktm_feature_schema_owner",
    _RECEIPT_HEAD_CHECK_SQL,
    "SET ROLE ktm_feature_schema_owner",
)
_SIDECARS: Final = (
    "exclusive_refresh_context",
    "validate_full_refresh",
    "reject_unsupported_active_mutation",
    "validate_base_field_value",
)


def upgrade() -> None:
    bind = op.get_bind()
    rows = bind.execute(
        text("""SELECT p.proname,p.prosrc,r.rolname,p.prosecdef,p.prokind::text
        FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
        JOIN pg_roles r ON r.oid=p.proowner
        WHERE n.nspname='feature' AND p.proname=ANY(CAST(:names AS text[]))"""),
        {"names": list(_EXPECTED)},
    ).all()
    if len(rows) != len(_EXPECTED) or any(
        owner != "ktm_feature_state_procedure_owner"
        or not sd
        or kind != "f"
        or hashlib.sha256(body.encode()).hexdigest() != _EXPECTED[name]
        for name, body, owner, sd, kind in rows
    ):
        raise RuntimeError("reviewed active guard definition drifted before419")
    settings = dict(
        bind.execute(
            text(
                "SELECT name,setting FROM pg_settings "
                "WHERE name IN ('lock_timeout','statement_timeout')"
            )
        ).all()
    )
    for name, cap in (("lock_timeout", 1000), ("statement_timeout", 30000)):
        value = int(settings[name])
        bind.execute(
            text("SELECT set_config(:name,:value,true)"),
            {"name": name, "value": str(min(value, cap) if value else cap)},
        )
    bind.execute(text("SET ROLE ktm_feature_state_procedure_owner"))
    bind.execute(text("SELECT ops.lock_scoped_feature_write_protocol(true)"))
    bind.execute(text("SET ROLE ktm_feature_schema_owner"))
    prior = bool(
        bind.scalar(
            text(
                "SELECT has_schema_privilege('ktm_feature_state_procedure_owner',"
                "'feature','CREATE')"
            )
        )
    )
    bind.execute(text("GRANT CREATE ON SCHEMA feature TO ktm_feature_state_procedure_owner"))
    bind.execute(text("SET ROLE ktm_feature_state_procedure_owner"))
    for name in _SIDECARS:
        bind.execute(text(Path(__file__).with_name("_419_" + name + ".sql").read_text()))
    bind.execute(
        text(
            "REVOKE ALL ON FUNCTION feature._exclusive_provider_refresh_context(uuid,bigint) "
            "FROM PUBLIC,ktm_feature_runtime"
        )
    )
    bind.execute(
        text(
            "REVOKE ALL ON FUNCTION feature.validate_exclusive_provider_snapshot("
            "uuid,bigint,jsonb,text[]) FROM PUBLIC"
        )
    )
    bind.execute(
        text(
            "GRANT EXECUTE ON FUNCTION feature.validate_exclusive_provider_snapshot("
            "uuid,bigint,jsonb,text[]) TO ktm_feature_runtime"
        )
    )
    bind.execute(text("SET ROLE ktm_feature_schema_owner"))
    if not prior:
        bind.execute(text("REVOKE CREATE ON SCHEMA feature FROM ktm_feature_state_procedure_owner"))
    for statement in _UPGRADE_STATEMENTS:
        op.execute(statement)
    for name, value in settings.items():
        bind.execute(text("SELECT set_config(:name,:value,true)"), {"name": name, "value": value})
    op.execute("SET ROLE ktm_feature_schema_owner")


def downgrade() -> None:
    raise RuntimeError("forward-only migration")
