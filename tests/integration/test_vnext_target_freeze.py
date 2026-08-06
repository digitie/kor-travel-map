"""T-VN-31 vNext target freeze의 executable contract 검증 (T-VN-31C).

빈 PostGIS DB(새 database + ``x_extension`` 확장)에서:

1. ``contracts/vnext/target-schema-v1.sql``이 그대로 적용된다.
2. ``contracts/vnext/target-invariants-v1.sql``의 모든 assertion이 0을 반환한다
   (빈 DB — 위반 0).
3. ``contracts/vnext/violation-fixtures-v1.sql`` 각 case가
   ``expected-rejections-v1.json``의 SQLSTATE·제약명으로 **DB에서** 거부된다.
4. H35 7 카테고리 catalog 질의(출처: ``src/kortravelmap/cli/_h35_catalog.py``)로
   재계산한 fingerprint가 ``target-schema-fingerprints-v1.json``과 일치한다.

이 테스트가 target freeze artifact의 drift를 fail-close한다 (T-VN-31C).
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, Final
from uuid import uuid4

import asyncpg
import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url

from kortravelmap.cli._h35_contract import canonical_json_bytes
from kortravelmap.infra.db import make_async_engine, normalize_async_dsn

pytestmark = pytest.mark.integration

_ROOT: Final = Path(__file__).resolve().parents[2]
_CONTRACTS: Final = _ROOT / "contracts" / "vnext"
_SCHEMA_SQL: Final = _CONTRACTS / "target-schema-v1.sql"
_INVARIANTS_SQL: Final = _CONTRACTS / "target-invariants-v1.sql"
_FINGERPRINTS_JSON: Final = _CONTRACTS / "target-schema-fingerprints-v1.json"
_VIOLATIONS_SQL: Final = _CONTRACTS / "violation-fixtures-v1.sql"
_REJECTIONS_JSON: Final = _CONTRACTS / "expected-rejections-v1.json"

_EXPECTED_INVARIANT_COUNT: Final = 47
_INVARIANT_PHASES: Final = frozenset({"pre-backfill", "post-backfill", "both"})

# fingerprint 대상 — target-schema-v1.sql이 만드는 전체 relation.
_TARGET_TABLES: Final = (
    "feature.categories",
    "feature.features",
    "feature.feature_state_transitions",
    "feature.feature_aliases",
    "feature.feature_points",
    "feature.feature_events",
    "feature.feature_notices",
    "feature.feature_routes",
    "feature.feature_areas",
    "feature.feature_weather_values",
    "feature.current_weather_summary",
    "feature.feature_price_values",
    "feature.current_price_summary",
    "feature.curated_themes",
    "feature.curation_collections",
    "feature.curation_items",
    "feature.theme_feature_candidates",
    "provider_sync.provider_datasets",
    "provider_sync.provider_dataset_operations",
    "provider_sync.source_entities",
    "provider_sync.source_records",
    "provider_sync.source_entity_heads",
    "provider_sync.source_links",
    "provider_sync.notice_states",
    "ops.feature_override_field_paths",
    "ops.feature_overrides",
)
_TARGET_RELATIONS: Final = (*_TARGET_TABLES, "feature.public_features")
_TARGET_FUNCTIONS: Final = (
    "feature.force_features_row_revision()",
    "provider_sync.is_valid_provider_dataset_capabilities(jsonb)",
    "provider_sync.reject_provider_dataset_identity_update()",
    "provider_sync.touch_provider_dataset()",
    "provider_sync.reject_inactive_provider_dataset()",
    "provider_sync.reject_source_record_update()",
    "provider_sync.enforce_source_entity_head_freshness()",
    "provider_sync.assert_source_entity_head_completeness()",
)

# =============================================================================
# H35 catalog 질의 — src/kortravelmap/cli/_h35_catalog.py의 7 카테고리 질의를
# 복제·적응했다(출처 주석 — ADR/T-VN-31A 지시). 차이점:
#   * `ops` 고정 schema 대신 schema-qualified relation 목록($1::text[])
#   * functions의 outbox 소유자 대조·indexes의 단일 인덱스 예외 절 제거
#   * sequence는 대상 테이블 identity 컬럼이 소유한 sequence 전부
# =============================================================================

_RELATIONS_SQL: Final = """
SELECT ns.nspname || '.' || rel.relname AS identity,
       jsonb_build_object(
         'schema', ns.nspname,
         'relation', rel.relname,
         'kind', rel.relkind,
         'persistence', rel.relpersistence,
         'row_security', rel.relrowsecurity,
         'force_row_security', rel.relforcerowsecurity
       ) AS payload
