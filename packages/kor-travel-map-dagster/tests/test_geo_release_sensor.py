"""``kor_travel_geo_release_sensor`` tick 규칙 (ADR-109 결정 5, T-GR-05).

계획 판정은 공용 함수(``plan_geo_release`` — 통합 테스트
``tests/integration/test_geo_release_plans.py``)가 한다. 여기서는 센서가 그 결과를 **그대로**
따르는지, 그리고 센서 몫(전이·게이트·한 번에 하나·완료 호출)을 본다. client·run storage·geo는
가짜다 — tick의 외부 효과가 그 셋뿐이라는 것도 여기서 센다.
"""

from __future__ import annotations

import asyncio
import dataclasses
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from dagster import DagsterRunStatus, DefaultSensorStatus, RunRequest, SkipReason
from kortravelmap.dto.geo_dataset import DatasetRef
from kortravelmap.infra.geo_release_repo import (
    GeoReleaseCompletion,
    GeoReleaseDataset,
    GeoReleaseItem,
    GeoReleasePlan,
    GeoReleasePlanOutcome,
)

from kortravelmap.dagster import geo_release_sensor as gs
from kortravelmap.dagster.mois_chunked_load import (
    _CONTINUATION_TAGS,
    MOIS_LOAD_AVAILABLE_TAG,
    MOIS_LOAD_BUDGET_TAG,
    MOIS_LOAD_CONVERTED_TAG,
    MOIS_LOAD_JOB_NAME,
    MOIS_LOAD_OUTCOME_TAG,
)
from kortravelmap.dagster.schedules import FEATURE_LOAD_SCHEDULE_SPECS

_TOKEN = "dd1-" + "2" * 32
_CURRENT = DatasetRef(version_token="dv1-" + "b" * 32, data_token=_TOKEN)
_NOW = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)
_KNPS = "feature_place_knps_points_job"
_MCST = "feature_place_mcst_culture_job"
_KNPS_CONFIG = {
    "resources": {
        "knps_point_dataset_key": {"config": {"dataset_key": "knps_restrooms"}},
        "knps_point_records": {"config": {"dataset_key": "knps_restrooms"}},
    }
}
_MOIS_CONFIG: dict[str, Any] | None = None  # MOIS는 fetch run_config다(T-GR-08 — raw가 1:1 아님)
_FESTIVALS = "feature_event_datagokr_cultural_festivals_job"
_FESTIVALS_REPLAY = {
    "resources": {"datagokr_cultural_festivals": {"config": {"source_mode": "replay"}}}
}
# 게이트에 막힌 replay 항목의 예 — launchable 집합에 없는 operation이 replay config를 가진 경우.
_UNLISTED = "feature_place_unlisted_quota_job"
_UNLISTED_REPLAY = {"resources": {"unlisted_records": {"config": {"source_mode": "replay"}}}}


def _item(
    position: int,
    operation_key: str,
    *,
    state: str = "pending",
    run_config: dict[str, Any] | None = None,
    attempt_seq: int = 1,
    run_key: str | None = None,
    requested_at: datetime | None = None,
    datasets: int = 1,
) -> GeoReleaseItem:
    return GeoReleaseItem(
        plan_id=7,
        position=position,
        operation_key=operation_key,
        datasets=tuple(GeoReleaseDataset(100 + i, "p", f"d{i}") for i in range(datasets)),
        run_config=run_config,
        attempt_seq=attempt_seq,
        state=state,
        state_reason=None,
        run_key=run_key,
        dagster_run_id=None,
        requested_at=requested_at,
    )


