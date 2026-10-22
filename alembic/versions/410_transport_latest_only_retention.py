"""transport 출처 데이터를 최신값만 두는 DB 경계(ADR-114).

Revision ID: 410_transport_latest_only_retention
Revises: 409_geo_release_item_reasons

왜 필요한가. 2026-10-23 소유자 결정으로 Map은 kor-travel-transport 출처 데이터의 이력을 보관하지
않는다(transport가 이미 이력을 갖는다). 정책의 정본은 ``kortravelmap.core.retention``이고, 이 revision은
그 정책이 지우려는 것을 **DB가 허용하는 좁은 길**만 만든다. 무엇을 언제 지울지는 애플리케이션이 정한다
(적재 transaction 안 — seal을 잡기 전 — 과 maintenance).

세 길은 모두 SECURITY DEFINER 함수다(소유자 ``ktm_feature_schema_owner``, EXECUTE는 ``ktm_feature_runtime``
에만). runtime에 표 DELETE 권한을 더 주지 않는다 — runtime은 provider 증거 표 몇 개를 읽을 수조차 없어서
(``ops.manual_provider_dedup_cases`` 등 ACL ``()``) 참조 검사를 애플리케이션 SQL로 할 수 없고, 함수가 하면
검사와 삭제가 같은 권한·같은 문장열 안에 있다. 셋 다 첫 줄에서 dataset이 **존재·활성·provider =
kor-travel-transport**인지 본다(ADR-114 결정 1의 provider 단위 fence).

무엇을 하는가(실행 순서 = ``_UPGRADE_STATEMENTS``)
--------------------------------------------------

1. ``feature.reject_price_value_mutation()`` — DELETE 예외를 하나 더한다: fact의 dataset이 활성
   kor-travel-transport dataset이고 ``feature.current_price_summary``가 그 fact를 가리키지 않을 때.
   UPDATE는 여전히 거부한다. 다른 provider의 fact는 종전처럼 불변이다(ADR-089).
2. 역참조 index 셋. record·entity를 지우면 PostgreSQL이 참조 행마다 FK 검사를 한다. 아래 셋은 참조 컬럼으로
   시작하는 index가 없어 지운 행마다 표 전체를 훑는다(2026-10-23 prod ``feature_base_field_values`` 약
   340만 행). 기존 ``idx_feature_base_field_values_source``는 ``provider_dataset_id``가 앞이라 FK 검사가 못
   쓴다. env의 한 transaction 안에서 돌아 ``CONCURRENTLY``를 못 쓴다 — build 동안 그 표의 쓰기가 멈춘다
   (읽기는 된다). 배포 창(적재 정지)에서 돈다.
3. ``feature.prune_transport_price_facts(bigint)`` — summary가 가리키지 않는 fact를 지운다. 호출자는
   ``projection:current-price-summary`` transaction advisory lock을 쥐고, 같은 transaction에서 summary를
   물화한 뒤 부른다(``price_repo.prune_superseded_price_facts``).
4. ``provider_sync.prune_latest_only_lineage(bigint)`` — (a) head가 아닌 record, (b) 어느 Feature에도
   link되지 않은 entity(와 그 head·record), (c) head가 사라진 notice 계보의 present=false 상태 행을 지운다.
   참조된 record·entity는 건너뛰고 센다. 판정은 ``pg_constraint`` 순회다 — ``confdeltype IN ('r','a')``
   (RESTRICT·NO ACTION)와, 값을 잃으면 의미를 잃는 ``SET NULL``(``ops.data_integrity_violations`` 하나만
   예외 — ADR-114가 받아들인 손실). 이 함수가 직접 지우는 내부 간선(head→record, head/record/link→entity)은
   뺀다. 목록을 손으로 적지 않으므로 새 참조 표가 생겨도 저절로 덮인다.
5. ``feature.purge_ended_provider_notices(bigint, interval)`` — 종료 뒤 유예가 지난 notice Feature를
   **실제로 지운다**. 대상: 그 dataset entity에 primary link가 있고, 다른 dataset entity에는 link가 없고,
   manual claim이 없으며, ``valid_end_time``(retire된 중복은 마지막 retire 전이 시각)이 ``now() - p_grace``
   보다 이른 notice. 증거 FK(``confdeltype IN ('r','a')``)와 ``ops.feature_merge_history``(cascade로 지워지는
   감사성 이력)에 붙들린 것은 건너뛴다. **빈 활성 집합 보호**: 그 dataset의 notice scope에 present 계보가
   하나도 없으면 아무것도 지우지 않는다 — transport가 빈 집합을 하루 넘게 내면 모든 사건이 닫혀 있다가
   identity째 지워지는 것을 막는다. 지우는 것: identity claim(다시 나타난 사건이 새 uuid를 받게)과
   ``feature.features`` 행 — 나머지는 선언된 FK 동작이 따라간다. Feature마다 subtransaction이라 cascade
   트리거가 한 건을 거부해도(비활성 dataset의 자식 행 등) 그 건만 남고 센다. entity·record·head·lineage
   state는 4가 orphan으로 지운다. append-only 증거(``feature_state_transitions`` 등)에는 쓰지도 지우지도 않는다.
6. receipt head CHECK에 이 revision을 더한다.

forward-only. downgrade는 두지 않는다(``alembic/env.py``가 모든 downgrade를 해석 전에 거부한다).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from sqlalchemy import text

from alembic import op

# ruff: noqa: E501

revision: str = "410_transport_latest_only_retention"
down_revision: str | Sequence[str] | None = "409_geo_release_item_reasons"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: 스키마 소유자. env가 켠 롤이고, 마이그레이션은 이 롤로 끝나야 한다.
_SCHEMA_OWNER_ROLE: Final[str] = "ktm_feature_schema_owner"

_SET_OWNER_ROLE_SQL: Final[str] = f"SET ROLE {_SCHEMA_OWNER_ROLE}"

#: DB fence가 허용하는 provider. 정책 정본(``core.retention.LATEST_ONLY_PROVIDER``)과 같아야 하며
#: ``tests/unit/test_core_retention.py``가 대조한다.
LATEST_ONLY_PROVIDER: Final[str] = "kor-travel-transport"

#: 세 함수 공통의 첫 검사. ``v_dataset``(``provider_sync.provider_datasets%ROWTYPE``)을 채운다.
_DATASET_FENCE_PLPGSQL: Final[str] = f"""
    IF p_provider_dataset_id IS NULL THEN
        RAISE EXCEPTION 'latest-only retention needs a provider dataset'
            USING ERRCODE = '22023';
    END IF;
    SELECT * INTO v_dataset
    FROM provider_sync.provider_datasets AS dataset
    WHERE dataset.provider_dataset_id = p_provider_dataset_id;
    IF NOT FOUND OR NOT v_dataset.is_active OR v_dataset.provider <> '{LATEST_ONLY_PROVIDER}' THEN
        RAISE EXCEPTION 'latest-only retention only serves active {LATEST_ONLY_PROVIDER} datasets'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_latest_only_retention_scope';
    END IF;
