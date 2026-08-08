"""``kortravelmap.infra.sync_state_repo`` — provider dataset 증분 cursor 추적.

``provider_sync.provider_sync_state``는
``provider_dataset_id/sync_scope/operation_key`` PK + cursor JSONB를 소유한다.
provider/dataset 문자열은 API·ETL 입력과 조회 표시용
``provider_datasets`` projection일 뿐 state identity로 저장하지 않는다. 증분 적재는
provider별 ``cursor``(예:
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

from kortravelmap.core.feature_operation import ProviderDatasetOperationMembership

if TYPE_CHECKING:
    from datetime import datetime

    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = [
    "SyncState",
    "get_sync_state",
    "get_sync_state_for_operation_membership",
    "list_sync_states",
    "list_all_sync_states",
    "record_sync_success",
    "record_sync_success_for_operation_membership",
    "record_sync_failure",
    "record_sync_failure_for_operation_membership",
]


@dataclass(frozen=True)
class SyncState:
    """``provider_sync_state`` 행 표현 (repo 반환)."""

    provider_dataset_id: int
    provider: str
    dataset_key: str
    sync_scope: str
    operation_key: str
    status: str
    cursor: dict[str, Any]
    last_success_at: datetime | None
    last_failure_at: datetime | None
    consecutive_failures: int
    next_run_after: datetime | None


_RETURN_COLS: Final[str] = (
    "state.provider_dataset_id, dataset.provider, dataset.dataset_key, state.sync_scope, "
    "state.operation_key, "
    "state.status, state.cursor, state.last_success_at, state.last_failure_at, "
    "state.consecutive_failures, state.next_run_after"
)


def _row_to_state(row: Any) -> SyncState:
    cursor = row.cursor
    if isinstance(cursor, str):  # asyncpg가 JSONB를 str로 돌려주는 경우
        cursor = json.loads(cursor)
    return SyncState(
        provider_dataset_id=int(row.provider_dataset_id),
        provider=row.provider,
        dataset_key=row.dataset_key,
        sync_scope=row.sync_scope,
        operation_key=row.operation_key,
        status=row.status,
        cursor=dict(cursor) if cursor else {},
        last_success_at=row.last_success_at,
        last_failure_at=row.last_failure_at,
        consecutive_failures=row.consecutive_failures,
        next_run_after=row.next_run_after,
    )


_GET_SQL: Final[str] = f"""
SELECT {_RETURN_COLS}
FROM provider_sync.provider_sync_state AS state
JOIN provider_sync.provider_datasets AS dataset
  ON dataset.provider_dataset_id = state.provider_dataset_id
WHERE dataset.provider = :provider AND dataset.dataset_key = :dataset_key
  AND state.sync_scope = :sync_scope
  AND state.operation_key = :operation_key
"""

_GET_FOR_OPERATION_MEMBERSHIP_SQL: Final[str] = f"""
SELECT {_RETURN_COLS}
FROM provider_sync.provider_sync_state AS state
JOIN provider_sync.provider_datasets AS dataset
  ON dataset.provider_dataset_id = state.provider_dataset_id
JOIN provider_sync.provider_dataset_operation_scopes AS scope
 ON scope.provider_dataset_id = state.provider_dataset_id
 AND scope.sync_scope = state.sync_scope
 AND scope.operation_key = state.operation_key
JOIN provider_sync.provider_dataset_operations AS operation
  ON operation.provider_dataset_id = scope.provider_dataset_id
 AND operation.operation_key = scope.operation_key
 AND operation.operation_kind = scope.operation_kind
WHERE state.provider_dataset_id = CAST(:provider_dataset_id AS bigint)
  AND state.sync_scope = CAST(:sync_scope AS text)
  AND scope.operation_key = CAST(:operation_key AS text)
  AND scope.operation_kind = 'refresh'
  AND dataset.is_active
  AND operation.is_enabled
