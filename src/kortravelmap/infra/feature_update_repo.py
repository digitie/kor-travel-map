"""``ops.feature_update_requests`` lifecycle repository (ADR-045 T-206b).

Feature update request는 admin/OpenAPI가 만든 지리 범위/provider 범위 갱신
요청을 Dagster/import job과 연결하는 큐다. 본 모듈은 raw SQL만 사용하고
commit은 호출자에게 맡긴다(ADR-004).

흐름:
1. ``enqueue_feature_update_request`` — scope dry-run 해석 후, 실제 요청이면
   ``ops.import_jobs``와 ``ops.feature_update_requests``를 같은 transaction에 생성.
2. ``peek_next_update_request`` → executor request/scope lease → ``start_update_request``
   CAS — lock 경합에서 running 행을 소모하지 않는 기본 실행 흐름.
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

from kortravelmap.core.feature_operation import (
    ProviderDatasetOperationKey,
)
from kortravelmap.infra.advisory_lock import try_advisory_lock
from kortravelmap.infra.jobs_repo import (
    assert_generic_import_job_targets,
    enqueue_import_job,
)
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
    "advance_update_request_generation_after_pre_start_failure",
    "touch_queued_update_request_for_lock_retry",
    "claim_next_update_request",
    "claim_update_requests",
    "feature_update_scope_advisory_key",
    "start_update_request",
    "finish_update_request",
    "set_update_request_matched_scope",
    "cancel_update_request",
    "get_update_request",
    "lock_feature_update_execution_guard",
    "requeue_update_request_after_lock_contention",
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
    "cancellation_id, cancellation_requested_at, cancellation_requested_by, "
    "cancellation_reason, operator, reason, error_message, created_at, started_at, "
    "finished_at, updated_at"
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
    cancellation_id: str | None = None
    cancellation_requested_at: datetime | None = None
    cancellation_requested_by: str | None = None
    cancellation_reason: str | None = None


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
        cancellation_id=(
            str(row.cancellation_id) if row.cancellation_id is not None else None
        ),
        cancellation_requested_at=row.cancellation_requested_at,
        cancellation_requested_by=row.cancellation_requested_by,
        cancellation_reason=row.cancellation_reason,
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
) SELECT
    :request_id, :scope_type, CAST(:scope AS jsonb), CAST(:providers AS jsonb),
    CAST(:dataset_keys AS jsonb), CAST(:update_policy AS jsonb),
    :run_mode, :priority, 'queued', false, CAST(:matched_scope AS jsonb),
    :job_id, :operator, :reason
WHERE EXISTS (
    SELECT 1
    FROM ops.import_jobs AS job
    WHERE job.job_id = CAST(:job_id AS uuid)
      AND job.cancellation_id IS NULL
)
RETURNING {_RETURN_COLUMNS}
"""

_GET_REQUEST_SQL: Final[str] = f"""
SELECT {_RETURN_COLUMNS}
FROM ops.feature_update_requests
WHERE request_id = :request_id
"""

_LOCK_EXECUTION_REQUEST_SQL: Final[str] = f"""
SELECT {_RETURN_COLUMNS}
FROM ops.feature_update_requests
WHERE request_id = :request_id
FOR UPDATE
"""

_LOCK_EXECUTION_JOB_SQL: Final[str] = """
SELECT status, cancellation_id
FROM ops.import_jobs
WHERE job_id = CAST(:job_id AS uuid)
FOR UPDATE
"""

_CLAIM_REQUEST_SQL: Final[str] = f"""
UPDATE ops.feature_update_requests
SET status = 'running',
    started_at = COALESCE(started_at, now()),
    updated_at = now()
WHERE request_id = (
    SELECT request_id
    FROM ops.feature_update_requests
    WHERE status = 'queued'
      AND dry_run IS false
      AND cancellation_id IS NULL
    ORDER BY priority DESC, created_at, request_id
    FOR UPDATE SKIP LOCKED
    LIMIT 1
)
RETURNING {_RETURN_COLUMNS}
"""

_PEEK_REQUEST_SQL: Final[str] = f"""
SELECT {_RETURN_COLUMNS}
FROM ops.feature_update_requests
WHERE status = 'queued'
  AND dry_run IS false
  AND cancellation_id IS NULL
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
  AND cancellation_id IS NULL
  AND (
    (
      status = 'queued'
      AND dagster_run_id IS NULL
      AND (
        CAST(:expected_updated_at AS timestamptz) IS NULL
        OR updated_at = CAST(:expected_updated_at AS timestamptz)
      )
    )
    OR (
      status = 'running'
      AND dagster_run_id IS NOT DISTINCT FROM CAST(:dagster_run_id AS text)
    )
  )
RETURNING {_RETURN_COLUMNS}
"""

