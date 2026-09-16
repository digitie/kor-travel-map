#!/usr/bin/env python
"""닫힌 절을 `docs/tasks-acceptance.md`에서 `docs/archive/`로 **안전하게** 옮긴다.

## 왜 도구가 필요한가

원장을 제목(`## `)으로 자르는 것은 안전해 보이지만 아니다. **코드 fence가 절 경계를
가로지른다.** 어떤 절이 ```` ``` ````를 열고 닫지 않은 채 끝나면, 그 절을 들어냈을 때
나머지 파일에 남은 닫는 fence가 이번에는 **여는** fence가 되고, 그 뒤의 체크박스 항목이
통째로 사라진다 — 파일에는 그대로 있는데 `parse_checkboxes`가 보지 못한다.

그것이 정확히 `check_task_ledger_deletions.py`가 막으려는 사고다. 2026-09-13에 제목
기준으로 원장을 쪼개려던 시도가 삭제 게이트를 **37번** 빨갛게 만들고 되돌려졌다.

`--report` 실측(2026-09-16, 44개 절): 제목만 보고 자르면 **21개 절에서 경계가 fence
안에 떨어진다** — fence 마커가 홀수인 절 10개, 시작 경계가 이미 fence 안인 절 16개
(둘 다인 절 5개). **21개 중 11개는 마커 개수가 짝수다.** 홀짝만 세는 도구는 그 11개를
통과시킨다. 손으로 고를 수 있는 규모도 아니고, 홀짝으로 고를 수 있는 것도 아니다.

## 무엇을 결박하는가 (안전 성질)

옮기기 전 원본을 A, 옮긴 뒤 남는 원장을 B, 새 아카이브 파일을 C라 할 때

    parse_checkboxes(B) ⊎ parse_checkboxes(C) == parse_checkboxes(A)

가 **다중집합으로** 같아야 한다(줄 번호는 필연적으로 바뀌므로 지문에서 뺀다 —
`_fingerprints` 참조). 하나라도 다르면 절 이름과 함께 거절한다. 세기만 맞고 내용이
바뀌는 경우가 실제로 있어서(fence가 한 항목을 숨기고 다른 항목을 드러낸다) 개수가
아니라 다중집합을 본다.

fence 짝은 **그 성질이 깨지는 메커니즘**이므로 따로 진단해 이름을 붙인다. 다만 판정의
근거는 fence 정규식이 아니라 정본 state machine이다 — `_boundary_is_inside_fence`가
`strip_non_content`에 탐침 한 줄을 물어본다. fence 규칙을 여기서 다시 쓰면 정본과
갈라지고, 그 갈라짐이 애초의 실패 원인이었다.

## 쓰는 법

    # 44개 절 전부의 fence 진단 — 무엇을 옮길 수 있는지 먼저 본다
    python scripts/archive_task_ledger_section.py --report

    # 검산만 (파일을 쓰지 않는다. 기본 동작이다)
    python scripts/archive_task_ledger_section.py "T-VN-PAIR-V2" \
        --to tasks-acceptance-pair-v2.md

    # 검산이 통과했을 때만 실제로 옮긴다
    python scripts/archive_task_ledger_section.py "T-VN-PAIR-V2" \
        --to tasks-acceptance-pair-v2.md --apply

live 문서에는 `docs/tasks-rule.md` §8 관례대로 제목과 한 줄 stub만 남고, 상단
"과거 기록 아카이브" 표에 행이 하나 늘어난다.
"""

from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from task_ledger_lint import (  # noqa: E402
    MalformedCheckboxError,
    parse_checkboxes,
    strip_non_content,
)

LEDGER = "docs/tasks-acceptance.md"
ARCHIVE_DIR = "docs/archive"

#: live 문서 상단 인덱스 표를 찾는 닻(`docs/tasks-rule.md` §8 "인덱스 필수").
INDEX_ANCHOR = "과거 기록 아카이브"

#: 규약 §8이 정한 단일 파일 상한.
MAX_FILE_BYTES = 220 * 1024

_HEADING = re.compile(r"^## (?P<title>.+?)\s*$")

