"""``provider_refresh_policy_repo`` datasets grid 전량 조회 회귀 (#678)."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast

import pytest

from kortravelmap.infra.provider_refresh_policy_repo import (
    list_all_provider_refresh_policies,
)


class _Result:
    def __init__(self, rows: list[SimpleNamespace]) -> None:
        self._rows = rows

    def all(self) -> list[SimpleNamespace]:
        return self._rows


class _Session:
    def __init__(self, rows: list[SimpleNamespace]) -> None:
        self.rows = rows
        self.calls = 0

    async def execute(self, _statement: Any) -> _Result:
        self.calls += 1
        return _Result(self.rows)


def _row(index: int) -> SimpleNamespace:
    now = datetime(2026, 7, 15, tzinfo=UTC)
    return SimpleNamespace(
        provider=f"provider-{index:03d}",
        dataset_key=f"dataset-{index:03d}",
        source_kind="openapi",
        targeted_policy="follow_system",
        system_interval_seconds=None,
        optimal_interval_seconds=None,
        min_interval_seconds=None,
        stale_after_minutes=None,
        max_requests_per_minute=None,
        max_requests_per_hour=None,
        max_requests_per_day=None,
        max_concurrent=1,
        burst_size=None,
        rate_limit_source={},
        config_source="db",
        enabled=True,
        created_at=now,
        updated_at=now,
    )


@pytest.mark.unit
async def test_list_all_policies_does_not_apply_admin_list_limit() -> None:
    session = _Session([_row(index) for index in range(501)])

    policies = await list_all_provider_refresh_policies(cast(Any, session))

    assert len(policies) == 501
    assert policies[-1].provider == "provider-500"
    assert session.calls == 1
