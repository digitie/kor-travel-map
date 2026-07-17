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
from typing import Any, NoReturn
from uuid import UUID

import httpx
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
from kortravelmap.infra.poi_cache_target_repo import (
    has_active_poi_cache_targets_for_external_system,
)
from kortravelmap.infra.scope_repo import SigunguByRadiusResolver
from kortravelmap.settings import KorTravelMapSettings
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.api.feature_update_schema import (
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
from kortravelmap.api.provider_catalog import (
    catalog_refreshable_entries,
    find_catalog_entry,
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

DEFAULT_STATUS_URL_PREFIX = "/v1/admin/features/update-requests"
_SIGUNGU_RESOLVER_REQUIRED_MESSAGE = (
    "sigungu_by_radius scope에는 KOR_TRAVEL_MAP_KOR_TRAVEL_GEO_BASE_URL 설정이 필요합니다."
)


class FeatureUpdateServiceError(Exception):
    """Feature update application service의 공개 예외 기반."""


class SigunguResolverUnavailable(RuntimeError, FeatureUpdateServiceError):
    """시군구 반경 scope에 필요한 kor-travel-geo resolver 설정이 없을 때 발생."""


class FeatureUpdateValidationError(ValueError, FeatureUpdateServiceError):
    """요청 scope/provider/dataset 조합이 유효하지 않다."""


ResolvedPlanGuard = Callable[
    [frozenset[tuple[str, str]]],
    Awaitable[None],
]
"""영속 전 canonical provider/dataset exact pair 선행조건 검사."""


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
    """Global key가 다른 canonical body 또는 actor에 이미 사용됐다."""

    code = "FEATURE_UPDATE_IDEMPOTENCY_CONFLICT"

    def __init__(self, *, idempotency_key: str, request_id: str) -> None:
        super().__init__("같은 Idempotency-Key를 다른 갱신 요청에 재사용할 수 없습니다.")
        self.idempotency_key = idempotency_key
        self.request_id = request_id


class FeatureUpdateRequestNotFound(LookupError, FeatureUpdateServiceError):
    """request_id에 해당하는 canonical feature update request가 없다."""


class FeatureUpdateResolverError(RuntimeError, FeatureUpdateServiceError):
    """kor-travel-geo 호출이 실패했다."""


class FeatureUpdateEnqueueError(RuntimeError, FeatureUpdateServiceError):
    """분류할 수 없는 큐 적재 실패."""


def _scope_payload(scope: FeatureUpdateScope) -> dict[str, Any]:
    return scope.model_dump(mode="json", exclude_none=True)


def _update_policy_payload(policy: FeatureUpdatePolicy) -> dict[str, Any]:
    return dict(policy)


def _canonical_feature_update_request_body(
    body: FeatureUpdateRequestCreateRequest,
) -> dict[str, Any]:
    """Fingerprint와 실행 plan이 함께 쓰는 validated canonical body."""
    canonical_body = body.model_dump(mode="json", exclude_none=False)
    canonical_body["providers"] = sorted(canonical_body["providers"])
    canonical_body["dataset_keys"] = sorted(canonical_body["dataset_keys"])
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

    requested_sync_scope = (
        row.scope.get("sync_scope")
        if row.scope_type == "provider_dataset" and isinstance(row.scope.get("sync_scope"), str)
        else None
    )

    return FeatureUpdateRequestRecord(
        request_id=row.request_id,
        scope_type=row.scope_type,
        scope=row.scope,
        requested_sync_scope=requested_sync_scope,
        effective_sync_scope=row.effective_sync_scope,
        providers=list(row.providers),
        dataset_keys=list(row.dataset_keys),
        update_policy=row.update_policy,
        run_mode=row.run_mode,
        priority=row.priority,
        status=row.status,
        matched_scope=row.matched_scope,
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
        scope=preview.scope,
        providers=list(preview.providers),
        dataset_keys=list(preview.dataset_keys),
        update_policy=preview.update_policy,
        run_mode=preview.run_mode,
        priority=preview.priority,
        matched_scope=preview.matched_scope,
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


def _refreshable_pairs() -> frozenset[tuple[str, str]]:
    return frozenset((entry.provider, entry.dataset_key) for entry in catalog_refreshable_entries())


def _resolved_refreshable_pairs(
    *,
    scope: Mapping[str, Any],
    providers: Sequence[str],
    dataset_keys: Sequence[str],
) -> frozenset[tuple[str, str]]:
    """검증된 request filter를 실제 실행될 canonical exact pair로 확장한다."""

    refreshable_pairs = _refreshable_pairs()
    if scope.get("type") == "provider_dataset":
        return frozenset(
            {
                (
                    str(scope.get("provider", "")),
                    str(scope.get("dataset_key", "")),
                )
            }
        )
    if providers and dataset_keys:
        return frozenset(
            (provider, dataset_key) for provider in providers for dataset_key in dataset_keys
        )
    if providers:
        return frozenset(pair for pair in refreshable_pairs if pair[0] in providers)
    return frozenset(pair for pair in refreshable_pairs if pair[1] in dataset_keys)


async def _validate_refreshable_request(
    session: AsyncSession,
    *,
    scope: Mapping[str, Any],
    providers: Sequence[str],
    dataset_keys: Sequence[str],
) -> str | None:
    refreshable_pairs = _refreshable_pairs()
    target_scope_pairs = frozenset(
        (entry.provider, entry.dataset_key)
        for entry in catalog_refreshable_entries()
        if entry.scope_refresh_selector != "none"
    )
    refreshable_providers = {provider for provider, _dataset in refreshable_pairs}
    refreshable_datasets = {dataset for _provider, dataset in refreshable_pairs}

    def reject(provider: str | None, dataset_key: str | None) -> NoReturn:
        subject = (
            f"{provider}/{dataset_key}"
            if provider is not None and dataset_key is not None
            else provider
            if provider is not None
            else dataset_key
        )
        raise FeatureUpdateValidationError(
            "feature update request는 refresh 가능한 provider/dataset만 "
            f"요청할 수 있습니다: {subject}"
        )

    if scope.get("type") == "provider_dataset":
        provider = str(scope.get("provider", ""))
        dataset_key = str(scope.get("dataset_key", ""))
        if (provider, dataset_key) not in refreshable_pairs:
            reject(provider, dataset_key)
        entry = find_catalog_entry(provider, dataset_key)
        if entry is None:
            reject(provider, dataset_key)
        requested = scope.get("sync_scope")
        if entry.scope_refresh_selector == "none":
            if requested is not None:
                raise FeatureUpdateValidationError(
                    f"{provider}/{dataset_key}는 sync_scope 선택을 지원하지 않습니다."
                )
            return "dataset_wide"
        raw_scope = entry.sync_scope if requested is None else requested
        if not isinstance(raw_scope, str):
            raise FeatureUpdateValidationError("sync_scope는 문자열이어야 합니다.")
        try:
            canonical = parse_canonical_sync_scope(raw_scope)
        except ValueError as exc:
            raise FeatureUpdateValidationError(str(exc)) from exc
        if canonical.kind not in {"target_grids", "external_system"}:
            raise FeatureUpdateValidationError(
                f"{provider}/{dataset_key}는 target 기반 sync_scope만 지원합니다."
            )
        if (
            canonical.external_system is not None
            and not await has_active_poi_cache_targets_for_external_system(
                session,
                external_system=canonical.external_system,
            )
        ):
            raise FeatureUpdateValidationError(
                f"활성 POI cache target이 없는 external_system입니다: {canonical.external_system}"
            )
        return canonical.value

    if providers and dataset_keys:
        selected_pairs = {
            (provider, dataset_key) for provider in providers for dataset_key in dataset_keys
        }
    elif providers:
        selected_pairs = {pair for pair in refreshable_pairs if pair[0] in providers}
    elif dataset_keys:
        selected_pairs = {pair for pair in refreshable_pairs if pair[1] in dataset_keys}
    else:
        raise FeatureUpdateValidationError(
            "non-direct feature update request는 provider 또는 dataset_key "
            "filter를 하나 이상 지정해야 합니다."
        )
    unsupported_target_pairs = sorted(selected_pairs & target_scope_pairs)
    if unsupported_target_pairs:
        subjects = ", ".join(
            f"{provider}/{dataset_key}" for provider, dataset_key in unsupported_target_pairs
        )
        raise FeatureUpdateValidationError(
            f"target 선택형 dataset은 provider_dataset scope로만 요청할 수 있습니다: {subjects}"
        )

    if providers and dataset_keys:
        for provider in providers:
            for dataset_key in dataset_keys:
                if (provider, dataset_key) not in refreshable_pairs:
                    reject(provider, dataset_key)
        return None

    for provider in providers:
        if provider not in refreshable_providers:
            reject(provider, None)
    for dataset_key in dataset_keys:
        if dataset_key not in refreshable_datasets:
            reject(None, dataset_key)
    return None


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
        base_url=base_url,
        timeout=settings.kor_travel_geo_timeout_seconds,
    ) as http:
        client = KorTravelGeoRestClient(
            http,
            api_key=settings.kor_travel_geo_api_key_value,
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
    if isinstance(exc, ValueError):
        return FeatureUpdateValidationError(str(exc))
    if isinstance(exc, httpx.HTTPError):
        return FeatureUpdateResolverError(f"kor-travel-geo 호출 실패: {exc}")
    return FeatureUpdateEnqueueError("feature update request enqueue failed")


async def enqueue_update_request(
    session: AsyncSession,
    *,
    scope: Mapping[str, Any],
    providers: Sequence[str],
    dataset_keys: Sequence[str],
    update_policy: Mapping[str, Any],
    run_mode: str,
    priority: int,
    operator: str | None,
    reason: str | None,
    settings: KorTravelMapSettings,
) -> FeatureUpdateRequest:
    """검증과 geo resolver를 적용해 영속 갱신 요청을 큐에 넣는다."""

    effective_sync_scope = await _validate_refreshable_request(
        session,
        scope=scope,
        providers=providers,
        dataset_keys=dataset_keys,
    )
    return await _enqueue_validated_update_request(
        session,
        scope=scope,
        effective_sync_scope=effective_sync_scope,
        providers=providers,
        dataset_keys=dataset_keys,
        update_policy=update_policy,
        run_mode=run_mode,
        priority=priority,
        operator=operator,
        reason=reason,
        settings=settings,
    )


async def _enqueue_validated_update_request(
    session: AsyncSession,
    *,
    scope: Mapping[str, Any],
    effective_sync_scope: str | None,
    providers: Sequence[str],
    dataset_keys: Sequence[str],
    update_policy: Mapping[str, Any],
    run_mode: str,
    priority: int,
    operator: str | None,
    reason: str | None,
    settings: KorTravelMapSettings,
) -> FeatureUpdateRequest:
    """검증이 끝난 계획을 scope resolver와 canonical queue writer에 전달한다."""

    try:
        async with _sigungu_resolver_for_scope(scope, settings=settings) as sigungu_resolver:
            return await enqueue_feature_update_request(
                session,
                scope=scope,
                providers=providers,
                dataset_keys=dataset_keys,
                update_policy=update_policy,
                run_mode=run_mode,
                priority=priority,
                operator=operator,
                reason=reason,
                effective_sync_scope=effective_sync_scope,
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
    providers: Sequence[str],
    dataset_keys: Sequence[str],
    update_policy: Mapping[str, Any],
    run_mode: str,
    priority: int,
    settings: KorTravelMapSettings,
) -> FeatureUpdateRequestPreview:
    """검증과 geo resolver를 적용하되 어떤 영속 행도 만들지 않는다."""

    await _validate_refreshable_request(
        session,
        scope=scope,
        providers=providers,
        dataset_keys=dataset_keys,
    )
    try:
        async with _sigungu_resolver_for_scope(scope, settings=settings) as sigungu_resolver:
            return await preview_feature_update_request_repo(
                session,
                scope=scope,
                providers=providers,
                dataset_keys=dataset_keys,
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
    providers: Sequence[str],
    dataset_keys: Sequence[str],
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
    if existing.scope_type == "provider_dataset":
        existing_scope.pop("sync_scope", None)
        requested_scope.pop("sync_scope", None)
    same_plan = (
        existing_scope == requested_scope
        and existing.providers == tuple(providers)
        and existing.dataset_keys == tuple(dataset_keys)
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


async def _find_reusable_provider_dataset_request(
    session: AsyncSession,
    *,
    scope: Mapping[str, Any],
    effective_sync_scope: str | None,
    providers: Sequence[str],
    dataset_keys: Sequence[str],
    update_policy: Mapping[str, Any],
    run_mode: str,
    priority: int,
    operator: str,
    reason: str | None,
) -> FeatureUpdateRequest | None:
    if scope.get("type") != "provider_dataset" or effective_sync_scope is None:
        return None
    provider = scope.get("provider")
    dataset_key = scope.get("dataset_key")
    if not isinstance(provider, str) or not isinstance(dataset_key, str):
        raise FeatureUpdateValidationError(
            "provider_dataset scope에는 provider와 dataset_key가 필요합니다."
        )
    existing = await find_active_provider_dataset_request(
        session,
        provider=provider,
        dataset_key=dataset_key,
        sync_scope=effective_sync_scope,
    )
    if existing is None:
        return None
    _assert_reusable_active_request(
        existing,
        scope=scope,
        providers=providers,
        dataset_keys=dataset_keys,
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
    """Durable key로 생성 결과를 재생하거나 canonical 요청을 생성/reuse한다."""

    started_at = perf_counter()
    canonical_body = _canonical_feature_update_request_body(body)
    scope = dict(canonical_body["scope"])
    providers = tuple(canonical_body["providers"])
    dataset_keys = tuple(canonical_body["dataset_keys"])
    update_policy = dict(canonical_body["update_policy"])
    normalized_key = str(idempotency_key)
    request_fingerprint = _feature_update_request_fingerprint(
        canonical_body,
        operator=operator,
    )
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
        mapping = await get_feature_update_request_idempotency(
            session,
            normalized_key,
            actor=operator,
        )
        if mapping is not None:
            if (
                mapping.fingerprint_version != 1
                or mapping.actor != operator
                or mapping.request_fingerprint != request_fingerprint
            ):
                raise FeatureUpdateIdempotencyConflict(
                    idempotency_key=normalized_key,
                    request_id=mapping.request_id,
                )
            result = await get_update_request(session, mapping.request_id)
            if result is None:
                raise FeatureUpdateEnqueueError(
                    "idempotency ledger가 존재하지 않는 request를 참조합니다."
                )
            replayed = True
            reused = mapping.reused_active_request
        else:
            effective_sync_scope = await _validate_refreshable_request(
                session,
                scope=scope,
                providers=providers,
                dataset_keys=dataset_keys,
            )
            await resolved_plan_guard(
                _resolved_refreshable_pairs(
                    scope=scope,
                    providers=providers,
                    dataset_keys=dataset_keys,
                )
            )
            result = await _find_reusable_provider_dataset_request(
                session,
                scope=scope,
                effective_sync_scope=effective_sync_scope,
                providers=providers,
                dataset_keys=dataset_keys,
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
                        result = await _enqueue_validated_update_request(
                            session,
                            scope=scope,
                            effective_sync_scope=effective_sync_scope,
                            providers=providers,
                            dataset_keys=dataset_keys,
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
                    result = await _find_reusable_provider_dataset_request(
                        session,
                        scope=scope,
                        effective_sync_scope=effective_sync_scope,
                        providers=providers,
                        dataset_keys=dataset_keys,
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
    result = await preview_update_request(
        session,
        scope=_scope_payload(body.scope),
        providers=body.providers,
        dataset_keys=body.dataset_keys,
        update_policy=_update_policy_payload(body.update_policy),
        run_mode=body.run_mode,
        priority=body.priority,
        settings=settings,
    )
    return preview_response(result, started_at=started_at)