"""

_PRICE_VALUE_MUTATION_SQL: Final[str] = f"""
CREATE OR REPLACE FUNCTION feature.reject_price_value_mutation() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog'
    AS $$
        BEGIN
            -- parent feature cascade는 derived fact/summary 제거의 예외다.
            IF TG_OP = 'DELETE' AND NOT EXISTS (
                SELECT 1 FROM feature.features AS f WHERE f.feature_id = OLD.feature_id
            ) THEN
                RETURN OLD;
            END IF;
            -- ADR-114: transport 출처는 series당 현재 winner만 둔다. summary가 가리키지 않는
            -- fact만 지울 수 있다(winner를 지우면 summary가 cascade로 사라지므로 막는다).
            IF TG_OP = 'DELETE'
               AND EXISTS (
                   SELECT 1
                   FROM provider_sync.provider_datasets AS dataset
                   WHERE dataset.provider_dataset_id = OLD.provider_dataset_id
                     AND dataset.is_active
                     AND dataset.provider = '{LATEST_ONLY_PROVIDER}'
               )
               AND NOT EXISTS (
                   SELECT 1
                   FROM feature.current_price_summary AS summary
                   WHERE summary.price_value_key = OLD.price_value_key
               ) THEN
                RETURN OLD;
            END IF;
            RAISE EXCEPTION 'feature_price_values facts are immutable (ADR-089)'
                USING ERRCODE = '23514', CONSTRAINT = 'ck_price_values_immutable';
        END;
        $$
