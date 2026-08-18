"""``kortravelmap.infra.merge_repo`` — dedup 수동 병합 1차 함수 (ADR-016).

``ops.dedup_review_queue``의 후보 1쌍(또는 명시 master/loser)을 병합한다:

1. loser의 ``provider_sync.source_links``를 master로 재지정(충돌 키는 master가 이미
   보유하므로 drop).
2. loser의 ``feature.curation_items``와 전환기 legacy ``curated_features``를 master로
   재지정(같은 collection item 충돌은 master membership을 남긴다).
3. loser ``feature.features``를 typed lifecycle procedure로 retire/suppress한다.
4. loser에 typed lifecycle override를 남겨 provider 재적재 부활을 차단한다.
5. ``ops.feature_merge_history`` 1행 INSERT(ADR-016 이력 보존).
6. (``review_id`` 주어지면) ``ops.dedup_review_queue`` 행을 ``status='merged'``로
   전이(pending 행만).

master 선정은 ``core.scoring.select_master``(순수, ADR-016 3순위). commit은 호출자
책임(한 단위 of work — 하나라도 실패하면 호출자가 rollback). raw SQL은 본 모듈에
모음(ADR-004).

ADR 참조
--------
- ADR-004 — ORM 매핑만, 쿼리는 raw SQL
- ADR-008 — schema 격리(feature/provider_sync/ops)
- ADR-016 — master 선정 + ``feature_merge_history``
- ADR-017 — place soft-delete(무기한 보관, status만 전이)
- ADR-039 — 중복 실행은 호출 측 advisory lock(``dedup-merge:{review_id}``)
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from sqlalchemy import text

from kortravelmap.core.scoring import MasterCandidate, select_master
from kortravelmap.infra.curation_link_basis import trusted_basis_sql
from kortravelmap.infra.feature_repo import lock_feature_curation_write

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = [
    "MergeConflictError",
    "MergeError",
    "MergeNotFoundError",
    "MergeOutcome",
    "apply_feature_merge",
    "merge_from_review",
]


class MergeError(ValueError):
    """병합 불가(후보 미존재 / 이미 검토 완료 / feature 부재 등)."""


class MergeNotFoundError(MergeError):
    """병합 대상 review/feature를 찾을 수 없을 때 발생."""


class MergeConflictError(MergeError):
    """병합 대상은 있으나 현재 상태/입력이 병합을 허용하지 않을 때 발생."""


@dataclass(frozen=True)
class MergeOutcome:
    """병합 결과 — 어느 쪽이 master가 됐고 무엇이 바뀌었는지.

    - ``master_feature_id`` / ``loser_feature_id`` — 선정 결과.
    - ``source_links_moved`` — loser → master로 재지정된 source_link 수.
    - ``source_links_dropped`` — master가 이미 보유해 drop된 충돌 link 수.
    - ``merge_id`` — ``feature_merge_history`` 행 id.
    - ``queue_updated`` — ``dedup_review_queue`` 행이 merged로 전이됐는지.
    """

    master_feature_id: str
    loser_feature_id: str
    source_links_moved: int
    source_links_dropped: int
    merge_id: str
    queue_updated: bool


# ─── SQL 상수 (EXPLAIN 검증 대상) ───────────────────────────────────────────

# master 선정 입력 — 좌표 보유 / updated_at / 1차 source provider.
_SELECT_MASTER_INPUT_SQL: Final[str] = """
SELECT
    f.feature_id AS feature_id,
    (f.coord IS NOT NULL) AS has_coord,
    f.updated_at AS updated_at,
    (
        SELECT pd.provider
        FROM provider_sync.source_links sl
        JOIN provider_sync.source_entities se
          ON se.source_entity_key = sl.source_entity_key
        JOIN provider_sync.provider_datasets pd
          ON pd.provider_dataset_id = se.provider_dataset_id
        WHERE sl.feature_id = f.feature_id
        ORDER BY (sl.source_role = 'primary') DESC, sl.confidence DESC
        LIMIT 1
    ) AS provider
FROM feature.features f
WHERE f.feature_id = :feature_id
"""

# 검토 큐 행 조회(병합 진입점).
_SELECT_REVIEW_SQL: Final[str] = """
SELECT feature_id_a, feature_id_b, total_score, status
FROM ops.dedup_review_queue
WHERE review_id = :review_id
FOR UPDATE
"""

# loser source_link 중 master가 아직 안 가진 것만 master로 재지정.
# (rowcount 대신 RETURNING + fetchall — Result 타입 폭 회피, 코드베이스 컨벤션.)
_MOVE_LINKS_SQL: Final[str] = """
UPDATE provider_sync.source_links
SET feature_id = :master
WHERE feature_id = :loser
  AND source_entity_key NOT IN (
      SELECT source_entity_key
      FROM provider_sync.source_links
      WHERE feature_id = :master
  )
