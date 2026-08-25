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

from kortravelmap.core.feature_operation import FEATURE_UPDATE_REQUEST_JOB_KIND
from kortravelmap.core.sync_scope import parse_canonical_sync_scope
from kortravelmap.infra.advisory_lock import advisory_lock_key, try_advisory_lock
from kortravelmap.infra.jobs_repo import (
    ImportJobDatasetTarget,
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
    "FeatureUpdateRequestDataset",
    "FeatureUpdateRequest",
    "FeatureUpdateRequestIdempotency",
    "FeatureUpdateRequestPreview",
    "FeatureUpdateRequestPage",
    "FeatureUpdateLockBusy",
    "canonicalize_feature_update_policy",
    "execution_scope_for_request",
    "enqueue_cache_target_service_refresh_request",
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
    "get_update_request_by_job_id",
    "create_feature_update_request_idempotency",
    "get_feature_update_request_idempotency",
    "lock_feature_update_request_idempotency",
    "lock_feature_update_execution_guard",
    "requeue_update_request_after_lock_contention",
    "list_update_requests",
]

FEATURE_UPDATE_JOB_KIND: Final[str] = FEATURE_UPDATE_REQUEST_JOB_KIND
FEATURE_UPDATE_LOCK_RETRY_AFTER_SECONDS: Final[int] = 15
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
_RELAY_OWNED_EXTERNAL_SYSTEM: Final[str] = "pinvi"
_SERVICE_OWNED_CACHE_TARGET_REQUEST_MESSAGE: Final[str] = (
    "PinVi cache target refresh는 cache-target ServiceToken writer로만 요청할 수 있습니다."
)

_REQUEST_RETURN_COLUMNS: Final[str] = (
    "request.request_id, request.scope_type, request.scope, "
    "request.dataset_membership_mode, request.update_policy, request.run_mode, request.priority, "
    "job.status, request.matched_scope, request.job_id, job.dagster_run_id, "
    "job.cancellation_id, job.cancellation_requested_at, "
    "job.cancellation_requested_by, job.cancellation_reason, request.operator, "
    "request.reason, job.error_message, request.created_at, job.started_at, "
    "job.finished_at, request.generation, job.dispatch_requested_at, "
    "member.feature_update_request_dataset_id, member.provider_dataset_id, "
    "member.sync_scope, member.operation_key, dataset.provider, dataset.dataset_key"
)

_REQUEST_MEMBERSHIP_JOINS: Final[str] = """
LEFT JOIN ops.feature_update_request_datasets AS member
  ON member.request_id = request.request_id
LEFT JOIN provider_sync.provider_datasets AS dataset
  ON dataset.provider_dataset_id = member.provider_dataset_id
"""

_ACTIVE_DATASET_MEMBERSHIPS_SQL: Final[str] = """
WITH requested AS (
    SELECT target.provider_dataset_id, target.sync_scope, target.operation_key
    FROM jsonb_to_recordset(CAST(:dataset_memberships AS jsonb)) AS target(
        provider_dataset_id bigint,
        sync_scope text,
        operation_key text
    )
)
SELECT
    requested.provider_dataset_id,
    requested.sync_scope,
    requested.operation_key,
    dataset.provider,
    dataset.dataset_key
FROM requested
JOIN provider_sync.provider_datasets AS dataset
  ON dataset.provider_dataset_id = requested.provider_dataset_id
JOIN provider_sync.provider_dataset_operations AS operation
  ON operation.provider_dataset_id = requested.provider_dataset_id
 AND operation.operation_kind = 'refresh'
 AND operation.is_enabled
JOIN provider_sync.provider_dataset_operation_scopes AS operation_scope
  ON operation_scope.provider_dataset_id = operation.provider_dataset_id
 AND operation_scope.operation_key = operation.operation_key
 AND operation_scope.operation_kind = operation.operation_kind
 AND operation_scope.sync_scope = requested.sync_scope
 AND operation_scope.operation_key = requested.operation_key
WHERE dataset.is_active
ORDER BY requested.provider_dataset_id, requested.sync_scope
"""


@dataclass(frozen=True)
class FeatureUpdateRequest:
    """DB에 저장된 ``ops.feature_update_requests`` 행."""

    request_id: str
    scope_type: str
    scope: dict[str, Any]
    dataset_membership_mode: str
    dataset_memberships: tuple[FeatureUpdateRequestDataset, ...]
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
    dispatch_requested_at: datetime | None = None


@dataclass(frozen=True)
class FeatureUpdateRequestDataset:
    """요청 생성 시점에 고정된 canonical dataset+scope membership.

    ``provider``/``dataset_key``는 표시·runner 전달을 위한 catalog projection일 뿐
    identity나 writer 입력이 아니다. 영속 identity는 언제나
    ``provider_dataset_id + sync_scope + operation_key``다.
    """

    feature_update_request_dataset_id: str | None
    provider_dataset_id: int
    sync_scope: str
    provider: str
    dataset_key: str
    operation_key: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.provider_dataset_id, int)
            or isinstance(self.provider_dataset_id, bool)
            or self.provider_dataset_id <= 0
        ):
            raise ValueError("provider_dataset_id must be a positive integer")
        parse_canonical_sync_scope(self.sync_scope)
        if (
            not isinstance(self.operation_key, str)
            or not self.operation_key
            or self.operation_key != self.operation_key.strip()
        ):
            raise ValueError("operation_key must be a trimmed non-empty string")


