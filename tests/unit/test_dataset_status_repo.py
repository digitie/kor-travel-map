"""``infra.dataset_status_repo`` (ADR-064 T-ADM-C2) 단위 테스트."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast

import pytest

from kortravelmap.infra.dataset_status_repo import (
    DatasetIntegrityIssueCount,
    count_open_integrity_issues_by_dataset,
    list_ops_import_jobs_by_ids,
)
from kortravelmap.infra.ops_repo import OpsImportJob


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


def _job_row(job_id: str, *, at: datetime) -> SimpleNamespace:
    return SimpleNamespace(
        job_id=job_id,
        kind="feature_update_request",
        load_batch_id=None,
        parent_job_id=None,
        payload='{"request_id":"req-1"}',
        status="done",
        progress=100,
        current_stage="loading",
        source_checksum=None,
        error_message=None,
        created_at=at,
        started_at=at,
        finished_at=at,
        heartbeat_at=at,
        dagster_run_id="run-1",
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
async def test_list_jobs_by_ids_empty_input_skips_db() -> None:
    session = _Session()
    db = cast(Any, session)

    assert await list_ops_import_jobs_by_ids(db, []) == ()
    # 빈/falsy id만 있는 입력도 DB를 치지 않는다.
    assert await list_ops_import_jobs_by_ids(db, [""]) == ()
    assert session.params == []


@pytest.mark.unit
async def test_list_jobs_by_ids_dedupes_and_maps_rows() -> None:
    at = datetime(2026, 7, 14, tzinfo=UTC)
    session = _Session(
        _Result([_job_row("11111111-1111-1111-1111-111111111111", at=at)])
    )
    db = cast(Any, session)

    jobs = await list_ops_import_jobs_by_ids(
        db,
        [
            "22222222-2222-2222-2222-222222222222",
            "11111111-1111-1111-1111-111111111111",
            "11111111-1111-1111-1111-111111111111",
        ],
    )

    # 중복 제거 + 정렬된 jsonb 텍스트 배열로 바인딩한다.
    assert session.params[0]["job_ids"] == json.dumps(
        [
            "11111111-1111-1111-1111-111111111111",
            "22222222-2222-2222-2222-222222222222",
        ]
    )
    assert len(jobs) == 1
    job = jobs[0]
    assert isinstance(job, OpsImportJob)
    assert job.job_id == "11111111-1111-1111-1111-111111111111"
    assert job.payload == {"request_id": "req-1"}
    assert job.status == "done"
    assert job.progress == 100
    assert job.created_at == at
    # ADR-064: datasets 상세의 최근 실행 요약에 dagster_run_id 실컬럼이 흘러야 한다.
    assert job.dagster_run_id == "run-1"
