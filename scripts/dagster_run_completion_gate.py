#!/usr/bin/env python3
"""배포된 세대가 **run을 완주시키는지** 실측한다 (T-VN-DAGSTER-STORAGE 조문 3).

배포 사후점검은 컨테이너가 healthy인지와 정본/실물 image가 같은지를 본다. 그 둘이
초록이어도 run은 한 번도 끝나지 않을 수 있다 — 2026-09-11에 정확히 그랬다. 이 prod의
Dagster run 이력이 전부 실패였는데(조회 시점 8건 중 7 FAILURE + 1 진행) 컨테이너는
계속 healthy였고, `feature.features`가 0행이라는 사실이 드러나고 나서야 알았다.
원인은 `dagster.yaml`이 로컬 쓰기 두 축을 선언하지 않아 Dagster가 봉인된
`DAGSTER_HOME` 아래에 쓰려 한 것이었다.

**healthy와 "실행 가능"은 다른 사실이다.** 이 게이트가 그 둘을 가른다.

무엇을 보는가 — 다섯 축이 각각 독립적으로 빨개진다.

A. **배에 실린 live config**가 로컬 쓰기 두 자리를 여전히 선언한다. 저장소의 파일이
   아니라 컨테이너 안의 ``$DAGSTER_HOME/dagster.yaml``을 읽는다 — 배포된 것이
   무엇인지가 질문이기 때문이다. 2026-09-11 사고 당시 이 축이 즉시 red다.
B. metadata 표가 실재한다. ``should_autocreate_tables: false``이므로 표 부재는
   실재하는 실패다 — 만들지 않는다.
C. **daemon heartbeat가 신선하다.** 회수 기제(run_monitoring, queue dequeue)는 전부
   daemon 프로세스 안의 스레드다. 그것이 죽거나 끼이면 아래 D가 영원히 안 끝난다.
D. **능동 탐침 run이 완주한다.** 이 호출이 만든 새 run 하나가 ``SUCCESS``에 닿는다.
   이미 쌓인 성공 이력이 통과를 사 주지 못한다 — 매번 새 run을 요구한다.
E. **멈춘 run이 없다.** 자기 상한을 넘겨 여전히 진행 중인 run은 슬롯을 붙잡고 있고,
   그것이 형제 저장소를 18시간 멈춘 상태다.

항진명제가 아닌 근거는 **하한**이다. 빈 세계(run 0건, heartbeat 0건)에서 위 판정들이
"위반 없음"으로 초록이 되지 않도록, 본 것의 개수에 하한을 건다.

실행 위치는 ``dagster``(webserver) 컨테이너다 — metadata DSN과 GraphQL endpoint가
거기 있다. ``scripts/``는 이미지에 없으므로 stdin으로 밀어 넣는다::

    C=$(docker ps --filter label=com.docker.compose.service=dagster \\
                  --format '{{.Names}}' | head -1)
    docker exec -i "$C" python3 - --json < scripts/dagster_run_completion_gate.py

exit code
    0  전부 통과
    1  판정 실패 — 위 다섯 축 중 하나가 red
    2  env/config 부재 — 판정 불가
    3  관측 불가 — GraphQL 도달 실패, code location 로딩 실패, 탐침 job 부재
"""

from __future__ import annotations

import argparse
import json
import os
import posixpath
import sys
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field
from typing import Any

import yaml
from sqlalchemy import create_engine, text

#: 이미지가 appuser에게 넘긴 유일한 쓰기 자리.
_LOCAL_STATE_ROOT = "/opt/dagster/state"
#: 부작용 없는 탐침. DB projection 전용이라 provider 호출도 write도 없다.
_DEFAULT_PROBE_JOB = "current_weather_summary_refresh"
#: 이 게이트가 만든 run임을 표시한다. 잔여물 판독과 사후 구분에 쓴다.
_GATE_TAG = "kor_travel_map.gate_kind"
_GATE_TAG_VALUE = "dagster_run_completion"
#: 멈춤 판정의 여유. 회수는 poll 간격만큼 늦게 일어난다.
_STUCK_GRACE_SECONDS = 600
#: 본 것의 하한. 빈 세계에서 초록이 되는 것을 막는다.
_MIN_HEARTBEAT_TYPES = 1


