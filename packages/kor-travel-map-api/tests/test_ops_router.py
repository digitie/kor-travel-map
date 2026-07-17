"""존치하는 ``/v1/ops/*`` 관측 라우터 회귀."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from kortravelmap.infra.ops_repo import (
    OpsConsistencyReport,
    OpsConsistencyReportPage,
    OpsIntegrityIssue,
    OpsIntegrityIssueCounts,
    OpsIntegrityIssuePage,
)
from kortravelmap.infra.status_repo import StatusCounts

from kortravelmap.api.app import create_app
from kortravelmap.api.db import get_session
from kortravelmap.api.settings import ApiSettings


@pytest.fixture
def client() -> TestClient:
    app = create_app(ApiSettings())

    async def _fake_session() -> AsyncIterator[Any]:
        yield object()

    app.dependency_overrides[get_session] = _fake_session
    return TestClient(app)


def _report() -> OpsConsistencyReport:
    now = datetime(2026, 6, 3, tzinfo=UTC)
    return OpsConsistencyReport(
        report_id="22222222-2222-2222-2222-222222222222",
        batch_id="33333333-3333-3333-3333-333333333333",
        started_at=now,
        finished_at=now,
        severity_max="WARN",
        cases=[],
        summary={"total_violations": 3, "by_code": {"F4": 3}},
    )


def _issue() -> OpsIntegrityIssue:
    return OpsIntegrityIssue(
        issue_id="44444444-4444-4444-4444-444444444444",
        provider="python-mois-api",
        dataset_key="mois_license_features_bulk",
        source_record_key="src-1",
        feature_id="feature-1",
        violation_type="missing_coordinate",
        severity="error",
        message="좌표 없음",
        payload={"source": "unit"},
        status="open",
        detected_at=datetime(2026, 6, 3, tzinfo=UTC),
        resolved_at=None,
    )


@pytest.mark.unit
def test_remaining_ops_routes_mounted_in_openapi(client: TestClient) -> None:
    spec = client.get("/openapi.json").json()
    assert {
        "/v1/ops/metrics",
        "/v1/ops/health-deep",
        "/v1/ops/consistency/reports",
        "/v1/ops/consistency/issues",
    } <= set(spec["paths"])
    assert "OpsMetricsResponse" in spec["components"]["schemas"]


@pytest.mark.unit
def test_ops_live_websocket_initial_snapshot(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import ops_live as live_module

    async def _collect(
        _session: Any,
        topics: set[str],
    ) -> dict[str, live_module.LiveTopicSnapshot]:
        return {
            topic: live_module.LiveTopicSnapshot(
                topic=topic,
                revision=f"{topic}:1",
                data={"topic": topic, "ok": True},
            )
            for topic in topics
        }

    monkeypatch.setattr(live_module, "collect_live_topic_snapshots", _collect)
    with client.websocket_connect(
        "/v1/ops/live?topics=import_jobs&poll_interval_ms=1000"
    ) as websocket:
        hello = websocket.receive_json()
        snapshot = websocket.receive_json()

    assert hello["type"] == "hello"
    assert snapshot == {
        "type": "snapshot",
        "topic": "import_jobs",
        "revision": "import_jobs:1",
        "data": {"topic": "import_jobs", "ok": True},
    }


@pytest.mark.unit
def test_ops_live_queries_exclude_quarantined_rows() -> None:
    from kortravelmap.api.routers import ops_live as live_module

    assert live_module._IMPORT_JOBS_LIVE_SQL.count("quarantined_at IS NULL") >= 4
    assert "event.quarantined_at IS NULL" in live_module._IMPORT_JOBS_LIVE_SQL
    assert "event.quarantined_at IS NULL" in live_module._IMPORT_JOB_EVENTS_LIVE_SQL
    assert "ops.import_job_event_clock" in live_module._IMPORT_JOB_EVENTS_LIVE_SQL
    assert "ops.import_jobs" not in live_module._IMPORT_JOB_EVENTS_LIVE_SQL
    assert "COUNT(" not in live_module._IMPORT_JOB_EVENTS_LIVE_SQL
    assert "WHERE quarantined_at IS NULL" in live_module._DAGSTER_RUNS_LIVE_SQL
    assert "WHERE quarantined_at IS NULL" in live_module._DAGSTER_RUN_LIVE_SQL


@pytest.mark.unit
def test_ops_live_websocket_subscribe_command(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import ops_live as live_module

    async def _collect(
        _session: Any,
        topics: set[str],
    ) -> dict[str, live_module.LiveTopicSnapshot]:
        return {
            topic: live_module.LiveTopicSnapshot(
                topic=topic,
                revision=f"{topic}:1",
                data={"topic": topic},
            )
            for topic in topics
        }

    monkeypatch.setattr(live_module, "collect_live_topic_snapshots", _collect)
    with client.websocket_connect(
        "/v1/ops/live?topics=import_jobs&poll_interval_ms=1000"
    ) as websocket:
        assert websocket.receive_json()["type"] == "hello"
        assert websocket.receive_json()["topic"] == "import_jobs"
        websocket.send_json(
            {
                "type": "subscribe",
                "topics": ["import_job:11111111-1111-1111-1111-111111111111"],
            }
        )
        ack = websocket.receive_json()
        snapshots = [websocket.receive_json(), websocket.receive_json()]

    assert ack["type"] == "subscribed"
    assert ack["topics"] == [
        "import_job:11111111-1111-1111-1111-111111111111",
        "import_jobs",
    ]
    assert {message["topic"] for message in snapshots} == {
        "import_job:11111111-1111-1111-1111-111111111111",
        "import_jobs",
    }


@pytest.mark.unit
def test_ops_metrics_maps_counts(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import ops as module

    async def _counts(_session: Any) -> StatusCounts:
        return StatusCounts(
            features_total=10,
            features_active=9,
            features_inactive=1,
            features_by_kind={"place": 8, "event": 2},
            source_records_by_provider={"python-mois-api": 10},
            import_jobs_by_status={"running": 1},
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

    monkeypatch.setattr(module, "gather_status_counts", _counts)
    monkeypatch.setattr(module, "get_ops_integrity_issue_counts", _issue_counts)
    monkeypatch.setattr(module, "get_latest_consistency_report", _latest)
    response = client.get("/v1/ops/metrics")

    assert response.status_code == 200
    body = response.json()
    assert "duration_ms" in body["meta"]
    data = body["data"]
    assert data["features_total"] == 10
    assert data["import_jobs_by_status"] == {"running": 1}
    assert data["dedup_fp_stats"]["confirmed"] == 1
    assert data["dedup_fp_stats"]["rejected"] == 1
    assert data["data_integrity_issues"]["open_total"] == 3
    assert data["latest_consistency_report"]["severity_max"] == "WARN"


@pytest.mark.unit
def test_consistency_and_issue_lists_pass_filters(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import ops as module

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

    monkeypatch.setattr(module, "list_ops_consistency_reports", _reports)
    monkeypatch.setattr(module, "list_ops_integrity_issues", _issues)
    reports = client.get("/v1/ops/consistency/reports?severity_max=WARN&page_size=5")
    issues = client.get(
        "/v1/ops/consistency/issues?status=open&severity=error&"
        "violation_type=missing_coordinate&provider=python-mois-api&"
        "dataset_key=mois_license_features_bulk&feature_id=feature-1&page_size=5"
    )

    assert reports.status_code == 200
    assert reports.json()["data"]["items"][0]["summary"]["by_code"] == {"F4": 3}
    assert reports.json()["meta"]["page"]["page_size"] == 5
    assert issues.status_code == 200
    assert issues.json()["data"]["items"][0]["issue_id"] == _issue().issue_id
    assert issues.json()["data"]["items"][0]["message"] == "좌표 없음"
    assert issues.json()["meta"]["page"]["page_size"] == 5


@pytest.mark.unit
def test_health_deep_ok(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import ops as module
    from kortravelmap.api.routers.ops import OpsHealthCheck

    async def _database(_session: Any) -> OpsHealthCheck:
        return OpsHealthCheck(component="database", status="ok")

    async def _postgis(_session: Any) -> OpsHealthCheck:
        return OpsHealthCheck(component="postgis", status="ok", detail="3.5")

    async def _prewarm(_session: Any) -> OpsHealthCheck:
        return OpsHealthCheck(
            component="prewarm",
            status="ok",
            detail="extension=present, autoprewarm=off",
        )

    monkeypatch.setattr(module, "_check_database", _database)
    monkeypatch.setattr(module, "_check_postgis", _postgis)
    monkeypatch.setattr(module, "_check_prewarm", _prewarm)
    response = client.get("/v1/ops/health-deep")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"data", "meta"}
    assert body["data"]["status"] == "ok"
    assert {check["component"]: check["status"] for check in body["data"]["checks"]} == {
        "database": "ok",
        "postgis": "ok",
        "prewarm": "ok",
    }
    assert "duration_ms" in body["meta"]


@pytest.mark.unit
def test_health_deep_status_follows_required_checks(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import ops as module
    from kortravelmap.api.routers.ops import OpsHealthCheck

    async def _database(_session: Any) -> OpsHealthCheck:
        return OpsHealthCheck(component="database", status="error", detail="down")

    async def _postgis(_session: Any) -> OpsHealthCheck:
        return OpsHealthCheck(component="postgis", status="ok", detail="3.5")

    async def _prewarm(_session: Any) -> OpsHealthCheck:
        return OpsHealthCheck(component="prewarm", status="ok")

    monkeypatch.setattr(module, "_check_database", _database)
    monkeypatch.setattr(module, "_check_postgis", _postgis)
    monkeypatch.setattr(module, "_check_prewarm", _prewarm)
    response = client.get("/v1/ops/health-deep")

    assert response.status_code == 503
    assert response.json()["data"]["status"] == "degraded"
