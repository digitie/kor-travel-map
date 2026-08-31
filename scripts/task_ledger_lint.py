"""task 원장(markdown) 파싱의 단일 정본 — 게이트 3종이 공유한다.

## 왜 모듈인가 (적대 리뷰 R2-S2/S3/S6)

체크박스 정규식이 게이트마다 손 사본으로 존재하면 각자 다른 구멍을 갖는다 —
삭제 게이트는 bold/들여쓰기 변형을 놓치고, coverage 게이트는 substring 매칭으로
우회되고, 둘 다 코드 fence 안의 "체크박스처럼 보이는 줄"을 실제 항목으로 오인한다.
여기의 파서가 유일한 정의이고, 게이트는 전부 이것을 import한다.

## 파싱 규약

- fence(```/~~~)와 HTML 주석(<!-- -->) 내부는 내용이 아니다 — 제거 후 파싱.
- 체크박스 줄: 들여쓰기 허용, `- [ ]`/`- [x]`/`- [~]`/`- [/]`.
- ID: 항목 텍스트 안의 `T-...`(bold/backtick 감쌈 허용) 또는 `B1` 같은
  짧은 기준 코드. 없으면 None(서술형 하위 기준).
- **malformed fail-closed**: `- [y]`, `-[ ]` 처럼 체크박스를 시도했지만 규약을
  벗어난 줄은 파싱 실패가 아니라 **오류**다 — 변형 표기로 게이트를 우회하는
  경로를 막는다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: 정식 체크박스 상태 집합. `/`는 진행 중 표기 관례.
CHECKBOX_STATES = frozenset(" x~/")

#: 정식 체크박스 줄 — 들여쓰기 허용, 마커와 대괄호 사이 공백 1개 이상.
CHECKBOX_LINE = re.compile(r"^(?P<indent>\s*)-\s+\[(?P<state>[ x~/])\]\s+(?P<text>.*)$")

#: 체크박스를 "시도"한 것으로 보이는 줄 — 정식 규약과의 차집합이 malformed.
CHECKBOX_ATTEMPT = re.compile(r"^\s*-\s*\[[^\]]{0,3}\]")

#: 항목 텍스트에서 task/기준 ID 추출. bold(**)·backtick(`) 감쌈 허용.
_TASK_ID = re.compile(r"[*`]*\b(T-[A-Z0-9][A-Z0-9-]*)\b")
_CRITERION_ID = re.compile(r"[*`]*\b([A-Z]\d{1,2})\b")

_FENCE = re.compile(r"^(```|~~~)")
_HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)


@dataclass(frozen=True)
class CheckboxItem:
    line_no: int  # fence 제거 **전** 원본 파일의 1-기반 줄 번호
    indent: int
    state: str
    task_id: str | None
    criterion_id: str | None
    text: str

    @property
    def any_id(self) -> str | None:
        return self.task_id or self.criterion_id


class MalformedCheckboxError(ValueError):
    """체크박스를 시도했지만 규약을 벗어난 줄 — 우회 방지를 위해 fail-closed."""


def strip_non_content(text: str) -> list[str | None]:
    """fence·HTML 주석을 제거하되 줄 번호를 보존한다(제거 줄은 None)."""

    without_comments = _HTML_COMMENT.sub(lambda m: "\n" * m.group(0).count("\n"), text)
    lines: list[str | None] = []
    in_fence = False
    fence_marker = ""
    for line in without_comments.splitlines():
        fence = _FENCE.match(line.strip())
        if fence:
            if not in_fence:
                in_fence = True
                fence_marker = fence.group(1)
            elif line.strip().startswith(fence_marker):
                in_fence = False
            lines.append(None)
            continue
        lines.append(None if in_fence else line)
    return lines


def parse_checkboxes(text: str, *, source: str = "<ledger>") -> list[CheckboxItem]:
    """정식 체크박스 항목을 전부 파싱한다. malformed 시도는 오류."""

    items: list[CheckboxItem] = []
    for index, line in enumerate(strip_non_content(text), start=1):
        if line is None:
            continue
        match = CHECKBOX_LINE.match(line)
        if match:
            body = match.group("text")
            task = _TASK_ID.search(body)
            criterion = _CRITERION_ID.search(body)
            items.append(
                CheckboxItem(
                    line_no=index,
                    indent=len(match.group("indent")),
                    state=match.group("state"),
                    task_id=task.group(1) if task else None,
                    criterion_id=criterion.group(1) if criterion else None,
                    text=body.strip(),
                )
            )
            continue
        if CHECKBOX_ATTEMPT.match(line):
            raise MalformedCheckboxError(
                f"{source}:{index}: 체크박스 규약을 벗어난 줄이다 — "
                f"`- [ ]`/`- [x]`/`- [~]`/`- [/]`만 허용: {line.strip()[:80]!r}"
            )
    return items


def checkbox_task_ids(text: str, *, source: str = "<ledger>") -> set[str]:
    """체크박스 줄에 실린 task ID 집합(fence/주석 제외)."""

    return {
        item.task_id
        for item in parse_checkboxes(text, source=source)
        if item.task_id is not None
    }