FROM pg_catalog.pg_class AS rel
JOIN pg_catalog.pg_namespace AS ns ON ns.oid = rel.relnamespace
WHERE ns.nspname || '.' || rel.relname = ANY($1::text[])
ORDER BY identity
"""

_COLUMNS_SQL: Final = """
SELECT ns.nspname || '.' || rel.relname || '.' || att.attname AS identity,
       jsonb_build_object(
         'schema', ns.nspname,
         'relation', rel.relname,
         'position', att.attnum,
         'column', att.attname,
         'type', pg_catalog.format_type(att.atttypid, att.atttypmod),
         'not_null', att.attnotnull,
         'identity', att.attidentity,
         'generated', att.attgenerated,
         'default', pg_catalog.pg_get_expr(def.adbin, def.adrelid, true),
         'collation', CASE WHEN att.attcollation = 0 THEN NULL
                           ELSE coll_ns.nspname || '.' || coll.collname END
       ) AS payload
FROM pg_catalog.pg_attribute AS att
JOIN pg_catalog.pg_class AS rel ON rel.oid = att.attrelid
JOIN pg_catalog.pg_namespace AS ns ON ns.oid = rel.relnamespace
LEFT JOIN pg_catalog.pg_attrdef AS def
  ON def.adrelid = att.attrelid AND def.adnum = att.attnum
LEFT JOIN pg_catalog.pg_collation AS coll ON coll.oid = att.attcollation
LEFT JOIN pg_catalog.pg_namespace AS coll_ns ON coll_ns.oid = coll.collnamespace
WHERE ns.nspname || '.' || rel.relname = ANY($1::text[])
  AND att.attnum > 0 AND NOT att.attisdropped
ORDER BY identity
"""

_CONSTRAINTS_SQL: Final = """
SELECT ns.nspname || '.' || rel.relname || '.' || con.conname AS identity,
       jsonb_build_object(
         'schema', ns.nspname,
         'relation', rel.relname,
         'name', con.conname,
         'type', con.contype,
         'local_columns', ARRAY(
           SELECT att.attname
           FROM unnest(con.conkey) WITH ORDINALITY AS key(attnum, ordinal)
           JOIN pg_catalog.pg_attribute AS att
             ON att.attrelid = con.conrelid AND att.attnum = key.attnum
           ORDER BY key.ordinal
         ),
         'referenced_relation', CASE WHEN con.confrelid = 0 THEN NULL
           ELSE ref_ns.nspname || '.' || ref_rel.relname END,
         'referenced_columns', ARRAY(
           SELECT att.attname
           FROM unnest(con.confkey) WITH ORDINALITY AS key(attnum, ordinal)
           JOIN pg_catalog.pg_attribute AS att
             ON att.attrelid = con.confrelid AND att.attnum = key.attnum
           ORDER BY key.ordinal
         ),
         'update_action', con.confupdtype,
         'delete_action', con.confdeltype,
         'match_type', con.confmatchtype,
         'validated', con.convalidated,
         'deferrable', con.condeferrable,
         'initially_deferred', con.condeferred,
         'definition', pg_catalog.pg_get_constraintdef(con.oid, true)
       ) AS payload
