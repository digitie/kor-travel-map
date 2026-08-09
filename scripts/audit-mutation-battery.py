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

SRC = Path("/src")
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
    "M5 배열 트리거 워크플로": ("__array_trigger__", None),
    "M6 .yaml 확장자 워크플로": ("__yaml_ext__", None),
    "M8 composite action 스텝": (
        "frontend.yml",
        _insert_before_node_step(
            "      - name: fake gate\n        uses: ./.github/actions/fake-gate-m8"
        ),
    ),
}


def _run(label: str, target: str, mutate: Callable[[str], str] | None) -> bool:
    if WORK.exists():
        shutil.rmtree(WORK)
    for name in ("tests", ".github", "scripts"):
        shutil.copytree(SRC / name, WORK / name)

    if target == "__new__":
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
    print(f"{'잡음  ' if caught else '생존!!'} {label}")
    return caught


def main() -> int:
    results = [_run(label, *spec) for label, spec in MUTATIONS.items()]
    print(f"\n{sum(results)}/{len(results)} 변이 검출")
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
