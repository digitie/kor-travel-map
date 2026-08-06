"""``infra.dataset_status_repo`` (ADR-064 T-ADM-C2) 단위 테스트."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast

import pytest

from kortravelmap.infra import dataset_status_repo
from kortravelmap.infra.dataset_status_repo import (
    DatasetExecutionSnapshot,
    DatasetIntegrityIssueCount,
    DatasetLatestExecution,
    count_open_integrity_issues_by_dataset,
    list_dataset_execution_snapshots,
    list_latest_dataset_executions,
)
from kortravelmap.infra.pipeline_repo import (
    PipelineDatasetExecutionSnapshot,
    PipelineDatasetLatestExecution,
    PipelineExecution,
    PipelineProjectedJob,
)


class _Result:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return self._rows


class _Session:
    def __init__(self, *results: _Result) -> None:
        self._results = list(results)
        self.params: list[dict[str, Any]] = []

    async def execute(self, _statement: Any, params: dict[str, Any] | None = None) -> _Result:
        self.params.append(dict(params or {}))
        return self._results.pop(0)


def _count_row(
    provider_dataset_id: int,
    provider: str,
    dataset_key: str,
    *,
    open_total: int,
    by_severity: dict[str, int],
) -> SimpleNamespace:
    return SimpleNamespace(
        provider_dataset_id=provider_dataset_id,
        provider=provider,
        dataset_key=dataset_key,
        open_total=open_total,
        # asyncpg가 jsonb를 str로 돌려주는 경로를 함께 검증한다.
        by_severity=json.dumps(by_severity),
    )


def _pipeline_execution(*, at: datetime) -> PipelineExecution:
    return PipelineExecution(
        kind="update_request",
        id="11111111-1111-1111-1111-111111111111",
        status="running",
        created_at=at,
        provider_datasets=(),
        progress=None,
        current_stage=None,
        scope_type="provider_dataset",
        priority=50,
        run_mode="queued",
        operator=None,
        error_message=None,
        started_at=at,
        finished_at=None,
        dagster_run_id="run-1",
        dagster_run_status=None,
        trigger_kind="update_request",
        operation_key=None,
        requested_job_id="22222222-2222-2222-2222-222222222222",
        linked_job_count=1,
        projected_job=PipelineProjectedJob(
            id="22222222-2222-2222-2222-222222222222",
            job_kind="feature_update_request",
            status="running",
            progress=0,
            current_stage=None,
            error_message=None,
            created_at=at,
            started_at=at,
            finished_at=None,
            dagster_run_id="run-1",
            dagster_run_status=None,
            trigger_kind="update_request",
            operation_key=None,
            load_batch_id=None,
            parent_job_id=None,
            depth=0,
        ),
    )


@pytest.mark.unit
async def test_count_open_issues_by_dataset_maps_rows_and_defaults() -> None:
    session = _Session(
        _Result(
            [
                _count_row(
                    42,
                    "python-mois-api",
                    "mois_license_features_bulk",
                    open_total=3,
                    by_severity={"error": 2, "warning": 1},
                ),
            ]
        )
    )
    db = cast(Any, session)

    counts = await count_open_integrity_issues_by_dataset(db)

    assert session.params == [{"provider_dataset_id": None}]
    assert counts == (
        DatasetIntegrityIssueCount(
            provider_dataset_id=42,
            provider="python-mois-api",
            dataset_key="mois_license_features_bulk",
            open_total=3,
            by_severity={"error": 2, "warning": 1},
        ),
    )


@pytest.mark.unit
async def test_count_open_issues_passes_canonical_dataset_filter() -> None:
    session = _Session(_Result([]))
    db = cast(Any, session)

    counts = await count_open_integrity_issues_by_dataset(
        db,
        provider_dataset_id=42,
    )

    assert counts == ()
    assert session.params == [
        {
            "provider_dataset_id": 42,
        }
    ]


def test_open_issue_query_projects_display_only_from_canonical_dataset_fk() -> None:
    sql = dataset_status_repo._COUNT_OPEN_ISSUES_SQL

    assert "violation.provider_dataset_id" in sql
    assert "JOIN provider_sync.provider_datasets AS dataset" in sql
    assert "dataset.provider" in sql
    assert "dataset.dataset_key" in sql
    assert "violation.provider," not in sql
    assert "violation.dataset_key," not in sql


@pytest.mark.unit
async def test_list_latest_dataset_executions_maps_common_projection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    at = datetime(2026, 7, 15, tzinfo=UTC)
    session = _Session()
    projected = PipelineDatasetLatestExecution(
        provider_dataset_id=42,
        provider="python-mois-api",
        dataset_key="mois_license_features_bulk",
        sync_scope="dataset_wide",
        execution=_pipeline_execution(at=at),
        operation_member_id="22222222-2222-2222-2222-222222222222",
        pair_status="running",
    )

    async def _latest(_session: Any) -> tuple[PipelineDatasetLatestExecution, ...]:
        return (projected,)

    monkeypatch.setattr(
        dataset_status_repo,
        "list_latest_dataset_pipeline_executions",
        _latest,
    )

    executions = await list_latest_dataset_executions(cast(Any, session))

    assert session.params == []
    assert executions == (
        DatasetLatestExecution(
            provider_dataset_id=42,
            provider="python-mois-api",
            dataset_key="mois_license_features_bulk",
            sync_scope="dataset_wide",
            execution=projected.execution,
            operation_member_id="22222222-2222-2222-2222-222222222222",
            pair_status="running",
        ),
    )


@pytest.mark.unit
async def test_list_dataset_execution_snapshots_maps_both_status_groups(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    at = datetime(2026, 7, 15, tzinfo=UTC)
    session = _Session()
    terminal = PipelineDatasetLatestExecution(
        provider_dataset_id=42,
        provider="python-mois-api",
        dataset_key="mois_license_features_bulk",
        sync_scope="dataset_wide",
        execution=_pipeline_execution(at=at),
        operation_member_id="22222222-2222-2222-2222-222222222222",
        pair_status="done",
    )
    active = PipelineDatasetLatestExecution(
        provider_dataset_id=terminal.provider_dataset_id,
        provider=terminal.provider,
        dataset_key=terminal.dataset_key,
        sync_scope=terminal.sync_scope,
        execution=terminal.execution,
        operation_member_id=terminal.operation_member_id,
        pair_status="running",
    )
    projected = PipelineDatasetExecutionSnapshot(
        provider_dataset_id=terminal.provider_dataset_id,
        provider=terminal.provider,
        dataset_key=terminal.dataset_key,
        sync_scope=terminal.sync_scope,
        latest_terminal=terminal,
        active=active,
    )

    async def _snapshots(_session: Any) -> tuple[PipelineDatasetExecutionSnapshot, ...]:
        return (projected,)

    monkeypatch.setattr(
        dataset_status_repo,
        "list_dataset_pipeline_execution_snapshots",
        _snapshots,
    )

    snapshots = await list_dataset_execution_snapshots(cast(Any, session))

    assert snapshots == (
        DatasetExecutionSnapshot(
            provider_dataset_id=terminal.provider_dataset_id,
            provider=terminal.provider,
            dataset_key=terminal.dataset_key,
            sync_scope=terminal.sync_scope,
            latest_terminal=DatasetLatestExecution(
                provider_dataset_id=terminal.provider_dataset_id,
                provider=terminal.provider,
                dataset_key=terminal.dataset_key,
                sync_scope=terminal.sync_scope,
                execution=terminal.execution,
                operation_member_id=terminal.operation_member_id,
                pair_status="done",
            ),
            active=DatasetLatestExecution(
                provider_dataset_id=active.provider_dataset_id,
                provider=active.provider,
                dataset_key=active.dataset_key,
                sync_scope=active.sync_scope,
                execution=active.execution,
                operation_member_id=active.operation_member_id,
                pair_status="running",
            ),
        ),
    )


@pytest.mark.unit
async def test_scoped_snapshot_forwards_canonical_dataset_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _Session()
    projected = PipelineDatasetExecutionSnapshot(
        provider_dataset_id=42,
        provider="python-mois-api",
        dataset_key="mois_license_features_bulk",
        sync_scope="dataset_wide",
        latest_terminal=None,
        active=None,
    )
    observed: list[int] = []

    async def _scoped(
        _session: Any,
        *,
        provider_dataset_id: int,
    ) -> tuple[PipelineDatasetExecutionSnapshot, ...]:
        observed.append(provider_dataset_id)
        return (projected,)

    monkeypatch.setattr(
        dataset_status_repo,
        "list_dataset_pipeline_execution_snapshots_scoped",
        _scoped,
    )

    snapshots = await dataset_status_repo.list_dataset_execution_snapshots_scoped(
        cast(Any, session),
        provider_dataset_id=42,
    )

    assert observed == [42]
    assert snapshots == (
        DatasetExecutionSnapshot(
            provider_dataset_id=42,
            provider="python-mois-api",
            dataset_key="mois_license_features_bulk",
            sync_scope="dataset_wide",
            latest_terminal=None,
            active=None,
        ),
    )
