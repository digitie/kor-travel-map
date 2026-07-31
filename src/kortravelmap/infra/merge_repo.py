"""``kortravelmap.infra.merge_repo`` — dedup 수동 병합 1차 함수 (ADR-016).

``ops.dedup_review_queue``의 후보 1쌍(또는 명시 master/loser)을 병합한다:

1. loser의 ``provider_sync.source_links``를 master로 재지정(충돌 키는 master가 이미
   보유하므로 drop).
2. loser의 ``feature.curation_items``와 전환기 legacy ``curated_features``를 master로
   재지정(같은 collection item 충돌은 master membership을 남긴다).
3. loser ``feature.features``를 soft-delete(``status='deleted'`` + ``deleted_at``,
   ADR-017 — place는 하드 삭제 안 함).
4. loser에 ``ops.feature_overrides`` status 가드를 남겨 provider 재적재 부활을 차단.
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
        SELECT sr.provider
        FROM provider_sync.source_links sl
        JOIN provider_sync.source_entities se
          ON se.source_entity_key = sl.source_entity_key
        JOIN provider_sync.source_records sr
          ON sr.source_entity_key = se.source_entity_key
         AND sr.source_record_key = se.current_source_record_key
        WHERE sl.feature_id = f.feature_id
        ORDER BY sl.is_primary_source DESC, sl.confidence DESC
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

_LOCK_FEATURES_SQL: Final[str] = """
SELECT feature_id
FROM feature.features
WHERE feature_id IN (:master, :loser)
ORDER BY feature_id
FOR UPDATE
"""

# Merge는 Feature lifecycle을 먼저 고정한 뒤 legacy→collection→item 순서로
# 잠근다. Legacy DML의 row→collection→item 순서와 import의 Feature→collection
# 순서를 모두 확장하므로 양방향 sync/import와 교착하지 않는다.
_LOCK_CURATION_LEGACY_PROJECTIONS_SQL: Final[str] = """
SELECT legacy.curated_feature_id
FROM feature.curated_features AS legacy
WHERE legacy.feature_id IN (:master, :loser)
  AND NOT legacy.metadata @> '{"merge_projection_detached": true}'::jsonb
