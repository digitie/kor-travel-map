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

# 한 collection 안의 동일 official item을 Feature merge할 때 durable source/tombstone과
# operator override를 잃지 않는다. provider 파생 필드는 source-present row(동률이면 최신),
# operator 필드는 최신 updated_at row가 이기며, 어느 한쪽이라도 tombstone이면 tombstone이
# 최우선이다. master UUID를 survivor로 유지한 뒤 loser duplicate만 제거한다.
_MERGE_DUPLICATE_CURATION_ITEMS_SQL: Final[str] = """
WITH pairs AS MATERIALIZED (
    SELECT
        master_item.curation_item_id AS master_item_id,
        loser_item.curation_item_id AS loser_item_id,
        (
            (loser_item.source_present AND NOT master_item.source_present)
            OR (
                loser_item.source_present = master_item.source_present
                AND loser_item.updated_at > master_item.updated_at
            )
        ) AS loser_provider_wins,
        loser_item.updated_at > master_item.updated_at AS loser_override_wins,
        master_item.archived_at IS NOT NULL
            OR loser_item.archived_at IS NOT NULL AS tombstone_wins
    FROM feature.curation_items AS loser_item
    JOIN feature.curation_items AS master_item
      ON master_item.feature_id = :master
     AND loser_item.collection_id = master_item.collection_id
     AND loser_item.external_item_id = master_item.external_item_id
    WHERE loser_item.feature_id = :loser
    FOR UPDATE OF master_item, loser_item
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
            WHEN pairs.loser_override_wins THEN loser_item.curation_relation
            ELSE survivor.curation_relation
        END,
        reuse_policy = CASE
            WHEN pairs.loser_override_wins THEN loser_item.reuse_policy
            ELSE survivor.reuse_policy
        END,
        metadata = CASE
            WHEN pairs.loser_provider_wins THEN loser_item.metadata
            ELSE survivor.metadata
        END,
        updated_by = CASE
            WHEN pairs.loser_override_wins THEN loser_item.updated_by
            ELSE survivor.updated_by
        END,
        updated_at = now(),
        archived_at = CASE
            WHEN pairs.tombstone_wins
            THEN GREATEST(survivor.archived_at, loser_item.archived_at)
            ELSE NULL
        END
    FROM pairs
    JOIN feature.curation_items AS loser_item
      ON loser_item.curation_item_id = pairs.loser_item_id
    WHERE survivor.curation_item_id = pairs.master_item_id
    RETURNING pairs.loser_item_id
)
DELETE FROM feature.curation_items AS loser_item
USING reconciled
WHERE loser_item.curation_item_id = reconciled.loser_item_id
RETURNING loser_item.curation_item_id
"""

_MOVE_CURATION_ITEMS_SQL: Final[str] = """
UPDATE feature.curation_items
SET feature_id = :master, updated_at = now()
WHERE feature_id = :loser
RETURNING curation_item_id
"""

# 0045 전환 trigger는 legacy curated_feature UUID와 같은 curation_item UUID를 다시
# 만든다. master에도 같은 theme의 active legacy row가 있으면 loser legacy row를
# active 상태로 옮길 수 없으므로, 먼저 해당 item의 UUID를 분리해 richer membership을
# 보존한 뒤 legacy row만 archive한다.
_DETACH_CONFLICTING_LEGACY_CURATION_ITEMS_SQL: Final[str] = """
UPDATE feature.curation_items AS item
SET curation_item_id = x_extension.gen_random_uuid(), updated_at = now()
FROM feature.curated_features AS loser_curated
WHERE loser_curated.curated_feature_id = item.curation_item_id
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

# UUID가 분리됐거나 duplicate curation item이 이미 drop된 active legacy row는
# partial unique(theme_id, feature_id)를 피하기 위해 archive한다. trigger가 만드는
# archived mirror와 UUID를 분리한 active item이 함께 남아 richer 계약을 잃지 않는다.
_ARCHIVE_CONFLICTING_LEGACY_CURATED_FEATURES_SQL: Final[str] = """
UPDATE feature.curated_features AS loser_curated
SET feature_id = :master,
    curation_status = 'archived',
    archived_at = now(),
    updated_at = now()
WHERE loser_curated.feature_id = :loser
  AND loser_curated.archived_at IS NULL
  AND NOT EXISTS (
      SELECT 1
      FROM feature.curation_items AS item
      WHERE item.curation_item_id = loser_curated.curated_feature_id
        AND item.archived_at IS NULL
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

    moved = len(
        (
            await session.execute(text(_MOVE_LINKS_SQL), {"master": master_id, "loser": loser_id})
        ).fetchall()
    )
    dropped = len(
        (await session.execute(text(_DROP_LEFTOVER_LINKS_SQL), {"loser": loser_id})).fetchall()
    )
    await session.execute(
        text(_MERGE_DUPLICATE_CURATION_ITEMS_SQL),
        {"master": master_id, "loser": loser_id},
    )
    await session.execute(
        text(_MOVE_CURATION_ITEMS_SQL),
        {"master": master_id, "loser": loser_id},
    )
    await session.execute(
        text(_DETACH_CONFLICTING_LEGACY_CURATION_ITEMS_SQL),
        {"master": master_id, "loser": loser_id},
    )
    await session.execute(
        text(_ARCHIVE_CONFLICTING_LEGACY_CURATED_FEATURES_SQL),
        {"master": master_id, "loser": loser_id},
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
