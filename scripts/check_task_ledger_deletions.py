#!/usr/bin/env python
"""task 원장에서 체크박스 항목이 **조용히 삭제**되는 것을 막는다.

## 왜 필요한가

2026-08-27 `6d671ef1`이 `docs/tasks.md`를 평면화하며 991행을 지웠고, 그 안에
`T-VN-FINAL-REBUILD`의 미체크 해제 조건 B1~B4가 있었다. **다음 날** `b3bbd3a3`이 그
task를 `[x]`로 바꿨다 — 조건이 충족된 것이 아니라 삭제된 것이다. 이번 정체 근본원인
감사에서 "재발 시 피해가 가장 큰 항목"으로 판정됐다
(`docs/reports/map-stall-root-cause-2026-08-31.md` §3 I-7a, 적대 검증 CONFIRMED).

## 규칙 (적대 리뷰 R2-S2/S3/S6/S7 반영 — diff 줄이 아니라 base/HEAD 전체 파일 비교)

1. `docs/tasks.md`: base에 있던 체크박스 task ID가 HEAD에서 사라졌다면, 같은 변경에서
   `docs/tasks-done.md`에 **체크박스(`[x]`) 엔트리**로 추가돼야 한다. 단순 언급(stub)은
   이관이 아니다 — 엔트리 텍스트는 ID 외 실질 서술(40자 이상)을 요구한다.
2. `docs/tasks-acceptance.md` **와 그 아카이브 분리본**
   (`docs/archive/tasks-acceptance-*.md`): base에 있던 체크박스 항목(task/기준 ID)이
   HEAD에서 **두 곳 모두** 사라졌다면, 같은 변경에 **그 ID를 단 체크박스 항목**이
   감시 대상 파일 어딘가에 추가돼 있어야 한다.

   - 아카이브를 근거가 아니라 *감시 집합*으로 보는 이유: 이관을 근거로만 인정하면
     옮겨진 항목이 그 뒤로 영원히 감시 밖이다 — 다음 PR이 아카이브에서 통째로 지워도
     조용하다. 2026-09-16 실측으로 `archive/tasks-acceptance-m05.md`의 P1~P5 다섯 개가
     정확히 그 상태였다(어느 게이트도 그 파일을 읽지 않았다).
   - 근거가 **체크박스**여야 하는 이유: 종전 판정은 순수 부분일치(`any_id not in
     added_text`)였고 `A1`·`V1` 같은 두 글자 기준 ID는 평범한 산문 안에서 우연히
     맞는다. 실제 이관은 언제나 체크박스 줄의 모습을 하고 있다.
   - **감시 단위 (2026-09-16 적대 리뷰로 넓힘)**: 종전에는 항목의 *대표* ID
     (`any_id`) 하나만 셌고, 그래서 **살아 있는 해제 조문을 한 건도 보지 않았다.**
     조문은 `## T-XXX` 아래 `1. [x]` 번호 목록으로 적히는데 (a) 파서가 대시 항목만
     봤고 (b) 조문에는 자기 ID가 없다(ID는 절 제목에 있다). 실측으로 게이트가 세고
     있던 것은 fence 안의 **인용된 task 제목** 쪽이었다 — 정확히 거꾸로였다.
     이제 `_watched_ids()`가 항목의 ID 전부(`watch_ids`: 적힌 ID + 절 귀속 +
     조문 번호)와 `## ` 절 제목이 선언한 task ID(`section_task_ids`)를 합친다.
3. fence/HTML 주석 내부는 항목이 아니다. malformed 체크박스 표기는 그 자체로 오류다
   (`scripts/task_ledger_lint.py`가 파싱 정본).

   fence 안의 인용 제목이 보이지 않는 것은 **버그가 아니라 규약**이다. 그것이 깨져
   있던 동안(`3b11c9757`이 새 절 셋을 아직 닫히지 않은 인용 블록 **안쪽**에 끼워
   넣었다) 원장 3,083줄 중 2,045줄과 `## ` 제목 44개 중 16개가 파서에게 보이지
   않았고, 거기에 `T-VN-LEDGER-ARCHIVE`·`T-VN-QUEUE-QUOTA`·`T-VN-KREX-TPS-FANOUT`이
   들어 있었다.

base ref는 인자로 받고, 없으면 `origin/main`.
"""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from task_ledger_lint import (  # noqa: E402
    MalformedCheckboxError,
    checkbox_task_ids,
    parse_checkboxes,
    section_task_ids,
    watch_ids,
)

TASKS = "docs/tasks.md"
DONE = "docs/tasks-done.md"
ACCEPTANCE = "docs/tasks-acceptance.md"
ARCHIVE_DIR = "docs/archive"


def _git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return result.stdout


def _file_at(ref: str, path: str) -> str:
    try:
        return _git("show", f"{ref}:{path}")
    except subprocess.CalledProcessError:
        return ""  # base에 파일이 없으면 삭제 판정 대상도 없다


