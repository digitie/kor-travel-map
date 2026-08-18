"""T-VN-40-mapping — `ops.curation_cutover_identity_mappings` 일회 적재.

Revision ID: 0223_tvn40_identity_mappings
Revises: 0222_tvn40a_merge_runtime_role

설계: `docs/reports/t-vn-40-identity-mapping-loader-design-2026-08-18.md`(적대 리뷰 2명 통과).
근거: 상세 설계 §6.2 step 3·§6.3, `docs/tasks.md` "T-VN-40 인수 — 실태" 사전 task 2.

무엇을 하나. legacy overlay `feature.curated_features`의 각 행을 정확히 하나의 canonical
`feature.curation_items` 행에 대응시켜 0202가 만든 immutable 표에 **한 번** INSERT한다. 이 표는
PinVi가 `GET /v1/service/curation-cutover/identity-mappings`로 소비해 old plan/POI의 legacy UUID를
canonical item UUID로 backfill하는 유일한 입력이다.

분류(행 단위, 첫 매치):
  A  metadata.merge_projection_detached=true            → 중단(merge 의미의 결정, loader가 추정 안 함)
  B  legacy_projection_id = curated_feature_id 인 item 1  → 'legacy_projection' (0045 sync companion;
     2개는 uq_curation_items_legacy_projection_id 로 불가; archived 여부 무관 — identity ≠ liveness)
  C  B=0, 같은 theme·feature·미보관·projection 아닌 item 정확히 1, current_import_row_id 있음
                                                          → 'official_membership'
  D  C 조건인데 import row 없고 created_by/operator_updated_by 있음 → 'manual_membership'
  E  후보 0 · 후보 ≥2 · 근거 없음 · 같은 item을 legacy 2행이 잡음 → 중단(원인별 count)

불변식·실행 형태:
  - DO 블록 하나 = 단일 문장·단일 트랜잭션. 시작에 legacy/item/collection 표를 SHARE 잠금 —
    READ COMMITTED TOCTOU 제거, 그리고 prod ①에서 fence ACL은 upgrade **뒤**에 reconcile되므로
    옛 이미지 writer가 아직 살아 있을 수 있다.
  - 사전조건: 표가 비어 있어야 한다(재적용·오염 방지). 사후조건: 적재 수 = legacy 행 수.
  - bucket count는 RAISE NOTICE로 남기지 않는다(alembic env.py는 asyncpg — listener 없어 버려짐).
    적재 뒤 표를 다시 읽어 Python logging으로 남긴다.
  - alembic env.py에는 transaction_per_migration이 없다 → prod `upgrade head`(0104→0223)는 한
    트랜잭션. 여기서 RAISE하면 0202~0223 전부 롤백된다(head 0104 유지). 그래서 ① 직전에 read-only
    precheck(설계 §5)을 prod에서 돌린다.
  - source_row_hash = 적재 시점 legacy 행 스냅샷 digest(9필드, UTF-8, '|' 구분). 소비자는 대조하지
    않는다 — Merkle root(KTMCUR*)의 leaf 입력일 뿐이다.
  - forward-only. immutable 표라 되돌릴 방법이 원래 없다.

새 FK가 만드는 불변식: mapping.curation_item_id → curation_items(curation_item_id)는 ON UPDATE
CASCADE가 아니다. merge의 legacy-conflict detach가 curation_item_id를 rekey하는 경로는 mapping이
잡은 item에 대해 FK로 막힌다 — identity 안정성이 목적이며 merge_repo가 그 경우를 명시적
MergeConflictError로 먼저 잡는다.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Final

from sqlalchemy import text

from alembic import op

# Frozen PostgreSQL DO-block text intentionally exceeds Python line length.
# ruff: noqa: E501

revision: str = "0223_tvn40_identity_mappings"
down_revision: str | Sequence[str] | None = "0222_tvn40a_merge_runtime_role"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_LOG = logging.getLogger("alembic.runtime.migration")

# `source_row_hash` 정의 — 설계 §4. 테스트가 같은 식을 Python으로 재계산해 대조한다.
# 필드 순서와 구분자를 바꾸면 이미 적재된 prod 행과 다른 digest가 나온다 — 바꾸지 마라.
SOURCE_ROW_HASH_FIELDS: Final[tuple[str, ...]] = (
    "curated_feature_id",
    "theme_id",
    "feature_id",
    "source_id",
    "source_record_key",
    "curation_status",
    "curation_relation",
    "reuse_policy",
    "selection_origin",
)
SOURCE_ROW_HASH_SQL: Final[str] = (
    "encode(x_extension.digest(convert_to(concat_ws('|', "
    "legacy.curated_feature_id::text, legacy.theme_id::text, legacy.feature_id, "
    "coalesce(legacy.source_id::text, ''), coalesce(legacy.source_record_key, ''), "
    "legacy.curation_status, legacy.curation_relation, legacy.reuse_policy, "
    "legacy.selection_origin), 'UTF8'), 'sha256'), 'hex')"
)

# 테스트가 importlib로 이 모듈을 읽어 같은 본문을 실행한다(설계 §6). 여기 두는 이유:
# runtime(`src/kortravelmap`)은 이 표에 SELECT만이며 적재 SQL을 가져서는 안 된다.
LOADER_SQL: Final[str] = f"""
DO $tvn40_mapping$
DECLARE
    v_existing bigint;
    v_legacy bigint;
    v_detached bigint;
    v_zero bigint;
    v_multi bigint;
    v_no_evidence bigint;
    v_item_claimed_twice bigint;
    v_inserted bigint;
