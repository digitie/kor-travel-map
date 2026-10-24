"""직접 호출하는 기존 curation/policy SQL의 첫 잠금을 protocol EX로 고정한다."""

from __future__ import annotations

import hashlib
from typing import Final

from sqlalchemy import text

from alembic import op

revision: str = "413_legacy_sql_protocol_entry"
down_revision: str | None = "412_provider_scalar_projection"
branch_labels: str | None = None
depends_on: str | None = None

_LEGACY_OWNERS: Final[dict[str, str]] = {
    "archive_curation_item_command": "ktm_curation_command_owner",
    "create_curation_item_command": "ktm_curation_command_owner",
    "create_manual_curation_item_with_feature_command": "ktm_curation_command_owner",
    "finalize_provider_curation_root": "ktm_curation_command_owner",
    "patch_curation_item_command": "ktm_curation_command_owner",
    "reclassify_curation_quarantine_command": "ktm_curation_command_owner",
    "register_provider_field_shadow_policy": "ktm_feature_schema_owner",
}

# 412의 실제 head oracle에서 산출한 signature/body 정본이다. 임의 로컬 DDL은 수용하지 않는다.
_EXPECTED_DEFINITIONS: Final[dict[str, tuple[str, str]]] = {
    "archive_curation_item_command": (
        "0d2076967e73f7d48cc11cd9aa89f58839bccb3e2a5b6f4490963f2e3b743058",
        "18a93ca46a4e025bff1217e92d2c87b587ed87847e626f59194c23c44c3a9bb5",
    ),
    "create_curation_item_command": (
        "87578c60cf9f3e8ae6a03242bd51fe3834137bcf4f2165925987a66acd868d12",
        "5dcef22de66898d53d7426a9899525abe6ae121bd028592b8143732c172f70a4",
    ),
    "create_manual_curation_item_with_feature_command": (
        "fc3d1a71c6f6929c7f27ae21a948b62c54e44de3488ef6e2a712a7e7a70098f5",
        "a862453d708499e4527f1fed000564da6223b55d6ab6499aaa42066a98d901df",
    ),
    "finalize_provider_curation_root": (
        "c3ed2a4d1cd7b51d3fd8dbfc5683bc9c1063a818d732d510dab95ebd952bdf6a",
        "60adcade83c06c01e3900fb618f112c1edfdf0fb74eeb36fbc2098cde8c66e7d",
    ),
    "patch_curation_item_command": (
        "1de57bf9dcf8035df2779002c6309cf24a6ba35126deee10e59b91e65652d7a9",
        "47775ed61231258439b427863aae3948b06ebcb4204e0470cc93c7c1e5dc20db",
    ),
    "reclassify_curation_quarantine_command": (
        "187b1fee3ccc3f12ffc9e4ac52c68c55a810eda6a05e5cd216984b882c91f1b1",
        "dff5e68db7043769db7529ff34bc6212658a89735ee51d485f432bfec773ca3e",
    ),
    "register_provider_field_shadow_policy": (
        "6abd02f62327bdae2474b07c0202af520e8142eea68bd12b21cbc408a5655c2b",
        "60b8af159dd59afa128316c4d4dffee45c1d935953b771b888c156ec5af971b1",
    ),
}

_GLOBAL_FENCE: Final = (
    "PERFORM pg_advisory_xact_lock(hashtextextended('feature-curation-write', 0));"
)
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
        '413_legacy_sql_protocol_entry'
    ))
"""

_UPGRADE_STATEMENTS: Final[tuple[str, ...]] = (
    "SET ROLE ktm_feature_schema_owner",
    _RECEIPT_HEAD_CHECK_SQL,
    "SET ROLE ktm_feature_schema_owner",
)


def _with_protocol_entry(body: str) -> str:
    """기존 DDL 전체를 복제하지 않고 검토한 첫 BEGIN 위치만 엄격히 바꾼다."""
    if body.count(_GLOBAL_FENCE) != 1 or "lock_scoped_feature_write_protocol" in body:
        raise RuntimeError("legacy SQL fence changed; review migration inventory")
    before, separator, after = body.partition("\nBEGIN\n")
    if not separator or _GLOBAL_FENCE in before:
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
        raise RuntimeError("legacy SQL routine inventory differs from revision 412")
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
            text("SELECT has_schema_privilege('ktm_curation_command_owner','feature','CREATE')")
        )
    )
    bind.execute(text("SET ROLE ktm_feature_state_procedure_owner"))
    bind.execute(
        text("""GRANT EXECUTE ON FUNCTION ops.lock_scoped_feature_write_protocol(boolean)
        TO ktm_feature_schema_owner,ktm_curation_command_owner""")
    )
    bind.execute(text("SELECT ops.lock_scoped_feature_write_protocol(true)"))
    bind.execute(text("SET ROLE ktm_feature_schema_owner"))
    bind.execute(text("GRANT CREATE ON SCHEMA feature TO ktm_curation_command_owner"))
    for owner, definition in replacements:
        # owner는 위의 고정 whitelist와 실제 소유자가 일치할 때만 사용한다.
        bind.execute(text("SET ROLE " + owner))
        bind.execute(text(definition))
    bind.execute(text("SET ROLE ktm_feature_schema_owner"))
    if not prior_create:
        bind.execute(text("REVOKE CREATE ON SCHEMA feature FROM ktm_curation_command_owner"))
    # 정본 정적 gate도 전체 과거 허용 집합을 읽을 수 있게 명시한다.
    for statement in _UPGRADE_STATEMENTS:
        op.execute(statement)
    for name, value in settings.items():
        bind.execute(text("SELECT set_config(:name,:value,true)"), {"name": name, "value": value})
    op.execute("SET ROLE ktm_feature_schema_owner")


def downgrade() -> None:
    raise RuntimeError("forward-only migration")
