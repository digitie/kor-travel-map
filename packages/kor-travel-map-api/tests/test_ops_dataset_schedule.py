"""dataset grid Dagster schedule projection 회귀 (#678)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, cast

import httpx
import pytest
from kortravelmap.providers.feature_operation_registry import (
    FEATURE_OPERATION_IDENTITY_TAG,
    FEATURE_OPERATION_REGISTRY_VERSION_TAG,
    feature_operation_definition_tags,
    resolve_feature_operation_identity,
)
from kortravelmap.providers.mcst import MCST_FILE_DATASETS, MCST_PROVIDER_NAME

from kortravelmap.api.ops_dataset_schedule import _parse, load_dataset_schedule_index
from kortravelmap.api.settings import ApiSettings


def _definition_tag_list(job_name: str) -> list[dict[str, str]]:
    identity = resolve_feature_operation_identity(job_name=job_name)
    assert identity is not None
    return [
        {"key": key, "value": value}
        for key, value in feature_operation_definition_tags(identity).items()
    ]


@pytest.mark.unit
def test_schedule_projection_uses_exact_tags_and_earliest_running_tick() -> None:
    definition_tags = _definition_tag_list("feature_place_mois_licenses_job")
    payload = {
        "data": {
            "repositoriesOrError": {
                "__typename": "RepositoryConnection",
                "nodes": [
                    {
                        "schedules": [
                            {
                                "name": "stopped",
                                "pipelineName": "feature_place_mois_licenses_job",
                                "tags": definition_tags,
                                "scheduleState": {"status": "STOPPED"},
                                "futureTicks": {"results": [{"timestamp": 200.0}]},
                            },
                            {
                                "name": "running-late",
                                "pipelineName": "feature_place_mois_licenses_job",
                                "tags": definition_tags,
                                "scheduleState": {"status": "RUNNING"},
                                "futureTicks": {"results": [{"timestamp": 300.0}]},
                            },
                            {
                                "name": "running-early",
                                "pipelineName": "feature_place_mois_licenses_job",
                                "tags": definition_tags,
                                "scheduleState": {"status": "RUNNING"},
                                "futureTicks": {"results": [{"timestamp": 100.0}]},
                            },
                            {
                                "name": "name-looks-related-but-has-no-tags",
                                "pipelineName": "arbitrary_user_code_job",
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
def test_mcst_schedule_projection_expands_all_13_canonical_pairs() -> None:
    schedule_name = "feature_place_mcst_culture_monthly_schedule"
    next_tick = 200.0
    payload = {
        "data": {
            "repositoriesOrError": {
                "__typename": "RepositoryConnection",
                "nodes": [
                    {
                        "schedules": [
                            {
                                "name": schedule_name,
                                "pipelineName": "feature_place_mcst_culture_job",
                                "tags": _definition_tag_list(
                                    "feature_place_mcst_culture_job"
                                ),
                                "scheduleState": {"status": "RUNNING"},
                                "futureTicks": {
                                    "results": [{"timestamp": next_tick}]
                                },
                            }
                        ]
                    }
                ],
            }
        }
    }

    index = _parse(payload)

    assert index.source_status == "ok"
    assert index.errors == ()
    expected_dataset_keys = {
        spec.dataset_key for spec in MCST_FILE_DATASETS.values()
    }
    assert {
        dataset_key
        for provider, dataset_key in index.by_dataset
        if provider == MCST_PROVIDER_NAME
    } == expected_dataset_keys
    for dataset_key in expected_dataset_keys:
        state = index.for_dataset(MCST_PROVIDER_NAME, dataset_key)
        assert state.schedule_names == (schedule_name,)
        assert state.active_schedule_names == (schedule_name,)
        assert state.status == "RUNNING"
        assert state.next_scheduled_at == datetime.fromtimestamp(next_tick, tz=UTC)


@pytest.mark.unit
def test_schedule_projection_rejects_unknown_identity_and_ignores_scalar_fallback() -> None:
    valid_tags = {
        item["key"]: item["value"]
        for item in _definition_tag_list("feature_place_mois_licenses_job")
    }
    forged_identity = json.loads(valid_tags[FEATURE_OPERATION_IDENTITY_TAG])
    forged_identity["job"] = "unknown_feature_job"
    valid_tags[FEATURE_OPERATION_IDENTITY_TAG] = json.dumps(
        forged_identity,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    payload = {
        "data": {
            "repositoriesOrError": {
                "__typename": "RepositoryConnection",
                "nodes": [
                    {
                        "schedules": [
                            {
                                "name": "forged",
                                "pipelineName": "unknown_feature_job",
                                "tags": [
                                    {"key": key, "value": value}
                                    for key, value in valid_tags.items()
                                ],
                                "scheduleState": {"status": "RUNNING"},
                                "futureTicks": {"results": []},
                            },
                            {
                                "name": "scalar-only",
                                "pipelineName": "arbitrary_user_code_job",
                                "tags": [
                                    {
                                        "key": "kor_travel_map.provider",
                                        "value": "python-mois-api",
                                    },
                                    {
                                        "key": "kor_travel_map.dataset_key",
                                        "value": "mois_license_features_bulk",
                                    },
                                ],
                                "scheduleState": {"status": "RUNNING"},
                                "futureTicks": {"results": []},
                            },
                        ]
                    }
                ],
            }
        }
    }

    index = _parse(payload)

    assert index.source_status == "error"
    assert index.errors == ("forged: manifest에 없는 job identity",)
    assert index.by_dataset == {}
    state = index.for_dataset("python-mois-api", "mois_license_features_bulk")
    assert state.basis == "unknown"


@pytest.mark.unit
def test_schedule_projection_rejects_partial_identity_version_tags() -> None:
    valid_tags = {
        item["key"]: item["value"]
        for item in _definition_tag_list("feature_place_mois_licenses_job")
    }
    payload = {
        "data": {
            "repositoriesOrError": {
                "__typename": "RepositoryConnection",
                "nodes": [
                    {
                        "schedules": [
                            {
                                "name": "partial",
                                "pipelineName": "feature_place_mois_licenses_job",
                                "tags": [
                                    {
                                        "key": FEATURE_OPERATION_REGISTRY_VERSION_TAG,
                                        "value": "v1-deadbeefdead",
                                    }
                                ],
                                "scheduleState": {"status": "RUNNING"},
                                "futureTicks": {"results": []},
                            },
                            {
                                "name": "malformed",
                                "pipelineName": "feature_place_mois_licenses_job",
                                "tags": [
                                    {
                                        "key": FEATURE_OPERATION_IDENTITY_TAG,
                                        "value": "{",
                                    },
                                    {
                                        "key": FEATURE_OPERATION_REGISTRY_VERSION_TAG,
                                        "value": valid_tags[
                                            FEATURE_OPERATION_REGISTRY_VERSION_TAG
                                        ],
                                    },
                                ],
                                "scheduleState": {"status": "RUNNING"},
                                "futureTicks": {"results": []},
                            }
                        ]
                    }
                ],
            }
        }
    }

    index = _parse(payload)

    assert index.source_status == "error"
    assert index.errors == (
        "partial: identity/version tag가 함께 존재하지 않음",
        "malformed: canonical identity JSON이 아님",
    )
    assert index.by_dataset == {}


@pytest.mark.unit
def test_schedule_projection_rejects_registered_job_without_identity_tags() -> None:
    payload = {
        "data": {
            "repositoriesOrError": {
                "__typename": "RepositoryConnection",
                "nodes": [
                    {
                        "schedules": [
                            {
                                "name": "registered-without-tags",
                                "pipelineName": "feature_place_mois_licenses_job",
                                "tags": [],
                                "scheduleState": {"status": "RUNNING"},
                                "futureTicks": {"results": []},
                            }
                        ]
                    }
                ],
            }
        }
    }

    index = _parse(payload)

    assert index.source_status == "error"
    assert index.errors == (
        "registered-without-tags: 등록 feature job의 canonical identity/version tag 누락",
    )
    assert index.by_dataset == {}


@pytest.mark.unit
def test_schedule_projection_rejects_valid_identity_attached_to_other_job() -> None:
    payload = {
        "data": {
            "repositoriesOrError": {
                "__typename": "RepositoryConnection",
                "nodes": [
                    {
                        "schedules": [
                            {
                                "name": "cross-attached",
                                "pipelineName": (
                                    "feature_weather_kma_short_forecast_job"
                                ),
                                "tags": _definition_tag_list(
                                    "feature_place_mois_licenses_job"
                                ),
                                "scheduleState": {"status": "RUNNING"},
                                "futureTicks": {"results": []},
                            }
                        ]
                    }
                ],
            }
        }
    }

    index = _parse(payload)

    assert index.source_status == "error"
    assert index.errors == (
        "cross-attached: identity job/pipelineName 불일치",
    )
    assert index.by_dataset == {}


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
        assert "pipelineName" in query
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
