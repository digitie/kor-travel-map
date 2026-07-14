"""dataset grid Dagster schedule projection 회귀 (#678)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast

import httpx
import pytest

from kortravelmap.api.ops_dataset_schedule import _parse, load_dataset_schedule_index
from kortravelmap.api.settings import ApiSettings


@pytest.mark.unit
def test_schedule_projection_uses_exact_tags_and_earliest_running_tick() -> None:
    payload = {
        "data": {
            "repositoriesOrError": {
                "__typename": "RepositoryConnection",
                "nodes": [
                    {
                        "schedules": [
                            {
                                "name": "stopped",
                                "tags": [
                                    {
                                        "key": "kor_travel_map.provider",
                                        "value": "mois",
                                    },
                                    {
                                        "key": "kor_travel_map.dataset_key",
                                        "value": "mois_license_features_bulk",
                                    },
                                ],
                                "scheduleState": {"status": "STOPPED"},
                                "futureTicks": {"results": [{"timestamp": 200.0}]},
                            },
                            {
                                "name": "running-late",
                                "tags": [
                                    {
                                        "key": "kor_travel_map.provider",
                                        "value": "mois",
                                    },
                                    {
                                        "key": "kor_travel_map.dataset_key",
                                        "value": "mois_license_features_bulk",
                                    },
                                ],
                                "scheduleState": {"status": "RUNNING"},
                                "futureTicks": {"results": [{"timestamp": 300.0}]},
                            },
                            {
                                "name": "running-early",
                                "tags": [
                                    {
                                        "key": "kor_travel_map.provider",
                                        "value": "mois",
                                    },
                                    {
                                        "key": "kor_travel_map.dataset_key",
                                        "value": "mois_license_features_bulk",
                                    },
                                ],
                                "scheduleState": {"status": "RUNNING"},
                                "futureTicks": {"results": [{"timestamp": 100.0}]},
                            },
                            {
                                "name": "name-looks-related-but-has-no-tags",
                                "tags": [],
                                "scheduleState": {"status": "RUNNING"},
                                "futureTicks": {"results": [{"timestamp": 1.0}]},
                            },
                        ]
                    }
                ],
            }
        }
    }

    index = _parse(payload)

    state = index.for_dataset("python-mois-api", "mois_license_features_bulk")
    assert index.source_status == "ok"
    assert state.schedule_names == (
        "running-early",
        "running-late",
        "stopped",
    )
    assert state.active_schedule_names == ("running-early", "running-late")
    assert state.status == "RUNNING"
    assert state.next_scheduled_at == datetime.fromtimestamp(100, tz=UTC)


@pytest.mark.unit
def test_schedule_projection_degrades_graphql_error_to_unknown() -> None:
    index = _parse({"errors": [{"message": "Dagster unavailable"}]})

    assert index.source_status == "error"
    assert index.errors == ("Dagster unavailable",)
    state = index.for_dataset("python-mois-api", "mois_license_features_bulk")
    assert state.basis == "unknown"
    assert state.next_scheduled_at is None


@pytest.mark.unit
async def test_schedule_loader_calls_graphql_once_with_required_projection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api import ops_dataset_schedule as schedule_module

    calls = 0

    async def _post_graphql(**kwargs: Any) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        query = str(kwargs["query"])
        assert "tags { key value }" in query
        assert "futureTicks(limit: 1)" in query
        return {
            "data": {
                "repositoriesOrError": {
                    "__typename": "RepositoryConnection",
                    "nodes": [],
                }
            }
        }

    monkeypatch.setattr(
        schedule_module.dagster_graphql, "post_graphql", _post_graphql
    )

    index = await load_dataset_schedule_index(
        settings=ApiSettings(),
        client=cast(Any, object()),
    )

    assert calls == 1
    assert index.source_status == "ok"


@pytest.mark.unit
@pytest.mark.parametrize(
    ("failure", "expected_status"),
    [
        (httpx.ConnectError("dagster down"), "unavailable"),
        ({}, "error"),
    ],
)
async def test_schedule_loader_degrades_transport_and_invalid_payload(
    monkeypatch: pytest.MonkeyPatch,
    failure: Exception | dict[str, Any],
    expected_status: str,
) -> None:
    from kortravelmap.api import ops_dataset_schedule as schedule_module

    async def _post_graphql(**_kwargs: Any) -> dict[str, Any]:
        if isinstance(failure, Exception):
            raise failure
        return failure

    monkeypatch.setattr(
        schedule_module.dagster_graphql, "post_graphql", _post_graphql
    )

    index = await load_dataset_schedule_index(
        settings=ApiSettings(),
        client=cast(Any, object()),
    )

    assert index.source_status == expected_status
    assert index.for_dataset("python-mois-api", "mois_license_features_bulk").basis == (
        "unknown"
    )
