"""run 완주 게이트가 **재겠다고 말한 것을 실제로 들고 있는지** 결박한다.

이 게이트는 prod metadata DB와 GraphQL endpoint가 있어야 돌므로 CI에서 실행할 수
없다. 그렇다고 검사 밖에 두면, 술어가 하나씩 빠져도 아무도 모른 채 "배포 사후점검이
run 완주를 본다"는 주장만 남는다 — 이 저장소가 반복한 실패 모양이다.

그래서 **재는 대상의 이름**을 정적으로 확인한다. 약한 검사인 것을 안다: 이름이
있어도 술어가 틀릴 수 있다. 그 약점은 실측이 메운다 — 게이트 자체를 prod에서 돌려
2026-09-11 사고 config로 되돌렸을 때 red가 되는 것을 확인했고(`live-config` 두 축),
그 기록은 acceptance §T-VN-DAGSTER-STORAGE에 있다. 여기서 잡는 것은 **그 술어가
조용히 사라지는 것**이다.

탐침 job만은 이름이 아니라 **성질**을 잰다(아래 "탐침 job의 성질") — 게이트의 기본 탐침을
배포되는 Definitions에서 풀어, 일을 할 수 없는 job인지 resource·config·import·실행으로 본다.
"""

from __future__ import annotations

import ast
import inspect
import time
from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[2]
_GATE = _ROOT / "scripts" / "dagster_run_completion_gate.py"

#: 게이트가 반드시 재야 하는 축. 각각이 2026-09-11 사고의 한 겹이거나, 형제
#: 저장소가 18시간 멈춘 기제의 한 겹이다.
_REQUIRED_CHECKS = {
    # 사고 당시 config — 로컬 쓰기 두 축이 봉인된 DAGSTER_HOME으로 갔다.
    "live-config/local_artifact_storage",
    "live-config/compute_logs",
    # weather의 두 번째 겹 — storage가 SQLite로 떨어지면 종결 이벤트를 잃는다.
    "live-config/storage-is-postgres",
    "live-config/no-autocreate",
    # 회수 기제가 켜져 있고 이유를 묻지 않는 상한을 갖는다.
    "live-config/run-monitoring",
    "live-config/run-timeout-bounded",
    # 큐 상한이 버전 기본값이 아니라 이 파일에서 온다.
    "live-config/queue-cap-declared",
    # 능동 탐침 — 쌓인 성공 이력이 통과를 사 주지 못한다.
    "probe/reaches-success",
    # 멈춘 run이 슬롯을 붙잡고 있지 않다.
    "stuck/in-progress-past-bound",
    # 회수 기제를 담은 프로세스가 살아 있다.
    "daemon/heartbeats-fresh",
    # 빈 세계에서 초록이 되지 않는다.
    "floor/runs-observed",
    "floor/heartbeat-types",
}


def _judged_check_names() -> set[str]:
    """``gate.require(...)``의 **첫 인자 리터럴**만 모은다.

    두 번 좁혔다.

    1차: 모듈의 모든 문자열 리터럴을 모으던 것 → docstring까지 세어서 판정을
    지우고 문서에 이름만 남겨도 초록이었다.

    2차: 그것을 고치며 "require를 부르는 함수 안의 모든 튜플/리스트"를 허용했는데
    (축을 루프로 도는 자리가 있었다), 그 완화가 같은 구멍을 다시 열었다 — 루프
    변수로 판정하는 축은 이름이 **튜플에만** 있으므로 `gate.require(...)`를
    지워도 초록이었다(2026-09-13 2차 리뷰가 변이로 재현했다). 지금은 게이트
    쪽에서 그 루프를 펴서 첫 인자를 리터럴로 만들었고, 여기서는 그 자리만 본다.
    """

    tree = ast.parse(_GATE.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef):
            continue
        if not _calls_require(node):
            continue
        for child in ast.walk(node):
            # (a) `require("이름", ...)`의 첫 인자
            if isinstance(child, ast.Call) and _is_require(child) and child.args:
                first = child.args[0]
                if isinstance(first, ast.Constant) and isinstance(first.value, str):
                    names.add(first.value)
    return names


def _is_require(call: ast.Call) -> bool:
    func = call.func
    if isinstance(func, ast.Attribute):
        return func.attr == "require"
    return isinstance(func, ast.Name) and func.id == "require"


def _calls_require(node: ast.AST) -> bool:
    return any(
        isinstance(child, ast.Call) and _is_require(child) for child in ast.walk(node)
    )


