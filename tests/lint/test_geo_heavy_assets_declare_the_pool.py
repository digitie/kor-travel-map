"""**역지오코딩을 대량으로 하는 asset은 동시에 돌면 안 된다.**

경위. 2026-09-19에 `feature_place_mcst_culture_job`이 2시간54분·4회 시도 끝에
`GeoRequestError: ReadTimeout`으로 죽었다. 처음 진단은 "geo가 느리다"였고 **틀렸다** —
같은 시각 geo reverse는 p50 86ms로 답했고 5시간 동안 pool 포화 신호를 한 건도 내지
않았다. 다시 잰 것은 호스트였다.

    /proc/pressure/io   full avg300 = 25.5%   ← 1/4 시간 동안 모든 태스크가 막힘
    /proc/pressure/cpu  full avg300 =  0.0%
    04:05:00 최대 동시 run             8건

n150은 4코어이고 단일 회전 디스크를 weather/concierge/geo/airport와 함께 쓴다.
`docker/dagster.yaml`이 그 사실을 이미 적어 두었는데도 geo를 대량으로 쓰는 asset 중
pool을 선언한 것은 하나도 없었다.

**이 검사는 목록을 갖지 않는다.** 분모를 AST로 유도한다 — `reverse_geocoder=`를
넘기는 run 함수를 찾고, 그것을 쓰는 `@asset`을 찾는다. 그래서 21번째 provider가
생기면 아무도 이 파일을 고치지 않아도 빨개진다. 목록에 적어야만 재는 검사는 적어
둔 것만 잰다(`test_dagster_daemon_liveness_contract`가 같은 이유로 command에서
유도한다).

**제외도 유도한다.** schedule spec에 `max_runtime_seconds`가 있는 asset은 저장소가
"지연되면 안 되는 freshness 민감 job"으로 분류한 것이다. 그런 job을 몇 시간짜리
월간 적재 뒤에 줄 세우면 시간별 수집이 그만큼 멈춘다 — 그래서 pool에 넣지 **않는다.**
"""

from __future__ import annotations

import ast
import pathlib
import re
from typing import Final

from kortravelmap.core.feature_operation import (
    DATASET_CONFIGURED_OPERATION_RESOURCES,
    FEATURE_LOAD_DISABLED_OPERATION_KEYS,
    FEATURE_LOAD_JOB_OPERATION_KEYS,
    GEO_DEPENDENT_OPERATION_KEYS,
    REPLAY_RECORDS_RESOURCES,
)

REPO_ROOT: Final = pathlib.Path(__file__).resolve().parents[2]
_DAGSTER_PKG: Final = (
    REPO_ROOT
    / "packages"
    / "kor-travel-map-dagster"
    / "src"
    / "kortravelmap"
    / "dagster"
)
_SCHEDULES: Final = _DAGSTER_PKG / "schedules.py"

#: 이 pool 이름을 선언하면 `docker/dagster.yaml`의 `concurrency.pools`
#: (`default_limit: 1`, `granularity: run`)가 인스턴스 전역에서 한 번에 하나만 돌린다.
_POOL_CONSTANT: Final = "GEO_HEAVY_POOL"

#: geo를 쓰지만 pool에 넣지 **않는** 이유의 목록. 이름만 적는 면제가 아니라,
#: 그 asset이 왜 지연되면 안 되는지를 적어야 한다.
#:
#: 여기 적지 않아도 schedule spec의 `max_runtime_seconds`로 자동 제외되지만,
#: 그 유도가 낡으면(예: 상한이 다른 뜻으로 쓰이기 시작하면) 이 표와 어긋나면서
#: 아래 검사가 그것을 말해 준다.
#:
#: 2026-10-01 — 비었다. 여기 있던 둘(에어코리아 대기질·KREX 휴게소 기상, 매시 수집)은
#: ADR-105로 asset째 사라졌다. 표와 아래 대조 검사는 남긴다 — geo를 쓰는 freshness 민감
#: asset이 다시 생기면 `test_the_freshness_exclusions_are_still_the_ones_we_reasoned_about`이
#: 이유를 적으라고 빨개진다.
_FRESHNESS_SENSITIVE: Final[dict[str, str]] = {}