RETURNING source_entity_key
"""

# master가 이미 보유한 충돌 link(재지정 후 loser에 남은 것) drop.
_DROP_LEFTOVER_LINKS_SQL: Final[str] = """
DELETE FROM provider_sync.source_links WHERE feature_id = :loser
RETURNING source_entity_key
"""

# master/loser를 잠그면서 kind와 lifecycle tuple/revision까지 같이 읽는다.
# cross-kind 판정과 T-VN-34 transition의 expected revision이 같은 lock snapshot을
# 쓰므로 실행 사이에 kind/state가 바뀔 수 없다.
_LOCK_FEATURES_SQL: Final[str] = """
SELECT feature_id, kind, lifecycle_state, publication_state, quality_state, row_revision
FROM feature.features
WHERE feature_id IN (:master, :loser)
ORDER BY feature_id
FOR UPDATE
"""

# T-VN-40A(0222): legacy mirror 4문은 SECURITY DEFINER procedure다. fence가 runtime의
# `curated_features` write 권한을 뺐으므로(ACL 층) runtime이 직접 UPDATE/FOR UPDATE를
# 하면 42501이다. `ktm_curation_command_owner` 소유 procedure를 CALL해 mirror만 열어 둔다 —
# 0214의 canonical→legacy mirror와 같은 패턴. 4문을 하나로 합치지 않은 이유는 사이에
# canonical 작업이 끼어 호출 **순서**가 계약이기 때문이다. 40C에서 legacy와 함께 사라진다.
#
# Merge는 Feature lifecycle을 먼저 고정한 뒤 legacy→collection→item 순서로
# 잠근다. Legacy DML의 row→collection→item 순서와 import의 Feature→collection
# 순서를 모두 확장하므로 양방향 sync/import와 교착하지 않는다.
_LOCK_CURATION_LEGACY_PROJECTIONS_SQL: Final[str] = """
CALL feature.merge_lock_legacy_curated_features(CAST(:master AS text), CAST(:loser AS text))
"""

# Feature를 선잠근 merge와 legacy-backed writer는 legacy row를 거쳐
# collection(parent)→item(child) 순서로 들어간다. 영향 collection은 UUID
# 순서로 잠가 import/admin writer와의 교착을 막는다.
# 0222: runtime은 canonical 표에 lock 권한이 없으므로(0204 패턴) command_owner 소유
# procedure 안에서 잠근다 — 행 잠금은 트랜잭션 범위라 반환 뒤에도 유지된다.
_LOCK_CURATION_COLLECTIONS_SQL: Final[str] = """
CALL feature.merge_lock_curation_collections(CAST(:master AS text), CAST(:loser AS text))
"""

# 한 collection의 동일 official item에는 source에서 빠진 과거 component와 현재
# component가 함께 있을 수 있다. 따라서 master×loser pair join으로 UPDATE하지 않고,
# feature별 canonical row를 먼저 하나씩 고른 뒤 external item group당 정확히 한 번
# reconcile한다. 모든 loser duplicate는 일반 MOVE보다 먼저 source-absent master history로
# 전환해 active partial unique 충돌을 없애며 import/link provenance FK는 그대로 보존한다.
_MERGE_DUPLICATE_CURATION_ITEMS_SQL: Final[str] = """
WITH locked_items AS MATERIALIZED (
    SELECT
        item.*
    FROM feature.curation_items AS item
    WHERE item.feature_id IN (:master, :loser)
    ORDER BY
        item.collection_id,
        item.external_item_id,
        item.feature_id,
        item.curation_item_id
    FOR UPDATE OF item
), ranked AS MATERIALIZED (
    SELECT
        item.*,
        row_number() OVER (
            PARTITION BY
                item.collection_id,
                item.external_item_id,
                item.feature_id
            ORDER BY
                (
                    item.source_present
                    AND item.archived_at IS NULL
                    AND item.status <> 'archived'
                ) DESC,
                item.source_present DESC,
                (item.archived_at IS NULL) DESC,
                item.source_updated_at DESC,
                item.curation_item_id
        ) AS feature_rank
    FROM locked_items AS item
), canonical AS MATERIALIZED (
    SELECT *
    FROM ranked
    WHERE feature_rank = 1
), plans AS MATERIALIZED (
    SELECT
        master_item.collection_id,
        master_item.external_item_id,
        master_item.curation_item_id AS survivor_item_id,
        provider_winner.curation_item_id AS provider_winner_item_id,
        provider_winner.feature_id AS provider_winner_feature_id,
        operator_winner.curation_item_id AS operator_winner_item_id,
        (
            master_item.archived_at IS NOT NULL
            OR loser_item.archived_at IS NOT NULL
        ) AS tombstone_wins,
        bool_or(
            grouped.source_present
            AND grouped.archived_at IS NULL
            AND grouped.status <> 'archived'
        ) AS any_active_source
    FROM canonical AS master_item
    JOIN canonical AS loser_item
      ON loser_item.collection_id = master_item.collection_id
     AND loser_item.external_item_id = master_item.external_item_id
     AND loser_item.feature_id = :loser
    JOIN LATERAL (
        SELECT candidate.*
        FROM (VALUES
            (
                master_item.curation_item_id,
                master_item.feature_id,
                master_item.source_present,
                master_item.archived_at,
                master_item.status,
                master_item.source_updated_at
            ),
            (
                loser_item.curation_item_id,
                loser_item.feature_id,
                loser_item.source_present,
                loser_item.archived_at,
                loser_item.status,
                loser_item.source_updated_at
            )
        ) AS candidate(
            curation_item_id,
            feature_id,
            source_present,
            archived_at,
            status,
            source_updated_at
        )
        ORDER BY
            (
                candidate.source_present
                AND candidate.archived_at IS NULL
                AND candidate.status <> 'archived'
            ) DESC,
            candidate.source_present DESC,
            (candidate.archived_at IS NULL) DESC,
            candidate.source_updated_at DESC,
            candidate.curation_item_id
        LIMIT 1
    ) AS provider_winner ON true
    JOIN LATERAL (
        SELECT candidate.*
        FROM (VALUES
            (
                master_item.curation_item_id,
                master_item.archived_at,
                master_item.operator_updated_at
            ),
            (
                loser_item.curation_item_id,
                loser_item.archived_at,
                loser_item.operator_updated_at
            )
        ) AS candidate(
            curation_item_id,
            archived_at,
            operator_updated_at
        )
        ORDER BY
            (candidate.archived_at IS NOT NULL) DESC,
            COALESCE(
                candidate.operator_updated_at,
                candidate.archived_at
            ) DESC NULLS LAST,
            candidate.curation_item_id
        LIMIT 1
    ) AS operator_winner ON true
    JOIN locked_items AS grouped
      ON grouped.collection_id = master_item.collection_id
     AND grouped.external_item_id = master_item.external_item_id
     AND grouped.feature_id IN (:master, :loser)
    WHERE master_item.feature_id = :master
    GROUP BY
        master_item.collection_id,
        master_item.external_item_id,
        master_item.curation_item_id,
        master_item.archived_at,
        loser_item.archived_at,
        provider_winner.curation_item_id,
        provider_winner.feature_id,
        operator_winner.curation_item_id
), duplicate_losers AS MATERIALIZED (
    SELECT
        loser_item.*,
        plan.survivor_item_id
    FROM locked_items AS loser_item
    JOIN plans AS plan
      ON plan.collection_id = loser_item.collection_id
     AND plan.external_item_id = loser_item.external_item_id
    WHERE loser_item.feature_id = :loser
), revocations AS (
    INSERT INTO feature.curation_link_decisions (
        curation_item_id,
        feature_id,
        decision_kind,
        match_basis,
        resolver_version,
        evidence,
        actor,
        supersedes_decision_id
    )
    SELECT
        loser_item.curation_item_id,
        loser_item.feature_id,
        'revoked',
        'forward_recovery',
        'feature-merge-v1',
        jsonb_build_object(
            'operation', 'feature_merge_duplicate_archive',
            'master_feature_id', CAST(:master AS text),
            'loser_feature_id', CAST(:loser AS text),
            'review_id', CAST(:review_id AS text),
            'reason', CAST(:reason AS text)
        ),
        :merge_actor,
        loser_item.accepted_link_decision_id
    FROM duplicate_losers AS loser_item
    WHERE loser_item.accepted_link_decision_id IS NOT NULL
    RETURNING curation_item_id
), reconciled AS (
    UPDATE feature.curation_items AS survivor
    SET source_record_key = provider_winner.source_record_key,
        place_name = provider_winner.place_name,
        address_hint = provider_winner.address_hint,
        source_present = plan.any_active_source,
        source_updated_at = provider_winner.source_updated_at,
        status = CASE
            WHEN plan.tombstone_wins THEN 'archived'
            ELSE operator_winner.status
        END,
        sort_order = provider_winner.sort_order,
        item_title = provider_winner.item_title,
        item_summary = provider_winner.item_summary,
        curation_relation = operator_winner.curation_relation,
        reuse_policy = operator_winner.reuse_policy,
        metadata = provider_winner.metadata,
        updated_by = operator_winner.updated_by,
        operator_updated_by = operator_winner.operator_updated_by,
        operator_updated_at = operator_winner.operator_updated_at,
        updated_at = now(),
        archived_at = CASE
            WHEN plan.tombstone_wins THEN operator_winner.archived_at
            ELSE NULL
        END
    FROM plans AS plan
    JOIN locked_items AS provider_winner
      ON provider_winner.curation_item_id =
         plan.provider_winner_item_id
    JOIN locked_items AS operator_winner
      ON operator_winner.curation_item_id =
         plan.operator_winner_item_id
    WHERE survivor.curation_item_id = plan.survivor_item_id
    RETURNING
        survivor.collection_id,
        survivor.external_item_id,
        survivor.curation_item_id AS survivor_item_id,
        plan.provider_winner_item_id,
        (
            plan.provider_winner_item_id <>
            survivor.curation_item_id
        ) AS provider_winner_requires_recovery
), archived AS (
    UPDATE feature.curation_items AS loser_item
    SET feature_id = NULL,
        accepted_link_decision_id = NULL,
        source_present = false,
        status = 'archived',
        updated_by = :merge_actor,
        updated_at = now(),
        archived_at = COALESCE(loser_item.archived_at, now()),
        metadata = loser_item.metadata || jsonb_build_object(
            'feature_merge_duplicate_archived', true,
            'feature_merge_master_id', CAST(:master AS text),
            'feature_merge_loser_id', CAST(:loser AS text)
        )
    FROM duplicate_losers
    JOIN reconciled
      ON reconciled.collection_id = duplicate_losers.collection_id
     AND reconciled.external_item_id =
         duplicate_losers.external_item_id
    LEFT JOIN revocations
      ON revocations.curation_item_id =
         duplicate_losers.curation_item_id
    WHERE loser_item.curation_item_id =
          duplicate_losers.curation_item_id
    RETURNING
        loser_item.collection_id,
        loser_item.external_item_id,
        loser_item.curation_item_id
), archived_groups AS (
    SELECT DISTINCT collection_id, external_item_id
    FROM archived
)
SELECT
    reconciled.survivor_item_id,
    reconciled.provider_winner_item_id,
    reconciled.provider_winner_requires_recovery
