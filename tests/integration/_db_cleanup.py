"""Append-only production trigger를 보존하는 통합 테스트 전용 정리 도우미."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def truncate_committed_test_rows(
    session: AsyncSession,
    statement: str,
) -> None:
    """현재 cleanup transaction에서만 trigger를 끄고 committed fixture를 비운다."""

    await session.execute(text("SET LOCAL session_replication_role = replica"))
    await session.execute(text(statement))