"""

_PRICE_VALUE_SOURCE_RECORD_INDEX_SQL: Final[str] = """
CREATE INDEX idx_price_values_source_record
    ON feature.feature_price_values USING btree (source_record_key)
"""

_BASE_FIELD_SOURCE_RECORD_INDEX_SQL: Final[str] = """
CREATE INDEX idx_feature_base_field_values_source_record
    ON feature.feature_base_field_values USING btree (source_record_key)
"""

_BASE_FIELD_SOURCE_ENTITY_INDEX_SQL: Final[str] = """
CREATE INDEX idx_feature_base_field_values_source_entity
    ON feature.feature_base_field_values USING btree (source_entity_key)
"""

_PRUNE_PRICE_FACTS_SQL: Final[str] = f"""
CREATE FUNCTION feature.prune_transport_price_facts(p_provider_dataset_id bigint)
RETURNS integer
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog'
    AS $$
DECLARE
    v_dataset provider_sync.provider_datasets%ROWTYPE;
    v_deleted integer;
BEGIN
{_DATASET_FENCE_PLPGSQL}
    DELETE FROM feature.feature_price_values AS fact
    WHERE fact.provider_dataset_id = p_provider_dataset_id
      AND NOT EXISTS (
          SELECT 1
          FROM feature.current_price_summary AS summary
          WHERE summary.price_value_key = fact.price_value_key
      );
    GET DIAGNOSTICS v_deleted = ROW_COUNT;
    RETURN v_deleted;
END
$$
"""

#: 4의 참조 판정. ``v_target``(regclass)을 가리키는 FK 중 이 함수가 직접 지우는 내부 간선을 뺀 것.
_REFERENCE_BLOCKER_LOOP: Final[str] = """
        FOR v_fk IN
            SELECT constraint_row.conrelid, constraint_row.conkey, constraint_row.confkey
            FROM pg_catalog.pg_constraint AS constraint_row
            WHERE constraint_row.confrelid = v_target
              AND constraint_row.contype = 'f'
              AND constraint_row.conrelid <> ALL (v_internal)
              AND (
                  constraint_row.confdeltype IN ('r', 'a')
                  OR (
                      constraint_row.confdeltype = 'n'
                      AND constraint_row.conrelid <> 'ops.data_integrity_violations'::regclass
                  )
              )
            ORDER BY constraint_row.conname
        LOOP
            SELECT string_agg(
                       'child.' || quote_ident(child_column.attname)
                       || ' = parent.' || quote_ident(parent_column.attname),
                       ' AND ' ORDER BY position.ordinality
                   )
            INTO STRICT v_condition
            FROM unnest(v_fk.conkey, v_fk.confkey) WITH ORDINALITY
                AS position(child_attnum, parent_attnum, ordinality)
            JOIN pg_catalog.pg_attribute AS child_column
              ON child_column.attrelid = v_fk.conrelid
             AND child_column.attnum = position.child_attnum
            JOIN pg_catalog.pg_attribute AS parent_column
              ON parent_column.attrelid = v_target
             AND parent_column.attnum = position.parent_attnum;
            EXECUTE 'SELECT coalesce(array_agg(DISTINCT parent.' || v_key_column
                || '::text), ''{}''::text[]) FROM ' || v_target::text || ' AS parent'
                || ' WHERE parent.' || v_key_column || '::text = ANY($1)'
                || ' AND EXISTS (SELECT 1 FROM ' || v_fk.conrelid::regclass::text
                || ' AS child WHERE ' || v_condition || ')'
            INTO v_hits USING v_keys;
            v_blocked := v_blocked || v_hits;
        END LOOP;
