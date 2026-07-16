"""``infra.dataset_status_repo`` (ADR-064 T-ADM-C2) 단위 테스트."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast

import pytest

from kortravelmap.infra import dataset_status_repo
from kortravelmap.infra.dataset_status_repo import (
    DatasetIntegrityIssueCount,
    DatasetLatestExecution,
    count_open_integrity_issues_by_dataset,
    list_latest_dataset_executions,
)
from kortravelmap.infra.pipeline_repo import (
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
    provider: str,
    dataset_key: str | None,
    *,
    open_total: int,
    by_severity: dict[str, int],
) -> SimpleNamespace:
    return SimpleNamespace(
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
        providers=("python-mois-api",),
        dataset_keys=("mois_license_features_bulk",),
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
        operation_registry_version=None,
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
            operation_registry_version=None,
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
                    "python-mois-api",
                    "mois_license_features_bulk",
                    open_total=3,
                    by_severity={"error": 2, "warning": 1},
                ),
                _count_row(
                    "python-krex-api",
                    None,
                    open_total=1,
                    by_severity={"warning": 1},
                ),
            ]
        )
    )
    db = cast(Any, session)

    counts = await count_open_integrity_issues_by_dataset(db)

    assert session.params == [{"provider": None, "dataset_key": None}]
    assert counts == (
        DatasetIntegrityIssueCount(
            provider="python-mois-api",
            dataset_key="mois_license_features_bulk",
            open_total=3,
            by_severity={"error": 2, "warning": 1},
        ),
        DatasetIntegrityIssueCount(
            provider="python-krex-api",
            dataset_key=None,
            open_total=1,
            by_severity={"warning": 1},
        ),
    )


@pytest.mark.unit
async def test_count_open_issues_passes_filters() -> None:
    session = _Session(_Result([]))
    db = cast(Any, session)

    counts = await count_open_integrity_issues_by_dataset(
        db,
        provider="python-mois-api",
        dataset_key="mois_license_features_bulk",
    )

    assert counts == ()
    assert session.params == [
        {
            "provider": "python-mois-api",
            "dataset_key": "mois_license_features_bulk",
        }
    ]


@pytest.mark.unit
async def test_list_latest_dataset_executions_maps_common_projection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    at = datetime(2026, 7, 15, tzinfo=UTC)
    session = _Session()
    projected = PipelineDatasetLatestExecution(
        provider="python-mois-api",
        dataset_key="mois_license_features_bulk",
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
            provider="python-mois-api",
            dataset_key="mois_license_features_bulk",
            execution=projected.execution,
            operation_member_id="22222222-2222-2222-2222-222222222222",
            pair_status="running",
        ),
    )
