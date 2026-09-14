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