BEGIN
    -- 0. 정지 상태 확보 (설계 §5 step 0). lock_timeout: prod는 0(무한)이라 옛 이미지 writer가
    --    curated_features에 ROW EXCLUSIVE를 쥐고 있으면 0104→0223 전체 트랜잭션이 영원히 기다린다.
    --    30초 안에 못 잡으면 실패(→ 전체 롤백·재시도)가 낫다.
    SET LOCAL lock_timeout = '30s';
    LOCK TABLE feature.curated_features, feature.curation_items, feature.curation_collections IN SHARE MODE;

    -- 1. 사전조건: 표가 비어 있다
    SELECT count(*) INTO v_existing FROM ops.curation_cutover_identity_mappings;
    IF v_existing <> 0 THEN
        RAISE EXCEPTION 'tvn40 identity mapping: ops.curation_cutover_identity_mappings already has % row(s); the table is immutable and this loader is one-shot', v_existing
            USING ERRCODE = 'P0001';
    END IF;

    SELECT count(*) INTO v_legacy FROM feature.curated_features;

    -- 2. 중단 bucket (A/E) — 하나라도 있으면 원인별 count를 담아 중단
    SELECT count(*) INTO v_detached
    FROM feature.curated_features AS legacy
    WHERE legacy.metadata @> '{{"merge_projection_detached": true}}'::jsonb;

    -- 같은 트랜잭션에서 loader를 다시 부르는 테스트를 위해 먼저 지운다
    DROP TABLE IF EXISTS tvn40_mapping_candidates;
    CREATE TEMP TABLE tvn40_mapping_candidates ON COMMIT DROP AS
    WITH projection AS (
        SELECT item.legacy_projection_id AS legacy_id, item.curation_item_id, item.collection_id
        FROM feature.curation_items AS item
        WHERE item.legacy_projection_id IS NOT NULL
    ),
    membership AS (
        SELECT
            legacy.curated_feature_id AS legacy_id,
            item.curation_item_id,
            item.collection_id,
            CASE
                WHEN item.current_import_row_id IS NOT NULL THEN 'official_membership'
                WHEN item.created_by IS NOT NULL OR item.operator_updated_by IS NOT NULL THEN 'manual_membership'
                ELSE NULL
            END AS mapping_kind
        FROM feature.curated_features AS legacy
        JOIN feature.curation_collections AS collection ON collection.theme_id = legacy.theme_id
        JOIN feature.curation_items AS item
          ON item.collection_id = collection.collection_id
         AND item.feature_id = legacy.feature_id
         AND item.archived_at IS NULL
         AND item.legacy_projection_id IS NULL
        WHERE NOT EXISTS (
            SELECT 1 FROM projection AS p WHERE p.legacy_id = legacy.curated_feature_id
        )
    )
    SELECT legacy.curated_feature_id AS legacy_id,
           p.curation_item_id AS projection_item_id,
           p.collection_id AS projection_collection_id,
           (SELECT count(*) FROM membership AS m WHERE m.legacy_id = legacy.curated_feature_id) AS membership_count,
           (SELECT m.curation_item_id FROM membership AS m WHERE m.legacy_id = legacy.curated_feature_id LIMIT 1) AS membership_item_id,
           (SELECT m.collection_id FROM membership AS m WHERE m.legacy_id = legacy.curated_feature_id LIMIT 1) AS membership_collection_id,
           (SELECT m.mapping_kind FROM membership AS m WHERE m.legacy_id = legacy.curated_feature_id LIMIT 1) AS membership_kind
    FROM feature.curated_features AS legacy
    LEFT JOIN projection AS p ON p.legacy_id = legacy.curated_feature_id;

    SELECT count(*) INTO v_zero FROM tvn40_mapping_candidates
    WHERE projection_item_id IS NULL AND membership_count = 0;
    SELECT count(*) INTO v_multi FROM tvn40_mapping_candidates
    WHERE projection_item_id IS NULL AND membership_count >= 2;
    SELECT count(*) INTO v_no_evidence FROM tvn40_mapping_candidates
    WHERE projection_item_id IS NULL AND membership_count = 1 AND membership_kind IS NULL;
    SELECT count(*) INTO v_item_claimed_twice FROM (
        SELECT coalesce(projection_item_id, membership_item_id) AS item_id
        FROM tvn40_mapping_candidates
        WHERE coalesce(projection_item_id, membership_item_id) IS NOT NULL
        GROUP BY 1 HAVING count(*) >= 2
    ) AS dup;

    IF v_detached + v_zero + v_multi + v_no_evidence + v_item_claimed_twice <> 0 THEN
        RAISE EXCEPTION 'tvn40 identity mapping: unmapped/ambiguous legacy rows — detached=% no_candidate=% multi_candidate=% no_evidence=% item_claimed_twice=% (legacy_total=%). Resolve on the canonical side (never edit legacy) and re-run; see design §5.',
            v_detached, v_zero, v_multi, v_no_evidence, v_item_claimed_twice, v_legacy
            USING ERRCODE = 'P0001';
    END IF;

    -- 3. 적재 (B → C/D)
    INSERT INTO ops.curation_cutover_identity_mappings (
        legacy_curated_feature_id, collection_id, curation_item_id, mapping_kind, source_row_hash
    )
    SELECT
        legacy.curated_feature_id,
        coalesce(c.projection_collection_id, c.membership_collection_id),
        coalesce(c.projection_item_id, c.membership_item_id),
        CASE WHEN c.projection_item_id IS NOT NULL THEN 'legacy_projection' ELSE c.membership_kind END,
        {SOURCE_ROW_HASH_SQL}
    FROM feature.curated_features AS legacy
    JOIN tvn40_mapping_candidates AS c ON c.legacy_id = legacy.curated_feature_id;

    GET DIAGNOSTICS v_inserted = ROW_COUNT;

    -- 4. 사후조건
    IF v_inserted <> v_legacy THEN
        RAISE EXCEPTION 'tvn40 identity mapping: inserted % row(s) but legacy has % — refusing partial map', v_inserted, v_legacy
            USING ERRCODE = 'P0001';
    END IF;
END
$tvn40_mapping$;
"""

_MANIFEST_SQL: Final[str] = """
SELECT mapping_kind, count(*) AS n
FROM ops.curation_cutover_identity_mappings
GROUP BY mapping_kind
ORDER BY mapping_kind
"""


def upgrade() -> None:
    op.execute(LOADER_SQL)
    # manifest — NOTICE는 asyncpg 경로에서 버려지므로 표를 다시 읽어 남긴다(설계 §5 step 5).
    rows = op.get_bind().execute(text(_MANIFEST_SQL)).all()
    manifest = {str(kind): int(count) for kind, count in rows}
    _LOG.info(
        "0223 tvn40 identity mapping loaded: total=%d by_kind=%s",
        sum(manifest.values()),
        manifest,
    )


def downgrade() -> None:
    raise RuntimeError(
        "0223_tvn40_identity_mappings is forward-only; "
        "ops.curation_cutover_identity_mappings is immutable by design"
    )