"""

_RECORD_SUCCESS_SQL: Final[str] = f"""
WITH written AS (
    INSERT INTO provider_sync.provider_sync_state (
        provider_dataset_id, sync_scope, operation_key, status, cursor,
        last_success_at, consecutive_failures, next_run_after, updated_at
    )
    SELECT
        dataset.provider_dataset_id, :sync_scope, :operation_key, 'active', CAST(:cursor AS jsonb),
        now(), 0, :next_run_after, now()
    FROM provider_sync.provider_datasets AS dataset
    JOIN provider_sync.provider_dataset_operation_scopes AS scope
      ON scope.provider_dataset_id = dataset.provider_dataset_id
     AND scope.sync_scope = :sync_scope
     AND scope.operation_key = :operation_key
    JOIN provider_sync.provider_dataset_operations AS operation
      ON operation.provider_dataset_id = scope.provider_dataset_id
     AND operation.operation_key = scope.operation_key
     AND operation.operation_kind = scope.operation_kind
    WHERE dataset.provider = :provider
      AND dataset.dataset_key = :dataset_key
      AND scope.operation_kind = 'refresh'
      AND dataset.is_active
      AND operation.is_enabled
    ON CONFLICT (provider_dataset_id, sync_scope, operation_key) DO UPDATE SET
        status = 'active',
        cursor = EXCLUDED.cursor,
        last_success_at = now(),
        consecutive_failures = 0,
        next_run_after = EXCLUDED.next_run_after,
        updated_at = now()
    RETURNING *
)
SELECT {_RETURN_COLS}
FROM written AS state
JOIN provider_sync.provider_datasets AS dataset
  ON dataset.provider_dataset_id = state.provider_dataset_id
"""

_RECORD_SUCCESS_FOR_OPERATION_MEMBERSHIP_SQL: Final[str] = f"""
WITH exact_membership AS (
    SELECT dataset.provider_dataset_id
    FROM provider_sync.provider_datasets AS dataset
    JOIN provider_sync.provider_dataset_operation_scopes AS scope
      ON scope.provider_dataset_id = dataset.provider_dataset_id
    JOIN provider_sync.provider_dataset_operations AS operation
      ON operation.provider_dataset_id = scope.provider_dataset_id
     AND operation.operation_key = scope.operation_key
     AND operation.operation_kind = scope.operation_kind
    WHERE dataset.provider_dataset_id = CAST(:provider_dataset_id AS bigint)
      AND scope.sync_scope = CAST(:sync_scope AS text)
      AND scope.operation_key = CAST(:operation_key AS text)
      AND scope.operation_kind = 'refresh'
      AND dataset.is_active
      AND operation.is_enabled
), written AS (
    INSERT INTO provider_sync.provider_sync_state (
        provider_dataset_id, sync_scope, operation_key, status, cursor,
        last_success_at, consecutive_failures, next_run_after, updated_at
    )
    SELECT
        exact_membership.provider_dataset_id, :sync_scope, :operation_key,
        'active', CAST(:cursor AS jsonb),
        now(), 0, :next_run_after, now()
    FROM exact_membership
    ON CONFLICT (provider_dataset_id, sync_scope, operation_key) DO UPDATE SET
        status = 'active',
        cursor = EXCLUDED.cursor,
        last_success_at = now(),
        consecutive_failures = 0,
        next_run_after = EXCLUDED.next_run_after,
        updated_at = now()
    RETURNING *
)
SELECT {_RETURN_COLS}
FROM written AS state
JOIN provider_sync.provider_datasets AS dataset
  ON dataset.provider_dataset_id = state.provider_dataset_id
"""

# 실패는 cursor를 건드리지 않는다(미전진). 신규 행이면 cursor server_default '{}'.
_RECORD_FAILURE_SQL: Final[str] = f"""
WITH written AS (
    INSERT INTO provider_sync.provider_sync_state (
        provider_dataset_id, sync_scope, operation_key, status,
        last_failure_at, consecutive_failures, next_run_after, updated_at
    )
    SELECT
        dataset.provider_dataset_id, :sync_scope, :operation_key, 'active',
        now(), 1, :next_run_after, now()
    FROM provider_sync.provider_datasets AS dataset
    JOIN provider_sync.provider_dataset_operation_scopes AS scope
      ON scope.provider_dataset_id = dataset.provider_dataset_id
     AND scope.sync_scope = :sync_scope
     AND scope.operation_key = :operation_key
    JOIN provider_sync.provider_dataset_operations AS operation
      ON operation.provider_dataset_id = scope.provider_dataset_id
     AND operation.operation_key = scope.operation_key
     AND operation.operation_kind = scope.operation_kind
    WHERE dataset.provider = :provider
      AND dataset.dataset_key = :dataset_key
      AND scope.operation_kind = 'refresh'
      AND dataset.is_active
      AND operation.is_enabled
    ON CONFLICT (provider_dataset_id, sync_scope, operation_key) DO UPDATE SET
        last_failure_at = now(),
        consecutive_failures = provider_sync.provider_sync_state.consecutive_failures + 1,
        next_run_after = EXCLUDED.next_run_after,
        updated_at = now()
    RETURNING *
)
SELECT {_RETURN_COLS}
FROM written AS state
JOIN provider_sync.provider_datasets AS dataset
  ON dataset.provider_dataset_id = state.provider_dataset_id
