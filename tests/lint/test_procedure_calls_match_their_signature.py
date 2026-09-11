"""`CALL feature.foo(...)`의 자리표시자가 프로시저 시그니처와 맞는지 검사한다.

## 왜

PostgreSQL의 `CALL`은 **OUT 파라미터까지 세어** 프로시저를 찾는다. 자리 하나가
모자라거나 남으면 다른 시그니처를 찾다 실패하고, 오류는 인자 수를 말하지 않는다:

    asyncpg.exceptions.UndefinedFunctionError: procedure feature.foo(...) does not exist

즉 **그 경로 전량이 실패**한다. 부분 회귀가 아니다.

T-VN-39에서 이 부류가 두 번 나왔다. 재키가 legacy 문자열 축을 없애면서 여러
프로시저의 OUT이 하나씩 줄었는데, 파이썬 호출부의 `NULL::text` 자리표시자는 그대로
남았다:

- `feature.create_manual_curation_item_with_feature_command` — 8 → 7
- `feature.approve_feature_request_with_initial_state` — 5 → 4

둘 다 사람이 읽어서 찾았다. 자리표시자는 이름이 없어서 **읽어도 어느 자리가 남는지
보이지 않는다** — 세어야 보인다. 세는 일을 사람에게 맡기지 않는다.

## 무엇을 정본으로 삼는가

재키가 바꾸는 루틴은 사이드카(`alembic/versions/_<rev>_*.sql`)가, 손대지 않는 루틴은
head 오라클(`alembic/head-schema.sql`)이 정본이다. 사이드카가 우선한다 — 그것이
착지 후의 모습이다.

## 타입도 본다 — OUT 자리까지

처음엔 개수만 봤다. "PostgreSQL은 OUT 자리의 타입을 해석에 쓰지 않는다"고 적어
뒀는데 **그것이 틀렸다.** 2026-09-10 head 오라클이 잡았다:

    CALL feature.resolve_manual_provider_dedup_case_v2(..., NULL::text, ...)
    → procedure feature.resolve_manual_provider_dedup_case_v2(...) does not exist

`o_manual_feature_id`가 재키로 uuid가 됐는데 자리표시자는 `NULL::text`로 남아
있었다. SQL에서 부르는 `CALL`은 OUT 자리도 함수 해석에 넣으므로, 타입이 다르면 그
CALL은 **어떤 프로시저와도 맞지 않는다**.

그래서 호출부가 타입을 **명시한 자리만** 비교한다 — `CAST(:x AS <타입>)`과
`NULL::<타입>`. 맨 바인드(`:x`)나 리터럴은 서버가 문맥에서 정하므로 건드리지
않는다. 판단을 강요하지 결론을 강요하지 않는다.

제품 SQL은 `tests/integration/test_product_sql_parses_against_head.py`가 실제
Parse로 더 강하게 본다. 이 검사가 남는 이유는 **테스트 SQL**이다 — 거기까지는 그
오라클이 닿지 않는다.
"""

from __future__ import annotations

import pathlib
import re

_ROOT = pathlib.Path(__file__).resolve().parents[2]
_SELF = pathlib.Path(__file__).resolve()
_VERSIONS = _ROOT / "alembic" / "versions"
_HEAD_SCHEMA = _ROOT / "alembic" / "head-schema.sql"

#: 파이썬 소스에서 SQL 리터럴로 쓰인 프로시저 호출.
_CALL = re.compile(r"CALL\s+((?:feature|ops|provider_sync)\.[a-z_0-9]+)\s*\(", re.IGNORECASE)
#: pg_dump가 한 줄로 뱉는 완전한 시그니처.
_HEAD_SIGNATURE = re.compile(
    r"^ALTER PROCEDURE ([a-z_]+\.[a-z_0-9]+)\((.*?)\) OWNER TO", re.MULTILINE | re.DOTALL
)
_SIDECAR_SIGNATURE = re.compile(
    r"CREATE (?:OR REPLACE )?PROCEDURE ([a-z_]+\.[a-z_0-9]+)\((.*?)\)\s*\n\s*LANGUAGE",
    re.DOTALL,
)
#: 테스트도 같은 프로시저를 부른다. 처음에 뺐더니 통합 스위트에서 자리표시자
#: 불일치 13건이 `procedure ... does not exist`로 나왔다 — 검사가 안 보는 곳에
#: 같은 결함이 그대로 살아 있었다.
_SEARCH_ROOTS = ("src", "scripts", "packages", "tests")

#: `IN p_name uuid` / `OUT o_name text` / `p_after uuid DEFAULT NULL::uuid`에서
#: 타입만 뽑는다. 모드 키워드와 이름을 떼고, DEFAULT 이후는 버린다.
_PARAMETER_TYPE = re.compile(
    r"\A(?:(?:IN|OUT|INOUT|VARIADIC)\s+)?[a-z_][a-z_0-9]*\s+(.+?)(?:\s+DEFAULT\s.*)?\Z",
    re.IGNORECASE | re.DOTALL,
)
#: 호출부가 타입을 **명시한** 자리. 이 둘만 비교 대상이다.
_CAST_ARGUMENT = re.compile(
    r"\ACAST\s*\(\s*[^()]*?\s+AS\s+([a-zA-Z_][\w \[\]]*?)\s*\)\Z", re.IGNORECASE | re.DOTALL
)
_TYPED_NULL_ARGUMENT = re.compile(
    r"\ANULL\s*::\s*([a-zA-Z_][\w \[\]]*?)\Z", re.IGNORECASE | re.DOTALL
)

