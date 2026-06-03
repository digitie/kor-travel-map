"""``ops.provider_refresh_policies`` repository (ADR-045 T-205c).

Provider/dataset별 refresh 주기와 rate-limit 근거를 저장한다. 본 모듈은 정책 row의
upsert/get/list만 제공하고, 실제 rate-limit enforcement는 request 실행 본체(T-206d)
와 Dagster resource가 수행한다.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any, Final

from sqlalchemy import text

if TYPE_CHECKING:
    from collections.abc import Mapping

    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = [
    "ProviderRefreshPolicy",
    "get_provider_refresh_policy",
    "list_provider_refresh_policies",
    "upsert_provider_refresh_policy",
]

_SOURCE_KINDS: Final[frozenset[str]] = frozenset(
    {"openapi", "filedata", "manual", "system"}
)
_TARGETED_POLICIES: Final[frozenset[str]] = frozenset(
    {"follow_system", "allow_targeted", "disabled"}
)
_MAX_LIST_LIMIT: Final[int] = 500

_RETURN_COLUMNS: Final[str] = (
    "provider, dataset_key, source_kind, targeted_policy, "
    "system_interval_seconds, optimal_interval_seconds, min_interval_seconds, "
    "max_requests_per_minute, max_requests_per_hour, max_requests_per_day, "
    "max_concurrent, burst_size, rate_limit_source, config_source, enabled, "
    "created_at, updated_at"
)


@dataclass(frozen=True)
class ProviderRefreshPolicy:
    """``ops.provider_refresh_policies`` row."""

    provider: str
    dataset_key: str
    source_kind: str
    targeted_policy: str
    system_interval_seconds: int | None
    optimal_interval_seconds: int | None
    min_interval_seconds: int | None
    max_requests_per_minute: int | None
    max_requests_per_hour: int | None
    max_requests_per_day: int | None
    max_concurrent: int
    burst_size: int | None
    rate_limit_source: dict[str, Any]
    config_source: str
    enabled: bool
    created_at: datetime
    updated_at: datetime


def _json_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        value = json.loads(value)
    return dict(value) if value else {}


def _row_to_policy(row: Any) -> ProviderRefreshPolicy:
    return ProviderRefreshPolicy(
        provider=str(row.provider),
        dataset_key=str(row.dataset_key),
        source_kind=str(row.source_kind),
        targeted_policy=str(row.targeted_policy),
        system_interval_seconds=row.system_interval_seconds,
        optimal_interval_seconds=row.optimal_interval_seconds,
        min_interval_seconds=row.min_interval_seconds,
        max_requests_per_minute=row.max_requests_per_minute,
        max_requests_per_hour=row.max_requests_per_hour,
        max_requests_per_day=row.max_requests_per_day,
        max_concurrent=int(row.max_concurrent),
        burst_size=row.burst_size,
        rate_limit_source=_json_dict(row.rate_limit_source),
        config_source=str(row.config_source),
        enabled=bool(row.enabled),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _validate_policy(
    *,
    provider: str,
    dataset_key: str,
    source_kind: str,
    targeted_policy: str,
    max_concurrent: int,
) -> None:
    if not provider:
        raise ValueError("provider must be non-empty")
    if not dataset_key:
        raise ValueError("dataset_key must be non-empty")
    if source_kind not in _SOURCE_KINDS:
        raise ValueError(f"source_kind must be one of {sorted(_SOURCE_KINDS)}")
    if targeted_policy not in _TARGETED_POLICIES:
        raise ValueError(
            f"targeted_policy must be one of {sorted(_TARGETED_POLICIES)}"
        )
    if max_concurrent <= 0:
        raise ValueError("max_concurrent must be greater than 0")


_UPSERT_SQL: Final[str] = f"""
INSERT INTO ops.provider_refresh_policies (
    provider, dataset_key, source_kind, targeted_policy,
    system_interval_seconds, optimal_interval_seconds, min_interval_seconds,
    max_requests_per_minute, max_requests_per_hour, max_requests_per_day,
    max_concurrent, burst_size, rate_limit_source, config_source, enabled,
    updated_at
) VALUES (
    :provider, :dataset_key, :source_kind, :targeted_policy,
    :system_interval_seconds, :optimal_interval_seconds, :min_interval_seconds,
    :max_requests_per_minute, :max_requests_per_hour, :max_requests_per_day,
    :max_concurrent, :burst_size, CAST(:rate_limit_source AS jsonb),
    :config_source, :enabled, now()
)
ON CONFLICT (provider, dataset_key) DO UPDATE SET
    source_kind = EXCLUDED.source_kind,
    targeted_policy = EXCLUDED.targeted_policy,
    system_interval_seconds = EXCLUDED.system_interval_seconds,
    optimal_interval_seconds = EXCLUDED.optimal_interval_seconds,
    min_interval_seconds = EXCLUDED.min_interval_seconds,
    max_requests_per_minute = EXCLUDED.max_requests_per_minute,
    max_requests_per_hour = EXCLUDED.max_requests_per_hour,
    max_requests_per_day = EXCLUDED.max_requests_per_day,
    max_concurrent = EXCLUDED.max_concurrent,
    burst_size = EXCLUDED.burst_size,
    rate_limit_source = EXCLUDED.rate_limit_source,
    config_source = EXCLUDED.config_source,
    enabled = EXCLUDED.enabled,
    updated_at = now()
