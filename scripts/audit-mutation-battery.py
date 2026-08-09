"""``test_gate_script_mirrors_ci``가 실제로 무엇을 잡는지 **변이로 검증한다**.

감사 테스트가 통과한다는 것만으로는 그것이 유효하다는 뜻이 아니다 — 2026-08-09
적대 리뷰 6라운드가 변이 11종 중 7종이 그 감사를 그대로 통과함을 실증했다. 그중
J·K는 **게이트 스크립트가 자기 게이트 24개 중 2개를 지워도 감사가 침묵**하는
것이었다.

그래서 감사기나 게이트 스크립트를 고칠 때마다 이 배터리를 돌린다. 저장소를
건드리지 않고 ``/tmp`` 사본에만 변이를 심는다.

    # 컨테이너 안에서 (저장소가 /src에 마운트된 상태)
    python -B scripts/audit-mutation-battery.py

변이 목록 — **전부 FAIL로 잡혀야 한다**:

==  ====================================================
A   이름 있는 새 스텝
B   ``- name:``과 ``run:`` 사이에 주석 9줄
C   shell 스크립트를 부르는 스텝
D   이름 없는 스텝(``- run:``)
E   멀티라인 ``run: |``의 두 번째 명령
G   새 차단 워크플로 파일이 통째로 추가
H   스텝의 자기 가드(``if [ -d … ]``) 제거
I   coverage 임계 drift
J·K 게이트 스크립트가 자기 게이트를 삭제
L   게이트 스크립트가 integration 게이트를 삭제
M5  ``on: [push, pull_request]`` 배열 트리거 워크플로
M6  ``.yaml`` 확장자 워크플로
M7  실행문을 지우고 같은 문자열을 **주석으로만** 남김
M8  ``uses: ./.github/actions/…`` 로컬 composite action 스텝
M9  게이트를 **아무도 부르지 않는 함수**로 옮김
N1  다른 게이트에 조각을 빌려주는 게이트 삭제(``mypy core``)
N3  ``ruff check`` 경로 축소
N4  ``mypy --strict``에서 ``--strict`` 제거
N6  ``export_openapi.py``에서 ``--check`` 제거
==  ====================================================

M5~N6은 7라운드 적대 리뷰가 설계한 것으로 **전부 생존했었다** — 감사기가 통과하는
것과 감사기가 유효한 것은 다른 문제다.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

# 저장소 루트를 파일 위치에서 유도한다 — `/src` 하드코딩이면 pytest로 부를 수
# 없고, 그러면 이 배터리는 **어느 게이트에도 걸리지 않는** 도구로 남는다.
SRC = Path(__file__).resolve().parents[1]
WORK = Path("/tmp/ktm-audit-mutation")

_NODE_STEP = "      - name: Set up Node 22.23.1"
_FIXTURE_BLOCK = (
    "          if [ -d tests/fixtures ]; then\n"
    "            pytest tests/fixtures -q --no-cov\n"
    "          else\n"
    '            echo "tests/fixtures is absent; fixture replay gate is ready '
    'but has no replay suite yet."\n'
    "          fi"
)
_NEW_WORKFLOW = (
    "name: Security\n"
    "on:\n"
    "  pull_request:\n"
    "\n"
    "jobs:\n"
    "  scan:\n"
    "    runs-on: ubuntu-latest\n"
    "    steps:\n"
    "      - name: fake scan\n"
    "        run: npx --yes npm@12.0.1 run fake-gate-ggg\n"
)


def _insert_before_node_step(body: str) -> Callable[[str], str]:
    return lambda text: text.replace(_NODE_STEP, body + "\n\n" + _NODE_STEP, 1)


def _drop_script_lines(*markers: str) -> Callable[[str], str]:
    def mutate(text: str) -> str:
        return "".join(
            line
            for line in text.splitlines(keepends=True)
            if not any(marker in line for marker in markers)
        )

    return mutate


def _append_to_gate_line(marker: str, suffix: str) -> Callable[[str], str]:
    """``marker``를 담은 줄 끝에 ``suffix``를 붙인다(게이트 무력화 변이용)."""

    def mutate(text: str) -> str:
        out: list[str] = []
        done = False
        for line in text.splitlines(keepends=True):
            if not done and marker in line:
                stripped = line.rstrip("\r\n")
                out.append(stripped + suffix + line[len(stripped) :])
                done = True
            else:
                out.append(line)
        return "".join(out)

    return mutate


MUTATIONS: dict[str, tuple[str, Callable[[str], str] | None]] = {
    "A 이름있는 새 스텝": (
        "frontend.yml",
        _insert_before_node_step(
            "      - name: fake gate\n"
            "        run: npx --yes npm@12.0.1 run fake-gate-aaa"
        ),
    ),
    "B 주석 9줄 낀 스텝": (
        "frontend.yml",
        _insert_before_node_step(
            "      - name: fake gate\n"
            + "        # c\n" * 9
            + "        run: npx --yes npm@12.0.1 run fake-gate-bbb"
        ),
    ),
    "C shell 스크립트 스텝": (
        "frontend.yml",
        _insert_before_node_step(
            "      - name: fake gate\n        run: bash scripts/verify-brand-new.sh"
        ),
    ),
    "D 이름 없는 스텝": (
        "frontend.yml",
        _insert_before_node_step("      - run: npx --yes npm@12.0.1 run fake-gate-ddd"),
    ),
    "E 멀티라인 2번째 명령": (
        "frontend.yml",
        lambda text: text.replace(
            "npm@12.0.1 -w packages/kor-travel-map-user-client run type-check",
            "npm@12.0.1 -w packages/kor-travel-map-user-client run fake-gate-eee",
            1,
        ),
    ),
    "G 새 차단 워크플로": ("__new__", None),
    "H fixture 가드 제거": (
        "ci.yml",
        lambda text: text.replace(
            _FIXTURE_BLOCK, "          pytest tests/fixtures -q --no-cov", 1
        ),
    ),
    "I coverage 임계 drift": (
        "ci.yml",
        lambda text: text.replace("--cov-fail-under=70", "--cov-fail-under=99", 1),
    ),
    "J 스크립트에서 게이트 삭제(user-client gen)": (
        "__script__",
        _drop_script_lines("user-client gen:types:check"),
    ),
    "K 스크립트에서 게이트 삭제(user-client type)": (
        "__script__",
        _drop_script_lines("user-client type-check"),
    ),
    "L 스크립트에서 integration 삭제": (
        "__script__",
        _drop_script_lines("tests/integration", "pytest integration"),
    ),
    # --- 7라운드 적대 리뷰가 설계한 변이 (전부 생존했었다) ---
    "M7 실행문 지우고 주석만 남기기": (
        "__script__",
        lambda text: text.replace(
            'run_gate "admin react-doctor" doctor_on_native_fs',
            '#   CI 원본: $NPM -w $ADMIN run doctor',
            1,
        ),
    ),
    "N1 mypy core 게이트 삭제(조각 빌려주기)": (
        "__script__",
        _drop_script_lines('run_gate "mypy core"'),
    ),
    "N3 ruff 경로 축소": (
        "__script__",
        lambda text: re.sub(
            r"python -m ruff check src tests [^']*", "python -m ruff check src", text, count=1
        ),
    ),
    "N4 mypy --strict 제거": (
        "__script__",
        lambda text: text.replace(
            "python -m mypy --strict -p kortravelmap.api",
            "python -m mypy -p kortravelmap.api",
            1,
        ),
    ),
    "N6 openapi --check 제거": (
        "__script__",
        lambda text: text.replace(
            "export_openapi.py --profile all --check", "export_openapi.py --profile all", 1
        ),
    ),
    # 도달성 판정 자체를 겨냥한다 — 게이트를 아무도 부르지 않는 함수로 옮기면
    # 조각은 파일에 남지만 실행되지 않는다.
    "M9 죽은 함수로 게이트 이동": (
        "__script__",
        lambda text: text.replace(
            'run_gate "verify:next-sharp"       repo "$NPM run verify:next-sharp"',
            'dead_helper() {\n  repo "$NPM run verify:next-sharp"\n}',
            1,
        ),
    ),
    # --- 8라운드 적대 리뷰가 설계한 변이 (전부 생존했었다) ---
    # 부류 1: 게이트가 **실패할 수 없게** 만든다. 조각은 그대로라 미러링 감사는 침묵했다.
    "X2a mypy core 무력화(|| true)": (
        "__script__",
        _append_to_gate_line('run_gate "mypy core"', " || true"),
    ),
    "X2c integration 무력화(|| true)": (
        "__script__",
        _append_to_gate_line("--assert-ran /tmp/g4.log", " || true"),
    ),
    "X9 openapi 무력화(|| true)": (
        "__script__",
        _append_to_gate_line('run_gate "OpenAPI drift"', " || true"),
    ),
    "X10 next build 무력화(|| true)": (
        "__script__",
        _append_to_gate_line('run_gate "admin next build"', " || true"),
    ),
    "X2b eslint 경고 예산 완화": (
        "__script__",
        lambda text: text.replace(
            '"$NPM -w $ADMIN run lint"',
            '"$NPM -w $ADMIN run lint -- --max-warnings=9999"',
            1,
        ),
    ),
    # 부류 2: 로컬 pytest 경로 축소. ruff/mypy에는 막아 놓고 pytest만 빠져 있었다.
    "X1 pytest 스위트 축소(tests/lint 제거)": (
        "__script__",
        lambda text: text.replace(
            "python -m pytest tests/unit tests/lint -q",
            "python -m pytest tests/unit -q",
            1,
        ),
    ),
    # 부류 3: 면제 키를 부분문자열로 끼워 넣어 **새 차단 스텝을 밀수**한다.
    "X3 밀수(echo 포함)": (
        "frontend.yml",
        _insert_before_node_step(
            "      - name: fake gate\n"
            "        run: bash scripts/verify-x3.sh && echo done"
        ),
    ),
    "X4 밀수(.github/actions/ 경로)": (
        "frontend.yml",
        _insert_before_node_step(
            "      - name: fake gate\n"
            "        run: bash .github/actions/verify-x4.sh"
        ),
    ),
    "X6 밀수(pip install 포함)": (
        "frontend.yml",
        _insert_before_node_step(
            "      - name: fake gate\n"
            "        run: pip install ruff && bash scripts/verify-x6.sh"
        ),
    ),
    "X7 밀수(mv 포함)": (
        "frontend.yml",
        _insert_before_node_step(
            "      - name: fake gate\n"
            "        run: mv dist out && bash scripts/verify-x7.sh"
        ),
    ),
    # 부류 4: 차단 워크플로 탐지 회피.
    "X5b 헤더 주석에 jobs:": ("__jobs_comment__", None),
    "X8 merge_group 전용 트리거": ("__merge_group__", None),
    # --- 9라운드 적대 리뷰가 설계한 변이 (통제군 결함 때문에 전부 "잡음"으로
    # 보였을 뿐, 하네스를 고치면 3/18만 잡혔다) ---
    # 부류 A: CI 스텝을 **지우거나 무력화**한다. 감사기가 CI->로컬 한 방향만 봐서
    # 원리적으로 사각이었다.
    "R1 CI에서 vitest 스텝 삭제": (
        "frontend.yml",
        lambda text: text.replace(
            "      - name: admin frontend unit tests (vitest)\n", "", 1
        ).replace(
            "        run: npx --yes npm@12.0.1 -w "
            "packages/kor-travel-map-admin/frontend run test\n",
            "",
            1,
        ),
    ),
    "R2 integration 스텝에 continue-on-error": (
        "ci.yml",
        lambda text: text.replace(
            "      - name: Run integration tests",
            "      - continue-on-error: true\n      - name: Run integration tests",
            1,
        ),
    ),
    "R3 CI에서 admin eslint 스텝 삭제": (
        "frontend.yml",
        _drop_script_lines(
            "        run: npx --yes npm@12.0.1 -w packages/kor-travel-map-admin/frontend run lint"
        ),
    ),
    "R4 CI에서 mypy core 스텝 삭제": (
        "lint.yml",
        _drop_script_lines("        run: mypy --strict -p kortravelmap\n"),
    ),
    # 부류 B: 로컬 게이트를 **실패 불가**로 만든다.
    "R5 파이프로 종료코드 삼키기": (
        "__script__",
        lambda text: text.replace(
            "'python -m mypy --strict -p kortravelmap'",
            "'python -m mypy --strict -p kortravelmap | cat'",
            1,
        ),
    ),
    "R6 run_gate 실패 회계 제거": (
        "__script__",
        _drop_script_lines('FAILED+=("$name")'),
    ),
    "R7 최종 exit 1 -> exit 0": (
        "__script__",
        lambda text: text.replace("\nexit 1\n", "\nexit 0\n", 1),
    ),
    "R8 게이트 실행자 py -> echo": (
        "__script__",
        lambda text: text.replace('run_gate "pytest api" py', 'run_gate "pytest api" echo', 1),
    ),
    "R13 컨테이너 복사 실패를 다시 삼킴": (
        "__script__",
        lambda text: text.replace("exit 97", "exit 0", 1),
    ),
    # 부류 C: pytest 스위트를 **경로는 남긴 채** 플래그로 줄인다.
    "R9 pytest --ignore로 축소": (
        "__script__",
        lambda text: text.replace(
            "python -m pytest tests/unit tests/lint -q",
            "python -m pytest tests/unit tests/lint -q "
            "--ignore=tests/unit/test_gate_script_mirrors_ci.py",
            1,
        ),
    ),
    "R10 pytest -k로 축소": (
        "__script__",
        lambda text: text.replace(
            "python -m pytest tests/unit tests/lint -q",
            "python -m pytest tests/unit tests/lint -q -k dedup",
            1,
        ),
    ),
    # 부류 D: geo live 반증 장치 제거.
    "R11 geo live probe 제거": (
        "__script__",
        lambda text: text.replace("python scripts/geo_live_probe.py || exit 96; ", "", 1),
    ),
    "R11b geo live 사후 단언 제거": (
        "__script__",
        lambda text: text.replace(
            "python scripts/geo_live_probe.py --assert-ran /tmp/g4.log || exit 95; ", "", 1
        ),
    ),
    # 부류 E: 면제 접두 뒤에 `;`/`||`/블록 끝으로 진짜 게이트를 밀수한다.
    "R14 밀수(; 로 이어붙임)": (
        "frontend.yml",
        _insert_before_node_step(
            "      - name: fake gate\n        run: echo start; bash scripts/verify-r14.sh"
        ),
    ),
    "R15 밀수(|| 로 이어붙임)": (
        "frontend.yml",
        _insert_before_node_step(
            "      - name: fake gate\n        run: mv a b || bash scripts/verify-r15.sh"
        ),
    ),
    "R16 밀수(fixture 가드 블록 뒤)": (
        "ci.yml",
        lambda text: text.replace(
            _FIXTURE_BLOCK, _FIXTURE_BLOCK + "\n          bash scripts/verify-r16.sh", 1
        ),
    ),
    "M5 배열 트리거 워크플로": ("__array_trigger__", None),
    "M6 .yaml 확장자 워크플로": ("__yaml_ext__", None),
    "M8 composite action 스텝": (
        "frontend.yml",
        _insert_before_node_step(
            "      - name: fake gate\n        uses: ./.github/actions/fake-gate-m8"
        ),
    ),
}


def _run(
    label: str,
    target: str,
    mutate: Callable[[str], str] | None,
    *,
    quiet: bool = False,
) -> bool:
    if WORK.exists():
        shutil.rmtree(WORK)
    for name in ("tests", ".github", "scripts"):
        shutil.copytree(SRC / name, WORK / name)
    # 감사기가 읽는 **모든 것**을 사본에 넣는다. `pyproject.toml`이 빠져 있어
    # `test_documented_integration_coverage_threshold_matches_pyproject`가 변이와
    # 무관하게 FileNotFoundError로 죽었고, `caught = returncode != 0`이 **항상 참**이
    # 됐다 — 배터리가 출력하던 "32/32"는 측정이 아니라 상수였다(9라운드 적대 리뷰).
    shutil.copy2(SRC / "pyproject.toml", WORK / "pyproject.toml")

    if target == "__control__":
        pass
    elif target == "__new__":
        (WORK / ".github/workflows/security.yml").write_text(
            _NEW_WORKFLOW, encoding="utf-8"
        )
    elif target == "__array_trigger__":
        (WORK / ".github/workflows/security2.yml").write_text(
            _NEW_WORKFLOW.replace(
                "on:\n  pull_request:\n", "on: [push, pull_request]\n"
            ),
            encoding="utf-8",
        )
    elif target == "__jobs_comment__":
        (WORK / ".github/workflows/security4.yml").write_text(
            "# 이 워크플로의 jobs: 구성은 아래와 같다\n" + _NEW_WORKFLOW,
            encoding="utf-8",
        )
    elif target == "__merge_group__":
        (WORK / ".github/workflows/security5.yml").write_text(
            _NEW_WORKFLOW.replace("  pull_request:\n", "  merge_group:\n"),
            encoding="utf-8",
        )
    elif target == "__yaml_ext__":
        (WORK / ".github/workflows/security3.yaml").write_text(
            _NEW_WORKFLOW, encoding="utf-8"
        )
    else:
        assert mutate is not None
        path = (
            WORK / "scripts/verify-all-gates.sh"
            if target == "__script__"
            else WORK / ".github/workflows" / target
        )
        original = path.read_text(encoding="utf-8")
        mutated = mutate(original)
        if mutated == original:
            print(f"변이 미적용!! {label} — 대상 문자열이 바뀌었다")
            return False
        path.write_text(mutated, encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            "-B",
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:randomly",
            "tests/unit/test_gate_script_mirrors_ci.py",
        ],
        cwd=WORK,
        capture_output=True,
        text=True,
        check=False,
    )
    caught = result.returncode != 0
    if not quiet:
        print(f"{'잡음  ' if caught else '생존!!'} {label}")
    return caught


def _control_group_is_clean() -> bool:
    """변이를 **하나도 심지 않은** 사본에서 감사기가 통과하는지 본다.

    이것이 없으면 배터리는 무의미하다. 하네스가 깨져 있으면 모든 변이가 "잡음"으로
    보이고, 그 100%는 감사기가 무엇을 하든 나오는 숫자다. 실제로 그 상태의 "32/32"를
    머지 근거로 인용했다 — 검증 장치 안에, 이 저장소가 여덟 번 반려된 것과 똑같은
    결함(선언한 검증 범위 != 실제 검증 범위)이 들어 있었다.
    """

    clean = not _run("[통제군]", "__control__", None, quiet=True)
    print(
        "[통제군] 변이 없는 사본에서 감사기: "
        + ("통과(정상)" if clean else "실패(하네스 고장)")
    )
    return clean


def main() -> int:
    if not _control_group_is_clean():
        print(
            "\n하네스가 깨졌다 — 변이 없이도 감사기가 실패한다. 이 상태의 검출률은 "
            "감사기와 무관한 상수이므로 아래 결과는 근거가 되지 못한다."
        )
        return 1
    results = [_run(label, *spec) for label, spec in MUTATIONS.items()]
    print(f"\n{sum(results)}/{len(results)} 변이 검출")
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
