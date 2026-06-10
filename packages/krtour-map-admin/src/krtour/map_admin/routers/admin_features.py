"""``/admin/features`` 운영 feature 라우터 (ADR-045 T-207c)."""

from __future__ import annotations

from datetime import datetime
from time import perf_counter
from typing import Annotated, Any, Literal, cast

from fastapi import APIRouter, Depends, HTTPException, Query, status
from krtour.map.core import make_feature_id
from krtour.map.infra.admin_feature_repo import (
    AdminFeaturePage,
    AdminFeatureRow,
    FeatureChangeConflict,
    FeatureChangeRequest,
    FeatureDeactivateResult,
    FeatureOverride,
    FeatureStateConflict,
    apply_feature_change_request,
    deactivate_feature,
    list_admin_features,
    list_feature_change_requests,
    reject_feature_change_request,
    submit_feature_change_request,
)
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from krtour.map_admin.auth import require_admin_destructive_enabled
from krtour.map_admin.db import get_session
from krtour.map_admin.response import Meta, make_meta
from krtour.map_admin.settings import AdminSettings

__all__ = [
    "router",
    "AdminFeatureRecord",
    "AdminFeaturesListResponse",
    "AdminFeatureDeactivateRequest",
    "AdminFeatureDeactivateResponse",
    "AdminFeatureCreateRequest",
    "AdminFeaturePatchRequest",
    "AdminFeatureChangeResponse",
]


router = APIRouter(prefix="/admin/features", tags=["admin-features"])

AdminFeatureSort = Literal[
    "name",
    "updated_at",
    "created_at",
    "kind",
    "status",
    "provider",
    "issue_count",
]
SortOrder = Literal["asc", "desc"]
FeatureMutationReviewMode = Literal["require_review", "immediate"]


class AdminFeatureIssueRecord(BaseModel):
    """Admin feature 목록 issue summary."""

    model_config = ConfigDict(extra="forbid")

    issue_id: str | None = None
    violation_type: str | None = None
    severity: str | None = None
    message: str | None = None
    detected_at: datetime | None = None


class AdminFeatureRecord(BaseModel):
    """``GET /admin/features`` item."""

    model_config = ConfigDict(extra="forbid")

    feature_id: str
    kind: str
    name: str
    category: str
    status: str
    lon: float | None = None
    lat: float | None = None
    address_label: str
    primary_provider: str | None = None
    primary_dataset_key: str | None = None
    issue_count: int
    issues: list[AdminFeatureIssueRecord]
    created_at: datetime
    updated_at: datetime


class AdminFeaturesListData(BaseModel):
    """Admin feature 목록 data."""

    model_config = ConfigDict(extra="forbid")

    items: list[AdminFeatureRecord]


class AdminFeaturesListResponse(BaseModel):
    """``GET /admin/features`` 응답."""

    model_config = ConfigDict(extra="forbid")

    data: AdminFeaturesListData
    meta: Meta


class AdminFeatureOverrideRecord(BaseModel):
    """생성/갱신된 feature override."""

    model_config = ConfigDict(extra="forbid")

    override_id: str
    feature_id: str
    field_path: str
    override_value: Any
    prevent_provider_reactivation: bool
    reason: str | None = None
    created_by: str | None = None
    created_at: datetime


class AdminFeatureDeactivateRequest(BaseModel):
    """``POST /admin/features/{feature_id}/deactivate`` body."""

    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1)
    operator: str | None = None
    prevent_provider_reactivation: bool = True


class AdminFeatureDeactivateData(BaseModel):
    """Feature deactivate 결과 data."""

    model_config = ConfigDict(extra="forbid")

    feature_id: str
    previous_status: str
    status: str
    override_created: bool
    override: AdminFeatureOverrideRecord | None = None


class AdminFeatureDeactivateResponse(BaseModel):
    """``POST /admin/features/{feature_id}/deactivate`` 응답."""

    model_config = ConfigDict(extra="forbid")

    data: AdminFeatureDeactivateData
    meta: Meta


