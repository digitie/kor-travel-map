"""``GET /place-attributes`` — 공개 장소 속성 catalog (ADR-121 §7.2).

장소 속성(반려동물 동반·무장애·서점 유형 등)은 Feature의 source link에서 유도한다.
목록·검색·주변 응답은 코드(``attribute_codes``)만 싣고, 라벨·묶음은 이 catalog로 푼다.
``attribute`` 필터가 받는 코드도 이 목록이다. ``admin_only`` 코드는 싣지 않는다.

catalog는 migration이 심는 작은 표라 매 요청 읽는다(캐시 없음, ADR-030).
"""

from __future__ import annotations

from time import perf_counter
from typing import Annotated

from fastapi import APIRouter, Depends
from kortravelmap.infra import place_attribute_repo
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.api.db import get_session
from kortravelmap.api.response import Meta, make_meta

__all__ = ["PlaceAttributesResponse", "router"]

router = APIRouter(tags=["place-attributes"])


class PlaceAttributeSummary(BaseModel):
    """공개 장소 속성 catalog 1건."""

    model_config = ConfigDict(extra="forbid")

    code: str
    label: str
    group: str
    sort_order: int


class PlaceAttributesData(BaseModel):
    """``GET /place-attributes`` data payload."""

    model_config = ConfigDict(extra="forbid")

    items: list[PlaceAttributeSummary]


class PlaceAttributesResponse(BaseModel):
    """``GET /place-attributes`` 응답."""

    model_config = ConfigDict(extra="forbid")

    data: PlaceAttributesData
    meta: Meta


@router.get(
    "/place-attributes",
    response_model=PlaceAttributesResponse,
    summary="공개 장소 속성 catalog (sort_order 순)",
)
async def list_public_place_attributes(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> PlaceAttributesResponse:
    started_at = perf_counter()
    catalog = await place_attribute_repo.list_place_attributes(session, public_only=True)
    return PlaceAttributesResponse(
        data=PlaceAttributesData(
            items=[
                PlaceAttributeSummary(
                    code=item.code,
                    label=item.label,
                    group=item.group,
                    sort_order=item.sort_order,
                )
                for item in catalog
            ]
        ),
        meta=make_meta(started_at=started_at),
    )
