"""공개 provider 신선도 조회 라우터.

운영자용 provider 상태·정책·실행 기능은 ``/ops/datasets``로 수렴한다. 이
모듈은 외부 소비자가 사용하는 bounded read 계약 두 개만 소유한다.
"""

from __future__ import annotations

from datetime import datetime
from time import perf_counter
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from kortravelmap.infra import sync_state_repo
from kortravelmap.infra.sync_state_repo import SyncState
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.api.db import get_session
from kortravelmap.api.response import Meta, make_meta

__all__ = ["router"]

router = APIRouter(prefix="/providers", tags=["providers"])


class SyncStateSummary(BaseModel):
    """provider dataset 신선도. 내부 cursor는 공개하지 않는다."""

    model_config = ConfigDict(extra="forbid")

    dataset_key: str
    sync_scope: str
    # 실행 membership identity는 triple이다(ADR-088 §결정 2). operation_key가
    # 없으면 operation만 다른 두 state가 같은 항목으로 보인다.
    operation_key: str
    status: str
    last_success_at: datetime | None
    last_failure_at: datetime | None
    consecutive_failures: int


class ProviderLastSyncData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str
    items: list[SyncStateSummary]


class ProviderLastSyncResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data: ProviderLastSyncData
    meta: Meta


class ProviderSyncStateSummary(SyncStateSummary):
    model_config = ConfigDict(extra="forbid")

    provider: str


class ProvidersFreshnessData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[ProviderSyncStateSummary]


class ProvidersFreshnessResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data: ProvidersFreshnessData
    meta: Meta


def _summary(state: SyncState) -> SyncStateSummary:
    return SyncStateSummary(
        dataset_key=state.dataset_key,
        sync_scope=state.sync_scope,
        operation_key=state.operation_key,
        status=state.status,
        last_success_at=state.last_success_at,
        last_failure_at=state.last_failure_at,
        consecutive_failures=state.consecutive_failures,
    )


def _provider_summary(state: SyncState) -> ProviderSyncStateSummary:
    return ProviderSyncStateSummary(provider=state.provider, **_summary(state).model_dump())


@router.get(
    "",
    response_model=ProvidersFreshnessResponse,
    summary="전 provider 데이터 신선도 목록",
)
async def list_providers_freshness(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ProvidersFreshnessResponse:
    """bounded provider×dataset×scope 신선도 목록을 반환한다."""
    started_at = perf_counter()
    states = await sync_state_repo.list_all_sync_states(session)
    return ProvidersFreshnessResponse(
        data=ProvidersFreshnessData(items=[_provider_summary(state) for state in states]),
        meta=make_meta(started_at=started_at),
    )


@router.get(
    "/{provider}/last-sync",
    response_model=ProviderLastSyncResponse,
    summary="provider 데이터 신선도(last-sync)",
    responses={404: {"description": "provider sync state 없음"}},
)
async def get_provider_last_sync(
    provider: str,
    session: Annotated[AsyncSession, Depends(get_session)],
    dataset_key: Annotated[str | None, Query(description="dataset_key 필터")] = None,
    sync_scope: Annotated[str | None, Query(description="sync_scope 필터")] = None,
    operation_key: Annotated[str | None, Query(description="operation_key 필터")] = None,
) -> ProviderLastSyncResponse:
    started_at = perf_counter()
    states = await sync_state_repo.list_sync_states(
        session,
        provider=provider,
        dataset_key=dataset_key,
        sync_scope=sync_scope,
        operation_key=operation_key,
    )
    if not states:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"provider sync state 없음: {provider!r}",
        )
    return ProviderLastSyncResponse(
        data=ProviderLastSyncData(
            provider=provider,
            items=[_summary(state) for state in states],
        ),
        meta=make_meta(started_at=started_at),
    )
