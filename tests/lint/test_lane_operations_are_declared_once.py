"""D2 lane의 operation·산출물 계약이 **한 곳에서만** 선언되는지 본다.

`assert_container_residue_zero`는 실행이 끝난 뒤 결정론적 컨테이너 이름이 남아 있지
않은지 확인한다. 그런데 그 이름을 만들려면 operation 목록이 필요했고, 종전에는 그
목록이 호출부와 잔여물 루프 **두 곳에** 리터럴로 있었다. 새 operation을 호출부에만
더하면 잔여물 확인이 그 이름을 조용히 건너뛴다 — 컨테이너가 남아도 lane이 green이다.

곧 실제로 그럴 예정이었다: `T-VN-D2-API-AUDIT`가 helper의 `api-audit`/`purge` 경로를
살리면 `helper-api-audit`·`helper-purge`가 생긴다.

같은 이유로 evidence 계약도 결박한다. `_validate_evidence`는 **스펙이 통과한 뒤에야**
돌기 때문에, 파일 집합이나 operation 집합이 어긋나면 배포 스택 실행을 통째로 한 번
치르고서야 그 사실을 안다. `.stderr` 셋과 `executor.log`가 각각 실행 한 번씩을 먹었다.

2026-09-06 적대 리뷰가 이 게이트 자체의 과허용을 **실측**했다. 전부 "게이트가 자기
존재 이유인 실패를 green으로 통과시킨다"였다:

1. guard의 **존재**만 보고 **동작**을 안 봤다. 비교를 `!=` → `==` 로 뒤집으면 빈
   문자열까지 통과하는데 게이트는 6/6 green이었다.
2. `assert "die " in guard` 도, 잔여물 루프의 `${LANE_OPERATIONS[@]}` 확인도 **주석
   한 줄**로 만족됐다.
3. guard의 **위치**를 안 봤다 — supervisor 기동 뒤로 옮겨도 green.
4. `re.search`가 검증기의 **첫** `required_operations`만 읽어 **recovery 경로가 전혀
   결박되지 않았다**. recovery `expected_names`도 진부분집합만 확인했다.
5. `container_name`을 직접 불러 funnel을 우회하면 정적·런타임 어느 쪽도 못 봤다.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[2]
_RUNNER = _ROOT / "scripts" / "run-admin-feature-live-acceptance.sh"
_STATE = _ROOT / "scripts" / "admin_feature_live_state.py"
_SUPERVISOR = _ROOT / "scripts" / "admin_feature_live_supervisor.py"

_DECLARATION = re.compile(
    r"^readonly LANE_OPERATIONS=\(\n(?P<body>.*?)^\)$", re.MULTILINE | re.DOTALL
)
_GUARD_FUNCTION = re.compile(
    r"^assert_registered_operation\(\) \{\n.*?^\}$", re.MULTILINE | re.DOTALL
)
_SHELL_FUNCTION = re.compile(
    r"^(?P<name>[A-Za-z_][A-Za-z0-9_]*)\(\) \{\n(?P<body>.*?)^\}$",
    re.MULTILINE | re.DOTALL,
)
#: `run_helper cleanup "$RUNTIME_DIR/direct-cleanup.json"` → `helper-cleanup`
_HELPER_CALL = re.compile(
    r"^\s*run_helper\s+(?P<action>[a-z][a-z0-9-]*)\b", re.MULTILINE
)
_EXECUTOR_CALL = re.compile(
    r"^\s*run_executor\s+(?P<operation>[a-z][a-z0-9-]*)\b", re.MULTILINE
)
_SUPERVISOR_CALL = re.compile(
    r"^\s*run_supervisor\s+[a-z]+\s+(?P<operation>[a-z][a-z0-9-]*)\b", re.MULTILINE
)
_HELPER_OUTPUT = re.compile(
    r'^\s*run_helper\s+[a-z][a-z0-9-]*\s+"\$RUNTIME_DIR/(?P<name>[A-Za-z0-9._-]+)"',
    re.MULTILINE,
)
_EXECUTOR_OUTPUT = re.compile(
    r'^\s*run_executor\s+[a-z][a-z0-9-]*\s+"\$RUNTIME_DIR/(?P<name>[A-Za-z0-9._-]+)"',
    re.MULTILINE,
)
#: `--output "$RUNTIME_DIR/cursor-probe.json"` 같은 임의의 산출물 경로
_RUNTIME_PATH = re.compile(r'"\$RUNTIME_DIR/(?P<name>[A-Za-z0-9._-]+)"')
_EXPECTED_BLOCK = re.compile(r"expected_names = \{(?P<body>.*?)\n        \}", re.DOTALL)
_REQUIRED_BLOCK = re.compile(r"required_operations = \{(?P<body>[^}]*)\}", re.DOTALL)
_ENTRY = re.compile(r'"(?P<name>[A-Za-z0-9._-]+)"')
_STDERR_SIBLING = re.compile(
    r'_write_root_only_file\(\s*f"\{self\.args\.output\}(?P<suffix>[A-Za-z0-9._-]+)"'
)

#: 정상 실행 / 복구 실행의 진입 함수. 검증기의 두 계약이 각각 이 둘에 대응한다.
_ENTRY_FUNCTIONS = ("run_new", "recover_run")
#: 컨테이너 **이름을 만들어도 되는** 곳. funnel은 만들기 위해, 나머지 둘은 이미
#: 있는 것을 확인·제거하기 위해 부른다. 이 셋 밖에서 이름을 만들면 등록 확인을
#: 우회해 `docker create --name`을 부를 수 있다.
_CONTAINER_NAME_CALLERS = [
    "assert_container_residue_zero",
    "drain_terminal_active",
    "run_supervisor",
]


def _runner_source() -> str:
    return _RUNNER.read_text(encoding="utf-8")


def _without_comments(text: str) -> str:
    """줄 주석을 지운다.

    부분문자열 검사가 **주석으로 만족되던** 구멍을 닫는다. 적대 리뷰가 잔여물 루프와
    `die` 확인 둘 다 주석 한 줄로 green을 만들었다. 문자열 안의 `#`은 이 lane 소스에
    나타나지 않으므로 단순 규칙으로 충분하다.
    """

    return "\n".join(re.sub(r"#.*$", "", line) for line in text.splitlines())


def _shell_functions() -> dict[str, str]:
    return {
        match.group("name"): match.group("body")
        for match in _SHELL_FUNCTION.finditer(_runner_source())
    }


def _function_body(name: str) -> str:
    functions = _shell_functions()
    assert name in functions, (
        f"러너에서 `{name}` 함수를 찾지 못했다 — 이름이 바뀌었으면 이 게이트도 함께 "
        "다시 판단하라. 지금 상태로는 아무것도 유도하지 못한다."
    )
    return functions[name]


def _reachable_body(entry: str, *, until: str | None = None) -> str:
    """진입 함수와 그것이 부르는 `run_*` 래퍼들의 본문을 합친다.

    `run_cursor_probe`처럼 한 겹 감싼 호출이 있어 진입 함수만 보면 probe operation과
    그 산출물을 놓친다.

    `until`을 주면 **진입 함수 본문을 먼저 자르고** 그 앞부분에서만 호출을 따라간다.
    합친 뒤에 자르면 래퍼 본문이 절단 지점 뒤로 밀려 통째로 사라진다 —
    `cursor-probe.json`이 실제로 그렇게 사라졌다.
    """

    functions = _shell_functions()
    seen: set[str] = {entry}
    root = _function_body(entry)
    if until is not None:
        root = _without_comments(root).partition(until)[0]
    parts: list[str] = [root]
    pending = [
        called
        for called in re.findall(r"\b(run_[A-Za-z0-9_]*)\b", root)
        if called in functions and called not in seen
    ]
    while pending:
        name = pending.pop()
        if name in seen or name not in functions:
            continue
        seen.add(name)
        body = functions[name]
        parts.append(body)
        pending.extend(
            called
            for called in re.findall(r"\b(run_[A-Za-z0-9_]*)\b", body)
            if called in functions and called not in seen
        )
    return "\n".join(parts)


def _declared_operations() -> list[str]:
    match = _DECLARATION.search(_runner_source())
    assert match is not None, (
        "`readonly LANE_OPERATIONS=(...)` 선언을 찾지 못했다 — 목록이 다시 흩어졌거나 "
        "이 게이트의 파서가 낡았다. 어느 쪽이든 잔여물 확인의 범위를 다시 판단하라."
    )
    return [
        line.strip()
        for line in match.group("body").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def _operations_in(body: str) -> set[str]:
    """본문이 만드는 operation 이름을 유도한다.

    `run_helper <action>`은 supervisor에 `helper-<action>`으로 넘어간다. 나머지 둘은
    이름을 그대로 넘긴다.
    """

    operations = {
        f"helper-{match.group('action')}" for match in _HELPER_CALL.finditer(body)
    }
    operations |= {match.group("operation") for match in _EXECUTOR_CALL.finditer(body)}
    operations |= {match.group("operation") for match in _SUPERVISOR_CALL.finditer(body)}
    return operations


def _supervisor_stderr_suffix() -> str:
    """supervisor가 helper 출력 옆에 붙이는 접미사를 **생산자에서** 읽는다.

    검증기 상수(`_HELPER_STDERR_SUFFIX`)를 읽으면 두 소비자를 서로 대조하는 꼴이라
    둘이 같이 틀려도 green이다. 파일을 실제로 만드는 쪽에서 유도한다.
    """

    match = _STDERR_SIBLING.search(_SUPERVISOR.read_text(encoding="utf-8"))
    assert match is not None, (
        "supervisor의 helper stderr sibling 기록을 찾지 못했다 — 이름 규칙이 바뀌었으면 "
        "evidence 파일 집합 계약도 함께 다시 판단하라."
    )
    return match.group("suffix")


def _produced_names_in(body: str) -> set[str]:
    """그 실행이 `$RUNTIME_DIR` 최상위에 남기는 이름 — **evidence 검증 시점까지**.

    호출자가 `validate_evidence` 앞까지로 자른 본문을 준다 — `write_result`처럼 검증
    **뒤에** 쓰는 것은 파일 집합 계약 대상이 아니기 때문이다. 자르지 않으면
    `result.json`이 계약에 없다고 거짓 실패한다.
    """

    before = _without_comments(body)
    suffix = _supervisor_stderr_suffix()
    names = {"lifecycle"}
    for match in _HELPER_OUTPUT.finditer(before):
        names.add(match.group("name"))
        names.add(match.group("name") + suffix)
    names |= {match.group("name") for match in _EXECUTOR_OUTPUT.finditer(before)}
    names |= {match.group("name") for match in _RUNTIME_PATH.finditer(before)}
    return names


def _lane_evidence_body(entry: str) -> str:
    """evidence 검증 **전까지**의 실행 본문."""

    return _reachable_body(entry, until="validate_evidence")


def _state_source() -> str:
    return _STATE.read_text(encoding="utf-8")


def _validator_expected_names() -> list[set[str]]:
    """검증기가 요구하는 파일 집합 둘(normal, recovery)."""

    source = _state_source()
    suffix = re.search(
        r'_HELPER_STDERR_SUFFIX:\s*Final\[str\]\s*=\s*"(?P<value>[^"]+)"', source
    )
    assert suffix is not None, "`_HELPER_STDERR_SUFFIX` 상수를 찾지 못했다"
    sets: list[set[str]] = []
    for match in _EXPECTED_BLOCK.finditer(source):
        names: set[str] = set()
        for line in match.group("body").splitlines():
            entry = _ENTRY.search(line)
            if entry is None:
                continue
            name = entry.group("name")
            if "_HELPER_STDERR_SUFFIX" in line:
                name += suffix.group("value")
            names.add(name)
        sets.append(names)
    return sets


def _validator_required_operations() -> list[set[str]]:
    """검증기가 요구하는 operation 집합 둘(normal, recovery).

    종전에는 `re.search`로 **첫 블록만** 읽어 recovery 경로가 전혀 결박되지 않았다
    (적대 리뷰 실측).
    """

    return [
        set(_ENTRY.findall(match.group("body")))
        for match in _REQUIRED_BLOCK.finditer(_state_source())
    ]


def test_the_gate_reads_both_sides() -> None:
    """대조 양쪽이 실제로 읽혔는지부터 본다 — 비면 아래 단언이 공허하다."""

    declared = _declared_operations()
    assert len(declared) >= 5, f"선언된 operation을 {len(declared)}개만 읽었다"
    assert len(declared) == len(set(declared)), f"선언에 중복이 있다: {declared}"
    for entry in _ENTRY_FUNCTIONS:
        assert _operations_in(
            _reachable_body(entry)
        ), f"`{entry}`에서 operation을 하나도 유도하지 못했다"
        produced = _produced_names_in(_lane_evidence_body(entry))
        assert len(produced) >= 4, f"`{entry}`의 산출물을 {len(produced)}개만 유도했다"
    assert len(_validator_expected_names()) == 2, "검증기 파일 집합이 둘이 아니다"
    assert len(_validator_required_operations()) == 2, "검증기 operation 집합이 둘이 아니다"


def test_every_invoked_operation_is_declared() -> None:
    """호출부가 만드는 operation과 선언이 정확히 같아야 한다."""

    declared = set(_declared_operations())
    invoked: set[str] = set()
    for entry in _ENTRY_FUNCTIONS:
        invoked |= _operations_in(_reachable_body(entry))
    unknown = sorted(invoked - declared)
    assert unknown == [], (
        f"호출부가 선언에 없는 operation을 만든다: {unknown}. "
        "`assert_container_residue_zero`가 그 이름의 컨테이너를 **확인하지 않으므로** "
        "잔여물이 남아도 lane이 green이 된다. `LANE_OPERATIONS`에 더해라."
    )
    unused = sorted(declared - invoked)
    assert unused == [], (
        f"선언에 있으나 아무 경로도 만들지 않는 operation이 있다: {unused}. "
        "죽은 선언은 잔여물 확인의 범위를 부풀리기만 한다 — 지우거나 부르는 곳을 만들어라."
    )


def test_the_residue_loop_reads_the_declaration() -> None:
    """잔여물 루프가 리터럴이 아니라 선언을 읽어야 한다."""

    body = _without_comments(_function_body("assert_container_residue_zero"))
    assert '"${LANE_OPERATIONS[@]}"' in body, (
        "잔여물 루프가 `LANE_OPERATIONS`를 읽지 않는다 — 목록이 다시 이중 선언됐다. "
        "호출부에만 더한 operation을 이 확인이 건너뛰게 된다."
    )
    stray = sorted(
        set(_declared_operations()) & set(re.findall(r"[a-z][a-z0-9-]+", body))
    )
    assert stray == [], (
        f"잔여물 루프 본문에 operation 이름이 리터럴로 있다: {stray}. 선언을 읽는 것처럼 "
        "보이지만 리터럴이 함께 남아 이중 선언이 부활했을 수 있다."
    )


def test_the_launcher_binds_the_declaration_before_it_acts() -> None:
    """등록 확인이 **부수효과보다 앞**에 있어야 한다.

    종전에는 부분문자열 존재만 봤다. 확인을 supervisor 기동 뒤로 옮겨도 green이었고,
    그러면 컨테이너가 이미 만들어진 뒤에 죽는다(적대 리뷰 실측).
    """

    funnel = _without_comments(_function_body("run_supervisor"))
    assert 'assert_registered_operation "$operation"' in funnel, (
        "`run_supervisor`가 operation 등록을 확인하지 않는다 — 변수로 들어오는 "
        "operation이 선언 밖이어도 컨테이너가 만들어진다."
    )
    assert funnel.index("assert_registered_operation") < funnel.index("setsid"), (
        "등록 확인이 supervisor 기동 **뒤**에 있다 — 컨테이너가 이미 만들어진 뒤에 "
        "죽으므로 확인이 아니라 사후 통보다."
    )
    executor = _without_comments(_function_body("run_executor"))
    assert executor.index("assert_registered_operation") < executor.index("mkdir"), (
        "`run_executor`가 디렉터리를 만든 **뒤에** 등록을 확인한다 — 미등록 operation이 "
        "root 소유 아티팩트 디렉터리를 남기고 죽는다."
    )


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash가 없다")
def test_the_registration_guard_actually_rejects() -> None:
    """guard를 **실제로 실행해** 동작을 본다.

    존재만 보면 비교를 한 글자 뒤집는 것으로 무력화된다 — 그때 guard는 빈 문자열까지
    통과시키는데 게이트는 green이었다(적대 리뷰 실측). 선언과 guard만 뽑아 돌린다.
    """

    source = _runner_source()
    declaration = _DECLARATION.search(source)
    assert declaration is not None, "선언을 찾지 못했다"
    guard = _GUARD_FUNCTION.search(source)
    assert guard is not None, "`assert_registered_operation` 함수를 찾지 못했다"
    prelude = (
        "set -euo pipefail\n"
        'die() { echo "DIE: $*" >&2; exit 1; }\n'
        f"{declaration.group(0)}\n{guard.group(0)}\n"
    )
    declared = _declared_operations()
    # 거부 후보는 **선언에 없는 것**에서 유도한다. 리터럴로 박으면 그중 하나가 나중에
    # 등록되는 순간(실제로 `helper-api-audit`이 그랬다) 이 테스트가 "등록된 것을
    # 거부해야 한다"고 요구하며 거짓 실패한다.
    outsiders = [
        name
        for name in ("helper-purge", "helper-api-audit", "helper-nonexistent", "*", "")
        if name not in declared
    ]
    assert outsiders, "선언 밖 후보를 하나도 만들지 못했다 — 거부 검증이 공허하다"
    accepted: list[str] = []
    rejected: list[str] = []
    for candidate in [*declared, *outsiders]:
        # 후보를 **스크립트 본문에** 셸 인용으로 박고 **바이트 stdin**으로 넘긴다.
        # Git Bash(MSYS)에서는 셋 다 새는 것을 실측했다(2026-09-06):
        #   `bash -c s arg0 arg1` → `$0=/bin/bash`, `$#=0`
        #   `env=`로 넘긴 변수  → `${VAR-UNSET}` = UNSET
        #   Windows 경로 인자    → 역슬래시가 먹혀 `No such file or directory`
        # 그리고 text 모드 stdin은 CRLF가 되어 `set: pipefail\r: invalid option name`.
        # 어느 경우든 이 테스트가 조용히 공허해지므로(전부 통과 또는 전부 거부)
        # 아래 `accepted == declared` 가 그 두 방향을 모두 잡는다.
        quoted = "'" + candidate.replace("'", "'\\''") + "'"
        script = f"{prelude}assert_registered_operation {quoted}\n"
        completed = subprocess.run(  # noqa: S603
            ["bash", "-s"],
            input=script.encode("utf-8"),
            capture_output=True,
            check=False,
        )
        (accepted if completed.returncode == 0 else rejected).append(candidate)
    assert accepted == declared, (
        f"guard가 통과시킨 것이 선언과 다르다. 통과={accepted} 거부={rejected}. "
        "비교가 뒤집혔거나 인용이 빠져 패턴으로 해석되고 있는지 보라."
    )
    unrejected = [candidate for candidate in outsiders if candidate not in rejected]
    assert unrejected == [], (
        f"guard가 미등록 operation을 거부하지 않는다: {unrejected!r} — 확인이 아니라 장식이다."
    )


def test_the_container_name_helper_is_only_reachable_through_the_funnel() -> None:
    """이름을 만드는 곳이 funnel과 잔여물 확인 둘뿐이어야 한다.

    `container_name`을 직접 불러 `docker create --name`을 쓰면 런타임 guard도 정적
    유도도 보지 못한다(적대 리뷰 실측).
    """

    callers = sorted(
        name
        for name, body in _shell_functions().items()
        if name != "container_name"
        and re.search(r"\bcontainer_name\b", _without_comments(body))
    )
    assert callers == _CONTAINER_NAME_CALLERS, (
        f"`container_name`을 부르는 곳이 {callers}다. funnel(`run_supervisor`)과 잔여물 "
        "확인 밖에서 이름을 만들면 등록 확인을 우회한다."
    )
    funnel = _without_comments(_function_body("run_supervisor"))
    assert 'container_name "$ACTOR" "$ATTEMPT" "$operation"' in funnel, (
        "funnel이 **검증한 그 변수**로 이름을 만들지 않는다 — 확인한 값과 쓰는 값이 "
        "달라지면 등록 확인이 의미를 잃는다."
    )


def test_the_evidence_file_set_matches_what_each_lane_produces() -> None:
    """검증기의 두 파일 집합이 각 진입 함수의 유도와 **정확히** 같아야 한다.

    종전에는 normal만 exact로 보고 recovery는 진부분집합만 확인했다. recovery
    집합에서 `playwright-recovery`를 지워도 green이었고, 그러면 recovery 실행이
    evidence 단계에서 죽는다 — 배포 스택 실행 1회 손실(적대 리뷰 실측).
    """

    for entry, expected in zip(
        _ENTRY_FUNCTIONS, _validator_expected_names(), strict=True
    ):
        produced = _produced_names_in(_lane_evidence_body(entry))
        assert expected == produced, (
            f"`{entry}`의 산출물 유도와 검증기 파일 집합이 다르다.\n"
            f"  검증기에만: {sorted(expected - produced)}\n"
            f"  호출부에만: {sorted(produced - expected)}\n"
            "이 불일치는 스펙이 통과한 뒤 evidence 검증에서만 드러난다 — 배포 스택 "
            "실행 한 번을 치르고 나서야 알게 된다. 여기서 맞춰라."
        )


def test_the_validator_operation_sets_match_each_lane() -> None:
    """검증기의 두 operation 집합이 각 진입 함수의 유도와 같아야 한다.

    lifecycle 파일 이름이 그 집합에서 만들어져 실제 디렉터리와 exact 대조되므로,
    호출부에 operation을 더하고 여기를 안 고치면 lane이 evidence 단계에서 죽는다.
    """

    union: set[str] = set()
    for entry, required in zip(
        _ENTRY_FUNCTIONS, _validator_required_operations(), strict=True
    ):
        invoked = _operations_in(_reachable_body(entry))
        assert required == invoked, (
            f"`{entry}`의 operation 유도와 검증기 집합이 다르다.\n"
            f"  검증기에만: {sorted(required - invoked)}\n"
            f"  호출부에만: {sorted(invoked - required)}"
        )
        union |= required
    declared = set(_declared_operations())
    assert union == declared, (
        f"두 lane의 operation 합집합이 선언과 다르다.\n"
        f"  선언에만: {sorted(declared - union)}\n"
        f"  검증기에만: {sorted(union - declared)}\n"
        "선언은 잔여물 확인의 범위이므로 두 lane이 만드는 것을 정확히 덮어야 한다."
    )


def _entry_function_body(name: str) -> str:
    """진입 함수 본문. 이 파일의 다른 게이트와 같은 파서를 쓴다."""
    runner = _RUNNER.read_text(encoding="utf-8")
    for match in _SHELL_FUNCTION.finditer(runner):
        if match.group("name") == name:
            return match.group("body")
    raise AssertionError(f"러너에서 `{name}` 함수를 찾지 못했다")


#: lane마다 "여기부터는 run 전체가 초록이다"를 선언하는 마지막 게이트.
#: purge는 그 **뒤**여야 한다.
_LAST_GATE = {
    "run_new": "write_blocked test-failed-restored",
    "recover_run": "write_blocked recovery-failed",
}


@pytest.mark.parametrize("entry", _ENTRY_FUNCTIONS)
def test_purge_runs_only_after_every_gate_of_its_lane(entry: str) -> None:
    """purge는 감사·테스트 게이트를 전부 지난 뒤에만 돈다.

    purge를 게이트 **앞**에 두면 두 가지가 동시에 깨진다. 둘 다 적대 리뷰가
    독립적인 두 렌즈에서 잡은 것이다.

    1. 감사가 red인 채로 그 감사 대상 행을 지운다. 운영자가 무엇이 걸렸는지
       DB에서 다시 볼 수 없다.
    2. **실패한 run의 소유 Feature가 사라진다.** 복구 lane의 api-audit은
       `_audit_complete_api_owned`에서 그 행 1건을 요구하므로, 먼저 지우면
       `recover`가 구조적으로 통과 불가능해진다. BLOCKED는 `recover`로만 지워지고
       `run` 모드는 `prior BLOCKED state requires recover mode`로 막히므로,
       그 순간 D2 lane이 prod에서 **영구 정지**한다.

    사람이 읽어서는 알 수 없는 순서다 — 두 줄의 상대 위치가 lane의 생사를
    가르는데 둘 다 그냥 helper 호출로 보인다. 그래서 게이트로 못 박는다.
    """
    body = _entry_function_body(entry)
    gate = _LAST_GATE[entry]

    gate_at = body.find(gate)
    purge_at = body.find('run_helper purge "$RUNTIME_DIR/')
    evidence_at = body.find("validate_evidence ")

    assert gate_at >= 0, f"`{entry}`에서 마지막 게이트 `{gate}`를 찾지 못했다"
    assert purge_at >= 0, f"`{entry}`가 purge를 부르지 않는다"
    assert evidence_at >= 0, f"`{entry}`가 증거 검증을 부르지 않는다"

    assert gate_at < purge_at, (
        f"`{entry}`가 게이트(`{gate}`)보다 **먼저** purge한다. 그러면 실패한 run의 "
        "소유 Feature가 사라져 복구 lane의 api-audit이 구조적으로 통과할 수 없고, "
        "BLOCKED가 영구화돼 lane이 prod에서 멈춘다."
    )
    assert purge_at < evidence_at, (
        f"`{entry}`가 증거 검증 뒤에 purge한다 — 검증기가 `direct-purge.json`을 "
        "요구하므로 파일이 아직 없다."
    )