_REQUEUE_REQUEST_SQL: Final[str] = f"""
UPDATE ops.feature_update_requests
SET status = 'queued',
    dagster_run_id = NULL,
    error_message = NULL,
    started_at = NULL,
    finished_at = NULL,
    updated_at = GREATEST(updated_at + INTERVAL '1 microsecond', clock_timestamp())
WHERE request_id = :request_id
  AND status IN ('queued', 'running')
  AND cancellation_id IS NULL
RETURNING {_RETURN_COLUMNS}
"""

_SET_MATCHED_SCOPE_SQL: Final[str] = f"""
UPDATE ops.feature_update_requests
SET matched_scope = CAST(:matched_scope AS jsonb),
    updated_at = now()
WHERE request_id = :request_id
  AND status IN ('queued', 'running')
  AND cancellation_id IS NULL
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
  AND cancellation_id IS NULL
  AND (
    CAST(:expected_dagster_run_id AS text) IS NULL
    OR dagster_run_id = CAST(:expected_dagster_run_id AS text)
  )
RETURNING {_RETURN_COLUMNS}
"""

_START_IMPORT_JOB_SQL: Final[str] = """
UPDATE ops.import_jobs
SET status = 'running',
    started_at = COALESCE(started_at, now()),
    heartbeat_at = now(),
    current_stage = COALESCE(:current_stage, current_stage),
    dagster_run_id = COALESCE(:dagster_run_id, dagster_run_id)
WHERE job_id = :job_id
  AND kind NOT IN ('provider_feature_load_run','provider_feature_load')
  AND cancellation_id IS NULL
  AND (
    (status = 'queued' AND dagster_run_id IS NULL)
    OR (
      status = 'running'
      AND dagster_run_id IS NOT DISTINCT FROM CAST(:dagster_run_id AS text)
    )
  )
RETURNING job_id
"""

_FINISH_IMPORT_JOB_SQL: Final[str] = """
UPDATE ops.import_jobs
SET status = :status,
    finished_at = now(),
    heartbeat_at = now(),
    dagster_run_id = COALESCE(:dagster_run_id, dagster_run_id),
    error_message = :error_message,
    progress = CASE WHEN :status = 'done' THEN 100 ELSE progress END
WHERE job_id = :job_id
  AND status IN ('queued', 'running')
  AND kind NOT IN ('provider_feature_load_run','provider_feature_load')
  AND cancellation_id IS NULL
  AND (
    CAST(:expected_dagster_run_id AS text) IS NULL
    OR dagster_run_id = CAST(:expected_dagster_run_id AS text)
  )
RETURNING job_id
"""

_REQUEUE_IMPORT_JOB_SQL: Final[str] = """
UPDATE ops.import_jobs
SET status = 'queued',
    payload = payload - 'dagster_run_id' - 'run_id',
    progress = 0,
    current_stage = NULL,
    dagster_run_id = NULL,
    error_message = NULL,
    started_at = NULL,
    heartbeat_at = NULL,
    finished_at = NULL
WHERE job_id = CAST(:job_id AS uuid)
  AND status IN ('queued', 'running')
  AND kind NOT IN ('provider_feature_load_run','provider_feature_load')
  AND cancellation_id IS NULL
RETURNING job_id
"""

_TOUCH_QUEUED_REQUEST_FOR_LOCK_RETRY_SQL: Final[str] = f"""
UPDATE ops.feature_update_requests
SET updated_at = GREATEST(updated_at + INTERVAL '1 microsecond', clock_timestamp())
WHERE request_id = :request_id
  AND status = 'queued'
  AND cancellation_id IS NULL
RETURNING {_RETURN_COLUMNS}
"""

