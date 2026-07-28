"""아카이브 이동으로 깨진 Markdown 상대 링크를 영구 차단한다."""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

_REPO_ROOT = Path(__file__).resolve().parents[2]
_ARCHIVE_ROOT = _REPO_ROOT / "docs" / "archive"
_INLINE_LINK = re.compile(r"!?\[[^\]]*\]\((?:<([^>]+)>|([^\s)]+))(?:\s+[\"'][^)]*[\"'])?\)")
_REFERENCE_LINK = re.compile(r"^\s{0,3}\[[^\]]+\]:\s*(?:<([^>]+)>|(\S+))")
_INLINE_CODE = re.compile(r"`+[^`]*`+")


def _markdown_destinations(document: Path) -> list[tuple[int, str]]:
    destinations: list[tuple[int, str]] = []
    fence: str | None = None

    for line_number, raw_line in enumerate(
        document.read_text(encoding="utf-8").splitlines(), start=1
    ):
        stripped = raw_line.lstrip()
        fence_match = re.match(r"(`{3,}|~{3,})", stripped)
        if fence_match is not None:
            marker = fence_match.group(1)
            if fence is None:
                fence = marker[0]
            elif marker[0] == fence:
                fence = None
            continue
        if fence is not None:
            continue

        line = _INLINE_CODE.sub("", raw_line)
        for match in _INLINE_LINK.finditer(line):
            destinations.append((line_number, match.group(1) or match.group(2)))
        reference = _REFERENCE_LINK.match(line)
        if reference is not None:
            destinations.append((line_number, reference.group(1) or reference.group(2)))

    return destinations


def _local_target(document: Path, destination: str) -> Path | None:
    parsed = urlsplit(destination)
    if parsed.scheme or parsed.netloc or not parsed.path or parsed.path.startswith("/"):
        return None
    return (document.parent / unquote(parsed.path)).resolve()


def test_archive_markdown_relative_links_resolve() -> None:
    failures: list[str] = []
    for document in sorted(_ARCHIVE_ROOT.glob("*.md")):
        for line_number, destination in _markdown_destinations(document):
            target = _local_target(document, destination)
            if target is None:
                continue
            if not target.is_relative_to(_REPO_ROOT) or not target.exists():
                failures.append(
                    f"{document.relative_to(_REPO_ROOT)}:{line_number}: {destination!r} -> {target}"
                )

    assert not failures, "깨진 archive Markdown 상대 링크:\n" + "\n".join(failures)
