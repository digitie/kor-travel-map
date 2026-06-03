"""``infra.ops_repo`` read-only helper unit tests."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast

import pytest

from krtour.map.infra.ops_repo import (
    OpsConsistencyReport,
    OpsImportJob,
    OpsIntegrityIssue,
    get_latest_consistency_report,
    get_ops_import_job,
    get_ops_integrity_issue_counts,
    list_ops_consistency_reports,
    list_ops_import_jobs,
    list_ops_integrity_issues,
)


class _Result:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return self._rows

    def one(self) -> Any:
        return self._rows[0]

    def one_or_none(self) -> Any | None:
        return self._rows[0] if self._rows else None


class _Session:
    def __init__(self, *results: _Result) -> None:
        self._results = list(results)
        self.params: list[dict[str, Any]] = []

    async def execute(self, _statement: Any, params: dict[str, Any] | None = None) -> _Result:
        self.params.append(dict(params or {}))
        return self._results.pop(0)


def _job_row(job_id: str, *, at: datetime) -> SimpleNamespace:
    return SimpleNamespace(
        job_id=job_id,
        kind="feature_update_request",
        payload='{"request_id":"req-1"}',
        state="running",
        progress=42,
        current_stage="loading",
        source_checksum=None,
        error_message=None,
        created_at=at,
        started_at=at,
        finished_at=None,
        heartbeat_at=at,
    )


def _report_row(report_id: str, *, at: datetime) -> SimpleNamespace:
    return SimpleNamespace(
        report_id=report_id,
        batch_id="33333333-3333-3333-3333-333333333333",
        started_at=at,
        finished_at=at,
        severity_max="WARN",
        cases='[{"code":"F4","count":3}]',
        summary='{"total_violations":3}',
    )


def _issue_row(key: str, *, at: datetime) -> SimpleNamespace:
    return SimpleNamespace(
        violation_key=key,
        provider="python-mois-api",
        dataset_key="mois_license_features_bulk",
        source_record_key=None,
        feature_id="feature-1",
        violation_type="missing_coordinate",
        severity="error",
        message="좌표 없음",
        payload='{"source":"unit"}',
        status="open",
        detected_at=at,
        resolved_at=None,
    )


@pytest.mark.unit
async def test_import_job_list_detail_and_cursor() -> None:
    at = datetime(2026, 6, 3, tzinfo=UTC)
    session = _Session(
        _Result(
            [
                _job_row("11111111-1111-1111-1111-111111111111", at=at),
                _job_row("22222222-2222-2222-2222-222222222222", at=at),
            ]
        ),
        _Result([_job_row("11111111-1111-1111-1111-111111111111", at=at)]),
        _Result([_job_row("11111111-1111-1111-1111-111111111111", at=at)]),
    )
    db = cast(Any, session)

    page = await list_ops_import_jobs(
        db, state="running", kind="feature_update_request", limit=1
    )
    assert len(page.items) == 1
    assert isinstance(page.items[0], OpsImportJob)
    assert page.items[0].payload == {"request_id": "req-1"}
    assert page.next_cursor is not None

    page2 = await list_ops_import_jobs(db, limit=1, cursor=page.next_cursor)
    assert session.params[1]["cursor_created_at"] == at
    assert session.params[1]["cursor_job_id"] == "11111111-1111-1111-1111-111111111111"
    assert len(page2.items) == 1

    loaded = await get_ops_import_job(
        db, "11111111-1111-1111-1111-111111111111"
    )
    assert loaded is not None
    assert loaded.current_stage == "loading"


@pytest.mark.unit
async def test_invalid_cursor_rejected() -> None:
    session = _Session()
    db = cast(Any, session)
    with pytest.raises(ValueError, match="invalid import_jobs cursor"):
        await list_ops_import_jobs(db, cursor="not-base64")


@pytest.mark.unit
async def test_consistency_reports_list_and_latest() -> None:
    at = datetime(2026, 6, 3, tzinfo=UTC)
    session = _Session(
        _Result(
            [
                _report_row("11111111-1111-1111-1111-111111111111", at=at),
                _report_row("22222222-2222-2222-2222-222222222222", at=at),
            ]
        ),
        _Result([_report_row("11111111-1111-1111-1111-111111111111", at=at)]),
    )
    db = cast(Any, session)

    page = await list_ops_consistency_reports(db, severity_max="WARN", limit=1)
    assert isinstance(page.items[0], OpsConsistencyReport)
    assert page.items[0].cases == [{"code": "F4", "count": 3}]
    assert page.items[0].summary == {"total_violations": 3}
    assert page.next_cursor is not None

    latest = await get_latest_consistency_report(db)
    assert latest is not None
    assert latest.severity_max == "WARN"


@pytest.mark.unit
async def test_integrity_issues_list_and_counts() -> None:
    at = datetime(2026, 6, 3, tzinfo=UTC)
    session = _Session(
        _Result(
            [
                _issue_row("11111111-1111-1111-1111-111111111111", at=at),
                _issue_row("22222222-2222-2222-2222-222222222222", at=at),
            ]
        ),
        _Result(
            [
                SimpleNamespace(
                    by_status={"open": 2},
                    by_severity={"error": 2},
                    by_type={"missing_coordinate": 2},
                    open_total=2,
                )
            ]
        ),
    )
    db = cast(Any, session)

    page = await list_ops_integrity_issues(
        db,
        status="open",
        severity="error",
        violation_type="missing_coordinate",
        provider="python-mois-api",
        dataset_key="mois_license_features_bulk",
        feature_id="feature-1",
        limit=1,
    )
    assert isinstance(page.items[0], OpsIntegrityIssue)
    assert page.items[0].payload == {"source": "unit"}
    assert page.next_cursor is not None

    counts = await get_ops_integrity_issue_counts(db)
    assert counts.open_total == 2
    assert counts.by_status == {"open": 2}
    assert counts.by_severity == {"error": 2}
    assert counts.by_type == {"missing_coordinate": 2}
