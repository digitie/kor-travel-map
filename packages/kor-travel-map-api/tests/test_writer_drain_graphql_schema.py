"""writer-drain GraphQL 문서가 설치된 Dagster 스키마에서 유효한지 본다.

writer-drain의 ``stopSensor``는 ``sensorOriginId``·``sensorSelectorId`` 인자와 ``SensorState``
타입을 썼는데, Dagster 1.13 스키마에는 둘 다 없다(``jobOriginId``·``jobSelectorId``,
``StopSensorMutationResult``/``Sensor``). webserver는 그런 문서를 실행 전 검증 단계에서
거부하므로 drain은 sensor를 하나도 멈추지 못한다. 손으로 만든 응답을 돌려주는 단위
시험으로는 이 어긋남이 보이지 않는다 — 그래서 문서를 ``dagster-graphql``이 만드는
스키마로 직접 검증한다. CI는 ``docker/constraints-dagster.txt``로 운영 webserver와 같은
``dagster-graphql``을 설치한다.
"""

from __future__ import annotations

import pytest

from kortravelmap.api import writer_drain_service as service

dagster_graphql_schema = pytest.importorskip("dagster_graphql.schema")
graphql = pytest.importorskip("graphql")

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


@pytest.fixture(scope="module")
def dagster_schema() -> object:
    return dagster_graphql_schema.create_schema().graphql_schema


def test_every_writer_drain_graphql_document_is_listed() -> None:
    # 새 문서를 더하고 이 목록에 빠뜨리면 검증 없이 운영에 나간다.
    found = {
        name
        for name, value in vars(service).items()
        if isinstance(value, str)
        and value.lstrip().startswith(("query ", "mutation "))
    }
    assert found == set(_DOCUMENT_NAMES)


@pytest.mark.parametrize("name", _DOCUMENT_NAMES)
def test_writer_drain_graphql_document_validates_against_dagster_schema(
    dagster_schema: object, name: str
) -> None:
    document = graphql.parse(getattr(service, name))
    errors = graphql.validate(dagster_schema, document)
    assert [error.message for error in errors] == []


@pytest.mark.parametrize(
    ("kind", "start"),
    [("schedule", True), ("schedule", False), ("sensor", True), ("sensor", False)],
)
def test_success_typename_and_state_key_exist_in_the_mutation_result(
    dagster_schema: object, kind: str, start: bool
) -> None:
    # 성공 판정에 쓰는 __typename이 그 mutation 결과 union의 멤버이고, 상태 key가 그
    # 타입의 field여야 한다. 아니면 정상 응답도 DAGSTER_MUTATION_FAILED가 된다.
    _query, field, success_type, state_key = service._INSTIGATION_MUTATIONS[  # noqa: SLF001
        (kind, start)  # type: ignore[index]
    ]
    mutation_type = dagster_schema.mutation_type  # type: ignore[attr-defined]
    result_type = graphql.get_named_type(mutation_type.fields[field].type)
    members = {member.name for member in dagster_schema.get_possible_types(result_type)}  # type: ignore[attr-defined]
    assert success_type in members
    success = dagster_schema.get_type(success_type)  # type: ignore[attr-defined]
    assert state_key in success.fields
    state_type = graphql.get_named_type(success.fields[state_key].type)
    assert state_type.name == "InstigationState"
