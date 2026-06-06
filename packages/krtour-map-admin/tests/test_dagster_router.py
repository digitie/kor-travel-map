"""Dagster 운영 요약 라우터 단위 테스트."""

from __future__ import annotations

from collections.abc import Iterator

import httpx
import pytest
from fastapi.testclient import TestClient

from krtour.map_admin.app import create_app
from krtour.map_admin.routers import dagster as dagster_mod
from krtour.map_admin.settings import AdminSettings


@pytest.fixture
def client() -> Iterator[TestClient]:
    app = create_app(
        AdminSettings(
            dagster_url="http://dagster.example:9013",
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
        assert graphql_url == "http://dagster.example:9013/graphql"
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
                                "name": "krtour.map_dagster.definitions",
                            },
                            "pipelines": [{"name": "__ASSET_JOB", "isJob": True}],
                            "schedules": [],
                            "sensors": [],
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

    response = client.get("/ops/dagster/summary?run_limit=3")

    assert response.status_code == 200
    body = response.json()
    assert "duration_ms" in body["meta"]
    data = body["data"]
    assert data["status"] == "ok"
    assert data["dagster_url"] == "http://dagster.example:9013"
    assert data["graphql_url"] == "http://dagster.example:9013/graphql"
    assert data["version"] == "1.13.7"
    assert data["repository_count"] == 1
    assert data["job_count"] == 1
    assert data["asset_count"] == 2
    assert data["run_counts"] == {"SUCCESS": 1}
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
        assert graphql_url == "http://dagster.example:9013/graphql"
        calls.append({"query": query, "variables": variables})
        assert query == dagster_mod._DAGSTER_SET_NUX_SEEN_MUTATION
        assert variables == {}
        return {"data": {"setNuxSeen": True}}

    monkeypatch.setattr(dagster_mod, "_post_graphql", _fake_post_graphql)

    response = client.post("/ops/dagster/nux-seen")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["seen"] is True
    assert body["errors"] == []
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

    response = client.get("/ops/dagster/summary")

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
        AdminSettings(
            dagster_url="http://169.254.169.254:9013",
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
        response = test_client.get("/ops/dagster/summary")

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
        AdminSettings(
            dagster_url="http://127.0.0.1:9013",
            dagster_graphql_url="http://127.0.0.1:9013/query",
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
        response = test_client.post("/ops/dagster/nux-seen")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "error"
    assert body["seen"] is False
    assert body["errors"] == ["dagster_graphql_url path must end with /graphql"]


@pytest.mark.unit
def test_dagster_summary_openapi_path_is_mounted(client: TestClient) -> None:
    spec = client.get("/openapi.json").json()
    assert "/ops/dagster/summary" in spec["paths"]
    assert "/ops/dagster/nux-seen" in spec["paths"]
    assert "DagsterSummaryResponse" in spec["components"]["schemas"]
    assert "DagsterNuxSeenResponse" in spec["components"]["schemas"]