@dataclass
class _FakeClient:
    """공용 계획 함수의 결과를 돌려주고, 항목 전이를 메모리에서 흉내 낸다."""

    kind: str
    items: dict[int, GeoReleaseItem] = field(default_factory=dict)
    plan_seq: int = 2
    calls: list[str] = field(default_factory=list)
    completions: list[object] = field(default_factory=list)

    def _plan(self) -> GeoReleasePlan:
        return GeoReleasePlan(
            plan_id=7,
            geo_data_token=_TOKEN,
            plan_seq=self.plan_seq,
            geo_version_token=_CURRENT.version_token,
            activated_at=None,
            reference_months=None,
            state="running",
            residual_stale=None,
            sweep_started_at=None,
            observed_at=_NOW,
            completed_at=None,
            items=tuple(self.items[p] for p in sorted(self.items)),
        )

    async def create_geo_release_plan(self, current: DatasetRef) -> GeoReleasePlanOutcome:
        self.calls.append("create")
        plan = self._plan() if self.kind in ("existing", "created") else None
        return GeoReleasePlanOutcome(kind=self.kind, plan=plan)  # type: ignore[arg-type]

    async def get_geo_release_plan(self, plan_id: int) -> GeoReleasePlan:
        return self._plan()

    async def mark_geo_release_item_requested(
        self, plan_id: int, position: int, *, attempt_seq: int, run_key: str
    ) -> bool:
        item = self.items[position]
        if item.state != "pending" or item.attempt_seq != attempt_seq:
            return False
        self.items[position] = dataclasses.replace(
            item, state="requested", run_key=run_key, requested_at=_NOW
        )
        return True

    async def settle_geo_release_item(
        self,
        plan_id: int,
        position: int,
        *,
        state: str,
        reason: str | None = None,
        dagster_run_id: str | None = None,
    ) -> bool:
        self.calls.append(f"settle:{position}:{state}:{reason}")
        self.items[position] = dataclasses.replace(
            self.items[position], state=state, state_reason=reason
        )
        return True

    async def requeue_geo_release_item(self, plan_id: int, position: int) -> int:
        item = self.items[position]
        self.items[position] = dataclasses.replace(
            item, state="pending", attempt_seq=item.attempt_seq + 1, run_key=None
        )
        self.calls.append(f"requeue:{position}")
        return item.attempt_seq + 1

    async def complete_geo_release_plan(
        self, plan_id: int, *, sigungu_resolver: object
    ) -> GeoReleaseCompletion:
        self.completions.append(sigungu_resolver)
        return GeoReleaseCompletion(kind="done", plan=self._plan())


@dataclass
class _Run:
    status: DagsterRunStatus
    tags: dict[str, str] = field(default_factory=dict)
    run_id: str = "run-1"
    run_config: dict[str, Any] = field(default_factory=dict)

    @property
    def is_finished(self) -> bool:
        return self.status in (
            DagsterRunStatus.SUCCESS,
            DagsterRunStatus.FAILURE,
            DagsterRunStatus.CANCELED,
        )


@dataclass
class _Runs:
    worker: str | None = None
    busy: dict[str, str] = field(default_factory=dict)
    by_key: dict[str, _Run] = field(default_factory=dict)

    def active_queue_worker(self) -> str | None:
        return self.worker

    def active_run_for(self, operation_key: str) -> str | None:
        return self.busy.get(operation_key)

    def run_for_key(self, run_key: str) -> _Run | None:
        return self.by_key.get(run_key)


_RESOLVER = object()


@dataclass
class _Geo:
    value: DatasetRef | None = _CURRENT
    reads: int = 0

    async def current(self) -> DatasetRef | None:
        self.reads += 1
        return self.value

    @property
    def sigungu_resolver(self) -> object:
        return _RESOLVER


def _tick(
    client: _FakeClient, runs: _Runs | None = None, geo: _Geo | None = None, *, now: datetime = _NOW
) -> RunRequest | SkipReason:
    return asyncio.run(
        gs.evaluate_geo_release_tick(
            client=client,  # type: ignore[arg-type]
            runs=runs or _Runs(),
            geo=geo or _Geo(),  # type: ignore[arg-type]
            now=now.timestamp(),
        )
    )


# -- 감지: 공용 함수의 결과를 그대로 따른다 ----------------------------------------------------


