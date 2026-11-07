"""공유 통합 cluster가 실제로 비내구·tmpfs로 도는지 서버에서 확인한다 (n150 디스크 I/O 보호).

설정 함수가 옵션을 얹는 것(unit)과 서버가 그 옵션으로 뜬 것은 다른 층이다 — 효과를 본다.
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.integration._disposable_pg import DATA_ROOT

pytestmark = pytest.mark.integration


def _run(pg_container: Any, *argv: str) -> str:
    result = pg_container.get_wrapped_container().exec_run(list(argv), user="postgres")
    # 이미지의 local socket은 trust다. superuser 역할 이름은 fixture가 만든 것(기본 "test").
    assert result.exit_code == 0, result.output
    return str(result.output.decode()).strip()


def _psql(pg_container: Any, query: str) -> str:
    role = str(pg_container.username)
    return _run(pg_container, "psql", "-XtA", "-U", role, "-d", "postgres", "-c", query)


@pytest.mark.parametrize("knob", ["fsync", "synchronous_commit", "full_page_writes"])
def test_shared_cluster_runs_without_durability(pg_container: Any, knob: str) -> None:
    assert _psql(pg_container, f"SHOW {knob}") == "off"


def test_shared_cluster_data_directory_is_on_tmpfs(pg_container: Any) -> None:
    data_directory = _psql(pg_container, "SHOW data_directory")
    assert data_directory.startswith(DATA_ROOT + "/")
    assert _run(pg_container, "stat", "-f", "-c", "%T", data_directory) == "tmpfs"
