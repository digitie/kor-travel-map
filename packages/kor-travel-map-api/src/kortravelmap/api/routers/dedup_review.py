"""``/admin/dedup-reviews`` 운영 중복 후보 검토 라우터."""

from __future__ import annotations

from datetime import datetime
from time import perf_counter
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from kortravelmap.infra.admin_feature_repo import (
    DedupFeatureSummary,
    DedupReviewDetail,
    DedupReviewPage,
    DedupReviewRow,
    ReviewFeatureDetail,
    ReviewSourceDetail,
    get_dedup_review_detail,
    list_dedup_reviews,
    merge_dedup_review,
    set_dedup_review_decision,
)
from kortravelmap.infra.advisory_lock import advisory_lock
from kortravelmap.infra.merge_repo import (
    MergeConflictError,
    MergeError,
    MergeNotFoundError,
    MergeOutcome,
)
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.api.db import get_session
from kortravelmap.api.response import Meta, OffsetMeta, make_meta, make_offset_meta

__all__ = [
    "router",
    "DedupReviewRecord",
    "DedupReviewListResponse",
    "DedupReviewDetailResponse",
    "DedupReviewDecisionRequest",
    "DedupReviewDecisionResponse",
]


router = APIRouter(prefix="/admin/dedup-reviews", tags=["admin-dedup"])

DedupStatus = Literal["pending", "accepted", "rejected", "merged", "ignored"]
DedupDecision = Literal["accepted", "rejected", "merged", "ignored"]


class DedupFeatureRecord(BaseModel):
    """Dedup 후보 한쪽 feature summary."""

    model_config = ConfigDict(extra="forbid")

    feature_id: str
    name: str
    kind: str
    category: str
    lon: float | None = None
    lat: float | None = None
    provider: str | None = None
    dataset_key: str | None = None


class DedupReviewRecord(BaseModel):
    """``GET /admin/dedup-reviews`` item."""

    model_config = ConfigDict(extra="forbid")

    review_id: str
    status: str
    total_score: float
    name_score: float
    spatial_score: float
    category_score: float
    feature_a: DedupFeatureRecord
    feature_b: DedupFeatureRecord
    distance_m: float | None = None
    decision_reason: str | None = None
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    created_at: datetime


class DedupReviewListData(BaseModel):
    """Dedup review list data."""

    model_config = ConfigDict(extra="forbid")

    items: list[DedupReviewRecord]


class DedupReviewListResponse(BaseModel):
    """``GET /admin/dedup-reviews`` response."""

    model_config = ConfigDict(extra="forbid")

    data: DedupReviewListData
    meta: OffsetMeta


class ReviewSourceDetailRecord(BaseModel):
    """Review 상세 source record/link snapshot."""

    model_config = ConfigDict(extra="forbid")

    source_record_key: str
    provider: str
    dataset_key: str
    source_entity_type: str
    source_entity_id: str
    source_version: str | None = None
    raw_name: str | None = None
    raw_address: str | None = None
    raw_longitude: float | None = None
    raw_latitude: float | None = None
    raw_payload_hash: str
    raw_data: dict[str, Any]
    fetched_at: datetime | None = None
    imported_at: datetime | None = None
    expires_at: datetime | None = None
    source_role: str | None = None
    match_method: str | None = None
    confidence: int | None = None
    is_primary_source: bool | None = None
    linked_at: datetime | None = None


class ReviewFeatureDetailRecord(BaseModel):
    """Review 상세 feature snapshot."""

    model_config = ConfigDict(extra="forbid")

    feature_id: str
    kind: str
    name: str
    category: str
    status: str
    lon: float | None = None
    lat: float | None = None
    address: dict[str, Any]
    detail: dict[str, Any]
    urls: dict[str, Any]
    raw_refs: list[dict[str, Any]]
    marker_icon: str | None = None
    marker_color: str | None = None
    data_origin: str
    data_version: int
    created_at: datetime
    updated_at: datetime
    sources: list[ReviewSourceDetailRecord]


