"""Feature update request 운영 라우터 (ADR-045 T-207a).

OpenAPI로 들어온 지역/provider 갱신 요청을 ``ops.feature_update_requests`` 큐에
저장하고, 진행 상태 조회/취소/재요청을 제공한다. 실제 provider 실행은 Dagster
sensor/job(T-208e)이 맡는다.
"""

from __future__ import annotations

from datetime import datetime
from time import perf_counter
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from kortravelmap.infra.feature_update_repo import (
    FeatureUpdateRequestPage,
    cancel_update_request,
    get_update_request,
    list_update_requests,
)
from kortravelmap.settings import KorTravelMapSettings
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.api import feature_update_service
from kortravelmap.api.db import get_session
from kortravelmap.api.feature_update_http import to_http_exception
from kortravelmap.api.feature_update_schema import (
    FeatureUpdateRequestCancelRequest,
    FeatureUpdateRequestCreateRequest,
    FeatureUpdateRequestCreateResponse,
    FeatureUpdateRequestDetailResponse,
    FeatureUpdateRequestListData,
    FeatureUpdateRequestListResponse,
    FeatureUpdateRequestRecord,
    FeatureUpdateRequestRunNowRequest,
    FeatureUpdateState,
)
from kortravelmap.api.response import make_meta

__all__ = [
    "router",
    "feature_router",
    "FeatureUpdateRequestCreateRequest",
    "FeatureUpdateRequestRecord",
    "FeatureUpdateRequestCreateResponse",
    "FeatureUpdateRequestListResponse",
]


ADMIN_FEATURE_UPDATE_REQUESTS_ROUTE_PREFIX = "/admin/feature-update-requests"
ADMIN_FEATURE_UPDATE_REQUESTS_URL_PREFIX = "/v1/admin/feature-update-requests"
ADMIN_FEATURE_UPDATE_REQUESTS_FEATURE_ROUTE_PREFIX = "/admin/features/update-requests"
ADMIN_FEATURE_UPDATE_REQUESTS_FEATURE_URL_PREFIX = "/v1/admin/features/update-requests"

router = APIRouter(
    prefix=ADMIN_FEATURE_UPDATE_REQUESTS_ROUTE_PREFIX,
    tags=["admin-update-requests"],
    include_in_schema=False,
)
feature_router = APIRouter(
    prefix=ADMIN_FEATURE_UPDATE_REQUESTS_FEATURE_ROUTE_PREFIX,
    tags=["admin-update-requests"],
)


async def _create_request_response(
    body: FeatureUpdateRequestCreateRequest,
    session: AsyncSession,
    *,
    status_url_prefix: str,
) -> FeatureUpdateRequestCreateResponse:
    try:
        return await feature_update_service.create_feature_update_request(
            body,
            session,
            status_url_prefix=status_url_prefix,
            settings=KorTravelMapSettings(),
        )
    except feature_update_service.FeatureUpdateServiceError as exc:
        raise to_http_exception(exc) from exc


@router.post(
    "",
    response_model=FeatureUpdateRequestCreateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="feature update request 생성 또는 dry-run",
    responses={409: {"description": ("run_mode=now 요청의 동일 scope advisory lock 경합")}},
)
async def create_feature_update_request(
    body: FeatureUpdateRequestCreateRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> FeatureUpdateRequestCreateResponse:
    return await _create_request_response(
        body,
        session,
        status_url_prefix=ADMIN_FEATURE_UPDATE_REQUESTS_URL_PREFIX,
    )


@feature_router.post(
    "",
    response_model=FeatureUpdateRequestCreateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="feature update request 생성 또는 dry-run",
    responses={409: {"description": ("run_mode=now 요청의 동일 scope advisory lock 경합")}},
)
async def create_feature_update_request_feature_route(
    body: FeatureUpdateRequestCreateRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> FeatureUpdateRequestCreateResponse:
    return await _create_request_response(
        body,
        session,
        status_url_prefix=ADMIN_FEATURE_UPDATE_REQUESTS_FEATURE_URL_PREFIX,
    )


@feature_router.get(
    "",
    response_model=FeatureUpdateRequestListResponse,
    summary="feature update request 목록",
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
            status=status_filter,
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
            items=[feature_update_service.record_from_request(item) for item in page.items],
        ),
        meta=make_meta(
            started_at=started_at,
            page_size=page_size,
            next_cursor=page.next_cursor,
        ),
    )


@feature_router.get(
    "/{request_id}",
    response_model=FeatureUpdateRequestDetailResponse,
    summary="feature update request 단건 조회",
    responses={404: {"description": "request_id 없음"}},
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
        data=feature_update_service.record_from_request(row),
        meta=make_meta(started_at=started_at),
    )


@feature_router.post(
    "/{request_id}/cancel",
    response_model=FeatureUpdateRequestCreateResponse,
    summary="feature update request 취소",
    responses={
        404: {"description": "request_id 없음"},
        409: {"description": "이미 terminal 상태라 취소 불가"},
    },
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
        body.error_message if body is not None and body.error_message else "cancelled by admin API"
    )
    async with session.begin():
        cancelled = await cancel_update_request(session, request_id, error_message=error_message)
        if cancelled is None:
            existing = await get_update_request(session, request_id)
            if existing is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"feature update request 없음: {request_id!r}",
                )
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"취소할 수 없는 상태: {existing.status}",
            )
    return feature_update_service.create_response(cancelled, started_at=started_at)


@feature_router.post(
    "/{request_id}/run-now",
    response_model=FeatureUpdateRequestCreateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="기존 request payload를 run_mode=now로 재큐잉",
    responses={
        404: {"description": "request_id 없음"},
        409: {"description": "이미 running 상태 또는 동일 scope lock 경합"},
    },
)
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
        if existing.status == "running":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="이미 running 상태인 request는 run-now 재요청할 수 없습니다.",
            )
        try:
            result = await feature_update_service.enqueue_update_request(
                session,
                scope=existing.scope,
                providers=existing.providers,
                dataset_keys=existing.dataset_keys,
                update_policy=existing.update_policy,
                run_mode="now",
                priority=(
                    body.priority
                    if body and body.priority is not None
                    else existing.priority
                ),
                dry_run=False,
                operator=body.operator if body and body.operator else existing.operator,
                reason=(
                    body.reason
                    if body and body.reason
                    else f"run-now from {existing.request_id}"
                ),
                settings=KorTravelMapSettings(),
            )
        except feature_update_service.FeatureUpdateServiceError as exc:
            raise to_http_exception(exc) from exc
    return feature_update_service.create_response(result, started_at=started_at)
