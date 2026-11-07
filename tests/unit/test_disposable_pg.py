"""테스트 cluster는 비내구·tmpfs로 뜬다 (n150 디스크 I/O 보호).

``make_nondurable``이 명령과 tmpfs를 실제로 얹는지(testcontainers 두 모양 모두), 그리고
``tests/`` 안의 모든 ``PostgresContainer(...)`` 생성이 그 함수를 거치는지 본다.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

import pytest

from tests.integration._disposable_pg import (
    DATA_ROOT,
    DEFAULT_TMPFS_SIZE,
    NONDURABLE_COMMAND,
    TMPFS_SIZE_ENV,
    make_nondurable,
    resolve_tmpfs_size,
)

pytestmark = pytest.mark.unit

_TESTS = Path(__file__).resolve().parents[1]


class _Legacy:
    """testcontainers ≤4.14 모양 — tmpfs는 kwargs로만 넘길 수 있다."""

    def __init__(self) -> None:
        self._kwargs: dict[str, Any] = {"labels": {"a": "b"}}
        self.command: str | None = None

    def with_command(self, command: str) -> _Legacy:
        self.command = command
        return self

    def with_kwargs(self, **kwargs: Any) -> _Legacy:
        self._kwargs = kwargs
        return self


class _Modern(_Legacy):
    """testcontainers 4.15+ 모양 — ``tmpfs`` 속성을 run()에 따로 넘긴다."""

    def __init__(self) -> None:
        super().__init__()
        self.tmpfs: dict[str, str] = {}


def test_command_turns_off_every_durability_knob() -> None:
    for knob in ("fsync=off", "synchronous_commit=off", "full_page_writes=off"):
        assert f"-c {knob}" in NONDURABLE_COMMAND


def test_legacy_shape_gets_command_and_tmpfs_kwarg_without_losing_others() -> None:
    container = make_nondurable(_Legacy(), size="1g")
    assert container.command == NONDURABLE_COMMAND
    assert container._kwargs == {"labels": {"a": "b"}, "tmpfs": {DATA_ROOT: "rw,size=1g"}}


def test_modern_shape_uses_the_tmpfs_attribute_not_kwargs() -> None:
    # kwargs에도 넣으면 containers.run(tmpfs=..., **kwargs)가 중복 인자로 죽는다.
    container = make_nondurable(_Modern(), size="2g")
    assert container.tmpfs == {DATA_ROOT: "rw,size=2g"}
    assert "tmpfs" not in container._kwargs
    assert container.command == NONDURABLE_COMMAND


def test_tmpfs_size_absent_is_default_and_malformed_fails() -> None:
    assert resolve_tmpfs_size({}) == DEFAULT_TMPFS_SIZE
    assert resolve_tmpfs_size({TMPFS_SIZE_ENV: "512m"}) == "512m"
    for bad in ("", "3", "3G", "0g", "3gb", " 3g"):
        with pytest.raises(ValueError):
            resolve_tmpfs_size({TMPFS_SIZE_ENV: bad})


def _unwrapped_constructions(path: Path) -> list[int]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    wrapped: set[int] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "make_nondurable"
        ):
            for arg in node.args:
                wrapped.update(id(inner) for inner in ast.walk(arg))
    bad = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
        if name in {"PostgresContainer", "container_cls"} and id(node) not in wrapped:
            bad.append(node.lineno)
    return bad


def test_every_test_cluster_goes_through_make_nondurable() -> None:
    offenders: dict[str, list[int]] = {}
    seen = 0
    for path in sorted(_TESTS.rglob("*.py")):
        if path.name == "test_disposable_pg.py":
            continue
        text = path.read_text(encoding="utf-8")
        if "PostgresContainer" not in text:
            continue
        seen += 1
        lines = _unwrapped_constructions(path)
        if lines:
            offenders[str(path.relative_to(_TESTS))] = lines
    # 본 것에 하한을 건다 — 경로가 바뀌어 아무 파일도 안 보면 공허하게 초록이 된다.
    assert seen >= 5
    assert offenders == {}