"""

_RECORD_FAILURE_FOR_OPERATION_MEMBERSHIP_SQL: Final[str] = f"""
WITH exact_membership AS (
    SELECT dataset.provider_dataset_id
    FROM provider_sync.provider_datasets AS dataset
    JOIN provider_sync.provider_dataset_operation_scopes AS scope
      ON scope.provider_dataset_id = dataset.provider_dataset_id
    JOIN provider_sync.provider_dataset_operations AS operation
      ON operation.provider_dataset_id = scope.provider_dataset_id
     AND operation.operation_key = scope.operation_key
     AND operation.operation_kind = scope.operation_kind
    WHERE dataset.provider_dataset_id = CAST(:provider_dataset_id AS bigint)
      AND scope.sync_scope = CAST(:sync_scope AS text)
      AND scope.operation_key = CAST(:operation_key AS text)
      AND scope.operation_kind = 'refresh'
      AND dataset.is_active
      AND operation.is_enabled
), written AS (
    INSERT INTO provider_sync.provider_sync_state (
        provider_dataset_id, sync_scope, operation_key, status,
        last_failure_at, consecutive_failures, next_run_after, updated_at
    )
    SELECT
        exact_membership.provider_dataset_id, :sync_scope, :operation_key, 'active',
        now(), 1, :next_run_after, now()
    FROM exact_membership
    ON CONFLICT (provider_dataset_id, sync_scope, operation_key) DO UPDATE SET
        last_failure_at = now(),
        consecutive_failures = provider_sync.provider_sync_state.consecutive_failures + 1,
        next_run_after = EXCLUDED.next_run_after,
        updated_at = now()
    RETURNING *
)
SELECT {_RETURN_COLS}
FROM written AS state
JOIN provider_sync.provider_datasets AS dataset
  ON dataset.provider_dataset_id = state.provider_dataset_id
"""


async def get_sync_state(
    session: AsyncSession,
    *,
    provider: str,
    dataset_key: str,
    operation_key: str,
    sync_scope: str = "dataset_wide",
) -> SyncState | None:
    """cursor 상태 조회. 없으면 ``None``(최초 적재 = full로 간주은 호출자 판단)."""
    row = (
        await session.execute(
            text(_GET_SQL),
            {
                "provider": provider,
                "dataset_key": dataset_key,
                "sync_scope": sync_scope,
                "operation_key": operation_key,
            },
        )
    ).one_or_none()
    return _row_to_state(row) if row is not None else None


async def get_sync_state_for_operation_membership(
    session: AsyncSession,
    *,
    membership: ProviderDatasetOperationMembership,
) -> SyncState | None:
    """active refresh operation의 exact ID/scope/key로 cursor를 읽는다."""
    row = (
        await session.execute(
            text(_GET_FOR_OPERATION_MEMBERSHIP_SQL),
            {
                "provider_dataset_id": membership.provider_dataset_id,
                "sync_scope": membership.sync_scope,
                "operation_key": membership.operation_key,
            },
        )
    ).one_or_none()
    return _row_to_state(row) if row is not None else None


_LIST_SQL: Final[str] = f"""
SELECT {_RETURN_COLS}
FROM provider_sync.provider_sync_state AS state
JOIN provider_sync.provider_datasets AS dataset
  ON dataset.provider_dataset_id = state.provider_dataset_id
WHERE dataset.provider = :provider
  AND (CAST(:dataset_key AS text) IS NULL OR dataset.dataset_key = :dataset_key)
  AND (CAST(:sync_scope AS text) IS NULL OR state.sync_scope = :sync_scope)
  AND (CAST(:operation_key AS text) IS NULL OR state.operation_key = :operation_key)
ORDER BY dataset.dataset_key, state.sync_scope, state.operation_key
"""

_LIST_BY_DATASET_ID_SQL: Final[str] = f"""
SELECT {_RETURN_COLS}
FROM provider_sync.provider_sync_state AS state
JOIN provider_sync.provider_datasets AS dataset
  ON dataset.provider_dataset_id = state.provider_dataset_id
WHERE state.provider_dataset_id = CAST(:provider_dataset_id AS bigint)
  AND (CAST(:sync_scope AS text) IS NULL OR state.sync_scope = :sync_scope)
  AND (CAST(:operation_key AS text) IS NULL OR state.operation_key = :operation_key)
