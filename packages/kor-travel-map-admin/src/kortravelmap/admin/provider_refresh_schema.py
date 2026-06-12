"""provider refresh policy HTTP schema helpers."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from kortravelmap.infra.provider_refresh_policy_repo import ProviderRefreshPolicy
from pydantic import BaseModel, ConfigDict

__all__ = ["ProviderRefreshPolicyRecord", "provider_refresh_policy_record"]


class ProviderRefreshPolicyRecord(BaseModel):
    """``ops.provider_refresh_policies`` HTTP 표현."""

    model_config = ConfigDict(extra="forbid")

    provider: str
    dataset_key: str
    source_kind: str
    targeted_policy: str
    system_interval_seconds: int | None = None
    optimal_interval_seconds: int | None = None
    min_interval_seconds: int | None = None
    max_requests_per_minute: int | None = None
    max_requests_per_hour: int | None = None
    max_requests_per_day: int | None = None
    max_concurrent: int
    burst_size: int | None = None
    rate_limit_source: dict[str, Any]
    config_source: str
    enabled: bool
    created_at: datetime
    updated_at: datetime


def provider_refresh_policy_record(
    policy: ProviderRefreshPolicy,
) -> ProviderRefreshPolicyRecord:
    """repo dataclass를 OpenAPI DTO로 변환한다."""
    return ProviderRefreshPolicyRecord(
        provider=policy.provider,
        dataset_key=policy.dataset_key,
        source_kind=policy.source_kind,
        targeted_policy=policy.targeted_policy,
        system_interval_seconds=policy.system_interval_seconds,
        optimal_interval_seconds=policy.optimal_interval_seconds,
        min_interval_seconds=policy.min_interval_seconds,
        max_requests_per_minute=policy.max_requests_per_minute,
        max_requests_per_hour=policy.max_requests_per_hour,
        max_requests_per_day=policy.max_requests_per_day,
        max_concurrent=policy.max_concurrent,
        burst_size=policy.burst_size,
        rate_limit_source=policy.rate_limit_source,
        config_source=policy.config_source,
        enabled=policy.enabled,
        created_at=policy.created_at,
        updated_at=policy.updated_at,
    )
