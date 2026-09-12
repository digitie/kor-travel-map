"""워크플로의 `run:` 블록에 **인자가 명령으로 떨어져 나간 줄**이 없는지 결박한다.

2026-09-13에 정확히 그 일이 났다. mypy 스텝에 파일 하나를 더하면서 **앞줄의 줄
이음을 빠뜨렸고**, 그 결과

    mypy --strict \\
      scripts/admin_feature_live_fixture.py \\
      scripts/admin_feature_live_state.py \\
      scripts/admin_feature_live_supervisor.py
      scripts/dagster_run_completion_gate.py      # ← 별개의 명령이 됐다

셸은 마지막 줄을 **실행할 프로그램**으로 읽었고 `Permission denied`(exit 126)로
죽었다. 더 나쁜 것은 실패가 아니라 그 사이의 초록이다 — 이 파일이 mypy 인자였다면
타입 검사를 받았을 텐데, 인자가 아닌 동안에도 "워크플로에 이름이 있다"고 세는 검사는
초록이었다. 이름이 적혀 있는 것과 검사를 받는 것은 다른 사실이다.

여기서 잡는 것은 그 **부류**다: `run:` 블록의 논리적 한 줄이 `.py` 경로로 시작하면
그것은 인자가 떨어져 나온 것이다. 이 저장소의 CI는 Python 파일을 언제나 해석기나
도구의 인자로 준다(`python x.py`, `mypy --strict x.py`) — 직접 실행하지 않는다.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[2]
_WORKFLOWS = _ROOT / ".github" / "workflows"

#: `\` + 개행 + 들여쓰기 = 같은 명령의 계속.
_CONTINUATION = re.compile("\\\\\n\\s*")

#: 논리적 한 줄의 첫 토큰이 `.py`로 끝나는가. `./x.py`는 의도적 직접 실행이므로 뺀다.
_LEADING_PY = re.compile(r"^(?!\./)[\w./-]+\.py(\s|$)")


def _run_blocks() -> list[tuple[str, str, str]]:
    """(워크플로 파일명, 스텝 이름, run 본문)을 YAML에서 유도한다."""

    blocks: list[tuple[str, str, str]] = []
    for path in sorted(_WORKFLOWS.glob("*.yml")):
        document: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
        for job in (document.get("jobs") or {}).values():
            for step in job.get("steps") or ():
                run = step.get("run")
                if isinstance(run, str):
                    blocks.append((path.name, step.get("name") or "(이름 없음)", run))
    return blocks


def test_the_scan_actually_finds_run_blocks() -> None:
    """유도의 전제. 비면 아래 단언이 무엇도 재지 못한다."""

    blocks = _run_blocks()
    assert len(blocks) >= 10, (
        f"`run:` 블록을 {len(blocks)}개만 찾았다 — YAML 구조가 바뀌었는지 의심하라."
    )
    assert any("mypy --strict" in run for _, _, run in blocks), (
        "`mypy --strict` 스텝을 찾지 못했다 — 이 검사가 겨냥한 자리가 사라졌다."
    )


def test_no_run_block_line_starts_with_a_python_file() -> None:
    """인자가 명령으로 떨어져 나간 줄이 없어야 한다."""

    dangling: list[str] = []
    for name, step, run in _run_blocks():
        for line in _CONTINUATION.sub(" ", run).splitlines():
            stripped = line.strip()
            if _LEADING_PY.match(stripped):
                dangling.append(f"{name} · {step} · {stripped}")

    assert dangling == [], (
        "`run:` 블록에서 Python 파일이 **명령 자리**에 있다 — 앞줄의 줄 이음(\\)이 "
        "빠졌을 가능성이 높다. 셸은 그것을 실행할 프로그램으로 읽고, 그 파일은 "
        "원래 받을 검사를 받지 못한다:\n  " + "\n  ".join(dangling)
    )
