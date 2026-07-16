"""Feature update request 운영 라우터 (ADR-045 T-207a).

OpenAPI로 들어온 지역/provider 갱신 요청을 ``ops.feature_update_requests`` 큐에
저장하고, 진행 상태 조회/취소/재요청을 제공한다. 실제 provider 실행은 Dagster
sensor/job(T-208e)이 맡는다.
"""

from __future__ import annotations

from datetime import datetime
from time import perf_counter
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from kortravelmap.infra.feature_update_repo import (
    FeatureUpdateRequestPage,
    get_update_request,
    list_update_requests,
)
from kortravelmap.settings import KorTravelMapSettings
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from kortravelmap.api import (
    feature_update_service,
    mois_source_precheck,
    pipeline_cancellation_service,
)
from kortravelmap.api.auth import AdminProxyContext, require_admin_frontend
from kortravelmap.api.dagster_http import (
    dagster_http_dependencies,
    http_client_from_request,
    settings_from_request,
)
from kortravelmap.api.db import get_engine, get_session
from kortravelmap.api.feature_update_http import (
    FEATURE_UPDATE_CONFLICT_RESPONSES,
    to_http_exception,
)
from kortravelmap.api.feature_update_schema import (
    FeatureUpdateRequestCreateRequest,
    FeatureUpdateRequestCreateResponse,
    FeatureUpdateRequestDetailResponse,
    FeatureUpdateRequestListData,
    FeatureUpdateRequestListResponse,
    FeatureUpdateRequestMutationResponse,
    FeatureUpdateRequestPreviewRequest,
    FeatureUpdateRequestPreviewResponse,
    FeatureUpdateRequestRecord,
    FeatureUpdateRequestRunNowRequest,
    FeatureUpdateState,
    ScopeType,
)
from kortravelmap.api.pipeline_cancellation_http import (
    error_responses as cancellation_error_responses,
)
from kortravelmap.api.pipeline_cancellation_http import (
    to_http_exception as cancellation_to_http_exception,
)
from kortravelmap.api.pipeline_cancellation_schema import (
    PipelineCancellationRequest,
    PipelineCancellationResponse,
)
from kortravelmap.api.response import make_meta

__all__ = [
    "router",
    "FeatureUpdateRequestCreateRequest",
    "FeatureUpdateRequestRecord",
    "FeatureUpdateRequestCreateResponse",
    "FeatureUpdateRequestMutationResponse",
    "FeatureUpdateRequestPreviewRequest",
    "FeatureUpdateRequestPreviewResponse",
    "FeatureUpdateRequestListResponse",
]


ADMIN_FEATURE_UPDATE_REQUESTS_ROUTE_PREFIX = "/admin/features/update-requests"
ADMIN_FEATURE_UPDATE_REQUESTS_URL_PREFIX = "/v1/admin/features/update-requests"

router = APIRouter(
    prefix=ADMIN_FEATURE_UPDATE_REQUESTS_ROUTE_PREFIX,
    tags=["admin-update-requests"],
)


async def _create_request_response(
    request: Request,
    body: FeatureUpdateRequestCreateRequest,
    session: AsyncSession,
    *,
    operator: str,
) -> FeatureUpdateRequestCreateResponse:
    api_settings = settings_from_request(request)
    dagster_client = http_client_from_request(request, api_settings)

    async def _resolved_plan_guard(
        resolved_pairs: frozenset[tuple[str, str]],
    ) -> None:
        await mois_source_precheck.ensure_mois_source_sync_for_plan(
            resolved_pairs,
            settings=api_settings,
            client=dagster_client,
        )

    try:
        return await feature_update_service.create_feature_update_request(
            body,
            session,
            operator=operator,
            status_url_prefix=ADMIN_FEATURE_UPDATE_REQUESTS_URL_PREFIX,
            settings=KorTravelMapSettings(),
            resolved_plan_guard=_resolved_plan_guard,
        )
    except (
        mois_source_precheck.MoisSourceSyncPrecheckError,
        mois_source_precheck.MoisSourceSyncRequired,
    ) as exc:
        raise mois_source_precheck.to_http_exception(exc) from exc
    except feature_update_service.FeatureUpdateServiceError as exc:
        raise to_http_exception(exc) from exc


async def _preview_request_response(
    body: FeatureUpdateRequestPreviewRequest,
    session: AsyncSession,
) -> FeatureUpdateRequestPreviewResponse:
    try:
        return await feature_update_service.preview_feature_update_request(
            body,
            session,
            settings=KorTravelMapSettings(),
        )
    except feature_update_service.FeatureUpdateServiceError as exc:
        raise to_http_exception(exc) from exc


