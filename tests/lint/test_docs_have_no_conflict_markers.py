"""커밋된 Markdown에 git 충돌 마커가 남지 않는다.

diff3 스타일 리베이스(`|||||||` 기준 구간)를 손이나 스크립트로 풀 때 마커 줄 하나가 남기 쉽다 —
2026-10-15에 `docs/archive/journal-2026-08d.md`·`docs/tasks-done.md`에 몇 주 전부터 남아 있던 것과,
같은 날 두 PR의 리베이스가 journal·resume에 새로 남긴 것을 리뷰가 찾았다. 마커는 줄 머리에서만
본다(표의 `|||` 같은 본문은 건드리지 않는다).
"""

from __future__ import annotations

import codecs
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_REPO = Path(__file__).resolve().parents[2]
_MARKER = re.compile(r"^(?:<{7}|\|{7}|>{7})(?: |$)|^={7}$", re.MULTILINE)


def _markdown_files() -> list[Path]:
    files = sorted((_REPO / "docs").rglob("*.md"))
    files += sorted(_REPO.glob("*.md"))
    return files


def _read(path: Path) -> str:
    """UTF-8, 또는 BOM이 있으면 UTF-16(저장소에 UTF-16 보고서가 하나 있다)."""
    raw = path.read_bytes()
    if raw.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return raw.decode("utf-16")
    return raw.decode("utf-8")


def offenders(text: str) -> list[int]:
    return [text.count("\n", 0, match.start()) + 1 for match in _MARKER.finditer(text)]


def test_no_conflict_markers_in_markdown() -> None:
    files = _markdown_files()
    assert len(files) > 50, "docs Markdown을 거의 못 봤다 — 경로가 바뀌었나"
    found = [
        f"{path.relative_to(_REPO)}:{line}"
        for path in files
        for line in offenders(_read(path))
    ]
    assert not found, "충돌 마커가 남은 줄:\n" + "\n".join(found)


@pytest.mark.parametrize(
    ("text", "lines"),
    [
        ("a\n||||||| parent of abc (x)\nb\n", [2]),
        ("<<<<<<< HEAD\nx\n=======\ny\n>>>>>>> abc\n", [1, 3, 5]),
        ("| a || b |||||||\n|---|---|\n", []),
        ("=======\n", [1]),
        ("text ======= text\n", []),
    ],
)
def test_marker_matcher(text: str, lines: list[int]) -> None:
    assert offenders(text) == lines
