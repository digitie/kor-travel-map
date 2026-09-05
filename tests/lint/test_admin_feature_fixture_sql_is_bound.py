"""D2 fixture helper의 raw SQL을 **baseline 스키마에 결박**한다.

`scripts/admin_feature_live_fixture.py`는 ORM을 우회하는 raw SQL을 여럿 갖는다.
그 SQL이 참조하는 컬럼은 어디에도 결박돼 있지 않았고, 그래서 스키마가 움직여도
**아무도 알려주지 않았다.** 2026-09-05 실행에서 `entity.provider` /
`entity.dataset_key`가 그렇게 드러났다 — 두 컬럼은
`provider_sync.provider_datasets`의 것인데 helper는 `provider_sync.source_entities`
alias로 읽고 있었다. 그 경로는 배포 스택 seed 도중에야 죽었고, 그때는 이미 rebuild
1회와 lane 실행 1회를 태운 뒤였다.

## 이 게이트가 보는 범위 (과장하지 않는다)

`FROM/JOIN/USING/UPDATE/INTO [ONLY] <schema>.<table> [AS] <alias>`로 **alias→관계를
유도**하고, 같은 statement의 `<alias>.<column>` 참조만 `alembic/baseline/schema.sql`의
컬럼 집합과 대조한다. 따라서 **덮지 못하는 것이 있다**:

- alias 없는 bare column 목록(`INSERT INTO t (a, b, c)`)은 대조하지 않는다.
- 뷰는 DDL에 컬럼 목록이 없어 대조하지 않는다(`feature.public_features`).
- `pg_catalog.*`처럼 baseline 밖 관계는 대조하지 않는다.
- 같은 statement에서 한 alias가 서로 다른 관계에 묶이면(중첩 subquery의 alias 충돌)
  **모호하다고 보고 그 alias만 건너뛴다** — 틀린 red를 내지 않기 위해서다.

이 한계는 게이트가 공허하다는 뜻이 아니다. `test_the_gate_still_catches_the_defect_
that_created_it`이 실제 결함 형태에서 red가 되는지 매번 확인한다.

## role escalation 순서

같은 파일의 preflight도 함께 본다. LOGIN role은 `rolinherit=false`라 membership
권한을 자동으로 갖지 않으므로, `SET ROLE` **전에** 관계를 읽으면 권한 오류로 죽는다.
2026-09-05에 `public.alembic_version`이 정확히 그랬다. 여기서는 SQL 리터럴을 **AST로**
집어 순서를 보므로 주석·대소문자·`ONLY`·비수식 이름에 속지 않는다. 실제 실행 순서
자체는 `tests/unit/test_admin_feature_live_acceptance.py`의 stub이 statement 목록으로
관측해 고정한다 — 이 lint는 그 위의 값싼 두 번째 그물이다.
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

#: 숫자를 포함하는 관계가 실재한다(`ops.c6c_cancel_probe_fixtures`,
#: `ops.tvn36_legacy_freeze_preflight_manifest`). 숫자를 빼면 그 둘이 파서와
#: alias 추출기 **양쪽에서** 보이지 않게 된다.
_NAME = r"[a-z_][a-z0-9_]*"
_QUALIFIED = _NAME + r"\." + _NAME

_CREATE_TABLE = re.compile(
    r"^CREATE TABLE (?P<name>" + _QUALIFIED + r") \((?P<body>.*?)\n\);",
    re.DOTALL | re.MULTILINE,
)
_CREATE_TABLE_HEADER = re.compile(r"^CREATE TABLE (?P<name>\S+)", re.MULTILINE)
_CREATE_VIEW = re.compile(
    r"^CREATE (?:MATERIALIZED )?VIEW (?P<name>" + _QUALIFIED + r")", re.MULTILINE
)

#: `FROM/JOIN/USING/UPDATE/INTO [ONLY] <schema>.<table> [AS] <alias>`.
#: 앞자리에 `,`도 받는다 — `FROM a AS x, b AS y`의 두 번째 항이 그렇지 않으면 통째로
#: 빠지고, 그 alias의 컬럼 참조가 조용히 검사되지 않는다.
_ALIASED = re.compile(
    r"(?:\b(?:FROM|JOIN|USING|UPDATE|INTO)\b|,)\s*(?:ONLY\s+)?(?P<table>"
    + _QUALIFIED
    + r")(?:\s+AS)?\s+(?P<alias>"
    + _NAME
    + r")\b",
    re.IGNORECASE,
)
#: 대소문자를 무시한다. `_ALIASED`만 IGNORECASE이고 여기가 아니면, 대문자 SQL이
#: alias map은 채우면서 참조는 0건이 되어 **모든 자기검사를 통과한 채** 공허해진다.
_REFERENCE = re.compile(
    r"\b(?P<alias>" + _NAME + r")\.(?P<column>" + _NAME + r")\b", re.IGNORECASE
)
_STATEMENT = re.compile(r"\b(?:SELECT|INSERT|UPDATE|DELETE)\b", re.IGNORECASE)
_FROM_ANY = re.compile(r"\bFROM\s+(?:ONLY\s+)?(?P<name>" + _NAME + r"(?:\." + _NAME + r")?)", re.IGNORECASE)

#: alias 자리에 올 수 없는 SQL 예약어. 이것들을 alias로 잡으면 대조가 공허해진다.
_KEYWORDS = frozenset(
    {
        "and", "as", "conflict", "cross", "do", "except", "for", "from", "full",
        "group", "having", "inner", "into", "join", "lateral", "left", "limit",
        "natural", "not", "nothing", "offset", "on", "only", "or", "order",
        "returning", "right", "select", "set", "union", "using", "values",
        "where", "window", "with",
    }
)

_ESCALATION = "SET ROLE "
_PRIVILEGED_READ = "public.alembic_version"


def _schema_relations() -> dict[str, frozenset[str]]:
    """baseline DDL에서 관계 → 컬럼 집합을 유도한다(뷰는 빈 집합 = 미대조)."""

    text = _SCHEMA.read_text(encoding="utf-8")
    relations: dict[str, frozenset[str]] = {}
    for match in _CREATE_TABLE.finditer(text):
        columns: set[str] = set()
        for line in match.group("body").splitlines():
            stripped = line.strip().rstrip(",")
            if not stripped or stripped.upper().startswith("CONSTRAINT"):
                continue
            name = stripped.split()[0]
            if re.fullmatch(_NAME, name):
                columns.add(name)
        relations[match.group("name")] = frozenset(columns)
    for match in _CREATE_VIEW.finditer(text):
        relations.setdefault(match.group("name"), frozenset())
    return relations


def _sql_literals(node: ast.AST) -> list[tuple[int, int, str]]:
    """`node` 아래의 SQL 리터럴을 (줄, 열, 본문)으로 소스 순서대로 뽑는다.

    f-string(`JoinedStr`)도 본다 — `SET ROLE {_FIXTURE_SCHEMA_OWNER}`가 그 형태다.
    독스트링과 떠 있는 문자열 표현식은 **뺀다** — 실행되는 SQL이 아니라 산문이라,
    거기 적힌 관계 이름이 순서 검사를 거짓으로 red로 만든다.
    """

    prose = {
        id(child.value)
        for child in ast.walk(node)
        if isinstance(child, ast.Expr) and isinstance(child.value, ast.Constant)
    }
    found: list[tuple[int, int, str]] = []
    for child in ast.walk(node):
        if id(child) in prose:
            continue
        if isinstance(child, ast.Constant) and isinstance(child.value, str):
            found.append((child.lineno, child.col_offset, child.value))
        elif isinstance(child, ast.JoinedStr):
            rendered = "".join(
                part.value
                for part in child.values
                if isinstance(part, ast.Constant) and isinstance(part.value, str)
            )
            found.append((child.lineno, child.col_offset, rendered))
    return sorted(found)


def _helper_tree() -> ast.Module:
    return ast.parse(_HELPER.read_text(encoding="utf-8"))


def _helper_statements() -> list[tuple[int, str]]:
    """helper 소스의 SQL 리터럴을 줄번호와 함께 뽑는다."""

    return [
        (lineno, sql)
        for lineno, _, sql in _sql_literals(_helper_tree())
        if _STATEMENT.search(sql) and "." in sql
    ]


def _aliases(sql: str) -> dict[str, str]:
    """alias → 관계. 한 alias가 서로 다른 관계에 묶이면 **모호**하므로 뺀다."""

    bound: dict[str, str] = {}
    ambiguous: set[str] = set()
    for match in _ALIASED.finditer(sql):
        alias = match.group("alias").lower()
        if alias in _KEYWORDS:
            continue
        table = match.group("table").lower()
        if bound.get(alias, table) != table:
            ambiguous.add(alias)
        bound[alias] = table
    for alias in ambiguous:
        del bound[alias]
    return bound


def _violations(source_helper: str | None = None) -> list[str]:
    """helper SQL이 baseline에 없는 컬럼을 읽는 지점을 모은다."""

    relations = _schema_relations()
    tree = ast.parse(source_helper) if source_helper is not None else _helper_tree()
    statements = [
        (lineno, sql)
        for lineno, _, sql in _sql_literals(tree)
        if _STATEMENT.search(sql) and "." in sql
    ]
    found: list[str] = []
    for lineno, sql in statements:
        aliases = _aliases(sql)
        if not aliases:
            continue
        for match in _REFERENCE.finditer(sql):
            table = aliases.get(match.group("alias").lower())
            if table is None:
                continue
            known = relations.get(table)
            if not known:
                # 뷰·baseline 밖 관계는 컬럼 목록이 없으므로 대조하지 않는다.
                continue
            column = match.group("column").lower()
            if column not in known:
                found.append(
                    f"line {lineno}: {match.group('alias')}.{column} not in {table}"
                )
    return sorted(set(found))


def _preflight_function() -> ast.AST:
    for node in ast.walk(_helper_tree()):
        if (
            isinstance(node, ast.AsyncFunctionDef)
            and node.name == "_prepare_fixture_connection"
        ):
            return node
    raise AssertionError("preflight 함수를 찾지 못했다 — 이 게이트가 공허해졌다")


def test_the_schema_parser_sees_every_create_table() -> None:
    """파서가 DDL의 `CREATE TABLE`을 **하나도 빠뜨리지 않는지** 본다.

    이름에 숫자가 있는 관계를 놓치면 그 관계의 컬럼 참조가 조용히 검사되지 않는다.
    """

    text = _SCHEMA.read_text(encoding="utf-8")
    declared = {match.group("name") for match in _CREATE_TABLE_HEADER.finditer(text)}
    parsed = set(_schema_relations())
    missing = sorted(declared - parsed)
    assert missing == [], (
        f"DDL이 선언한 관계 {len(declared)}개 중 {len(missing)}개를 파서가 놓쳤다: "
        f"{missing}. 이 관계들의 컬럼 참조는 대조 없이 통과한다 — 패턴을 넓혀라."
    )


def test_the_gate_reads_a_real_schema_and_real_sql() -> None:
    """대조 양쪽이 실제로 읽혔는지부터 본다 — 비면 아래 단언이 공허하다."""

    relations = _schema_relations()
    assert len(relations) >= 100, f"관계를 {len(relations)}개만 읽었다 — 파서를 의심하라"
    statements = _helper_statements()
    assert len(statements) >= 10, f"SQL을 {len(statements)}건만 읽었다 — 파서를 의심하라"
    compared = [
        sql
        for _, sql in statements
        if any(
            _REFERENCE.search(sql) and alias in sql.lower() for alias in _aliases(sql)
        )
    ]
    assert len(compared) >= 5, (
        f"실제로 컬럼이 대조된 SQL이 {len(compared)}건뿐이다 — 파서를 의심하라"
    )


def test_every_aliased_column_reference_exists_in_the_baseline_schema() -> None:
    """helper SQL의 alias 컬럼 참조가 전부 baseline에 존재해야 한다."""

    violations = _violations()
    assert violations == [], (
        "helper의 raw SQL이 baseline에 없는 컬럼을 읽는다. "
        f"위반={violations}. "
        "alias가 가리키는 관계를 고치거나 컬럼 이름을 스키마에 맞춰라 — "
        "**배포 스택 실행 중에 죽게 두지 마라.**"
    )


def test_the_gate_still_catches_the_defect_that_created_it() -> None:
    """게이트가 실제 결함 형태에서 red가 되는지 매번 확인한다.

    한계 목록(모듈 독스트링)이 늘어나도 이 단언이 남아 있으면 게이트가 공허해지지
    않는다.
    """

    source = _HELPER.read_text(encoding="utf-8")
    broken = source.replace(
        "AND dataset.provider = :provider", "AND entity.provider = :provider", 1
    )
    assert broken != source, "변이 지점을 찾지 못했다 — 이 확인이 공허해졌다"
    assert any("entity.provider" in item for item in _violations(broken)), (
        "결함을 되살려도 게이트가 조용하다 — 대조가 공허하다"
    )


def test_preflight_reads_no_relation_before_role_escalation() -> None:
    """`SET ROLE` 앞에서는 권한 없이 읽히는 session identity만 읽어야 한다.

    LOGIN role은 `rolinherit=false`라 membership 권한을 자동으로 갖지 않는다.
    """

    literals = _sql_literals(_preflight_function())
    escalation = [
        index for index, (_, _, sql) in enumerate(literals) if _ESCALATION in sql
    ]
    assert escalation, "preflight에서 role escalation을 찾지 못했다 — 게이트가 공허해졌다"
    before = literals[: escalation[0]]
    referenced = sorted(
        {
            match.group("name").lower()
            for _, _, sql in before
            for match in _FROM_ANY.finditer(sql)
        }
    )
    assert referenced == [], (
        f"role escalation **전에** 관계를 읽고 있다: {referenced}. "
        "LOGIN role은 rolinherit=false라 이 읽기는 권한 오류로 죽는다. "
        "`SET ROLE` 뒤로 옮겨라 — 여전히 모든 mutation보다 앞이다."
    )


def test_the_alembic_read_that_broke_this_is_after_escalation() -> None:
    """이 게이트를 만들게 한 실제 사례가 계속 덮이는지 본다."""

    literals = _sql_literals(_preflight_function())
    escalation = next(
        index for index, (_, _, sql) in enumerate(literals) if _ESCALATION in sql
    )
    reads = [
        index
        for index, (_, _, sql) in enumerate(literals)
        if _PRIVILEGED_READ in sql.lower()
    ]
    assert reads, (
        f"preflight가 `{_PRIVILEGED_READ}`를 더 이상 읽지 않는다. "
        "schema head 확인을 없앴다면 이 게이트도 함께 다시 판단하라."
    )
    assert min(reads) > escalation, (
        f"`{_PRIVILEGED_READ}` 읽기가 role escalation보다 앞에 있다. "
        "baseline은 그 SELECT를 소유자와 `ktm_feature_runtime`에만 준다 "
        "(alembic/versions/300_schema_baseline.py)."
    )
