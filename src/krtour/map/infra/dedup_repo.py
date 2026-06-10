"""``krtour.map.infra.dedup_repo`` — dedup 후보 검토 큐 적재 raw SQL repository.

``core.dedup.find_dedup_candidates``가 만든 ``DedupCandidate``(cross-provider
중복 후보)를 ``ops.dedup_review_queue``에 upsert한다 (ADR-016, SPRINT-3 §2.5).
``infra/feature_repo.py``와 같은 설계 — raw SQL ``text()``(ADR-004), commit은
호출자 책임, idempotent upsert.

설계 원칙
---------
- **raw SQL ``text()``만** (ADR-004) — ``_SQL`` 상수로 모아 EXPLAIN 검증 친화.
- **commit은 호출자 책임** — transaction 경계는 오케스트레이션(client)이 잡는다.
- **점수 0~100 변환** — core.scoring 점수는 0.0~1.0, 큐 컬럼은 ``NUMERIC(5,2)``
  0~100 (``ck_dedup_scores``). ``round(score * 100, 2)``로 변환.
- **순서 독립 pair** — ``feature_id_a < feature_id_b``로 canonicalize해 ``(a,b)``와
  ``(b,a)``가 같은 큐 행으로 수렴한다. self-pair는 큐에 넣지 않는다.
- **재스캔 안전 (검토 보존)** — canonical ``(feature_id_a, feature_id_b)`` 충돌 시
  ``status='pending'`` 행만 점수/제안 갱신. 운영자가 이미 accepted/rejected/
  merged/ignored한 행은 건드리지 않는다 (``DO UPDATE ... WHERE status='pending'``).
- **FK 선결** — ``feature_id_a/b``는 ``feature.features`` FK(CASCADE)라, 두 feature가
  먼저 적재돼 있어야 한다 (오케스트레이션: features 적재 → dedup 후보 적재).

ADR 참조
--------
- ADR-002 — async-only
- ADR-004 — ORM 매핑만, 쿼리는 raw SQL ``text()``
- ADR-016 — Record Linkage 점수 + ``ops.dedup_review_queue``
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

from sqlalchemy import text

if TYPE_CHECKING:
    from collections.abc import Iterable

    from sqlalchemy.ext.asyncio import AsyncSession

    from krtour.map.core.dedup import DedupCandidate

__all__ = [
    "DedupQueueResult",
    "enqueue_dedup_candidate",
    "enqueue_dedup_candidates",
    "pending_dedup_reviews",
]


# ─── SQL 상수 (EXPLAIN 검증 대상) ───────────────────────────────────────────

# status 기본 'pending'. 충돌 시 pending 행만 점수/제안 갱신 (검토 완료 행 보존).
# RETURNING (xmax = 0): INSERT면 true(신규), DO UPDATE면 false(갱신).
# WHERE로 update가 스킵되면 RETURNING row 자체가 없음 → skipped (이미 검토됨).
_UPSERT_DEDUP_SQL: Final[str] = """
INSERT INTO ops.dedup_review_queue (
    feature_id_a, feature_id_b,
    total_score, name_score, spatial_score, category_score,
    status, decision_reason
) VALUES (
    :feature_id_a, :feature_id_b,
    :total_score, :name_score, :spatial_score, :category_score,
    'pending', :decision_reason
)
ON CONFLICT (feature_id_a, feature_id_b) DO UPDATE SET
    total_score = EXCLUDED.total_score,
    name_score = EXCLUDED.name_score,
    spatial_score = EXCLUDED.spatial_score,
    category_score = EXCLUDED.category_score,
    decision_reason = EXCLUDED.decision_reason
WHERE ops.dedup_review_queue.status = 'pending'
RETURNING (xmax = 0) AS inserted
"""

# pending 후보 조회 — idx_dedup_status_score (status, total_score DESC) 사용.
_PENDING_DEDUP_SQL: Final[str] = """
SELECT
    review_id, feature_id_a, feature_id_b,
    total_score, name_score, spatial_score, category_score,
    status, decision_reason, created_at
