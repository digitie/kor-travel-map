"""``/v1/ops/*`` 라우터 단위 테스트."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from krtour.map.infra.ops_repo import (
    OpsConsistencyReport,
    OpsConsistencyReportPage,
    OpsImportJob,
    OpsImportJobPage,
    OpsIntegrityIssue,
    OpsIntegrityIssueCounts,
    OpsIntegrityIssuePage,
)
from krtour.map.infra.status_repo import StatusCounts

from krtour.map_admin.app import create_app
from krtour.map_admin.db import get_session
from krtour.map_admin.settings import AdminSettings


class _FakeSession:
    pass


@pytest.fixture
def session() -> _FakeSession:
    return _FakeSession()


@pytest.fixture
def client(session: _FakeSession) -> TestClient:
    app = create_app(AdminSettings())

    async def _fake_session() -> AsyncIterator[_FakeSession]:
        yield session

    app.dependency_overrides[get_session] = _fake_session
    return TestClient(app)


def _job(job_id: str = "11111111-1111-1111-1111-111111111111") -> OpsImportJob:
    now = datetime(2026, 6, 3, tzinfo=UTC)
    return OpsImportJob(
        job_id=job_id,
        kind="feature_update_request",
        load_batch_id="33333333-3333-3333-3333-333333333333",
        parent_job_id="44444444-4444-4444-4444-444444444444",
        payload={"request_id": "req-1"},
        state="running",
        progress=40,
        current_stage="loading",
        source_checksum=None,
        error_message=None,
        created_at=now,
        started_at=now,
        finished_at=None,
        heartbeat_at=now,
    )


def _report(
    report_id: str = "22222222-2222-2222-2222-222222222222",
) -> OpsConsistencyReport:
    now = datetime(2026, 6, 3, tzinfo=UTC)
    return OpsConsistencyReport(
        report_id=report_id,
        batch_id="33333333-3333-3333-3333-333333333333",
        started_at=now,
        finished_at=now,
        severity_max="WARN",
        cases=[
            {
                "code": "F4",
                "severity": "WARN",
                "description": "dedup backlog",
                "count": 3,
                "sample_ids": ["review-1"],
            }
        ],
        summary={"total_violations": 3, "by_code": {"F4": 3}},
    )


def _issue(
    violation_key: str = "44444444-4444-4444-4444-444444444444",
) -> OpsIntegrityIssue:
    now = datetime(2026, 6, 3, tzinfo=UTC)
    return OpsIntegrityIssue(
        violation_key=violation_key,
        provider="python-mois-api",
        dataset_key="mois_license_features_bulk",
        source_record_key="src-1",
        feature_id="feature-1",
        violation_type="missing_coordinate",
        severity="error",
        message="좌표 없음",
        payload={"source": "unit"},
        status="open",
        detected_at=now,
        resolved_at=None,
    )


@pytest.mark.unit
def test_ops_routes_mounted_in_openapi(client: TestClient) -> None:
    spec = client.get("/openapi.json").json()
    assert "/v1/ops/metrics" in spec["paths"]
    assert "/v1/ops/import-jobs" in spec["paths"]
    assert "/v1/ops/import-jobs/{job_id}" in spec["paths"]
    assert "/v1/ops/consistency/reports" in spec["paths"]
    assert "/v1/ops/consistency/issues" in spec["paths"]
    assert "OpsMetricsResponse" in spec["components"]["schemas"]


@pytest.mark.unit
def test_ops_metrics_maps_counts(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from krtour.map_admin.routers import ops as router_mod

    async def _counts(_session: Any) -> StatusCounts:
        return StatusCounts(
            features_total=10,
            features_active=9,
            features_inactive=1,
            features_by_kind={"place": 8, "event": 2},
            source_records_by_provider={"python-mois-api": 10},
            import_jobs_by_state={"running": 1},
            dedup_queue_by_status={"merged": 1, "rejected": 1, "pending": 2},
        )

    async def _issue_counts(_session: Any) -> OpsIntegrityIssueCounts:
        return OpsIntegrityIssueCounts(
            open_total=3,
            by_status={"open": 3},
            by_severity={"error": 2, "warning": 1},
            by_type={"missing_coordinate": 2, "missing_address": 1},
        )

    async def _latest(_session: Any) -> OpsConsistencyReport:
        return _report()

    monkeypatch.setattr(router_mod, "gather_status_counts", _counts)
    monkeypatch.setattr(router_mod, "get_ops_integrity_issue_counts", _issue_counts)
    monkeypatch.setattr(router_mod, "get_latest_consistency_report", _latest)

    response = client.get("/v1/ops/metrics")

    assert response.status_code == 200
    body = response.json()
    assert "duration_ms" in body["meta"]
    data = body["data"]
    assert data["features_total"] == 10
    assert data["import_jobs_by_state"] == {"running": 1}
    assert data["dedup_fp_stats"]["confirmed"] == 1
    assert data["dedup_fp_stats"]["rejected"] == 1
    assert data["data_integrity_issues"]["open_total"] == 3
    assert data["latest_consistency_report"]["severity_max"] == "WARN"


@pytest.mark.unit
def test_import_jobs_list_passes_filters(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from krtour.map_admin.routers import ops as router_mod

    async def _list(_session: Any, **kwargs: Any) -> OpsImportJobPage:
        assert kwargs == {
            "state": "running",
            "kind": "feature_update_request",
            "load_batch_id": "33333333-3333-3333-3333-333333333333",
            "parent_job_id": "44444444-4444-4444-4444-444444444444",
            "limit": 25,
            "cursor": "cursor-1",
        }
        return OpsImportJobPage(items=(_job(),), next_cursor="cursor-2")

    monkeypatch.setattr(router_mod, "list_ops_import_jobs", _list)

    response = client.get(
        "/v1/ops/import-jobs?"
        "status=running&kind=feature_update_request"
        "&load_batch_id=33333333-3333-3333-3333-333333333333"
        "&parent_job_id=44444444-4444-4444-4444-444444444444"
        "&page_size=25&cursor=cursor-1"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["data"]["items"][0]["job_id"] == _job().job_id
    assert body["data"]["items"][0]["load_batch_id"] == _job().load_batch_id
    assert body["data"]["items"][0]["parent_job_id"] == _job().parent_job_id
    assert body["data"]["items"][0]["status"] == "running"
    assert body["meta"]["page"] == {
        "page_size": 25,
        "next_cursor": "cursor-2",
        "total": None,
    }


@pytest.mark.unit
def test_import_job_detail_404(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from krtour.map_admin.routers import ops as router_mod

    async def _get(_session: Any, job_id: str) -> None:
        assert job_id == "missing"

    monkeypatch.setattr(router_mod, "get_ops_import_job", _get)

    response = client.get("/v1/ops/import-jobs/missing")

    assert response.status_code == 404


@pytest.mark.unit
def test_consistency_and_issue_lists_pass_filters(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from krtour.map_admin.routers import ops as router_mod

    async def _reports(_session: Any, **kwargs: Any) -> OpsConsistencyReportPage:
        assert kwargs == {"severity_max": "WARN", "limit": 5, "cursor": None}
        return OpsConsistencyReportPage(items=(_report(),), next_cursor=None)

    async def _issues(_session: Any, **kwargs: Any) -> OpsIntegrityIssuePage:
        assert kwargs == {
            "status": "open",
            "severity": "error",
            "violation_type": "missing_coordinate",
            "provider": "python-mois-api",
            "dataset_key": "mois_license_features_bulk",
            "feature_id": "feature-1",
            "limit": 5,
            "cursor": None,
        }
        return OpsIntegrityIssuePage(items=(_issue(),), next_cursor=None)

    monkeypatch.setattr(router_mod, "list_ops_consistency_reports", _reports)
    monkeypatch.setattr(router_mod, "list_ops_integrity_issues", _issues)

    reports = client.get("/v1/ops/consistency/reports?severity_max=WARN&page_size=5")
    issues = client.get(
        "/v1/ops/consistency/issues?"
        "status=open&severity=error&violation_type=missing_coordinate&"
        "provider=python-mois-api&dataset_key=mois_license_features_bulk&"
        "feature_id=feature-1&page_size=5"
    )

    assert reports.status_code == 200
    assert reports.json()["data"]["items"][0]["summary"]["by_code"] == {"F4": 3}
    assert reports.json()["meta"]["page"]["page_size"] == 5
    assert issues.status_code == 200
    assert issues.json()["data"]["items"][0]["issue_id"] == _issue().violation_key
    assert issues.json()["data"]["items"][0]["message"] == "좌표 없음"
    assert issues.json()["meta"]["page"]["page_size"] == 5


@pytest.mark.unit
def test_health_deep_ok(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from krtour.map_admin.routers import ops as router_mod
    from krtour.map_admin.routers.ops import OpsHealthCheck

    async def _db(_session: Any) -> OpsHealthCheck:
        return OpsHealthCheck(component="database", status="ok")

    async def _postgis(_session: Any) -> OpsHealthCheck:
        return OpsHealthCheck(component="postgis", status="ok", detail="3.5")

    async def _prewarm(_session: Any) -> OpsHealthCheck:
        return OpsHealthCheck(
            component="prewarm", status="ok", detail="extension=present, autoprewarm=off"
        )

    monkeypatch.setattr(router_mod, "_check_database", _db)
    monkeypatch.setattr(router_mod, "_check_postgis", _postgis)
    monkeypatch.setattr(router_mod, "_check_prewarm", _prewarm)

    response = client.get("/v1/ops/health-deep")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"data", "meta"}
    assert body["data"]["status"] == "ok"
    components = {c["component"]: c["status"] for c in body["data"]["checks"]}
    assert components == {"database": "ok", "postgis": "ok", "prewarm": "ok"}
    assert "duration_ms" in body["meta"]


@pytest.mark.unit
def test_health_deep_degraded_returns_503(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from krtour.map_admin.routers import ops as router_mod
    from krtour.map_admin.routers.ops import OpsHealthCheck

    async def _db(_session: Any) -> OpsHealthCheck:
        return OpsHealthCheck(
            component="database", status="error", detail="connection refused"
        )

    async def _postgis(_session: Any) -> OpsHealthCheck:
        return OpsHealthCheck(component="postgis", status="ok", detail="3.5")

    async def _prewarm(_session: Any) -> OpsHealthCheck:
        return OpsHealthCheck(component="prewarm", status="ok")

    monkeypatch.setattr(router_mod, "_check_database", _db)
    monkeypatch.setattr(router_mod, "_check_postgis", _postgis)
    monkeypatch.setattr(router_mod, "_check_prewarm", _prewarm)

    response = client.get("/v1/ops/health-deep")

    assert response.status_code == 503
    body = response.json()
    assert body["data"]["status"] == "degraded"
    db_check = next(c for c in body["data"]["checks"] if c["component"] == "database")
    assert db_check["status"] == "error"
