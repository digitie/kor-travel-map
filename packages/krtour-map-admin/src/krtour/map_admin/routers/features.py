"""``krtour.map_admin.routers.features`` — feature 조회 API (``/features``).

적재된 feature를 운영자/frontend 지도가 조회한다 (ADR-035 운영 범위). 쿼리는
``krtour.map.infra.feature_repo``의 raw SQL(ADR-004) — 본 라우터는 HTTP 표면 +
DTO 매핑만, SQL 미보유.

엔드포인트:
- ``GET /features`` — bbox 안 feature 경량 표현 list (지도 뷰포트 로드).
- ``GET /features/{feature_id}`` — feature 단건 상세.

ADR 참조
--------
- ADR-004 — 쿼리는 raw SQL (``feature_repo``)
- ADR-005 + ADR-035 — 인증 없음, 운영 범위. 본 라우터는 ``/features`` prefix.
- ADR-012 — bbox/좌표는 4326, GIST 인덱스 사용 (술어에 ST_Transform 없음)
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from krtour.map.infra import feature_repo
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from krtour.map_admin.db import get_session

__all__ = [
    "router",
    "FeatureSummary",
    "FeaturesInBboxResponse",
    "FeatureDetailResponse",
]


router = APIRouter(prefix="/features", tags=["features"])


# ── 응답 schema ────────────────────────────────────────────────────────


class FeatureSummary(BaseModel):
    """지도/목록용 경량 feature 표현 (bbox 조회 결과 1건)."""

    model_config = ConfigDict(extra="forbid")

    feature_id: str
    kind: str
    name: str
    category: str
    lon: float | None = Field(description="경도 (WGS84). coord 없으면 null.")
    lat: float | None = Field(description="위도 (WGS84).")
    marker_icon: str | None = None
    marker_color: str | None = None
    status: str


class FeaturesInBboxResponse(BaseModel):
    """``GET /features`` 응답 — bbox 안 feature 목록."""

    model_config = ConfigDict(extra="forbid")

    count: int
    items: list[FeatureSummary]


class FeatureDetailResponse(BaseModel):
    """``GET /features/{feature_id}`` 응답 — 단건 상세 (raw row 기반)."""

    model_config = ConfigDict(extra="forbid")

    feature_id: str
    kind: str
    name: str
    category: str
    lon: float | None = None
    lat: float | None = None
    coord_5179_srid: int | None = Field(
        default=None,
        description="coord_5179 STORED generated column의 SRID (ADR-012 검증용).",
    )
    address: dict[str, Any]
    detail: dict[str, Any]
    urls: dict[str, Any]
    legal_dong_code: str | None = None
    sido_code: str | None = None
    sigungu_code: str | None = None
    marker_icon: str | None = None
    marker_color: str | None = None
    status: str
    parent_feature_id: str | None = None
    sibling_group_id: str | None = None


# ── 라우터 ───────────────────────────────────────────────────────────


@router.get(
    "",
    response_model=FeaturesInBboxResponse,
    summary="bbox 안 feature 목록 (지도 뷰포트)",
    description=(
        "주어진 경계 상자(WGS84) 안의 feature 경량 표현 list. ``coord``의 GIST "
        "인덱스를 사용하는 공간 조회 (ADR-012). ``kind`` 반복 파라미터로 종류 "
        "필터 (예: ``?kind=place&kind=event``). 삭제된 feature 제외."
    ),
)
async def list_features_in_bbox(
    session: Annotated[AsyncSession, Depends(get_session)],
    min_lon: Annotated[float, Query(description="bbox 최소 경도 (WGS84).")],
    min_lat: Annotated[float, Query(description="bbox 최소 위도.")],
    max_lon: Annotated[float, Query(description="bbox 최대 경도.")],
    max_lat: Annotated[float, Query(description="bbox 최대 위도.")],
    kind: Annotated[
        list[str] | None,
        Query(description="feature kind 필터 (반복 가능). 미지정 시 전체."),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=5000, description="최대 반환 수.")] = 1000,
) -> FeaturesInBboxResponse:
    if min_lon > max_lon or min_lat > max_lat:
        # 422 (Unprocessable) — starlette 버전별 상수명 변경 회피 위해 정수 리터럴.
        raise HTTPException(
            status_code=422,
            detail="bbox min 좌표가 max보다 큽니다 (min_lon≤max_lon, min_lat≤max_lat).",
        )
    rows = await feature_repo.features_in_bbox(
        session,
        min_lon=min_lon,
        min_lat=min_lat,
        max_lon=max_lon,
        max_lat=max_lat,
        kinds=kind,
        limit=limit,
    )
    items = [FeatureSummary(**row) for row in rows]
    return FeaturesInBboxResponse(count=len(items), items=items)


@router.get(
    "/{feature_id}",
    response_model=FeatureDetailResponse,
    summary="feature 단건 상세",
    responses={404: {"description": "feature_id 없음"}},
)
async def get_feature(
    feature_id: str,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> FeatureDetailResponse:
    row = await feature_repo.get_feature_row(session, feature_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"feature 없음: {feature_id!r}",
        )
    # raw row에서 응답 schema가 쓰는 필드만 추림 (created_at 등 제외).
    return FeatureDetailResponse(
        feature_id=row["feature_id"],
        kind=row["kind"],
        name=row["name"],
        category=row["category"],
        lon=row["lon"],
        lat=row["lat"],
        coord_5179_srid=row["coord_5179_srid"],
        address=row["address"],
        detail=row["detail"],
        urls=row["urls"],
        legal_dong_code=row["legal_dong_code"],
        sido_code=row["sido_code"],
        sigungu_code=row["sigungu_code"],
        marker_icon=row["marker_icon"],
        marker_color=row["marker_color"],
        status=row["status"],
        parent_feature_id=row["parent_feature_id"],
        sibling_group_id=row["sibling_group_id"],
    )
