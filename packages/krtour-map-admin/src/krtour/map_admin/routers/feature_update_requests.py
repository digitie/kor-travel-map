"""Feature update request 운영 라우터 (ADR-045 T-207a).

OpenAPI로 들어온 지역/provider 갱신 요청을 ``ops.feature_update_requests`` 큐에
저장하고, 진행 상태 조회/취소/재요청을 제공한다. 실제 provider 실행은 Dagster
sensor/job(T-208e)이 맡는다.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import asynccontextmanager
from datetime import datetime
from time import perf_counter
from typing import Annotated, Any, Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status
from krtour.map.geocoding import (
    KraddrGeoRestClient,
    resolve_sigungu_by_radius,
)
from krtour.map.infra.feature_update_repo import (
    FeatureUpdateLockBusy,
    FeatureUpdateRequest,
    FeatureUpdateRequestPage,
    FeatureUpdateRequestPreview,
    cancel_update_request,
    enqueue_feature_update_request,
    get_update_request,
    list_update_requests,
)
from krtour.map.infra.scope_repo import SigunguByRadiusResolver
from krtour.map.settings import KrtourMapSettings
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)
from sqlalchemy.ext.asyncio import AsyncSession

from krtour.map_admin.db import get_session
from krtour.map_admin.response import Meta, make_meta

__all__ = [
    "router",
    "FeatureUpdateRequestCreateRequest",
    "FeatureUpdateRequestRecord",
    "FeatureUpdateRequestCreateResponse",
    "FeatureUpdateRequestListResponse",
]


ADMIN_FEATURE_UPDATE_REQUESTS_ROUTE_PREFIX = "/admin/feature-update-requests"
ADMIN_FEATURE_UPDATE_REQUESTS_URL_PREFIX = "/v1/admin/feature-update-requests"

router = APIRouter(
    prefix=ADMIN_FEATURE_UPDATE_REQUESTS_ROUTE_PREFIX,
    tags=["admin-update-requests"],
)

FeatureUpdateState = Literal["queued", "running", "done", "failed", "cancelled"]
RunMode = Literal["queued", "now"]
ScopeMode = Literal["center_radius", "sigungu_by_radius"]
SigunguRadiusMatch = Literal["intersects", "contains_center", "feature_sigungu"]
FeatureUpdatePolicyMode = Literal["refresh_existing"]
NonEmptyString = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)
]
FeatureIdString = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=256)
]
TargetKeyString = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=256)
]
MAX_PROVIDER_FILTERS = 32
MAX_DATASET_FILTERS = 64
MAX_SCOPE_FEATURE_IDS = 1000
MAX_SCOPE_TARGET_KEYS = 500
MAX_RADIUS_KM = 500.0
_SIGUNGU_RESOLVER_REQUIRED_MESSAGE = (
    "sigungu_by_radius scope에는 KRTOUR_MAP_KRADDR_GEO_BASE_URL 설정이 필요합니다."
)


class SigunguResolverUnavailable(RuntimeError):
    """시군구 반경 scope에 필요한 kraddr-geo resolver 설정이 없을 때 발생."""


class FeatureUpdatePoint(BaseModel):
    """WGS84 lon/lat 좌표."""

    model_config = ConfigDict(extra="forbid")

    lon: float = Field(ge=-180, le=180)
    lat: float = Field(ge=-90, le=90)


class FeatureIdsScope(BaseModel):
    """특정 feature id 목록 갱신 scope."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["feature_ids"]
    feature_ids: list[FeatureIdString] = Field(max_length=MAX_SCOPE_FEATURE_IDS)


class CenterRadiusScope(BaseModel):
    """좌표 중심 반경 갱신 scope."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["center_radius"]
    center: FeatureUpdatePoint
    radius_km: float = Field(gt=0, le=MAX_RADIUS_KM)


class SigunguByRadiusScope(BaseModel):
    """kraddr-geo가 계산한 반경 교차 시군구 기준 갱신 scope."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["sigungu_by_radius"]
    center: FeatureUpdatePoint
    radius_km: float = Field(gt=0, le=MAX_RADIUS_KM)
    match: SigunguRadiusMatch = "intersects"