def test_an_active_queue_worker_skips_before_reading_geo() -> None:
    client, geo = _FakeClient("created"), _Geo()
    result = _tick(client, _Runs(worker="w-1"), geo)
    assert isinstance(result, SkipReason)
    assert geo.reads == 0
    assert client.calls == []


@pytest.mark.parametrize(
    ("value", "needle"),
    [(None, "읽지 못했다"), (DatasetRef(version_token="dv1-" + "a" * 32), "data_token 없음")],
)
def test_no_current_token_never_plans(value: DatasetRef | None, needle: str) -> None:
    client = _FakeClient("created")
    result = _tick(client, geo=_Geo(value))
    assert isinstance(result, SkipReason)
    assert needle in (result.skip_message or "")
    assert client.calls == []


@pytest.mark.parametrize("kind", ["baseline_recorded", "baseline", "already_complete"])
def test_no_plan_outcomes_launch_nothing(kind: str) -> None:
    """빈 상태 + 첫 토큰 → 기준선(계획 0·RunRequest 0), 재빌드·끝난 토큰도 0 — 판정은 공용 함수."""
    client = _FakeClient(kind, items={1: _item(1, _KNPS, run_config=_KNPS_CONFIG)})
    geo = _Geo()
    result = _tick(client, geo=geo)
    assert isinstance(result, SkipReason)
    assert kind in (result.skip_message or "")
    assert client.items[1].state == "pending"
    assert geo.reads == 1  # tick의 geo 효과는 dataset/version 1회


# -- 실행: 한 번에 하나, 게이트 통과만 --------------------------------------------------------


def test_created_plan_launches_the_first_launchable_item_with_release_tags() -> None:
    client = _FakeClient(
        "created",
        items={
            1: _item(1, _UNLISTED, run_config=_UNLISTED_REPLAY),  # replay — 게이트에 막힘
            2: _item(2, _MCST, datasets=13),
            3: _item(3, _KNPS, run_config=_KNPS_CONFIG),
        },
    )
    result = _tick(client)

    assert isinstance(result, RunRequest)
    assert result.job_name == _MCST  # 막힌 replay는 건너뛰고, MCST 13 dataset이 run 1개
    assert result.run_key == f"geo_release/{_TOKEN}/2/{_MCST}/2/1"
    assert result.tags == {
        "kor_travel_map.trigger_kind": "sensor",
        gs.GEO_RELEASE_PLAN_ID_TAG: "7",
        gs.GEO_RELEASE_RUN_KEY_TAG: result.run_key,
    }
    assert client.items[2].state == "requested"
    assert client.items[1].state == "pending"


def test_knps_run_carries_its_dataset_run_config() -> None:
    client = _FakeClient("created", items={1: _item(1, _KNPS, run_config=_KNPS_CONFIG)})
    result = _tick(client)
    assert isinstance(result, RunRequest)
    assert result.run_config == _KNPS_CONFIG


def test_only_blocked_items_left_reports_the_reason() -> None:
    client = _FakeClient("existing", items={1: _item(1, _UNLISTED, run_config=_UNLISTED_REPLAY)})
    result = _tick(client)
    assert isinstance(result, SkipReason)
    assert "replay_not_launchable_before_t_gr_08" in (result.skip_message or "")


def test_a_launchable_replay_item_runs_with_its_replay_config() -> None:
    """T-GR-08 뒤 replay 항목(축제)은 게이트를 지나 replay run_config 그대로 나간다."""
    client = _FakeClient("created", items={1: _item(1, _FESTIVALS, run_config=_FESTIVALS_REPLAY)})
    result = _tick(client)
    assert isinstance(result, RunRequest)
    assert (result.job_name, result.run_config) == (_FESTIVALS, _FESTIVALS_REPLAY)


def test_a_mois_item_runs_in_fetch_mode() -> None:
    """MOIS는 replay가 아니다 — run_config 없이(fetch) 나간다."""
    client = _FakeClient("created", items={1: _item(1, MOIS_LOAD_JOB_NAME)})
    result = _tick(client)
    assert isinstance(result, RunRequest)
    assert result.job_name == MOIS_LOAD_JOB_NAME
    assert not result.run_config


