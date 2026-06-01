"""``krtour.map.infra.merge_repo`` — dedup 수동 병합 1차 함수 (ADR-016).

``ops.dedup_review_queue``의 후보 1쌍(또는 명시 master/loser)을 병합한다:

1. loser의 ``provider_sync.source_links``를 master로 재지정(충돌 키는 master가 이미
   보유하므로 drop).
2. loser ``feature.features``를 soft-delete(``status='deleted'`` + ``deleted_at``,
   ADR-017 — place는 하드 삭제 안 함).
3. ``ops.feature_merge_history`` 1행 INSERT(ADR-016 이력 보존).
4. (``review_key`` 주어지면) ``ops.dedup_review_queue`` 행을 ``status='merged'``로
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
- ADR-039 — 중복 실행은 호출 측 advisory lock(``dedup-merge:{review_key}``)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from sqlalchemy import text

from krtour.map.core.scoring import MasterCandidate, select_master

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = [
    "MergeError",
    "MergeOutcome",
    "apply_feature_merge",
    "merge_from_review",
]


class MergeError(ValueError):
    """병합 불가(후보 미존재 / 이미 검토 완료 / feature 부재 등)."""


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
        JOIN provider_sync.source_records sr
          ON sr.source_record_key = sl.source_record_key
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
WHERE review_key = :review_key
"""

# loser source_link 중 master가 아직 안 가진 것만 master로 재지정.
# (rowcount 대신 RETURNING + fetchall — Result 타입 폭 회피, 코드베이스 컨벤션.)
_MOVE_LINKS_SQL: Final[str] = """
UPDATE provider_sync.source_links
SET feature_id = :master
WHERE feature_id = :loser
  AND source_record_key NOT IN (
      SELECT source_record_key
      FROM provider_sync.source_links
      WHERE feature_id = :master
  )
RETURNING source_record_key
"""

# master가 이미 보유한 충돌 link(재지정 후 loser에 남은 것) drop.
_DROP_LEFTOVER_LINKS_SQL: Final[str] = """
DELETE FROM provider_sync.source_links WHERE feature_id = :loser
RETURNING source_record_key
"""

# loser feature soft-delete (ADR-017).
_SOFT_DELETE_LOSER_SQL: Final[str] = """
UPDATE feature.features
SET status = 'deleted', deleted_at = now(), updated_at = now()
WHERE feature_id = :loser AND status <> 'deleted'
"""

_INSERT_HISTORY_SQL: Final[str] = """
INSERT INTO ops.feature_merge_history (
    master_feature_id, loser_feature_id, score, review_key, merged_by, reason
) VALUES (
    :master, :loser, :score, :review_key, :merged_by, :reason
)
RETURNING merge_id
"""

# 큐 행을 merged로 전이 — pending 행만(이미 검토된 행 보존).
_MARK_QUEUE_MERGED_SQL: Final[str] = """
UPDATE ops.dedup_review_queue
SET status = 'merged', reviewed_at = now(), reviewed_by = :merged_by,
    decision_reason = COALESCE(:reason, decision_reason)
WHERE review_key = :review_key AND status = 'pending'
RETURNING review_key
"""


async def _master_candidate(
    session: AsyncSession, feature_id: str
) -> MasterCandidate:
    row = (
        await session.execute(
            text(_SELECT_MASTER_INPUT_SQL), {"feature_id": feature_id}
        )
    ).one_or_none()
    if row is None:
        raise MergeError(f"feature 없음 — {feature_id!r}")
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
    review_key: str | None = None,
    merged_by: str | None = None,
    reason: str | None = None,
) -> MergeOutcome:
    """명시 master/loser로 병합 적용(재지정 → soft-delete → 이력 → 큐 전이).

    commit은 호출자 책임. ``master_id == loser_id``는 ``MergeError``.
    """
    if master_id == loser_id:
        raise MergeError(f"master와 loser가 같음 — {master_id!r}")

    moved = len(
        (
            await session.execute(
                text(_MOVE_LINKS_SQL), {"master": master_id, "loser": loser_id}
            )
        ).fetchall()
    )
    dropped = len(
        (
            await session.execute(
                text(_DROP_LEFTOVER_LINKS_SQL), {"loser": loser_id}
            )
        ).fetchall()
    )
    await session.execute(text(_SOFT_DELETE_LOSER_SQL), {"loser": loser_id})
    merge_id = (
        await session.execute(
            text(_INSERT_HISTORY_SQL),
            {
                "master": master_id,
                "loser": loser_id,
                "score": score,
                "review_key": review_key,
                "merged_by": merged_by,
                "reason": reason,
            },
        )
    ).scalar_one()
    queue_updated = False
    if review_key is not None:
        result = await session.execute(
            text(_MARK_QUEUE_MERGED_SQL),
            {"review_key": review_key, "merged_by": merged_by, "reason": reason},
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
    review_key: str,
    *,
    merged_by: str | None = None,
    reason: str | None = None,
) -> MergeOutcome:
    """검토 큐 후보(``review_key``) 1쌍을 master 자동 선정 후 병합한다.

    큐 행이 없거나 이미 검토(``status != 'pending'``)됐으면 ``MergeError``.
    master는 ``core.scoring.select_master``(좌표 → updated_at → source 우선순위)로
    결정한다. commit은 호출자 책임.
    """
    row = (
        await session.execute(
            text(_SELECT_REVIEW_SQL), {"review_key": review_key}
        )
    ).one_or_none()
    if row is None:
        raise MergeError(f"review_key 없음 — {review_key!r}")
    if row.status != "pending":
        raise MergeError(
            f"이미 검토된 후보(status={row.status!r}) — {review_key!r}"
        )

    cand_a = await _master_candidate(session, row.feature_id_a)
    cand_b = await _master_candidate(session, row.feature_id_b)
    master_id, loser_id = select_master(cand_a, cand_b)

    score: float | None = float(row.total_score) if row.total_score is not None else None
    return await apply_feature_merge(
        session,
        master_id=master_id,
        loser_id=loser_id,
        score=score,
        review_key=review_key,
        merged_by=merged_by,
        reason=reason,
    )
