"""H35 0075~0078 PostgreSQL catalog semantic contract."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Final

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from kortravelmap.cli._h35_contract import canonical_json_bytes

_TABLES: Final = (
    "poi_cache_target_streams",
    "poi_cache_target_restore_fences",
    "poi_cache_target_source_heads",
    "poi_cache_target_source_events",
    "poi_cache_target_refresh_members",
    "poi_cache_target_reconciliation_requests",
    "poi_cache_target_outbox_events",
    "poi_cache_target_outbox_claims",
    "poi_cache_target_outbox_deliveries",
    "poi_cache_target_outbox_claim_events",
    "poi_cache_target_snapshots",
    "poi_cache_target_snapshot_items",
    "poi_cache_target_snapshot_gc_observations",
)
_EXTRA_CONSTRAINTS: Final = (
    "ck_feature_update_requests_scope_shape",
    "ck_poi_cache_targets_external_system_identity",
    "ck_poi_cache_targets_target_key_identity",
)
_FUNCTION_SIGNATURES: Final = (
    "ops.assign_cache_target_outbox_relay_order()",
    "ops.is_valid_feature_update_scope(text,jsonb)",
    "ops.is_valid_feature_update_scope_0074(text,jsonb)",
    "ops.is_valid_feature_update_scope_0052(text,jsonb)",
    "ops.reject_cache_target_history_mutation()",
)

# PostgreSQL 16/PostGIS 3.5에서 0075→0078 migration이 만든 structured catalog의
# canonical SHA-256. 값은 tests/integration/test_h35_cutover_rehearsal.py가 실제
# migration 직후 다시 계산해 drift를 고정한다.
EXPECTED_CATALOG_FINGERPRINTS: Final[dict[str, str]] = {
    "columns": "8604ad59e72300f206103d73108e98a451de3e4c06c45190ac8c249c2919c0f5",
    "constraints": "f87104501ca458143d4f1858aac2948fd9f95307ec724aa76c55e2f3658d8401",
    "functions": "652c068ef0fe961d54d18e6cac7b407b76c41b5e55decc6cbd23c86d8ef14dc5",
    "indexes": "3c58c7b00f2f2ad43665077daa4600e0a6fc3cf84f3ffba1746bb3caf2000d80",
    "relations": "7cf9f623113c6de15bcc98c6c26c2263f423b583449155a9f715a86bc7e756cf",
    "sequence": "c5afb8ec28f1183f74023fc907459e6b8fc751e197943064a238ee0a34632230",
    "triggers": "fe315c2f4912e9f312101b73bba9279b98755f86a4229a501f9708b3273c7eb9",
}

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
JOIN pg_catalog.pg_namespace AS ns ON ns.oid=rel.relnamespace
WHERE ns.nspname='ops' AND rel.relname=ANY(CAST(:tables AS text[]))
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
         'collation', CASE WHEN att.attcollation=0 THEN NULL
                           ELSE coll_ns.nspname || '.' || coll.collname END
       ) AS payload
FROM pg_catalog.pg_attribute AS att
JOIN pg_catalog.pg_class AS rel ON rel.oid=att.attrelid
JOIN pg_catalog.pg_namespace AS ns ON ns.oid=rel.relnamespace
LEFT JOIN pg_catalog.pg_attrdef AS def
  ON def.adrelid=att.attrelid AND def.adnum=att.attnum
LEFT JOIN pg_catalog.pg_collation AS coll ON coll.oid=att.attcollation
LEFT JOIN pg_catalog.pg_namespace AS coll_ns ON coll_ns.oid=coll.collnamespace
WHERE ns.nspname='ops' AND rel.relname=ANY(CAST(:tables AS text[]))
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
             ON att.attrelid=con.conrelid AND att.attnum=key.attnum
           ORDER BY key.ordinal
         ),
         'referenced_relation', CASE WHEN con.confrelid=0 THEN NULL
           ELSE ref_ns.nspname || '.' || ref_rel.relname END,
         'referenced_columns', ARRAY(
           SELECT att.attname
           FROM unnest(con.confkey) WITH ORDINALITY AS key(attnum, ordinal)
           JOIN pg_catalog.pg_attribute AS att
             ON att.attrelid=con.confrelid AND att.attnum=key.attnum
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
JOIN pg_catalog.pg_class AS rel ON rel.oid=con.conrelid
JOIN pg_catalog.pg_namespace AS ns ON ns.oid=rel.relnamespace
LEFT JOIN pg_catalog.pg_class AS ref_rel ON ref_rel.oid=con.confrelid
LEFT JOIN pg_catalog.pg_namespace AS ref_ns ON ref_ns.oid=ref_rel.relnamespace
WHERE (ns.nspname='ops' AND rel.relname=ANY(CAST(:tables AS text[])))
   OR con.conname=ANY(CAST(:extra_constraints AS text[]))
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
           JOIN pg_catalog.pg_opclass AS opc ON opc.oid=item.opclass_oid
           JOIN pg_catalog.pg_namespace AS opc_ns ON opc_ns.oid=opc.opcnamespace
           ORDER BY item.ordinal
         )
       ) AS payload
FROM pg_catalog.pg_index AS idx
JOIN pg_catalog.pg_class AS rel ON rel.oid=idx.indrelid
JOIN pg_catalog.pg_namespace AS ns ON ns.oid=rel.relnamespace
JOIN pg_catalog.pg_class AS idx_rel ON idx_rel.oid=idx.indexrelid
JOIN pg_catalog.pg_am AS am ON am.oid=idx_rel.relam
WHERE (ns.nspname='ops' AND rel.relname=ANY(CAST(:tables AS text[])))
   OR (ns.nspname='ops' AND idx_rel.relname='uq_poi_cache_targets_source_identity')
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
JOIN pg_catalog.pg_class AS rel ON rel.oid=trg.tgrelid
JOIN pg_catalog.pg_namespace AS ns ON ns.oid=rel.relnamespace
JOIN pg_catalog.pg_proc AS proc ON proc.oid=trg.tgfoid
JOIN pg_catalog.pg_namespace AS proc_ns ON proc_ns.oid=proc.pronamespace
WHERE ns.nspname='ops' AND rel.relname=ANY(CAST(:tables AS text[]))
  AND NOT trg.tgisinternal
ORDER BY identity
"""

