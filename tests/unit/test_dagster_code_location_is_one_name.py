"""Map의 Dagster code location 이름은 한 곳(``docker/workspace.yaml``)에서 나온다.

webserver 하나가 여러 프로젝트의 code location을 싣는 공유 Dagster plane에서는 모든
소비자(API·admin UI·run 완주 게이트)가 조회를 이 이름으로 좁힌다. 이름이 한 곳에서라도
어긋나면 그 소비자는 조용히 빈 결과(``RepositoryNotFoundError``·run 0건)를 보거나,
좁히지 않은 채 다른 프로젝트의 것을 본다. 그래서 이름을 쓰는 자리를 전부 정본과 대조한다.
"""

from __future__ import annotations

import ast
import functools
import re
import warnings
from pathlib import Path

import pytest
import yaml
from graphql import get_named_type
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


@functools.cache
def filtered_run_readers() -> frozenset[str]:
    """``RunsFilter``를 받는 Query root field — 설치된 dagster_graphql schema에서 읽는다.

    이 field들은 filter가 없으면(또는 repository tag가 없는 filter면) 공유 webserver에
    올라탄 **모든** 프로젝트의 run을 돌려준다(``runsOrError``·``runsFeedOrError``·
    ``runsFeedCountOrError``·``pipelineRunsOrError``·``runIdsOrError``). Dagster가 새
    filter 조회를 더하면 이 집합이 저절로 넓어진다.

    id로 읽는 조회(``runOrError``·``logsForRun``·``terminateRun`` 등)는 여기 없다 — run
    id는 이미 좁힌 조회(위 field를 ``$runsFilter``로 부른 결과)나 이 location에 낸 launch
    에서만 나오므로 출처로 좁혀져 있다.
    """

    # dagster_graphql은 import 시점에 Python 3.14의 asyncio deprecation을 낸다 —
    # filterwarnings=error가 그것을 수집 오류로 올리지 않게 import만 감싼다.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        from dagster_graphql.schema import create_schema

        schema = create_schema()
    query_type = schema.graphql_schema.query_type
    assert query_type is not None
    return frozenset(
        name
        for name, field in query_type.fields.items()
        if any(get_named_type(arg.type).name == "RunsFilter" for arg in field.args.values())
    )


#: ``runId``를 받지만 그 run의 **group 전체**(재실행 계보)를 돌려주는 조회. 필요해진 적이
#: 없으니 쓰지 않는다 — 쓰게 되면 출처 근거를 이 검사에 먼저 적는다.
_UNUSED_RUN_READERS = frozenset({"runGroupOrError"})


def _run_reader_selection() -> re.Pattern[str]:
    """GraphQL 선택으로서의 run 조회 — 인자 괄호 또는 선택 중괄호가 뒤따른다.

    ``data.get("runsOrError")``·``data.runsOrError`` 같은 응답 읽기는 걸리지 않는다.
    """

    names = sorted(filtered_run_readers() | _UNUSED_RUN_READERS)
    return re.compile(r"\b(" + "|".join(map(re.escape, names)) + r")\s*([({])")


_GRAPHQL_COMMENT = re.compile(r"#[^\n]*")
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


def unscoped_runs_selections(query: str) -> list[str]:
    """GraphQL 문서에서 이 code location으로 좁혀지지 않은 run 조회를 모두 돌려준다.

    ``#`` 주석은 먼저 버린다 — 주석 속 guard·변수 선언은 조회를 좁히지 않는다.
    ``filtered_run_readers()``의 각 선택은 조건 셋을 모두 지켜야 한다.

    1. 인자가 ``filter: $runsFilter``다. 리터럴 filter(``filter: {statuses: [...]}``)나
       filter 없는 조회, 인자 없는 bare 선택은 전 프로젝트의 run이다. 그 변수 값이
       ``DagsterUrls.runs_filter()``에서 나오는지는 ``run_query_binding_violations``가 본다.
    2. 같은 operation이 ``$runsFilter: RunsFilter!``를 선언한다.
    3. 같은 operation이 **앞서** ``repositoryOrError(repositorySelector:
       $repositorySelector)``를 싣는다 — location 이름이 틀려 tag filter가 조용히
       0건이 되는 경우를 오류로 올리는 손잡이다.

    ``_UNUSED_RUN_READERS``는 선택 자체가 위반이다.
    """

    text = _GRAPHQL_COMMENT.sub("", query)
    violations: list[str] = []
    for match in _run_reader_selection().finditer(text):
        snippet = text[match.start() : match.start() + 80].splitlines()[0]
        if match[1] in _UNUSED_RUN_READERS:
            violations.append(f"unused run reader is selected: {snippet}")
            continue
        if match[2] == "{":
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


