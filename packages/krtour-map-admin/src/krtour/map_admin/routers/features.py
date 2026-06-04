"""``krtour.map_admin.routers.features`` — feature 조회 API (``/features``).

적재된 feature를 운영자/frontend 지도가 조회한다 (ADR-035 운영 범위). 쿼리는
``krtour.map.infra.feature_repo``의 raw SQL(ADR-004) — 본 라우터는 HTTP 표면 +
DTO 매핑만, SQL 미보유.

엔드포인트:
- ``GET /features`` — bbox 안 feature 경량 표현 list (지도 뷰포트 로드).
- ``GET /features/in-bounds`` — TripMate/user용 bbox envelope 응답.
- ``GET /features/search`` — TripMate/user용 이름/bbox 검색.
- ``GET /features/{feature_id}`` — feature 단건 상세.
- ``POST /tripmate/features/batch`` — TripMate N+1 방지 batch 상세.

ADR 참조
--------
- ADR-004 — 쿼리는 raw SQL (``feature_repo``)
- ADR-005 + ADR-035 — 인증 없음, 운영 범위. 본 라우터는 ``/features`` prefix.
- ADR-012 — bbox/좌표는 4326, GIST 인덱스 사용 (술어에 ST_Transform 없음)
"""

from __future__ import annotations

from datetime import datetime
from time import perf_counter
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from krtour.map.infra import feature_repo
from krtour.map.infra.poi_cache_target_repo import (
    PoiCacheTarget,
    get_poi_cache_target_by_key,
)
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from krtour.map_admin.db import get_session

__all__ = [
    "router",
    "tripmate_router",
    "FeatureSummary",
    "FeaturesInBboxResponse",
    "FeaturesInBoundsResponse",
    "FeatureDetailResponse",
    "FeatureDetailEnvelopeResponse",
    "FeatureBatchRequest",
    "FeatureBatchResponse",
    "FeatureSearchResponse",
    "FeaturesNearbyByTargetResponse",
]


router = APIRouter(prefix="/features", tags=["features"])
tripmate_router = APIRouter(prefix="/tripmate", tags=["tripmate"])
NearbySort = Literal["distance", "name", "last_updated_at"]


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
    """feature 단건 상세 data payload."""

    model_config = ConfigDict(extra="forbid")

    feature_id: str
    kind: str
    name: str
    category: str
    lon: float | None = None
    lat: float | None = None
    address: dict[str, Any]
    detail: dict[str, Any]
    urls: dict[str, Any]
    legal_dong_code: str | None = None
    sido_code: str | None = None
    sigungu_code: str | None = None
    marker_icon: str | None = None
    marker_color: str | None = None
    status: str
    updated_at: datetime


class PublicFeatureListData(BaseModel):
    """public feature 목록 data payload."""

    model_config = ConfigDict(extra="forbid")

    count: int
    items: list[FeatureSummary]
    cluster_unit: str | None = None


class FeatureListMeta(BaseModel):
    """public feature 목록 meta."""

    model_config = ConfigDict(extra="forbid")

    duration_ms: int


class FeaturesInBoundsResponse(BaseModel):
    """``GET /features/in-bounds`` 응답."""

    model_config = ConfigDict(extra="forbid")

    data: PublicFeatureListData
    meta: FeatureListMeta


class FeatureDetailMeta(BaseModel):
    """feature 상세 meta."""

    model_config = ConfigDict(extra="forbid")

    duration_ms: int


class FeatureDetailEnvelopeResponse(BaseModel):
    """``GET /features/{feature_id}`` public envelope 응답."""

    model_config = ConfigDict(extra="forbid")

    data: FeatureDetailResponse
    meta: FeatureDetailMeta


class FeatureBatchRequest(BaseModel):
    """TripMate batch 상세 조회 요청."""

    model_config = ConfigDict(extra="forbid")

    feature_ids: list[str] = Field(min_length=1, max_length=200)


class FeatureBatchData(BaseModel):
    """TripMate batch 상세 data payload."""

    model_config = ConfigDict(extra="forbid")

    items: dict[str, FeatureDetailResponse]
    missing: list[str]


class FeatureBatchResponse(BaseModel):
    """``POST /tripmate/features/batch`` 응답."""

    model_config = ConfigDict(extra="forbid")

    data: FeatureBatchData
    meta: FeatureDetailMeta


class FeatureSearchData(BaseModel):
    """사용자 feature 검색 data payload."""

    model_config = ConfigDict(extra="forbid")

    items: list[FeatureSummary]
    next_cursor: str | None = None
    total_count: int | None = None


class FeatureSearchResponse(BaseModel):
    """``GET /features/search`` 응답."""

    model_config = ConfigDict(extra="forbid")

    data: FeatureSearchData
    meta: FeatureListMeta


class NearbyTargetSummary(BaseModel):
    """주변 조회 기준 public target summary."""

    model_config = ConfigDict(extra="forbid")

    external_system: str
    target_key: str
    lon: float
    lat: float


