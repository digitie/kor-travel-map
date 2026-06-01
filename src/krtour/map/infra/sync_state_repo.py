"""``krtour.map.infra.sync_state_repo`` — provider 증분 cursor 추적 (Step B).

``provider_sync.provider_sync_state``(provider/dataset_key/sync_scope PK + cursor
JSONB)를 읽고 갱신한다. 증분 적재(Step B)는 provider별 ``cursor``(예:
``{"last_modified_date": "2026-06-01"}``)를 운영해 "지난 적재 이후 변경분"만 받는다
— **무엇이 변경됐는지/다음 cursor 값은 호출자(provider) 책임**(ADR-006). 본 모듈은
적재 성공/실패 시 cursor·타임스탬프·연속 실패 수만 영속화한다.

raw SQL은 본 모듈에 모음(ADR-004). commit은 호출자 책임.

ADR 참조
--------
- ADR-004 — ORM 매핑만, 쿼리는 raw SQL
- ADR-006 — provider 미import (cursor 진행은 호출자가 결정)
- ADR-008 — schema 격리(provider_sync)
- ADR-019 — TIMESTAMPTZ aware
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

from sqlalchemy import text

if TYPE_CHECKING:
    from datetime import datetime

    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = [
    "SyncState",
    "get_sync_state",
    "record_sync_success",
    "record_sync_failure",
]


@dataclass(frozen=True)
class SyncState:
    """``provider_sync_state`` 행 표현 (repo 반환)."""

    provider: str
    dataset_key: str
    sync_scope: str
    status: str
    cursor: dict[str, Any]
    last_success_at: datetime | None
    last_failure_at: datetime | None
    consecutive_failures: int
    next_run_after: datetime | None


_RETURN_COLS: Final[str] = (
    "provider, dataset_key, sync_scope, status, cursor, last_success_at, "
    "last_failure_at, consecutive_failures, next_run_after"
)


def _row_to_state(row: Any) -> SyncState:
    cursor = row.cursor
    if isinstance(cursor, str):  # asyncpg가 JSONB를 str로 돌려주는 경우
        cursor = json.loads(cursor)
    return SyncState(
        provider=row.provider,
        dataset_key=row.dataset_key,
        sync_scope=row.sync_scope,
        status=row.status,
        cursor=dict(cursor) if cursor else {},
        last_success_at=row.last_success_at,
        last_failure_at=row.last_failure_at,
        consecutive_failures=row.consecutive_failures,
        next_run_after=row.next_run_after,
    )


_GET_SQL: Final[str] = f"""
SELECT {_RETURN_COLS}
FROM provider_sync.provider_sync_state
WHERE provider = :provider AND dataset_key = :dataset_key
  AND sync_scope = :sync_scope
"""

_RECORD_SUCCESS_SQL: Final[str] = f"""
INSERT INTO provider_sync.provider_sync_state (
    provider, dataset_key, sync_scope, status, cursor,
    last_success_at, consecutive_failures, next_run_after, updated_at
) VALUES (
    :provider, :dataset_key, :sync_scope, 'active', CAST(:cursor AS jsonb),
    now(), 0, :next_run_after, now()
)
ON CONFLICT (provider, dataset_key, sync_scope) DO UPDATE SET
    status = 'active',
    cursor = EXCLUDED.cursor,
    last_success_at = now(),
    consecutive_failures = 0,
    next_run_after = EXCLUDED.next_run_after,
    updated_at = now()
RETURNING {_RETURN_COLS}
"""

# 실패는 cursor를 건드리지 않는다(미전진). 신규 행이면 cursor server_default '{}'.
_RECORD_FAILURE_SQL: Final[str] = f"""
INSERT INTO provider_sync.provider_sync_state (
    provider, dataset_key, sync_scope, status,
    last_failure_at, consecutive_failures, next_run_after, updated_at
) VALUES (
    :provider, :dataset_key, :sync_scope, 'active',
    now(), 1, :next_run_after, now()
)
ON CONFLICT (provider, dataset_key, sync_scope) DO UPDATE SET
    last_failure_at = now(),
    consecutive_failures = provider_sync.provider_sync_state.consecutive_failures + 1,
    next_run_after = EXCLUDED.next_run_after,
    updated_at = now()
RETURNING {_RETURN_COLS}
"""


async def get_sync_state(
    session: AsyncSession,
    *,
    provider: str,
    dataset_key: str,
    sync_scope: str = "default",
) -> SyncState | None:
    """cursor 상태 조회. 없으면 ``None``(최초 적재 = full로 간주은 호출자 판단)."""
    row = (
        await session.execute(
            text(_GET_SQL),
            {
                "provider": provider,
                "dataset_key": dataset_key,
                "sync_scope": sync_scope,
            },
        )
    ).one_or_none()
    return _row_to_state(row) if row is not None else None


async def record_sync_success(
    session: AsyncSession,
    *,
    provider: str,
    dataset_key: str,
    sync_scope: str = "default",
    cursor: dict[str, Any],
    next_run_after: datetime | None = None,
) -> SyncState:
    """적재 성공 — cursor 전진 + ``last_success_at`` 갱신 + 연속 실패 0 (UPSERT)."""
    row = (
        await session.execute(
            text(_RECORD_SUCCESS_SQL),
            {
                "provider": provider,
                "dataset_key": dataset_key,
                "sync_scope": sync_scope,
                "cursor": json.dumps(cursor),
                "next_run_after": next_run_after,
            },
        )
    ).one()
    return _row_to_state(row)


async def record_sync_failure(
    session: AsyncSession,
    *,
    provider: str,
    dataset_key: str,
    sync_scope: str = "default",
    next_run_after: datetime | None = None,
) -> SyncState:
    """적재 실패 — cursor 미전진 + ``last_failure_at`` + 연속 실패 +1 (UPSERT)."""
    row = (
        await session.execute(
            text(_RECORD_FAILURE_SQL),
            {
                "provider": provider,
                "dataset_key": dataset_key,
                "sync_scope": sync_scope,
                "next_run_after": next_run_after,
            },
        )
    ).one()
    return _row_to_state(row)
