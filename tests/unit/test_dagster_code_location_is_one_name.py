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
    assert isinstance(name, str)
    assert name
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


#: Dagster 조회 문자열이 살 수 있는 자리 — API·Dagster 패키지, core, 운영 스크립트
#: (``scripts/lib``·``scripts/n150`` 포함, ``.sh`` 포함), admin UI(src·e2e의 ``.ts``/``.tsx``).
_QUERY_SOURCE_ROOTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("packages/kor-travel-map-api/src", (".py",)),
    ("packages/kor-travel-map-dagster/src", (".py",)),
    ("src", (".py",)),
    ("scripts", (".py", ".sh", ".mjs", ".js", ".ts")),
    ("packages/kor-travel-map-admin/frontend/src", (".ts", ".tsx")),
    ("packages/kor-travel-map-admin/frontend/e2e", (".ts", ".tsx")),
)

#: GraphQL 선택으로서의 ``runsOrError`` — 인자 괄호 또는 선택 중괄호가 뒤따른다.
#: ``data.get("runsOrError")``·``data.runsOrError`` 같은 응답 읽기는 걸리지 않는다.
_RUNS_SELECTION = re.compile(r"\brunsOrError\s*([({])")
_OPERATION_START = re.compile(r"\b(?:query|mutation|subscription)\b\s*\w*\s*[({]")
_RUNS_FILTER_ARGUMENT = re.compile(r"\bfilter:\s*\$runsFilter\b")
_RUNS_FILTER_VARIABLE = re.compile(r"\$runsFilter:\s*RunsFilter!")
_REPOSITORY_GUARD = "repositoryOrError(repositorySelector: $repositorySelector)"


def _balanced_arguments(text: str, open_index: int) -> str:
    depth = 0
    for index in range(open_index, len(text)):
        char = text[index]
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return text[open_index + 1 : index]
    return text[open_index + 1 :]


def unscoped_runs_selections(text: str) -> list[str]:
    """이 code location으로 좁혀지지 않은 ``runsOrError`` 선택을 모두 돌려준다.

    통과 조건은 셋이다.

    1. 인자가 ``filter: $runsFilter``다 — ``DagsterUrls.runs_filter()``가 만든,
       repository tag가 들어 있는 filter만 그 변수로 들어온다. 리터럴 filter
       (``filter: {statuses: [...]}``)나 filter 없는 조회, 인자 없는 bare
       ``runsOrError {``는 전 프로젝트의 run이다.
    2. 같은 operation이 ``$runsFilter: RunsFilter!``를 선언한다.
    3. 같은 operation이 **앞서** ``repositoryOrError(repositorySelector:
       $repositorySelector)``를 싣는다 — location 이름이 틀려 tag filter가 조용히
       0건이 되는 경우를 오류로 올리는 손잡이다.
    """

    violations: list[str] = []
    for match in _RUNS_SELECTION.finditer(text):
        snippet = text[match.start() : match.start() + 80].splitlines()[0]
        if match[1] == "{":
            violations.append(f"bare selection: {snippet}")
            continue
        arguments = _balanced_arguments(text, match.end() - 1)
        if not _RUNS_FILTER_ARGUMENT.search(arguments):
            violations.append(f"filter is not $runsFilter: {snippet}")
            continue
        operations = list(_OPERATION_START.finditer(text, 0, match.start()))
        operation = text[operations[-1].start() : match.start()] if operations else ""
        if not _RUNS_FILTER_VARIABLE.search(operation):
            violations.append(f"operation does not declare $runsFilter: RunsFilter!: {snippet}")
        if _REPOSITORY_GUARD not in operation:
            violations.append(f"operation has no repositoryOrError guard: {snippet}")
    return violations


