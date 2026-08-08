"""``infra.ops_repo`` read-only helper unit tests."""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast

import pytest

from kortravelmap.infra import ops_repo
from kortravelmap.infra.ops_repo import (
    OpsConsistencyReport,
    OpsImportJob,
    OpsImportJobEvent,
    OpsIntegrityIssue,
    get_latest_consistency_report,
    get_ops_import_job,
    get_ops_integrity_issue_counts,
    list_ops_consistency_reports,
    list_ops_import_job_events,
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
        self.statements: list[str] = []

    async def execute(self, _statement: Any, params: dict[str, Any] | None = None) -> _Result:
        self.statements.append(str(_statement))
        self.params.append(dict(params or {}))
        return self._results.pop(0)


def _job_row(job_id: str, *, at: datetime) -> SimpleNamespace:
    return SimpleNamespace(
        job_id=job_id,
        kind="feature_update_request",
        load_batch_id="33333333-3333-3333-3333-333333333333",
        parent_job_id="44444444-4444-4444-4444-444444444444",
        update_request_id="22222222-2222-2222-2222-222222222222",
        payload='{"request_id":"req-1"}',
        status="running",
        progress=42,
        current_stage="loading",
        source_checksum=None,
        error_message=None,
        created_at=at,
        started_at=at,
        finished_at=None,
        heartbeat_at=at,
        dagster_run_id="run-1",
        dataset_memberships=json.dumps(
            [
                {
                    "import_job_dataset_id": job_id,
                    "provider_dataset_id": 1,
                    "provider": "python-mois-api",
                    "dataset_key": "mois_license_features_bulk",
                    "sync_scope": "dataset_wide",
                    "operation_key": "feature_place_mois_licenses_job",
                }
            ]
        ),
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


def _event_row(event_id: str, *, at: datetime) -> SimpleNamespace:
    return SimpleNamespace(
        event_id=event_id,
        job_id="11111111-1111-1111-1111-111111111111",
        import_job_dataset_id="11111111-1111-1111-1111-111111111111",
        provider_dataset_id=1,
        sync_scope="dataset_wide",
        operation_key="feature_place_mois_licenses_job",
        feature_id=None,
        stage="loading",
        level="error",
        code="provider.timeout",
        message="provider timeout",
        payload='{"attempt":2}',
        occurred_at=at,
    )


def _issue_row(key: str, *, at: datetime) -> SimpleNamespace:
    return SimpleNamespace(
        issue_id=key,
        provider_dataset_id=42,
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
        last_seen_at=at,
        resolved_at=None,
    )


def _cursor(payload: object) -> str:
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


@pytest.mark.unit
def test_import_job_reads_exclude_quarantined_rows() -> None:
    assert "job.quarantined_at IS NULL" in ops_repo._LIST_IMPORT_JOBS_SQL
    assert "job.quarantined_at IS NULL" in ops_repo._GET_IMPORT_JOB_SQL

    events_sql = ops_repo._list_import_job_events_sql(
        job_id=None,
        level=None,
        provider_dataset_id=None,
        sync_scope=None,
        operation_key=None,
        cursor_occurred_at=None,
    )
    assert "event.quarantined_at IS NULL" in events_sql
    assert "event.sync_scope" not in events_sql
    assert "JOIN LATERAL" not in events_sql
    assert "JOIN ops.import_jobs AS job" not in events_sql
    assert "c6c_cancel_probe" not in events_sql
    assert "ops.feature_update_requests" not in events_sql


@pytest.mark.unit
def test_ops_projection_uses_membership_not_dropped_pair_columns() -> None:
    assert "ops.import_job_datasets AS member" in ops_repo._IMPORT_JOB_MEMBERSHIPS_SQL
    assert "event.import_job_dataset_id" in ops_repo._IMPORT_JOB_EVENT_COLUMNS
    assert "event.provider" not in ops_repo._IMPORT_JOB_EVENT_COLUMNS
    assert "event.dataset_key" not in ops_repo._IMPORT_JOB_EVENT_COLUMNS
    assert "event.sync_scope" not in ops_repo._IMPORT_JOB_EVENT_COLUMNS


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
        db,
        status="running",
        kind="feature_update_request",
        load_batch_id="33333333-3333-3333-3333-333333333333",
        parent_job_id="44444444-4444-4444-4444-444444444444",
        limit=1,
    )
    assert len(page.items) == 1
    assert isinstance(page.items[0], OpsImportJob)
    assert page.items[0].load_batch_id == "33333333-3333-3333-3333-333333333333"
    assert page.items[0].parent_job_id == "44444444-4444-4444-4444-444444444444"
    assert page.items[0].payload == {"request_id": "req-1"}
    assert page.next_cursor is not None

    page2 = await list_ops_import_jobs(db, limit=1, cursor=page.next_cursor)
    assert session.params[0]["load_batch_id"] == "33333333-3333-3333-3333-333333333333"
    assert session.params[0]["parent_job_id"] == "44444444-4444-4444-4444-444444444444"
    assert session.params[1]["cursor_created_at"] == at
    assert session.params[1]["cursor_job_id"] == "11111111-1111-1111-1111-111111111111"
    assert len(page2.items) == 1

    loaded = await get_ops_import_job(
        db, "11111111-1111-1111-1111-111111111111"
    )
    assert loaded is not None
    assert loaded.current_stage == "loading"


@pytest.mark.unit
@pytest.mark.parametrize(
    "cursor",
    [
        "not-base64",
        _cursor(
            {
                "v": 1,
                "kind": "consistency_reports",
                "at": "2026-06-03T00:00:00+00:00",
                "key": "k",
            }
        ),
        _cursor({"v": 1, "kind": "import_jobs", "key": "k"}),
        _cursor({"v": 1, "kind": "import_jobs", "at": "not-datetime", "key": "k"}),
        _cursor(["not", "mapping"]),
    ],
)
async def test_invalid_cursor_rejected(cursor: str) -> None:
    session = _Session()
    db = cast(Any, session)
    with pytest.raises(ValueError, match="invalid import_jobs cursor"):
        await list_ops_import_jobs(db, cursor=cursor)
    assert session.params == []


@pytest.mark.unit
async def test_import_job_events_list_and_cursor() -> None:
    at = datetime(2026, 6, 3, tzinfo=UTC)
    session = _Session(
        _Result(
            [
                _event_row("11111111-1111-1111-1111-111111111111", at=at),
                _event_row("22222222-2222-2222-2222-222222222222", at=at),
            ]
        ),
        _Result([_event_row("11111111-1111-1111-1111-111111111111", at=at)]),
    )
    db = cast(Any, session)

    page = await list_ops_import_job_events(
        db,
        "11111111-1111-1111-1111-111111111111",
        level="error",
        limit=1,
    )
    assert isinstance(page.items[0], OpsImportJobEvent)
    assert page.items[0].provider_dataset_id == 1
    assert page.items[0].payload == {"attempt": 2}
    assert page.next_cursor is not None

    page2 = await list_ops_import_job_events(
        db,
        "11111111-1111-1111-1111-111111111111",
        level="error",
        limit=1,
        cursor=page.next_cursor,
    )
    assert session.params[0]["level"] == "error"
    assert session.params[1]["cursor_occurred_at"] == at
    assert session.params[1]["cursor_event_id"] == (
        "11111111-1111-1111-1111-111111111111"
    )
    assert len(page2.items) == 1


@pytest.mark.unit
async def test_import_job_events_global_filters() -> None:
    at = datetime(2026, 6, 3, tzinfo=UTC)
    session = _Session(_Result([_event_row("11111111-1111-1111-1111-111111111111", at=at)]))
    db = cast(Any, session)

    page = await list_ops_import_job_events(
        db,
        level="warning",
        provider_dataset_id=1,
        limit=50,
    )

    assert len(page.items) == 1
    assert session.params[0]["job_id"] is None
    assert session.params[0]["level"] == "warning"
    assert session.params[0]["provider_dataset_id"] == 1


@pytest.mark.unit
async def test_import_job_events_scope_filter_uses_typed_event_identity() -> None:
    at = datetime(2026, 6, 3, tzinfo=UTC)
    session = _Session(
        _Result([_event_row("11111111-1111-1111-1111-111111111111", at=at)])
    )

    page = await list_ops_import_job_events(
        cast(Any, session),
        provider_dataset_id=1,
        sync_scope="dataset_wide",
        limit=20,
    )

    assert len(page.items) == 1
    sql = session.statements[0]
    assert "JOIN ops.import_jobs AS job" not in sql
    assert "c6c_cancel_probe" not in sql
    assert "ops.feature_update_requests" not in sql
    assert "member.sync_scope = CAST(:sync_scope AS text)" in sql
    assert (
        sql.index("member.sync_scope = CAST(:sync_scope AS text)")
        < sql.index("ORDER BY")
        < sql.index("LIMIT")
    )
    assert session.params[0]["sync_scope"] == "dataset_wide"


@pytest.mark.unit
async def test_import_job_events_scope_filter_requires_typed_pair() -> None:
    session = _Session()

    with pytest.raises(ValueError, match="provider_dataset_id must be greater than 0"):
        await list_ops_import_job_events(
            cast(Any, session),
            provider_dataset_id=0,
        )

    with pytest.raises(ValueError, match="requires provider_dataset_id"):
        await list_ops_import_job_events(
            cast(Any, session),
            sync_scope="target_grids",
        )

    assert session.params == []


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
        provider_dataset_id=42,
        feature_id="feature-1",
        limit=1,
    )
    assert isinstance(page.items[0], OpsIntegrityIssue)
    assert page.items[0].provider_dataset_id == 42
    assert page.items[0].payload == {"source": "unit"}
    assert page.next_cursor is not None

    counts = await get_ops_integrity_issue_counts(db)
    assert counts.open_total == 2
    assert counts.by_status == {"open": 2}
    assert counts.by_severity == {"error": 2}
    assert counts.by_type == {"missing_coordinate": 2}


@pytest.mark.unit
async def test_integrity_issues_rejects_detected_at_cursor_contract() -> None:
    legacy_cursor = _cursor(
        {
            "v": 1,
            "kind": "integrity_issues",
            "at": "2026-06-03T00:00:00+00:00",
            "key": "11111111-1111-1111-1111-111111111111",
        }
    )

    with pytest.raises(ValueError, match="invalid integrity_issues_last_seen_v2 cursor"):
        await list_ops_integrity_issues(
            cast(Any, _Session()),
            cursor=legacy_cursor,
        )

    with pytest.raises(ValueError, match="provider_dataset_id must be greater than 0"):
        await list_ops_integrity_issues(
            cast(Any, _Session()),
            provider_dataset_id=0,
        )
