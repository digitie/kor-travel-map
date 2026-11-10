"""``GET /admin/theme-attach-decisions`` — MCST 테마 목록 붙임 판정 조회 (ADR-121 §7.2).

apply 모드 MCST 적재가 행마다 남기는 판정(``provider_sync.theme_attach_decisions``)을
운영자가 읽는다. 판정은 근거 보관용이고 정본은 source link다. 읽기 전용 — 수동 붙임·보류
command는 R5에서 둔다. 목록은 PK ``(provider_dataset_id, natural_key)`` keyset cursor다.
"""

from __future__ import annotations

from datetime import datetime
from time import perf_counter
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from kortravelmap.infra import place_attribute_repo
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.api.db import get_read_snapshot_session
from kortravelmap.api.response import Meta, make_meta

__all__ = ["ThemeAttachDecisionListResponse", "router"]

router = APIRouter(prefix="/admin/theme-attach-decisions", tags=["admin-theme-attach"])

ThemeAttachDecisionState = Literal[
    "owner", "matched", "sticky", "redirected", "created", "ambiguous", "unresolved"
]


class ThemeAttachDecisionRecord(BaseModel):
    """MCST 행 하나의 붙임 판정."""

    model_config = ConfigDict(extra="forbid")

    provider: str
    dataset_key: str
    natural_key: str
    state: ThemeAttachDecisionState
    target_feature_id: str | None = Field(
        default=None,
        description="link가 걸린 Feature(보류 상태 ambiguous·unresolved면 null).",
    )
    rule_version: str
    evidence: dict[str, Any] = Field(description="후보 상위 3개의 거리·이름 점수·tier.")
    decided_at: datetime


class ThemeAttachDecisionListData(BaseModel):
    """판정 목록 data."""

    model_config = ConfigDict(extra="forbid")

    items: list[ThemeAttachDecisionRecord]


class ThemeAttachDecisionListResponse(BaseModel):
    """``GET /admin/theme-attach-decisions`` 응답."""

    model_config = ConfigDict(extra="forbid")

    data: ThemeAttachDecisionListData
    meta: Meta


@router.get(
    "",
    response_model=ThemeAttachDecisionListResponse,
    summary="MCST 테마 목록 붙임 판정 목록 (읽기 전용)",
    responses={422: {"description": "cursor·필터 오류"}},
)
async def list_theme_attach_decisions(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_read_snapshot_session)],
    dataset_key: Annotated[
        str | None,
        Query(min_length=1, max_length=200, description="MCST dataset_key 필터."),
    ] = None,
    state: Annotated[
        ThemeAttachDecisionState | None,
        Query(description="판정 상태 필터."),
    ] = None,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: Annotated[str | None, Query()] = None,
) -> ThemeAttachDecisionListResponse:
    started_at = perf_counter()
    try:
        page = await place_attribute_repo.list_theme_attach_decisions(
            session,
            dataset_key=dataset_key,
            state=state,
            page_size=page_size,
            cursor=cursor,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    return ThemeAttachDecisionListResponse(
        data=ThemeAttachDecisionListData(
            items=[
                ThemeAttachDecisionRecord.model_validate(item, from_attributes=True)
                for item in page.items
            ]
        ),
        meta=make_meta(
            request,
            started_at=started_at,
            page_size=page_size,
            next_cursor=page.next_cursor,
        ),
    )
