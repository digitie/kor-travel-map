"""``krtour.map_debug_ui.routers.mois_detail`` — MOIS 인허가 on-demand 상세.

SPRINT-4 §2.1 **Step D** — 디버그 UI에서 사용자가 명시 트리거하는 단건 상세
(``mois_license_detail``). **캐시만, 적재 없음**: 이미 적재된 MOIS feature의
원본 provider payload(``source_records.raw_data``) + feature core를 조립해 반환하고,
프로세스 내 TTL 캐시에 담는다(반복 클릭 시 재조회 회피). DB write는 일절 없다.

``license_id``는 MOIS 인허가 feature의 ``source_entity_id`` = ``{slug}::{mng_no}``
(bulk 적재 자연키, ADR-009).

ADR 참조
--------
- ADR-004 — 쿼리는 raw SQL (``feature_repo.get_primary_source_detail``)
- ADR-005 + ADR-035 — 인증 없음, 운영 범위. 본 라우터는 ``/debug`` prefix.
- ADR-006 — provider 라이브러리 미import (적재된 raw_data 재사용, on-demand fetch 아님)
"""

from __future__ import annotations

import time
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from krtour.map.infra import feature_repo
from krtour.map.providers.mois import DATASET_KEY_BULK, PROVIDER_NAME
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from krtour.map_debug_ui.db import get_session

__all__ = ["router", "MoisLicenseDetailResponse", "clear_detail_cache"]

# providers.mois._LICENSE_ENTITY_TYPE (private)와 동일 — license_place.
_MOIS_ENTITY_TYPE = "license_place"

_CACHE_TTL_SECONDS = 300.0
# 프로세스 내 캐시(적재 아님) — license_id → (만료 monotonic, 응답).
_CACHE: dict[str, tuple[float, MoisLicenseDetailResponse]] = {}

router = APIRouter(prefix="/debug/mois-license", tags=["debug", "mois"])


class MoisLicenseDetailResponse(BaseModel):
    """``GET /debug/mois-license/{license_id}`` 응답 — 단건 on-demand 상세."""

    model_config = ConfigDict(extra="forbid")

    license_id: str = Field(description="source_entity_id ({slug}::{mng_no}).")
    feature_id: str
    name: str
    category: str
    status: str
    lon: float | None = None
    lat: float | None = None
    address: dict[str, Any]
    detail: dict[str, Any]
    raw: dict[str, Any] = Field(description="원본 MOIS payload (source_records.raw_data).")
    cached: bool = Field(description="프로세스 캐시 히트 여부.")


def clear_detail_cache() -> None:
    """프로세스 내 상세 캐시 비우기 (테스트/운영 무효화용)."""
    _CACHE.clear()


def _cache_get(license_id: str) -> MoisLicenseDetailResponse | None:
    hit = _CACHE.get(license_id)
    if hit is not None and hit[0] > time.monotonic():
        return hit[1]
    return None


@router.get(
    "/{license_id}",
    response_model=MoisLicenseDetailResponse,
    summary="MOIS 인허가 on-demand 상세 (Step D, 캐시만)",
    responses={404: {"description": "license_id(source_entity_id) 미적재"}},
)
async def get_mois_license_detail(
    license_id: str,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> MoisLicenseDetailResponse:
    cached = _cache_get(license_id)
    if cached is not None:
        return cached.model_copy(update={"cached": True})

    row = await feature_repo.get_primary_source_detail(
        session,
        provider=PROVIDER_NAME,
        dataset_key=DATASET_KEY_BULK,
        source_entity_type=_MOIS_ENTITY_TYPE,
        source_entity_id=license_id,
    )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"MOIS 인허가 미적재: {license_id!r}",
        )
    resp = MoisLicenseDetailResponse(
        license_id=license_id,
        feature_id=row["feature_id"],
        name=row["name"],
        category=row["category"],
        status=row["status"],
        lon=row["lon"],
        lat=row["lat"],
        address=row["address"],
        detail=row["detail"],
        raw=row["raw_data"],
        cached=False,
    )
    _CACHE[license_id] = (time.monotonic() + _CACHE_TTL_SECONDS, resp)
    return resp