class DedupReviewDetailData(BaseModel):
    """Dedup review 상세 비교 data."""

    model_config = ConfigDict(extra="forbid")

    review_id: str
    status: str
    total_score: float
    name_score: float
    spatial_score: float
    category_score: float
    distance_m: float | None = None
    decision_reason: str | None = None
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    created_at: datetime
    feature_a: ReviewFeatureDetailRecord
    feature_b: ReviewFeatureDetailRecord


class DedupReviewDetailResponse(BaseModel):
    """``GET /admin/dedup-reviews/{review_id}`` response."""

    model_config = ConfigDict(extra="forbid")

    data: DedupReviewDetailData
    meta: Meta


class DedupReviewDecisionRequest(BaseModel):
    """``PATCH /admin/dedup-reviews/{review_id}`` body."""

    model_config = ConfigDict(extra="forbid")

    decision: DedupDecision
    master_feature_id: str | None = None
    decision_reason: str | None = Field(default=None, min_length=1)
    reviewed_by: str | None = None


class DedupReviewDecisionData(BaseModel):
    """Dedup decision result data."""

    model_config = ConfigDict(extra="forbid")

    review_id: str
    decision: DedupDecision
    changed: bool
    master_feature_id: str | None = None
    loser_feature_id: str | None = None
    merge_id: str | None = None
    source_links_moved: int | None = None
    source_links_dropped: int | None = None


class DedupReviewDecisionResponse(BaseModel):
    """``PATCH /admin/dedup-reviews/{review_id}`` response."""

    model_config = ConfigDict(extra="forbid")

    data: DedupReviewDecisionData
    meta: Meta


def _feature(item: DedupFeatureSummary) -> DedupFeatureRecord:
    return DedupFeatureRecord(
        feature_id=item.feature_id,
        name=item.name,
        kind=item.kind,
        category=item.category,
        lon=item.lon,
        lat=item.lat,
        provider=item.provider,
        dataset_key=item.dataset_key,
    )


def _record(row: DedupReviewRow) -> DedupReviewRecord:
    return DedupReviewRecord(
        review_id=row.review_id,
        status=row.status,
        total_score=row.total_score,
        name_score=row.name_score,
        spatial_score=row.spatial_score,
        category_score=row.category_score,
        feature_a=_feature(row.feature_a),
        feature_b=_feature(row.feature_b),
        distance_m=row.distance_m,
        decision_reason=row.decision_reason,
        reviewed_by=row.reviewed_by,
        reviewed_at=row.reviewed_at,
        created_at=row.created_at,
    )


def _source_detail(row: ReviewSourceDetail) -> ReviewSourceDetailRecord:
    return ReviewSourceDetailRecord.model_validate(row, from_attributes=True)


def _feature_detail(row: ReviewFeatureDetail) -> ReviewFeatureDetailRecord:
    return ReviewFeatureDetailRecord(
        feature_id=row.feature_id,
        kind=row.kind,
        name=row.name,
        category=row.category,
        status=row.status,
        lon=row.lon,
        lat=row.lat,
        address=row.address,
        detail=row.detail,
        urls=row.urls,
        raw_refs=row.raw_refs,
        marker_icon=row.marker_icon,
        marker_color=row.marker_color,
        data_origin=row.data_origin,
        data_version=row.data_version,
        created_at=row.created_at,
        updated_at=row.updated_at,
        sources=[_source_detail(source) for source in row.sources],
    )


def _detail(row: DedupReviewDetail) -> DedupReviewDetailData:
    return DedupReviewDetailData(
        review_id=row.review_id,
        status=row.status,
        total_score=row.total_score,
        name_score=row.name_score,
        spatial_score=row.spatial_score,
        category_score=row.category_score,
        distance_m=row.distance_m,
        decision_reason=row.decision_reason,
        reviewed_by=row.reviewed_by,
        reviewed_at=row.reviewed_at,
        created_at=row.created_at,
        feature_a=_feature_detail(row.feature_a),
        feature_b=_feature_detail(row.feature_b),
    )


