"""삭제 게이트가 **살아 있는 해제 조문**을 본다 — 인용된 제목이 아니라.

2026-09-16 적대 리뷰가 게이트의 두 사각지대를 실측으로 보였다.

1. **fence 짝이 깨져 있었다.** `3b11c9757`(#1200)이 새 절 셋을 아직 닫히지 않은
   `` ```markdown `` 인용 블록 **안쪽**에 끼워 넣었고, 그 뒤 모든 신설 절이 같은
   블록 안으로 들어갔다. 실측: 3,083줄 중 **2,045줄(66%)**과 `## ` 제목 44개 중
   **16개**가 파서에게 보이지 않았다 — `T-VN-LEDGER-ARCHIVE`·`T-VN-QUEUE-QUOTA`·
   `T-VN-KREX-TPS-FANOUT`이 그 안에 있었다.
2. **조문에는 ID가 없다.** 해제 조건은 `## T-XXX` 아래 `1. [x]` 번호 목록으로
   적히는데 종전 파서는 `- [ ]` 대시 항목만 봤고, ID는 줄 텍스트 안에서만 찾았다.
   ID는 절 제목에 있다.

둘이 겹쳐서 게이트가 실제로 세고 있던 것은 **fence 안의 인용된 task 제목**이었다.
지켜야 할 것은 못 보고 지키면 안 되는 것을 보고 있었다 — 정확히 거꾸로다.

**이 파일은 이름이 아니라 효과에 결박한다.** 게이트 소스에 무슨 단어가 있는지 세지
않는다. 임시 git 저장소에서 실제로 조문을 지워 보고 exit 1을 확인하고, 실제 원장에
대고 조문 식별자가 실재하는지 확인한다. 변이 실측(2026-09-16)으로 각 조각이
정말 결박되어 있는지도 함께 쟀다 — 조각을 하나씩 빼면 아래가 빨개진다.

    빼는 조각                                  (a)조문 삭제   base→HEAD 전이
    `clause_id`                                초록(맹목)     초록
    번호 목록 지원(두 정규식 모두)              초록(맹목)     초록
    절 귀속(`section_task_id` 자체)             초록(맹목)     빨강 8건 오탐
    게이트의 `section_task_ids` 층              빨강           빨강 5건 오탐
    fence 복구                                  초록(맹목)     초록
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DETECTOR = REPO_ROOT / "scripts" / "check_task_ledger_deletions.py"
PARSER = REPO_ROOT / "scripts" / "task_ledger_lint.py"
LEDGER = REPO_ROOT / "docs" / "tasks-acceptance.md"

sys.path.insert(0, str(REPO_ROOT / "scripts"))

from task_ledger_lint import (  # noqa: E402
    MalformedCheckboxError,
    parse_checkboxes,
    section_task_ids,
    strip_non_content,
    watch_ids,
)

# ── 1층: 파싱 규약 자체 ────────────────────────────────────────────────

_CLAUSES = """# 원장 (fixture)

## T-RIGHT

**무엇이 참이면 닫히는가.**

1. [x] 첫 조문 — 자기 ID가 없다. 절에서 물려받아야 한다.
2. [ ] 둘째 조문. 이 줄을 지우는 것이 6d671ef1이 한 일이다.

## T-OTHER

