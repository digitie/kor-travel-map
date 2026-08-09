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

1~4는 전부 **계약 ↔ 계약** 대조라 계약이 실제 migration과 갈라져도 green이다.
그래서 T-VN-33 감사에서 계약 파일이 pair 시절 guard를 그대로 들고 있는데도 이
파일 전체가 통과하는 거짓 green이 확인됐다. 다섯 번째 축이 그 사각을 닫는다:

5. ``tvn33-reference-ownership-v1.sql``이 선언한 제약·트리거·함수가
   ``alembic upgrade head``의 DB에도 같은 정의로 있다
   (``test_frozen_contract_matches_alembic_head``).
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import AsyncIterator, Sequence
from pathlib import Path
from typing import Any, Final
from uuid import UUID, uuid4

import asyncpg
import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine

from kortravelmap.cli._h35_contract import canonical_json_bytes
from kortravelmap.infra.db import make_async_engine, normalize_async_dsn

pytestmark = pytest.mark.integration

_ROOT: Final = Path(__file__).resolve().parents[2]
_CONTRACTS: Final = _ROOT / "contracts" / "vnext"
_SCHEMA_SQL: Final = _CONTRACTS / "target-schema-v1.sql"
_REFERENCE_OWNERSHIP_SQL: Final = _CONTRACTS / "tvn33-reference-ownership-v1.sql"
_INVARIANTS_SQL: Final = _CONTRACTS / "target-invariants-v1.sql"
_FINGERPRINTS_JSON: Final = _CONTRACTS / "target-schema-fingerprints-v1.json"
_VIOLATIONS_SQL: Final = _CONTRACTS / "violation-fixtures-v1.sql"
_REJECTIONS_JSON: Final = _CONTRACTS / "expected-rejections-v1.json"

_EXPECTED_INVARIANT_COUNT: Final = 58
_INVARIANT_PHASES: Final = frozenset({"pre-backfill", "post-backfill", "both"})

# fingerprint 대상 — target-schema-v1.sql과 T-VN-33 reference ownership DDL의 전체 relation.
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
    "provider_sync.provider_dataset_operation_scopes",
    "provider_sync.source_entities",
    "provider_sync.source_records",
    "provider_sync.source_entity_heads",
    "provider_sync.source_links",
    "provider_sync.notice_states",
    "provider_sync.notice_lifecycle_scopes",
    "provider_sync.notice_lineage_states",
    "ops.feature_override_field_paths",
    "ops.feature_overrides",
    "ops.current_summary_runs",
    "provider_sync.provider_sync_state",
    "feature.curated_sources",
    "feature.curated_source_rules",
    "ops.import_jobs",
    "ops.import_job_datasets",
    "ops.import_job_events",
    "ops.feature_update_requests",
    "ops.feature_update_request_datasets",
    "ops.provider_refresh_policies",
    "ops.offline_uploads",
    "ops.integrity_observation_scopes",
    "ops.integrity_observation_runs",
    "ops.data_integrity_violations",
    "ops.poi_cache_targets",
    "ops.poi_cache_target_feature_links",
    "ops.enrichment_review_queue",
    "ops.managed_files",
)
_TARGET_RELATIONS: Final = (*_TARGET_TABLES, "feature.public_features")
_TARGET_FUNCTIONS: Final = (
    "feature.force_features_row_revision()",
    "feature.prepare_feature_state_context(jsonb,text)",
    "feature.write_feature_state_transition()",
    "feature.reject_feature_state_transition_mutation()",
    "feature.create_feature_with_initial_state(jsonb,text,text,text,jsonb)",
    "feature.transition_feature_state(uuid,text,text,text,bigint,jsonb)",
    "provider_sync.is_valid_provider_dataset_capabilities(jsonb)",
    "provider_sync.is_valid_provider_dataset_sync_scope(text)",
    "provider_sync.reject_provider_dataset_identity_update()",
    "provider_sync.touch_provider_dataset()",
    "provider_sync.assert_active_provider_dataset(bigint)",
    "provider_sync.reject_inactive_provider_dataset()",
    "provider_sync.assert_active_source_entity_dataset(text)",
    "provider_sync.reject_inactive_source_entity_dataset()",
    "provider_sync.touch_provider_dataset_operation()",
    "provider_sync.reject_source_record_update()",
    "ops.reject_terminal_current_summary_run_mutation()",
    "feature.reject_weather_value_mutation()",
    "feature.reject_price_value_mutation()",
    "provider_sync.enforce_source_entity_head_freshness()",
    "provider_sync.enforce_source_entity_identity_and_seen_at()",
    "provider_sync.assert_source_entity_head_completeness()",
    # 실행 membership 4테이블의 triple 가드 (alembic 0091/0092와 동일 정의).
    # pair 시절의 `assert_active_provider_dataset_scope(bigint,text)` /
    # `reject_inactive_provider_dataset_scope()`가 이 넷으로 갈라졌다.
    "provider_sync.reject_inactive_sync_state_operation()",
    "provider_sync.reject_inactive_import_job_dataset_membership()",
    "provider_sync.reject_inactive_feature_update_request_dataset_membership()",
    "provider_sync.reject_inactive_offline_upload_membership()",
    "provider_sync.assert_active_notice_lifecycle_scope(bigint)",
    "provider_sync.reject_inactive_notice_lifecycle_scope()",
    "provider_sync.assert_active_curated_source_dataset(uuid)",
    "provider_sync.reject_inactive_curated_source_dataset()",
    "provider_sync.assert_import_job_members_active(uuid)",
    "provider_sync.reject_inactive_import_job_members()",
    "provider_sync.assert_import_job_membership_complete()",
    "provider_sync.assert_import_job_event_member(uuid,uuid)",
    "provider_sync.reject_inactive_import_job_dataset()",
    "provider_sync.assert_feature_update_request_members_active(uuid)",
    "provider_sync.reject_inactive_feature_update_request_members()",
    "provider_sync.assert_feature_update_request_membership_complete()",
    "provider_sync.assert_active_integrity_observation_scope(bigint)",
    "provider_sync.reject_inactive_integrity_observation_scope()",
    "provider_sync.assert_active_source_record_dataset(text)",
    "provider_sync.validate_data_integrity_violation_dataset()",
    # `ops.managed_files` 전용 가드 (alembic 0092). registry는 storage의 거울이라
    # 활성 검사 대상이 아니고 소유권 immutable만 남는다.
    "provider_sync.reject_managed_file_dataset_rebinding()",
)

