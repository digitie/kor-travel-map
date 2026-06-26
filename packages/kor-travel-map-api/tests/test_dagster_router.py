"""Dagster 운영 요약 라우터 단위 테스트."""

from __future__ import annotations

from collections.abc import Iterator

import httpx
import pytest
from fastapi.testclient import TestClient

from kortravelmap.api.app import create_app
from kortravelmap.api.routers import dagster as dagster_mod
from kortravelmap.api.settings import ApiSettings


@pytest.fixture
def client() -> Iterator[TestClient]:
    app = create_app(
        ApiSettings(
            dagster_url="http://dagster.example:12302",
            dagster_allowed_hosts=["dagster.example"],
            dagster_request_timeout_seconds=1.0,
        )
    )
    with TestClient(app) as test_client:
        yield test_client


@pytest.mark.unit
def test_dagster_summary_parses_graphql_response(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[dict[str, object]] = []

    async def _fake_post_graphql(
        client: httpx.AsyncClient,
        graphql_url: str,
        variables: dict[str, object],
        query: str = dagster_mod._DAGSTER_SUMMARY_QUERY,
    ) -> dict[str, object]:
        assert graphql_url == "http://dagster.example:12302/graphql"
        calls.append({"query": query, "variables": variables})
        assert query == dagster_mod._DAGSTER_SUMMARY_QUERY
        assert variables == {"limit": 3}
        return {
            "data": {
                "version": "1.13.7",
                "repositoriesOrError": {
                    "__typename": "RepositoryConnection",
                    "nodes": [
                        {
                            "name": "__repository__",
                            "location": {
                                "name": "kortravelmap.dagster.definitions",
                            },
                            "pipelines": [{"name": "__ASSET_JOB", "isJob": True}],
                            "schedules": [
                                {
                                    "name": "nightly_feature_refresh",
                                    "cronSchedule": "0 2 * * *",
                                    "executionTimezone": "Asia/Seoul",
                                    "scheduleState": {
                                        "status": "RUNNING",
                                        "ticks": [
                                            {
                                                "tickId": "schedule-tick-1",
                                                "status": "SUCCESS",
                                                "timestamp": 1710000000.0,
                                                "endTimestamp": 1710000010.0,
                                                "runIds": ["run-1"],
                                                "runKeys": ["nightly"],
                                                "skipReason": None,
                                                "cursor": "cursor-1",
                                                "error": None,
                                            }
                                        ],
                                    },
                                }
                            ],
                            "sensors": [
                                {
                                    "name": "provider_failure_sensor",
                                    "sensorState": {
                                        "status": "STOPPED",
                                        "ticks": [
                                            {
                                                "tickId": "sensor-tick-1",
                                                "status": "FAILURE",
                                                "timestamp": 1710000200.0,
                                                "endTimestamp": None,
                                                "runIds": [],
                                                "runKeys": [],
                                                "skipReason": None,
                                                "cursor": None,
                                                "error": {
                                                    "message": "sensor failed",
                                                    "stack": ["frame 1"],
                                                    "className": "SensorFailure",
                                                },
                                            }
                                        ],
                                    },
                                }
                            ],
                            "assetNodes": [
                                {
                                    "id": "asset-1",
                                    "groupName": "features_place",
                                    "assetKey": {
                                        "path": ["feature_place_mois_licenses"]
                                    },
                                },
                                {
                                    "id": "asset-2",
                                    "groupName": "features_event",
                                    "assetKey": {
                                        "path": [
                                            "feature_event_datagokr_cultural_festivals"
                                        ]
                                    },
                                },
                            ],
                        }
                    ],
                },
                "runsOrError": {
                    "__typename": "Runs",
                    "results": [
                        {
                            "runId": "run-1",
                            "jobName": "__ASSET_JOB",
                            "status": "SUCCESS",
                            "startTime": 1.0,
                            "endTime": 2.0,
                            "updateTime": 2.0,
                            "tags": [{"key": "dagster/job", "value": "__ASSET_JOB"}],
                        }
                    ],
                },
            }
        }

    monkeypatch.setattr(dagster_mod, "_post_graphql", _fake_post_graphql)

    response = client.get("/v1/ops/dagster/summary?page_size=3")

    assert response.status_code == 200
    body = response.json()
    assert "duration_ms" in body["meta"]
    data = body["data"]
    assert data["status"] == "ok"
    assert data["dagster_url"] == "http://dagster.example:12302"
    assert data["graphql_url"] == "http://dagster.example:12302/graphql"
    assert data["version"] == "1.13.7"
    assert data["repository_count"] == 1
    assert data["job_count"] == 1
    assert data["asset_count"] == 2
    assert data["schedule_count"] == 1
    assert data["sensor_count"] == 1
    assert data["run_counts"] == {"SUCCESS": 1}
    repository = data["repositories"][0]
    assert repository["schedules"][0]["recent_ticks"] == [
        {
            "tick_id": "schedule-tick-1",
            "status": "SUCCESS",
            "timestamp": 1710000000.0,
            "end_timestamp": 1710000010.0,
            "run_ids": ["run-1"],
            "run_keys": ["nightly"],
            "skip_reason": None,
            "cursor": "cursor-1",
            "error": None,
        }
    ]
    assert repository["sensors"][0]["recent_ticks"][0]["error"] == {
        "message": "sensor failed",
        "stack": ["frame 1"],
        "class_name": "SensorFailure",
    }
    assert data["repositories"][0]["asset_groups"] == [
        {
            "group_name": "features_event",
            "asset_count": 1,
            "assets": ["feature_event_datagokr_cultural_festivals"],
        },
        {
            "group_name": "features_place",
            "asset_count": 1,
            "assets": ["feature_place_mois_licenses"],
        },
    ]
    assert data["recent_runs"][0]["run_id"] == "run-1"
    assert calls == [
        {"query": dagster_mod._DAGSTER_SUMMARY_QUERY, "variables": {"limit": 3}},
    ]


@pytest.mark.unit
def test_dagster_run_detail_parses_graphql_response(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[dict[str, object]] = []

    async def _fake_post_graphql(
        client: httpx.AsyncClient,
        graphql_url: str,
        variables: dict[str, object],
        query: str = dagster_mod._DAGSTER_SUMMARY_QUERY,
    ) -> dict[str, object]:
        assert graphql_url == "http://dagster.example:12302/graphql"
        calls.append({"query": query, "variables": variables})
        assert query == dagster_mod._DAGSTER_RUN_DETAIL_QUERY
        assert variables == {
            "runId": "run-1",
            "eventLimit": 5,
            "afterCursor": None,
        }
        return {
            "data": {
                "runOrError": {
                    "__typename": "Run",
                    "runId": "run-1",
                    "jobName": "__ASSET_JOB",
                    "status": "FAILURE",
                    "startTime": 1710000000.0,
                    "endTime": 1710000030.0,
                    "updateTime": 1710000030.0,
                    "tags": [{"key": "dagster/job", "value": "__ASSET_JOB"}],
                    "eventConnection": {
                        "cursor": "event-cursor-1",
                        "hasMore": True,
                        "events": [
                            {
                                "__typename": "StepStartEvent",
                                "message": "step started",
                                "timestamp": "1710000001.0",
                                "level": "INFO",
                                "stepKey": "load_features",
                                "eventType": "STEP_START",
                            },
                            {
                                "__typename": "RunFailureEvent",
                                "message": "run failed",
                                "timestamp": "1710000030.0",
                                "level": "ERROR",
                                "stepKey": None,
                                "eventType": "RUN_FAILURE",
                                "error": {
                                    "message": "boom",
                                    "stack": ["traceback"],
                                    "className": "RuntimeError",
                                },
                            },
                        ],
                    },
                }
            }
        }

    monkeypatch.setattr(dagster_mod, "_post_graphql", _fake_post_graphql)

    response = client.get("/v1/ops/dagster/runs/run-1?page_size=5")

    assert response.status_code == 200
    body = response.json()
    assert "duration_ms" in body["meta"]
    data = body["data"]
    assert data["status"] == "ok"
    assert data["dagster_url"] == "http://dagster.example:12302"
    assert data["graphql_url"] == "http://dagster.example:12302/graphql"
    assert data["run"]["run_id"] == "run-1"
    assert data["run"]["status"] == "FAILURE"
    assert data["event_cursor"] == "event-cursor-1"
    assert data["event_has_more"] is True
    assert data["events"][0]["dagster_event_type"] == "STEP_START"
    assert data["events"][1]["error"] == {
        "message": "boom",
        "stack": ["traceback"],
        "class_name": "RuntimeError",
    }
    assert data["failure_reason"] == "RuntimeError: boom"
    assert data["failure_events"] == [
        {
            "event_type": "RunFailureEvent",
            "message": "RuntimeError: boom",
            "timestamp": "1710000030.0",
            "level": "ERROR",
            "step_id": None,
            "dagster_event_type": "RUN_FAILURE",
            "error": {
                "message": "boom",
                "stack": ["traceback"],
                "class_name": "RuntimeError",
            },
        }
    ]
    assert calls == [
        {
            "query": dagster_mod._DAGSTER_RUN_DETAIL_QUERY,
            "variables": {"runId": "run-1", "eventLimit": 5, "afterCursor": None},
        },
    ]


@pytest.mark.unit
def test_dagster_run_detail_returns_not_found(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _fake_post_graphql(
        client: httpx.AsyncClient,
        graphql_url: str,
        variables: dict[str, object],
        query: str = dagster_mod._DAGSTER_SUMMARY_QUERY,
    ) -> dict[str, object]:
        return {
            "data": {
                "runOrError": {
                    "__typename": "RunNotFoundError",
                    "message": "Run not found",
                    "runId": "missing-run",
                }
            }
        }

    monkeypatch.setattr(dagster_mod, "_post_graphql", _fake_post_graphql)

    response = client.get("/v1/ops/dagster/runs/missing-run")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "not_found"
    assert data["run"] is None
    assert data["events"] == []
    assert data["errors"] == ["Run not found"]


@pytest.mark.unit
def test_dagster_run_detail_passes_after_cursor(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``after`` 쿼리파라미터가 GraphQL ``afterCursor`` 변수로 전달돼야 한다(긴 run
    뒤쪽 실패 이벤트로 전진 페이지네이션, #291 리뷰)."""
    seen: list[dict[str, object]] = []

    async def _fake_post_graphql(
        client: httpx.AsyncClient,
        graphql_url: str,
        variables: dict[str, object],
        query: str = dagster_mod._DAGSTER_SUMMARY_QUERY,
    ) -> dict[str, object]:
        seen.append(variables)
        return {
            "data": {
                "runOrError": {
                    "__typename": "Run",
                    "runId": "run-1",
                    "status": "FAILURE",
                    "tags": [],
                    "eventConnection": {"cursor": None, "hasMore": False, "events": []},
                }
            }
        }

    monkeypatch.setattr(dagster_mod, "_post_graphql", _fake_post_graphql)

    response = client.get("/v1/ops/dagster/runs/run-1?page_size=5&after=ev-cursor-80")

    assert response.status_code == 200
    assert seen == [{"runId": "run-1", "eventLimit": 5, "afterCursor": "ev-cursor-80"}]


@pytest.mark.unit
def test_dagster_run_detail_graphql_error_extracts_message(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """GraphQL top-level errors는 dict repr이 아니라 message만 노출돼야 한다(#291 리뷰)."""

    async def _fake_post_graphql(
        client: httpx.AsyncClient,
        graphql_url: str,
        variables: dict[str, object],
        query: str = dagster_mod._DAGSTER_SUMMARY_QUERY,
    ) -> dict[str, object]:
        return {
            "errors": [
                {
                    "message": "Field 'bogus' doesn't exist",
                    "locations": [{"line": 3, "column": 5}],
                    "path": ["runOrError"],
                }
            ]
        }

    monkeypatch.setattr(dagster_mod, "_post_graphql", _fake_post_graphql)

    response = client.get("/v1/ops/dagster/runs/run-1")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "error"
    assert data["errors"] == ["Field 'bogus' doesn't exist"]
    # dict repr(파이썬 표현)이 새지 않아야 한다.
    assert "locations" not in data["errors"][0]


@pytest.mark.unit
def test_mark_dagster_nux_seen_posts_mutation(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[dict[str, object]] = []

    async def _fake_post_graphql(
        client: httpx.AsyncClient,
        graphql_url: str,
        variables: dict[str, object],
        query: str = dagster_mod._DAGSTER_SUMMARY_QUERY,
    ) -> dict[str, object]:
        assert graphql_url == "http://dagster.example:12302/graphql"
        calls.append({"query": query, "variables": variables})
        assert query == dagster_mod._DAGSTER_SET_NUX_SEEN_MUTATION
        assert variables == {}
        return {"data": {"setNuxSeen": True}}

    monkeypatch.setattr(dagster_mod, "_post_graphql", _fake_post_graphql)

    response = client.post("/v1/ops/dagster/nux-seen")

    assert response.status_code == 200
    body = response.json()
    assert "duration_ms" in body["meta"]
    data = body["data"]
    assert data["status"] == "ok"
    assert data["seen"] is True
    assert data["errors"] == []
    assert calls == [
        {"query": dagster_mod._DAGSTER_SET_NUX_SEEN_MUTATION, "variables": {}}
    ]


@pytest.mark.unit
def test_dagster_summary_returns_unavailable_when_graphql_fails(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _raise_post_graphql(
        client: httpx.AsyncClient,
        graphql_url: str,
        variables: dict[str, object],
        query: str = dagster_mod._DAGSTER_SUMMARY_QUERY,
    ) -> dict[str, object]:
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(dagster_mod, "_post_graphql", _raise_post_graphql)

    response = client.get("/v1/ops/dagster/summary")

    assert response.status_code == 200
    body = response.json()
    data = body["data"]
    assert data["status"] == "unavailable"
    assert data["repository_count"] == 0
    assert data["recent_runs"] == []
    assert data["errors"]


@pytest.mark.unit
def test_dagster_summary_rejects_disallowed_url_before_http_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = create_app(
        ApiSettings(
            dagster_url="http://169.254.169.254:12302",
            dagster_allowed_hosts=["127.0.0.1"],
        )
    )

    async def _unexpected_post_graphql(
        client: httpx.AsyncClient,
        graphql_url: str,
        variables: dict[str, object],
        query: str = dagster_mod._DAGSTER_SUMMARY_QUERY,
    ) -> dict[str, object]:
        raise AssertionError("disallowed Dagster URL must not be requested")

    monkeypatch.setattr(dagster_mod, "_post_graphql", _unexpected_post_graphql)

    with TestClient(app) as test_client:
        response = test_client.get("/v1/ops/dagster/summary")

    assert response.status_code == 200
    body = response.json()
    data = body["data"]
    assert data["status"] == "error"
    assert data["repository_count"] == 0
    assert data["errors"] == ["dagster_url host is not in dagster_allowed_hosts"]


@pytest.mark.unit
def test_dagster_nux_seen_rejects_invalid_graphql_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = create_app(
        ApiSettings(
            dagster_url="http://127.0.0.1:12302",
            dagster_graphql_url="http://127.0.0.1:12302/query",
            dagster_allowed_hosts=["127.0.0.1"],
        )
    )

    async def _unexpected_post_graphql(
        client: httpx.AsyncClient,
        graphql_url: str,
        variables: dict[str, object],
        query: str = dagster_mod._DAGSTER_SUMMARY_QUERY,
    ) -> dict[str, object]:
        raise AssertionError("invalid GraphQL URL must not be requested")

    monkeypatch.setattr(dagster_mod, "_post_graphql", _unexpected_post_graphql)

    with TestClient(app) as test_client:
        response = test_client.post("/v1/ops/dagster/nux-seen")

    assert response.status_code == 200
    body = response.json()
    data = body["data"]
    assert data["status"] == "error"
    assert data["seen"] is False
    assert data["errors"] == ["dagster_graphql_url path must end with /graphql"]


@pytest.mark.unit
def test_dagster_summary_openapi_path_is_mounted(client: TestClient) -> None:
    spec = client.get("/openapi.json").json()
    assert "/v1/ops/dagster/runs/{run_id}" in spec["paths"]
    assert "/v1/ops/dagster/summary" in spec["paths"]
    assert "/v1/ops/dagster/nux-seen" in spec["paths"]
    assert "DagsterRunDetailResponse" in spec["components"]["schemas"]
    assert "DagsterSummaryResponse" in spec["components"]["schemas"]
    assert "DagsterNuxSeenResponse" in spec["components"]["schemas"]