class BboxScope(BaseModel):
    """WGS84 bbox 안 feature 갱신 scope."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["bbox"]
    min_lon: float = Field(ge=-180, le=180)
    min_lat: float = Field(ge=-90, le=90)
    max_lon: float = Field(ge=-180, le=180)
    max_lat: float = Field(ge=-90, le=90)

    @model_validator(mode="after")
    def _validate_order(self) -> BboxScope:
        if self.min_lon > self.max_lon or self.min_lat > self.max_lat:
            raise ValueError(
                "bbox min values must be less than or equal to max values"
            )
        return self


class ProviderDatasetScope(BaseModel):
    """특정 provider/dataset 자체 갱신 scope."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["provider_dataset"]
    provider: NonEmptyString
    dataset_key: NonEmptyString
    sync_scope: NonEmptyString | None = None


class CacheTargetKeysScope(BaseModel):
    """외부 POI/cache target key 목록 기반 갱신 scope."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["cache_target_keys"]
    external_system: NonEmptyString
    target_keys: list[TargetKeyString] = Field(max_length=MAX_SCOPE_TARGET_KEYS)
    radius_km: float | None = Field(default=None, gt=0, le=MAX_RADIUS_KM)
    scope_mode: ScopeMode = "center_radius"


FeatureUpdateScope = Annotated[
    FeatureIdsScope
    | CenterRadiusScope
    | SigunguByRadiusScope
    | BboxScope
    | ProviderDatasetScope
    | CacheTargetKeysScope,
    Field(discriminator="type"),
]


class FeatureUpdatePolicy(BaseModel):
    """Provider refresh 실행 정책 override."""

    model_config = ConfigDict(extra="forbid")

    mode: FeatureUpdatePolicyMode | None = None
    include_inactive: bool | None = None
    force_provider_call: bool | None = None
    dedup_after_load: bool | None = None
    consistency_check_after_load: bool | None = None
    prevent_provider_reactivation: bool | None = None


class FeatureUpdateRequestCreateRequest(BaseModel):
    """feature update request 생성 요청."""

    model_config = ConfigDict(extra="forbid")

    scope: FeatureUpdateScope = Field(description="feature update scope payload.")
    providers: list[NonEmptyString] = Field(
        default_factory=list,
        max_length=MAX_PROVIDER_FILTERS,
    )
    dataset_keys: list[NonEmptyString] = Field(
        default_factory=list,
        max_length=MAX_DATASET_FILTERS,
    )
    update_policy: FeatureUpdatePolicy = Field(default_factory=FeatureUpdatePolicy)
    run_mode: RunMode = "queued"
    priority: int = Field(default=50, ge=0, le=1000)
    dry_run: bool = False
    operator: str | None = None
    reason: str | None = None


class FeatureUpdateRequestRecord(BaseModel):
    """feature update request 행/preview의 HTTP 표현."""

    model_config = ConfigDict(extra="forbid")

    request_id: str | None = None
    scope_type: str
    scope: dict[str, Any]
    providers: list[str]
    dataset_keys: list[str]
    update_policy: dict[str, Any]
    run_mode: RunMode
    priority: int
    status: str
    dry_run: bool
    matched_scope: dict[str, Any]
    job_id: str | None = None
    dagster_run_id: str | None = None
    operator: str | None = None
    reason: str | None = None
    error_message: str | None = None
    created_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    updated_at: datetime | None = None
    status_url: str | None = None


class FeatureUpdateRequestCreateResponse(BaseModel):
    """생성/취소/run-now 응답."""

    model_config = ConfigDict(extra="forbid")

    data: FeatureUpdateRequestRecord
    meta: Meta


class FeatureUpdateRequestDetailResponse(BaseModel):
    """feature update request 단건 조회 응답 (DA-D-03 envelope)."""

    model_config = ConfigDict(extra="forbid")

    data: FeatureUpdateRequestRecord
    meta: Meta


class FeatureUpdateRequestListData(BaseModel):
    """feature update request 목록 data."""

    model_config = ConfigDict(extra="forbid")

    items: list[FeatureUpdateRequestRecord]


class FeatureUpdateRequestListResponse(BaseModel):
    """feature update request 목록 응답 (DA-D-03 envelope)."""

    model_config = ConfigDict(extra="forbid")

    data: FeatureUpdateRequestListData
    meta: Meta


class FeatureUpdateRequestCancelRequest(BaseModel):
    """취소 요청 body."""

    model_config = ConfigDict(extra="forbid")

    error_message: str | None = Field(
        default=None,
        description="취소 사유. 미지정 시 기본 메시지를 저장한다.",
    )


class FeatureUpdateRequestRunNowRequest(BaseModel):
    """기존 request payload를 run_mode=now로 재큐잉할 때의 override."""

    model_config = ConfigDict(extra="forbid")

    priority: int | None = Field(default=None, ge=0, le=1000)
    operator: str | None = None
    reason: str | None = None


def _scope_payload(scope: FeatureUpdateScope) -> dict[str, Any]:
    return scope.model_dump(mode="json", exclude_none=True)


def _update_policy_payload(policy: FeatureUpdatePolicy) -> dict[str, Any]:
    return policy.model_dump(mode="json", exclude_none=True, exclude_unset=True)


def _record_from_request(
    row: FeatureUpdateRequest,
    *,
    status_url_prefix: str = ADMIN_FEATURE_UPDATE_REQUESTS_URL_PREFIX,
) -> FeatureUpdateRequestRecord:
    return FeatureUpdateRequestRecord(
        request_id=row.request_id,
        scope_type=row.scope_type,
        scope=row.scope,
        providers=list(row.providers),
        dataset_keys=list(row.dataset_keys),
        update_policy=row.update_policy,
        run_mode=row.run_mode,
        priority=row.priority,
        status=row.state,
        dry_run=row.dry_run,
        matched_scope=row.matched_scope,
        job_id=row.job_id,
        dagster_run_id=row.dagster_run_id,
        operator=row.operator,
        reason=row.reason,
        error_message=row.error_message,
        created_at=row.created_at,
        started_at=row.started_at,
        finished_at=row.finished_at,
        updated_at=row.updated_at,
        status_url=f"{status_url_prefix}/{row.request_id}",
    )


def _record_from_preview(
    preview: FeatureUpdateRequestPreview,
) -> FeatureUpdateRequestRecord:
    return FeatureUpdateRequestRecord(
        scope_type=preview.scope_type,
        scope=preview.scope,
        providers=list(preview.providers),
        dataset_keys=list(preview.dataset_keys),
        update_policy=preview.update_policy,
        run_mode=preview.run_mode,
        priority=preview.priority,
        status="dry_run",
        dry_run=True,
        matched_scope=preview.matched_scope,
    )


def _create_response(
    data: FeatureUpdateRequest | FeatureUpdateRequestPreview,
    *,
    started_at: float,
    status_url_prefix: str = ADMIN_FEATURE_UPDATE_REQUESTS_URL_PREFIX,
) -> FeatureUpdateRequestCreateResponse:
    record = (
        _record_from_request(data, status_url_prefix=status_url_prefix)
        if isinstance(data, FeatureUpdateRequest)
        else _record_from_preview(data)
    )
    return FeatureUpdateRequestCreateResponse(
        data=record,
        meta=make_meta(started_at=started_at),
    )


def _scope_explicitly_needs_sigungu(scope: Mapping[str, Any]) -> bool:
    if scope.get("type") == "sigungu_by_radius":
        return True
    return (
        scope.get("type") == "cache_target_keys"
        and scope.get("scope_mode") == "sigungu_by_radius"
    )


@asynccontextmanager
async def _sigungu_resolver_for_scope(
    scope: Mapping[str, Any],
) -> AsyncIterator[SigunguByRadiusResolver | None]:
    settings = KrtourMapSettings()
    base_url = settings.kraddr_geo_base_url
    if base_url is None:
        if _scope_explicitly_needs_sigungu(scope):
            raise SigunguResolverUnavailable(_SIGUNGU_RESOLVER_REQUIRED_MESSAGE)
        yield None
        return

    async with httpx.AsyncClient(
        base_url=base_url,
        timeout=settings.kraddr_geo_timeout_seconds,
    ) as http:
        client = KraddrGeoRestClient(http)

        async def _resolver(
            *,
            lon: float,
            lat: float,
            radius_km: float,
        ) -> tuple[str, ...]:
            return await resolve_sigungu_by_radius(
                client, lon=lon, lat=lat, radius_km=radius_km
            )

        yield _resolver


def _handle_enqueue_error(exc: Exception) -> HTTPException:
    if isinstance(exc, FeatureUpdateLockBusy):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": exc.code,
                "message": str(exc),
                "details": {
                    "retry_after_seconds": exc.retry_after_seconds,
                },
            },
            headers={"Retry-After": str(exc.retry_after_seconds)},
        )
    if isinstance(exc, SigunguResolverUnavailable):
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        )
    message = str(exc)
    if isinstance(exc, ValueError):
        return HTTPException(status_code=422, detail=message)
    if isinstance(exc, httpx.HTTPError):
        return HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"kraddr-geo 호출 실패: {message}",
        )
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="feature update request enqueue failed",
    )


async def _enqueue(
    session: AsyncSession,
    *,
    scope: Mapping[str, Any],
    providers: Sequence[str],
    dataset_keys: Sequence[str],
    update_policy: Mapping[str, Any],
    run_mode: str,
    priority: int,
    dry_run: bool,
    operator: str | None,
    reason: str | None,
) -> FeatureUpdateRequest | FeatureUpdateRequestPreview:
    try:
        async with _sigungu_resolver_for_scope(scope) as sigungu_resolver:
            return await enqueue_feature_update_request(
                session,
                scope=scope,
                providers=providers,
                dataset_keys=dataset_keys,
                update_policy=update_policy,
                run_mode=run_mode,
                priority=priority,
                dry_run=dry_run,
                operator=operator,
                reason=reason,
                sigungu_resolver=sigungu_resolver,
            )
    except HTTPException:
        raise
    except Exception as exc:
        raise _handle_enqueue_error(exc) from exc


async def _create_feature_update_request_response(
    body: FeatureUpdateRequestCreateRequest,
    session: AsyncSession,
    *,
    status_url_prefix: str,
) -> FeatureUpdateRequestCreateResponse:
    started_at = perf_counter()
    scope = _scope_payload(body.scope)
    update_policy = _update_policy_payload(body.update_policy)
    if body.dry_run:
        result = await _enqueue(
            session,
            scope=scope,
            providers=body.providers,
            dataset_keys=body.dataset_keys,
            update_policy=update_policy,
            run_mode=body.run_mode,
            priority=body.priority,
            dry_run=True,
            operator=body.operator,
            reason=body.reason,
        )
        return _create_response(
            result,
            started_at=started_at,
            status_url_prefix=status_url_prefix,
        )

    async with session.begin():
        result = await _enqueue(
            session,
            scope=scope,
            providers=body.providers,
            dataset_keys=body.dataset_keys,
            update_policy=update_policy,
            run_mode=body.run_mode,
            priority=body.priority,
            dry_run=False,
            operator=body.operator,
            reason=body.reason,
        )
    return _create_response(
        result,
        started_at=started_at,
        status_url_prefix=status_url_prefix,
    )


@router.post(
    "",
    response_model=FeatureUpdateRequestCreateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="feature update request 생성 또는 dry-run",
    responses={
        409: {
            "description": (
                "run_mode=now 요청의 동일 scope advisory lock 경합"
            )
        }
    },
)
async def create_feature_update_request(
    body: FeatureUpdateRequestCreateRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> FeatureUpdateRequestCreateResponse:
    return await _create_feature_update_request_response(
        body,
        session,
        status_url_prefix=ADMIN_FEATURE_UPDATE_REQUESTS_URL_PREFIX,
    )


@router.get(
    "",
    response_model=FeatureUpdateRequestListResponse,
    summary="feature update request 목록",
)
async def list_feature_update_requests(
    session: Annotated[AsyncSession, Depends(get_session)],
    status_filter: Annotated[FeatureUpdateState | None, Query(alias="status")] = None,
    scope_type: Annotated[str | None, Query()] = None,
    provider: Annotated[str | None, Query()] = None,
    dataset_key: Annotated[str | None, Query()] = None,
    created_from: Annotated[datetime | None, Query()] = None,
    created_to: Annotated[datetime | None, Query()] = None,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: Annotated[str | None, Query()] = None,
) -> FeatureUpdateRequestListResponse:
    started_at = perf_counter()
    try:
        page: FeatureUpdateRequestPage = await list_update_requests(
            session,
            state=status_filter,
            scope_type=scope_type,
            provider=provider,
            dataset_key=dataset_key,
            created_from=created_from,
            created_to=created_to,
            limit=page_size,
            cursor=cursor,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return FeatureUpdateRequestListResponse(
        data=FeatureUpdateRequestListData(
            items=[_record_from_request(item) for item in page.items],
        ),
        meta=make_meta(
            started_at=started_at,
            page_size=page_size,
            next_cursor=page.next_cursor,
        ),
    )


@router.get(
    "/{request_id}",
    response_model=FeatureUpdateRequestDetailResponse,
    summary="feature update request 단건 조회",
    responses={404: {"description": "request_id 없음"}},
)
async def get_feature_update_request(
    request_id: str,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> FeatureUpdateRequestDetailResponse:
    started_at = perf_counter()
    row = await get_update_request(session, request_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"feature update request 없음: {request_id!r}",
        )
    return FeatureUpdateRequestDetailResponse(
        data=_record_from_request(row),
        meta=make_meta(started_at=started_at),
    )


@router.post(
    "/{request_id}/cancel",
    response_model=FeatureUpdateRequestCreateResponse,
    summary="feature update request 취소",
    responses={
        404: {"description": "request_id 없음"},
        409: {"description": "이미 terminal 상태라 취소 불가"},
    },
)
async def cancel_feature_update_request(
    request_id: str,
    session: Annotated[AsyncSession, Depends(get_session)],
    body: FeatureUpdateRequestCancelRequest | None = None,
) -> FeatureUpdateRequestCreateResponse:
    started_at = perf_counter()
    error_message = (
        body.error_message
        if body is not None and body.error_message
        else "cancelled by admin API"
    )
    async with session.begin():
        cancelled = await cancel_update_request(
            session, request_id, error_message=error_message
        )
        if cancelled is None:
            existing = await get_update_request(session, request_id)
            if existing is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"feature update request 없음: {request_id!r}",
                )
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"취소할 수 없는 상태: {existing.state}",
            )
    return _create_response(cancelled, started_at=started_at)


@router.post(
    "/{request_id}/run-now",
    response_model=FeatureUpdateRequestCreateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="기존 request payload를 run_mode=now로 재큐잉",
    responses={
        404: {"description": "request_id 없음"},
        409: {"description": "이미 running 상태 또는 동일 scope lock 경합"},
    },
)
async def run_feature_update_request_now(
    request_id: str,
    session: Annotated[AsyncSession, Depends(get_session)],
    body: FeatureUpdateRequestRunNowRequest | None = None,
) -> FeatureUpdateRequestCreateResponse:
    started_at = perf_counter()
    async with session.begin():
        existing = await get_update_request(session, request_id)
        if existing is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"feature update request 없음: {request_id!r}",
            )
        if existing.state == "running":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="이미 running 상태인 request는 run-now 재요청할 수 없습니다.",
            )
        result = await _enqueue(
            session,
            scope=existing.scope,
            providers=existing.providers,
            dataset_keys=existing.dataset_keys,
            update_policy=existing.update_policy,
            run_mode="now",
            priority=body.priority if body and body.priority is not None else existing.priority,
            dry_run=False,
            operator=body.operator if body and body.operator else existing.operator,
            reason=(
                body.reason
                if body and body.reason
                else f"run-now from {existing.request_id}"
            ),
        )
    return _create_response(result, started_at=started_at)
