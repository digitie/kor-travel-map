"""삭제 게이트가 **아카이브까지** 보는지를, 실제로 빨갛게 만들어 확인한다.

`scripts/check_task_ledger_deletions.py`는 오래 `docs/archive/`를 한 번도 읽지 않았다
(2026-09-16까지 소스에 "archive"가 0번 등장). 그래서 원장에서 아카이브로 옮긴 항목은
그 순간부터 감시 밖이었고, `docs/archive/tasks-acceptance-m05.md`의 P1~P5 다섯 개가
정확히 그 상태로 남아 있었다 — 다음 PR이 통째로 지워도 게이트는 조용했다.

**이 파일은 이름이 아니라 효과에 결박한다.** 게이트 소스에 "archive"가 있는지 세지
않는다(그런 검사는 감시 목록을 비워도 초록이다). 대신 임시 git 저장소를 만들어 실제로
지워 보고, 게이트가 exit 1을 내는지 본다. 감시에서 아카이브를 빼면 1번 검사가, 근거
판정을 다시 부분일치로 되돌리면 3·5번 검사가 초록이 되면서 **여기가 실패한다.**

게이트는 커밋된 base↔HEAD를 비교하므로 각 시나리오는 반드시 커밋까지 해야 한다 —
작업 트리에만 있는 편집은 게이트에 보이지 않는다.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DETECTOR = REPO_ROOT / "scripts" / "check_task_ledger_deletions.py"
PARSER = REPO_ROOT / "scripts" / "task_ledger_lint.py"

ARCHIVE_PATH = "docs/archive/tasks-acceptance-old.md"

TASKS = """# 활성 backlog

- [ ] T-FIX-01 — fixture용 열린 task
"""

DONE = """# 완료 원장

- [x] T-OLD-01 — 이전에 닫힌 task. 무엇이 어떻게 완료됐는지는 여기가 소유한다.
"""

ACCEPTANCE = """# 해제 조건

## T-FIX-01

- [ ] A1. 첫 기준 — 활성 원장이 소유한다.
- [ ] A2. 둘째 기준.
"""

ACCEPTANCE_WITHOUT_A1 = """# 해제 조건

## T-FIX-01

- [ ] A2. 둘째 기준.
"""

ARCHIVE = """# T-OLD-01 (archived)

- [x] P1. 아카이브가 소유한 기준.
- [x] P2. 아카이브가 소유한 또 하나의 기준.
"""

ARCHIVE_WITHOUT_P1 = """# T-OLD-01 (archived)

