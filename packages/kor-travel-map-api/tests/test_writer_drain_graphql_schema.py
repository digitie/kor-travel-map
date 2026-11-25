"""writer-drain GraphQL 문서가 설치된 Dagster 스키마에서 유효한지 본다.

writer-drain의 ``stopSensor``는 ``sensorOriginId``·``sensorSelectorId`` 인자와 ``SensorState``
타입을 썼는데, Dagster 1.13 스키마에는 둘 다 없다(``jobOriginId``·``jobSelectorId``,
``StopSensorMutationResult``/``Sensor``). webserver는 그런 문서를 실행 전 검증 단계에서
거부하므로 drain은 sensor를 하나도 멈추지 못한다. 손으로 만든 응답을 돌려주는 단위
시험으로는 이 어긋남이 보이지 않는다 — 그래서 문서를 ``dagster-graphql``이 만드는
스키마로 직접 검증한다. CI는 ``docker/constraints-dagster.txt``로 운영 webserver와 같은
``dagster-graphql``을 설치한다.

``importorskip``을 쓰지 않는다: 설치 구성이 바뀌어 ``dagster_graphql``이 빠지면 이 가드가
조용히 skip되는 대신 실패해야 한다.
"""

from __future__ import annotations

import ast
import inspect
import re
from pathlib import Path
from typing import Any

import dagster_graphql.schema as dagster_graphql_schema
import graphql
import pytest
from dagster_graphql.version import __version__ as dagster_graphql_version

from kortravelmap.api import writer_drain_service as service

_CONSTRAINTS = Path(__file__).resolve().parents[3] / "docker" / "constraints-dagster.txt"

_DOCUMENT_NAMES = (
    "_INSTIGATIONS_QUERY",
    "_NONTERMINAL_RUNS_QUERY",
    "_RUN_STATUS_QUERY",
    "_TERMINATE_RUN_MUTATION",
    "_START_SCHEDULE_MUTATION",
    "_STOP_SCHEDULE_MUTATION",
    "_START_SENSOR_MUTATION",
    "_STOP_SENSOR_MUTATION",
)

_INSTIGATION_KEYS = [("schedule", True), ("schedule", False), ("sensor", True), ("sensor", False)]


@pytest.fixture(scope="module")
def dagster_schema() -> Any:
    return dagster_graphql_schema.create_schema().graphql_schema


def _operation_documents_in_module_source() -> set[str]:
    """모듈 소스의 문자열 상수 가운데 GraphQL operation으로 parse되는 것 전부.

    이름 규칙이나 시작 글자에 기대지 않는다 — dict·호출 인자에 인라인으로 쓴 문서도 잡는다.
    """

    found: set[str] = set()
    for node in ast.walk(ast.parse(inspect.getsource(service))):
        if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
            continue
        try:
            document = graphql.parse(node.value)
        except graphql.GraphQLError:
            continue
        if any(isinstance(d, graphql.OperationDefinitionNode) for d in document.definitions):
            found.add(node.value)
    return found


def test_installed_dagster_graphql_matches_the_pinned_host_version() -> None:
    # 다른 버전 스키마로 검증하면 운영(n150 공유 webserver)과 어긋나도 통과한다.
    match = re.search(
        r"^dagster-graphql==(\S+)$", _CONSTRAINTS.read_text(encoding="utf-8"), re.MULTILINE
    )
    assert match is not None
    assert dagster_graphql_version == match.group(1)


def test_every_writer_drain_graphql_document_is_listed() -> None:
    # 새 문서를 더하고 이 목록에 빠뜨리면(또는 인라인으로 쓰면) 검증 없이 운영에 나간다.
    listed = {getattr(service, name) for name in _DOCUMENT_NAMES}
    assert len(listed) == len(_DOCUMENT_NAMES)
    assert _operation_documents_in_module_source() == listed


@pytest.mark.parametrize("name", _DOCUMENT_NAMES)
def test_writer_drain_graphql_document_validates_against_dagster_schema(
    dagster_schema: Any, name: str
) -> None:
    document = graphql.parse(getattr(service, name))
    errors = graphql.validate(dagster_schema, document)
    assert [error.message for error in errors] == []


@pytest.mark.parametrize(("kind", "start"), _INSTIGATION_KEYS)
def test_success_typename_and_state_key_exist_in_the_mutation_result(
    dagster_schema: Any, kind: str, start: bool
) -> None:
    # 성공 판정에 쓰는 __typename이 그 mutation 결과 union의 멤버이고, 상태 key가 그
    # 타입의 InstigationState field여야 한다. 아니면 정상 응답도 DAGSTER_MUTATION_FAILED다.
    _query, field, success_type, state_key = service._INSTIGATION_MUTATIONS[  # noqa: SLF001
        (kind, start)  # type: ignore[index]
    ]
    result_type = graphql.get_named_type(dagster_schema.mutation_type.fields[field].type)
    members = {member.name for member in dagster_schema.get_possible_types(result_type)}
    assert success_type in members
    success = dagster_schema.get_type(success_type)
    assert state_key in success.fields
    assert graphql.get_named_type(success.fields[state_key].type).name == "InstigationState"


@pytest.mark.parametrize(("kind", "start"), _INSTIGATION_KEYS)
def test_mutation_document_selects_what_the_success_check_reads(kind: str, start: bool) -> None:
    # 판정 표(field·성공 타입·상태 key)와 문서의 selection을 묶는다. 스키마상 유효해도
    # alias가 붙거나 성공 fragment가 상태 객체를 고르지 않으면 운영에서 DAGSTER_PROTOCOL이다.
    query, field, success_type, state_key = service._INSTIGATION_MUTATIONS[  # noqa: SLF001
        (kind, start)  # type: ignore[index]
    ]
    (operation,) = graphql.parse(query).definitions
    assert isinstance(operation, graphql.OperationDefinitionNode)
    assert operation.operation == graphql.OperationType.MUTATION
    (root,) = operation.selection_set.selections
    assert isinstance(root, graphql.FieldNode)
    assert root.alias is None
    assert root.name.value == field
    assert root.selection_set is not None
    fragments = [
        selection
        for selection in root.selection_set.selections
        if isinstance(selection, graphql.InlineFragmentNode)
        and selection.type_condition is not None
        and selection.type_condition.name.value == success_type
    ]
    assert len(fragments) == 1
    state_fields = [
        selection
        for selection in fragments[0].selection_set.selections
        if isinstance(selection, graphql.FieldNode) and selection.name.value == state_key
    ]
    assert len(state_fields) == 1
    assert state_fields[0].alias is None
    assert state_fields[0].selection_set is not None
    assert {
        selection.name.value
        for selection in state_fields[0].selection_set.selections
        if isinstance(selection, graphql.FieldNode) and selection.alias is None
    } >= {"status"}
    typename_fields = [
        selection
        for selection in root.selection_set.selections
        if isinstance(selection, graphql.FieldNode) and selection.name.value == "__typename"
    ]
    assert len(typename_fields) == 1
    assert typename_fields[0].alias is None
