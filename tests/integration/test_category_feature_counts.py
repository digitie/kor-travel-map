"""``category_feature_counts`` 통합 테스트 (T-213f)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text

from kortravelmap.infra import feature_repo

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration

_KST = timezone(timedelta(hours=9))
_FETCHED = datetime(2026, 6, 3, 12, 0, tzinfo=_KST)

_VISIBLE_SEED_SQL = """
SELECT feature_id FROM feature.public_features WHERE feature_id LIKE 'cc:%'
"""


async def _ins(
    session: AsyncSession,
    fid: str,
    category: str,
    *,
    lifecycle_state: str = "active",
    publication_state: str = "published",
    quality_state: str = "valid",
) -> None:
    """seed 1건. 기본값은 "공개 표면에 보이는" 상태 tuple이다.

    T-VN-34 이후 상태의 정본은 단일 ``status``가 아니라 3축이고, 공개 여부는
    ``feature.public_features``가 세 축의 교집합(active/published/valid)으로
    정의한다. 따라서 이 헬퍼는 축 값을 그대로 받는다 — 예전 ``status='active'``
    기본값과 등가인 tuple이 위 세 기본값이다.
    """
    await session.execute(
        text(
            """
            INSERT INTO feature.features (
                feature_id, kind, name, category, coord,
                lifecycle_state, publication_state, quality_state, updated_at
            )
            VALUES (
                :fid, 'place', 'x', :category,
                x_extension.ST_SetSRID(x_extension.ST_MakePoint(127.0, 37.5), 4326),
                :lifecycle_state, :publication_state, :quality_state, :ts
            )
            """
        ),
        {
            "fid": fid,
            "category": category,
            "lifecycle_state": lifecycle_state,
            "publication_state": publication_state,
            "quality_state": quality_state,
            "ts": _FETCHED,
        },
    )
    await session.flush()


async def test_category_feature_counts(migrated_session: AsyncSession) -> None:
    """counts는 항상 ADR-067 공개 projection(``public_features``) 기준이다 (T-VN-04).

    비공개 feature는 공개 표면 집계에 포함되지 않는다 — 과거 ``active_only=False``
    경로가 비공개 분포를 노출했던 F-1 leak의 회귀 방지.

    이 테스트가 세는 대상은 "축 값"이 아니라 "공개 표면에 실재하는가"이므로,
    비공개 fixture 2건은 공개에서 빠지는 서로 **다른 이유**를 하나씩 대표한다
    (0095 backfill 매핑 기준의 종전 fixture와 등가):

    - ``cc:3``: 예전 ``status='inactive'`` — lifecycle이 ``retired``라 애초에
      살아있지 않다. ``ck_features_state_tuple``이 retired에 published를
      허용하지 않으므로 publication은 ``suppressed``가 동반된다.
    - ``cc:5``: 예전 ``status='draft'`` — lifecycle은 ``active``지만 아직
      publish되지 않았다. 즉 "살아있으나 공개 전"이라는 축이 분리된 사례라,
      단일 status 시절과 달리 lifecycle만 봐서는 비공개임을 알 수 없다.
    """
    await _ins(migrated_session, "cc:1", "01070100")
    await _ins(migrated_session, "cc:2", "01070100")
    await _ins(
        migrated_session,
        "cc:3",
        "01070100",
        lifecycle_state="retired",
        publication_state="suppressed",
    )
    await _ins(migrated_session, "cc:5", "01070100", publication_state="draft")
    await _ins(migrated_session, "cc:4", "06020000")

    # 집계의 기준선이 공개 projection임을 먼저 고정한다 — 비공개 2건이 정말로
    # ``public_features``에 없어서 빠지는 것이지, 집계 쿼리가 따로 거른 게 아니다.
    visible = set((await migrated_session.execute(text(_VISIBLE_SEED_SQL))).scalars().all())
    assert visible == {"cc:1", "cc:2", "cc:4"}

    counts = await feature_repo.category_feature_counts(migrated_session)
    assert counts["01070100"] == 2
    assert counts["06020000"] == 1