def _dagster_query_sources() -> list[Path]:
    sources: list[Path] = []
    for relative, suffixes in _QUERY_SOURCE_ROOTS:
        root = _ROOT / relative
        assert root.is_dir(), relative
        for path in sorted(root.rglob("*")):
            if (
                path.is_file()
                and path.suffix in suffixes
                and "node_modules" not in path.parts
                and "__pycache__" not in path.parts
            ):
                sources.append(path)
    return sources


def test_no_consumer_reads_every_repository_or_every_run() -> None:
    """``repositoriesOrError``와 좁히지 않은 ``runsOrError``는 공유 webserver의 전 프로젝트다."""

    sources = _dagster_query_sources()
    suffixes = {path.suffix for path in sources}
    # 하한: 선언한 언어를 실제로 훑었다.
    assert {".py", ".sh", ".ts"} <= suffixes, suffixes
    seen_selections: list[str] = []
    for path in sources:
        text = path.read_text(encoding="utf-8")
        relative = path.relative_to(_ROOT).as_posix()
        assert "repositoriesOrError" not in text, relative
        selections = list(_RUNS_SELECTION.finditer(text))
        if not selections:
            continue
        seen_selections.extend(relative for _ in selections)
        assert unscoped_runs_selections(text) == [], relative
        # $runsFilter의 값은 repository tag를 붙이는 한 곳에서 만든다.
        if path.suffix == ".py":
            assert "runs_filter(" in text, relative
        else:
            assert ".dagster/repository" in text, relative
    # 하한: 지금 존재하는 run 조회를 **본** 것 — overview·runs 패널(라우터 둘),
    # summary, MOIS precheck, writer drain. 새 조회가 늘면 올린다.
    assert len(seen_selections) >= 5, seen_selections


# 과거에 이 검사를 통과했던 모양들 — 하나하나 빨갛게 나와야 한다.
_OLD_DRAIN_QUERY = """
query KorTravelMapWriterDrainRuns($limit: Int!) {
  runsOrError(
    filter: {statuses: [QUEUED, NOT_STARTED, STARTED, MANAGED, CANCELING]},
    limit: $limit
  ) {
    __typename
    ... on Runs { results { runId status } }
  }
}
"""
_UNGUARDED_QUERY = """
query Runs($limit: Int!, $runsFilter: RunsFilter!) {
  runsOrError(filter: $runsFilter, limit: $limit) { __typename }
}
"""
_SCOPED_QUERY = """
query Runs(
  $limit: Int!, $repositorySelector: RepositorySelector!, $runsFilter: RunsFilter!
) {
  repositoryOrError(repositorySelector: $repositorySelector) { __typename }
  runsOrError(filter: $runsFilter, limit: $limit) { __typename }
}
"""


@pytest.mark.parametrize(
    ("query", "reason"),
    [
        (_OLD_DRAIN_QUERY, "filter is not $runsFilter"),
        ("query Runs { runsOrError { __typename } }", "bare selection"),
        ("query Runs($limit: Int!) { runsOrError(limit: $limit) { __typename } }", "filter is not"),
        (_UNGUARDED_QUERY, "no repositoryOrError guard"),
        (
            _SCOPED_QUERY.replace("$runsFilter: RunsFilter!", "$runsFilter: RunsFilter"),
            "does not declare $runsFilter",
        ),
    ],
)
def test_unscoped_runs_detector_rejects_the_old_shapes(query: str, reason: str) -> None:
    violations = unscoped_runs_selections(query)
    assert len(violations) == 1, violations
    assert reason in violations[0]


def test_unscoped_runs_detector_accepts_the_scoped_shape() -> None:
    assert unscoped_runs_selections(_SCOPED_QUERY) == []
    # 응답 읽기는 선택이 아니다.
    assert unscoped_runs_selections('data.get("runsOrError"); data.runsOrError;') == []


def test_run_completion_gate_is_the_workspace_location() -> None:
    relative = "scripts/dagster_run_completion_gate.py"
    assert _python_constant(relative, "_CODE_LOCATION") == _workspace_location()
    assert _python_constant(relative, "_REPOSITORY_NAME") == "__repository__"
