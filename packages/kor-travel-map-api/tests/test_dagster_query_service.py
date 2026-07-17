"""Legacy router와 분리된 Dagster query/parser application service 회귀."""

from __future__ import annotations

import httpx
import pytest

from kortravelmap.api import dagster_graphql
from kortravelmap.api import dagster_query_service as service
from kortravelmap.api.settings import ApiSettings

_SETTINGS = ApiSettings(
    dagster_url="http://dagster.example:12302",
    dagster_allowed_hosts=["dagster.example"],
)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_summary_service_parses_repository_and_run_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _post(**kwargs: object) -> dict[str, object]:
        assert kwargs["variables"] == {"limit": 3}
        assert kwargs["query"] == service._DAGSTER_SUMMARY_QUERY
        return {
            "data": {
                "version": "1.13.7",
                "repositoriesOrError": {
                    "__typename": "RepositoryConnection",
                    "nodes": [
                        {
                            "name": "__repository__",
                            "location": {"name": "location"},
                            "pipelines": [{"name": "job", "isJob": True}],
                            "schedules": [],
                            "sensors": [],
                            "assetNodes": [
                                {
                                    "id": "asset-1",
                                    "groupName": "features_place",
                                    "assetKey": {"path": ["feature_place_mois_licenses"]},
                                }
                            ],
                        }
                    ],
                },
                "runsOrError": {
                    "__typename": "Runs",
                    "results": [
                        {
                            "runId": "run-1",
                            "jobName": "job",
                            "status": "SUCCESS",
                            "tags": [],
                        }
                    ],
                },
            }
        }

    monkeypatch.setattr(dagster_graphql, "post_graphql", _post)
    async with httpx.AsyncClient() as client:
        response = await service.get_summary(
            settings=_SETTINGS,
            client=client,
            overrides={},
            page_size=3,
        )

    assert response.data.status == "ok"
    assert response.data.repository_count == 1
    assert response.data.job_count == 1
    assert response.data.asset_count == 1
    assert response.data.run_counts == {"SUCCESS": 1}
    assert response.data.recent_runs[0].run_id == "run-1"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_run_detail_service_parses_event_page_and_forwards_cursor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _post(**kwargs: object) -> dict[str, object]:
        assert kwargs["variables"] == {
            "runId": "run-1",
            "eventLimit": 5,
            "afterCursor": "cursor-0",
        }
        return {
            "data": {
                "runOrError": {
                    "__typename": "Run",
                    "runId": "run-1",
                    "jobName": "job",
                    "status": "FAILURE",
                    "tags": [],
                    "eventConnection": {
                        "cursor": "cursor-1",
                        "hasMore": True,
                        "events": [
                            {
                                "__typename": "RunFailureEvent",
                                "message": "failed",
                                "timestamp": "1710000030.0",
                                "level": "ERROR",
                                "stepKey": None,
                                "eventType": "RUN_FAILURE",
                                "error": {
                                    "message": "boom",
                                    "stack": ["traceback"],
                                    "className": "RuntimeError",
                                },
                            }
                        ],
                    },
                }
            }
        }

    monkeypatch.setattr(dagster_graphql, "post_graphql", _post)
    async with httpx.AsyncClient() as client:
        response = await service.get_run_detail(
            settings=_SETTINGS,
            client=client,
            run_id="run-1",
            page_size=5,
            after="cursor-0",
        )

    assert response.data.status == "ok"
    assert response.data.event_cursor == "cursor-1"
    assert response.data.event_has_more is True
    assert response.data.failure_reason == "RuntimeError: boom"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_run_detail_service_fails_closed_on_malformed_pagination(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _post(**_kwargs: object) -> dict[str, object]:
        return {
            "data": {
                "runOrError": {
                    "__typename": "Run",
                    "runId": "run-1",
                    "status": "SUCCESS",
                    "tags": [],
                    "eventConnection": {
                        "cursor": None,
                        "hasMore": True,
                        "events": [],
                    },
                }
            }
        }

    monkeypatch.setattr(dagster_graphql, "post_graphql", _post)
    async with httpx.AsyncClient() as client:
        response = await service.get_run_detail(
            settings=_SETTINGS,
            client=client,
            run_id="run-1",
            page_size=5,
            after=None,
        )

    assert response.data.status == "error"
    assert response.data.run is None
    assert response.data.events == []
    assert response.data.errors