def _is_helper_call(node: ast.expr | None, helper: str) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == helper
    )


def run_query_binding_violations(source: str) -> tuple[int, list[str]]:
    """Python 모듈의 run 조회가 operation 단위로 좁혀지는지 본다.

    run 조회(``filtered_run_readers()`` 선택 또는 ``$runsFilter``)를 싣는 문자열은
    모듈 최상위 상수여야 하고, 그 상수는 ``query=`` 키워드로만 쓰이며, 같은 호출의
    ``variables=`` dict 리터럴이 ``"runsFilter"``를 ``….runs_filter(…)``로,
    ``"repositorySelector"``를 ``….repository_selector()``로 채워야 한다 — 파일 어딘가에
    ``runs_filter(``가 있다는 것만으로는 그 operation의 filter가 좁혀졌다는 보장이 없다.
    돌려주는 것은 (좁혀진 채 보내진 호출 수, 위반).
    """

    tree = ast.parse(source)
    selection = _run_reader_selection()

    def carries_run_query(value: str) -> bool:
        text = _GRAPHQL_COMMENT.sub("", value)
        return selection.search(text) is not None or "$runsFilter" in text

    queries: dict[str, str] = {}
    query_nodes: set[int] = set()
    for statement in tree.body:
        target: ast.expr | None = None
        value: ast.expr | None = None
        if isinstance(statement, ast.Assign) and len(statement.targets) == 1:
            target, value = statement.targets[0], statement.value
        elif isinstance(statement, ast.AnnAssign):
            target, value = statement.target, statement.value
        if (
            isinstance(target, ast.Name)
            and isinstance(value, ast.Constant)
            and isinstance(value.value, str)
            and carries_run_query(value.value)
        ):
            queries[target.id] = value.value
            query_nodes.add(id(value))

    violations: list[str] = []
    for name, query in queries.items():
        violations.extend(f"{name}: {violation}" for violation in unscoped_runs_selections(query))
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in query_nodes
            and carries_run_query(node.value)
        ):
            violations.append(f"line {node.lineno}: run 조회가 모듈 최상위 상수가 아니다")

    bound_names: set[int] = set()
    sent: dict[str, int] = dict.fromkeys(queries, 0)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        keywords = {keyword.arg: keyword.value for keyword in node.keywords}
        query_value = keywords.get("query")
        if not (isinstance(query_value, ast.Name) and query_value.id in queries):
            continue
        bound_names.add(id(query_value))
        sent[query_value.id] += 1
        variables = keywords.get("variables")
        if not isinstance(variables, ast.Dict):
            violations.append(f"{query_value.id}: variables가 dict 리터럴이 아니다")
            continue
        entries = {
            key.value: value
            for key, value in zip(variables.keys, variables.values, strict=True)
            if isinstance(key, ast.Constant)
        }
        if not _is_helper_call(entries.get("runsFilter"), "runs_filter"):
            violations.append(f"{query_value.id}: runsFilter가 runs_filter(…)에서 오지 않는다")
        if not _is_helper_call(entries.get("repositorySelector"), "repository_selector"):
            violations.append(
                f"{query_value.id}: repositorySelector가 repository_selector()에서 오지 않는다"
            )
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Name)
            and isinstance(node.ctx, ast.Load)
            and node.id in queries
            and id(node) not in bound_names
        ):
            violations.append(f"{node.id}: query= 키워드 밖에서 쓰인다(line {node.lineno})")
    violations.extend(f"{name}: 보내는 호출이 없다" for name, count in sent.items() if not count)
    return sum(sent.values()), violations


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


def test_run_readers_come_from_the_installed_schema() -> None:
    # 하한: reviewer가 이름 붙인 filter 조회가 모두 schema에서 나왔다(유도가 공허하지 않다).
    assert {
        "runsOrError",
        "runsFeedOrError",
        "runsFeedCountOrError",
        "pipelineRunsOrError",
        "runIdsOrError",
    } <= filtered_run_readers()
    # id 조회는 filter 조회가 아니다.
    assert not {"runOrError", "logsForRun", "runGroupOrError"} & filtered_run_readers()


