#!/usr/bin/env python3
"""Require docs/journal.md when staged source or test files change."""

from __future__ import annotations

import os
import subprocess
import sys

JOURNAL_PATH = "docs/journal.md"


def normalize_path(path: str) -> str:
    return path.replace("\\", "/").removeprefix("./")


def is_source_or_test_path(path: str) -> bool:
    normalized = normalize_path(path)
    return (
        normalized.startswith(("src/", "tests/"))
        or "/src/" in normalized
        or "/tests/" in normalized
    )


def requires_journal_update(paths: list[str]) -> bool:
    normalized_paths = {normalize_path(path) for path in paths}
    if JOURNAL_PATH in normalized_paths:
        return False
    # 규약 §8 분리 직후에는 당월 archive shard에 쓰는 것도 기록이다 — 이걸 인정하지
    # 않으면 hook이 분리하자마자 live 파일을 도로 부풀린다.
    if any(path.startswith("docs/archive/journal-") for path in normalized_paths):
        return False
    return any(is_source_or_test_path(path) for path in normalized_paths)


def staged_paths() -> list[str]:
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
        check=True,
        capture_output=True,
        text=True,
    )
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def main() -> int:
    if os.environ.get("BYPASS") == "1":
        return 0

    paths = staged_paths()
    if not requires_journal_update(paths):
        return 0

    watched = [path for path in paths if is_source_or_test_path(path)]
    print("docs/journal.md update required for staged source/test changes.", file=sys.stderr)
    print(
        "Add a journal entry, or use BYPASS=1 for a one-time intentional bypass.", file=sys.stderr
    )
    for path in watched[:20]:
        print(f"  - {path}", file=sys.stderr)
    if len(watched) > 20:
        print(f"  ... and {len(watched) - 20} more", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
