"""Provider dataset update의 active identity와 dispatch intent repository (#686).

active identity는 lifecycle 단일 정본인 ``ops.import_jobs``의 typed
``provider × dataset_key × sync_scope``를 사용한다. 조회는 request/job을 한 SQL
snapshot으로 읽고, 생성 경합의 최종 방어선은 같은 컬럼의 partial unique index다.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from kortravelmap.core.sync_scope import parse_canonical_sync_scope
from kortravelmap.infra.feature_update_repo import (
    _REQUEST_RETURN_COLUMNS,
    FeatureUpdateRequest,
    _row_to_request,
    get_update_request,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = [
    "ACTIVE_PROVIDER_DATASET_UNIQUE_INDEX",
    "FeatureUpdateDispatchConflict",
    "effective_sync_scope",
    "find_active_provider_dataset_request",
    "is_active_provider_dataset_unique_violation",
    "request_feature_update_dispatch",
]

ACTIVE_PROVIDER_DATASET_UNIQUE_INDEX: Final[str] = "uq_import_jobs_active_feature_update_scope"

_FIND_ACTIVE_REQUEST_SQL: Final[str] = f"""
SELECT {_REQUEST_RETURN_COLUMNS}
FROM ops.import_jobs AS job
JOIN ops.feature_update_requests AS request ON request.job_id = job.job_id
WHERE job.kind = 'feature_update_request'
  AND job.provider = CAST(:provider AS text)
  AND job.dataset_key = CAST(:dataset_key AS text)
  AND job.sync_scope = CAST(:sync_scope AS text)
  AND job.status IN ('queued', 'running')
  AND job.quarantined_at IS NULL
ORDER BY (job.status = 'running') DESC,
         (job.dispatch_requested_at IS NOT NULL) DESC,
         request.created_at,
         request.request_id
LIMIT 1
"""

_REQUEST_DISPATCH_SQL: Final[str] = """
WITH locked AS MATERIALIZED (
    SELECT
      request.request_id,
      job.job_id,
      job.status,
      job.cancellation_id,
      job.quarantined_at
    FROM ops.feature_update_requests AS request
    JOIN ops.import_jobs AS job ON job.job_id = request.job_id
    WHERE request.request_id = CAST(:request_id AS uuid)
      AND job.kind = 'feature_update_request'
    FOR UPDATE OF request, job
),
updated AS (
    UPDATE ops.import_jobs AS job
       SET dispatch_requested_at = COALESCE(
             job.dispatch_requested_at,
             clock_timestamp()
           )
      FROM locked
     WHERE job.job_id = locked.job_id
       AND locked.status = 'queued'
       AND locked.cancellation_id IS NULL
       AND locked.quarantined_at IS NULL
    RETURNING job.job_id, job.dispatch_requested_at
)
SELECT
  locked.request_id,
  locked.status,
  locked.cancellation_id,
  locked.quarantined_at,
  updated.dispatch_requested_at
FROM locked
LEFT JOIN updated ON updated.job_id = locked.job_id
"""


class FeatureUpdateDispatchConflict(RuntimeError):
    """queued dispatch intent를 기록할 수 없는 현재 lifecycle 상태."""

    def __init__(self, *, request_id: str, current_status: str) -> None:
        self.request_id = request_id
        self.current_status = current_status
        super().__init__(
            "feature update dispatch request conflicts with current lifecycle: "
            f"request_id={request_id}, current_status={current_status}"
        )


def effective_sync_scope(sync_scope: str) -> str:
    """active lookup 경계에서 canonical effective identity를 강제한다."""
    return parse_canonical_sync_scope(sync_scope).value


async def find_active_provider_dataset_request(
    session: AsyncSession,
    *,
    provider: str,
    dataset_key: str,
    sync_scope: str,
) -> FeatureUpdateRequest | None:
    """같은 canonical direct scope의 active request를 한 SQL snapshot으로 읽는다."""
    row = (
        await session.execute(
            text(_FIND_ACTIVE_REQUEST_SQL),
            {
                "provider": provider,
                "dataset_key": dataset_key,
                "sync_scope": effective_sync_scope(sync_scope),
            },
        )
    ).one_or_none()
    return _row_to_request(row) if row is not None else None


def _driver_constraint_identity(exc: BaseException) -> tuple[str | None, str | None]:
    """SQLAlchemy/asyncpg/psycopg 예외에서 SQLSTATE와 constraint 이름을 꺼낸다."""
    candidates: list[Any] = [exc]
    seen: set[int] = set()
    found_sqlstate: str | None = None
    found_constraint_name: str | None = None
    while candidates:
        candidate = candidates.pop()
        if candidate is None or id(candidate) in seen:
            continue
        seen.add(id(candidate))
        diag = getattr(candidate, "diag", None)
        found_constraint_name = (
            found_constraint_name
            or getattr(candidate, "constraint_name", None)
            or getattr(diag, "constraint_name", None)
        )
        found_sqlstate = found_sqlstate or (
            getattr(candidate, "sqlstate", None)
            or getattr(candidate, "pgcode", None)
            or getattr(diag, "sqlstate", None)
        )
        if found_constraint_name is not None and found_sqlstate is not None:
            return found_sqlstate, found_constraint_name
        candidates.extend(
            (
                getattr(candidate, "orig", None),
                getattr(candidate, "__cause__", None),
                getattr(candidate, "__context__", None),
            )
        )
    return found_sqlstate, found_constraint_name


def is_active_provider_dataset_unique_violation(exc: BaseException) -> bool:
    """active scope index의 ``23505``만 constraint metadata로 판정한다."""
    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, IntegrityError):
            sqlstate, constraint_name = _driver_constraint_identity(current)
            if sqlstate == "23505" and constraint_name == ACTIVE_PROVIDER_DATASET_UNIQUE_INDEX:
                return True
        current = current.__cause__ or current.__context__
    return False


async def request_feature_update_dispatch(
    session: AsyncSession,
    request_id: str,
) -> FeatureUpdateRequest:
    """기존 queued request에 새 행 없이 최초 dispatch intent를 원자적으로 기록한다.

    같은 queued request 재호출은 원래 timestamp를 보존한다. running/terminal/취소·격리
    상태는 caller가 명시적으로 분기할 수 있도록 typed conflict로 반환한다.
    """
    row = (
        await session.execute(text(_REQUEST_DISPATCH_SQL), {"request_id": request_id})
    ).one_or_none()
    if row is None:
        raise FeatureUpdateDispatchConflict(
            request_id=request_id,
            current_status="not_found",
        )
    if row.dispatch_requested_at is None:
        status = str(row.status)
        if row.quarantined_at is not None:
            status = "quarantined"
        elif row.cancellation_id is not None:
            status = "cancellation_requested"
        raise FeatureUpdateDispatchConflict(
            request_id=str(row.request_id),
            current_status=status,
        )
    request = await get_update_request(session, str(row.request_id))
    if request is None:  # request/job은 위 statement에서 잠겨 있으므로 invariant 위반이다.
        raise RuntimeError("dispatch-promoted feature update request disappeared")
    return request
