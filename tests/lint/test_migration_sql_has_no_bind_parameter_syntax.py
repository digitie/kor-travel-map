"""마이그레이션이 실행할 SQL에 SQLAlchemy 바인드 표기가 없는지 검사한다.

## 왜

`op.execute(statement)`는 문자열을 `text()`로 감싼다. `text()`는 `:이름`을 **바인드
파라미터**로 읽고, 마이그레이션은 파라미터를 하나도 넘기지 않으므로 그런 표기가
하나만 있어도 그 문장은 실행 시점에 죽는다:

    sqlalchemy.exc.StatementError: (InvalidRequestError)
    A value is required for bind parameter 'feature_id'

`text()`는 **SQL 주석을 모른다.** 2026-09-09 T-VN-39에서 사이드카 머리말 주석 한 줄에
설명으로 적어 둔 `CAST(:feature_id AS uuid)` 때문에 마이그레이션이 통째로 죽었고,
그 결과 통합 스위트 아홉 묶음 700여 건이 전부 setup error가 됐다. 진단은
"bind parameter 'feature_id'"라고만 말하지 주석을 가리키지 않는다 — 읽는 사람은
프로시저 본문의 파라미터를 먼저 의심한다.

주석은 실행되지 않는다는 직관이 여기서 틀린다. 그 함정을 사람 눈에 맡기지 않는다.

## 무엇이 걸리고 무엇이 안 걸리는가

**규칙을 발명하지 않고 엔진에서 읽는다.** SQLAlchemy가 실제로 쓰는 정규식은
`TextClause._bind_params_regex`이고, 이 검사는 그것을 그대로 쓴다. 직접 만든 근사치는
반드시 한쪽으로 틀린다 — 처음 쓴 판은 `'service:feature-reference-reconciliation'`이나
`'YYYY-MM-DD"T"HH24:MI:SS'` 같은 **문자열 리터럴 안의 콜론**을 전부 위반으로 셌다.
엔진 규칙은 콜론 앞에 단어 문자가 오면 바인드로 읽지 않으므로 그것들은 애초에
바인드가 아니었다. 걸리는 것은 `CAST(:feature_id AS uuid)`처럼 콜론 앞이 구분자인
경우다.
"""

from __future__ import annotations

import pathlib
import re

from sqlalchemy.sql.elements import TextClause

_ROOT = pathlib.Path(__file__).resolve().parents[2]
_VERSIONS = _ROOT / "alembic" / "versions"

#: SQLAlchemy 자신의 규칙. 근사치를 쓰면 검사가 엔진과 갈라진다.
_BIND = TextClause._bind_params_regex


def _bind_hits(text: str) -> list[tuple[int, str, str]]:
    hits: list[tuple[int, str, str]] = []
    for number, line in enumerate(text.splitlines(), 1):
        for match in _BIND.finditer(line):
            hits.append((number, match.group(1), line.strip()))
    return hits


def test_sidecars_carry_no_bind_parameter_syntax() -> None:
    offenders: list[str] = []
    for path in sorted(_VERSIONS.glob("_*.sql")):
        for number, name, line in _bind_hits(path.read_text(encoding="utf-8")):
            offenders.append(f"{path.name}:{number} :{name} — {line[:90]}")

    assert not offenders, (
        "마이그레이션이 실행할 SQL에 SQLAlchemy 바인드 표기가 있다:\n  "
        + "\n  ".join(offenders)
        + "\n\n`op.execute()`가 이것을 파라미터로 읽고 마이그레이션은 값을 넘기지 않으므로 "
        "그 문장이 실행 시점에 죽는다. **주석 안이어도 마찬가지다** — `text()`는 SQL "
        "주석을 모른다. 설명으로 바인드 표기를 적어야 한다면 콜론을 빼고 쓰라."
    )


def test_inline_migration_statements_carry_no_bind_parameter_syntax() -> None:
    """`.py` 안에 직접 쓴 SQL 리터럴도 같은 함정을 갖는다."""
    offenders: list[str] = []
    statement = re.compile(r'"((?:ALTER|CREATE|DROP|INSERT|UPDATE|DELETE|SET|GRANT|REVOKE)[^"]*)"')
    for path in sorted(_VERSIONS.glob("*.py")):
        source = path.read_text(encoding="utf-8")
        for match in statement.finditer(source):
            for name in _BIND.findall(match.group(1)):
                number = source.count("\n", 0, match.start()) + 1
                offenders.append(f"{path.name}:{number} :{name} — {match.group(1)[:80]}")

    assert not offenders, (
        "마이그레이션 `.py`의 SQL 리터럴에 바인드 표기가 있다:\n  "
        + "\n  ".join(dict.fromkeys(offenders))
        + "\n\n마이그레이션은 파라미터를 넘기지 않는다. 값이 필요하면 리터럴로 박거나 "
        "`op.execute(text(...).bindparams(...))`처럼 값을 함께 주라."
    )
