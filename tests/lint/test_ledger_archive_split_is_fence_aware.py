"""원장 분리가 체크박스 항목을 조용히 잃지 않는다 — `T-VN-LEDGER-ARCHIVE` 조문 2.

2026-09-13에 `docs/tasks-acceptance.md`를 제목(``## ``) 기준으로 쪼개려던 시도가
삭제 게이트를 **37번** 빨갛게 만들고 되돌려졌다. 원인은 단순하다: **코드 fence가 절
경계를 가로지른다.** 어떤 절이 fence를 열고 닫지 않은 채 끝나면, 그 절을 들어냈을 때
나머지 파일에 남은 닫는 fence가 이번에는 **여는** fence가 되고 그 뒤의 항목이
`parse_checkboxes`에서 사라진다. 파일에는 그대로 있는데 게이트가 보지 못한다 —
``6d671ef1``이 한 번 연 경로와 결과가 같다.

그래서 `scripts/archive_task_ledger_section.py`가 옮기기 전에 검산한다. 본 파일은 그
검산이 **실제로 빨갛게 될 수 있는지**를 결박한다. 세 fixture를 쓴다.

1. `_LEDGER_FENCE_CROSSES` — fence가 경계를 넘는 절(2026-09-13의 모양).
   **옮기기 전후 항목 개수가 3건으로 같다.** 개수만 세는 검사는 여기서 초록이다.
2. `_LEDGER_EVEN_PARITY_INSIDE_FENCE` — 절 안의 fence 마커가 **짝수**인데 시작
   경계가 이미 fence 안인 절. 마커 개수의 홀짝만 보는 검사는 여기서 초록이다.
   (실측: 실제 원장 44개 절 중 잘라선 안 되는 21개 가운데 **11개가 이 모양**이다.)
3. `_LEDGER_CLEAN` — 실제로 옮겨도 되는 절. 여기서는 통과해야 한다. 아무것도
   통과시키지 못하는 검사는 검사가 아니다.

문구가 아니라 **구조화된 판정**에 건다(`Diagnosis.is_movable`, `parse_sum_delta`).
메시지 문자열에 거는 검사는 문구만 바꿔도 초록이 되고, 이 저장소는 그런 항진명제에
세 번 데였다.
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import archive_task_ledger_section as splitter  # noqa: E402
from task_ledger_lint import parse_checkboxes  # noqa: E402

_INDEX_HEADER = """# 원장 (fixture)

> **과거 기록 아카이브** (규약 §8)
>
> | 절 | 파일 | 크기 |
> | --- | --- | --- |
> | `T-OLD` (완료) | [archive/tasks-acceptance-old.md](archive/tasks-acceptance-old.md) | 약 3 KB |

"""

_LEDGER_FENCE_CROSSES = (
    _INDEX_HEADER
    + """## T-KEEP-BEFORE

- [ ] **T-KEEP-BEFORE — 앞 절은 그대로 남는다**
  - [ ] A1 하위 기준 하나

## T-CROSS-CLOSED

닫힌 절이다. 그런데 이 절이 연 fence는 이 절 안에서 닫히지 않는다.

```markdown
- [x] B1 이 줄은 원본에서 fence 안이라 항목이 아니다

## T-KEEP-AFTER

- [x] B2 이 줄도 원본에서는 fence 안이다
```

- [ ] **T-KEEP-AFTER — 이 항목이 조용히 사라지는 것이 사고다**
"""
)

_LEDGER_EVEN_PARITY_INSIDE_FENCE = (
    _INDEX_HEADER
    + """## T-OPEN-FENCE

- [ ] **T-OPEN-FENCE — 이 절이 fence를 열고 닫지 않는다**

```markdown
- [x] C1 여기부터 fence 안

## T-EVEN-CLOSED

- [x] C2 아직 fence 안이다
```

산문 한 줄. 여기까지가 앞 fence의 바깥이다.

```markdown
- [x] C3 다시 fence 안

## T-TAIL

- [x] C4 아직 fence 안
```

- [ ] **T-TAIL — fence 밖 항목**
"""
)

_LEDGER_CLEAN = (
    _INDEX_HEADER
    + """## T-KEEP-BEFORE

- [ ] **T-KEEP-BEFORE — 앞 절은 그대로 남는다**
  - [ ] A1 하위 기준 하나

## T-CLEAN-CLOSED

닫힌 절이다. 복원 블록과 판정 문단이 절 안에서 닫힌다.

```markdown
- [x] T-CLEAN-CLOSED — 원문 복원 블록(fence 안이라 항목이 아니다)
```