"""

_PRUNE_LINEAGE_SQL: Final[str] = f"""
CREATE FUNCTION provider_sync.prune_latest_only_lineage(p_provider_dataset_id bigint)
RETURNS TABLE(
    records_pruned integer,
    entities_pruned integer,
    lineage_states_pruned integer,
    records_held integer,
    entities_held integer
)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog'
    AS $$
DECLARE
    v_dataset provider_sync.provider_datasets%ROWTYPE;
    v_target regclass;
    v_internal regclass[];
    v_key_column text;
    v_keys text[];
    v_hits text[];
    v_blocked text[];
    v_fk record;
    v_condition text;
    v_record_keys text[];
    v_entity_keys text[];
    v_records_pruned integer := 0;
    v_orphan_records integer := 0;
    v_entities_pruned integer := 0;
    v_states_pruned integer := 0;
    v_records_held integer := 0;
    v_entities_held integer := 0;
BEGIN
{_DATASET_FENCE_PLPGSQL}
    -- (a) head가 아닌 record. head가 없는 entity의 record는 판정할 기준이 없으니 건드리지 않는다.
    SELECT coalesce(array_agg(record.source_record_key::text ORDER BY record.source_record_key), '{{}}'::text[])
    INTO v_record_keys
    FROM provider_sync.source_records AS record
    JOIN provider_sync.source_entities AS entity
      ON entity.source_entity_key = record.source_entity_key
    JOIN provider_sync.source_entity_heads AS head
      ON head.source_entity_key = record.source_entity_key
    WHERE entity.provider_dataset_id = p_provider_dataset_id
      AND record.source_record_key <> head.current_source_record_key;
    IF cardinality(v_record_keys) > 0 THEN
        v_target := 'provider_sync.source_records'::regclass;
        v_internal := ARRAY['provider_sync.source_entity_heads'::regclass];
        v_key_column := 'source_record_key';
        v_keys := v_record_keys;
        v_blocked := '{{}}'::text[];
{_REFERENCE_BLOCKER_LOOP}
        v_records_held := (SELECT count(DISTINCT blocked) FROM unnest(v_blocked) AS blocked);
        DELETE FROM provider_sync.source_records AS record
        WHERE record.source_record_key = ANY(v_record_keys)
          AND NOT (record.source_record_key = ANY(v_blocked));
        GET DIAGNOSTICS v_records_pruned = ROW_COUNT;
    END IF;

    -- (b) 어느 Feature에도 link되지 않은 entity. entity를 붙든 참조와, 그 entity의 모든 record를 붙든
    --     참조를 함께 본다(head는 이 함수가 먼저 지우므로 빼고 본다).
    SELECT coalesce(array_agg(entity.source_entity_key ORDER BY entity.source_entity_key), '{{}}'::text[])
    INTO v_entity_keys
    FROM provider_sync.source_entities AS entity
    WHERE entity.provider_dataset_id = p_provider_dataset_id
      AND NOT EXISTS (
          SELECT 1 FROM provider_sync.source_links AS link
          WHERE link.source_entity_key = entity.source_entity_key
      );
    IF cardinality(v_entity_keys) > 0 THEN
        v_target := 'provider_sync.source_entities'::regclass;
        v_internal := ARRAY[
            'provider_sync.source_records'::regclass,
            'provider_sync.source_entity_heads'::regclass
        ];
        v_key_column := 'source_entity_key';
        v_keys := v_entity_keys;
        v_blocked := '{{}}'::text[];
{_REFERENCE_BLOCKER_LOOP}
        -- record 쪽 참조로 붙들린 entity
        v_target := 'provider_sync.source_records'::regclass;
        v_internal := ARRAY['provider_sync.source_entity_heads'::regclass];
        v_key_column := 'source_record_key';
        SELECT coalesce(array_agg(record.source_record_key::text), '{{}}'::text[]) INTO v_keys
        FROM provider_sync.source_records AS record
        WHERE record.source_entity_key = ANY(v_entity_keys);
        IF cardinality(v_keys) > 0 THEN
            DECLARE
                v_entity_blocked text[] := v_blocked;
            BEGIN
                v_blocked := '{{}}'::text[];
{_REFERENCE_BLOCKER_LOOP}
                SELECT coalesce(array_agg(DISTINCT record.source_entity_key), '{{}}'::text[])
                INTO v_hits
                FROM provider_sync.source_records AS record
                WHERE record.source_record_key = ANY(v_blocked);
                v_blocked := v_entity_blocked || v_hits;
            END;
        END IF;
        v_entity_keys := ARRAY(
            SELECT candidate FROM unnest(v_entity_keys) AS candidate
            EXCEPT
            SELECT blocked FROM unnest(v_blocked) AS blocked
        );
        v_entities_held := (SELECT count(DISTINCT blocked) FROM unnest(v_blocked) AS blocked);
        -- 순서: head → record → entity. entity를 먼저 지우면 head cascade의 활성 검사 트리거가
        -- 이미 사라진 entity를 찾지 못해 거부한다.
        DELETE FROM provider_sync.source_entity_heads AS head
        WHERE head.source_entity_key = ANY(v_entity_keys);
        DELETE FROM provider_sync.source_records AS record
        WHERE record.source_entity_key = ANY(v_entity_keys);
        GET DIAGNOSTICS v_orphan_records = ROW_COUNT;
        v_records_pruned := v_records_pruned + v_orphan_records;
        DELETE FROM provider_sync.source_entities AS entity
        WHERE entity.source_entity_key = ANY(v_entity_keys);
        GET DIAGNOSTICS v_entities_pruned = ROW_COUNT;
    END IF;

    -- (c) head가 하나도 남지 않은 notice 계보의 닫힌 상태 행.
    DELETE FROM provider_sync.notice_lineage_states AS state
    USING provider_sync.notice_lifecycle_scopes AS scope
    WHERE scope.notice_lifecycle_scope_id = state.notice_lifecycle_scope_id
      AND scope.provider_dataset_id = p_provider_dataset_id
      AND NOT state.present
      AND NOT EXISTS (
          SELECT 1
          FROM provider_sync.source_entity_heads AS head
          JOIN provider_sync.source_entities AS entity
            ON entity.source_entity_key = head.source_entity_key
          WHERE entity.provider_dataset_id = scope.provider_dataset_id
            AND entity.source_entity_type = scope.source_entity_type
            AND head.lineage_key = state.lineage_key
      );
    GET DIAGNOSTICS v_states_pruned = ROW_COUNT;

    RETURN QUERY SELECT
        v_records_pruned, v_entities_pruned, v_states_pruned, v_records_held, v_entities_held;
