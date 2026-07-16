"""``ops.feature_update_requests`` lifecycle repository (ADR-045 T-206b).

Feature update request는 admin/OpenAPI가 만든 지리 범위/provider 범위 갱신
요청을 Dagster/import job과 연결하는 큐다. 본 모듈은 raw SQL만 사용하고
commit은 호출자에게 맡긴다(ADR-004).

흐름:
1. ``preview_feature_update_request`` — scope를 해석하되 아무 행도 저장하지 않음.
2. ``enqueue_feature_update_request`` — ``ops.import_jobs``와
   ``ops.feature_update_requests``를 같은 transaction에 생성.
3. ``peek_next_update_request`` → executor request/scope lease → ``start_update_request``
   CAS — lock 경합에서 running 행을 소모하지 않는 기본 실행 흐름.
4. ``start_update_request`` / ``finish_update_request`` — 단일 lifecycle 정본인
   canonical import job의 Dagster owner와 terminal 상태를 CAS로 전이.
5. ``list_update_requests`` — D-10 keyset cursor(``created_at, request_id``) 기반.
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
    FEATURE_UPDATE_REQUEST_JOB_KIND,
    ProviderDatasetOperationKey,
)
from kortravelmap.core.sync_scope import parse_canonical_sync_scope
from kortravelmap.infra.advisory_lock import try_advisory_lock
from kortravelmap.infra.jobs_repo import (
    enqueue_feature_update_request_job,
    record_import_job_event,
)
from kortravelmap.infra.scope_repo import (
    SigunguByRadiusResolver,
    canonicalize_feature_update_scope,
    count_features_matching_scope,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = [
    "FEATURE_UPDATE_JOB_KIND",
    "FeatureUpdateRequest",
    "FeatureUpdateRequestPreview",
    "FeatureUpdateRequestPage",
    "FeatureUpdateLockBusy",
    "canonicalize_feature_update_policy",
    "enqueue_feature_update_request",
    "preview_feature_update_request",
    "peek_update_requests",
    "peek_next_update_request",
    "advance_update_request_generation_after_pre_start_failure",
    "touch_queued_update_request_for_lock_retry",
    "feature_update_scope_advisory_key",
    "start_update_request",
    "finish_update_request",
    "heartbeat_feature_update_request_job",
    "set_update_request_matched_scope",
    "get_update_request",
    "lock_feature_update_execution_guard",
    "requeue_update_request_after_lock_contention",
    "list_update_requests",
]

FEATURE_UPDATE_JOB_KIND: Final[str] = FEATURE_UPDATE_REQUEST_JOB_KIND
FEATURE_UPDATE_LOCK_RETRY_AFTER_SECONDS: Final[int] = 15
MAX_FEATURE_UPDATE_PROVIDERS: Final[int] = 32
MAX_FEATURE_UPDATE_DATASET_KEYS: Final[int] = 64
MAX_FEATURE_UPDATE_FILTER_LENGTH: Final[int] = 128
DATASET_WIDE_SYNC_SCOPE: Final[str] = "dataset_wide"

_RUN_MODES: Final[frozenset[str]] = frozenset({"queued", "now"})
_FEATURE_UPDATE_POLICY_MODE: Final[str] = "refresh_existing"
_FEATURE_UPDATE_POLICY_BOOLEAN_KEYS: Final[tuple[str, ...]] = (
    "include_inactive",
    "force_provider_call",
    "dedup_after_load",
    "consistency_check_after_load",
    "prevent_provider_reactivation",
)
_FEATURE_UPDATE_POLICY_KEYS: Final[frozenset[str]] = frozenset(
    ("mode", *_FEATURE_UPDATE_POLICY_BOOLEAN_KEYS)
)
_TERMINAL_STATES: Final[frozenset[str]] = frozenset({"done", "failed"})
_MAX_LIST_LIMIT: Final[int] = 200
_MAX_PEEK_LIMIT: Final[int] = 50

_REQUEST_RETURN_COLUMNS: Final[str] = (
    "request.request_id, request.scope_type, request.scope, request.providers, "
    "request.dataset_keys, request.update_policy, request.run_mode, request.priority, "
    "job.status, request.matched_scope, request.job_id, job.dagster_run_id, "
    "job.cancellation_id, job.cancellation_requested_at, "
    "job.cancellation_requested_by, job.cancellation_reason, request.operator, "
    "request.reason, job.error_message, request.created_at, job.started_at, "
    "job.finished_at, request.generation, "
    "job.sync_scope AS effective_sync_scope, job.dispatch_requested_at"
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
    matched_scope: dict[str, Any]
    job_id: str
    dagster_run_id: str | None
    operator: str | None
    reason: str | None
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    generation: int
    cancellation_id: str | None = None
    cancellation_requested_at: datetime | None = None
    cancellation_requested_by: str | None = None
    cancellation_reason: str | None = None
    effective_sync_scope: str | None = None
    dispatch_requested_at: datetime | None = None


@dataclass(frozen=True)
class FeatureUpdateRequestPreview:
    """미리보기 결과. DB row/import job을 만들지 않는다."""

    scope_type: str
    scope: dict[str, Any]
    providers: tuple[str, ...]
    dataset_keys: tuple[str, ...]
    update_policy: dict[str, Any]
    run_mode: str
    priority: int
    matched_scope: dict[str, Any]


@dataclass(frozen=True)
class _ResolvedFeatureUpdatePlan:
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


def _validate_dagster_owner(value: str, *, field_name: str) -> None:
    if not value or value != value.strip():
        raise ValueError(f"{field_name} must be a trimmed non-empty string")


def _row_to_request(row: Any) -> FeatureUpdateRequest:
    if row.job_id is None:
        raise RuntimeError("persisted feature update request requires an import job")
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
        matched_scope=_json_dict(row.matched_scope),
        job_id=str(row.job_id),
        dagster_run_id=row.dagster_run_id,
        cancellation_id=(str(row.cancellation_id) if row.cancellation_id is not None else None),
        cancellation_requested_at=row.cancellation_requested_at,
        cancellation_requested_by=row.cancellation_requested_by,
        cancellation_reason=row.cancellation_reason,
        operator=row.operator,
        reason=row.reason,
        error_message=row.error_message,
        created_at=row.created_at,
        started_at=row.started_at,
        finished_at=row.finished_at,
        generation=int(row.generation),
        effective_sync_scope=row.effective_sync_scope,
        dispatch_requested_at=row.dispatch_requested_at,
    )


def _scope_type(scope: Mapping[str, Any]) -> str:
    scope_type = scope.get("type")
    if not isinstance(scope_type, str) or not scope_type:
        raise ValueError("scope requires non-empty type")
    return scope_type


def _normalize_strings(
    values: Sequence[str] | None,
    *,
    field_name: str,
    max_items: int,
) -> tuple[str, ...]:
    if values is None:
        return ()
    if isinstance(values, (str, bytes)) or len(values) > max_items:
        raise ValueError(f"{field_name} must contain at most {max_items} strings")
    normalized: list[str] = []
    seen: set[str] = set()
    for item in values:
        if not isinstance(item, str):
            raise ValueError(f"{field_name} items must be strings")
        canonical = item.strip()
        if not canonical or len(canonical) > MAX_FEATURE_UPDATE_FILTER_LENGTH:
            raise ValueError(
                f"{field_name} items must contain 1..{MAX_FEATURE_UPDATE_FILTER_LENGTH} "
                "non-whitespace characters"
            )
        if canonical in seen:
            raise ValueError(f"{field_name} items must be unique")
        seen.add(canonical)
        normalized.append(canonical)
    return tuple(normalized)


def _validate_run_mode(run_mode: str) -> None:
    if run_mode not in _RUN_MODES:
        raise ValueError(f"run_mode must be one of {sorted(_RUN_MODES)}")


def _effective_sync_scope(
    *,
    scope_type: str,
    scope: Mapping[str, Any],
    supplied: str | None,
) -> str | None:
    """request JSON과 typed job identity가 공유할 canonical sync scope를 검증한다."""
    if scope_type != "provider_dataset":
        if supplied is not None:
            raise ValueError("effective_sync_scope is only valid for provider_dataset scope")
        return None

    explicit = scope.get("sync_scope")
    if supplied is None:
        raise ValueError("provider_dataset scope requires an explicit effective_sync_scope")
    value = supplied
    try:
        parse_canonical_sync_scope(value)
    except ValueError as exc:
        raise ValueError(
            "effective_sync_scope must be dataset_wide, target_grids, or "
            "external_system:<exact trimmed non-empty name>"
        ) from exc
    if len(value) > 128:
        raise ValueError("effective_sync_scope must contain at most 128 characters")
    if isinstance(explicit, str) and value != explicit:
        raise ValueError("effective_sync_scope must equal an explicit requested sync_scope")
    return value


def canonicalize_feature_update_policy(
    update_policy: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Typed API와 DB CHECK가 공유하는 canonical update policy를 만든다."""

    if update_policy is None:
        return {}
    if not isinstance(update_policy, MappingABC):
        raise ValueError("update_policy must be an object")

    unknown_keys = set(update_policy) - _FEATURE_UPDATE_POLICY_KEYS
    if unknown_keys:
        unknown = ", ".join(sorted(str(key) for key in unknown_keys))
        raise ValueError(f"update_policy contains unknown keys: {unknown}")

    canonical: dict[str, Any] = {}
    mode = update_policy.get("mode")
    if mode is not None:
        if mode != _FEATURE_UPDATE_POLICY_MODE:
            raise ValueError(
                f"update_policy.mode must be {_FEATURE_UPDATE_POLICY_MODE!r}"
            )
        canonical["mode"] = mode

    for key in _FEATURE_UPDATE_POLICY_BOOLEAN_KEYS:
        value = update_policy.get(key)
        if value is None:
            continue
        if type(value) is not bool:
            raise ValueError(f"update_policy.{key} must be a boolean")
        canonical[key] = value
    return canonical


