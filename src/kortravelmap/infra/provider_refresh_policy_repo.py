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
    "ProviderRefreshPolicyRevisionConflict",
    "ProviderRefreshPolicyRevisionExhausted",
    "ProviderRefreshPolicySourceKindImmutable",
    "get_provider_refresh_policy",
    "list_all_provider_refresh_policies",
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
_BIGINT_MAX: Final[int] = 9_223_372_036_854_775_807

_RETURN_COLUMNS: Final[str] = (
    "policy.provider_dataset_id, dataset.provider, dataset.dataset_key, "
    "policy.source_kind, policy.targeted_policy, "
    "policy.system_interval_seconds, policy.optimal_interval_seconds, "
    "policy.min_interval_seconds, policy.max_requests_per_minute, "
    "policy.max_requests_per_hour, policy.max_requests_per_day, "
    "policy.max_concurrent, policy.burst_size, policy.rate_limit_source, "
    "policy.config_source, policy.enabled, policy.stale_after_minutes, "
    "policy.revision, policy.created_at, policy.updated_at"
)

_POLICY_FROM: Final[str] = """
FROM ops.provider_refresh_policies AS policy
LEFT JOIN provider_sync.provider_datasets AS dataset
  ON dataset.provider_dataset_id = policy.provider_dataset_id
"""


@dataclass(frozen=True)
class ProviderRefreshPolicy:
    """``ops.provider_refresh_policies`` row."""

    provider_dataset_id: int
    provider: str | None
    dataset_key: str | None
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
    revision: int
    created_at: datetime
    updated_at: datetime
    stale_after_minutes: int | None = None


class ProviderRefreshPolicyRevisionConflict(RuntimeError):
    """정책 create/update 종류 또는 expected revision이 현재 row와 불일치."""

    def __init__(
        self,
        *,
        expected_revision: int | None,
        current: ProviderRefreshPolicy | None,
    ) -> None:
        super().__init__("provider refresh policy revision conflict")
        self.expected_revision = expected_revision
        self.current = current


class ProviderRefreshPolicyRevisionExhausted(RuntimeError):
    """정책 revision이 BIGINT 최댓값이라 더 증가시킬 수 없음."""

    def __init__(self, *, current: ProviderRefreshPolicy) -> None:
        super().__init__("provider refresh policy revision exhausted")
        self.current = current


class ProviderRefreshPolicySourceKindImmutable(RuntimeError):
    """기존 정책의 source_kind 변경 요청을 거절한다."""

    def __init__(
        self,
        *,
        requested_source_kind: str,
        current: ProviderRefreshPolicy,
    ) -> None:
        super().__init__("provider refresh policy source_kind is immutable")
        self.requested_source_kind = requested_source_kind
        self.current = current


def _json_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        value = json.loads(value)
    return dict(value) if value else {}


