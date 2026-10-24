"""protocol EX 재진입은 xact 소유를 보장한 뒤 불필요한 GUC 조회를 생략한다."""

from __future__ import annotations

import hashlib
from typing import Final

from sqlalchemy import text

from alembic import op

revision: str = "417_protocol_ex_reentry"
down_revision: str | None = "416_field_override_protocol"
branch_labels: str | None = None
depends_on: str | None = None

_OWNER: Final = "ktm_feature_state_procedure_owner"
_EXPECTED_SIGNATURE_SHA256: Final = (
    "138a380968414ac41b828d34b98955f5af695c3741c49631e540683607ee83bd"
)
_EXPECTED_BODY_SHA256: Final = "b2985b46cf5f506595019a91b5351b3eb73a63575be96435008098f0d9a157a0"
_ENTRY_MARKER: Final = "    -- 두 정수의 고정 gate 한 개만 사용한다."
_FAST_REENTRY: Final = """    IF p_exclusive AND EXISTS (
        SELECT 1 FROM pg_locks WHERE locktype='advisory' AND pid=pg_backend_pid()
        AND classid=1369104691::oid AND objid=115::oid AND objsubid=2
        AND mode='ExclusiveLock' AND granted
    ) THEN
        -- pg_locks는 session/xact를 구별하지 않는다. 반드시 xact 소유를 덧붙인다.
        PERFORM pg_advisory_xact_lock(1369104691,115);
        RETURN;
    END IF;
"""

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
        '417_protocol_ex_reentry'
    ))
"""

_UPGRADE_STATEMENTS: Final[tuple[str, ...]] = (
    "SET ROLE ktm_feature_schema_owner",
    _RECEIPT_HEAD_CHECK_SQL,
    "SET ROLE ktm_feature_schema_owner",
)


def _with_fast_reentry(body: str) -> str:
    """검토된 NULL 검사 뒤 한 진입만 추가하고 원문 나머지는 보존한다."""
    if body.count(_ENTRY_MARKER) != 1 or _FAST_REENTRY in body:
        raise RuntimeError("protocol SQL shape changed; review reentry migration")
    return body.replace(_ENTRY_MARKER, _FAST_REENTRY + _ENTRY_MARKER, 1)


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
        WHERE namespace.nspname='ops' AND procedure.proname='lock_scoped_feature_write_protocol'
        ORDER BY procedure.proname COLLATE "C"
        """),
        )
        .mappings()
        .all()
    )
    if len(rows) != 1:
        raise RuntimeError("protocol SQL routine inventory differs from revision 416")
    replacements: list[tuple[str, str]] = []
    for row in rows:
        if (
            row["owner"] != _OWNER
            or row["prokind"] != "f"
            or not row["prosecdef"]
            or row["language"] != "plpgsql"
            or row["definition"].count(row["body"]) != 1
            or hashlib.sha256(row["signature"].encode()).hexdigest() != _EXPECTED_SIGNATURE_SHA256
            or hashlib.sha256(row["body"].encode()).hexdigest() != _EXPECTED_BODY_SHA256
        ):
            raise RuntimeError(
                "legacy SQL owner or definition changed: "
                + str(
                    {key: row[key] for key in ("name", "owner", "prokind", "prosecdef", "language")}
                )
            )
        body = _with_fast_reentry(row["body"])
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
            text("SELECT has_schema_privilege('ktm_feature_state_procedure_owner','ops','CREATE')")
        )
    )
    # 함수 소유자로 기존 protocol EX를 먼저 획득한다. 신규 EXECUTE grant는 없다.
    bind.execute(text("SET ROLE ktm_feature_state_procedure_owner"))
    bind.execute(text("SELECT ops.lock_scoped_feature_write_protocol(true)"))
    bind.execute(text("SET ROLE ktm_feature_schema_owner"))
    bind.execute(text("GRANT CREATE ON SCHEMA ops TO ktm_feature_state_procedure_owner"))
    for owner, definition in replacements:
        # owner는 위 고정 소유자와 실제 catalog가 일치할 때만 사용한다.
        bind.execute(text("SET ROLE " + owner))
        bind.execute(text(definition))
    bind.execute(text("SET ROLE ktm_feature_schema_owner"))
    if not prior_create:
        bind.execute(text("REVOKE CREATE ON SCHEMA ops FROM ktm_feature_state_procedure_owner"))
    # 정본 정적 gate도 전체 과거 허용 집합을 읽을 수 있게 명시한다.
    for statement in _UPGRADE_STATEMENTS:
        op.execute(statement)
    for name, value in settings.items():
        bind.execute(text("SELECT set_config(:name,:value,true)"), {"name": name, "value": value})
    op.execute("SET ROLE ktm_feature_schema_owner")


def downgrade() -> None:
    raise RuntimeError("forward-only migration")
