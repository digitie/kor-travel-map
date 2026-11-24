"""운영 창 freeze 도구가 기본으로 건너뛰는 Valkey 상태 적재 job이 Map PG에 쓰지 않는지 검사한다.

## 왜

``scripts/n150/dagster-freeze.py``는 Map PG writer를 멈추는 도구다. ``weather_state_*``·
``transport_state_*`` schedule(ADR-114)까지 멈추면 창 동안 PinVi가 보는 날씨·교통 상태가 낡고,
Dagster가 놓친 tick을 따라잡지 않아 하루 한 번 도는 것은 unfreeze 뒤에도 다음 cron까지(최대 약
24시간) 낡는다(#1541 리뷰). 그래서 도구는 ``--include-state`` 없이는 이름 접두어
(``STATE_JOB_PREFIXES``)로 그 schedule을 멈추지 않고 그 run을 기다리지 않는다.

그 예외가 안전하려면 접두어가 상태 적재 job·schedule **만** 가리키고, 그 job이 Map PG에 쓰지 않아야
한다. 여기서 보는 것은 정의와 소스에서 드러나는 쓰기 길이다.

- op가 ``kor_travel_map_client`` resource를 요구하지 않는다.
- job tag와 schedule tag(run tag는 둘을 합친다)에 operation key가 없다 — 있으면 run-status sensor가
  operation 상태를 Map DB에 반영한다.
- 상태 job 모듈 소스가 ``pg_dsn``·``AsyncKorTravelMapClient``를 쓰지 않는다 — op는
  ``KorTravelMapSettings()``를 직접 만들므로 resource 없이도 settings의 DSN으로 PG를 열 수 있다.
  이것은 소스 문자열 검사라 다른 모듈을 거치는 길까지 막지는 못한다(리뷰 몫).

읽기 길은 하나 있고 예외로 둔다 — Map run은 모두 run 프로세스가 정의를 import할 때
``ops.dagster_schedule_overrides``를 읽는다(``cron_for_schedule``). 운영 compose는 그것을
필수(``KOR_TRAVEL_MAP_DAGSTER_SCHEDULE_OVERRIDES_REQUIRED=true``)로 둬 PG에 닿지 못하면 상태 run도
시작하지 못한다. 공용 PG 재생성 창에서는 그래서 ``--include-state``를 쓴다(scripts/n150/README.md).
"""

from __future__ import annotations

import importlib.util
import inspect
import sys
from pathlib import Path
from types import ModuleType

from kortravelmap.dagster import transport_state, weather_state
from kortravelmap.dagster.definitions import defs
from kortravelmap.dagster.transport_state import TRANSPORT_STATE_SPECS
from kortravelmap.dagster.weather_state import WEATHER_STATE_SPECS

_SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "n150" / "dagster-freeze.py"
_OPERATION_KEY_TAG = "kor_travel_map.operation_key"


def _freeze_tool() -> ModuleType:
    spec = importlib.util.spec_from_file_location("_ktm_dagster_freeze_scope", _SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_state_prefixes_name_exactly_the_valkey_state_jobs_and_schedules() -> None:
    tool = _freeze_tool()
    specs = (*WEATHER_STATE_SPECS, *TRANSPORT_STATE_SPECS)
    repository = defs.get_repository_def()

    jobs = {job.name for job in defs.resolve_all_job_defs() if tool.is_state_job(job.name)}
    schedules = {s.name for s in repository.schedule_defs if tool.is_state_job(s.name)}
    sensors = {s.name for s in repository.sensor_defs if tool.is_state_job(s.name)}

    assert jobs == {spec.job_name for spec in specs}
    assert schedules == {spec.schedule_name for spec in specs}
    assert not sensors
    for schedule in repository.schedule_defs:
        if schedule.name in schedules:
            assert schedule.job_name in jobs, schedule.name


def test_state_jobs_do_not_write_map_pg() -> None:
    tool = _freeze_tool()
    repository = defs.get_repository_def()
    jobs = [job for job in defs.resolve_all_job_defs() if tool.is_state_job(job.name)]
    schedules = [s for s in repository.schedule_defs if tool.is_state_job(s.name)]
    assert jobs
    assert schedules

    for job in jobs:
        assert job.tags.get("kor_travel_map.job_scope") == "state", job.name
        # operation tag가 없으면 run-status sensor는 그 run을 panel-only로 지나간다(DB 반영 없음).
        assert _OPERATION_KEY_TAG not in job.tags, job.name
        required = {key for node in job.all_node_defs for key in node.required_resource_keys}
        assert "kor_travel_map_client" not in required, job.name
    for schedule in schedules:
        # schedule tag도 run tag에 합쳐진다.
        assert _OPERATION_KEY_TAG not in schedule.tags, schedule.name


def test_state_job_modules_do_not_open_map_pg_from_settings() -> None:
    for module in (weather_state, transport_state):
        source = inspect.getsource(module)
        assert "pg_dsn" not in source, module.__name__
        assert "AsyncKorTravelMapClient" not in source, module.__name__