- [x] P2. 아카이브가 소유한 또 하나의 기준.
"""


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return result.stdout


def _commit(repo: Path, message: str) -> None:
    _git(repo, "add", "-A")
    _git(
        repo,
        "-c",
        "user.email=ledger-gate@test.invalid",
        "-c",
        "user.name=ledger gate test",
        "-c",
        "commit.gpgsign=false",
        "commit",
        "-q",
        "-m",
        message,
    )


def _make_repo(tmp_path: Path) -> tuple[Path, str]:
    """base 커밋까지 끝낸 임시 원장 저장소와 그 base SHA."""

    repo = tmp_path / "ledger"
    (repo / "docs" / "archive").mkdir(parents=True)
    (repo / "scripts").mkdir()
    (repo / "docs" / "tasks.md").write_text(TASKS, encoding="utf-8")
    (repo / "docs" / "tasks-done.md").write_text(DONE, encoding="utf-8")
    (repo / "docs" / "tasks-acceptance.md").write_text(ACCEPTANCE, encoding="utf-8")
    (repo / ARCHIVE_PATH).write_text(ARCHIVE, encoding="utf-8")
    shutil.copy(DETECTOR, repo / "scripts" / DETECTOR.name)
    shutil.copy(PARSER, repo / "scripts" / PARSER.name)
    _git(repo, "init", "-q", "-b", "main")
    _commit(repo, "base")
    return repo, _git(repo, "rev-parse", "HEAD").strip()


def _gate(repo: Path, base: str) -> subprocess.CompletedProcess[str]:
    """게이트를 그 저장소 안에서 실행한다 — 한국어 메시지 때문에 stdio는 utf-8 고정."""

    return subprocess.run(
        [sys.executable, f"scripts/{DETECTOR.name}", base],
        cwd=repo,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )


def test_deleting_an_archived_criterion_is_caught(tmp_path: Path) -> None:
    """아카이브 안의 기준을 지우면 근거 없이는 통과하지 못한다.

    감시 집합에서 아카이브를 빼는 순간 이 검사가 초록이 된다 — 그것이 2026-09-16
    이전의 상태였고, 그때 P1~P5가 아무에게도 보이지 않았다.
    """
    repo, base = _make_repo(tmp_path)
    (repo / ARCHIVE_PATH).write_text(ARCHIVE_WITHOUT_P1, encoding="utf-8")
    _commit(repo, "아카이브 기준 삭제")

    result = _gate(repo, base)
    assert result.returncode == 1, f"게이트가 조용했다: {result.stdout} {result.stderr}"
    assert "P1" in result.stderr
    assert ARCHIVE_PATH in result.stderr


def test_deleting_the_whole_archive_file_is_caught(tmp_path: Path) -> None:
    """파일째 지우는 것도 같은 삭제다 — 감시 목록을 base 쪽에서도 세우는 이유."""
    repo, base = _make_repo(tmp_path)
    (repo / ARCHIVE_PATH).unlink()
    _commit(repo, "아카이브 파일 삭제")

    result = _gate(repo, base)
    assert result.returncode == 1, f"게이트가 조용했다: {result.stdout} {result.stderr}"
    assert "P1" in result.stderr
    assert "P2" in result.stderr


def test_moving_a_criterion_into_a_new_archive_file_is_accepted(tmp_path: Path) -> None:
    """원장 → **이번 변경에서 새로 만든** 아카이브 이동은 삭제가 아니다.

    이것이 오탐 쪽 경계다. 새 분리본을 HEAD 목록에서도 세우지 않으면 정당한 분리가
    전부 빨개지고, 그러면 게이트를 끄는 쪽이 합리적인 선택이 돼 버린다.
    """
    repo, base = _make_repo(tmp_path)
    (repo / "docs" / "tasks-acceptance.md").write_text(
        ACCEPTANCE_WITHOUT_A1, encoding="utf-8"
    )
    (repo / "docs" / "archive" / "tasks-acceptance-fix01.md").write_text(
        "# T-FIX-01 (archived)\n\n- [ ] A1. 첫 기준 — 이제 아카이브가 소유한다.\n",
        encoding="utf-8",
    )
    _commit(repo, "acceptance → 새 아카이브 분리")

    result = _gate(repo, base)
    assert result.returncode == 0, f"정당한 이관이 막혔다: {result.stderr}"


def test_prose_mentioning_the_id_is_not_a_justification(tmp_path: Path) -> None:
    """산문 속 맨 `A1`은 근거가 아니다 — 두 글자 ID는 우연히 맞는다.

    종전 판정(`item.any_id not in added_text`)에서는 이 시나리오가 초록이었다.
    """
    repo, base = _make_repo(tmp_path)
    (repo / "docs" / "tasks-acceptance.md").write_text(
        ACCEPTANCE_WITHOUT_A1 + "\nA1 관련 논의는 다른 판에서 이어간다.\n",
        encoding="utf-8",
    )
    _commit(repo, "A1 삭제 + 산문 언급")

    result = _gate(repo, base)
    assert result.returncode == 1, f"산문이 근거로 통과했다: {result.stdout}"
    assert "A1" in result.stderr


def test_a_same_id_checkbox_in_the_done_ledger_is_a_justification(tmp_path: Path) -> None:
    """실제 이관 — 같은 ID의 체크박스가 추가되면 통과한다.

    엔트리 본문이 상위 task ID를 함께 적는 것이 보통이다. `any_id`는 task ID를
    우선하므로 근거 판정이 대표 ID만 보면 이 정상 문장이 반려된다 — 이 fixture가
    실제로 그렇게 실패해서 `_item_ids`가 생겼다. 문구에서 `T-FIX-01`을 빼면
    검사가 약해진다.
    """
    repo, base = _make_repo(tmp_path)
    (repo / "docs" / "tasks-acceptance.md").write_text(
        ACCEPTANCE_WITHOUT_A1, encoding="utf-8"
    )
    (repo / "docs" / "tasks-done.md").write_text(
        DONE + "\n- [x] A1 — T-FIX-01의 첫 기준을 완료 원장으로 귀속했다.\n",
        encoding="utf-8",
    )
    _commit(repo, "A1 → done 이관")

    result = _gate(repo, base)
    assert result.returncode == 0, f"정당한 이관이 막혔다: {result.stderr}"


def test_a_fenced_checkbox_is_not_a_justification(tmp_path: Path) -> None:
    """코드 fence 안의 체크박스는 항목이 아니다.

    diff는 줄 단위라 그 줄이 fence 안이었는지 모른다. 그래서 게이트는 같은 ID가 HEAD
    파일에서도 fence 밖 항목으로 읽히는지 함께 본다 — 예시 블록에 `- [x] A1`을 적어
    두는 우회가 여기서 막힌다.
    """
    repo, base = _make_repo(tmp_path)
    (repo / "docs" / "tasks-acceptance.md").write_text(
        ACCEPTANCE_WITHOUT_A1, encoding="utf-8"
    )
    (repo / "docs" / "tasks-done.md").write_text(
        DONE + "\n표기 예시:\n\n```md\n- [x] A1 — 예시일 뿐 항목이 아니다\n```\n",
        encoding="utf-8",
    )
    _commit(repo, "A1 삭제 + fence 안 가짜 체크박스")

    result = _gate(repo, base)
    assert result.returncode == 1, f"fence 안 표기가 근거로 통과했다: {result.stdout}"


def test_a_change_that_touches_no_ledger_stays_green(tmp_path: Path) -> None:
    """원장을 건드리지 않는 변경은 조용해야 한다 — 게이트는 PR을 막는 물건이다."""
    repo, base = _make_repo(tmp_path)
    (repo / "README.md").write_text("관계없는 변경\n", encoding="utf-8")
    _commit(repo, "무관한 변경")

    result = _gate(repo, base)
    assert result.returncode == 0, f"무관한 변경이 막혔다: {result.stderr}"