# 계약이 목표 명명으로 다시 선언했지만 head는 선행 migration의 옛 이름을 쓰는 제약.
# 정의(`pg_get_constraintdef`)가 같은 relation에서 완전히 일치하는 것만 여기 들어온다
# (`_renamed_in_head`가 그렇게 판정한다) — T-VN-33은 제약 rename을 하지 않는다.
# `test_frozen_contract_matches_alembic_head`가 이 목록과 실측이 **정확히** 같은지
# 단언하므로, 새 이름 불일치가 생기거나 head가 수렴하면 red가 된다.
_CONSTRAINTS_RENAMED_IN_HEAD: Final = frozenset(
    {
        "feature.curated_source_rules.fk_curated_source_rules_source",
        "feature.curated_source_rules.fk_curated_source_rules_theme",
        "feature.curated_source_rules.pk_curated_source_rules",
        "feature.curated_sources.pk_curated_sources",
        "ops.data_integrity_violations.ck_data_integrity_violations_status",
        "ops.data_integrity_violations.fk_data_integrity_violations_source_record",
        "ops.enrichment_review_queue.fk_enrichment_review_queue_feature",
        "ops.enrichment_review_queue.uq_enrichment_review_queue_identity",
        "ops.import_job_datasets.uq_import_job_datasets_identity",
        "ops.import_job_events.fk_import_job_events_job",
        "ops.import_job_events.pk_import_job_events",
        "ops.import_jobs.ck_import_jobs_status_target",
        "ops.integrity_observation_runs.uq_integrity_observation_runs_generation",
        "ops.managed_files.ck_managed_files_owner",
        "ops.managed_files.uq_managed_files_location_path",
        "ops.poi_cache_target_feature_links.fk_poi_cache_target_feature_links_feature",
        "ops.poi_cache_target_feature_links.fk_poi_cache_target_feature_links_target",
        "ops.provider_refresh_policies.ck_provider_refresh_policy_concurrent",
        "ops.provider_refresh_policies.ck_provider_refresh_policy_interval",
        "ops.provider_refresh_policies.ck_provider_refresh_policy_stale_after",
    }
)

# 계약이 목표 상태로 선언했지만 head가 아직 그 형태로 갖고 있지 않은 제약.
# `target-schema-v1.sql`/T-VN-33 계약은 도달점 선언이고 head는 현재 상태라 이 간극은
# 정상이다 — 다만 **어느 것이 왜 비었는지**를 여기 적어 두지 않으면 진짜 결함이
# 섞여 들어와도 보이지 않는다. 값은 head DB 실측(`head@relation` 진단 출력) 근거다.
# `test_frozen_contract_matches_alembic_head`가 이 목록과 실측이 정확히 같은지
# 단언하므로, head가 수렴하거나 새 간극이 생기면 red가 된다.
_CONSTRAINTS_ABSENT_FROM_HEAD: Final[dict[str, str]] = {
    "feature.curated_sources.ck_curated_sources_metadata": (
        "head의 curated_sources에는 metadata jsonb 축이 없다 — 제약 자체가 없다."
    ),
    "ops.feature_update_requests.ck_feature_update_requests_status_target": (
        "head의 feature_update_requests에는 status 컬럼 CHECK가 없다"
        "(run_mode/scope_type/membership_mode 축만 있다)."
    ),
    "ops.integrity_observation_scopes.ck_integrity_observation_scopes_generation": (
        "head는 더 강한 술어를 다른 이름으로 갖는다 — "
        "ck_integrity_observation_scopes_ck_integrity_observatio_2e27 = "
        "latest_generation >= 0 AND latest_authoritative_generation >= 0 "
        "AND latest_authoritative_generation <= latest_generation."
    ),
    "ops.offline_uploads.ck_offline_uploads_checksum": (
        "head는 같은 정규식을 ck_offline_uploads_ck_offline_uploads_checksum_sha256으로 "
        "갖는다. 이름뿐 아니라 컬럼 타입도 달라(varchar → `checksum_sha256::text ~ ...`) "
        "정의 문자열이 일치하지 않는다."
    ),
    "ops.poi_cache_targets.uq_poi_cache_targets_identity": (
        "head는 (external_system, target_key) 유일성을 테이블 제약이 아니라 "
        "부분 UNIQUE **인덱스** uq_poi_cache_targets_active_key "
        "(`WHERE deleted_at IS NULL`, alembic 0009)로 건다 — pg_constraint에 나타나지 "
        "않고, soft-delete 행에는 걸리지 않아 계약의 무조건 UNIQUE보다 약하다."
    ),
    "provider_sync.provider_sync_state.ck_provider_sync_state_cursor": (
        "head의 provider_sync_state에는 cursor jsonb_typeof CHECK가 없다."
    ),
    "provider_sync.provider_sync_state.ck_provider_sync_state_status": (
        "head는 같은 값 집합을 ck_provider_sync_state_ck_provider_sync_state_status로 "
        "갖는다. status 컬럼이 varchar라 정의가 "
        "`status::text = ANY (ARRAY[...]::character varying[]::text[])`로 찍혀 "
        "계약(text)과 문자열이 다르다."
    ),
}

# 계약과 head가 **같은 이름**으로 갖고 있으나 `pg_get_indexdef` 문자열이 갈리는 index.
# 여기 있는 것만 differs에서 면제된다 — 나머지는 전부 red다.
# `test_frozen_contract_matches_alembic_head`가 이 목록과 실측이 정확히 같은지
# 단언하므로 새 divergence가 조용히 늘거나 head가 수렴해도 red가 된다.
_INDEXES_DIVERGENT_FROM_HEAD: Final[dict[str, str]] = {
    "provider_sync.provider_sync_state.idx_provider_sync_state_next_run": (
        "열·정렬·부분 술어가 같고 술어의 캐스팅 표기만 다르다: 계약 "
        "`WHERE status = 'active'::text` vs head `WHERE status::text = 'active'::text`. "
        "원인은 status 컬럼 타입이다 — head 실측 information_schema.columns.data_type = "
        "'character varying', 계약 선언 = text. 같은 간극을 CHECK 축에서는 "
        "_CONSTRAINTS_ABSENT_FROM_HEAD의 ck_provider_sync_state_status가 이미 기록하고 "
        "있다. text가 vNext 도착점이고 varchar가 선행 상태이므로 계약을 head에 맞추지 "
        "않는다 — 맞추면 계약이 도착점 선언이기를 그만두게 된다."
    ),
}

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

# 계약 ↔ head 대조 전용 index 축. `_INDEXES_SQL`(fingerprint용)과 갈라 두는 이유는
# 두 가지다:
#   * fingerprint payload는 `indoption`/`indclass` 같은 catalog 내부 표현까지 담아
#     사람이 읽는 진단으로 쓸 수 없다. 대조에는 `pg_get_indexdef` 한 문자열이면
#     충분하고, 그 한 문자열에 열·정렬·INCLUDE·부분 술어·연산자 클래스가 모두 들어
#     있다(실측: head의 idx_import_job_events_member_time은 `INCLUDE (level)`과
#     `WHERE ... AND quarantined_at IS NULL`까지 이 문자열에 찍힌다).
#   * `_INDEXES_SQL`을 건드리면 frozen fingerprint가 통째로 바뀐다.
#
# 제약이 뒤에 만든 index(PK/UNIQUE/EXCLUDE backing index)는 제외한다 — 그쪽은
# constraints 축이 `pg_get_constraintdef`로 이미 대조하고, rename/부재 목록도 거기
# 달려 있다. 여기 다시 넣으면 같은 divergence를 두 축에서 두 번 세게 된다.
_INDEX_DEFS_SQL: Final = """
SELECT ns.nspname || '.' || rel.relname || '.' || idx_rel.relname AS identity,
       jsonb_build_object(
         'schema', ns.nspname,
         'relation', rel.relname,
         'name', idx_rel.relname,
         'definition', pg_catalog.pg_get_indexdef(idx.indexrelid, 0, true)
       ) AS payload
FROM pg_catalog.pg_index AS idx
JOIN pg_catalog.pg_class AS rel ON rel.oid = idx.indrelid
JOIN pg_catalog.pg_namespace AS ns ON ns.oid = rel.relnamespace
JOIN pg_catalog.pg_class AS idx_rel ON idx_rel.oid = idx.indexrelid
WHERE ns.nspname || '.' || rel.relname = ANY($1::text[])
  AND NOT EXISTS (
    SELECT 1 FROM pg_catalog.pg_constraint AS con WHERE con.conindid = idx.indexrelid
  )
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

_CONTRACT_SCHEMAS: Final = ("feature", "provider_sync", "ops")

# 인자 **타입만**으로 signature를 만든다. `pg_get_function_identity_arguments`는
# 인자 이름까지 붙여서(`(dataset_id bigint, scope_value text)`) 돌려주므로
# `to_regprocedure`가 파싱하지 못한다 — `_FUNCTIONS_SQL`의 `required_signature`
# 입력으로 쓰려면 `_TARGET_FUNCTIONS`와 같은 `schema.name(type,type)` 꼴이어야 한다.
_SCHEMA_FUNCTIONS_SQL: Final = """
SELECT ns.nspname || '.' || proc.proname || '(' || COALESCE(
         (
           SELECT string_agg(pg_catalog.format_type(item.type_oid, NULL), ',' ORDER BY item.ordinal)
           FROM unnest(proc.proargtypes) WITH ORDINALITY AS item(type_oid, ordinal)
         ),
         ''
       ) || ')' AS identity,
       proc.prosrc AS body