def test_the_gate_source_parses() -> None:
    """유도의 전제. 파싱되지 않으면 아래 단언이 무엇도 재지 못한다."""
    assert _GATE.is_file(), f"{_GATE}가 없다"
    judged = _judged_check_names()
    assert len(judged) >= len(_REQUIRED_CHECKS), (
        f"`require(...)` 호출을 {len(judged)}개만 찾았다 — 유도가 낡았다. 찾은 것="
        f"{sorted(judged)}"
    )


@pytest.mark.parametrize("check_name", sorted(_REQUIRED_CHECKS))
def test_the_gate_still_measures(check_name: str) -> None:
    """각 축이 **판정되고** 있다 — 이름이 어딘가 적혀 있는 것으로는 부족하다."""
    assert check_name in _judged_check_names(), (
        f"게이트가 `{check_name}`을 더 이상 **판정하지** 않는다(`require(...)`의 "
        "첫 인자가 아니다). 이 축은 2026-09-11 사고나 형제 저장소의 18시간 정지 중 "
        "한 겹이다 — 지우려면 그 겹이 왜 사라졌는지 acceptance에 먼저 적어라."
    )


def test_the_gate_reads_the_live_config_not_the_repo_copy() -> None:
    """배포된 것을 봐야 한다 — 저장소의 파일은 배포된 것이 아니다.

    2026-09-13에 같은 착각으로 `docker-compose.yml`을 Map 저장소에서 고치고
    "prod의 공백을 메웠다"고 적었다가 적대 리뷰에 잡혔다. prod가 읽는 것은 다른
    파일이었다. 이 게이트는 그 실수를 구조적으로 못 하게 한다 — 컨테이너 안의
    `$DAGSTER_HOME/dagster.yaml`을 읽는다.
    """
    source = _GATE.read_text(encoding="utf-8")
    assert "DAGSTER_HOME" in source
    assert 'posixpath.join(dagster_home, "dagster.yaml")' in source, (
        "게이트가 live config 경로를 `$DAGSTER_HOME`에서 유도하지 않는다 — "
        "저장소 사본을 읽으면 배포된 것이 아니라 적어 둔 것을 재게 된다."
    )


# -- 탐침 job의 성질 ----------------------------------------------------------------------
#
# 게이트가 재는 것은 run 실행 **경로**다. 탐침 job이 일을 하면 게이트를 돌리는 것 자체가
# 운영 행위가 된다 — 종전 기본 탐침 ``cache_target_snapshot_gc``는 prod에서 한 번도 돈 적
# 없는 GC라 첫 실행이 최대 2,000 batch backlog를 지우고 600초 탐침 상한을 넘길 수 있었다
# (2026-10-02 적대 리뷰). 종전 검사는 그 job **이름**이 기본값인지만 봤다 — 이름이 맞는
# 동안 job이 무엇을 하든 초록이었다.
#
# 여기서는 이름을 적지 않는다. 게이트가 실제로 쓰는 기본값(``--probe-job``의 default)에서
# 출발해 배포되는 ``defs``의 job을 풀고, 그 job이 **일을 할 수 없다**는 성질을 잰다.
#
# - 요구 resource ⊆ ``{"io_manager"}`` — Dagster는 run이 요구하는 resource만 초기화한다.
#   DB client·provider record·geo client를 요구하지 않으면 그 run에서 만들어지지 않는다.
# - run config 없이 유효하다 — 게이트는 config 없이 launch한다.
# - op 모듈이 Map 코드·DB driver·HTTP client를 import하지 않는다(허용 목록), hook이 없다.
# - operation key tag가 없다 — 있으면 상태 sensor가 ``ops.import_jobs``에 행을 만든다.
# - in-process로 실제로 돌려 성공하고 수 초 안에 끝난다(효과 결박).
#
# - pool·retry policy가 없다 — pool은 탐침을 적재 뒤에 줄 세우고 retry는 실패를 가린다.
#
# **red 재현**(2026-10-02, WSL dagster 1.13.16에서 이 함수들을 직접 호출해 확인). 게이트의
# ``_DEFAULT_PROBE_JOB``을 ``"cache_target_snapshot_gc"``로 되돌리면 resource 검사
# (``kor_travel_map_client``), import 검사(``kortravelmap.infra.*``·상대 import), pool/retry
# 검사(``MAINTENANCE_RETRY_POLICY``), in-process 검사(전제 실패) 넷이 빨개진다. config 검사와
# operation key 검사는 초록으로 남는다 — 그 job의 config는 전부 기본값이 있고 operation key
# tag도 없다. 그래서 그 둘 하나만으로는 이 성질을 잴 수 없다.

