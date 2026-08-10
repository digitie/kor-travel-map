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
def test_schedule_projection_reports_identity_drift_instead_of_swallowing_it() -> None:
    """tag 누락·job 불일치는 **관측 가능한 오류**여야 한다.

    앞 판은 둘 다 조용히 `continue`로 버리고 `source_status="ok"`를 무조건 냈다.
    그러면 실재하는 schedule이 붙은 dataset이 `basis="not_scheduled"`와
    "소스는 건강하다"를 **동시에** 단언한다 — 둘 다 거짓이고, 운영자가 멈춘 적재를
    알아챌 축이 사라진다(적대 리뷰 10라운드). 응답 모델은 error 상태와 errors
    배열을 계속 선언하고 있었으므로, 계약이 표현할 수 있다고 말하는 사실을 구현이
    만들지 못하는 상태이기도 했다.

    드리프트로 셀 대상은 **code handler가 있는 feature 적재 job**뿐이다 — 무관한
    schedule의 tag 부재까지 오류로 세면 그 채널이 노이즈로 죽는다.
    """
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

    assert index.source_status == "error"
    assert len(index.errors) == 2
    assert any("tag가 없다" in message for message in index.errors)
    assert any("job은 'different_job'이다" in message for message in index.errors)

    # 잘못 붙은 schedule을 operation에 귀속시키지 않는 것은 그대로다.
    state = index.for_operation_keys(("feature_place_mois_licenses_job",))
    assert state.schedule_names == ()
    # 소스가 error인데 "not_scheduled"라 단정하지 않는다 — 모르는 것은 모른다고 한다.
    assert state.basis == "unknown"


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
