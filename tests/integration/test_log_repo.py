"""``log_repo`` 운영 로그 surface 통합 테스트 (T-212c)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text

from krtour.map.infra.log_repo import (
    list_api_call_logs,
    list_system_logs,
    record_api_call,
    record_system_log,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration

_KST = timezone(timedelta(hours=9))


async def _set_system_log_created_at(
    session: AsyncSession, *, key: str, created_at: datetime
) -> None:
    await session.execute(
        text(
            """
            UPDATE ops.system_log
            SET created_at = :created_at
            WHERE system_log_key = :key
            """
        ),
        {"key": key, "created_at": created_at},
    )


async def _set_api_call_created_at(
    session: AsyncSession, *, key: str, created_at: datetime
) -> None:
    await session.execute(
        text(
            """
            UPDATE ops.api_call_log
            SET created_at = :created_at
            WHERE api_call_log_key = :key
            """
        ),
        {"key": key, "created_at": created_at},
    )


async def test_record_and_list_system_logs_cursor_and_filters(
    migrated_session: AsyncSession,
) -> None:
    old = await record_system_log(
        migrated_session,
        level="info",
        source="offline_upload",
        event="upload_done",
        message="오래된 업로드 완료",
        detail={"count": 1},
        request_id="req-old",
    )
    new = await record_system_log(
        migrated_session,
        level="error",
        source="geocoding",
        event="reverse_fail",
        message="새 역지오코딩 실패",
        detail={"feature_id": "f1"},
    )
    await _set_system_log_created_at(
        migrated_session,
        key=old.system_log_key,
        created_at=datetime(2026, 6, 3, 10, 0, tzinfo=_KST),
    )
    await _set_system_log_created_at(
        migrated_session,
        key=new.system_log_key,
        created_at=datetime(2026, 6, 3, 11, 0, tzinfo=_KST),
    )
    await migrated_session.flush()

    # keyset cursor: page1 = 최신(new), page2 = 오래된(old).
    page1 = await list_system_logs(migrated_session, limit=1)
    assert [row.system_log_key for row in page1.items] == [new.system_log_key]
    assert page1.next_cursor is not None
    assert page1.items[0].detail == {"feature_id": "f1"}

    page2 = await list_system_logs(
        migrated_session, limit=1, cursor=page1.next_cursor
    )
    assert [row.system_log_key for row in page2.items] == [old.system_log_key]

    # level 필터.
    errors = await list_system_logs(migrated_session, level="error")
    assert {row.system_log_key for row in errors.items} == {new.system_log_key}

    # source 필터.
    uploads = await list_system_logs(migrated_session, source="offline_upload")
    assert {row.system_log_key for row in uploads.items} == {old.system_log_key}

    # q: message 부분일치.
    matched = await list_system_logs(migrated_session, q="역지오코딩")
    assert {row.system_log_key for row in matched.items} == {new.system_log_key}


async def test_record_system_log_invalid_level_raises(
    migrated_session: AsyncSession,
) -> None:
    with pytest.raises(ValueError, match="level must be one of"):
        await record_system_log(
            migrated_session,
            level="trace",
            source="admin",
            event="x",
            message="y",
        )


async def test_record_and_list_api_call_logs_cursor_and_min_status(
    migrated_session: AsyncSession,
) -> None:
    ok = await record_api_call(
        migrated_session,
        method="GET",
        path="/ops/metrics",
        status_code=200,
        duration_ms=8,
        request_id="req-ok",
    )
    err = await record_api_call(
        migrated_session,
        method="POST",
        path="/admin/features",
        status_code=500,
        duration_ms=30,
        error_code="INTERNAL_ERROR",
    )
    await _set_api_call_created_at(
        migrated_session,
        key=ok.api_call_log_key,
        created_at=datetime(2026, 6, 3, 10, 0, tzinfo=_KST),
    )
    await _set_api_call_created_at(
        migrated_session,
        key=err.api_call_log_key,
        created_at=datetime(2026, 6, 3, 11, 0, tzinfo=_KST),
    )
    await migrated_session.flush()

    # keyset cursor: page1 = 최신(err), page2 = 오래된(ok).
    page1 = await list_api_call_logs(migrated_session, limit=1)
    assert [row.api_call_log_key for row in page1.items] == [err.api_call_log_key]
    assert page1.next_cursor is not None

    page2 = await list_api_call_logs(
        migrated_session, limit=1, cursor=page1.next_cursor
    )
    assert [row.api_call_log_key for row in page2.items] == [ok.api_call_log_key]

    # min_status 필터: >= 500.
    failures = await list_api_call_logs(migrated_session, min_status=500)
    assert {row.api_call_log_key for row in failures.items} == {err.api_call_log_key}
    assert failures.items[0].error_code == "INTERNAL_ERROR"

    # method + path 필터.
    by_method = await list_api_call_logs(
        migrated_session, method="GET", path="/ops"
    )
    assert {row.api_call_log_key for row in by_method.items} == {ok.api_call_log_key}
