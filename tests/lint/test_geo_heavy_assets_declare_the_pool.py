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
_FRESHNESS_SENSITIVE: Final[dict[str, str]] = {
    "feature_weather_airkorea_air_quality": "매시 10분 수집 — 월간 적재 뒤에 서면 한 시간을 잃는다",
    "feature_weather_krex_rest_areas": "매시 35분 수집 — 같은 이유",
}


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
