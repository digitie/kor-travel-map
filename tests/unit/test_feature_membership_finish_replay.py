"""공개 finish 후속 호출과 정상 root 완료 경합의 직접 회귀."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from kortravelmap.core.feature_operation import (
    DagsterFeatureOperation,
    DagsterFeatureOperationMember,
    FeatureOperationInvariantConflict,
    ProviderDatasetOperationMembership,
)
from kortravelmap.infra import feature_operation_repo as repo


def _operation() -> DagsterFeatureOperation:
    now = datetime(2026, 10, 25, tzinfo=UTC)
    member = DagsterFeatureOperationMember(
        job_id=str(uuid4()),
        import_job_dataset_id=str(uuid4()),
        membership=ProviderDatasetOperationMembership(7, "dataset_wide", "feature_probe_job"),
        status="done",
        progress=100,
        current_stage="completed",
        started_at=now,
        finished_at=now,
    )
    return DagsterFeatureOperation(
        root_job_id=str(uuid4()),
        dagster_run_id="finish-replay",
        status="done",
        dagster_run_status="SUCCESS",
        progress=100,
        current_stage="completed",
        created_at=now,
        started_at=now,
        finished_at=now,
        trigger_kind="manual",
        operation_key="feature_probe_job",
        members=(member,),
    )


class _Session:
    def __init__(
        self, operation: DagsterFeatureOperation, *, cancelled: bool = False, safe: bool = True
    ) -> None:
        self.operation = operation
        self.cancelled = cancelled
        self.safe = safe
        self.statements: list[tuple[str, dict[str, Any]]] = []

    async def execute(self, statement: Any, params: dict[str, Any]) -> Any:
        sql = str(statement)
        self.statements.append((sql, params))
        assert sql == repo._LOCK_ROOT_BY_RUN_SQL  # DML나 seal 호출은 이 fixture에서 즉시 실패한다.
        root = SimpleNamespace(
            root_job_id=self.operation.root_job_id,
            root_cancellation_id=uuid4() if self.cancelled else None,
        )
        return SimpleNamespace(one_or_none=lambda: root)

    async def scalar(self, statement: Any, params: dict[str, Any]) -> bool:
        self.statements.append((str(statement), params))
        return self.safe


def _locks_and_read(
    monkeypatch: pytest.MonkeyPatch, operation: DagsterFeatureOperation
) -> list[str]:
    order: list[str] = []

    async def lock(_session: Any, **kwargs: Any) -> None:
        order.append("root" if kwargs else "prefix")

    monkeypatch.setattr(repo, "lock_provider_feature_finalization", lock)
    monkeypatch.setattr(repo, "lock_pipeline_lineage_mutation", lock)
    monkeypatch.setattr(repo, "lock_pipeline_cancellation_root", lock)
    monkeypatch.setattr(repo, "_load_operation", AsyncMock(return_value=operation))
    return order


async def test_successful_root_after_child_finish_is_read_only_noop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """entry guard 뒤 다른 worker의 child seal/root SUCCESS를 관측한 상태다."""
    operation = _operation()
    order = _locks_and_read(monkeypatch, operation)
    session = _Session(operation)
    result = await repo.finish_dagster_feature_membership(
        session,  # type: ignore[arg-type]
        dagster_run_id=operation.dagster_run_id,
        membership=operation.members[0].membership,
        authoritative_snapshot_complete=True,
    )
    assert result.outcome == "noop"
    assert result.operation is operation
    assert order == ["prefix", "prefix", "root"]
    assert len(session.statements) == 2
    assert session.statements[1][1] == {
        "root_job_id": operation.root_job_id,
        "dagster_run_id": operation.dagster_run_id,
        "member_job_id": operation.members[0].job_id,
        "member_id": operation.members[0].import_job_dataset_id,
        "provider_dataset_id": 7,
        "sync_scope": "dataset_wide",
        "operation_key": "feature_probe_job",
    }


@pytest.mark.parametrize(
    ("status", "engine"),
    [("failed", "FAILURE"), ("cancelled", "CANCELED"), ("done", "STARTED")],
)
async def test_non_success_terminal_root_stays_blocked(
    monkeypatch: pytest.MonkeyPatch, status: Any, engine: Any
) -> None:
    operation = replace(_operation(), status=status, dagster_run_status=engine)
    _locks_and_read(monkeypatch, operation)
    session = _Session(operation)
    result = await repo.finish_dagster_feature_membership(
        session,  # type: ignore[arg-type]
        dagster_run_id=operation.dagster_run_id,
        membership=operation.members[0].membership,
    )
    assert (result.outcome, result.block_reason) == ("blocked", "terminal")
    assert len(session.statements) == 1


async def test_root_cancellation_precedes_completed_member(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operation = _operation()
    _locks_and_read(monkeypatch, operation)
    session = _Session(operation, cancelled=True)
    result = await repo.finish_dagster_feature_membership(
        session,  # type: ignore[arg-type]
        dagster_run_id=operation.dagster_run_id,
        membership=operation.members[0].membership,
    )
    assert (result.outcome, result.block_reason) == ("blocked", "cancellation")
    assert len(session.statements) == 1


async def test_successful_root_cannot_finish_unfinished_child(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operation = _operation()
    operation = replace(operation, members=(replace(operation.members[0], status="running"),))
    _locks_and_read(monkeypatch, operation)
    session = _Session(operation)
    result = await repo.finish_dagster_feature_membership(
        session,  # type: ignore[arg-type]
        dagster_run_id=operation.dagster_run_id,
        membership=operation.members[0].membership,
    )
    assert (result.outcome, result.block_reason) == ("blocked", "terminal")
    assert len(session.statements) == 1


@pytest.mark.parametrize("axis", ["dataset", "scope", "operation"])
async def test_successful_root_requires_frozen_membership(
    monkeypatch: pytest.MonkeyPatch, axis: str
) -> None:
    operation = _operation()
    member = operation.members[0].membership
    foreign = replace(
        member,
        **{
            "dataset": {"provider_dataset_id": 8},
            "scope": {"sync_scope": "target_grids"},
            "operation": {"operation_key": "feature_other_job"},
        }[axis],
    )
    _locks_and_read(monkeypatch, operation)
    session = _Session(operation)
    with pytest.raises(FeatureOperationInvariantConflict, match="frozen run selection"):
        await repo.finish_dagster_feature_membership(
            session,  # type: ignore[arg-type]
            dagster_run_id=operation.dagster_run_id,
            membership=foreign,
        )
    assert len(session.statements) == 1


async def test_unsafe_completion_proof_cannot_become_noop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operation = _operation()
    _locks_and_read(monkeypatch, operation)
    session = _Session(operation, safe=False)
    result = await repo.finish_dagster_feature_membership(
        session,  # type: ignore[arg-type]
        dagster_run_id=operation.dagster_run_id,
        membership=operation.members[0].membership,
    )
    assert (result.outcome, result.block_reason) == ("blocked", "terminal")
    assert len(session.statements) == 2


async def test_running_root_completed_child_preserves_existing_noop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operation = replace(_operation(), status="running", dagster_run_status="STARTED")
    _locks_and_read(monkeypatch, operation)
    session = _Session(operation)
    result = await repo.finish_dagster_feature_membership(
        session,  # type: ignore[arg-type]
        dagster_run_id=operation.dagster_run_id,
        membership=operation.members[0].membership,
    )
    assert result.outcome == "noop"
    assert len(session.statements) == 1
