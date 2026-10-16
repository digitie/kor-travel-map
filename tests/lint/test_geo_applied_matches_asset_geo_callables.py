"""asset이 넘기는 ``geo_applied``는 그 run이 실제로 넘긴 geo 콜러블과 같다(ADR-109 결정 3, T-GR-02).

``geo_applied``는 스탬프 outcome 판정의 첫 입력이다 — 틀리면 geo를 쓴 행이 스탬프 없이 남거나
(재지오코딩 대상에서 빠짐) geo를 안 쓴 price/notice 행이 stale로 계속 계획된다. 손으로 적은 값이
사실과 같다는 것을 효과로 결박한다: ``assets.py``에서 ``_load(``/``_load_snapshot_batches(``를
부르는 함수마다

- ``reverse`` == 그 함수 안에 ``_reverse_geocoder(context)`` 호출이나 ``None``이 아닌
  ``reverse_geocoder=`` 인자가 있는가(한쪽만 보면 다른 모양의 run을 ``reverse=False``로 민다)
- ``geocode`` == 그 함수 안에 ``None``이 아닌 ``address_resolver=`` 인자가 있는가

이고, ``geo_applied=GeoApplied(reverse=<bool>, geocode=<bool>)`` 리터럴로 넘겨야 한다(변수 금지 —
값을 볼 수 없다). 현재 asset은 전부 ``geocode=False``다(``address_resolver=`` 0건; offline upload·
CLI만 geocode를 쓴다).

run-scoped 현재 토큰의 팩토리가 하나라는 것도 여기서 센다 — ``fetch_current_dataset(`` 호출은
Dagster resource·offline upload·CLI 세 곳뿐이고, asset과 큐 runner는 같은 resource 키를 common
resource로 갖는다.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_DAGSTER = _REPO / "packages" / "kor-travel-map-dagster" / "src" / "kortravelmap" / "dagster"
_ASSETS = _DAGSTER / "assets.py"
_LOADERS = frozenset({"_load", "_load_snapshot_batches"})


def _name(call: ast.Call) -> str | None:
    func = call.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _violations(source: str) -> tuple[list[str], int]:
    problems: list[str] = []
    seen = 0
    for func in ast.walk(ast.parse(source)):
        if not isinstance(func, ast.FunctionDef | ast.AsyncFunctionDef) or func.name in _LOADERS:
            continue
        calls = [node for node in ast.walk(func) if isinstance(node, ast.Call)]
        loads = [call for call in calls if _name(call) in _LOADERS]
        if not loads:
            continue
        reverse = any(_name(call) == "_reverse_geocoder" for call in calls) or any(
            keyword.arg == "reverse_geocoder"
            and not (isinstance(keyword.value, ast.Constant) and keyword.value.value is None)
            for call in calls
            for keyword in call.keywords
        )
        geocode = any(
            keyword.arg == "address_resolver"
            and not (isinstance(keyword.value, ast.Constant) and keyword.value.value is None)
            for call in calls
            for keyword in call.keywords
        )
        for load in loads:
            seen += 1
            where = f"{func.name}():{load.lineno}"
            value = next((kw.value for kw in load.keywords if kw.arg == "geo_applied"), None)
            if not (isinstance(value, ast.Call) and _name(value) == "GeoApplied"):
                problems.append(f"{where}: geo_applied=GeoApplied(...) 리터럴이 아니다")
                continue
            given = {
                kw.arg: kw.value.value
                for kw in value.keywords
                if isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, bool)
            }
            expected = {"reverse": reverse, "geocode": geocode}
            if given != expected:
                problems.append(f"{where}: geo_applied={given} — 실제 geo 콜러블은 {expected}")
    return problems, seen


def _loader_modules() -> list[Path]:
    """``assets.py``와, 거기서 ``_load``/``_load_snapshot_batches``를 import하는 모듈(예: MCST)."""
    modules = [_ASSETS]
    for path in sorted(_DAGSTER.glob("*.py")):
        if path == _ASSETS:
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (
                isinstance(node, ast.ImportFrom)
                and (node.module or "").endswith("assets")
                and any(alias.name in _LOADERS for alias in node.names)
            ):
                modules.append(path)
                break
    return modules


def test_asset_geo_applied_matches_the_callables_it_passes() -> None:
    modules = _loader_modules()
    assert any(path.name == "mcst_features.py" for path in modules), modules
    problems: list[str] = []
    seen = 0
    for path in modules:
        found, count = _violations(path.read_text(encoding="utf-8"))
        problems.extend(f"{path.name}:{item}" for item in found)
        seen += count
    assert seen >= 10, f"적재 호출을 {seen}건밖에 못 봤다 — 로더 이름이 바뀌었나"
    assert not problems, "geo_applied가 사실과 다르다:\n" + "\n".join(problems)


_SAMPLE = """
async def run(context):
    bundles = await convert(records, reverse_geocoder=_reverse_geocoder(context))
    return await _load(
        context, bundles=bundles, geo_applied=GeoApplied(reverse=True, geocode=False)
    )
