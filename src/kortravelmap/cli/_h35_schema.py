"""H35 Map helper의 0063→0078 schema preflight, migration, verification."""

from __future__ import annotations

import asyncio
import io
import os
import unicodedata
from collections.abc import Mapping, Sequence
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Final

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from alembic import command
from kortravelmap.cli._h35_catalog import (
    EXPECTED_CATALOG_FINGERPRINTS,
    catalog_fingerprints,
    collect_catalog_objects,
)
from kortravelmap.cli._h35_contract import (
    H35IdentityError,
    H35Request,
    JsonValue,
    Receipt,
    all_pass,
    bind_database_identity,
    check,
    receipt,
)
from kortravelmap.infra.curation_link_basis import trusted_basis_sql
from kortravelmap.infra.db import make_async_engine

PRE_SCHEMA: Final = "0063_pipeline_root_id"
TARGET_SCHEMA: Final = "0078_cache_target_gc_observe"
EXPECTED_PRE_PUBLIC: Final = 3_265
EXPECTED_MIGRATED_PUBLIC: Final = 3_043
EXPECTED_POST_PUBLIC: Final = 3_265
_ALEMBIC_CONFIG_PATH: Final = Path("alembic.ini")

_CANONICAL_WHITESPACE: Final = "".join(
    chr(codepoint)
    for codepoint in (
        32,
        9,
        10,
        11,
        12,
        13,
        28,
        29,
        30,
        31,
        133,
        160,
        5760,
        8192,
        8193,
        8194,
        8195,
        8196,
        8197,
        8198,
        8199,
        8200,
        8201,
        8202,
        8232,
        8233,
        8239,
        8287,
        12288,
    )
)
_REVISION_CHAIN: Final = (
    PRE_SCHEMA,
    "0064_price_series_identity",
    "0065_curation_source_presence",
    "0066_curation_component_identity",
    "0067_integrity_dedupe_key",
    "0068_integrity_last_seen",
    "0069_weather_series_catalog",
    "0070_domain_command_ledger",
    "0071_integrity_observations",
    "0072_curation_provenance",
    "0073_curation_source_rule",
    "0074_curation_item_rekey_cascade",
    "0075_cache_target_outbox",
    "0076_cache_target_receipt",
    "0077_cache_target_snapshot_gc",
    TARGET_SCHEMA,
)
_REVISION_ORDER: Final = {revision: index for index, revision in enumerate(_REVISION_CHAIN)}
_PRICE_PARTIAL: Final = frozenset({"idx_price_values_feature_observed_identity"})
_INTEGRITY_PARTIAL: Final = frozenset(
    {
        "idx_violations_status_seen",
        "idx_violations_provider_status_seen",
        "idx_violations_feature_seen",
    }
)
_WEATHER_PARTIAL: Final = frozenset(
    {
        "idx_weather_values_feature_effective",
        "idx_features_public_weather_coord_5179_gist",
    }
)
_PARTIAL_INDEXES: Final = _PRICE_PARTIAL | _INTEGRITY_PARTIAL | _WEATHER_PARTIAL
_OLD_PRICE: Final = "idx_price_values_feature_product_observed"
_OLD_INTEGRITY: Final = (
    "idx_violations_status_detected",
    "idx_violations_provider_status_detected",
    "idx_violations_feature_detected",
)
_NEW_INTEGRITY: Final = (
    "idx_violations_status_seen",
    "idx_violations_provider_status_seen",
    "idx_violations_feature_seen",
)
_WEATHER_SEQUENCE: Final = (
    "idx_weather_values_feature_effective",
    "idx_features_public_weather_coord_5179_gist",
)
_ALLOWED_INVALID_BY_REVISION: Final = {
    PRE_SCHEMA: _PRICE_PARTIAL,
    "0067_integrity_dedupe_key": _INTEGRITY_PARTIAL,
    "0068_integrity_last_seen": _WEATHER_PARTIAL,
}
_MIGRATION_OUTPUT_LIMIT: Final = 16_384
_INDEX_SIGNATURES: Final[dict[str, tuple[str, ...]]] = {
    "idx_price_values_feature_product_observed": (
        "on feature.feature_price_values using btree",
        "(feature_id, price_domain, product_key, observed_at desc)",
    ),
    "idx_price_values_feature_observed_identity": (
        "on feature.feature_price_values using btree",
        "(feature_id, observed_at desc, provider, price_domain, product_key)",
    ),
    "idx_violations_status_detected": (
        "on ops.data_integrity_violations using btree",
        "(status, detected_at desc, issue_id desc)",
    ),
    "idx_violations_status_seen": (
        "on ops.data_integrity_violations using btree",
        "(status, last_seen_at desc, issue_id desc)",
    ),
    "idx_violations_provider_status_detected": (
        "(provider, status, detected_at desc, issue_id desc)",
        "where (provider is not null)",
    ),
    "idx_violations_provider_status_seen": (
        "(provider, status, last_seen_at desc, issue_id desc)",
        "where (provider is not null)",
    ),
    "idx_violations_feature_detected": (
        "(feature_id, detected_at desc, issue_id desc)",
        "where (feature_id is not null)",
    ),
    "idx_violations_feature_seen": (
        "(feature_id, last_seen_at desc, issue_id desc)",
        "where (feature_id is not null)",
    ),
    "idx_weather_values_feature_effective": (
        "on feature.feature_weather_values using btree",
        "(feature_id, provider, weather_domain, forecast_style, metric_key",
        "coalesce(valid_at, observed_at, valid_from, issued_at)",
    ),
    "idx_features_public_weather_coord_5179_gist": (
        "on feature.features using gist (coord_5179)",
        "kind = 'weather'::text",
        "coord_5179 is not null",
    ),
}