def test_one_run_in_flight_at_a_time() -> None:
    key = "geo_release/x/1/a/1/1"
    client = _FakeClient(
        "existing",
        items={
            1: _item(1, _MCST, state="requested", run_key=key, requested_at=_NOW),
            2: _item(2, _KNPS, run_config=_KNPS_CONFIG),
        },
    )
    result = _tick(client, _Runs(by_key={key: _Run(DagsterRunStatus.STARTED)}))
    assert isinstance(result, SkipReason)
    assert client.items[2].state == "pending"


def test_a_running_job_of_the_same_operation_blocks_the_launch() -> None:
    client = _FakeClient("existing", items={1: _item(1, _KNPS, run_config=_KNPS_CONFIG)})
    result = _tick(client, _Runs(busy={_KNPS: "manual-run"}))
    assert isinstance(result, SkipReason)
    assert client.items[1].state == "pending"


# -- 전이 --------------------------------------------------------------------------------------


def test_success_settles_done_and_the_next_item_launches() -> None:
    key = "geo_release/x/1/a/1/1"
    client = _FakeClient(
        "existing",
        items={
            1: _item(1, _MCST, state="requested", run_key=key, requested_at=_NOW),
            2: _item(2, _KNPS, run_config=_KNPS_CONFIG),
        },
    )
    result = _tick(client, _Runs(by_key={key: _Run(DagsterRunStatus.SUCCESS)}))
    assert client.items[1].state == "done"
    assert isinstance(result, RunRequest)
    assert result.job_name == _KNPS


def test_a_failed_run_is_retried_once_then_fails() -> None:
    key = "geo_release/x/1/a/1/1"
    client = _FakeClient(
        "existing", items={1: _item(1, _MCST, state="requested", run_key=key, requested_at=_NOW)}
    )
    runs = _Runs(by_key={key: _Run(DagsterRunStatus.FAILURE)})
    retried = _tick(client, runs)
    assert client.items[1].attempt_seq == 2
    assert isinstance(retried, RunRequest)
    assert retried.run_key.endswith("/1/2")  # 새 attempt_seq → 새 run_key(실제 run이 생긴다)
    runs.by_key[retried.run_key] = _Run(DagsterRunStatus.FAILURE)
    _tick(client, runs)
    assert (client.items[1].state, client.items[1].state_reason) == ("failed", "run_failed")


def test_a_request_without_a_run_for_three_ticks_is_run_not_launched() -> None:
    old = _NOW - timedelta(seconds=gs.GEO_RELEASE_RUN_LAUNCH_TIMEOUT_SECONDS + 1)
    recent = _NOW - timedelta(seconds=gs.GEO_RELEASE_SENSOR_INTERVAL_SECONDS)
    client = _FakeClient(
        "existing",
        items={
            1: _item(1, _MCST, state="requested", run_key="k1", requested_at=old),
            2: _item(2, _KNPS, state="requested", run_key="k2", requested_at=recent),
        },
    )
    _tick(client)
    assert (client.items[1].state, client.items[1].state_reason) == (
        "failed",
        "run_not_launched",
    )
    assert client.items[2].state == "requested"


def _mois_run(*, converted: str, budget: str = "3600", available: str = "3600") -> _Run:
    return _Run(
        DagsterRunStatus.SUCCESS,
        tags={
            MOIS_LOAD_OUTCOME_TAG: "budget_exhausted",
            MOIS_LOAD_CONVERTED_TAG: converted,
            MOIS_LOAD_BUDGET_TAG: budget,
            MOIS_LOAD_AVAILABLE_TAG: available,
        },
    )


# MOIS 이어 달리기 — T-GR-08부터 MOIS 항목은 fetch run_config로 나가므로 운영 경로다.


