"""``/admin/dedup-reviews`` 운영 중복 후보 검토 라우터."""

from __future__ import annotations

from datetime import datetime
from time import perf_counter
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from krtour.map.infra.admin_feature_repo import (
    DedupFeatureSummary,
    DedupReviewPage,
    DedupReviewRow,
    list_dedup_reviews,
    merge_dedup_review,
    set_dedup_review_decision,
)
from krtour.map.infra.advisory_lock import advisory_lock
from krtour.map.infra.merge_repo import (
    MergeConflictError,
    MergeError,
    MergeNotFoundError,
    MergeOutcome,
)
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from krtour.map_admin.db import get_session
from krtour.map_admin.response import Meta, make_meta

__all__ = [
    "router",
    "DedupReviewRecord",
    "DedupReviewListResponse",
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
    cursor: Annotated[str | None, Query()] = None,
) -> DedupReviewListResponse:
    started_at = perf_counter()
    try:
        page: DedupReviewPage = await list_dedup_reviews(
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
            cursor=cursor,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return DedupReviewListResponse(
        data=DedupReviewListData(
            items=[_record(item) for item in page.items],
        ),
        meta=make_meta(
            request,
            started_at=started_at,
            page_size=page_size,
            next_cursor=page.next_cursor,
        ),
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