class NearbyFeatureSummary(BaseModel):
    """POI/cache target 주변 public feature summary."""

    model_config = ConfigDict(extra="forbid")

    feature_id: str
    kind: str
    name: str
    category: str
    status: str
    lon: float
    lat: float
    distance_m: float


class FeaturesNearbyByTargetData(BaseModel):
    """``GET /features/nearby/by-target`` data payload."""

    model_config = ConfigDict(extra="forbid")

    target: NearbyTargetSummary
    items: list[NearbyFeatureSummary]
    next_cursor: str | None = None


class FeaturesNearbyByTargetMeta(BaseModel):
    """주변 feature 목록 메타데이터."""

    model_config = ConfigDict(extra="forbid")

    count: int
    duration_ms: int


class FeaturesNearbyByTargetResponse(BaseModel):
    """``GET /features/nearby/by-target`` 응답."""

    model_config = ConfigDict(extra="forbid")

    data: FeaturesNearbyByTargetData
    meta: FeaturesNearbyByTargetMeta


def _nearby_target(target: PoiCacheTarget) -> NearbyTargetSummary:
    return NearbyTargetSummary(
        external_system=target.external_system,
        target_key=target.target_key,
        lon=target.lon,
        lat=target.lat,
    )


def _duration_ms(started_at: float) -> int:
    return max(0, int((perf_counter() - started_at) * 1000))


def _detail_from_row(row: dict[str, Any]) -> FeatureDetailResponse:
    return FeatureDetailResponse(
        feature_id=row["feature_id"],
        kind=row["kind"],
        name=row["name"],
        category=row["category"],
        lon=row["lon"],
        lat=row["lat"],
        address=row["address"],
        detail=row["detail"],
        urls=row["urls"],
        legal_dong_code=row["legal_dong_code"],
        sido_code=row["sido_code"],
        sigungu_code=row["sigungu_code"],
        marker_icon=row["marker_icon"],
        marker_color=row["marker_color"],
        status=row["status"],
        updated_at=row["updated_at"],
    )


def _parse_bbox_csv(value: str | None) -> tuple[float, float, float, float] | None:
    if value is None:
        return None
    parts = [part.strip() for part in value.split(",")]
    if len(parts) != 4:
        raise ValueError("bbox는 min_lon,min_lat,max_lon,max_lat CSV 형식이어야 합니다")
    try:
        min_lon, min_lat, max_lon, max_lat = (float(part) for part in parts)
    except ValueError as exc:
        raise ValueError("bbox 좌표는 숫자여야 합니다") from exc
    if min_lon > max_lon or min_lat > max_lat:
        raise ValueError("bbox min 좌표가 max보다 큽니다")
    return (min_lon, min_lat, max_lon, max_lat)


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
    category: Annotated[
        list[str] | None,
        Query(description="category code 필터 (반복 가능). 미지정 시 전체."),
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
        categories=category,
        limit=limit,
    )
    items = [FeatureSummary(**row) for row in rows]
    return FeaturesInBboxResponse(count=len(items), items=items)


@router.get(
    "/in-bounds",
    response_model=FeaturesInBoundsResponse,
    summary="bbox 안 feature 목록 (TripMate/public envelope)",
)
async def list_public_features_in_bounds(
    session: Annotated[AsyncSession, Depends(get_session)],
    min_lon: Annotated[float, Query(description="bbox 최소 경도 (WGS84).")],
    min_lat: Annotated[float, Query(description="bbox 최소 위도.")],
    max_lon: Annotated[float, Query(description="bbox 최대 경도.")],
    max_lat: Annotated[float, Query(description="bbox 최대 위도.")],
    kind: Annotated[list[str] | None, Query(description="feature kind 반복 필터.")] = None,
    category: Annotated[
        list[str] | None,
        Query(description="category code 반복 필터."),
    ] = None,
    zoom: Annotated[int | None, Query(ge=0, le=24)] = None,
    limit: Annotated[int, Query(ge=1, le=5000)] = 1000,
) -> FeaturesInBoundsResponse:
    started_at = perf_counter()
    if min_lon > max_lon or min_lat > max_lat:
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
        categories=category,
        limit=limit,
    )
    items = [FeatureSummary(**row) for row in rows]
    _ = zoom  # 클러스터링 구현 전까지 OpenAPI query 계약만 유지한다.
    return FeaturesInBoundsResponse(
        data=PublicFeatureListData(
            count=len(items),
            items=items,
            cluster_unit=None,
        ),
        meta=FeatureListMeta(duration_ms=_duration_ms(started_at)),
    )