def _json_param(value: Mapping[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _canonical_jsonable(value: Any) -> Any:
    if isinstance(value, MappingABC):
        return {
            str(key): _canonical_jsonable(value[key])
            for key in sorted(value, key=lambda item: str(item))
        }
    if isinstance(value, SequenceABC) and not isinstance(value, (str, bytes, bytearray)):
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
    canonical_scope = canonicalize_feature_update_scope(scope)
    if canonical_scope["type"] != scope_type:
        raise ValueError("scope_type must equal scope.type")
    provider_values = _normalize_strings(
        providers,
        field_name="providers",
        max_items=MAX_FEATURE_UPDATE_PROVIDERS,
    )
    dataset_values = _normalize_strings(
        dataset_keys,
        field_name="dataset_keys",
        max_items=MAX_FEATURE_UPDATE_DATASET_KEYS,
    )
    if scope_type == "provider_dataset" and (provider_values or dataset_values):
        raise ValueError(
            "provider_dataset scope must not repeat providers or dataset_keys filters"
        )
    payload = {
        "scope_type": scope_type,
        "scope": _canonical_jsonable(canonical_scope),
        "providers": sorted(provider_values),
        "dataset_keys": sorted(dataset_values),
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
WITH request AS (
    INSERT INTO ops.feature_update_requests (
        request_id, scope_type, scope, providers, dataset_keys, update_policy,
        run_mode, priority, matched_scope, job_id, operator, reason
    ) SELECT
        CAST(:request_id AS uuid), :scope_type, CAST(:scope AS jsonb),
        CAST(:providers AS text[]), CAST(:dataset_keys AS text[]),
        CAST(:update_policy AS jsonb), :run_mode, :priority,
        CAST(:matched_scope AS jsonb), CAST(:job_id AS uuid), :operator, :reason
    WHERE EXISTS (
        SELECT 1
        FROM ops.import_jobs AS identity_job
        WHERE identity_job.job_id = CAST(:job_id AS uuid)
          AND identity_job.kind = 'feature_update_request'
          AND identity_job.status = 'queued'
          AND identity_job.cancellation_id IS NULL
    )
    RETURNING *
)
SELECT {_REQUEST_RETURN_COLUMNS}
FROM request
JOIN ops.import_jobs AS job ON job.job_id = request.job_id
"""

_GET_REQUEST_SQL: Final[str] = f"""
SELECT {_REQUEST_RETURN_COLUMNS}
FROM ops.feature_update_requests AS request
JOIN ops.import_jobs AS job ON job.job_id = request.job_id
WHERE request.request_id = CAST(:request_id AS uuid)
"""

_LOCK_EXECUTION_REQUEST_SQL: Final[str] = f"""
SELECT {_REQUEST_RETURN_COLUMNS}
FROM ops.feature_update_requests AS request
JOIN ops.import_jobs AS job ON job.job_id = request.job_id
WHERE request.request_id = CAST(:request_id AS uuid)
  AND request.generation = CAST(:expected_generation AS bigint)
  AND job.kind = 'feature_update_request'
  AND job.cancellation_id IS NULL
  AND (
    (job.status = 'queued' AND job.dagster_run_id IS NULL)
    OR (
      job.status = 'running'
      AND job.dagster_run_id = CAST(:owner_dagster_run_id AS text)
    )
  )
FOR UPDATE OF request, job
"""

_PEEK_REQUEST_SQL: Final[str] = f"""
SELECT {_REQUEST_RETURN_COLUMNS}
FROM ops.feature_update_requests AS request
JOIN ops.import_jobs AS job ON job.job_id = request.job_id
WHERE job.kind = 'feature_update_request'
  AND job.status = 'queued'
  AND job.dagster_run_id IS NULL
  AND job.cancellation_id IS NULL
ORDER BY (job.dispatch_requested_at IS NOT NULL) DESC,
         request.priority DESC,
         job.dispatch_requested_at NULLS LAST,
         request.created_at,
         request.request_id
LIMIT :limit
"""

_START_REQUEST_SQL: Final[str] = f"""
WITH locked AS (
    SELECT request.request_id, request.job_id
    FROM ops.feature_update_requests AS request
    JOIN ops.import_jobs AS job ON job.job_id = request.job_id
    WHERE request.request_id = CAST(:request_id AS uuid)
      AND request.generation = CAST(:expected_generation AS bigint)
      AND job.kind = 'feature_update_request'
      AND job.cancellation_id IS NULL
      AND (
        (job.status = 'queued' AND job.dagster_run_id IS NULL)
        OR (
          job.status = 'running'
          AND job.dagster_run_id = CAST(:dagster_run_id AS text)
        )
      )
    FOR UPDATE OF request, job
),
job AS (
    UPDATE ops.import_jobs AS mutable_job
    SET status = 'running',
        started_at = COALESCE(mutable_job.started_at, now()),
        heartbeat_at = now(),
        current_stage = COALESCE(mutable_job.current_stage, 'started'),
        dagster_run_id = CAST(:dagster_run_id AS text)
    FROM locked
    WHERE mutable_job.job_id = locked.job_id
    RETURNING mutable_job.*
)
SELECT {_REQUEST_RETURN_COLUMNS}
FROM ops.feature_update_requests AS request
JOIN job ON job.job_id = request.job_id
"""

_REQUEUE_REQUEST_SQL: Final[str] = f"""
WITH locked AS (
    SELECT request.request_id, request.job_id
    FROM ops.feature_update_requests AS request
    JOIN ops.import_jobs AS job ON job.job_id = request.job_id
    WHERE request.request_id = CAST(:request_id AS uuid)
      AND request.generation = CAST(:expected_generation AS bigint)
      AND job.kind = 'feature_update_request'
      AND job.cancellation_id IS NULL
      AND (
        (job.status = 'queued' AND job.dagster_run_id IS NULL)
        OR (
          job.status = 'running'
          AND job.dagster_run_id = CAST(:caller_dagster_run_id AS text)
        )
      )
    FOR UPDATE OF request, job
),
updated_job AS (
    UPDATE ops.import_jobs AS job
    SET status = 'queued',
        progress = 0,
        current_stage = NULL,
        dagster_run_id = NULL,
        error_message = NULL,
        started_at = NULL,
        heartbeat_at = NULL,
        finished_at = NULL
    FROM locked
    WHERE job.job_id = locked.job_id
    RETURNING job.*
),
request AS (
    UPDATE ops.feature_update_requests AS mutable_request
    SET generation = mutable_request.generation + 1
    FROM updated_job AS job
    WHERE mutable_request.job_id = job.job_id
    RETURNING mutable_request.*
)
SELECT {_REQUEST_RETURN_COLUMNS}
FROM request
JOIN updated_job AS job ON job.job_id = request.job_id
"""

_SET_MATCHED_SCOPE_SQL: Final[str] = f"""
WITH locked AS (
    SELECT request.request_id, request.job_id
    FROM ops.feature_update_requests AS request
    JOIN ops.import_jobs AS job ON job.job_id = request.job_id
    WHERE request.request_id = CAST(:request_id AS uuid)
      AND request.generation = CAST(:expected_generation AS bigint)
      AND job.kind = 'feature_update_request'
      AND job.status = 'running'
      AND job.dagster_run_id = CAST(:owner_dagster_run_id AS text)
      AND job.cancellation_id IS NULL
    FOR UPDATE OF request, job
),
request AS (
    UPDATE ops.feature_update_requests AS mutable_request
    SET matched_scope = CAST(:matched_scope AS jsonb)
    FROM locked
    WHERE mutable_request.request_id = locked.request_id
    RETURNING mutable_request.*
)
SELECT {_REQUEST_RETURN_COLUMNS}
FROM request
JOIN ops.import_jobs AS job ON job.job_id = request.job_id
"""

_FINISH_REQUEST_SQL: Final[str] = f"""
WITH locked AS (
    SELECT request.request_id, request.job_id
    FROM ops.feature_update_requests AS request
    JOIN ops.import_jobs AS job ON job.job_id = request.job_id
    WHERE request.request_id = CAST(:request_id AS uuid)
      AND request.generation = CAST(:expected_generation AS bigint)
      AND job.kind = 'feature_update_request'
      AND job.status = 'running'
      AND job.cancellation_id IS NULL
      AND job.dagster_run_id = CAST(:owner_dagster_run_id AS text)
    FOR UPDATE OF request, job
),
job AS (
    UPDATE ops.import_jobs AS mutable_job
    SET status = CAST(:status AS text),
        finished_at = now(),
        heartbeat_at = now(),
        error_message = CAST(:error_message AS text),
        progress = CASE
          WHEN CAST(:status AS text) = 'done' THEN 100
          ELSE mutable_job.progress
        END
    FROM locked
    WHERE mutable_job.job_id = locked.job_id
    RETURNING mutable_job.*
)
SELECT {_REQUEST_RETURN_COLUMNS}
FROM ops.feature_update_requests AS request
JOIN job ON job.job_id = request.job_id
"""

_HEARTBEAT_IMPORT_JOB_SQL: Final[str] = """
WITH locked AS (
    SELECT request.request_id, request.job_id
    FROM ops.feature_update_requests AS request
    JOIN ops.import_jobs AS job ON job.job_id = request.job_id
    WHERE job.job_id = CAST(:job_id AS uuid)
      AND request.generation = CAST(:expected_generation AS bigint)
      AND job.kind = 'feature_update_request'
      AND job.status = 'running'
      AND job.dagster_run_id = CAST(:owner_dagster_run_id AS text)
      AND job.cancellation_id IS NULL
    FOR UPDATE OF request, job
),
job AS (
    UPDATE ops.import_jobs AS mutable_job
    SET heartbeat_at = now(),
        progress = COALESCE(:progress, mutable_job.progress),
        current_stage = COALESCE(:current_stage, mutable_job.current_stage)
    FROM locked
    WHERE mutable_job.job_id = locked.job_id
    RETURNING mutable_job.*
)
SELECT job.job_id, job.status, job.progress, job.current_stage
FROM job
"""

_TOUCH_QUEUED_REQUEST_FOR_LOCK_RETRY_SQL: Final[str] = f"""
WITH locked AS (
    SELECT request.request_id, request.job_id
    FROM ops.feature_update_requests AS request
    JOIN ops.import_jobs AS job ON job.job_id = request.job_id
    WHERE request.request_id = CAST(:request_id AS uuid)
      AND request.generation = CAST(:expected_generation AS bigint)
      AND job.kind = 'feature_update_request'
      AND job.status = 'queued'
      AND job.dagster_run_id IS NULL
      AND job.cancellation_id IS NULL
    FOR UPDATE OF request, job
),
request AS (
    UPDATE ops.feature_update_requests AS mutable_request
    SET generation = mutable_request.generation + 1
    FROM locked
    WHERE mutable_request.request_id = locked.request_id
    RETURNING mutable_request.*
)
SELECT {_REQUEST_RETURN_COLUMNS}
FROM request
JOIN ops.import_jobs AS job ON job.job_id = request.job_id
"""

_ADVANCE_PRE_START_FAILURE_GENERATION_SQL: Final[str] = (
    _TOUCH_QUEUED_REQUEST_FOR_LOCK_RETRY_SQL
)

_LIST_REQUEST_FILTERS_SQL: Final[str] = """
WHERE (CAST(:status AS text) IS NULL OR job.status = CAST(:status AS text))
  AND (
    CAST(:scope_type AS text) IS NULL
    OR request.scope_type = CAST(:scope_type AS text)
  )
  AND (
    CAST(:created_from AS timestamptz) IS NULL
    OR request.created_at >= CAST(:created_from AS timestamptz)
  )
  AND (
    CAST(:created_to AS timestamptz) IS NULL
    OR request.created_at <= CAST(:created_to AS timestamptz)
  )
  AND (
    CAST(:cursor_created_at AS timestamptz) IS NULL
    OR (request.created_at, request.request_id) < (
        CAST(:cursor_created_at AS timestamptz),
        CAST(:cursor_request_id AS uuid)
    )
  )
ORDER BY request.created_at DESC, request.request_id DESC
LIMIT :limit_plus_one
"""


def _list_requests_sql(*, candidate_sql: str | None = None) -> str:
    candidate_cte = f"WITH candidate_request_ids AS ({candidate_sql})" if candidate_sql else ""
    candidate_join = (
        "JOIN candidate_request_ids AS candidate "
        "ON candidate.request_id = request.request_id"
        if candidate_sql
        else ""
    )
    return f"""
{candidate_cte}
SELECT {_REQUEST_RETURN_COLUMNS}
FROM ops.feature_update_requests AS request
JOIN ops.import_jobs AS job ON job.job_id = request.job_id
{candidate_join}
{_LIST_REQUEST_FILTERS_SQL}
"""


_LIST_REQUESTS_SQL: Final[str] = _list_requests_sql()
_LIST_PROVIDER_REQUESTS_SQL: Final[str] = _list_requests_sql(
    candidate_sql="""
    SELECT request.request_id
    FROM ops.feature_update_requests AS request
    WHERE request.scope_type <> 'provider_dataset'
      AND request.providers @> CAST(:provider_filter AS text[])
    UNION ALL
    SELECT request.request_id
    FROM ops.import_jobs AS identity_job
    JOIN ops.feature_update_requests AS request ON request.job_id = identity_job.job_id
    WHERE request.scope_type = 'provider_dataset'
      AND identity_job.provider = CAST(:provider AS text)
    """,
)
_LIST_DATASET_REQUESTS_SQL: Final[str] = _list_requests_sql(
    candidate_sql="""
    SELECT request.request_id
    FROM ops.feature_update_requests AS request
    WHERE request.scope_type <> 'provider_dataset'
      AND request.dataset_keys @> CAST(:dataset_key_filter AS text[])
    UNION ALL
    SELECT request.request_id
    FROM ops.import_jobs AS identity_job
    JOIN ops.feature_update_requests AS request ON request.job_id = identity_job.job_id
    WHERE request.scope_type = 'provider_dataset'
      AND identity_job.dataset_key = CAST(:dataset_key AS text)
    """,
)
_LIST_PROVIDER_DATASET_REQUESTS_SQL: Final[str] = _list_requests_sql(
    candidate_sql="""
    SELECT request.request_id
    FROM ops.feature_update_requests AS request
    WHERE request.scope_type <> 'provider_dataset'
      AND request.providers @> CAST(:provider_filter AS text[])
      AND request.dataset_keys @> CAST(:dataset_key_filter AS text[])
    UNION ALL
    SELECT request.request_id
    FROM ops.import_jobs AS identity_job
    JOIN ops.feature_update_requests AS request ON request.job_id = identity_job.job_id
    WHERE request.scope_type = 'provider_dataset'
      AND identity_job.provider = CAST(:provider AS text)
      AND identity_job.dataset_key = CAST(:dataset_key AS text)
    """,
)

_LIST_DIRECT_REQUESTS_SQL: Final[str] = f"""
SELECT {_REQUEST_RETURN_COLUMNS}
FROM ops.import_jobs AS job
JOIN ops.feature_update_requests AS request ON request.job_id = job.job_id
WHERE job.provider = CAST(:provider AS text)
  AND job.dataset_key = CAST(:dataset_key AS text)
  AND request.scope_type = 'provider_dataset'
  AND (CAST(:status AS text) IS NULL OR job.status = CAST(:status AS text))
  AND (
    CAST(:created_from AS timestamptz) IS NULL
    OR request.created_at >= CAST(:created_from AS timestamptz)
  )
  AND (
    CAST(:created_to AS timestamptz) IS NULL
    OR request.created_at <= CAST(:created_to AS timestamptz)
  )
  AND (
    CAST(:cursor_created_at AS timestamptz) IS NULL
    OR (request.created_at, request.request_id) < (
        CAST(:cursor_created_at AS timestamptz),
        CAST(:cursor_request_id AS uuid)
    )
  )
ORDER BY request.created_at DESC, request.request_id DESC
LIMIT :limit_plus_one
"""


async def _resolve_feature_update_plan(
    session: AsyncSession,
    *,
    scope: Mapping[str, Any],
    providers: Sequence[str] | None = None,
    dataset_keys: Sequence[str] | None = None,
    update_policy: Mapping[str, Any] | None = None,
    run_mode: str = "queued",
    priority: int = 50,
    sigungu_resolver: SigunguByRadiusResolver | None = None,
) -> _ResolvedFeatureUpdatePlan:
    _validate_run_mode(run_mode)
    scope_payload = canonicalize_feature_update_scope(scope)
    scope_type = _scope_type(scope_payload)
    provider_values = _normalize_strings(
        providers,
        field_name="providers",
        max_items=MAX_FEATURE_UPDATE_PROVIDERS,
    )
    dataset_values = _normalize_strings(
        dataset_keys,
        field_name="dataset_keys",
        max_items=MAX_FEATURE_UPDATE_DATASET_KEYS,
    )
    if scope_type == "provider_dataset" and (provider_values or dataset_values):
        raise ValueError(
            "provider_dataset scope must not repeat providers or dataset_keys filters"
        )
    if isinstance(priority, bool) or not isinstance(priority, int) or not 0 <= priority <= 1000:
        raise ValueError("priority must be an integer between 0 and 1000")
    policy = canonicalize_feature_update_policy(update_policy)
    resolution = await count_features_matching_scope(
        session, scope_payload, sigungu_resolver=sigungu_resolver
    )
    matched_scope = resolution.matched_scope()
    return _ResolvedFeatureUpdatePlan(
        scope_type=scope_type,
        scope=scope_payload,
        providers=provider_values,
        dataset_keys=dataset_values,
        update_policy=policy,
        run_mode=run_mode,
        priority=priority,
        matched_scope=matched_scope,
    )


async def preview_feature_update_request(
    session: AsyncSession,
    *,
    scope: Mapping[str, Any],
    providers: Sequence[str] | None = None,
    dataset_keys: Sequence[str] | None = None,
    update_policy: Mapping[str, Any] | None = None,
    run_mode: str = "queued",
    priority: int = 50,
    sigungu_resolver: SigunguByRadiusResolver | None = None,
) -> FeatureUpdateRequestPreview:
    """scope를 해석하되 request/import job은 만들지 않는다."""
    plan = await _resolve_feature_update_plan(
        session,
        scope=scope,
        providers=providers,
        dataset_keys=dataset_keys,
        update_policy=update_policy,
        run_mode=run_mode,
        priority=priority,
        sigungu_resolver=sigungu_resolver,
    )
    return FeatureUpdateRequestPreview(
        scope_type=plan.scope_type,
        scope=plan.scope,
        providers=plan.providers,
        dataset_keys=plan.dataset_keys,
        update_policy=plan.update_policy,
        run_mode=plan.run_mode,
        priority=plan.priority,
        matched_scope=plan.matched_scope,
    )


async def enqueue_feature_update_request(
    session: AsyncSession,
    *,
    scope: Mapping[str, Any],
    effective_sync_scope: str | None = None,
    providers: Sequence[str] | None = None,
    dataset_keys: Sequence[str] | None = None,
    update_policy: Mapping[str, Any] | None = None,
    run_mode: str = "queued",
    priority: int = 50,
    operator: str | None = None,
    reason: str | None = None,
    sigungu_resolver: SigunguByRadiusResolver | None = None,
) -> FeatureUpdateRequest:
    """정규화한 scope와 canonical import job을 한 요청으로 영속화한다."""
    plan = await _resolve_feature_update_plan(
        session,
        scope=scope,
        providers=providers,
        dataset_keys=dataset_keys,
        update_policy=update_policy,
        run_mode=run_mode,
        priority=priority,
        sigungu_resolver=sigungu_resolver,
    )
    scope_type = plan.scope_type
    scope_payload = plan.scope
    provider_values = plan.providers
    dataset_values = plan.dataset_keys
    policy = plan.update_policy
    matched_scope = plan.matched_scope
    canonical_sync_scope = _effective_sync_scope(
        scope_type=scope_type,
        scope=scope_payload,
        supplied=effective_sync_scope,
    )

    scope_lock_key = feature_update_scope_advisory_key(
        scope_type=scope_type,
        scope=scope_payload,
        providers=provider_values,
        dataset_keys=dataset_values,
    )
    if plan.run_mode == "now":
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
    job = await enqueue_feature_update_request_job(
        session,
        provider_dataset=provider_dataset,
        effective_sync_scope=canonical_sync_scope,
        dispatch_requested=plan.run_mode == "now",
    )
    row = (
        await session.execute(
            text(_INSERT_REQUEST_SQL),
            {
                "request_id": request_id,
                "scope_type": scope_type,
                "scope": _json_param(scope_payload),
                "providers": list(provider_values),
                "dataset_keys": list(dataset_values),
                "update_policy": _json_param(policy),
                "run_mode": plan.run_mode,
                "priority": plan.priority,
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
        await session.execute(text(_PEEK_REQUEST_SQL), {"limit": min(limit, _MAX_PEEK_LIMIT)})
    ).all()
    return tuple(_row_to_request(row) for row in rows)


async def peek_next_update_request(
    session: AsyncSession,
) -> FeatureUpdateRequest | None:
    """claim 순서상 다음 queued request를 상태 변경 없이 조회한다."""
    requests = await peek_update_requests(session, limit=1)
    return requests[0] if requests else None


async def start_update_request(
    session: AsyncSession,
    request_id: str,
    *,
    dagster_run_id: str,
    expected_generation: int,
) -> FeatureUpdateRequest | None:
    """queued generation을 claim하거나 같은 running owner를 멱등 재확인한다.

    다른 ``dagster_run_id``가 소유한 running request는 절대 덮지 않는다. queued
    transition에는 sensor가 고정한 ``expected_generation``을 반드시 적용한다.
    """
    _validate_dagster_owner(dagster_run_id, field_name="dagster_run_id")
    if expected_generation <= 0:
        raise ValueError("expected_generation must be positive")
    row = (
        await session.execute(
            text(_START_REQUEST_SQL),
            {
                "request_id": request_id,
                "dagster_run_id": dagster_run_id,
                "expected_generation": expected_generation,
            },
        )
    ).one_or_none()
    return _row_to_request(row) if row is not None else None


async def finish_update_request(
    session: AsyncSession,
    request_id: str,
    *,
    status: str = "done",
    owner_dagster_run_id: str,
    expected_generation: int,
    error_message: str | None = None,
) -> FeatureUpdateRequest | None:
    """동일 generation/run owner의 running canonical job만 terminal로 닫는다."""
    if status not in _TERMINAL_STATES:
        raise ValueError(f"status must be one of {sorted(_TERMINAL_STATES)}")
    _validate_dagster_owner(
        owner_dagster_run_id,
        field_name="owner_dagster_run_id",
    )
    if expected_generation <= 0:
        raise ValueError("expected_generation must be positive")
    row = (
        await session.execute(
            text(_FINISH_REQUEST_SQL),
            {
                "request_id": request_id,
                "status": status,
                "owner_dagster_run_id": owner_dagster_run_id,
                "expected_generation": expected_generation,
                "error_message": error_message,
            },
        )
    ).one_or_none()
    return _row_to_request(row) if row is not None else None


async def set_update_request_matched_scope(
    session: AsyncSession,
    request_id: str,
    *,
    matched_scope: Mapping[str, Any],
    expected_generation: int,
    owner_dagster_run_id: str,
) -> FeatureUpdateRequest | None:
    """동일 generation/run owner가 실행 중일 때만 scope 해석 결과를 저장한다."""
    if expected_generation <= 0:
        raise ValueError("expected_generation must be positive")
    _validate_dagster_owner(
        owner_dagster_run_id,
        field_name="owner_dagster_run_id",
    )
    row = (
        await session.execute(
            text(_SET_MATCHED_SCOPE_SQL),
            {
                "request_id": request_id,
                "matched_scope": _json_param(matched_scope),
                "expected_generation": expected_generation,
                "owner_dagster_run_id": owner_dagster_run_id,
            },
        )
    ).one_or_none()
    return _row_to_request(row) if row is not None else None


async def get_update_request(
    session: AsyncSession,
    request_id: str,
) -> FeatureUpdateRequest | None:
    """request id로 단건 조회."""
    row = (await session.execute(text(_GET_REQUEST_SQL), {"request_id": request_id})).one_or_none()
    return _row_to_request(row) if row is not None else None


async def lock_feature_update_execution_guard(
    session: AsyncSession,
    request_id: str,
    *,
    expected_generation: int,
    owner_dagster_run_id: str,
) -> FeatureUpdateRequest | None:
    """실행 phase 직전에 request→job을 잠그고 marker/status를 검증한다.

    취소 coordinator와 같은 base row 순서를 사용한다. 반환값이 ``None``이면
    현재 transaction에서 provider runner나 lifecycle write를 시작하면 안 된다.
    """
    if expected_generation <= 0:
        raise ValueError("expected_generation must be positive")
    _validate_dagster_owner(
        owner_dagster_run_id,
        field_name="owner_dagster_run_id",
    )
    row = (
        await session.execute(
            text(_LOCK_EXECUTION_REQUEST_SQL),
            {
                "request_id": request_id,
                "expected_generation": expected_generation,
                "owner_dagster_run_id": owner_dagster_run_id,
            },
        )
    ).one_or_none()
    if row is None:
        return None
    request = _row_to_request(row)
    if request.status not in {"queued", "running"} or request.cancellation_id is not None:
        return None
    return request


async def requeue_update_request_after_lock_contention(
    session: AsyncSession,
    request_id: str,
    *,
    expected_generation: int,
    caller_dagster_run_id: str,
) -> FeatureUpdateRequest | None:
    """request lease를 가진 executor가 scope 경합 대상을 다시 실행 가능하게 둔다.

    한 generation의 최초 loser만 canonical job을 queued로 돌리고 generation을 +1한다.
    running job은 동일 ``caller_dagster_run_id`` owner일 때만 되돌릴 수 있다.
    """
    if expected_generation <= 0:
        raise ValueError("expected_generation must be positive")
    _validate_dagster_owner(
        caller_dagster_run_id,
        field_name="caller_dagster_run_id",
    )
    row = (
        await session.execute(
            text(_REQUEUE_REQUEST_SQL),
            {
                "request_id": request_id,
                "expected_generation": expected_generation,
                "caller_dagster_run_id": caller_dagster_run_id,
            },
        )
    ).one_or_none()
    return _row_to_request(row) if row is not None else None


async def heartbeat_feature_update_request_job(
    session: AsyncSession,
    job_id: str,
    *,
    expected_generation: int,
    owner_dagster_run_id: str,
    progress: int | None = None,
    current_stage: str | None = None,
) -> bool:
    """canonical request job의 진행 정보만 갱신한다."""
    if expected_generation <= 0:
        raise ValueError("expected_generation must be positive")
    _validate_dagster_owner(
        owner_dagster_run_id,
        field_name="owner_dagster_run_id",
    )
    row = (
        await session.execute(
            text(_HEARTBEAT_IMPORT_JOB_SQL),
            {
                "job_id": job_id,
                "expected_generation": expected_generation,
                "owner_dagster_run_id": owner_dagster_run_id,
                "progress": progress,
                "current_stage": current_stage,
            },
        )
    ).one_or_none()
    if row is None:
        return False
    if progress is not None or current_stage is not None:
        await record_import_job_event(
            session,
            str(row.job_id),
            code="job.heartbeat",
            message="import job heartbeat",
            payload={"status": str(row.status), "progress": int(row.progress)},
            stage=str(row.current_stage) if row.current_stage is not None else None,
        )
    return True


async def touch_queued_update_request_for_lock_retry(
    session: AsyncSession,
    request_id: str,
    *,
    expected_generation: int,
) -> FeatureUpdateRequest | None:
    """request lease loser가 queued 행의 Dagster run key만 안전하게 전진시킨다.

    동일 queued generation의 최초 loser만 +1한다. running/terminal/marker 행과 stale
    generation은 절대 건드리지 않는다.
    """
    if expected_generation <= 0:
        raise ValueError("expected_generation must be positive")
    row = (
        await session.execute(
            text(_TOUCH_QUEUED_REQUEST_FOR_LOCK_RETRY_SQL),
            {
                "request_id": request_id,
                "expected_generation": expected_generation,
            },
        )
    ).one_or_none()
    return _row_to_request(row) if row is not None else None


async def advance_update_request_generation_after_pre_start_failure(
    session: AsyncSession,
    request_id: str,
    *,
    expected_generation: int,
) -> FeatureUpdateRequest | None:
    """CAS start 전 실패한 queued generation의 sensor run key를 전진시킨다.

    ``queued + dagster_run_id IS NULL``인 동일 정수 generation만
    갱신한다. running owner, 더 최신 generation, cancellation marker, terminal
    request는 모두 0행 no-op이다.
    """
    if expected_generation <= 0:
        raise ValueError("expected_generation must be positive")
    row = (
        await session.execute(
            text(_ADVANCE_PRE_START_FAILURE_GENERATION_SQL),
            {
                "request_id": request_id,
                "expected_generation": expected_generation,
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
    if scope_type == "provider_dataset" and provider is not None and dataset_key is not None:
        query = _LIST_DIRECT_REQUESTS_SQL
    elif provider is not None and dataset_key is not None:
        query = _LIST_PROVIDER_DATASET_REQUESTS_SQL
    elif provider is not None:
        query = _LIST_PROVIDER_REQUESTS_SQL
    elif dataset_key is not None:
        query = _LIST_DATASET_REQUESTS_SQL
    else:
        query = _LIST_REQUESTS_SQL
    rows = (
        await session.execute(
            text(query),
            {
                "status": status,
                "scope_type": scope_type,
                "provider": provider,
                "provider_filter": [provider] if provider else None,
                "dataset_key": dataset_key,
                "dataset_key_filter": [dataset_key] if dataset_key else None,
                "created_from": created_from,
                "created_to": created_to,
                "cursor_created_at": cursor_created_at,
                "cursor_request_id": cursor_request_id,
                "limit_plus_one": effective_limit + 1,
            },
        )
    ).all()
    requests = tuple(_row_to_request(row) for row in rows[:effective_limit])
    next_cursor = _encode_cursor(requests[-1]) if len(rows) > effective_limit and requests else None
    return FeatureUpdateRequestPage(items=requests, next_cursor=next_cursor)
