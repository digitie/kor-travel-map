"""Feature update request application service.

scope 검증, geo resolver 조립, 큐 적재와 HTTP 표현 변환을 제공한다. 예외는 typed
application exception으로 노출하며 HTTP status 매핑은 각 라우터가 담당한다.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import asynccontextmanager
from time import perf_counter
from typing import Any

import httpx
from kortravelmap.geocoding import KorTravelGeoRestClient, resolve_sigungu_by_radius
from kortravelmap.infra.feature_update_repo import (
    FeatureUpdateLockBusy,
    FeatureUpdateRequest,
    FeatureUpdateRequestPreview,
    enqueue_feature_update_request,
)
from kortravelmap.infra.feature_update_repo import (
    preview_feature_update_request as preview_feature_update_request_repo,
)
from kortravelmap.infra.scope_repo import SigunguByRadiusResolver
from kortravelmap.settings import KorTravelMapSettings
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
from kortravelmap.api.provider_catalog import catalog_refreshable_entries
from kortravelmap.api.response import make_meta

__all__ = [
    "FeatureUpdateEnqueueError",
    "FeatureUpdateLockConflict",
    "FeatureUpdateResolverError",
    "FeatureUpdateServiceError",
    "FeatureUpdateValidationError",
    "SigunguResolverUnavailable",
    "create_feature_update_request",
    "created_response",
    "enqueue_update_request",
    "persisted_response",
    "preview_feature_update_request",
    "preview_response",
    "preview_update_request",
    "record_from_request",
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


class FeatureUpdateLockConflict(RuntimeError, FeatureUpdateServiceError):
    """동일 scope 즉시 실행 advisory lock 경합."""

    def __init__(self, exc: FeatureUpdateLockBusy) -> None:
        super().__init__(str(exc))
        self.code = exc.code
        self.retry_after_seconds = exc.retry_after_seconds


class FeatureUpdateResolverError(RuntimeError, FeatureUpdateServiceError):
    """kor-travel-geo 호출이 실패했다."""


class FeatureUpdateEnqueueError(RuntimeError, FeatureUpdateServiceError):
    """분류할 수 없는 큐 적재 실패."""


def _scope_payload(scope: FeatureUpdateScope) -> dict[str, Any]:
    return scope.model_dump(mode="json", exclude_none=True)


def _update_policy_payload(policy: FeatureUpdatePolicy) -> dict[str, Any]:
    return dict(policy)


def record_from_request(
    row: FeatureUpdateRequest,
    *,
    status_url_prefix: str = DEFAULT_STATUS_URL_PREFIX,
) -> FeatureUpdateRequestRecord:
    """저장 행을 persisted HTTP 표현으로 변환한다."""

    return FeatureUpdateRequestRecord(
        request_id=row.request_id,
        scope_type=row.scope_type,
        scope=row.scope,
        providers=list(row.providers),
        dataset_keys=list(row.dataset_keys),
        update_policy=row.update_policy,
        run_mode=row.run_mode,
        priority=row.priority,
        status=row.status,
        matched_scope=row.matched_scope,
        job_id=row.job_id,
        dagster_run_id=row.dagster_run_id,
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
    status_url_prefix: str = DEFAULT_STATUS_URL_PREFIX,
) -> FeatureUpdateRequestCreateResponse:
    """새 영속 요청을 생성 응답으로 변환한다."""

    persisted = record_from_request(data, status_url_prefix=status_url_prefix)
    return FeatureUpdateRequestCreateResponse(
        data=FeatureUpdateRequestCreatedRecord(
            result_kind="request",
            **persisted.model_dump(),
        ),
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


def _validate_refreshable_request(
    *,
    scope: Mapping[str, Any],
    providers: Sequence[str],
    dataset_keys: Sequence[str],
) -> None:
    refreshable_pairs = _refreshable_pairs()
    refreshable_providers = {provider for provider, _dataset in refreshable_pairs}
    refreshable_datasets = {dataset for _provider, dataset in refreshable_pairs}

    def reject(provider: str | None, dataset_key: str | None) -> None:
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

    if providers and dataset_keys:
        for provider in providers:
            for dataset_key in dataset_keys:
                if (provider, dataset_key) not in refreshable_pairs:
                    reject(provider, dataset_key)
        return

    for provider in providers:
        if provider not in refreshable_providers:
            reject(provider, None)
    for dataset_key in dataset_keys:
        if dataset_key not in refreshable_datasets:
            reject(None, dataset_key)


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

    _validate_refreshable_request(
        scope=scope,
        providers=providers,
        dataset_keys=dataset_keys,
    )
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

    _validate_refreshable_request(
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


async def create_feature_update_request(
    body: FeatureUpdateRequestCreateRequest,
    session: AsyncSession,
    *,
    operator: str,
    status_url_prefix: str,
    settings: KorTravelMapSettings,
) -> FeatureUpdateRequestCreateResponse:
    """영속 갱신 요청을 생성하고 201 응답을 만든다."""

    started_at = perf_counter()
    scope = _scope_payload(body.scope)
    update_policy = _update_policy_payload(body.update_policy)
    async with session.begin():
        result = await enqueue_update_request(
            session,
            scope=scope,
            providers=body.providers,
            dataset_keys=body.dataset_keys,
            update_policy=update_policy,
            run_mode=body.run_mode,
            priority=body.priority,
            operator=operator,
            reason=body.reason,
            settings=settings,
        )
    return created_response(
        result,
        started_at=started_at,
        status_url_prefix=status_url_prefix,
    )


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
