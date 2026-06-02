"""Dagster 운영 요약 라우터 단위 테스트."""

from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from krtour.map_admin.app import create_app
from krtour.map_admin.routers import dagster as dagster_mod
from krtour.map_admin.settings import AdminSettings


@pytest.fixture
def client() -> TestClient:
    app = create_app(
        AdminSettings(
            dagster_url="http://dagster.example:9013",
            dagster_request_timeout_seconds=1.0,
        )
    )
    return TestClient(app)


@pytest.mark.unit
def test_dagster_summary_parses_graphql_response(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[dict[str, object]] = []

    async def _fake_post_graphql(
        graphql_url: str,
        variables: dict[str, object],
        timeout_seconds: float,
        query: str = dagster_mod._DAGSTER_SUMMARY_QUERY,
    ) -> dict[str, object]:
        assert graphql_url == "http://dagster.example:9013/graphql"
        assert timeout_seconds == 1.0
        calls.append({"query": query, "variables": variables})
        if query == dagster_mod._DAGSTER_SET_NUX_SEEN_MUTATION:
            assert variables == {}
            return {"data": {"setNuxSeen": True}}

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
    assert body["status"] == "ok"
    assert body["dagster_url"] == "http://dagster.example:9013"
    assert body["graphql_url"] == "http://dagster.example:9013/graphql"
    assert body["version"] == "1.13.7"
    assert body["repository_count"] == 1
    assert body["job_count"] == 1
    assert body["asset_count"] == 2
    assert body["run_counts"] == {"SUCCESS": 1}
    assert body["repositories"][0]["asset_groups"] == [
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
    assert body["recent_runs"][0]["run_id"] == "run-1"
    assert calls == [
        {"query": dagster_mod._DAGSTER_SUMMARY_QUERY, "variables": {"limit": 3}},
        {"query": dagster_mod._DAGSTER_SET_NUX_SEEN_MUTATION, "variables": {}},
    ]


@pytest.mark.unit
def test_dagster_summary_returns_unavailable_when_graphql_fails(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _raise_post_graphql(
        graphql_url: str,
        variables: dict[str, object],
        timeout_seconds: float,
        query: str = dagster_mod._DAGSTER_SUMMARY_QUERY,
    ) -> dict[str, object]:
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(dagster_mod, "_post_graphql", _raise_post_graphql)

    response = client.get("/ops/dagster/summary")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "unavailable"
    assert body["repository_count"] == 0
    assert body["recent_runs"] == []
    assert body["errors"]


@pytest.mark.unit
def test_dagster_summary_openapi_path_is_mounted(client: TestClient) -> None:
    spec = client.get("/openapi.json").json()
    assert "/ops/dagster/summary" in spec["paths"]
    assert "DagsterSummaryResponse" in spec["components"]["schemas"]
