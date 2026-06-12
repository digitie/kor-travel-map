"""``test_dedup_repo`` — ops.dedup_review_queue 적재 (ADR-016, SPRINT-3 §2.5).

``infra/dedup_repo.py``의 ``enqueue_dedup_candidate(s)`` / ``pending_dedup_reviews``를
실 PostGIS(migrated_session, alembic head)에서 검증한다:

- 신규 후보 insert + 점수 0~100 변환(×100) + status='pending' + decision_reason.
- 재스캔 시 pending 행 점수 갱신(updated), 검토 완료(accepted) 행 보존(skipped).
- reversed pair도 같은 canonical queue row로 수렴하며, self-pair는 skipped.
- ``pending_dedup_reviews`` total_score 내림차순 + float 변환.
- FK — 존재하지 않는 feature 참조 시 IntegrityError (CASCADE FK 강제).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from kortravelmap.core.dedup import DedupCandidate
from kortravelmap.infra.dedup_repo import (
    DedupQueueResult,
    enqueue_dedup_candidate,
    enqueue_dedup_candidates,
    pending_dedup_reviews,
)
from kortravelmap.infra.models import FeatureRow

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration

_TEMPLE_CAT = "01070100"  # TOURISM_HERITAGE_TEMPLE


def _temple(feature_id: str, name: str = "불국사") -> FeatureRow:
    """temple place feature (dedup 후보 FK 대상)."""
    from geoalchemy2 import WKTElement

    return FeatureRow(
        feature_id=feature_id,
        kind="place",
        name=name,
        category=_TEMPLE_CAT,
        coord=WKTElement("POINT(129.3320 35.7900)", srid=4326),
        detail={"summary": "temple"},
    )


def _candidate(
    fa: str,
    fb: str,
    *,
    score: float = 0.74,
    decision: str = "manual_review",
    name_score: float = 0.90,
    spatial_score: float = 0.60,
    category_score: float = 1.0,
) -> DedupCandidate:
    return DedupCandidate(
        feature_id_a=fa,
        feature_id_b=fb,
        name_a="불국사",
        name_b="불국사",
        score=score,
        decision=decision,
        name_score=name_score,
        spatial_score=spatial_score,
        category_score=category_score,
    )


async def _score_row(session: AsyncSession, fa: str, fb: str) -> object:
    return (
        await session.execute(
            text(
                "SELECT total_score, name_score, spatial_score, category_score, "
                "status, decision_reason FROM ops.dedup_review_queue "
                "WHERE feature_id_a = :a AND feature_id_b = :b"
            ),
            {"a": fa, "b": fb},
        )
    ).one()


async def test_enqueue_inserts_and_persists(migrated_session: AsyncSession) -> None:
    migrated_session.add(_temple("f_knps_1"))
    migrated_session.add(_temple("f_krh_1"))
    await migrated_session.flush()

    result = await enqueue_dedup_candidates(
        migrated_session,
        [_candidate("f_knps_1", "f_krh_1")],
    )
    assert result == DedupQueueResult(
        candidates_total=1, inserted=1, updated=0, skipped=0
    )

    row = await _score_row(migrated_session, "f_knps_1", "f_krh_1")
    # 0.0~1.0 점수 → 0~100 NUMERIC(5,2) 변환 확인.
    assert float(row.total_score) == 74.0
    assert float(row.name_score) == 90.0
    assert float(row.spatial_score) == 60.0
    assert float(row.category_score) == 100.0
    assert row.status == "pending"
    assert row.decision_reason == "manual_review"


async def test_reenqueue_updates_pending_scores(
    migrated_session: AsyncSession,
) -> None:
    migrated_session.add(_temple("f_knps_1"))
    migrated_session.add(_temple("f_krh_1"))
    await migrated_session.flush()

    await enqueue_dedup_candidate(migrated_session, _candidate("f_knps_1", "f_krh_1"))
    # 재스캔 — 점수가 달라진 같은 쌍.
    result = await enqueue_dedup_candidates(
        migrated_session,
        [_candidate("f_knps_1", "f_krh_1", score=0.80, name_score=0.95)],
    )
    assert result.updated == 1
    assert result.inserted == 0
    assert result.skipped == 0

    row = await _score_row(migrated_session, "f_knps_1", "f_krh_1")
    assert float(row.total_score) == 80.0  # 갱신됨
    assert float(row.name_score) == 95.0


async def test_reversed_pair_reuses_canonical_queue_row(
    migrated_session: AsyncSession,
) -> None:
    migrated_session.add(_temple("f_a"))
    migrated_session.add(_temple("f_b"))
    await migrated_session.flush()

    first = await enqueue_dedup_candidate(migrated_session, _candidate("f_b", "f_a"))
    second = await enqueue_dedup_candidate(
        migrated_session,
        _candidate("f_a", "f_b", score=0.83, name_score=0.97),
    )

    assert first == "inserted"
    assert second == "updated"
    row = await _score_row(migrated_session, "f_a", "f_b")
    assert float(row.total_score) == 83.0
    assert float(row.name_score) == 97.0
    count = (
        await migrated_session.execute(
            text(
                "SELECT count(*) FROM ops.dedup_review_queue "
                "WHERE feature_id_a IN ('f_a','f_b') "
                "AND feature_id_b IN ('f_a','f_b')"
            )
        )
    ).scalar_one()
    assert count == 1


async def test_self_pair_is_skipped(
    migrated_session: AsyncSession,
) -> None:
    migrated_session.add(_temple("f_same"))
    await migrated_session.flush()

    result = await enqueue_dedup_candidate(
        migrated_session,
        _candidate("f_same", "f_same"),
    )

    assert result == "skipped"
    count = (
        await migrated_session.execute(
            text("SELECT count(*) FROM ops.dedup_review_queue")
        )
    ).scalar_one()
    assert count == 0


async def test_db_rejects_non_canonical_pair_insert(
    migrated_session: AsyncSession,
) -> None:
    migrated_session.add(_temple("f_a"))
    migrated_session.add(_temple("f_b"))
    await migrated_session.flush()

    with pytest.raises(IntegrityError):  # noqa: PT012 — savepoint 격리 필요
        async with migrated_session.begin_nested():
            await migrated_session.execute(
                text(
                    "INSERT INTO ops.dedup_review_queue "
                    "(feature_id_a, feature_id_b, total_score, name_score, "
                    "spatial_score, category_score, status) "
                    "VALUES ('f_b', 'f_a', 70, 90, 60, 100, 'pending')"
                )
            )


async def test_reviewed_row_preserved_on_reenqueue(
    migrated_session: AsyncSession,
) -> None:
    migrated_session.add(_temple("f_knps_1"))
    migrated_session.add(_temple("f_krh_1"))
    await migrated_session.flush()

    await enqueue_dedup_candidate(migrated_session, _candidate("f_knps_1", "f_krh_1"))
    # 운영자가 검토 완료 (accepted).
    await migrated_session.execute(
        text(
            "UPDATE ops.dedup_review_queue SET status = 'accepted' "
            "WHERE feature_id_a = 'f_knps_1' AND feature_id_b = 'f_krh_1'"
        )
    )

    # 재스캔 — 더 높은 점수로 들어와도 검토 완료 행은 보존.
    result = await enqueue_dedup_candidates(
        migrated_session,
        [_candidate("f_knps_1", "f_krh_1", score=0.95, decision="auto_merge")],
    )
    assert result.skipped == 1
    assert result.updated == 0
    assert result.inserted == 0

    row = await _score_row(migrated_session, "f_knps_1", "f_krh_1")
    assert row.status == "accepted"  # 보존
    assert float(row.total_score) == 74.0  # 점수 갱신 안 됨
    assert row.decision_reason == "manual_review"  # 갱신 안 됨


async def test_pending_dedup_reviews_sorted_desc(
    migrated_session: AsyncSession,
) -> None:
    for fid in ("a1", "b1", "a2", "b2"):
        migrated_session.add(_temple(fid))
    await migrated_session.flush()

    await enqueue_dedup_candidates(
        migrated_session,
        [
            _candidate("a1", "b1", score=0.70),
            _candidate("a2", "b2", score=0.82),
        ],
    )
    rows = await pending_dedup_reviews(migrated_session, limit=10)
    assert len(rows) == 2
    # total_score 내림차순.
    assert rows[0]["total_score"] == 82.0
    assert rows[1]["total_score"] == 70.0
    # 점수는 float (JSON 친화).
    assert isinstance(rows[0]["total_score"], float)
    assert rows[0]["status"] == "pending"


async def test_fk_requires_existing_features(
    migrated_session: AsyncSession,
) -> None:
    # 두 feature 모두 미적재 → FK(CASCADE) 위반.
    cand = _candidate("ghost-a", "ghost-b")
    with pytest.raises(IntegrityError):  # noqa: PT012 — savepoint 격리 필요
        async with migrated_session.begin_nested():
            await enqueue_dedup_candidate(migrated_session, cand)
