"""Append-only production trigger를 보존하는 통합 테스트 전용 정리 도우미."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_IMMUTABLE_HISTORY_TABLES = (
    "curation_import_batches",
    "curation_import_rows",
    "curation_link_decisions",
)
_CURATION_RESET_SQL = """
TRUNCATE
    feature.curation_link_decisions,
    feature.curation_import_rows,
    feature.curation_import_batches,
    feature.curation_items,
    feature.curation_collections
RESTART IDENTITY CASCADE
"""


async def truncate_committed_test_rows(
    session: AsyncSession,
    statement: str,
) -> None:
    """테스트 savepoint 안에서 curation 전체와 committed fixture를 원자적으로 비운다.

    운영 append-only trigger는 그대로 유지한다. cleanup 도중 실패하면 savepoint
    rollback이 ``DISABLE TRIGGER``까지 되돌리므로 trigger가 비활성화된 채 남지 않는다.
    """

    savepoint = await session.begin_nested()
    try:
        for table_name in _IMMUTABLE_HISTORY_TABLES:
            await session.execute(
                text(
                    f"ALTER TABLE feature.{table_name} "
                    f"DISABLE TRIGGER trg_{table_name}_append_only"
                )
            )
            await session.execute(
                text(
                    f"ALTER TABLE feature.{table_name} "
                    f"DISABLE TRIGGER trg_{table_name}_no_truncate"
                )
            )

        # 기존 committed fixture cleanup에는 curation 외 append-only ledger도
        # cascade될 수 있다. 복제 role은 이 savepoint 안에서만 열고 성공 경로에서도
        # 즉시 origin으로 복원한다.
        await session.execute(text("SET LOCAL session_replication_role = replica"))
        await session.execute(text(_CURATION_RESET_SQL))
        await session.execute(text(statement))
        await session.execute(text("SET LOCAL session_replication_role = origin"))

        for table_name in reversed(_IMMUTABLE_HISTORY_TABLES):
            await session.execute(
                text(
                    f"ALTER TABLE feature.{table_name} "
                    f"ENABLE TRIGGER trg_{table_name}_no_truncate"
                )
            )
            await session.execute(
                text(
                    f"ALTER TABLE feature.{table_name} "
                    f"ENABLE TRIGGER trg_{table_name}_append_only"
                )
            )
    except BaseException:
        await savepoint.rollback()
        raise
    else:
        await savepoint.commit()