def _added_diff_lines(base: str, path: str) -> list[str]:
    lines = _git("diff", f"{base}...HEAD", "--", path).splitlines()
    return [
        line[1:]
        for line in lines
        if line.startswith("+") and not line.startswith("+++")
    ]


def _added_done_entries(base: str) -> dict[str, str]:
    """DONE에 추가된 `[x]` 엔트리: task ID → 연속 추가 줄을 합친 텍스트."""

    added = _added_diff_lines(base, DONE)
    entries: dict[str, list[str]] = {}
    current: str | None = None
    for line in added:
        try:
            items = parse_checkboxes(line, source=DONE)
        except MalformedCheckboxError:
            items = []
        if items and items[0].task_id and items[0].state == "x":
            current = items[0].task_id
            entries.setdefault(current, []).append(items[0].text)
        elif line.strip().startswith("#"):
            # 다음 섹션 헤딩 — 엔트리 경계. (빈 줄은 경계가 아니다: done 관례는
            # 체크박스 헤더와 본문 문단 사이에 빈 줄을 둔다.)
            current = None
        elif current is not None and line.strip():
            entries[current].append(line.strip())
    return {task: " ".join(parts) for task, parts in entries.items()}


def _head_file(head_root: Path, path: str) -> str:
    """HEAD 쪽 내용(없는 파일은 빈 문자열).

    규칙 1이 이미 그러듯 **작업 트리**에서 읽는다 — CI checkout에서는 HEAD와 같다.
    추가 줄은 커밋된 diff(`base...HEAD`)에서만 오므로, 커밋하지 않은 로컬 편집은
    근거로 세어지지 않는다(종전과 같은 성질이다).
    """

    target = head_root / path
    return target.read_text(encoding="utf-8") if target.exists() else ""


def _archive_watch_paths(base: str) -> list[str]:
    """감시 대상 아카이브 = ACCEPTANCE 원장에서 갈라져 나온 분리본들.

    base와 HEAD **양쪽**의 tracked 목록을 합친다. base에만 있으면 이번 변경이 파일째
    지운 경우이고, HEAD에만 있으면 이번 변경이 새로 만든 분리본이다 — 후자를 넣어야
    "이번 PR에서 아카이브로 옮기고 다음 PR에서 지우기"의 첫 단계가 감시 안에서 끝난다.

    `tasks-done-*` 아카이브는 일부러 제외한다. 아카이브는 원본 원장의 감시 수위를
    물려받는데 `docs/tasks-done.md`는 삭제 감시 대상이 아니고(규칙 1은 그것을 *받는
    쪽*으로만 본다), 무엇보다 done 아카이브에는 `P0`·`S1` 같은 짧은 기준 ID가 이미
    들어 있다 — 같은 ID 공간에 합치면 acceptance에서 지워진 `P0`이 done 아카이브의
    `P0` 때문에 살아 있는 것으로 보인다. 감시를 넓히려다 구멍을 내는 쪽이다.
    """

    prefix = f"{ARCHIVE_DIR}/{Path(ACCEPTANCE).stem}-"
    paths: set[str] = set()
    for ref in (base, "HEAD"):
        listing = _git("ls-tree", "-r", "--name-only", ref, "--", ARCHIVE_DIR)
        paths.update(
            name
            for name in listing.splitlines()
            if name.startswith(prefix) and name.endswith(".md")
        )
    return sorted(paths)


def _watched_ids(text: str, *, source: str) -> set[str]:
    """한 파일이 감시 집합에 넣는 ID 전부.

    두 층을 합친다.

    1. 체크박스 항목이 달고 있는 ID(`watch_ids` — task·기준·절 귀속·조문 번호).
       `any_id`만 보면 안 되는 이유는 `watch_ids` docstring에 있다: 조문 텍스트에
       우연히 든 `D2` 같은 두 글자 코드가 대표 ID를 차지해 조문 식별자를 가린다.
    2. `## ` 절 제목이 선언한 task ID(`section_task_ids`). 체크박스가 **하나도 없는**
       절이 이 원장에 실재하기 때문이다 — 해제 조건을 `1. [ ]`가 아니라 맨 번호
       목록으로 적은 절이 그렇고, 그런 절은 통째로 지워도 1층에는 잡히지 않는다.
    """

    ids = set(section_task_ids(text))
    for item in parse_checkboxes(text, source=source):
        ids |= watch_ids(item)
    return ids