#: **표시 전용** fence 카운터다. 안전 판정은 이 값을 한 번도 쓰지 않는다 —
#: 전부 `_boundary_is_inside_fence`(정본 state machine 탐침)에서 나온다.
#: 사람에게 "이 절에 fence 마커가 몇 개인가"를 보여주기 위해서만 센다.
_FENCE_MARKER = re.compile(r"^(```|~~~)")

#: `strip_non_content`가 지우는지 보고 "이 자리가 fence 안인가"를 되묻기 위한 한 줄.
#: fence로도 체크박스로도 읽히지 않아야 하고, 제어문자를 쓰면
#: `tests/lint/test_no_control_characters_in_source.py`가 막으므로 순수 ASCII다.
_PROBE_LINE = "KTM-FENCE-PROBE"

#: 절 본문에 상대 링크가 있으면 `docs/archive/` 기준으로 깨진다(규약 §8).
#: 바이트 보존과 재기준화는 동시에 성립할 수 없으므로 도구는 고치지 않고 거절한다.
_MARKDOWN_LINK = re.compile(r"\[[^\]]*\]\((?P<target>[^)\s]+)\)")

#: 항목 지문 — `CheckboxItem`에서 줄 번호만 뺀 것.
Fingerprint = tuple[int, str, str | None, str | None, str]


@dataclass(frozen=True)
class Section:
    """`## ` 한 개가 소유하는 줄 구간. `end`는 배타적."""

    title: str
    start: int
    end: int


@dataclass(frozen=True)
class Diagnosis:
    """한 절을 들어냈을 때 경계가 어디에 떨어지는가."""

    section: Section
    fence_markers: int
    enters_inside_fence: bool
    exits_inside_fence: bool
    comment_opens: int
    comment_closes: int

    @property
    def fence_parity_is_odd(self) -> bool:
        """fence 마커가 홀수인가 — 정본 state machine이 뒤집혔는지로 판정한다.

        마커를 세서 나눈 나머지가 아니다. `~~~`로 연 fence는 ```` ``` ````로 닫히지
        않으므로(정본 `strip_non_content`의 닫힘 조건) 마커 개수와 실제 뒤집힘이
        어긋날 수 있고, 어긋날 때 옳은 쪽은 state machine이다.
        """
        return self.enters_inside_fence != self.exits_inside_fence

    @property
    def is_movable(self) -> bool:
        return not (
            self.enters_inside_fence
            or self.exits_inside_fence
            or self.comment_opens != self.comment_closes
        )


@dataclass(frozen=True)
class ArchivePlan:
    """옮긴 결과 두 파일이 어떤 내용이 되는가 — 아직 아무것도 쓰지 않은 상태."""

    section: Section
    diagnosis: Diagnosis
    label: str
    archive_name: str
    section_text: str
    ledger_before: str
    ledger_after: str
    archive_after: str


def _boundary_is_inside_fence(prefix: str) -> bool:
    """`prefix` **바로 다음 줄**이 fence 안인가를 정본에 직접 물어본다.

    fence 규칙을 여기서 다시 쓰지 않는 것이 요점이다. 탐침 한 줄을 붙여
    `strip_non_content`가 그 줄을 지우면(=`None`) 그 자리는 fence 안이다. 정본의
    fence 문법이 바뀌어도 이 판정은 저절로 따라온다.

    HTML 주석은 이 탐침으로 보이지 않는다 — 닫는 `-->`가 없으면 정본 정규식이 아예
    매칭하지 않기 때문이다. 그쪽은 `comment_opens/closes` 진단과, 최종적으로는
    다중집합 검산이 잡는다.
    """
    lines = strip_non_content(prefix + "\n" + _PROBE_LINE)
    return lines[-1] is None


def split_sections(text: str) -> list[Section]:
    """`## ` 제목 기준 구간 목록. 첫 제목 앞 서문은 어느 절에도 속하지 않는다."""

    lines = text.splitlines()
    starts = [index for index, line in enumerate(lines) if _HEADING.match(line)]
    bounds = [*starts[1:], len(lines)]
    sections: list[Section] = []
    for start, end in zip(starts, bounds, strict=True):
        match = _HEADING.match(lines[start])
        assert match is not None  # starts는 방금 같은 정규식으로 골랐다
        sections.append(Section(title=match.group("title"), start=start, end=end))
    return sections