FROM reconciled
JOIN archived_groups
  ON archived_groups.collection_id = reconciled.collection_id
 AND archived_groups.external_item_id =
     reconciled.external_item_id
"""

_MOVE_CURATION_ITEMS_SQL: Final[str] = f"""
WITH candidates AS MATERIALIZED (
    SELECT
        item.curation_item_id,
        item.feature_id,
        item.accepted_link_decision_id,
        current_decision.decision_kind AS previous_decision_kind,
        current_decision.match_basis AS previous_match_basis,
        COALESCE(
            current_decision.decision_kind = 'accepted'
            AND {trusted_basis_sql("current_decision.match_basis")},
            false
        ) AS has_trusted_acceptance,
        (
            item.archived_at IS NULL
            AND item.source_present
            AND item.status <> 'archived'
        ) AS remains_active
    FROM feature.curation_items AS item
    LEFT JOIN feature.curation_link_decisions AS current_decision
      ON current_decision.decision_id = item.accepted_link_decision_id
     AND current_decision.curation_item_id = item.curation_item_id
     AND current_decision.feature_id = item.feature_id
    WHERE item.feature_id = :loser
    FOR UPDATE OF item
), decisions AS (
    INSERT INTO feature.curation_link_decisions (
        curation_item_id,
        feature_id,
        decision_kind,
        match_basis,
        resolver_version,
        evidence,
        actor,
        supersedes_decision_id
    )
    SELECT
        candidate.curation_item_id,
        CASE
            WHEN candidate.remains_active
             AND candidate.has_trusted_acceptance
            THEN CAST(:master AS text)
            ELSE candidate.feature_id
        END,
        CASE
            WHEN candidate.remains_active
             AND candidate.has_trusted_acceptance
            THEN 'accepted'
            ELSE 'revoked'
        END,
        'forward_recovery',
        'feature-merge-v1',
        jsonb_build_object(
            'operation', 'feature_merge_link_retarget',
            'master_feature_id', CAST(:master AS text),
            'loser_feature_id', CAST(:loser AS text),
            'review_id', CAST(:review_id AS text),
            'reason', CAST(:reason AS text),
            'previous_decision_kind', candidate.previous_decision_kind,
            'previous_match_basis', candidate.previous_match_basis,
            'trusted_acceptance',
                candidate.has_trusted_acceptance
        ),
        :merge_actor,
        candidate.accepted_link_decision_id
    FROM candidates AS candidate
    RETURNING decision_id, curation_item_id, decision_kind
)
UPDATE feature.curation_items AS item
SET feature_id = :master,
    accepted_link_decision_id = CASE
        WHEN decision.decision_kind = 'accepted' THEN decision.decision_id
        ELSE NULL
    END,
    updated_by = :merge_actor,
    updated_at = now()
