#!/usr/bin/env python3
"""Map Dagster code location의 자동 writer를 전부 멈추고(freeze) 그대로 되돌린다(unfreeze).

usage:
  dagster-freeze.py status   [--snapshot ABS_FILE]
  dagster-freeze.py freeze   --snapshot ABS_FILE [--resume] [--dry-run]
                             [--wait-timeout S] [--settle S] [--poll S] [--max-age-hours H]
  dagster-freeze.py unfreeze --snapshot ABS_FILE [--dry-run] [--accept-missing] [--max-age-hours H]

옛 ``~/freeze.py``는 산사태 schedule과 update-request 큐 sensor 둘만 멈췄다. PG에 쓰는 나머지
Map instigator(MOIS·consistency·GC·file scan·feature 적재 schedule 등 약 42개)는 그대로 돌았다
(수집 실패 감사 2026-11-23 §1.4, §4 #10). 이 도구는 **Map code location 하나의** schedule·sensor
전체를 대상으로 한다. 다른 location(PinVi·concierge)은 읽지도 바꾸지도 않는다. 예외는 Map PG를
읽지도 쓰지도 않는 Valkey 상태 적재 schedule(``weather_state_*``·``transport_state_*``,
ADR-114)이다 — 멈추지 않고 그 run도 기다리지 않는다(``STATE_JOB_PREFIXES``). 멈추면 창 동안과
창 뒤 다음 cron까지 PinVi가 보는 날씨·교통 상태가 낡는다.

freeze
  0. 스냅샷 경로는 절대 경로만 받는다(다른 cwd에서 다시 돌려 엉뚱한 새 스냅샷을 쓰지 않게).
     파일이 이미 있으면 ``--resume``일 때만 이어 쓴다(``--max-age-hours`` 안, 스냅샷이 RUNNING으로
     적지 않은 instigator가 지금 RUNNING이면 거부). 새로 쓸 때 RUNNING launcher가 하나도 없으면
     "이미 얼어 있다"로 보고 거부한다 — 그 상태를 스냅샷하면 unfreeze가 아무것도 되살리지 못한다.
  1. 모든 schedule·sensor의 상태·코드 기본값·저장 상태 여부를 스냅샷 파일에 남긴다
     (0600, 임시 파일 → fsync → rename).
  2. launcher(Valkey 상태 schedule을 뺀 schedule 전부와 RUN_STATUS가 아닌 sensor)를 멈춘다.
     하나라도 실패하면 run-status sensor는 켜 둔 채 1로 끝난다(계속 도는 launcher가 낸 run을
     관찰할 sensor가 남아야 한다).
  3. Map run 중 끝나지 않은 것(QUEUED·NOT_STARTED·STARTING·STARTED·MANAGED·CANCELING, Valkey 상태
     적재 run 제외)이 0이 될 때까지 기다린다(진행 표시, ``--wait-timeout``).
  4. run-status sensor가 마지막 terminal 사건을 DB에 반영했는지 본다 — ``--settle``초 뒤, 켜진
     run-status sensor마다 run이 0이 된 뒤 사유 없는 SKIPPED(처리할 사건 없음) tick을 서로 다른 두
     시각에 볼 때까지. 사유 있는 SKIPPED는 사건 하나를 처리한 tick이다(failure sensor).
     그다음 run을 다시 센다: run-status sensor 하나(``feature_operation_success_sensor``)는
     completion job run을 **낸다**. 새 run이 있으면 3으로 돌아간다.
  5. run-status sensor를 멈추고 run을 다시 센다. 그 사이 run이 생겼으면 방금 멈춘 run-status
     sensor를 되살리고 1로 끝난다.
  6. Valkey 상태 schedule 말고 전부 STOPPED이고 run 0이면 ``FREEZE_OK``(0). 대기 초과·실패는
     ``FREEZE_INCOMPLETE``(1)이고,
     ``--resume``으로 같은 명령을 다시 돌리면 이어 한다.

unfreeze
  스냅샷이 RUNNING으로 적은 instigator만 되살린다(run-status sensor → 나머지 sensor → schedule).
  스냅샷 당시 저장 상태가 없던(코드 기본값 그대로이던) 것은 ``reset``으로, 나머지는 ``start``로 —
  코드 기본값을 나중에 바꿔도 저장된 RUNNING 행이 그것을 덮지 않게. 스냅샷이 STOPPED로 적은 것
  (예: MOIS continuation sensor)은 그대로 둔다. 스냅샷 없이는 거부한다. 지금 정의에 없는 이름은
  ``missing``으로 알리고 1로 끝난다(``--accept-missing``이면 알리고 진행). 성공하면 스냅샷을
  ``<FILE>.restored-<UTC>``로 옮긴다. ``--max-age-hours``(기본 48)보다 오래된 스냅샷은 거부한다.
  창 안에 놓친 cron tick은 Dagster가 따라잡지 않는다. Valkey 상태 schedule은 freeze가 멈추지
  않으므로 대개 할 일이 없다 — 이 예외 이전 판이 멈춘 스냅샷이면(스냅샷 RUNNING·지금 STOPPED)
  다른 것과 같이 되살린다.

스냅샷은 재부팅에 살아남는 곳(운영 계정 홈)에 둔다 — ``/tmp``에 두었다가 사라지면 부분 freeze 뒤의
새 스냅샷이 이미 멈춘 것을 STOPPED로 적어 영구히 꺼 둘 수 있다.

이 도구가 막지 못하는 writer: Map API의 ``launchRun``(관리자 "지금 실행"·offline upload), 관리자
화면의 schedule 켜기, 이미 요청된 backfill. 운영 창에서는 따로 멈춘다.

환경 변수 (값은 출력하지 않는다)
  KTM_DAGSTER_FREEZE_GRAPHQL_URL     기본 ``http://127.0.0.1:11002/graphql``
                                     (n150 공용 webserver loopback, 인증 없음)
  KTM_DAGSTER_FREEZE_BASIC_AUTH_FILE 있으면 ``user:password`` 한 줄 파일로 Basic Auth
                                     (https 또는 loopback 주소일 때만, redirect는 따라가지 않는다)
  KTM_DAGSTER_FREEZE_LOCATION        기본 ``kortravelmap.dagster.definitions``
  KTM_DAGSTER_FREEZE_REPOSITORY      기본 ``__repository__``

종료 코드: 0 성공·dry-run, 1 불완전, 2 입력·연결 오류, 3 스냅샷 안전 검사 거부.

GraphQL mutation 인자·반환형은 n150 Dagster 1.13.24 스키마를 introspection으로 확인한 모양이다
(``stopRunningSchedule(scheduleOriginId, scheduleSelectorId)``·``stopSensor(jobOriginId,
jobSelectorId)`` → ``StopSensorMutationResult``·``startSensor``/``resetSensor`` → ``Sensor``).
HTTP 5xx·연결 오류는 backoff로 다시 시도한다(공용 PG 재생성 직후 webserver의 첫 storage 호출이
HTTP 500을 내는 일이 있었다, 2026-11-23).
"""