1. [ ] 다른 절의 첫 조문 — 번호가 같아도 다른 조문이다.
"""


def test_a_numbered_clause_inherits_its_section_and_keeps_its_number() -> None:
    """번호 조문은 절 ID를 물려받고, 목록 번호로 자기 식별자를 갖는다."""
    items = parse_checkboxes(_CLAUSES, source="<fixture>")
    assert [item.clause_number for item in items] == [1, 2, 1]
    assert [item.section_task_id for item in items] == ["T-RIGHT", "T-RIGHT", "T-OTHER"]
    assert [item.clause_id for item in items] == ["T-RIGHT#1", "T-RIGHT#2", "T-OTHER#1"]

    # 줄에 적힌 ID는 없다 — 물려받은 값을 `task_id`에 밀어 넣지 않는다는 뜻이다.
    assert {item.task_id for item in items} == {None}

    # 절마다 번호가 1부터 다시 시작해도 식별자는 충돌하지 않는다.
    assert items[0].clause_id != items[2].clause_id
    assert watch_ids(items[1]) == {"T-RIGHT", "T-RIGHT#2"}


def test_clause_identity_survives_a_wording_change_but_not_a_deletion() -> None:
    """문구를 고치거나 `[ ]`→`[x]`로 바꾸는 것은 삭제가 아니다.

    조문 식별자를 **순서**로 매기면 이 성질이 깨진다(앞에 하나 끼우면 뒤가 전부
    다른 이름이 된다). 문서에 이미 적힌 번호를 쓰는 이유가 그것이다.
    """
    edited = _CLAUSES.replace("2. [ ] 둘째 조문.", "2. [x] 둘째 조문을 다시 썼다.")
    before = {i.clause_id for i in parse_checkboxes(_CLAUSES, source="<f>")}
    after = {i.clause_id for i in parse_checkboxes(edited, source="<f>")}
    assert before == after == {"T-RIGHT#1", "T-RIGHT#2", "T-OTHER#1"}

    deleted = _CLAUSES.replace("2. [ ] 둘째 조문. 이 줄을 지우는 것이 6d671ef1이 한 일이다.\n", "")
    assert {i.clause_id for i in parse_checkboxes(deleted, source="<f>")} == {
        "T-RIGHT#1",
        "T-OTHER#1",
    }


_FENCED_TITLE = """# 원장 (fixture)

## T-LIVE

```markdown
- [x] T-QUOTED — 인용된 제목이다. 항목이 아니다.

## T-QUOTED-SECTION

- [ ] Q1 이 줄도 인용문 안이다.
```