@dataclass(frozen=True)
class FeatureUpdateRequestIdempotency:
    """Append-only feature update request idempotency ledger row."""

    idempotency_key: str
    fingerprint_version: int
    request_fingerprint: str
    request_id: str
    actor: str
    reused_active_request: bool
    created_at: datetime


@dataclass(frozen=True)
class FeatureUpdateRequestPreview:
    """미리보기 결과. DB row/import job을 만들지 않는다."""

    scope_type: str
    scope: dict[str, Any]
    dataset_memberships: tuple[FeatureUpdateRequestDataset, ...]
    update_policy: dict[str, Any]
    run_mode: str
    priority: int
    matched_scope: dict[str, Any]


@dataclass(frozen=True)
class _ResolvedFeatureUpdatePlan:
    scope_type: str
    scope: dict[str, Any]
    dataset_memberships: tuple[FeatureUpdateRequestDataset, ...]
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


def _validate_dagster_owner(value: str, *, field_name: str) -> None:
    if not value or value != value.strip():
        raise ValueError(f"{field_name} must be a trimmed non-empty string")


def _row_to_membership(row: Any) -> FeatureUpdateRequestDataset | None:
    if row.feature_update_request_dataset_id is None:
        return None
    return FeatureUpdateRequestDataset(
        feature_update_request_dataset_id=str(row.feature_update_request_dataset_id),
        provider_dataset_id=int(row.provider_dataset_id),
        sync_scope=str(row.sync_scope),
        operation_key=str(row.operation_key),
        provider=str(row.provider),
        dataset_key=str(row.dataset_key),
    )


def _rows_to_request(rows: Sequence[Any]) -> FeatureUpdateRequest:
    if not rows:
        raise ValueError("expected a persisted feature update request row")
    row = rows[0]
    if row.job_id is None:
        raise RuntimeError("persisted feature update request requires an import job")
    memberships = tuple(
        membership for item in rows if (membership := _row_to_membership(item)) is not None
    )
    if not memberships:
        raise RuntimeError("persisted feature update request requires dataset memberships")
    return FeatureUpdateRequest(
        request_id=str(row.request_id),
        scope_type=str(row.scope_type),
        scope=_json_dict(row.scope),
        dataset_membership_mode=str(row.dataset_membership_mode),
        dataset_memberships=memberships,
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
        dispatch_requested_at=row.dispatch_requested_at,
    )


def _rows_to_requests(rows: Sequence[Any]) -> tuple[FeatureUpdateRequest, ...]:
    rows_by_request: dict[str, list[Any]] = {}
    for row in rows:
        rows_by_request.setdefault(str(row.request_id), []).append(row)
    return tuple(_rows_to_request(request_rows) for request_rows in rows_by_request.values())


def _scope_type(scope: Mapping[str, Any]) -> str:
    scope_type = scope.get("type")
    if not isinstance(scope_type, str) or not scope_type:
        raise ValueError("scope requires non-empty type")
    return scope_type


def _validate_run_mode(run_mode: str) -> None:
    if run_mode not in _RUN_MODES:
        raise ValueError(f"run_mode must be one of {sorted(_RUN_MODES)}")


def _normalized_dataset_memberships(
    memberships: Sequence[ImportJobDatasetTarget],
) -> tuple[ImportJobDatasetTarget, ...]:
    values = tuple(memberships)
    if not values:
        raise ValueError("feature update request requires at least one dataset membership")
    if any(
        not isinstance(member.operation_key, str)
        or not member.operation_key
        or member.operation_key != member.operation_key.strip()
        for member in values
    ):
        raise ValueError(
            "feature update dataset memberships require a trimmed non-empty operation_key"
        )
    identities = tuple(
        (member.provider_dataset_id, member.sync_scope, member.operation_key)
        for member in values
    )
    if len(set(identities)) != len(identities):
        raise ValueError("dataset memberships must not contain duplicate dataset operations")
    return values


