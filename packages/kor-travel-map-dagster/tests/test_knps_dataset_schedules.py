"""KNPS operation마다 결박된 dataset **전부**가 자기 schedule을 갖는다(#1450).

KNPS는 operation 하나(job 하나)에 dataset 다섯이 결박돼 있고 asset은 run 1회에 dataset
1개만 적재한다. 종전 schedule은 운영자 노브(``knps_*_dataset_key``) 한 값만 돌렸다 — 나머지
넷은 아무도 갱신 요청을 넣지 않아 prod에서 한 번도 적재되지 않았다(국립공원 경계 area 0건).

여기서는 helper가 아니라 **빌드된 definitions의 schedule 객체**를 평가한다. 기대 집합은
provider registry(``KNPS_PLACE_DATASETS``·``KNPS_GEOMETRY_DATASETS``)에서 유도한다 — dataset이
registry에 늘면 schedule 없이는 이 검사가 먼저 빨개진다.
"""

from __future__ import annotations

import pytest
from dagster import DefaultScheduleStatus, build_schedule_context
from kortravelmap.providers.knps import KNPS_GEOMETRY_DATASETS, KNPS_PLACE_DATASETS
from kortravelmap.providers.knps import PROVIDER_NAME as KNPS_PROVIDER_NAME

from kortravelmap.dagster.definitions import defs
from kortravelmap.dagster.feature_operation_tracking import (
    EXECUTION_SCOPES_TAG,
    DeclaredExecutionScope,
    declared_execution_scopes,
)
from kortravelmap.dagster.schedules import KST_TIMEZONE

pytestmark = pytest.mark.filterwarnings(
    "ignore:Parameter `owners` of initializer `SensorDefinition.__init__`"
    ".*:dagster_shared.utils.warnings.BetaWarning"
)

_FAMILIES = (
    pytest.param(
        "feature_place_knps_points_job",
        ("knps_point_dataset_key", "knps_point_records"),
        frozenset(KNPS_PLACE_DATASETS),
        id="points",
    ),
    pytest.param(
        "feature_geometry_knps_records_job",
        ("knps_geometry_dataset_key", "knps_geometry_records"),
        frozenset(KNPS_GEOMETRY_DATASETS),
        id="geometry",
    ),
)


def _schedules_for(job_name: str) -> list:  # type: ignore[type-arg]
    return [
        schedule
        for schedule in defs.get_repository_def().schedule_defs
        if schedule.job_name == job_name
    ]


@pytest.mark.parametrize(("job_name", "resources", "dataset_keys"), _FAMILIES)
def test_every_registered_knps_dataset_has_exactly_one_schedule(
    job_name: str,
    resources: tuple[str, str],
    dataset_keys: frozenset[str],
) -> None:
    # 전제: registry가 비면 아래가 공회전한다.
    assert len(dataset_keys) >= 2

    covered: dict[str, str] = {}
    for schedule in _schedules_for(job_name):
        tick = schedule.evaluate_tick(build_schedule_context())
        assert len(tick.run_requests) == 1, schedule.name
        request = tick.run_requests[0]
        configured = {
            resource: request.run_config["resources"][resource]["config"]["dataset_key"]
            for resource in resources
        }
        # 두 resource가 같은 dataset을 가리킨다 — 하나만 바뀌면 fetch와 변환이 갈라진다.
        assert len(set(configured.values())) == 1, (schedule.name, configured)
        dataset_key = next(iter(configured.values()))
        assert dataset_key not in covered, (
            f"{dataset_key}를 두 schedule이 적재한다: {covered[dataset_key]}, {schedule.name}"
        )
        covered[dataset_key] = schedule.name

        # 실행 manifest 선언이 run_config와 같은 dataset이어야 한다 — 다르면 guard가
        # 실행하지 않는 member를 running으로 만들고 reconcile이 operation을 실패시킨다.
        assert declared_execution_scopes(request.tags, boundary="test") == (
            DeclaredExecutionScope(
                provider=KNPS_PROVIDER_NAME,
                dataset_key=dataset_key,
                sync_scope="dataset_wide",
            ),
        )
        assert request.tags[EXECUTION_SCOPES_TAG] == schedule.tags[EXECUTION_SCOPES_TAG]
        assert schedule.tags["kor_travel_map.operation_key"] == job_name
        assert schedule.tags["kor_travel_map.trigger_kind"] == "schedule"
        assert schedule.execution_timezone == KST_TIMEZONE
        assert schedule.default_status == DefaultScheduleStatus.STOPPED

    assert set(covered) == dataset_keys


@pytest.mark.parametrize(("job_name", "resources", "dataset_keys"), _FAMILIES)
def test_knps_dataset_schedules_fire_at_distinct_times(
    job_name: str,
    resources: tuple[str, str],
    dataset_keys: frozenset[str],
) -> None:
    """같은 job의 dataset schedule이 한 시각에 몰리지 않는다(GEO_HEAVY pool 한 슬롯)."""
    del resources, dataset_keys
    crons = [schedule.cron_schedule for schedule in _schedules_for(job_name)]
    assert len(crons) == len(set(crons)), crons
