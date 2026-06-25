"""``GET /categories`` — PlaceCategory 정적 카탈로그(144건) HTTP 표면 (T-213f).

``kortravelmap.category`` 카탈로그(ADR-023/027)를 public/admin frontend가 런타임에
받을 수 있게 노출한다. 정적 카탈로그는 immutable이라 모듈 로드 시 1회 구성한다
(ADR-030 narrow 예외). ``include_counts=true``면 현재 DB 적재 분포(category code별
feature 수)를 합쳐 "활성 category" 판단에 쓸 수 있다.
"""

from __future__ import annotations

from time import perf_counter
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from kortravelmap.category import PLACE_CATEGORY_DEFINITIONS, PlaceCategory
from kortravelmap.infra import feature_repo
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.api.db import get_session
from kortravelmap.api.response import Meta, make_meta

router = APIRouter(tags=["categories"])


class CategorySummary(BaseModel):
    """정적 카탈로그 1건 (+ 선택적 DB 분포)."""

    model_config = ConfigDict(extra="forbid")

    code: str
    depth: int
    tier1_code: str
    tier1_name: str
    tier2_code: str
    tier2_name: str | None
    tier3_code: str
    tier3_name: str | None
    tier4_code: str
    tier4_name: str | None
    label: str
    path: list[str]
    parent_code: str | None
    sort_order: int
    is_active: bool
    maki_icon: str
    # include_counts=true일 때만 채움.
    db_feature_count: int | None = None
    db_active: bool | None = None


class CategoriesData(BaseModel):
    """``GET /categories`` data payload."""

    model_config = ConfigDict(extra="forbid")

    items: list[CategorySummary]
    include_counts: bool


class CategoriesResponse(BaseModel):
    """``GET /categories`` 응답."""

    model_config = ConfigDict(extra="forbid")

    data: CategoriesData
    meta: Meta


def _static_summary(cat: PlaceCategory) -> CategorySummary:
    return CategorySummary(
        code=cat.code,
        depth=cat.depth,
        tier1_code=cat.tier1_code,
        tier1_name=cat.tier1_name,
        tier2_code=cat.tier2_code,
        tier2_name=cat.tier2_name,
        tier3_code=cat.tier3_code,
        tier3_name=cat.tier3_name,
        tier4_code=cat.tier4_code,
        tier4_name=cat.tier4_name,
        label=cat.label,
        path=list(cat.path),
        parent_code=cat.parent_code,
        sort_order=cat.sort_order,
        is_active=cat.is_active,
        maki_icon=cat.mapbox_maki_icon,
    )


# immutable 카탈로그 — 모듈 로드 시 1회 구성(ADR-030). sort_order 정렬 고정.
_STATIC_CATEGORIES: tuple[CategorySummary, ...] = tuple(
    _static_summary(cat)
    for cat in sorted(PLACE_CATEGORY_DEFINITIONS, key=lambda c: c.sort_order)
)


@router.get(
    "/categories",
    response_model=CategoriesResponse,
    summary="PlaceCategory 정적 카탈로그(144건, 선택적 DB 분포)",
)
async def list_categories(
    session: Annotated[AsyncSession, Depends(get_session)],
    include_counts: Annotated[
        bool, Query(description="현재 DB feature 분포(category별 수)를 포함")
    ] = False,
    active_only: Annotated[
        bool, Query(description="counts를 status='active' feature만으로 집계")
    ] = False,
) -> CategoriesResponse:
    started_at = perf_counter()
    if not include_counts:
        items = list(_STATIC_CATEGORIES)
    else:
        counts = await feature_repo.category_feature_counts(
            session, active_only=active_only
        )
        items = [
            summary.model_copy(
                update={
                    "db_feature_count": counts.get(summary.code, 0),
                    "db_active": counts.get(summary.code, 0) > 0,
                }
            )
            for summary in _STATIC_CATEGORIES
        ]
    return CategoriesResponse(
        data=CategoriesData(items=items, include_counts=include_counts),
        meta=make_meta(started_at=started_at),
    )
