"""``test_dedup_repo`` — ops.dedup_review_queue 적재 (ADR-016, SPRINT-3 §2.5).

``infra/dedup_repo.py``의 ``enqueue_dedup_candidate(s)`` / ``pending_dedup_reviews``를
실 PostGIS(migrated_session, alembic head)에서 검증한다:

- 신규 후보 insert + 점수 0~100 변환(×100) + status='pending' + decision_reason.
- 재스캔 시 pending 행 점수 갱신(updated), 검토 완료(accepted) 행 보존(skipped).
- reversed pair도 같은 canonical queue row로 수렴하며, self-pair는 skipped.
- ``pending_dedup_reviews`` total_score 내림차순 + float 변환.
- 존재하지 않는 feature 참조는 **쓰기 전에** `UnresolvedFeatureRefError`로 멈춘다
  (T-VN-39부터). FK(CASCADE)는 DB 층 보장으로 그대로 남아 repo를 우회한 직접
  INSERT를 계속 막는다.

T-VN-39 재키(alembic 309) 뒤 ``feature.features.feature_id``와 그것을 참조하는
``ops.dedup_review_queue.feature_id_a/b``는 **uuid**다. 그래서 이 파일의 seed id는
legacy ``f_*`` 문자열이 아니라 고정 UUIDv7이고, 무엇을 가리키는지는 값이 아니라
상수 이름이 진다.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from kortravelmap.core.dedup import DedupCandidate
from kortravelmap.infra.canonical_feature_ids import UnresolvedFeatureRefError
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

# ``ops.dedup_review_queue``의 canonical 제약은 ``feature_id_a < feature_id_b``를
# **uuid 비교**로 강제하고, ``infra/dedup_repo._canonical_pair``는 같은 판정을
# 파이썬 문자열 비교로 한다. 아래 값은 소문자 canonical 표기라 두 순서가 일치하고,
# 짝을 이루는 상수는 마지막 자리로 순서를 고정한다 — 이 순서가 곧 테스트 대상이다.
_F_KNPS = "00000000-0000-7000-8000-0000000d0001"
_F_KRH = "00000000-0000-7000-8000-0000000d0002"
_F_PAIR_A = "00000000-0000-7000-8000-0000000d0011"
_F_PAIR_B = "00000000-0000-7000-8000-0000000d0012"
_F_SELF = "00000000-0000-7000-8000-0000000d0020"
_F_SORT_A1 = "00000000-0000-7000-8000-0000000d0031"
_F_SORT_B1 = "00000000-0000-7000-8000-0000000d0032"
_F_SORT_A2 = "00000000-0000-7000-8000-0000000d0033"
_F_SORT_B2 = "00000000-0000-7000-8000-0000000d0034"
#: features에 적재하지 않는다 — "가리키는 Feature가 없다"를 관측하는 probe.
_F_GHOST_A = "00000000-0000-7000-8000-0000000d00f1"
_F_GHOST_B = "00000000-0000-7000-8000-0000000d00f2"


def _temple(feature_id: str, name: str = "불국사") -> FeatureRow:
    """temple place feature (dedup 후보 FK 대상)."""
    from geoalchemy2 import WKTElement

    return FeatureRow(
        feature_id=feature_id,
        kind="place",
        name=name,
        category=_TEMPLE_CAT,
        coord=WKTElement("POINT(129.3320 35.7900)", srid=4326),
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
    migrated_session.add(_temple(_F_KNPS))
    migrated_session.add(_temple(_F_KRH))
    await migrated_session.flush()

    result = await enqueue_dedup_candidates(
        migrated_session,
        [_candidate(_F_KNPS, _F_KRH)],
    )
    assert result == DedupQueueResult(
        candidates_total=1, inserted=1, updated=0, skipped=0
    )

    row = await _score_row(migrated_session, _F_KNPS, _F_KRH)
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
    migrated_session.add(_temple(_F_KNPS))
    migrated_session.add(_temple(_F_KRH))
    await migrated_session.flush()

    await enqueue_dedup_candidate(migrated_session, _candidate(_F_KNPS, _F_KRH))
    # 재스캔 — 점수가 달라진 같은 쌍.
    result = await enqueue_dedup_candidates(
        migrated_session,
        [_candidate(_F_KNPS, _F_KRH, score=0.80, name_score=0.95)],
    )
    assert result.updated == 1
    assert result.inserted == 0
    assert result.skipped == 0

    row = await _score_row(migrated_session, _F_KNPS, _F_KRH)
    assert float(row.total_score) == 80.0  # 갱신됨
    assert float(row.name_score) == 95.0


async def test_reversed_pair_reuses_canonical_queue_row(
    migrated_session: AsyncSession,
) -> None:
    migrated_session.add(_temple(_F_PAIR_A))
    migrated_session.add(_temple(_F_PAIR_B))
    await migrated_session.flush()

    first = await enqueue_dedup_candidate(migrated_session, _candidate(_F_PAIR_B, _F_PAIR_A))
    second = await enqueue_dedup_candidate(
        migrated_session,
        _candidate(_F_PAIR_A, _F_PAIR_B, score=0.83, name_score=0.97),
    )

    assert first == "inserted"
    assert second == "updated"
    row = await _score_row(migrated_session, _F_PAIR_A, _F_PAIR_B)
    assert float(row.total_score) == 83.0
    assert float(row.name_score) == 97.0
    count = (
        await migrated_session.execute(
            text(
                "SELECT count(*) FROM ops.dedup_review_queue "
                "WHERE feature_id_a IN (:a, :b) "
                "AND feature_id_b IN (:a, :b)"
            ),
            {"a": _F_PAIR_A, "b": _F_PAIR_B},
        )
    ).scalar_one()
    assert count == 1


async def test_self_pair_is_skipped(
    migrated_session: AsyncSession,
) -> None:
    migrated_session.add(_temple(_F_SELF))
    await migrated_session.flush()

    result = await enqueue_dedup_candidate(
        migrated_session,
        _candidate(_F_SELF, _F_SELF),
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
    migrated_session.add(_temple(_F_PAIR_A))
    migrated_session.add(_temple(_F_PAIR_B))
    await migrated_session.flush()

    with pytest.raises(IntegrityError):  # noqa: PT012 — savepoint 격리 필요
        async with migrated_session.begin_nested():
            await migrated_session.execute(
                text(
                    "INSERT INTO ops.dedup_review_queue "
                    "(feature_id_a, feature_id_b, total_score, name_score, "
                    "spatial_score, category_score, status) "
                    # 큰 uuid를 a 자리에 — canonical 제약이 거부해야 한다.
                    "VALUES (:b, :a, 70, 90, 60, 100, 'pending')"
                ),
                {"a": _F_PAIR_A, "b": _F_PAIR_B},
            )


async def test_reviewed_row_preserved_on_reenqueue(
    migrated_session: AsyncSession,
) -> None:
    migrated_session.add(_temple(_F_KNPS))
    migrated_session.add(_temple(_F_KRH))
    await migrated_session.flush()

    await enqueue_dedup_candidate(migrated_session, _candidate(_F_KNPS, _F_KRH))
    # 운영자가 검토 완료 (accepted).
    await migrated_session.execute(
        text(
            "UPDATE ops.dedup_review_queue SET status = 'accepted' "
            "WHERE feature_id_a = :a AND feature_id_b = :b"
        ),
        {"a": _F_KNPS, "b": _F_KRH},
    )

    # 재스캔 — 더 높은 점수로 들어와도 검토 완료 행은 보존.
    result = await enqueue_dedup_candidates(
        migrated_session,
        [_candidate(_F_KNPS, _F_KRH, score=0.95, decision="auto_merge")],
    )
    assert result.skipped == 1
    assert result.updated == 0
    assert result.inserted == 0

    row = await _score_row(migrated_session, _F_KNPS, _F_KRH)
    assert row.status == "accepted"  # 보존
    assert float(row.total_score) == 74.0  # 점수 갱신 안 됨
    assert row.decision_reason == "manual_review"  # 갱신 안 됨


async def test_pending_dedup_reviews_sorted_desc(
    migrated_session: AsyncSession,
) -> None:
    for fid in (_F_SORT_A1, _F_SORT_B1, _F_SORT_A2, _F_SORT_B2):
        migrated_session.add(_temple(fid))
    await migrated_session.flush()

    await enqueue_dedup_candidates(
        migrated_session,
        [
            _candidate(_F_SORT_A1, _F_SORT_B1, score=0.70),
            _candidate(_F_SORT_A2, _F_SORT_B2, score=0.82),
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


async def test_unknown_features_fail_before_any_write(
    migrated_session: AsyncSession,
) -> None:
    """미적재 feature를 가리키는 후보는 **쓰기 전에** 멈춘다.

    T-VN-39 전에는 FK 위반(IntegrityError)이 이것을 잡았다. 그 판정은 옳았지만
    두 가지가 아쉬웠다 — 오류가 **어느 참조가 문제인지 말하지 않고**, FK 위반은
    트랜잭션을 통째로 중단시켜 같은 배치의 앞선 적재까지 잃는다.

    이제 repo가 후보의 참조를 정본 uuid로 풀면서 그 자리에서 멈춘다. FK는
    사라지지 않았고 DB 층 보장으로 그대로 남는다 — 다만 정상 경로에서 그것이
    울릴 일이 없어졌다.
    """
    cand = _candidate(_F_GHOST_A, _F_GHOST_B)
    with pytest.raises(UnresolvedFeatureRefError) as caught:
        await enqueue_dedup_candidate(migrated_session, cand)
    assert _F_GHOST_A in str(caught.value)
    count = (
        await migrated_session.execute(
            text("SELECT count(*) FROM ops.dedup_review_queue")
        )
    ).scalar_one()
    assert count == 0


async def test_db_still_rejects_a_queue_row_without_its_features(
    migrated_session: AsyncSession,
) -> None:
    """repo를 우회해 직접 넣으면 FK가 여전히 잡는다 — DB 층 보장은 그대로다."""
    with pytest.raises(IntegrityError):  # noqa: PT012 — savepoint 격리 필요
        async with migrated_session.begin_nested():
            await migrated_session.execute(
                text(
                    "INSERT INTO ops.dedup_review_queue "
                    "(feature_id_a, feature_id_b, total_score, name_score, "
                    " spatial_score, category_score, status, decision_reason) "
                    "VALUES (CAST(:a AS uuid), CAST(:b AS uuid), "
                    "        50, 50, 50, 50, 'pending', 'manual_review')"
                ),
                {"a": _F_GHOST_A, "b": _F_GHOST_B},
            )