def diagnose(text: str, section: Section) -> Diagnosis:
    """한 절의 경계·fence·주석 상태."""

    lines = text.splitlines()
    body = lines[section.start : section.end]
    return Diagnosis(
        section=section,
        fence_markers=sum(1 for line in body if _FENCE_MARKER.match(line.strip())),
        enters_inside_fence=_boundary_is_inside_fence("\n".join(lines[: section.start])),
        exits_inside_fence=_boundary_is_inside_fence("\n".join(lines[: section.end])),
        comment_opens="\n".join(body).count("<!--"),
        comment_closes="\n".join(body).count("-->"),
    )


def _fingerprints(text: str, *, source: str) -> Counter[Fingerprint]:
    """체크박스 항목의 다중집합 지문.

    `line_no`는 뺀다 — 절을 들어내면 모든 줄 번호가 밀리므로 넣으면 항상 불일치가
    되어 검사가 무의미해진다. 나머지 다섯 필드는 한 글자도 바뀌면 안 되는 값이고,
    그 중 `text`가 핵심이다: 개수만 보거나 ID만 보면 fence가 한 항목을 숨기고 다른
    항목을 드러내는 교환이 통과한다(실제로 그런 모양이 만들어진다).
    """
    return Counter(
        (item.indent, item.state, item.task_id, item.criterion_id, item.text)
        for item in parse_checkboxes(text, source=source)
    )


def _describe(fingerprint: Fingerprint) -> str:
    indent, state, task_id, criterion_id, body = fingerprint
    return f"[{state}] {task_id or criterion_id or '?'} (indent {indent}): {body[:60]}"


def _archive_header(plan_label: str, archive_name: str, diagnosis: Diagnosis, today: str) -> str:
    """`docs/archive/tasks-acceptance-*.md` 관례 헤더 — 잰 값을 함께 남긴다.

    m05·pair-v2 두 선례가 "바이트 보존"과 "분리 전에 쟀다"를 산문으로 적었다. 도구가
    쓰면 그 문장이 실제 측정값에서 나오므로 나중에 읽는 사람이 믿을 수 있다.
    """
    parity = "홀" if diagnosis.fence_parity_is_odd else "짝"
    return (
        f"# tasks-acceptance 아카이브 — `{plan_label}` (완료)\n"
        "\n"
        f"> `{plan_label}`의 해제 조건 원문이다. 절은 닫혔고, live 문서\n"
        "> [`../tasks-acceptance.md`](../tasks-acceptance.md)가 220 KiB(225,280 bytes)\n"
        f"> 상한에 닿아 `docs/tasks-rule.md` §8대로 분리했다({today}).\n"
        ">\n"
        "> **본문은 바이트 단위로 보존했다** — 옮기기만 했고 한 글자도 고치지 않았다\n"
        "> (파일 끝 빈 줄만 하나로 정규화).\n"
        ">\n"
        "> **분리 전에 쟀다.** `scripts/archive_task_ledger_section.py`가 확인한 것:\n"
        f"> 이 절의 fence 마커 {diagnosis.fence_markers}개({parity}), 시작·끝 경계 모두\n"
        "> fence 밖, 그리고 옮긴 뒤 두 파일의 `parse_checkboxes` 결과 합이 옮기기 전과\n"
        "> **다중집합으로 같음**. 2026-09-13에 제목 기준으로 원장을 통째로 쪼개려다\n"
        "> 되돌린 적이 있는데, 그때 깨진 것이 바로 이 성질이다.\n"
        ">\n"
        "> 과거 검색은 `rg <패턴> docs/archive/`.\n"
        "\n"
    )


def _stub_line(archive_name: str, today: str) -> str:
    return (
        f"닫힌 절이다. 해제 조건 원문은 [archive/{archive_name}](archive/{archive_name})로 "
        f"옮겼다({today}, 규약 §8 — 원장이 220 KiB 상한에 닿았다)."
    )


def _index_row(label: str, archive_name: str, archive_bytes: int) -> str:
    return (
        f"> | `{label}` (완료) | [archive/{archive_name}](archive/{archive_name}) | "
        f"약 {archive_bytes // 1024} KB |"
    )