class GateUnobservable(RuntimeError):
    """관측 자체가 불가능하다 — 판정 실패와 섞지 않는다."""


class GateEnvironmentMissing(RuntimeError):
    """판정에 필요한 env/config가 없다."""


@dataclass(frozen=True)
class Check:
    name: str
    observed: str | None
    expected: str
    detail: str | None = None

    @property
    def ok(self) -> bool:
        return self.observed == self.expected


@dataclass
class Gate:
    checks: list[Check] = field(default_factory=list)

    def require(
        self, name: str, observed: object, expected: object, detail: object = None
    ) -> None:
        self.checks.append(
            Check(
                name=name,
                observed=None if observed is None else str(observed),
                expected=str(expected),
                detail=None if detail is None else str(detail),
            )
        )


def _require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise GateEnvironmentMissing(f"{name}이 없습니다")
    return value


def _graphql(endpoint: str, query: str, variables: dict[str, Any] | None = None) -> Any:
    payload = json.dumps({"query": query, "variables": variables or {}}).encode("utf-8")
    request = urllib.request.Request(
        endpoint, data=payload, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            document = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        raise GateUnobservable(f"GraphQL 도달 실패: {exc}") from exc
    if document.get("errors"):
        raise GateUnobservable(f"GraphQL 오류: {document['errors'][:1]}")
    return document["data"]


_REPOSITORIES = """
{
  repositoriesOrError {
    __typename
    ... on RepositoryConnection {
      nodes { name location { name } pipelines { name } }
    }
    ... on PythonError { message }
  }
}
"""

_LAUNCH = """
mutation($params: ExecutionParams!) {
  launchPipelineExecution(executionParams: $params) {
    __typename
    ... on LaunchRunSuccess { run { runId } }
    ... on PythonError { message }
  }
}
"""


def _selector_for(endpoint: str, job_name: str) -> dict[str, str]:
    data = _graphql(endpoint, _REPOSITORIES)["repositoriesOrError"]
    if data.get("__typename") != "RepositoryConnection":
        raise GateUnobservable(
            f"code location을 읽지 못했습니다: {data.get('message', data)!s:.200}"
        )
    for node in data["nodes"]:
        names = {pipeline["name"] for pipeline in node["pipelines"]}
        if job_name in names:
            return {
                "repositoryName": node["name"],
                "repositoryLocationName": node["location"]["name"],
                "jobName": job_name,
            }
    raise GateUnobservable(f"배포된 code location에 job이 없습니다: {job_name}")


def _launch_probe(endpoint: str, selector: dict[str, str]) -> str:
    params = {
        "selector": selector,
        "mode": "default",
        "executionMetadata": {
            "tags": [
                {"key": _GATE_TAG, "value": _GATE_TAG_VALUE},
                {"key": f"{_GATE_TAG}_nonce", "value": uuid.uuid4().hex},
            ]
        },
    }
    result = _graphql(endpoint, _LAUNCH, {"params": params})["launchPipelineExecution"]
    if result.get("__typename") != "LaunchRunSuccess":
        raise GateUnobservable(
            f"탐침 run을 띄우지 못했습니다: {result.get('__typename')} "
            f"{result.get('message', '')!s:.200}"
        )
    return str(result["run"]["runId"])


def _live_config(dagster_home: str) -> dict[str, Any]:
    path = posixpath.join(dagster_home, "dagster.yaml")
    try:
        with open(path, encoding="utf-8") as handle:
            document = yaml.safe_load(handle.read())
    except (OSError, yaml.YAMLError) as exc:
        raise GateEnvironmentMissing(f"live config를 읽지 못했습니다: {path}") from exc
    if not isinstance(document, dict):
        raise GateEnvironmentMissing(f"live config가 매핑이 아닙니다: {path}")
    return document


def _under_state_root(value: object) -> bool:
    if not isinstance(value, str) or not value.startswith("/"):
        return False
    return posixpath.normpath(value).startswith(f"{_LOCAL_STATE_ROOT}/")


def _check_live_config(gate: Gate, config: dict[str, Any]) -> int:
    """A축 — 배포된 config가 로컬 쓰기 두 자리를 여전히 선언한다."""
    for key in ("local_artifact_storage", "compute_logs"):
        section = config.get(key)
        base_dir = (
            section.get("config", {}).get("base_dir")
            if isinstance(section, dict)
            else None
        )
        gate.require(
            f"live-config/{key}",
            "under-state-root" if _under_state_root(base_dir) else "elsewhere",
            "under-state-root",
            detail=base_dir,
        )
    storage = config.get("storage")
    postgres = storage.get("postgres") if isinstance(storage, dict) else None
    gate.require(
        "live-config/storage-is-postgres",
        "postgres" if isinstance(postgres, dict) else "not-postgres",
        "postgres",
    )
    gate.require(
        "live-config/no-autocreate",
        (postgres or {}).get("should_autocreate_tables"),
        False,
    )
    monitoring = config.get("run_monitoring") or {}
    gate.require("live-config/run-monitoring", monitoring.get("enabled"), True)
    runtime_cap = monitoring.get("max_runtime_seconds")
    gate.require(
        "live-config/run-timeout-bounded",
        "bounded" if type(runtime_cap) is int and runtime_cap >= 1 else "unbounded",
        "bounded",
        detail=runtime_cap,
    )
    runs = (config.get("concurrency") or {}).get("runs") or {}
    queue_cap = runs.get("max_concurrent_runs")
    gate.require(
        "live-config/queue-cap-declared",
        "declared" if type(queue_cap) is int and queue_cap >= 1 else "inherited",
        "declared",
        detail=queue_cap,
    )
    return int(runtime_cap) if type(runtime_cap) is int else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--probe-job", default=_DEFAULT_PROBE_JOB)
    parser.add_argument("--timeout-seconds", type=int, default=600)
    parser.add_argument("--poll-seconds", type=int, default=5)
    args = parser.parse_args()

    try:
        dsn = _require_env("KOR_TRAVEL_MAP_DAGSTER_PG_URL")
        dagster_home = _require_env("DAGSTER_HOME")
        port = _require_env("KOR_TRAVEL_MAP_DAGSTER_PORT")
        config = _live_config(dagster_home)
    except GateEnvironmentMissing as exc:
        print(f"!! {exc}", file=sys.stderr)
        return 2

    gate = Gate()
    run_timeout = _check_live_config(gate, config)
    endpoint = f"http://127.0.0.1:{port}/graphql"
    engine = create_engine(dsn, pool_size=1, max_overflow=0)
    population: dict[str, Any] = {
        "kind": "dagster-run-completion",
        "probe_job": args.probe_job,
        "run_timeout_seconds": run_timeout,
    }
    probe: dict[str, Any] = {}

    try:
        with engine.connect() as connection:
            for table in ("runs", "event_logs", "daemon_heartbeats"):
                exists = connection.execute(
                    text("SELECT to_regclass(:name) IS NOT NULL"),
                    {"name": f"public.{table}"},
                ).scalar()
                gate.require(f"metadata-table/{table}", bool(exists), True)
            epoch = connection.execute(
                text("SELECT (transaction_timestamp() AT TIME ZONE 'UTC')")
            ).scalar()
        population["epoch_utc"] = str(epoch)

        selector = _selector_for(endpoint, args.probe_job)
        run_id = _launch_probe(endpoint, selector)
        probe = {"run_id": run_id, "selector": selector}

        deadline = time.monotonic() + args.timeout_seconds
        status = None
        while time.monotonic() < deadline:
            with engine.connect() as connection:
                status = connection.execute(
                    text("SELECT status FROM runs WHERE run_id = :run_id"),
                    {"run_id": run_id},
                ).scalar()
            if status in {"SUCCESS", "FAILURE", "CANCELED"}:
                break
            time.sleep(args.poll_seconds)
        probe["waited_seconds"] = round(
            args.timeout_seconds - max(deadline - time.monotonic(), 0)
        )
        probe["status"] = status

        # 판정은 단일 read-only snapshot에서 한다 — 대기 중 흔들린 값으로 재지 않는다.
        with engine.connect() as connection, connection.begin():
            connection.execute(
                text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            )
            gate.require("probe/reaches-success", status, "SUCCESS")

            total_runs = connection.execute(text("SELECT count(*) FROM runs")).scalar()
            population["runs_observed"] = int(total_runs or 0)
            gate.require(
                "floor/runs-observed",
                "non-empty" if int(total_runs or 0) >= 1 else "empty",
                "non-empty",
                detail=total_runs,
            )

            stuck = connection.execute(
                text(
                    "SELECT count(*) FROM runs "
                    "WHERE status IN ('STARTING', 'STARTED', 'CANCELING') "
                    "AND create_timestamp < now() - make_interval(secs => :bound)"
                ),
                {"bound": run_timeout + _STUCK_GRACE_SECONDS},
            ).scalar()
            gate.require("stuck/in-progress-past-bound", int(stuck or 0), 0)

            beats = connection.execute(
                text(
                    "SELECT count(*), "
                    "count(*) FILTER (WHERE timestamp > now() - make_interval("
                    "secs => :tolerance)) "
                    "FROM daemon_heartbeats"
                ),
                {"tolerance": _stale_tolerance()},
            ).one()
            population["heartbeat_types"] = int(beats[0])
            gate.require(
                "floor/heartbeat-types",
                "non-empty" if int(beats[0]) >= _MIN_HEARTBEAT_TYPES else "empty",
                "non-empty",
                detail=beats[0],
            )
            gate.require(
                "daemon/heartbeats-fresh",
                f"{int(beats[1])}/{int(beats[0])}",
                f"{int(beats[0])}/{int(beats[0])}",
            )
    except GateUnobservable as exc:
        print(f"!! 관측 불가: {exc}", file=sys.stderr)
        return 3
    finally:
        engine.dispose()

    failed = [check for check in gate.checks if not check.ok]
    if args.json:
        json.dump(
            {
                "checks": [
                    {
                        "name": check.name,
                        "observed": check.observed,
                        "expected": check.expected,
                        "detail": check.detail,
                        "ok": check.ok,
                    }
                    for check in gate.checks
                ],
                "counts": {"total": len(gate.checks), "failed": len(failed)},
                "population": population,
                "probe": probe,
                "result": "failed" if failed else "passed",
                "version": 1,
            },
            sys.stdout,
            ensure_ascii=False,
            sort_keys=True,
        )
        sys.stdout.write("\n")
    else:
        for check in gate.checks:
            mark = "OK " if check.ok else "!! "
            extra = "" if check.detail is None else f"  ({check.detail})"
            print(
                f"{mark}{check.name}: observed={check.observed} "
                f"expected={check.expected}{extra}"
            )
        print(f"{len(gate.checks) - len(failed)}/{len(gate.checks)} passed")
    return 1 if failed else 0


def _stale_tolerance() -> int:
    raw = os.environ.get("DAGSTER_DAEMON_HEARTBEAT_TOLERANCE", "").strip()
    return int(raw) if raw.isdecimal() else 1800


if __name__ == "__main__":
    raise SystemExit(main())