#: 탐침이 요구해도 되는 resource. op 출력이 있으면 Dagster는 ``io_manager``를 언제나
#: 요구한다. Map ``defs``가 그것을 바인딩하지 않는 동안(아래에서 확인) 구현은 Dagster 기본
#: filesystem io_manager이고, 쓰는 자리는 ``local_artifact_storage`` — 게이트 축 A가 재는
#: 2026-09-11 사고 자리다. 탐침이 거기 실제로 한 번 쓰는 것은 의도다.
_PROBE_ALLOWED_RESOURCE_KEYS = frozenset({"io_manager"})

#: 탐침 op 모듈이 import해도 되는 최상위 이름. 허용 목록이다 — 금지 목록은 새 driver를
#: 놓친다. Map 패키지(``kortravelmap``)·상대 import도 허용하지 않는다: 그 길로 infra
#: writer와 provider client에 닿는다.
_PROBE_ALLOWED_IMPORT_ROOTS = frozenset({"__future__", "typing", "collections", "dagster"})

#: in-process 완주 상한(초). 게이트의 탐침 상한(600초)보다 훨씬 작다 — 아무 일도 하지
#: 않는 run이 수십 초 걸린다면 그것은 이미 일을 하고 있다.
_PROBE_MAX_SECONDS = 30.0


def _gate_default_probe_job() -> str:
    """게이트가 **실제로** launch하는 기본 탐침 — ``--probe-job``의 ``default``를 푼다.

    상수 이름이 아니라 argparse가 쓰는 값을 따른다. default가 상수를 가리키면 모듈
    최상위 대입에서 그 값을 읽는다.
    """

    tree = ast.parse(_GATE.read_text(encoding="utf-8"))
    constants: dict[str, str] = {}
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    constants[target.id] = node.value.value
    defaults: list[str | None] = []
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "add_argument"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and node.args[0].value == "--probe-job"
        ):
            continue
        for keyword in node.keywords:
            if keyword.arg != "default":
                continue
            value = keyword.value
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                defaults.append(value.value)
            elif isinstance(value, ast.Name):
                defaults.append(constants.get(value.id))
            else:
                defaults.append(None)
    assert len(defaults) == 1, f"`--probe-job` 정의를 하나로 찾지 못했다: {defaults}"
    assert defaults[0], "`--probe-job` 기본값을 문자열로 풀지 못했다 — 유도가 낡았다."
    return defaults[0]


@pytest.fixture(scope="module")
def probe_job() -> Any:
    from kortravelmap.dagster.definitions import defs

    name = _gate_default_probe_job()
    names = {job.name for job in defs.resolve_all_job_defs()}
    assert name in names, (
        f"게이트의 기본 탐침 `{name}`이 배포되는 Definitions에 없다 — 게이트가 exit 3"
        "(탐침 job 부재)로 끝난다."
    )
    return defs.resolve_job_def(name)


def test_the_probe_requires_no_resource_that_can_do_work(probe_job: Any) -> None:
    from kortravelmap.dagster.definitions import defs

    required = set(probe_job.required_resource_keys)
    assert required <= _PROBE_ALLOWED_RESOURCE_KEYS, (
        f"탐침 `{probe_job.name}`이 resource "
        f"{sorted(required - _PROBE_ALLOWED_RESOURCE_KEYS)}를 요구한다 — 게이트를 돌릴 "
        "때마다 그 resource가 만들어지고(DB·upstream) 탐침이 일을 한다."
    )
    assert "io_manager" not in defs.resources, (
        "Map Definitions가 `io_manager`를 바인딩했다 — 허용의 전제(Dagster 기본 filesystem "
        "구현)가 깨졌다. 그 구현이 무엇을 쓰는지 보고 이 허용을 다시 판단해라."
    )


def test_the_probe_needs_no_run_config(probe_job: Any) -> None:
    from dagster import validate_run_config

    # 유효하지 않으면 DagsterInvalidConfigError — 게이트는 config 없이 launch한다.
    validate_run_config(probe_job, {})


def _hook_defs(job: Any) -> set[Any]:
    from dagster import GraphDefinition

    hooks: set[Any] = set(job.hook_defs)

    def walk(graph: Any) -> None:
        for node in graph.nodes:
            hooks.update(node.hook_defs)
            if isinstance(node.definition, GraphDefinition):
                walk(node.definition)

    walk(job.graph)
    return hooks


