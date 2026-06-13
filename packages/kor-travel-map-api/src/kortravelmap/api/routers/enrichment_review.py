"""``/admin/enrichment-reviews`` 축제 enrichment 매칭 수동 검토 라우터 (T-RV-52c).

visitkorea(2차)↔datagokr(1차) 축제 이름 유사도가 자동 확정 임계 미만·검토 하한 이상인
모호한 매칭(``ops.enrichment_review_queue``)을 운영자가 accept/reject/ignore 한다. accept는
보관된 ``SourceRecord``를 복원해 ENRICHMENT ``SourceLink``를 1차 feature에 적재한다.
dedup-reviews 라우터(병합)와 달리 단순 link 적재이므로 advisory lock/merge 분기가 없다.
"""

from __future__ import annotations

from datetime import datetime
from time import perf_counter
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from kortravelmap.infra.admin_feature_repo import (
    EnrichmentReviewPage,
    EnrichmentReviewRow,
    list_enrichment_reviews,
)
from kortravelmap.infra.enrichment_review_repo import decide_enrichment_review
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.api.db import get_session
from kortravelmap.api.response import Meta, make_meta

__all__ = [
    "router",
    "EnrichmentReviewRecord",
    "EnrichmentReviewListResponse",
    "EnrichmentReviewDecisionRequest",
    "EnrichmentReviewDecisionResponse",
]


router = APIRouter(prefix="/admin/enrichment-reviews", tags=["admin-enrichment"])

EnrichmentStatus = Literal["pending", "accepted", "rejected", "ignored"]
EnrichmentDecision = Literal["accepted", "rejected", "ignored"]


class EnrichmentReviewRecord(BaseModel):
    """``GET /admin/enrichment-reviews`` item."""

    model_config = ConfigDict(extra="forbid")

    review_id: str
    status: str
    name_score: float
    target_feature_id: str
    target_name: str
    target_kind: str | None = None
    target_category: str | None = None
    target_lon: float | None = None
    target_lat: float | None = None
    source_provider: str
    source_dataset_key: str
    source_entity_id: str
    source_name: str
    decision_reason: str | None = None
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    created_at: datetime


class EnrichmentReviewListData(BaseModel):
    """Enrichment review list data."""

    model_config = ConfigDict(extra="forbid")

    items: list[EnrichmentReviewRecord]


class EnrichmentReviewListResponse(BaseModel):
    """``GET /admin/enrichment-reviews`` response."""

    model_config = ConfigDict(extra="forbid")

    data: EnrichmentReviewListData
    meta: Meta


class EnrichmentReviewDecisionRequest(BaseModel):
    """``PATCH /admin/enrichment-reviews/{review_id}`` body."""

    model_config = ConfigDict(extra="forbid")

    decision: EnrichmentDecision
    decision_reason: str | None = Field(default=None, min_length=1)
    reviewed_by: str | None = None


class EnrichmentReviewDecisionData(BaseModel):
    """Enrichment decision result data."""

    model_config = ConfigDict(extra="forbid")

    review_id: str
    decision: EnrichmentDecision
    changed: bool
    applied: bool
    source_links_inserted: int | None = None
    source_links_updated: int | None = None


class EnrichmentReviewDecisionResponse(BaseModel):
    """``PATCH /admin/enrichment-reviews/{review_id}`` response."""

    model_config = ConfigDict(extra="forbid")

    data: EnrichmentReviewDecisionData
    meta: Meta


def _record(row: EnrichmentReviewRow) -> EnrichmentReviewRecord:
    return EnrichmentReviewRecord(
        review_id=row.review_id,
        status=row.status,
        name_score=row.name_score,
        target_feature_id=row.target_feature_id,
        target_name=row.target_name,
        target_kind=row.target_kind,
        target_category=row.target_category,
        target_lon=row.target_lon,
        target_lat=row.target_lat,
        source_provider=row.source_provider,
        source_dataset_key=row.source_dataset_key,
        source_entity_id=row.source_entity_id,
        source_name=row.source_name,
        decision_reason=row.decision_reason,
        reviewed_by=row.reviewed_by,
        reviewed_at=row.reviewed_at,
        created_at=row.created_at,
    )


@router.get("", response_model=EnrichmentReviewListResponse)
async def list_reviews(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    review_status: Annotated[
        list[EnrichmentStatus] | None,
        Query(alias="status", description="enrichment review status 반복 필터"),
    ] = None,
    provider: Annotated[list[str] | None, Query()] = None,
    min_score: Annotated[float | None, Query(ge=0, le=100)] = None,
    max_score: Annotated[float | None, Query(ge=0, le=100)] = None,
    q: Annotated[str | None, Query()] = None,
    page_size: Annotated[int, Query(ge=1, le=500)] = 50,
    cursor: Annotated[str | None, Query()] = None,
) -> EnrichmentReviewListResponse:
    started_at = perf_counter()
    try:
        page: EnrichmentReviewPage = await list_enrichment_reviews(
            session,
            statuses=review_status if review_status is not None else ("pending",),
            providers=provider,
            min_score=min_score,
            max_score=max_score,
            q=q,
            page_size=page_size,
            cursor=cursor,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return EnrichmentReviewListResponse(
        data=EnrichmentReviewListData(
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
    response_model=EnrichmentReviewDecisionResponse,
    responses={409: {"description": "이미 검토됨/없음"}},
)
async def decide_review(
    request: Request,
    review_id: str,
    body: EnrichmentReviewDecisionRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> EnrichmentReviewDecisionResponse:
    started_at = perf_counter()
    async with session.begin():
        result = await decide_enrichment_review(
            session,
            review_id,
            body.decision,
            reviewed_by=body.reviewed_by,
            reason=body.decision_reason,
        )
    if not result.changed:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"pending enrichment review 전이 실패: {review_id!r}",
        )
    return EnrichmentReviewDecisionResponse(
        data=EnrichmentReviewDecisionData(
            review_id=result.review_id,
            decision=body.decision,
            changed=result.changed,
            applied=result.applied,
            source_links_inserted=(
                result.load.source_links_inserted if result.load is not None else None
            ),
            source_links_updated=(
                result.load.source_links_updated if result.load is not None else None
            ),
        ),
        meta=make_meta(request, started_at=started_at),
    )
