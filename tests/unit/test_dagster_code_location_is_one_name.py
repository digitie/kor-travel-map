"""Map의 Dagster code location 이름은 한 곳(``docker/workspace.yaml``)에서 나온다.

webserver 하나가 여러 프로젝트의 code location을 싣는 공유 Dagster plane에서는 모든
소비자(API·admin UI·run 완주 게이트)가 조회를 이 이름으로 좁힌다. 이름이 한 곳에서라도
어긋나면 그 소비자는 조용히 빈 결과(``RepositoryNotFoundError``·run 0건)를 보거나,
좁히지 않은 채 다른 프로젝트의 것을 본다. 그래서 이름을 쓰는 자리를 전부 정본과 대조한다.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest
import yaml
from kortravelmap.api.settings import ApiSettings

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[2]


def _workspace_location() -> str:
    document = yaml.safe_load((_ROOT / "docker" / "workspace.yaml").read_text(encoding="utf-8"))
    entries = document["load_from"]
    assert len(entries) == 1, entries
    name = entries[0]["grpc_server"]["location_name"]
    assert isinstance(name, str) and name
    return name


def _python_constant(relative: str, name: str) -> object:
    tree = ast.parse((_ROOT / relative).read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == name for target in node.targets
        ):
            return ast.literal_eval(node.value)
    raise AssertionError(f"{relative}: {name}이 없다")


def test_api_settings_default_is_the_workspace_location() -> None:
    field = ApiSettings.model_fields["dagster_repository_location_name"]
    assert field.default == _workspace_location()
    assert ApiSettings.model_fields["dagster_repository_name"].default == "__repository__"


def test_api_env_example_is_the_workspace_location() -> None:
    text = (_ROOT / "packages" / "kor-travel-map-api" / ".env.example").read_text(
        encoding="utf-8"
    )
    match = re.search(
        r"^KOR_TRAVEL_MAP_API_DAGSTER_REPOSITORY_LOCATION_NAME=(\S+)$", text, re.MULTILINE
    )
    assert match is not None
    assert match[1] == _workspace_location()


def test_admin_ui_constant_is_the_workspace_location() -> None:
    text = (
        _ROOT / "packages" / "kor-travel-map-admin" / "frontend" / "src" / "api" / "pipeline.ts"
    ).read_text(encoding="utf-8")
    match = re.search(r'^export const DAGSTER_CODE_LOCATION = "([^"]+)";$', text, re.MULTILINE)
    assert match is not None
    assert match[1] == _workspace_location()


@pytest.mark.parametrize(
    "relative",
    [
        "packages/kor-travel-map-admin/frontend/e2e/live/_ops-c7-admin-api.ts",
        "packages/kor-travel-map-admin/frontend/e2e/live/_ops-c7-dagster-sensor.ts",
    ],
)
def test_c7_live_selectors_are_the_workspace_location(relative: str) -> None:
    text = (_ROOT / relative).read_text(encoding="utf-8")
    block = re.search(
        r"const MAP_DAGSTER_REPOSITORY_SELECTOR = \{\n"
        r'  repositoryName: "([^"]+)",\n'
        r'  repositoryLocationName: "([^"]+)",\n'
        r"\} as const;",
        text,
    )
    assert block is not None, relative
    assert block[1] == "__repository__"
    assert block[2] == _workspace_location()
    # 조회는 이 selector로 좁힌다 — 전 repository를 도는 조회가 돌아오지 않았다.
    assert "repositoriesOrError" not in text, relative


def _dagster_query_sources() -> list[Path]:
    sources = sorted((_ROOT / "packages" / "kor-travel-map-api" / "src").rglob("*.py"))
    sources += sorted((_ROOT / "scripts").glob("*.py"))
    return [path for path in sources if "OrError" in path.read_text(encoding="utf-8")]


def test_no_consumer_reads_every_repository_or_every_run() -> None:
    """``repositoriesOrError``와 filter 없는 ``runsOrError``는 공유 webserver의 전 프로젝트다."""

    sources = _dagster_query_sources()
    # 하한: 실제 조회 파일을 봤다(API 서비스·라우터·게이트 스크립트).
    assert len(sources) >= 6, sources
    for path in sources:
        text = path.read_text(encoding="utf-8")
        assert "repositoriesOrError" not in text, path
        for match in re.finditer(r"runsOrError\(([^)]*)\)", text):
            assert "filter:" in match[1], (path, match[0])


def test_run_completion_gate_is_the_workspace_location() -> None:
    relative = "scripts/dagster_run_completion_gate.py"
    assert _python_constant(relative, "_CODE_LOCATION") == _workspace_location()
    assert _python_constant(relative, "_REPOSITORY_NAME") == "__repository__"
