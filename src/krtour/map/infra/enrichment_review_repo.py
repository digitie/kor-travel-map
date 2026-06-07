"""``krtour.map.infra.enrichment_review_repo`` — 축제 enrichment 검토 큐 repository.

visitkorea(2차)↔datagokr(1차) 축제 이름 유사도가 자동 확정 임계 미만·검토 하한 이상인
모호한 매칭(``providers/visitkorea.festival_to_review_candidates``)을
``ops.enrichment_review_queue``에 upsert하고(``enqueue_review_candidates``), 운영자 결정
(accept/reject/ignore)을 반영한다(``decide_enrichment_review``). accept는 보관된
``SourceRecord``를 복원해 ENRICHMENT ``SourceLink``와 함께 적재한다.

설계 원칙(``dedup_repo``와 동일)
--------------------------------
- **raw SQL ``text()``만** (ADR-004) — ``_SQL`` 상수로 모음.
- **commit은 호출자 책임** — transaction 경계는 오케스트레이션(client/admin)이 잡는다.
- **점수 0~100 변환** — 이름 유사도 0.0~1.0 → ``NUMERIC(5,2)`` 0~100.
- **재스캔 안전(검토 보존)** — ``(target_feature_id, source_provider, source_dataset_key,
  source_entity_id)`` 충돌 시 ``status='pending'`` 행만 점수/이름 갱신. 검토 완료 행 보존.
- **의존 방향(ADR-020)** — infra는 providers를 import하지 않는다. enqueue 입력은
  provider 타입(``FestivalReviewCandidate``)이 아니라 generic ``EnrichmentReviewInput``
  (``SourceRecord`` dto만 사용)이며, client가 매핑한다(``load_source_record_links`` 패턴).

ADR 참조: ADR-002 / ADR-004 / ADR-016 / ADR-019 / ADR-042.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

from sqlalchemy import text

from krtour.map.dto import SourceLink, SourceRecord, SourceRole
from krtour.map.infra.feature_repo import (
    EnrichmentLoadResult,
    load_source_record_links,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = [
    "EnrichmentReviewInput",
    "EnrichmentQueueResult",
    "EnrichmentDecisionResult",
    "enqueue_review_candidate",
    "enqueue_review_candidates",
    "pending_enrichment_reviews",
    "decide_enrichment_review",
    "ENRICHMENT_REVIEW_DECISIONS",
]

ENRICHMENT_REVIEW_DECISIONS: Final[frozenset[str]] = frozenset(
    {"accepted", "rejected", "ignored"}
)
"""운영자가 내릴 수 있는 결정(accept는 enrichment 적재 동반)."""

_MANUAL_MATCH_METHOD: Final[str] = "manual_review"
"""accept 시 ENRICHMENT ``SourceLink.match_method`` — 사람 확정 provenance."""


# ─── SQL 상수 ───────────────────────────────────────────────────────────────

_UPSERT_SQL: Final[str] = """
INSERT INTO ops.enrichment_review_queue (
    target_feature_id, source_provider, source_dataset_key, source_entity_id,
    source_name, target_name, name_score, source_record, status
) VALUES (
    :target_feature_id, :source_provider, :source_dataset_key, :source_entity_id,
    :source_name, :target_name, :name_score, CAST(:source_record AS jsonb), 'pending'
)
ON CONFLICT (target_feature_id, source_provider, source_dataset_key, source_entity_id)
DO UPDATE SET
    source_name = EXCLUDED.source_name,
    target_name = EXCLUDED.target_name,
    name_score = EXCLUDED.name_score,
    source_record = EXCLUDED.source_record
WHERE ops.enrichment_review_queue.status = 'pending'
RETURNING (xmax = 0) AS inserted
"""

_PENDING_SQL: Final[str] = """
SELECT
    review_key, target_feature_id, source_provider, source_dataset_key,
    source_entity_id, source_name, target_name, name_score, status,
    decision_reason, created_at