def _dsn() -> str:
    value = os.environ.get("KOR_TRAVEL_MAP_PG_DSN")
    if not value:
        raise RuntimeError("database_configuration_missing")
    return value


def _engine() -> AsyncEngine:
    return make_async_engine(
        _dsn(),
        pool_size=1,
        max_overflow=0,
        server_settings={
            "application_name": "kor-travel-map-h35-helper",
            "lock_timeout": "5s",
        },
    )


def image_revision_check(request: H35Request) -> dict[str, JsonValue]:
    return check(
        "candidate_image_source_revision",
        expected=request.source_revision,
        observed=os.environ.get("KOR_TRAVEL_MAP_IMAGE_REVISION", ""),
    )


def _repository_head() -> str:
    config = Config(str(_ALEMBIC_CONFIG_PATH))
    heads = ScriptDirectory.from_config(config).get_heads()
    return heads[0] if len(heads) == 1 else ",".join(sorted(heads))


async def _current_schema(connection: AsyncConnection) -> str:
    value = await connection.scalar(text("SELECT version_num FROM alembic_version"))
    return str(value) if value is not None else "missing"


async def _bind_live_database_identity(
    connection: AsyncConnection,
    request: H35Request,
) -> tuple[H35Request, dict[str, JsonValue]]:
    row = (
        (
            await connection.execute(
                text(
                    "SELECT current_database() AS database_name, "
                    "(pg_control_system()).system_identifier::text AS system_identifier, "
                    "(SELECT count(*) FROM alembic_version) AS alembic_rows"
                )
            )
        )
        .mappings()
        .one()
    )
    if int(row["alembic_rows"]) != 1:
        raise H35IdentityError("alembic_version_cardinality_invalid")
    return bind_database_identity(
        request,
        database=str(row["database_name"]),
        system_identifier=str(row["system_identifier"]),
    )


def _public_count_sql(*, migrated: bool) -> str:
    link_predicate = (
        "AND EXISTS (SELECT 1 FROM feature.curation_link_decisions AS decision "
        "WHERE decision.decision_id = item.accepted_link_decision_id "
        "AND decision.curation_item_id = item.curation_item_id "
        "AND decision.feature_id = item.feature_id "
        "AND decision.decision_kind = 'accepted' "
        f"AND {trusted_basis_sql('decision.match_basis')})"
        if migrated
        else "AND item.feature_id IS NOT NULL"
    )
    return f"""
        SELECT count(*)::bigint
        FROM feature.curation_items AS item
        JOIN feature.curation_collections AS collection
          ON collection.collection_id = item.collection_id
        JOIN feature.curated_themes AS theme ON theme.theme_id = collection.theme_id
        WHERE item.archived_at IS NULL AND collection.archived_at IS NULL
          AND item.status = 'included' AND collection.status = 'published'
          AND collection.visibility = 'public' AND theme.visibility = 'public'
          {link_predicate}
    """


