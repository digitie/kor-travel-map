"""T-VN-40C — legacy 물리 삭제.

Revision ID: 0225_tvn40c_physical_removal
Revises: 0224_c7_external_system_scope

manifest: docs/reports/t-vn-40c-physical-removal-manifest-2026-08-18.md ·
          contracts/vnext/t-vn-40c-removal-manifest-v1.json (D1~D12)

원칙
- forward-only · 단일 트랜잭션. 모든 DROP은 RESTRICT — manifest가 모르는 dependent가 있으면 트랜잭션이
  죽고 manifest를 고친 뒤 재실행한다(trigger disable 같은 우회 없음).
- 이 migration은 데이터를 파괴한다(legacy overlay 표). 선행조건 P1~P6(manifest §0)을 사람이 확인한 뒤에만
  적용한다. api-entrypoint의 EXPECTED_HEAD pin은 0225로.
- fresh DB에서도 0202~0225 전체가 통과해야 한다(legacy 0행 → 0223 0건 적재 → 0225 drop).
- ops.curation_cutover_identity_mappings는 **남긴다**(PinVi cutover 증거; FK → curation_items 유지).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# ruff: noqa: E501

revision: str = "0225_tvn40c_physical_removal"
down_revision: str | Sequence[str] | None = "0224_c7_external_system_scope"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_PRECHECK_SQL = """
DO $tvn40c_precheck$
DECLARE
    v_legacy bigint;
    v_mapped bigint;
BEGIN
    -- P3: ① 이후 legacy 신규 write가 없었어야 한다(mapping 1:1). 다르면 중단.
    SELECT count(*) INTO v_legacy FROM feature.curated_features;
    SELECT count(*) INTO v_mapped FROM ops.curation_cutover_identity_mappings;
    IF v_legacy <> v_mapped THEN
        RAISE EXCEPTION 'tvn40c physical removal: legacy rows (%) != identity mappings (%) — resolve before dropping', v_legacy, v_mapped
            USING ERRCODE = 'P0001';
    END IF;
END
$tvn40c_precheck$;
"""

# D1 — 0222 legacy mirror procedure 4개 (canonical collections lock ⑤는 유지)
_D1_SQL = """
DROP PROCEDURE feature.merge_lock_legacy_curated_features(text, text) RESTRICT;
DROP PROCEDURE feature.merge_archive_conflicting_legacy_curated_features(text, text) RESTRICT;
DROP PROCEDURE feature.merge_sync_master_legacy_curated_features(text) RESTRICT;
DROP PROCEDURE feature.merge_move_legacy_curated_features(text, text) RESTRICT;
"""

# D2 — 0045 sync trigger + function
_D2_SQL = """
DROP TRIGGER trg_sync_curated_feature_collection ON feature.curated_features;
DROP FUNCTION feature.sync_curated_feature_collection() RESTRICT;
"""

# D3 — legacy projection만 입력으로 쓰던 source-rule decision trigger + function
_D3_SQL = """
DROP TRIGGER trg_curation_items_source_rule_decision ON feature.curation_items;
DROP FUNCTION feature.issue_curation_source_rule_decision() RESTRICT;
"""

# D3b — legacy_projection_id를 읽는 BEFORE INSERT trigger (plpgsql 본문은 pg_depend 밖 — D5 뒤에 남으면 모든
#       curation_items INSERT가 42703). 반드시 D5보다 먼저.
_D3B_SQL = """
DROP TRIGGER trg_curation_items_legacy_component_identity ON feature.curation_items;
DROP FUNCTION feature.set_curation_item_legacy_component_identity() RESTRICT;
"""

# D4 — 0214 item command procedure 2개: legacy 분기(v_hint.legacy_projection_id · curated_features FOR UPDATE ·
#      mirror UPDATE) 제거본으로 CREATE OR REPLACE. owner=ktm_curation_command_owner → SET ROLE 아래서.
#      본문은 `0214_tvn40_item_commands.py`의 두 procedure에서 legacy 분기(v_linked_legacy 선언·hint lock·
#      identity 비교 항·source-owner RAISE·mirror UPDATE)만 제거한 전문이다. 손으로 옮겨 적지 않고 원본에서
#      추출해 제거 대상마다 1회 매칭을 단언하며 만들었다 — 조용한 변형이 불가능하다.
#      **CREATE OR REPLACE는 명시하지 않은 속성을 기본값으로 되돌린다** — 반드시 `SECURITY DEFINER`와
#      `SET search_path = pg_catalog, feature, ops`(0214:270-271, 525-526)를 다시 적는다. 안 그러면 executor 게이트가
#      INVOKER로 조용히 깨진다(리뷰 P1). D4 대상은 정확히 patch/archive 둘 — create_curation_item_command에는 legacy 참조 없음.
_D4_SQL = r"""
SET ROLE ktm_curation_command_owner;

