"""``ops.feature_update_requests`` lifecycle repository (ADR-045 T-206b).

Feature update request는 admin/OpenAPI가 만든 지리 범위/provider 범위 갱신
요청을 Dagster/import job과 연결하는 큐다. 본 모듈은 raw SQL만 사용하고
commit은 호출자에게 맡긴다(ADR-004).

흐름:
1. ``enqueue_feature_update_request`` — scope dry-run 해석 후, 실제 요청이면
   ``ops.import_jobs``와 ``ops.feature_update_requests``를 같은 transaction에 생성.
2. ``claim_next_update_request`` — priority/created_at 순서로 queued 요청 1건을
   ``running`` 전이(``FOR UPDATE SKIP LOCKED`` + advisory lock).
3. ``start_update_request`` / ``finish_update_request`` — Dagster run id와 terminal
   상태를 request/import job 양쪽에 반영.
4. ``list_update_requests`` — D-10 keyset cursor(``created_at, request_id``) 기반.
"""

from __future__ import annotations

import base64
import json
from collections.abc import Mapping as MappingABC
from collections.abc import Sequence as SequenceABC
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any, Final
from uuid import uuid4

from sqlalchemy import text

from kortravelmap.infra.advisory_lock import try_advisory_lock
from kortravelmap.infra.jobs_repo import enqueue_import_job
from kortravelmap.infra.scope_repo import (
    SigunguByRadiusResolver,
    count_features_matching_scope,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = [
    "FEATURE_UPDATE_JOB_KIND",
    "FEATURE_UPDATE_QUEUE_ADVISORY_KEY",
    "FeatureUpdateRequest",
    "FeatureUpdateRequestPreview",
    "FeatureUpdateRequestPage",
    "FeatureUpdateLockBusy",
    "FeatureUpdateQueueLockBusy",
    "enqueue_feature_update_request",
    "peek_update_requests",
    "peek_next_update_request",
    "claim_next_update_request",
    "feature_update_scope_advisory_key",
    "start_update_request",
    "finish_update_request",
    "set_update_request_matched_scope",
    "cancel_update_request",
    "get_update_request",
    "list_update_requests",
]

FEATURE_UPDATE_JOB_KIND: Final[str] = "feature_update_request"
FEATURE_UPDATE_QUEUE_ADVISORY_KEY: Final[str] = "kortravelmap:feature_update:claim"
FEATURE_UPDATE_LOCK_RETRY_AFTER_SECONDS: Final[int] = 15

_RUN_MODES: Final[frozenset[str]] = frozenset({"queued", "now"})
_TERMINAL_STATES: Final[frozenset[str]] = frozenset(
    {"done", "failed", "cancelled"}
)
_MAX_LIST_LIMIT: Final[int] = 200
_MAX_PEEK_LIMIT: Final[int] = 50

_RETURN_COLUMNS: Final[str] = (
    "request_id, scope_type, scope, providers, dataset_keys, update_policy, "
    "run_mode, priority, status, dry_run, matched_scope, job_id, dagster_run_id, "
    "operator, reason, error_message, created_at, started_at, finished_at, updated_at"
)


@dataclass(frozen=True)
class FeatureUpdateRequest:
    """DB에 저장된 ``ops.feature_update_requests`` 행."""

    request_id: str
    scope_type: str
    scope: dict[str, Any]
    providers: tuple[str, ...]
    dataset_keys: tuple[str, ...]
    update_policy: dict[str, Any]
    run_mode: str
    priority: int
    status: str
    dry_run: bool
    matched_scope: dict[str, Any]
    job_id: str | None
    dagster_run_id: str | None
    operator: str | None
    reason: str | None
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    updated_at: datetime


@dataclass(frozen=True)
class FeatureUpdateRequestPreview:
    """Dry-run 결과. DB row/import job을 만들지 않는다."""

    scope_type: str
    scope: dict[str, Any]
    providers: tuple[str, ...]
    dataset_keys: tuple[str, ...]
    update_policy: dict[str, Any]
    run_mode: str
    priority: int
    matched_scope: dict[str, Any]


@dataclass(frozen=True)
class FeatureUpdateRequestPage:
    """Keyset cursor 기반 목록 응답."""

    items: tuple[FeatureUpdateRequest, ...]
    next_cursor: str | None


class FeatureUpdateLockBusy(RuntimeError):
    """동일 feature update scope가 이미 실행 중임을 나타낸다."""

    code: str = "LOCK_BUSY"

    def __init__(
        self,
        message: str = "동일 feature update scope가 이미 실행 중입니다.",
        *,
        retry_after_seconds: int = FEATURE_UPDATE_LOCK_RETRY_AFTER_SECONDS,
        lock_key: str | None = None,
    ) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds
        self.lock_key = lock_key


class FeatureUpdateQueueLockBusy(FeatureUpdateLockBusy):
    """feature update queue claim lock이 다른 worker에 점유되어 있다."""

    def __init__(
        self,
        message: str = "feature update queue claim lock이 이미 점유되어 있습니다.",
        *,
        retry_after_seconds: int = FEATURE_UPDATE_LOCK_RETRY_AFTER_SECONDS,
    ) -> None:
        super().__init__(message, retry_after_seconds=retry_after_seconds)


def _json_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        value = json.loads(value)
    return dict(value) if value else {}


def _json_str_tuple(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        value = json.loads(value)
    if not value:
        return ()
    return tuple(str(item) for item in value)


def _row_to_request(row: Any) -> FeatureUpdateRequest:
    return FeatureUpdateRequest(
        request_id=str(row.request_id),
        scope_type=str(row.scope_type),
        scope=_json_dict(row.scope),
        providers=_json_str_tuple(row.providers),
        dataset_keys=_json_str_tuple(row.dataset_keys),
        update_policy=_json_dict(row.update_policy),
        run_mode=str(row.run_mode),
        priority=int(row.priority),
        status=str(row.status),
        dry_run=bool(row.dry_run),
        matched_scope=_json_dict(row.matched_scope),
        job_id=str(row.job_id) if row.job_id is not None else None,
        dagster_run_id=row.dagster_run_id,
        operator=row.operator,
        reason=row.reason,
        error_message=row.error_message,
        created_at=row.created_at,
        started_at=row.started_at,
        finished_at=row.finished_at,
        updated_at=row.updated_at,
    )


def _scope_type(scope: Mapping[str, Any]) -> str:
    scope_type = scope.get("type")
    if not isinstance(scope_type, str) or not scope_type:
        raise ValueError("scope requires non-empty type")
    return scope_type


def _normalize_strings(values: Sequence[str] | None) -> tuple[str, ...]:
    if values is None:
        return ()
    return tuple(str(item) for item in values if str(item))


def _validate_run_mode(run_mode: str) -> None:
    if run_mode not in _RUN_MODES:
        raise ValueError(f"run_mode must be one of {sorted(_RUN_MODES)}")


def _json_param(value: Mapping[str, Any] | Sequence[str]) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _canonical_jsonable(value: Any) -> Any:
    if isinstance(value, MappingABC):
        return {
            str(key): _canonical_jsonable(value[key])
            for key in sorted(value, key=lambda item: str(item))
        }
    if isinstance(value, SequenceABC) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        items = [_canonical_jsonable(item) for item in value]
        return sorted(
            items,
            key=lambda item: json.dumps(
                item,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
        )
    return value


def feature_update_scope_advisory_key(
    *,
    scope_type: str,
    scope: Mapping[str, Any],
    providers: Sequence[str] | None = None,
    dataset_keys: Sequence[str] | None = None,
) -> str:
    """동일 update scope를 판정하는 advisory lock key를 만든다."""
    payload = {
        "scope_type": scope_type,
        "scope": _canonical_jsonable(scope),
        "providers": sorted(_normalize_strings(providers)),
        "dataset_keys": sorted(_normalize_strings(dataset_keys)),
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return f"kortravelmap:feature_update:scope:{encoded}"


def _encode_cursor(item: FeatureUpdateRequest) -> str:
    payload = {
        "created_at": item.created_at.isoformat(),
        "request_id": item.request_id,
    }
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_cursor(cursor: str | None) -> tuple[datetime | None, str | None]:
    if cursor is None:
        return None, None
    padded = cursor + ("=" * (-len(cursor) % 4))
    try:
        payload = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
        created_at = datetime.fromisoformat(str(payload["created_at"]))
        request_id = str(payload["request_id"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("invalid feature update request cursor") from exc
    return created_at, request_id


_INSERT_REQUEST_SQL: Final[str] = f"""
INSERT INTO ops.feature_update_requests (
    request_id, scope_type, scope, providers, dataset_keys, update_policy,
    run_mode, priority, status, dry_run, matched_scope, job_id, operator, reason
) VALUES (
    :request_id, :scope_type, CAST(:scope AS jsonb), CAST(:providers AS jsonb),
    CAST(:dataset_keys AS jsonb), CAST(:update_policy AS jsonb),
    :run_mode, :priority, 'queued', false, CAST(:matched_scope AS jsonb),
    :job_id, :operator, :reason
)
RETURNING {_RETURN_COLUMNS}
"""

_GET_REQUEST_SQL: Final[str] = f"""
SELECT {_RETURN_COLUMNS}
FROM ops.feature_update_requests
WHERE request_id = :request_id
"""

_CLAIM_REQUEST_SQL: Final[str] = f"""
UPDATE ops.feature_update_requests
SET status = 'running',
    started_at = COALESCE(started_at, now()),
    updated_at = now()
WHERE request_id = (
    SELECT request_id
    FROM ops.feature_update_requests
    WHERE status = 'queued' AND dry_run IS false
    ORDER BY priority DESC, created_at, request_id
    FOR UPDATE SKIP LOCKED
    LIMIT 1
)
RETURNING {_RETURN_COLUMNS}
"""

_PEEK_REQUEST_SQL: Final[str] = f"""
SELECT {_RETURN_COLUMNS}
FROM ops.feature_update_requests
WHERE status = 'queued' AND dry_run IS false
ORDER BY priority DESC, created_at, request_id
LIMIT :limit
"""

_START_REQUEST_SQL: Final[str] = f"""
UPDATE ops.feature_update_requests
SET status = 'running',
    started_at = COALESCE(started_at, now()),
    dagster_run_id = COALESCE(:dagster_run_id, dagster_run_id),
    updated_at = now()
WHERE request_id = :request_id
  AND status IN ('queued', 'running')
RETURNING {_RETURN_COLUMNS}
"""

_SET_MATCHED_SCOPE_SQL: Final[str] = f"""
UPDATE ops.feature_update_requests
SET matched_scope = CAST(:matched_scope AS jsonb),
    updated_at = now()
WHERE request_id = :request_id
  AND status IN ('queued', 'running')
RETURNING {_RETURN_COLUMNS}
"""

_FINISH_REQUEST_SQL: Final[str] = f"""
UPDATE ops.feature_update_requests
SET status = :status,
    dagster_run_id = COALESCE(:dagster_run_id, dagster_run_id),
    error_message = :error_message,
    finished_at = now(),
    updated_at = now()
WHERE request_id = :request_id
  AND status IN ('queued', 'running')
RETURNING {_RETURN_COLUMNS}
"""

_START_IMPORT_JOB_SQL: Final[str] = """
UPDATE ops.import_jobs
SET status = 'running',
    started_at = COALESCE(started_at, now()),
    heartbeat_at = now(),
    current_stage = COALESCE(:current_stage, current_stage)
WHERE job_id = :job_id
  AND status IN ('queued', 'running')
"""

_FINISH_IMPORT_JOB_SQL: Final[str] = """
UPDATE ops.import_jobs
SET status = :status,
    finished_at = now(),
    heartbeat_at = now(),
    error_message = :error_message,
    progress = CASE WHEN :status = 'done' THEN 100 ELSE progress END
WHERE job_id = :job_id
  AND status IN ('queued', 'running')
"""

_LIST_REQUESTS_SQL: Final[str] = f"""
SELECT {_RETURN_COLUMNS}
FROM ops.feature_update_requests
WHERE (CAST(:status AS text) IS NULL OR status = CAST(:status AS text))
  AND (CAST(:scope_type AS text) IS NULL OR scope_type = CAST(:scope_type AS text))
  AND (
    CAST(:provider AS text) IS NULL
    OR providers @> CAST(:provider_filter AS jsonb)
    OR (
      scope_type = 'provider_dataset'
      AND scope->>'provider' = CAST(:provider AS text)
    )
  )
  AND (
    CAST(:dataset_key AS text) IS NULL
    OR dataset_keys @> CAST(:dataset_key_filter AS jsonb)
    OR (
      scope_type = 'provider_dataset'
      AND scope->>'dataset_key' = CAST(:dataset_key AS text)
    )
  )
  AND (
    CAST(:created_from AS timestamptz) IS NULL
    OR created_at >= CAST(:created_from AS timestamptz)
  )
  AND (
    CAST(:created_to AS timestamptz) IS NULL
    OR created_at <= CAST(:created_to AS timestamptz)
  )
  AND (
    CAST(:cursor_created_at AS timestamptz) IS NULL
    OR (created_at, request_id) < (
        CAST(:cursor_created_at AS timestamptz),
        CAST(:cursor_request_id AS uuid)
    )
  )
ORDER BY created_at DESC, request_id DESC
LIMIT :limit_plus_one
"""


async def _start_import_job(
    session: AsyncSession,
    *,
    job_id: str | None,
    current_stage: str,
) -> None:
    if job_id is None:
        return
    await session.execute(
        text(_START_IMPORT_JOB_SQL),
        {"job_id": job_id, "current_stage": current_stage},
    )


async def _finish_import_job(
    session: AsyncSession,
    *,
    job_id: str | None,
    status: str,
    error_message: str | None,
) -> None:
    if job_id is None:
        return
    await session.execute(
        text(_FINISH_IMPORT_JOB_SQL),
        {"job_id": job_id, "status": status, "error_message": error_message},
    )


async def enqueue_feature_update_request(
    session: AsyncSession,
    *,
    scope: Mapping[str, Any],
    providers: Sequence[str] | None = None,
    dataset_keys: Sequence[str] | None = None,
    update_policy: Mapping[str, Any] | None = None,
    run_mode: str = "queued",
    priority: int = 50,
    dry_run: bool = False,
    operator: str | None = None,
    reason: str | None = None,
    sigungu_resolver: SigunguByRadiusResolver | None = None,
) -> FeatureUpdateRequest | FeatureUpdateRequestPreview:
    """요청을 해석하고, 실제 실행 요청이면 request/import job row를 생성한다."""
    _validate_run_mode(run_mode)
    scope_payload = dict(scope)
    scope_type = _scope_type(scope_payload)
    provider_values = _normalize_strings(providers)
    dataset_values = _normalize_strings(dataset_keys)
    policy = dict(update_policy) if update_policy else {}
    resolution = await count_features_matching_scope(
        session, scope_payload, sigungu_resolver=sigungu_resolver
    )
    matched_scope = resolution.matched_scope()

    if dry_run:
        return FeatureUpdateRequestPreview(
            scope_type=scope_type,
            scope=scope_payload,
            providers=provider_values,
            dataset_keys=dataset_values,
            update_policy=policy,
            run_mode=run_mode,
            priority=priority,
            matched_scope=matched_scope,
        )

    scope_lock_key = feature_update_scope_advisory_key(
        scope_type=scope_type,
        scope=scope_payload,
        providers=provider_values,
        dataset_keys=dataset_values,
    )
    if run_mode == "now":
        async with try_advisory_lock(session, scope_lock_key) as acquired:
            if not acquired:
                raise FeatureUpdateLockBusy(lock_key=scope_lock_key)

    request_id = str(uuid4())
    job = await enqueue_import_job(
        session,
        kind=FEATURE_UPDATE_JOB_KIND,
        payload={
            "request_id": request_id,
            "scope_type": scope_type,
            "scope": scope_payload,
            "providers": list(provider_values),
            "dataset_keys": list(dataset_values),
            "update_policy": policy,
            "run_mode": run_mode,
            "matched_scope": matched_scope,
        },
    )
    row = (
        await session.execute(
            text(_INSERT_REQUEST_SQL),
            {
                "request_id": request_id,
                "scope_type": scope_type,
                "scope": _json_param(scope_payload),
                "providers": _json_param(list(provider_values)),
                "dataset_keys": _json_param(list(dataset_values)),
                "update_policy": _json_param(policy),
                "run_mode": run_mode,
                "priority": priority,
                "matched_scope": _json_param(matched_scope),
                "job_id": job.job_id,
                "operator": operator,
                "reason": reason,
            },
        )
    ).one()
    return _row_to_request(row)


async def peek_update_requests(
    session: AsyncSession,
    *,
    limit: int = 10,
) -> tuple[FeatureUpdateRequest, ...]:
    """claim 순서상 queued request 여러 건을 상태 변경 없이 조회한다."""
    if limit <= 0:
        raise ValueError("limit must be positive")
    rows = (
        await session.execute(
            text(_PEEK_REQUEST_SQL), {"limit": min(limit, _MAX_PEEK_LIMIT)}
        )
    ).all()
    return tuple(_row_to_request(row) for row in rows)


async def peek_next_update_request(
    session: AsyncSession,
) -> FeatureUpdateRequest | None:
    """claim 순서상 다음 queued request를 상태 변경 없이 조회한다."""
    requests = await peek_update_requests(session, limit=1)
    return requests[0] if requests else None



async def claim_next_update_request(
    session: AsyncSession,
) -> FeatureUpdateRequest | None:
    """가장 높은 priority의 queued 요청 1건을 running으로 claim한다."""
    async with try_advisory_lock(
        session, FEATURE_UPDATE_QUEUE_ADVISORY_KEY
    ) as acquired:
        if not acquired:
            raise FeatureUpdateQueueLockBusy()
        row = (await session.execute(text(_CLAIM_REQUEST_SQL))).one_or_none()
        if row is None:
            return None
        request = _row_to_request(row)
        await _start_import_job(
            session, job_id=request.job_id, current_stage="claimed"
        )
        return request


async def start_update_request(
    session: AsyncSession,
    request_id: str,
    *,
    dagster_run_id: str | None = None,
) -> FeatureUpdateRequest | None:
    """queued/running 요청을 running으로 만들고 Dagster run id를 기록한다."""
    row = (
        await session.execute(
            text(_START_REQUEST_SQL),
            {"request_id": request_id, "dagster_run_id": dagster_run_id},
        )
    ).one_or_none()
    if row is None:
        return None
    request = _row_to_request(row)
    await _start_import_job(
        session, job_id=request.job_id, current_stage="started"
    )
    return request


async def finish_update_request(
    session: AsyncSession,
    request_id: str,
    *,
    status: str = "done",
    dagster_run_id: str | None = None,
    error_message: str | None = None,
) -> FeatureUpdateRequest | None:
    """queued/running 요청을 terminal 상태로 닫고 import job도 같은 상태로 닫는다."""
    if status not in _TERMINAL_STATES:
        raise ValueError(f"status must be one of {sorted(_TERMINAL_STATES)}")
    row = (
        await session.execute(
            text(_FINISH_REQUEST_SQL),
            {
                "request_id": request_id,
                "status": status,
                "dagster_run_id": dagster_run_id,
                "error_message": error_message,
            },
        )
    ).one_or_none()
    if row is None:
        return None
    request = _row_to_request(row)
    await _finish_import_job(
        session,
        job_id=request.job_id,
        status=status,
        error_message=error_message,
    )
    return request


async def set_update_request_matched_scope(
    session: AsyncSession,
    request_id: str,
    *,
    matched_scope: Mapping[str, Any],
) -> FeatureUpdateRequest | None:
    """queued/running request의 실행 시점 scope 해석 결과를 저장한다."""
    row = (
        await session.execute(
            text(_SET_MATCHED_SCOPE_SQL),
            {
                "request_id": request_id,
                "matched_scope": _json_param(matched_scope),
            },
        )
    ).one_or_none()
    return _row_to_request(row) if row is not None else None


async def cancel_update_request(
    session: AsyncSession,
    request_id: str,
    *,
    error_message: str | None = None,
) -> FeatureUpdateRequest | None:
    """queued/running 요청을 ``cancelled``로 닫는다."""
    return await finish_update_request(
        session,
        request_id,
        status="cancelled",
        error_message=error_message,
    )


async def get_update_request(
    session: AsyncSession,
    request_id: str,
) -> FeatureUpdateRequest | None:
    """request id로 단건 조회."""
    row = (
        await session.execute(
            text(_GET_REQUEST_SQL), {"request_id": request_id}
        )
    ).one_or_none()
    return _row_to_request(row) if row is not None else None


async def list_update_requests(
    session: AsyncSession,
    *,
    status: str | None = None,
    scope_type: str | None = None,
    provider: str | None = None,
    dataset_key: str | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    limit: int = 50,
    cursor: str | None = None,
) -> FeatureUpdateRequestPage:
    """``created_at DESC, request_id DESC`` keyset cursor로 요청 목록을 조회한다."""
    if limit <= 0:
        raise ValueError("limit must be greater than 0")
    effective_limit = min(limit, _MAX_LIST_LIMIT)
    cursor_created_at, cursor_request_id = _decode_cursor(cursor)
    rows = (
        await session.execute(
            text(_LIST_REQUESTS_SQL),
            {
                "status": status,
                "scope_type": scope_type,
                "provider": provider,
                "provider_filter": _json_param([provider]) if provider else None,
                "dataset_key": dataset_key,
                "dataset_key_filter": (
                    _json_param([dataset_key]) if dataset_key else None
                ),
                "created_from": created_from,
                "created_to": created_to,
                "cursor_created_at": cursor_created_at,
                "cursor_request_id": cursor_request_id,
                "limit_plus_one": effective_limit + 1,
            },
        )
    ).all()
    requests = tuple(_row_to_request(row) for row in rows[:effective_limit])
    next_cursor = (
        _encode_cursor(requests[-1])
        if len(rows) > effective_limit and requests
        else None
    )
    return FeatureUpdateRequestPage(items=requests, next_cursor=next_cursor)