ORDER BY legacy.curated_feature_id
FOR UPDATE OF legacy
"""

# Feature를 선잠근 merge와 legacy-backed writer는 legacy row를 거쳐
# collection(parent)→item(child) 순서로 들어간다. 영향 collection은 UUID
# 순서로 잠가 import/admin writer와의 교착을 막는다.
_LOCK_CURATION_COLLECTIONS_SQL: Final[str] = """
SELECT collection.collection_id
FROM feature.curation_collections AS collection
WHERE EXISTS (
    SELECT 1
    FROM feature.curation_items AS item
    WHERE item.collection_id = collection.collection_id
      AND item.feature_id IN (:master, :loser)
)
ORDER BY collection.collection_id
FOR UPDATE OF collection
"""

# 한 collection 안의 동일 official item을 Feature merge할 때 durable source/tombstone과
# operator override를 잃지 않는다. provider 파생 필드는 source-present row(동률이면 최신),
# operator 필드는 전용 operator_updated_at이 최신인 row가 이기며, 어느 한쪽이라도
# tombstone이면 tombstone이 최우선이다. master UUID를 survivor로 유지하고 loser
# duplicate는 물리 삭제하지 않는다. Feature link를 철회한 archive tombstone으로
# 남겨 import/link provenance의 append-only FK를 보존한다.
_MERGE_DUPLICATE_CURATION_ITEMS_SQL: Final[str] = """
WITH pairs AS MATERIALIZED (
    SELECT
        master_item.curation_item_id AS master_item_id,
        loser_item.curation_item_id AS loser_item_id,
        (
            (loser_item.source_present AND NOT master_item.source_present)
            OR (
                loser_item.source_present = master_item.source_present
                AND loser_item.source_updated_at > master_item.source_updated_at
            )
        ) AS loser_provider_wins,
        (
            loser_item.operator_updated_at IS NOT NULL
            AND (
                master_item.operator_updated_at IS NULL
                OR loser_item.operator_updated_at > master_item.operator_updated_at
            )
        ) AS loser_override_wins,
        master_item.archived_at IS NOT NULL
            OR loser_item.archived_at IS NOT NULL AS tombstone_wins,
        loser_item.archived_at IS NOT NULL
            AND (
                master_item.archived_at IS NULL
                OR COALESCE(
                    loser_item.operator_updated_at,
                    loser_item.archived_at
                ) > COALESCE(
                    master_item.operator_updated_at,
                    master_item.archived_at
                )
            ) AS loser_tombstone_wins
    FROM feature.curation_items AS loser_item
    JOIN feature.curation_items AS master_item
      ON master_item.feature_id = :master
     AND loser_item.collection_id = master_item.collection_id
     AND loser_item.external_item_id = master_item.external_item_id
    WHERE loser_item.feature_id = :loser
    FOR UPDATE OF master_item, loser_item
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
    FROM pairs
    JOIN feature.curation_items AS loser_item
      ON loser_item.curation_item_id = pairs.loser_item_id
    WHERE loser_item.accepted_link_decision_id IS NOT NULL
    RETURNING curation_item_id
), reconciled AS (
    UPDATE feature.curation_items AS survivor
    SET source_record_key = CASE
            WHEN pairs.loser_provider_wins THEN loser_item.source_record_key
            ELSE survivor.source_record_key
        END,
        place_name = CASE
            WHEN pairs.loser_provider_wins THEN loser_item.place_name
            ELSE survivor.place_name
        END,
        address_hint = CASE
            WHEN pairs.loser_provider_wins THEN loser_item.address_hint
            ELSE survivor.address_hint
        END,
        source_present = survivor.source_present OR loser_item.source_present,
        source_updated_at = CASE
            WHEN pairs.loser_provider_wins THEN loser_item.source_updated_at
            ELSE survivor.source_updated_at
        END,
        status = CASE
            WHEN pairs.tombstone_wins THEN 'archived'
            WHEN pairs.loser_override_wins THEN loser_item.status
            ELSE survivor.status
        END,
        sort_order = CASE
            WHEN pairs.loser_provider_wins THEN loser_item.sort_order
            ELSE survivor.sort_order
        END,
        item_title = CASE
            WHEN pairs.loser_provider_wins THEN loser_item.item_title
            ELSE survivor.item_title
        END,
        item_summary = CASE
            WHEN pairs.loser_provider_wins THEN loser_item.item_summary
            ELSE survivor.item_summary
        END,
        curation_relation = CASE
            WHEN pairs.tombstone_wins AND pairs.loser_tombstone_wins
            THEN loser_item.curation_relation
            WHEN pairs.tombstone_wins THEN survivor.curation_relation
            WHEN pairs.loser_override_wins THEN loser_item.curation_relation
            ELSE survivor.curation_relation
        END,
        reuse_policy = CASE
            WHEN pairs.tombstone_wins AND pairs.loser_tombstone_wins
            THEN loser_item.reuse_policy
            WHEN pairs.tombstone_wins THEN survivor.reuse_policy
            WHEN pairs.loser_override_wins THEN loser_item.reuse_policy
            ELSE survivor.reuse_policy
        END,
        metadata = CASE
            WHEN pairs.loser_provider_wins THEN loser_item.metadata
            ELSE survivor.metadata
        END,
        updated_by = CASE
            WHEN pairs.tombstone_wins AND pairs.loser_tombstone_wins
            THEN loser_item.updated_by
            WHEN pairs.tombstone_wins THEN survivor.updated_by
            WHEN pairs.loser_override_wins THEN loser_item.updated_by
            ELSE survivor.updated_by
        END,
        operator_updated_by = CASE
            WHEN pairs.tombstone_wins AND pairs.loser_tombstone_wins
            THEN loser_item.operator_updated_by
            WHEN pairs.tombstone_wins THEN survivor.operator_updated_by
            WHEN pairs.loser_override_wins THEN loser_item.operator_updated_by
            ELSE survivor.operator_updated_by
        END,
        operator_updated_at = CASE
            WHEN pairs.tombstone_wins AND pairs.loser_tombstone_wins
            THEN loser_item.operator_updated_at
            WHEN pairs.tombstone_wins THEN survivor.operator_updated_at
            WHEN pairs.loser_override_wins THEN loser_item.operator_updated_at
            ELSE survivor.operator_updated_at
        END,
        updated_at = now(),
        archived_at = CASE
            WHEN pairs.tombstone_wins
            THEN CASE
                WHEN pairs.loser_tombstone_wins THEN loser_item.archived_at
                ELSE survivor.archived_at
            END
            ELSE NULL
        END
    FROM pairs
    JOIN feature.curation_items AS loser_item
      ON loser_item.curation_item_id = pairs.loser_item_id
    WHERE survivor.curation_item_id = pairs.master_item_id
    RETURNING
        survivor.curation_item_id AS survivor_item_id,
        pairs.loser_item_id,
        pairs.loser_provider_wins
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
    FROM reconciled
    LEFT JOIN revocations
      ON revocations.curation_item_id = reconciled.loser_item_id
    WHERE loser_item.curation_item_id = reconciled.loser_item_id
    RETURNING loser_item.curation_item_id
)
SELECT
    reconciled.survivor_item_id,
    reconciled.loser_item_id,
    reconciled.loser_provider_wins
