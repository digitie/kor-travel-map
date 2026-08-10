"""T-VN-36D forward-only destructive schema fence."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[2]
_CONTRACT = _ROOT / "contracts" / "vnext" / "tvn36-post-cutover-invariants-v1.sql"


def _contract_queries() -> list[str]:
    content = _CONTRACT.read_text(encoding="utf-8")
    parsed = re.findall(
        r"(?ms)^(SELECT .*?); -- expect: 0 -- phase: post-tvn36$",
        content,
    )
    markers = re.findall(r"(?m); -- expect: 0 -- phase: post-tvn36$", content)
    assert len(parsed) == len(markers)
    return parsed


async def test_tvn36_final_fence_contract_holds_at_head(
    migrated_session: AsyncSession,
) -> None:
    """최종 head는 contract의 모든 destructive absence assertion을 만족한다."""

    for query in _contract_queries():
        assert await migrated_session.scalar(text(query)) == 0, query


async def test_tvn36_final_fence_has_no_whole_row_freeze_storage(
    migrated_session: AsyncSession,
) -> None:
    """catalog 자체가 old write bridge를 되살릴 relation을 남기지 않는다."""

    rows = (
        await migrated_session.execute(
            text(
                """
                SELECT table_schema, table_name
                FROM information_schema.tables
                WHERE (table_schema, table_name) IN (
                    ('feature', 'feature_versions'),
                    ('ops', 'feature_change_requests')
                )
                """
            )
        )
    ).all()
    assert rows == []