FROM ops.enrichment_review_queue
WHERE status = 'pending'
ORDER BY name_score DESC, review_key
LIMIT :limit
"""

# ``FOR UPDATE`` — 동시 결정 race 방지(#297). 같은 review_key를 두 운영자가 동시에
# 결정하면 한 transaction이 행 잠금을 먼저 잡고, 다른 쪽은 commit까지 대기했다가
# 갱신된 status(이미 non-pending)를 보고 side-effect 없이 changed=False를 반환한다.
# 이렇게 "상태 점유 → side-effect" 순서를 보장해 accepted link가 새는 것을 막는다.
_SELECT_ROW_SQL: Final[str] = """
SELECT
    review_key, target_feature_id, source_record, name_score, status
FROM ops.enrichment_review_queue
WHERE review_key = :review_key
FOR UPDATE
"""

_MARK_DECISION_SQL: Final[str] = """
UPDATE ops.enrichment_review_queue
SET status = :status,
    decision_reason = :decision_reason,
    reviewed_by = :reviewed_by,
    reviewed_at = now()
WHERE review_key = :review_key AND status = 'pending'
RETURNING review_key
"""

_SCORE_COLUMNS: Final[tuple[str, ...]] = ("name_score",)


@dataclass(frozen=True)
class EnrichmentReviewInput:
    """enqueue 입력 — provider 타입 비의존(ADR-020). client가 매핑한다.

    ``source_record``는 accept 시 적재할 visitkorea ``SourceRecord`` dto. provider/
    dataset_key/source_entity_id는 여기서 파생하므로 중복 보관하지 않는다.
    """

    target_feature_id: str
    target_name: str
    source_name: str
    name_score: float
    """이름 유사도 0.0~1.0 (큐에는 ×100 NUMERIC으로 저장)."""

    source_record: SourceRecord


@dataclass(frozen=True)
class EnrichmentQueueResult:
    """``enqueue_review_candidates`` 적재 결과 카운트(``DedupQueueResult`` 미러)."""

    candidates_total: int = 0
    inserted: int = 0
    updated: int = 0
    skipped: int = 0


@dataclass(frozen=True)
class EnrichmentDecisionResult:
    """``decide_enrichment_review`` 결과.

    - ``changed`` — pending 행을 실제로 갱신했는지(False면 이미 검토됨/없음).
    - ``applied`` — accept로 enrichment를 적재했는지.
    - ``load`` — accept 시 enrichment 적재 카운트(없으면 None).
    """

    review_key: str
    decision: str
    changed: bool
    applied: bool
    load: EnrichmentLoadResult | None = None


def _input_params(candidate: EnrichmentReviewInput) -> dict[str, Any]:
    record = candidate.source_record
    return {
        "target_feature_id": candidate.target_feature_id,
        "source_provider": record.provider,
        "source_dataset_key": record.dataset_key,
        "source_entity_id": record.source_entity_id,
        "source_name": candidate.source_name,
        "target_name": candidate.target_name,
        "name_score": round(candidate.name_score * 100, 2),
        "source_record": record.model_dump_json(),
    }


async def enqueue_review_candidate(
    session: AsyncSession, candidate: EnrichmentReviewInput
) -> str:
    """검토 후보 1건을 ``ops.enrichment_review_queue``에 upsert.

    Returns ``"inserted"`` / ``"updated"`` / ``"skipped"``(이미 검토된 행 보존).
    """
    result = await session.execute(text(_UPSERT_SQL), _input_params(candidate))
    row = result.first()
    if row is None:
        return "skipped"
    return "inserted" if bool(row.inserted) else "updated"


async def enqueue_review_candidates(
    session: AsyncSession, candidates: Iterable[EnrichmentReviewInput]
) -> EnrichmentQueueResult:
    """검토 후보 다수를 같은 transaction에서 순차 upsert. commit은 호출자 책임.

    FK상 ``target_feature_id``(1차 festival)가 먼저 적재돼 있어야 한다.
    """
    inserted = updated = skipped = total = 0
    for candidate in candidates:
        total += 1
        outcome = await enqueue_review_candidate(session, candidate)
        if outcome == "inserted":
            inserted += 1
        elif outcome == "updated":
            updated += 1
        else:
            skipped += 1
    return EnrichmentQueueResult(
        candidates_total=total,
        inserted=inserted,
        updated=updated,
        skipped=skipped,
    )


async def pending_enrichment_reviews(
    session: AsyncSession, *, limit: int = 100
) -> list[dict[str, Any]]:
    """검토 대기(``status='pending'``) 후보 list — name_score 내림차순.

    점수 컬럼은 ``float``로 변환(JSON 친화). DTO 매핑은 상위(client/admin) 책임.
    """
    rows = (
        await session.execute(text(_PENDING_SQL), {"limit": limit})
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


def _rebuild_enrichment(
    target_feature_id: str,
    source_record_json: dict[str, Any] | str,
    name_score: float,
) -> tuple[SourceRecord, SourceLink]:
    """보관된 ``SourceRecord`` JSON → (record, ENRICHMENT link) 복원(accept 적용용).

    JSONB 컬럼은 드라이버(asyncpg)에 따라 ``str`` 또는 ``dict``로 올 수 있어 양쪽을
    처리한다(raw ``text()`` 쿼리는 SQLAlchemy JSON result processor를 안 거침).
    """
    record = (
        SourceRecord.model_validate_json(source_record_json)
        if isinstance(source_record_json, str)
        else SourceRecord.model_validate(source_record_json)
    )
    link = SourceLink(
        feature_id=target_feature_id,
        source_record_key=record.source_record_key,
        source_role=SourceRole.ENRICHMENT,
        match_method=_MANUAL_MATCH_METHOD,
        confidence=round(name_score),
        is_primary_source=False,
    )
    return record, link


async def decide_enrichment_review(
    session: AsyncSession,
    review_key: str,
    decision: str,
    *,
    reviewed_by: str | None = None,
    reason: str | None = None,
) -> EnrichmentDecisionResult:
    """검토 행에 운영자 결정을 반영. accept는 enrichment를 적재한다.

    pending 행에 한해 ``status``를 갱신한다(이미 검토된 행은 ``changed=False``).
    ``decision='accepted'``이면 보관된 ``SourceRecord``를 복원해 ENRICHMENT link과
    함께 적재한 뒤 상태를 갱신한다. commit은 호출자 책임.

    동시성(#297): 행을 ``SELECT ... FOR UPDATE``로 잠가 같은 review_key의 동시 결정을
    직렬화한다. 잠금을 먼저 잡은 transaction이 끝날 때까지 다른 결정은 대기하므로,
    "상태 점유 → side-effect" 순서가 보장되어 changed=False면 link도 적재되지 않는다
    (accepted link 누수 방지). accepted link 적재가 실패하면 같은 transaction이라
    상태 변경도 함께 rollback된다.

    Raises
    ------
    ValueError
        ``decision``이 ``ENRICHMENT_REVIEW_DECISIONS`` 밖일 때.
    """
    if decision not in ENRICHMENT_REVIEW_DECISIONS:
        raise ValueError(
            f"decision은 {sorted(ENRICHMENT_REVIEW_DECISIONS)} 중 하나여야 함: "
            f"{decision!r}"
        )

    row = (
        await session.execute(text(_SELECT_ROW_SQL), {"review_key": review_key})
    ).mappings().first()
    if row is None or row["status"] != "pending":
        return EnrichmentDecisionResult(
            review_key=review_key, decision=decision, changed=False, applied=False
        )

    load: EnrichmentLoadResult | None = None
    if decision == "accepted":
        # 보관된 점수(0~100)를 0~100 confidence로 그대로 사용.
        record, link = _rebuild_enrichment(
            row["target_feature_id"], row["source_record"], float(row["name_score"])
        )
        load = await load_source_record_links(session, [(record, link)])

    marked = (
        await session.execute(
            text(_MARK_DECISION_SQL),
            {
                "review_key": review_key,
                "status": decision,
                "decision_reason": reason,
                "reviewed_by": reviewed_by,
            },
        )
    ).first()
    changed = marked is not None
    return EnrichmentDecisionResult(
        review_key=review_key,
        decision=decision,
        changed=changed,
        applied=changed and decision == "accepted",
        load=load if changed else None,
    )