from __future__ import annotations

import argparse
import base64
import http.client
import json
import os
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

DESCRIPTION = "Map Dagster code location의 자동 writer를 전부 멈추고 그대로 되돌린다."
SNAPSHOT_FORMAT = "ktm-dagster-freeze/v1"
DEFAULT_URL = "http://127.0.0.1:11002/graphql"
DEFAULT_LOCATION = "kortravelmap.dagster.definitions"
DEFAULT_REPOSITORY = "__repository__"
REPOSITORY_RUN_TAG_KEY = ".dagster/repository"
NONTERMINAL_RUN_STATUSES = ("QUEUED", "NOT_STARTED", "STARTING", "STARTED", "MANAGED", "CANCELING")
RETRY_DELAYS = (2, 5, 10, 20, 30, 45, 60)
RUN_LIST_LIMIT = 200

EXIT_OK = 0
EXIT_INCOMPLETE = 1
EXIT_ERROR = 2
EXIT_REFUSED = 3

#: Valkey 상태 적재(ADR-114 ``weather_state``·``transport_state`` 모듈)의 job·schedule 이름 접두어.
#: 이 job은 Map PG를 읽지도 쓰지도 않는다(``kor_travel_map_client``를 요구하지 않고 operation
#: tag가 없어 run-status sensor도 PG에 반영하지 않는다). freeze는 이 schedule을 멈추지 않고 run
#: 대기에서 이 run을 세지 않는다 — 멈추면 창 동안 PinVi가 보는 날씨·교통 상태가 낡고, 하루 한 번
#: 도는 것은 unfreeze 뒤에도 다음 cron까지(최대 약 24시간) 낡는다(Dagster는 놓친 tick을 따라잡지
#: 않는다). ``tests/unit/test_n150_dagster_freeze.py``가 code location 정의와 대조한다.
STATE_JOB_PREFIXES = ("weather_state_", "transport_state_")


def is_state_job(name: object) -> bool:
    """Valkey 상태 적재 job 또는 그 schedule의 이름인가."""

    return isinstance(name, str) and name.startswith(STATE_JOB_PREFIXES)


class Gql(Protocol):
    def __call__(self, *, query: str, variables: dict[str, Any]) -> dict[str, Any]: ...


class FreezeError(RuntimeError):
    """사람이 읽을 secret-free 오류."""


# --------------------------------------------------------------------------- GraphQL


def _basic_auth_header(path: str) -> str:
    try:
        raw = Path(path).read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise FreezeError(f"basic auth 파일을 읽지 못했다: {type(exc).__name__}") from None
    if ":" not in raw or "\n" in raw:
        raise FreezeError("basic auth 파일은 user:password 한 줄이어야 한다")
    return "Basic " + base64.b64encode(raw.encode()).decode()


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """3xx를 따라가지 않는다 — urllib는 POST redirect에 Authorization을 그대로 실어 보낸다."""

    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


