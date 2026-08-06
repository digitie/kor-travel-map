"""Dagster execution guard의 canonical operation membership 회귀."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

from kortravelmap.core.feature_operation import ProviderDatasetOperationMembership

from kortravelmap.dagster.feature_operation_tracking import (
    FeatureOperationExecutionGuard,
    _guard_from_context_async,
    run_tracked_feature_asset,
)


class _Client:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.memberships = (
            ProviderDatasetOperationMembership(
                provider_dataset_id=41,
                sync_scope="dataset_wide",
                operation_key="feature_place_mcst_culture_job",
            ),
        )

    async def ensure_dagster_feature_operation(self, **kwargs: Any) -> Any:
        self.calls.append(("ensure", kwargs))
        return SimpleNamespace(outcome="applied", block_reason=None)

    async def finish_dagster_feature_membership(self, **kwargs: Any) -> Any:
        self.calls.append(("finish", kwargs))
        return SimpleNamespace(outcome="applied", block_reason=None)

    async def append_dagster_feature_attempt_event(self, **kwargs: Any) -> None:
        self.calls.append(("attempt", kwargs))

    async def resolve_feature_operation_memberships(self, **kwargs: Any) -> Any:
        self.calls.append(("memberships", kwargs))
        return self.memberships


class _Instance:
    def __init__(self, run: Any) -> None:
        self.run = run

    def get_run_record_by_id(self, run_id: str) -> Any:
        assert run_id == self.run.run_id
        return SimpleNamespace(
            dagster_run=self.run,
            create_timestamp=datetime(2026, 8, 1, tzinfo=UTC),
            start_time=datetime(2026, 8, 1, 1, tzinfo=UTC).timestamp(),
        )


def _run(*, tagged: bool = True) -> Any:
    tags = (
        {
            "kor_travel_map.operation_key": "feature_place_mcst_culture_job",
            "kor_travel_map.trigger_kind": "schedule",
        }
        if tagged
        else {}
    )
    return SimpleNamespace(
        run_id="run-41",
        job_name="feature_place_mcst_culture_job",
        tags=tags,
        status=SimpleNamespace(value="STARTED"),
    )


def _guard(client: _Client) -> FeatureOperationExecutionGuard:
    run = _run()
    return FeatureOperationExecutionGuard(
        client=client,  # type: ignore[arg-type]
        instance=_Instance(run),
        operation_key="feature_place_mcst_culture_job",
        memberships=client.memberships,
        dagster_run_id=run.run_id,
        trigger_kind="schedule",
    )


def test_guard_ensures_frozen_memberships_with_operation_key() -> None:
    client = _Client()
    guard = _guard(client)

    asyncio.run(guard.ensure())

    name, call = client.calls[0]
    assert name == "ensure"
    assert call["operation_key"] == "feature_place_mcst_culture_job"
    assert call["selected_memberships"] == client.memberships


def test_single_member_wrapper_finishes_canonical_membership() -> None:
    client = _Client()
    guard = _guard(client)
    context = SimpleNamespace(
        resources=SimpleNamespace(feature_operation_guard=guard, kor_travel_map_client=client),
        instance=guard.instance,
        run=guard.instance.run,
        retry_number=0,
    )

    result = asyncio.run(run_tracked_feature_asset(context, lambda _context: _result()))

    assert result == "loaded"
    assert client.calls[-1] == (
        "finish",
        {"dagster_run_id": "run-41", "membership": client.memberships[0]},
    )


async def _result() -> str:
    return "loaded"


def test_resource_guard_loads_enabled_memberships_from_database() -> None:
    client = _Client()
    run = _run()
    context = SimpleNamespace(
        run=run,
        instance=_Instance(run),
        resources=SimpleNamespace(kor_travel_map_client=client),
    )

    guard = asyncio.run(_guard_from_context_async(context))

    assert guard.operation_key == "feature_place_mcst_culture_job"
    assert guard.memberships == client.memberships
    assert client.calls == [("memberships", {"operation_key": "feature_place_mcst_culture_job"})]


def test_untagged_run_remains_panel_only_without_database_lookup() -> None:
    client = _Client()
    run = _run(tagged=False)
    context = SimpleNamespace(
        run=run,
        instance=_Instance(run),
        resources=SimpleNamespace(kor_travel_map_client=client),
    )

    guard = asyncio.run(_guard_from_context_async(context))

    assert guard.operation_key is None
    assert guard.memberships == ()
    assert client.calls == []