@router.get(
    "/search",
    response_model=FeatureSearchResponse,
    summary="feature 검색 (이름 trgm + bbox)",
    responses={422: {"description": "검색 범위 또는 cursor 오류"}},
)
async def search_public_features(
    session: Annotated[AsyncSession, Depends(get_session)],
    q: Annotated[str | None, Query(description="name pg_trgm 검색어.")] = None,
    kind: Annotated[list[str] | None, Query(description="feature kind 반복 필터.")] = None,
    category: Annotated[
        list[str] | None,
        Query(description="category code 반복 필터."),
    ] = None,
    bbox: Annotated[
        str | None,
        Query(description="min_lon,min_lat,max_lon,max_lat CSV."),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: Annotated[str | None, Query()] = None,
) -> FeatureSearchResponse:
    started_at = perf_counter()
    try:
        page = await feature_repo.search_features(
            session,
            q=q,
            bbox=_parse_bbox_csv(bbox),
            kinds=kind,
            categories=category,
            limit=limit,
            cursor=cursor,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    items = [
        FeatureSummary(
            feature_id=item.feature_id,
            kind=item.kind,
            name=item.name,
            category=item.category,
            lon=item.lon,
            lat=item.lat,
            marker_icon=item.marker_icon,
            marker_color=item.marker_color,
            status=item.status,
        )
        for item in page.items
    ]
    return FeatureSearchResponse(
        data=FeatureSearchData(
            items=items,
            next_cursor=page.next_cursor,
            total_count=page.total_count,
        ),
        meta=FeatureListMeta(duration_ms=_duration_ms(started_at)),
    )


@router.get(
    "/nearby/by-target",
    response_model=FeaturesNearbyByTargetResponse,
    summary="외부 POI/cache target key 기준 주변 feature 목록",
    responses={
        404: {"description": "target 없음"},
        422: {"description": "cursor/sort/radius 오류"},
    },
)
async def list_features_nearby_by_target(
    session: Annotated[AsyncSession, Depends(get_session)],
    external_system: Annotated[str, Query(description="외부 시스템 이름. 예: tripmate")],
    target_key: Annotated[str, Query(description="외부 POI 고유 key.")],
    radius_km: Annotated[
        float | None,
        Query(gt=0, le=100, description="미지정 시 target 기본 radius 사용."),
    ] = None,
    kind: Annotated[list[str] | None, Query(description="feature kind 반복 필터.")] = None,
    category: Annotated[
        list[str] | None,
        Query(description="category code 반복 필터."),
    ] = None,
    feature_status: Annotated[
        list[str] | None,
        Query(alias="status", description="feature status 반복 필터. 기본 active."),
    ] = None,
    provider: Annotated[
        list[str] | None,
        Query(description="primary provider 반복 필터."),
    ] = None,
    page_size: Annotated[int, Query(ge=1, le=500)] = 100,
    cursor: Annotated[str | None, Query()] = None,
    sort: Annotated[NearbySort, Query()] = "distance",
) -> FeaturesNearbyByTargetResponse:
    started_at = perf_counter()
    target = await get_poi_cache_target_by_key(
        session,
        external_system=external_system,
        target_key=target_key,
    )
    if target is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"POI/cache target 없음: {external_system!r}/{target_key!r}",
        )
    try:
        page = await feature_repo.features_nearby_poi_cache_target(
            session,
            target_id=target.target_id,
            radius_km=radius_km,
            kinds=kind,
            categories=category,
            statuses=feature_status if feature_status is not None else ("active",),
            providers=provider,
            sort=sort,
            limit=page_size,
            cursor=cursor,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    items = [
        NearbyFeatureSummary(
            feature_id=item.feature_id,
            kind=item.kind,
            name=item.name,
            category=item.category,
            status=item.status,
            lon=item.lon,
            lat=item.lat,
            distance_m=item.distance_m,
        )
        for item in page.items
    ]
    return FeaturesNearbyByTargetResponse(
        data=FeaturesNearbyByTargetData(
            target=_nearby_target(target),
            items=items,
            next_cursor=page.next_cursor,
        ),
        meta=FeaturesNearbyByTargetMeta(
            count=len(items),
            duration_ms=_duration_ms(started_at),
        ),
    )


@router.get(
    "/{feature_id}",
    response_model=FeatureDetailEnvelopeResponse,
    summary="feature 단건 상세",
    responses={404: {"description": "feature_id 없음"}},
)
async def get_feature(
    feature_id: str,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> FeatureDetailEnvelopeResponse:
    started_at = perf_counter()
    row = await feature_repo.get_feature_row(session, feature_id)
    if row is None or row["deleted_at"] is not None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"feature 없음: {feature_id!r}",
        )
    return FeatureDetailEnvelopeResponse(
        data=_detail_from_row(row),
        meta=FeatureDetailMeta(duration_ms=_duration_ms(started_at)),
    )


@tripmate_router.post(
    "/features/batch",
    response_model=FeatureBatchResponse,
    summary="TripMate feature 상세 batch 조회",
    responses={422: {"description": "feature_ids 1~200개 필요"}},
)
async def get_tripmate_features_batch(
    body: FeatureBatchRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> FeatureBatchResponse:
    started_at = perf_counter()
    feature_ids = list(dict.fromkeys(body.feature_ids))
    rows = await feature_repo.get_feature_rows_by_ids(session, feature_ids)
    items = {
        feature_id: _detail_from_row(rows[feature_id])
        for feature_id in feature_ids
        if feature_id in rows
    }
    missing = [feature_id for feature_id in feature_ids if feature_id not in rows]
    return FeatureBatchResponse(
        data=FeatureBatchData(items=items, missing=missing),
        meta=FeatureDetailMeta(duration_ms=_duration_ms(started_at)),
    )