FROM candidates AS candidate
LEFT JOIN decisions AS decision
  ON decision.curation_item_id = candidate.curation_item_id
WHERE item.curation_item_id = candidate.curation_item_id
RETURNING item.curation_item_id
"""

_INSERT_MERGE_IMPORT_BATCH_SQL: Final[str] = """
INSERT INTO feature.curation_import_batches (
    content_sha256,
    batch_kind,
    row_count,
    actor,
    metadata
) VALUES (
    :content_sha256,
    'forward_recovery',
    :row_count,
    :merge_actor,
    CAST(:metadata AS jsonb)
)
RETURNING import_batch_id
"""

_APPEND_DUPLICATE_MERGE_IMPORT_ROWS_SQL: Final[str] = f"""
WITH pair_input AS MATERIALIZED (
    SELECT *
    FROM jsonb_to_recordset(CAST(:pairs AS jsonb)) AS pair(
        row_number integer,
        survivor_item_id uuid,
        provider_winner_item_id uuid
    )
), snapshots AS MATERIALIZED (
    SELECT
        pair.row_number,
        survivor.curation_item_id,
        survivor.feature_id,
        survivor.accepted_link_decision_id AS previous_decision_id,
        previous_decision.decision_kind AS previous_decision_kind,
        previous_decision.match_basis AS previous_match_basis,
        survivor.current_import_row_id AS survivor_previous_import_row_id,
        provider_winner.current_import_row_id AS
            provider_winner_import_row_id,
        jsonb_build_object(
            'row_number', pair.row_number,
            'collection_key', collection.collection_key,
            'theme_slug', theme.theme_slug,
            'theme_name', theme.theme_name,
            'theme_group', theme.theme_group,
            'title', collection.title,
            'edition_key', collection.edition_key,
            'provider', dataset.provider,
            'dataset_key', dataset.dataset_key,
            'source_name', source.source_name,
            'source_url', source.source_url,
            'source_item_key', survivor.external_item_id,
            'source_component_key', survivor.external_component_id,
            'feature_id', survivor.feature_id,
            'place_name', survivor.place_name,
            'address_hint', survivor.address_hint,
            'sort_order', survivor.sort_order,
            'item_title', survivor.item_title,
            'item_summary', survivor.item_summary,
            'metadata', survivor.metadata
        ) AS row_payload
    FROM pair_input AS pair
    JOIN feature.curation_items AS survivor
      ON survivor.curation_item_id = pair.survivor_item_id
    JOIN feature.curation_items AS provider_winner
      ON provider_winner.curation_item_id =
         pair.provider_winner_item_id
    JOIN feature.curation_collections AS collection
      ON collection.collection_id = survivor.collection_id
    JOIN feature.curated_themes AS theme
      ON theme.theme_id = collection.theme_id
    LEFT JOIN feature.curated_sources AS source
      ON source.source_id = collection.source_id
    LEFT JOIN provider_sync.provider_datasets AS dataset
      ON dataset.provider_dataset_id = source.provider_dataset_id
    LEFT JOIN feature.curation_link_decisions AS previous_decision
      ON previous_decision.decision_id =
         survivor.accepted_link_decision_id
     AND previous_decision.curation_item_id =
         survivor.curation_item_id
     AND previous_decision.feature_id = survivor.feature_id
), inserted_rows AS (
    INSERT INTO feature.curation_import_rows (
        import_batch_id,
        curation_item_id,
        row_number,
        source_row_sha256,
        row_payload,
        provenance
    )
    SELECT
        CAST(:import_batch_id AS uuid),
        snapshot.curation_item_id,
        snapshot.row_number,
        encode(
            x_extension.digest(snapshot.row_payload::text, 'sha256'),
            'hex'
        ),
        snapshot.row_payload,
        jsonb_build_object(
            'schema_version', 1,
            'operation', 'feature_merge_duplicate_source_winner',
            'master_feature_id', CAST(:master AS text),
            'loser_feature_id', CAST(:loser AS text),
            'review_id', CAST(:review_id AS text),
            'reason', CAST(:reason AS text),
            'survivor_previous_import_row_id',
                snapshot.survivor_previous_import_row_id,
            'provider_winner_import_row_id',
                snapshot.provider_winner_import_row_id
        )
    FROM snapshots AS snapshot
    RETURNING import_row_id, curation_item_id, source_row_sha256
), accepted AS (
    INSERT INTO feature.curation_link_decisions (
        curation_item_id,
        feature_id,
        import_row_id,
        decision_kind,
        match_basis,
        resolver_version,
        evidence,
        actor,
        supersedes_decision_id
    )
    SELECT
        snapshot.curation_item_id,
        snapshot.feature_id,
        inserted.import_row_id,
        'accepted',
        'forward_recovery',
        'feature-merge-v2',
        jsonb_build_object(
            'operation', 'feature_merge_duplicate_source_winner',
            'master_feature_id', CAST(:master AS text),
            'loser_feature_id', CAST(:loser AS text),
            'review_id', CAST(:review_id AS text),
            'reason', CAST(:reason AS text),
            'source_row_sha256', inserted.source_row_sha256,
            'previous_match_basis', snapshot.previous_match_basis
        ),
        :merge_actor,
        snapshot.previous_decision_id
    FROM snapshots AS snapshot
    JOIN inserted_rows AS inserted
      ON inserted.curation_item_id = snapshot.curation_item_id
    WHERE snapshot.previous_decision_kind = 'accepted'
      AND {trusted_basis_sql("snapshot.previous_match_basis")}
    RETURNING decision_id, curation_item_id
)
UPDATE feature.curation_items AS survivor
SET current_import_row_id = inserted.import_row_id,
    accepted_link_decision_id = accepted.decision_id,
    updated_by = :merge_actor,
    updated_at = now()