def _module_source(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def _freshness_capped_assets() -> set[str]:
    """schedule spec에 `max_runtime_seconds`가 있는 asset 이름."""

    source = _module_source(_SCHEDULES)
    capped: set[str] = set()
    for block in re.findall(r"FeatureLoadScheduleSpec\((.*?)\n    \),", source, re.S):
        if "max_runtime_seconds" not in block:
            continue
        match = re.search(r"asset=(\w+)", block)
        if match:
            capped.add(match.group(1))
    return capped


def _passes_reverse_geocoder(node: ast.AST) -> bool:
    return any(
        keyword.arg == "reverse_geocoder"
        for sub in ast.walk(node)
        if isinstance(sub, ast.Call)
        for keyword in sub.keywords
    )


def _asset_decorator(node: ast.AST) -> ast.Call | None:
    if not isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef):
        return None
    for decorator in node.decorator_list:
        if isinstance(decorator, ast.Call) and ast.unparse(decorator.func).endswith(
            "asset"
        ):
            return decorator
    return None


def _geo_heavy_assets() -> dict[str, str | None]:
    """geo를 쓰는 asset 이름 → 선언된 pool 표현식(없으면 ``None``)."""

    found: dict[str, str | None] = {}
    for path in sorted(_DAGSTER_PKG.glob("*.py")):
        tree = ast.parse(_module_source(path))
        run_functions = {
            node.name
            for node in ast.walk(tree)
            if isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef)
            and _passes_reverse_geocoder(node)
        }
        if not run_functions:
            continue
        for node in ast.walk(tree):
            decorator = _asset_decorator(node)
            if decorator is None:
                continue
            assert isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef)
            referenced = {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}
            if not (run_functions & referenced):
                continue
            pool = next(
                (
                    ast.unparse(keyword.value)
                    for keyword in decorator.keywords
                    if keyword.arg == "pool"
                ),
                None,
            )
            found[node.name] = pool
    return found


def _resolved_pool(asset_name: str) -> str | None:
    """**Dagster가 실제로 파싱한** pool. 소스 문자열이 아니다.

    `@asset(pool=...)`은 op에 실린다 — `AssetsDefinition.op.pool`이 정본이고
    `AssetsDefinition`에는 `pools` 속성이 없다(2026-09-19 실측에서 내가 먼저
    틀린 속성을 봤고, 그래서 "선언했는데 0개"라는 거짓 관측을 한 번 만들었다).
    """

    import importlib

    for module_name in (
        "kortravelmap.dagster.assets",
        "kortravelmap.dagster.mcst_features",
    ):
        module = importlib.import_module(module_name)
        definition = getattr(module, asset_name, None)
        if definition is None:
            continue
        op = getattr(definition, "op", None)
        return getattr(op, "pool", None) if op is not None else None
    raise AssertionError(f"asset을 찾지 못했다: {asset_name}")


def test_the_scan_actually_finds_geo_heavy_assets() -> None:
    """항진명제 방지 — 유도가 낡으면 분모가 0이 되고 아래 검사가 무의미해진다."""

    assets = _geo_heavy_assets()
    assert len(assets) >= 15, (
        f"`reverse_geocoder=`를 넘기는 asset을 {len(assets)}개만 찾았다 — AST 유도가 "
        "낡았다(주입 헬퍼 이름이나 키워드가 바뀌었을 수 있다)."
    )


