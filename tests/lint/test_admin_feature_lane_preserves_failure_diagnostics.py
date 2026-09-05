"""D2 lane이 컨테이너 실패 원인을 **버리지 않는지** 결박한다.

`admin_feature_live_supervisor.py`는 helper 컨테이너를 돌리고 `docker logs`로
출력을 거둔다. 종전에는 helper 경로만 `stdout`을 쓰고 `stderr`를 버렸다. helper는
결과 JSON을 stdout에, 실패 원인(RuntimeError·traceback)을 stderr에 내므로, seed가
죽으면 증거로 **0바이트 파일**만 남았다.

그 대가는 실측됐다 — 2026-09-05에 fixture seed가 세 번 죽었고 그때마다 원인을 알려면
배포 스택에서 `docker create` 인자를 손으로 재현해야 했다. 불완전한 재현은 매번
**다른 틀린 오류**를 냈다. 같은 파일의 probe/executor 경로는 처음부터 두 스트림을
함께 읽고 있었다 — 즉 계약은 있었고 helper 경로만 어긋나 있었다.

이 게이트는 `docker logs`로 출력을 거두는 **모든** 함수가 `stderr`도 소비하는지
본다. 새 실행 경로가 늘어도 같은 사각을 다시 만들지 못한다.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[2]
_SUPERVISOR = _ROOT / "scripts" / "admin_feature_live_supervisor.py"


def _captures_docker_logs(node: ast.AST) -> bool:
    """`node` 아래에서 `docker logs` 출력을 거두는 호출이 있는지 본다."""

    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        for argument in child.args:
            if not isinstance(argument, ast.List):
                continue
            literals = [
                item.value
                for item in argument.elts
                if isinstance(item, ast.Constant) and isinstance(item.value, str)
            ]
            if "docker" in literals and "logs" in literals:
                return True
    return False


def _functions() -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    tree = ast.parse(_SUPERVISOR.read_text(encoding="utf-8"))
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    ]


def _capture_sites() -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    return [node for node in _functions() if _captures_docker_logs(node)]


def _reads_stderr(node: ast.AST) -> bool:
    return any(
        isinstance(child, ast.Attribute) and child.attr == "stderr"
        for child in ast.walk(node)
    )


def test_the_gate_finds_real_capture_sites() -> None:
    """대조 대상이 실제로 잡혔는지부터 본다 — 0건이면 아래 단언이 공허하다."""

    sites = _capture_sites()
    # 2026-09-05 실측: helper 경로와 probe/executor 경로 둘이다. 이 수가 줄면
    # 파서가 형태를 놓친 것이고, 그러면 아래 단언이 조용히 공허해진다.
    assert len(sites) >= 2, (
        f"`docker logs` 출력을 거두는 함수를 {len(sites)}개만 찾았다 — 파서를 의심하라. "
        f"찾은 것={[node.name for node in sites]}"
    )


def test_every_docker_logs_capture_consumes_stderr() -> None:
    """출력을 거두는 모든 경로가 `stderr`도 소비해야 한다."""

    blind = [node.name for node in _capture_sites() if not _reads_stderr(node)]
    assert blind == [], (
        f"`docker logs` 출력을 거두면서 stderr를 버리는 경로가 있다: {blind}. "
        "helper·probe·executor는 실패 원인을 stderr에 낸다 — 버리면 증거로 0바이트 "
        "파일만 남고, 원인을 알려면 배포 스택에서 컨테이너를 손으로 재현해야 한다."
    )
