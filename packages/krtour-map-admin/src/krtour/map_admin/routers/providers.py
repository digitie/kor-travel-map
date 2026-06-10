"""``/providers`` — provider 데이터 신선도 (T-213g 단건 + T-217g 목록).

``provider_sync.provider_sync_state``를 기준으로 provider의 마지막 적재 성공/실패
시각을 제공한다. 단건(``GET /providers/{provider}/last-sync``)은 TripMate 상세 카드
"n시간 전 갱신" 표시용, 목록(``GET /providers``)은 전 provider×dataset 신선도/최근
실패를 한눈에 보는 운영 대시보드용(D-07/T-217g). 내부 cursor(provider 증분 상태)는
**응답에 노출하지 않는다**(운영 내부 값). 단건은 ``dataset_key``/``sync_scope``
필터로 좁힐 수 있고, 매칭 행이 없으면 404. 목록은 빈 배열을 200으로 반환한다
(아직 한 번도 적재하지 않은 환경).
"""

from __future__ import annotations

from datetime import datetime
from time import perf_counter
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from krtour.map.infra import sync_state_repo
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from krtour.map_admin.db import get_session
from krtour.map_admin.response import Meta, make_meta

router = APIRouter(tags=["providers"])


class SyncStateSummary(BaseModel):
    """provider 1 (dataset_key, sync_scope) 신선도 — cursor 제외."""

    model_config = ConfigDict(extra="forbid")

    dataset_key: str
    sync_scope: str
    status: str
    last_success_at: datetime | None
    last_failure_at: datetime | None
    consecutive_failures: int


class ProviderLastSyncData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str
    items: list[SyncStateSummary]


class ProviderLastSyncResponse(BaseModel):
    """``GET /providers/{provider}/last-sync`` 응답."""

    model_config = ConfigDict(extra="forbid")

    data: ProviderLastSyncData
    meta: Meta


class ProviderSyncStateSummary(BaseModel):
    """전체 목록의 1행 — ``SyncStateSummary`` + ``provider`` (cursor 제외)."""

    model_config = ConfigDict(extra="forbid")

    provider: str
    dataset_key: str
    sync_scope: str
    status: str
    last_success_at: datetime | None
    last_failure_at: datetime | None
    consecutive_failures: int


class ProvidersFreshnessData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[ProviderSyncStateSummary]


class ProvidersFreshnessResponse(BaseModel):
    """``GET /providers`` 응답 — 전 provider×dataset 신선도 목록."""

    model_config = ConfigDict(extra="forbid")

    data: ProvidersFreshnessData
    meta: Meta


@router.get(
    "/providers",
    response_model=ProvidersFreshnessResponse,
    summary="전 provider 데이터 신선도 목록(대시보드)",
)
async def list_providers_freshness(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ProvidersFreshnessResponse:
    """전 provider×dataset×scope의 last-sync/최근 실패 요약 (T-217g, D-07).

    행 수가 유한(provider×dataset 수십 개)하므로 페이지네이션 없이 전량 반환한다
    (``/v1/categories`` bounded reference 패턴). 빈 환경은 200 + 빈 ``items``.
    """
    started_at = perf_counter()
    states = await sync_state_repo.list_all_sync_states(session)
    items = [
        ProviderSyncStateSummary(
            provider=s.provider,
            dataset_key=s.dataset_key,
            sync_scope=s.sync_scope,
            status=s.status,
            last_success_at=s.last_success_at,
            last_failure_at=s.last_failure_at,
            consecutive_failures=s.consecutive_failures,
        )
        for s in states
    ]
    return ProvidersFreshnessResponse(
        data=ProvidersFreshnessData(items=items),
        meta=make_meta(started_at=started_at),
    )


@router.get(
    "/providers/{provider}/last-sync",
    response_model=ProviderLastSyncResponse,
    summary="provider 데이터 신선도(last-sync)",
    responses={404: {"description": "provider sync state 없음"}},
)
async def get_provider_last_sync(
    session: Annotated[AsyncSession, Depends(get_session)],
    provider: str,
    dataset_key: Annotated[str | None, Query(description="dataset_key 필터")] = None,
    sync_scope: Annotated[str | None, Query(description="sync_scope 필터")] = None,
) -> ProviderLastSyncResponse:
    started_at = perf_counter()
    states = await sync_state_repo.list_sync_states(
        session, provider=provider, dataset_key=dataset_key, sync_scope=sync_scope
    )
    if not states:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"provider sync state 없음: {provider!r}",
        )
    items = [
        SyncStateSummary(
            dataset_key=s.dataset_key,
            sync_scope=s.sync_scope,
            status=s.status,
            last_success_at=s.last_success_at,
            last_failure_at=s.last_failure_at,
            consecutive_failures=s.consecutive_failures,
        )
        for s in states
    ]
    return ProviderLastSyncResponse(
        data=ProviderLastSyncData(provider=provider, items=items),
        meta=make_meta(started_at=started_at),
    )
