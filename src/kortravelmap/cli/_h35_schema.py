"""H35 Map helper의 0063→0079 schema preflight, migration, verification."""

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
from kortravelmap.cli._h35_schema_version import FORWARD_BOUNDARY, PRE_SCHEMA, TARGET_SCHEMA
from kortravelmap.infra.curation_link_basis import trusted_basis_sql
from kortravelmap.infra.db import make_async_engine

EXPECTED_PRE_PUBLIC: Final = 3_265
EXPECTED_MIGRATED_PUBLIC: Final = 3_043
EXPECTED_POST_PUBLIC: Final = 3_265
# `0065`는 legacy-marker collection 안의 canonical-only item(= `curated_features`
# 투영본이 아닌 item)을 admin-only quarantine collection으로 옮긴다. 2026-08-03 라이브
# prod(`krtour_map`) 읽기 전용 실측에서 그 교집합은 비어 있다 — legacy collection 52개는
# 투영본 3,044건만, CSV collection은 네이티브 486건만 담아 2×2가 대각선만 채운다. 격리
# clone에 `0065`를 실제로 적용해도 0이었다.
#
# **이 검사는 preflight에만 hard gate로 둔다.** 격리 발생은 공개 카운트로 드러나지 않는다 —
# 격리 조건(`legacy_projection_id IS NULL`)은 `status`·`source_present`·accepted link
# 어느 것도 요구하지 않아 공개 집합과 독립이다. 실제로 회귀 픽스처에서 격리 1건이 생겨도
# 공개 수는 3,043 그대로였다. 그러니 migrate/verify에 hard check로 두면 **기존 게이트가
# 통과시키던 상태를 경계 뒤에서 새로 거부**하게 되고, 그 지점에는 출구가 없다:
# csv5는 accepted prior receipt를 요구하고, migrate 재실행은 `schema_before=0063`을 요구하는데
# DB는 이미 0078이며, `0065` downgrade는 durable state에 fail-close한다 → PITR 없는 prod에서
# dump 복원만 남는다. `#925`에서 index signature로 겪은 것과 같은 계열의 함정이다.
#
# preflight는 `forward_boundary="not_crossed"`에서 거부하므로 재실행 가능하고, 운영자가
# 격리 후보를 정리한 뒤 그대로 다시 돌릴 수 있다. 경계 뒤에는 관측치만 남긴다.
EXPECTED_QUARANTINE_CANDIDATES: Final = 0
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
    "0078_cache_target_gc_observe",
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
        # `feature.features.kind`는 `character varying`이라(0002) PostgreSQL이
        # 술어를 항상 `((kind)::text = 'weather'::text)`로 deparse한다.
        # `kind = 'weather'::text`로 적으면 **어떤 DB에서도 일치하지 않아** 이 index가
        # 영구히 non-canonical이 되고, head에서 partial probe가 통과할 수 없다.
        "on feature.features using gist (coord_5179)",
        "(kind)::text = 'weather'::text",
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