def test_the_probe_ops_import_nothing_that_can_write(probe_job: Any) -> None:
    op_defs = list(probe_job.graph.iterate_op_defs())
    # 하한: op를 하나도 보지 못했으면 아래 import 검사가 항진명제다.
    assert op_defs, f"탐침 `{probe_job.name}`에서 op를 하나도 읽지 못했다"
    assert not _hook_defs(probe_job), "탐침에 hook이 있다 — hook은 step 뒤에 일을 한다"

    modules = set()
    for op_def in op_defs:
        compute = getattr(op_def.compute_fn, "decorated_fn", op_def.compute_fn)
        module = inspect.getmodule(compute)
        assert module is not None, f"op `{op_def.name}`의 모듈을 찾지 못했다"
        modules.add(module)

    offenders: list[str] = []
    for module in modules:
        tree = ast.parse(inspect.getsource(module))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.level:
                    offenders.append(f"{module.__name__}: 상대 import .{node.module or ''}")
                elif (node.module or "").split(".")[0] not in _PROBE_ALLOWED_IMPORT_ROOTS:
                    offenders.append(f"{module.__name__}: from {node.module}")
            elif isinstance(node, ast.Import):
                offenders.extend(
                    f"{module.__name__}: import {alias.name}"
                    for alias in node.names
                    if alias.name.split(".")[0] not in _PROBE_ALLOWED_IMPORT_ROOTS
                )
            elif (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "__import__"
            ):
                offenders.append(f"{module.__name__}: __import__ 호출")
    assert not offenders, (
        f"탐침 `{probe_job.name}`의 op 모듈이 일을 할 수 있는 코드를 import한다: {offenders}"
    )


def test_the_probe_ops_neither_queue_nor_retry(probe_job: Any) -> None:
    """pool은 탐침을 적재 뒤에 줄 세우고, retry는 실패를 늦추거나 가린다."""
    op_defs = list(probe_job.graph.iterate_op_defs())
    assert op_defs, f"탐침 `{probe_job.name}`에서 op를 하나도 읽지 못했다"
    pooled = sorted(f"{op.name}={op.pool}" for op in op_defs if op.pool)
    assert not pooled, (
        f"탐침 op가 pool에 있다: {pooled} — 게이트가 run 경로가 아니라 pool이 비었는지를 잰다."
    )
    retried = sorted(op.name for op in op_defs if op.retry_policy is not None)
    assert not retried, f"탐침 op에 retry policy가 있다: {retried}"


def test_the_probe_creates_no_operation_rows(probe_job: Any) -> None:
    """operation key tag가 있으면 상태·reconcile sensor가 ``ops.import_jobs``에 행을 만든다.

    sensor가 run을 operation으로 볼지 정하는 **바로 그 함수**로 판정한다 — tag 이름을 여기
    다시 적으면 sensor 쪽 판정이 바뀌어도 초록이다.
    """
    from kortravelmap.dagster import feature_operation_sensors

    tag = feature_operation_sensors._OPERATION_KEY_TAG
    operation_key = feature_operation_sensors._operation_key(probe_job.tags)
    assert tag not in probe_job.tags, f"탐침 `{probe_job.name}`이 `{tag}` tag를 단다"
    assert operation_key is None, (
        f"탐침 `{probe_job.name}`이 operation key `{operation_key}`를 단다 — 게이트 run마다 "
        "provider operation 행이 생긴다."
    )


def test_the_probe_completes_in_process_without_doing_work(probe_job: Any) -> None:
    """효과 결박: 실제로 돌려 성공하고, 수 초 안에 끝난다."""
    required = set(probe_job.required_resource_keys)
    if not required <= _PROBE_ALLOWED_RESOURCE_KEYS:
        # 실행하면 DB·upstream resource를 만든다 — 실행하지 않고 실패한다.
        pytest.fail(
            f"전제 실패: 탐침 `{probe_job.name}`이 {sorted(required)}를 요구한다 — "
            "실행하지 않는다."
        )
    started = time.monotonic()
    result = probe_job.execute_in_process(raise_on_error=False)
    elapsed = time.monotonic() - started
    assert result.success, f"탐침 `{probe_job.name}`이 resource 없이 완주하지 못했다"
    assert elapsed < _PROBE_MAX_SECONDS, (
        f"탐침 `{probe_job.name}`이 in-process로 {elapsed:.1f}초 걸렸다 — 일을 하고 있다."
    )
