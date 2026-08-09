"""ADR-090 runtime table ACL reconciliation after an Alembic upgrade.

The dedicated bootstrap transfers application-object ownership to the NOLOGIN
schema owner *before* Alembic runs.  PostgreSQL default privileges are an
unsafe way to restore old broad writer access: a later state or audit table
would silently become mutable by API/Dagster.  Instead the migrator performs
this explicit, fail-closed reconciliation after every upgrade and before the
API process discards its migrator DSN.

Only the migrator LOGIN can enter ``ktm_feature_schema_owner``.  Runtime
LOGINs merely inherit the resulting table grants and cannot ``SET ROLE`` into
any owner/group role.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Mapping
from typing import cast

from sqlalchemy import text

from kortravelmap.infra.db import make_async_engine

__all__ = [
    "RuntimePrivilegeReconciliationError",
    "reconcile_runtime_privileges",
]


class RuntimePrivilegeReconciliationError(RuntimeError):
    """migrator가 ADR-090의 명시 ACL inventory를 만족하지 못했을 때의 오류."""


_RUNTIME_ROLE = "ktm_feature_runtime"
_MIGRATOR_ROLE = "ktm_feature_migrator"
_SCHEMA_OWNER_ROLE = "ktm_feature_schema_owner"

# feature schema에는 procedure-only state/audit object가 섞여 있다. 이 map은
# runtime이 직접 접근하는 table만 이름으로 허용한다. 새 feature table은 이 목록을
# 의도적으로 갱신하기 전까지 deployment를 막는다.
_FEATURE_TABLE_PRIVILEGES: Mapping[str, tuple[str, ...]] = {
    "curated_features": ("SELECT", "INSERT", "UPDATE", "DELETE"),
    "curated_feature_detail_snapshots": ("SELECT", "INSERT", "UPDATE", "DELETE"),
    "curated_source_rules": ("SELECT", "INSERT", "UPDATE", "DELETE"),
    "curated_sources": ("SELECT", "INSERT", "UPDATE", "DELETE"),
    "curated_themes": ("SELECT", "INSERT", "UPDATE", "DELETE"),
    "curated_tripmate_copy_snapshots": ("SELECT", "INSERT", "UPDATE", "DELETE"),
    "curation_collections": ("SELECT", "INSERT", "UPDATE", "DELETE"),
    "curation_import_batches": ("SELECT", "INSERT", "UPDATE", "DELETE"),
    "curation_import_rows": ("SELECT", "INSERT", "UPDATE", "DELETE"),
    "curation_items": ("SELECT", "INSERT", "UPDATE", "DELETE"),
    "curation_link_decisions": ("SELECT", "INSERT", "UPDATE", "DELETE"),
    "current_price_summary": ("SELECT", "INSERT", "UPDATE", "DELETE"),
    "current_weather_summary": ("SELECT", "INSERT", "UPDATE", "DELETE"),
    "feature_aliases": ("SELECT",),
    "feature_events": ("SELECT", "INSERT", "UPDATE", "DELETE"),
    "feature_notices": ("SELECT", "INSERT", "UPDATE", "DELETE"),
    "feature_places": ("SELECT", "INSERT", "UPDATE", "DELETE"),
    "feature_price_values": ("SELECT", "INSERT"),
    "feature_weather_values": ("SELECT", "INSERT"),
    "weather_metric_series": ("SELECT", "INSERT", "UPDATE", "DELETE"),
}

# Route/area geometry is the sole cross-relation public index case.  Keep the
# runtime grant column-scoped so it cannot make the DB-owned ``public_ready``
# cache stale (T-VN-34B).  These tables intentionally do not use the broad
# feature table inventory above.
_ROUTE_AREA_RUNTIME_COLUMNS: Mapping[str, tuple[str, ...]] = {
    "feature_routes": (
        "feature_id",
        "feature_uuid",
        "kind",
        "geom",
        "route_type",
        "geometry_source",
        "geometry_status",
        "total_distance_meters",
        "expected_duration_minutes",
        "difficulty",
        "begin_name",
        "begin_address",
        "end_name",
        "end_address",
        "payload",
    ),
    "feature_areas": (
        "feature_id",
        "feature_uuid",
        "kind",
        "geom",
        "area_kind",
        "boundary_source",
        "area_square_meters",
        "regulation_scope",
        "administrative_office",
        "description",
        "payload",
    ),
}

_ROUTE_AREA_RUNTIME_GRANTS = tuple(
    statement
    for relation, columns in _ROUTE_AREA_RUNTIME_COLUMNS.items()
    for statement in (
        f"GRANT SELECT ON feature.{relation} TO ktm_feature_runtime",
        f"GRANT INSERT ({', '.join(columns)}) ON feature.{relation} "
        "TO ktm_feature_runtime",
        f"GRANT UPDATE ({', '.join(columns)}) ON feature.{relation} "
        "TO ktm_feature_runtime",
        f"GRANT DELETE ON feature.{relation} TO ktm_feature_runtime",
        f"GRANT SELECT (feature_id, public_ready), UPDATE (public_ready) "
        f"ON feature.{relation} "
        "TO ktm_feature_state_procedure_owner",
    )
)

# Provider/ops schemas contain ordinary application data, not state/audit
# evidence.  Existing repositories use their complete current table surface;
# granting only DML (never CREATE/ALTER/TRUNCATE/ownership) maintains that
# boundary after ownership transfer.  No ALTER DEFAULT PRIVILEGES is used:
# this reconciler grants a newly-created table only during a deliberate startup
# migration pass, never when a state/audit relation happens to be created.
_ORDINARY_SCHEMA_PRIVILEGES: Mapping[str, tuple[str, ...]] = {
    "provider_sync": ("SELECT", "INSERT", "UPDATE", "DELETE"),
    "ops": ("SELECT", "INSERT", "UPDATE", "DELETE"),
}

# `ops.feature_overrides` can keep a provider-retired Feature from being
# reactivated.  It is not ordinary ops data: runtime must only observe it
# directly.  A typed state-owner procedure owns author/revoke mutation so a
# provider/admin connection cannot erase that fence through raw SQL.
_OPS_TABLE_PRIVILEGES: Mapping[str, tuple[str, ...]] = {
    "feature_overrides": ("SELECT",),
}

_PROTECTED_FEATURE_TABLES = frozenset({"features", "feature_state_transitions", "feature_versions"})
_PROTECTED_FEATURE_SEQUENCES = frozenset({"feature_state_transitions_transition_id_seq"})

_APPLICATION_RELATIONS_SQL = text(
    """
    SELECT namespace.nspname AS schema_name, relation.relname AS relation_name,
           relation.relkind AS relation_kind
    FROM pg_catalog.pg_class AS relation
    JOIN pg_catalog.pg_namespace AS namespace
      ON namespace.oid = relation.relnamespace
    WHERE namespace.nspname IN ('feature', 'provider_sync', 'ops')
      AND relation.relkind IN ('r', 'p', 'S')
    ORDER BY namespace.nspname, relation.relkind, relation.relname
    """
)

_CORE_FEATURE_GRANTS = (
    "GRANT USAGE ON SCHEMA feature, provider_sync, ops, x_extension TO ktm_feature_runtime",
    "GRANT SELECT, UPDATE ("
    "kind, name, category, coord, coord_precision_digits, address, "
    "legal_dong_code, road_name_code, road_address_management_no, "
    "admin_dong_code, sido_code, sigungu_code, urls, marker_icon, marker_color, "
    "parent_feature_id, sibling_group_id, raw_refs, created_at, updated_at"
    ") ON feature.features TO ktm_feature_runtime",
    "GRANT SELECT ON feature.feature_state_transitions TO ktm_feature_runtime",
)

_STATE_OWNER_FUNCTION_ACL = (
    "REVOKE ALL ON FUNCTION feature.prepare_feature_state_context(jsonb, text) "
    "FROM PUBLIC, ktm_feature_runtime",
    "REVOKE ALL ON PROCEDURE feature.create_feature_with_initial_state("
    "jsonb, text, text, text, jsonb) FROM PUBLIC",
    "REVOKE ALL ON PROCEDURE feature.transition_feature_state("
    "text, text, text, text, bigint, jsonb) FROM PUBLIC",
    "REVOKE ALL ON PROCEDURE feature.materialize_user_feature_change_provenance("
    "text, text, uuid, text, text, bigint) FROM PUBLIC",
    "REVOKE ALL ON PROCEDURE feature.author_lifecycle_override("
    "text, text, text, boolean, text, text, bigint) FROM PUBLIC",
    "REVOKE ALL ON PROCEDURE feature.revoke_lifecycle_override("
    "text, text, bigint) FROM PUBLIC",
    "REVOKE ALL ON PROCEDURE feature.materialize_provider_feature_version("
    "text) FROM PUBLIC",
    "GRANT EXECUTE ON PROCEDURE feature.create_feature_with_initial_state("
    "jsonb, text, text, text, jsonb) TO ktm_feature_runtime",
    "GRANT EXECUTE ON PROCEDURE feature.transition_feature_state("
    "text, text, text, text, bigint, jsonb) TO ktm_feature_runtime",
    "GRANT EXECUTE ON PROCEDURE feature.materialize_user_feature_change_provenance("
    "text, text, uuid, text, text, bigint) TO ktm_feature_runtime",
    "GRANT EXECUTE ON PROCEDURE feature.author_lifecycle_override("
    "text, text, text, boolean, text, text, bigint) TO ktm_feature_runtime",
    "GRANT EXECUTE ON PROCEDURE feature.revoke_lifecycle_override("
    "text, text, bigint) TO ktm_feature_runtime",
    "GRANT EXECUTE ON PROCEDURE feature.materialize_provider_feature_version("
    "text) TO ktm_feature_runtime",
)

_AUDIT_WRITER_FUNCTION_ACL = (
    "REVOKE ALL ON FUNCTION feature.write_feature_state_transition() "
    "FROM PUBLIC, ktm_feature_runtime",
    "REVOKE ALL ON FUNCTION feature.reject_feature_state_transition_mutation() "
    "FROM PUBLIC, ktm_feature_runtime",
)

_SUBTYPE_READY_FUNCTION_ACL = (
    "REVOKE ALL ON FUNCTION feature.derive_subtype_public_ready() "
    "FROM PUBLIC, ktm_feature_runtime",
    "REVOKE ALL ON FUNCTION feature.sync_subtype_public_ready() "
    "FROM PUBLIC, ktm_feature_runtime",
)


def _quote_identifier(value: str) -> str:
    """closed inventory name을 PostgreSQL identifier로 rendering한다."""

    return '"' + value.replace('"', '""') + '"'


def _grant_sql(*, schema: str, relation: str, privileges: tuple[str, ...]) -> str:
    return (
        f"GRANT {', '.join(privileges)} ON TABLE "
        f"{_quote_identifier(schema)}.{_quote_identifier(relation)} "
        f"TO {_quote_identifier(_RUNTIME_ROLE)}"
    )


def _sequence_grant_sql(*, schema: str, relation: str) -> str:
    return (
        "GRANT USAGE, SELECT ON SEQUENCE "
        f"{_quote_identifier(schema)}.{_quote_identifier(relation)} "
        f"TO {_quote_identifier(_RUNTIME_ROLE)}"
    )


def _runtime_relation_grants(
    rows: list[Mapping[str, object]],
) -> tuple[list[str], list[str]]:
    """catalog relation inventory를 ACL SQL와 fail-closed unknown 목록으로 바꾼다."""

    grants: list[str] = []
    unknown_feature_relations: list[str] = []
    for row in rows:
        schema = str(row["schema_name"])
        relation = str(row["relation_name"])
        raw_relation_kind = row["relation_kind"]
        # PostgreSQL ``char`` (pg_class.relkind) is returned as ``bytes`` by
        # asyncpg on some builds. ``str(b'S')`` would be ``"b'S'"`` and route
        # the audit sequence into the feature-table unknown-policy path.
        relation_kind = (
            raw_relation_kind.decode("ascii")
            if isinstance(raw_relation_kind, bytes)
            else str(raw_relation_kind)
        )
        if relation_kind == "S":
            if schema == "feature" and (
                relation in _PROTECTED_FEATURE_SEQUENCES
                or relation.startswith("feature_state_transitions_")
            ):
                continue
            grants.append(_sequence_grant_sql(schema=schema, relation=relation))
            continue
        if schema == "feature":
            if relation in _PROTECTED_FEATURE_TABLES:
                continue
            if relation in _ROUTE_AREA_RUNTIME_COLUMNS:
                continue
            privileges = _FEATURE_TABLE_PRIVILEGES.get(relation)
            if privileges is None:
                unknown_feature_relations.append(f"feature.{relation}")
                continue
        else:
            privileges = _OPS_TABLE_PRIVILEGES.get(
                relation,
                _ORDINARY_SCHEMA_PRIVILEGES[schema],
            )
        grants.append(_grant_sql(schema=schema, relation=relation, privileges=privileges))
    return grants, unknown_feature_relations


async def reconcile_runtime_privileges() -> None:
    """migrator session에서 state/audit 안전 ACL을 post-upgrade로 재조정한다."""

    migrator_dsn = os.environ.get("KOR_TRAVEL_MAP_PG_DSN")
    if not migrator_dsn:
        raise RuntimePrivilegeReconciliationError(
            "KOR_TRAVEL_MAP_PG_DSN migrator DSN is required for runtime ACL reconciliation"
        )
    engine = make_async_engine(migrator_dsn, pool_size=1)
    try:
        async with engine.begin() as connection:
            identity = (await connection.execute(text("SELECT session_user::text"))).scalar_one()
            if identity != _MIGRATOR_ROLE:
                raise RuntimePrivilegeReconciliationError(
                    "runtime ACL reconciliation requires the dedicated "
                    f"{_MIGRATOR_ROLE} login, not {identity!r}"
                )
            await connection.execute(text(f"SET ROLE {_SCHEMA_OWNER_ROLE}"))
            # Clear stale broad grants left by the pre-ADR-090 bootstrap owner
            # before applying the closed inventory.  This makes a bootstrap of
            # an already-migrated DB safe as well as a fresh DB.
            await connection.execute(
                text(
                    "REVOKE ALL ON ALL TABLES IN SCHEMA feature, provider_sync, ops "
                    "FROM ktm_feature_runtime"
                )
            )
            await connection.execute(
                text(
                    "REVOKE ALL ON ALL SEQUENCES IN SCHEMA feature, provider_sync, ops "
                    "FROM ktm_feature_runtime"
                )
            )
            rows = list((await connection.execute(_APPLICATION_RELATIONS_SQL)).mappings().all())
            grants, unknown_feature_relations = _runtime_relation_grants(
                [cast(Mapping[str, object], row) for row in rows]
            )
            if unknown_feature_relations:
                raise RuntimePrivilegeReconciliationError(
                    "new feature relation has no deliberate runtime ACL policy: "
                    + ", ".join(unknown_feature_relations)
                )
            for statement in grants:
                await connection.execute(text(statement))
            for statement in _CORE_FEATURE_GRANTS:
                await connection.execute(text(statement))
            for statement in _ROUTE_AREA_RUNTIME_GRANTS:
                await connection.execute(text(statement))

            # Routine ownership is deliberately split from table ownership.
            # The schema owner has SET-only membership in each NOLOGIN routine
            # owner; runtime identities never receive this path.
            await connection.execute(text("SET ROLE ktm_feature_state_procedure_owner"))
            for statement in _STATE_OWNER_FUNCTION_ACL:
                await connection.execute(text(statement))
            for statement in _SUBTYPE_READY_FUNCTION_ACL:
                await connection.execute(text(statement))
            await connection.execute(text("SET ROLE ktm_feature_audit_writer"))
            for statement in _AUDIT_WRITER_FUNCTION_ACL:
                await connection.execute(text(statement))
    finally:
        await engine.dispose()


def main() -> None:
    """API entrypoint가 Alembic 직후 호출하는 CLI module entrypoint."""

    asyncio.run(reconcile_runtime_privileges())


if __name__ == "__main__":  # pragma: no cover - shell entrypoint가 호출
    main()