CREATE OR REPLACE PROCEDURE feature.patch_curation_item_command(
  IN p_collection_id uuid,
  IN p_curation_item_id uuid,
  IN p_expected_item_revision bigint,
  IN p_feature_id text,
  IN p_source_record_key text,
  IN p_external_item_id text,
  IN p_external_component_id text,
  IN p_place_name text,
  IN p_address_hint text,
  IN p_status text,
  IN p_sort_order integer,
  IN p_item_title text,
  IN p_item_summary text,
  IN p_curation_relation text,
  IN p_reuse_policy text,
  IN p_metadata jsonb,
  IN p_command_id bigint,
  IN p_principal text,
  OUT o_curation_item_id uuid,
  OUT o_item_revision bigint,
  OUT o_collection_revision bigint
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, feature, ops
AS $command$
DECLARE
  v_command ops.domain_commands%ROWTYPE;
  v_collection feature.curation_collections%ROWTYPE;
  v_hint feature.curation_items%ROWTYPE;
  v_item feature.curation_items%ROWTYPE;
  v_decision_id uuid;
  v_source_owned_changed boolean;
  v_operator_owned_changed boolean;
BEGIN
  IF current_setting('transaction_isolation') <> 'serializable' THEN
    RAISE EXCEPTION 'item command requires SERIALIZABLE transaction'
      USING ERRCODE = '25001';
  END IF;
  IF NOT pg_has_role(session_user, 'ktm_curation_admin_executor', 'member')
     OR pg_has_role(session_user, 'ktm_curation_provider_executor', 'member') THEN
    RAISE EXCEPTION 'item command requires the admin executor'
      USING ERRCODE = '42501';
  END IF;
  IF p_principal IS NULL OR p_principal <> btrim(p_principal) OR p_principal = ''
     OR p_collection_id IS NULL OR p_curation_item_id IS NULL
     OR p_expected_item_revision IS NULL OR p_expected_item_revision < 1
     OR p_external_item_id IS NULL
     OR p_external_item_id <> btrim(p_external_item_id)
     OR p_external_item_id = ''
     OR p_external_component_id IS NULL
     OR p_external_component_id <> btrim(p_external_component_id)
     OR p_external_component_id = ''
     OR p_place_name IS NULL OR p_place_name <> btrim(p_place_name)
     OR p_place_name = ''
     OR p_address_hint IS DISTINCT FROM NULLIF(btrim(p_address_hint), '')
     OR p_status NOT IN ('candidate','included','rejected')
     OR p_sort_order IS NULL OR p_sort_order < 0
     OR p_curation_relation NOT IN (
       'primary_stop','food_stop','cafe_stop','bookstore_stop','nearby_option',
       'accessibility_support','pet_support','family_support','theme_area_anchor'
     )
     OR p_reuse_policy NOT IN ('allowed','blocked','manual_review')
     OR jsonb_typeof(p_metadata) <> 'object' THEN
    RAISE EXCEPTION 'item command input is not canonical'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_item_command_input';
  END IF;
  SELECT command.* INTO STRICT v_command
  FROM ops.domain_commands AS command WHERE command.command_id = p_command_id;
  IF v_command.actor <> p_principal
     OR v_command.operation <> 'admin.curation-item.patch' THEN
    RAISE EXCEPTION 'domain command does not match item patch'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_item_domain_command';
  END IF;

  SELECT item.* INTO STRICT v_hint FROM feature.curation_items AS item
  WHERE item.collection_id = p_collection_id
    AND item.curation_item_id = p_curation_item_id;
  PERFORM pg_advisory_xact_lock(hashtextextended('kortravelmap:curation-import', 0));
  PERFORM pg_advisory_xact_lock(hashtextextended('feature-curation-write', 0));
  PERFORM pg_advisory_xact_lock(hashtextextended('feature-write:' || touched.feature_id, 0))
  FROM (
    SELECT v_hint.feature_id AS feature_id
    UNION SELECT p_feature_id WHERE p_feature_id IS NOT NULL
  ) AS touched
  WHERE touched.feature_id IS NOT NULL
  ORDER BY touched.feature_id;
  SELECT collection.* INTO STRICT v_collection
  FROM feature.curation_collections AS collection
  WHERE collection.collection_id = p_collection_id FOR UPDATE;
  IF v_collection.archived_at IS NOT NULL OR v_collection.status = 'archived' THEN
    RAISE EXCEPTION 'target curation collection is archived'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_item_collection_active';
  END IF;
  SELECT item.* INTO STRICT v_item FROM feature.curation_items AS item
  WHERE item.collection_id = p_collection_id
    AND item.curation_item_id = p_curation_item_id FOR UPDATE;
  IF v_item.curation_item_id <> v_hint.curation_item_id
     OR v_item.feature_id IS DISTINCT FROM v_hint.feature_id
     OR v_item.row_revision <> p_expected_item_revision THEN
    RAISE EXCEPTION 'item identity or revision changed while locking'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_item_expected_revision';
  END IF;
  IF v_item.archived_at IS NOT NULL THEN
    RAISE EXCEPTION 'archived item cannot be patched'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_item_active';
  END IF;
  IF p_feature_id IS NOT NULL THEN
    PERFORM 1 FROM feature.features AS feature
    WHERE feature.feature_id = p_feature_id
      AND feature.lifecycle_state = 'active'
      AND feature.publication_state <> 'suppressed'
    FOR SHARE;
    IF NOT FOUND THEN
      RAISE EXCEPTION 'feature_id must reference an active Feature'
        USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_item_active_feature';
    END IF;
  END IF;
  IF EXISTS (
    SELECT 1 FROM feature.curation_items AS item
    WHERE item.collection_id = p_collection_id
      AND item.curation_item_id <> p_curation_item_id
      AND item.external_item_id = p_external_item_id
      AND item.external_component_id = p_external_component_id
  ) THEN
    RAISE EXCEPTION 'curation item identity already exists'
      USING ERRCODE = '23505', CONSTRAINT = 'uq_curation_items_component_identity';
  END IF;
  IF p_feature_id IS NOT NULL AND EXISTS (
    SELECT 1 FROM feature.curation_items AS item
    WHERE item.collection_id = p_collection_id
      AND item.curation_item_id <> p_curation_item_id
      AND item.external_item_id = p_external_item_id
      AND item.feature_id = p_feature_id
      AND item.source_present AND item.archived_at IS NULL
  ) THEN
    RAISE EXCEPTION 'active source feature identity already exists'
      USING ERRCODE = '23505', CONSTRAINT = 'uq_curation_items_active_source_feature';
  END IF;
  v_source_owned_changed := (
    v_item.feature_id, v_item.source_record_key, v_item.external_item_id,
    v_item.external_component_id, v_item.place_name, v_item.address_hint,
    v_item.sort_order, v_item.item_title, v_item.item_summary, v_item.metadata
  ) IS DISTINCT FROM (
    p_feature_id, p_source_record_key, p_external_item_id,
    p_external_component_id, p_place_name, p_address_hint,
    p_sort_order, p_item_title, p_item_summary, p_metadata
  );
  v_operator_owned_changed := (
    v_item.status, v_item.curation_relation, v_item.reuse_policy
  ) IS DISTINCT FROM (
    p_status, p_curation_relation, p_reuse_policy
  );
  PERFORM feature.claim_curation_catalog_command_effect(
    p_command_id, v_command.operation, 'item', p_curation_item_id
  );
  o_curation_item_id := p_curation_item_id;
  o_collection_revision := v_collection.row_revision;
  IF NOT v_source_owned_changed AND NOT v_operator_owned_changed THEN
    o_item_revision := v_item.row_revision;
    RETURN;
  END IF;
  IF v_item.feature_id IS DISTINCT FROM p_feature_id THEN
    IF p_feature_id IS NOT NULL THEN
      INSERT INTO feature.curation_link_decisions (
        curation_item_id, feature_id, decision_kind, match_basis,
        resolver_version, evidence, actor, supersedes_decision_id
      ) VALUES (
        p_curation_item_id, p_feature_id, 'accepted', 'admin_review',
        'manual-admin-v1', jsonb_build_object(
          'operation', 'patch_curation_item_command',
          'previous_feature_id', v_item.feature_id,
          'requested_feature_id', p_feature_id,
          'command_id', p_command_id
        ), p_principal, v_item.accepted_link_decision_id
      ) RETURNING decision_id INTO STRICT v_decision_id;
    ELSIF v_item.feature_id IS NOT NULL THEN
      INSERT INTO feature.curation_link_decisions (
        curation_item_id, feature_id, decision_kind, match_basis,
        resolver_version, evidence, actor, supersedes_decision_id
      ) VALUES (
        p_curation_item_id, v_item.feature_id, 'revoked', 'admin_review',
        'manual-admin-v1', jsonb_build_object(
          'operation', 'patch_curation_item_command',
          'previous_feature_id', v_item.feature_id,
          'reason', 'explicit feature_id=null',
          'command_id', p_command_id
        ), p_principal, v_item.accepted_link_decision_id
      ) RETURNING decision_id INTO STRICT v_decision_id;
    END IF;
  END IF;
  UPDATE feature.curation_items AS item
  SET feature_id = p_feature_id,
      source_record_key = p_source_record_key,
      external_item_id = p_external_item_id,
      external_component_id = p_external_component_id,
      place_name = p_place_name,
      address_hint = p_address_hint,
      status = p_status,
      sort_order = p_sort_order,
      item_title = p_item_title,
      item_summary = p_item_summary,
      curation_relation = p_curation_relation,
      reuse_policy = p_reuse_policy,
      metadata = p_metadata,
      accepted_link_decision_id = CASE
        WHEN v_item.feature_id IS NOT DISTINCT FROM p_feature_id
          THEN v_item.accepted_link_decision_id
        WHEN p_feature_id IS NULL THEN NULL
        ELSE v_decision_id
      END,
      source_updated_at = CASE WHEN v_source_owned_changed
        THEN clock_timestamp() ELSE item.source_updated_at END,
      operator_updated_by = CASE WHEN v_operator_owned_changed
        THEN p_principal ELSE item.operator_updated_by END,
      operator_updated_at = CASE WHEN v_operator_owned_changed
        THEN clock_timestamp() ELSE item.operator_updated_at END,
      updated_by = p_principal,
      row_revision = item.row_revision + 1,
      updated_at = clock_timestamp()
  WHERE item.curation_item_id = p_curation_item_id
  RETURNING item.row_revision INTO STRICT o_item_revision;
  UPDATE feature.curation_collections AS collection
  SET updated_by = p_principal, updated_at = clock_timestamp(),
      row_revision = collection.row_revision + 1
  WHERE collection.collection_id = p_collection_id
  RETURNING collection.row_revision INTO STRICT o_collection_revision;
END
$command$;

CREATE OR REPLACE PROCEDURE feature.archive_curation_item_command(
  IN p_collection_id uuid,
  IN p_curation_item_id uuid,
  IN p_expected_item_revision bigint,
  IN p_command_id bigint,
  IN p_principal text,
  OUT o_curation_item_id uuid,
  OUT o_item_revision bigint,
  OUT o_collection_revision bigint
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, feature, ops
AS $command$
DECLARE
  v_command ops.domain_commands%ROWTYPE;
  v_collection feature.curation_collections%ROWTYPE;
  v_hint feature.curation_items%ROWTYPE;
  v_item feature.curation_items%ROWTYPE;
BEGIN
  IF current_setting('transaction_isolation') <> 'serializable' THEN
    RAISE EXCEPTION 'item command requires SERIALIZABLE transaction'
      USING ERRCODE = '25001';
  END IF;
  IF NOT pg_has_role(session_user, 'ktm_curation_admin_executor', 'member')
     OR pg_has_role(session_user, 'ktm_curation_provider_executor', 'member') THEN
    RAISE EXCEPTION 'item command requires the admin executor'
      USING ERRCODE = '42501';
  END IF;
  IF p_principal IS NULL OR p_principal <> btrim(p_principal) OR p_principal = ''
     OR p_collection_id IS NULL OR p_curation_item_id IS NULL
     OR p_expected_item_revision IS NULL OR p_expected_item_revision < 1 THEN
    RAISE EXCEPTION 'item archive input is not canonical'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_item_command_input';
  END IF;
  SELECT command.* INTO STRICT v_command
  FROM ops.domain_commands AS command WHERE command.command_id = p_command_id;
  IF v_command.actor <> p_principal
     OR v_command.operation <> 'admin.curation-item.archive' THEN
    RAISE EXCEPTION 'domain command does not match item archive'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_item_domain_command';
  END IF;

  SELECT item.* INTO STRICT v_hint FROM feature.curation_items AS item
  WHERE item.collection_id = p_collection_id
    AND item.curation_item_id = p_curation_item_id;
  PERFORM pg_advisory_xact_lock(hashtextextended('kortravelmap:curation-import', 0));
  PERFORM pg_advisory_xact_lock(hashtextextended('feature-curation-write', 0));
  IF v_hint.feature_id IS NOT NULL THEN
    PERFORM pg_advisory_xact_lock(hashtextextended('feature-write:' || v_hint.feature_id, 0));
  END IF;
  SELECT collection.* INTO STRICT v_collection
  FROM feature.curation_collections AS collection
  WHERE collection.collection_id = p_collection_id FOR UPDATE;
  SELECT item.* INTO STRICT v_item FROM feature.curation_items AS item
  WHERE item.collection_id = p_collection_id
    AND item.curation_item_id = p_curation_item_id FOR UPDATE;
  IF v_item.feature_id IS DISTINCT FROM v_hint.feature_id
     OR v_item.row_revision <> p_expected_item_revision THEN
    RAISE EXCEPTION 'item identity or revision changed while locking'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_item_expected_revision';
  END IF;
  PERFORM feature.claim_curation_catalog_command_effect(
    p_command_id, v_command.operation, 'item', p_curation_item_id
  );
  o_curation_item_id := p_curation_item_id;
  o_collection_revision := v_collection.row_revision;
  IF v_item.archived_at IS NOT NULL THEN
    o_item_revision := v_item.row_revision;
    RETURN;
  END IF;
  UPDATE feature.curation_items AS item
  SET status = 'archived', archived_at = clock_timestamp(),
      operator_updated_by = p_principal, operator_updated_at = clock_timestamp(),
      updated_by = p_principal, row_revision = item.row_revision + 1,
      updated_at = clock_timestamp()
  WHERE item.curation_item_id = p_curation_item_id
  RETURNING item.row_revision INTO STRICT o_item_revision;
  UPDATE feature.curation_collections AS collection
  SET updated_by = p_principal, updated_at = clock_timestamp(),
      row_revision = collection.row_revision + 1
  WHERE collection.collection_id = p_collection_id
  RETURNING collection.row_revision INTO STRICT o_collection_revision;
END
$command$;

SET ROLE ktm_feature_schema_owner;
"""

# D5 — legacy_projection_id 흔적
_D5_SQL = """
ALTER TABLE feature.curation_items DROP CONSTRAINT fk_curation_items_legacy_projection_id_curated_features;
DROP INDEX feature.uq_curation_items_legacy_projection_id;
ALTER TABLE feature.curation_items DROP COLUMN legacy_projection_id RESTRICT;
"""

# D6·D7 — overlay 표 (snapshot 먼저: FK → curated_features)
_D6_D7_SQL = """
DROP TABLE feature.curated_feature_detail_snapshots RESTRICT;
DROP TABLE feature.curated_features RESTRICT;
"""

# D8 — 0074의 ON UPDATE CASCADE 4 FK → NO ACTION (rekey 경로 소멸)
_D8_SQL = """
ALTER TABLE feature.curation_import_rows
    DROP CONSTRAINT fk_curation_import_rows_item,
    ADD CONSTRAINT fk_curation_import_rows_item
        FOREIGN KEY (curation_item_id) REFERENCES feature.curation_items(curation_item_id)
        ON UPDATE NO ACTION ON DELETE RESTRICT;
ALTER TABLE feature.curation_link_decisions
    DROP CONSTRAINT fk_curation_link_decisions_import_row,
    ADD CONSTRAINT fk_curation_link_decisions_import_row
        FOREIGN KEY (import_row_id, curation_item_id) REFERENCES feature.curation_import_rows(import_row_id, curation_item_id)
        ON UPDATE NO ACTION ON DELETE RESTRICT;
ALTER TABLE feature.curation_link_decisions
    DROP CONSTRAINT fk_curation_link_decisions_item,
    ADD CONSTRAINT fk_curation_link_decisions_item
        FOREIGN KEY (curation_item_id) REFERENCES feature.curation_items(curation_item_id)
        ON UPDATE NO ACTION ON DELETE RESTRICT;
ALTER TABLE feature.curation_link_decisions
    DROP CONSTRAINT fk_curation_link_decisions_supersedes,
    ADD CONSTRAINT fk_curation_link_decisions_supersedes
        FOREIGN KEY (supersedes_decision_id, curation_item_id) REFERENCES feature.curation_link_decisions(decision_id, curation_item_id)
        ON UPDATE NO ACTION ON DELETE RESTRICT;
"""
# TODO(draft): 위 4 FK의 정확한 열·참조·DEFERRABLE 옵션은 baseline schema.sql 12748~12800의 정의를 그대로 복사해
#              ON UPDATE만 바꾼다. 적용 전 실제 정의와 대조(테스트가 pg_get_constraintdef로 고정).

# D9 — history 가드 무조건 거부
_D9_SQL = """
CREATE OR REPLACE FUNCTION feature.reject_curation_history_mutation() RETURNS trigger
    LANGUAGE plpgsql
AS $$
BEGIN
  -- T-VN-40C: merge의 legacy-conflict detach(rekey)가 사라져 curation_item_id 재작성 허용 분기도 없다.
  RAISE EXCEPTION 'curation import/link history is append-only'
    USING ERRCODE = '55000';
END;
$$;
"""

_POSTCHECK_SQL = """
DO $tvn40c_postcheck$
BEGIN
    IF to_regclass('feature.curated_features') IS NOT NULL
       OR to_regclass('feature.curated_feature_detail_snapshots') IS NOT NULL THEN
        RAISE EXCEPTION 'tvn40c physical removal: legacy relation still present' USING ERRCODE = 'P0001';
    END IF;
    IF EXISTS (SELECT 1 FROM pg_attribute WHERE attrelid = 'feature.curation_items'::regclass AND attname = 'legacy_projection_id' AND NOT attisdropped) THEN
        RAISE EXCEPTION 'tvn40c physical removal: legacy_projection_id still present' USING ERRCODE = 'P0001';
    END IF;
    IF EXISTS (SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace WHERE n.nspname = 'feature' AND p.proname LIKE 'merge_%legacy%') THEN
        RAISE EXCEPTION 'tvn40c physical removal: legacy merge procedure still present' USING ERRCODE = 'P0001';
    END IF;
    -- 이름만이 아니라 본문(prosrc)도 본다 — 0214 item command의 legacy 분기·D3b trigger 함수 잔존을 잡는다.
    IF EXISTS (SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
               WHERE n.nspname IN ('feature','ops','provider_sync','public')
                 AND (p.prosrc LIKE '%curated_features%' OR p.prosrc LIKE '%legacy_projection_id%')) THEN
        RAISE EXCEPTION 'tvn40c physical removal: a routine body still references the legacy overlay' USING ERRCODE = 'P0001';
    END IF;
END
$tvn40c_postcheck$;
"""


# 0214와 같은 dollar-quote 인식 splitter — D4의 procedure 본문($$ … ; … $$)을 쪼개지 않는다.
def _execute_commands(source: str) -> None:
    """Dollar-quoted routine bodies를 보존해 asyncpg statement를 분리한다."""

    statements: list[str] = []
    start = 0
    index = 0
    quote: str | None = None
    dollar_tag: str | None = None
    while index < len(source):
        character = source[index]
        if dollar_tag is not None:
            if source.startswith(dollar_tag, index):
                index += len(dollar_tag)
                dollar_tag = None
                continue
            index += 1
            continue
        if quote is not None:
            if character == quote:
                if index + 1 < len(source) and source[index + 1] == quote:
                    index += 2
                    continue
                quote = None
            index += 1
            continue
        if character in {"'", '"'}:
            quote = character
            index += 1
            continue
        if character == "$":
            end = source.find("$", index + 1)
            if end != -1:
                candidate = source[index : end + 1]
                inner = candidate[1:-1]
                if not inner or inner.replace("_", "a").isalnum():
                    dollar_tag = candidate
                    index = end + 1
                    continue
        if character == ";":
            statement = source[start:index].strip()
            if statement:
                statements.append(statement)
            start = index + 1
        index += 1
    trailing = source[start:].strip()
    if trailing:
        statements.append(trailing)
    for statement in statements:
        op.execute(statement)


def upgrade() -> None:
    op.execute(_PRECHECK_SQL)
    _execute_commands(_D1_SQL)
    _execute_commands(_D2_SQL)
    _execute_commands(_D3_SQL)
    _execute_commands(_D3B_SQL)
    _execute_commands(_D4_SQL)  # TODO(draft): 본문 채운 뒤 활성
    _execute_commands(_D5_SQL)
    _execute_commands(_D6_D7_SQL)
    _execute_commands(_D8_SQL)
    op.execute(_D9_SQL)
    op.execute(_POSTCHECK_SQL)
    # D10 ACL: 코드(runtime_privileges) 변경 + 배포 후 reconcile. D12 models/graph/head pin: 같은 PR.


def downgrade() -> None:
    raise RuntimeError(
        "0225_tvn40c_physical_removal is forward-only; legacy overlay was physically removed"
    )
