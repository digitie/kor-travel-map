"""provider refresh policy HTTP schema helpers."""

from __future__ import annotations

from datetime import datetime
from math import ceil
from typing import Annotated, Any, Literal

from kortravelmap.infra.provider_refresh_policy_repo import ProviderRefreshPolicy
from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

from kortravelmap.api.response import ProblemDetail

__all__ = [
    "ProviderRefreshPolicyRecord",
    "ProviderRefreshPolicyConflictDetails",
    "ProviderRefreshPolicyConflictProblem",
    "ProviderRefreshPolicyUpsertRequest",
    "provider_refresh_policy_record",
]

SourceKind = Literal["openapi", "filedata", "manual", "system"]
TargetedPolicy = Literal["follow_system", "allow_targeted", "disabled"]
_BIGINT_MAX = 9_223_372_036_854_775_807


def _positive_bigint_decimal(value: str) -> str:
    if int(value) > _BIGINT_MAX:
        raise ValueError("revision must fit signed BIGINT")
    return value


PositiveBigintDecimal = Annotated[
    str,
    Field(pattern=r"^[1-9][0-9]*$"),
    AfterValidator(_positive_bigint_decimal),
]


class ProviderRefreshPolicyUpsertRequest(BaseModel):
    """canonical ``/ops/datasets/refresh-policy`` full upsert 요청 본문."""

    model_config = ConfigDict(extra="forbid")

    expected_revision: PositiveBigintDecimal | None = Field(
        description=(
            "신규 생성은 null, 기존 갱신은 조회한 양수 BIGINT revision의 "
            "정규화된 10진 문자열. 필드 생략은 허용하지 않는다."
        ),
    )
    source_kind: SourceKind
    targeted_policy: TargetedPolicy = "follow_system"
    system_interval_seconds: int | None = Field(default=None, gt=0)
    optimal_interval_seconds: int | None = Field(default=None, gt=0)
    min_interval_seconds: int | None = Field(default=None, gt=0)
    stale_after_minutes: int | None = Field(
        default=None,
        gt=0,
        description=(
            "마지막 성공 이후 stale로 판정할 명시적 운영 SLA(분). "
            "미설정이면 freshness는 unknown이며 호출 간격/rate-limit에서 추론하지 않는다."
        ),
    )
    max_requests_per_minute: int | None = Field(default=None, gt=0)
    max_requests_per_hour: int | None = Field(default=None, gt=0)
    max_requests_per_day: int | None = Field(default=None, gt=0)
    max_concurrent: int = Field(default=1, gt=0)
    burst_size: int | None = Field(default=None, gt=0)
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

    provider_dataset_id: int = Field(
        ge=1,
        description="정책 저장·변경의 유일한 canonical provider dataset 식별자.",
    )
    provider: str | None = Field(
        default=None,
        description="provider_datasets join에서만 얻는 표시용 provider.",
    )
    dataset_key: str | None = Field(
        default=None,
        description="provider_datasets join에서만 얻는 표시용 dataset key.",
    )
    source_kind: str
    targeted_policy: str
    system_interval_seconds: int | None = None
    optimal_interval_seconds: int | None = None
    min_interval_seconds: int | None = None
    stale_after_minutes: int | None = None
    max_requests_per_minute: int | None = None
    max_requests_per_hour: int | None = None
    max_requests_per_day: int | None = None
    max_concurrent: int
    burst_size: int | None = None
    rate_limit_source: dict[str, Any]
    config_source: str
    enabled: bool
    revision: PositiveBigintDecimal = Field(
        description="DB BIGINT revision의 정규화된 양수 10진 문자열.",
    )
    created_at: datetime
    updated_at: datetime


class ProviderRefreshPolicyConflictDetails(BaseModel):
    """orphan 또는 revision conflict의 typed 세부 정보."""

    model_config = ConfigDict(extra="forbid")

    expected_revision: PositiveBigintDecimal | None
    current_revision: PositiveBigintDecimal | None
    current_record: ProviderRefreshPolicyRecord | None
    mutation_disabled_reason: str | None


class ProviderRefreshPolicyConflictProblem(ProblemDetail):
    """refresh-policy PUT의 typed RFC7807 409 응답."""

    details: ProviderRefreshPolicyConflictDetails


def provider_refresh_policy_record(
    policy: ProviderRefreshPolicy,
) -> ProviderRefreshPolicyRecord:
    """repo dataclass를 OpenAPI DTO로 변환한다."""
    return ProviderRefreshPolicyRecord(
        provider_dataset_id=policy.provider_dataset_id,
        provider=policy.provider,
        dataset_key=policy.dataset_key,
        source_kind=policy.source_kind,
        targeted_policy=policy.targeted_policy,
        system_interval_seconds=policy.system_interval_seconds,
        optimal_interval_seconds=policy.optimal_interval_seconds,
        min_interval_seconds=policy.min_interval_seconds,
        stale_after_minutes=policy.stale_after_minutes,
        max_requests_per_minute=policy.max_requests_per_minute,
        max_requests_per_hour=policy.max_requests_per_hour,
        max_requests_per_day=policy.max_requests_per_day,
        max_concurrent=policy.max_concurrent,
        burst_size=policy.burst_size,
        rate_limit_source=policy.rate_limit_source,
        config_source=policy.config_source,
        enabled=policy.enabled,
        revision=str(policy.revision),
        created_at=policy.created_at,
        updated_at=policy.updated_at,
    )