def test_every_geo_heavy_bulk_asset_declares_the_pool() -> None:
    """freshness 민감이 아닌 geo 중량 asset은 전부 pool을 선언해야 한다.

    판정은 **Dagster가 파싱한 op의 pool**로 한다 — 소스에 `pool=`이 적혀 있는지가
    아니라, 그 선언이 실제로 op까지 닿았는지를 본다.
    """

    capped = _freshness_capped_assets()
    expected_pool = _resolved_pool("feature_place_mcst_culture")
    assert expected_pool, (
        "기준 asset에서 pool이 op까지 닿지 않았다 — `pool=` 인자가 Dagster 버전에서 "
        "사라졌거나 다른 이름이 됐다."
    )
    offenders = [
        name
        for name in _geo_heavy_assets()
        if name not in capped and _resolved_pool(name) != expected_pool
    ]
    assert not offenders, (
        "역지오코딩을 대량으로 하는 asset이 pool 없이 돈다 — n150은 4코어 단일 "
        "디스크이고 2026-09-19에 동시 run 8건이 `/proc/pressure/io` full 25%를 만들어 "
        f"3시간짜리 적재를 ReadTimeout으로 죽였다. `pool={_POOL_CONSTANT}`를 선언할 것: "
        f"{sorted(offenders)}"
    )


def test_freshness_sensitive_geo_assets_stay_out_of_the_pool() -> None:
    """**빠져 있어야 할 것이 들어오는 것도 결함이다.**

    `default_limit: 1`이므로 여기 들어온 시간별 job은 몇 시간짜리 월간 적재 뒤에
    줄을 선다. "전부 pool에 넣었는가"만 세면 이 방향은 영원히 안 보인다.
    """

    offenders = {
        name: _resolved_pool(name)
        for name in _FRESHNESS_SENSITIVE
        if _resolved_pool(name) is not None
    }
    assert not offenders, (
        "freshness 민감 asset이 pool에 들어갔다 — 월간 적재가 pool을 쥔 동안 "
        f"시간별 수집이 그만큼 멈춘다: {offenders}. 이유: {_FRESHNESS_SENSITIVE}"
    )


def test_the_freshness_exclusions_are_still_the_ones_we_reasoned_about() -> None:
    """자동 제외(상한 있음)와 손으로 적은 이유가 **서로 어긋나지 않아야** 한다.

    `max_runtime_seconds`가 다른 뜻으로 쓰이기 시작하면 제외 집합이 조용히 넓어진다.
    그때 이 검사가 말해 준다 — 넓어진 쪽을 보고 이유를 적거나 유도를 고치라고.
    """

    capped = _freshness_capped_assets()
    geo_heavy = set(_geo_heavy_assets())
    auto_excluded = geo_heavy & capped
    documented = set(_FRESHNESS_SENSITIVE)
    assert auto_excluded == documented, (
        "geo를 쓰면서 pool에서 자동 제외되는 asset이 바뀌었다. "
        f"자동 제외={sorted(auto_excluded)} / 적어 둔 이유={sorted(documented)}. "
        "새로 제외된 것은 왜 지연되면 안 되는지 `_FRESHNESS_SENSITIVE`에 적고, "
        "사라진 것은 pool에 넣을 것."
    )


