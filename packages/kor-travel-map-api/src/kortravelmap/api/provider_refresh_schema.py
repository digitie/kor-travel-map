"""provider refresh policy HTTP schema helpers."""

from __future__ import annotations

from datetime import datetime
from math import ceil
from typing import Any, Literal

from kortravelmap.infra.provider_refresh_policy_repo import ProviderRefreshPolicy
from pydantic import BaseModel, ConfigDict, Field, model_validator

__all__ = [
    "ProviderRefreshPolicyRecord",
    "ProviderRefreshPolicyUpsertRequest",
    "provider_refresh_policy_record",
]

SourceKind = Literal["openapi", "filedata", "manual", "system"]
TargetedPolicy = Literal["follow_system", "allow_targeted", "disabled"]


class ProviderRefreshPolicyUpsertRequest(BaseModel):
    """provider/dataset refresh policy full upsert 요청 본문.

    ``/admin/provider-refresh-policies``(구)와 ``/ops/datasets``(ADR-064 신규)
    라우터가 공유한다 — 구 라우터가 삭제(T-ADM-C6b)돼도 계약은 여기 남는다.
    """

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
