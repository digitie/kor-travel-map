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


async def _ins(
    session: AsyncSession, fid: str, category: str, status: str = "active"
) -> None:
    await session.execute(
        text(
            """
            INSERT INTO feature.features (
                feature_id, kind, name, category, coord, status, updated_at
            )
            VALUES (
                :fid, 'place', 'x', :category,
                x_extension.ST_SetSRID(x_extension.ST_MakePoint(127.0, 37.5), 4326),
                :status, :ts
            )
            """
        ),
        {"fid": fid, "category": category, "status": status, "ts": _FETCHED},
    )
    await session.flush()


async def test_category_feature_counts(migrated_session: AsyncSession) -> None:
    """counts는 항상 ADR-067 공개 projection(``public_features``) 기준이다 (T-VN-04).

    비공개(inactive/draft/hidden 등) feature는 공개 표면 집계에 포함되지 않는다 —
    과거 ``active_only=False`` 경로가 비공개 분포를 노출했던 F-1 leak의 회귀 방지.
    """
    await _ins(migrated_session, "cc:1", "01070100")
    await _ins(migrated_session, "cc:2", "01070100")
    await _ins(migrated_session, "cc:3", "01070100", status="inactive")
    await _ins(migrated_session, "cc:5", "01070100", status="draft")
    await _ins(migrated_session, "cc:4", "06020000")

    counts = await feature_repo.category_feature_counts(migrated_session)
    assert counts["01070100"] == 2
    assert counts["06020000"] == 1