def _canonicalize_request_scope(scope: Mapping[str, Any]) -> dict[str, Any]:
    """Stored request scope를 canonical exact membership shape으로 좁힌다."""
    scope_type = _scope_type(scope)
    if scope_type != "provider_dataset":
        return canonicalize_feature_update_scope(scope)

    provider_dataset_id = scope.get("provider_dataset_id")
    if (
        not isinstance(provider_dataset_id, int)
        or isinstance(provider_dataset_id, bool)
        or provider_dataset_id <= 0
    ):
        raise ValueError("provider_dataset scope requires a positive provider_dataset_id")
    sync_scope = scope.get("sync_scope")
    operation_key = scope.get("operation_key")
    if (
        not isinstance(sync_scope, str)
        or not sync_scope
        or sync_scope != sync_scope.strip()
        or not isinstance(operation_key, str)
        or not operation_key
        or operation_key != operation_key.strip()
    ):
        raise ValueError(
            "provider_dataset scope requires trimmed sync_scope and operation_key"
        )
    if set(scope) != {"type", "provider_dataset_id", "sync_scope", "operation_key"}:
        raise ValueError(
            "provider_dataset scope only permits type, provider_dataset_id, sync_scope, "
            "and operation_key"
        )
    return {
        "type": "provider_dataset",
        "provider_dataset_id": provider_dataset_id,
        "sync_scope": sync_scope,
        "operation_key": operation_key,
    }