def test_mois_budget_exhausted_is_continued_not_done() -> None:
    client = _FakeClient(
        "existing",
        items={
            1: _item(
                1,
                MOIS_LOAD_JOB_NAME,
                state="requested",
                run_key="k",
                requested_at=_NOW,
                run_config=_MOIS_CONFIG,
            )
        },
    )
    result = _tick(client, _Runs(by_key={"k": _mois_run(converted="500")}))
    # 이어 달리기 = 다음 attempt로 되돌리고, 게이트가 없으니(fetch) 같은 tick에 그 attempt를 낸다.
    assert (client.items[1].state, client.items[1].attempt_seq) == ("requested", 2)
    assert isinstance(result, RunRequest)
    assert result.run_key is not None
    assert result.run_key.endswith("/2")


def test_mois_budget_exhausted_without_progress_fails() -> None:
    client = _FakeClient(
        "existing",
        items={
            1: _item(
                1,
                MOIS_LOAD_JOB_NAME,
                state="requested",
                run_key="k",
                requested_at=_NOW,
                run_config=_MOIS_CONFIG,
            )
        },
    )
    _tick(client, _Runs(by_key={"k": _mois_run(converted="0")}))
    assert (client.items[1].state, client.items[1].state_reason) == ("failed", "no_progress")


# -- 완료 --------------------------------------------------------------------------------------


def test_all_terminal_items_complete_the_plan_with_the_geo_resolver() -> None:
    """DISABLED(skipped) 항목이 섞여도 실행 항목이 끝나면 완료 — resolver는 이 tick의 geo에서."""
    skipped = dataclasses.replace(
        _item(2, "feature_place_standard_special_streets_job"),
        state="skipped",
        state_reason="disabled",
    )
    client = _FakeClient(
        "existing", items={1: _item(1, _MCST, state="done"), 2: skipped}
    )
    result = _tick(client)
    assert isinstance(result, SkipReason)
    assert client.completions == [_RESOLVER]


# -- 선언 --------------------------------------------------------------------------------------


def test_sensor_declaration_is_stopped_light_and_covers_every_feature_load_job() -> None:
    sensor = gs.kor_travel_geo_release_sensor
    assert sensor.default_status == DefaultSensorStatus.STOPPED
    assert sensor.minimum_interval_seconds == gs.GEO_RELEASE_SENSOR_INTERVAL_SECONDS
    # reverse_geocoder 등 무거운 resource를 초기화하지 않는다 — DB client 하나뿐이다.
    assert set(sensor.required_resource_keys) == {"kor_travel_map_client"}
    assert {target.job_name for target in sensor.targets} == {
        spec.job_name for spec in FEATURE_LOAD_SCHEDULE_SPECS
    }


def test_mois_continuation_runs_are_not_release_runs() -> None:
    assert gs.GEO_RELEASE_PLAN_ID_TAG not in _CONTINUATION_TAGS
    assert gs.GEO_RELEASE_PLAN_ID_TAG.startswith("kor_travel_map.")


def test_a_canceled_run_is_not_retried() -> None:
    """운영자의 취소를 존중한다 — 재요청 없이 ``failed(canceled)``."""
    client = _FakeClient(
        "existing",
        items={1: _item(1, _MCST, state="requested", run_key="k", requested_at=_NOW)},
    )
    _tick(client, _Runs(by_key={"k": _Run(DagsterRunStatus.CANCELED)}))
    assert (client.items[1].state, client.items[1].state_reason, client.items[1].attempt_seq) == (
        "failed",
        "canceled",
        1,
    )


def test_a_replanned_token_gets_a_new_run_key() -> None:
    """A→B→A — 두 번째 A 계획(``plan_seq=2``)의 run_key는 첫 계획과 달라 실제 run이 생긴다."""
    first = _FakeClient("created", items={1: _item(1, _MCST)}, plan_seq=1)
    first_request = _tick(first)
    second = _FakeClient("created", items={1: _item(1, _MCST)}, plan_seq=2)
    second_request = _tick(second)
    assert isinstance(first_request, RunRequest)
    assert isinstance(second_request, RunRequest)
    assert f"/{_TOKEN}/1/" in (first_request.run_key or "")
    assert f"/{_TOKEN}/2/" in (second_request.run_key or "")
    assert first_request.run_key != second_request.run_key


