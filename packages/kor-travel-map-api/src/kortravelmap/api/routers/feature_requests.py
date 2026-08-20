"""T-VN-M04 범용 Feature request queue service/admin routes."""

from __future__ import annotations

from datetime import datetime
from math import isfinite
from time import perf_counter
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from kortravelmap.infra import feature_request_repo
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.api.auth import (
    AdminManualFeatureCreateContext,
    FeatureRequestServiceContext,
    require_admin_manual_feature_create,
    require_feature_request_service_principal,
)
from kortravelmap.api.db import get_session
from kortravelmap.api.domain_command_service import (
    current_domain_command,
    domain_command_transaction,
    idempotent_domain_command,
)
from kortravelmap.api.http_revision import revision_etag
from kortravelmap.api.response import Meta, make_meta

__all__ = ["admin_router", "service_router"]

service_router = APIRouter(
    prefix="/service/feature-requests", tags=["service-feature-requests"]
)
admin_router = APIRouter(
    prefix="/admin/feature-requests", tags=["admin-feature-requests"]
)


class FeatureRequestCoordInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lon: float = Field(ge=124, le=132)
    lat: float = Field(ge=33, le=39.5)

    @field_validator("lon", "lat")
    @classmethod
    def finite(cls, value: float) -> float:
        if not isfinite(value):
            raise ValueError("finite coordinate가 필요합니다.")
        return value


class FeatureRequestSubmitInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: UUID
    kind: Literal["place", "event"]
    name: str = Field(min_length=1, max_length=200)
    coord: FeatureRequestCoordInput
    categories: list[str] = Field(default_factory=list, max_length=10)
    note: str | None = Field(default=None, max_length=2000)


class FeatureRequestApprovalInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: str = Field(pattern=r"^\d{8}$")
    marker_color: str = Field(pattern=r"^P-(?:0[1-9]|1[0-6])$")
    marker_icon: str = Field(min_length=1, max_length=64)


class FeatureRequestRejectInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=500)


class FeatureRequestData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: UUID
    status: Literal["pending", "approved", "rejected", "exact_conflict"]
    kind: Literal["place", "event"]
    name: str
    coord: FeatureRequestCoordInput
    categories: list[str]
    note: str | None
    submitted_at: datetime
    resolved_at: datetime | None
    resolved_by_actor: str | None
    feature_id: str | None
    rejection_reason: str | None


class FeatureRequestResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data: FeatureRequestData
    meta: Meta


class FeatureRequestPageData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[FeatureRequestData]


class FeatureRequestPageResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data: FeatureRequestPageData
    meta: Meta


def _request_data(
    item: feature_request_repo.FeatureRequest,
) -> FeatureRequestData:
    payload = item.request_payload
    coord = FeatureRequestCoordInput(lon=float(payload["lon"]), lat=float(payload["lat"]))
    return FeatureRequestData(
        request_id=item.request_id,
        status=item.status,
        kind=payload["kind"],
        name=str(payload["name"]),
        coord=coord,
        categories=[str(value) for value in payload["categories"]],
        note=str(payload["note"]) if payload.get("note") is not None else None,
        submitted_at=item.submitted_at,
        resolved_at=item.resolved_at,
        resolved_by_actor=item.resolved_by_actor,
        feature_id=item.resolved_feature_id,
        rejection_reason=item.rejection_reason,
    )


async def _queue_item_or_404(
    session: AsyncSession, request_id: UUID
) -> feature_request_repo.FeatureRequest:
    item = await feature_request_repo.get_feature_request(
        session, request_id=request_id
    )
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "FEATURE_REQUEST_NOT_FOUND",
                "message": "Feature 요청을 찾을 수 없습니다.",
                "details": {},
            },
        )
    return item


@service_router.post(
    "",
    response_model=FeatureRequestResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        401: {"description": "Feature request service token 없음/불일치"},
        403: {"description": "다른 service scope token"},
        503: {"description": "M04 queue credential/activation 전"},
    },
)
@idempotent_domain_command("service.feature-request.submit.v1")
async def submit_feature_request_route(
    body: FeatureRequestSubmitInput,
    request: Request,
    context: Annotated[
        FeatureRequestServiceContext,
        Depends(require_feature_request_service_principal),
    ],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> FeatureRequestResponse:
    started_at = perf_counter()
    payload: dict[str, Any] = {
        "kind": body.kind,
        "name": body.name,
        "lon": body.coord.lon,
        "lat": body.coord.lat,
        "categories": body.categories,
    }
    if body.note is not None:
        payload["note"] = body.note
    try:
        async with domain_command_transaction(session):
            await feature_request_repo.submit_feature_request(
                session,
                request_id=body.request_id,
                request_payload=payload,
                command_id=current_domain_command().command_id,
            )
            item = await _queue_item_or_404(session, body.request_id)
    except feature_request_repo.FeatureRequestValidationError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "VALIDATION_ERROR", "message": str(error), "details": {}},
        ) from error
    except feature_request_repo.FeatureRequestError as error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "code": "INTERNAL_ERROR",
                "message": "Feature 요청 처리 중 내부 오류가 발생했습니다.",
                "details": {},
            },
        ) from error
    return FeatureRequestResponse(
        data=_request_data(item), meta=make_meta(request, started_at=started_at)
    )