def execution_scope_for_request(request: FeatureUpdateRequest) -> dict[str, Any]:
    """저장된 direct scope와 immutable membership의 exact identity를 대조한다."""
    if request.scope_type != "provider_dataset":
        return dict(request.scope)
    if len(request.dataset_memberships) != 1:
        raise RuntimeError("direct feature update request requires exactly one membership")
    membership = request.dataset_memberships[0]
    provider_dataset_id = request.scope.get("provider_dataset_id")
    if (
        provider_dataset_id != membership.provider_dataset_id
        or request.scope.get("sync_scope") != membership.sync_scope
        or request.scope.get("operation_key") != membership.operation_key
    ):
        raise RuntimeError("direct feature update scope and membership disagree")
    return {
        "type": "provider_dataset",
        "provider_dataset_id": membership.provider_dataset_id,
        "sync_scope": membership.sync_scope,
        "operation_key": membership.operation_key,
    }


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
            raise ValueError(f"update_policy.mode must be {_FEATURE_UPDATE_POLICY_MODE!r}")
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
    dataset_memberships: Sequence[FeatureUpdateRequestDataset],
) -> str:
    """동일 request scope + immutable canonical memberships의 lock key를 만든다."""
    canonical_scope = _canonicalize_request_scope(scope)
    if canonical_scope["type"] != scope_type:
        raise ValueError("scope_type must equal scope.type")
    membership_values = tuple(
        (membership.provider_dataset_id, membership.sync_scope, membership.operation_key)
        for membership in dataset_memberships
    )
    if not membership_values:
        raise ValueError("feature update lock requires at least one dataset membership")
    if len(set(membership_values)) != len(membership_values):
        raise ValueError("feature update lock memberships must be unique")
    payload = {
        "scope_type": scope_type,
        "scope": _canonical_jsonable(canonical_scope),
        "dataset_memberships": sorted(membership_values),
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


#: 요청 생성 transaction의 **첫 lock**으로 canonical scope 행을 정렬 순서로 잡는다.
#:
#: 이 lock이 없으면 같은 canonical scope의 동시 생성이 아래 순서 역전으로
#: deadlock한다 (실측 서버 로그 기준):
#:
#: 1. ``ops.import_job_datasets`` INSERT의 FK가 scope 행에 ``FOR KEY SHARE``를
#:    건다 — 공유 lock이라 두 transaction이 동시에 보유한다.
#: 2. ``ops.import_job_events`` INSERT의 statement trigger가 전역 singleton
#:    ``ops.import_job_event_clock`` 행을 commit까지 배타 점유한다.
#: 3. request membership INSERT의 overlap trigger
#:    (``assert_feature_update_request_member_available``)가 같은 scope 행을
#:    ``FOR UPDATE``로 **승격**한다 — 상대의 KEY SHARE 때문에 대기한다.
#:
#: clock 행을 먼저 잡은 쪽은 3에서, 못 잡은 쪽은 2에서 서로를 기다린다. 강한
#: lock을 미리 잡아 두면 모든 transaction이 scope → clock 한 방향으로만 lock을
#: 얻으므로 순환이 생기지 않는다. 정렬 순서는 DB 쪽
#: ``lock_feature_update_request_member_scopes`` / membership 검사 loop와 같은
#: ``(provider_dataset_id, sync_scope, operation_key)``다 — 다중 membership끼리도
#: 순서가 엇갈리지 않는다.
_LOCK_MEMBER_SCOPES_SQL: Final[str] = """
SELECT scope.provider_dataset_id
FROM provider_sync.provider_dataset_operation_scopes AS scope
JOIN jsonb_to_recordset(CAST(:dataset_memberships AS jsonb)) AS target(
    provider_dataset_id bigint,
    sync_scope text,
    operation_key text
) ON target.provider_dataset_id = scope.provider_dataset_id
 AND target.sync_scope = scope.sync_scope
 AND target.operation_key = scope.operation_key
ORDER BY scope.provider_dataset_id, scope.sync_scope, scope.operation_key
FOR UPDATE OF scope
"""

_INSERT_REQUEST_SQL: Final[str] = f"""
WITH expected_members AS (
    SELECT target.provider_dataset_id, target.sync_scope, target.operation_key
    FROM jsonb_to_recordset(CAST(:dataset_memberships AS jsonb)) AS target(
        provider_dataset_id bigint,
        sync_scope text,
        operation_key text
    )
),
request AS (
    INSERT INTO ops.feature_update_requests (
        request_id, scope_type, scope, dataset_membership_mode, update_policy,
        run_mode, priority, matched_scope, job_id, operator, reason
    ) SELECT
        CAST(:request_id AS uuid), :scope_type, CAST(:scope AS jsonb),
        :dataset_membership_mode, CAST(:update_policy AS jsonb), :run_mode, :priority,
        CAST(:matched_scope AS jsonb), CAST(:job_id AS uuid), :operator, :reason
    WHERE EXISTS (
        SELECT 1
        FROM ops.import_jobs AS identity_job
        WHERE identity_job.job_id = CAST(:job_id AS uuid)
          AND identity_job.kind = 'feature_update_request'
          AND identity_job.status = 'queued'
          AND identity_job.cancellation_id IS NULL
    )
      AND NOT EXISTS (
        SELECT 1
        FROM (
            (
                (SELECT member.provider_dataset_id, member.sync_scope, member.operation_key
                 FROM ops.import_job_datasets AS member
                 WHERE member.job_id = CAST(:job_id AS uuid))
                EXCEPT
                (SELECT provider_dataset_id, sync_scope, operation_key FROM expected_members)
            )
            UNION ALL
            (
                (SELECT provider_dataset_id, sync_scope, operation_key FROM expected_members)
                EXCEPT
                (SELECT member.provider_dataset_id, member.sync_scope, member.operation_key
                 FROM ops.import_job_datasets AS member
                 WHERE member.job_id = CAST(:job_id AS uuid))
            )
        ) AS mismatch
    )
    RETURNING *
),
inserted_members AS (
    INSERT INTO ops.feature_update_request_datasets (
        request_id, provider_dataset_id, sync_scope, operation_key
    )
    SELECT request.request_id, expected.provider_dataset_id, expected.sync_scope,
           expected.operation_key
    FROM request
    CROSS JOIN expected_members AS expected
    RETURNING feature_update_request_dataset_id, request_id, provider_dataset_id, sync_scope,
              operation_key
)
SELECT {_REQUEST_RETURN_COLUMNS}
FROM request
JOIN ops.import_jobs AS job ON job.job_id = request.job_id
JOIN inserted_members AS member ON member.request_id = request.request_id
JOIN provider_sync.provider_datasets AS dataset
  ON dataset.provider_dataset_id = member.provider_dataset_id
ORDER BY member.provider_dataset_id, member.sync_scope, member.operation_key
"""

_GET_REQUEST_SQL: Final[str] = f"""
SELECT {_REQUEST_RETURN_COLUMNS}
FROM ops.feature_update_requests AS request
JOIN ops.import_jobs AS job ON job.job_id = request.job_id
{_REQUEST_MEMBERSHIP_JOINS}
WHERE request.request_id = CAST(:request_id AS uuid)
ORDER BY member.provider_dataset_id, member.sync_scope, member.operation_key
"""

_GET_REQUEST_BY_JOB_SQL: Final[str] = f"""
SELECT {_REQUEST_RETURN_COLUMNS}
FROM ops.feature_update_requests AS request
JOIN ops.import_jobs AS job ON job.job_id = request.job_id
{_REQUEST_MEMBERSHIP_JOINS}
WHERE request.job_id = CAST(:job_id AS uuid)
ORDER BY member.provider_dataset_id, member.sync_scope, member.operation_key
"""

_GET_IDEMPOTENCY_SQL: Final[str] = """
SELECT idempotency_key, fingerprint_version, request_fingerprint, request_id,
       actor, reused_active_request, created_at
FROM ops.feature_update_request_idempotency
WHERE actor = :actor
  AND idempotency_key = CAST(:idempotency_key AS uuid)
"""

_INSERT_IDEMPOTENCY_SQL: Final[str] = """
INSERT INTO ops.feature_update_request_idempotency (
    idempotency_key, fingerprint_version, request_fingerprint, request_id,
    actor, reused_active_request
) VALUES (
    CAST(:idempotency_key AS uuid), 1, :request_fingerprint,
    CAST(:request_id AS uuid), :actor, :reused_active_request
)
RETURNING idempotency_key, fingerprint_version, request_fingerprint, request_id,
          actor, reused_active_request, created_at
"""

_LOCK_EXECUTION_REQUEST_SQL: Final[str] = f"""
SELECT {_REQUEST_RETURN_COLUMNS}
FROM ops.feature_update_requests AS request
JOIN ops.import_jobs AS job ON job.job_id = request.job_id
{_REQUEST_MEMBERSHIP_JOINS}
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
ORDER BY member.provider_dataset_id, member.sync_scope
FOR UPDATE OF request, job
"""

_PEEK_REQUEST_SQL: Final[str] = f"""
WITH candidates AS (
    SELECT request.request_id, request.created_at
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
)
SELECT {_REQUEST_RETURN_COLUMNS}
FROM candidates
JOIN ops.feature_update_requests AS request ON request.request_id = candidates.request_id
JOIN ops.import_jobs AS job ON job.job_id = request.job_id
{_REQUEST_MEMBERSHIP_JOINS}
ORDER BY (job.dispatch_requested_at IS NOT NULL) DESC,
         request.priority DESC,
         job.dispatch_requested_at NULLS LAST,
         candidates.created_at,
         request.request_id,
         member.provider_dataset_id,
         member.sync_scope
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
{_REQUEST_MEMBERSHIP_JOINS}
ORDER BY member.provider_dataset_id, member.sync_scope
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
{_REQUEST_MEMBERSHIP_JOINS}
ORDER BY member.provider_dataset_id, member.sync_scope
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
{_REQUEST_MEMBERSHIP_JOINS}
ORDER BY member.provider_dataset_id, member.sync_scope
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
{_REQUEST_MEMBERSHIP_JOINS}
ORDER BY member.provider_dataset_id, member.sync_scope
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
SELECT job.job_id, job.status, job.progress, job.current_stage,
       member.import_job_dataset_id
FROM job
JOIN ops.import_job_datasets AS member ON member.job_id = job.job_id
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
{_REQUEST_MEMBERSHIP_JOINS}
ORDER BY member.provider_dataset_id, member.sync_scope
"""

_ADVANCE_PRE_START_FAILURE_GENERATION_SQL: Final[str] = _TOUCH_QUEUED_REQUEST_FOR_LOCK_RETRY_SQL

_LIST_REQUESTS_SQL: Final[str] = f"""
WITH candidate_request_ids AS (
    SELECT request.request_id, request.created_at
    FROM ops.feature_update_requests AS request
    JOIN ops.import_jobs AS job ON job.job_id = request.job_id
    WHERE (CAST(:status AS text) IS NULL OR job.status = CAST(:status AS text))
      AND (CAST(:scope_type AS text) IS NULL OR request.scope_type = CAST(:scope_type AS text))
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
          CAST(:cursor_created_at AS timestamptz), CAST(:cursor_request_id AS uuid)
          )
      )
      AND (CAST(:provider AS text) IS NULL OR EXISTS (
          SELECT 1
          FROM ops.feature_update_request_datasets AS candidate_member
          JOIN provider_sync.provider_datasets AS candidate_dataset
            ON candidate_dataset.provider_dataset_id = candidate_member.provider_dataset_id
          WHERE candidate_member.request_id = request.request_id
            AND candidate_dataset.provider = CAST(:provider AS text)
      ))
      AND (CAST(:dataset_key AS text) IS NULL OR EXISTS (
          SELECT 1
          FROM ops.feature_update_request_datasets AS candidate_member
          JOIN provider_sync.provider_datasets AS candidate_dataset
            ON candidate_dataset.provider_dataset_id = candidate_member.provider_dataset_id
          WHERE candidate_member.request_id = request.request_id
            AND candidate_dataset.dataset_key = CAST(:dataset_key AS text)
      ))
    ORDER BY request.created_at DESC, request.request_id DESC
    LIMIT :limit_plus_one
)
SELECT {_REQUEST_RETURN_COLUMNS}
FROM candidate_request_ids AS candidate
JOIN ops.feature_update_requests AS request ON request.request_id = candidate.request_id
JOIN ops.import_jobs AS job ON job.job_id = request.job_id
{_REQUEST_MEMBERSHIP_JOINS}
ORDER BY candidate.created_at DESC,
         request.request_id DESC,
         member.provider_dataset_id,
         member.sync_scope
"""


async def _resolve_feature_update_plan(
    session: AsyncSession,
    *,
    scope: Mapping[str, Any],
    dataset_memberships: Sequence[ImportJobDatasetTarget] | None = None,
    update_policy: Mapping[str, Any] | None = None,
    run_mode: str = "queued",
    priority: int = 50,
    sigungu_resolver: SigunguByRadiusResolver | None = None,
) -> _ResolvedFeatureUpdatePlan:
    """제출 시점에 active catalog membership을 해석해 immutable snapshot을 만든다."""
    _validate_run_mode(run_mode)
    scope_payload = _canonicalize_request_scope(scope)
    scope_type = _scope_type(scope_payload)
    if isinstance(priority, bool) or not isinstance(priority, int) or not 0 <= priority <= 1000:
        raise ValueError("priority must be an integer between 0 and 1000")
    policy = canonicalize_feature_update_policy(update_policy)
    supplied_memberships = (
        _normalized_dataset_memberships(dataset_memberships)
        if dataset_memberships is not None
        else None
    )

    if scope_type == "provider_dataset":
        if supplied_memberships is None or len(supplied_memberships) != 1:
            raise ValueError("provider_dataset scope requires exactly one canonical membership")
        catalog_memberships = await _resolve_active_dataset_memberships(
            session, supplied_memberships
        )
        member = catalog_memberships[0]
        if (
            scope_payload["provider_dataset_id"] != member.provider_dataset_id
            or scope_payload["sync_scope"] != member.sync_scope
            or scope_payload["operation_key"] != member.operation_key
        ):
            raise ValueError("provider_dataset scope must match its canonical membership")
        resolution = await count_features_matching_scope(
            session,
            {
                "type": "provider_dataset",
                "provider_dataset_id": member.provider_dataset_id,
                "sync_scope": member.sync_scope,
                "operation_key": member.operation_key,
            },
            sigungu_resolver=sigungu_resolver,
        )
    else:
        resolution = await count_features_matching_scope(
            session, scope_payload, sigungu_resolver=sigungu_resolver
        )
        if supplied_memberships is None:
            supplied_memberships = tuple(
                ImportJobDatasetTarget(
                    provider_dataset_id=item.provider_dataset_id,
                    sync_scope=item.sync_scope,
                    operation_key=item.operation_key,
                )
                for item in resolution.provider_datasets
            )
        catalog_memberships = await _resolve_active_dataset_memberships(
            session, supplied_memberships
        )

    matched_scope = resolution.matched_scope()
    matched_scope["dataset_memberships"] = [
        {
            "provider_dataset_id": member.provider_dataset_id,
            "sync_scope": member.sync_scope,
            "operation_key": member.operation_key,
        }
        for member in catalog_memberships
    ]
    return _ResolvedFeatureUpdatePlan(
        scope_type=scope_type,
        scope=scope_payload,
        dataset_memberships=catalog_memberships,
        update_policy=policy,
        run_mode=run_mode,
        priority=priority,
        matched_scope=matched_scope,
    )


async def _resolve_active_dataset_memberships(
    session: AsyncSession,
    memberships: Sequence[ImportJobDatasetTarget],
) -> tuple[FeatureUpdateRequestDataset, ...]:
    """active dataset + enabled refresh scope를 exact canonical ID로 검증한다."""
    normalized = _normalized_dataset_memberships(memberships)
    rows = (
        await session.execute(
            text(_ACTIVE_DATASET_MEMBERSHIPS_SQL),
            {
                "dataset_memberships": json.dumps(
                    [
                        {
                            "provider_dataset_id": member.provider_dataset_id,
                            "sync_scope": member.sync_scope,
                            "operation_key": member.operation_key,
                        }
                        for member in normalized
                    ]
                )
            },
        )
    ).mappings().all()
    if len(rows) != len(normalized):
        raise ValueError(
            "each feature update membership must reference an active dataset "
            "and enabled refresh scope"
        )
    resolved = tuple(
        FeatureUpdateRequestDataset(
            feature_update_request_dataset_id=None,
            provider_dataset_id=int(row["provider_dataset_id"]),
            sync_scope=str(row["sync_scope"]),
            operation_key=str(row["operation_key"]),
            provider=str(row["provider"]),
            dataset_key=str(row["dataset_key"]),
        )
        for row in rows
    )
    if {
        (item.provider_dataset_id, item.sync_scope, item.operation_key) for item in resolved
    } != {
        (item.provider_dataset_id, item.sync_scope, item.operation_key)
        for item in normalized
    }:
        raise RuntimeError("active membership lookup returned an unexpected dataset scope")
    return resolved


async def preview_feature_update_request(
    session: AsyncSession,
    *,
    scope: Mapping[str, Any],
    dataset_memberships: Sequence[ImportJobDatasetTarget] | None = None,
    update_policy: Mapping[str, Any] | None = None,
    run_mode: str = "queued",
    priority: int = 50,
    sigungu_resolver: SigunguByRadiusResolver | None = None,
) -> FeatureUpdateRequestPreview:
    """scope를 해석하되 request/import job은 만들지 않는다."""
    plan = await _resolve_feature_update_plan(
        session,
        scope=scope,
        dataset_memberships=dataset_memberships,
        update_policy=update_policy,
        run_mode=run_mode,
        priority=priority,
        sigungu_resolver=sigungu_resolver,
    )
    return FeatureUpdateRequestPreview(
        scope_type=plan.scope_type,
        scope=plan.scope,
        dataset_memberships=plan.dataset_memberships,
        update_policy=plan.update_policy,
        run_mode=plan.run_mode,
        priority=plan.priority,
        matched_scope=plan.matched_scope,
    )


def _is_service_owned_cache_target_scope(scope: Mapping[str, Any]) -> bool:
    return (
        scope.get("type") == "cache_target_keys"
        and scope.get("external_system") == _RELAY_OWNED_EXTERNAL_SYSTEM
    )


async def enqueue_feature_update_request(
    session: AsyncSession,
    *,
    scope: Mapping[str, Any],
    dataset_memberships: Sequence[ImportJobDatasetTarget] | None = None,
    update_policy: Mapping[str, Any] | None = None,
    run_mode: str = "queued",
    priority: int = 50,
    operator: str | None = None,
    reason: str | None = None,
    sigungu_resolver: SigunguByRadiusResolver | None = None,
) -> FeatureUpdateRequest:
    """일반 writer로 정규화한 scope와 canonical import job을 영속화한다."""
    if _is_service_owned_cache_target_scope(scope):
        raise ValueError(_SERVICE_OWNED_CACHE_TARGET_REQUEST_MESSAGE)
    return await _enqueue_feature_update_request(
        session,
        scope=scope,
        dataset_memberships=dataset_memberships,
        update_policy=update_policy,
        run_mode=run_mode,
        priority=priority,
        operator=operator,
        reason=reason,
        sigungu_resolver=sigungu_resolver,
    )


async def enqueue_cache_target_service_refresh_request(
    session: AsyncSession,
    *,
    scope: Mapping[str, Any],
    dataset_memberships: Sequence[ImportJobDatasetTarget],
    operator: str,
    reason: str,
) -> FeatureUpdateRequest:
    """Service refresh가 검증한 cache target을 전용 outbox writer로 적재한다."""
    if scope.get("type") != "cache_target_keys":
        raise ValueError(
            "cache-target service refresh는 cache_target_keys scope만 허용합니다."
        )
    return await _enqueue_feature_update_request(
        session,
        scope=scope,
        dataset_memberships=dataset_memberships,
        run_mode="queued",
        operator=operator,
        reason=reason,
    )


async def _enqueue_feature_update_request(
    session: AsyncSession,
    *,
    scope: Mapping[str, Any],
    dataset_memberships: Sequence[ImportJobDatasetTarget] | None = None,
    update_policy: Mapping[str, Any] | None = None,
    run_mode: str = "queued",
    priority: int = 50,
    operator: str | None = None,
    reason: str | None = None,
    sigungu_resolver: SigunguByRadiusResolver | None = None,
) -> FeatureUpdateRequest:
    """전용 writer가 검증한 scope를 canonical request/import job으로 영속화한다."""
    plan = await _resolve_feature_update_plan(
        session,
        scope=scope,
        dataset_memberships=dataset_memberships,
        update_policy=update_policy,
        run_mode=run_mode,
        priority=priority,
        sigungu_resolver=sigungu_resolver,
    )
    scope_type = plan.scope_type
    scope_payload = plan.scope
    memberships = tuple(
        ImportJobDatasetTarget(
            provider_dataset_id=member.provider_dataset_id,
            sync_scope=member.sync_scope,
            operation_key=member.operation_key,
        )
        for member in plan.dataset_memberships
    )
    policy = plan.update_policy
    matched_scope = plan.matched_scope

    scope_lock_key = feature_update_scope_advisory_key(
        scope_type=scope_type,
        scope=scope_payload,
        dataset_memberships=plan.dataset_memberships,
    )
    if plan.run_mode == "now":
        async with try_advisory_lock(session, scope_lock_key) as acquired:
            if not acquired:
                raise FeatureUpdateLockBusy(lock_key=scope_lock_key)

    membership_param = json.dumps(
        [
            {
                "provider_dataset_id": member.provider_dataset_id,
                "sync_scope": member.sync_scope,
                "operation_key": member.operation_key,
            }
            for member in memberships
        ]
    )
    # 아래 job/request INSERT가 같은 scope 행의 lock을 KEY SHARE → FOR UPDATE로
    # 승격하며 서로 교차 대기하지 않도록, 강한 lock을 정렬 순서로 미리 잡는다
    # (``_LOCK_MEMBER_SCOPES_SQL`` 주석의 실측 deadlock 사슬 참조).
    await session.execute(
        text(_LOCK_MEMBER_SCOPES_SQL),
        {"dataset_memberships": membership_param},
    )
    request_id = str(uuid4())
    job = await enqueue_feature_update_request_job(
        session,
        dataset_memberships=memberships,
        dispatch_requested=plan.run_mode == "now",
    )
    rows = (
        await session.execute(
            text(_INSERT_REQUEST_SQL),
            {
                "request_id": request_id,
                "scope_type": scope_type,
                "scope": _json_param(scope_payload),
                "dataset_membership_mode": "single" if len(memberships) == 1 else "multiple",
                "dataset_memberships": membership_param,
                "update_policy": _json_param(policy),
                "run_mode": plan.run_mode,
                "priority": plan.priority,
                "matched_scope": _json_param(matched_scope),
                "job_id": job.job_id,
                "operator": operator,
                "reason": reason,
            },
        )
    ).all()
    return _rows_to_request(rows)


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
    return _rows_to_requests(rows)


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
    rows = (
        await session.execute(
            text(_START_REQUEST_SQL),
            {
                "request_id": request_id,
                "dagster_run_id": dagster_run_id,
                "expected_generation": expected_generation,
            },
        )
    ).all()
    return _rows_to_request(rows) if rows else None


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
    rows = (
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
    ).all()
    return _rows_to_request(rows) if rows else None


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
    rows = (
        await session.execute(
            text(_SET_MATCHED_SCOPE_SQL),
            {
                "request_id": request_id,
                "matched_scope": _json_param(matched_scope),
                "expected_generation": expected_generation,
                "owner_dagster_run_id": owner_dagster_run_id,
            },
        )
    ).all()
    return _rows_to_request(rows) if rows else None


async def get_update_request(
    session: AsyncSession,
    request_id: str,
) -> FeatureUpdateRequest | None:
    """request id로 단건 조회."""
    rows = (await session.execute(text(_GET_REQUEST_SQL), {"request_id": request_id})).all()
    return _rows_to_request(rows) if rows else None


async def get_update_request_by_job_id(
    session: AsyncSession,
    job_id: str,
) -> FeatureUpdateRequest | None:
    """canonical import job에 연결된 feature update request를 조회한다."""
    rows = (await session.execute(text(_GET_REQUEST_BY_JOB_SQL), {"job_id": job_id})).all()
    return _rows_to_request(rows) if rows else None


async def lock_feature_update_request_idempotency(
    session: AsyncSession,
    idempotency_key: str,
    *,
    actor: str,
) -> None:
    """Actor-scoped UUID key를 transaction advisory lock으로 직렬화한다."""
    lock_id = advisory_lock_key(f"feature-update-idempotency:{actor}:{idempotency_key}")
    await session.execute(
        text("SELECT pg_advisory_xact_lock(CAST(:lock_id AS bigint))"),
        {"lock_id": lock_id},
    )


async def get_feature_update_request_idempotency(
    session: AsyncSession,
    idempotency_key: str,
    *,
    actor: str,
) -> FeatureUpdateRequestIdempotency | None:
    """Actor-scoped UUID key의 durable request mapping을 조회한다."""
    row = (
        await session.execute(
            text(_GET_IDEMPOTENCY_SQL),
            {"idempotency_key": idempotency_key, "actor": actor},
        )
    ).one_or_none()
    if row is None:
        return None
    return FeatureUpdateRequestIdempotency(
        idempotency_key=str(row.idempotency_key),
        fingerprint_version=int(row.fingerprint_version),
        request_fingerprint=str(row.request_fingerprint),
        request_id=str(row.request_id),
        actor=str(row.actor),
        reused_active_request=bool(row.reused_active_request),
        created_at=row.created_at,
    )


async def create_feature_update_request_idempotency(
    session: AsyncSession,
    *,
    idempotency_key: str,
    request_fingerprint: str,
    request_id: str,
    actor: str,
    reused_active_request: bool,
) -> FeatureUpdateRequestIdempotency:
    """현재 transaction이 만든/reuse한 request에 durable key를 매핑한다."""
    row = (
        await session.execute(
            text(_INSERT_IDEMPOTENCY_SQL),
            {
                "idempotency_key": idempotency_key,
                "request_fingerprint": request_fingerprint,
                "request_id": request_id,
                "actor": actor,
                "reused_active_request": reused_active_request,
            },
        )
    ).one()
    return FeatureUpdateRequestIdempotency(
        idempotency_key=str(row.idempotency_key),
        fingerprint_version=int(row.fingerprint_version),
        request_fingerprint=str(row.request_fingerprint),
        request_id=str(row.request_id),
        actor=str(row.actor),
        reused_active_request=bool(row.reused_active_request),
        created_at=row.created_at,
    )


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
    rows = (
        await session.execute(
            text(_LOCK_EXECUTION_REQUEST_SQL),
            {
                "request_id": request_id,
                "expected_generation": expected_generation,
                "owner_dagster_run_id": owner_dagster_run_id,
            },
        )
    ).all()
    if not rows:
        return None
    request = _rows_to_request(rows)
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
    rows = (
        await session.execute(
            text(_REQUEUE_REQUEST_SQL),
            {
                "request_id": request_id,
                "expected_generation": expected_generation,
                "caller_dagster_run_id": caller_dagster_run_id,
            },
        )
    ).all()
    return _rows_to_request(rows) if rows else None


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
            import_job_dataset_id=str(row.import_job_dataset_id),
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
    rows = (
        await session.execute(
            text(_TOUCH_QUEUED_REQUEST_FOR_LOCK_RETRY_SQL),
            {
                "request_id": request_id,
                "expected_generation": expected_generation,
            },
        )
    ).all()
    return _rows_to_request(rows) if rows else None


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
    rows = (
        await session.execute(
            text(_ADVANCE_PRE_START_FAILURE_GENERATION_SQL),
            {
                "request_id": request_id,
                "expected_generation": expected_generation,
            },
        )
    ).all()
    return _rows_to_request(rows) if rows else None


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
                "dataset_key": dataset_key,
                "created_from": created_from,
                "created_to": created_to,
                "cursor_created_at": cursor_created_at,
                "cursor_request_id": cursor_request_id,
                "limit_plus_one": effective_limit + 1,
            },
        )
    ).all()
    requests = _rows_to_requests(rows)
    page_items = requests[:effective_limit]
    next_cursor = (
        _encode_cursor(page_items[-1])
        if len(requests) > effective_limit and page_items
        else None
    )
    return FeatureUpdateRequestPage(items=page_items, next_cursor=next_cursor)
