"""task 원장(markdown) 파싱의 단일 정본 — 게이트 3종이 공유한다.

## 왜 모듈인가 (적대 리뷰 R2-S2/S3/S6)

체크박스 정규식이 게이트마다 손 사본으로 존재하면 각자 다른 구멍을 갖는다 —
삭제 게이트는 bold/들여쓰기 변형을 놓치고, coverage 게이트는 substring 매칭으로
우회되고, 둘 다 코드 fence 안의 "체크박스처럼 보이는 줄"을 실제 항목으로 오인한다.
여기의 파서가 유일한 정의이고, 게이트는 전부 이것을 import한다.

## 파싱 규약

- fence(```/~~~)와 HTML 주석(<!-- -->) 내부는 내용이 아니다 — 제거 후 파싱.
- 체크박스 줄: 들여쓰기 허용, 마커는 `-` **또는 `1.` 같은 번호**,
  상태는 `[ ]`/`[x]`/`[~]`/`[/]`.
- ID: 항목 텍스트 안의 `T-...`(bold/backtick 감쌈 허용) 또는 `B1` 같은
  짧은 기준 코드. 없으면 **자기가 속한 `## ` 절**에서 물려받는다(아래).
- **malformed fail-closed**: `- [y]`, `-[ ]`, `1.[ ]` 처럼 체크박스를 시도했지만
  규약을 벗어난 줄은 파싱 실패가 아니라 **오류**다 — 변형 표기로 게이트를
  우회하는 경로를 막는다.

## 왜 번호 목록과 절 귀속이 필요한가 (2026-09-16 적대 리뷰)

살아 있는 해제 조건은 이 저장소에서 `## T-XXX` 아래 **번호 목록**으로 적힌다
(`1. [x]` / `2. [ ]`). 그런데 종전 `CHECKBOX_LINE`은 `- [ ]` 대시 항목만 봤고,
ID는 항목 **텍스트 안**에서만 찾았다. 번호 조문에는 자기 ID가 없다 — ID는 절
제목에 있다. 그래서 삭제 게이트(`any_id is None`이면 건너뛴다)에게 살아 있는
조문은 처음부터 존재하지 않았다.

동시에 fence가 깨져 있던 동안 게이트가 실제로 세고 있던 것은 **fence 안의 인용된
task 제목**이었다(`` ```markdown `` 블록 안의 `- [x] T-VN-39-DEPLOY — …`). 즉
지켜야 할 것은 못 보고 지키면 안 되는 것을 보고 있었다 — 정확히 거꾸로였다.

그래서 셋을 함께 고친다.

1. 번호 목록도 정식 체크박스로 인정한다(`CHECKBOX_LINE`).
2. 번호 조문은 자기가 속한 `## ` 절의 task ID를 **물려받고**(`section_task_id`),
   목록 번호로 **자기 식별자**를 갖는다(`clause_id` = `T-XXX#2`).
3. fence 안의 인용 제목은 그대로 보이지 않는다 — 그것이 옳은 의미이고,
   `docs/tasks-acceptance.md`의 fence 복구가 그 성질을 되돌려 놓았다.

### `task_id`를 덮어쓰지 않고 새 필드를 쓰는 이유

`task_id`는 **그 줄에 실제로 적힌 ID**라는 뜻을 지킨다. 여기에 물려받은 값을
집어넣으면 `checkbox_task_ids()`가 한 절의 조문 수만큼 같은 task를 세게 되고,
그 함수를 쓰는 `docs/tasks.md` 규약 검사(완료 표시·마커 검사)의 의미가 조용히
바뀐다. 물려받은 값은 별도 필드로 싣고, **감시 집합을 만드는 쪽**(`watch_ids`)이
그것을 합친다 — 넓히는 책임을 소비자가 명시적으로 지게 한다.

### 절 ID **와** 조문 번호를 둘 다 싣는 이유

절 ID만 실으면 조문 2를 지워도 조문 1·3이 남아 절 ID가 살아 있으므로 게이트가
조용하다. 조문 식별자만 실으면, fence가 고쳐지며 인용 제목이 사라진 자리에서
`T-VN-39-DEPLOY` 같은 **task ID 자체**가 감시 집합에서 빠져 나가 이번 변경이
"삭제"로 오판된다. 둘 다 실어야 조문 단위 삭제가 빨개지면서 task 단위 연속성도
유지된다.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass

#: 정식 체크박스 상태 집합. `/`는 진행 중 표기 관례.
CHECKBOX_STATES = frozenset(" x~/")

#: 정식 체크박스 줄 — 들여쓰기 허용, 마커와 대괄호 사이 공백 1개 이상.
#:
#: 마커는 `-` 또는 `1.` 같은 **번호**다. 번호를 세 자리로 제한하는 것은 `2026.`
#: 같은 연도 표기가 목록 마커로 읽히는 것을 막기 위해서다.
CHECKBOX_LINE = re.compile(
    r"^(?P<indent>\s*)(?:-|(?P<number>\d{1,3})\.)\s+\[(?P<state>[ x~/])\]\s+(?P<text>.*)$"
)

#: 체크박스를 "시도"한 것으로 보이는 줄 — 정식 규약과의 차집합이 malformed.
#:
#: `CHECKBOX_LINE`과 **대칭으로** 넓힌다. 한쪽만 넓히면 `1. [y]`가 정식도 아니고
#: 시도도 아닌 것이 되어 조용히 사라진다 — 그것이 바로 이 상수가 막으려던 우회다.
#: (넓히기 전후 실측: 감시 대상 원장 7개 파일 × base/HEAD 양쪽에서 새로 드러난
#: malformed 줄 **0건**. 드러났다면 덮지 말고 보고할 것.)
CHECKBOX_ATTEMPT = re.compile(r"^\s*(?:-|\d{1,3}\.)\s*\[[^\]]{0,3}\]")

#: 항목 텍스트에서 task/기준 ID 추출. bold(**)·backtick(`) 감쌈 허용.
_TASK_ID = re.compile(r"[*`]*\b(T-[A-Z0-9][A-Z0-9-]*)\b")
_CRITERION_ID = re.compile(r"[*`]*\b([A-Z]\d{1,2})\b")

#: 줄에 **직접 적힌** 조문 식별자 — `T-VN-LEDGER-ARCHIVE#2` 꼴.
#:
#: 게이트가 삭제 근거로 요구하는 문구가 바로 이 모양인데 `_TASK_ID`는 `#`에서
#: 멈추므로, 그 줄을 파싱해도 `T-VN-LEDGER-ARCHIVE`만 나왔다. 즉 **게이트가
#: 시키는 대로 적어도 매칭되지 않아** task를 닫는 PR이 통과할 수 없었다
#: (2026-09-16 적대 리뷰 N1). 조문 식별자는 `clause_id`로 파생되기도 하고
#: 이렇게 손으로 적히기도 하며, 둘은 같은 이름이어야 한다.
_WRITTEN_CLAUSE_ID = re.compile(r"[*`]*\b(T-[A-Z0-9][A-Z0-9-]*#\d{1,3})\b")

#: task 하나가 소유하는 절의 제목. `### `/`#### `는 절이 아니라 절 **안**의
#: 소제목이므로 `##` 바로 뒤 공백을 요구해 배제한다
#: (`scripts/archive_task_ledger_section.py`의 `_HEADING`과 같은 문법이다 —
#: 분리 도구가 자르는 단위와 귀속 단위가 어긋나면 옮길 때 ID가 바뀐다).
_SECTION_HEADING = re.compile(r"^## (?P<title>.+?)\s*$")

_FENCE = re.compile(r"^(```|~~~)")
_HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)


@dataclass(frozen=True)
class CheckboxItem:
    line_no: int  # fence 제거 **전** 원본 파일의 1-기반 줄 번호
    indent: int
    state: str
    task_id: str | None  # **그 줄에 적힌** task ID. 물려받은 값은 여기 넣지 않는다.
    criterion_id: str | None
    text: str
    section_task_id: str | None = None  # 이 항목을 감싸는 `## ` 절의 task ID
    clause_number: int | None = None  # 번호 목록 마커(`2. [ ]`의 2). 대시 항목은 None
    written_clause_id: str | None = None  # 줄에 **직접 적힌** `T-XXX#2` 표기

    @property
    def clause_id(self) -> str | None:
        """번호 조문의 자기 식별자 — `T-VN-LEDGER-ARCHIVE#2` 꼴.

        절 ID로 한정한다. 번호만으로는 절마다 `2`가 있어 충돌하고, 절 ID만으로는
        조문 2를 지워도 1·3이 남아 삭제가 보이지 않는다.

        번호를 쓰는 이유는 그것이 **문서에 이미 적혀 있는** 안정된 이름이기
        때문이다. 순서로 매기면 조문을 하나 끼워 넣을 때마다 뒤가 전부 다른
        식별자가 되어 정당한 편집이 삭제로 보인다.
        """
        if self.section_task_id is None or self.clause_number is None:
            return None
        return f"{self.section_task_id}#{self.clause_number}"

    @property
    def any_id(self) -> str | None:
        """이 항목을 사람에게 부를 때 쓰는 **대표 이름** 하나.

        줄에 적힌 것이 먼저고, 없으면 물려받은 것으로 떨어진다. 물려받은 값까지
        보는 이유는 종전 게이트가 `any_id is None`인 항목을 건너뛰었기 때문이다 —
        번호 조문은 전부 그 상태였고, 그래서 살아 있는 해제 조건이 한 건도
        감시되지 않았다. 여기서 `None`으로 두면 그 버그가 그대로 돌아온다.

        **감시 집합을 이것으로 만들지 말 것.** 대표는 하나뿐이라 가려지는 ID가
        생긴다 — 조문 텍스트에 `D2` 같은 두 글자 코드가 우연히 들어 있으면
        `criterion_id`가 이겨서 조문 식별자가 사라진다. 감시 집합은
        `watch_ids()`가 만들고, 삭제 게이트는 그쪽을 쓴다.
        """
        return self.task_id or self.criterion_id or self.clause_id or self.section_task_id


def watch_ids(item: CheckboxItem) -> set[str]:
    """이 항목이 감시 집합에 넣는 ID **전부** — 대표 하나가 아니다.

    삭제 게이트가 "base에 있던 ID가 HEAD에 없다"를 판정하는 단위다.

    - `task_id`/`criterion_id`: 줄에 직접 적힌 ID. 종전 감시 단위 그대로다.
    - `clause_id`: 조문 **하나**의 삭제. **결박 확인됨** — 이 항만 빼고 재면
      `T-VN-LEDGER-ARCHIVE` 조문 2·3을 지워도 게이트가 초록이다(조문 1이 남아
      절 ID가 살아 있다). 2026-09-16 변이 실측.
    - `section_task_id`: 이 항목이 어느 task의 조건인가. **오늘 이 값만 빼면
      아무것도 빨개지지 않는다** — 삭제 게이트가 `section_task_ids()`로 같은
      집합을 따로 더하기 때문이다(변이 실측: 오탐 0건). 그래도 싣는 이유는
      `watch_ids`가 **혼자서도 옳아야** 하기 때문이다. 절 층을 더하지 않는
      소비자가 이 함수만 보고 감시 집합을 만들면, 이 값이 없을 때 조문을 가진
      task의 연속성이 조용히 사라진다.

    귀속 자체(`section_task_id`를 채우는 일)는 전혀 다른 문제다. 그것을 끄면
    base→HEAD 전이에서 **8건**이 오탐으로 빨개진다 — 조문이 소유자를 잃으면
    fence 복구로 사라진 인용 제목을 대신할 것이 없어지기 때문이다.
    """

    return {
        value
        for value in (
            item.task_id,
            item.criterion_id,
            item.section_task_id,
            item.clause_id,
            item.written_clause_id,
        )
        if value is not None
    }


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


def _attributed_lines(text: str) -> Iterator[tuple[int, str, str | None]]:
    """(줄 번호, 줄, 그 줄이 속한 `## ` 절의 task ID)를 내용 줄마다 낸다.

    귀속 규칙의 **유일한 정의**다. `parse_checkboxes`와 `section_task_ids`가 이것을
    공유해야 하는 이유는 단순하다 — 둘이 각자 절을 세면 한쪽만 고쳐질 수 있고,
    그때 게이트는 "조문은 A절 것, 절은 B절 것"이라는 모순된 감시 집합을 갖는다.

    절 제목은 `strip_non_content`가 남긴 줄에서만 읽는다. fence 안의 인용 제목
    (`## T-101 — …`)이 귀속 문맥을 바꾸면, 인용문이 그 뒤에 오는 **살아 있는**
    조문의 소유자를 정하게 된다.
    """

    section_task_id: str | None = None
    for index, line in enumerate(strip_non_content(text), start=1):
        if line is None:
            continue
        heading = _SECTION_HEADING.match(line)
        if heading:
            found = _TASK_ID.search(heading.group("title"))
            section_task_id = found.group(1) if found else None
        yield index, line, section_task_id


def section_task_ids(text: str) -> set[str]:
    """`## ` 절을 소유한 task ID 집합 — 체크박스가 하나도 없는 절도 포함한다.

    `parse_checkboxes`의 동반 함수다. 필요한 이유는 실측에서 나왔다: 이 저장소의
    해제 조건 중 상당수는 **체크박스가 아예 없는 번호 목록**으로 적혀 있다
    (`1. D2가 완주한 뒤 …`). 그런 절은 파싱되는 항목이 0건이라, 절을 통째로 지워도
    체크박스만 세는 감시에는 아무 일도 일어나지 않는다 — `T-VN-D2-RESIDUE`·
    `T-VN-CURATION-SEAL-ACL`·`T-VN-39-D2-FIXTURE`·`T-VN-39-PROVIDER-PAGINATION`·
    `T-VN-39` 다섯이 2026-09-16 실측에서 정확히 그 상태였다.

    절 제목은 그 task의 판정 근거가 **어디에 사는지**를 가리키는 마지막 표식이다.
    표식이 사라지면 근거도 사라진 것으로 본다.
    """

    return {
        section
        for _, _, section in _attributed_lines(text)
        if section is not None
    }


def parse_checkboxes(text: str, *, source: str = "<ledger>") -> list[CheckboxItem]:
    """정식 체크박스 항목을 전부 파싱한다. malformed 시도는 오류."""

    items: list[CheckboxItem] = []
    for index, line, section_task_id in _attributed_lines(text):
        if _SECTION_HEADING.match(line):
            continue
        match = CHECKBOX_LINE.match(line)
        if match:
            body = match.group("text")
            task = _TASK_ID.search(body)
            criterion = _CRITERION_ID.search(body)
            number = match.group("number")
            items.append(
                CheckboxItem(
                    line_no=index,
                    indent=len(match.group("indent")),
                    state=match.group("state"),
                    task_id=task.group(1) if task else None,
                    criterion_id=criterion.group(1) if criterion else None,
                    text=body.strip(),
                    section_task_id=section_task_id,
                    clause_number=int(number) if number is not None else None,
                    written_clause_id=(
                        written.group(1) if (written := _WRITTEN_CLAUSE_ID.search(body)) else None
                    ),
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
    """체크박스 **줄에 직접 실린** task ID 집합(fence/주석 제외).

    물려받은 `section_task_id`는 **일부러 세지 않는다.** 이 함수의 소비자는
    `docs/tasks.md`의 규약 검사(`[x]`가 활성 원장에 남았는가, 정의되지 않은
    마커를 쓰는가)와 삭제 게이트 규칙 1인데, 물려받은 값을 합치면 한 절의 조문
    수만큼 같은 task가 중복되고 "그 줄의 상태"가 task의 상태로 잘못 읽힌다.
    감시 집합을 넓히는 일은 `watch_ids()`가 명시적으로 한다.

    (`docs/tasks.md`에는 `## ` 절 자체가 없어 현재 두 해석의 결과가 같다.
    같다는 사실에 기대지 않고 뜻을 갈라 둔다 — 절이 생기는 날 조용히 달라진다.)
    """

    return {
        item.task_id
        for item in parse_checkboxes(text, source=source)
        if item.task_id is not None
    }
