"""아카이브 이동으로 깨진 Markdown 상대 링크를 영구 차단한다."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import unquote, urlsplit

from markdown_it import MarkdownIt
from markdown_it.token import Token

_REPO_ROOT = Path(__file__).resolve().parents[2]
_ARCHIVE_ROOT = _REPO_ROOT / "docs" / "archive"
_MAX_ARCHIVE_BYTES = 220 * 1024
_MARKDOWN = MarkdownIt("commonmark")


def _markdown_destinations(document: Path) -> list[tuple[int, str]]:
    destinations: list[tuple[int, str]] = []

    def visit(tokens: list[Token], parent_line: int = 1) -> None:
        for token in tokens:
            line_number = token.map[0] + 1 if token.map is not None else parent_line
            attribute = "href" if token.type == "link_open" else "src"
            if token.type in {"link_open", "image"}:
                destination = token.attrGet(attribute)
                if destination is not None:
                    destinations.append((line_number, destination))
            if token.children:
                visit(token.children, line_number)

    visit(_MARKDOWN.parse(document.read_text(encoding="utf-8")))

    return destinations


def _local_target(document: Path, destination: str) -> Path | None:
    try:
        parsed = urlsplit(destination)
    except ValueError:
        return None
    if parsed.scheme or parsed.netloc or not parsed.path or parsed.path.startswith("/"):
        return None
    return (document.parent / unquote(parsed.path)).resolve()


def test_markdown_parser_covers_commonmark_link_edges(tmp_path: Path) -> None:
    document = tmp_path / "links.md"
    document.write_text(
        """
[escaped \\] label](../balanced(1).md)
[reference link][reference]

[reference]:
  ../multiline.md

````
[ignored](../inside-fence.md)
```
````
""".lstrip(),
        encoding="utf-8",
    )

    assert [destination for _, destination in _markdown_destinations(document)] == [
        "../balanced(1).md",
        "../multiline.md",
    ]


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


def test_archive_markdown_files_stay_within_readable_limit() -> None:
    oversized = [
        f"{document.relative_to(_REPO_ROOT)}: {document.stat().st_size:,} bytes"
        for document in sorted(_ARCHIVE_ROOT.glob("*.md"))
        if document.stat().st_size > _MAX_ARCHIVE_BYTES
    ]
    assert not oversized, (
        f"archive Markdown은 {_MAX_ARCHIVE_BYTES:,} bytes 이하여야 함:\n" + "\n".join(oversized)
    )