def _row_to_policy(row: Any) -> ProviderRefreshPolicy:
    return ProviderRefreshPolicy(
        provider_dataset_id=int(row.provider_dataset_id),
        provider=str(row.provider) if row.provider is not None else None,
        dataset_key=str(row.dataset_key) if row.dataset_key is not None else None,
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
        revision=int(row.revision),
        stale_after_minutes=row.stale_after_minutes,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _validate_policy(
    *,
    provider_dataset_id: int,
    source_kind: str,
    targeted_policy: str,
    max_concurrent: int,
    stale_after_minutes: int | None,
) -> None:
    if (
        isinstance(provider_dataset_id, bool)
        or not isinstance(provider_dataset_id, int)
        or not 0 < provider_dataset_id <= _BIGINT_MAX
    ):
        raise ValueError("provider_dataset_id must be a positive BIGINT")
    if source_kind not in _SOURCE_KINDS:
        raise ValueError(f"source_kind must be one of {sorted(_SOURCE_KINDS)}")
    if targeted_policy not in _TARGETED_POLICIES:
        raise ValueError(
            f"targeted_policy must be one of {sorted(_TARGETED_POLICIES)}"
        )
    if max_concurrent <= 0:
        raise ValueError("max_concurrent must be greater than 0")
    if stale_after_minutes is not None and stale_after_minutes <= 0:
        raise ValueError("stale_after_minutes must be greater than 0")


_INSERT_SQL: Final[str] = """
INSERT INTO ops.provider_refresh_policies (
    provider_dataset_id, source_kind, targeted_policy,
    system_interval_seconds, optimal_interval_seconds, min_interval_seconds,
    max_requests_per_minute, max_requests_per_hour, max_requests_per_day,
    max_concurrent, burst_size, rate_limit_source, config_source, enabled,
    stale_after_minutes, revision,
    updated_at
) VALUES (
    :provider_dataset_id, :source_kind, :targeted_policy,
    :system_interval_seconds, :optimal_interval_seconds, :min_interval_seconds,
    :max_requests_per_minute, :max_requests_per_hour, :max_requests_per_day,
    :max_concurrent, :burst_size, CAST(:rate_limit_source AS jsonb),
    :config_source, :enabled, :stale_after_minutes, 1, now()
)
ON CONFLICT (provider_dataset_id) DO NOTHING
RETURNING provider_dataset_id
"""

_UPDATE_SQL: Final[str] = f"""
UPDATE ops.provider_refresh_policies AS policy
SET targeted_policy = :targeted_policy,
    system_interval_seconds = :system_interval_seconds,
    optimal_interval_seconds = :optimal_interval_seconds,
    min_interval_seconds = :min_interval_seconds,
    max_requests_per_minute = :max_requests_per_minute,
    max_requests_per_hour = :max_requests_per_hour,
    max_requests_per_day = :max_requests_per_day,
    max_concurrent = :max_concurrent,
    burst_size = :burst_size,
    rate_limit_source = CASE
        WHEN CAST(:rate_limit_source_provided AS boolean)
        THEN CAST(:rate_limit_source AS jsonb)
        ELSE policy.rate_limit_source
    END,
    config_source = :config_source,
    enabled = :enabled,
    stale_after_minutes = :stale_after_minutes,
    revision = policy.revision + 1,
    updated_at = now()
WHERE policy.provider_dataset_id = :provider_dataset_id
  AND policy.revision = CAST(:expected_revision AS bigint)
  AND policy.revision < {_BIGINT_MAX}
  AND policy.source_kind = :source_kind
RETURNING policy.provider_dataset_id
"""

_GET_SQL: Final[str] = f"""
SELECT {_RETURN_COLUMNS}
{_POLICY_FROM}
WHERE policy.provider_dataset_id = :provider_dataset_id
"""

_LIST_SQL: Final[str] = f"""
SELECT {_RETURN_COLUMNS}
{_POLICY_FROM}
WHERE (
    CAST(:provider_dataset_id AS bigint) IS NULL
    OR policy.provider_dataset_id = CAST(:provider_dataset_id AS bigint)
)
  AND (
    CAST(:enabled AS boolean) IS NULL
    OR policy.enabled = CAST(:enabled AS boolean)
)
ORDER BY policy.provider_dataset_id
LIMIT :limit
"""

_LIST_ALL_SQL: Final[str] = f"""
SELECT {_RETURN_COLUMNS}
{_POLICY_FROM}
ORDER BY policy.provider_dataset_id
"""


async def upsert_provider_refresh_policy(
    session: AsyncSession,
    *,
    provider_dataset_id: int,
    source_kind: str,
    expected_revision: int | None,
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
    stale_after_minutes: int | None = None,
) -> ProviderRefreshPolicy:
    """정책 row를 expected revision CAS로 upsert한다. commit은 호출자 책임.

    ``rate_limit_source``는 provider 계약을 수집하는 내부 caller가 소유한다.
    ``None``이면 신규 row에는 빈 object를 기록하고 기존 row에서는 provenance를
    보존한다. 명시한 mapping(빈 mapping 포함)은 내부 동기화 값으로 교체한다.

    ``expected_revision=None``은 create-only, 양수 정수는 update-only다. 종류가
    다르거나 stale이면 write 없이 ``ProviderRefreshPolicyRevisionConflict``를
    발생시키며 현재 row를 함께 제공한다. 생성 뒤 ``source_kind``는 불변이고,
    BIGINT 최댓값 revision은 증가를 시도하지 않고 각각 명시적 오류로 닫는다.
    """
    _validate_policy(
        provider_dataset_id=provider_dataset_id,
        source_kind=source_kind,
        targeted_policy=targeted_policy,
        max_concurrent=max_concurrent,
        stale_after_minutes=stale_after_minutes,
    )
    if expected_revision is not None and not 0 < expected_revision <= _BIGINT_MAX:
        raise ValueError("expected_revision must be a positive BIGINT")
    params = {
        "provider_dataset_id": provider_dataset_id,
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
            dict(rate_limit_source) if rate_limit_source is not None else {},
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        "rate_limit_source_provided": rate_limit_source is not None,
        "config_source": config_source,
        "enabled": enabled,
        "stale_after_minutes": stale_after_minutes,
        "expected_revision": expected_revision,
    }
    statement = _INSERT_SQL if expected_revision is None else _UPDATE_SQL
    changed = (await session.execute(text(statement), params)).one_or_none()
    if changed is None:
        current = await get_provider_refresh_policy(
            session,
            provider_dataset_id=provider_dataset_id,
        )
        if (
            current is not None
            and expected_revision == current.revision
            and source_kind != current.source_kind
        ):
            raise ProviderRefreshPolicySourceKindImmutable(
                requested_source_kind=source_kind,
                current=current,
            )
        if (
            current is not None
            and expected_revision == current.revision == _BIGINT_MAX
        ):
            raise ProviderRefreshPolicyRevisionExhausted(current=current)
        raise ProviderRefreshPolicyRevisionConflict(
            expected_revision=expected_revision,
            current=current,
        )
    policy = await get_provider_refresh_policy(
        session,
        provider_dataset_id=provider_dataset_id,
    )
    if policy is None:
        raise AssertionError("provider refresh policy write disappeared")
    return policy


async def get_provider_refresh_policy(
    session: AsyncSession,
    *,
    provider_dataset_id: int,
) -> ProviderRefreshPolicy | None:
    """정책 row 1건 조회. 없으면 ``None``."""
    row = (
        await session.execute(
            text(_GET_SQL),
            {"provider_dataset_id": provider_dataset_id},
        )
    ).one_or_none()
    return _row_to_policy(row) if row is not None else None


async def list_provider_refresh_policies(
    session: AsyncSession,
    *,
    provider_dataset_id: int | None = None,
    enabled: bool | None = None,
    limit: int = 200,
) -> tuple[ProviderRefreshPolicy, ...]:
    """정책 목록 조회. API pagination은 후속 admin 라우터에서 cursor로 감싼다."""
    safe_limit = max(1, min(limit, _MAX_LIST_LIMIT))
    rows = (
        await session.execute(
            text(_LIST_SQL),
            {
                "provider_dataset_id": provider_dataset_id,
                "enabled": enabled,
                "limit": safe_limit,
            },
        )
    ).all()
    return tuple(_row_to_policy(row) for row in rows)


async def list_all_provider_refresh_policies(
    session: AsyncSession,
) -> tuple[ProviderRefreshPolicy, ...]:
    """datasets grid 조립용으로 정책을 silent limit 없이 전량 반환한다."""
    rows = (await session.execute(text(_LIST_ALL_SQL))).all()
    return tuple(_row_to_policy(row) for row in rows)