1. [ ] 살아 있는 조문. 자기 텍스트에는 ID가 한 글자도 없다.
"""


def test_a_quoted_title_inside_a_fence_is_neither_an_item_nor_a_section() -> None:
    """fence 안의 인용 제목은 항목도 아니고 귀속 문맥도 바꾸지 않는다.

    두 번째 단언이 핵심이다. 제목을 fence 무시하고 읽으면, **인용문**이 그 뒤에
    오는 살아 있는 조문의 소유자를 정하게 된다 — 원장 관례가 완료된 task의 원문을
    인용 블록으로 보존하므로, 그렇게 되면 닫힌 task가 열린 조문을 소유한다.
    """
    items = parse_checkboxes(_FENCED_TITLE, source="<fixture>")
    assert len(items) == 1, f"fence 안의 줄이 항목으로 셌다: {[i.text for i in items]}"
    assert items[0].task_id is None
    assert items[0].section_task_id == "T-LIVE"
    assert items[0].clause_id == "T-LIVE#1"
    assert section_task_ids(_FENCED_TITLE) == {"T-LIVE"}


def test_a_malformed_numbered_checkbox_is_an_error_too() -> None:
    """`1. [y]`도 `- [y]`와 같은 오류다 — 두 정규식을 대칭으로 넓혔기 때문이다.

    `CHECKBOX_LINE`만 넓히면 `1. [y]`가 정식도 아니고 "시도"도 아닌 것이 되어
    조용히 사라진다. 그것이 바로 malformed fail-closed가 막으려던 우회다.
    """
    with pytest.raises(MalformedCheckboxError):
        parse_checkboxes("## T-X\n\n1. [y] 규약에 없는 상태\n", source="<fixture>")
    with pytest.raises(MalformedCheckboxError):
        parse_checkboxes("## T-X\n\n1.[ ] 공백이 없다\n", source="<fixture>")


def test_a_section_with_no_checkbox_at_all_is_still_named() -> None:
    """체크박스가 하나도 없는 절도 감시된다 — 이 원장에 실재하는 모양이다.

    `T-VN-D2-RESIDUE`처럼 해제 조건을 `1. [ ]`가 아니라 **맨 번호 목록**으로 적은
    절이 있다. 체크박스만 세면 파싱 결과가 0건이라, 절을 통째로 지워도 아무 일도
    일어나지 않는다.
    """
    text = "# 원장\n\n## T-NO-BOXES\n\n1. 맨 번호 목록이다. 체크박스가 아니다.\n"
    assert parse_checkboxes(text, source="<fixture>") == []
    assert section_task_ids(text) == {"T-NO-BOXES"}


# ── 2층: 실제 원장이 보이는 상태로 남아 있는가 ──────────────────────────


def test_the_real_ledger_has_balanced_fences() -> None:
    """원장의 fence가 짝이 맞고, 여는 쪽만 언어 태그를 단다.

    이 검사가 빨개지면 누군가 인용 블록 안쪽에 내용을 끼워 넣었다는 뜻이다 —
    `3b11c9757`이 한 일이고, 그 뒤 신설된 절 열이 전부 안 보이게 된 경로다.
    """
    lines = LEDGER.read_text(encoding="utf-8").splitlines()
    fence = re.compile(r"^(```|~~~)")
    depth, marker, opened = 0, "", []
    for number, line in enumerate(lines, start=1):
        stripped = line.strip()
        match = fence.match(stripped)
        if not match:
            continue
        if depth == 0:
            depth, marker = 1, match.group(1)
            opened.append((number, stripped))
        elif stripped.startswith(marker):
            depth = 0
            assert stripped == marker, (
                f"L{number}: 닫는 fence가 언어 태그를 달고 있다 ({stripped!r}) — "
                f"짝이 어긋나 여는 자리로 읽혔다는 신호다. 열린 자리: L{opened[-1][0]}"
            )
    assert depth == 0, f"닫히지 않은 fence가 있다 — 마지막으로 연 자리: L{opened[-1][0]}"


@pytest.mark.parametrize(
    "task",
    ["T-VN-LEDGER-ARCHIVE", "T-VN-QUEUE-QUOTA", "T-VN-KREX-TPS-FANOUT"],
)
def test_the_sections_that_were_invisible_are_now_parsed(task: str) -> None:
    """2026-09-16 이전에 fence 안에 갇혀 있던 절의 조문이 실제로 파싱된다.

    세 이름을 박아 두는 이유: 이것들이 안 보이던 상태가 정확히 `6d671ef1`의 재발
    조건이었다.

    **원장만 보지 않고 감시 대상 전체를 본다.** 절이 닫히면 규약 §8대로
    `docs/archive/tasks-acceptance-*.md`로 옮겨지는데, 그것은 **사라진 것이 아니라
    옮겨진 것**이고 삭제 게이트는 아카이브도 감시 대상으로 읽는다
    (`_archive_watch_paths`, `T-VN-LEDGER-ARCHIVE` 조문 3). 여기서 원장만 보면
    닫아서 아카이브로 옮기는 정상 동작이 이 검사를 빨갛게 만든다 — 실제로
    2026-09-16에 `T-VN-LEDGER-ARCHIVE`를 닫고 옮기자 그렇게 됐다.

    즉 이 검사가 묻는 것은 "원장에 있는가"가 아니라 **"게이트에게 보이는가"**이고,
    게이트가 보는 집합과 같은 집합을 봐야 그 물음이 성립한다.
    """
    watched = [LEDGER, *sorted(LEDGER.parent.glob("archive/tasks-acceptance-*.md"))]
    seen_section: list[str] = []
    clauses: list[str] = []
    for path in watched:
        text = path.read_text(encoding="utf-8")
        if task in section_task_ids(text):
            seen_section.append(path.name)
        # **첫 매치에서 멈추면 안 된다.** 절이 아카이브로 옮겨지면 live 원장에는
        # 제목 + stub 한 줄만 남고 조문 본문은 아카이브에 있다(규약 §8). 원장에서
        # 제목을 보고 거기서 끝내면 "제목은 있는데 조문이 0건"으로 빨개진다 —
        # 정상 동작을 고장으로 읽는 것이다.
        clauses.extend(
            item.clause_id
            for item in parse_checkboxes(text, source=str(path))
            if item.section_task_id == task and item.clause_id is not None
        )

    assert seen_section, (
        f"`## {task}` 절이 감시 대상 어디에서도 파서에게 보이지 않는다 "
        f"(찾아본 곳 {len(watched)}개)"
    )
    assert clauses, (
        f"{task}의 절은 {seen_section}에서 보이는데 해제 조문이 하나도 파싱되지 않았다 — "
        "제목만 남고 조문이 어디에서도 안 보이면 게이트가 지킬 것이 없다"
    )


# ── 3층: 게이트가 실제로 빨개지는가 (임시 git 저장소) ──────────────────

TASKS = """# 활성 backlog