"""


@pytest.mark.parametrize(
    ("source", "needle"),
    [
        (_SAMPLE.replace("reverse=True", "reverse=False"), "실제 geo 콜러블"),
        (
            _SAMPLE.replace("reverse_geocoder=_reverse_geocoder(context)", "reverse_geocoder=None"),
            "실제 geo 콜러블",
        ),
        (_SAMPLE.replace("geo_applied=GeoApplied(reverse=True, geocode=False)", "x=1"), "리터럴"),
        (
            _SAMPLE.replace("_reverse_geocoder(context)", "geocoder").replace(
                "reverse=True", "reverse=False"
            ),
            "실제 geo 콜러블",
        ),
        (_SAMPLE.replace("GeoApplied(reverse=True, geocode=False)", "applied"), "리터럴"),
        (
            _SAMPLE.replace("records,", "records, address_resolver=resolver,"),
            "실제 geo 콜러블",
        ),
    ],
)
def test_checker_goes_red(source: str, needle: str) -> None:
    problems, seen = _violations(source)
    assert seen == 1
    assert any(needle in problem for problem in problems), problems


def test_one_current_dataset_factory_for_every_known_caller() -> None:
    """``fetch_current_dataset(`` 호출 = resource·offline upload·CLI(asset·runner는 resource)
    + 운영 API ``/v1/ops/geo-releases``(감지·현재 토큰 표시 — T-GR-04) + 릴리스 센서(T-GR-05 — 같은
    tick의 geo client로 sigungu resolver도 만든다)."""
    roots = (
        _REPO / "src",
        _REPO / "packages" / "kor-travel-map-api" / "src",
        _REPO / "packages" / "kor-travel-map-dagster" / "src",
    )
    callers: set[str] = set()
    direct_dataset_version: set[str] = set()
    for root in roots:
        for path in root.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            rel = path.relative_to(_REPO).as_posix()
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                if _name(node) == "fetch_current_dataset":
                    callers.add(rel)
                if _name(node) == "dataset_version" and not rel.endswith(
                    "src/kortravelmap/geocoding.py"
                ):
                    direct_dataset_version.add(rel)
    assert callers == {
        "packages/kor-travel-map-dagster/src/kortravelmap/dagster/resources.py",
        "packages/kor-travel-map-dagster/src/kortravelmap/dagster/offline_uploads.py",
        "src/kortravelmap/cli/main.py",
        "packages/kor-travel-map-api/src/kortravelmap/api/routers/ops_geo_releases.py",
        "packages/kor-travel-map-dagster/src/kortravelmap/dagster/geo_release_sensor.py",
    }
    assert direct_dataset_version == set(), "dataset_version()을 팩토리 밖에서 부른다"

    # asset과 큐 runner는 같은 resource 키를 common resource로 갖고, 그 키의 기본 구현이 팩토리를
    # 부르는 resource다(AST로 본다 — 이 lint는 dagster를 import하지 않는다).
    for module in ("assets.py", "feature_update_runner.py"):
        assert "kor_travel_geo_dataset" in _common_resource_keys(_DAGSTER / module), module
    definitions = ast.parse((_DAGSTER / "definitions.py").read_text(encoding="utf-8"))
    bound = {
        key.value: value.id
        for node in ast.walk(definitions)
        if isinstance(node, ast.Dict)
        for key, value in zip(node.keys, node.values, strict=True)
        if isinstance(key, ast.Constant) and isinstance(value, ast.Name)
    }
    assert bound.get("kor_travel_geo_dataset") == "kor_travel_geo_dataset_resource"


def _common_resource_keys(path: Path) -> set[str]:
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        target = node.target if isinstance(node, ast.AnnAssign) else None
        if (
            isinstance(target, ast.Name)
            and target.id == "_COMMON_RESOURCE_KEYS"
            and isinstance(node, ast.AnnAssign)
            and isinstance(node.value, ast.Set)
        ):
            return {
                element.value
                for element in node.value.elts
                if isinstance(element, ast.Constant) and isinstance(element.value, str)
            }
    raise AssertionError(f"{path.name}에 _COMMON_RESOURCE_KEYS 집합 리터럴이 없다")
