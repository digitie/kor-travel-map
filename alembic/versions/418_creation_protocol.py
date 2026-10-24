"""Feature 생성 core와 외부 writer의 첫 잠금을 protocol EX로 맞춘다."""

from __future__ import annotations

import hashlib
from typing import Final

from sqlalchemy import text

from alembic import op

revision: str = "418_creation_protocol"
down_revision: str | None = "417_protocol_ex_reentry"
branch_labels: str | None = None
depends_on: str | None = None

_LEGACY_OWNERS: Final[dict[str, str]] = {
    "approve_feature_request_with_initial_state": "ktm_feature_request_procedure_owner",
    "create_admin_manual_feature_with_initial_state": "ktm_manual_feature_procedure_owner",
    "create_feature_with_initial_state": "ktm_feature_state_procedure_owner",
    "create_provider_feature_with_initial_state": "ktm_feature_state_procedure_owner",
}

# fresh416 catalog와417 oracle의 같은 정본 정의를 고정한다.
_EXPECTED_DEFINITIONS: Final[dict[str, tuple[str, str]]] = {
    "approve_feature_request_with_initial_state": (
        "417804f39918559e21e9733be1a99817165b440fbbaeed176a2def5cde9d9a37",
        "7c519ca8e4d20a5121b1ad7ff0df194ea1782d30b5abc26f10061b054e44ec0f",
    ),
    "create_admin_manual_feature_with_initial_state": (
        "8c515b6ecf0fe6d6cbe111a0805bdbcdb19970206d3f5eaebfdd14933c412aaa",
        "90e5ec6ba1b09f3318f124c8dcaad3d430aa05e8046e5454cc0f80eef4e381cf",
    ),
    "create_feature_with_initial_state": (
        "d23c904e629075609c55e14d798dd7ce25d7eb28f27e9afbe33698af90304588",
        "5daff3a3ba54b7045be4ee6a19d043eac92f9a0e6a76291b3b0ed7057104d776",
    ),
    "create_provider_feature_with_initial_state": (
        "e7360a1cfa0eb08eb6f1f33081338dd467b633a0deb2f3a0403ea9c557da00a3",
        "d70559483bbbcde7aad19840f4c2fa9b712eacea12337fa72ad933536684d23e",
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
        '415_state_lifecycle_protocol',
        '416_field_override_protocol',
        '417_protocol_ex_reentry',
        '418_creation_protocol'
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
        raise RuntimeError("creation SQL routine inventory differs from revision 417")
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
    owners = sorted(set(_LEGACY_OWNERS.values()))
    prior_create = {
        owner: bool(
            bind.scalar(
                text("SELECT has_schema_privilege(:owner,'feature','CREATE')"), {"owner": owner}
            )
        )
        for owner in owners
    }
    # protocol 소유자로 배타 경계를 잡고 두 내부 owner의 함수 호출만 허용한다.
    bind.execute(text("SET ROLE ktm_feature_state_procedure_owner"))
    bind.execute(text("SELECT ops.lock_scoped_feature_write_protocol(true)"))
    bind.execute(text("SET ROLE ktm_feature_schema_owner"))
    bind.execute(
        text(
            "GRANT EXECUTE ON FUNCTION ops.lock_scoped_feature_write_protocol(boolean) "
            "TO ktm_manual_feature_procedure_owner,ktm_feature_request_procedure_owner"
        )
    )
    for owner in owners:
        bind.execute(text("GRANT CREATE ON SCHEMA feature TO " + owner))
    for owner, definition in replacements:
        # 고정 whitelist와 실제 catalog 소유자가 일치한 뒤에만 식별자로 쓴다.
        bind.execute(text("SET ROLE " + owner))
        bind.execute(text(definition))
    bind.execute(text("SET ROLE ktm_feature_schema_owner"))
    for owner in owners:
        if not prior_create[owner]:
            bind.execute(text("REVOKE CREATE ON SCHEMA feature FROM " + owner))
    # 정본 정적 gate도 전체 과거 허용 집합을 읽을 수 있게 명시한다.
    for statement in _UPGRADE_STATEMENTS:
        op.execute(statement)
    for name, value in settings.items():
        bind.execute(text("SELECT set_config(:name,:value,true)"), {"name": name, "value": value})
    op.execute("SET ROLE ktm_feature_schema_owner")


def downgrade() -> None:
    raise RuntimeError("forward-only migration")