FROM pg_catalog.pg_constraint AS con
JOIN pg_catalog.pg_class AS rel ON rel.oid = con.conrelid
JOIN pg_catalog.pg_namespace AS ns ON ns.oid = rel.relnamespace
LEFT JOIN pg_catalog.pg_class AS ref_rel ON ref_rel.oid = con.confrelid
LEFT JOIN pg_catalog.pg_namespace AS ref_ns ON ref_ns.oid = ref_rel.relnamespace
WHERE ns.nspname || '.' || rel.relname = ANY($1::text[])
ORDER BY identity
"""

_INDEXES_SQL: Final = """
SELECT ns.nspname || '.' || rel.relname || '.' || idx_rel.relname AS identity,
       jsonb_build_object(
         'schema', ns.nspname,
         'relation', rel.relname,
         'name', idx_rel.relname,
         'unique', idx.indisunique,
         'nulls_not_distinct', idx.indnullsnotdistinct,
         'primary', idx.indisprimary,
         'exclusion', idx.indisexclusion,
         'immediate', idx.indimmediate,
         'valid', idx.indisvalid,
         'ready', idx.indisready,
         'live', idx.indislive,
         'method', am.amname,
         'key_count', idx.indnkeyatts,
         'attribute_count', idx.indnatts,
         'keys', ARRAY(
           SELECT pg_catalog.pg_get_indexdef(idx.indexrelid, position, true)
           FROM generate_series(1, idx.indnatts) AS position
         ),
         'predicate', pg_catalog.pg_get_expr(idx.indpred, idx.indrelid, true),
         'expressions', pg_catalog.pg_get_expr(idx.indexprs, idx.indrelid, true),
         'options', idx.indoption::text,
         'opclasses', ARRAY(
           SELECT opc_ns.nspname || '.' || opc.opcname
           FROM unnest(idx.indclass) WITH ORDINALITY AS item(opclass_oid, ordinal)
           JOIN pg_catalog.pg_opclass AS opc ON opc.oid = item.opclass_oid
           JOIN pg_catalog.pg_namespace AS opc_ns ON opc_ns.oid = opc.opcnamespace
           ORDER BY item.ordinal
         )
       ) AS payload
FROM pg_catalog.pg_index AS idx
JOIN pg_catalog.pg_class AS rel ON rel.oid = idx.indrelid
JOIN pg_catalog.pg_namespace AS ns ON ns.oid = rel.relnamespace
JOIN pg_catalog.pg_class AS idx_rel ON idx_rel.oid = idx.indexrelid
JOIN pg_catalog.pg_am AS am ON am.oid = idx_rel.relam
WHERE ns.nspname || '.' || rel.relname = ANY($1::text[])
ORDER BY identity
"""

_TRIGGERS_SQL: Final = """
SELECT ns.nspname || '.' || rel.relname || '.' || trg.tgname AS identity,
       jsonb_build_object(
         'schema', ns.nspname,
         'relation', rel.relname,
         'name', trg.tgname,
         'enabled', trg.tgenabled,
         'internal', trg.tgisinternal,
         'function', proc_ns.nspname || '.' || proc.proname || '('
           || pg_catalog.pg_get_function_identity_arguments(proc.oid) || ')',
         'definition', pg_catalog.pg_get_triggerdef(trg.oid, true)
       ) AS payload
FROM pg_catalog.pg_trigger AS trg
JOIN pg_catalog.pg_class AS rel ON rel.oid = trg.tgrelid
JOIN pg_catalog.pg_namespace AS ns ON ns.oid = rel.relnamespace
JOIN pg_catalog.pg_proc AS proc ON proc.oid = trg.tgfoid
JOIN pg_catalog.pg_namespace AS proc_ns ON proc_ns.oid = proc.pronamespace
WHERE ns.nspname || '.' || rel.relname = ANY($1::text[])
  AND NOT trg.tgisinternal
ORDER BY identity
"""

_FUNCTIONS_SQL: Final = """
WITH required AS (
  SELECT signature, pg_catalog.to_regprocedure(signature) AS function_oid
  FROM unnest($1::text[]) AS item(signature)
)
SELECT ns.nspname || '.' || proc.proname || '('
         || pg_catalog.pg_get_function_identity_arguments(proc.oid) || ')' AS identity,
       jsonb_build_object(
         'required_signature', required.signature,
         'schema', ns.nspname,
         'name', proc.proname,
         'identity_arguments', pg_catalog.pg_get_function_identity_arguments(proc.oid),
         'result', pg_catalog.pg_get_function_result(proc.oid),
         'language', lang.lanname,
         'kind', proc.prokind,
         'volatility', proc.provolatile,
         'strict', proc.proisstrict,
         'security_definer', proc.prosecdef,
         'leakproof', proc.proleakproof,
         'parallel', proc.proparallel,
         'config', COALESCE(to_jsonb(proc.proconfig), '[]'::jsonb),
         'body', proc.prosrc
       ) AS payload