def http_transport(
    url: str, *, auth_file: str | None = None, sleep: Callable[[float], None] = time.sleep
) -> Gql:
    """urllib GraphQL POST. 오류 문자열에 URL·인증을 넣지 않는다."""

    try:
        parts = urllib.parse.urlsplit(url)
        host = parts.hostname
    except ValueError:
        raise FreezeError("KTM_DAGSTER_FREEZE_GRAPHQL_URL을 해석하지 못했다") from None
    if parts.scheme not in {"http", "https"} or not host or parts.username or parts.password:
        raise FreezeError("KTM_DAGSTER_FREEZE_GRAPHQL_URL은 userinfo 없는 http(s) URL이어야 한다")
    headers = {"content-type": "application/json"}
    if auth_file:
        if parts.scheme != "https" and host not in _LOOPBACK_HOSTS:
            raise FreezeError("Basic Auth는 https 또는 loopback 주소로만 보낸다")
        headers["authorization"] = _basic_auth_header(auth_file)
    opener = urllib.request.build_opener(_NoRedirect)

    def post(*, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps({"query": query, "variables": variables}).encode()
        last = ""
        for attempt in range(len(RETRY_DELAYS) + 1):
            request = urllib.request.Request(url, data=body, headers=headers, method="POST")
            try:
                with opener.open(request, timeout=60) as response:
                    payload = json.load(response)
            except urllib.error.HTTPError as exc:
                last = f"HTTP {exc.code}"
                exc.close()
                if exc.code < 500:
                    raise FreezeError(last) from None
            except (json.JSONDecodeError, http.client.HTTPException, OSError) as exc:
                # 연결 오류·잘린 응답·JSON이 아닌 응답(프록시 오류 페이지) — 다시 시도한다.
                # URLError·TimeoutError·ConnectionError는 OSError다.
                last = type(exc).__name__
            except ValueError as exc:
                # 잘못된 URL — 메시지에 URL 원문이 들 수 있어 이름만 남긴다.
                raise FreezeError(f"GraphQL 요청 실패: {type(exc).__name__}") from None
            else:
                if not isinstance(payload, dict):
                    raise FreezeError("GraphQL 응답이 객체가 아니다")
                if payload.get("errors"):
                    raise FreezeError("GraphQL errors: " + json.dumps(payload["errors"])[:300])
                data = payload.get("data")
                if not isinstance(data, dict):
                    raise FreezeError("GraphQL 응답에 data가 없다")
                return data
            if attempt < len(RETRY_DELAYS):
                delay = RETRY_DELAYS[attempt]
                print(f"  retry {attempt + 1}/{len(RETRY_DELAYS)} in {delay}s ({last})")
                sleep(delay)
        raise FreezeError(f"gave up after {len(RETRY_DELAYS) + 1} attempts: {last}")

    return post


_REPOSITORY_QUERY = """
query KtmFreezeInstigators($s: RepositorySelector!) {
  repositoryOrError(repositorySelector: $s) {
    __typename
    ... on Repository {
      schedules { id name defaultStatus canReset scheduleState { selectorId status } }
      sensors {
        id name sensorType defaultStatus canReset sensorState { selectorId status }
      }
    }
    ... on RepositoryNotFoundError { message }
    ... on PythonError { message }
  }
}
"""

_SENSOR_TICKS_QUERY = """
query KtmFreezeSensorTicks($s: RepositorySelector!, $after: Float) {
  repositoryOrError(repositorySelector: $s) {
    __typename
    ... on Repository {
      sensors {
        name
        sensorState { ticks(limit: 1, afterTimestamp: $after) { status timestamp skipReason } }
      }
    }
    ... on RepositoryNotFoundError { message }
    ... on PythonError { message }
  }
}
"""

_RUNS_QUERY = """
query KtmFreezeRuns(
  $limit: Int!, $repositorySelector: RepositorySelector!, $runsFilter: RunsFilter!
) {
  repositoryOrError(repositorySelector: $repositorySelector) {
    __typename
    ... on RepositoryNotFoundError { message }
    ... on PythonError { message }
  }
  runsOrError(filter: $runsFilter, limit: $limit) {
    __typename
    ... on Runs { results { runId status jobName } }
    ... on PythonError { message }
  }
}
"""

_STOP_SCHEDULE = """
mutation KtmFreezeStopSchedule($o: String, $i: String) {
  stopRunningSchedule(scheduleOriginId: $o, scheduleSelectorId: $i) {
    __typename
    ... on ScheduleStateResult { scheduleState { status } }
    ... on PythonError { message }
  }
}
"""

_STOP_SENSOR = """
mutation KtmFreezeStopSensor($o: String, $i: String) {
  stopSensor(jobOriginId: $o, jobSelectorId: $i) {
    __typename
    ... on StopSensorMutationResult { instigationState { status } }
    ... on PythonError { message }
  }
}
"""

_START_SCHEDULE = """
mutation KtmFreezeStartSchedule($s: ScheduleSelector!) {
  startSchedule(scheduleSelector: $s) {
    __typename
    ... on ScheduleStateResult { scheduleState { status } }
    ... on PythonError { message }
  }
}
"""

_RESET_SCHEDULE = """
mutation KtmFreezeResetSchedule($s: ScheduleSelector!) {
  resetSchedule(scheduleSelector: $s) {
    __typename
    ... on ScheduleStateResult { scheduleState { status } }
    ... on PythonError { message }
  }
}
"""

_START_SENSOR = """
mutation KtmFreezeStartSensor($s: SensorSelector!) {
  startSensor(sensorSelector: $s) {
    __typename
    ... on Sensor { sensorState { status } }
    ... on PythonError { message }
  }
}
"""

_RESET_SENSOR = """
mutation KtmFreezeResetSensor($s: SensorSelector!) {
  resetSensor(sensorSelector: $s) {
    __typename
    ... on Sensor { sensorState { status } }
    ... on PythonError { message }
  }
}
"""


@dataclass(frozen=True)
class Instigator:
    kind: str  # "schedule" | "sensor"
    name: str
    status: str  # RUNNING | STOPPED
    origin_id: str
    selector_id: str
    sensor_type: str | None = None
    default_status: str | None = None
    #: Dagster ``canReset`` — 인스턴스에 저장된 상태가 있다(코드 기본값을 덮고 있다).
    stored: bool = True

    @property
    def key(self) -> str:
        return f"{self.kind}:{self.name}"

    @property
    def is_observer(self) -> bool:
        """run-status sensor — 끝난 run을 DB에 반영한다. 멈추는 것은 맨 마지막이다."""

        return self.kind == "sensor" and self.sensor_type == "RUN_STATUS"

    @property
    def is_state(self) -> bool:
        """Valkey 상태 적재 schedule — freeze 대상이 아니다(``STATE_JOB_PREFIXES``)."""

        return self.kind == "schedule" and is_state_job(self.name)


@dataclass(frozen=True)
class Target:
    location: str
    repository: str

    def repository_selector(self) -> dict[str, str]:
        return {"repositoryLocationName": self.location, "repositoryName": self.repository}

    def runs_filter(self, **fields: object) -> dict[str, object]:
        """이 code location의 run만 — Dagster가 모든 run에 다는 repository tag로 좁힌다."""

        tag = {"key": REPOSITORY_RUN_TAG_KEY, "value": f"{self.repository}@{self.location}"}
        return {**fields, "tags": [tag]}


def _repository(data: dict[str, Any]) -> dict[str, Any]:
    repo = data.get("repositoryOrError") or {}
    if repo.get("__typename") != "Repository":
        detail = str(repo.get("message"))[:200]
        raise FreezeError(f"code location을 읽지 못했다: {repo.get('__typename')} {detail}")
    return dict(repo)


def list_instigators(gql: Gql, target: Target) -> dict[str, Instigator]:
    repo = _repository(
        gql(query=_REPOSITORY_QUERY, variables={"s": target.repository_selector()})
    )
    try:
        return _parse_instigators(repo)
    except (KeyError, TypeError, AttributeError) as exc:
        raise FreezeError(f"instigator 응답 모양이 예상과 다르다: {type(exc).__name__}") from None


def _parse_instigators(repo: dict[str, Any]) -> dict[str, Instigator]:
    found: dict[str, Instigator] = {}
    for entry in repo.get("schedules") or []:
        state = entry["scheduleState"]
        item = Instigator(
            kind="schedule",
            name=entry["name"],
            status=state["status"],
            origin_id=entry["id"],
            selector_id=state["selectorId"],
            default_status=entry.get("defaultStatus"),
            stored=bool(entry.get("canReset", True)),
        )
        found[item.key] = item
    for entry in repo.get("sensors") or []:
        state = entry["sensorState"]
        item = Instigator(
            kind="sensor",
            name=entry["name"],
            status=state["status"],
            origin_id=entry["id"],
            selector_id=state["selectorId"],
            sensor_type=entry.get("sensorType"),
            default_status=entry.get("defaultStatus"),
            stored=bool(entry.get("canReset", True)),
        )
        found[item.key] = item
    return found


def latest_sensor_ticks(gql: Gql, target: Target, after: float) -> dict[str, dict[str, Any]]:
    """sensor 이름 → ``after`` 이후 최신 tick(없으면 빠진다)."""

    repo = _repository(
        gql(
            query=_SENSOR_TICKS_QUERY,
            variables={"s": target.repository_selector(), "after": after},
        )
    )
    latest: dict[str, dict[str, Any]] = {}
    for entry in repo.get("sensors") or []:
        ticks = (entry.get("sensorState") or {}).get("ticks") or []
        if ticks:
            latest[entry["name"]] = ticks[0]
    return latest


def active_runs(gql: Gql, target: Target) -> list[dict[str, str]]:
    data = gql(
        query=_RUNS_QUERY,
        variables={
            "limit": RUN_LIST_LIMIT,
            "repositorySelector": target.repository_selector(),
            "runsFilter": target.runs_filter(statuses=list(NONTERMINAL_RUN_STATUSES)),
        },
    )
    repo = data.get("repositoryOrError") or {}
    if repo.get("__typename") != "Repository":
        # location 이름이 틀리면 tag filter가 조용히 0건이 된다 — 그것을 "run 0"으로 읽지 않는다.
        raise FreezeError(f"code location을 찾지 못했다: {repo.get('__typename')}")
    runs = data.get("runsOrError") or {}
    if runs.get("__typename") != "Runs":
        raise FreezeError(f"run 목록을 읽지 못했다: {runs.get('__typename')}")
    return list(runs.get("results") or [])


def writer_runs(gql: Gql, target: Target) -> list[dict[str, str]]:
    """freeze가 기다리는 run — 끝나지 않은 Map run 중 Valkey 상태 적재 run을 뺀 것."""

    return [run for run in active_runs(gql, target) if not is_state_job(run.get("jobName"))]


def _ok(data: dict[str, Any], field: str, ok_type: str) -> None:
    value = data.get(field) or {}
    if value.get("__typename") != ok_type:
        raise FreezeError(f"{field}: {value.get('__typename')} {str(value.get('message'))[:200]}")


def stop(gql: Gql, item: Instigator) -> None:
    variables = {"o": item.origin_id, "i": item.selector_id}
    if item.kind == "schedule":
        result = gql(query=_STOP_SCHEDULE, variables=variables)
        _ok(result, "stopRunningSchedule", "ScheduleStateResult")
    else:
        result = gql(query=_STOP_SENSOR, variables=variables)
        _ok(result, "stopSensor", "StopSensorMutationResult")


def restore(gql: Gql, target: Target, item: Instigator, recorded: dict[str, Any]) -> str:
    """스냅샷의 RUNNING을 되살린다. 저장 상태가 없던 기본 RUNNING은 reset, 나머지는 start."""

    reset = (not recorded.get("stored", True)) and recorded.get("default_status") == "RUNNING"
    if item.kind == "schedule":
        selector = dict(target.repository_selector(), scheduleName=item.name)
        if reset:
            result = gql(query=_RESET_SCHEDULE, variables={"s": selector})
            _ok(result, "resetSchedule", "ScheduleStateResult")
        else:
            result = gql(query=_START_SCHEDULE, variables={"s": selector})
            _ok(result, "startSchedule", "ScheduleStateResult")
    else:
        selector = dict(target.repository_selector(), sensorName=item.name)
        if reset:
            result = gql(query=_RESET_SENSOR, variables={"s": selector})
            _ok(result, "resetSensor", "Sensor")
        else:
            result = gql(query=_START_SENSOR, variables={"s": selector})
            _ok(result, "startSensor", "Sensor")
    return "reset" if reset else "started"


# --------------------------------------------------------------------------- snapshot


@dataclass(frozen=True)
class Snapshot:
    taken_at: datetime
    entries: dict[str, dict[str, Any]]  # key → {status, default_status, stored, sensor_type}

    def status(self, key: str) -> str | None:
        entry = self.entries.get(key)
        return None if entry is None else str(entry["status"])


def snapshot_document(
    target: Target, items: dict[str, Instigator], now: datetime
) -> dict[str, Any]:
    instigators = [
        {
            "kind": item.kind,
            "name": item.name,
            "status": item.status,
            "sensor_type": item.sensor_type,
            "default_status": item.default_status,
            "stored": item.stored,
        }
        for item in sorted(items.values(), key=lambda value: value.key)
    ]
    return {
        "format": SNAPSHOT_FORMAT,
        "location": target.location,
        "repository": target.repository,
        "taken_at": now.isoformat(),
        "count": len(instigators),
        "instigators": instigators,
    }


def write_snapshot(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:  # mkstemp가 0600으로 만든다.
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(document, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        if os.path.exists(tmp_name):
            os.replace(tmp_name, f"{tmp_name}.failed")
        raise


def read_snapshot(path: Path, target: Target) -> Snapshot:
    """형식·location·개수가 맞지 않거나 비어 있으면 거부한다."""

    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise FreezeError(f"스냅샷이 없다: {path}") from None
    except (OSError, json.JSONDecodeError) as exc:
        raise FreezeError(f"스냅샷을 읽지 못했다: {path} ({type(exc).__name__})") from None
    if not isinstance(document, dict) or document.get("format") != SNAPSHOT_FORMAT:
        raise FreezeError(f"스냅샷 형식이 {SNAPSHOT_FORMAT}이 아니다")
    if (document.get("location"), document.get("repository")) != (
        target.location,
        target.repository,
    ):
        raise FreezeError("스냅샷의 code location이 대상과 다르다")
    raw = document.get("instigators")
    if not isinstance(raw, list) or not raw or document.get("count") != len(raw):
        raise FreezeError("스냅샷의 instigator 목록이 비었거나 count와 다르다")
    try:
        taken_at = datetime.fromisoformat(str(document["taken_at"]))
        entries = {f"{entry['kind']}:{entry['name']}": dict(entry) for entry in raw}
    except (KeyError, TypeError, ValueError):
        raise FreezeError("스냅샷 항목을 해석하지 못했다") from None
    if len(entries) != len(raw) or taken_at.tzinfo is None:
        raise FreezeError("스냅샷 항목이 중복이거나 taken_at에 timezone이 없다")
    return Snapshot(taken_at=taken_at, entries=entries)


def _absolute(path: Path) -> Path:
    if not path.is_absolute():
        raise FreezeError("--snapshot은 절대 경로여야 한다(다른 cwd에서 다른 파일을 집지 않게)")
    return path


# --------------------------------------------------------------------------- commands


def _summary(items: dict[str, Instigator]) -> str:
    running = sum(1 for item in items.values() if item.status == "RUNNING")
    state = sum(1 for item in items.values() if item.is_state and item.status == "RUNNING")
    return (
        f"instigators={len(items)} running={running} stopped={len(items) - running} "
        f"(running 중 Valkey 상태 schedule={state} — freeze 대상 아님)"
    )


def _runs_line(runs: Sequence[dict[str, str]]) -> str:
    if not runs:
        return "active_runs=0"
    jobs: dict[str, int] = {}
    for run in runs:
        label = f"{run.get('jobName')}/{run.get('status')}"
        jobs[label] = jobs.get(label, 0) + 1
    detail = ", ".join(f"{label}×{count}" for label, count in sorted(jobs.items()))
    more = "+" if len(runs) >= RUN_LIST_LIMIT else ""
    return f"active_runs={len(runs)}{more} ({detail})"


def cmd_status(gql: Gql, target: Target, snapshot: Path | None) -> int:
    items = list_instigators(gql, target)
    print(f"location={target.location} {_summary(items)}")
    for item in sorted(items.values(), key=lambda value: value.key):
        extra = f" [{item.sensor_type}]" if item.sensor_type else ""
        extra += " [Valkey 상태 — freeze 대상 아님]" if item.is_state else ""
        print(f"  {item.status:<8} {item.key}{extra}")
    print(_runs_line(active_runs(gql, target)))
    if snapshot is not None and _absolute(snapshot).exists():
        recorded = read_snapshot(snapshot, target)
        diff = []
        for key, entry in sorted(recorded.entries.items()):
            current = items[key].status if key in items else "missing"
            if current != entry["status"]:
                diff.append(f"  {key}: snapshot={entry['status']} now={current}")
        new = sorted(set(items) - set(recorded.entries))
        print(
            f"snapshot={snapshot} taken_at={recorded.taken_at.isoformat()} "
            f"recorded={len(recorded.entries)} differs={len(diff)} new={len(new)}"
        )
        for line in diff:
            print(line)
        for key in new:
            print(f"  {key}: not in snapshot (now={items[key].status})")
    return EXIT_OK


def _stop_all(gql: Gql, items: Iterable[Instigator]) -> list[str]:
    failed: list[str] = []
    for item in items:
        try:
            stop(gql, item)
            print(f"  stopped {item.key}")
        except FreezeError as exc:
            print(f"  ERROR stop {item.key}: {exc}")
            failed.append(item.key)
    return failed


def _running(items: dict[str, Instigator], *, observers: bool) -> list[Instigator]:
    """freeze가 멈출 RUNNING instigator — Valkey 상태 schedule은 빠진다."""

    return sorted(
        (
            i
            for i in items.values()
            if i.status == "RUNNING" and i.is_observer == observers and not i.is_state
        ),
        key=lambda i: i.key,
    )


@dataclass
class _Clocks:
    monotonic: Callable[[], float]
    wall: Callable[[], float]
    sleep: Callable[[float], None]


def _wait_runs_zero(
    gql: Gql, target: Target, deadline: float, poll: float, clocks: _Clocks
) -> list[dict[str, str]]:
    runs = writer_runs(gql, target)
    while runs and clocks.monotonic() < deadline:
        print(f"  {_runs_line(runs)} — {int(deadline - clocks.monotonic())}s left")
        clocks.sleep(poll)
        runs = writer_runs(gql, target)
    return runs


def _observers_caught_up(
    gql: Gql,
    target: Target,
    observers: Sequence[Instigator],
    drained_at: float,
    deadline: float,
    poll: float,
    clocks: _Clocks,
) -> list[str]:
    """따라잡지 못한 run-status sensor 목록.

    따라잡음 = run 0 뒤 최신 tick이 **사유 없는** SKIPPED이고, 그런 tick을 서로 다른 두 시각에
    봤다. 사유를 본다: Dagster run-status sensor 감싸개는 사건 하나에 사용자 함수가 값을 돌려주면
    그것을 내고 tick을 끝낸다. ``feature_update_request_failure_sensor``는 실패 사건마다
    ``SkipReason``을 돌려주므로 그 tick은 SKIPPED지만 사건 하나를 처리했고, 실패가 몰렸으면 뒤에
    사건이 남아 있다. 처리할 사건이 없던 tick은 감싸개가 아무것도 내지 않아 사유가 없다.
    한 번으로는 부족하다: run-status sensor는 tick마다 공용 event log의 사건을 몇 건씩만 읽어,
    다른 location의 사건만 읽은 tick도 사유 없는 SKIPPED가 될 수 있다. 도구 호스트와 Dagster
    서버의 시계 차이도 두 번째 tick이 흡수한다.
    """

    seen: dict[str, set[float]] = {item.name: set() for item in observers}
    while True:
        ticks = latest_sensor_ticks(gql, target, drained_at)
        for item in observers:
            tick = ticks.get(item.name) or {}
            if tick.get("status") == "SKIPPED" and not tick.get("skipReason"):
                seen[item.name].add(float(tick.get("timestamp") or 0.0))
            else:
                seen[item.name].clear()
        lagging = sorted(name for name, stamps in seen.items() if len(stamps) < 2)
        if not lagging or clocks.monotonic() >= deadline:
            return lagging
        print(f"  waiting for run-status sensor ticks: {', '.join(lagging)}")
        clocks.sleep(poll)


def cmd_freeze(
    gql: Gql,
    target: Target,
    snapshot: Path,
    *,
    dry_run: bool,
    resume: bool,
    wait_timeout: float,
    settle: float,
    poll: float,
    max_age_hours: float = 24.0,
    clock: Callable[[], float] = time.monotonic,
    wall: Callable[[], float] = time.time,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> int:
    clocks = _Clocks(monotonic=clock, wall=wall, sleep=sleep)
    _absolute(snapshot)
    items = list_instigators(gql, target)
    print(f"before: {_summary(items)}")

    if snapshot.exists():
        if not resume:
            print(f"REFUSE: 스냅샷이 이미 있다: {snapshot}")
            print("중단된 freeze를 이어 하려면 --resume, 끝난 창의 것이면 먼저 unfreeze하라.")
            return EXIT_REFUSED
        recorded = read_snapshot(snapshot, target)
        age = now() - recorded.taken_at
        if age > timedelta(hours=max_age_hours):
            print(f"REFUSE: 스냅샷이 {age}만큼 오래됐다(--max-age-hours {max_age_hours}).")
            print("지난 창의 스냅샷이면 unfreeze 결과를 먼저 확인하라.")
            print("이어 쓰면 그 뒤에 바뀐 instigator 상태를 잃는다.")
            return EXIT_REFUSED
        stray = sorted(
            key
            for key, item in items.items()
            if item.status == "RUNNING" and recorded.status(key) != "RUNNING" and not item.is_state
        )
        if stray:
            print("REFUSE: 스냅샷이 RUNNING으로 적지 않은 instigator가 지금 RUNNING이다:")
            for key in stray:
                print(f"  {key} (snapshot={recorded.status(key) or 'absent'})")
            print("그것을 멈추면 unfreeze가 되살리지 못한다. 누가 켰는지 확인하라.")
            return EXIT_REFUSED
        print(f"snapshot resumed: {snapshot} (taken_at={recorded.taken_at.isoformat()})")
        again = _running(items, observers=False)
        if again:
            # 스냅샷이 RUNNING으로 적은 것은 거부하지 않고 다시 멈춘다. 앞선 시도가 멈추지 못한 것과
            # 창 안에서 누가 다시 켠 것은 여기서 갈리지 않으므로 이름을 남긴다.
            print(
                f"  note: 스냅샷이 RUNNING으로 적은 launcher {len(again)}개가 지금 RUNNING이다 — "
                "앞선 시도가 멈추지 못했거나 창 안에서 다시 켜졌다. 다시 멈춘다:"
            )
            for item in again:
                print(f"    {item.key}")
        orphaned = [
            item
            for key, item in sorted(items.items())
            if item.is_observer and item.status != "RUNNING" and recorded.status(key) == "RUNNING"
        ]
        if orphaned and not dry_run and writer_runs(gql, target):
            # 앞선 시도가 run-status sensor를 멈춘 뒤 run이 생겼다 — 관찰부터 되살린다.
            for item in orphaned:
                restore(gql, target, item, recorded.entries[item.key])
                print(f"  restored {item.key} (run이 있는데 run-status sensor가 꺼져 있었다)")
            items = list_instigators(gql, target)
    else:
        if resume:
            print(f"REFUSE: 이어 할 스냅샷이 없다: {snapshot}")
            return EXIT_REFUSED
        if not _running(items, observers=False):
            print("REFUSE: RUNNING launcher가 하나도 없다 — 이미 얼어 있는 것으로 보인다.")
            print("이 상태를 스냅샷하면 unfreeze가 아무것도 되살리지 못한다.")
            print("기존 스냅샷 경로를 확인하라. 아무것도 바꾸지 않았다.")
            print("운영 창 안의 회전이면 회전의 freeze·unfreeze 단계를 빼라 — 창 freeze가 덮는다.")
            return EXIT_REFUSED
        if dry_run:
            print(f"would write snapshot: {snapshot}")
        else:
            write_snapshot(snapshot, snapshot_document(target, items, now()))
            print(f"snapshot written: {snapshot}")

    launchers = _running(items, observers=False)
    kept = sum(1 for item in items.values() if item.is_state and item.status == "RUNNING")
    print(f"phase 1: stop {len(launchers)} launcher(s) (schedules + non-run-status sensors)")
    print(f"  keep {kept} Valkey state schedule(s) running (Map PG 미사용, run도 기다리지 않는다)")
    if dry_run:
        for item in launchers:
            print(f"  would stop {item.key}")
        observers = _running(items, observers=True)
        print(_runs_line(writer_runs(gql, target)))
        print(f"phase 3 would stop {len(observers)} run-status sensor(s) after runs drain")
        for item in observers:
            print(f"  would stop {item.key}")
        print("FREEZE_DRY_RUN")
        return EXIT_OK
    failed = _stop_all(gql, launchers)
    if failed:
        print("launcher 정지 실패 — run-status sensor는 켜 둔다.")
        print("원인을 본 뒤 --resume으로 다시 돌려라.")
        print(f"FREEZE_INCOMPLETE failed={failed}")
        return EXIT_INCOMPLETE

    deadline = clocks.monotonic() + wait_timeout
    while True:
        print("phase 2: wait for Map runs to finish")
        runs = _wait_runs_zero(gql, target, deadline, poll, clocks)
        if runs:
            print(f"  timeout: {_runs_line(runs)}")
            print("run-status sensor는 켜 둔다(끝나는 run을 DB에 반영).")
            print("--resume으로 이어 기다린다.")
            print(f"FREEZE_INCOMPLETE active_runs={len(runs)}")
            return EXIT_INCOMPLETE
        drained_at = clocks.wall()
        print("  active_runs=0")
        observers = _running(list_instigators(gql, target), observers=True)
        if not observers:
            break
        print(f"phase 3: settle {int(settle)}s, then confirm run-status sensor ticks")
        clocks.sleep(settle)
        lagging = _observers_caught_up(
            gql, target, observers, drained_at, deadline, poll, clocks
        )
        if lagging:
            print(f"FREEZE_INCOMPLETE run-status sensors not caught up: {lagging}")
            return EXIT_INCOMPLETE
        runs = writer_runs(gql, target)
        if not runs:
            break
        # feature_operation_success_sensor가 completion job run을 냈다 — 다시 기다린다.
        print(f"  new runs during settle: {_runs_line(runs)}")

    print(f"phase 4: stop {len(observers)} run-status sensor(s)")
    failed = _stop_all(gql, observers)
    runs = writer_runs(gql, target)
    if runs:
        # 멈추기 직전에 낸 run — 관찰할 sensor를 되살린다.
        print(f"  run appeared while stopping run-status sensors: {_runs_line(runs)}")
        recorded = read_snapshot(snapshot, target)
        for item in observers:
            if item.key not in failed:
                restore(gql, target, item, recorded.entries.get(item.key, {}))
                print(f"  restored {item.key}")
        print("FREEZE_INCOMPLETE — --resume으로 다시 돌려라.")
        return EXIT_INCOMPLETE

    after = list_instigators(gql, target)
    still = sorted(
        key for key, item in after.items() if item.status == "RUNNING" and not item.is_state
    )
    print(f"after: {_summary(after)} {_runs_line(runs)}")
    if failed or still:
        print(f"FREEZE_INCOMPLETE failed={failed} still_running={still}")
        return EXIT_INCOMPLETE
    print("FREEZE_OK")
    return EXIT_OK


def cmd_unfreeze(
    gql: Gql,
    target: Target,
    snapshot: Path,
    *,
    dry_run: bool,
    accept_missing: bool = False,
    max_age_hours: float = 48.0,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> int:
    recorded = read_snapshot(_absolute(snapshot), target)
    age = now() - recorded.taken_at
    if age > timedelta(hours=max_age_hours):
        print(f"REFUSE: 스냅샷이 {age}만큼 오래됐다(--max-age-hours {max_age_hours}).")
        print("그 뒤에 일부러 끈 instigator를 다시 켤 수 있다.")
        print("확인했으면 --max-age-hours를 늘려라.")
        return EXIT_REFUSED
    items = list_instigators(gql, target)
    want_running = sorted(
        key for key, entry in recorded.entries.items() if entry["status"] == "RUNNING"
    )
    missing = [key for key in want_running if key not in items]
    to_start = [
        items[key] for key in want_running if key in items and items[key].status != "RUNNING"
    ]
    # run-status sensor를 먼저 켜야 곧 뜰 run의 상태 전이를 놓치지 않는다.
    to_start.sort(key=lambda i: (not i.is_observer, i.kind != "sensor", i.key))
    kept_stopped = sorted(set(recorded.entries) - set(want_running))
    unexpected = sorted(
        key
        for key, item in items.items()
        if item.status == "RUNNING" and recorded.status(key) != "RUNNING"
    )
    print(
        f"snapshot: taken_at={recorded.taken_at.isoformat()} recorded={len(recorded.entries)} "
        f"running={len(want_running)} kept_stopped={len(kept_stopped)} to_start={len(to_start)}"
    )
    for key in kept_stopped:
        print(f"  keep STOPPED {key}")
    for key in missing:
        print(f"  missing (지금 정의에 없다) {key}")
    for key in unexpected:
        print(f"  note: 스냅샷이 RUNNING으로 적지 않았는데 지금 RUNNING — 건드리지 않는다: {key}")

    failed: list[str] = []
    for item in to_start:
        if dry_run:
            print(f"  would restore {item.key}")
            continue
        try:
            how = restore(gql, target, item, recorded.entries[item.key])
            print(f"  {how} {item.key}")
        except FreezeError as exc:
            print(f"  ERROR restore {item.key}: {exc}")
            failed.append(item.key)
    if dry_run:
        print("UNFREEZE_DRY_RUN")
        return EXIT_OK

    after = list_instigators(gql, target)
    mismatch = sorted(
        key for key in want_running if key in after and after[key].status != "RUNNING"
    )
    print(f"after: {_summary(after)}")
    print(
        "note: 창 동안(taken_at 이후) 놓친 cron tick은 Dagster가 따라잡지 않는다 — "
        "월간·주간 schedule의 tick이 창 안에 있었으면 수동 실행을 검토하라."
    )
    if failed or mismatch or (missing and not accept_missing):
        print(f"UNFREEZE_INCOMPLETE failed={failed} mismatch={mismatch} missing={missing}")
        return EXIT_INCOMPLETE
    restored = snapshot.with_name(f"{snapshot.name}.restored-{now().strftime('%Y%m%dT%H%M%SZ')}")
    os.replace(snapshot, restored)
    print(f"snapshot archived: {restored}")
    print("UNFREEZE_OK" + (f" (accepted missing={missing})" if missing else ""))
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=DESCRIPTION)
    sub = parser.add_subparsers(dest="command", required=True)
    status = sub.add_parser("status", help="instigator·run 상태(읽기 전용)")
    status.add_argument("--snapshot", type=Path)
    freeze = sub.add_parser("freeze", help="스냅샷 → launcher STOP → run 0 → run-status STOP")
    freeze.add_argument("--snapshot", type=Path, required=True)
    freeze.add_argument("--resume", action="store_true", help="기존 스냅샷으로 이어 한다")
    freeze.add_argument("--dry-run", action="store_true")
    freeze.add_argument("--wait-timeout", type=float, default=3600.0)
    freeze.add_argument("--settle", type=float, default=90.0)
    freeze.add_argument("--poll", type=float, default=30.0)
    freeze.add_argument("--max-age-hours", type=float, default=24.0)
    unfreeze = sub.add_parser("unfreeze", help="스냅샷의 RUNNING만 복원")
    unfreeze.add_argument("--snapshot", type=Path, required=True)
    unfreeze.add_argument("--dry-run", action="store_true")
    unfreeze.add_argument("--accept-missing", action="store_true")
    unfreeze.add_argument("--max-age-hours", type=float, default=48.0)
    return parser


def main(argv: Sequence[str] | None = None, gql: Gql | None = None) -> int:
    args = build_parser().parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(line_buffering=True)  # 운영 로그로 옮겨도 진행이 바로 보이게
    target = Target(
        location=os.environ.get("KTM_DAGSTER_FREEZE_LOCATION", DEFAULT_LOCATION),
        repository=os.environ.get("KTM_DAGSTER_FREEZE_REPOSITORY", DEFAULT_REPOSITORY),
    )
    try:
        if gql is None:
            gql = http_transport(
                os.environ.get("KTM_DAGSTER_FREEZE_GRAPHQL_URL", DEFAULT_URL),
                auth_file=os.environ.get("KTM_DAGSTER_FREEZE_BASIC_AUTH_FILE") or None,
            )
        if args.command == "status":
            return cmd_status(gql, target, args.snapshot)
        if args.command == "unfreeze":
            return cmd_unfreeze(
                gql,
                target,
                args.snapshot,
                dry_run=args.dry_run,
                accept_missing=args.accept_missing,
                max_age_hours=args.max_age_hours,
            )
        code = cmd_freeze(
            gql,
            target,
            args.snapshot,
            dry_run=args.dry_run,
            resume=args.resume,
            wait_timeout=args.wait_timeout,
            settle=args.settle,
            poll=args.poll,
            max_age_hours=args.max_age_hours,
        )
    except FreezeError as exc:
        print(f"ERROR {exc}")
        code = EXIT_ERROR
    if args.command == "freeze":
        _rollback_hint(args.snapshot, code, dry_run=args.dry_run)
    return code


def _rollback_hint(snapshot: Path, code: int, *, dry_run: bool) -> None:
    """freeze가 일부를 멈춘 채 끝났을 수 있으면(1·2, 스냅샷 있음) 되돌리는 길을 적는다.

    거부(3)는 아무것도 바꾸지 않았다 — 그때 unfreeze를 부르면 남의 스냅샷(창)을 되살릴 수 있어
    적지 않는다. 자동 회전 스크립트도 같은 규칙을 따른다(scripts/n150/README.md §Dagster freeze).
    """

    if dry_run or code not in (EXIT_INCOMPLETE, EXIT_ERROR):
        return
    if not snapshot.is_absolute() or not snapshot.exists():
        return
    print(f"rollback: 접으려면 unfreeze --snapshot {snapshot} (부분 freeze도 스냅샷대로 되살린다)")
    print(f"rollback: 이어 하려면 원인을 본 뒤 freeze --snapshot {snapshot} --resume")


if __name__ == "__main__":
    sys.exit(main())