ORDER BY state.sync_scope, state.operation_key
"""


async def list_sync_states(
    session: AsyncSession,
    *,
    provider: str,
    dataset_key: str | None = None,
    sync_scope: str | None = None,
    operation_key: str | None = None,
) -> list[SyncState]:
    """provider의 sync state 목록(데이터 신선도). ``dataset_key``/``sync_scope``로
    좁힐 수 있다. 매칭 행이 없으면 빈 list — 404 판단은 호출자(라우터) 책임(T-213g)."""
    rows = (
        await session.execute(
            text(_LIST_SQL),
            {
                "provider": provider,
                "dataset_key": dataset_key,
                "sync_scope": sync_scope,
                "operation_key": operation_key,
            },
        )
    ).all()
    return [_row_to_state(row) for row in rows]


async def list_sync_states_by_dataset_id(
    session: AsyncSession,
    *,
    provider_dataset_id: int,
    sync_scope: str | None = None,
    operation_key: str | None = None,
) -> list[SyncState]:
    """canonical dataset identity로 sync state를 읽는다."""
    if provider_dataset_id <= 0:
        raise ValueError("provider_dataset_id must be positive")
    rows = (
        await session.execute(
            text(_LIST_BY_DATASET_ID_SQL),
            {
                "provider_dataset_id": provider_dataset_id,
                "sync_scope": sync_scope,
                "operation_key": operation_key,
            },
        )
    ).all()
    return [_row_to_state(row) for row in rows]


_LIST_ALL_SQL: Final[str] = f"""
SELECT {_RETURN_COLS}
FROM provider_sync.provider_sync_state AS state
JOIN provider_sync.provider_datasets AS dataset
  ON dataset.provider_dataset_id = state.provider_dataset_id
ORDER BY dataset.provider, dataset.dataset_key, state.sync_scope, state.operation_key
"""


async def list_all_sync_states(session: AsyncSession) -> list[SyncState]:
    """전 provider×dataset×scope×operation sync state 목록(신선도 대시보드, T-217g).

    provider×dataset 조합은 유한(수십 행)하므로 페이지네이션 없이 전량 반환한다 —
    ``/v1/categories``와 같은 bounded reference 목록 패턴.
    """
    rows = (await session.execute(text(_LIST_ALL_SQL))).all()
    return [_row_to_state(row) for row in rows]


async def record_sync_success(
    session: AsyncSession,
    *,
    provider: str,
    dataset_key: str,
    operation_key: str,
    sync_scope: str = "dataset_wide",
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
                "operation_key": operation_key,
                "cursor": json.dumps(cursor),
                "next_run_after": next_run_after,
            },
        )
    ).one()
    return _row_to_state(row)


async def record_sync_success_for_operation_membership(
    session: AsyncSession,
    *,
    membership: ProviderDatasetOperationMembership,
    cursor: dict[str, Any],
    next_run_after: datetime | None = None,
) -> SyncState:
    """active exact refresh membership의 cursor를 성공 상태로 원자 갱신한다."""
    row = (
        await session.execute(
            text(_RECORD_SUCCESS_FOR_OPERATION_MEMBERSHIP_SQL),
            {
                "provider_dataset_id": membership.provider_dataset_id,
                "sync_scope": membership.sync_scope,
                "operation_key": membership.operation_key,
                "cursor": json.dumps(cursor),
                "next_run_after": next_run_after,
            },
        )
    ).one_or_none()
    if row is None:
        raise ValueError("operation membership is not an active enabled refresh scope")
    return _row_to_state(row)


async def record_sync_failure(
    session: AsyncSession,
    *,
    provider: str,
    dataset_key: str,
    operation_key: str,
    sync_scope: str = "dataset_wide",
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
                "operation_key": operation_key,
                "next_run_after": next_run_after,
            },
        )
    ).one()
    return _row_to_state(row)


async def record_sync_failure_for_operation_membership(
    session: AsyncSession,
    *,
    membership: ProviderDatasetOperationMembership,
    next_run_after: datetime | None = None,
) -> SyncState:
    """active exact refresh membership의 cursor를 보존한 채 실패를 기록한다."""
    row = (
        await session.execute(
            text(_RECORD_FAILURE_FOR_OPERATION_MEMBERSHIP_SQL),
            {
                "provider_dataset_id": membership.provider_dataset_id,
                "sync_scope": membership.sync_scope,
                "operation_key": membership.operation_key,
                "next_run_after": next_run_after,
            },
        )
    ).one_or_none()
    if row is None:
        raise ValueError("operation membership is not an active enabled refresh scope")
    return _row_to_state(row)