FROM reconciled
JOIN archived
  ON archived.curation_item_id = reconciled.loser_item_id
"""

_MOVE_CURATION_ITEMS_SQL: Final[str] = """
WITH candidates AS MATERIALIZED (
    SELECT
        item.curation_item_id,
        item.feature_id,
        item.accepted_link_decision_id,
        current_decision.decision_kind AS previous_decision_kind,
        current_decision.match_basis AS previous_match_basis,
        COALESCE(
            current_decision.decision_kind = 'accepted'
            AND current_decision.match_basis IN (
                'csv_explicit_feature_id',
                'admin_review',
                'forward_recovery'
            ),
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

_APPEND_DUPLICATE_MERGE_IMPORT_ROWS_SQL: Final[str] = """
WITH pair_input AS MATERIALIZED (
    SELECT *
    FROM jsonb_to_recordset(CAST(:pairs AS jsonb)) AS pair(
        row_number integer,
        survivor_item_id uuid,
        loser_item_id uuid
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
        loser.current_import_row_id AS loser_import_row_id,
        jsonb_build_object(
            'row_number', pair.row_number,
            'collection_key', collection.collection_key,
            'theme_slug', theme.theme_slug,
            'theme_name', theme.theme_name,
            'theme_group', theme.theme_group,
            'title', collection.title,
            'edition_key', collection.edition_key,
            'provider', source.provider,
            'dataset_key', source.dataset_key,
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
    JOIN feature.curation_items AS loser
      ON loser.curation_item_id = pair.loser_item_id
    JOIN feature.curation_collections AS collection
      ON collection.collection_id = survivor.collection_id
    JOIN feature.curated_themes AS theme
      ON theme.theme_id = collection.theme_id
    LEFT JOIN feature.curated_sources AS source
      ON source.source_id = collection.source_id
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
            'loser_import_row_id', snapshot.loser_import_row_id
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
      AND snapshot.previous_match_basis IN (
          'csv_explicit_feature_id',
          'admin_review',
          'forward_recovery'
      )
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
UPDATE feature.curated_features AS legacy
SET curation_status = CASE item.status
        WHEN 'included' THEN 'curated'
        ELSE item.status
    END,
    selection_origin = CASE
        WHEN item.operator_updated_at IS NOT NULL THEN 'admin'
        ELSE legacy.selection_origin
    END,
    selected_by = CASE
        WHEN item.status = 'included' THEN item.operator_updated_by
        ELSE legacy.selected_by
    END,
    selected_at = CASE
        WHEN item.status = 'included' THEN item.operator_updated_at
        ELSE legacy.selected_at
    END,
    rejected_by = CASE
        WHEN item.status = 'rejected' THEN item.operator_updated_by
        WHEN item.status IN ('included', 'candidate') THEN NULL
        ELSE legacy.rejected_by
    END,
    rejected_at = CASE
        WHEN item.status = 'rejected' THEN item.operator_updated_at
        WHEN item.status IN ('included', 'candidate') THEN NULL
        ELSE legacy.rejected_at
    END,
    rejection_reason = CASE
        WHEN item.status IN ('included', 'candidate') THEN NULL
        ELSE legacy.rejection_reason
    END,
    curation_relation = item.curation_relation,
    reuse_policy = item.reuse_policy,
    operator_updated_by = item.operator_updated_by,
    operator_updated_at = item.operator_updated_at,
    archived_at = item.archived_at,
    updated_at = clock_timestamp(),
    content_version = legacy.content_version + 1
FROM feature.curation_items AS item
WHERE item.feature_id = :master
  AND legacy.feature_id = :master
  AND legacy.archived_at IS NULL
  AND NOT legacy.metadata @> '{"merge_projection_detached": true}'::jsonb
  AND item.legacy_projection_id = legacy.curated_feature_id
  AND (
      legacy.curation_status,
      legacy.curation_relation,
      legacy.reuse_policy,
      legacy.operator_updated_by,
      legacy.operator_updated_at,
      legacy.archived_at
  ) IS DISTINCT FROM (
      CASE item.status
          WHEN 'included' THEN 'curated'
          ELSE item.status
      END,
      item.curation_relation,
      item.reuse_policy,
      item.operator_updated_by,
      item.operator_updated_at,
      item.archived_at
  )
RETURNING legacy.curated_feature_id
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

# UUID가 분리된 same-theme legacy conflict 또는 아직 이동하지 않은 loser UUID item과
# 같은 stored collection/external identity의 master canonical pair만 archive한다.
# Mutable slug/title로 collection key를 재계산하거나 MOVE 뒤 feature_id를 증거로 쓰지 않는다.
_ARCHIVE_CONFLICTING_LEGACY_CURATED_FEATURES_SQL: Final[str] = """
UPDATE feature.curated_features AS loser_curated
SET feature_id = :master,
    curation_status = 'archived',
    metadata = loser_curated.metadata || jsonb_build_object(
        'merge_projection_detached',
        true
    ),
    archived_at = now(),
    updated_at = now()
WHERE loser_curated.feature_id = :loser
  AND loser_curated.archived_at IS NULL
  AND (
      (
          NOT EXISTS (
              SELECT 1
              FROM feature.curation_items AS direct_item
              WHERE direct_item.legacy_projection_id =
                    loser_curated.curated_feature_id
                AND direct_item.archived_at IS NULL
          )
          AND EXISTS (
              SELECT 1
              FROM feature.curated_features AS master_curated
              WHERE master_curated.feature_id = :master
                AND master_curated.theme_id = loser_curated.theme_id
                AND master_curated.archived_at IS NULL
                AND NOT master_curated.metadata @>
                    '{"merge_projection_detached": true}'::jsonb
          )
      )
      OR EXISTS (
          SELECT 1
          FROM feature.curation_items AS loser_item
          JOIN feature.curation_items AS master_item
            ON master_item.collection_id = loser_item.collection_id
           AND master_item.external_item_id = loser_item.external_item_id
          WHERE master_item.feature_id = :master
            AND loser_item.legacy_projection_id =
                loser_curated.curated_feature_id
            AND master_item.curation_item_id <>
                loser_item.curation_item_id
      )
  )
RETURNING loser_curated.curated_feature_id
"""

# 충돌을 정리한 뒤 남은 active/archived legacy row도 master로 옮긴다. 이 UPDATE로
# 0045 trigger가 다시 실행되어도 NEW.feature_id가 master이므로 병합이 되돌아가지 않는다.
_MOVE_LEGACY_CURATED_FEATURES_SQL: Final[str] = """
UPDATE feature.curated_features
SET feature_id = :master, updated_at = now()
WHERE feature_id = :loser
RETURNING curated_feature_id
"""

# loser feature soft-delete (ADR-017).
_SOFT_DELETE_LOSER_SQL: Final[str] = """
WITH locked AS (
    SELECT feature_id, status AS previous_status
    FROM feature.features
    WHERE feature_id = :loser
    FOR UPDATE
),
updated AS (
    UPDATE feature.features AS f
    SET status = 'deleted', deleted_at = now(), updated_at = now()
    FROM locked
    WHERE f.feature_id = locked.feature_id
      AND locked.previous_status <> 'deleted'
    RETURNING f.feature_id, locked.previous_status
)
SELECT feature_id, previous_status
FROM updated
"""

_UPSERT_LOSER_STATUS_OVERRIDE_SQL: Final[str] = """
INSERT INTO ops.feature_overrides (
    feature_id, source_record_key, field_path,
    source_value, override_value, prevent_provider_reactivation,
    status, reason, created_by
) VALUES (
    :loser, NULL, 'status',
    to_jsonb(CAST(:source_value AS text)),
    to_jsonb('deleted'::text),
    true,
    'active', :reason, :merged_by
)
ON CONFLICT (feature_id, field_path) WHERE status = 'active'
DO UPDATE SET
    source_value = EXCLUDED.source_value,
    override_value = EXCLUDED.override_value,
    prevent_provider_reactivation = true,
    reason = EXCLUDED.reason,
    created_by = EXCLUDED.created_by,
    created_at = now()
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

    (
        await session.execute(
            text(_LOCK_FEATURES_SQL),
            {"master": master_id, "loser": loser_id},
        )
    ).fetchall()
    (
        await session.execute(
            text(_LOCK_CURATION_LEGACY_PROJECTIONS_SQL),
            {"master": master_id, "loser": loser_id},
        )
    ).fetchall()
    (
        await session.execute(
            text(_LOCK_CURATION_COLLECTIONS_SQL),
            {"master": master_id, "loser": loser_id},
        )
    ).fetchall()
    moved = len(
        (
            await session.execute(text(_MOVE_LINKS_SQL), {"master": master_id, "loser": loser_id})
        ).fetchall()
    )
    dropped = len(
        (await session.execute(text(_DROP_LEFTOVER_LINKS_SQL), {"loser": loser_id})).fetchall()
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
    provider_winner_pairs = [
        {
            "row_number": row_number,
            "survivor_item_id": str(row["survivor_item_id"]),
            "loser_item_id": str(row["loser_item_id"]),
        }
        for row_number, row in enumerate(
            (
                row
                for row in duplicate_rows
                if bool(row["loser_provider_wins"])
            ),
            start=1,
        )
    ]
    if provider_winner_pairs:
        batch_identity = {
            "schema_version": 1,
            "operation": "feature_merge_duplicate_source_winner",
            "master_feature_id": master_id,
            "loser_feature_id": loser_id,
            "review_id": review_id,
            "pairs": provider_winner_pairs,
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
                        "content_sha256": hashlib.sha256(
                            canonical_batch
                        ).hexdigest(),
                        "row_count": len(provider_winner_pairs),
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
                    provider_winner_pairs,
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
        text(_MOVE_LEGACY_CURATED_FEATURES_SQL),
        {"master": master_id, "loser": loser_id},
    )
    soft_deleted = (
        (await session.execute(text(_SOFT_DELETE_LOSER_SQL), {"loser": loser_id}))
        .mappings()
        .first()
    )
    if soft_deleted is not None:
        await session.execute(
            text(_UPSERT_LOSER_STATUS_OVERRIDE_SQL),
            {
                "loser": loser_id,
                "source_value": soft_deleted["previous_status"],
                "reason": reason,
                "merged_by": merged_by,
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
