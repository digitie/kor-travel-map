"""Geo stamp 직접 DML을 닫고 legacy EX/제한 SH의 SD 경계를 분리한다."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Final

from sqlalchemy import text

from alembic import op

revision: str = "421_stamp_writer_boundary"
down_revision: str | None = "420_exclusive_provider_refresh"
branch_labels: str | None = None
depends_on: str | None = None


def _sidecar(name: str) -> str:
    return Path(__file__).with_name(name).read_text(encoding="utf-8")


_EXPECTED_INSTALLER_BODY_SHA: Final[str] = (
    "f8db128ea1712051475ecd5af20d14788facda20b61ca160c944d28a8d860ea2"
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
        '421_stamp_writer_boundary'
    ))
"""
_REWIRE_SQL: Final[str] = """
DO $rewire$
DECLARE v_count bigint;
BEGIN
    v_count:=feature._assert_stamp_projection_guard_inventory(false);
    IF v_count=0 THEN RETURN; END IF;
    DROP TRIGGER trg_scalar_unsupported ON feature.feature_geocode_stamps;
    CREATE TRIGGER trg_scalar_unsupported BEFORE DELETE ON feature.feature_geocode_stamps
        FOR EACH ROW EXECUTE FUNCTION feature.reject_unsupported_active_scalar_mutation();
    CREATE TRIGGER trg_stamp_writer_entry BEFORE INSERT OR UPDATE ON feature.feature_geocode_stamps
        FOR EACH ROW EXECUTE FUNCTION feature.guard_stamp_writer_entry();
    PERFORM feature._assert_stamp_projection_guard_inventory(true);
END;
$rewire$;
"""
_UPGRADE_STATEMENTS: Final[tuple[str, ...]] = (
    "SET ROLE ktm_feature_schema_owner",
    "LOCK TABLE feature.feature_geocode_stamps IN ACCESS EXCLUSIVE MODE",
    "REVOKE INSERT,UPDATE ON feature.feature_geocode_stamps FROM ktm_feature_runtime",
    "GRANT SELECT,INSERT,UPDATE ON feature.feature_geocode_stamps TO "
    "ktm_feature_state_procedure_owner",
    "GRANT CREATE ON SCHEMA feature TO ktm_feature_state_procedure_owner",
    "SET ROLE ktm_feature_state_procedure_owner",
    _sidecar("_421_stamp_writer_entry.sql"),
    "GRANT EXECUTE ON FUNCTION feature.guard_stamp_writer_entry() TO ktm_feature_schema_owner",
    _sidecar("_421_legacy_stamp_upsert.sql"),
    _sidecar("_421_validate_scoped_stamps.sql"),
    _sidecar("_421_lock_scoped_stamps.sql"),
    _sidecar("_421_reobserve_scoped_stamps.sql"),
    "REVOKE ALL ON FUNCTION feature.guard_stamp_writer_entry() FROM PUBLIC,ktm_feature_runtime",
    "REVOKE ALL ON FUNCTION "
    "feature._validate_scoped_provider_geocode_stamps(uuid,uuid,text,t"
    "ext,jsonb,boolean) FROM PUBLIC,ktm_feature_runtime",
    "REVOKE ALL ON FUNCTION "
    "feature.upsert_provider_geocode_stamps_ex(uuid[],text[],text,text) FROM PUBLIC",
    "REVOKE ALL ON FUNCTION "
    "feature.lock_scoped_provider_geocode_stamps(uuid,uuid,text,text,jsonb) FROM PUBLIC",
    "REVOKE ALL ON FUNCTION "
    "feature.reobserve_scoped_provider_geocode_stamps(uuid,uuid,text,text,jsonb) FROM PUBLIC",
    "GRANT EXECUTE ON FUNCTION "
    "feature.upsert_provider_geocode_stamps_ex(uuid[],text[],text,text) TO ktm_feature_runtime",
    "GRANT EXECUTE ON FUNCTION "
    "feature.lock_scoped_provider_geocode_stamps(uuid,uuid,text,text,jsonb) TO ktm_feature_runtime",
    "GRANT EXECUTE ON FUNCTION "
    "feature.reobserve_scoped_provider_geocode_stamps(uuid,uuid,text,t"
    "ext,jsonb) TO ktm_feature_runtime",
    "SET ROLE ktm_feature_schema_owner",
    _sidecar("_421_projection_guard_inventory.sql"),
    "REVOKE ALL ON FUNCTION feature._assert_stamp_projection_guard_inventory(boolean) "
    "FROM PUBLIC,ktm_feature_runtime",
    _sidecar("_421_install_projection_guards.sql"),
    _REWIRE_SQL,
    _RECEIPT_HEAD_CHECK_SQL,
)


def upgrade() -> None:
    bind = op.get_bind()
    row = bind.execute(
        text("""SELECT p.prosrc,r.rolname,p.prosecdef,p.prokind::text
      FROM pg_proc p JOIN pg_roles r ON r.oid=p.proowner
      WHERE p.oid='feature._install_provider_field_projection_guards()'::regprocedure""")
    ).one()
    if (
        row[1:] != ("ktm_feature_schema_owner", True, "f")
        or hashlib.sha256(row[0].encode()).hexdigest() != _EXPECTED_INSTALLER_BODY_SHA
    ):
        raise RuntimeError("projection installer definition drifted before421")
    prior_create = bool(
        bind.scalar(
            text(
                "SELECT has_schema_privilege("
                "'ktm_feature_state_procedure_owner','feature','CREATE')"
            )
        )
    )
    prior = dict(
        bind.execute(
            text(
                "SELECT name,setting FROM pg_settings WHERE name IN "
                "('lock_timeout','statement_timeout')"
            )
        ).all()
    )
    for name, cap in (("lock_timeout", 1000), ("statement_timeout", 30000)):
        value = int(prior[name])
        bind.execute(
            text("SELECT set_config(:name,:value,true)"),
            {"name": name, "value": str(min(value, cap) if value else cap)},
        )
    bind.execute(text("SET ROLE ktm_feature_state_procedure_owner"))
    bind.execute(text("SELECT ops.lock_scoped_feature_write_protocol(true)"))
    bind.execute(text("SELECT pg_advisory_xact_lock(hashtextextended('feature-curation-write',0))"))
    for statement in _UPGRADE_STATEMENTS:
        bind.execute(text(statement))
    if not prior_create:
        bind.execute(text("REVOKE CREATE ON SCHEMA feature FROM ktm_feature_state_procedure_owner"))
    for name, value in prior.items():
        bind.execute(text("SELECT set_config(:name,:value,true)"), {"name": name, "value": value})
    bind.execute(text("SET ROLE ktm_feature_schema_owner"))


def downgrade() -> None:
    raise RuntimeError("forward-only migration")
