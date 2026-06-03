"""``/admin/poi-cache-targets`` 운영 라우터 (ADR-045 T-207f)."""

from __future__ import annotations

from datetime import datetime
from time import perf_counter
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from krtour.map.infra.poi_cache_target_repo import (
    PoiCacheTarget,
    PoiCacheTargetConflict,
    delete_poi_cache_target,
    get_poi_cache_target_by_key,
    list_poi_cache_targets,
    upsert_poi_cache_target,
)
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from krtour.map_admin.db import get_session

__all__ = [
    "router",
    "PoiCacheTargetRecord",
    "PoiCacheTargetUpsertRequest",
    "PoiCacheTargetResponse",
    "PoiCacheTargetListResponse",
]

OnConflict = Literal["reject", "move"]
ScopeMode = Literal["center_radius", "sigungu_by_radius"]
RefreshPolicy = Literal[
    "provider_default",
    "follow_system",
    "allow_targeted",
    "disabled",
]

router = APIRouter(
    prefix="/admin/poi-cache-targets",
    tags=["admin-poi-cache-targets"],
)


class CoordinateBody(BaseModel):
    """WGS84 좌표. 모든 외부 인터페이스는 lon/lat 순서를 사용한다."""

    model_config = ConfigDict(extra="forbid")

    lon: float = Field(ge=124.0, le=132.0)
    lat: float = Field(ge=33.0, le=39.5)


class PoiCacheTargetUpsertRequest(BaseModel):
    """cache target 등록/갱신 요청."""

    model_config = ConfigDict(extra="forbid")

    coord: CoordinateBody
    coord_precision_digits: int = Field(default=6, ge=3, le=8)
    radius_km: float = Field(default=5.0, gt=0, le=100)
    name: str | None = None
    scope_mode: ScopeMode = "center_radius"
    update_enabled: bool = True
    refresh_policy: RefreshPolicy = "provider_default"
    provider_overrides: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    on_conflict: OnConflict = "reject"


class PoiCacheTargetRecord(BaseModel):
    """``ops.poi_cache_targets``의 HTTP 표현."""

    model_config = ConfigDict(extra="forbid")

    target_id: str
    external_system: str
    target_key: str
    name: str | None = None
    coord: CoordinateBody
    coord_precision_digits: int
    coord_key: str
    radius_km: float
    scope_mode: str
    update_enabled: bool
    refresh_policy: str
    provider_overrides: dict[str, Any]
    metadata: dict[str, Any]
    last_seen_at: datetime
    last_requested_at: datetime | None = None
    last_refreshed_at: datetime | None = None
    last_failed_at: datetime | None = None
    next_eligible_refresh_at: datetime | None = None
    deleted_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    status_url: str
    nearby_url: str


class PoiCacheTargetMeta(BaseModel):
    """쓰기 요청의 간단한 메타데이터."""

    model_config = ConfigDict(extra="forbid")

    duration_ms: int


class PoiCacheTargetResponse(BaseModel):
    """단건 응답."""

    model_config = ConfigDict(extra="forbid")

    data: PoiCacheTargetRecord
    meta: PoiCacheTargetMeta


class PoiCacheTargetListResponse(BaseModel):
    """목록 응답."""

    model_config = ConfigDict(extra="forbid")

    count: int
    items: list[PoiCacheTargetRecord]


def _record_from_target(target: PoiCacheTarget) -> PoiCacheTargetRecord:
    return PoiCacheTargetRecord(
        target_id=target.target_id,
        external_system=target.external_system,
        target_key=target.target_key,
        name=target.name,
        coord=CoordinateBody(lon=target.lon, lat=target.lat),
        coord_precision_digits=target.coord_precision_digits,
        coord_key=target.coord_key,
        radius_km=target.radius_km,
        scope_mode=target.scope_mode,
        update_enabled=target.update_enabled,
        refresh_policy=target.refresh_policy,
        provider_overrides=target.provider_overrides,
        metadata=target.metadata,
        last_seen_at=target.last_seen_at,
        last_requested_at=target.last_requested_at,
        last_refreshed_at=target.last_refreshed_at,
        last_failed_at=target.last_failed_at,
        next_eligible_refresh_at=target.next_eligible_refresh_at,
        deleted_at=target.deleted_at,
        created_at=target.created_at,
        updated_at=target.updated_at,
        status_url=(
            f"/admin/poi-cache-targets/{target.external_system}/{target.target_key}"
        ),
        nearby_url=(
            "/features/nearby/by-target?"
            f"external_system={target.external_system}&target_key={target.target_key}"
        ),
    )