async def _public_count(connection: AsyncConnection, *, migrated: bool) -> int:
    return int((await connection.scalar(text(_public_count_sql(migrated=migrated)))) or 0)


def _canonical_identity_issues(value: object, *, maximum: int) -> set[str]:
    issues: set[str] = set()
    if not isinstance(value, str) or not value:
        return {"identity"}
    if value.strip(_CANONICAL_WHITESPACE) != value:
        issues.add("trim")
    if unicodedata.normalize("NFC", value) != value:
        issues.add("nfc")
    if len(value) > maximum:
        issues.add("length")
    return issues


def _scope_issue_kinds(scope: object) -> set[str]:
    if not isinstance(scope, dict) or any(not isinstance(key, str) for key in scope):
        return {"check"}
    required = {"type", "external_system", "target_keys", "scope_mode"}
    if not required <= set(scope) or set(scope) - (required | {"radius_km"}):
        return {"check"}
    issues = _canonical_identity_issues(scope.get("external_system"), maximum=112)
    if scope.get("type") != "cache_target_keys":
        issues.add("check")
    if scope.get("scope_mode") not in {"center_radius", "sigungu_by_radius"}:
        issues.add("check")
    keys = scope.get("target_keys")
    if not isinstance(keys, list) or len(keys) > 500:
        issues.add("check")
    else:
        seen: set[str] = set()
        for key in keys:
            issues.update(_canonical_identity_issues(key, maximum=512))
            if isinstance(key, str):
                if key in seen:
                    issues.add("identity")
                seen.add(key)
    if "radius_km" in scope:
        radius = scope["radius_km"]
        if isinstance(radius, bool) or not isinstance(radius, int | float) or not 0 < radius <= 500:
            issues.add("check")
    return issues


async def _preflight_counts(connection: AsyncConnection) -> dict[str, int]:
    targets = (
        (
            await connection.execute(
                text("SELECT external_system, target_key FROM ops.poi_cache_targets")
            )
        )
        .mappings()
        .all()
    )
    scopes = (
        (
            await connection.execute(
                text(
                    "SELECT scope FROM ops.feature_update_requests "
                    "WHERE scope_type='cache_target_keys'"
                )
            )
        )
        .mappings()
        .all()
    )
    counts = {f"{name}_invalid": 0 for name in ("identity", "nfc", "trim", "length", "check", "fk")}
    for row in targets:
        issues = _canonical_identity_issues(row["external_system"], maximum=112)
        issues.update(_canonical_identity_issues(row["target_key"], maximum=512))
        for issue in issues:
            counts[f"{issue}_invalid"] += 1
    for row in scopes:
        for issue in _scope_issue_kinds(row["scope"]):
            counts[f"{issue}_invalid"] += 1
    counts["fk_invalid"] = int(
        (
            await connection.scalar(
                text(
                    "SELECT count(*) FROM ops.poi_cache_target_feature_links AS link "
                    "LEFT JOIN ops.poi_cache_targets AS target ON target.target_id=link.target_id "
                    "LEFT JOIN feature.features AS feature ON feature.feature_id=link.feature_id "
                    "WHERE target.target_id IS NULL OR feature.feature_id IS NULL"
                )
            )
        )
        or 0
    )
    return counts


async def run_preflight(request: H35Request) -> Receipt:
    engine = _engine()
    try:
        async with engine.connect() as connection:
            live_request, identity_check = await _bind_live_database_identity(connection, request)
            schema = await _current_schema(connection)
            counts = await _preflight_counts(connection)
            public = await _public_count(connection, migrated=False)
    finally:
        await engine.dispose()
    checks = [
        identity_check,
        image_revision_check(request),
        check("repository_alembic_head", expected=TARGET_SCHEMA, observed=_repository_head()),
        check("schema_before", expected=PRE_SCHEMA, observed=schema),
        check("public_items_before", expected=EXPECTED_PRE_PUBLIC, observed=public),
        *(
            check(f"0075_existing_{name}", expected=0, observed=value)
            for name, value in sorted(counts.items())
        ),
    ]
    return receipt(
        live_request,
        status="accepted" if all_pass(checks) else "rejected",
        schema_before=schema,
        schema_after=schema,
        forward_boundary="not_crossed",
        row_counts={"public_items": public, **counts},
        checks=checks,
    )


