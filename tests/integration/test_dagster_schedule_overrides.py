"""ops.dagster_schedule_overrides 읽기/쓰기 경로 + 0037 마이그레이션 계약 회귀(#613).

dagster 라우터의 raw ``text()`` SQL(_upsert/_schedule_overrides/_delete)이 0037 테이블
스키마(컬럼명·ON CONFLICT 타겟·스키마 한정자)와 일치하는지 실제 DB로 검증한다 — 오타가
나면 CI에서 잡힌다(이전엔 n150 live e2e뿐이라 CI 미검출).

라우터 함수는 내부에서 ``session.commit()``하므로 rollback 격리용 ``migrated_session``
대신 ``migrated_engine``에 직접 autobegin 세션을 열고, finally에서 정리한다.
"""

from __future__ import annotations

import pytest
from kortravelmap.api.routers.dagster import (
    _delete_schedule_override,
    _schedule_overrides,
    _upsert_schedule_override,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

pytestmark = pytest.mark.integration

_NAME = "__test_override_schedule__"


async def _row(session: AsyncSession, name: str) -> object | None:
    result = await session.execute(
        text(
            """
            SELECT cron_schedule, updated_by, reason, updated_at
            FROM ops.dagster_schedule_overrides
            WHERE schedule_name = :name
            """
        ),
        {"name": name},
    )
    return result.one_or_none()


async def test_schedule_override_upsert_read_conflict_delete(
    migrated_engine: AsyncEngine,
) -> None:
    async with AsyncSession(migrated_engine, expire_on_commit=False) as session:
        try:
            # INSERT
            await _upsert_schedule_override(
                session,
                schedule_name=_NAME,
                cron_schedule="5 4 * * *",
                operator="op-1",
                reason="initial",
            )
            assert (await _schedule_overrides(session)).get(_NAME) == "5 4 * * *"
            first = await _row(session, _NAME)
            assert first is not None
            assert (first.cron_schedule, first.updated_by, first.reason) == (
                "5 4 * * *",
                "op-1",
                "initial",
            )

            # ON CONFLICT (schedule_name) DO UPDATE → cron/updated_by/reason/updated_at 갱신
            await _upsert_schedule_override(
                session,
                schedule_name=_NAME,
                cron_schedule="15 6 * * *",
                operator="op-2",
                reason="changed",
            )
            assert (await _schedule_overrides(session)).get(_NAME) == "15 6 * * *"
            second = await _row(session, _NAME)
            assert second is not None
            assert (second.cron_schedule, second.updated_by, second.reason) == (
                "15 6 * * *",
                "op-2",
                "changed",
            )
            assert second.updated_at >= first.updated_at

            # DELETE
            await _delete_schedule_override(session, schedule_name=_NAME)
            assert _NAME not in await _schedule_overrides(session)
            assert await _row(session, _NAME) is None
        finally:
            await session.execute(
                text(
                    "DELETE FROM ops.dagster_schedule_overrides "
                    "WHERE schedule_name = :name"
                ),
                {"name": _NAME},
            )
            await session.commit()
