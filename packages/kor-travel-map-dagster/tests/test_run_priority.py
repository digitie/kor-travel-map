"""공용 run 큐 우선순위 ``dagster/priority`` (수집 실패 감사 2026-11-23 §2.6 #9·§4 #13).

규칙(소유자 결정 2026-11-24, 정본 kor-travel-docker-manager
``docs/dagster-tenant-fairness.md``): 10 = 1시간 미만 주기 정기 수집·상태 적재,
5 = 1시간 이상·하루 미만 주기 정기 수집, 0 = 그 밖(하루 이상·정리·유지보수·검증·수동).

이 시험은 표(``run_priority.JOB_RUN_PRIORITIES``)를 다시 읽지 않고 **코드 cron에서
기대값을 따로 유도**해 표와 맞춰 본다. 그리고 schedule tick·sensor 요청이 daemon의
run tag 합성을 거친 뒤에도 값이 남는지 본다.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from dagster import DagsterInstance, DagsterRunStatus, RunRequest, build_schedule_context
from dagster._utils.schedules import cron_string_iterator

from kortravelmap.dagster import mois_chunked_load, run_priority, sensors
from kortravelmap.dagster.definitions import defs
from kortravelmap.dagster.feature_operation_completion import feature_operation_completion_job
from kortravelmap.dagster.feature_operation_sensors import _completion_run_request
from kortravelmap.dagster.mois_source_sync import MOIS_SOURCE_SYNC_CRON
from kortravelmap.dagster.run_heartbeat import RUN_HEARTBEAT_JOB_TAGS
from kortravelmap.dagster.run_priority import (
    JOB_RUN_PRIORITIES,
    RUN_PRIORITY_TAG,
    RUN_PRIORITY_VALUES,
    run_priority_tags,
)
from kortravelmap.dagster.schedules import (
    FEATURE_LOAD_SCHEDULE_SPECS,
    KNPS_DATASET_SCHEDULE_SPECS,
    KST_TIMEZONE,
)
from kortravelmap.dagster.transport_state import TRANSPORT_STATE_SPECS
from kortravelmap.dagster.weather_state import WEATHER_STATE_SPECS

pytestmark = pytest.mark.filterwarnings(
    "ignore:Parameter `owners` of initializer `SensorDefinition.__init__`"
    ".*:dagster_shared.utils.warnings.BetaWarning"
)

_IMPLICIT_ASSET_JOB_PREFIX = "__ASSET_JOB"
"""``Definitions(assets=…)``의 암묵 asset job — UI 수동 materialize 전용, tag 없음(기본 0)."""

_WINDOW_START = datetime(2026, 11, 1, tzinfo=ZoneInfo(KST_TIMEZONE))
_WINDOW = timedelta(days=28)
"""주기 측정 창 4주 — 매월 cron은 한 번, 매주 cron은 네 번 든다(29~31일 cron 없음)."""


def _defined_jobs() -> dict[str, object]:
    return {
        job.name: job
        for job in defs.resolve_all_job_defs()
        if not job.name.startswith(_IMPLICIT_ASSET_JOB_PREFIX)
    }


def _mean_interval(cron: str) -> timedelta | None:
    """창 안 tick 수로 나눈 평균 간격. 창에 tick이 없으면 ``None``(하루 이상 주기)."""
    end = (_WINDOW_START + _WINDOW).timestamp()
    ticks = 0
    for tick in cron_string_iterator(_WINDOW_START.timestamp(), cron, KST_TIMEZONE):
        if tick.timestamp() >= end:
            break
        ticks += 1
    return _WINDOW / ticks if ticks else None


def _rule_priority(crons: list[str]) -> int:
    """공용 규칙을 cron에서 적용한다.

    cron 하나의 주기는 4주 창의 **평균** 간격이다(예: ``25,40``은 30분, ``40 6,7,18,19``는 6시간).
    지금 쓰는 cron은 평균·최소·최대 간격 어느 것으로 재도 같은 등급이다. 한 job의 schedule이
    여럿이면 가장 잦은 것으로 본다. 규칙의 "기준 자료는 주기와 무관하게 0"은 여기서 보지
    않는다 — 하루 미만 주기의 수집 job은 모두 현황·가격·예보라 해당이 없다(새로 생기면 이
    함수가 5·10을 요구하므로 사람이 판단해 예외를 둔다). 10은 현황(관측·상태)만이다 — 1시간 미만
    주기 job 둘(고속도로 돌발·weather 현재)은 모두 현황이라 주기만으로 판정해도 같다.
    """
    intervals = [interval for cron in crons if (interval := _mean_interval(cron)) is not None]
    shortest = min(intervals, default=None)
    if shortest is None or shortest >= timedelta(days=1):
        return 0
    if shortest >= timedelta(hours=1):
        return 5
    return 10


def _collection_crons() -> dict[str, list[str]]:
    """정기 수집 job → 코드 기본 cron들(override 전 값 — 표는 코드 주기로 분류한다)."""
    crons: dict[str, list[str]] = defaultdict(list)
    for spec in (*FEATURE_LOAD_SCHEDULE_SPECS, *KNPS_DATASET_SCHEDULE_SPECS):
        crons[spec.job_name].append(spec.cron_schedule)
    for state_spec in (*TRANSPORT_STATE_SPECS, *WEATHER_STATE_SPECS):
        crons[state_spec.job_name].append(state_spec.cron_schedule)
    # MOIS LOCALDATA 원천 파일 DB 갱신도 정기 수집이다(feature 적재 전 단계).
    crons["mois_localdata_source_sync"].append(MOIS_SOURCE_SYNC_CRON)
    return dict(crons)


def test_mean_interval_measures_what_the_rule_means() -> None:
    """측정 함수 자체의 경계 — 이게 틀리면 아래 대조가 항진명제가 된다."""
    assert _mean_interval("3-59/10 * * * *") == timedelta(minutes=10)
    assert _mean_interval("25,40 * * * *") == timedelta(minutes=30)
    assert _mean_interval("48 * * * *") == timedelta(hours=1)
    assert _mean_interval("20 1,5,9,13,17,21 * * *") == timedelta(hours=4)
    assert _mean_interval("45 4 * * *") == timedelta(days=1)
    assert _mean_interval("5 3 * * 1") == timedelta(days=7)
    assert _mean_interval("15 2 2 * *") == timedelta(days=28)
    assert [_rule_priority([c]) for c in ("3-59/10 * * * *", "48 * * * *", "45 4 * * *")] == [
        10,
        5,
        0,
    ]


def test_every_defined_job_is_in_the_single_table_and_nothing_else_is() -> None:
    """새 job이 표 없이 들어오거나, 사라진 job이 표에 남으면 여기서 깨진다."""
    assert set(_defined_jobs()) == set(JOB_RUN_PRIORITIES)


def test_every_job_definition_carries_its_table_value() -> None:
    """job 정의 tag가 정본이다 — schedule·sensor·launchpad·재실행 run이 모두 이 tag를 물려받는다."""
    for name, job in _defined_jobs().items():
        tags = job.tags  # type: ignore[attr-defined]
        assert RUN_PRIORITY_TAG in tags, f"{name}에 {RUN_PRIORITY_TAG} tag가 없다"
        value = int(tags[RUN_PRIORITY_TAG])
        assert value in RUN_PRIORITY_VALUES, (name, value)
        assert value == JOB_RUN_PRIORITIES[name], name


def test_table_only_uses_rule_values() -> None:
    assert set(JOB_RUN_PRIORITIES.values()) <= RUN_PRIORITY_VALUES
    assert sorted(RUN_PRIORITY_VALUES) == [0, 5, 10]
    # 음수(다른 테넌트 뒤로 밀림)·10 초과(다른 테넌트 굶김)는 규칙 밖이다.
    assert min(JOB_RUN_PRIORITIES.values()) == 0
    assert max(JOB_RUN_PRIORITIES.values()) == 10


def test_collection_jobs_follow_their_code_cron_period() -> None:
    crons = _collection_crons()
    mismatched = {
        name: (JOB_RUN_PRIORITIES[name], _rule_priority(job_crons), job_crons)
        for name, job_crons in crons.items()
        if JOB_RUN_PRIORITIES[name] != _rule_priority(job_crons)
    }
    assert mismatched == {}


def test_realtime_and_hourly_sets_are_the_reviewed_ones() -> None:
    """유도 규칙과 별개로 결과 집합을 박아 둔다 — cron을 바꾸면 이 목록을 사람이 다시 본다."""
    by_value: dict[int, set[str]] = defaultdict(set)
    for name, value in JOB_RUN_PRIORITIES.items():
        by_value[value].add(name)
    assert by_value[10] == {"transport_state_highway_incidents", "weather_state_current"}
    assert by_value[5] == {
        "transport_state_fuel_stations",
        "transport_state_rest_area_fuel_prices",
        "weather_state_forecast_ultra_short",
        "weather_state_daily_summaries",
        "weather_state_forecast_short",
        "weather_state_forecast_external",
        "weather_state_forecast_mid",
        "feature_notice_krforest_landslide_forecast_issues_job",
    }


def test_jobs_without_a_periodic_collection_schedule_are_batch() -> None:
    """정리·유지보수·검증·큐·수동 job은 schedule 주기와 상관없이 0(매시 GC·6시간 file scan 포함)."""
    collection = set(_collection_crons())
    others = {name: JOB_RUN_PRIORITIES[name] for name in _defined_jobs() if name not in collection}
    assert others, "비수집 job을 하나도 못 봤다 — 대조가 항진명제다"
    assert {name for name, value in others.items() if value != 0} == set()


def test_probe_and_completion_jobs_carry_batch_priority() -> None:
    """탐침은 상대 import를 못 해 값을 직접 적는다 — 표와 어긋나지 않게 묶는다."""
    assert RUN_HEARTBEAT_JOB_TAGS[RUN_PRIORITY_TAG] == str(JOB_RUN_PRIORITIES["map_run_heartbeat"])
    assert feature_operation_completion_job.tags[RUN_PRIORITY_TAG] == "0"


def test_unknown_job_fails_loudly() -> None:
    with pytest.raises(KeyError, match="JOB_RUN_PRIORITIES"):
        run_priority_tags("feature_place_not_classified_job")
    assert run_priority.run_priority_tags("transport_state_highway_incidents") == {
        RUN_PRIORITY_TAG: "10"
    }


def _daemon_run_tags(job: Any, request: RunRequest) -> dict[str, str]:
    """daemon이 tick의 run에 쓰는 tag — Dagster 1.13.24 ``_scheduler/scheduler.py``
    ``_create_scheduler_run``·``_daemon/sensor.py`` ``_get_or_create_sensor_run``의
    ``{**remote_job.run_tags, **run_request.tags}``(같은 키는 요청이 이긴다).

    ``run_tags``는 job에 ``run_tags``를 따로 주지 않으면 정의 ``tags``다.
    """
    return {**job.run_tags, **request.tags}


def test_job_run_tags_are_the_definition_tags() -> None:
    """daemon·재실행은 ``run_tags``를 읽는다. 따로 준 ``run_tags``가 priority를 숨기지 않는지."""
    for name, job in _defined_jobs().items():
        assert job.run_tags.get(RUN_PRIORITY_TAG) == str(JOB_RUN_PRIORITIES[name]), name  # type: ignore[attr-defined]


def test_schedule_ticks_keep_the_job_priority_in_the_run_tags() -> None:
    """모든 schedule tick을 실제로 평가해(coalescing ``execution_fn`` 포함) run tag의 값을 본다.

    schedule·``RunRequest`` tag는 job 정의 tag를 덮을 수 있으므로 job tag만 보는 것으로는 부족하다.
    """
    jobs = _defined_jobs()
    seen = 0
    with DagsterInstance.local_temp() as instance:
        for schedule in defs.get_repository_def().schedule_defs:
            with build_schedule_context(
                instance=instance, scheduled_execution_time=_WINDOW_START
            ) as context:
                result = schedule.evaluate_tick(context)
            requests = result.run_requests or []
            assert requests, f"{schedule.name} tick이 run을 내지 않았다: {result.skip_message}"
            job = jobs[schedule.job_name]
            for request in requests:
                # 공용 규칙: RunRequest는 이 key를 싣지 않는다(job 값을 덮지 않는다).
                assert RUN_PRIORITY_TAG not in request.tags, schedule.name
                tags = _daemon_run_tags(job, request)
                assert tags[RUN_PRIORITY_TAG] == str(JOB_RUN_PRIORITIES[schedule.job_name]), (
                    schedule.name
                )
                seen += 1
    assert seen == len(defs.get_repository_def().schedule_defs)


def test_sensor_run_requests_keep_the_job_priority() -> None:
    """sensor가 실제로 만드는 요청을 daemon 합성에 넣는다 — 요청이 job 값을 덮지 않는다."""
    jobs = _defined_jobs()

    queue_request = sensors._run_request_for_request(
        SimpleNamespace(  # type: ignore[arg-type]
            request_id="req-1", generation=1, run_mode="now", scope_type="feature"
        )
    )
    last_mois_run = SimpleNamespace(
        run_id="run-1",
        is_finished=True,
        status=DagsterRunStatus.SUCCESS,
        run_config={},
        tags={
            mois_chunked_load.MOIS_LOAD_OUTCOME_TAG: (
                mois_chunked_load.MOIS_LOAD_OUTCOME_BUDGET_EXHAUSTED
            ),
            mois_chunked_load.MOIS_LOAD_CONVERTED_TAG: "10",
        },
    )
    continuation = mois_chunked_load.mois_load_continuation_decision(last_mois_run)
    assert isinstance(continuation, RunRequest), continuation
    cases = {
        "feature_update_request_worker": queue_request,
        mois_chunked_load.MOIS_LOAD_JOB_NAME: continuation,
        "feature_operation_completion": _completion_run_request("sweep"),
    }
    for job_name, request in cases.items():
        assert RUN_PRIORITY_TAG not in request.tags, job_name
        tags = _daemon_run_tags(jobs[job_name], request)
        assert tags[RUN_PRIORITY_TAG] == str(JOB_RUN_PRIORITIES[job_name]), job_name


_PRIORITY_KEY_OWNERS = frozenset({"run_priority.py", "run_heartbeat.py"})
"""``dagster/priority`` key를 직접 적어도 되는 모듈. 나머지는 ``run_priority_tags``로만 단다."""


def test_only_the_table_module_spells_the_priority_key() -> None:
    """RunRequest·schedule tag에 key를 손으로 넣어 job 값을 덮는 길을 정적으로 막는다."""
    package = Path(run_priority.__file__).parent
    offenders = [
        path.name
        for path in sorted(package.glob("*.py"))
        if path.name not in _PRIORITY_KEY_OWNERS
        and (
            "dagster/priority" in (text := path.read_text(encoding="utf-8"))
            # ``RUN_PRIORITY_TAG``와 Dagster ``_core.storage.tags.PRIORITY_TAG`` 둘 다
            or "PRIORITY_TAG" in text
        )
    ]
    assert offenders == []
