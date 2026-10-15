"""geo·transport client는 connect timeout이 분리된 팩토리로만 만든다(ADR-110 결정 3, T-MAP-02).

geo·transport는 2026-10-14~15 다른 호스트(odroid)로 옮겨졌다. 그 호스트가 꺼지면 연결은
거부(RST)가 아니라 무응답이고, ``timeout=<float>`` 하나로 만든 client는 연결 수립에도 read
상한(geo 10 s·transport 30 s)을 다 쓴다. 그래서 효과에 결박한다 — 이름이 아니라 **값의
출처**를 본다: geo/transport client를 만드는 함수 안의 모든 ``httpx.AsyncClient(...)``는
``timeout=`` 이 ``geo_http_timeout(...)``/``transport_http_timeout(...)`` **호출**이어야 한다.
리터럴(``10.0``)·부재(httpx 기본 5 s)·settings float 직접 전달(``timeout=settings.
kor_travel_geo_timeout_seconds`` — connect 분리 없이 '설정을 읽는' 것처럼 보이는 꼴)은 모두
빨갛다. client 생성이 그 함수 밖에 있으면(다른 함수가 만든 http를 넘겨받으면) 출처를 볼 수
없으므로 그것도 빨갛다.

geo 생성 지점은 ``KorTravelGeoRestClient(`` 호출이 있는 함수, transport 생성 지점은
``_transport_connection(`` 호출이 있는 함수다(둘 다 그 경계를 지나야 base URL·인증을 얻는다).
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_ROOTS = (
    _REPO / "src",
    _REPO / "packages" / "kor-travel-map-api" / "src",
    _REPO / "packages" / "kor-travel-map-dagster" / "src",
)


@dataclass(frozen=True)
class _Rule:
    kind: str
    marker: str  # 이 이름을 호출하는 함수가 생성 지점이다
    factory: str  # 그 함수의 AsyncClient timeout= 값이어야 하는 호출


_RULES = (
    _Rule("geo", "KorTravelGeoRestClient", "geo_http_timeout"),
    _Rule("transport", "_transport_connection", "transport_http_timeout"),
)


def _call_name(node: ast.AST) -> str | None:
    if not isinstance(node, ast.Call):
        return None
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _violations(source: str, filename: str) -> tuple[list[str], dict[str, int]]:
    """(위반 목록, 규칙별 '본' 생성 지점 수)."""
    tree = ast.parse(source, filename=filename)
    problems: list[str] = []
    seen = {rule.kind: 0 for rule in _RULES}
    for func in ast.walk(tree):
        if not isinstance(func, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        calls = [node for node in ast.walk(func) if isinstance(node, ast.Call)]
        names = {_call_name(call) for call in calls}
        clients = [call for call in calls if _call_name(call) == "AsyncClient"]
        for rule in _RULES:
            if rule.marker not in names:
                continue
            # 정의 자체(def _transport_connection)는 생성 지점이 아니다.
            if func.name == rule.marker:
                continue
            seen[rule.kind] += 1
            where = f"{filename}:{func.lineno} {func.name}()"
            if not clients:
                problems.append(
                    f"{where}: {rule.kind} client의 httpx.AsyncClient 생성이 이 함수 안에 없다 — "
                    "timeout 출처를 볼 수 없다"
                )
            for client in clients:
                timeout = next((kw.value for kw in client.keywords if kw.arg == "timeout"), None)
                if timeout is None:
                    problems.append(
                        f"{where}:{client.lineno}: timeout= 없음(httpx 기본 5 s) — "
                        f"{rule.factory}(settings)를 쓸 것"
                    )
                elif _call_name(timeout) != rule.factory:
                    problems.append(
                        f"{where}:{client.lineno}: timeout={ast.unparse(timeout)} — "
                        f"connect 분리가 없다. {rule.factory}(settings)를 쓸 것"
                    )
    return problems, seen


def _repo_sources() -> list[Path]:
    return sorted(path for root in _ROOTS for path in root.rglob("*.py"))


def test_geo_and_transport_clients_use_the_timeout_factory() -> None:
    problems: list[str] = []
    seen = {rule.kind: 0 for rule in _RULES}
    for path in _repo_sources():
        found, counts = _violations(
            path.read_text(encoding="utf-8"), str(path.relative_to(_REPO))
        )
        problems.extend(found)
        for kind, count in counts.items():
            seen[kind] += count
    # 하한은 '본 것'에 건다 — 마커 이름이 바뀌어 아무것도 안 보이면 이 검사는 항진명제다.
    assert seen["geo"] >= 1, "geo client 생성 지점(KorTravelGeoRestClient 호출)을 하나도 못 봤다"
    assert seen["transport"] >= 1, "transport 생성 지점(_transport_connection 호출)을 하나도 못 봤다"
    assert not problems, "connect timeout 분리 없는 client:\n" + "\n".join(problems)


_GOOD_GEO = """
async def f(settings):
    async with httpx.AsyncClient(base_url=u, timeout=geo_http_timeout(settings)) as http:
        KorTravelGeoRestClient(http, api_key=k)
"""


@pytest.mark.parametrize(
    ("source", "needle"),
    [
        (_GOOD_GEO.replace("geo_http_timeout(settings)", "10.0"), "timeout=10.0"),
        (
            _GOOD_GEO.replace(
                "geo_http_timeout(settings)", "settings.kor_travel_geo_timeout_seconds"
            ),
            "timeout=settings.kor_travel_geo_timeout_seconds",
        ),
        (_GOOD_GEO.replace(", timeout=geo_http_timeout(settings)", ""), "timeout= 없음"),
        (
            _GOOD_GEO.replace("geo_http_timeout", "transport_http_timeout"),
            "geo_http_timeout(settings)를 쓸 것",
        ),
        (
            "async def f(http):\n    KorTravelGeoRestClient(http, api_key=k)\n",
            "AsyncClient 생성이 이 함수 안에 없다",
        ),
        (
            "async def f(settings):\n"
            "    base, headers = _transport_connection(settings)\n"
            "    async with httpx.AsyncClient(base_url=base, timeout=30.0) as c:\n"
            "        pass\n",
            "transport_http_timeout(settings)를 쓸 것",
        ),
    ],
)
def test_checker_goes_red_on_each_unsplit_shape(source: str, needle: str) -> None:
    problems, _ = _violations(source, "sample.py")
    assert any(needle in problem for problem in problems), problems


def test_checker_accepts_the_factory_shapes() -> None:
    transport = (
        "async def f(settings):\n"
        "    base, headers = _transport_connection(settings)\n"
        "    async with httpx.AsyncClient(base_url=base, timeout=transport_http_timeout(settings)):\n"
        "        pass\n"
    )
    for source in (_GOOD_GEO, transport):
        problems, seen = _violations(source, "sample.py")
        assert problems == []
        assert sum(seen.values()) == 1
