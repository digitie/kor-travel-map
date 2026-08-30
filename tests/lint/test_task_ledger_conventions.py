"""task 원장 규약 게이트 — 해제 조건이 다시 사라지지 않게 한다.

2026-08-27 커밋 ``6d671ef1``(``docs: flatten active task order``)이 ``docs/tasks.md``를
991줄 → 30줄로 줄이면서, 완료 항목을 ``tasks-done.md``로 옮긴 것이 아니라 **아직 열려
있는 항목의 acceptance criteria를 지웠다.** 같은 커밋은 ``tasks-done.md``를 건드리지
않았으므로 그 기준은 어디로도 이관되지 않았다.

다음 날 ``b3bbd3a3``이 ``T-VN-FINAL-REBUILD``를 ``[ ]`` → ``[x]``로 바꿨다. 그 task의
해제 조건 B1~B4는 삭제 직전 **전부 미체크**였다. 조건이 충족된 것이 아니라 조건 자체가
문서에서 사라진 뒤 완료 처리된 것이고, 그 잘못된 완료가 ``T-VN-41F1D-D1``/``-E``/``-D2``
→ ``T-VN-41C`` 네 하위 task에 "배리어가 열렸다"는 형식적 근거를 만들어 줬다.

본 게이트는 그 경로를 막는다.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TASKS = REPO_ROOT / "docs" / "tasks.md"
TASKS_DONE = REPO_ROOT / "docs" / "tasks-done.md"
ACCEPTANCE = REPO_ROOT / "docs" / "tasks-acceptance.md"

_ITEM_RE = re.compile(r"^- \[(?P<marker>.)\] (?P<task>T-[A-Z0-9-]+)", re.MULTILINE)
_ALLOWED_MARKERS = frozenset({" ", "~"})
"""``docs/tasks-rule.md`` §4는 ``[ ]``·``[x]``·``[~]`` 셋을 정의한다.

활성 파일에는 ``[x]``가 올 수 없으므로(아래 참조) 남는 것은 둘뿐이다. 규약에 없는
``[/]``가 한때 6개 항목에 쓰였다 — 정의되지 않은 마커는 읽는 사람마다 다르게 해석한다.
"""


def _items() -> list[tuple[str, str]]:
    text = TASKS.read_text(encoding="utf-8")
    return [(m.group("marker"), m.group("task")) for m in _ITEM_RE.finditer(text)]


def test_active_backlog_uses_defined_markers_only() -> None:
    """``tasks.md``는 ``tasks-rule.md`` §4가 정의한 마커만 쓴다."""
    items = _items()
    assert items, "docs/tasks.md에서 backlog 항목을 하나도 읽지 못했다"
    undefined = sorted(
        {f"[{marker}] {task}" for marker, task in items if marker not in _ALLOWED_MARKERS}
    )
    assert not undefined, (
        "docs/tasks-rule.md §4에 없는 status 마커다 — "
        f"미완료는 `[ ]`, 부분완료는 `[~]`를 쓸 것: {undefined}"
    )


def test_completed_items_live_in_the_done_ledger() -> None:
    """완료 항목은 활성 파일이 아니라 ``tasks-done.md``가 소유한다.

    ``tasks.md`` 서문은 "완료되지 않은 작업만 나열한다"이고 ``tasks-rule.md`` §4는
    ``[x]``를 ``tasks-done.md`` 소관으로 정의한다. 그런데 두 항목이 완료 원장에
    엔트리 없이 활성 파일에서만 ``[x]``로 표시된 적이 있다. 완료 원장을 거치지 않는
    완료 표시는 아무도 검토하지 않는다.
    """
    completed = sorted({task for marker, task in _items() if marker == "x"})
    assert not completed, (
        "docs/tasks.md에 완료 표시가 남아 있다 — 근거와 함께 docs/tasks-done.md로 "
        f"이관하거나, 해제 조건이 실제로 충족되지 않았다면 열린 상태로 되돌릴 것: {completed}"
    )


def test_every_open_task_has_recorded_acceptance_criteria() -> None:
    """열린 모든 task의 해제 조건이 ``tasks-acceptance.md``에 있어야 한다.

    이것이 본 게이트의 본체다. 평면화가 다시 일어나도 판정 근거는 남는다 — 그리고
    새 task를 열면서 해제 조건을 적지 않는 것도 여기서 막힌다. 조건 없는 task는
    "완료"를 누가 어떻게 판정하는지 아무도 모른다.
    """
    assert ACCEPTANCE.exists(), (
        "docs/tasks-acceptance.md가 없다 — 열린 task의 해제 조건 정본이다"
    )
    criteria = ACCEPTANCE.read_text(encoding="utf-8")
    open_tasks = sorted({task for marker, task in _items()})

    # 세부 task는 상위 task 섹션이 조건을 소유할 수 있다(T-VN-H49-PINVI → T-VN-H49).
    def covered(task: str) -> bool:
        if task in criteria:
            return True
        parent = task.rsplit("-", 1)[0]
        return parent != task and parent in criteria

    missing = [task for task in open_tasks if not covered(task)]
    assert not missing, (
        "해제 조건이 기록되지 않은 열린 task다 — docs/tasks-acceptance.md에 "
        f"판정 근거를 적을 것(무엇이 참이면 닫히는가): {missing}"
    )


def test_done_ledger_is_not_empty() -> None:
    """완료 원장이 실제로 존재하고 엔트리를 담고 있어야 한다.

    위 두 검사는 "완료를 원장으로 옮겨라"라고만 말한다. 원장 자체가 비거나 사라지면
    그 지시가 무의미해지므로 최소한의 존재 확인을 둔다.
    """
    assert TASKS_DONE.exists(), "docs/tasks-done.md가 없다"
    assert "- [x]" in TASKS_DONE.read_text(encoding="utf-8"), (
        "docs/tasks-done.md에 완료 엔트리가 하나도 없다"
    )
