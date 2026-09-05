"""D2 lane이 적재하는 Python 파일이 전부 `mypy --strict` 아래에 있는지 결박한다.

이 lane은 프로덕션 PostgreSQL에 직접 쓰고, 프로덕션 API 이미지로 컨테이너를
만들어 fixture DSN을 주입한다. 그런데 2026-09-05까지 CI mypy는 `kortravelmap` 세
패키지만 봤다. 그 사이 `await`가 속성 접근 뒤에 묶여 coroutine에 `.mappings()`를
부르는 결함이 살아남았고, **배포 스택 seed 도중에야** 드러났다. mypy는 같은 결함을
`Maybe you forgot to use "await"?`로 즉시 말한다(실측).

한 파일만 편입하면 나머지에 경계를 설명할 수 없다. 그래서 목록을 손으로 적지 않고
**러너가 적재하는 파일에서 유도**한다 — `run-admin-feature-live-acceptance.sh`가
`readonly <NAME>="$SCRIPT_DIR/<file>.py"`로 선언하는 것이 곧 설치 스냅샷이 담는
것이다. lane에 파일이 늘면 이 게이트가 mypy 스텝도 함께 늘라고 말한다
(AGENTS.md DO NOT 15: 유도 → 결박 → 탐지).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[2]
_RUNNER = _ROOT / "scripts" / "run-admin-feature-live-acceptance.sh"
_WORKFLOW = _ROOT / ".github" / "workflows" / "lint.yml"
_GATES = _ROOT / "scripts" / "verify-all-gates.sh"

#: `readonly SUPERVISOR="$SCRIPT_DIR/admin_feature_live_supervisor.py"`
_LOADED = re.compile(
    r'^readonly\s+\w+="\$SCRIPT_DIR/(?P<name>[\w.-]+\.py)"', re.MULTILINE
)


def _lane_modules() -> list[str]:
    """러너가 적재하는 Python 파일을 소스에서 유도한다."""

    return sorted(
        {
            f"scripts/{match.group('name')}"
            for match in _LOADED.finditer(_RUNNER.read_text(encoding="utf-8"))
        }
    )


def test_the_gate_finds_the_lane_modules() -> None:
    """유도가 실제로 파일을 찾았는지부터 본다 — 비면 아래 단언이 공허하다."""

    modules = _lane_modules()
    assert len(modules) >= 3, (
        f"러너가 적재하는 Python 파일을 {len(modules)}개만 찾았다 — 패턴을 의심하라. "
        f"찾은 것={modules}"
    )
    for module in modules:
        assert (_ROOT / module).is_file(), f"{module}이 실재하지 않는다"


def test_every_lane_module_is_under_mypy_strict_in_ci() -> None:
    """lane이 적재하는 모든 모듈이 CI의 `mypy --strict` 인자에 있어야 한다."""

    workflow = _WORKFLOW.read_text(encoding="utf-8")
    missing = [module for module in _lane_modules() if module not in workflow]
    assert missing == [], (
        f"D2 lane 모듈이 CI mypy 밖에 있다: {missing}. "
        "이 코드는 프로덕션 DB를 바꾼다 — 타입 검사 밖에 두지 마라. "
        f"`{_WORKFLOW.relative_to(_ROOT).as_posix()}`의 mypy 스텝에 더해라."
    )


def test_the_local_gate_script_mirrors_the_same_module_set() -> None:
    """로컬 게이트 스크립트도 같은 집합을 돌려야 한다."""

    gates = _GATES.read_text(encoding="utf-8")
    missing = [module for module in _lane_modules() if module not in gates]
    assert missing == [], (
        f"D2 lane 모듈이 로컬 게이트 밖에 있다: {missing}. "
        f"`{_GATES.relative_to(_ROOT).as_posix()}`의 mypy 게이트에 더해라 — "
        "CI와 갈라지면 로컬 green이 근거가 되지 못한다."
    )
