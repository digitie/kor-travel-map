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
2. `docs/tasks-acceptance.md`: base에 있던 체크박스 항목(task/기준 ID)이 HEAD에서
   사라졌다면, 그 ID가 같은 diff의 **추가된 줄** 어딘가에 이름으로 등장해야 한다 —
   삭제의 근거를 적지 않고 기준을 지울 수 없다.
3. fence/HTML 주석 내부는 항목이 아니다. malformed 체크박스 표기는 그 자체로 오류다
   (`scripts/task_ledger_lint.py`가 파싱 정본).

base ref는 인자로 받고, 없으면 `origin/main`.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from task_ledger_lint import (  # noqa: E402
    MalformedCheckboxError,
    checkbox_task_ids,
    parse_checkboxes,
)

TASKS = "docs/tasks.md"
DONE = "docs/tasks-done.md"
ACCEPTANCE = "docs/tasks-acceptance.md"


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

        # ── 규칙 2: tasks-acceptance.md 삭제 → 추가 줄에 ID 명시 ────────
        base_acceptance = parse_checkboxes(
            _file_at(base, ACCEPTANCE), source=f"{base}:{ACCEPTANCE}"
        )
        head_acceptance_path = head_root / ACCEPTANCE
        head_acceptance_text = (
            head_acceptance_path.read_text(encoding="utf-8")
            if head_acceptance_path.exists()
            else ""
        )
        head_ids = {
            item.any_id
            for item in parse_checkboxes(head_acceptance_text, source=ACCEPTANCE)
            if item.any_id
        }
        added_text = "\n".join(
            _added_diff_lines(base, ACCEPTANCE)
            + _added_diff_lines(base, TASKS)
            + _added_diff_lines(base, DONE)
        )
        for item in base_acceptance:
            if item.any_id is None or item.any_id in head_ids:
                continue
            if item.any_id not in added_text:
                failures.append(
                    f"{ACCEPTANCE}: {item.any_id} 항목이 삭제됐는데 같은 변경의 추가 "
                    "줄 어디에도 그 ID가 없다 — 삭제 근거(귀속/폐기 사유)를 적을 것"
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