END
$$
"""

_PURGE_ENDED_NOTICES_SQL: Final[str] = f"""
CREATE FUNCTION feature.purge_ended_provider_notices(
    p_provider_dataset_id bigint,
    p_grace interval
) RETURNS TABLE(purged_count integer, held_count integer, empty_snapshot_guarded boolean)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog'
    AS $$
DECLARE
    v_dataset provider_sync.provider_datasets%ROWTYPE;
    v_candidates uuid[];
    v_blocked uuid[] := '{{}}'::uuid[];
    v_hits uuid[];
    v_fk record;
    v_column name;
    v_feature uuid;
    v_purged integer := 0;
    v_failed integer := 0;
BEGIN
{_DATASET_FENCE_PLPGSQL}
    IF p_grace IS NULL OR p_grace < interval '0' THEN
        RAISE EXCEPTION 'ended notice purge needs a non-negative grace'
            USING ERRCODE = '22023';
    END IF;
    IF NOT ((v_dataset.capabilities -> 'produces') @> '["notice"]'::jsonb) THEN
        RAISE EXCEPTION 'ended notice purge only serves notice datasets'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_latest_only_retention_scope';
    END IF;

    -- 빈 활성 집합 보호: 현재 present 계보가 하나도 없으면(빈 snapshot이 전부 닫은 상태일 수 있다)
    -- 아무것도 지우지 않는다. 빈 집합이 하루를 넘겨도 identity를 잃지 않는다.
    IF NOT EXISTS (
        SELECT 1
        FROM provider_sync.notice_lineage_states AS state
        JOIN provider_sync.notice_lifecycle_scopes AS scope
          ON scope.notice_lifecycle_scope_id = state.notice_lifecycle_scope_id
        WHERE scope.provider_dataset_id = p_provider_dataset_id
          AND state.present
    ) THEN
        RETURN QUERY SELECT 0, 0, true;
        RETURN;
    END IF;

    -- 대상 고정. 잠금 순서는 feature_id 오름차순이다.
    SELECT coalesce(array_agg(candidate.feature_id ORDER BY candidate.feature_id), '{{}}'::uuid[])
    INTO v_candidates
    FROM (
        SELECT f.feature_id
        FROM feature.features AS f
        JOIN feature.feature_notices AS notice
          ON notice.feature_id = f.feature_id
        WHERE COALESCE(
                  notice.valid_end_time,
                  CASE WHEN f.lifecycle_state = 'retired' THEN (
                      SELECT max(transition.occurred_at)
                      FROM feature.feature_state_transitions AS transition
                      WHERE transition.feature_id = f.feature_id
                        AND transition.to_lifecycle_state = 'retired'
                  ) END
              ) < now() - p_grace
          AND EXISTS (
              SELECT 1
              FROM provider_sync.source_links AS link
              JOIN provider_sync.source_entities AS entity
                ON entity.source_entity_key = link.source_entity_key
              WHERE link.feature_id = f.feature_id
                AND link.source_role = 'primary'
                AND entity.provider_dataset_id = p_provider_dataset_id
          )
          AND NOT EXISTS (
              SELECT 1
              FROM provider_sync.source_links AS link
              JOIN provider_sync.source_entities AS entity
                ON entity.source_entity_key = link.source_entity_key
              WHERE link.feature_id = f.feature_id
                AND entity.provider_dataset_id <> p_provider_dataset_id
          )
          AND NOT EXISTS (
              SELECT 1
              FROM feature.manual_feature_identity_claims AS claim
              WHERE claim.feature_id = f.feature_id
          )
        ORDER BY f.feature_id
        FOR UPDATE OF f
    ) AS candidate;

    IF cardinality(v_candidates) = 0 THEN
        RETURN QUERY SELECT 0, 0, false;
        RETURN;
    END IF;

    -- 증거 FK(RESTRICT·NO ACTION)와 감사성 merge 이력에 붙들린 대상은 건너뛴다.
    FOR v_fk IN
        SELECT constraint_row.conrelid, constraint_row.conkey, constraint_row.conname
        FROM pg_catalog.pg_constraint AS constraint_row
        WHERE constraint_row.confrelid = 'feature.features'::regclass
          AND constraint_row.contype = 'f'
          AND (
              constraint_row.confdeltype IN ('r', 'a')
              OR constraint_row.conrelid = 'ops.feature_merge_history'::regclass
          )
        ORDER BY constraint_row.conname
    LOOP
        IF cardinality(v_fk.conkey) <> 1 THEN
            RAISE EXCEPTION 'evidence FK % is multi-column; ended notice purge cannot judge it', v_fk.conname
                USING ERRCODE = '23514', CONSTRAINT = 'ck_ended_notice_purge_evidence_shape';
        END IF;
        SELECT attribute.attname INTO STRICT v_column
        FROM pg_catalog.pg_attribute AS attribute
        WHERE attribute.attrelid = v_fk.conrelid
          AND attribute.attnum = v_fk.conkey[1];
        EXECUTE 'SELECT coalesce(array_agg(DISTINCT child.' || quote_ident(v_column)
            || '), ''{{}}''::uuid[]) FROM ' || v_fk.conrelid::regclass::text
            || ' AS child WHERE child.' || quote_ident(v_column) || ' = ANY($1)'
        INTO v_hits USING v_candidates;
        v_blocked := v_blocked || v_hits;
    END LOOP;

    -- Feature마다 subtransaction — cascade 트리거가 한 건을 거부해도 나머지는 지워진다.
    FOREACH v_feature IN ARRAY v_candidates LOOP
        CONTINUE WHEN v_feature = ANY(v_blocked);
        BEGIN
            DELETE FROM provider_sync.provider_feature_identities AS claim
            WHERE claim.feature_id = v_feature;
            DELETE FROM feature.features AS f
            WHERE f.feature_id = v_feature;
            v_purged := v_purged + 1;
        EXCEPTION WHEN check_violation OR foreign_key_violation OR restrict_violation THEN
            v_failed := v_failed + 1;
        END;
    END LOOP;

    RETURN QUERY SELECT
        v_purged,
        (SELECT count(DISTINCT blocked)::integer FROM unnest(v_blocked) AS blocked) + v_failed,
        false;
