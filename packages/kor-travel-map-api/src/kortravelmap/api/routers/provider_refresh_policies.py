"""``/admin/provider-refresh-policies`` — provider refresh policy 편집 API."""

from __future__ import annotations

from time import perf_counter
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from kortravelmap.infra.provider_refresh_policy_repo import (
    get_provider_refresh_policy,
    list_provider_refresh_policies,
    upsert_provider_refresh_policy,
)
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.api.db import get_session
from kortravelmap.api.provider_refresh_schema import (
    ProviderRefreshPolicyRecord,
    ProviderRefreshPolicyUpsertRequest,
    provider_refresh_policy_record,
)
from kortravelmap.api.response import Meta, make_meta

__all__ = [
    "ProviderRefreshPolicyListResponse",
    "ProviderRefreshPolicyResponse",
    "ProviderRefreshPolicyUpsertRequest",
    "router",
]


router = APIRouter(
    prefix="/admin/provider-refresh-policies",
    tags=["admin-provider-refresh-policies"],
)


class ProviderRefreshPolicyListData(BaseModel):
    """provider refresh policy 목록 data."""

    model_config = ConfigDict(extra="forbid")

    items: list[ProviderRefreshPolicyRecord]


class ProviderRefreshPolicyListResponse(BaseModel):
    """``GET /admin/provider-refresh-policies`` 응답."""

    model_config = ConfigDict(extra="forbid")

    data: ProviderRefreshPolicyListData
    meta: Meta


class ProviderRefreshPolicyResponse(BaseModel):
    """provider refresh policy 단건 응답."""

    model_config = ConfigDict(extra="forbid")

    data: ProviderRefreshPolicyRecord
    meta: Meta


@router.get("", response_model=ProviderRefreshPolicyListResponse)
async def list_provider_refresh_policy_route(
    session: Annotated[AsyncSession, Depends(get_session)],
    provider: Annotated[str | None, Query()] = None,
    enabled: Annotated[bool | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
) -> ProviderRefreshPolicyListResponse:
    """provider/dataset refresh policy 목록."""
    started_at = perf_counter()
    policies = await list_provider_refresh_policies(
        session, provider=provider, enabled=enabled, limit=limit
    )
    return ProviderRefreshPolicyListResponse(
        data=ProviderRefreshPolicyListData(
            items=[provider_refresh_policy_record(policy) for policy in policies],
        ),
        meta=make_meta(started_at=started_at),
    )


@router.get(
    "/{provider}/{dataset_key}",
    response_model=ProviderRefreshPolicyResponse,
    responses={404: {"description": "provider refresh policy 없음"}},
)
async def get_provider_refresh_policy_route(
    provider: str,
    dataset_key: str,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ProviderRefreshPolicyResponse:
    """provider/dataset refresh policy 단건."""
    started_at = perf_counter()
    policy = await get_provider_refresh_policy(
        session, provider=provider, dataset_key=dataset_key
    )
    if policy is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                "provider refresh policy 없음: "
                f"{provider!r}/{dataset_key!r}"
            ),
        )
    return ProviderRefreshPolicyResponse(
        data=provider_refresh_policy_record(policy),
        meta=make_meta(started_at=started_at),
    )


@router.put(
    "/{provider}/{dataset_key}",
    response_model=ProviderRefreshPolicyResponse,
)
async def upsert_provider_refresh_policy_route(
    provider: str,
    dataset_key: str,
    body: ProviderRefreshPolicyUpsertRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ProviderRefreshPolicyResponse:
    """provider/dataset refresh policy를 full upsert한다."""
    started_at = perf_counter()
    try:
        async with session.begin():
            policy = await upsert_provider_refresh_policy(
                session,
                provider=provider,
                dataset_key=dataset_key,
                source_kind=body.source_kind,
                targeted_policy=body.targeted_policy,
                system_interval_seconds=body.system_interval_seconds,
                optimal_interval_seconds=body.optimal_interval_seconds,
                min_interval_seconds=body.min_interval_seconds,
                stale_after_minutes=body.stale_after_minutes,
                max_requests_per_minute=body.max_requests_per_minute,
                max_requests_per_hour=body.max_requests_per_hour,
                max_requests_per_day=body.max_requests_per_day,
                max_concurrent=body.max_concurrent,
                burst_size=body.burst_size,
                config_source=body.config_source,
                enabled=body.enabled,
            )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return ProviderRefreshPolicyResponse(
        data=provider_refresh_policy_record(policy),
        meta=make_meta(started_at=started_at),
    )