RETURNING {_RETURN_COLUMNS}
"""

_GET_SQL: Final[str] = f"""
SELECT {_RETURN_COLUMNS}
FROM ops.provider_refresh_policies
WHERE provider = :provider AND dataset_key = :dataset_key
"""

_LIST_SQL: Final[str] = f"""
SELECT {_RETURN_COLUMNS}
FROM ops.provider_refresh_policies
WHERE (CAST(:provider AS text) IS NULL OR provider = CAST(:provider AS text))
  AND (CAST(:enabled AS boolean) IS NULL OR enabled = CAST(:enabled AS boolean))
ORDER BY provider, dataset_key
LIMIT :limit
"""


async def upsert_provider_refresh_policy(
    session: AsyncSession,
    *,
    provider: str,
    dataset_key: str,
    source_kind: str,
    targeted_policy: str = "follow_system",
    system_interval_seconds: int | None = None,
    optimal_interval_seconds: int | None = None,
    min_interval_seconds: int | None = None,
    max_requests_per_minute: int | None = None,
    max_requests_per_hour: int | None = None,
    max_requests_per_day: int | None = None,
    max_concurrent: int = 1,
    burst_size: int | None = None,
    rate_limit_source: Mapping[str, Any] | None = None,
    config_source: str = "db",
    enabled: bool = True,
) -> ProviderRefreshPolicy:
    """정책 row를 upsert한다. commit은 호출자 책임."""
    _validate_policy(
        provider=provider,
        dataset_key=dataset_key,
        source_kind=source_kind,
        targeted_policy=targeted_policy,
        max_concurrent=max_concurrent,
    )
    row = (
        await session.execute(
            text(_UPSERT_SQL),
            {
                "provider": provider,
                "dataset_key": dataset_key,
                "source_kind": source_kind,
                "targeted_policy": targeted_policy,
                "system_interval_seconds": system_interval_seconds,
                "optimal_interval_seconds": optimal_interval_seconds,
                "min_interval_seconds": min_interval_seconds,
                "max_requests_per_minute": max_requests_per_minute,
                "max_requests_per_hour": max_requests_per_hour,
                "max_requests_per_day": max_requests_per_day,
                "max_concurrent": max_concurrent,
                "burst_size": burst_size,
                "rate_limit_source": json.dumps(
                    dict(rate_limit_source) if rate_limit_source else {},
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
                "config_source": config_source,
                "enabled": enabled,
            },
        )
    ).one()
    return _row_to_policy(row)


async def get_provider_refresh_policy(
    session: AsyncSession,
    *,
    provider: str,
    dataset_key: str,
) -> ProviderRefreshPolicy | None:
    """정책 row 1건 조회. 없으면 ``None``."""
    row = (
        await session.execute(
            text(_GET_SQL),
            {"provider": provider, "dataset_key": dataset_key},
        )
    ).one_or_none()
    return _row_to_policy(row) if row is not None else None


async def list_provider_refresh_policies(
    session: AsyncSession,
    *,
    provider: str | None = None,
    enabled: bool | None = None,
    limit: int = 200,
) -> tuple[ProviderRefreshPolicy, ...]:
    """정책 목록 조회. API pagination은 후속 admin 라우터에서 cursor로 감싼다."""
    safe_limit = max(1, min(limit, _MAX_LIST_LIMIT))
    rows = (
        await session.execute(
            text(_LIST_SQL),
            {"provider": provider, "enabled": enabled, "limit": safe_limit},
        )
    ).all()
    return tuple(_row_to_policy(row) for row in rows)