# -- 실제 run storage(``DagsterInstance.ephemeral``) --------------------------------------------


def _add_run(
    instance: Any, *, run_id: str, job_name: str, status: DagsterRunStatus, tags: dict[str, str]
) -> None:
    from dagster import DagsterRun

    instance.add_run(DagsterRun(job_name=job_name, run_id=run_id, tags=tags, status=status))


def test_instance_lookups_use_the_release_tags() -> None:
    from dagster import DagsterInstance

    from kortravelmap.dagster.run_scope import CODE_LOCATION_RUN_TAG, MAP_CODE_LOCATION_NAME

    with DagsterInstance.ephemeral() as instance:
        _add_run(
            instance,
            run_id="release-1",
            job_name=_KNPS,
            status=DagsterRunStatus.STARTED,
            tags={
                "kor_travel_map.operation_key": _KNPS,
                gs.GEO_RELEASE_RUN_KEY_TAG: "geo_release/x/1/knps/1/1",
                gs.GEO_RELEASE_PLAN_ID_TAG: "7",
            },
        )
        _add_run(
            instance,
            run_id="done-1",
            job_name=_MCST,
            status=DagsterRunStatus.SUCCESS,
            tags={"kor_travel_map.operation_key": _MCST},
        )
        _add_run(
            instance,
            run_id="worker-1",
            job_name="feature_update_request_worker",
            status=DagsterRunStatus.STARTED,
            tags={CODE_LOCATION_RUN_TAG: MAP_CODE_LOCATION_NAME},
        )
        runs = gs._InstanceRuns(instance)  # noqa: SLF001

        found = runs.run_for_key("geo_release/x/1/knps/1/1")
        assert found is not None
        assert found.run_id == "release-1"
        assert runs.run_for_key("geo_release/x/1/knps/1/2") is None
        assert runs.active_run_for(_KNPS) == "release-1"
        assert runs.active_run_for(_MCST) is None  # 끝난 run은 활성이 아니다
        assert runs.active_queue_worker() == "worker-1"


def test_mois_continuation_sensor_leaves_release_runs_to_the_release_sensor() -> None:
    """이중 continuation 체인 방지 — 마지막 MOIS run이 릴리스 run이면 이어 달리기 센서는 Skip."""
    from dagster import DagsterInstance, build_sensor_context

    from kortravelmap.dagster.mois_chunked_load import mois_load_continuation_sensor

    tags = {
        "kor_travel_map.operation_key": MOIS_LOAD_JOB_NAME,
        MOIS_LOAD_OUTCOME_TAG: "budget_exhausted",
        MOIS_LOAD_CONVERTED_TAG: "500",
    }
    with DagsterInstance.ephemeral() as instance:
        _add_run(
            instance,
            run_id="mois-release",
            job_name=MOIS_LOAD_JOB_NAME,
            status=DagsterRunStatus.SUCCESS,
            tags={**tags, gs.GEO_RELEASE_PLAN_ID_TAG: "7"},
        )
        result = mois_load_continuation_sensor(build_sensor_context(instance=instance))
        assert isinstance(result, SkipReason)
        assert "릴리스" in (result.skip_message or "")
    with DagsterInstance.ephemeral() as instance:
        _add_run(
            instance,
            run_id="mois-plain",
            job_name=MOIS_LOAD_JOB_NAME,
            status=DagsterRunStatus.SUCCESS,
            tags=tags,
        )
        # 릴리스 run이 아니면 종전대로 이어 달린다.
        assert isinstance(
            mois_load_continuation_sensor(build_sensor_context(instance=instance)), RunRequest
        )
