#!/usr/bin/env python3
"""Fail if committed docs leak prod endpoint details (domain or private IP).

Durable guard for #508: production domains (`*.digitie.mywire.org`) and
private host IPs (RFC1918 `192.168.x.x`) must live only in gitignored
.env/.env.prod/ops notes, never in tracked docs. Real values are redacted
to placeholders (`<prod-host-alias>` / `<prod-host-ip>` / `<*-host>`).

Scans tracked files under docs/ (or, in pre-commit, the staged docs files
passed as arguments). Exits non-zero on any hit so the commit / CI fails.
"""

from __future__ import annotations

import re
import subprocess
import sys

# Production domain and RFC1918 192.168.x.x private host IP.
FORBIDDEN_PATTERNS = [
    (re.compile(r"digitie\.mywire\.org"), "prod domain (use a <*-host> placeholder)"),
    (re.compile(r"\b192\.168\.\d{1,3}\.\d{1,3}\b"), "private host IP (use <prod-host-ip>)"),
]


def normalize_path(path: str) -> str:
    return path.replace("\\", "/").removeprefix("./")


def is_docs_path(path: str) -> bool:
    normalized = normalize_path(path)
    return normalized.startswith("docs/") and normalized.endswith((".md", ".mdx", ".txt", ".rst"))


def tracked_docs() -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", "docs/"],
        check=True,
        capture_output=True,
        text=True,
    )
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def candidate_paths(argv: list[str]) -> list[str]:
    # pre-commit passes staged filenames as args; CI runs with no args.
    explicit = [p for p in argv if is_docs_path(p)]
    if explicit:
        return explicit
    return [p for p in tracked_docs() if is_docs_path(p)]


def scan(path: str) -> list[str]:
    hits: list[str] = []
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            for lineno, line in enumerate(handle, start=1):
                for pattern, why in FORBIDDEN_PATTERNS:
                    if pattern.search(line):
                        hits.append(f"  {path}:{lineno}: {why}")
    except FileNotFoundError:
        return []
    return hits


def main(argv: list[str]) -> int:
    hits: list[str] = []
    for path in candidate_paths(argv):
        hits.extend(scan(path))

    if not hits:
        return 0

    print(
        "prod endpoint details leaked into committed docs (#508 redaction guard):",
        file=sys.stderr,
    )
    for hit in hits:
        print(hit, file=sys.stderr)
    print(
        "Replace with placeholders (<prod-host-alias> / <prod-host-ip> / <*-host>); "
        "real values belong in gitignored .env/.env.prod / ops notes.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