- [ ] T-FIX-01 — fixture용 열린 task
"""

DONE = """# 완료 원장

- [x] T-OLD-01 — 이전에 닫힌 task. 무엇이 어떻게 완료됐는지는 여기가 소유한다.
"""

ACCEPTANCE = """# 해제 조건

## T-FIX-01

**무엇이 참이면 닫히는가.**

1. [x] 첫 조문 — 충족됐다.
2. [ ] 둘째 조문 — 아직이다. 지워지면 안 되는 바로 그 줄이다.
3. [ ] 셋째 조문 — 역시 아직이다.

## T-NO-BOXES

1. 체크박스가 없는 해제 조건이다. 절 제목만이 이 task의 표식이다.
"""


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    ).stdout


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
    repo = tmp_path / "ledger"
    (repo / "docs" / "archive").mkdir(parents=True)
    (repo / "scripts").mkdir()
    (repo / "docs" / "tasks.md").write_text(TASKS, encoding="utf-8")
    (repo / "docs" / "tasks-done.md").write_text(DONE, encoding="utf-8")
    (repo / "docs" / "tasks-acceptance.md").write_text(ACCEPTANCE, encoding="utf-8")
    shutil.copy(DETECTOR, repo / "scripts" / DETECTOR.name)
    shutil.copy(PARSER, repo / "scripts" / PARSER.name)
    _git(repo, "init", "-q", "-b", "main")
    _commit(repo, "base")
    return repo, _git(repo, "rev-parse", "HEAD").strip()


def _gate(repo: Path, base: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, f"scripts/{DETECTOR.name}", base],
        cwd=repo,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )


def test_deleting_one_unchecked_clause_is_caught(tmp_path: Path) -> None:
    """조문 하나를 지우면 **그 조문의 이름으로** 빨개진다.

    절 ID만 감시하면 여기가 초록이다 — 조문 1·3이 남아 `T-FIX-01`은 살아 있다.
    실측으로 `clause_id`를 빼면 이 검사가 실제로 초록이 된다.
    """
    repo, base = _make_repo(tmp_path)
    (repo / "docs" / "tasks-acceptance.md").write_text(
        ACCEPTANCE.replace("2. [ ] 둘째 조문 — 아직이다. 지워지면 안 되는 바로 그 줄이다.\n", ""),
        encoding="utf-8",
    )
    _commit(repo, "조문 2 삭제")

    result = _gate(repo, base)
    assert result.returncode == 1, f"게이트가 조용했다: {result.stdout} {result.stderr}"
    assert "T-FIX-01#2" in result.stderr
    # 남은 조문은 고발하지 않는다 — 시끄러운 게이트는 꺼지는 게이트다.
    assert "T-FIX-01#1" not in result.stderr
    assert "T-FIX-01#3" not in result.stderr


def test_editing_a_clause_in_place_stays_green(tmp_path: Path) -> None:
    """문구를 고치고 `[ ]`를 `[x]`로 바꾸는 것은 삭제가 아니다."""
    repo, base = _make_repo(tmp_path)
    (repo / "docs" / "tasks-acceptance.md").write_text(
        ACCEPTANCE.replace(
            "2. [ ] 둘째 조문 — 아직이다. 지워지면 안 되는 바로 그 줄이다.",
            "2. [x] 둘째 조문 — 문구를 다시 쓰고 충족 처리했다.",
        ),
        encoding="utf-8",
    )
    _commit(repo, "조문 2 문구 수정 + 충족 처리")

    result = _gate(repo, base)
    assert result.returncode == 0, f"정당한 편집이 막혔다: {result.stderr}"


def test_deleting_a_section_that_has_no_checkbox_is_caught(tmp_path: Path) -> None:
    """체크박스가 없는 절을 통째로 지우는 것도 삭제다.

    게이트의 `section_task_ids` 층을 빼면 여기가 초록이 된다. 실제 원장에서
    다섯 절이 정확히 이 모양이었다.
    """
    repo, base = _make_repo(tmp_path)
    head, _, _ = ACCEPTANCE.partition("## T-NO-BOXES")
    (repo / "docs" / "tasks-acceptance.md").write_text(head, encoding="utf-8")
    _commit(repo, "체크박스 없는 절 삭제")

    result = _gate(repo, base)
    assert result.returncode == 1, f"게이트가 조용했다: {result.stdout} {result.stderr}"
    assert "T-NO-BOXES" in result.stderr


def test_a_fenced_clause_is_not_a_justification(tmp_path: Path) -> None:
    """지운 조문을 코드 블록에 옮겨 적는 것은 근거가 아니다.

    diff는 줄 단위라 그 줄이 fence 안이었는지 모른다. 게이트가 HEAD 파일을 fence
    인지 파서로 다시 읽는 이유다.
    """
    repo, base = _make_repo(tmp_path)
    (repo / "docs" / "tasks-acceptance.md").write_text(
        ACCEPTANCE.replace("2. [ ] 둘째 조문 — 아직이다. 지워지면 안 되는 바로 그 줄이다.\n", "")
        + "\n표기 예시:\n\n```markdown\n2. [x] 둘째 조문 — 예시일 뿐 항목이 아니다\n```\n",
        encoding="utf-8",
    )
    _commit(repo, "조문 2 삭제 + fence 안 가짜 조문")

    result = _gate(repo, base)
    assert result.returncode == 1, f"fence 안 표기가 근거로 통과했다: {result.stdout}"
    assert "T-FIX-01#2" in result.stderr


def test_moving_a_clause_to_the_archive_is_accepted(tmp_path: Path) -> None:
    """절을 아카이브로 옮기면 조문 식별자가 따라간다 — 오탐 쪽 경계다.

    귀속이 `## ` 제목에서 오므로 제목과 함께 옮기기만 하면 같은 식별자가 된다.
    정당한 분리가 빨개지면 게이트를 끄는 쪽이 합리적인 선택이 돼 버린다.
    """
    repo, base = _make_repo(tmp_path)
    head, marker, tail = ACCEPTANCE.partition("## T-FIX-01")
    (repo / "docs" / "tasks-acceptance.md").write_text(head.rstrip() + "\n", encoding="utf-8")
    (repo / "docs" / "archive" / "tasks-acceptance-fix01.md").write_text(
        "# 아카이브\n\n" + marker + tail, encoding="utf-8"
    )
    _commit(repo, "T-FIX-01 절을 아카이브로 분리")

    result = _gate(repo, base)
    assert result.returncode == 0, f"정당한 이관이 막혔다: {result.stderr}"


def test_the_gate_still_reads_only_content_lines(tmp_path: Path) -> None:
    """원장을 건드리지 않는 변경은 조용해야 한다."""
    repo, base = _make_repo(tmp_path)
    (repo / "README.md").write_text("관계없는 변경\n", encoding="utf-8")
    _commit(repo, "무관한 변경")

    result = _gate(repo, base)
    assert result.returncode == 0, f"무관한 변경이 막혔다: {result.stderr}"


def test_strip_non_content_still_hides_fenced_lines() -> None:
    """귀속을 더하면서 fence 인지가 약해지지 않았는지 직접 본다."""
    visible = strip_non_content(_FENCED_TITLE)
    fenced = [
        line
        for line in visible
        if line is not None and ("T-QUOTED" in line or line.strip().startswith("- [ ] Q1"))
    ]
    assert not fenced, f"fence 안의 줄이 내용으로 남았다: {fenced}"
    # 살아 있는 줄은 그대로 남아야 한다 — 전부 숨기는 것은 통과가 아니다.
    assert any(line is not None and line.startswith("1. [ ]") for line in visible)
