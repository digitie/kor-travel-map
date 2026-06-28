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
    EnrichmentReviewDetail,
    EnrichmentReviewPage,
    EnrichmentReviewRow,
    ReviewFeatureDetail,
    ReviewSourceDetail,
    get_enrichment_review_detail,
    list_enrichment_reviews,
)
from kortravelmap.infra.enrichment_review_repo import decide_enrichment_review
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.api.db import get_session
from kortravelmap.api.response import Meta, make_meta
from kortravelmap.api.routers.dedup_review import (
    ReviewFeatureDetailRecord,
    ReviewSourceDetailRecord,
)

__all__ = [
    "router",
    "EnrichmentReviewRecord",
    "EnrichmentReviewListResponse",
    "EnrichmentReviewDetailResponse",
    "EnrichmentReviewDecisionRequest",
    "EnrichmentReviewDecisionResponse",
]


router = APIRouter(prefix="/admin/enrichment-reviews", tags=["admin-enrichment"])

EnrichmentStatus = Literal["pending", "accepted", "rejected", "ignored"]
EnrichmentDecision = Literal["accepted", "rejected", "ignored"]
EnrichmentDetailSource = Literal["target", "visitkorea"]
EnrichmentDetailSourceEffect = Literal["audit_only"]


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
    target_start_date: str | None = None
    target_end_date: str | None = None
    source_provider: str
    source_dataset_key: str
    source_entity_id: str
    source_name: str
    source_lon: float | None = None
    source_lat: float | None = None
    source_start_date: str | None = None
    source_end_date: str | None = None
    distance_m: float | None = None
    spatial_score: float | None = None
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


class EnrichmentReviewDetailData(BaseModel):
    """Enrichment review 상세 비교 data."""

    model_config = ConfigDict(extra="forbid")

    review_id: str
    status: str
    name_score: float
    target_feature_id: str
    target_name: str
    source_provider: str
    source_dataset_key: str
    source_entity_id: str
    source_name: str
    target_start_date: str | None = None
    target_end_date: str | None = None
    source_start_date: str | None = None
    source_end_date: str | None = None
    distance_m: float | None = None
    spatial_score: float | None = None
    decision_reason: str | None = None
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    created_at: datetime
    target: ReviewFeatureDetailRecord
    source: ReviewSourceDetailRecord
    target_detail_available: bool
    default_detail_source: EnrichmentDetailSource
    detail_source_effect: EnrichmentDetailSourceEffect = "audit_only"


class EnrichmentReviewDetailResponse(BaseModel):
    """``GET /admin/enrichment-reviews/{review_id}`` response."""

    model_config = ConfigDict(extra="forbid")

    data: EnrichmentReviewDetailData
    meta: Meta


class EnrichmentReviewDecisionRequest(BaseModel):
    """``PATCH /admin/enrichment-reviews/{review_id}`` body."""

    model_config = ConfigDict(extra="forbid")

    decision: EnrichmentDecision
    decision_reason: str | None = Field(default=None, min_length=1)
    selected_detail_source: EnrichmentDetailSource | None = Field(
        default=None,
        description=(
            "운영자가 비교 다이얼로그에서 선택한 상세 source. 현재 accept 적용 데이터는 "
            "바꾸지 않고 decision_reason audit marker로만 기록한다."
        ),
    )
    reviewed_by: str | None = None


class EnrichmentReviewDecisionData(BaseModel):
    """Enrichment decision result data."""

    model_config = ConfigDict(extra="forbid")

    review_id: str
    decision: EnrichmentDecision
    changed: bool
    applied: bool
    selected_detail_source: EnrichmentDetailSource | None = None
    detail_source_effect: EnrichmentDetailSourceEffect = "audit_only"
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
        target_start_date=row.target_start_date,
        target_end_date=row.target_end_date,
        source_provider=row.source_provider,
        source_dataset_key=row.source_dataset_key,
        source_entity_id=row.source_entity_id,
        source_name=row.source_name,
        source_lon=row.source_lon,
        source_lat=row.source_lat,
        source_start_date=row.source_start_date,
        source_end_date=row.source_end_date,
        distance_m=row.distance_m,
        spatial_score=row.spatial_score,
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


def _detail(row: EnrichmentReviewDetail) -> EnrichmentReviewDetailData:
    return EnrichmentReviewDetailData(
        review_id=row.review_id,
        status=row.status,
        name_score=row.name_score,
        target_feature_id=row.target_feature_id,
        target_name=row.target_name,
        source_provider=row.source_provider,
        source_dataset_key=row.source_dataset_key,
        source_entity_id=row.source_entity_id,
        source_name=row.source_name,
        target_start_date=row.target_start_date,
        target_end_date=row.target_end_date,
        source_start_date=row.source_start_date,
        source_end_date=row.source_end_date,
        distance_m=row.distance_m,
        spatial_score=row.spatial_score,
        decision_reason=row.decision_reason,
        reviewed_by=row.reviewed_by,
        reviewed_at=row.reviewed_at,
        created_at=row.created_at,
        target=_feature_detail(row.target),
        source=_source_detail(row.source),
        target_detail_available=row.target_detail_available,
        default_detail_source=row.default_detail_source,
        detail_source_effect="audit_only",
    )


def _reason_with_detail_source(
    reason: str | None, selected_detail_source: EnrichmentDetailSource | None
) -> str | None:
    if selected_detail_source is None:
        return reason
    marker = f"detail_source={selected_detail_source}"
    return f"{reason}; {marker}" if reason else marker


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
    page_number: Annotated[int, Query(alias="page", ge=1)] = 1,
) -> EnrichmentReviewListResponse:
    started_at = perf_counter()
    try:
        review_page: EnrichmentReviewPage = await list_enrichment_reviews(
            session,
            statuses=review_status if review_status is not None else ("pending",),
            providers=provider,
            min_score=min_score,
            max_score=max_score,
            q=q,
            page_size=page_size,
            page=page_number,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return EnrichmentReviewListResponse(
        data=EnrichmentReviewListData(
            items=[_record(item) for item in review_page.items],
        ),
        meta=make_meta(
            request,
            started_at=started_at,
            page_size=page_size,
            total=review_page.total_count,
        ),
    )


@router.get(
    "/{review_id}",
    response_model=EnrichmentReviewDetailResponse,
    responses={404: {"description": "review_id 없음"}},
)
async def get_review_detail(
    request: Request,
    review_id: str,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> EnrichmentReviewDetailResponse:
    started_at = perf_counter()
    detail = await get_enrichment_review_detail(session, review_id)
    if detail is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"enrichment review 없음: {review_id!r}",
        )
    return EnrichmentReviewDetailResponse(
        data=_detail(detail),
        meta=make_meta(request, started_at=started_at),
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
            reason=_reason_with_detail_source(
                body.decision_reason,
                body.selected_detail_source,
            ),
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
            selected_detail_source=body.selected_detail_source,
            detail_source_effect="audit_only",
            source_links_inserted=(
                result.load.source_links_inserted if result.load is not None else None
            ),
            source_links_updated=(
                result.load.source_links_updated if result.load is not None else None
            ),
        ),
        meta=make_meta(request, started_at=started_at),
    )