@admin_router.get(
    "/{request_id}",
    response_model=FeatureRequestResponse,
    responses={404: {"description": "Feature 요청 없음"}},
)
async def get_feature_request_route(
    request_id: UUID,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> FeatureRequestResponse:
    started_at = perf_counter()
    item = await _queue_item_or_404(session, request_id)
    return FeatureRequestResponse(
        data=_request_data(item), meta=make_meta(request, started_at=started_at)
    )


@admin_router.get("", response_model=FeatureRequestPageResponse)
async def list_feature_requests_route(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    status_filter: Annotated[
        Literal["pending", "approved", "rejected", "exact_conflict"] | None,
        Query(alias="status"),
    ] = "pending",
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> FeatureRequestPageResponse:
    """Map admin이 pending queue를 UUID를 알기 전부터 발견할 수 있는 목록."""

    started_at = perf_counter()
    items = await feature_request_repo.list_feature_requests(
        session, status=status_filter, limit=limit
    )
    return FeatureRequestPageResponse(
        data=FeatureRequestPageData(items=[_request_data(item) for item in items]),
        meta=make_meta(request, started_at=started_at),
    )


@admin_router.post(
    "/{request_id}/approve",
    response_model=FeatureRequestResponse,
    status_code=status.HTTP_200_OK,
    responses={
        403: {"description": "admin manual Feature create scope 없음"},
        503: {"description": "수동 Feature 생성 승인 경계 비활성"},
        409: {"description": "pending 상태 아님"},
        422: {"description": "approval 입력 오류"},
        404: {"description": "Feature 요청 없음"},
    },
)
@idempotent_domain_command("admin.feature-request.approve.v1")
async def approve_feature_request_route(
    request_id: UUID,
    body: FeatureRequestApprovalInput,
    request: Request,
    response: Response,
    context: Annotated[
        AdminManualFeatureCreateContext,
        Depends(require_admin_manual_feature_create),
    ],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> FeatureRequestResponse:
    started_at = perf_counter()
    try:
        async with domain_command_transaction(session):
            item = await _queue_item_or_404(session, request_id)
            result = await feature_request_repo.approve_feature_request(
                session,
                request=item,
                category=body.category,
                marker_color=body.marker_color,
                marker_icon=body.marker_icon,
                command_id=current_domain_command().command_id,
            )
            if isinstance(result, feature_request_repo.FeatureRequestExactConflict):
                item = await _queue_item_or_404(session, request_id)
                return FeatureRequestResponse(
                    data=_request_data(item),
                    meta=make_meta(request, started_at=started_at),
                )
            item = await _queue_item_or_404(session, request_id)
    except feature_request_repo.FeatureRequestStateConflict as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "FEATURE_REQUEST_STATE_CONFLICT", "message": str(error), "details": {}},
        ) from error
    except feature_request_repo.FeatureRequestValidationError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "VALIDATION_ERROR", "message": str(error), "details": {}},
        ) from error
    except feature_request_repo.FeatureRequestError as error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "code": "INTERNAL_ERROR",
                "message": "Feature 요청 승인 중 내부 오류가 발생했습니다.",
                "details": {},
            },
        ) from error
    response.headers["ETag"] = revision_etag(result.row_revision)
    response.headers["Location"] = f"/v1/admin/features/{result.feature_uuid}"
    return FeatureRequestResponse(
        data=_request_data(item), meta=make_meta(request, started_at=started_at)
    )


@admin_router.post(
    "/{request_id}/reject",
    response_model=FeatureRequestResponse,
    responses={
        403: {"description": "admin manual Feature create scope 없음"},
        503: {"description": "수동 Feature 생성 승인 경계 비활성"},
        409: {"description": "pending 상태 아님"},
        422: {"description": "거절 입력 오류"},
        404: {"description": "Feature 요청 없음"},
    },
)
@idempotent_domain_command("admin.feature-request.reject.v1")
async def reject_feature_request_route(
    request_id: UUID,
    body: FeatureRequestRejectInput,
    request: Request,
    context: Annotated[
        AdminManualFeatureCreateContext,
        Depends(require_admin_manual_feature_create),
    ],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> FeatureRequestResponse:
    started_at = perf_counter()
    try:
        async with domain_command_transaction(session):
            await _queue_item_or_404(session, request_id)
            await feature_request_repo.reject_feature_request(
                session,
                request_id=request_id,
                reason=body.reason,
                command_id=current_domain_command().command_id,
            )
            item = await _queue_item_or_404(session, request_id)
    except feature_request_repo.FeatureRequestStateConflict as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "FEATURE_REQUEST_STATE_CONFLICT", "message": str(error), "details": {}},
        ) from error
    except feature_request_repo.FeatureRequestValidationError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "VALIDATION_ERROR", "message": str(error), "details": {}},
        ) from error
    except feature_request_repo.FeatureRequestError as error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "code": "INTERNAL_ERROR",
                "message": "Feature 요청 거절 중 내부 오류가 발생했습니다.",
                "details": {},
            },
        ) from error
    return FeatureRequestResponse(
        data=_request_data(item), meta=make_meta(request, started_at=started_at)
    )