@router.post(
    "",
    response_model=FeatureUpdateRequestCreateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="feature update request 생성",
    responses={
        200: {
            "model": FeatureUpdateRequestCreateResponse,
            "description": "같은 계획의 활성 canonical request 재사용",
        },
        **FEATURE_UPDATE_CONFLICT_RESPONSES,
        **mois_source_precheck.MOIS_SOURCE_PRECHECK_ERROR_RESPONSES,
    },
)
async def create_feature_update_request(
    request: Request,
    body: FeatureUpdateRequestCreateRequest,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AdminProxyContext, Depends(require_admin_frontend)],
) -> FeatureUpdateRequestCreateResponse:
    result = await _create_request_response(
        request,
        body,
        session,
        operator=context.actor,
    )
    if result.reused_active_request:
        response.status_code = status.HTTP_200_OK
    return result


@router.post(
    "/preview",
    response_model=FeatureUpdateRequestPreviewResponse,
    status_code=status.HTTP_200_OK,
    summary="feature update request 비영속 미리보기",
)
async def preview_feature_update_request(
    body: FeatureUpdateRequestPreviewRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> FeatureUpdateRequestPreviewResponse:
    return await _preview_request_response(body, session)


@router.get(
    "",
    response_model=FeatureUpdateRequestListResponse,
    summary="feature update request 목록",
)
async def list_feature_update_requests(
    session: Annotated[AsyncSession, Depends(get_session)],
    status_filter: Annotated[FeatureUpdateState | None, Query(alias="status")] = None,
    scope_type: Annotated[ScopeType | None, Query()] = None,
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


@router.get(
    "/{request_id}",
    response_model=FeatureUpdateRequestDetailResponse,
    summary="feature update request 단건 조회",
    responses={404: {"description": "request_id 없음"}},
)
async def get_feature_update_request(
    request_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> FeatureUpdateRequestDetailResponse:
    started_at = perf_counter()
    row = await get_update_request(session, str(request_id))
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"feature update request 없음: {request_id!r}",
        )
    return FeatureUpdateRequestDetailResponse(
        data=feature_update_service.record_from_request(row),
        meta=make_meta(started_at=started_at),
    )


@router.post(
    "/{request_id}/cancel",
    response_model=PipelineCancellationResponse,
    summary="feature update request 계층 취소",
    responses=cancellation_error_responses(not_found_description="request_id 없음"),
)
async def cancel_feature_update_request(
    request_id: UUID,
    request: Request,
    engine: Annotated[AsyncEngine, Depends(get_engine)],
    context: Annotated[AdminProxyContext, Depends(require_admin_frontend)],
    body: PipelineCancellationRequest | None = None,
) -> PipelineCancellationResponse:
    started_at = perf_counter()
    settings, http_client = dagster_http_dependencies(request)
    try:
        detail = await pipeline_cancellation_service.cancel_pipeline_execution(
            engine=engine,
            settings=settings,
            http_client=http_client,
            kind="update_request",
            execution_id=str(request_id),
            requested_by=context.actor,
            reason=body.reason if body is not None else None,
        )
    except pipeline_cancellation_service.PipelineCancellationServiceError as exc:
        raise cancellation_to_http_exception(exc) from exc
    return PipelineCancellationResponse(
        data=detail,
        meta=make_meta(started_at=started_at),
    )


@router.post(
    "/{request_id}/run-now",
    response_model=FeatureUpdateRequestMutationResponse,
    status_code=status.HTTP_200_OK,
    summary="기존 canonical request 우선 dispatch 요청",
    responses={
        404: {"description": "request_id 없음"},
        **FEATURE_UPDATE_CONFLICT_RESPONSES,
    },
)
async def run_feature_update_request_now(
    request_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    _context: Annotated[AdminProxyContext, Depends(require_admin_frontend)],
    _body: FeatureUpdateRequestRunNowRequest | None = None,
) -> FeatureUpdateRequestMutationResponse:
    started_at = perf_counter()
    try:
        async with session.begin():
            result = await feature_update_service.run_feature_update_request_now(
                session,
                request_id=str(request_id),
            )
    except feature_update_service.FeatureUpdateServiceError as exc:
        raise to_http_exception(exc) from exc
    return feature_update_service.persisted_response(result, started_at=started_at)