def _added_checkbox_ids(base: str, paths: Sequence[str], head_root: Path) -> set[str]:
    """추가된 줄에 실린 **체크박스 항목**의 ID 집합 — 삭제 근거로 인정되는 것.

    diff는 줄 단위라 그 줄이 fence 안이었는지 알 수 없다. 그래서 같은 ID가 HEAD 파일을
    fence 인지 파서로 읽었을 때도 항목으로 남아 있을 때만 인정한다 — 코드 블록 안에
    `- [x] A1`을 적어 근거를 위조하는 경로를 닫는다.
    """

    justified: set[str] = set()
    for path in paths:
        live = _watched_ids(_head_file(head_root, path), source=path)
        if not live:
            continue
        for line in _added_diff_lines(base, path):
            try:
                items = parse_checkboxes(line, source=path)
            except MalformedCheckboxError:
                # 한 줄만 떼어 보면 오탐이 가능하다. malformed 표기 자체는 아래 전체
                # 파일 파싱이 fail-closed로 잡으므로 여기서 다시 세지 않는다.
                continue
            for item in items:
                # 한 줄만 보면 절 문맥이 없으므로 `watch_ids`는 줄에 적힌 ID만 낸다.
                # 옮긴 조문의 귀속 ID는 `head_ids`(파일 전체 파싱) 쪽에서 살아난다.
                justified |= watch_ids(item) & live
    return justified


def _resolve_base(candidates: list[str]) -> str | None:
    """첫 해석 가능한 base ref — push 이벤트의 `github.event.before`는 브랜치 생성
    시 all-zero라 해석 불가일 수 있다(R2-S11). 그때는 다음 후보(origin/main)."""

    for candidate in candidates:
        if not candidate or set(candidate) == {"0"}:
            continue
        probe = subprocess.run(
            ["git", "rev-parse", "--verify", "--quiet", f"{candidate}^{{commit}}"],
            capture_output=True,
            text=True,
        )
        if probe.returncode == 0:
            return candidate
    return None


def main() -> int:
    base = _resolve_base(sys.argv[1:] or ["origin/main"]) or "origin/main"
    failures: list[str] = []
    try:
        head_root = Path(_git("rev-parse", "--show-toplevel").strip())

        # ── 규칙 1: tasks.md 삭제 → done 이관(실질 엔트리) ──────────────
        base_tasks = checkbox_task_ids(_file_at(base, TASKS), source=f"{base}:{TASKS}")
        head_tasks_text = (head_root / TASKS).read_text(encoding="utf-8")
        head_tasks = checkbox_task_ids(head_tasks_text, source=TASKS)
        removed = base_tasks - head_tasks
        if removed:
            done_entries = _added_done_entries(base)
            for task in sorted(removed):
                entry = done_entries.get(task)
                if entry is None:
                    failures.append(
                        f"{TASKS}: {task} 체크박스가 삭제됐는데 {DONE}에 `[x]` 이관 "
                        "엔트리가 없다"
                    )
                elif len(entry.replace(task, "")) < 40:
                    failures.append(
                        f"{DONE}: {task} 이관 엔트리가 stub이다 — 무엇이 어떻게 "
                        "완료됐는지 실질 서술(40자 이상)을 남길 것"
                    )

        # ── 규칙 2: acceptance(+아카이브) 삭제 → 같은 ID의 체크박스가 근거 ──
        watched = [ACCEPTANCE, *_archive_watch_paths(base)]
        # ID → base에서 그 항목이 있던 파일. 한 ID가 여러 절에 있을 수 있어
        # (지금 `C1`·`C2`가 그렇다) 첫 자리만 기억하고 메시지도 한 번만 낸다.
        base_locations: dict[str, str] = {}
        for path in watched:
            for watched_id in sorted(
                _watched_ids(_file_at(base, path), source=f"{base}:{path}")
            ):
                base_locations.setdefault(watched_id, path)
        head_ids: set[str] = set()
        for path in watched:
            head_ids |= _watched_ids(_head_file(head_root, path), source=path)
        # 근거를 받는 자리는 감시 집합 + 두 원장뿐이다. 감시 밖 파일에 다시 적은 것을
        # 근거로 인정하면 "감시되지 않는 이름으로 옮기기"가 곧 조용한 탈출구가 된다.
        justified = _added_checkbox_ids(base, [*watched, TASKS, DONE], head_root)
        archive_glob = f"{ARCHIVE_DIR}/{Path(ACCEPTANCE).stem}-*.md"
        for watched_id, path in sorted(base_locations.items()):
            if watched_id in head_ids or watched_id in justified:
                continue
            failures.append(
                f"{path}: {watched_id} 항목이 삭제됐는데 같은 변경 어디에도 그 ID를 단 "
                f"체크박스가 없다 — 옮겼다면 감시 대상({ACCEPTANCE}, {archive_glob}, "
                f"{TASKS}, {DONE}) 안의 옮긴 자리를, 폐기했다면 "
                f"`- [x] {watched_id} — 폐기 사유` 한 줄을 남길 것"
            )
    except MalformedCheckboxError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as exc:
        print(f"base {base!r}와의 비교에 실패했다: {exc}", file=sys.stderr)
        return 2

    if failures:
        print(
            "\n".join(failures)
            + "\n(선례: 6d671ef1 평면화가 해제 조건을 지운 다음 날 b3bbd3a3이 그 "
            "task를 완료 처리했다 — 조건이 충족된 게 아니라 사라진 것이다.)",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
