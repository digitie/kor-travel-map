"""상한이 **프로세스당**인 provider는 큐 경로에서 gate를 선언해야 한다.

`python-krex-api`는 초당 5건을 지킨다 — 그러나 그 보증은 한 프로세스 안에서다. 큐
센서는 틱당 RunRequest를 10개 내고 `docker/dagster.yaml`이 4를 동시에 돌리므로,
run마다 client가 따로면 버킷도 따로여서 합계가 **4배**가 된다(2026-09-14 적대 리뷰가
두 명 독립적으로 짚었다).

`feature_update_runner`의 `provider_rate_gate`가 그것을 막는데, **막는 것은
`rate_gate`를 선언한 operation뿐이다.** 새 krex operation을 선언 없이 추가하면 그
경로는 아무 검사도 건드리지 않고 gate를 비켜 간다 — 여기서 잡는다.

이 검사는 이름이 아니라 **등록 자리의 모양**을 본다: `resources=`에 `fetch_krex_*`를
넘기는 `_operation_specs(...)` 호출은 `rate_gate=`를 함께 넘겨야 한다.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Final

import pytest

_RUNNER: Final[Path] = (
    Path(__file__).resolve().parents[2]
    / "packages"
    / "kor-travel-map-dagster"
    / "src"
    / "kortravelmap"
    / "dagster"
    / "feature_update_runner.py"
)

#: gate가 필요한 fetcher의 접두사 → gate 이름.
#:
#: **provider마다 다른 이유가 있다.** krex는 TPS 제약이고(일일 한도 미공개),
#: 분모가 있는 provider는 일일 예산이 맞는 조치다 — 그것은 `T-VN-QUEUE-QUOTA`.
#: 여기에는 "프로세스당 상한이라 프로세스 수만큼 곱해지는" provider만 적는다.
_GATED_FETCHER_PREFIXES: Final[dict[str, str]] = {"fetch_krex_": "KREX_RATE_GATE"}


def _spec_calls() -> list[ast.Call]:
    tree = ast.parse(_RUNNER.read_text(encoding="utf-8"))
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_operation_specs"
    ]


def _fetcher_names(call: ast.Call) -> set[str]:
    names: set[str] = set()
    for keyword in call.keywords:
        if keyword.arg != "resources":
            continue
        for node in ast.walk(keyword.value):
            if isinstance(node, ast.Name):
                names.add(node.id)
    return names


def _declared_gate(call: ast.Call) -> str | None:
    for keyword in call.keywords:
        if keyword.arg == "rate_gate" and isinstance(keyword.value, ast.Name):
            return keyword.value.id
    return None


def test_every_rate_gated_fetcher_declares_its_gate() -> None:
    """gate가 필요한 fetcher를 쓰는 operation은 전부 `rate_gate=`를 선언한다."""

    calls = _spec_calls()
    assert calls, "`_operation_specs(...)` 등록 자리를 하나도 찾지 못했다 — 이 검사가 낡았다"

    missing: list[str] = []
    wrong: list[str] = []
    gated_seen = 0
    for call in calls:
        fetchers = _fetcher_names(call)
        for prefix, gate in _GATED_FETCHER_PREFIXES.items():
            if not any(name.startswith(prefix) for name in fetchers):
                continue
            gated_seen += 1
            declared = _declared_gate(call)
            where = ", ".join(sorted(name for name in fetchers if name.startswith(prefix)))
            if declared is None:
                missing.append(f"{where}(줄 {call.lineno})")
            elif declared != gate:
                wrong.append(f"{where}(줄 {call.lineno}) → {declared}, 기대 {gate}")

    assert not missing, (
        "프로세스당 상한인 provider의 operation이 gate를 선언하지 않았다 — 큐가 run을 "
        f"동시에 띄우면 상한이 프로세스 수만큼 곱해진다: {missing}"
    )
    assert not wrong, f"gate 이름이 다르다: {wrong}"
    assert gated_seen >= 4, (
        f"gate가 걸린 등록 자리를 {gated_seen}개만 봤다. krex operation은 넷이다 — "
        "이 검사가 등록 자리를 놓치고 있으면 항진명제가 된다."
    )


def test_every_declared_gate_is_actually_in_the_gate_table() -> None:
    """선언한 gate 이름이 **`PROVIDER_RATE_GATES`의 키로** 들어 있다.

    이것이 요점이다 — `provider_rate_gate()`는 표에서 못 찾으면 **락 없이 통과시킨다**
    (`PROVIDER_RATE_GATES.get(gate)`가 `None`). 그래서 표에서 한 줄만 지우면 선언은
    그대로인 채 gate가 조용히 꺼진다.

    처음 쓴 판은 소스에 `"KREX_RATE_GATE: "`가 있는지 봤는데, 그 문자열은
    `KREX_RATE_GATE: Final[str] = "krex"`라는 **어노테이션에도** 들어 있어서 표를 통째로
    비워도 초록이었다. 항진명제였다. 지금은 딕셔너리 키를 직접 읽는다.
    """

    tree = ast.parse(_RUNNER.read_text(encoding="utf-8"))
    tables = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Name)
        and node.target.id == "PROVIDER_RATE_GATES"
        and node.value is not None
    ]
    assert len(tables) == 1, "`PROVIDER_RATE_GATES` 선언을 정확히 하나 찾지 못했다"

    literals = [node for node in ast.walk(tables[0]) if isinstance(node, ast.Dict)]
    assert len(literals) == 1, "`PROVIDER_RATE_GATES`가 딕셔너리 리터럴이 아니다 — 검사가 낡았다"
    keys = {key.id for key in literals[0].keys if isinstance(key, ast.Name)}
    assert keys, "gate 표가 비어 있다 — 선언한 operation이 전부 락 없이 통과한다"

    for gate in _GATED_FETCHER_PREFIXES.values():
        assert gate in keys, (
            f"`{gate}`가 PROVIDER_RATE_GATES의 키에 없다({sorted(keys)}). "
            "표에 없으면 `provider_rate_gate()`가 락 없이 통과시킨다 — gate가 꺼진다."
        )

    # 그리고 간격이 실제 상한과 맞는가 — 0이면 이음매에서 상한을 넘는다.
    for key, value in zip(literals[0].keys, literals[0].values, strict=True):
        if not isinstance(key, ast.Name):
            continue
        # `1.0 / 5.0` 같은 식으로 적혀 있으므로 `literal_eval`이 아니라 컴파일해서 읽는다.
        cooldown = eval(  # noqa: S307 - 이 저장소 소스의 상수 식만 평가한다.
            compile(ast.Expression(body=value), "<gate-table>", "eval"), {}, {}
        )
        assert cooldown > 0, f"`{key.id}`의 교대 간격이 {cooldown}이다 — 이음매가 열린다"


#: 형제 체크아웃 루트 후보 — `test_quota_exception_contract`와 같은 관례(ADR-044).
_SIBLING_ROOTS: Final = (Path("F:/dev"), Path("/f/dev"), Path.home() / "dev")

#: gate 이름 → (형제 저장소, 모듈, 기본 상한 상수를 담은 파일).
_GATE_PROVIDER_SOURCES: Final[dict[str, tuple[str, str, str]]] = {
    "KREX_RATE_GATE": ("python-krex-api", "krex", "_http.py"),
}


def _library_default_max_rps(repo: str, module: str, filename: str) -> float | None:
    """형제 소스에서 ``DEFAULT_MAX_RPS``를 **AST로** 읽는다(import하지 않는다)."""

    for root in _SIBLING_ROOTS:
        candidate = root / repo / "src" / module / filename
        if not candidate.is_file():
            continue
        tree = ast.parse(candidate.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            target = None
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                target = node.target.id
            elif isinstance(node, ast.Assign) and len(node.targets) == 1:
                first = node.targets[0]
                target = first.id if isinstance(first, ast.Name) else None
            if target == "DEFAULT_MAX_RPS" and node.value is not None:
                return float(ast.literal_eval(node.value))
        return None
    return None


def test_the_gate_interval_matches_the_library_default() -> None:
    """gate의 교대 간격이 **라이브러리가 실제로 지키는 상한**과 같아야 한다.

    두 곳이 각자 `5`를 들고 서로를 모르고 있었다 — `PROVIDER_RATE_GATES`의
    `1.0 / 5.0`과 `krex._http.DEFAULT_MAX_RPS`다. Map은 `max_rps`를 넘기지 않으므로
    **라이브러리 기본값에 의존한다.** 그쪽이 3이나 10으로 바뀌면 gate의 간격은
    조용히 틀린 값이 되고, 그래도 모든 검사가 초록이다.

    프로세스 안의 상한(라이브러리)과 프로세스 사이의 간격(gate)은 **같은 수에서
    나와야** 합계가 그 수를 넘지 않는다.

    형제 체크아웃이 없으면 확인할 길이 없으므로 skip한다 — provider 핀을 바꾸는
    환경에서는 반드시 초록이어야 한다(ADR-044).
    """

    tree = ast.parse(_RUNNER.read_text(encoding="utf-8"))
    tables = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Name)
        and node.target.id == "PROVIDER_RATE_GATES"
        and node.value is not None
    ]
    assert len(tables) == 1
    literals = [node for node in ast.walk(tables[0]) if isinstance(node, ast.Dict)]
    assert len(literals) == 1
    cooldowns = {
        key.id: eval(  # noqa: S307 - 이 저장소 소스의 상수 식만 평가한다.
            compile(ast.Expression(body=value), "<gate-table>", "eval"), {}, {}
        )
        for key, value in zip(literals[0].keys, literals[0].values, strict=True)
        if isinstance(key, ast.Name)
    }

    checked = 0
    for gate, (repo, module, filename) in _GATE_PROVIDER_SOURCES.items():
        assert gate in cooldowns, f"`{gate}`가 gate 표에 없다"
        max_rps = _library_default_max_rps(repo, module, filename)
        if max_rps is None:
            pytest.skip(
                f"형제 체크아웃이 없어 `{module}`의 기본 상한을 확인하지 못했다"
                "(ADR-044). provider 핀을 바꾸는 환경에서는 반드시 초록이어야 한다."
            )
        checked += 1
        expected = 1.0 / max_rps
        assert cooldowns[gate] == pytest.approx(expected), (
            f"`{gate}` 교대 간격이 {cooldowns[gate]}인데 `{module}`의 기본 상한 "
            f"{max_rps} TPS가 요구하는 값은 {expected}다. 프로세스 안의 상한과 "
            "프로세스 사이의 간격이 갈라지면 합계가 상한을 넘는다."
        )

    assert checked, "확인한 gate가 0개다 — 이 검사가 항진명제가 됐다"
