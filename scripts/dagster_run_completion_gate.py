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
#: 탐침. **upstream 호출이 없다** — DB projection만 갱신한다.
#:
#: "부작용이 없다"고 적었던 것은 틀렸다(적대 리뷰 지적). 이 job은 projection 표를
#: 원자적으로 다시 쓰고, 분 단위 schedule의 tick 하나를 먹는다. 여기서 중요한 것은
#: **upstream 쿼터를 쓰지 않는 것**이고, 그 성질을 정적 검사가 결박한다 — provider
#: 적재 job으로 바꾸면 게이트를 돌릴 때마다 일일 한도를 깎는다.
_DEFAULT_PROBE_JOB = "current_weather_summary_refresh"
#: 이 게이트가 만든 run임을 표시한다. 잔여물 판독과 사후 구분에 쓴다.
_GATE_TAG = "kor_travel_map.gate_kind"
_GATE_TAG_VALUE = "dagster_run_completion"
#: 멈춤 판정의 여유. 회수는 poll 간격만큼 늦게 일어난다.
_STUCK_GRACE_SECONDS = 600
#: 살아 있어야 하는 daemon. **개수가 아니라 이름을 센다.**
#:
#: 종전에는 하한이 상수 1이었다 — daemon 하나만 살아 있어도 "non-empty"로 초록이고,
#: 하필 죽은 것이 회수 daemon이면 이 게이트가 겨냥한 바로 그 정지가 보이지 않는다
#: (적대 리뷰 지적). 그래서 종류를 지목한다.
#:
#: - ``MONITORING`` — ``run_monitoring``이 여기 산다. 프로세스가 사라진 run을
#:   실패시켜 큐 슬롯을 푸는 기제 자체다.
#: - ``QUEUED_RUN_COORDINATOR`` — 큐에서 run을 꺼내 띄운다. 형제 저장소가 18시간
#:   멈췄을 때 "Maximum is 10, won't launch more"를 적던 그 daemon이다.
#: - ``SCHEDULER`` / ``SENSOR`` — 이 둘이 없으면 일이 도착하지 않는다.
#:
#: prod 실측 daemon 종류는 7개다(ASSET·BACKFILL·FRESHNESS_DAEMON 포함). 나머지
#: 셋을 필수로 두지 않는 이유는 그것이 없어도 정기 적재가 돌기 때문이다 — 신선도
#: 판정은 **관측된 전부**에 대해 따로 한다.
_REQUIRED_DAEMON_TYPES: tuple[str, ...] = (
    "MONITORING",
    "QUEUED_RUN_COORDINATOR",
    "SCHEDULER",
    "SENSOR",
)


def _run_bound_seconds(tag_value: object, global_bound: float) -> float:
    """이 run이 실제로 받는 runtime 회수 상한(초).

    job tag ``dagster/max_runtime``이 있으면 그것이고, 없으면
    ``run_monitoring.max_runtime_seconds``다. Dagster의 회수 판정이 그 순서다.
    tag가 숫자가 아니면 전역값으로 되돌린다 — 여기서 죽으면 게이트가 판정 대신
    파싱 오류로 끝난다.

    **전역값이 0 이하면 상한이 없는 것으로 본다**(``inf``). config가 상한을
    선언하지 않은 세계에서 "모든 진행 중 run이 stuck"이라고 말하면, 그 자리의
    진짜 문제(``live-config/run-timeout-bounded``가 이미 red다)를 가린다.
    """

    fallback = float(global_bound) if global_bound > 0 else float("inf")
    if tag_value is None:
        return fallback
    try:
        parsed = float(str(tag_value))
    except ValueError:
        return fallback
    return parsed if parsed > 0 else fallback


def _exceeds_reclaim_bound(row: Any, bounds: ReclaimBounds) -> bool:
    """이 run이 **자기 상태의** 회수 기준을 넘겼는가.

    row = ``(run_id, status, seconds_since_start, seconds_since_transition, tag)``.

    - ``STARTING`` — 아직 안 돌고 있다. 기준은 ``start_timeout_seconds``이고,
      경과는 마지막 상태 전이부터 잰다.
    - ``CANCELING`` — 기준은 ``cancel_timeout_seconds``.
    - ``STARTED`` — 기준은 job tag 또는 ``max_runtime_seconds``, 경과는
      ``start_time``부터. ``create_timestamp``로 재면 큐에서 기다린 시간이 섞인다.
    """

    status = str(row[1])
    since_start = float(row[2] or 0.0)
    since_transition = float(row[3] or 0.0)
    if status == "STARTING":
        bound = float(bounds.start_timeout) if bounds.start_timeout > 0 else float("inf")
        return since_transition > bound + _STUCK_GRACE_SECONDS
    if status == "CANCELING":
        bound = (
            float(bounds.cancel_timeout) if bounds.cancel_timeout > 0 else float("inf")
        )
        return since_transition > bound + _STUCK_GRACE_SECONDS
    return since_start > _run_bound_seconds(row[4], bounds.max_runtime) + _STUCK_GRACE_SECONDS


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


