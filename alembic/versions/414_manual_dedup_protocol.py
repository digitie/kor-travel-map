"""M05 후보 기록·판정의 Feature→source 역순을 protocol-first로 격리한다."""

from __future__ import annotations

import hashlib
from typing import Final

from sqlalchemy import text

from alembic import op

revision: str = "414_manual_dedup_protocol"
down_revision: str | None = "413_legacy_sql_protocol_entry"
branch_labels: str | None = None
depends_on: str | None = None

_LEGACY_OWNERS: Final[dict[str, str]] = {
    "record_manual_provider_dedup_candidate": "ktm_manual_provider_dedup_procedure_owner",
    "resolve_manual_provider_dedup_case": "ktm_manual_provider_dedup_procedure_owner",
    "resolve_manual_provider_dedup_case_v2": "ktm_manual_provider_dedup_procedure_owner",
}

# 413 실제 head oracle의 signature/body 정본. 기존 설정·ACL은 재작성하지 않는다.
_EXPECTED_DEFINITIONS: Final[dict[str, tuple[str, str]]] = {
    "record_manual_provider_dedup_candidate": (
        "c09b16b2b56167acc6d3e1083b1cd73a93a85720593ccff8bb7891f0c0525b30",
        "8470151afd5e2416bc1528d5d070f1d89f909869a4043fc3e7efcfc21e33fd2e",
    ),
    "resolve_manual_provider_dedup_case": (
        "85f1c55a8feab8fea45a5c87109b1b1344161f3953d8fc25664fb0f30c34ea2b",
        "8f9ff620b815f2af732ef2a9a970633526f440cda8edee67f045360a927a0393",
    ),
    "resolve_manual_provider_dedup_case_v2": (
        "85f1c55a8feab8fea45a5c87109b1b1344161f3953d8fc25664fb0f30c34ea2b",
        "2cab903b68c0620319ccbdd2d294af6efe4264d38a106b327e8ae2e420049da2",
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
        '414_manual_dedup_protocol'
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
        raise RuntimeError("legacy SQL routine inventory differs from revision 413")
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
                "'ktm_manual_provider_dedup_procedure_owner','feature','CREATE')"
            )
        )
    )
    bind.execute(text("SET ROLE ktm_feature_state_procedure_owner"))
    bind.execute(
        text("""GRANT EXECUTE ON FUNCTION ops.lock_scoped_feature_write_protocol(boolean)
        TO ktm_manual_provider_dedup_procedure_owner""")
    )
    bind.execute(text("SELECT ops.lock_scoped_feature_write_protocol(true)"))
    bind.execute(text("SET ROLE ktm_feature_schema_owner"))
    bind.execute(
        text("GRANT CREATE ON SCHEMA feature TO ktm_manual_provider_dedup_procedure_owner")
    )
    for owner, definition in replacements:
        # owner는 위의 고정 whitelist와 실제 소유자가 일치할 때만 사용한다.
        bind.execute(text("SET ROLE " + owner))
        bind.execute(text(definition))
    bind.execute(text("SET ROLE ktm_feature_schema_owner"))
    if not prior_create:
        bind.execute(
            text("REVOKE CREATE ON SCHEMA feature FROM ktm_manual_provider_dedup_procedure_owner")
        )
    # 정본 정적 gate도 전체 과거 허용 집합을 읽을 수 있게 명시한다.
    for statement in _UPGRADE_STATEMENTS:
        op.execute(statement)
    for name, value in settings.items():
        bind.execute(text("SELECT set_config(:name,:value,true)"), {"name": name, "value": value})
    op.execute("SET ROLE ktm_feature_schema_owner")


def downgrade() -> None:
    raise RuntimeError("forward-only migration")