FROM required
JOIN pg_catalog.pg_proc AS proc ON proc.oid = required.function_oid
JOIN pg_catalog.pg_namespace AS ns ON ns.oid = proc.pronamespace
JOIN pg_catalog.pg_language AS lang ON lang.oid = proc.prolang
ORDER BY identity
"""

_SEQUENCE_SQL: Final = """
SELECT ns.nspname || '.' || seq_rel.relname AS identity,
       jsonb_build_object(
         'schema', ns.nspname,
         'name', seq_rel.relname,
         'data_type', pg_catalog.format_type(seq.seqtypid, NULL),
         'start', seq.seqstart,
         'increment', seq.seqincrement,
         'minimum', seq.seqmin,
         'maximum', seq.seqmax,
         'cache', seq.seqcache,
         'cycle', seq.seqcycle,
         'persistence', seq_rel.relpersistence,
         'owned_by', owned_ns.nspname || '.' || owned_rel.relname || '.' || owned_att.attname
       ) AS payload
FROM pg_catalog.pg_sequence AS seq
JOIN pg_catalog.pg_class AS seq_rel ON seq_rel.oid = seq.seqrelid
JOIN pg_catalog.pg_namespace AS ns ON ns.oid = seq_rel.relnamespace
JOIN pg_catalog.pg_depend AS dep
  ON dep.classid = 'pg_class'::regclass AND dep.objid = seq_rel.oid
 AND dep.refclassid = 'pg_class'::regclass AND dep.deptype IN ('a', 'i')
JOIN pg_catalog.pg_class AS owned_rel ON owned_rel.oid = dep.refobjid
JOIN pg_catalog.pg_namespace AS owned_ns ON owned_ns.oid = owned_rel.relnamespace
JOIN pg_catalog.pg_attribute AS owned_att
  ON owned_att.attrelid = owned_rel.oid AND owned_att.attnum = dep.refobjsubid