class AdminFeatureCoordInput(BaseModel):
    """Feature mutation 좌표 입력."""

    model_config = ConfigDict(extra="forbid")

    lon: float = Field(ge=124.0, le=132.0)
    lat: float = Field(ge=33.0, le=39.5)


class AdminFeatureBaseMutation(BaseModel):
    """place/event feature 추가·수정 공통 입력."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1)
    category: str | None = Field(default=None, pattern=r"^\d{8}$")
    coord: AdminFeatureCoordInput | None = None
    coord_precision_digits: int | None = Field(default=None, ge=3, le=8)
    geom: str | None = None
    address: dict[str, Any] | None = None
    legal_dong_code: str | None = None
    road_name_code: str | None = None
    road_address_management_no: str | None = None
    admin_dong_code: str | None = None
    sido_code: str | None = None
    sigungu_code: str | None = None
    urls: dict[str, Any] | None = None
    marker_icon: str | None = Field(default=None, min_length=1)
    marker_color: str | None = Field(default=None, pattern=r"^P-(0[1-9]|1[0-6])$")
    parent_feature_id: str | None = None
    sibling_group_id: str | None = None
    detail: dict[str, Any] | None = None


class AdminFeatureCreateRequest(AdminFeatureBaseMutation):
    """``POST /admin/features`` body."""

    feature_id: str | None = Field(
        default=None,
        description=(
            "기존 provider feature와 겹치는 사용자 version을 만들 때 명시한다. "
            "미지정 시 user_request 자연키로 새 feature_id를 생성한다."
        ),
    )
    kind: Literal["place", "event"]
    name: str = Field(min_length=1)
    category: str = Field(pattern=r"^\d{8}$")
    marker_icon: str = Field(min_length=1)
    marker_color: str = Field(pattern=r"^P-(0[1-9]|1[0-6])$")
    status: Literal["draft", "active", "inactive", "hidden"] = "active"
    reason: str = Field(min_length=1)
    operator: str | None = None
    idempotency_key: str | None = Field(
        default=None,
        description="feature_id 미지정 시 source_natural_key로 쓰는 caller-provided key.",
    )


class AdminFeaturePatchRequest(AdminFeatureBaseMutation):
    """``PATCH /admin/features/{feature_id}`` body."""

    reason: str = Field(min_length=1)
    operator: str | None = None

    @model_validator(mode="after")
    def _at_least_one_patch_field(self) -> AdminFeaturePatchRequest:
        values = self.model_dump(exclude={"reason", "operator"}, exclude_unset=True)
        if not values:
            raise ValueError("수정할 feature field가 1개 이상 필요")
        return self


class AdminFeatureDeleteRequest(BaseModel):
    """``DELETE /admin/features/{feature_id}`` body."""

    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1)
    operator: str | None = None


class AdminFeatureChangeRequestRecord(BaseModel):
    """feature add/update/delete request 응답 data."""

    model_config = ConfigDict(extra="forbid")

    request_id: str
    feature_id: str
    action: Literal["add", "update", "delete"]
    status: Literal["pending", "applied", "rejected"]
    review_mode: FeatureMutationReviewMode
    payload: dict[str, Any]
    reason: str | None = None
    requested_by: str | None = None
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    applied_at: datetime | None = None
    created_at: datetime


class AdminFeatureChangeData(BaseModel):
    """단건 feature change response data."""

    model_config = ConfigDict(extra="forbid")

    request: AdminFeatureChangeRequestRecord


class AdminFeatureChangeResponse(BaseModel):
    """feature add/update/delete/approve/reject 응답."""

    model_config = ConfigDict(extra="forbid")

    data: AdminFeatureChangeData
    meta: Meta


class AdminFeatureChangeListData(BaseModel):
    """feature change request list data."""

    model_config = ConfigDict(extra="forbid")

    items: list[AdminFeatureChangeRequestRecord]
    review_mode: FeatureMutationReviewMode


class AdminFeatureChangeListResponse(BaseModel):
    """``GET /admin/features/change-requests`` 응답."""

    model_config = ConfigDict(extra="forbid")

    data: AdminFeatureChangeListData
    meta: Meta


class AdminFeatureReviewActionRequest(BaseModel):
    """approve/reject body."""

    model_config = ConfigDict(extra="forbid")

    operator: str | None = None
    reason: str | None = None


def _settings() -> AdminSettings:
    return AdminSettings()


def _issue_record(issue: dict[str, Any]) -> AdminFeatureIssueRecord:
    return AdminFeatureIssueRecord(
        issue_id=issue.get("issue_id"),
        violation_type=issue.get("violation_type"),
        severity=issue.get("severity"),
        message=issue.get("message"),
        detected_at=issue.get("detected_at"),
    )


def _record(row: AdminFeatureRow) -> AdminFeatureRecord:
    return AdminFeatureRecord(
        feature_id=row.feature_id,
        kind=row.kind,
        name=row.name,
        category=row.category,
        status=row.status,
        lon=row.lon,
        lat=row.lat,
        address_label=row.address_label,
        primary_provider=row.primary_provider,
        primary_dataset_key=row.primary_dataset_key,
        issue_count=row.issue_count,
        issues=[_issue_record(issue) for issue in row.issues],
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _override(row: FeatureOverride | None) -> AdminFeatureOverrideRecord | None:
    if row is None:
        return None
    return AdminFeatureOverrideRecord(
        override_id=row.override_id,
        feature_id=row.feature_id,
        field_path=row.field_path,
        override_value=row.override_value,
        prevent_provider_reactivation=row.prevent_provider_reactivation,
        reason=row.reason,
        created_by=row.created_by,
        created_at=row.created_at,
    )


def _deactivate_response(
    row: FeatureDeactivateResult,
    *,
    started_at: float,
) -> AdminFeatureDeactivateResponse:
    return AdminFeatureDeactivateResponse(
        data=AdminFeatureDeactivateData(
            feature_id=row.feature_id,
            previous_status=row.previous_status,
            status=row.status,
            override_created=row.override_created,
            override=_override(row.override),
        ),
        meta=make_meta(started_at=started_at),
    )


def _change_record(row: FeatureChangeRequest) -> AdminFeatureChangeRequestRecord:
    return AdminFeatureChangeRequestRecord(
        request_id=row.request_id,
        feature_id=row.feature_id,
        action=row.action,
        status=row.state,
        review_mode=row.review_mode,
        payload=row.payload,
        reason=row.reason,
        requested_by=row.requested_by,
        reviewed_by=row.reviewed_by,
        reviewed_at=row.reviewed_at,
        applied_at=row.applied_at,
        created_at=row.created_at,
    )


def _change_response(
    row: FeatureChangeRequest,
    *,
    started_at: float,
) -> AdminFeatureChangeResponse:
    return AdminFeatureChangeResponse(
        data=AdminFeatureChangeData(request=_change_record(row)),
        meta=make_meta(started_at=started_at),
    )


def _review_mode(settings: AdminSettings) -> FeatureMutationReviewMode:
    mode = settings.feature_change_review_mode
    if mode not in {"require_review", "immediate"}:
        return "require_review"
    return cast(FeatureMutationReviewMode, mode)


def _payload(body: AdminFeatureBaseMutation) -> dict[str, Any]:
    raw = body.model_dump(exclude={"reason", "operator"}, exclude_unset=True)
    coord = raw.get("coord")
    if isinstance(coord, dict):
        raw["coord"] = {"lon": coord["lon"], "lat": coord["lat"]}
    return raw


def _create_feature_id(body: AdminFeatureCreateRequest) -> str:
    if body.feature_id:
        return body.feature_id
    coord_key = "global"
    if body.coord is not None:
        coord_key = f"{body.coord.lon:.6f},{body.coord.lat:.6f}"
    natural_key = body.idempotency_key or f"{body.name}:{coord_key}"
    return make_feature_id(
        bjd_code=body.legal_dong_code,
        kind=body.kind,
        category=body.category,
        source_type="user_request",
        source_natural_key=natural_key,
    )


def _change_error(exc: FeatureChangeConflict) -> HTTPException:
    status_code = (
        status.HTTP_404_NOT_FOUND
        if "feature 없음" in str(exc)
        else status.HTTP_409_CONFLICT
    )
    return HTTPException(status_code=status_code, detail=str(exc))


@router.get("", response_model=AdminFeaturesListResponse)
async def list_features(
    session: Annotated[AsyncSession, Depends(get_session)],
    q: Annotated[str | None, Query(description="name/address/feature/source 검색")] = None,
    kind: Annotated[list[str] | None, Query(description="feature kind 반복 필터")] = None,
    category: Annotated[
        list[str] | None,
        Query(description="category code 반복 필터"),
    ] = None,
    feature_status: Annotated[
        list[str] | None,
        Query(alias="status", description="feature status 반복 필터. 기본 active."),
    ] = None,
    provider: Annotated[
        list[str] | None,
        Query(description="primary provider 반복 필터"),
    ] = None,
    dataset_key: Annotated[
        list[str] | None,
        Query(description="primary dataset_key 반복 필터"),
    ] = None,
    has_coord: Annotated[bool | None, Query()] = None,
    has_issue: Annotated[bool | None, Query()] = None,
    issue_type: Annotated[list[str] | None, Query()] = None,
    updated_from: Annotated[datetime | None, Query()] = None,
    updated_to: Annotated[datetime | None, Query()] = None,
    page_size: Annotated[int, Query(ge=1, le=500)] = 50,
    cursor: Annotated[str | None, Query()] = None,
    sort: Annotated[AdminFeatureSort, Query()] = "name",
    order: Annotated[SortOrder | None, Query()] = None,
) -> AdminFeaturesListResponse:
    started_at = perf_counter()
    effective_order: SortOrder = (
        "desc" if order is None and sort == "issue_count" else order or "asc"
    )
    try:
        page: AdminFeaturePage = await list_admin_features(
            session,
            q=q,
            kinds=kind,
            categories=category,
            statuses=feature_status if feature_status is not None else ("active",),
            providers=provider,
            dataset_keys=dataset_key,
            has_coord=has_coord,
            has_issue=has_issue,
            issue_types=issue_type,
            updated_from=updated_from,
            updated_to=updated_to,
            page_size=page_size,
            cursor=cursor,
            sort=sort,
            order=effective_order,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return AdminFeaturesListResponse(
        data=AdminFeaturesListData(items=[_record(item) for item in page.items]),
        meta=make_meta(
            started_at=started_at,
            page_size=page_size,
            next_cursor=page.next_cursor,
        ),
    )


@router.get(
    "/change-requests",
    response_model=AdminFeatureChangeListResponse,
)
async def list_feature_change_request_route(
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[AdminSettings, Depends(_settings)],
    status_filter: Annotated[
        list[Literal["pending", "applied", "rejected"]] | None,
        Query(alias="status"),
    ] = None,
    action: Annotated[
        list[Literal["add", "update", "delete"]] | None,
        Query(),
    ] = None,
    q: Annotated[str | None, Query()] = None,
    page_size: Annotated[int, Query(ge=1, le=500)] = 100,
) -> AdminFeatureChangeListResponse:
    started_at = perf_counter()
    rows = await list_feature_change_requests(
        session,
        states=status_filter,
        actions=action,
        q=q,
        limit=page_size,
    )
    return AdminFeatureChangeListResponse(
        data=AdminFeatureChangeListData(
            items=[_change_record(row) for row in rows],
            review_mode=_review_mode(settings),
        ),
        meta=make_meta(
            started_at=started_at,
            page_size=page_size,
            next_cursor=None,
        ),
    )


@router.post("", response_model=AdminFeatureChangeResponse)
async def create_feature_route(
    body: AdminFeatureCreateRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[AdminSettings, Depends(_settings)],
) -> AdminFeatureChangeResponse:
    started_at = perf_counter()
    feature_id = _create_feature_id(body)
    payload = _payload(body)
    payload["feature_id"] = feature_id
    async with session.begin():
        try:
            result = await submit_feature_change_request(
                session,
                action="add",
                feature_id=feature_id,
                payload=payload,
                review_mode=_review_mode(settings),
                reason=body.reason,
                requested_by=body.operator,
            )
        except FeatureChangeConflict as exc:
            raise _change_error(exc) from exc
    return _change_response(result, started_at=started_at)


@router.patch(
    "/{feature_id}",
    response_model=AdminFeatureChangeResponse,
    responses={404: {"description": "feature 없음"}, 409: {"description": "변경 불가"}},
)
async def patch_feature_route(
    feature_id: str,
    body: AdminFeaturePatchRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[AdminSettings, Depends(_settings)],
) -> AdminFeatureChangeResponse:
    started_at = perf_counter()
    async with session.begin():
        try:
            result = await submit_feature_change_request(
                session,
                action="update",
                feature_id=feature_id,
                payload=_payload(body),
                review_mode=_review_mode(settings),
                reason=body.reason,
                requested_by=body.operator,
            )
        except FeatureChangeConflict as exc:
            raise _change_error(exc) from exc
    return _change_response(result, started_at=started_at)


@router.delete(
    "/{feature_id}",
    response_model=AdminFeatureChangeResponse,
    responses={404: {"description": "feature 없음"}, 409: {"description": "삭제 불가"}},
)
async def delete_feature_route(
    feature_id: str,
    body: AdminFeatureDeleteRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[AdminSettings, Depends(_settings)],
) -> AdminFeatureChangeResponse:
    started_at = perf_counter()
    async with session.begin():
        try:
            result = await submit_feature_change_request(
                session,
                action="delete",
                feature_id=feature_id,
                payload={},
                review_mode=_review_mode(settings),
                reason=body.reason,
                requested_by=body.operator,
            )
        except FeatureChangeConflict as exc:
            raise _change_error(exc) from exc
    return _change_response(result, started_at=started_at)


@router.post(
    "/change-requests/{request_id}/approve",
    response_model=AdminFeatureChangeResponse,
    responses={404: {"description": "request 없음"}, 409: {"description": "승인 불가"}},
)
async def approve_feature_change_request_route(
    request_id: str,
    body: AdminFeatureReviewActionRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AdminFeatureChangeResponse:
    started_at = perf_counter()
    async with session.begin():
        try:
            result = await apply_feature_change_request(
                session,
                request_id,
                operator=body.operator,
            )
        except FeatureChangeConflict as exc:
            raise _change_error(exc) from exc
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"feature change request 없음: {request_id!r}",
        )
    return _change_response(result, started_at=started_at)


@router.post(
    "/change-requests/{request_id}/reject",
    response_model=AdminFeatureChangeResponse,
    responses={404: {"description": "request 없음"}},
)
async def reject_feature_change_request_route(
    request_id: str,
    body: AdminFeatureReviewActionRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AdminFeatureChangeResponse:
    started_at = perf_counter()
    async with session.begin():
        result = await reject_feature_change_request(
            session,
            request_id,
            operator=body.operator,
            reason=body.reason,
        )
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"pending feature change request 없음: {request_id!r}",
        )
    return _change_response(result, started_at=started_at)


@router.post(
    "/{feature_id}/deactivate",
    response_model=AdminFeatureDeactivateResponse,
    dependencies=[Depends(require_admin_destructive_enabled)],
    responses={
        404: {"description": "feature 없음"},
        409: {"description": "feature 상태 전이 불가"},
        403: {"description": "파괴적 admin 작업 비활성"},
    },
)
async def deactivate_feature_route(
    feature_id: str,
    body: AdminFeatureDeactivateRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AdminFeatureDeactivateResponse:
    started_at = perf_counter()
    async with session.begin():
        try:
            result = await deactivate_feature(
                session,
                feature_id,
                reason=body.reason,
                operator=body.operator,
                prevent_provider_reactivation=body.prevent_provider_reactivation,
            )
        except FeatureStateConflict as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(exc),
            ) from exc
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"feature 없음: {feature_id!r}",
        )
    return _deactivate_response(result, started_at=started_at)