#: pg_dump와 손으로 쓴 사이드카가 같은 타입을 다르게 적는다. 비교 전에 하나로 만든다.
_TYPE_ALIASES: dict[str, str] = {
    "timestamptz": "timestamp with time zone",
    "int8": "bigint",
    "int4": "integer",
    "int": "integer",
    "bool": "boolean",
    "float8": "double precision",
    "character varying": "text",
    "varchar": "text",
}


def _split_top_level(text: str) -> list[str]:
    """괄호 깊이 0의 콤마로만 자른다."""
    pieces: list[str] = []
    depth = 0
    current: list[str] = []
    for char in text:
        if char in "([":
            depth += 1
        elif char in ")]":
            depth -= 1
        if char == "," and depth == 0:
            pieces.append("".join(current))
            current = []
            continue
        current.append(char)
    if current:
        pieces.append("".join(current))
    return [piece.strip() for piece in pieces if piece.strip()]


def _normalize_type(raw: str) -> str:
    collapsed = " ".join(raw.split()).lower()
    return _TYPE_ALIASES.get(collapsed, collapsed)


def _parameter_types(declaration: str) -> list[str]:
    types: list[str] = []
    for piece in _split_top_level(declaration):
        match = _PARAMETER_TYPE.match(piece.strip())
        types.append(_normalize_type(match.group(1)) if match else "?")
    return types


def _argument_type(argument: str) -> str | None:
    """호출부가 **명시한** 타입. 서버가 문맥에서 정하는 자리면 ``None``."""
    body = argument.strip()
    for pattern in (_CAST_ARGUMENT, _TYPED_NULL_ARGUMENT):
        match = pattern.match(body)
        if match is not None:
            return _normalize_type(match.group(1))
    return None


def _signature_by_routine() -> dict[str, list[str]]:
    """루틴 이름 → 파라미터 타입 목록(IN + OUT 순서대로). 사이드카가 head를 덮는다."""
    signatures: dict[str, list[str]] = {}
    for match in _HEAD_SIGNATURE.finditer(_HEAD_SCHEMA.read_text(encoding="utf-8")):
        signatures[match.group(1)] = _parameter_types(match.group(2))
    for path in sorted(_VERSIONS.glob("_*.sql")):
        body = path.read_text(encoding="utf-8")
        if re.search(r"판정:\s*[^\n]*무변경", body):
            continue
        for match in _SIDECAR_SIGNATURE.finditer(body):
            signatures[match.group(1)] = _parameter_types(match.group(2))
    return signatures


def _closing_paren(text: str, start: int) -> int:
    depth = 1
    index = start
    while index < len(text) and depth:
        if text[index] == "(":
            depth += 1
        elif text[index] == ")":
            depth -= 1
        index += 1
    return index - 1


def test_procedure_calls_pass_the_declared_number_of_arguments() -> None:
    signatures = _signature_by_routine()
    mismatches: list[str] = []
    wrong_types: list[str] = []

    for root in _SEARCH_ROOTS:
        directory = _ROOT / root
        if not directory.is_dir():
            continue
        for path in sorted(directory.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            if path == _SELF:
                # 이 파일의 docstring이 실패 예시로 `CALL ...`을 인용한다. 자기
                # 자신을 세면 그 예시가 결함으로 잡힌다 — 검사기가 자기 설명을
                # 검사 대상으로 삼는 자리다.
                continue
            source = path.read_text(encoding="utf-8", errors="replace")
            # 파이썬 문자열 연결로 쪼개진 SQL을 한 덩어리로 본다.
            flat = re.sub(r'"\s*\n\s*"', "", source)
            flat = re.sub(r"'\s*\n\s*'", "", flat)
            for match in _CALL.finditer(flat):
                routine = match.group(1)
                declared = signatures.get(routine)
                if declared is None:
                    continue
                end = _closing_paren(flat, match.end())
                arguments = _split_top_level(flat[match.end() : end])
                relative = path.relative_to(_ROOT).as_posix()
                if len(arguments) != len(declared):
                    mismatches.append(
                        f"{relative}: {routine} — 자리표시자 {len(arguments)}개, "
                        f"선언 {len(declared)}개"
                    )
                    continue
                for position, argument in enumerate(arguments):
                    written = _argument_type(argument)
                    expected = declared[position]
                    if written is None or expected in {"?", written}:
                        continue
                    wrong_types.append(
                        f"{relative}: {routine} #{position + 1} — "
                        f"호출부 {written}, 선언 {expected}"
                    )

    assert not mismatches, (
        "프로시저 호출의 자리표시자 수가 시그니처와 다르다:\n  "
        + "\n  ".join(dict.fromkeys(mismatches))
        + "\n\nPostgreSQL의 CALL은 OUT까지 세어 프로시저를 찾는다 — 개수가 어긋나면 "
        "`procedure ... does not exist`로 그 경로 **전량**이 실패한다. 자리표시자는 "
        "이름이 없어 읽어서는 어느 자리가 남는지 보이지 않으므로, 사이드카나 "
        "head 오라클의 시그니처를 열어 세어 맞춰라."
    )
    assert not wrong_types, (
        "프로시저 호출이 명시한 타입이 시그니처와 다르다:\n  "
        + "\n  ".join(dict.fromkeys(wrong_types))
        + "\n\nSQL의 `CALL`은 **OUT 자리의 타입까지** 함수 해석에 넣는다. 한 자리만 "
        "달라도 그 CALL은 어떤 프로시저와도 맞지 않아 `procedure ... does not exist`가 "
        "되고, 오류는 어느 자리가 틀렸는지 말하지 않는다."
    )