WHERE owned_ns.nspname || '.' || owned_rel.relname = ANY($1::text[])
ORDER BY identity
"""


def _asyncpg_kwargs(async_dsn: str, database: str | None = None) -> dict[str, Any]:
    url = make_url(async_dsn)
    return {
        "host": url.host,
        "port": url.port,
        "user": url.username,
        "password": url.password,
        "database": database or url.database,
    }


async def _connect(async_dsn: str, database: str | None = None) -> asyncpg.Connection:
    connection = await asyncpg.connect(**_asyncpg_kwargs(async_dsn, database))
    await connection.set_type_codec(
        "jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog"
    )
    return connection


def load_invariant_queries() -> list[tuple[str, str]]:
    """`SELECT ...; -- expect: 0 -- phase: <phase>` assertion을 (질의, phase)로 파싱한다.

    fail-open 봉합(리뷰 D1): trailer 표식 개수와 파싱된 질의 수가 일치해야 하며,
    phase 태그가 없는 assertion은 파싱 자체가 거부한다.
    """
    content = _INVARIANTS_SQL.read_text(encoding="utf-8")
    parsed = re.findall(
        r"(?ms)^(SELECT .*?); -- expect: 0 -- phase: (pre-backfill|post-backfill|both)$",
        content,
    )
    marker_count = content.count("-- expect: 0")
    if marker_count != len(parsed):
        raise AssertionError(
            f"invariant trailer {marker_count}개 중 {len(parsed)}개만 파싱됨 — "
            "phase 태그 누락 또는 trailer 문법 위반"
        )
    return [(query, phase) for query, phase in parsed]


def load_violation_cases() -> dict[str, str]:
    """`-- case: <id>` 헤더로 구분된 위반 fixture case를 파싱한다."""
    cases: dict[str, list[str]] = {}
    current: str | None = None
    for line in _VIOLATIONS_SQL.read_text(encoding="utf-8").splitlines():
        matched = re.match(r"^-- case: (\S+)$", line)
        if matched:
            current = matched.group(1)
            cases[current] = []
        elif current is not None:
            cases[current].append(line)
    return {name: "\n".join(lines).strip() for name, lines in cases.items()}


@pytest.fixture(scope="module")
async def freeze_db(pg_container: Any) -> AsyncIterator[asyncpg.Connection]:
    """새 database + x_extension 확장 위에 target-schema-v1.sql을 적용한다.

    `migrated_engine`(alembic head)이 아니라 **빈 PostGIS DB**가 대상이다 —
    freeze DDL은 자기완결로 적용 가능해야 한다.
    """
    admin_dsn = normalize_async_dsn(pg_container.get_connection_url())
    database = f"vnext_freeze_{uuid4().hex}"
    admin_engine = make_async_engine(admin_dsn)
    try:
        async with admin_engine.connect() as raw_connection:
            autocommit = await raw_connection.execution_options(isolation_level="AUTOCOMMIT")
            await autocommit.execute(text(f'CREATE DATABASE "{database}"'))
    finally:
        await admin_engine.dispose()

    connection = await _connect(admin_dsn, database)
    try:
        # x_extension schema + 확장은 사전 존재 가정(ADR-008) — 테스트가 만든다.
        await connection.execute("CREATE SCHEMA x_extension")
        for extension in ("postgis", "pg_trgm", "pgcrypto"):
            await connection.execute(
                f"CREATE EXTENSION IF NOT EXISTS {extension} WITH SCHEMA x_extension"
            )
        await connection.execute("SET search_path = public, x_extension")
        await connection.execute(_SCHEMA_SQL.read_text(encoding="utf-8"))
        yield connection
    finally:
        await connection.close()
        admin_engine = make_async_engine(admin_dsn)
        try:
            async with admin_engine.connect() as raw_connection:
                autocommit = await raw_connection.execution_options(isolation_level="AUTOCOMMIT")
                await autocommit.execute(text(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)'))
        finally:
            await admin_engine.dispose()


async def test_invariants_all_zero_on_empty_target(freeze_db: asyncpg.Connection) -> None:
    queries = load_invariant_queries()
    assert len(queries) == _EXPECTED_INVARIANT_COUNT
    # 빈 DB에서는 전 phase를 실행한다 — 전부 0이어야 한다.
    for query, phase in queries:
        assert phase in _INVARIANT_PHASES
        observed = await freeze_db.fetchval(query)
        assert observed == 0, (
            f"invariant 위반 (expect 0, got {observed}, phase {phase}): {query[:120]}"
        )


async def test_violation_fixtures_rejected_with_expected_sqlstate(
    freeze_db: asyncpg.Connection,
) -> None:
    expectations = json.loads(_REJECTIONS_JSON.read_text(encoding="utf-8"))["cases"]
    cases = load_violation_cases()
    assert set(cases) == set(expectations), "fixture case와 기대 rejection 목록 불일치"
    for name, case_sql in cases.items():
        expected = expectations[name]
        transaction = freeze_db.transaction()
        await transaction.start()
        try:
            with pytest.raises(asyncpg.PostgresError) as excinfo:
                await freeze_db.execute(case_sql)
        finally:
            await transaction.rollback()
        error = excinfo.value
        assert getattr(error, "sqlstate", None) == expected["sqlstate"], (
            f"case {name}: SQLSTATE {getattr(error, 'sqlstate', None)!r} != "
            f"{expected['sqlstate']!r} ({error})"
        )
        constraint = getattr(error, "constraint_name", None)
        if constraint is not None:
            assert constraint == expected["constraint"], f"case {name}: {error}"
        else:
            assert expected["constraint"] in str(error), f"case {name}: {error}"


async def test_catalog_fingerprints_match_frozen_artifact(
    freeze_db: asyncpg.Connection,
) -> None:
    catalog_queries: dict[str, tuple[str, tuple[str, ...]]] = {
        "relations": (_RELATIONS_SQL, _TARGET_RELATIONS),
        "columns": (_COLUMNS_SQL, _TARGET_RELATIONS),
        "constraints": (_CONSTRAINTS_SQL, _TARGET_TABLES),
        "indexes": (_INDEXES_SQL, _TARGET_TABLES),
        "triggers": (_TRIGGERS_SQL, _TARGET_TABLES),
        "functions": (_FUNCTIONS_SQL, _TARGET_FUNCTIONS),
        "sequence": (_SEQUENCE_SQL, _TARGET_TABLES),
    }
    computed: dict[str, str] = {}
    for category, (query, parameter) in sorted(catalog_queries.items()):
        rows = await freeze_db.fetch(query, list(parameter))
        objects = {str(row["identity"]): row["payload"] for row in rows}
        computed[category] = hashlib.sha256(canonical_json_bytes(objects)).hexdigest()

    frozen = json.loads(_FINGERPRINTS_JSON.read_text(encoding="utf-8"))
    assert computed == frozen["fingerprints"], (
        "catalog fingerprint drift — 재계산 값:\n" + json.dumps(computed, indent=2)
    )
    schema_sha = hashlib.sha256(_SCHEMA_SQL.read_bytes()).hexdigest()
    assert schema_sha == frozen["target_schema_sql_sha256"], (
        f"target-schema-v1.sql bytes drift — 재계산 {schema_sha}"
    )
