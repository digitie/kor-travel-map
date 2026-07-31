"""통합 테스트 DB reset helper의 append-only trigger 복원 검증."""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration._db_cleanup import truncate_committed_test_rows

pytestmark = pytest.mark.integration


async def _assert_history_truncate_is_rejected(session: AsyncSession) -> None:
    with pytest.raises(DBAPIError, match="curation import/link history is append-only"):
        async with session.begin_nested():
            await session.execute(
                text("TRUNCATE feature.curation_import_batches CASCADE")
            )


async def test_cleanup_reenables_append_only_trigger_after_success(
    migrated_session: AsyncSession,
) -> None:
    await truncate_committed_test_rows(
        migrated_session,
        "TRUNCATE feature.features RESTART IDENTITY CASCADE",
    )

    await _assert_history_truncate_is_rejected(migrated_session)


async def test_cleanup_rollback_reenables_append_only_trigger_after_failure(
    migrated_session: AsyncSession,
) -> None:
    with pytest.raises(DBAPIError):
        await truncate_committed_test_rows(
            migrated_session,
            "TRUNCATE feature.missing_cleanup_table",
        )

    await _assert_history_truncate_is_rejected(migrated_session)