def _insert_index_row(lines: list[str], row: str) -> list[str] | None:
    """"과거 기록 아카이브" 표의 마지막 행 뒤에 한 줄 끼운다. 표가 없으면 None."""

    anchor = next((i for i, line in enumerate(lines) if INDEX_ANCHOR in line), None)
    if anchor is None:
        return None
    last_row: int | None = None
    for index in range(anchor, len(lines)):
        stripped = lines[index].strip()
        if stripped.startswith("> |"):
            last_row = index
        elif last_row is not None and not stripped.startswith(">"):
            break
    if last_row is None:
        return None
    return [*lines[: last_row + 1], row, *lines[last_row + 1 :]]


def build_plan(
    ledger_text: str,
    title: str,
    archive_name: str,
    *,
    archive_dir_text: str = "",
    label: str | None = None,
    today: str | None = None,
) -> ArchivePlan:
    """옮긴 뒤의 두 파일 내용을 계산한다. 디스크는 건드리지 않는다."""

    del archive_dir_text  # 새 파일만 만든다 — 기존 아카이브에 덧붙이지 않는다
    today = today or dt.date.today().isoformat()
    sections = split_sections(ledger_text)
    matched = [section for section in sections if section.title == title]
    if not matched:
        raise LookupError(
            f"`## {title}` 절이 없다. `--report`로 절 목록을 확인할 것 "
            f"(제목은 `## ` 뒤 원문 그대로여야 한다)."
        )
    if len(matched) > 1:
        raise LookupError(f"`## {title}` 절이 {len(matched)}개다 — 어느 것인지 알 수 없다.")
    section = matched[0]
    diagnosis = diagnose(ledger_text, section)

    lines = ledger_text.splitlines()
    section_text = "\n".join(lines[section.start : section.end])
    display = label or title

    archive_after = (
        _archive_header(display, archive_name, diagnosis, today)
        + section_text.rstrip("\n")
        + "\n"
    )

    replacement = [lines[section.start], "", _stub_line(archive_name, today), ""]
    remainder = [*lines[: section.start], *replacement, *lines[section.end :]]
    with_row = _insert_index_row(
        remainder, _index_row(display, archive_name, len(archive_after.encode("utf-8")))
    )
    ledger_after = "\n".join(with_row if with_row is not None else remainder) + "\n"

    return ArchivePlan(
        section=section,
        diagnosis=diagnosis,
        label=display,
        archive_name=archive_name,
        section_text=section_text,
        ledger_before=ledger_text,
        ledger_after=ledger_after,
        archive_after=archive_after,
    )


def parse_sum_delta(plan: ArchivePlan) -> tuple[Counter[Fingerprint], Counter[Fingerprint]]:
    """(사라지는 항목, 새로 생기는 항목). 둘 다 비어야 옮겨도 된다.

    이것이 이 도구가 지키는 성질의 전부다. `check_plan`의 문구가 아니라 이 함수의
    반환값에 결박할 것 — 메시지 문자열에 거는 검사는 문구만 바꿔도 초록이 된다.
    """
    before = _fingerprints(plan.ledger_before, source=f"{LEDGER} (before)")
    after = _fingerprints(plan.ledger_after, source=f"{LEDGER} (after)") + _fingerprints(
        plan.archive_after, source=f"{ARCHIVE_DIR}/{plan.archive_name}"
    )
    return before - after, after - before