# -- geo 의존 operation의 런타임 정본(ADR-109 결정 3·5, T-GR-04) ------------------------------
#
# 릴리스 계획(센서·`/detect`)은 `core.feature_operation.GEO_DEPENDENT_OPERATION_KEYS`로
# "이 operation이 geo 유도 값을 만드는가"를 본다 — API 프로세스는 `kortravelmap.dagster`를
# import하지 않으므로 런타임 AST 파싱은 없다. 그 상수가 사실과 같다는 것을 여기서 고정한다.
# 위 pool 술어(`_passes_reverse_geocoder`)는 **그대로 둔다** — pool이 필요한 집합(geo 중량)과
# geo 의존 집합은 같은 개념이 아니다.
#
# 이 유도가 pool 유도와 다른 셋:
# ① `reverse_geocoder=`/`address_resolver=`에 **None 상수가 아닌 값**을 넘겨야 센다(키워드
#    존재만이 아니다 — 돌발정보 notice처럼 `reverse_geocoder=None`을 명시한 asset은 geo 의존이
#    아니다).
# ② 함수 본문이 참조하는 이름으로 **모듈을 가로질러, 전이적으로** 잇는다
#    (`run_tracked_feature_asset` → `run_feature_…` → 변환기 호출; MOIS는
#    `load_mois_license_records_chunked`). 데코레이터는 보지 않는다 — `deps=[다른 asset]`이
#    geo 의존을 옮기지 않게.
# ③ asset → job은 `FEATURE_LOAD_SCHEDULE_SPECS`의 `job_name`이다(datagokr fileData는 asset
#    하나에 job 넷).
#
# 한계(알고 쓴다):
# - **이름 매칭이다.** 함수는 이름으로 잇는다 — 다른 모듈의 같은 이름 함수는 하나로 섞이고,
#   속성 이름(`x.observe`)도 이름으로 센다. 그래서 과대 유도 쪽으로 틀린다(geo 아닌 asset이 geo
#   의존으로 잡히면 상수와 어긋나 빨갛다 — 조용히 빠지는 방향보다 낫다).
# - **패키지 최상위 모듈만 본다**(`kortravelmap/dagster/*.py`, 하위 패키지·main 패키지의 변환기
#   본문은 보지 않는다). 변환기가 받은 콜러블을 실제로 부르는지는 별도 lint
#   (`test_converters_call_geo_when_input_present.py`)가 본다.
# - replay records resource 검사는 **부분집합**이다(선언한 resource가 asset의 required key에
#   있는가) — 그 resource가 `source_mode`를 구현했는지는 보지 않는다(T-GR-08, 런타임 게이트는
#   `SENSOR_LAUNCHABLE_REPLAY_OPERATION_KEYS`).


def _passes_geo_callable(node: ast.AST) -> bool:
    return any(
        keyword.arg in ("reverse_geocoder", "address_resolver")
        and not (isinstance(keyword.value, ast.Constant) and keyword.value.value is None)
        for sub in ast.walk(node)
        if isinstance(sub, ast.Call)
        for keyword in sub.keywords
    )


def _body_references(node: ast.AsyncFunctionDef | ast.FunctionDef) -> set[str]:
    found: set[str] = set()
    for statement in node.body:
        for sub in ast.walk(statement):
            if isinstance(sub, ast.Name):
                found.add(sub.id)
            elif isinstance(sub, ast.Attribute):
                found.add(sub.attr)
    return found


def _geo_dependent_names(sources: dict[str, str]) -> tuple[set[str], set[str]]:
    """(geo 의존 함수 이름, 그중 `@asset`) — 모듈을 가로지르는 전이 폐포."""

    functions: dict[str, list[ast.AsyncFunctionDef | ast.FunctionDef]] = {}
    assets: set[str] = set()
    for source in sources.values():
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef):
                functions.setdefault(node.name, []).append(node)
                if _asset_decorator(node) is not None:
                    assets.add(node.name)
    geo = {
        name
        for name, nodes in functions.items()
        if any(_passes_geo_callable(node) for node in nodes)
    }
    changed = True
    while changed:
        changed = False
        for name, nodes in functions.items():
            if name not in geo and any(_body_references(node) & geo for node in nodes):
                geo.add(name)
                changed = True
    return geo, geo & assets


def _derived_geo_dependent_operation_keys() -> set[str]:
    from kortravelmap.dagster.schedules import FEATURE_LOAD_SCHEDULE_SPECS

    sources = {path.name: _module_source(path) for path in sorted(_DAGSTER_PKG.glob("*.py"))}
    _, geo_assets = _geo_dependent_names(sources)
    return {
        spec.job_name
        for spec in FEATURE_LOAD_SCHEDULE_SPECS
        if spec.asset.key.path[-1] in geo_assets
    }


