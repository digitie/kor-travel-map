"""Feature update request application service.

scope 검증, geo resolver 조립, 큐 적재와 HTTP 표현 변환을 제공한다. 예외는 typed
application exception으로 노출하며 HTTP status 매핑은 각 라우터가 담당한다.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
from contextlib import asynccontextmanager
from time import perf_counter
from typing import Any, TypeVar
from uuid import UUID

import httpx
from kortravelmap.core.exceptions import GeoAuthNotConfiguredError, GeoRequestError
from kortravelmap.core.sync_scope import parse_canonical_sync_scope
from kortravelmap.geocoding import KorTravelGeoRestClient, resolve_sigungu_by_radius
from kortravelmap.infra.feature_update_active_repo import (
    FeatureUpdateDispatchConflict,
    find_active_provider_dataset_request,
    is_active_provider_dataset_unique_violation,
    request_feature_update_dispatch,
)
from kortravelmap.infra.feature_update_repo import (
    FeatureUpdateLockBusy,
    FeatureUpdateRequest,
    FeatureUpdateRequestDataset,
    FeatureUpdateRequestPreview,
    create_feature_update_request_idempotency,
    enqueue_feature_update_request,
    get_feature_update_request_idempotency,
    get_update_request,
    lock_feature_update_request_idempotency,
)
from kortravelmap.infra.feature_update_repo import (
    preview_feature_update_request as preview_feature_update_request_repo,
)
from kortravelmap.infra.jobs_repo import ImportJobDatasetTarget
from kortravelmap.infra.scope_repo import SigunguByRadiusResolver
from kortravelmap.settings import KorTravelMapSettings
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.api.feature_ref import resolve_write_feature_refs_or_error
from kortravelmap.api.feature_update_schema import (
    FeatureIdsScope,
    FeatureUpdateDatasetMembership,
    FeatureUpdatePolicy,
    FeatureUpdateRequestCreatedRecord,
    FeatureUpdateRequestCreateRequest,
    FeatureUpdateRequestCreateResponse,
    FeatureUpdateRequestMutationResponse,
    FeatureUpdateRequestPreviewRecord,
    FeatureUpdateRequestPreviewRequest,
    FeatureUpdateRequestPreviewResponse,
    FeatureUpdateRequestRecord,
    FeatureUpdateScope,
)
from kortravelmap.api.response import make_meta

__all__ = [
    "FeatureUpdateEnqueueError",
    "FeatureUpdateActiveScopeConflict",
    "FeatureUpdateDispatchStateConflict",
    "FeatureUpdateIdempotencyConflict",
    "FeatureUpdateLockConflict",
    "FeatureUpdateRequestNotFound",
    "FeatureUpdateResolverError",
    "FeatureUpdateServiceError",
    "FeatureUpdateValidationError",
    "ResolvedPlanGuard",
    "SigunguResolverUnavailable",
    "create_feature_update_request",
    "created_response",
    "enqueue_update_request",
    "persisted_response",
    "preview_feature_update_request",
    "preview_response",
    "preview_update_request",
    "record_from_request",
    "run_feature_update_request_now",
]

DEFAULT_STATUS_URL_PREFIX = "/v1/ops/pipeline/executions/update_request"
_SIGUNGU_RESOLVER_REQUIRED_MESSAGE = (
    "sigungu_by_radius scope에는 KOR_TRAVEL_MAP_KOR_TRAVEL_GEO_BASE_URL 설정이 필요합니다."
)
_RELAY_OWNED_EXTERNAL_SYSTEM = "pinvi"
_SERVICE_OWNED_CACHE_TARGET_REQUEST_MESSAGE = (
    "PinVi cache target refresh는 /v1/service/refresh-requests "
    "ServiceToken 경로로만 요청할 수 있습니다."
)


class FeatureUpdateServiceError(Exception):
    """Feature update application service의 공개 예외 기반."""


class SigunguResolverUnavailable(GeoAuthNotConfiguredError, FeatureUpdateServiceError):
    """시군구 반경 scope에 필요한 kor-travel-geo resolver 설정이 없을 때 발생."""


class FeatureUpdateValidationError(ValueError, FeatureUpdateServiceError):
    """요청 scope/provider/dataset 조합이 유효하지 않다."""


ResolvedPlanGuard = Callable[
    [frozenset[tuple[int, str]]],
    Awaitable[None],
]
"""영속 전 immutable canonical dataset membership 선행조건 검사."""


class FeatureUpdateLockConflict(RuntimeError, FeatureUpdateServiceError):
    """동일 scope 즉시 실행 advisory lock 경합."""

    def __init__(self, exc: FeatureUpdateLockBusy) -> None:
        super().__init__(str(exc))
        self.code = exc.code
        self.retry_after_seconds = exc.retry_after_seconds


class FeatureUpdateActiveScopeConflict(RuntimeError, FeatureUpdateServiceError):
    """같은 effective scope의 활성 작업이 서로 다른 요청 계획을 가진다."""

    code = "ACTIVE_SCOPE_CONFLICT"

    def __init__(self, request: FeatureUpdateRequest) -> None:
        super().__init__("같은 provider/dataset/sync_scope에 다른 활성 요청이 이미 있습니다.")
        self.request_id = request.request_id
        self.status = (
            "cancellation_requested" if request.cancellation_id is not None else request.status
        )


class FeatureUpdateDispatchStateConflict(RuntimeError, FeatureUpdateServiceError):
    """terminal request에 즉시 dispatch를 요청했다."""

    code = "REQUEST_NOT_DISPATCHABLE"

    def __init__(self, *, request_id: str, current_status: str) -> None:
        super().__init__(f"{current_status} 상태인 request는 dispatch할 수 없습니다.")
        self.request_id = request_id
        self.current_status = current_status


class FeatureUpdateIdempotencyConflict(RuntimeError, FeatureUpdateServiceError):
    """같은 actor namespace의 key가 다른 canonical body에 이미 사용됐다."""

    code = "FEATURE_UPDATE_IDEMPOTENCY_CONFLICT"

    def __init__(self, *, idempotency_key: str, request_id: str) -> None:
        super().__init__("같은 Idempotency-Key를 다른 갱신 요청에 재사용할 수 없습니다.")
        self.idempotency_key = idempotency_key
        self.request_id = request_id


class FeatureUpdateRequestNotFound(LookupError, FeatureUpdateServiceError):
    """request_id에 해당하는 canonical feature update request가 없다."""


class FeatureUpdateResolverError(GeoRequestError, FeatureUpdateServiceError):
    """kor-travel-geo 호출이 실패했다."""


class FeatureUpdateEnqueueError(RuntimeError, FeatureUpdateServiceError):
    """분류할 수 없는 큐 적재 실패."""


def _scope_payload(scope: FeatureUpdateScope) -> dict[str, Any]:
    return scope.model_dump(mode="json", exclude_none=True)


def _reject_service_owned_cache_target_generic_writer(
    scope: Mapping[str, Any],
) -> None:
    """relay source head/outbox writer를 일반 ops queue가 우회하지 못하게 한다."""

    if (
        scope.get("type") == "cache_target_keys"
        and scope.get("external_system") == _RELAY_OWNED_EXTERNAL_SYSTEM
    ):
        raise FeatureUpdateValidationError(_SERVICE_OWNED_CACHE_TARGET_REQUEST_MESSAGE)


def _update_policy_payload(policy: FeatureUpdatePolicy) -> dict[str, Any]:
    return dict(policy)


def _membership_records(
    memberships: Sequence[FeatureUpdateRequestDataset],
) -> list[FeatureUpdateDatasetMembership]:
    return [
        FeatureUpdateDatasetMembership(
            provider_dataset_id=membership.provider_dataset_id,
            sync_scope=membership.sync_scope,
            operation_key=membership.operation_key,
        )
        for membership in memberships
    ]


def _public_scope(
    scope: Mapping[str, Any],
    memberships: Sequence[FeatureUpdateRequestDataset],
) -> dict[str, Any]:
    """DB 내부 direct scope를 API의 complete canonical scope로 복원한다."""
    public_scope = dict(scope)
    if public_scope.get("type") != "provider_dataset":
        return public_scope
    if len(memberships) != 1:
        raise FeatureUpdateEnqueueError(
            "provider_dataset request requires exactly one dataset membership"
        )
    member = memberships[0]
    if public_scope.get("provider_dataset_id") != member.provider_dataset_id:
        raise FeatureUpdateEnqueueError(
            "provider_dataset request scope and membership disagree"
        )
    return {
        "type": "provider_dataset",
        "provider_dataset_id": member.provider_dataset_id,
        "sync_scope": member.sync_scope,
        "operation_key": member.operation_key,
    }


_NATURAL_IDENTITY_RESPONSE_KEYS = frozenset(
    {"provider", "dataset_key", "providers", "dataset_keys"}
)


def _public_matched_scope(value: Mapping[str, Any]) -> dict[str, Any]:
    """실행 진단에서 legacy natural identity projection을 유출하지 않는다."""

    def sanitize(item: Any) -> Any:
        if isinstance(item, Mapping):
            return {
                str(key): sanitize(nested)
                for key, nested in item.items()
                if str(key) not in _NATURAL_IDENTITY_RESPONSE_KEYS
            }
        if isinstance(item, list | tuple):
            return [sanitize(nested) for nested in item]
        return item

    sanitized = sanitize(value)
    if not isinstance(sanitized, dict):  # pragma: no cover - core invariant.
        raise FeatureUpdateEnqueueError("feature update matched_scope must be an object")
    return sanitized


def _core_scope_and_memberships(
    scope: Mapping[str, Any],
) -> tuple[dict[str, Any], tuple[ImportJobDatasetTarget, ...] | None]:
    """HTTP direct scope를 core persistence shape으로 좁힌다."""
    if scope.get("type") != "provider_dataset":
        return dict(scope), None
    provider_dataset_id = scope.get("provider_dataset_id")
    sync_scope = scope.get("sync_scope")
    operation_key = scope.get("operation_key")
    if (
        not isinstance(provider_dataset_id, int)
        or isinstance(provider_dataset_id, bool)
        or provider_dataset_id <= 0
        or not isinstance(sync_scope, str)
        or not isinstance(operation_key, str)
    ):
        raise FeatureUpdateValidationError(
            "provider_dataset scope requires provider_dataset_id, sync_scope, and operation_key"
        )
    try:
        canonical_scope = parse_canonical_sync_scope(sync_scope).value
    except ValueError as exc:
        raise FeatureUpdateValidationError(str(exc)) from exc
    if canonical_scope != sync_scope:
        raise FeatureUpdateValidationError("sync_scope must be canonical")
    if not operation_key or operation_key != operation_key.strip():
        raise FeatureUpdateValidationError("operation_key must be a trimmed non-empty string")
    return (
        {
            "type": "provider_dataset",
            "provider_dataset_id": provider_dataset_id,
            "sync_scope": canonical_scope,
            "operation_key": operation_key,
        },
        (
            ImportJobDatasetTarget(
                provider_dataset_id=provider_dataset_id,
                sync_scope=canonical_scope,
                operation_key=operation_key,
            ),
        ),
    )


def _membership_targets(
    memberships: Sequence[FeatureUpdateRequestDataset],
) -> tuple[ImportJobDatasetTarget, ...]:
    return tuple(
        ImportJobDatasetTarget(
            provider_dataset_id=membership.provider_dataset_id,
            sync_scope=membership.sync_scope,
            operation_key=membership.operation_key,
        )
        for membership in memberships
    )


def _canonical_feature_update_request_body(
    body: FeatureUpdateRequestCreateRequest,
    *,
    dataset_memberships: Sequence[FeatureUpdateRequestDataset],
) -> dict[str, Any]:
    """Idempotency에 쓸 입력 scope+제출 시점 membership snapshot.

    geo scope는 자연키 filter가 아니라 DB가 해석한 active refresh membership이
    실행 의미다. 따라서 snapshot이 달라지면 같은 Idempotency-Key도 다른 본문으로
    취급한다. 이후 live catalog 변경은 과거 요청을 바꾸지 않는다.
    """
    canonical_body = body.model_dump(mode="json", exclude_none=False)
    canonical_body["dataset_memberships"] = [
        {
            "provider_dataset_id": membership.provider_dataset_id,
            "sync_scope": membership.sync_scope,
            "operation_key": membership.operation_key,
        }
        for membership in sorted(
            dataset_memberships,
            key=lambda item: (item.provider_dataset_id, item.sync_scope, item.operation_key),
        )
    ]
    scope = canonical_body["scope"]
    if scope["type"] == "feature_ids":
        scope["feature_ids"] = sorted(scope["feature_ids"])
    elif scope["type"] == "cache_target_keys":
        scope["target_keys"] = sorted(scope["target_keys"])
    return canonical_body


def _feature_update_request_fingerprint(
    canonical_body: Mapping[str, Any],
    *,
    operator: str,
) -> str:
    """Canonical validated body+actor SHA-256."""
    serialized = json.dumps(
        {"actor": operator, "body": canonical_body},
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def record_from_request(
    row: FeatureUpdateRequest,
    *,
    status_url_prefix: str = DEFAULT_STATUS_URL_PREFIX,
) -> FeatureUpdateRequestRecord:
    """저장 행을 persisted HTTP 표현으로 변환한다."""

    scope = _public_scope(row.scope, row.dataset_memberships)

    return FeatureUpdateRequestRecord(
        request_id=row.request_id,
        scope_type=row.scope_type,
        scope=scope,
        dataset_memberships=_membership_records(row.dataset_memberships),
        update_policy=row.update_policy,
        run_mode=row.run_mode,
        priority=row.priority,
        status=row.status,
        matched_scope=_public_matched_scope(row.matched_scope),
        job_id=row.job_id,
        dagster_run_id=row.dagster_run_id,
        dispatch_requested_at=row.dispatch_requested_at,
        operator=row.operator,
        reason=row.reason,
        error_message=row.error_message,
        created_at=row.created_at,
        started_at=row.started_at,
        finished_at=row.finished_at,
        generation=row.generation,
        status_url=f"{status_url_prefix}/{row.request_id}",
    )


def _record_from_preview(
    preview: FeatureUpdateRequestPreview,
) -> FeatureUpdateRequestPreviewRecord:
    return FeatureUpdateRequestPreviewRecord(
        result_kind="preview",
        scope_type=preview.scope_type,
        scope=_public_scope(preview.scope, preview.dataset_memberships),
        dataset_memberships=_membership_records(preview.dataset_memberships),
        update_policy=preview.update_policy,
        run_mode=preview.run_mode,
        priority=preview.priority,
        matched_scope=_public_matched_scope(preview.matched_scope),
    )


def created_response(
    data: FeatureUpdateRequest,
    *,
    started_at: float,
    idempotent_replay: bool = False,
    reused_active_request: bool = False,
    status_url_prefix: str = DEFAULT_STATUS_URL_PREFIX,
) -> FeatureUpdateRequestCreateResponse:
    """새 영속 요청을 생성 응답으로 변환한다."""

    persisted = record_from_request(data, status_url_prefix=status_url_prefix)
    return FeatureUpdateRequestCreateResponse(
        data=FeatureUpdateRequestCreatedRecord(
            result_kind="request",
            **persisted.model_dump(),
        ),
        idempotent_replay=idempotent_replay,
        reused_active_request=reused_active_request,
        meta=make_meta(started_at=started_at),
    )


def preview_response(
    data: FeatureUpdateRequestPreview,
    *,
    started_at: float,
) -> FeatureUpdateRequestPreviewResponse:
    """비영속 scope 해석 결과를 미리보기 응답으로 변환한다."""

    return FeatureUpdateRequestPreviewResponse(
        data=_record_from_preview(data),
        meta=make_meta(started_at=started_at),
    )


def persisted_response(
    data: FeatureUpdateRequest,
    *,
    started_at: float,
    status_url_prefix: str = DEFAULT_STATUS_URL_PREFIX,
) -> FeatureUpdateRequestMutationResponse:
    """반드시 저장 행을 반환해야 하는 mutation 응답을 만든다."""

    return FeatureUpdateRequestMutationResponse(
        data=record_from_request(data, status_url_prefix=status_url_prefix),
        meta=make_meta(started_at=started_at),
    )


def _scope_explicitly_needs_sigungu(scope: Mapping[str, Any]) -> bool:
    if scope.get("type") == "sigungu_by_radius":
        return True
    return (
        scope.get("type") == "cache_target_keys" and scope.get("scope_mode") == "sigungu_by_radius"
    )


@asynccontextmanager
async def _sigungu_resolver_for_scope(
    scope: Mapping[str, Any],
    *,
    settings: KorTravelMapSettings,
) -> AsyncIterator[SigunguByRadiusResolver | None]:
    base_url = settings.kor_travel_geo_base_url
    if base_url is None:
        if _scope_explicitly_needs_sigungu(scope):
            raise SigunguResolverUnavailable(_SIGUNGU_RESOLVER_REQUIRED_MESSAGE)
        yield None
        return

    async with httpx.AsyncClient(
        base_url=base_url.get_secret_value(),
        timeout=settings.kor_travel_geo_timeout_seconds,
    ) as http:
        client = KorTravelGeoRestClient(
            http,
            api_key=settings.kor_travel_geo_api_key,
        )

        async def resolver(
            *,
            lon: float,
            lat: float,
            radius_km: float,
        ) -> tuple[str, ...]:
            return await resolve_sigungu_by_radius(client, lon=lon, lat=lat, radius_km=radius_km)

        yield resolver


def _enqueue_error(exc: Exception) -> FeatureUpdateServiceError:
    if isinstance(exc, FeatureUpdateLockBusy):
        return FeatureUpdateLockConflict(exc)
    if isinstance(exc, SigunguResolverUnavailable):
        return exc
    if isinstance(exc, GeoAuthNotConfiguredError):
        # T-VN-H21: key 미결선은 base_url 미설정(SigunguResolverUnavailable → 503)과
        # 같은 등급의 서버측 설정 결함이다. ValueError보다 먼저 분기해야 422로 새지 않는다.
        return SigunguResolverUnavailable(str(exc))
    if isinstance(exc, ValueError):
        return FeatureUpdateValidationError(str(exc))
    if isinstance(exc, httpx.HTTPError | GeoRequestError):
        return FeatureUpdateResolverError(f"kor-travel-geo 호출 실패: {exc}")
    return FeatureUpdateEnqueueError("feature update request enqueue failed")


async def enqueue_update_request(
    session: AsyncSession,
    *,
    scope: Mapping[str, Any],
    update_policy: Mapping[str, Any],
    run_mode: str,
    priority: int,
    operator: str | None,
    reason: str | None,
    settings: KorTravelMapSettings,
) -> FeatureUpdateRequest:
    """HTTP scope를 DB-validated canonical snapshot으로 적재한다."""
    _reject_service_owned_cache_target_generic_writer(scope)
    core_scope, direct_memberships = _core_scope_and_memberships(scope)
    preview = await _preview_resolved_update_request(
        session,
        scope=core_scope,
        dataset_memberships=direct_memberships,
        update_policy=update_policy,
        run_mode=run_mode,
        priority=priority,
        settings=settings,
    )
    return await _enqueue_resolved_update_request(
        session,
        scope=core_scope,
        dataset_memberships=_membership_targets(preview.dataset_memberships),
        update_policy=update_policy,
        run_mode=run_mode,
        priority=priority,
        operator=operator,
        reason=reason,
        settings=settings,
    )


async def _enqueue_resolved_update_request(
    session: AsyncSession,
    *,
    scope: Mapping[str, Any],
    dataset_memberships: Sequence[ImportJobDatasetTarget],
    update_policy: Mapping[str, Any],
    run_mode: str,
    priority: int,
    operator: str | None,
    reason: str | None,
    settings: KorTravelMapSettings,
) -> FeatureUpdateRequest:
    """이미 제출 시점에 고정한 membership으로 canonical queue writer를 호출한다."""

    try:
        async with _sigungu_resolver_for_scope(scope, settings=settings) as sigungu_resolver:
            return await enqueue_feature_update_request(
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
    except (
        FeatureUpdateEnqueueError,
        FeatureUpdateLockConflict,
        FeatureUpdateResolverError,
        FeatureUpdateValidationError,
        SigunguResolverUnavailable,
    ):
        raise
    except IntegrityError:
        raise
    except Exception as exc:
        raise _enqueue_error(exc) from exc


async def preview_update_request(
    session: AsyncSession,
    *,
    scope: Mapping[str, Any],
    update_policy: Mapping[str, Any],
    run_mode: str,
    priority: int,
    settings: KorTravelMapSettings,
) -> FeatureUpdateRequestPreview:
    """HTTP scope의 canonical membership snapshot을 비영속적으로 계산한다."""
    core_scope, direct_memberships = _core_scope_and_memberships(scope)
    return await _preview_resolved_update_request(
        session,
        scope=core_scope,
        dataset_memberships=direct_memberships,
        update_policy=update_policy,
        run_mode=run_mode,
        priority=priority,
        settings=settings,
    )


async def _preview_resolved_update_request(
    session: AsyncSession,
    *,
    scope: Mapping[str, Any],
    dataset_memberships: Sequence[ImportJobDatasetTarget] | None,
    update_policy: Mapping[str, Any],
    run_mode: str,
    priority: int,
    settings: KorTravelMapSettings,
) -> FeatureUpdateRequestPreview:
    """core resolver가 현재 DB catalog에서 exact member를 결정하게 한다."""
    try:
        async with _sigungu_resolver_for_scope(scope, settings=settings) as sigungu_resolver:
            return await preview_feature_update_request_repo(
                session,
                scope=scope,
                dataset_memberships=dataset_memberships,
                update_policy=update_policy,
                run_mode=run_mode,
                priority=priority,
                sigungu_resolver=sigungu_resolver,
            )
    except (
        FeatureUpdateEnqueueError,
        FeatureUpdateLockConflict,
        FeatureUpdateResolverError,
        FeatureUpdateValidationError,
        SigunguResolverUnavailable,
    ):
        raise
    except Exception as exc:
        raise _enqueue_error(exc) from exc


def _assert_reusable_active_request(
    existing: FeatureUpdateRequest,
    *,
    scope: Mapping[str, Any],
    dataset_memberships: Sequence[ImportJobDatasetTarget],
    update_policy: Mapping[str, Any],
    priority: int,
    operator: str,
    reason: str | None,
) -> None:
    """활성 identity가 같아도 감사·실행 계획이 다르면 조용히 재사용하지 않는다."""

    if existing.cancellation_id is not None:
        raise FeatureUpdateActiveScopeConflict(existing)

    existing_scope = dict(existing.scope)
    requested_scope = dict(scope)
    same_plan = (
        existing_scope == requested_scope
        and {
            (member.provider_dataset_id, member.sync_scope, member.operation_key)
            for member in existing.dataset_memberships
        }
        == {
            (member.provider_dataset_id, member.sync_scope, member.operation_key)
            for member in dataset_memberships
        }
        and existing.update_policy == dict(update_policy)
        and existing.priority == priority
        and existing.operator == operator
        and existing.reason == reason
    )
    if not same_plan:
        raise FeatureUpdateActiveScopeConflict(existing)


async def _reuse_active_request(
    session: AsyncSession,
    existing: FeatureUpdateRequest,
    *,
    requested_run_mode: str,
) -> FeatureUpdateRequest | None:
    if requested_run_mode != "now" or existing.status == "running":
        return existing
    try:
        return await request_feature_update_dispatch(session, existing.request_id)
    except FeatureUpdateDispatchConflict as exc:
        current = await get_update_request(session, existing.request_id)
        if current is not None and current.cancellation_id is not None:
            raise FeatureUpdateActiveScopeConflict(current) from exc
        if current is not None and current.status == "running":
            return current
        if current is not None and current.status in {"done", "failed", "cancelled"}:
            return None
        if current is None:
            return None
        raise FeatureUpdateDispatchStateConflict(
            request_id=current.request_id,
            current_status=current.status,
        ) from exc


async def _find_reusable_active_request(
    session: AsyncSession,
    *,
    scope: Mapping[str, Any],
    dataset_memberships: Sequence[ImportJobDatasetTarget],
    update_policy: Mapping[str, Any],
    run_mode: str,
    priority: int,
    operator: str,
    reason: str | None,
) -> FeatureUpdateRequest | None:
    """snapshot member와 겹치는 request는 같은 완전한 plan일 때만 재사용한다."""
    existing_by_id: dict[str, FeatureUpdateRequest] = {}
    for membership in dataset_memberships:
        existing = await find_active_provider_dataset_request(
            session,
            provider_dataset_id=membership.provider_dataset_id,
            sync_scope=membership.sync_scope,
            operation_key=membership.operation_key,
        )
        if existing is not None:
            existing_by_id[existing.request_id] = existing
    if not existing_by_id:
        return None
    if len(existing_by_id) != 1:
        raise FeatureUpdateActiveScopeConflict(next(iter(existing_by_id.values())))
    existing = next(iter(existing_by_id.values()))
    _assert_reusable_active_request(
        existing,
        scope=scope,
        dataset_memberships=dataset_memberships,
        update_policy=update_policy,
        priority=priority,
        operator=operator,
        reason=reason,
    )
    return await _reuse_active_request(
        session,
        existing,
        requested_run_mode=run_mode,
    )


_ScopePlanT = TypeVar(
    "_ScopePlanT", FeatureUpdateRequestCreateRequest, FeatureUpdateRequestPreviewRequest
)


async def resolve_feature_ids_scope_refs(
    body: _ScopePlanT, session: AsyncSession
) -> _ScopePlanT:
    """feature_ids scope의 참조를 legacy 정본 키로 경계 해석한다 (T-VN-32C PR-2).

    값 전환 후 운영자가 응답에서 복사한 UUID를 scope에 넣으면, 해석 없이는
    matched_feature_count=0인 요청이 영속 생성되고 job이 빈 scope로 성공
    종료한다(조사 S1 — 조용한 no-op). 미해석 참조는 422 fail-close. 서로 다른
    표기가 같은 feature로 해석되면 중복을 제거한다(순서 보존).

    호출 위치 주의(리뷰 H1): create 경로는 반드시
    :func:`create_feature_update_request`의 트랜잭션 **안**에서 호출된다 —
    라우터에서 먼저 호출하면 SELECT autobegin이 ``session.begin()``과 충돌한다.
    """
    scope = body.scope
    if not isinstance(scope, FeatureIdsScope):
        return body
    resolved = await resolve_write_feature_refs_or_error(
        session, scope.feature_ids, field_name="scope.feature_ids"
    )
    legacy_ids: list[str] = []
    seen: set[str] = set()
    for ref in scope.feature_ids:
        legacy = resolved[ref].feature_id
        if legacy not in seen:
            seen.add(legacy)
            legacy_ids.append(legacy)
    if legacy_ids == list(scope.feature_ids):
        return body
    return body.model_copy(
        update={"scope": scope.model_copy(update={"feature_ids": legacy_ids})}
    )


async def create_feature_update_request(
    body: FeatureUpdateRequestCreateRequest,
    session: AsyncSession,
    *,
    idempotency_key: UUID,
    operator: str,
    status_url_prefix: str,
    settings: KorTravelMapSettings,
    resolved_plan_guard: ResolvedPlanGuard,
) -> FeatureUpdateRequestCreateResponse:
    """Durable key로 생성 결과를 재생하거나 canonical 요청을 생성/reuse한다.

    T-VN-32C PR-2 — feature_ids scope의 참조 해석(UUID→legacy)은 **이
    트랜잭션 안, idempotency lock 직후·fingerprint 계산 이전**에 수행한다:

    - 라우터에서 먼저 해석하면 SELECT가 autobegin을 열어 아래
      ``session.begin()``이 InvalidRequestError로 전건 500이 된다(리뷰 H1).
    - fingerprint를 해석 **후** body로 계산하므로 legacy/UUID 표기가 같은
      canonical 요청으로 dedup된다. 대가로 (a) 값 전환 배포 이전에 저장된
      혼합 표기 요청의 바이트 동일 재전송은 fingerprint 불일치 409가 될 수
      있고(전환기 1회성), (b) scope 참조가 이후 해석 불가가 되면 같은 key
      재전송이 terminal 재생 대신 422로 fail-close한다 — 재생은 "여전히
      유효한 동일 요청"에 한한다는 의도된 강화다(리뷰 M2 명시 결정).
    """

    started_at = perf_counter()
    normalized_key = str(idempotency_key)
    result: FeatureUpdateRequest | None = None
    reused = False
    replayed = False
    async with session.begin():
        # 같은 actor/key의 느린 precheck도 하나만 수행하도록 lock을 transaction
        # 전체(검증→enqueue/reuse→ledger insert) 동안 의도적으로 유지한다.
        await lock_feature_update_request_idempotency(
            session,
            normalized_key,
            actor=operator,
        )
        body = await resolve_feature_ids_scope_refs(body, session)
        scope_payload = _scope_payload(body.scope)
        scope, direct_memberships = _core_scope_and_memberships(scope_payload)
        update_policy = _update_policy_payload(body.update_policy)
        mapping = await get_feature_update_request_idempotency(
            session,
            normalized_key,
            actor=operator,
        )
        if mapping is not None:
            result = await get_update_request(session, mapping.request_id)
            if result is None:
                raise FeatureUpdateEnqueueError(
                    "idempotency ledger가 존재하지 않는 request를 참조합니다."
                )
            canonical_body = _canonical_feature_update_request_body(
                body,
                dataset_memberships=result.dataset_memberships,
            )
            request_fingerprint = _feature_update_request_fingerprint(
                canonical_body,
                operator=operator,
            )
            if (
                mapping.fingerprint_version != 1
                or mapping.actor != operator
                or mapping.request_fingerprint != request_fingerprint
            ):
                raise FeatureUpdateIdempotencyConflict(
                    idempotency_key=normalized_key,
                    request_id=mapping.request_id,
                )
            replayed = True
            reused = mapping.reused_active_request
        else:
            _reject_service_owned_cache_target_generic_writer(scope_payload)
            preview = await _preview_resolved_update_request(
                session,
                scope=scope,
                dataset_memberships=direct_memberships,
                update_policy=update_policy,
                run_mode=body.run_mode,
                priority=body.priority,
                settings=settings,
            )
            dataset_memberships = _membership_targets(preview.dataset_memberships)
            canonical_body = _canonical_feature_update_request_body(
                body,
                dataset_memberships=preview.dataset_memberships,
            )
            request_fingerprint = _feature_update_request_fingerprint(
                canonical_body,
                operator=operator,
            )
            await resolved_plan_guard(
                frozenset(
                    (membership.provider_dataset_id, membership.sync_scope)
                    for membership in preview.dataset_memberships
                )
            )
            result = await _find_reusable_active_request(
                session,
                scope=scope,
                dataset_memberships=dataset_memberships,
                update_policy=update_policy,
                run_mode=body.run_mode,
                priority=body.priority,
                operator=operator,
                reason=body.reason,
            )
            reused = result is not None
            for attempt in range(3):
                if result is not None:
                    break
                try:
                    async with session.begin_nested():
                        result = await _enqueue_resolved_update_request(
                            session,
                            scope=scope,
                            dataset_memberships=dataset_memberships,
                            update_policy=update_policy,
                            run_mode=body.run_mode,
                            priority=body.priority,
                            operator=operator,
                            reason=body.reason,
                            settings=settings,
                        )
                except IntegrityError as exc:
                    if not is_active_provider_dataset_unique_violation(exc):
                        raise FeatureUpdateEnqueueError(
                            "feature update request enqueue failed"
                        ) from exc
                    result = await _find_reusable_active_request(
                        session,
                        scope=scope,
                        dataset_memberships=dataset_memberships,
                        update_policy=update_policy,
                        run_mode=body.run_mode,
                        priority=body.priority,
                        operator=operator,
                        reason=body.reason,
                    )
                    if result is not None:
                        reused = True
                if result is None and attempt == 2:
                    raise FeatureUpdateEnqueueError(
                        "활성 scope lifecycle 경합이 반복되어 요청을 생성하지 못했습니다."
                    )
            if result is None:  # pragma: no cover - 마지막 attempt가 위에서 거절한다.
                raise FeatureUpdateEnqueueError(
                    "활성 scope lifecycle 경합이 반복되어 요청을 생성하지 못했습니다."
                )
            await create_feature_update_request_idempotency(
                session,
                idempotency_key=normalized_key,
                request_fingerprint=request_fingerprint,
                request_id=result.request_id,
                actor=operator,
                reused_active_request=reused,
            )
    if result is None:  # pragma: no cover - loop의 마지막 attempt가 위에서 거절한다.
        raise FeatureUpdateEnqueueError(
            "활성 scope lifecycle 경합이 반복되어 요청을 생성하지 못했습니다."
        )
    return created_response(
        result,
        started_at=started_at,
        idempotent_replay=replayed,
        reused_active_request=reused,
        status_url_prefix=status_url_prefix,
    )


async def run_feature_update_request_now(
    session: AsyncSession,
    *,
    request_id: str,
) -> FeatureUpdateRequest:
    """새 행 없이 기존 canonical request에 우선 dispatch 의도를 멱등 기록한다."""

    existing = await get_update_request(session, request_id)
    if existing is None:
        raise FeatureUpdateRequestNotFound(f"feature update request 없음: {request_id!r}")
    if existing.cancellation_id is not None:
        raise FeatureUpdateDispatchStateConflict(
            request_id=existing.request_id,
            current_status="cancellation_requested",
        )
    if existing.status == "running":
        return existing
    try:
        return await request_feature_update_dispatch(session, request_id)
    except FeatureUpdateDispatchConflict as exc:
        current = await get_update_request(session, request_id)
        if current is not None and current.cancellation_id is not None:
            raise FeatureUpdateDispatchStateConflict(
                request_id=current.request_id,
                current_status="cancellation_requested",
            ) from exc
        if current is not None and current.status == "running":
            return current
        raise FeatureUpdateDispatchStateConflict(
            request_id=exc.request_id,
            current_status=exc.current_status,
        ) from exc


async def preview_feature_update_request(
    body: FeatureUpdateRequestPreviewRequest,
    session: AsyncSession,
    *,
    settings: KorTravelMapSettings,
) -> FeatureUpdateRequestPreviewResponse:
    """갱신 scope를 비영속적으로 해석하고 200 응답을 만든다."""

    started_at = perf_counter()
    body = await resolve_feature_ids_scope_refs(body, session)
    result = await preview_update_request(
        session,
        scope=_scope_payload(body.scope),
        update_policy=_update_policy_payload(body.update_policy),
        run_mode=body.run_mode,
        priority=body.priority,
        settings=settings,
    )
    return preview_response(result, started_at=started_at)