FROM pg_catalog.pg_proc AS proc
JOIN pg_catalog.pg_namespace AS ns ON ns.oid = proc.pronamespace
WHERE ns.nspname = ANY($1::text[])
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
async def _freeze_contract(
    pg_container: Any,
) -> AsyncIterator[tuple[asyncpg.Connection, dict[str, frozenset[str]]]]:
    """새 database + x_extension 확장 위에 target-schema-v1.sql을 적용한다.

    `migrated_engine`(alembic head)이 아니라 **빈 PostGIS DB**가 대상이다 —
    freeze DDL은 자기완결로 적용 가능해야 한다.

    두 계약 파일 사이에서 catalog를 한 번 스냅샷해, 두 번째 파일
    (`tvn33-reference-ownership-v1.sql`)이 **새로 선언한** 제약·트리거·함수
    identity 집합을 뽑는다. 이 집합이 `test_frozen_contract_matches_alembic_head`의
    대조 범위다 — 텍스트 파싱이 아니라 DB catalog 차분이므로, 계약에 객체를 더하면
    대조 범위도 자동으로 넓어진다(파싱 실패로 게이트가 조용히 좁아지지 않는다).
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
        before = await _declarable_identities(connection)
        before_bodies = await _schema_function_bodies(connection)
        await connection.execute(_REFERENCE_OWNERSHIP_SQL.read_text(encoding="utf-8"))
        after = await _declarable_identities(connection)
        after_bodies = await _schema_function_bodies(connection)
        declared = {
            category: frozenset(after[category] - before[category]) for category in after
        }
        # `CREATE OR REPLACE`로 **본문만** 바꾼 함수는 identity 차집합에 안 잡힌다 —
        # 그런 함수는 계약이 head와 갈려도 대조 범위 밖이라 조용히 통과한다(실측:
        # `provider_sync.reject_inactive_provider_dataset`은 target-schema-v1.sql이
        # 만들고 이 파일이 0092 본문으로 다시 쓴다). 본문이 달라진 것도 "이 파일이
        # 선언한 것"으로 세어 대조 범위에 넣는다.
        declared["functions"] = frozenset(
            declared["functions"]
            | {
                identity
                for identity, body in after_bodies.items()
                if identity in before_bodies and before_bodies[identity] != body
            }
        )
        yield connection, declared
    finally:
        await connection.close()
        admin_engine = make_async_engine(admin_dsn)
        try:
            async with admin_engine.connect() as raw_connection:
                autocommit = await raw_connection.execution_options(isolation_level="AUTOCOMMIT")
                await autocommit.execute(text(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)'))
        finally:
            await admin_engine.dispose()


@pytest.fixture(scope="module")
def freeze_db(
    _freeze_contract: tuple[asyncpg.Connection, dict[str, frozenset[str]]],
) -> asyncpg.Connection:
    """계약 두 파일이 모두 적용된 DB 연결."""
    return _freeze_contract[0]


@pytest.fixture(scope="module")
def tvn33_declared_identities(
    _freeze_contract: tuple[asyncpg.Connection, dict[str, frozenset[str]]],
) -> dict[str, frozenset[str]]:
    """`tvn33-reference-ownership-v1.sql`이 새로 선언한 catalog 객체 identity."""
    return _freeze_contract[1]


@pytest.fixture(scope="module")
async def head_db(migrated_engine: AsyncEngine) -> AsyncIterator[asyncpg.Connection]:
    """`alembic upgrade head`가 적용된 DB로의 asyncpg 연결.

    `freeze_db`(계약 DDL만 적용)의 **대조군**이다. 두 fixture가 함께 있어야
    "계약이 실제 migration 결과와 같은 스키마를 만든다"를 기계로 확인할 수 있다.
    """
    connection = await _connect(migrated_engine.url.render_as_string(hide_password=False))
    try:
        yield connection
    finally:
        await connection.close()


async def _catalog_objects(
    connection: asyncpg.Connection, query: str, parameter: Sequence[str]
) -> dict[str, Any]:
    rows = await connection.fetch(query, list(parameter))
    return {str(row["identity"]): row["payload"] for row in rows}


async def _declarable_identities(connection: asyncpg.Connection) -> dict[str, set[str]]:
    """대조 축 4종(제약·index·트리거·함수)의 현재 identity 집합."""
    constraints = await connection.fetch(_CONSTRAINTS_SQL, list(_TARGET_TABLES))
    indexes = await connection.fetch(_INDEX_DEFS_SQL, list(_TARGET_TABLES))
    triggers = await connection.fetch(_TRIGGERS_SQL, list(_TARGET_TABLES))
    functions = await connection.fetch(_SCHEMA_FUNCTIONS_SQL, list(_CONTRACT_SCHEMAS))
    return {
        "constraints": {str(row["identity"]) for row in constraints},
        "indexes": {str(row["identity"]) for row in indexes},
        "triggers": {str(row["identity"]) for row in triggers},
        "functions": {str(row["identity"]) for row in functions},
    }


async def _schema_function_bodies(connection: asyncpg.Connection) -> dict[str, str]:
    """계약 schema 함수의 identity → `prosrc`."""
    rows = await connection.fetch(_SCHEMA_FUNCTIONS_SQL, list(_CONTRACT_SCHEMAS))
    return {str(row["identity"]): str(row["body"]) for row in rows}


def _relation_of(payload: Any) -> str:
    return f"{payload.get('schema')}.{payload.get('relation')}"


def _renamed_in_head(
    contract: dict[str, Any], head: dict[str, Any]
) -> frozenset[str]:
    """계약 이름으로는 head에 없지만, **같은 relation에 정의가 동일한 제약**이 있는 것.

    T-VN-33 계약은 선행 테이블(`ops.import_jobs` 등)까지 목표 명명으로 다시 적지만
    head의 그 제약들은 선행 migration이 붙인 옛 이름을 그대로 쓴다. T-VN-33은 제약
    rename을 하지 않으므로 이건 divergence가 아니다 — 다만 조용히 늘지 않도록
    호출부가 목록과 정확히 일치하는지 단언한다.
    """
    head_definitions = {
        (str(payload["schema"]), str(payload["relation"]), str(payload["definition"]))
        for payload in head.values()
    }
    return frozenset(
        identity
        for identity, payload in contract.items()
        if identity not in head
        and (str(payload["schema"]), str(payload["relation"]), str(payload["definition"]))
        in head_definitions
    )


def _executable_body(body: str) -> str:
    """`prosrc`에서 SQL 주석을 걷어내고 연속 공백을 접는다.

    계약은 손으로 쓴 DDL, head는 migration 문자열이라 들여쓰기가 다르고, 각 문장의
    근거 주석은 migration 쪽에만 길게 달려 있다. 주석과 들여쓰기까지 대조하면
    계약이 migration의 글자 사본이 되어야 하므로 **실행되는 문장만** 남겨 비교한다.
    토큰이 하나라도 바뀌면(가드 술어, 예외 메시지, ERRCODE, 분기) 여전히 red다.
    이 함수들의 문자열 리터럴에는 `--`도 연속 공백도 없다 — 전부 한 칸짜리 영어
    문장이라 이 정규화가 가리는 의미 차이가 없다.
    """
    without_block_comments = re.sub(r"/\*.*?\*/", " ", body, flags=re.DOTALL)
    without_comments = re.sub(r"--[^\n]*", " ", without_block_comments)
    return " ".join(without_comments.split())


def _normalize_function_bodies(objects: dict[str, Any]) -> dict[str, Any]:
    """함수 payload의 `body`를 실행 문장만 남긴 형태로 바꾼다."""
    folded: dict[str, Any] = {}
    for identity, payload in objects.items():
        normalized = dict(payload)
        normalized["body"] = _executable_body(str(payload["body"]))
        folded[identity] = normalized
    return folded


def _by_required_signature(objects: dict[str, Any]) -> dict[str, Any]:
    """함수 catalog를 요청 signature(`schema.name(type,type)`)로 다시 키잉한다.

    `_FUNCTIONS_SQL`이 돌려주는 identity는 인자 **이름**을 포함하므로 그대로 키로
    쓰면 인자 이름만 달라도 only-in-* 로 갈려 원인이 흐려진다. 이름 차이는
    payload의 `identity_arguments`에 그대로 남아 differs로 잡힌다.
    """
    return {str(payload["required_signature"]): payload for payload in objects.values()}


def _restrict(objects: dict[str, Any], identities: frozenset[str]) -> dict[str, Any]:
    """T-VN-33 계약이 선언한 identity만 남긴다."""
    return {identity: payload for identity, payload in objects.items() if identity in identities}


def _diff_catalog(
    category: str,
    contract: dict[str, Any],
    head: dict[str, Any],
    head_context: dict[str, Any] | None = None,
) -> list[str]:
    """계약 DB와 head DB의 같은 카테고리 catalog 객체를 identity 단위로 대조한다.

    `head_context`는 진단 출력 전용이다 — head 쪽 전량(대조 범위로 좁히기 전)을 넘기면
    only-in-contract 항목 옆에 같은 relation의 head 정의를 함께 찍는다.
    """
    # only-in-contract는 "head가 다른 이름으로 갖고 있다"와 "head에 없다"가 섞이므로
    # 같은 relation의 head 쪽 정의를 함께 찍는다 — 둘을 눈으로 갈라 볼 수 있어야 한다.
    head_by_relation: dict[str, list[str]] = {}
    for payload in (head if head_context is None else head_context).values():
        relation = f"{payload.get('schema')}.{payload.get('relation')}"
        head_by_relation.setdefault(relation, []).append(
            f"{payload.get('name')}={payload.get('definition')}"
        )
    problems = [
        f"[{category}] only-in-contract: {identity} — {contract[identity].get('definition')}"
        f" | head@relation: "
        f"{sorted(head_by_relation.get(_relation_of(contract[identity]), []))}"
        for identity in sorted(set(contract) - set(head))
    ]
    problems += [
        f"[{category}] only-in-head: {identity} — {head[identity].get('definition')}"
        for identity in sorted(set(head) - set(contract))
    ]
    for identity in sorted(set(contract) & set(head)):
        left, right = contract[identity], head[identity]
        if left == right:
            continue
        keys = sorted(key for key in set(left) | set(right) if left.get(key) != right.get(key))
        detail = "; ".join(
            f"{key}: contract={left.get(key)!r} head={right.get(key)!r}" for key in keys
        )
        problems.append(f"[{category}] differs: {identity} — {detail}")
    return problems


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
        error: asyncpg.PostgresError | None = None
        try:
            try:
                await freeze_db.execute(case_sql)
            except asyncpg.PostgresError as caught:
                error = caught
            else:
                raise AssertionError(f"case {name}: expected DB rejection was not raised")
        finally:
            await transaction.rollback()
        assert error is not None
        assert getattr(error, "sqlstate", None) == expected["sqlstate"], (
            f"case {name}: SQLSTATE {getattr(error, 'sqlstate', None)!r} != "
            f"{expected['sqlstate']!r} ({error})"
        )
        if "column" in expected:
            assert getattr(error, "column_name", None) == expected["column"], (
                f"case {name}: {error}"
            )
        else:
            constraint = getattr(error, "constraint_name", None)
            if constraint is not None:
                assert constraint == expected["constraint"], f"case {name}: {error}"
            else:
                assert expected["constraint"] in str(error), f"case {name}: {error}"


async def test_uuid_state_procedure_derives_provider_receipt_and_fences_retired_override(
    freeze_db: asyncpg.Connection,
) -> None:
    """final UUID procedure도 current 0095와 같은 provider proof/fence를 강제한다."""

    transaction = freeze_db.transaction()
    await transaction.start()
    try:
        feature_id = UUID("00000000-0000-0000-0000-000000003490")
        dataset_id = await freeze_db.fetchval(
            """
            INSERT INTO provider_sync.provider_datasets (
                provider, dataset_key, display_name, source_kind
            ) VALUES ('target-tvn34', 'state', 'Target T-VN-34 state', 'manual')
            RETURNING provider_dataset_id
            """
        )
        await freeze_db.execute(
            """
            INSERT INTO feature.categories (kind, code) VALUES ('place', 'target-tvn34')
            """
        )
        await freeze_db.execute(
            """
            INSERT INTO provider_sync.source_entities (
                source_entity_key, provider_dataset_id, source_entity_type, source_entity_id,
                first_seen_at, last_seen_at
            ) VALUES ('target-tvn34-entity', $1, 'place', 'target-tvn34-source', now(), now())
            """,
            dataset_id,
        )
        await freeze_db.execute(
            """
            INSERT INTO provider_sync.source_records (
                source_record_key, source_entity_key, raw_data, raw_payload_hash, fetched_at
            ) VALUES (
                'target-tvn34-record', 'target-tvn34-entity', '{}'::jsonb,
                '0000000000000000000000000000000000000000000000000000000000003490', now()
            )
            """
        )
        await freeze_db.execute(
            """
            INSERT INTO provider_sync.source_entity_heads (
                source_entity_key, current_source_record_key, observed_at
            ) VALUES ('target-tvn34-entity', 'target-tvn34-record', now())
            """
        )
        provider_context = {
            "transition_kind": "provider_sync",
            "reason_code": "provider_initial",
            "provider_dataset_id": dataset_id,
            "source_entity_key": "target-tvn34-entity",
            "source_record_key": "target-tvn34-record",
        }
        await freeze_db.execute("SET ROLE ktm_feature_runtime")
        try:
            await freeze_db.fetchrow(
                """
                CALL feature.create_feature_with_initial_state(
                    $1::jsonb, 'active', 'published', 'valid', $2::jsonb, NULL, NULL, NULL
                )
                """,
                    {
                        "feature_id": str(feature_id),
                        "kind": "place",
                        "name": "target provider feature",
                        "category_code": "target-tvn34",
                    },
                    provider_context,
                )
            unlinked_savepoint = freeze_db.transaction()
            await unlinked_savepoint.start()
            try:
                with pytest.raises(asyncpg.PostgresError) as unlinked:
                    await freeze_db.fetchrow(
                        """
                        CALL feature.transition_feature_state(
                            $1::uuid, 'retired', 'suppressed', 'valid', 1, $2::jsonb, NULL, NULL
                        )
                        """,
                        feature_id,
                        {**provider_context, "reason_code": "provider_retire"},
                    )
            finally:
                await unlinked_savepoint.rollback()
            assert unlinked.value.sqlstate == "23514"
            assert unlinked.value.constraint_name == "ck_feature_provider_source_provenance"

            forged_savepoint = freeze_db.transaction()
            await forged_savepoint.start()
            try:
                with pytest.raises(asyncpg.PostgresError) as forged:
                    await freeze_db.fetchrow(
                        """
                        CALL feature.transition_feature_state(
                            $1::uuid, 'retired', 'suppressed', 'valid', 1, $2::jsonb, NULL, NULL
                        )
                        """,
                        feature_id,
                        {
                            **provider_context,
                            "reason_code": "provider_retire",
                            "provider_evidence": {
                                "authoritative_receipt": "caller-forged"
                            },
                        },
                    )
            finally:
                await forged_savepoint.rollback()
            assert forged.value.sqlstate == "23514"
            assert forged.value.constraint_name == "ck_feature_state_transition_context"
        finally:
            await freeze_db.execute("RESET ROLE")

        await freeze_db.execute(
            """
            INSERT INTO provider_sync.source_links (
                feature_id, source_entity_key, source_role, match_method, confidence
            ) VALUES ($1::uuid, 'target-tvn34-entity', 'primary', 'fixture', 100)
            """,
            feature_id,
        )
        await freeze_db.execute(
            """
            INSERT INTO ops.feature_override_field_paths (field_path, value_type)
            VALUES ('lifecycle_state', 'string')
            """
        )
        await freeze_db.execute(
            """
            INSERT INTO ops.feature_overrides (
                feature_id, field_path, override_value, prevent_provider_reactivation, status,
                created_by
            ) VALUES ($1::uuid, 'lifecycle_state', '"active"'::jsonb, true, 'active',
                      'admin:target-tvn34')
            """,
            feature_id,
        )

        await freeze_db.execute("SET ROLE ktm_feature_runtime")
        try:
            await freeze_db.fetchrow(
                """
                CALL feature.transition_feature_state(
                    $1::uuid, 'retired', 'suppressed', 'valid', 1, $2::jsonb, NULL, NULL
                )
                """,
                feature_id,
                {**provider_context, "reason_code": "provider_retire"},
            )
            # ``override_value='active'``는 provider reactivation을 막지 않는다.
            reactivated = await freeze_db.fetchrow(
                """
                CALL feature.transition_feature_state(
                    $1::uuid, 'active', 'suppressed', 'valid', 2, $2::jsonb, NULL, NULL
                )
                """,
                feature_id,
                {**provider_context, "reason_code": "provider_reingest"},
            )
            assert reactivated["o_row_revision"] == 3
            await freeze_db.fetchrow(
                """
                CALL feature.transition_feature_state(
                    $1::uuid, 'retired', 'suppressed', 'valid', 3, $2::jsonb, NULL, NULL
                )
                """,
                feature_id,
                {**provider_context, "reason_code": "provider_retire"},
            )
        finally:
            await freeze_db.execute("RESET ROLE")

        await freeze_db.execute(
            """
            UPDATE ops.feature_overrides
            SET override_value = '"retired"'::jsonb
            WHERE feature_id = $1::uuid AND field_path = 'lifecycle_state' AND status = 'active'
            """,
            feature_id,
        )
        await freeze_db.execute("SET ROLE ktm_feature_runtime")
        try:
            fenced_savepoint = freeze_db.transaction()
            await fenced_savepoint.start()
            try:
                with pytest.raises(asyncpg.PostgresError) as fenced:
                    await freeze_db.fetchrow(
                        """
                        CALL feature.transition_feature_state(
                            $1::uuid, 'active', 'suppressed', 'valid', 4, $2::jsonb, NULL, NULL
                        )
                        """,
                        feature_id,
                        {**provider_context, "reason_code": "provider_reingest"},
                    )
            finally:
                await fenced_savepoint.rollback()
            assert fenced.value.sqlstate == "23514"
            assert fenced.value.constraint_name == "ck_feature_provider_reactivation_override"
        finally:
            await freeze_db.execute("RESET ROLE")

        audit = await freeze_db.fetchrow(
            """
            SELECT provider_dataset_id, source_entity_key, source_record_key, provider_evidence
            FROM feature.feature_state_transitions
            WHERE feature_id = $1::uuid AND transition_kind = 'provider_sync'
            ORDER BY transition_id
            LIMIT 1
            """,
            feature_id,
        )
        assert audit is not None
        assert dict(audit) == {
            "provider_dataset_id": dataset_id,
            "source_entity_key": "target-tvn34-entity",
            "source_record_key": "target-tvn34-record",
            "provider_evidence": {
                "authoritative_receipt": (
                    "00000000000000000000000000000000"
                    "00000000000000000000000000003490"
                )
            },
        }
    finally:
        await transaction.rollback()


async def test_final_target_excludes_current_user_provenance_snapshot_bridge(
    freeze_db: asyncpg.Connection,
) -> None:
    """0095 typed provenance/version bridge는 T36C 이후 final UUID target에 남지 않는다."""

    routine = await freeze_db.fetchval(
        """
        SELECT to_regprocedure(
            'feature.materialize_user_feature_change_provenance(text,text,uuid,text,text,bigint)'
        )
        """
    )
    assert routine is None
    assert await freeze_db.fetchval("SELECT to_regclass('feature.feature_versions')") is None
    legacy_columns = await freeze_db.fetchval(
        """
        SELECT count(*)
        FROM information_schema.columns
        WHERE table_schema = 'feature'
          AND table_name = 'features'
          AND column_name = ANY(
              ARRAY[
                  'data_origin', 'data_version', 'user_change_kind',
                  'user_change_status', 'user_change_request_id',
                  'user_deleted_at', 'user_deleted_by', 'user_change_reason'
              ]
          )
        """
    )
    assert legacy_columns == 0


async def test_multiple_records_with_one_head_satisfy_completeness_invariant(
    freeze_db: asyncpg.Connection,
) -> None:
    """정상 history 2건 + head 1건은 INV-069-06a를 위반하지 않는다."""
    transaction = freeze_db.transaction()
    await transaction.start()
    try:
        dataset_id = await freeze_db.fetchval(
            """
            INSERT INTO provider_sync.provider_datasets (
                provider, dataset_key, display_name, source_kind
            ) VALUES ('positive-fixture', 'head-history', 'head history', 'manual')
            RETURNING provider_dataset_id
            """
        )
        await freeze_db.execute(
            """
            INSERT INTO provider_sync.source_entities (
                source_entity_key, provider_dataset_id, source_entity_type,
                source_entity_id, first_seen_at, last_seen_at
            ) VALUES ('positive-head-entity', $1, 'place', 'positive-1', now(), now())
            """,
            dataset_id,
        )
        await freeze_db.execute(
            """
            INSERT INTO provider_sync.source_records (
                source_record_key, source_entity_key, raw_data, raw_payload_hash, fetched_at
            ) VALUES
                ('positive-head-record-a', 'positive-head-entity', '{}'::jsonb, 'b1', now()),
                ('positive-head-record-b', 'positive-head-entity', '{}'::jsonb, 'b2', now())
            """
        )
        await freeze_db.execute(
            """
            INSERT INTO provider_sync.source_entity_heads (
                source_entity_key, current_source_record_key, observed_at
            ) VALUES ('positive-head-entity', 'positive-head-record-b', now())
            """
        )
        await freeze_db.execute("SET CONSTRAINTS ALL IMMEDIATE")
        completeness_query = next(
            query
            for query, _phase in load_invariant_queries()
            if "count(DISTINCT head.source_entity_key)" in query
        )
        assert await freeze_db.fetchval(completeness_query) == 0
    finally:
        await transaction.rollback()


async def test_membership_modes_accept_only_a_complete_canonical_shape(
    freeze_db: asyncpg.Connection,
) -> None:
    """root job은 member 0개, single job/request는 member 1개일 때만 정상이다."""
    transaction = freeze_db.transaction()
    await transaction.start()
    try:
        dataset_id = await freeze_db.fetchval(
            """
            INSERT INTO provider_sync.provider_datasets (
                provider, dataset_key, display_name, source_kind
            ) VALUES ('positive-fixture', 'membership', 'membership', 'manual')
            RETURNING provider_dataset_id
            """
        )
        await freeze_db.execute(
            """
            INSERT INTO provider_sync.provider_dataset_operations (
                provider_dataset_id, operation_key, operation_kind
            ) VALUES ($1, 'refresh', 'refresh')
            """,
            dataset_id,
        )
        await freeze_db.execute(
            """
            INSERT INTO provider_sync.provider_dataset_operation_scopes (
                provider_dataset_id, sync_scope, operation_key
            ) VALUES ($1, 'dataset_wide', 'refresh')
            """,
            dataset_id,
        )
        single_job_id = await freeze_db.fetchval(
            """
            INSERT INTO ops.import_jobs (kind, dataset_membership_mode)
            VALUES ('positive-single-job', 'single')
            RETURNING job_id
            """
        )
        await freeze_db.execute(
            """
            INSERT INTO ops.import_job_datasets (
                job_id, provider_dataset_id, sync_scope, operation_key
            ) VALUES ($1, $2, 'dataset_wide', 'refresh')
            """,
            single_job_id,
            dataset_id,
        )
        await freeze_db.execute(
            "INSERT INTO ops.import_jobs (kind, dataset_membership_mode) VALUES ('root', 'root')"
        )
        request_id = await freeze_db.fetchval(
            """
            INSERT INTO ops.feature_update_requests (dataset_membership_mode)
            VALUES ('single')
            RETURNING request_id
            """
        )
        await freeze_db.execute(
            """
            INSERT INTO ops.feature_update_request_datasets (
                request_id, provider_dataset_id, sync_scope, operation_key
            ) VALUES ($1, $2, 'dataset_wide', 'refresh')
            """,
            request_id,
            dataset_id,
        )
        await freeze_db.execute("SET CONSTRAINTS ALL IMMEDIATE")
    finally:
        await transaction.rollback()


async def test_active_parent_cascades_preserve_indirect_owner_guards(
    freeze_db: asyncpg.Connection,
) -> None:
    """활성 parent의 FK cascade는 indirect active guard에 의해 막히지 않는다."""
    transaction = freeze_db.transaction()
    await transaction.start()
    try:
        dataset_id = await freeze_db.fetchval(
            """
            INSERT INTO provider_sync.provider_datasets (
                provider, dataset_key, display_name, source_kind
            ) VALUES ('positive-fixture', 'cascade-guard', 'cascade guard', 'manual')
            RETURNING provider_dataset_id
            """
        )
        notice_scope_id = await freeze_db.fetchval(
            """
            INSERT INTO provider_sync.notice_lifecycle_scopes (
                provider_dataset_id, source_entity_type, mode, applied_at, state_fingerprint
            ) VALUES ($1, 'notice', 'snapshot', now(), 'cascade-notice')
            RETURNING notice_lifecycle_scope_id
            """,
            dataset_id,
        )
        await freeze_db.execute(
            """
            INSERT INTO provider_sync.notice_lineage_states (
                notice_lifecycle_scope_id, lineage_key, present, changed_at
            ) VALUES ($1, 'cascade-lineage', true, now())
            """,
            notice_scope_id,
        )
        integrity_scope_id = await freeze_db.fetchval(
            """
            INSERT INTO ops.integrity_observation_scopes (provider_dataset_id)
            VALUES ($1)
            RETURNING integrity_observation_scope_id
            """,
            dataset_id,
        )
        await freeze_db.execute(
            """
            INSERT INTO ops.integrity_observation_runs (
                integrity_observation_scope_id, generation, external_run_id
            ) VALUES ($1, 1, 'cascade-run')
            """,
            integrity_scope_id,
        )
        theme_id = await freeze_db.fetchval(
            """
            INSERT INTO feature.curated_themes (theme_key, title)
            VALUES ('cascade-guard', 'cascade guard')
            RETURNING theme_id
            """
        )
        source_id = await freeze_db.fetchval(
            """
            INSERT INTO feature.curated_sources (
                provider_dataset_id, source_name, source_kind
            ) VALUES ($1, 'cascade source', 'fixture')
            RETURNING source_id
            """,
            dataset_id,
        )
        await freeze_db.execute(
            """
            INSERT INTO feature.curated_source_rules (theme_id, source_id)
            VALUES ($1, $2)
            """,
            theme_id,
            source_id,
        )

        await freeze_db.execute(
            "DELETE FROM provider_sync.notice_lifecycle_scopes "
            "WHERE notice_lifecycle_scope_id = $1",
            notice_scope_id,
        )
        await freeze_db.execute(
            "DELETE FROM ops.integrity_observation_scopes "
            "WHERE integrity_observation_scope_id = $1",
            integrity_scope_id,
        )
        await freeze_db.execute(
            "DELETE FROM feature.curated_sources WHERE source_id = $1",
            source_id,
        )

        assert (
            await freeze_db.fetchval(
                "SELECT count(*) FROM provider_sync.notice_lineage_states"
            )
            == 0
        )
        assert (
            await freeze_db.fetchval("SELECT count(*) FROM ops.integrity_observation_runs")
            == 0
        )
        assert (
            await freeze_db.fetchval("SELECT count(*) FROM feature.curated_source_rules")
            == 0
        )
    finally:
        await transaction.rollback()


async def test_kma_producing_response_lineage_and_feature_summary_cascade(
    freeze_db: asyncpg.Connection,
) -> None:
    """KMA grid는 anchor 입력일 뿐 forecast fact의 source가 아니다.

    feature 삭제는 파생 summary까지 끝낸다.
    """
    transaction = freeze_db.transaction()
    await transaction.start()
    try:
        feature_id = uuid4()
        await freeze_db.execute(
            "INSERT INTO feature.categories (kind, code) VALUES ('weather', 'positive-kma')"
        )
        await freeze_db.execute(
            """
            INSERT INTO feature.features (
                feature_id, kind, name, category_code,
                lifecycle_state, publication_state, quality_state
            ) VALUES ($1, 'weather', 'KMA response lineage', 'positive-kma',
                      'active', 'published', 'valid')
            """,
            feature_id,
        )
        grid_dataset_id = await freeze_db.fetchval(
            """
            INSERT INTO provider_sync.provider_datasets (
                provider, dataset_key, display_name, source_kind
            ) VALUES ('kma', 'positive-kma-grid', 'positive KMA grid', 'openapi')
            RETURNING provider_dataset_id
            """
        )
        forecast_dataset_id = await freeze_db.fetchval(
            """
            INSERT INTO provider_sync.provider_datasets (
                provider, dataset_key, display_name, source_kind
            ) VALUES ('kma', 'positive-kma-forecast', 'positive KMA forecast', 'openapi')
            RETURNING provider_dataset_id
            """
        )
        await freeze_db.execute(
            """
            INSERT INTO provider_sync.source_entities (
                source_entity_key, provider_dataset_id, source_entity_type, source_entity_id,
                first_seen_at, last_seen_at
            ) VALUES
                ('positive-kma-grid-entity', $1, 'grid', '60:127',
                 '2026-01-01T00:00:00+00', '2026-01-01T00:00:00+00'),
                ('positive-kma-response-entity', $2, 'weather-response', '2026-01-01T00',
                 '2026-01-01T00:00:00+00', '2026-01-01T00:00:00+00')
            """,
            grid_dataset_id,
            forecast_dataset_id,
        )
        await freeze_db.execute(
            """
            INSERT INTO provider_sync.source_records (
                source_record_key, source_entity_key, raw_data, raw_payload_hash, fetched_at
            ) VALUES
                ('positive-kma-grid-record', 'positive-kma-grid-entity', '{}'::jsonb, 'e1',
                 '2026-01-01T00:00:00+00'),
                ('positive-kma-response-record', 'positive-kma-response-entity', '{}'::jsonb, 'e2',
                 '2026-01-01T00:00:00+00')
            """
        )
        await freeze_db.execute(
            """
            INSERT INTO provider_sync.source_entity_heads (
                source_entity_key, current_source_record_key, observed_at
            ) VALUES
                ('positive-kma-grid-entity', 'positive-kma-grid-record', '2026-01-01T00:00:00+00'),
                (
                    'positive-kma-response-entity', 'positive-kma-response-record',
                    '2026-01-01T00:00:00+00'
                )
            """
        )
        await freeze_db.execute(
            """
            INSERT INTO feature.feature_weather_values (
                weather_value_key, feature_id, provider_dataset_id, weather_domain,
                forecast_style, metric_key, value_number, target_at, known_at,
                source_entity_key, source_record_key
            ) VALUES (
                'positive-kma-forecast-fact', $1, $2, 'forecast', 'short', 'TMP', 1.0,
                '2026-01-01T03:00:00+00', '2026-01-01T00:00:00+00',
                'positive-kma-response-entity', 'positive-kma-response-record'
            )
            """,
            feature_id,
            forecast_dataset_id,
        )
        receipt_id = await freeze_db.fetchval(
            """
            INSERT INTO ops.current_summary_runs (
                projection_kind, run_kind, status, started_at, finished_at
            ) VALUES (
                'weather', 'reconcile', 'succeeded',
                '2026-01-01T03:00:00+00', '2026-01-01T03:01:00+00'
            ) RETURNING summary_run_id
            """
        )
        await freeze_db.execute(
            """
            INSERT INTO feature.current_weather_summary (
                feature_id, provider_dataset_id, weather_domain, forecast_style, metric_key,
                weather_value_key, summary_run_id, selected_at, refresh_after
            ) VALUES (
                $1, $2, 'forecast', 'short', 'TMP', 'positive-kma-forecast-fact', $3,
                '2026-01-01T03:00:00+00', '2026-01-01T04:00:00+00'
            )
            """,
            feature_id,
            forecast_dataset_id,
            receipt_id,
        )
        assert await freeze_db.fetchval(
            "SELECT count(*) FROM feature.current_weather_summary"
        ) == 1

        await freeze_db.execute("DELETE FROM feature.features WHERE feature_id = $1", feature_id)

        assert await freeze_db.fetchval(
            "SELECT count(*) FROM feature.feature_weather_values"
        ) == 0
        assert await freeze_db.fetchval(
            "SELECT count(*) FROM feature.current_weather_summary"
        ) == 0
        await freeze_db.execute("SET CONSTRAINTS ALL IMMEDIATE")
    finally:
        await transaction.rollback()


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
    reference_sha = hashlib.sha256(_REFERENCE_OWNERSHIP_SQL.read_bytes()).hexdigest()
    assert reference_sha == frozen["tvn33_reference_ownership_sql_sha256"], (
        "tvn33-reference-ownership-v1.sql bytes drift — 재계산 " + reference_sha
    )


async def test_frozen_contract_matches_alembic_head(
    freeze_db: asyncpg.Connection,
    head_db: asyncpg.Connection,
    tvn33_declared_identities: dict[str, frozenset[str]],
) -> None:
    """T-VN-33 계약이 선언한 객체가 `alembic upgrade head`에도 그대로 있는지 대조한다.

    이 파일의 다른 테스트는 전부 `freeze_db` **한쪽만** 본다. fingerprint 테스트조차
    계약을 적용한 DB에서 뽑은 값과 계약에서 뽑아 둔 값을 맞춰 보는 계약↔계약 대조라,
    계약이 migration과 갈라져도 green이 된다(그래서 계약 파일이 pair 시절 guard를
    보존한 채로 CI가 통과했다). 이 테스트가 그 사각을 닫는다.

    **대조 범위** = `tvn33-reference-ownership-v1.sql`이 새로 만든 제약·트리거·함수
    **와 `CREATE OR REPLACE`로 본문을 다시 쓴 함수**(`tvn33_declared_identities`).
    두 계약 파일 사이의 catalog 차분이라 계약이 커지면 범위도 함께 커진다.
    축은 `pg_constraint` / `pg_index` / `pg_trigger` / `pg_proc`이고
    payload는 `pg_get_constraintdef` · `pg_get_indexdef` · `pg_get_triggerdef` ·
    `prosrc`까지 포함하므로 ON DELETE 동작, index의 열·정렬·INCLUDE·부분 술어,
    트리거가 실행하는 함수, 함수 본문이 한 글자라도 갈리면 red다.

    index 축은 라운드13에서 열었다. 그 전에는 축이 제약·트리거·함수 셋뿐이라
    같은 이름 index의 정의 차이가 대조되지 않았고, 실제로
    `idx_import_job_events_member_time`이 계약과 head에서 다른 정의로 공존했다.

    **범위 밖**: head에만 있는 객체. `target-schema-v1.sql`은 아직 도달하지 않은
    vNext 목표 상태(weather/price fact·typed notice_states는 T-VN-38/T-VN-37 소관)를
    담고 있고, T-VN-33 계약도 `ops.import_jobs` 같은 선행 테이블을 identity에
    필요한 만큼만 선언한다. 즉 계약은 head의 부분집합 선언이지 물리 스키마 전수
    사본이 아니다. 컬럼 물리 순서(`attnum`)도 같은 이유로 축이 아니다 — 계약은
    `CREATE TABLE` 한 번, head는 `ALTER TABLE` 누적이다.

    **컬럼 축(NOT NULL·타입)을 아직 열지 않은 이유**는 비용이 아니라 의미다. 라운드13에
    실측했다(`_TARGET_TABLES` 전체, 계약 DB ↔ head DB): 계약 291열 · head 486열 ·
    이름이 겹치는 220열 · 계약에만 있는 71열. 그 220열 중 **`attnotnull`이 갈리는 것은
    2건뿐**이라(`ops.feature_overrides.created_by`는 계약 NOT NULL/head nullable,
    `ops.import_job_events.level`은 계약 nullable/head NOT NULL) NOT NULL 축 자체는 싸다.
    문제는 같은 220열에서 **타입이 갈리는 것이 30건**이고 그 대부분이 legacy varchar →
    vNext text/uuid 수렴(다른 T-VN 과제 소관)이라는 점이다. 게다가 계약의 컬럼 층은
    의도적으로 stylized다 — 예를 들어 `ops.import_job_events`는 계약에만 있는
    `event_kind`를 갖고 `event_id`가 bigint identity인 반면 head는 uuid다(둘 다 실측).
    즉 "NOT NULL은 맞아야 하고 타입은 안 맞아도 된다"는 규칙은 계약의 컬럼 층이 무엇을
    선언하는 것인지 먼저 정해야 근거가 생긴다. 그 결정 없이 축만 켜면 allowlist가
    drift 기록이 아니라 to-do 목록이 된다.
    """
    declared_constraints = tvn33_declared_identities["constraints"]
    declared_indexes = tvn33_declared_identities["indexes"]
    declared_triggers = tvn33_declared_identities["triggers"]
    declared_functions = tuple(sorted(tvn33_declared_identities["functions"]))
    # 차분이 비면 대조가 통째로 사라진다(fail-open) — 계약 파일이 지워지거나
    # 스냅샷 순서가 깨진 경우가 그렇다. 실측 하한으로 못박는다.
    # 하한은 `alembic 0092` head + 현재 계약 파일에서 이 fixture가 실제로 뽑은 값이다:
    # 제약 76 · index 11 · 트리거 23 · 함수 22.
    #   * index 11 = 계약 파일의 `CREATE INDEX` 11문. 제약이 뒤에 만드는 backing
    #     index는 `_INDEX_DEFS_SQL`이 걸러내므로 여기 세지 않는다.
    #   * 트리거 23 = 계약 파일의 `CREATE TRIGGER` 19문 + `CREATE CONSTRAINT TRIGGER`
    #     4문. 앞 판의 하한 19는 뒤 4문을 빼먹은 값이었다.
    #   * 함수 22 = `CREATE FUNCTION` 21문 + `CREATE OR REPLACE`로 본문만 바꾼 1건
    #     (`provider_sync.reject_inactive_provider_dataset` — target-schema-v1.sql이
    #     만들고 이 계약이 0092 본문으로 다시 쓴다).
    # 계약이 커지면 이 하한도 같이 올려라.
    assert len(declared_constraints) >= 76, sorted(declared_constraints)
    assert len(declared_indexes) >= 11, sorted(declared_indexes)
    assert len(declared_triggers) >= 23, sorted(declared_triggers)
    assert len(declared_functions) >= 22, declared_functions

    head_indexes = await _catalog_objects(head_db, _INDEX_DEFS_SQL, _TARGET_TABLES)
    contract_indexes = _restrict(
        await _catalog_objects(freeze_db, _INDEX_DEFS_SQL, _TARGET_TABLES), declared_indexes
    )
    scoped_head_indexes = _restrict(head_indexes, declared_indexes)
    divergent = frozenset(
        identity
        for identity in set(contract_indexes) & set(scoped_head_indexes)
        if contract_indexes[identity] != scoped_head_indexes[identity]
    )
    assert divergent == frozenset(_INDEXES_DIVERGENT_FROM_HEAD), (
        "계약과 head가 같은 이름으로 다르게 갖고 있는 index 목록이 바뀌었다. 새 항목은 "
        "어느 쪽이 T-VN-33의 도착점인지 판단해 계약을 고치거나 근거를 실측해 "
        "_INDEXES_DIVERGENT_FROM_HEAD에 적고, 사라진 항목은 한쪽이 수렴한 것이니 빼라: "
        f"실측 - 목록: {sorted(divergent - frozenset(_INDEXES_DIVERGENT_FROM_HEAD))} / "
        f"목록 - 실측: {sorted(frozenset(_INDEXES_DIVERGENT_FROM_HEAD) - divergent)}"
    )
    problems = _diff_catalog(
        "indexes",
        {
            identity: payload
            for identity, payload in contract_indexes.items()
            if identity not in divergent
        },
        {
            identity: payload
            for identity, payload in scoped_head_indexes.items()
            if identity not in divergent
        },
        head_context=head_indexes,
    )

    problems += _diff_catalog(
        "triggers",
        _restrict(
            await _catalog_objects(freeze_db, _TRIGGERS_SQL, _TARGET_TABLES), declared_triggers
        ),
        _restrict(
            await _catalog_objects(head_db, _TRIGGERS_SQL, _TARGET_TABLES), declared_triggers
        ),
    )

    head_constraints = await _catalog_objects(head_db, _CONSTRAINTS_SQL, _TARGET_TABLES)
    contract_constraints = _restrict(
        await _catalog_objects(freeze_db, _CONSTRAINTS_SQL, _TARGET_TABLES), declared_constraints
    )
    renamed = _renamed_in_head(contract_constraints, head_constraints)
    assert renamed == _CONSTRAINTS_RENAMED_IN_HEAD, (
        "계약 이름 ↔ head 옛 이름 목록이 바뀌었다. 새 항목이 생겼다면 그 제약이 "
        "정말 이름만 다른지 확인하고, 사라졌다면 head가 수렴한 것이니 목록에서 빼라: "
        f"실측 - 목록: {sorted(renamed - _CONSTRAINTS_RENAMED_IN_HEAD)} / "
        f"목록 - 실측: {sorted(_CONSTRAINTS_RENAMED_IN_HEAD - renamed)}"
    )
    absent = frozenset(set(contract_constraints) - set(head_constraints) - renamed)
    assert absent == frozenset(_CONSTRAINTS_ABSENT_FROM_HEAD), (
        "계약이 선언했지만 head에 없는 제약 목록이 바뀌었다. 새 항목은 근거를 실측해 "
        "_CONSTRAINTS_ABSENT_FROM_HEAD에 적고, 사라진 항목은 head가 수렴한 것이니 빼라: "
        f"실측 - 목록: {sorted(absent - frozenset(_CONSTRAINTS_ABSENT_FROM_HEAD))} / "
        f"목록 - 실측: {sorted(frozenset(_CONSTRAINTS_ABSENT_FROM_HEAD) - absent)}"
    )
    problems += _diff_catalog(
        "constraints",
        {
            identity: payload
            for identity, payload in contract_constraints.items()
            if identity not in renamed and identity not in absent
        },
        _restrict(head_constraints, declared_constraints),
        head_context=head_constraints,
    )
    problems += _diff_catalog(
        "functions",
        _normalize_function_bodies(
            _by_required_signature(
                await _catalog_objects(freeze_db, _FUNCTIONS_SQL, declared_functions)
            )
        ),
        _normalize_function_bodies(
            _by_required_signature(
                await _catalog_objects(head_db, _FUNCTIONS_SQL, declared_functions)
            )
        ),
    )
    assert problems == [], (
        "frozen 계약과 alembic head가 갈라졌다 — 한쪽만 고쳤다는 뜻이다:\n" + "\n".join(problems)
    )
