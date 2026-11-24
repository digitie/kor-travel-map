"""`scripts/n150/dagster-freeze.py` — Map location 전체 freeze/unfreeze (감사 §4 #10).

GraphQL은 가짜 webserver(아래 ``_FakeDagster``)가 받는다. instigator 목록은 2026-11-24
n150 Map location의 실제 구성(schedule 49 · sensor 12, 읽기 전용 조회)을 옮긴 것이고,
미기동이던 schedule 6개는 소유자 결정으로 켠 뒤의 상태(RUNNING)다. 다른 location
(PinVi·concierge)의 instigator도 같은 webserver에 있어 그것을 건드리지 않는지 본다.
"""

from __future__ import annotations

import http.server
import importlib.util
import json
import sys
import threading
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType
from typing import Any, ClassVar

import pytest
import yaml

pytestmark = pytest.mark.unit

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "n150" / "dagster-freeze.py"
_MAP = "kortravelmap.dagster.definitions"
_PINVI = "pinvi.etl.definitions"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("_ktm_dagster_freeze", _SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


freeze = _load()

#: 소유자 결정(2026-11-24)으로 켠, 그때까지 한 번도 켜지 않았던 schedule 6개.
_NEWLY_ENABLED = (
    "feature_place_visitkorea_tourist_attractions_daily_schedule",
    "feature_place_standard_special_streets_monthly_schedule",
    "feature_place_standard_traditional_markets_monthly_schedule",
    "feature_place_krheritage_items_monthly_schedule",
    "feature_place_kor_travel_concierge_youtube_monthly_schedule",
    "feature_place_transport_fuel_stations_weekly_schedule",
)

_RUNNING_SCHEDULES = (
    "cache_target_snapshot_gc_hourly_schedule",
    "consistency_dedup_refresh_daily_schedule",
    "feature_event_krheritage_events_monthly_schedule",
    "feature_event_visitkorea_festivals_daily_schedule",
    "feature_geometry_knps_records_monthly_schedule",
    "feature_geometry_knps_records_park_boundaries_monthly_schedule",
    "feature_geometry_knps_records_protected_areas_monthly_schedule",
    "feature_notice_krforest_landslide_forecast_issues_six_daily_schedule",
    "feature_place_datagokr_seoul_bookstores_monthly_schedule",
    "feature_place_khoa_beaches_monthly_schedule",
    "feature_place_knps_points_campgrounds_monthly_schedule",
    "feature_place_knps_points_cultural_resources_monthly_schedule",
    "feature_place_knps_points_monthly_schedule",
    "feature_place_knps_points_restrooms_monthly_schedule",
    "feature_place_knps_points_shelters_monthly_schedule",
    "feature_place_krforest_arboretums_monthly_schedule",
    "feature_place_krforest_recreation_forests_monthly_schedule",
    "feature_place_mcst_culture_monthly_schedule",
    "feature_place_mois_licenses_monthly_schedule",
    "feature_place_standard_museums_monthly_schedule",
    "feature_place_standard_parking_lots_monthly_schedule",
    "feature_place_standard_tourist_attractions_monthly_schedule",
    "feature_place_transport_airports_monthly_schedule",
    "feature_place_transport_ferry_ports_weekly_schedule",
    "feature_place_transport_rail_stations_weekly_schedule",
    "feature_place_transport_rest_areas_weekly_schedule",
    "feature_route_krforest_dulle_trails_monthly_schedule",
    "feature_route_krforest_mountain_trails_monthly_schedule",
    "managed_file_scan_six_hourly_schedule",
    "manual_provider_dedup_detection_daily_schedule",
    "mois_localdata_source_sync_weekly_schedule",
    "transport_state_airports_schedule",
    "transport_state_fuel_stations_schedule",
    "transport_state_highway_incidents_schedule",
    "transport_state_rest_area_fuel_prices_schedule",
    "transport_state_rest_areas_schedule",
    "weather_state_current_schedule",
    "weather_state_daily_summaries_schedule",
    "weather_state_forecast_external_schedule",
    "weather_state_forecast_mid_schedule",
    "weather_state_forecast_short_schedule",
    "weather_state_forecast_ultra_short_schedule",
    "weather_state_locations_schedule",
    *_NEWLY_ENABLED,
)

_SENSORS = (
    ("feature_operation_canceled_sensor", "RUN_STATUS", "RUNNING"),
    ("feature_operation_canceling_sensor", "RUN_STATUS", "RUNNING"),
    ("feature_operation_failure_sensor", "RUN_STATUS", "RUNNING"),
    ("feature_operation_queued_sensor", "RUN_STATUS", "RUNNING"),
    ("feature_operation_reconciliation_sensor", "STANDARD", "RUNNING"),
    ("feature_operation_started_sensor", "RUN_STATUS", "RUNNING"),
    ("feature_operation_starting_sensor", "RUN_STATUS", "RUNNING"),
    ("feature_operation_success_sensor", "RUN_STATUS", "RUNNING"),
    ("feature_place_mois_licenses_continuation_sensor", "STANDARD", "STOPPED"),
    ("feature_update_request_failure_sensor", "RUN_STATUS", "RUNNING"),
    ("feature_update_request_queue_sensor", "STANDARD", "RUNNING"),
    ("kor_travel_geo_release_sensor", "STANDARD", "STOPPED"),
)

_RUN_STATUS_SENSORS = {name for name, kind, _ in _SENSORS if kind == "RUN_STATUS"}

#: Valkey 상태 적재 schedule(ADR-114) — Map PG를 읽지도 쓰지도 않아 freeze가 멈추지 않는다.
_STATE_SCHEDULES = frozenset(
    {
        "transport_state_airports_schedule",
        "transport_state_fuel_stations_schedule",
        "transport_state_highway_incidents_schedule",
        "transport_state_rest_area_fuel_prices_schedule",
        "transport_state_rest_areas_schedule",
        "weather_state_current_schedule",
        "weather_state_daily_summaries_schedule",
        "weather_state_forecast_external_schedule",
        "weather_state_forecast_mid_schedule",
        "weather_state_forecast_short_schedule",
        "weather_state_forecast_ultra_short_schedule",
        "weather_state_locations_schedule",
    }
)


#: 코드 기본값이 RUNNING인 것(n150에서는 모두 저장 상태가 있다 — canReset true).
_DEFAULT_RUNNING = {
    "consistency_dedup_refresh_daily_schedule",
    *(name for name, _, status in _SENSORS if status == "RUNNING"),
}


class _FakeDagster:
    """공유 webserver 하나 — Map과 PinVi location의 instigator와 run, sensor tick."""

    def __init__(self) -> None:
        self.state: dict[tuple[str, str, str], dict[str, Any]] = {}
        for name in _RUNNING_SCHEDULES:
            self._add(_MAP, "schedule", name, "RUNNING")
        for name, sensor_type, status in _SENSORS:
            self._add(_MAP, "sensor", name, status, sensor_type)
        # geo release sensor는 n150에서 저장 상태가 없다(canReset false).
        self.state[(_MAP, "sensor", "kor_travel_geo_release_sensor")]["stored"] = False
        self._add(_PINVI, "schedule", "pinvi_weather_retention_horizon_schedule", "RUNNING")
        self._add(_PINVI, "sensor", "pinvi_queue_sensor", "RUNNING", "STANDARD")
        self.runs: list[dict[str, str]] = []
        self.calls: list[str] = []
        #: run 목록 조회 때마다 하나씩 꺼내 Map run 목록을 바꾼다(끝나 가는·새로 뜨는 run).
        self.run_script: list[list[dict[str, str]]] = []
        #: sensor tick 조회마다 하나씩 꺼내는 {sensor 이름: 최신 tick status}. 없으면 SKIPPED.
        #: ``(status, skipReason)``이면 사유를 단 tick, ``None``이면 tick 없음.
        self.tick_script: list[dict[str, str | tuple[str, str] | None]] = []
        self.fail_stop: set[str] = set()

    def _add(
        self, location: str, kind: str, name: str, status: str, sensor_type: str | None = None
    ) -> None:
        self.state[(location, kind, name)] = {
            "status": status,
            "origin": f"{location}:{kind}:{name}:origin",
            "selector": f"{location}:{kind}:{name}:selector",
            "sensor_type": sensor_type,
            "default": "RUNNING" if name in _DEFAULT_RUNNING else "STOPPED",
            "stored": True,
        }

    def status(self, kind: str, name: str, location: str = _MAP) -> str:
        return str(self.state[(location, kind, name)]["status"])

    def entries(self, location: str) -> list[tuple[str, str, dict[str, Any]]]:
        return [(k, n, e) for (loc, k, n), e in self.state.items() if loc == location]

    def _by_origin(self, origin: str, selector: str) -> dict[str, Any]:
        for entry in self.state.values():
            if entry["origin"] == origin and entry["selector"] == selector:
                return entry
        raise AssertionError(f"unknown instigator {origin}")

    def __call__(self, *, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        if "KtmFreezeInstigators" in query:
            return self._instigators(variables)
        if "KtmFreezeSensorTicks" in query:
            return self._ticks(variables)
        if "KtmFreezeRuns" in query:
            return self._runs(variables)
        if "KtmFreezeStop" in query:
            return self._stop(query, variables)
        if "KtmFreezeStart" in query or "KtmFreezeReset" in query:
            return self._restore(query, variables)
        raise AssertionError(f"unexpected query {query[:60]}")

    def _instigators(self, variables: dict[str, Any]) -> dict[str, Any]:
        assert variables["s"]["repositoryName"] == "__repository__"
        schedules: list[dict[str, Any]] = []
        sensors: list[dict[str, Any]] = []
        for kind, name, entry in self.entries(variables["s"]["repositoryLocationName"]):
            common = {
                "id": entry["origin"],
                "name": name,
                "defaultStatus": entry["default"],
                "canReset": entry["stored"],
            }
            state = {"selectorId": entry["selector"], "status": entry["status"]}
            if kind == "schedule":
                schedules.append({**common, "scheduleState": state})
            else:
                sensors.append({**common, "sensorType": entry["sensor_type"], "sensorState": state})
        return {
            "repositoryOrError": {
                "__typename": "Repository",
                "schedules": schedules,
                "sensors": sensors,
            }
        }

    def _ticks(self, variables: dict[str, Any]) -> dict[str, Any]:
        self.calls.append("ticks")
        statuses = self.tick_script.pop(0) if self.tick_script else {}
        after = float(variables["after"])
        sensors = []
        for kind, name, _ in self.entries(variables["s"]["repositoryLocationName"]):
            if kind != "sensor":
                continue
            value = statuses.get(name, "SKIPPED")
            status, reason = value if isinstance(value, tuple) else (value, None)
            stamp = after + len(self.calls)  # 조회마다 새 tick
            ticks = (
                []
                if status is None
                else [{"status": status, "timestamp": stamp, "skipReason": reason}]
            )
            sensors.append({"name": name, "sensorState": {"ticks": ticks}})
        return {"repositoryOrError": {"__typename": "Repository", "sensors": sensors}}

    def _runs(self, variables: dict[str, Any]) -> dict[str, Any]:
        assert variables["repositorySelector"]["repositoryLocationName"] == _MAP
        assert variables["runsFilter"]["tags"] == [
            {"key": ".dagster/repository", "value": f"__repository__@{_MAP}"}
        ], "run 조회는 Map location tag로 좁혀야 한다"
        assert "STARTED" in variables["runsFilter"]["statuses"]
        if self.run_script:
            self.runs = self.run_script.pop(0)
        return {
            "repositoryOrError": {"__typename": "Repository"},
            "runsOrError": {"__typename": "Runs", "results": list(self.runs)},
        }

    def _stop(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        entry = self._by_origin(variables["o"], variables["i"])
        name = entry["origin"].split(":")[2]
        self.calls.append(f"stop:{name}")
        field = "stopRunningSchedule" if "Schedule" in query else "stopSensor"
        if name in self.fail_stop:
            return {field: {"__typename": "PythonError", "message": "boom"}}
        entry["status"] = "STOPPED"
        entry["stored"] = True
        ok = "ScheduleStateResult" if "Schedule" in query else "StopSensorMutationResult"
        return {field: {"__typename": ok}}

    def _restore(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        selector = variables["s"]
        kind = "schedule" if "scheduleName" in selector else "sensor"
        name = selector.get("scheduleName") or selector["sensorName"]
        entry = self.state[(selector["repositoryLocationName"], kind, name)]
        if "KtmFreezeReset" in query:
            self.calls.append(f"reset:{name}")
            entry["status"] = entry["default"]
            entry["stored"] = False
            field = "resetSchedule" if kind == "schedule" else "resetSensor"
        else:
            self.calls.append(f"start:{name}")
            entry["status"] = "RUNNING"
            entry["stored"] = True
            field = "startSchedule" if kind == "schedule" else "startSensor"
        ok = "ScheduleStateResult" if kind == "schedule" else "Sensor"
        return {field: {"__typename": ok}}


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def wall(self) -> float:
        return 1_800_000_000.0 + self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


_NOW = datetime(2026, 11, 25, 1, 30, tzinfo=UTC)
_TARGET = freeze.Target(_MAP, "__repository__")


def _freeze(
    fake: _FakeDagster,
    path: Path,
    clock: _Clock | None = None,
    now: datetime = _NOW,
    **kwargs: Any,
) -> int:
    clock = clock or _Clock()
    options: dict[str, Any] = {
        "dry_run": False,
        "resume": False,
        "wait_timeout": 600.0,
        "settle": 90.0,
        "poll": 30.0,
    }
    options.update(kwargs)
    return int(
        freeze.cmd_freeze(
            fake,
            _TARGET,
            path,
            clock=clock.monotonic,
            wall=clock.wall,
            sleep=clock.sleep,
            now=lambda: now,
            **options,
        )
    )


def _unfreeze(fake: _FakeDagster, path: Path, **kwargs: Any) -> int:
    options: dict[str, Any] = {"dry_run": False}
    options.update(kwargs)
    return int(freeze.cmd_unfreeze(fake, _TARGET, path, now=lambda: _NOW, **options))


def _map_statuses(fake: _FakeDagster) -> dict[tuple[str, str], str]:
    return {(kind, name): str(e["status"]) for kind, name, e in fake.entries(_MAP)}


def _stops(fake: _FakeDagster) -> list[str]:
    return [call.removeprefix("stop:") for call in fake.calls if call.startswith("stop:")]


def _assert_frozen(fake: _FakeDagster) -> None:
    """Valkey 상태 schedule만 RUNNING이고 나머지 Map instigator는 전부 STOPPED다."""

    running = {name for (_, name), status in _map_statuses(fake).items() if status == "RUNNING"}
    assert running == _STATE_SCHEDULES


def _run(job: str = "feature_place_mois_licenses_job") -> dict[str, str]:
    return {"runId": "r1", "status": "STARTED", "jobName": job}


# --------------------------------------------------------------------------- freeze/unfreeze


def test_freeze_stops_every_map_instigator_and_unfreeze_restores_the_exact_snapshot(
    tmp_path: Path,
) -> None:
    fake = _FakeDagster()
    before = _map_statuses(fake)
    snapshot = tmp_path / "freeze.json"

    assert _freeze(fake, snapshot) == 0
    _assert_frozen(fake)
    # 다른 location은 그대로다.
    assert fake.status("schedule", "pinvi_weather_retention_horizon_schedule", _PINVI) == "RUNNING"
    assert fake.status("sensor", "pinvi_queue_sensor", _PINVI) == "RUNNING"

    document = json.loads(snapshot.read_text(encoding="utf-8"))
    assert document["format"] == "ktm-dagster-freeze/v1"
    assert document["location"] == _MAP
    assert document["count"] == len(_RUNNING_SCHEDULES) + len(_SENSORS) == 61
    recorded = {(e["kind"], e["name"]): e["status"] for e in document["instigators"]}
    assert recorded == before

    assert _unfreeze(fake, snapshot) == 0
    assert _map_statuses(fake) == before
    # 의도적으로 STOPPED였던 sensor는 STOPPED로 남는다.
    assert fake.status("sensor", "feature_place_mois_licenses_continuation_sensor") == "STOPPED"
    assert fake.status("sensor", "kor_travel_geo_release_sensor") == "STOPPED"
    assert not any("geo_release" in call for call in fake.calls)
    # 성공한 스냅샷은 옆으로 옮겨져 다음 freeze가 이어 쓰지 않는다(지우지 않는다).
    assert not snapshot.exists()
    assert (tmp_path / "freeze.json.restored-20261125T013000Z").exists()


@pytest.mark.parametrize("name", _NEWLY_ENABLED)
def test_newly_enabled_schedules_are_frozen_and_restored(tmp_path: Path, name: str) -> None:
    fake = _FakeDagster()
    snapshot = tmp_path / "freeze.json"
    assert _freeze(fake, snapshot) == 0
    document = json.loads(snapshot.read_text(encoding="utf-8"))
    entry = next(e for e in document["instigators"] if e["name"] == name)
    assert (entry["kind"], entry["status"]) == ("schedule", "RUNNING")
    assert fake.status("schedule", name) == "STOPPED"
    assert _unfreeze(fake, snapshot) == 0
    assert fake.status("schedule", name) == "RUNNING"


def test_valkey_state_schedules_keep_running_and_their_runs_are_not_awaited(
    tmp_path: Path,
) -> None:
    """``weather_state_*``·``transport_state_*``는 Map PG에 닿지 않는다 — 멈추면 상태만 낡는다.

    멈춘 채 두면 창 동안 낡고, Dagster가 놓친 tick을 따라잡지 않아 하루 한 번 도는 것은 unfreeze
    뒤 다음 cron까지 낡는다. 그 run이 창 안에서 계속 떠도 freeze는 그것을 기다리지 않는다.
    """

    fake = _FakeDagster()
    before = _map_statuses(fake)
    fake.runs = [_run("weather_state_current"), _run("transport_state_highway_incidents")]
    clock = _Clock()
    snapshot = tmp_path / "freeze.json"

    assert _freeze(fake, snapshot, clock) == 0
    _assert_frozen(fake)
    assert not set(_stops(fake)) & _STATE_SCHEDULES
    # 상태 적재 run을 기다리지 않는다 — settle과 두 번째 tick만.
    assert clock.sleeps == [90.0, 30.0]

    fake.calls.clear()
    assert _unfreeze(fake, snapshot) == 0
    assert _map_statuses(fake) == before
    assert not {call.split(":", 1)[1] for call in fake.calls} & _STATE_SCHEDULES


def test_state_schedules_stopped_by_an_earlier_freeze_are_restored(tmp_path: Path) -> None:
    """이 예외 이전 판의 freeze(상태 schedule을 RUNNING으로 적고 멈췄다)도 이어 하고 되살린다."""

    fake = _FakeDagster()
    fake.runs = [_run()]
    snapshot = tmp_path / "freeze.json"
    assert _freeze(fake, snapshot, wait_timeout=0.0) == 1
    for name in _STATE_SCHEDULES:
        fake.state[(_MAP, "schedule", name)]["status"] = "STOPPED"

    fake.runs = []
    assert _freeze(fake, snapshot, resume=True) == 0
    assert _unfreeze(fake, snapshot) == 0
    assert {name for name in _STATE_SCHEDULES if fake.status("schedule", name) == "RUNNING"} == (
        _STATE_SCHEDULES
    )


def test_resume_does_not_refuse_a_state_schedule_turned_on_in_the_window(tmp_path: Path) -> None:
    """상태 schedule은 freeze 대상이 아니다 — 창 안에서 켜져도 이어 하기를 막지 않는다."""

    fake = _FakeDagster()
    locations = fake.state[(_MAP, "schedule", "weather_state_locations_schedule")]
    locations["status"] = "STOPPED"
    fake.runs = [_run()]
    snapshot = tmp_path / "freeze.json"
    assert _freeze(fake, snapshot, wait_timeout=0.0) == 1
    locations["status"] = "RUNNING"

    fake.runs = []
    assert _freeze(fake, snapshot, resume=True) == 0
    assert locations["status"] == "RUNNING"


def test_state_prefixes_match_the_fixture_state_schedules() -> None:
    """가짜 webserver의 n150 구성에서 도구가 건너뛰는 것은 상태 schedule 12개뿐이다.

    이름 규칙이 code location 정의와 맞는지(그리고 그 job이 Map PG에 닿지 않는지)는
    ``packages/kor-travel-map-dagster/tests/test_freeze_skips_state_jobs.py``가 본다.
    """

    names = {*_RUNNING_SCHEDULES, *(name for name, _, _ in _SENSORS)}
    assert {name for name in names if freeze.is_state_job(name)} == _STATE_SCHEDULES


def test_run_status_sensors_stop_last_after_runs_drain_and_ticks_settle(tmp_path: Path) -> None:
    fake = _FakeDagster()
    fake.run_script = [[_run()], [_run()], []]
    fake.tick_script = [{"feature_operation_success_sensor": "SUCCESS"}, {}]
    clock = _Clock()

    assert _freeze(fake, tmp_path / "freeze.json", clock) == 0

    stops = _stops(fake)
    first_observer = min(i for i, name in enumerate(stops) if name in _RUN_STATUS_SENSORS)
    assert set(stops[first_observer:]) == _RUN_STATUS_SENSORS
    assert not set(stops[:first_observer]) & _RUN_STATUS_SENSORS
    assert "feature_update_request_queue_sensor" in stops[:first_observer]
    assert "feature_operation_reconciliation_sensor" in stops[:first_observer]
    # run 대기 poll 둘, settle, 그다음 SKIPPED tick을 두 시각에 볼 때까지 poll — success
    # sensor가 첫 조회에서 SUCCESS라 하나 더 기다린다.
    assert clock.sleeps == [30.0, 30.0, 90.0, 30.0, 30.0]


def test_a_run_launched_by_the_success_sensor_during_settle_is_awaited(tmp_path: Path) -> None:
    """``feature_operation_success_sensor``는 completion job run을 낸다 — 그것도 기다린다."""

    fake = _FakeDagster()
    completion = _run("feature_operation_completion_job")
    # 대기: 0 → settle 뒤: completion run → 대기: 아직 → 0 → settle 뒤: 0.
    fake.run_script = [[], [completion], [completion], [], []]
    clock = _Clock()

    assert _freeze(fake, tmp_path / "freeze.json", clock) == 0
    # settle·두 번째 SKIPPED tick → completion run 대기 → settle·두 번째 SKIPPED tick.
    assert clock.sleeps == [90.0, 30.0, 30.0, 90.0, 30.0]
    _assert_frozen(fake)


def test_lagging_run_status_sensor_keeps_observers_running(tmp_path: Path) -> None:
    fake = _FakeDagster()
    fake.tick_script = [{"feature_operation_failure_sensor": None}] * 50

    assert _freeze(fake, tmp_path / "freeze.json", wait_timeout=200.0) == 1
    for name in _RUN_STATUS_SENSORS:
        assert fake.status("sensor", name) == "RUNNING"


def test_launcher_stop_failure_keeps_run_status_sensors_running(tmp_path: Path) -> None:
    fake = _FakeDagster()
    fake.fail_stop = {"managed_file_scan_six_hourly_schedule"}
    snapshot = tmp_path / "freeze.json"

    assert _freeze(fake, snapshot) == 1
    for name in _RUN_STATUS_SENSORS:
        assert fake.status("sensor", name) == "RUNNING"
    assert not set(_stops(fake)) & _RUN_STATUS_SENSORS

    fake.fail_stop = set()
    assert _freeze(fake, snapshot, resume=True) == 0
    _assert_frozen(fake)


def test_run_appearing_while_observers_stop_restores_them(tmp_path: Path) -> None:
    fake = _FakeDagster()
    # 대기: 0 → settle 뒤: 0 → run-status sensor 정지 직후: 새 run.
    fake.run_script = [[], [], [_run()]]

    assert _freeze(fake, tmp_path / "freeze.json") == 1
    for name in _RUN_STATUS_SENSORS:
        assert fake.status("sensor", name) == "RUNNING"
    assert fake.status("sensor", "feature_update_request_queue_sensor") == "STOPPED"


def test_timeout_keeps_run_status_sensors_running_and_resume_continues(tmp_path: Path) -> None:
    fake = _FakeDagster()
    fake.runs = [_run()]
    snapshot = tmp_path / "freeze.json"

    assert _freeze(fake, snapshot, wait_timeout=60.0) == 1
    for name in _RUN_STATUS_SENSORS:
        assert fake.status("sensor", name) == "RUNNING"
    assert fake.status("sensor", "feature_update_request_queue_sensor") == "STOPPED"
    first = snapshot.read_text(encoding="utf-8")

    fake.runs = []
    assert _freeze(fake, snapshot) == 3, "--resume 없이 기존 스냅샷을 이어 쓰지 않는다"
    assert _freeze(fake, snapshot, resume=True) == 0
    # 이어 하기는 스냅샷을 덮어쓰지 않는다 — 원래 RUNNING이던 것이 그대로 적혀 있다.
    assert snapshot.read_text(encoding="utf-8") == first
    assert _unfreeze(fake, snapshot) == 0
    assert fake.status("schedule", "consistency_dedup_refresh_daily_schedule") == "RUNNING"


def test_resume_refuses_when_a_non_snapshot_instigator_was_turned_on(tmp_path: Path) -> None:
    fake = _FakeDagster()
    fake.runs = [_run()]
    snapshot = tmp_path / "freeze.json"
    assert _freeze(fake, snapshot, wait_timeout=0.0) == 1
    # 창 안에서 누가 STOPPED였던 sensor를 켰다.
    fake.state[(_MAP, "sensor", "kor_travel_geo_release_sensor")]["status"] = "RUNNING"
    fake.calls.clear()

    assert _freeze(fake, snapshot, resume=True) == 3
    assert not _stops(fake)


def test_resume_refuses_a_stale_snapshot(tmp_path: Path) -> None:
    fake = _FakeDagster()
    fake.runs = [_run()]
    snapshot = tmp_path / "freeze.json"
    assert _freeze(fake, snapshot, wait_timeout=0.0) == 1
    fake.calls.clear()
    assert _freeze(fake, snapshot, now=_NOW + timedelta(hours=25), resume=True) == 3
    assert not _stops(fake)


def test_resume_names_recorded_running_launchers_it_stops_again(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """스냅샷이 RUNNING으로 적은 것이 창 안에서 다시 켜지면 거부 없이 다시 멈추고 이름을 남긴다."""

    fake = _FakeDagster()
    snapshot = tmp_path / "freeze.json"
    assert _freeze(fake, snapshot) == 0
    mcst = fake.state[(_MAP, "schedule", "feature_place_mcst_culture_monthly_schedule")]
    mcst["status"] = "RUNNING"
    capsys.readouterr()

    assert _freeze(fake, snapshot, resume=True) == 0
    out = capsys.readouterr().out
    assert "launcher 1개가 지금 RUNNING" in out
    assert "    schedule:feature_place_mcst_culture_monthly_schedule" in out
    assert mcst["status"] == "STOPPED"


def test_failed_freeze_prints_how_to_roll_back_and_unfreeze_does(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """1로 끝난 freeze를 접는 길 — 같은 스냅샷의 unfreeze가 부분 freeze를 되돌린다."""

    fake = _FakeDagster()
    before = _map_statuses(fake)
    fake.fail_stop = {"managed_file_scan_six_hourly_schedule"}
    snapshot = tmp_path / "freeze.json"

    assert freeze.main(["freeze", "--snapshot", str(snapshot)], gql=fake) == 1
    out = capsys.readouterr().out
    assert f"rollback: 접으려면 unfreeze --snapshot {snapshot}" in out

    assert freeze.main(["unfreeze", "--snapshot", str(snapshot)], gql=fake) == 0
    assert _map_statuses(fake) == before


def test_refused_freeze_changes_nothing_and_offers_no_rollback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """창 안의 회전이 새 파일로 freeze하면 거부(3)된다 — 아무것도 안 바꿨으니 되돌릴 것도 없다."""

    fake = _FakeDagster()
    assert _freeze(fake, tmp_path / "window.json") == 0
    frozen = _map_statuses(fake)
    capsys.readouterr()
    fake.calls.clear()

    rotation = tmp_path / "rotation.json"
    assert freeze.main(["freeze", "--snapshot", str(rotation)], gql=fake) == 3
    out = capsys.readouterr().out
    assert "회전의 freeze·unfreeze 단계를 빼라" in out
    assert "rollback" not in out
    assert not rotation.exists()
    assert not fake.calls
    assert _map_statuses(fake) == frozen


def test_resume_without_a_snapshot_is_refused(tmp_path: Path) -> None:
    fake = _FakeDagster()
    assert _freeze(fake, tmp_path / "freeze.json", resume=True) == 3
    assert not _stops(fake)


def test_new_snapshot_of_an_already_frozen_location_is_refused(tmp_path: Path) -> None:
    """다른 경로로 다시 돌리면 얼어 있는 상태를 스냅샷해 unfreeze가 아무것도 켜지 못한다."""

    fake = _FakeDagster()
    assert _freeze(fake, tmp_path / "a" / "freeze.json") == 0
    fake.calls.clear()
    other = tmp_path / "b" / "freeze.json"
    assert _freeze(fake, other) == 3
    assert not other.exists()
    assert not fake.calls


def test_relative_snapshot_path_is_rejected() -> None:
    fake = _FakeDagster()
    assert freeze.main(["freeze", "--snapshot", "freeze.json"], gql=fake) == 2
    assert freeze.main(["unfreeze", "--snapshot", "freeze.json"], gql=fake) == 2
    assert not fake.calls


def test_unfreeze_requires_a_snapshot(tmp_path: Path) -> None:
    fake = _FakeDagster()
    assert freeze.main(["unfreeze", "--snapshot", str(tmp_path / "absent.json")], gql=fake) == 2
    assert not fake.calls


_ONE = [{"kind": "schedule", "name": "x", "status": "RUNNING"}]


@pytest.mark.parametrize(
    "document",
    [
        {"location": _PINVI, "instigators": _ONE, "count": 1},
        {"location": _MAP, "instigators": [], "count": 0},
        {"location": _MAP, "instigators": _ONE, "count": 2},
    ],
    ids=["other-location", "empty", "count-mismatch"],
)
def test_unfreeze_rejects_a_bad_snapshot(tmp_path: Path, document: dict[str, Any]) -> None:
    fake = _FakeDagster()
    snapshot = tmp_path / "freeze.json"
    payload = {
        "format": "ktm-dagster-freeze/v1",
        "repository": "__repository__",
        "taken_at": _NOW.isoformat(),
        **document,
    }
    snapshot.write_text(json.dumps(payload), encoding="utf-8")
    assert freeze.main(["unfreeze", "--snapshot", str(snapshot)], gql=fake) == 2
    assert not fake.calls


def test_unfreeze_reports_missing_names_and_starts_run_status_sensors_first(
    tmp_path: Path,
) -> None:
    fake = _FakeDagster()
    snapshot = tmp_path / "freeze.json"
    assert _freeze(fake, snapshot) == 0
    # 창 안의 배포가 schedule 하나의 이름을 지웠다.
    del fake.state[(_MAP, "schedule", "weather_state_locations_schedule")]
    fake.calls.clear()

    assert _unfreeze(fake, snapshot) == 1
    restored = [call.split(":", 1)[1] for call in fake.calls]
    observer_positions = [i for i, name in enumerate(restored) if name in _RUN_STATUS_SENSORS]
    assert observer_positions == list(range(len(_RUN_STATUS_SENSORS)))
    assert snapshot.exists(), "불완전한 unfreeze는 스냅샷을 남긴다"

    # 사람이 확인한 뒤 명시적으로 받아들이면 보관하고 끝난다.
    assert _unfreeze(fake, snapshot, accept_missing=True) == 0
    assert not snapshot.exists()


def test_default_running_instigator_without_stored_state_is_reset_not_started(
    tmp_path: Path,
) -> None:
    """저장 상태가 없던 기본 RUNNING을 start로 되살리면 저장된 행이 코드 기본값을 덮는다."""

    fake = _FakeDagster()
    queue = fake.state[(_MAP, "sensor", "feature_update_request_queue_sensor")]
    queue["stored"] = False
    snapshot = tmp_path / "freeze.json"
    assert _freeze(fake, snapshot) == 0
    fake.calls.clear()

    assert _unfreeze(fake, snapshot) == 0
    assert "reset:feature_update_request_queue_sensor" in fake.calls
    assert queue["status"] == "RUNNING"
    assert queue["stored"] is False
    assert "start:feature_operation_success_sensor" in fake.calls


def test_dry_runs_change_nothing(tmp_path: Path) -> None:
    fake = _FakeDagster()
    before = _map_statuses(fake)
    snapshot = tmp_path / "freeze.json"

    assert _freeze(fake, snapshot, dry_run=True) == 0
    assert not snapshot.exists()
    assert _map_statuses(fake) == before
    assert not _stops(fake)

    assert _freeze(fake, snapshot) == 0
    stopped = _map_statuses(fake)
    fake.calls.clear()
    assert _unfreeze(fake, snapshot, dry_run=True) == 0
    assert _map_statuses(fake) == stopped
    assert snapshot.exists()
    assert not fake.calls


def test_status_is_read_only(capsys: pytest.CaptureFixture[str]) -> None:
    fake = _FakeDagster()
    assert freeze.main(["status"], gql=fake) == 0
    out = capsys.readouterr().out
    assert "feature_place_krheritage_items_monthly_schedule" in out
    assert "pinvi" not in out
    assert not fake.calls


def test_default_location_is_the_workspace_location() -> None:
    root = Path(__file__).resolve().parents[2]
    workspace = yaml.safe_load((root / "docker" / "workspace.yaml").read_text(encoding="utf-8"))
    location = workspace["load_from"][0]["grpc_server"]["location_name"]
    assert location == freeze.DEFAULT_LOCATION


# --------------------------------------------------------------------------- HTTP transport


@pytest.mark.parametrize(
    "url",
    [
        "ftp://secret-host.invalid/graphql",
        "http://user:hunter2@secret-host.invalid/graphql",
        "::bad",
    ],
)
def test_bad_endpoint_is_rejected_without_echoing_it(
    url: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("KTM_DAGSTER_FREEZE_GRAPHQL_URL", url)
    assert freeze.main(["status"]) == 2
    out = capsys.readouterr().out
    assert "secret-host" not in out
    assert "hunter2" not in out


def test_basic_auth_is_not_sent_over_plain_http_to_a_remote_host(tmp_path: Path) -> None:
    auth = tmp_path / "auth"
    auth.write_text("user:pw\n", encoding="utf-8")
    with pytest.raises(freeze.FreezeError, match="https 또는 loopback"):
        freeze.http_transport("http://dagster.example/graphql", auth_file=str(auth))
    freeze.http_transport("https://dagster.example/graphql", auth_file=str(auth))
    freeze.http_transport("http://127.0.0.1:1/graphql", auth_file=str(auth))


def test_basic_auth_file_errors_are_input_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bad = tmp_path / "bad"
    bad.write_text("no-colon\n", encoding="utf-8")
    with pytest.raises(freeze.FreezeError):
        freeze._basic_auth_header(str(bad))
    monkeypatch.setenv("KTM_DAGSTER_FREEZE_BASIC_AUTH_FILE", str(tmp_path / "absent"))
    assert freeze.main(["status"]) == 2


class _Handler(http.server.BaseHTTPRequestHandler):
    replies: ClassVar[list[tuple[int, bytes, dict[str, str]]]] = []
    seen: ClassVar[list[dict[str, str]]] = []

    def do_POST(self) -> None:
        length = int(self.headers.get("content-length", "0"))
        self.rfile.read(length)
        type(self).seen.append(dict(self.headers))
        status, body, headers = type(self).replies.pop(0)
        self.send_response(status)
        for key, value in headers.items():
            self.send_header(key, value)
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:
        return None


@pytest.fixture
def server() -> Iterator[str]:
    _Handler.replies = []
    _Handler.seen = []
    httpd = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}/graphql"
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_transport_retries_5xx_and_non_json_then_succeeds(server: str) -> None:
    _Handler.replies = [
        (500, b"boom", {}),
        (200, b"<html>proxy</html>", {}),
        (200, json.dumps({"data": {"ok": 1}}).encode(), {}),
    ]
    sleeps: list[float] = []
    post = freeze.http_transport(server, sleep=sleeps.append)
    assert post(query="{ ok }", variables={}) == {"ok": 1}
    assert sleeps == [2, 5]


def test_transport_does_not_follow_redirects_with_credentials(
    server: str, tmp_path: Path
) -> None:
    auth = tmp_path / "auth"
    auth.write_text("user:pw\n", encoding="utf-8")
    _Handler.replies = [(307, b"", {"location": "http://elsewhere.invalid/graphql"})]
    post = freeze.http_transport(server, auth_file=str(auth), sleep=lambda _: None)
    with pytest.raises(freeze.FreezeError, match="HTTP 307"):
        post(query="{ ok }", variables={})
    assert len(_Handler.seen) == 1


def test_one_skipped_tick_is_not_enough(tmp_path: Path) -> None:
    """다른 location의 사건만 읽은 tick도 SKIPPED일 수 있다 — 서로 다른 두 시각을 요구한다."""

    fake = _FakeDagster()
    clock = _Clock()
    assert _freeze(fake, tmp_path / "freeze.json", clock) == 0
    assert fake.calls.count("ticks") == 2
    assert clock.sleeps == [90.0, 30.0]


def test_a_skipped_tick_with_a_reason_handled_an_event_and_is_not_caught_up(
    tmp_path: Path,
) -> None:
    """``feature_update_request_failure_sensor``는 실패 사건 하나를 처리할 때마다 SkipReason을 낸다.

    Dagster run-status sensor 감싸개는 사용자 함수가 돌려준 값을 내고 그 tick을 끝낸다 — tick은
    SKIPPED지만 사건 하나를 처리했고, 실패가 몰리면 뒤에 사건이 남아 있다. 처리할 사건이 없던
    tick만 사유가 없다(감싸개가 아무것도 내지 않는다).
    """

    fake = _FakeDagster()
    handled = ("SKIPPED", "Dagster feature update worker failed: run_id=r9 request_id=q9")
    fake.tick_script = [{"feature_update_request_failure_sensor": handled}] * 3
    clock = _Clock()

    assert _freeze(fake, tmp_path / "freeze.json", clock) == 0
    # 사유 있는 SKIPPED 세 번은 따라잡음이 아니다 — 그 뒤 사유 없는 tick을 서로 다른 두 시각에 본다.
    assert fake.calls.count("ticks") == 5
    assert clock.sleeps == [90.0, 30.0, 30.0, 30.0, 30.0]


def test_resume_restores_run_status_sensors_left_off_while_runs_exist(tmp_path: Path) -> None:
    """앞선 시도가 run-status sensor를 멈춘 뒤 run이 생겼으면 이어 하기는 관찰부터 되살린다."""

    fake = _FakeDagster()
    snapshot = tmp_path / "freeze.json"
    fake.runs = [_run()]
    assert _freeze(fake, snapshot, wait_timeout=0.0) == 1
    # 중단으로 run-status sensor 하나가 꺼진 채 남았다.
    success = fake.state[(_MAP, "sensor", "feature_operation_success_sensor")]
    success["status"] = "STOPPED"
    fake.calls.clear()

    assert _freeze(fake, snapshot, resume=True, wait_timeout=0.0) == 1
    assert fake.calls[0] == "start:feature_operation_success_sensor", "관찰을 먼저 되살린다"
    assert success["status"] == "RUNNING"


def test_unfreeze_refuses_a_stale_snapshot(tmp_path: Path) -> None:
    fake = _FakeDagster()
    snapshot = tmp_path / "freeze.json"
    assert _freeze(fake, snapshot) == 0
    fake.calls.clear()
    later = _NOW + timedelta(hours=49)
    assert freeze.cmd_unfreeze(fake, _TARGET, snapshot, dry_run=False, now=lambda: later) == 3
    assert not [call for call in fake.calls if not call.startswith("ticks")]
    assert snapshot.exists()
    result = freeze.cmd_unfreeze(
        fake, _TARGET, snapshot, dry_run=False, max_age_hours=72.0, now=lambda: later
    )
    assert result == 0


def test_unexpected_response_shape_is_an_error_not_a_traceback() -> None:
    def gql(*, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        return {"repositoryOrError": {"__typename": "Repository", "schedules": [{"name": "x"}]}}

    assert freeze.main(["status"], gql=gql) == 2
