"""직접 호출하는 기존 curation/policy SQL의 첫 잠금을 protocol EX로 고정한다."""

from __future__ import annotations

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
_GLOBAL_FENCE: Final = (
    "PERFORM pg_advisory_xact_lock(hashtextextended('feature-curation-write', 0));"
)
_PROTOCOL: Final = "PERFORM ops.lock_scoped_feature_write_protocol(true);"


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
            procedure.prokind::text AS prokind,procedure.prosecdef,language.lanname AS language
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
        ):
            raise RuntimeError(
                "legacy SQL owner or definition changed: "
                + str(
                    {key: row[key] for key in ("name", "owner", "prokind", "prosecdef", "language")}
                )
            )
        body = _with_protocol_entry(row["body"])
        replacements.append((row["owner"], row["definition"].replace(row["body"], body, 1)))
    settings = dict(
        bind.execute(
            text(
                "SELECT name,setting FROM pg_settings "
                "WHERE name IN ('lock_timeout','statement_timeout')"
            )
        ).all()
    )
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
    # 배포 receipt의 기존 허용 head는 제거하지 않고 현재 head만 확장한다.
    from importlib.util import module_from_spec, spec_from_file_location
    from pathlib import Path

    path = Path(__file__).with_name("412_provider_scalar_projection.py")
    spec = spec_from_file_location("_map_412_receipt", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("revision 412 receipt definition is unavailable")
    previous = module_from_spec(spec)
    spec.loader.exec_module(previous)
    receipt = previous._RECEIPT_HEAD_CHECK_SQL
    marker = "'412_provider_scalar_projection'\n"
    if receipt.count(marker) != 1:
        raise RuntimeError("revision 412 receipt definition changed")
    bind.execute(
        text(
            receipt.replace(
                marker, "'412_provider_scalar_projection',\n        '" + revision + "'\n"
            )
        )
    )
    for name, value in settings.items():
        bind.execute(text("SELECT set_config(:name,:value,true)"), {"name": name, "value": value})
    op.execute("SET ROLE ktm_feature_schema_owner")


def downgrade() -> None:
    raise RuntimeError("forward-only migration")
