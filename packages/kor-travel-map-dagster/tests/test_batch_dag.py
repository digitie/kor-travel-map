"""T-200 batch DAG consistency gate Dagster job unit test."""

from __future__ import annotations

from typing import Any

import pytest
from kortravelmap.infra.batch_dag import BatchDagRunResult
from kortravelmap.infra.consistency import ConsistencyReport
from kortravelmap.infra.jobs_repo import ImportJob

from kortravelmap.dagster.batch_dag import full_load_batch_consistency_gate_job

pytestmark = pytest.mark.filterwarnings(
    "ignore:Parameter `owners` of initializer `SensorDefinition.__init__`"
    ".*:dagster_shared.utils.warnings.BetaWarning"
)


class _Client:
    def __init__(self, result: BatchDagRunResult) -> None:
        self.result = result
        self.calls: list[dict[str, Any]] = []

    async def run_batch_dag_consistency_gate(
        self,
        **kwargs: Any,
    ) -> BatchDagRunResult:
        self.calls.append(kwargs)
        return self.result


def test_full_load_batch_consistency_gate_job_executes_client() -> None:
    client = _Client(_result(state="done"))

    result = full_load_batch_consistency_gate_job.execute_in_process(
        run_config={
            "ops": {
                "run_full_load_batch_consistency_gate": {
                    "config": {
                        "child_job_ids": [
                            "10000000-0000-0000-0000-000000000001"
                        ],
                        "load_batch_id": "20000000-0000-0000-0000-000000000001",
                        "root_payload": {"source": "pytest"},
                        "persist": False,
                        "sample_limit": 7,
                        "dedup_pending_threshold": 2,
                        "materialized_views": ["feature.search_mv"],
                        "mv_refresh_strategy": "refresh",
                    }
                }
            }
        },
        resources={"kor_travel_map_client": client},
    )

    assert result.success
    assert client.calls[0]["child_job_ids"] == (
        "10000000-0000-0000-0000-000000000001",
    )
    assert client.calls[0]["load_batch_id"] == "20000000-0000-0000-0000-000000000001"
    assert client.calls[0]["root_payload"] == {"source": "pytest"}
    assert client.calls[0]["consistency_persist"] is False
    assert client.calls[0]["sample_limit"] == 7
    assert client.calls[0]["dedup_pending_threshold"] == 2
    assert client.calls[0]["materialized_views"] == ("feature.search_mv",)
    assert client.calls[0]["mv_refresh_strategy"] == "refresh"

    output = result.output_for_node("run_full_load_batch_consistency_gate")
    assert output["state"] == "done"
    assert output["consistency_severity_max"] == "OK"


def test_full_load_batch_consistency_gate_job_fails_on_blocked_gate() -> None:
    client = _Client(
        _result(
            state="failed",
            blocked_by_gate=True,
            error_message="consistency gate blocked mv_refresh: severity_max=ERROR",
        )
    )

    result = full_load_batch_consistency_gate_job.execute_in_process(
        resources={"kor_travel_map_client": client},
        raise_on_error=False,
    )

    assert not result.success
    assert client.calls[0]["mv_refresh_strategy"] == "swap"


def _result(
    *,
    state: str,
    blocked_by_gate: bool = False,
    error_message: str | None = None,
) -> BatchDagRunResult:
    return BatchDagRunResult(
        load_batch_id="20000000-0000-0000-0000-000000000001",
        state=state,
        root_job=_job("00000000-0000-0000-0000-000000000001", "full_load_batch"),
        child_jobs=(
            _job("10000000-0000-0000-0000-000000000001", "offline_upload_load"),
        ),
        consistency_job=_job(
            "30000000-0000-0000-0000-000000000001", "consistency_check"
        ),
        mv_refresh_job=(
            _job("40000000-0000-0000-0000-000000000001", "mv_refresh")
            if state == "done"
            else None
        ),
        consistency_report=ConsistencyReport(
            batch_id="20000000-0000-0000-0000-000000000001",
            severity_max="ERROR" if blocked_by_gate else "OK",
            cases=[],
            summary={
                "total_violations": 1 if blocked_by_gate else 0,
                "cases_evaluated": 4,
                "by_code": {},
            },
        ),
        blocked_by_gate=blocked_by_gate,
        error_message=error_message,
    )


def _job(job_id: str, kind: str) -> ImportJob:
    return ImportJob(
        job_id=job_id,
        kind=kind,
        payload={},
        status="done",
        progress=100,
        current_stage=None,
        source_checksum=None,
        error_message=None,
        load_batch_id="20000000-0000-0000-0000-000000000001",
        parent_job_id=None,
    )
