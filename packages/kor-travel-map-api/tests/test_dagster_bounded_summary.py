"""최근 목록 밖의 활성 실행과 잘못된 GraphQL 응답을 정상으로 숨기지 않는다."""

from __future__ import annotations

import httpx
import pytest

from kortravelmap.api.dagster_graphql import merge_recent_active_runs, parse_runs, post_graphql


def row(run_id: str, status: str, time: float) -> dict[str, object]:
    return {"runId": run_id, "status": status, "jobName": "map_job", "startTime": time, "tags": []}


def test_old_active_run_is_visible_after_recent_successes() -> None:
    recent = [row(f"success-{i}", "SUCCESS", float(100 + i)) for i in range(30)]
    runs, counts, errors = merge_recent_active_runs(
        {
            "runsOrError": {"__typename": "Runs", "results": recent},
            "activeRunsOrError": {"__typename": "Runs", "results": [row("old", "STARTED", 1)]},
        },
        recent_limit=30,
    )
    assert not errors
    assert len(runs) == 31
    assert counts == {"SUCCESS": 30, "STARTED": 1}
    assert runs[-1].run_id == "old"


@pytest.mark.parametrize("results", [None, {}, "bad", True, [None], [{"runId": "x", "status": []}]])
def test_malformed_runs_never_look_healthy(results: object) -> None:
    runs, counts, errors = parse_runs({"__typename": "Runs", "results": results}, limit=3)
    assert errors
    assert not runs
    assert not counts


def test_response_exceeding_query_limit_is_rejected() -> None:
    assert parse_runs(
        {"__typename": "Runs", "results": [row(str(i), "STARTED", 1) for i in range(4)]}, limit=3
    )[2]


def test_terminal_transition_wins_over_active_sample() -> None:
    runs, counts, errors = merge_recent_active_runs(
        {
            "runsOrError": {"__typename": "Runs", "results": [row("same", "SUCCESS", 2)]},
            "activeRunsOrError": {"__typename": "Runs", "results": [row("same", "STARTED", 1)]},
        },
        recent_limit=30,
    )
    assert not errors
    assert len(runs) == 1
    assert counts == {"SUCCESS": 1}


@pytest.mark.asyncio
async def test_post_graphql_rejects_compressed_body_before_decode() -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, headers={"Content-Encoding": "gzip"}, stream=httpx.ByteStream(b"invalid")
            )
        )
    ) as client:
        with pytest.raises(httpx.RequestError):
            await post_graphql(
                client=client,
                graphql_url="http://example.test/graphql",
                query="{version}",
                variables={},
            )


@pytest.mark.parametrize(
    "repository",
    [
        {"__typename": "Repository"},
        {"__typename": "RepositoryConnection", "nodes": None},
        {
            "__typename": "Repository",
            "name": "x",
            "location": {"name": "y"},
            "pipelines": [],
            "schedules": [],
            "sensors": [],
            "assetNodes": None,
        },
        {
            "__typename": "Repository",
            "name": "x",
            "location": {"name": "y"},
            "pipelines": [None],
            "schedules": [],
            "sensors": [],
            "assetNodes": [],
        },
    ],
)
@pytest.mark.asyncio
async def test_malformed_repository_is_not_a_healthy_empty_snapshot(repository: object) -> None:
    from kortravelmap.api.dagster_query_service import get_summary
    from kortravelmap.api.settings import ApiSettings

    payload = {
        "data": {
            "repositoryOrError": repository,
            "runsOrError": {"__typename": "Runs", "results": []},
            "activeRunsOrError": {"__typename": "Runs", "results": []},
        }
    }
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
    ) as client:
        response = await get_summary(
            settings=ApiSettings(
                dagster_url="http://example.test", dagster_allowed_hosts=["example.test"]
            ),
            client=client,
            overrides={},
            page_size=30,
        )
    assert response.data.status == "error"
    assert response.data.errors


@pytest.mark.parametrize(
    ("name", "location", "expected"),
    [
        ("__repository__", "kortravelmap.dagster.definitions", "ok"),
        ("foreign_repository", "kortravelmap.dagster.definitions", "error"),
        ("__repository__", "geo_location", "error"),
    ],
)
@pytest.mark.asyncio
async def test_summary_repository_must_match_requested_identity(
    name: str, location: str, expected: str
) -> None:
    from kortravelmap.api.dagster_query_service import get_summary
    from kortravelmap.api.settings import ApiSettings

    payload = {
        "data": {
            "repositoryOrError": {
                "__typename": "Repository",
                "name": name,
                "location": {"name": location},
                "pipelines": [],
                "schedules": [],
                "sensors": [],
                "assetNodes": [],
            },
            "runsOrError": {"__typename": "Runs", "results": []},
            "activeRunsOrError": {"__typename": "Runs", "results": []},
        }
    }
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))
    ) as client:
        response = await get_summary(
            settings=ApiSettings(
                dagster_url="http://example.test", dagster_allowed_hosts=["example.test"]
            ),
            client=client,
            overrides={},
            page_size=30,
        )
    assert response.data.status == expected
    assert bool(response.data.errors) == (expected == "error")
    assert response.data.repository_count == (1 if expected == "ok" else 0)
    assert len(response.data.repositories) == (1 if expected == "ok" else 0)
