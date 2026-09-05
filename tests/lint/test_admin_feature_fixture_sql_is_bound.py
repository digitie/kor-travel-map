"""D2 fixture helper의 raw SQL을 **baseline 스키마에 결박**한다.

`scripts/admin_feature_live_fixture.py`는 ORM을 우회하는 raw SQL을 여럿 갖는다.
그 SQL이 참조하는 컬럼은 어디에도 결박돼 있지 않았고, 그래서 스키마가 움직여도
**아무도 알려주지 않았다.** 2026-09-05 실행에서 `entity.provider` /
`entity.dataset_key`가 그렇게 드러났다 — 두 컬럼은
`provider_sync.provider_datasets`의 것인데 helper는 `provider_sync.source_entities`
alias로 읽고 있었다. 그 경로는 배포 스택 seed 도중에야 죽었고, 그때는 이미 rebuild
1회와 lane 실행 1회를 태운 뒤였다.

이 게이트는 helper의 SQL 문자열에서 `FROM/JOIN/USING/UPDATE/INTO <schema>.<table>
AS <alias>`로 **alias→관계를 유도**하고, 같은 SQL 안의 `<alias>.<column>` 참조를
`alembic/baseline/schema.sql`의 실제 컬럼 집합과 대조한다. 한쪽만 바뀌면 여기서
깨진다(AGENTS.md DO NOT 15: 유도 → 결박 → 탐지).

같은 파일의 role escalation 순서도 함께 본다. LOGIN role은 `rolinherit=false`라
membership 권한을 자동으로 갖지 않으므로, `SET ROLE` **전에** 관계를 읽으면 권한
오류로 죽는다. 2026-09-05에 `public.alembic_version`이 정확히 그랬다.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[2]
_SCHEMA = _ROOT / "alembic" / "baseline" / "schema.sql"
_HELPER = _ROOT / "scripts" / "admin_feature_live_fixture.py"

_QUALIFIED = r"[a-z_]+\.[a-z_]+"
_IDENTIFIER = r"[a-z_][a-z0-9_]*"

_TABLE = re.compile(
    r"CREATE TABLE (?P<name>" + _QUALIFIED + r") \((?P<body>.*?)\n\);",
    re.DOTALL,
)
_VIEW = re.compile(r"CREATE (?:MATERIALIZED )?VIEW (?P<name>" + _QUALIFIED + r")")

#: `FROM/JOIN/USING/UPDATE/INTO <schema>.<table> [AS] <alias>`
_ALIASED = re.compile(
    r"\b(?:FROM|JOIN|USING|UPDATE|INTO)\s+(?P<table>"
    + _QUALIFIED
    + r")(?:\s+AS)?\s+(?P<alias>"
    + _IDENTIFIER
    + r")\b",
    re.IGNORECASE,
)
_REFERENCE = re.compile(
    r"\b(?P<alias>" + _IDENTIFIER + r")\.(?P<column>" + _IDENTIFIER + r")\b"
)
_STATEMENT = re.compile(r"\b(?:SELECT|INSERT|UPDATE|DELETE)\b")

#: alias 자리에 올 수 없는 SQL 예약어. 이것들을 alias로 잡으면 대조가 공허해진다.
_KEYWORDS = frozenset(
    {
        "and",
        "as",
        "conflict",
        "cross",
        "do",
        "from",
        "full",
        "group",
        "inner",
        "into",
        "join",
        "left",
        "limit",
        "not",
        "nothing",
        "on",
        "or",
        "order",
        "returning",
        "right",
        "select",
        "set",
        "using",
        "values",
        "where",
        "with",
    }
)


def _schema_relations() -> dict[str, frozenset[str]]:
    """baseline DDL에서 관계 → 컬럼 집합을 유도한다(뷰는 빈 집합 = 미대조)."""

    text = _SCHEMA.read_text(encoding="utf-8")
    relations: dict[str, frozenset[str]] = {}
    for match in _TABLE.finditer(text):
        columns: set[str] = set()
        for line in match.group("body").splitlines():
            stripped = line.strip().rstrip(",")
            if not stripped or stripped.upper().startswith("CONSTRAINT"):
                continue
            name = stripped.split()[0]
            if re.fullmatch(_IDENTIFIER, name):
                columns.add(name)
        relations[match.group("name")] = frozenset(columns)
    for match in _VIEW.finditer(text):
        relations.setdefault(match.group("name"), frozenset())
    return relations


def _helper_statements() -> list[tuple[int, str]]:
    """helper 소스의 SQL 리터럴을 줄번호와 함께 뽑는다."""

    tree = ast.parse(_HELPER.read_text(encoding="utf-8"))
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            value = node.value
            if _STATEMENT.search(value) and "." in value:
                found.append((node.lineno, value))
    return found


def _aliases(sql: str) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for match in _ALIASED.finditer(sql):
        alias = match.group("alias").lower()
        if alias in _KEYWORDS:
            continue
        aliases[alias] = match.group("table").lower()
    return aliases


def _preflight_body() -> str:
    source = _HELPER.read_text(encoding="utf-8")
    start = source.index("async def _prepare_fixture_connection")
    return source[start : source.index("async def _run(", start)]


def test_the_gate_reads_a_real_schema_and_real_sql() -> None:
    """대조 양쪽이 실제로 읽혔는지부터 본다 — 비면 아래 단언이 공허하다."""

    relations = _schema_relations()
    assert len(relations) >= 100, f"관계를 {len(relations)}개만 읽었다 — 파서를 의심하라"
    statements = _helper_statements()
    assert len(statements) >= 10, f"SQL을 {len(statements)}건만 읽었다 — 파서를 의심하라"
    aliased = [sql for _, sql in statements if _aliases(sql)]
    assert len(aliased) >= 5, f"alias를 가진 SQL이 {len(aliased)}건뿐이다 — 파서를 의심하라"


def test_every_aliased_column_reference_exists_in_the_baseline_schema() -> None:
    """helper SQL의 alias 컬럼 참조가 전부 baseline에 존재해야 한다."""

    relations = _schema_relations()
    violations: list[str] = []
    for lineno, sql in _helper_statements():
        aliases = _aliases(sql)
        if not aliases:
            continue
        for match in _REFERENCE.finditer(sql):
            table = aliases.get(match.group("alias").lower())
            if table is None:
                continue
            known = relations.get(table)
            if not known:
                # 미등록 관계·뷰는 컬럼 목록이 없으므로 대조하지 않는다.
                continue
            column = match.group("column").lower()
            if column not in known:
                violations.append(
                    f"line {lineno}: {match.group('alias')}.{column} not in {table}"
                )
    assert violations == [], (
        "helper의 raw SQL이 baseline에 없는 컬럼을 읽는다. "
        f"위반={sorted(set(violations))}. "
        "alias가 가리키는 관계를 고치거나 컬럼 이름을 스키마에 맞춰라 — "
        "**배포 스택 실행 중에 죽게 두지 마라.**"
    )


def test_preflight_reads_no_relation_before_role_escalation() -> None:
    """`SET ROLE` 앞에서는 권한 없이 읽히는 session identity만 읽어야 한다.

    LOGIN role은 `rolinherit=false`라 membership 권한을 자동으로 갖지 않는다.
    """

    body = _preflight_body()
    marker = "SET ROLE {_FIXTURE_SCHEMA_OWNER}"
    assert marker in body, "preflight에서 role escalation을 찾지 못했다 — 게이트가 공허해졌다"
    before = body[: body.index(marker)]
    referenced = re.findall(r"\bFROM\s+(" + _QUALIFIED + r")", before, re.IGNORECASE)
    assert referenced == [], (
        f"role escalation **전에** 관계를 읽고 있다: {sorted(set(referenced))}. "
        "LOGIN role은 rolinherit=false라 이 읽기는 권한 오류로 죽는다. "
        "`SET ROLE` 뒤로 옮겨라 — 여전히 모든 mutation보다 앞이다."
    )


def test_the_alembic_read_that_broke_this_is_after_escalation() -> None:
    """이 게이트를 만들게 한 실제 사례가 계속 덮이는지 본다."""

    body = _preflight_body()
    escalation = body.index("SET ROLE {_FIXTURE_SCHEMA_OWNER}")
    read = body.index("FROM public.alembic_version")
    assert read > escalation, (
        "`public.alembic_version` 읽기가 role escalation보다 앞에 있다. "
        "baseline은 그 SELECT를 소유자와 `ktm_feature_runtime`에만 준다 "
        "(alembic/versions/300_schema_baseline.py)."
    )