FROM inserted_rows AS inserted
LEFT JOIN accepted
  ON accepted.curation_item_id = inserted.curation_item_id
WHERE survivor.curation_item_id = inserted.curation_item_id
RETURNING
    survivor.curation_item_id,
    survivor.current_import_row_id,
    survivor.accepted_link_decision_id
"""

# Duplicate reconcile가 loser의 최신 operator state/tombstone을 master canonical
# survivor에 반영했으면 master legacy projection도 같은 transaction에서 맞춘다.
_SYNC_MASTER_LEGACY_PROJECTIONS_SQL: Final[str] = """
CALL feature.merge_sync_master_legacy_curated_features(CAST(:master AS text))
"""

# Legacy projection 동기화 전에는 duplicate history의 target을 비워 둔다. 같은
# collection/external item에서 survivor와 archived history가 모두 master를 가리키면
# 0065 legacy trigger의 target identity 조회가 둘 중 하나를 임의 선택해 active master
# projection을 detach할 수 있다. 정본 projection을 먼저 동기화한 뒤 history만 master로
# 옮기며 source/current pointer는 건드리지 않는다.
_MOVE_ARCHIVED_DUPLICATE_CURATION_HISTORY_SQL: Final[str] = """
UPDATE feature.curation_items AS item
SET feature_id = :master,
    updated_at = now()
WHERE item.feature_id IS NULL
  AND NOT item.source_present
  AND item.archived_at IS NOT NULL
  AND item.metadata @> jsonb_build_object(
      'feature_merge_duplicate_archived', true,
      'feature_merge_master_id', CAST(:master AS text),
      'feature_merge_loser_id', CAST(:loser AS text)
  )
