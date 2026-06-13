"""``/admin/provider-refresh-policies`` — provider refresh policy 편집 API."""

from __future__ import annotations

from math import ceil
from time import perf_counter
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from kortravelmap.infra.provider_refresh_policy_repo import (
    get_provider_refresh_policy,
    list_provider_refresh_policies,
    upsert_provider_refresh_policy,
)
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.api.db import get_session
from kortravelmap.api.provider_refresh_schema import (
    ProviderRefreshPolicyRecord,
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

SourceKind = Literal["openapi", "filedata", "manual", "system"]
TargetedPolicy = Literal["follow_system", "allow_targeted", "disabled"]


class ProviderRefreshPolicyUpsertRequest(BaseModel):
    """provider/dataset refresh policy full upsert 요청."""

    model_config = ConfigDict(extra="forbid")

    source_kind: SourceKind
    targeted_policy: TargetedPolicy = "follow_system"
    system_interval_seconds: int | None = Field(default=None, gt=0)
    optimal_interval_seconds: int | None = Field(default=None, gt=0)
    min_interval_seconds: int | None = Field(default=None, gt=0)
    max_requests_per_minute: int | None = Field(default=None, gt=0)
    max_requests_per_hour: int | None = Field(default=None, gt=0)
    max_requests_per_day: int | None = Field(default=None, gt=0)
    max_concurrent: int = Field(default=1, gt=0)
    burst_size: int | None = Field(default=None, gt=0)
    rate_limit_source: dict[str, Any] = Field(default_factory=dict)
    config_source: str = Field(default="db", min_length=1, max_length=64)
    enabled: bool = True

    @model_validator(mode="after")
    def _validate_interval_floor(self) -> ProviderRefreshPolicyUpsertRequest:
        floor = self._effective_min_interval_seconds()
        if self.min_interval_seconds is not None and self.min_interval_seconds < floor:
            raise ValueError(
                "min_interval_seconds must not be lower than declared rate limits"
            )
        for field_name in ("system_interval_seconds", "optimal_interval_seconds"):
            value = getattr(self, field_name)
            if value is not None and value < floor:
                raise ValueError(
                    f"{field_name} must be greater than or equal to the effective "
                    "rate-limit interval"
                )
        return self

    def _effective_min_interval_seconds(self) -> int:
        floors = [self.min_interval_seconds or 0]
        if self.max_requests_per_minute:
            floors.append(ceil(60 / self.max_requests_per_minute))
        if self.max_requests_per_hour:
            floors.append(ceil(3600 / self.max_requests_per_hour))
        if self.max_requests_per_day:
            floors.append(ceil(86400 / self.max_requests_per_day))
        return max(floors)


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
                max_requests_per_minute=body.max_requests_per_minute,
                max_requests_per_hour=body.max_requests_per_hour,
                max_requests_per_day=body.max_requests_per_day,
                max_concurrent=body.max_concurrent,
                burst_size=body.burst_size,
                rate_limit_source=body.rate_limit_source,
                config_source=body.config_source,
                enabled=body.enabled,
            )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return ProviderRefreshPolicyResponse(
        data=provider_refresh_policy_record(policy),
        meta=make_meta(started_at=started_at),
    )
