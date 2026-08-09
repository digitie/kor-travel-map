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
_BLOCKING_TRIGGERS = ("pull_request", "push", "merge_group")

#: CI에 있으나 로컬에서 **의도적으로** 돌리지 않는 명령과 그 이유.
#: 새 항목을 넣을 때는 반드시 이유를 적는다 — 이유 없는 면제가 곧 다음 사각이다.
_EXEMPT: dict[str, str] = {
    "ruff format --check": (
        "lint.yml에서 `if: false`다. 이 저장소는 자동 format을 쓰지 않으며 286개 "
        "파일이 재포맷 대상이라 켜면 즉시 red가 된다."
    ),
    "python -m pip install": "의존성 설치는 컨테이너 이미지가 대신한다.",
    "pip install": "의존성 설치는 컨테이너 이미지가 대신한다(위 항목과 같은 이유).",
    "mv ": "coverage 데이터 이동은 job 간 전달용이라 로컬에 대응물이 없다.",
    "npx --yes npm@12.0.1 ci": "의존성 설치. 로컬은 이미 설치된 node_modules를 쓴다.",
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

    candidates = sorted(
        [*_WORKFLOW_DIR.glob("*.yml"), *_WORKFLOW_DIR.glob("*.yaml")]
    )
    found: list[Path] = []
    reusable: set[str] = set()
    for path in candidates:
        text = path.read_text(encoding="utf-8")
        # 헤더는 **열 0의 ``jobs:``**까지다. `text.split("jobs:")`는 주석이나 문자열
        # 안의 `jobs:` 한 조각에도 잘려, 그 앞에 트리거가 없으면 워크플로가 통째로
        # 안 보인다(적대 리뷰 8라운드 X5b). 주석 줄은 트리거 근거가 아니다.
        header_lines: list[str] = []
        for line in text.splitlines():
            if re.match(r"^jobs:\s*$", line):
                break
            if not line.lstrip().startswith("#"):
                header_lines.append(line)
        header = "\n".join(header_lines)
        # `on: pull_request:` 뿐 아니라 `on: [push, pull_request]` 배열도 차단이다.
        if any(
            re.search(rf"(?<![A-Za-z_]){trigger}(?![A-Za-z_])", header)
            for trigger in _BLOCKING_TRIGGERS
        ):
            found.append(path)
            # 차단 워크플로가 job-level `uses:`로 부르는 재사용 워크플로도 차단이다.
            reusable.update(
                re.findall(r"uses:\s*\./\.github/workflows/([\w.-]+)", text)
            )
    for name in sorted(reusable):
        target = _WORKFLOW_DIR / name
        if target.exists() and target not in found:
            found.append(target)
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
    for entry in block:
        # 로컬 composite action은 임의의 명령을 돌린다 — `run:`만 보면 안 보인다.
        local_action = re.match(r"^\s*(?:- )?uses:\s*(\./[\w./-]+)\s*$", entry)
        if local_action is not None:
            commands.append(f"uses {local_action.group(1)}")
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
    """면제는 **명령의 접두**로만 판정한다.

    부분문자열 면제는 밀수 토큰이 된다 — 진짜 차단 스텝을
    ``bash scripts/verify-x.sh && echo done``이나
    ``pip install ruff && bash scripts/verify-x.sh``로 적으면 ``echo ``/``pip install``
    이 명령 **어딘가에** 있다는 이유로 통째로 면제됐다(적대 리뷰 8라운드 X3·X4·X6·X7).
    면제표의 "echo는 실패를 만들 수 없다"는 서술도 그래서 거짓이었다 — 코드가 하던
    일은 "echo인 명령"이 아니라 "echo를 포함한 명령"의 면제였다.

    로컬 composite action(``uses ./…``)은 저장소 안의 임의 명령을 돌리므로 게이트다.
    """

    if command.startswith("uses ./"):
        return False
    # `&&`로 이어 붙인 명령은 **구간마다** 판정한다. 접두만 보면
    # `pip install ruff && bash scripts/verify-x6.sh`처럼 면제 명령 뒤에 진짜
    # 게이트를 붙여 통째로 면제받을 수 있다(X6·X7).
    segments = [segment.strip() for segment in command.split("&&") if segment.strip()]
    return bool(segments) and all(
        any(segment.startswith(marker) for marker in _EXEMPT) for segment in segments
    )


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
    if command.startswith("uses "):
        return [command.split(maxsplit=1)[1]]
    if "export_openapi.py" in command:
        # `--check`가 빠지면 검사가 아니라 재작성이 된다 — 로컬이 drift를 만들고도
        # 통과한다. **이 분기는 아래 일반 script 분기보다 먼저 와야 한다** —
        # 순서가 뒤바뀌면 경로만 조각이 되어 플래그 drift를 놓친다(변이 N6).
        fragments = ["export_openapi.py"]
        fragments.extend(
            flag for flag in ("--check", "--profile all") if flag in command
        )
        return fragments
    script_call = re.search(r"(scripts/[\w./-]+\.py)", command)
    if script_call is not None:
        return [script_call.group(1)]
    if command.startswith("pytest "):
        # 경로를 **전부** 요구한다. 첫 경로 하나만 보면 로컬이
        # `pytest tests/unit tests/lint` -> `pytest tests/unit`으로 줄여도 통과한다
        # (적대 리뷰 8라운드 X1). 같은 축소를 ruff/mypy에는 이미 막아 놓고 pytest만
        # 빠져 있었다.
        fragments = [
            token
            for token in command.split()[1:]
            if not token.startswith("-") and "/" in token
        ]
        if not fragments:
            fragments = [command.split()[1]]
        gate = re.search(r"--cov-fail-under=(\d+)", command)
        if gate is not None and gate.group(1) != "0":
            fragments.append(f"--cov-fail-under={gate.group(1)}")
        return fragments
    if command.startswith("ruff check"):
        # 경로를 전부 요구한다. `ruff check` 하나만 보면 로컬이 7경로 중 1개로
        # 좁혀도 통과한다(적대 리뷰 7라운드 변이 N3).
        return ["ruff check", *command.split()[2:]]
    mypy = re.search(r"mypy --strict -p ([\w.]+)", command)
    if mypy is not None:
        # `--strict`를 조각에 넣는다. 빼면 로컬이 느슨한 mypy로 통과한다(변이 N4).
        return ["--strict", f"-p {mypy.group(1)}"]
    if "lint_imports_command" in command:
        return ["lint_imports_command"]
    return None


def _contains_token(line: str, fragment: str) -> str | None:
    """조각이 **토큰 경계에서** 나타나는지 본다.

    단순 부분문자열이면 조각을 서로 빌려준다 — `-p kortravelmap`이
    `-p kortravelmap.api` 줄에도 매치돼 `mypy core` 게이트를 지워도 감사기가
    침묵했다(적대 리뷰 7라운드). 조각 뒤에 식별자 문자가 이어지면 다른 대상이다.
    """

    start = 0
    while True:
        index = line.find(fragment, start)
        if index < 0:
            return None
        after = index + len(fragment)
        trailing = line[after : after + 1]
        if trailing not in {".", "-", "_", "/", ":"} and not trailing.isalnum():
            return line
        start = after


def _expanded_script_lines() -> list[str]:
    """스크립트 줄을 **셸 변수를 펼친 상태로** 돌려준다.

    게이트가 `$ADMIN` 같은 변수를 쓰면 리터럴 경로가 그 줄에 없다. 펼치지 않으면
    감사가 실재하는 게이트를 없다고 오판한다 — 반대로 펼치지 않은 채 조각을 느슨히
    잡으면 변이 J·K(다른 게이트가 조각을 빌려줌)를 놓친다.
    """

    text = _SCRIPT.read_text(encoding="utf-8")
    assignments = dict(re.findall(r'^([A-Z_]+)="([^"]*)"$', text, flags=re.M))
    logical: list[str] = []
    pending: list[str] = []
    for line in text.splitlines():
        # **주석은 증거가 아니다.** 실행문을 지우고 같은 문자열을 주석으로 남기면
        # 게이트가 사라져도 감사기가 침묵한다 — 실제로 커밋 5235c910이 그렇게 해서
        # react-doctor 게이트를 주석만으로 통과시켰고, 적대 리뷰 7라운드가 잡았다.
        if line.lstrip().startswith("#"):
            continue
        for name, value in assignments.items():
            line = line.replace(f"${name}", value)
        # 줄바꿈 이어쓰기(`\`)는 한 논리 줄이다. 안 이으면 이어진 쪽 조각이
        # `run_gate` 호출과 떨어져, 아래 도달성 판정에서 사라진다.
        if line.rstrip().endswith("\\"):
            pending.append(line.rstrip()[:-1])
            continue
        logical.append(" ".join([*pending, line]) if pending else line)
        pending = []
    if pending:
        logical.append(" ".join(pending))
    return logical


def _gate_lines() -> list[str]:
    """**``run_gate``로 실제 실행되는** 줄만 돌려준다.

    스크립트 어딘가에 조각이 있기만 하면 되는 판정은 약하다 — 실행문을 지워도
    헬퍼 함수 본문이나 주석에 같은 문자열이 남아 감사기가 침묵한다(변이 M7:
    ``run_gate "admin react-doctor" doctor_on_native_fs``를 지워도
    ``doctor_on_native_fs`` 본문의 ``run doctor``가 조각을 대신 만족시켰다).

    그래서 도달성을 본다: ``run_gate`` 호출 줄, 그리고 그 줄이 **이름으로 부르는**
    함수의 본문만 증거로 인정한다. 아무도 부르지 않는 함수는 죽은 코드다.
    """

    logical = _expanded_script_lines()
    bodies: dict[str, list[str]] = {}
    current: str | None = None
    for line in logical:
        define = re.match(r"^(\w+)\(\)\s*\{", line)
        if define is not None:
            current = define.group(1)
            bodies[current] = []
            continue
        if current is not None:
            if line.startswith("}"):
                current = None
            else:
                bodies[current].append(line)
    gate_lines: list[str] = []
    for line in logical:
        if not line.lstrip().startswith("run_gate"):
            continue
        gate_lines.append(line)
        seen: set[str] = set()
        queue = [name for name in bodies if _contains_token(line, name)]
        while queue:
            name = queue.pop()
            if name in seen:
                continue
            seen.add(name)
            gate_lines.extend(bodies[name])
            queue.extend(
                other
                for body in [bodies[name]]
                for entry in body
                for other in bodies
                if other not in seen and _contains_token(entry, other)
            )
    return gate_lines


def test_gate_script_covers_every_ci_blocking_command() -> None:
    """CI가 돌리는 명령의 **식별 가능한 조각**이 게이트 스크립트에 있어야 한다.

    문자열 동등이 아니라 조각 포함으로 본다 — 로컬은 컨테이너/``python -m`` 접두가
    붙어 명령이 그대로 같을 수 없기 때문이다.
    """

    # 조각을 파일 전체에서 따로 찾으면 안 된다 — admin과 user-client의 게이트가
    # 서로의 조각을 빌려줘, 스크립트가 둘 중 하나를 지워도 통과한다(변이 J·K).
    # **한 줄에 모두** 있어야 그 게이트가 실재하는 것이다.
    script_lines = _gate_lines()
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
                all(_contains_token(line, fragment) for fragment in fragments)
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


def test_gate_sources_have_no_invisible_control_characters() -> None:
    """감사기·게이트 스크립트에 보이지 않는 제어문자가 없어야 한다.

    2026-08-09에 같은 사고를 두 번 냈다 — 셸 헤어독으로 파일을 고치면서 정규식
    `\b`(단어 경계)가 **백스페이스 문자(0x08)로 들어갔다**. 눈으로도 diff로도
    보이지 않고 패턴만 조용히 무력화된다. 첫 번째는 제어 흐름 감지를, 두 번째는
    차단 워크플로 판정을 통째로 죽였다(둘 다 "잡아야 할 것을 안 잡는" 방향이다).

    탭과 개행만 허용한다.
    """

    allowed = {0x09, 0x0A, 0x0D}
    for path in (Path(__file__), _SCRIPT, _ROOT / "scripts" / "audit-mutation-battery.py"):
        raw = path.read_bytes()
        bad = sorted({byte for byte in raw if byte < 0x20 and byte not in allowed})
        assert bad == [], f"{path.name}에 제어문자 {[hex(b) for b in bad]}"


def test_documented_integration_coverage_threshold_matches_pyproject() -> None:
    """스크립트가 적어 둔 integration 합산 임계가 실제 설정과 같아야 한다.

    CI의 integration 스텝은 ``--cov-fail-under``를 주지 않는다 — 임계는
    ``pyproject.toml``의 ``fail_under``에서 **암묵적으로** 온다. 그래서 조각 감사로는
    이 축의 drift가 보이지 않는다(적대 리뷰 8라운드 A6). 로컬이 그 합산 게이트를
    재현하지 못한다는 사실은 스크립트 머리말에 적혀 있고, 여기서는 **적어 둔 숫자가
    거짓이 되지 않게** 못을 박는다.
    """

    pyproject = (_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r"^fail_under\s*=\s*(\d+)", pyproject, flags=re.M)
    assert match is not None, "pyproject.toml에 fail_under가 없다"
    header = _SCRIPT.read_text(encoding="utf-8")
    assert f"fail_under={match.group(1)}" in header, (
        f"스크립트 머리말의 임계가 pyproject({match.group(1)})와 다르다"
    )


#: 게이트 줄에 있으면 **그 게이트는 실패할 수 없다**. 값과 이유를 함께 둔다.
_FAILURE_SUPPRESSORS: dict[str, str] = {
    "|| true": "실패해도 0으로 덮는다.",
    "|| :": "`:`는 no-op이라 `|| true`와 같다.",
    "|| exit 0": "실패를 성공 종료로 바꾼다.",
    "; true": "종료코드가 마지막 명령(`true`)의 것이 된다.",
    "set +e": "이후 실패가 스크립트 종료코드에 반영되지 않는다.",
    "--exit-zero": "린터가 발견을 하고도 0으로 끝난다.",
    "|| echo": "실패를 출력으로 바꿔 삼킨다.",
}


def test_gate_script_does_not_suppress_failures() -> None:
    """게이트가 **실패할 수 있는지**를 본다.

    미러링 감사는 "CI의 명령이 스크립트에 있는가"만 봤다. 그래서 어떤 게이트든
    `|| true`를 붙여 무력화해도 조각은 그대로라 침묵했다(적대 리뷰 8라운드
    X2a·X2c·X9·X10 — mypy/integration/openapi/next build 전부 생존).

    스크립트 자신은 이 실패 모드를 알고 있었다 — `py()` 주석이 "파이프를 걸지 마라,
    exit code가 마지막 명령의 것이 되어 게이트가 늘 통과한다"고 적어 두었다.
    아는 것과 검사하는 것은 다르다.
    """

    offenders: list[str] = []
    for line in _gate_lines():
        for marker, reason in _FAILURE_SUPPRESSORS.items():
            if marker in line:
                offenders.append(f"{marker} ({reason}): {line.strip()[:100]}")
    assert offenders == [], (
        "게이트가 실패를 삼킨다 — 통과해도 근거가 되지 못한다:\n" + "\n".join(offenders)
    )


def test_gate_script_keeps_eslint_warning_budget_at_zero() -> None:
    """eslint 게이트의 경고 예산이 0에서 벗어나지 않는다.

    로컬이 `--max-warnings=9999`를 덧붙이면 CI와 같은 npm script를 부르면서도
    판정만 느슨해진다. 조각 일치로는 보이지 않는다(변이 X2b).
    """

    budgets = re.findall(r"--max-warnings[= ](\d+)", "\n".join(_gate_lines()))
    assert all(value == "0" for value in budgets), (
        f"eslint 경고 예산이 0이 아니다: {budgets}"
    )


def test_exempt_entries_state_a_reason() -> None:
    """면제에는 이유가 붙어야 한다 — 이유 없는 면제가 다음 사각이다."""

    assert all(reason.strip() for reason in _EXEMPT.values())
    assert all(len(reason) > 20 for reason in _EXEMPT.values())