def _base_dir(config: dict[str, Any], key: str) -> Any:
    """``<key>.config.base_dir``. 없으면 ``None``."""

    section = config.get(key)
    if not isinstance(section, dict):
        return None
    inner = section.get("config")
    return inner.get("base_dir") if isinstance(inner, dict) else None


@dataclass(frozen=True)
class ReclaimBounds:
    """Dagster가 상태별로 run을 회수하는 기준(초).

    **한 값으로 재면 안 된다.** ``run_monitoring``은 상태마다 다른 knob을 쓴다 —
    띄우지 못하는 run은 ``start_timeout_seconds``(기본 config 600초), 도는 run은
    ``max_runtime_seconds``(21,600초), 취소 중인 run은 ``cancel_timeout_seconds``다.
    셋을 모두 max_runtime으로 재면 **launcher가 죽어 STARTING에 갇힌 run이 6시간
    넘게 초록**이다(2026-09-13 2차 리뷰 지적).
    """

    max_runtime: int
    start_timeout: int
    cancel_timeout: int


def _check_live_config(gate: Gate, config: dict[str, Any]) -> ReclaimBounds:
    """A축 — 배포된 config가 로컬 쓰기 두 자리를 여전히 선언한다."""
    # 이름을 f-string으로도, **루프 변수로도** 만들지 않는다. 판정 호출의 첫 인자가
    # 리터럴이어야 정적 검사가 "이 축이 판정된다"를 볼 수 있다 — 루프로 돌리면
    # 이름이 튜플에만 남아서, 판정을 지워도 검사가 초록이었다(2026-09-13 2차 리뷰).
    gate.require(
        "live-config/local_artifact_storage",
        "under-state-root"
        if _under_state_root(_base_dir(config, "local_artifact_storage"))
        else "elsewhere",
        "under-state-root",
        detail=_base_dir(config, "local_artifact_storage"),
    )
    gate.require(
        "live-config/compute_logs",
        "under-state-root"
        if _under_state_root(_base_dir(config, "compute_logs"))
        else "elsewhere",
        "under-state-root",
        detail=_base_dir(config, "compute_logs"),
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
    return ReclaimBounds(
        max_runtime=int(runtime_cap) if type(runtime_cap) is int else 0,
        start_timeout=_positive_int(monitoring.get("start_timeout_seconds")),
        cancel_timeout=_positive_int(monitoring.get("cancel_timeout_seconds")),
    )


def _positive_int(value: object) -> int:
    """config의 양의 정수. 없거나 이상하면 0(= 상한 없음으로 본다)."""

    return value if type(value) is int and value > 0 else 0


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
    bounds = _check_live_config(gate, config)
    endpoint = f"http://127.0.0.1:{port}/graphql"
    engine = create_engine(dsn, pool_size=1, max_overflow=0)
    population: dict[str, Any] = {
        "kind": "dagster-run-completion",
        "probe_job": args.probe_job,
        "run_timeout_seconds": bounds.max_runtime,
        "start_timeout_seconds": bounds.start_timeout,
    }
    probe: dict[str, Any] = {}

    try:
        with engine.connect() as connection:
            for check_name, table in (
                ("metadata-table/runs", "runs"),
                ("metadata-table/event_logs", "event_logs"),
                ("metadata-table/daemon_heartbeats", "daemon_heartbeats"),
            ):
                exists = connection.execute(
                    text("SELECT to_regclass(:name) IS NOT NULL"),
                    {"name": f"public.{table}"},
                ).scalar()
                gate.require(check_name, bool(exists), True)
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

            # **게이트가 만든 run을 전부 빼고 센다.** 빼지 않으면 이 하한은
            # 항진명제다 — 방금 만든 run이 항상 한 건 있기 때문이다(적대 리뷰 지적).
            #
            # 이번 run만 빼는 것으로는 부족하다. 게이트를 연속으로 돌리면 직전
            # 탐침들이 남아 같은 항진명제로 돌아간다. 그래서 `_GATE_TAG`로 계보
            # 전체를 뺀다 — 그 tag를 다는 이유가 원래 "잔여물 판독과 사후 구분"이다.
            other_runs = connection.execute(
                text(
                    "SELECT count(*) FROM runs r WHERE NOT EXISTS ("
                    "  SELECT 1 FROM run_tags t"
                    "  WHERE t.run_id = r.run_id AND t.key = :gate_key"
                    "    AND t.value = :gate_value"
                    ")"
                ),
                {"gate_key": _GATE_TAG, "gate_value": _GATE_TAG_VALUE},
            ).scalar()
            population["runs_observed_excluding_gate"] = int(other_runs or 0)
            gate.require(
                "floor/runs-observed",
                "non-empty" if int(other_runs or 0) >= 1 else "empty",
                "non-empty",
                detail=other_runs,
            )

            # **run마다 자기 상한으로, 그 상태의 기준 시각으로 잰다.**
            #
            # 전역 상한 하나로 재면 job tag ``dagster/max_runtime``(최신성 job
            # 7,200초)을 세 배 넘긴 run이 네 시간 더 초록이다. 그리고 경과를
            # ``create_timestamp``로 재면 **큐에서 기다린 시간**이 섞여 큐가 밀린
            # 정상 상황에서 거짓 red가 난다 — Dagster가 max_runtime과 비교하는 것은
            # ``start_time``이다. 마지막으로 STARTING은 max_runtime이 아니라
            # ``start_timeout_seconds``로 회수된다. 셋 다 2026-09-13 2차 리뷰가
            # 잡았다.
            in_progress = connection.execute(
                text(
                    "SELECT r.run_id, r.status, "
                    "EXTRACT(EPOCH FROM (now() - COALESCE("
                    "  to_timestamp(r.start_time), r.update_timestamp,"
                    "  r.create_timestamp))), "
                    "EXTRACT(EPOCH FROM (now() - COALESCE("
                    "  r.update_timestamp, r.create_timestamp))), "
                    "(SELECT t.value FROM run_tags t "
                    " WHERE t.run_id = r.run_id AND t.key = 'dagster/max_runtime') "
                    "FROM runs r "
                    "WHERE r.status IN ('STARTING', 'STARTED', 'CANCELING')"
                )
            ).all()
            stuck_runs = [
                f"{row[0]}({row[1]})"
                for row in in_progress
                if _exceeds_reclaim_bound(row, bounds)
            ]
            population["in_progress_runs"] = len(in_progress)
            gate.require(
                "stuck/in-progress-past-bound",
                len(stuck_runs),
                0,
                detail=stuck_runs[:5],
            )

            beats = connection.execute(
                text(
                    "SELECT daemon_type, "
                    "max(timestamp) > now() - make_interval(secs => :tolerance) "
                    "FROM daemon_heartbeats GROUP BY daemon_type"
                ),
                {"tolerance": _stale_tolerance()},
            ).all()
            fresh_types = {str(row[0]) for row in beats if bool(row[1])}
            observed_types = {str(row[0]) for row in beats}
            population["daemon_types_observed"] = sorted(observed_types)
            population["daemon_types_stale"] = sorted(observed_types - fresh_types)

            # **이름을 센다.** 개수 하한은 회수 daemon만 죽은 세계에서 초록이었다.
            missing = sorted(set(_REQUIRED_DAEMON_TYPES) - fresh_types)
            gate.require(
                "floor/heartbeat-types",
                "all-required-fresh" if not missing else f"missing:{','.join(missing)}",
                "all-required-fresh",
                detail=sorted(_REQUIRED_DAEMON_TYPES),
            )
            # **필수 종류에 대해서만 판정한다.** 분모를 "관측된 전부"로 두면
            # 한 번이라도 떴다가 꺼진 daemon의 heartbeat 행이 낡은 채로 영구
            # 잔류해(`daemon_heartbeats.daemon_type`은 UNIQUE이고 wipe로만 지워진다)
            # 이 축이 그때부터 절대 초록이 되지 않는다. Dagster 자신도 신선도를
            # required 종류에 대해서만 판정한다(2026-09-13 2차 리뷰 지적).
            required = set(_REQUIRED_DAEMON_TYPES)
            fresh_required = sorted(required & fresh_types)
            gate.require(
                "daemon/heartbeats-fresh",
                f"{len(fresh_required)}/{len(required)}",
                f"{len(required)}/{len(required)}",
                detail=sorted(required - fresh_types),
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