END
$$
"""

_FUNCTION_SIGNATURES: Final[tuple[str, ...]] = (
    "feature.prune_transport_price_facts(bigint)",
    "provider_sync.prune_latest_only_lineage(bigint)",
    "feature.purge_ended_provider_notices(bigint, interval)",
)

_FUNCTION_ACL_SQL: Final[tuple[str, ...]] = tuple(
    statement
    for signature in _FUNCTION_SIGNATURES
    for statement in (
        f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC",
        f"GRANT EXECUTE ON FUNCTION {signature} TO ktm_feature_runtime",
    )
)

_RECEIPT_HEAD_CHECK_SQL: Final[str] = """
ALTER TABLE ops.application_schema_operation_receipts
    DROP CONSTRAINT ck_application_schema_operation_receipts_head,
    ADD CONSTRAINT ck_application_schema_operation_receipts_head CHECK (destination_head IN ('300', '301_m03_import_children', '302_m03_child_issuance', '303_m05_payload_hash_domain', '304_m05_detector_manuals', '305_m05_relitigation_fence', '306_m02_manual_feature_purge', '307_m02_truncate_fence', '308_t39_provider_identities', '309_t39_feature_id_rekey', '310_seoul_source_move', '311_seal_member_digest', '312_route_geometry_sidecar', '313_single_service_role', '400', '401_retire_map_kma_refresh', '402_remove_map_weather_data', '403_drop_kma_notice_lineage', '404_transport_provider_identity', '405_mois_freshness_sla', '406_feature_write_gate', '407_feature_geocode_stamps', '408_kor_travel_geo_releases', '409_geo_release_item_reasons', '410_transport_latest_only_retention'))