async def _index_states(
    connection: AsyncConnection, names: Sequence[str]
) -> dict[str, tuple[bool, bool]]:
    rows = (
        (
            await connection.execute(
                text(
                    "SELECT class.relname, index.indisvalid, index.indisready, "
                    "index.indislive, pg_get_indexdef(class.oid) AS definition "
                    "FROM pg_catalog.pg_class AS class "
                    "JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid=class.relnamespace "
                    "JOIN pg_catalog.pg_index AS index ON index.indexrelid=class.oid "
                    "WHERE namespace.nspname IN ('feature','ops') "
                    "AND class.relname=ANY(CAST(:names AS text[]))"
                ),
                {"names": list(names)},
            )
        )
        .mappings()
        .all()
    )
    found: dict[str, tuple[bool, bool]] = {}
    for row in rows:
        name = str(row["relname"])
        definition = " ".join(str(row["definition"]).lower().split())
        canonical = (
            bool(row["indisvalid"])
            and bool(row["indisready"])
            and bool(row["indislive"])
            and all(fragment in definition for fragment in _INDEX_SIGNATURES.get(name, ()))
        )
        found[name] = (True, canonical)
    return {name: found.get(name, (False, False)) for name in names}


def partial_invalid_indexes_allowed(schema: str, invalid_names: Sequence[str]) -> bool:
    """현재 down-revision에서 재시도 가능한 단일 concurrent-index residue인지 판정한다."""
    names = set(invalid_names)
    allowed = _ALLOWED_INVALID_BY_REVISION.get(schema, frozenset())
    return len(names) <= 1 and names <= allowed


def _statement_prefix_allowed(
    states: Mapping[str, tuple[bool, bool]],
    names: Sequence[str],
) -> bool:
    canonical = [states[name][1] for name in names]
    prefix_length = next((index for index, value in enumerate(canonical) if not value), len(names))
    if any(canonical[prefix_length:]):
        return False
    residues = [name for name in names if states[name][0] and not states[name][1]]
    return not residues or (prefix_length < len(names) and residues == [names[prefix_length]])


def partial_index_state_allowed(
    schema: str,
    states: Mapping[str, tuple[bool, bool]],
) -> bool:
    """0064/0068/0069 autocommit statement prefix와 canonical access path를 판정한다."""
    order = _REVISION_ORDER.get(schema, -1)
    if order < 0:
        return False
    price_new = "idx_price_values_feature_observed_identity"
    if order == 0:
        if not (states[_OLD_PRICE][1] or states[price_new][1]):
            return False
        if states[price_new][0] and not states[price_new][1] and not states[_OLD_PRICE][1]:
            return False
    elif not states[price_new][1] or states[_OLD_PRICE][0]:
        return False

    if order < _REVISION_ORDER["0067_integrity_dedupe_key"]:
        if any(states[name][0] for name in (*_NEW_INTEGRITY, *_WEATHER_SEQUENCE)):
            return False
    elif order == _REVISION_ORDER["0067_integrity_dedupe_key"]:
        if not _statement_prefix_allowed(states, _NEW_INTEGRITY):
            return False
        if any(states[name][0] for name in _WEATHER_SEQUENCE):
            return False
        if any(
            not (states[old][1] or states[new][1])
            for old, new in zip(_OLD_INTEGRITY, _NEW_INTEGRITY, strict=True)
        ):
            return False
    elif any(not states[name][1] for name in _NEW_INTEGRITY) or any(
        states[name][0] for name in _OLD_INTEGRITY
    ):
        return False

    if order == _REVISION_ORDER["0068_integrity_last_seen"]:
        return _statement_prefix_allowed(states, _WEATHER_SEQUENCE)
    if order > _REVISION_ORDER["0068_integrity_last_seen"]:
        return all(states[name][1] for name in _WEATHER_SEQUENCE)
    return True