_ADVANCE_PRE_START_FAILURE_GENERATION_SQL: Final[str] = f"""
UPDATE ops.feature_update_requests
SET updated_at = GREATEST(updated_at + INTERVAL '1 microsecond', clock_timestamp())
WHERE request_id = :request_id
  AND status = 'queued'
  AND dagster_run_id IS NULL
  AND updated_at = CAST(:expected_updated_at AS timestamptz)
  AND cancellation_id IS NULL
RETURNING {_RETURN_COLUMNS}
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
    dagster_run_id: str | None = None,
) -> bool:
    if job_id is None:
        return True
    await assert_generic_import_job_targets(session, (job_id,))
    row = (
        await session.execute(
            text(_START_IMPORT_JOB_SQL),
            {
                "job_id": job_id,
                "current_stage": current_stage,
                "dagster_run_id": dagster_run_id,
            },
        )
    ).one_or_none()
    return row is not None


async def _finish_import_job(
    session: AsyncSession,
    *,
    job_id: str | None,
    status: str,
    dagster_run_id: str | None,
    expected_dagster_run_id: str | None,
    error_message: str | None,
) -> bool:
    if job_id is None:
        return True
    await assert_generic_import_job_targets(session, (job_id,))
    row = (
        await session.execute(
            text(_FINISH_IMPORT_JOB_SQL),
            {
                "job_id": job_id,
                "status": status,
                "dagster_run_id": dagster_run_id,
                "expected_dagster_run_id": expected_dagster_run_id,
                "error_message": error_message,
            },
        )
    ).one_or_none()
    return row is not None


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
    provider_dataset = None
    if scope_type == "provider_dataset":
        provider = scope_payload.get("provider")
        dataset_key = scope_payload.get("dataset_key")
        if not isinstance(provider, str) or not isinstance(dataset_key, str):
            raise ValueError("provider_dataset scope requires provider and dataset_key")
        provider_dataset = ProviderDatasetOperationKey(provider, dataset_key)
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
        provider_dataset=provider_dataset,
        trigger_kind="update_request",
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
        async with session.begin_nested():
            row = (await session.execute(text(_CLAIM_REQUEST_SQL))).one_or_none()
            if row is None:
                return None
            request = _row_to_request(row)
            job_started = await _start_import_job(
                session, job_id=request.job_id, current_stage="claimed"
            )
            if not job_started:
                raise RuntimeError(
                    "feature update request was claimed but its import job was not"
                )
            return request


async def claim_update_requests(
    session: AsyncSession,
    *,
    limit: int = 10,
) -> tuple[FeatureUpdateRequest, ...]:
    """claim 순서상 queued request 여러 건을 running으로 전이한다."""
    if limit <= 0:
        raise ValueError("limit must be positive")
    claimed: list[FeatureUpdateRequest] = []
    for _ in range(min(limit, _MAX_PEEK_LIMIT)):
        request = await claim_next_update_request(session)
        if request is None:
            break
        claimed.append(request)
    return tuple(claimed)


async def start_update_request(
    session: AsyncSession,
    request_id: str,
    *,
    dagster_run_id: str | None = None,
    expected_updated_at: datetime | None = None,
) -> FeatureUpdateRequest | None:
    """queued generation을 claim하거나 같은 running owner를 멱등 재확인한다.

    다른 ``dagster_run_id``가 소유한 running request는 절대 덮지 않는다. queued
    transition에는 sensor가 고정한 ``expected_updated_at``을 선택적으로 적용한다.
    연결 import job start가 실패하면 nested transaction 전체를 rollback한다.
    """
    if dagster_run_id == "":
        raise ValueError("dagster_run_id must not be empty")
    if expected_updated_at is not None and (
        expected_updated_at.tzinfo is None
        or expected_updated_at.utcoffset() is None
    ):
        raise ValueError("expected_updated_at must be timezone-aware")
    async with session.begin_nested():
        row = (
            await session.execute(
                text(_START_REQUEST_SQL),
                {
                    "request_id": request_id,
                    "dagster_run_id": dagster_run_id,
                    "expected_updated_at": expected_updated_at,
                },
            )
        ).one_or_none()
        if row is None:
            return None
        request = _row_to_request(row)
        job_started = await _start_import_job(
            session,
            job_id=request.job_id,
            current_stage="started",
            dagster_run_id=dagster_run_id,
        )
        if not job_started:
            raise RuntimeError(
                "feature update request was started but its import job was not"
            )
        return request


async def finish_update_request(
    session: AsyncSession,
    request_id: str,
    *,
    status: str = "done",
    dagster_run_id: str | None = None,
    expected_dagster_run_id: str | None = None,
    error_message: str | None = None,
) -> FeatureUpdateRequest | None:
    """요청과 import job을 닫되 지정한 Dagster run 세대가 아니면 건너뛴다."""
    if status not in _TERMINAL_STATES:
        raise ValueError(f"status must be one of {sorted(_TERMINAL_STATES)}")
    if expected_dagster_run_id == "":
        raise ValueError("expected_dagster_run_id must not be empty")
    if (
        expected_dagster_run_id is not None
        and dagster_run_id is not None
        and expected_dagster_run_id != dagster_run_id
    ):
        raise ValueError(
            "dagster_run_id must match expected_dagster_run_id when both are set"
        )
    row = (
        await session.execute(
            text(_FINISH_REQUEST_SQL),
            {
                "request_id": request_id,
                "status": status,
                "dagster_run_id": dagster_run_id,
                "expected_dagster_run_id": expected_dagster_run_id,
                "error_message": error_message,
            },
        )
    ).one_or_none()
    if row is None:
        return None
    request = _row_to_request(row)
    job_finished = await _finish_import_job(
        session,
        job_id=request.job_id,
        status=status,
        dagster_run_id=dagster_run_id,
        expected_dagster_run_id=expected_dagster_run_id,
        error_message=error_message,
    )
    if expected_dagster_run_id is not None and not job_finished:
        raise RuntimeError(
            "feature update request was finished but its import job run generation "
            "did not match"
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


async def lock_feature_update_execution_guard(
    session: AsyncSession,
    request_id: str,
) -> FeatureUpdateRequest | None:
    """실행 phase 직전에 request→job을 잠그고 marker/status를 검증한다.

    취소 coordinator와 같은 base row 순서를 사용한다. 반환값이 ``None``이면
    현재 transaction에서 provider runner나 lifecycle write를 시작하면 안 된다.
    """
    row = (
        await session.execute(
            text(_LOCK_EXECUTION_REQUEST_SQL),
            {"request_id": request_id},
        )
    ).one_or_none()
    if row is None:
        return None
    request = _row_to_request(row)
    if (
        request.status not in {"queued", "running"}
        or request.cancellation_id is not None
    ):
        return None
    if request.job_id is None:
        return request
    job = (
        await session.execute(
            text(_LOCK_EXECUTION_JOB_SQL),
            {"job_id": request.job_id},
        )
    ).one_or_none()
    if (
        job is None
        or str(job.status) not in {"queued", "running"}
        or job.cancellation_id is not None
    ):
        return None
    return request


async def requeue_update_request_after_lock_contention(
    session: AsyncSession,
    request_id: str,
) -> FeatureUpdateRequest | None:
    """request lease를 가진 executor가 scope 경합 대상을 다시 실행 가능하게 둔다.

    request→job row를 먼저 잠가 cancellation marker와 terminal 상태를 확인한다.
    이미 queued인 행도 ``updated_at``을 전진시켜 Dagster sensor가 새 run key로 다시
    제출할 수 있게 한다. marker가 있으면 coordinator가 lifecycle을 소유하므로 아무
    상태도 되돌리지 않는다.
    """
    current = await lock_feature_update_execution_guard(session, request_id)
    if current is None:
        return None
    row = (
        await session.execute(
            text(_REQUEUE_REQUEST_SQL),
            {"request_id": request_id},
        )
    ).one_or_none()
    if row is None:
        return None
    requeued = _row_to_request(row)
    if requeued.job_id is not None:
        await assert_generic_import_job_targets(session, (requeued.job_id,))
        job_row = (
            await session.execute(
                text(_REQUEUE_IMPORT_JOB_SQL),
                {"job_id": requeued.job_id},
            )
        ).one_or_none()
        if job_row is None:
            raise RuntimeError(
                "feature update request was requeued but its import job was not"
            )
    return requeued


async def touch_queued_update_request_for_lock_retry(
    session: AsyncSession,
    request_id: str,
) -> FeatureUpdateRequest | None:
    """request lease loser가 queued 행의 Dagster run key만 안전하게 전진시킨다.

    running/terminal/marker 행은 절대 건드리지 않는다. 정상 owner가 아직 CAS start 전이면
    새 sensor run이 예약될 수 있지만 request lease가 중복 실행을 막고, owner가 start한
    뒤에는 queued 조건이 깨져 추가 run key를 만들지 않는다.
    """
    row = (
        await session.execute(
            text(_TOUCH_QUEUED_REQUEST_FOR_LOCK_RETRY_SQL),
            {"request_id": request_id},
        )
    ).one_or_none()
    return _row_to_request(row) if row is not None else None


async def advance_update_request_generation_after_pre_start_failure(
    session: AsyncSession,
    request_id: str,
    *,
    expected_updated_at: datetime,
) -> FeatureUpdateRequest | None:
    """CAS start 전 실패한 queued generation의 sensor run key를 전진시킨다.

    ``queued + dagster_run_id IS NULL``인 동일 ``updated_at`` generation만
    갱신한다. running owner, 더 최신 generation, cancellation marker, terminal
    request는 모두 0행 no-op이다.
    """
    if expected_updated_at.tzinfo is None or expected_updated_at.utcoffset() is None:
        raise ValueError("expected_updated_at must be timezone-aware")
    row = (
        await session.execute(
            text(_ADVANCE_PRE_START_FAILURE_GENERATION_SQL),
            {
                "request_id": request_id,
                "expected_updated_at": expected_updated_at,
            },
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
