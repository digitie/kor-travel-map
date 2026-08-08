"""dataset grid의 DB operation-key schedule projection 회귀."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from kortravelmap.api.ops_dataset_schedule import OPERATION_KEY_TAG, _parse


def _tags(operation_key: str) -> list[dict[str, str]]:
    return [{"key": OPERATION_KEY_TAG, "value": operation_key}]


def _payload(schedules: list[dict[str, object]]) -> dict[str, object]:
    return {
        "data": {
            "repositoriesOrError": {
                "__typename": "RepositoryConnection",
                "nodes": [{"schedules": schedules}],
            }
        }
    }


@pytest.mark.unit
def test_schedule_projection_uses_operation_key_and_earliest_running_tick() -> None:
    operation_key = "feature_place_mois_licenses_job"
    index = _parse(
        _payload(
            [
                {
                    "name": "stopped",
                    "pipelineName": operation_key,
                    "tags": _tags(operation_key),
                    "scheduleState": {"status": "STOPPED"},
                    "futureTicks": {"results": [{"timestamp": 200.0}]},
                },
                {
                    "name": "running-late",
                    "pipelineName": operation_key,
                    "tags": _tags(operation_key),
                    "scheduleState": {"status": "RUNNING"},
                    "futureTicks": {"results": [{"timestamp": 300.0}]},
                },
                {
                    "name": "running-early",
                    "pipelineName": operation_key,
                    "tags": _tags(operation_key),
                    "scheduleState": {"status": "RUNNING"},
                    "futureTicks": {"results": [{"timestamp": 100.0}]},
                },
            ]
        )
    )

    state = index.for_operation_keys((operation_key,))
    assert index.source_status == "ok"
    assert state.basis == "dagster_operation_key_tag"
    assert state.schedule_names == ("running-early", "running-late", "stopped")
    assert state.active_schedule_names == ("running-early", "running-late")
    assert state.status == "RUNNING"
    assert state.next_scheduled_at == datetime.fromtimestamp(100, tz=UTC)


@pytest.mark.unit
def test_schedule_projection_rejects_missing_or_mismatched_operation_key() -> None:
    index = _parse(
        _payload(
            [
                {
                    "name": "untagged",
                    "pipelineName": "feature_place_mois_licenses_job",
                    "tags": [],
                    "scheduleState": {"status": "RUNNING"},
                    "futureTicks": {"results": [{"timestamp": 1.0}]},
                },
                {
                    "name": "forged",
                    "pipelineName": "different_job",
                    "tags": _tags("feature_place_mois_licenses_job"),
                    "scheduleState": {"status": "RUNNING"},
                    "futureTicks": {"results": [{"timestamp": 1.0}]},
                },
            ]
        )
    )

    state = index.for_operation_keys(("feature_place_mois_licenses_job",))
    assert state.basis == "not_scheduled"
    assert state.schedule_names == ()


@pytest.mark.unit
def test_operation_key_summary_aggregates_multiple_db_members_without_pair_tags() -> None:
    operation_key = "feature_place_mcst_culture_job"
    index = _parse(
        _payload(
            [
                {
                    "name": "mcst-monthly",
                    "pipelineName": operation_key,
                    "tags": _tags(operation_key),
                    "scheduleState": {"status": "RUNNING"},
                    "futureTicks": {"results": [{"timestamp": 200.0}]},
                }
            ]
        )
    )

    state = index.for_operation_keys((operation_key, operation_key))
    assert state.schedule_names == ("mcst-monthly",)
    assert state.next_scheduled_at == datetime.fromtimestamp(200, tz=UTC)
