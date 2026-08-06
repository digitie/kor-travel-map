"""``provider_refresh_policy_repo`` datasets grid 전량 조회 회귀 (#678)."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast

import pytest

from kortravelmap.infra.provider_refresh_policy_repo import (
    list_all_provider_refresh_policies,
    upsert_provider_refresh_policy,
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


class _OneResult:
    def __init__(self, row: SimpleNamespace) -> None:
        self._row = row

    def one_or_none(self) -> SimpleNamespace:
        return self._row


class _UpsertSession:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def execute(
        self,
        statement: Any,
        params: dict[str, Any],
    ) -> _OneResult:
        self.calls.append((str(statement), params))
        return _OneResult(_row(0))


def _row(index: int) -> SimpleNamespace:
    now = datetime(2026, 7, 15, tzinfo=UTC)
    return SimpleNamespace(
        provider_dataset_id=index + 1,
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
        revision=index + 1,
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


@pytest.mark.unit
async def test_upsert_distinguishes_omitted_and_explicit_provenance() -> None:
    session = _UpsertSession()

    await upsert_provider_refresh_policy(
        cast(Any, session),
        provider_dataset_id=1,
        source_kind="openapi",
        expected_revision=None,
    )
    await upsert_provider_refresh_policy(
        cast(Any, session),
        provider_dataset_id=1,
        source_kind="openapi",
        expected_revision=1,
        rate_limit_source={},
    )

    insert_sql, omitted_params = session.calls[0]
    update_sql, explicit_params = session.calls[2]
    assert "ON CONFLICT (provider_dataset_id) DO NOTHING" in insert_sql
    assert "provider_dataset_id" in update_sql
    assert "policy.revision = CAST(:expected_revision AS bigint)" in update_sql
    assert "revision = policy.revision + 1" in update_sql
    assert "policy.revision < 9223372036854775807" in update_sql
    assert "policy.source_kind = :source_kind" in update_sql
    assert "SET source_kind" not in update_sql
    assert "ELSE policy.rate_limit_source" in update_sql
    assert omitted_params["rate_limit_source"] == "{}"
    assert omitted_params["provider_dataset_id"] == 1
    assert omitted_params["rate_limit_source_provided"] is False
    assert explicit_params["rate_limit_source"] == "{}"
    assert explicit_params["rate_limit_source_provided"] is True
