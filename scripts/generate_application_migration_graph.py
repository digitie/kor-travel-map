#!/usr/bin/env python3
"""Map application Alembic graph를 실행 없이 package artifact로 고정한다.

후보 API image가 reset 전에 application schema head를 attest할 때 source checkout,
현재 작업 디렉터리, Alembic runtime을 신뢰하면 안 된다. 이 도구는 migration module을
import하지 않고 module-top-level ``revision``/``down_revision`` literal만 AST로 읽어
설치 package에 포함할 immutable graph artifact를 만든다.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Final

_GRAPH_SCHEMA: Final = "kor-travel-map.application-migration-graph.v1"
# Docker Manager F1D-C2의 candidate head parser와 같은 정본 문법이다.
_REVISION_PATTERN: Final = re.compile(r"^[0-9a-z][0-9a-z_.-]{0,127}$")
_ROOT: Final = Path(__file__).resolve().parents[1]
_DEFAULT_VERSIONS_DIRECTORY: Final = _ROOT / "alembic" / "versions"
_DEFAULT_OUTPUT: Final = _ROOT / "src" / "kortravelmap" / "_application_migration_graph.json"


class ApplicationMigrationGraphError(ValueError):
    """정적 migration graph를 만들 수 없는 fail-closed 입력 오류."""


def _literal_assignment(module: ast.Module, name: str, *, path: Path) -> object:
    """module top-level의 정확히 하나인 literal assignment를 반환한다."""
    values: list[ast.expr] = []
    for statement in module.body:
        if isinstance(statement, ast.Assign):
            if len(statement.targets) != 1 or not isinstance(statement.targets[0], ast.Name):
                continue
            if statement.targets[0].id == name:
                values.append(statement.value)
        elif (
            isinstance(statement, ast.AnnAssign)
            and isinstance(statement.target, ast.Name)
            and statement.target.id == name
            and statement.value is not None
        ):
            values.append(statement.value)

    if len(values) != 1:
        raise ApplicationMigrationGraphError(
            f"{path.name}: {name} must have exactly one module-level literal assignment"
        )
    try:
        return ast.literal_eval(values[0])
    except (TypeError, ValueError) as exc:
        raise ApplicationMigrationGraphError(
            f"{path.name}: {name} must be a literal"
        ) from exc


def _revision_id(value: object, *, path: Path, field: str) -> str:
    if not isinstance(value, str) or not _REVISION_PATTERN.fullmatch(value):
        raise ApplicationMigrationGraphError(
            f"{path.name}: {field} must be a non-empty Alembic revision identifier"
        )
    return value


def _down_revisions(value: object, *, path: Path) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [_revision_id(value, path=path, field="down_revision")]
    if isinstance(value, (list, tuple)):
        if not value:
            raise ApplicationMigrationGraphError(
                f"{path.name}: down_revision sequence must not be empty"
            )
        parents = [
            _revision_id(parent, path=path, field="down_revision") for parent in value
        ]
        if len(set(parents)) != len(parents):
            raise ApplicationMigrationGraphError(
                f"{path.name}: down_revision must not repeat a parent"
            )
        return parents
    raise ApplicationMigrationGraphError(
        f"{path.name}: down_revision must be None, a string, or a literal sequence"
    )


def _validate_graph(
    revisions: list[dict[str, object]],
    *,
    revision_ids: set[str],
    referenced_parents: set[str],
) -> None:
    """root 도달성·acyclic·단일 terminal head를 source 단계에서 함께 고정한다."""
    unknown_parents = referenced_parents.difference(revision_ids)
    if unknown_parents:
        raise ApplicationMigrationGraphError(
            "application migration graph has unknown parents: "
            + ", ".join(sorted(unknown_parents))
        )

    roots: set[str] = set()
    children: dict[str, set[str]] = {}
    for record in revisions:
        revision = record["revision"]
        down_revision = record["down_revision"]
        if not isinstance(revision, str) or not isinstance(down_revision, list):
            raise ApplicationMigrationGraphError("application migration graph is invalid")
        if not down_revision:
            roots.add(revision)
        for parent in down_revision:
            if not isinstance(parent, str):
                raise ApplicationMigrationGraphError("application migration graph is invalid")
            children.setdefault(parent, set()).add(revision)
    if len(roots) != 1:
        raise ApplicationMigrationGraphError(
            "application migration graph must have exactly one root"
        )

    visit_state: dict[str, int] = {}

    def _visit(revision: str) -> None:
        state = visit_state.get(revision, 0)
        if state == 1:
            raise ApplicationMigrationGraphError("application migration graph contains a cycle")
        if state == 2:
            return
        visit_state[revision] = 1
        for child in children.get(revision, ()):
            _visit(child)
        visit_state[revision] = 2

    _visit(next(iter(roots)))
    if set(visit_state) != revision_ids:
        raise ApplicationMigrationGraphError(
            "application migration graph has revisions unreachable from its root"
        )
    if len(revision_ids.difference(referenced_parents)) != 1:
        raise ApplicationMigrationGraphError(
            "application migration graph must have exactly one terminal head"
        )


def build_application_migration_graph(versions_directory: Path) -> dict[str, object]:
    """Alembic module을 실행하지 않고 정규화된 graph artifact를 만든다."""
    paths = sorted(versions_directory.glob("*.py"))
    if not paths:
        raise ApplicationMigrationGraphError("no application migration modules found")

    revisions: list[dict[str, object]] = []
    seen: set[str] = set()
    referenced_parents: set[str] = set()
    for path in paths:
        try:
            module = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError) as exc:
            raise ApplicationMigrationGraphError(
                f"{path.name}: unable to parse migration module"
            ) from exc
        revision = _revision_id(
            _literal_assignment(module, "revision", path=path),
            path=path,
            field="revision",
        )
        if revision in seen:
            raise ApplicationMigrationGraphError(
                f"{path.name}: duplicate revision {revision}"
            )
        seen.add(revision)
        down_revision = _down_revisions(
            _literal_assignment(module, "down_revision", path=path), path=path
        )
        referenced_parents.update(down_revision)
        revisions.append(
            {
                "revision": revision,
                "down_revision": down_revision,
            }
        )

    _validate_graph(
        revisions,
        revision_ids=seen,
        referenced_parents=referenced_parents,
    )
    return {"schema": _GRAPH_SCHEMA, "revisions": revisions}


def _canonical_json(payload: dict[str, object]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    """artifact를 출력하거나 checked-in artifact와 strict equality를 확인한다."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--versions-directory", type=Path, default=_DEFAULT_VERSIONS_DIRECTORY)
    parser.add_argument("--output", type=Path, default=_DEFAULT_OUTPUT)
    arguments = parser.parse_args(argv)
    if arguments.check and arguments.write:
        parser.error("--check and --write are mutually exclusive")

    try:
        rendered = _canonical_json(build_application_migration_graph(arguments.versions_directory))
    except ApplicationMigrationGraphError as exc:
        print(f"application migration graph: {exc}", file=sys.stderr)
        return 1

    if arguments.check:
        try:
            actual = arguments.output.read_text(encoding="utf-8")
        except OSError:
            print("application migration graph artifact is missing", file=sys.stderr)
            return 1
        if actual != rendered:
            print("application migration graph artifact is stale", file=sys.stderr)
            return 1
        return 0
    if arguments.write:
        arguments.output.write_text(rendered, encoding="utf-8")
        return 0
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
