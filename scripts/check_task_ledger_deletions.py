#!/usr/bin/env python
"""task 원장에서 체크박스 줄이 **조용히 삭제**되는 것을 막는다.

## 왜 필요한가

2026-08-27 `6d671ef1`이 `docs/tasks.md`를 평면화하며 991행을 지웠고, 그 안에
`T-VN-FINAL-REBUILD`의 미체크 해제 조건 B1~B4가 있었다. **다음 날** `b3bbd3a3`이 그
task를 `[x]`로 바꿨다 — 조건이 충족된 것이 아니라 삭제된 것이다. 이번 정체 근본원인
감사에서 "재발 시 피해가 가장 큰 항목"으로 판정됐다
(`docs/reports/map-stall-root-cause-2026-08-31.md` §3 I-7a, 적대 검증 CONFIRMED).

## 규칙

base와의 diff에서 `docs/tasks.md`의 체크박스 줄(`- [ ]`/`- [~]`/`- [x]`)이 삭제됐다면,
그 줄의 task ID가 다음 중 하나를 만족해야 한다.

1. `docs/tasks.md`에 여전히 존재한다(줄 편집이지 삭제가 아니다), 또는
2. 같은 diff에서 `docs/tasks-done.md`에 **추가**됐다(완료 이관).

git과 stdlib만 쓴다. base ref는 인자로 받고, 없으면 `origin/main`.
"""

from __future__ import annotations

import re
import subprocess
import sys

TASKS = "docs/tasks.md"
DONE = "docs/tasks-done.md"
CHECKBOX = re.compile(r"^-\s*\[[ x~/]\]\s*\*{0,2}(T[-A-Z0-9]+)")


def _diff(base: str, path: str) -> list[str]:
    result = subprocess.run(
        ["git", "diff", f"{base}...HEAD", "--", path],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return result.stdout.splitlines()


def _task_id(line: str) -> str | None:
    match = CHECKBOX.match(line.strip())
    return match.group(1) if match else None


def main() -> int:
    base = sys.argv[1] if len(sys.argv) > 1 else "origin/main"
    try:
        deleted = {
            task
            for line in _diff(base, TASKS)
            if line.startswith("-") and not line.startswith("---")
            and (task := _task_id(line[1:])) is not None
        }
    except subprocess.CalledProcessError as exc:
        print(f"base {base!r}와의 diff를 얻지 못했다: {exc}", file=sys.stderr)
        return 2
    if not deleted:
        return 0

    still_open = set()
    with open(TASKS, encoding="utf-8") as handle:
        for line in handle:
            task = _task_id(line)
            if task:
                still_open.add(task)

    added_to_done = {
        task
        for line in _diff(base, DONE)
        if line.startswith("+") and not line.startswith("+++")
        and (task := _task_id(line[1:])) is not None
    }

    orphaned = sorted(deleted - still_open - added_to_done)
    if orphaned:
        print(
            "docs/tasks.md에서 체크박스 줄이 삭제됐는데 docs/tasks-done.md에 대응 이관이 "
            f"없다: {orphaned}\n"
            "완료면 tasks-done.md에 엔트리를 추가하고, 재구성이면 같은 ID의 줄을 "
            "tasks.md에 남길 것. (선례: 6d671ef1 평면화가 해제 조건을 지운 다음 날 "
            "b3bbd3a3이 그 task를 완료 처리했다 — 조건이 충족된 게 아니라 사라진 것이다.)",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