_FUNCTIONS_SQL: Final = """
WITH required AS (
  SELECT signature, pg_catalog.to_regprocedure(signature) AS function_oid
  FROM unnest(CAST(:function_signatures AS text[])) AS item(signature)
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
         'body', proc.prosrc,
         'owner_matches_outbox_table', proc.proowner=outbox.relowner
       ) AS payload
FROM required
JOIN pg_catalog.pg_proc AS proc ON proc.oid=required.function_oid
JOIN pg_catalog.pg_namespace AS ns ON ns.oid=proc.pronamespace
JOIN pg_catalog.pg_language AS lang ON lang.oid=proc.prolang
JOIN pg_catalog.pg_class AS outbox
  ON outbox.oid=to_regclass('ops.poi_cache_target_outbox_events')
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
         'owner_matches_outbox_table', seq_rel.relowner=outbox.relowner,
         'owned_by', owned_ns.nspname || '.' || owned_rel.relname || '.' || owned_att.attname
       ) AS payload
FROM pg_catalog.pg_sequence AS seq
JOIN pg_catalog.pg_class AS seq_rel ON seq_rel.oid=seq.seqrelid
JOIN pg_catalog.pg_namespace AS ns ON ns.oid=seq_rel.relnamespace
JOIN pg_catalog.pg_class AS outbox
  ON outbox.oid=to_regclass('ops.poi_cache_target_outbox_events')
LEFT JOIN pg_catalog.pg_depend AS dep
  ON dep.classid='pg_class'::regclass AND dep.objid=seq_rel.oid
 AND dep.refclassid='pg_class'::regclass AND dep.deptype IN ('a','i')
LEFT JOIN pg_catalog.pg_class AS owned_rel ON owned_rel.oid=dep.refobjid
LEFT JOIN pg_catalog.pg_namespace AS owned_ns ON owned_ns.oid=owned_rel.relnamespace
LEFT JOIN pg_catalog.pg_attribute AS owned_att
  ON owned_att.attrelid=owned_rel.oid AND owned_att.attnum=dep.refobjsubid
WHERE ns.nspname='ops' AND seq_rel.relname='poi_cache_target_outbox_relay_order_seq'
ORDER BY identity
"""

_CATALOG_QUERIES: Final = {
    "relations": _RELATIONS_SQL,
    "columns": _COLUMNS_SQL,
    "constraints": _CONSTRAINTS_SQL,
    "indexes": _INDEXES_SQL,
    "triggers": _TRIGGERS_SQL,
    "functions": _FUNCTIONS_SQL,
    "sequence": _SEQUENCE_SQL,
}


async def collect_catalog_objects(
    connection: AsyncConnection,
) -> dict[str, dict[str, object]]:
    """catalog structured field와 PostgreSQL canonical definition을 수집한다."""
    parameters = {
        "tables": list(_TABLES),
        "extra_constraints": list(_EXTRA_CONSTRAINTS),
        "function_signatures": list(_FUNCTION_SIGNATURES),
    }
    catalog: dict[str, dict[str, object]] = {}
    for category, query in _CATALOG_QUERIES.items():
        rows = (await connection.execute(text(query), parameters)).mappings().all()
        catalog[category] = {str(row["identity"]): row["payload"] for row in rows}
    return catalog


def catalog_fingerprints(
    catalog: Mapping[str, Mapping[str, object]],
) -> dict[str, str]:
    """category별 identity→structured payload map의 canonical SHA-256을 만든다."""
    return {
        category: hashlib.sha256(canonical_json_bytes(dict(objects))).hexdigest()
        for category, objects in sorted(catalog.items())
    }


__all__ = [
    "EXPECTED_CATALOG_FINGERPRINTS",
    "catalog_fingerprints",
    "collect_catalog_objects",
]
