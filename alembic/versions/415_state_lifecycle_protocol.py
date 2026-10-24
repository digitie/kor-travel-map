"""state/lifecycle SQL 진입의 첫 잠금을 protocol EX로 맞춘다. 의미·권한은 유지한다."""

from __future__ import annotations

import hashlib
from typing import Final

from sqlalchemy import text

from alembic import op

revision: str = "415_state_lifecycle_protocol"
down_revision: str | None = "414_manual_dedup_protocol"
branch_labels: str | None = None
depends_on: str | None = None

_LEGACY_OWNERS: Final[dict[str, str]] = {
    "transition_admin_feature_state": "ktm_feature_state_procedure_owner",
    "reactivate_admin_feature_state": "ktm_feature_state_procedure_owner",
    "transition_feature_state": "ktm_feature_state_procedure_owner",
    "author_lifecycle_override": "ktm_feature_state_procedure_owner",
    "revoke_lifecycle_override": "ktm_feature_state_procedure_owner",
}

# 414 실제 head oracle의 signature/prosrc 정본. 기존 설정·ACL을 그대로 재사용한다.
_EXPECTED_DEFINITIONS: Final[dict[str, tuple[str, str]]] = {
    "transition_admin_feature_state": (
        "364ba8df2f2bd663300cf27874a4726f537540f3e39d0d87fd7f15d4b5200d48",
        "0379801bdf8f90fdaf565dcae9a8505d54fdd9ef42c2cc103a08c1e09a84e8b6",
    ),
    "reactivate_admin_feature_state": (
        "3d8a3130f4686a094ffd4e54ef950a8715f31b7807db23475723d21a4ae165bd",
        "d5eb0ca77cbe114e4e755420d6584b63b61fb2c7a60dc0a2e1d19797b008e353",
    ),
    "transition_feature_state": (
        "a449c3635a10768eb421259a90d15a5426ad10e8b5786e031ae3f1bddc91d5c9",
        "16427ca4b0210a8c143c9b68ec71153a64df9fd1127d68e9f4c664b9b2d234a4",
    ),
    "author_lifecycle_override": (
        "d5f8f3f273a2502d2264fc6b7816e54b0341135917bd6bf7bcb58f1966485c91",
        "9cd2e50329bf5ee20eb36e7c9b90b3fb2ebdf19a4bb54e5059d570cc3e7698ac",
    ),
    "revoke_lifecycle_override": (
        "566c150fcb0d60bde81b41eddd0846dfc22792b089c3fe7651d2b44e04db536e",
        "053598682fa30798841fcd3b6e86e8666fd3820a1996a57fd52cee2f18d73e96",
    ),
}

_PROTOCOL: Final = "PERFORM ops.lock_scoped_feature_write_protocol(true);"

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
        '415_state_lifecycle_protocol'
    ))
"""

_UPGRADE_STATEMENTS: Final[tuple[str, ...]] = (
    "SET ROLE ktm_feature_schema_owner",
    _RECEIPT_HEAD_CHECK_SQL,
    "SET ROLE ktm_feature_schema_owner",
)


def _with_protocol_entry(body: str) -> str:
    """기존 DDL 전체를 복제하지 않고 검토한 첫 BEGIN 위치만 엄격히 바꾼다."""
    if "lock_scoped_feature_write_protocol" in body:
        raise RuntimeError("legacy SQL fence changed; review migration inventory")
    before, separator, after = body.partition("\nBEGIN\n")
    if not separator:
        raise RuntimeError("legacy SQL entry is not the reviewed PL/pgSQL shape")
    return before + separator + "  " + _PROTOCOL + "\n" + after


def upgrade() -> None:
    bind = op.get_bind()
    rows = (
        bind.execute(
            text("""SELECT procedure.proname AS name,role.rolname AS owner,
            procedure.prosrc AS body,pg_get_functiondef(procedure.oid) AS definition,
            procedure.prokind::text AS prokind,procedure.prosecdef,language.lanname AS language,
            pg_get_function_identity_arguments(procedure.oid) AS signature
        FROM pg_proc procedure JOIN pg_namespace namespace ON namespace.oid=procedure.pronamespace
        JOIN pg_roles role ON role.oid=procedure.proowner
        JOIN pg_language language ON language.oid=procedure.prolang
        WHERE namespace.nspname='feature' AND procedure.proname=ANY(CAST(:names AS text[]))
        ORDER BY procedure.proname COLLATE "C"
        """),
            {"names": list(_LEGACY_OWNERS)},
        )
        .mappings()
        .all()
    )
    if len(rows) != len(_LEGACY_OWNERS) or {row["name"] for row in rows} != set(_LEGACY_OWNERS):
        raise RuntimeError("legacy SQL routine inventory differs from revision 414")
    replacements: list[tuple[str, str]] = []
    for row in rows:
        if (
            row["owner"] != _LEGACY_OWNERS[row["name"]]
            or row["prokind"] != "p"
            or not row["prosecdef"]
            or row["language"] != "plpgsql"
            or row["definition"].count(row["body"]) != 1
            or hashlib.sha256(row["signature"].encode()).hexdigest()
            != _EXPECTED_DEFINITIONS[row["name"]][0]
            or hashlib.sha256(row["body"].encode()).hexdigest()
            != _EXPECTED_DEFINITIONS[row["name"]][1]
        ):
            raise RuntimeError(
                "legacy SQL owner or definition changed: "
                + str(
                    {key: row[key] for key in ("name", "owner", "prokind", "prosecdef", "language")}
                )
            )
        body = _with_protocol_entry(row["body"])
        replacements.append((row["owner"], row["definition"].replace(row["body"], body, 1)))
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
    bind.execute(text("SET ROLE ktm_feature_schema_owner"))
    prior_create = bool(
        bind.scalar(
            text(
                "SELECT has_schema_privilege("
                "'ktm_feature_state_procedure_owner','feature','CREATE')"
            )
        )
    )
    # 대상과 protocol 함수의 owner가 같으므로 새 EXECUTE grant가 필요 없다.
    bind.execute(text("SET ROLE ktm_feature_state_procedure_owner"))
    bind.execute(text("SELECT ops.lock_scoped_feature_write_protocol(true)"))
    bind.execute(text("SET ROLE ktm_feature_schema_owner"))
    bind.execute(text("GRANT CREATE ON SCHEMA feature TO ktm_feature_state_procedure_owner"))
    for owner, definition in replacements:
        # owner는 위의 고정 whitelist와 실제 소유자가 일치할 때만 사용한다.
        bind.execute(text("SET ROLE " + owner))
        bind.execute(text(definition))
    bind.execute(text("SET ROLE ktm_feature_schema_owner"))
    if not prior_create:
        bind.execute(text("REVOKE CREATE ON SCHEMA feature FROM ktm_feature_state_procedure_owner"))
    # 정본 정적 gate도 전체 과거 허용 집합을 읽을 수 있게 명시한다.
    for statement in _UPGRADE_STATEMENTS:
        op.execute(statement)
    for name, value in settings.items():
        bind.execute(text("SELECT set_config(:name,:value,true)"), {"name": name, "value": value})
    op.execute("SET ROLE ktm_feature_schema_owner")


def downgrade() -> None:
    raise RuntimeError("forward-only migration")