RETURNING item.curation_item_id
"""

# 0045 전환 trigger는 legacy curated_feature UUID와 같은 curation_item UUID를 다시
# 만든다. master에도 같은 theme의 active legacy row가 있으면 loser legacy row를
# active 상태로 옮길 수 없으므로, 먼저 해당 item의 UUID를 분리해 richer membership을
# 보존한 뒤 legacy row만 archive한다.
_DETACH_CONFLICTING_LEGACY_CURATION_ITEMS_SQL: Final[str] = """
UPDATE feature.curation_items AS item
SET curation_item_id = x_extension.gen_random_uuid(),
    legacy_projection_id = NULL,
    updated_at = now()
FROM feature.curated_features AS loser_curated
WHERE loser_curated.curated_feature_id = item.legacy_projection_id
  AND loser_curated.feature_id = :loser
  AND loser_curated.archived_at IS NULL
  AND item.archived_at IS NULL
  AND EXISTS (
      SELECT 1
      FROM feature.curated_features AS master_curated
      WHERE master_curated.feature_id = :master
        AND master_curated.theme_id = loser_curated.theme_id
        AND master_curated.archived_at IS NULL
  )
RETURNING loser_curated.curated_feature_id
"""

# 0223(T-VN-40-mapping) 이후 `ops.curation_cutover_identity_mappings.curation_item_id`가
# item PK를 ON UPDATE CASCADE 없이 참조한다 — PinVi cutover의 identity 안정성이 목적이다.
# 위 DETACH는 item UUID를 rekey하므로 mapping이 잡은 item에 대해서는 FK로 막힌다. raw
# 23503 대신 명시적 MergeConflictError를 내기 위해 같은 술어로 먼저 검사한다.
_PINNED_LEGACY_CONFLICT_ITEMS_SQL: Final[str] = """
SELECT item.curation_item_id
FROM feature.curation_items AS item
JOIN feature.curated_features AS loser_curated
  ON loser_curated.curated_feature_id = item.legacy_projection_id
JOIN ops.curation_cutover_identity_mappings AS mapping
  ON mapping.curation_item_id = item.curation_item_id
WHERE loser_curated.feature_id = :loser
  AND loser_curated.archived_at IS NULL
  AND item.archived_at IS NULL
  AND EXISTS (
      SELECT 1
      FROM feature.curated_features AS master_curated
      WHERE master_curated.feature_id = :master
        AND master_curated.theme_id = loser_curated.theme_id
        AND master_curated.archived_at IS NULL
  )
ORDER BY item.curation_item_id
"""

# UUID가 분리된 same-theme legacy conflict 또는 아직 이동하지 않은 loser UUID item과
# 같은 stored collection/external identity의 master canonical pair만 archive한다.
# Mutable slug/title로 collection key를 재계산하거나 MOVE 뒤 feature_id를 증거로 쓰지 않는다.
_ARCHIVE_CONFLICTING_LEGACY_CURATED_FEATURES_SQL: Final[str] = """
CALL feature.merge_archive_conflicting_legacy_curated_features(
    CAST(:master AS text), CAST(:loser AS text)
)
"""

# 충돌을 정리한 뒤 남은 active/archived legacy row도 master로 옮긴다. 이 UPDATE로
# 0045 trigger가 다시 실행되어도 NEW.feature_id가 master이므로 병합이 되돌아가지 않는다.
_MOVE_LEGACY_CURATED_FEATURES_SQL: Final[str] = """
CALL feature.merge_move_legacy_curated_features(CAST(:master AS text), CAST(:loser AS text))
"""

_TRANSITION_LOSER_LIFECYCLE_SQL: Final[str] = """
CALL feature.transition_feature_state(
    CAST(:feature_id AS text),
    'retired',
    'suppressed',
    CAST(:quality_state AS text),
    CAST(:expected_row_revision AS bigint),
    CAST(:state_context AS jsonb),
    NULL, NULL
)
"""

_AUTHOR_LOSER_LIFECYCLE_OVERRIDE_SQL: Final[str] = """
CALL feature.author_lifecycle_override(
    CAST(:feature_id AS text),
    CAST(:source_lifecycle_state AS text),
    'retired',
    true,
    CAST(:reason AS text),
    CAST(:principal AS text),
    CAST(:expected_row_revision AS bigint),
    NULL
)
"""

_INSERT_HISTORY_SQL: Final[str] = """
INSERT INTO ops.feature_merge_history (
    master_feature_id, loser_feature_id, score, review_id, merged_by, reason
) VALUES (
    :master, :loser, :score, :review_id, :merged_by, :reason
)
RETURNING merge_id
"""

# 큐 행을 merged로 전이 — pending 행만(이미 검토된 행 보존).
_MARK_QUEUE_MERGED_SQL: Final[str] = """
UPDATE ops.dedup_review_queue
SET status = 'merged', reviewed_at = now(), reviewed_by = :merged_by,
    decision_reason = COALESCE(:reason, decision_reason)