def check_plan(plan: ArchivePlan) -> list[str]:
    """거절 사유 전부. 빈 목록이면 옮겨도 파싱 결과가 달라지지 않는다.

    **먼저 걸린 것에서 멈추지 않는다.** fence 진단과 다중집합 검산은 서로를 대신하지
    못한다 — 짝이 맞아도 파싱이 달라지는 모양이 있고(진입 시점이 이미 fence 안이면
    마커 개수는 짝수여도 두 경계가 전부 fence 안이다), 그 반대도 있다. 둘 다 돌려서
    둘 다 보고한다.
    """
    failures: list[str] = []
    name = plan.section.title
    diagnosis = plan.diagnosis

    if diagnosis.enters_inside_fence:
        failures.append(
            f"`## {name}`: 절의 **시작** 경계가 이미 fence 안이다 — 앞 절이 연 fence가 "
            "닫히지 않았다. 여기서 자르면 잘린 두 조각 모두 fence 상태가 뒤집힌다."
        )
    if diagnosis.exits_inside_fence:
        failures.append(
            f"`## {name}`: 절의 **끝** 경계가 fence 안이다 — 이 절 안에서 열린 fence가 "
            f"다음 절에서 닫힌다(절 안 fence 마커 {diagnosis.fence_markers}개). 남는 "
            "원장에는 닫는 fence만 남아 그 줄이 이번에는 fence를 **연다**."
        )
    if diagnosis.comment_opens != diagnosis.comment_closes:
        failures.append(
            f"`## {name}`: HTML 주석이 경계를 넘는다 — 절 안의 `<!--` "
            f"{diagnosis.comment_opens}개 / `-->` {diagnosis.comment_closes}개. "
            "fence와 같은 이유로 주석도 절 경계를 넘으면 내용 판정이 뒤집힌다."
        )

    relative = sorted(
        {
            match.group("target")
            for match in _MARKDOWN_LINK.finditer(plan.section_text)
            if not re.match(r"[a-z][a-z0-9+.-]*:|#|/", match.group("target"))
        }
    )
    if relative:
        failures.append(
            f"`## {name}`: 본문에 상대 링크가 있다 — `docs/archive/` 기준으로 다시 써야 "
            "하는데 그러면 '바이트 보존'이 깨진다(규약 §8, "
            f"`tests/unit/test_docs_archive_links.py`가 상시 검사한다): {relative}"
        )

    try:
        lost, gained = parse_sum_delta(plan)
    except MalformedCheckboxError as exc:
        failures.append(
            f"`## {name}`: 옮긴 결과가 malformed 체크박스를 드러냈다 — fence 안에 "
            f"숨어 있던 줄이 내용이 됐다는 뜻이다: {exc}"
        )
        return failures

    if lost or gained:
        failures.append(
            f"`## {name}`: 옮기면 `parse_checkboxes`가 보는 것이 달라진다 — "
            f"사라지는 항목 {sum(lost.values())}건, 새로 생기는 항목 "
            f"{sum(gained.values())}건. **어느 쪽이든 삭제 게이트의 감시 집합이 소리 없이 "
            "바뀐다** — 사라진 항목은 그 뒤로 아무도 지켜보지 않고, 새로 생긴 항목은 "
            "기준이었던 적이 없는 줄이 기준 행세를 한다.\n"
            + "".join(f"\n    사라짐: {_describe(item)}" for item in sorted(lost))
            + "".join(f"\n    새로 생김: {_describe(item)}" for item in sorted(gained))
        )

    if plan.section_text.rstrip("\n") not in plan.archive_after:
        failures.append(
            f"`## {name}`: 아카이브 본문이 원문과 바이트 동일하지 않다 — 도구가 옮기며 "
            "내용을 건드렸다는 뜻이므로 그대로 진행하면 안 된다."
        )

    return failures