- [x] **T-CLEAN-CLOSED — 절 자체의 완료 표시**
  - [x] V1 검증 하나

## T-KEEP-AFTER

- [ ] **T-KEEP-AFTER — 뒤 절도 그대로 남는다**
"""
)


_LEDGER_SAME_ID_DIFFERENT_TEXT = (
    _INDEX_HEADER
    + """## T-KEEP-BEFORE

- [ ] **T-KEEP-BEFORE — 앞 절은 그대로 남는다**

## T-SWAP-CLOSED

닫힌 절이다. 이 절이 연 fence 안에 `B1`이라는 **같은 ID의 다른 문장**이 들어 있다.

```markdown
- [ ] B1 fence 안에 있던 문장 — 원본에서는 항목이 아니다

## T-KEEP-AFTER

- [ ] B1 이 줄도 원본에서는 fence 안이다
```

- [ ] B1 원본에서 실제로 보이는 조건
"""
)


def _multiset(text: str) -> Counter[tuple[int, str, str | None, str | None, str]]:
    """테스트가 **직접** 세는 지문 — 도구의 헬퍼를 빌리지 않는다.

    도구가 자기 함수로 자기를 검산하면 그 함수가 틀렸을 때 둘 다 같이 틀린다.
    줄 번호만 빼는 이유는 절을 들어내면 모든 줄이 밀리기 때문이다.
    """
    return Counter(
        (item.indent, item.state, item.task_id, item.criterion_id, item.text)
        for item in parse_checkboxes(text, source="<fixture>")
    )


def _plan(ledger: str, title: str, name: str) -> splitter.ArchivePlan:
    return splitter.build_plan(ledger, title, name, today="2026-09-16")


def test_refusal_message_survives_items_without_an_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """거절은 **메시지**로 나와야 한다 — 거절을 만들다가 죽으면 도구가 고장난 것처럼 보인다.

    지문 튜플에는 `task_id`·`criterion_id`가 `None`인 항목이 섞인다(절 제목이 ID를 갖고
    조문에는 없는 모양이 그렇다). `sorted()`로 튜플을 직접 비교하면 그 자리에서 str과
    None이 만나 `TypeError`가 난다 — 2026-09-16에 `T-FE-MOCK-FLAKE`를 시험하다 실제로
    그렇게 죽었다.

    **왜 이것이 조용한 사고인가.** 화면에 보이는 것이 "옮기면 안 된다"가 아니라 스택
    트레이스면, 읽는 사람은 절이 위험하다고 읽지 않고 **도구가 망가졌다**고 읽는다.
    그 다음 행동은 손으로 자르는 것이고, 그것이 2026-09-13에 삭제 게이트를 37번 빨갛게
    만든 바로 그 경로다. 거절 경로는 그 자체가 안전 장치이므로 따로 결박한다.
    """
    plan = _plan(_LEDGER_CLEAN, "T-CLEAN-CLOSED", "tasks-acceptance-clean.md")

    # 같은 (indent, state)에서 ID 있는 항목과 없는 항목이 섞이는 순간이 그 자리다.
    lost: Counter[tuple[int, str, str | None, str | None, str]] = Counter(
        {
            (0, " ", "T-HAS-ID", None, "T-HAS-ID — ID가 있는 항목"): 1,
            (0, " ", None, None, "ID가 없는 조문 항목"): 1,
        }
    )
    monkeypatch.setattr(splitter, "parse_sum_delta", lambda _plan: (lost, Counter()))

    failures = splitter.check_plan(plan)

    assert failures, "항목이 사라지는데 거절하지 않았다"
    joined = "\n".join(failures)
    # 무엇이 사라지는지를 **이름으로** 말해야 한다 — 건수만으로는 손댈 자리를 모른다.
    assert "T-HAS-ID" in joined, joined
    assert "ID가 없는 조문 항목" in joined, joined


def test_fence_crossing_section_is_refused() -> None:
    """fence가 경계를 넘는 절은 거절된다 — 2026-09-13의 모양 그대로."""
    plan = _plan(_LEDGER_FENCE_CROSSES, "T-CROSS-CLOSED", "tasks-acceptance-cross.md")

    assert plan.diagnosis.fence_parity_is_odd, "fixture가 홀수 fence 절이 아니다"
    assert plan.diagnosis.exits_inside_fence is True
    assert not plan.diagnosis.is_movable

    lost, gained = splitter.parse_sum_delta(plan)
    assert lost, "사라지는 항목이 없다 — fixture가 사고를 재현하지 못한다"
    assert gained, "새로 생기는 항목이 없다 — fixture가 사고를 재현하지 못한다"

    # 사라지는 것은 fence 밖의 실제 task, 새로 생기는 것은 원래 fence 안에 있던 줄이다.
    assert {item[2] for item in lost} == {"T-KEEP-AFTER"}
    assert {item[3] for item in gained} == {"B2"}

    assert any("T-CROSS-CLOSED" in failure for failure in splitter.check_plan(plan))


def test_the_multiset_check_is_not_a_count_check() -> None:
    """같은 fixture에서 **개수는 3건으로 같다** — 개수만 세면 초록이다.

    이 테스트가 없으면 `parse_sum_delta`를 `len(before) == len(after)`로 줄여도
    위 테스트가 그대로 초록일 수 있다. 다중집합이어야 하는 이유가 여기 있다.
    """
    plan = _plan(_LEDGER_FENCE_CROSSES, "T-CROSS-CLOSED", "tasks-acceptance-cross.md")
    before = _multiset(plan.ledger_before)
    after = _multiset(plan.ledger_after) + _multiset(plan.archive_after)

    assert sum(before.values()) == sum(after.values()) == 3
    assert before != after


def test_the_multiset_check_compares_item_text_not_just_ids() -> None:
    """ID·상태·들여쓰기가 **전부 같고 문장만 다른** 두 항목이 맞바뀌는 모양.

    적대 검증에서 이 fixture 없이 지문에서 `text`를 빼 봤더니 일곱 테스트가 전부
    초록이었다 — 문장 비교가 결박되지 않은 채 docstring만 그렇다고 적고 있었다.
    여기서는 `B1` 하나가 통째로 다른 문장으로 바뀌고 개수는 2건으로 같다. ID만 세는
    지문도, 개수만 세는 검사도 이 자리를 통과한다.
    """
    plan = _plan(_LEDGER_SAME_ID_DIFFERENT_TEXT, "T-SWAP-CLOSED", "tasks-acceptance-swap.md")
    before = _multiset(plan.ledger_before)
    after = _multiset(plan.ledger_after) + _multiset(plan.archive_after)

    assert sum(before.values()) == sum(after.values()) == 2
    assert {item[3] for item in before} == {item[3] for item in after} == {None, "B1"}

    lost, gained = splitter.parse_sum_delta(plan)
    assert [item[4] for item in lost] == ["B1 원본에서 실제로 보이는 조건"]
    assert [item[4] for item in gained] == ["B1 이 줄도 원본에서는 fence 안이다"]


def test_even_fence_parity_is_not_enough() -> None:
    """마커가 **짝수**인데도 경계가 fence 안인 절 — parity만 보는 도구는 초록이다.

    실제 원장에서 잘라선 안 되는 21개 절 중 11개가 이 모양이다(2026-09-16 실측).
    `Diagnosis.is_movable`이 진입 경계를 함께 보지 않으면 이 테스트가 빨개진다.
    """
    plan = _plan(
        _LEDGER_EVEN_PARITY_INSIDE_FENCE, "T-EVEN-CLOSED", "tasks-acceptance-even.md"
    )

    assert plan.diagnosis.fence_markers % 2 == 0, "fixture가 짝수 마커 절이 아니다"
    assert plan.diagnosis.fence_parity_is_odd is False
    assert plan.diagnosis.enters_inside_fence is True
    assert plan.diagnosis.is_movable is False

    _, gained = splitter.parse_sum_delta(plan)
    assert {item[3] for item in gained} == {"C2", "C3"}, (
        "fence 안에 숨어 있던 두 줄이 아카이브에서 항목으로 드러나야 한다"
    )


def test_clean_section_moves_and_the_parse_sum_holds(tmp_path: Path) -> None:
    """옮겨도 되는 절은 통과하고, 옮긴 뒤 두 파일의 파싱 합이 옮기기 전과 같다.

    `--apply` 경로까지 태운다. 검산이 옳아도 CLI가 그 결과를 무시하면 소용없다.
    """
    ledger = tmp_path / "tasks-acceptance.md"
    ledger.write_text(_LEDGER_CLEAN, encoding="utf-8", newline="\n")
    archive_dir = tmp_path / "archive"

    before = _multiset(_LEDGER_CLEAN)
    assert sum(before.values()) == 5, "fixture 항목 수가 바뀌었다"

    exit_code = splitter.main(
        [
            "T-CLEAN-CLOSED",
            "--to",
            "tasks-acceptance-clean.md",
            "--ledger",
            str(ledger),
            "--archive-dir",
            str(archive_dir),
            "--date",
            "2026-09-16",
            "--apply",
        ]
    )
    assert exit_code == 0

    archive = archive_dir / "tasks-acceptance-clean.md"
    remainder_text = ledger.read_text(encoding="utf-8")
    archive_text = archive.read_text(encoding="utf-8")

    after = _multiset(remainder_text) + _multiset(archive_text)
    assert after == before, "옮긴 뒤 파싱 결과가 달라졌다"

    # 갈라진 자리도 확인한다 — 합만 맞고 양쪽이 같은 것을 세면 안 된다.
    assert sum(_multiset(remainder_text).values()) == 3
    assert sum(_multiset(archive_text).values()) == 2

    # 관례: 본문은 바이트 보존, live에는 제목 + stub, 인덱스 표에 행 하나.
    section_start = _LEDGER_CLEAN.index("## T-CLEAN-CLOSED")
    section_end = _LEDGER_CLEAN.index("## T-KEEP-AFTER")
    assert _LEDGER_CLEAN[section_start:section_end].rstrip("\n") in archive_text
    assert "## T-CLEAN-CLOSED" in remainder_text
    assert "archive/tasks-acceptance-clean.md" in remainder_text
    assert remainder_text.count("> | `T-CLEAN-CLOSED` (완료) |") == 1
    assert "T-CLEAN-CLOSED — 절 자체의 완료 표시" not in remainder_text


@pytest.mark.parametrize(
    ("ledger", "title"),
    [
        (_LEDGER_FENCE_CROSSES, "T-CROSS-CLOSED"),
        (_LEDGER_EVEN_PARITY_INSIDE_FENCE, "T-EVEN-CLOSED"),
        (_LEDGER_SAME_ID_DIFFERENT_TEXT, "T-SWAP-CLOSED"),
    ],
    ids=["fence-crosses", "even-parity-inside-fence", "same-id-different-text"],
)
def test_apply_writes_nothing_when_the_check_refuses(
    tmp_path: Path, ledger: str, title: str
) -> None:
    """거절이면 `--apply`도 아무것도 쓰지 않는다.

    도구가 옳게 판정하고도 파일을 써 버리면 판정은 장식이다. 원장이 **바이트 동일**로
    남는 것까지 본다.
    """
    path = tmp_path / "tasks-acceptance.md"
    path.write_text(ledger, encoding="utf-8", newline="\n")
    archive_dir = tmp_path / "archive"

    exit_code = splitter.main(
        [
            title,
            "--to",
            "tasks-acceptance-refused.md",
            "--ledger",
            str(path),
            "--archive-dir",
            str(archive_dir),
            "--date",
            "2026-09-16",
            "--apply",
        ]
    )

    assert exit_code == 1
    assert path.read_text(encoding="utf-8") == ledger
    assert not (archive_dir / "tasks-acceptance-refused.md").exists()


def test_movable_verdict_agrees_with_the_parse_sum_on_the_real_ledger() -> None:
    """실제 원장에서 두 층이 서로 어긋나지 않는다.

    fence 진단(`is_movable`)은 **메커니즘**을 이름 붙여 보고하는 층이고, 다중집합
    검산은 **성질**을 지키는 층이다. 진단이 "옮겨도 된다"고 한 절에서 성질이 깨지면
    진단이 사람을 잘못된 안심으로 이끈다 — 실제 파일에서 그 일이 없는지 본다.

    (수치를 고정하지 않는다. 원장이 정리되면 통과 절이 늘어날 뿐이고, 그때 빨개지는
    테스트는 개선을 막는다.)
    """
    ledger_path = REPO_ROOT / "docs" / "tasks-acceptance.md"
    ledger_text = ledger_path.read_text(encoding="utf-8")
    sections = splitter.split_sections(ledger_text)
    assert len(sections) > 20, "원장에서 절을 거의 읽지 못했다 — 파싱이 깨졌다"

    movable = [
        section
        for section in sections
        if splitter.diagnose(ledger_text, section).is_movable
    ]
    assert movable, "옮길 수 있는 절이 하나도 없다 — 진단이 전부 STOP이면 도구가 무용지물이다"

    for section in movable:
        plan = _plan(ledger_text, section.title, "tasks-acceptance-probe.md")
        lost, gained = splitter.parse_sum_delta(plan)
        assert not lost, (
            f"`## {section.title}`을 진단은 '옮겨도 된다'고 했는데 항목이 사라진다: "
            f"{sorted(map(str, lost))}"
        )
        assert not gained, (
            f"`## {section.title}`을 진단은 '옮겨도 된다'고 했는데 없던 항목이 생긴다: "
            f"{sorted(map(str, gained))}"
        )
