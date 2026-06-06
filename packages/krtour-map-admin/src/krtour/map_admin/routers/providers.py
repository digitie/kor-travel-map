"""``GET /providers/{provider}/last-sync`` — provider 데이터 신선도 (T-213g).

``provider_sync.provider_sync_state``를 기준으로 provider의 마지막 적재 성공/실패
시각을 제공한다. TripMate 상세 카드 "n시간 전 갱신" 표시용. 내부 cursor(provider
증분 상태)는 **응답에 노출하지 않는다**(운영 내부 값). ``dataset_key``/``sync_scope``
필터로 좁힐 수 있고, 매칭 행이 없으면 404.
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
    count: int


class _Meta(BaseModel):
    model_config = ConfigDict(extra="forbid")

    count: int
    duration_ms: int


class ProviderLastSyncResponse(BaseModel):
    """``GET /providers/{provider}/last-sync`` 응답."""

    model_config = ConfigDict(extra="forbid")

    data: ProviderLastSyncData
    meta: _Meta


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
    duration_ms = max(0, int((perf_counter() - started_at) * 1000))
    return ProviderLastSyncResponse(
        data=ProviderLastSyncData(provider=provider, items=items, count=len(items)),
        meta=_Meta(count=len(items), duration_ms=duration_ms),
    )