def _response(
    target: PoiCacheTarget,
    *,
    started_at: float,
) -> PoiCacheTargetResponse:
    return PoiCacheTargetResponse(
        data=_record_from_target(target),
        meta=PoiCacheTargetMeta(
            duration_ms=max(0, int((perf_counter() - started_at) * 1000))
        ),
    )


def _unprocessable(exc: ValueError) -> HTTPException:
    return HTTPException(status_code=422, detail=str(exc))


@router.put(
    "/{external_system}/{target_key}",
    response_model=PoiCacheTargetResponse,
    summary="POI/cache target 등록 또는 갱신",
    responses={409: {"description": "같은 key의 좌표 conflict"}},
)
async def put_poi_cache_target(
    external_system: str,
    target_key: str,
    body: PoiCacheTargetUpsertRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> PoiCacheTargetResponse:
    started_at = perf_counter()
    try:
        async with session.begin():
            target = await upsert_poi_cache_target(
                session,
                external_system=external_system,
                target_key=target_key,
                name=body.name,
                lon=body.coord.lon,
                lat=body.coord.lat,
                radius_km=body.radius_km,
                coord_precision_digits=body.coord_precision_digits,
                scope_mode=body.scope_mode,
                update_enabled=body.update_enabled,
                refresh_policy=body.refresh_policy,
                provider_overrides=body.provider_overrides,
                metadata=body.metadata,
                on_conflict=body.on_conflict,
            )
    except PoiCacheTargetConflict as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except ValueError as exc:
        raise _unprocessable(exc) from exc
    return _response(target, started_at=started_at)


@router.get(
    "",
    response_model=PoiCacheTargetListResponse,
    summary="POI/cache target 목록",
)
async def list_poi_cache_target_records(
    session: Annotated[AsyncSession, Depends(get_session)],
    external_system: Annotated[str | None, Query()] = None,
    update_enabled: Annotated[bool | None, Query()] = None,
    include_deleted: Annotated[bool, Query()] = False,
    page_size: Annotated[int, Query(ge=1, le=500)] = 200,
) -> PoiCacheTargetListResponse:
    targets = await list_poi_cache_targets(
        session,
        external_system=external_system,
        update_enabled=update_enabled,
        include_deleted=include_deleted,
        limit=page_size,
    )
    return PoiCacheTargetListResponse(
        count=len(targets),
        items=[_record_from_target(target) for target in targets],
    )


@router.get(
    "/{external_system}/{target_key}",
    response_model=PoiCacheTargetRecord,
    summary="POI/cache target 단건 조회",
    responses={404: {"description": "target 없음"}},
)
async def get_poi_cache_target_record(
    external_system: str,
    target_key: str,
    session: Annotated[AsyncSession, Depends(get_session)],
    include_deleted: Annotated[bool, Query()] = False,
) -> PoiCacheTargetRecord:
    target = await get_poi_cache_target_by_key(
        session,
        external_system=external_system,
        target_key=target_key,
        include_deleted=include_deleted,
    )
    if target is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"POI/cache target 없음: {external_system!r}/{target_key!r}",
        )
    return _record_from_target(target)


@router.delete(
    "/{external_system}/{target_key}",
    response_model=PoiCacheTargetResponse,
    summary="POI/cache target soft delete",
    responses={404: {"description": "target 없음"}},
)
async def delete_poi_cache_target_record(
    external_system: str,
    target_key: str,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> PoiCacheTargetResponse:
    started_at = perf_counter()
    async with session.begin():
        target = await delete_poi_cache_target(
            session,
            external_system=external_system,
            target_key=target_key,
        )
        if target is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"POI/cache target 없음: {external_system!r}/{target_key!r}",
            )
    return _response(target, started_at=started_at)
