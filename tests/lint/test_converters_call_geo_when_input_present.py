"""변환 **함수** 단위로, 받은 geo 콜러블을 실제로 쓰는지 센다 (ADR-109 결정 3·4, T-GR-03).

지오코딩 스탬프의 outcome은 run 신호(``geo_applied``)로 정한다 — "이 run이 ``reverse_geocoder=``를
넘겼다"면 좌표 있는 행은 ``called``다. 그 전제는 **받은 함수가 그것을 실제로 부른다**는 것이다. 어느
변환기가 ``reverse_geocoder``를 받고도 부르지 않으면 geo를 쓰지 않은 행이 ``called``로 봉인되어
릴리스마다 헛되이 다시 계획된다(반대 방향의 오류도 같은 자리에서 생긴다).

모듈 단위로 세면 opinet·krex처럼 place 변환기와 price/notice 변환기가 한 모듈에 있는 곳이 늘
초록이다 — 그래서 함수 단위다. 각 함수에서 받은 파라미터가 **소비**되어야 한다: 호출
대상(``reverse_geocoder(…)``, ``reverse_geocoder.observe(…)``)이거나 다른 호출의 인자로 넘어가는
것(``cached_reverse_geocoder(reverse_geocoder)``, ``_resolve_address(…,
reverse_geocoder=reverse_geocoder)``). ``_ = address_resolver``처럼 받기만 하는 것은 소비가 아니다.

``address_resolver``는 ``docs/etl/address-geocoding.md`` §1 표대로 krex ``rest_areas_to_bundles``만
받되 쓰지 않는다 — 그 함수는 **반대로** 소비하지 않아야 한다(쓰기 시작하면 이 표·스탬프 규칙을 다시
볼 것).
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_PROVIDERS = Path(__file__).resolve().parents[2] / "src" / "kortravelmap" / "providers"

#: 받지만 쓰지 않는 것이 사실인 자리(``address-geocoding.md`` §1 표).
_DECLARED_UNUSED: frozenset[tuple[str, str, str]] = frozenset(
    {("krex.py", "rest_areas_to_bundles", "address_resolver")}
)
_PARAMS = ("reverse_geocoder", "address_resolver")


def _consumed(func: ast.AST, name: str) -> bool:
    for node in ast.walk(func):
        if not isinstance(node, ast.Call):
            continue
        target = node.func
        if isinstance(target, ast.Name) and target.id == name:
            return True
        if (
            isinstance(target, ast.Attribute)
            and isinstance(target.value, ast.Name)
            and target.value.id == name
        ):
            return True
        values = [*node.args, *(keyword.value for keyword in node.keywords)]
        if any(isinstance(value, ast.Name) and value.id == name for value in values):
            return True
    return False


def _functions(source: str) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    return [
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    ]


def _violations(filename: str, source: str) -> tuple[list[str], int]:
    problems: list[str] = []
    seen = 0
    for func in _functions(source):
        arguments = {arg.arg for arg in [*func.args.args, *func.args.kwonlyargs]}
        for param in _PARAMS:
            if param not in arguments:
                continue
            seen += 1
            consumed = _consumed(func, param)
            declared_unused = (filename, func.name, param) in _DECLARED_UNUSED
            if declared_unused and consumed:
                problems.append(
                    f"{filename}:{func.name}: {param}를 쓰기 시작했다 — "
                    "§1 표·스탬프 규칙을 갱신할 것"
                )
            elif not declared_unused and not consumed:
                problems.append(f"{filename}:{func.name}: {param}를 받고도 부르지 않는다")
    return problems, seen


def test_every_converter_consumes_the_geo_callables_it_takes() -> None:
    problems: list[str] = []
    seen = 0
    for path in sorted(_PROVIDERS.glob("*.py")):
        found, count = _violations(path.name, path.read_text(encoding="utf-8"))
        problems.extend(found)
        seen += count
    # 하한은 '본 것' — 12개 모듈에서 geo 콜러블을 받는 함수 수십 개를 실제로 봤는가.
    assert seen >= 40, f"geo 콜러블을 받는 변환 함수를 {seen}개밖에 못 봤다"
    assert not problems, "\n".join(problems)


@pytest.mark.parametrize(
    ("source", "needle"),
    [
        (
            "async def f(record, *, reverse_geocoder=None):\n    return record\n",
            "reverse_geocoder를 받고도 부르지 않는다",
        ),
        (
            "async def f(record, *, address_resolver=None):\n    _ = address_resolver\n",
            "address_resolver를 받고도 부르지 않는다",
        ),
    ],
)
def test_checker_goes_red_on_unused_callables(source: str, needle: str) -> None:
    problems, seen = _violations("sample.py", source)
    assert seen == 1
    assert any(needle in problem for problem in problems), problems


def test_checker_accepts_calls_and_pass_through() -> None:
    source = (
        "async def a(coord, *, reverse_geocoder=None):\n"
        "    return await reverse_geocoder(coord)\n"
        "async def b(coord, *, reverse_geocoder=None):\n"
        "    return await reverse_geocoder.observe(coord)\n"
        "async def c(rows, *, reverse_geocoder=None, address_resolver=None):\n"
        "    g = cached(reverse_geocoder)\n"
        "    return [x(row, address_resolver=address_resolver) for row in rows]\n"
    )
    problems, seen = _violations("sample.py", source)
    assert problems == []
    assert seen == 4


def test_declared_unused_turns_red_when_used() -> None:
    source = (
        "async def rest_areas_to_bundles(rows, *, address_resolver=None):\n"
        "    return await address_resolver(rows)\n"
    )
    problems, _ = _violations("krex.py", source)
    assert any("쓰기 시작했다" in problem for problem in problems), problems