async def partial_probe(connection: AsyncConnection, schema: str) -> list[dict[str, JsonValue]]:
    checks: list[dict[str, JsonValue]] = []
    order = _REVISION_ORDER.get(schema, -1)
    checks.append(check("migration_entry_revision_known", expected=True, observed=order >= 0))
    if order < 0:
        return checks
    state_names = sorted(_PARTIAL_INDEXES | {_OLD_PRICE, *_OLD_INTEGRITY})
    partial_state = await _index_states(connection, state_names)
    checks.append(
        check(
            "partial_statement_prefix_canonical",
            expected=True,
            observed=partial_index_state_allowed(schema, partial_state),
        )
    )
    price_names = (
        "idx_price_values_feature_product_observed",
        "idx_price_values_feature_observed_identity",
    )
    price = await _index_states(connection, price_names)
    price_safe = (
        price[price_names[0]][1] or price[price_names[1]][1]
        if order == 0
        else price[price_names[1]][1] and not price[price_names[0]][0]
    )
    checks.append(check("0064_partial_access_path_safe", expected=True, observed=price_safe))
    if order >= _REVISION_ORDER["0067_integrity_dedupe_key"]:
        last_seen_exists = bool(
            await connection.scalar(
                text(
                    "SELECT EXISTS (SELECT 1 FROM information_schema.columns "
                    "WHERE table_schema='ops' AND table_name='data_integrity_violations' "
                    "AND column_name='last_seen_at')"
                )
            )
        )
        null_count = (
            int(
                (
                    await connection.scalar(
                        text(
                            "SELECT count(*) FROM ops.data_integrity_violations "
                            "WHERE last_seen_at IS NULL"
                        )
                    )
                )
                or 0
            )
            if last_seen_exists
            else 0
        )
        pairs = (
            ("idx_violations_status_detected", "idx_violations_status_seen"),
            ("idx_violations_provider_status_detected", "idx_violations_provider_status_seen"),
            ("idx_violations_feature_detected", "idx_violations_feature_seen"),
        )
        state = await _index_states(connection, [name for pair in pairs for name in pair])
        paths_safe = all(state[old][1] or state[new][1] for old, new in pairs)
        if order == _REVISION_ORDER["0067_integrity_dedupe_key"]:
            last_seen_safe = not last_seen_exists or null_count == 0
        else:
            last_seen_safe = last_seen_exists and null_count == 0
            paths_safe = paths_safe and all(
                state[new][1] and not state[old][0] for old, new in pairs
            )
        checks.extend(
            (
                check("0068_partial_last_seen_safe", expected=True, observed=last_seen_safe),
                check("0068_partial_access_paths_safe", expected=True, observed=paths_safe),
            )
        )
    if order >= _REVISION_ORDER["0068_integrity_last_seen"]:
        exists = bool(
            await connection.scalar(
                text("SELECT to_regclass('feature.weather_metric_series') IS NOT NULL")
            )
        )
        safe = True
        if exists:
            columns = set(
                map(
                    str,
                    (
                        await connection.execute(
                            text(
                                "SELECT column_name FROM information_schema.columns "
                                "WHERE table_schema='feature' "
                                "AND table_name='weather_metric_series'"
                            )
                        )
                    ).scalars(),
                )
            )
            safe = columns == {
                "feature_id",
                "provider",
                "weather_domain",
                "forecast_style",
                "metric_key",
            }
        if order > _REVISION_ORDER["0068_integrity_last_seen"]:
            safe = safe and exists
        checks.append(check("0069_partial_catalog_safe", expected=True, observed=safe))
    invalid = set(
        map(
            str,
            (
                await connection.execute(
                    text(
                        "SELECT class.relname FROM pg_catalog.pg_index AS index "
                        "JOIN pg_catalog.pg_class AS class ON class.oid=index.indexrelid "
                        "JOIN pg_catalog.pg_namespace AS namespace "
                        "ON namespace.oid=class.relnamespace "
                        "WHERE NOT index.indisvalid "
                        "AND namespace.nspname IN ('feature','ops','provider_sync')"
                    )
                )
            ).scalars(),
        )
    )
    checks.append(
        check(
            "partial_invalid_indexes_revision_safe",
            expected=True,
            observed=partial_invalid_indexes_allowed(schema, sorted(invalid)),
        )
    )
    return checks


class _BoundedSink(io.TextIOBase):
    """Alembic 출력을 외부로 노출하지 않고 고정 크기까지만 흡수한다."""

    def __init__(self, limit: int = _MIGRATION_OUTPUT_LIMIT) -> None:
        self._limit = limit
        self._written = 0

    def writable(self) -> bool:
        return True

    def write(self, value: str) -> int:
        accepted = min(len(value), max(0, self._limit - self._written))
        self._written += accepted
        return len(value)

    def flush(self) -> None:
        return None


