"""아카이브 이동이 "근거 없는 삭제"로 판정되지 않게 한다.

`scripts/check_task_ledger_deletions.py`의 규칙 2는 acceptance 체크박스 항목이
사라지면 **같은 변경의 추가 줄** 어딘가에 그 ID가 있어야 한다고 요구한다. 좋은
규칙이지만 감시 대상이 세 파일(`tasks.md`/`tasks-done.md`/`tasks-acceptance.md`)
뿐이었다.

`docs/tasks-rule.md` §8은 live 문서가 읽기 한도를 넘으면 **`docs/archive/`로 분리**
하라고 요구한다. 그 둘이 부딪힌다 — 규약대로 절을 아카이브로 옮기면 게이트가 그
이동 전부를 삭제로 본다. 2026-09-13 4차 적대 리뷰가 실측으로 잡았다(37건).

아카이브 이동은 **삭제가 아니라 이관**이다. 그래서 게이트가 `docs/archive/`의 추가
줄도 근거로 센다. 여기서는 그 성질을 계약으로 박는다 — 스크립트를 직접 import해
가짜 diff로 판정시킨다(실제 git 상태에 의존하지 않는다).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS = _ROOT / "scripts"


def _load_gate() -> Any:
    sys.path.insert(0, str(_SCRIPTS))
    spec = importlib.util.spec_from_file_location(
        "_check_task_ledger_deletions", _SCRIPTS / "check_task_ledger_deletions.py"
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_gate_reads_the_archive_as_a_deletion_reason() -> None:
    """규칙 2의 근거 텍스트에 `docs/archive/`의 추가 줄이 들어간다.

    이것이 없으면 규약 §8이 시키는 분리가 CI에서 막힌다.
    """

    gate = _load_gate()
    assert gate.ARCHIVE == "docs/archive"
    assert hasattr(gate, "_added_archive_lines")


def test_the_archive_lines_come_from_a_directory_not_a_filename(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """파일명을 박으면 **다음** 분리에서 같은 구멍이 다시 열린다.

    디렉터리로 diff를 떠야 새 아카이브 파일이 자동으로 포함된다 — 여기서는
    `_added_diff_lines`가 받은 경로가 디렉터리인지 본다.
    """

    gate = _load_gate()
    seen: list[str] = []

    def _fake(base: str, path: str) -> list[str]:
        seen.append(path)
        return []

    monkeypatch.setattr(gate, "_added_diff_lines", _fake)
    gate._added_archive_lines("origin/main")

    assert seen == ["docs/archive"], (
        f"아카이브 근거를 {seen}에서 읽는다 — 디렉터리 하나로 떠야 새 아카이브 "
        "파일이 자동으로 포함된다."
    )


def test_moving_a_section_to_the_archive_is_not_a_deletion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """**효과 결박** — 아카이브로 옮긴 ID가 실패로 잡히지 않는다.

    가짜 diff를 물려 판정만 본다. 이 테스트가 빨개지는 변이는 하나뿐이다:
    `added_text`에서 아카이브 줄을 빼는 것.
    """

    gate = _load_gate()
    base_acceptance = "- [x] T-GONE-EXAMPLE — 옮겨질 절의 체크박스\n"

    monkeypatch.setattr(gate, "_git", lambda *args: str(_ROOT) + "\n")
    monkeypatch.setattr(gate, "_resolve_base", lambda candidates: "base-ref")
    monkeypatch.setattr(
        gate, "_file_at", lambda ref, path: base_acceptance if path == gate.ACCEPTANCE else ""
    )
    monkeypatch.setattr(gate, "_added_done_entries", lambda base: {})

    def _read_head(self: Path, *args: Any, **kwargs: Any) -> str:
        return ""

    monkeypatch.setattr(Path, "read_text", _read_head)
    monkeypatch.setattr(Path, "exists", lambda self: True)

    added: dict[str, list[str]] = {
        gate.ACCEPTANCE: [],
        gate.TASKS: [],
        gate.DONE: [],
        gate.ARCHIVE: ["- [x] T-GONE-EXAMPLE — 옮겨질 절의 체크박스"],
    }
    monkeypatch.setattr(gate, "_added_diff_lines", lambda base, path: added.get(path, []))
    monkeypatch.setattr(sys, "argv", ["gate", "", "origin/main"])

    assert gate.main() == 0, (
        "아카이브로 옮긴 절을 삭제로 판정했다 — 규약 §8이 시키는 분리가 CI에서 막힌다."
    )

    # 대조군: 아무 데도 없으면 여전히 실패해야 한다(이 검사가 항진명제가 아님).
    added[gate.ARCHIVE] = []
    assert gate.main() == 1, (
        "근거 없는 삭제를 통과시켰다 — 아카이브 예외가 게이트를 통째로 무력화했다."
    )