def test_no_consumer_reads_every_repository_or_every_run() -> None:
    """``repositoriesOrError``와 좁히지 않은 run 조회는 공유 webserver의 전 프로젝트다."""

    sources = _dagster_query_sources()
    suffixes = {path.suffix for path in sources}
    # 하한: 선언한 언어를 실제로 훑었다.
    assert {".py", ".sh", ".ts"} <= suffixes, suffixes
    selection = _run_reader_selection()
    sent: dict[str, int] = {}
    for path in sources:
        text = path.read_text(encoding="utf-8")
        relative = path.relative_to(_ROOT).as_posix()
        assert "repositoriesOrError" not in text, relative
        if path.suffix == ".py":
            count, violations = run_query_binding_violations(text)
            assert violations == [], (relative, violations)
            if count:
                sent[relative] = count
        else:
            # Python 밖에는 runs_filter()에 해당하는 결박이 없다 — run 조회는 API를 거친다.
            assert selection.search(text) is None, relative
            assert "$runsFilter" not in text, relative
    # 하한: 지금 존재하는 run 조회를 **본** 것 — overview·runs 패널(라우터 둘),
    # summary, MOIS precheck, writer drain. 새 조회가 늘면 올린다.
    assert sum(sent.values()) >= 5, sent


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
        # 주석 속 guard는 guard가 아니다.
        (
            _SCOPED_QUERY.replace("  repositoryOrError(", "  # repositoryOrError("),
            "no repositoryOrError guard",
        ),
        ("query G($id: ID!) { runGroupOrError(runId: $id) { __typename } }", "unused run reader"),
    ],
)
def test_unscoped_runs_detector_rejects_the_old_shapes(query: str, reason: str) -> None:
    violations = unscoped_runs_selections(query)
    assert len(violations) == 1, violations
    assert reason in violations[0]


@pytest.mark.parametrize("reader", sorted(filtered_run_readers()))
def test_unscoped_runs_detector_covers_every_filtered_reader(reader: str) -> None:
    literal = f"query Q {{ {reader}(filter: {{statuses: [STARTED]}}) {{ __typename }} }}"
    assert len(unscoped_runs_selections(literal)) == 1, reader
    assert unscoped_runs_selections(_SCOPED_QUERY.replace("runsOrError", reader)) == []


def test_unscoped_runs_detector_accepts_the_scoped_shape() -> None:
    assert unscoped_runs_selections(_SCOPED_QUERY) == []
    # 응답 읽기는 선택이 아니다.
    assert unscoped_runs_selections('data.get("runsOrError"); data.runsOrError;') == []


_BOUND_MODULE = f'''
_QUERY = """{_SCOPED_QUERY}"""


async def read(urls, client):
    return await post_graphql(
        client=client,
        variables={{
            "limit": 5,
            "repositorySelector": urls.repository_selector(),
            "runsFilter": urls.runs_filter(statuses=["STARTED"]),
        }},
        query=_QUERY,
    )
'''


def test_binding_detector_accepts_the_scoped_call() -> None:
    assert run_query_binding_violations(_BOUND_MODULE) == (1, [])


@pytest.mark.parametrize(
    ("module", "reason"),
    [
        # 같은 파일 다른 곳의 runs_filter( 호출은 이 operation을 좁히지 않는다.
        (
            _BOUND_MODULE.replace(
                '"runsFilter": urls.runs_filter(statuses=["STARTED"])',
                '"runsFilter": {"statuses": ["STARTED"]}',
            )
            + "\nUNRELATED = urls.runs_filter()\n",
            "runsFilter가 runs_filter",
        ),
        (
            _BOUND_MODULE.replace(
                '"repositorySelector": urls.repository_selector()',
                '"repositorySelector": {"repositoryName": "x", "repositoryLocationName": "y"}',
            ),
            "repositorySelector가 repository_selector",
        ),
        (_BOUND_MODULE.replace("variables={", "variables=VARIABLES or {"), "dict 리터럴"),
        (
            _BOUND_MODULE.replace("query=_QUERY", "query=alias") + "\nalias = _QUERY\n",
            "query= 키워드 밖",
        ),
        (_BOUND_MODULE.replace("query=_QUERY", "query=OTHER"), "보내는 호출이 없다"),
        (
            _BOUND_MODULE.replace("query=_QUERY", 'query="query Q { runIdsOrError { x } }"'),
            "모듈 최상위 상수가 아니다",
        ),
    ],
)
def test_binding_detector_rejects_unbound_operations(module: str, reason: str) -> None:
    _, violations = run_query_binding_violations(module)
    assert violations, module
    assert any(reason in violation for violation in violations), violations


def test_run_completion_gate_is_the_workspace_location() -> None:
    relative = "scripts/dagster_run_completion_gate.py"
    assert _python_constant(relative, "_CODE_LOCATION") == _workspace_location()
    assert _python_constant(relative, "_REPOSITORY_NAME") == "__repository__"
