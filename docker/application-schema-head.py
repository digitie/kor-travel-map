#!/usr/local/bin/python -I
"""후보 API image가 설치된 application Alembic head를 DB 접속 없이 attest한다.

이 command는 application package import, Alembic CLI, 환경변수, 현재 작업 디렉터리와
source checkout을 사용하지 않는다. build 시 AST로 검증해 package data에 넣은 immutable
graph만 설치된 Python purelib/platlib root에서 읽는다.
"""

from __future__ import annotations

import json
import re
import sys
import sysconfig
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Final, TextIO

_MANIFEST_NAME: Final = "_application_migration_graph.json"
_GRAPH_SCHEMA: Final = "kor-travel-map.application-migration-graph.v1"
_HEAD_SCHEMA: Final = "kor-travel-map.application-head.v1"
_ERROR_SCHEMA: Final = "kor-travel-map.application-head-error.v1"
# Docker Manager F1D-C2의 pinned runtime receipt parser와 같은 정본 문법이다.
_REVISION_PATTERN: Final = re.compile(r"^[0-9a-z][0-9a-z_.-]{0,127}$")


class ApplicationSchemaHeadError(RuntimeError):
    """후보 schema head를 안전하게 판단할 수 없을 때의 안정된 오류 코드."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _installed_package_root() -> Path:
    """현재 cwd/sys.path를 배제하고 설치 Python prefix의 Map package만 찾는다."""
    paths = sysconfig.get_paths()
    candidates: set[Path] = set()
    for key in ("purelib", "platlib"):
        raw_path = paths.get(key)
        if not raw_path:
            continue
        package_root = Path(raw_path) / "kortravelmap"
        if (package_root / _MANIFEST_NAME).is_file():
            candidates.add(package_root)
    if len(candidates) != 1:
        raise ApplicationSchemaHeadError("installed_application_graph_unavailable")
    return next(iter(candidates))


def _revision_id(value: object) -> str:
    if not isinstance(value, str) or not _REVISION_PATTERN.fullmatch(value):
        raise ApplicationSchemaHeadError("application_graph_invalid")
    return value


def _parents(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ApplicationSchemaHeadError("application_graph_invalid")
    parents = tuple(_revision_id(parent) for parent in value)
    if len(parents) != len(set(parents)):
        raise ApplicationSchemaHeadError("application_graph_invalid")
    return parents


def _application_head(payload: object) -> str:
    """immutable graph의 정확히 하나인 terminal revision을 계산한다."""
    if not isinstance(payload, Mapping) or payload.get("schema") != _GRAPH_SCHEMA:
        raise ApplicationSchemaHeadError("application_graph_invalid")
    raw_revisions = payload.get("revisions")
    if not isinstance(raw_revisions, list) or not raw_revisions:
        raise ApplicationSchemaHeadError("application_graph_invalid")

    revisions: set[str] = set()
    parents: set[str] = set()
    children: dict[str, set[str]] = {}
    roots: set[str] = set()
    for record in raw_revisions:
        if not isinstance(record, Mapping) or set(record) != {"revision", "down_revision"}:
            raise ApplicationSchemaHeadError("application_graph_invalid")
        revision = _revision_id(record["revision"])
        if revision in revisions:
            raise ApplicationSchemaHeadError("application_graph_invalid")
        revisions.add(revision)
        revision_parents = _parents(record["down_revision"])
        if not revision_parents:
            roots.add(revision)
        parents.update(revision_parents)
        for parent in revision_parents:
            children.setdefault(parent, set()).add(revision)

    if len(roots) != 1 or not parents.issubset(revisions):
        raise ApplicationSchemaHeadError("application_graph_invalid")
    reachable: set[str] = set()
    pending = list(roots)
    while pending:
        revision = pending.pop()
        if revision in reachable:
            continue
        reachable.add(revision)
        pending.extend(children.get(revision, ()))
    if reachable != revisions:
        raise ApplicationSchemaHeadError("application_graph_invalid")

    visit_state: dict[str, int] = {}

    def _visit(revision: str) -> None:
        state = visit_state.get(revision, 0)
        if state == 1:
            raise ApplicationSchemaHeadError("application_graph_invalid")
        if state == 2:
            return
        visit_state[revision] = 1
        for child in children.get(revision, ()):
            _visit(child)
        visit_state[revision] = 2

    _visit(next(iter(roots)))
    if len(visit_state) != len(revisions):
        raise ApplicationSchemaHeadError("application_graph_invalid")
    heads = revisions.difference(parents)
    if len(heads) != 1:
        raise ApplicationSchemaHeadError("application_head_ambiguous")
    return next(iter(heads))


def application_head() -> str:
    """설치된 candidate package artifact만 읽어 head를 반환한다."""
    manifest = _installed_package_root() / _MANIFEST_NAME
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ApplicationSchemaHeadError("installed_application_graph_unavailable") from exc
    return _application_head(payload)


def _emit(payload: Mapping[str, str], *, stream: TextIO = sys.stdout) -> None:
    print(json.dumps(payload, separators=(",", ":")), file=stream)


def main(argv: Sequence[str] | None = None) -> int:
    """``head``만 허용하고 DB/credential 없는 한 줄 JSON을 출력한다."""
    arguments = list(sys.argv[1:] if argv is None else argv)
    try:
        if arguments != ["head"]:
            raise ApplicationSchemaHeadError("invalid_arguments")
        _emit({"schema": _HEAD_SCHEMA, "head": application_head()})
        return 0
    except ApplicationSchemaHeadError as exc:
        _emit({"schema": _ERROR_SCHEMA, "code": exc.code}, stream=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