def _decision_response(
    *,
    review_id: str,
    decision: DedupDecision,
    changed: bool,
    started_at: float,
    request: Request,
    outcome: MergeOutcome | None = None,
) -> DedupReviewDecisionResponse:
    return DedupReviewDecisionResponse(
        data=DedupReviewDecisionData(
            review_id=review_id,
            decision=decision,
            changed=changed,
            master_feature_id=outcome.master_feature_id if outcome else None,
            loser_feature_id=outcome.loser_feature_id if outcome else None,
            merge_id=outcome.merge_id if outcome else None,
            source_links_moved=outcome.source_links_moved if outcome else None,
            source_links_dropped=outcome.source_links_dropped if outcome else None,
        ),
        meta=make_meta(request, started_at=started_at),
    )


@router.get("", response_model=DedupReviewListResponse)
async def list_reviews(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    review_status: Annotated[
        list[DedupStatus] | None,
        Query(alias="status", description="dedup review status 반복 필터"),
    ] = None,
    provider: Annotated[list[str] | None, Query()] = None,
    dataset_key: Annotated[list[str] | None, Query()] = None,
    kind: Annotated[list[str] | None, Query()] = None,
    category: Annotated[list[str] | None, Query()] = None,
    min_score: Annotated[float | None, Query(ge=0, le=100)] = None,
    max_score: Annotated[float | None, Query(ge=0, le=100)] = None,
    q: Annotated[str | None, Query()] = None,
    page_size: Annotated[int, Query(ge=1, le=500)] = 50,
    page_number: Annotated[int, Query(alias="page", ge=1)] = 1,
) -> DedupReviewListResponse:
    started_at = perf_counter()
    try:
        review_page: DedupReviewPage = await list_dedup_reviews(
            session,
            statuses=review_status if review_status is not None else ("pending",),
            providers=provider,
            dataset_keys=dataset_key,
            kinds=kind,
            categories=category,
            min_score=min_score,
            max_score=max_score,
            q=q,
            page_size=page_size,
            page=page_number,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return DedupReviewListResponse(
        data=DedupReviewListData(
            items=[_record(item) for item in review_page.items],
        ),
        meta=make_offset_meta(
            request,
            started_at=started_at,
            page_size=page_size,
            total=review_page.total_count,
        ),
    )


@router.get(
    "/{review_id}",
    response_model=DedupReviewDetailResponse,
    responses={404: {"description": "review_id 없음"}},
)
async def get_review_detail(
    request: Request,
    review_id: str,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> DedupReviewDetailResponse:
    started_at = perf_counter()
    detail = await get_dedup_review_detail(session, review_id)
    if detail is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"dedup review 없음: {review_id!r}",
        )
    return DedupReviewDetailResponse(
        data=_detail(detail),
        meta=make_meta(request, started_at=started_at),
    )


@router.patch(
    "/{review_id}",
    response_model=DedupReviewDecisionResponse,
    responses={404: {"description": "review_id 없음"}, 409: {"description": "전이 불가"}},
)
async def decide_review(
    request: Request,
    review_id: str,
    body: DedupReviewDecisionRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> DedupReviewDecisionResponse:
    started_at = perf_counter()
    if body.decision == "merged":
        try:
            async with (
                session.begin(),
                advisory_lock(session, f"dedup-merge:{review_id}"),
            ):
                outcome = await merge_dedup_review(
                    session,
                    review_id,
                    master_feature_id=body.master_feature_id,
                    merged_by=body.reviewed_by,
                    reason=body.decision_reason,
                )
        except MergeError as exc:
            if isinstance(exc, MergeNotFoundError):
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=str(exc),
                ) from exc
            if isinstance(exc, MergeConflictError):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=str(exc),
                ) from exc
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="dedup review merge failed",
            ) from exc
        return _decision_response(
            review_id=review_id,
            decision=body.decision,
            changed=True,
            outcome=outcome,
            started_at=started_at,
            request=request,
        )

    async with session.begin():
        changed = await set_dedup_review_decision(
            session,
            review_id,
            decision=body.decision,
            reviewed_by=body.reviewed_by,
            decision_reason=body.decision_reason,
        )
    if not changed:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"pending dedup review 전이 실패: {review_id!r}",
        )
    return _decision_response(
        review_id=review_id,
        decision=body.decision,
        changed=True,
        started_at=started_at,
        request=request,
    )