def test_geo_dependent_operation_keys_equal_the_ast_derivation() -> None:

    derived = _derived_geo_dependent_operation_keys()
    assert len(derived) >= 20, f"geo 의존 job을 {len(derived)}개만 찾았다 — 유도가 낡았다"
    assert derived == set(GEO_DEPENDENT_OPERATION_KEYS), (
        "core GEO_DEPENDENT_OPERATION_KEYS가 asset의 geo 콜러블 사용과 다르다 — "
        f"상수에만 있음={sorted(set(GEO_DEPENDENT_OPERATION_KEYS) - derived)} / "
        f"asset에만 있음={sorted(derived - set(GEO_DEPENDENT_OPERATION_KEYS))}. "
        "릴리스 계획이 geo를 쓰지 않는 dataset을 돌리거나 쓰는 dataset을 빼먹는다."
    )


def test_feature_load_job_operation_keys_equal_the_schedule_specs() -> None:
    from kortravelmap.dagster.schedules import FEATURE_LOAD_SCHEDULE_SPECS

    assert {spec.job_name for spec in FEATURE_LOAD_SCHEDULE_SPECS} == set(
        FEATURE_LOAD_JOB_OPERATION_KEYS
    )


def test_disabled_operation_keys_equal_the_dagster_schedules() -> None:
    from kortravelmap.dagster.schedules import DISABLED_FEATURE_LOAD_OPERATION_KEYS

    assert set(FEATURE_LOAD_DISABLED_OPERATION_KEYS) == set(
        DISABLED_FEATURE_LOAD_OPERATION_KEYS
    )


def test_dataset_configured_resources_equal_the_schedule_run_configs() -> None:
    """run_config로 dataset을 고르는 job의 resource 이름이 schedule spec과 같다."""

    from kortravelmap.dagster.schedules import FEATURE_LOAD_SCHEDULE_SPECS

    from_specs = {
        spec.job_name: tuple(sorted(spec.run_config["resources"]))
        for spec in FEATURE_LOAD_SCHEDULE_SPECS
        if spec.run_config is not None
    }
    declared = {
        job: tuple(sorted(resources))
        for job, resources in DATASET_CONFIGURED_OPERATION_RESOURCES.items()
    }
    assert declared == from_specs


def test_replay_records_resources_are_resources_the_asset_requires() -> None:
    from kortravelmap.dagster.schedules import FEATURE_LOAD_SCHEDULE_SPECS

    by_job = {spec.job_name: spec.asset for spec in FEATURE_LOAD_SCHEDULE_SPECS}
    missing = {
        job: resource
        for job, resource in REPLAY_RECORDS_RESOURCES.items()
        if job not in by_job or resource not in by_job[job].required_resource_keys
    }
    assert not missing, f"replay records resource가 asset에 없다: {missing}"


def test_the_geo_callable_predicate_ignores_explicit_none() -> None:
    """`reverse_geocoder=None`은 geo 의존이 아니다 — 키워드 존재만 보면 빨갛다."""

    assert not _passes_geo_callable(ast.parse("f(rows, reverse_geocoder=None)"))
    assert _passes_geo_callable(ast.parse("f(rows, reverse_geocoder=_reverse_geocoder(c))"))
    assert _passes_geo_callable(ast.parse("f(rows, address_resolver=resolver)"))


def test_the_derivation_crosses_modules_and_helpers_but_not_decorators() -> None:
    sources = {
        "a.py": (
            "async def run_x(context):\n"
            "    return await convert(rows, reverse_geocoder=_reverse_geocoder(context))\n"
            "async def run_y(context):\n"
            "    return await convert(rows, reverse_geocoder=None)\n"
        ),
        "b.py": (
            "@asset(group_name='g')\n"
            "async def x_asset(context):\n"
            "    return await run_tracked(context, run_x)\n"
            "@asset(deps=[x_asset])\n"
            "async def y_asset(context):\n"
            "    return await run_tracked(context, run_y)\n"
        ),
    }
    _, geo_assets = _geo_dependent_names(sources)
    assert geo_assets == {"x_asset"}