def _repository_campaign_revision() -> str:
    """저장소 migration lineage에서 H35 캠페인 target(0078)의 위치를 판정한다.

    반환값이 ``TARGET_SCHEMA``면 target revision script가 존재하고 단일 head의
    조상(head 자신 포함)이라는 뜻이다. 과거에는 repository head와
    ``TARGET_SCHEMA``의 **등호**를 검사했는데, 그 고정은 Wave 2 migration
    (0079+)이 head를 전진시키는 순간 이 캠페인 도구를 영구 거부 상태로
    만들었다(T-VN-32B에서 실측·수정). 캠페인 도구는 자신의 target에만
    앵커한다 — 실행도 head가 아니라 ``TARGET_SCHEMA``까지만 upgrade한다.
    """
    config = Config(str(_ALEMBIC_CONFIG_PATH))
    script = ScriptDirectory.from_config(config)
    heads = script.get_heads()
    if len(heads) != 1:
        return "multiple_heads:" + ",".join(sorted(heads))
    lineage = {revision.revision for revision in script.iterate_revisions(heads[0], "base")}
    return TARGET_SCHEMA if TARGET_SCHEMA in lineage else "target_not_in_lineage"


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
    # `curation_items.source_present`는 `0065`가 만든다. preflight는 `0063`에서 돌므로
    # 그 컬럼이 아직 없어 조건부로만 넣는다. 공개 목록 술어
    # (`curation_repo._LIST_FEATURE_ITEMS_SQL`)는 `AND i.source_present`를 포함하므로,
    # migrate 이후 이것을 빼면 source-absent가 된 item을 계속 공개로 세어 **de-publish를
    # 게이트가 놓친다**(격리 clone에서 재현함 — 실제 API 3,042인데 게이트는 3,043 보고).
    source_present_predicate = "AND item.source_present" if migrated else ""
    return f"""
        SELECT count(*)::bigint
        FROM feature.curation_items AS item
        JOIN feature.curation_collections AS collection
          ON collection.collection_id = item.collection_id
        JOIN feature.curated_themes AS theme ON theme.theme_id = collection.theme_id
        WHERE item.archived_at IS NULL AND collection.archived_at IS NULL
          {source_present_predicate}
          AND item.status = 'included' AND collection.status = 'published'
          AND collection.visibility = 'public' AND theme.visibility = 'public'
          {link_predicate}
    """


async def _public_count(connection: AsyncConnection, *, migrated: bool) -> int:
    return int((await connection.scalar(text(_public_count_sql(migrated=migrated)))) or 0)


# `0065`가 quarantine collection에 박는 marker 그대로 읽는다. `created_by`만 보면 `0065`가
# 만든 다른 행과 섞이므로 metadata marker를 함께 요구한다. LEFT JOIN이라 item이 0건인
# quarantine collection도 collection 쪽에는 잡힌다.
_QUARANTINE_COUNT_SQL: Final = """
    SELECT
        count(DISTINCT quarantine.collection_id)::bigint AS collections,
        count(item.curation_item_id)::bigint AS items
    FROM feature.curation_collections AS quarantine
    LEFT JOIN feature.curation_items AS item
      ON item.collection_id = quarantine.collection_id
    WHERE quarantine.created_by = 'migration:0065'
      AND quarantine.metadata @> '{"migration_quarantine": "0065"}'::jsonb
"""


async def _quarantine_counts(connection: AsyncConnection) -> tuple[int, int]:
    """`0065` quarantine의 collection 수와 item 수. **관측용** — 경계 뒤에서만 쓴다."""
    row = (await connection.execute(text(_QUARANTINE_COUNT_SQL))).one()
    return int(row.collections or 0), int(row.items or 0)


# 같은 조건을 `0063`에서, 즉 **되돌릴 수 있는 동안** 잰다. `0065`의 격리 술어는
# `legacy_projection_id IS NULL`인데(1437·1494행) 그 컬럼을 채우는 backfill은
#
#     UPDATE curation_items SET legacy_projection_id = legacy.curated_feature_id
#     FROM curated_features AS legacy WHERE curation_item_id = legacy.curated_feature_id
#
# 하나뿐이다(1158~1164행). 따라서 `0063`에서는 `curated_features`에 대응 행이 없다는 조건과
# 동치다 — 컬럼 없이도 같은 집합을 고를 수 있다.
#
# 근사인 지점: `0065`는 격리 블록 **앞에서** rekey와 tombstone 병합을 돌린다. 그것들은
# legacy collection 안에 네이티브 item을 **새로 만들지 않으므로** 후보를 늘리지는 않지만,
# 병합으로 줄일 수는 있다. 즉 이 카운트는 보수적인 상계다 — 0이면 격리도 0이고, 0이 아닌데
# 실제 격리가 0일 수는 있다. 게이트 기대값이 0이라 이 방향의 오차는 **안전한 쪽**이다
# (경계 앞 거짓 거부이며, 재실행 가능하다).
_QUARANTINE_CANDIDATE_SQL: Final = """
    SELECT count(*)::bigint
    FROM feature.curation_items AS item
    JOIN feature.curation_collections AS collection
      ON collection.collection_id = item.collection_id
    WHERE (
        COALESCE(
            collection.metadata ->> 'migrated_from' = 'feature.curated_features',
            false
        )
        OR collection.collection_key LIKE 'legacy:%'
      )
      AND NOT EXISTS (
          SELECT 1 FROM feature.curated_features AS legacy
          WHERE legacy.curated_feature_id = item.curation_item_id
      )
"""