"""

#: 실행 순서대로의 upgrade 문장. 창은 소유자 롤로 열고 같은 롤로 끝난다(RESET ROLE 없음).
_UPGRADE_STATEMENTS: Final[tuple[str, ...]] = (
    _SET_OWNER_ROLE_SQL,
    _PRICE_VALUE_MUTATION_SQL,
    _PRICE_VALUE_SOURCE_RECORD_INDEX_SQL,
    _BASE_FIELD_SOURCE_RECORD_INDEX_SQL,
    _BASE_FIELD_SOURCE_ENTITY_INDEX_SQL,
    _PRUNE_PRICE_FACTS_SQL,
    _PRUNE_LINEAGE_SQL,
    _PURGE_ENDED_NOTICES_SQL,
    *_FUNCTION_ACL_SQL,
    _RECEIPT_HEAD_CHECK_SQL,
)


def upgrade() -> None:
    """latest-only 정리 함수 셋·price fact 예외·역참조 index를 만들고 receipt head CHECK에 410을 더한다."""
    bind = op.get_bind()
    for statement in _UPGRADE_STATEMENTS:
        bind.execute(text(statement))


def downgrade() -> None:
    """되돌리지 않는다."""
    raise RuntimeError(
        "410_transport_latest_only_retention is forward-only: 지운 이력은 되살릴 수 없다(ADR-114)."
    )