def _run_alembic_upgrade() -> None:
    sink = _BoundedSink()
    with redirect_stdout(sink), redirect_stderr(sink):
        command.upgrade(Config(str(_ALEMBIC_CONFIG_PATH)), "head")


async def run_migrate(request: H35Request) -> Receipt:
    checks = [
        image_revision_check(request),
        check("repository_alembic_head", expected=TARGET_SCHEMA, observed=_repository_head()),
    ]
    engine = _engine()
    try:
        async with engine.connect() as connection:
            live_request, identity_check = await _bind_live_database_identity(connection, request)
            checks.insert(0, identity_check)
            schema_before = await _current_schema(connection)
            checks.extend(await partial_probe(connection, schema_before))
    finally:
        await engine.dispose()
    if not all_pass(checks):
        return receipt(
            live_request,
            status="rejected",
            schema_before=schema_before,
            schema_after=schema_before,
            forward_boundary="not_crossed",
            row_counts={},
            checks=checks,
        )
    if schema_before != TARGET_SCHEMA:
        await asyncio.to_thread(_run_alembic_upgrade)
    engine = _engine()
    try:
        async with engine.connect() as connection:
            final_live_request, final_identity_check = await _bind_live_database_identity(
                connection, request
            )
            schema_after = await _current_schema(connection)
            public = await _public_count(connection, migrated=True)
            structural, counts = await verify_0075_0078(connection)
    finally:
        await engine.dispose()
    checks.extend(
        (
            final_identity_check,
            check("schema_after_migrate", expected=TARGET_SCHEMA, observed=schema_after),
            check("public_items_after_migrate", expected=EXPECTED_MIGRATED_PUBLIC, observed=public),
            *structural,
        )
    )
    return receipt(
        final_live_request,
        status="accepted" if all_pass(checks) else "rejected",
        schema_before=schema_before,
        schema_after=schema_after,
        forward_boundary="schema_0078" if schema_after == TARGET_SCHEMA else "not_crossed",
        row_counts={"public_items": public, **counts},
        checks=checks,
    )


async def verify_0075_0078(
    connection: AsyncConnection,
) -> tuple[list[dict[str, JsonValue]], dict[str, int]]:
    catalog = await collect_catalog_objects(connection)
    fingerprints = catalog_fingerprints(catalog)
    invalid_indexes = int(
        (
            await connection.scalar(
                text(
                    "SELECT count(*) FROM pg_catalog.pg_index AS index "
                    "JOIN pg_catalog.pg_class AS class ON class.oid=index.indexrelid "
                    "JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid=class.relnamespace "
                    "WHERE NOT index.indisvalid "
                    "AND namespace.nspname IN ('feature','ops','provider_sync')"
                )
            )
        )
        or 0
    )
    checks = [
        *(
            check(
                f"0075_0078_{category}_semantic",
                expected=expected,
                observed=fingerprints.get(category, "missing"),
            )
            for category, expected in sorted(EXPECTED_CATALOG_FINGERPRINTS.items())
        ),
        check("invalid_app_indexes", expected=0, observed=invalid_indexes),
    ]
    return checks, {
        "invalid_indexes": invalid_indexes,
        **{f"catalog_{category}": len(objects) for category, objects in sorted(catalog.items())},
    }


async def collect_verify_state(
    request: H35Request,
) -> tuple[
    H35Request,
    dict[str, JsonValue],
    str,
    int,
    list[dict[str, JsonValue]],
    dict[str, int],
]:
    """verify phase가 schema와 0075~78 구조를 한 connection에서 읽는다."""
    engine = _engine()
    try:
        async with engine.connect() as connection:
            live_request, identity_check = await _bind_live_database_identity(connection, request)
            return (
                live_request,
                identity_check,
                await _current_schema(connection),
                await _public_count(connection, migrated=True),
                *(await verify_0075_0078(connection)),
            )
    finally:
        await engine.dispose()


__all__ = [
    "EXPECTED_POST_PUBLIC",
    "PRE_SCHEMA",
    "TARGET_SCHEMA",
    "collect_verify_state",
    "image_revision_check",
    "partial_index_state_allowed",
    "partial_invalid_indexes_allowed",
    "partial_probe",
    "run_migrate",
    "run_preflight",
    "verify_0075_0078",
]
