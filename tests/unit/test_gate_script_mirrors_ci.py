"""``scripts/verify-all-gates.sh``가 CI 차단 스텝을 빠뜨리지 않는지 검사한다.

2026-08-08에 같은 실패를 네 번 반복했다 — 변경 범위보다 좁은 집합만 검증하고
"green"이라 선언했다. 네 번째는 그 실패를 막으려고 만든 게이트 스크립트 자체가
CI 차단 스텝 22개 중 10개만 돌리면서 상단에 "전부 돌린다"고 적은 것이었고, 그
사각에서 branch-caused ESLint 실패가 실제로 나왔다.

그래서 목록의 정합성을 **사람 기억이 아니라 테스트가** 지킨다. 워크플로에 스텝이
늘면 이 테스트가 먼저 깨진다.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _ROOT / "scripts" / "verify-all-gates.sh"
_WORKFLOWS = ("ci", "lint", "openapi", "frontend")

#: CI에 있으나 로컬에서 **의도적으로** 돌리지 않는 명령과 그 이유.
#: 새 항목을 넣을 때는 반드시 이유를 적는다 — 이유 없는 면제가 곧 다음 사각이다.
_EXEMPT: dict[str, str] = {
    "ruff format --check": (
        "lint.yml에서 `if: false`다. 이 저장소는 자동 format을 쓰지 않으며 286개 "
        "파일이 재포맷 대상이라 켜면 즉시 red가 된다."
    ),
    "actions/": "GitHub Action 자체(체크아웃/캐시/업로드)는 게이트가 아니다.",
    "python -m pip install": "의존성 설치는 컨테이너 이미지가 대신한다.",
    "pip install": "의존성 설치는 컨테이너 이미지가 대신한다(위 항목과 같은 이유).",
    "mv ": "coverage 데이터 이동은 job 간 전달용이라 로컬에 대응물이 없다.",
    "npm@12.0.1 ci": "의존성 설치. 로컬은 이미 설치된 node_modules를 쓴다.",
    "tests/fixtures": (
        "fixture-replay 스텝은 `if [ -d tests/fixtures ]`로 자기 자신을 가드한다. "
        "이 저장소에 tests/fixtures가 없어 CI에서도 echo만 하고 끝난다 — 디렉터리가 "
        "생기면 이 면제를 지우고 게이트에 넣어야 한다."
    ),
}


def _workflow_commands() -> dict[str, list[str]]:
    """워크플로의 `run:` 본문을 스텝별로 모은다(`if: false`는 뺀다)."""

    found: dict[str, list[str]] = {}
    for name in _WORKFLOWS:
        path = _ROOT / ".github" / "workflows" / f"{name}.yml"
        lines = path.read_text(encoding="utf-8").split("\n")
        # 스텝 경계는 **다음 ``- name:``까지**다. 고정 크기 창(예전 8줄)으로 자르면
        # ``- name:``과 ``run:`` 사이 주석이 길 때 스텝을 통째로 놓친다 — 실제로
        # ``ci.yml``의 integration 차단 스텝이 주석 10줄 때문에 그렇게 사라져 있었고
        # 적대 리뷰의 변이 테스트가 그것을 잡아냈다.
        starts = [
            index for index, line in enumerate(lines) if re.match(r"^\s*- name: ", line)
        ]
        starts.append(len(lines))
        commands: list[str] = []
        for begin, stop in zip(starts, starts[1:], strict=False):
            block = lines[begin:stop]
            if any(re.match(r"^\s*if:\s*false\s*$", entry) for entry in block):
                continue
            for offset, entry in enumerate(block):
                run = re.match(r"^(\s*)run: (.*)$", entry)
                if run is None:
                    continue
                body = run.group(2).strip()
                if body == "|":
                    indent = len(run.group(1)) + 2
                    tail: list[str] = []
                    for follow in lines[begin + offset + 1 : stop]:
                        if follow.strip() and not follow.startswith(" " * indent):
                            break
                        tail.append(follow.strip())
                    body = " ".join(part for part in tail if part)
                if body:
                    commands.append(body)
                break
        found[name] = commands
    return found


def _is_exempt(command: str) -> bool:
    return any(marker in command for marker in _EXEMPT)


def test_gate_script_covers_every_ci_blocking_command() -> None:
    """CI가 돌리는 명령의 **식별 가능한 조각**이 게이트 스크립트에 있어야 한다.

    문자열 동등이 아니라 조각 포함으로 본다 — 로컬은 컨테이너/`python -m` 접두가
    붙어 명령이 그대로 같을 수 없기 때문이다. 대신 각 스텝을 유일하게 식별하는
    부분(스크립트 이름, npm run 대상, pytest 경로)이 반드시 나타나야 한다.
    """

    script = _SCRIPT.read_text(encoding="utf-8")
    missing: list[str] = []
    unrecognized: list[str] = []
    for workflow, commands in _workflow_commands().items():
        for command in commands:
            if _is_exempt(command):
                continue
            marker = _identifying_fragment(command)
            if marker is None:
                # 알아보지 못하는 명령 형태를 조용히 넘기면 새 게이트가 무방비로
                # 추가된다(적대 리뷰의 변이 테스트가 shell 스크립트 스텝으로 재현).
                unrecognized.append(f"{workflow}.yml: {command[:90]}")
                continue
            if marker not in script:
                missing.append(f"{workflow}.yml: {command[:90]} (조각 {marker!r})")

    assert missing == [], (
        "CI 차단 스텝이 scripts/verify-all-gates.sh에 없다. 스크립트에 추가하거나, "
        "돌리지 않는 이유를 _EXEMPT에 적어라:\n" + "\n".join(missing)
    )
    assert unrecognized == [], (
        "이 명령 형태를 감사기가 식별하지 못한다 — 조용히 통과시키면 새 게이트가 "
        "무방비가 된다. _identifying_fragment에 규칙을 넣거나 _EXEMPT에 이유를 "
        "적어라:\n" + "\n".join(unrecognized)
    )


def _identifying_fragment(command: str) -> str | None:
    """스텝을 유일하게 식별하는 조각을 뽑는다."""

    npm_run = re.search(r"run ([a-z0-9:-]+)", command)
    if "npm@" in command and npm_run is not None:
        return f"run {npm_run.group(1)}"
    script_call = re.search(r"(scripts/[\w./-]+\.py)", command)
    if script_call is not None:
        return script_call.group(1)
    if command.startswith("pytest "):
        return command.split()[1]
    if command.startswith("ruff check"):
        return "ruff check"
    mypy = re.search(r"mypy --strict -p ([\w.]+)", command)
    if mypy is not None:
        return f"-p {mypy.group(1)}"
    if "lint_imports_command" in command:
        return "lint_imports_command"
    if "export_openapi.py" in command:
        return "export_openapi.py"
    return None


def test_exempt_entries_state_a_reason() -> None:
    """면제에는 이유가 붙어야 한다 — 이유 없는 면제가 다음 사각이다."""

    assert all(reason.strip() for reason in _EXEMPT.values())
    assert all(len(reason) > 20 for reason in _EXEMPT.values())