WHERE review_id = :review_id AND status = 'pending'
RETURNING review_id
"""


async def _master_candidate(session: AsyncSession, feature_id: str) -> MasterCandidate:
    row = (
        await session.execute(text(_SELECT_MASTER_INPUT_SQL), {"feature_id": feature_id})
    ).one_or_none()
    if row is None:
        raise MergeConflictError(f"feature 없음 — {feature_id!r}")
    return MasterCandidate(
        feature_id=row.feature_id,
        has_coord=bool(row.has_coord),
        updated_at=row.updated_at,
        provider=row.provider,
    )


def _reject_cross_kind_merge(
    locked_kinds: dict[str, str], *, master_id: str, loser_id: str
) -> None:
    """kind가 다른 두 feature의 병합을 차단한다 (T-VN-35, ADR-086).

    kind는 **어떤 subtype 테이블에 값이 사는지**를 결정한다(``feature_places``
    /``feature_events``/…). 따라서 cross-kind 병합은 "place의 source_link를
    event로 옮기고 place를 지우는" 형태가 되어, 옮겨간 provider 정체성과 남은
    typed 값이 서로 다른 계약을 가리키게 된다 — 데이터 무결성을 직접 깬다.
    dedup 후보 생성기는 같은 kind만 짝지어 주지만 그 보장은 repo 밖에 있었고,
    ``apply_feature_merge``는 명시 id를 받는 공개 진입점이므로 여기서 닫는다.

    두 행을 모두 잠근 뒤(같은 SELECT … FOR UPDATE) 판정하므로 TOCTOU가 없다.
    한쪽 행이 없으면(=병합 대상 부재) kind 비교 자체가 성립하지 않고, 그
    경우의 처리는 종전과 같이 후속 단계가 맡는다.
    """

    master_kind = locked_kinds.get(master_id)
    loser_kind = locked_kinds.get(loser_id)
    if master_kind is None or loser_kind is None or master_kind == loser_kind:
        return
    raise MergeConflictError(
        "kind가 다른 feature는 병합할 수 없음 — "
        f"master {master_id!r}={master_kind!r}, loser {loser_id!r}={loser_kind!r}"
    )


async def apply_feature_merge(
    session: AsyncSession,
    *,
    master_id: str,
    loser_id: str,
    score: float | None = None,
    review_id: str | None = None,
    merged_by: str | None = None,
    reason: str | None = None,
) -> MergeOutcome:
    """명시 master/loser로 병합 적용(재지정 → soft-delete → 이력 → 큐 전이).

    commit은 호출자 책임. ``master_id == loser_id``는 ``MergeError``.
    """
    if master_id == loser_id:
        raise MergeConflictError(f"master와 loser가 같음 — {master_id!r}")

    await lock_feature_curation_write(session)

    locked_rows = (
        await session.execute(
            text(_LOCK_FEATURES_SQL),
            {"master": master_id, "loser": loser_id},
        )
    ).mappings().all()
    locked_kinds = {str(row["feature_id"]): str(row["kind"]) for row in locked_rows}
    _reject_cross_kind_merge(locked_kinds, master_id=master_id, loser_id=loser_id)
    loser_state = next(
        (row for row in locked_rows if str(row["feature_id"]) == loser_id), None
    )
    if loser_state is None:
        raise MergeConflictError(f"loser feature 없음 — {loser_id!r}")
    await session.execute(
        text(_LOCK_CURATION_LEGACY_PROJECTIONS_SQL),
        {"master": master_id, "loser": loser_id},
    )
    await session.execute(
        text(_LOCK_CURATION_COLLECTIONS_SQL),
        {"master": master_id, "loser": loser_id},
    )
    moved = len(
        (
            await session.execute(text(_MOVE_LINKS_SQL), {"master": master_id, "loser": loser_id})
        ).fetchall()
    )
    dropped = len(
        (await session.execute(text(_DROP_LEFTOVER_LINKS_SQL), {"loser": loser_id})).fetchall()
    )
    pinned = [
        str(row[0])
        for row in (
            await session.execute(
                text(_PINNED_LEGACY_CONFLICT_ITEMS_SQL),
                {"master": master_id, "loser": loser_id},
            )
        ).fetchall()
    ]
    if pinned:
        raise MergeConflictError(
            "same-theme legacy conflict item(s) are pinned by the T-VN-40 cutover identity "
            f"mapping and cannot be re-keyed — {pinned!r}. Resolve on the canonical side "
            "(archive/retarget the item through admin commands) before merging."
        )
    await session.execute(
        text(_DETACH_CONFLICTING_LEGACY_CURATION_ITEMS_SQL),
        {"master": master_id, "loser": loser_id},
    )
    await session.execute(
        text(_ARCHIVE_CONFLICTING_LEGACY_CURATED_FEATURES_SQL),
        {"master": master_id, "loser": loser_id},
    )
    merge_actor = (merged_by or "system:feature-merge").strip()
    if not merge_actor:
        merge_actor = "system:feature-merge"
    curation_merge_params = {
        "master": master_id,
        "loser": loser_id,
        "review_id": review_id,
        "reason": reason,
        "merge_actor": merge_actor,
    }
    duplicate_rows = (
        (
            await session.execute(
                text(_MERGE_DUPLICATE_CURATION_ITEMS_SQL),
                curation_merge_params,
            )
        )
        .mappings()
        .all()
    )
    provider_recovery_pairs = [
        {
            "row_number": row_number,
            "survivor_item_id": str(row["survivor_item_id"]),
            "provider_winner_item_id": str(row["provider_winner_item_id"]),
        }
        for row_number, row in enumerate(
            (row for row in duplicate_rows if bool(row["provider_winner_requires_recovery"])),
            start=1,
        )
    ]
    if provider_recovery_pairs:
        batch_identity = {
            "schema_version": 1,
            "operation": "feature_merge_duplicate_source_winner",
            "master_feature_id": master_id,
            "loser_feature_id": loser_id,
            "review_id": review_id,
            "pairs": provider_recovery_pairs,
        }
        canonical_batch = json.dumps(
            batch_identity,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        import_batch_id = str(
            (
                await session.execute(
                    text(_INSERT_MERGE_IMPORT_BATCH_SQL),
                    {
                        "content_sha256": hashlib.sha256(canonical_batch).hexdigest(),
                        "row_count": len(provider_recovery_pairs),
                        "merge_actor": merge_actor,
                        "metadata": json.dumps(
                            {
                                **batch_identity,
                                "reason": reason,
                            },
                            ensure_ascii=False,
                        ),
                    },
                )
            ).scalar_one()
        )
        await session.execute(
            text(_APPEND_DUPLICATE_MERGE_IMPORT_ROWS_SQL),
            {
                **curation_merge_params,
                "import_batch_id": import_batch_id,
                "pairs": json.dumps(
                    provider_recovery_pairs,
                    ensure_ascii=False,
                ),
            },
        )
    await session.execute(
        text(_MOVE_CURATION_ITEMS_SQL),
        curation_merge_params,
    )
    await session.execute(
        text(_SYNC_MASTER_LEGACY_PROJECTIONS_SQL),
        {"master": master_id},
    )
    await session.execute(
        text(_MOVE_ARCHIVED_DUPLICATE_CURATION_HISTORY_SQL),
        {"master": master_id, "loser": loser_id},
    )
    await session.execute(
        text(_MOVE_LEGACY_CURATED_FEATURES_SQL),
        {"master": master_id, "loser": loser_id},
    )
    merge_reason = (reason or "feature merge").strip() or "feature merge"
    lifecycle_revision = int(loser_state["row_revision"])
    source_lifecycle = str(loser_state["lifecycle_state"])
    if source_lifecycle != "retired":
        transition = (
            await session.execute(
                text(_TRANSITION_LOSER_LIFECYCLE_SQL),
                {
                    "feature_id": loser_id,
                    "quality_state": loser_state["quality_state"],
                    "expected_row_revision": lifecycle_revision,
                    "state_context": json.dumps(
                        {
                            "transition_kind": "merge",
                            "reason_code": "merge_loser",
                            "principal": merge_actor,
                            "causation_ref": review_id,
                        },
                        ensure_ascii=False,
                    ),
                },
            )
        ).mappings().one()
        lifecycle_revision = int(transition["o_row_revision"])
    await session.execute(
        text(_AUTHOR_LOSER_LIFECYCLE_OVERRIDE_SQL),
        {
            "feature_id": loser_id,
            "source_lifecycle_state": source_lifecycle,
            "reason": merge_reason,
            "principal": merge_actor,
            "expected_row_revision": lifecycle_revision,
        },
    )
    merge_id = (
        await session.execute(
            text(_INSERT_HISTORY_SQL),
            {
                "master": master_id,
                "loser": loser_id,
                "score": score,
                "review_id": review_id,
                "merged_by": merged_by,
                "reason": reason,
            },
        )
    ).scalar_one()
    queue_updated = False
    if review_id is not None:
        result = await session.execute(
            text(_MARK_QUEUE_MERGED_SQL),
            {"review_id": review_id, "merged_by": merged_by, "reason": reason},
        )
        queue_updated = bool(result.fetchall())
    return MergeOutcome(
        master_feature_id=master_id,
        loser_feature_id=loser_id,
        source_links_moved=moved,
        source_links_dropped=dropped,
        merge_id=str(merge_id),
        queue_updated=queue_updated,
    )


async def merge_from_review(
    session: AsyncSession,
    review_id: str,
    *,
    merged_by: str | None = None,
    reason: str | None = None,
) -> MergeOutcome:
    """검토 큐 후보(``review_id``) 1쌍을 master 자동 선정 후 병합한다.

    큐 행이 없거나 이미 검토(``status != 'pending'``)됐으면 ``MergeError``.
    master는 ``core.scoring.select_master``(좌표 → updated_at → source 우선순위)로
    결정한다. commit은 호출자 책임.
    """
    row = (await session.execute(text(_SELECT_REVIEW_SQL), {"review_id": review_id})).one_or_none()
    if row is None:
        raise MergeNotFoundError(f"review_id 없음 — {review_id!r}")
    if row.status != "pending":
        raise MergeConflictError(f"이미 검토된 후보(status={row.status!r}) — {review_id!r}")

    cand_a = await _master_candidate(session, row.feature_id_a)
    cand_b = await _master_candidate(session, row.feature_id_b)
    master_id, loser_id = select_master(cand_a, cand_b)

    score: float | None = float(row.total_score) if row.total_score is not None else None
    return await apply_feature_merge(
        session,
        master_id=master_id,
        loser_id=loser_id,
        score=score,
        review_id=review_id,
        merged_by=merged_by,
        reason=reason,
    )