FROM ops.dedup_review_queue
WHERE status = 'pending'
ORDER BY total_score DESC, review_id
LIMIT :limit
"""

# 0~100 NUMERIC(5,2) score 컬럼 — 조회 시 Decimal → float 변환 (JSON 친화).
_SCORE_COLUMNS: Final[tuple[str, ...]] = (
    "total_score",
    "name_score",
    "spatial_score",
    "category_score",
)


@dataclass(frozen=True)
class DedupQueueResult:
    """``enqueue_dedup_candidates`` 적재 결과 카운트.

    - ``candidates_total`` — 입력 후보 수.
    - ``inserted`` — 신규 큐 등록.
    - ``updated`` — 기존 pending 행 점수/제안 갱신 (재스캔).
    - ``skipped`` — 이미 검토된 행(status != pending) → 보존 (점수 갱신 안 함).
    """

    candidates_total: int = 0
    inserted: int = 0
    updated: int = 0
    skipped: int = 0


def _canonical_pair(feature_id_a: str, feature_id_b: str) -> tuple[str, str] | None:
    """검토 큐 저장용 feature pair를 순서 독립 key로 정규화한다."""
    if feature_id_a == feature_id_b:
        return None
    return (
        (feature_id_a, feature_id_b)
        if feature_id_a < feature_id_b
        else (feature_id_b, feature_id_a)
    )


def _candidate_params(candidate: DedupCandidate) -> dict[str, Any] | None:
    """``DedupCandidate`` → ``_UPSERT_DEDUP_SQL`` bind params.

    core.scoring 점수(0.0~1.0)를 큐 컬럼(0~100 NUMERIC)으로 ``×100`` 변환.
    ``decision_reason``에는 알고리즘 제안(auto_merge/manual_review)을 보관.
    """
    pair = _canonical_pair(candidate.feature_id_a, candidate.feature_id_b)
    if pair is None:
        return None
    feature_id_a, feature_id_b = pair
    return {
        "feature_id_a": feature_id_a,
        "feature_id_b": feature_id_b,
        "total_score": round(candidate.score * 100, 2),
        "name_score": round(candidate.name_score * 100, 2),
        "spatial_score": round(candidate.spatial_score * 100, 2),
        "category_score": round(candidate.category_score * 100, 2),
        "decision_reason": candidate.decision,
    }


async def enqueue_dedup_candidate(
    session: AsyncSession, candidate: DedupCandidate
) -> str:
    """``DedupCandidate`` 하나를 ``ops.dedup_review_queue``에 upsert.

    Returns
    -------
    str
        ``"inserted"`` (신규) / ``"updated"`` (pending 행 점수 갱신) /
        ``"skipped"`` (이미 검토 완료된 행이라 보존).
    """
    params = _candidate_params(candidate)
    if params is None:
        return "skipped"
    result = await session.execute(text(_UPSERT_DEDUP_SQL), params)
    row = result.first()
    if row is None:
        return "skipped"
    return "inserted" if bool(row.inserted) else "updated"


async def enqueue_dedup_candidates(
    session: AsyncSession, candidates: Iterable[DedupCandidate]
) -> DedupQueueResult:
    """``DedupCandidate`` 다수를 같은 session(transaction)에서 순차 upsert.

    commit은 호출자 책임. FK상 두 feature(``feature_id_a/b``)가 먼저 적재돼
    있어야 한다 (오케스트레이션이 features 적재 후 호출).
    """
    inserted = updated = skipped = total = 0
    for candidate in candidates:
        total += 1
        outcome = await enqueue_dedup_candidate(session, candidate)
        if outcome == "inserted":
            inserted += 1
        elif outcome == "updated":
            updated += 1
        else:
            skipped += 1
    return DedupQueueResult(
        candidates_total=total,
        inserted=inserted,
        updated=updated,
        skipped=skipped,
    )


async def pending_dedup_reviews(
    session: AsyncSession, *, limit: int = 100
) -> list[dict[str, Any]]:
    """검토 대기(``status='pending'``) 후보 list — total_score 내림차순.

    운영자 검토 UI / 디버깅용. 점수 컬럼은 ``float``로 변환해 반환 (JSON 친화).
    DTO 매핑은 상위(client/debug-ui) 책임 — 본 repo는 raw row만.
    """
    rows = (
        await session.execute(text(_PENDING_DEDUP_SQL), {"limit": limit})
    ).mappings().all()
    result: list[dict[str, Any]] = []
    for row in rows:
        data = dict(row)
        for col in _SCORE_COLUMNS:
            value = data.get(col)
            if value is not None:
                data[col] = float(value)
        result.append(data)
    return result