async def _quarantine_candidate_count(connection: AsyncConnection) -> int:
    """`0065`가 격리할 item 수를 `0063`에서 미리 잰다 (보수적 상계)."""
    return int((await connection.scalar(text(_QUARANTINE_CANDIDATE_SQL))) or 0)


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
            quarantine_candidates = await _quarantine_candidate_count(connection)
    finally:
        await engine.dispose()
    checks = [
        identity_check,
        image_revision_check(request),
        check(
            "repository_alembic_head",
            expected=TARGET_SCHEMA,
            observed=_repository_campaign_revision(),
        ),
        check("schema_before", expected=PRE_SCHEMA, observed=schema),
        check("public_items_before", expected=EXPECTED_PRE_PUBLIC, observed=public),
        check(
            "quarantine_candidates_before",
            expected=EXPECTED_QUARANTINE_CANDIDATES,
            observed=quarantine_candidates,
        ),
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
        row_counts={
            "public_items": public,
            "quarantine_candidates": quarantine_candidates,
            **counts,
        },
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
    # 캠페인 target까지만 upgrade한다 — "head"는 Wave 2 migration(0079+)이
    # 추가될 때마다 캠페인 결과가 달라지는 이동 표적이다(T-VN-32B 수정).
    sink = _BoundedSink()
    with redirect_stdout(sink), redirect_stderr(sink):
        command.upgrade(Config(str(_ALEMBIC_CONFIG_PATH)), TARGET_SCHEMA)


async def run_migrate(request: H35Request) -> Receipt:
    checks = [
        image_revision_check(request),
        check(
            "repository_alembic_head",
            expected=TARGET_SCHEMA,
            observed=_repository_campaign_revision(),
        ),
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
            structural, counts = await verify_0075_0079(connection)
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
        forward_boundary=FORWARD_BOUNDARY if schema_after == TARGET_SCHEMA else "not_crossed",
        row_counts={"public_items": public, **counts},
        checks=checks,
    )


async def verify_0075_0079(
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
    quarantine_collections, quarantine_items = await _quarantine_counts(connection)
    checks = [
        *(
            check(
                f"0075_0079_{category}_semantic",
                expected=expected,
                observed=fingerprints.get(category, "missing"),
            )
            for category, expected in sorted(EXPECTED_CATALOG_FINGERPRINTS.items())
        ),
        check("invalid_app_indexes", expected=0, observed=invalid_indexes),
    ]
    # quarantine은 **check가 아니라 관측치로만** 남긴다. 경계를 넘은 뒤 거부하면 출구가
    # 없다(상단 `EXPECTED_QUARANTINE_CANDIDATES` 주석 참조). 게이트는 preflight의
    # `quarantine_candidates_before`가 이미 걸었고, 여기서는 실제로 몇 건이 격리됐는지를
    # receipt에 남겨 사후 판정과 T-VN-H22 착수 여부의 근거로 쓴다.
    return checks, {
        "invalid_indexes": invalid_indexes,
        "quarantine_collections": quarantine_collections,
        "quarantine_items": quarantine_items,
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
                *(await verify_0075_0079(connection)),
            )
    finally:
        await engine.dispose()


__all__ = [
    "EXPECTED_POST_PUBLIC",
    "EXPECTED_QUARANTINE_CANDIDATES",
    "PRE_SCHEMA",
    "TARGET_SCHEMA",
    "collect_verify_state",
    "image_revision_check",
    "partial_index_state_allowed",
    "partial_invalid_indexes_allowed",
    "partial_probe",
    "run_migrate",
    "run_preflight",
    "verify_0075_0079",
]