def _print_report(ledger_text: str, path: str) -> None:
    sections = split_sections(ledger_text)
    print(f"{path}: {len(ledger_text.encode('utf-8')):,} bytes · 절 {len(sections)}개")
    blocked = 0
    for section in sections:
        diagnosis = diagnose(ledger_text, section)
        if not diagnosis.is_movable:
            blocked += 1
        mark = "OK " if diagnosis.is_movable else "STOP"
        reason = []
        if diagnosis.enters_inside_fence:
            reason.append("시작 경계 fence 안")
        if diagnosis.exits_inside_fence:
            reason.append("끝 경계 fence 안")
        if diagnosis.comment_opens != diagnosis.comment_closes:
            reason.append("주석 불균형")
        note = f" — {', '.join(reason)}" if reason else ""
        print(
            f"  {mark} L{section.start + 1:>5} fence {diagnosis.fence_markers:>2}개"
            f"({'홀' if diagnosis.fence_parity_is_odd else '짝'}) │ {section.title[:52]}{note}"
        )
    print(
        f"\n제목만 보고 자르면 {blocked}/{len(sections)}개 절에서 경계가 fence 안에 "
        "떨어진다 — 그래서 손으로 고르면 안 된다."
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("section", nargs="?", help="옮길 절 제목(`## ` 뒤 원문 그대로)")
    parser.add_argument("--to", help="아카이브 파일 이름(예: tasks-acceptance-pair-v2.md)")
    parser.add_argument("--label", help="인덱스 표·헤더에 쓸 표시 이름(기본: 절 제목)")
    parser.add_argument("--ledger", default=LEDGER, help=f"원장 경로(기본: {LEDGER})")
    parser.add_argument("--archive-dir", default=ARCHIVE_DIR, help=f"기본: {ARCHIVE_DIR}")
    parser.add_argument("--date", help="헤더·stub에 적을 날짜(기본: 오늘)")
    parser.add_argument("--report", action="store_true", help="절별 fence 진단만 출력")
    parser.add_argument(
        "--apply", action="store_true", help="검산 통과 시 실제로 파일을 쓴다(기본: 검산만)"
    )
    args = parser.parse_args(argv)

    ledger_path = Path(args.ledger)
    if not ledger_path.exists():
        print(f"원장이 없다: {ledger_path}", file=sys.stderr)
        return 2
    ledger_text = ledger_path.read_text(encoding="utf-8")

    if args.report:
        _print_report(ledger_text, str(ledger_path))
        return 0

    if not args.section or not args.to:
        parser.error("절 제목과 `--to <파일이름>`이 둘 다 필요하다 (또는 `--report`)")

    try:
        plan = build_plan(
            ledger_text,
            args.section,
            args.to,
            label=args.label,
            today=args.date,
        )
    except (LookupError, MalformedCheckboxError) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    diagnosis = plan.diagnosis
    print(
        f"`## {plan.section.title}` — 원장 L{plan.section.start + 1}~{plan.section.end} "
        f"({plan.section.end - plan.section.start}줄), fence 마커 {diagnosis.fence_markers}개"
        f"({'홀' if diagnosis.fence_parity_is_odd else '짝'}), 시작 경계 "
        f"{'fence 안' if diagnosis.enters_inside_fence else 'fence 밖'} → 끝 경계 "
        f"{'fence 안' if diagnosis.exits_inside_fence else 'fence 밖'}",
        flush=True,  # 아래 거절 사유(stderr)보다 먼저 보여야 읽는 순서가 맞는다
    )

    failures = check_plan(plan)
    if failures:
        print(
            "\n분리를 거절한다.\n\n"
            + "\n\n".join(failures)
            + "\n\n(선례: 2026-09-13에 제목 기준 분리가 삭제 게이트를 37번 빨갛게 만들고 "
            "되돌려졌다. 원장에서 항목이 조용히 사라지는 경로는 6d671ef1이 이미 한 번 "
            "열었다.)",
            file=sys.stderr,
        )
        return 1

    archive_path = Path(args.archive_dir) / args.to
    print(
        f"검산 통과 — 체크박스 항목 {sum(_fingerprints(ledger_text, source=LEDGER).values())}건이 "
        f"두 파일에 그대로 보존된다. 원장 "
        f"{len(ledger_text.encode('utf-8')):,} → {len(plan.ledger_after.encode('utf-8')):,} bytes, "
        f"아카이브 {len(plan.archive_after.encode('utf-8')):,} bytes."
    )
    if len(plan.archive_after.encode("utf-8")) > MAX_FILE_BYTES:
        print(
            f"경고: 아카이브가 규약 §8 상한({MAX_FILE_BYTES:,} bytes)을 넘는다.",
            file=sys.stderr,
        )

    if not args.apply:
        print("(--apply 없이는 쓰지 않는다.)")
        return 0

    if archive_path.exists():
        print(f"이미 있는 파일을 덮어쓰지 않는다: {archive_path}", file=sys.stderr)
        return 2
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    archive_path.write_text(plan.archive_after, encoding="utf-8", newline="\n")
    ledger_path.write_text(plan.ledger_after, encoding="utf-8", newline="\n")
    print(f"옮겼다: {archive_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
