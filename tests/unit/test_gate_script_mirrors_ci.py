"""``scripts/verify-all-gates.sh``가 CI 차단 스텝을 빠뜨리지 않는지 검사한다.

2026-08-08~09에 같은 실패를 다섯 번 반복했다 — 변경 범위보다 좁은 집합만 검증하고
"green"이라 선언했다. 네 번째는 그 실패를 막으려고 만든 게이트 스크립트 자체가 CI
차단 스텝 22개 중 10개만 돌리면서 "전부 돌린다"고 적은 것이었고, 여섯 번째 적대
리뷰는 **이 감사 테스트조차** 변이 7종을 놓친다는 것을 실증했다:

- D 이름 없는 스텝(``- run:``)
- E 멀티라인 ``run: |``의 두 번째 이후 명령
- G 새 워크플로 파일 통째
- H 스텝의 자기 가드 제거(면제가 계속 유효한 척)
- I coverage 플래그 drift
- J·K **스크립트가 자기 게이트를 잃어도 침묵**(admin과 user-client의 같은 npm run
  이름을 구분 못 함)

그래서 이 판은 목록을 하드코딩하지 않는다. 워크플로 파일을 디렉터리에서 찾고,
차단 여부를 **트리거로** 판정하고, 스텝의 모든 명령을 본다. 감사가 자기 사각을
스스로 못 보면 그 위의 "green"은 근거가 되지 못한다.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _ROOT / "scripts" / "verify-all-gates.sh"
_WORKFLOW_DIR = _ROOT / ".github" / "workflows"

#: 이 트리거 중 하나라도 있으면 PR을 막는 워크플로다. ``workflow_dispatch`` 전용은
#: 수동 실행이라 로컬 미러링 대상이 아니다.
_BLOCKING_TRIGGERS = ("pull_request", "push")

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
    "if [ -d tests/fixtures ]": (
        "fixture-replay 스텝은 `if [ -d tests/fixtures ]`로 **자기 자신을 가드**한다. "
        "이 저장소에 tests/fixtures가 없어 CI에서도 echo만 하고 끝난다. 면제 키가 그 "
        "가드 문자열 자체이므로, 가드를 없애 진짜 차단 게이트가 되면 이 면제는 더 "
        "이상 매치되지 않고 감사가 즉시 실패한다."
    ),
    "echo ": "안내 출력은 게이트가 아니다 — 실패를 만들 수 없으므로 미러링 대상이 아니다.",
}


def _blocking_workflows() -> list[Path]:
    """PR을 막는 워크플로를 **디렉터리에서 찾는다**(하드코딩하지 않는다).

    파일 목록을 상수로 박으면 새 워크플로가 통째로 추가돼도 감사가 침묵한다
    (적대 리뷰 변이 G).
    """

    found: list[Path] = []
    for path in sorted(_WORKFLOW_DIR.glob("*.yml")):
        header = path.read_text(encoding="utf-8").split("jobs:", 1)[0]
        if any(f"{trigger}:" in header for trigger in _BLOCKING_TRIGGERS):
            found.append(path)
    return found


def _step_commands(lines: list[str], begin: int, stop: int) -> list[str]:
    """한 스텝의 ``run:`` 명령을 **전부** 돌려준다.

    멀티라인 ``run: |``은 줄마다 별개 명령이다 — 첫 줄만 보면 두 번째 이후가
    무방비가 된다(변이 E).
    """

    block = lines[begin:stop]
    if any(re.match(r"^\s*if:\s*false\s*$", entry) for entry in block):
        return []
    commands: list[str] = []
    for offset, entry in enumerate(block):
        run = re.match(r"^(\s*)(?:- )?run: (.*)$", entry)
        if run is None:
            continue
        body = run.group(2).strip()
        if body != "|":
            commands.append(body)
            break
        indent = len(run.group(1)) + 2
        raw: list[str] = []
        for follow in lines[begin + offset + 1 : stop]:
            if follow.strip() and not follow.startswith(" " * indent):
                break
            text = follow.strip()
            # 쉘 주석은 명령이 아니다 — 게이트로 세면 감사가 헛짚는다.
            if text and not text.startswith("#"):
                raw.append(text)
        # 제어 흐름이 있는 블록은 **쪼개지 않는다**. `if [ -d … ]`로 자기를 가드하는
        # 스텝을 줄 단위로 나누면 가드와 본체가 떨어져, 가드를 없애는 변경(변이 H)이
        # 면제 매칭을 그대로 통과한다. 순차 명령 블록만 줄마다 본다(변이 E).
        if any(re.match(r"^(if|for|while|case)\b", entry) for entry in raw):
            commands.append(" ".join(raw))
            break
        current: list[str] = []
        for text in raw:
            current.append(text)
            if not text.endswith("\\"):
                commands.append(" ".join(part.rstrip("\\").strip() for part in current))
                current = []
        break
    return commands


def _workflow_commands() -> dict[str, list[str]]:
    """차단 워크플로의 ``run:`` 명령을 모은다.

    스텝 경계는 ``- name:`` **또는 이름 없는 ``- run:``**(변이 D)에서 시작해 다음
    스텝 시작까지다. 고정 크기 창으로 자르면 주석이 길 때 스텝을 통째로 놓친다.
    """

    found: dict[str, list[str]] = {}
    for path in _blocking_workflows():
        lines = path.read_text(encoding="utf-8").split("\n")
        starts = [
            index
            for index, line in enumerate(lines)
            if re.match(r"^\s*- (name|run|uses): ", line)
        ]
        starts.append(len(lines))
        commands: list[str] = []
        for begin, stop in zip(starts, starts[1:], strict=False):
            commands.extend(_step_commands(lines, begin, stop))
        found[path.name] = commands
    return found


def _is_exempt(command: str) -> bool:
    return any(marker in command for marker in _EXEMPT)


def _identifying_fragments(command: str) -> list[str] | None:
    """스텝을 유일하게 식별하는 조각들. 하나라도 스크립트에 없으면 누락이다."""

    if "npm@" in command:
        npm_run = re.search(r"run ([a-z0-9:-]+)", command)
        if npm_run is None:
            return None
        # workspace를 함께 봐야 admin과 user-client의 동명 script를 구분한다.
        # 안 그러면 스크립트가 둘 중 하나를 지워도 감사가 침묵한다(변이 J·K).
        workspace = re.search(r"-w (\S+)", command)
        fragments = [f"run {npm_run.group(1)}"]
        if workspace is not None:
            fragments.append(workspace.group(1).rsplit("/", 1)[-1])
        return fragments
    script_call = re.search(r"(scripts/[\w./-]+\.py)", command)
    if script_call is not None:
        return [script_call.group(1)]
    if command.startswith("pytest "):
        # coverage 게이팅 플래그도 미러링 대상이다 — 임계가 바뀌면 로컬이 다른
        # 기준으로 판정한다(변이 I).
        fragments = [command.split()[1]]
        gate = re.search(r"--cov-fail-under=(\d+)", command)
        if gate is not None and gate.group(1) != "0":
            fragments.append(f"--cov-fail-under={gate.group(1)}")
        return fragments
    if command.startswith("ruff check"):
        return ["ruff check"]
    mypy = re.search(r"mypy --strict -p ([\w.]+)", command)
    if mypy is not None:
        return [f"-p {mypy.group(1)}"]
    if "lint_imports_command" in command:
        return ["lint_imports_command"]
    if "export_openapi.py" in command:
        return ["export_openapi.py"]
    return None


def _expanded_script_lines() -> list[str]:
    """스크립트 줄을 **셸 변수를 펼친 상태로** 돌려준다.

    게이트가 `$ADMIN` 같은 변수를 쓰면 리터럴 경로가 그 줄에 없다. 펼치지 않으면
    감사가 실재하는 게이트를 없다고 오판한다 — 반대로 펼치지 않은 채 조각을 느슨히
    잡으면 변이 J·K(다른 게이트가 조각을 빌려줌)를 놓친다.
    """

    text = _SCRIPT.read_text(encoding="utf-8")
    assignments = dict(
        re.findall(r'^([A-Z_]+)="([^"]*)"$', text, flags=re.M)
    )
    lines = text.splitlines()
    expanded: list[str] = []
    for line in lines:
        for name, value in assignments.items():
            line = line.replace(f"${name}", value)
        expanded.append(line)
    return expanded


def test_gate_script_covers_every_ci_blocking_command() -> None:
    """CI가 돌리는 명령의 **식별 가능한 조각**이 게이트 스크립트에 있어야 한다.

    문자열 동등이 아니라 조각 포함으로 본다 — 로컬은 컨테이너/``python -m`` 접두가
    붙어 명령이 그대로 같을 수 없기 때문이다.
    """

    # 조각을 파일 전체에서 따로 찾으면 안 된다 — admin과 user-client의 게이트가
    # 서로의 조각을 빌려줘, 스크립트가 둘 중 하나를 지워도 통과한다(변이 J·K).
    # **한 줄에 모두** 있어야 그 게이트가 실재하는 것이다.
    script_lines = _expanded_script_lines()
    missing: list[str] = []
    unrecognized: list[str] = []
    for workflow, commands in _workflow_commands().items():
        for command in commands:
            if _is_exempt(command):
                continue
            fragments = _identifying_fragments(command)
            if fragments is None:
                # 알아보지 못하는 명령 형태를 조용히 넘기면 새 게이트가 무방비로
                # 추가된다. 인식 규칙을 넓히거나 _EXEMPT에 이유와 함께 적어야 한다.
                unrecognized.append(f"{workflow}: {command[:90]}")
                continue
            if not any(
                all(fragment in line for fragment in fragments)
                for line in script_lines
            ):
                missing.append(f"{workflow}: {command[:80]} (조각 {fragments})")

    assert missing == [], (
        "CI 차단 스텝이 scripts/verify-all-gates.sh에 없다. 스크립트에 추가하거나, "
        "돌리지 않는 이유를 _EXEMPT에 적어라:\n" + "\n".join(missing)
    )
    assert unrecognized == [], (
        "이 명령 형태를 감사기가 식별하지 못한다 — 조용히 통과시키면 새 게이트가 "
        "무방비가 된다. _identifying_fragments에 규칙을 넣거나 _EXEMPT에 이유를 "
        "적어라:\n" + "\n".join(unrecognized)
    )


def test_blocking_workflows_are_discovered_not_hardcoded() -> None:
    """차단 워크플로를 디렉터리에서 찾는다 — 새 파일이 생기면 자동으로 포함된다."""

    names = {path.name for path in _blocking_workflows()}
    assert {"ci.yml", "lint.yml", "openapi.yml", "frontend.yml"} <= names
    # workflow_dispatch 전용은 PR을 막지 않으므로 미러링 대상이 아니다.
    assert "postgis-only.yml" not in names


def test_exempt_entries_state_a_reason() -> None:
    """면제에는 이유가 붙어야 한다 — 이유 없는 면제가 다음 사각이다."""

    assert all(reason.strip() for reason in _EXEMPT.values())
    assert all(len(reason) > 20 for reason in _EXEMPT.values())
