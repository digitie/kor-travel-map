"""`CALL feature.foo(...)`의 자리표시자 수가 프로시저 시그니처와 맞는지 검사한다.

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

## 검사하지 않는 것

인자의 **타입**은 보지 않는다. 호출부는 `NULL::text` 같은 자리표시자를 쓰고 그
타입이 OUT 선언과 다를 수 있는데, PostgreSQL은 OUT 자리의 타입을 해석에 쓰지
않는다. 여기서 잡으려는 것은 **개수**뿐이다.
"""

from __future__ import annotations

import pathlib
import re

_ROOT = pathlib.Path(__file__).resolve().parents[2]
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
_SEARCH_ROOTS = ("src", "scripts", "packages")


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


def _arity_by_routine() -> dict[str, int]:
    """루틴 이름 → 전체 파라미터 수(IN + OUT). 사이드카가 head를 덮는다."""
    arity: dict[str, int] = {}
    for match in _HEAD_SIGNATURE.finditer(_HEAD_SCHEMA.read_text(encoding="utf-8")):
        arity[match.group(1)] = len(_split_top_level(match.group(2)))
    for path in sorted(_VERSIONS.glob("_*.sql")):
        body = path.read_text(encoding="utf-8")
        if re.search(r"판정:\s*[^\n]*무변경", body):
            continue
        for match in _SIDECAR_SIGNATURE.finditer(body):
            arity[match.group(1)] = len(_split_top_level(match.group(2)))
    return arity


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
    arity = _arity_by_routine()
    mismatches: list[str] = []

    for root in _SEARCH_ROOTS:
        directory = _ROOT / root
        if not directory.is_dir():
            continue
        for path in sorted(directory.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            source = path.read_text(encoding="utf-8", errors="replace")
            # 파이썬 문자열 연결로 쪼개진 SQL을 한 덩어리로 본다.
            flat = re.sub(r'"\s*\n\s*"', "", source)
            flat = re.sub(r"'\s*\n\s*'", "", flat)
            for match in _CALL.finditer(flat):
                routine = match.group(1)
                declared = arity.get(routine)
                if declared is None:
                    continue
                end = _closing_paren(flat, match.end())
                passed = len(_split_top_level(flat[match.end() : end]))
                if passed != declared:
                    relative = path.relative_to(_ROOT).as_posix()
                    mismatches.append(
                        f"{relative}: {routine} — 자리표시자 {passed}개, 선언 {declared}개"
                    )

    assert not mismatches, (
        "프로시저 호출의 자리표시자 수가 시그니처와 다르다:\n  "
        + "\n  ".join(dict.fromkeys(mismatches))
        + "\n\nPostgreSQL의 CALL은 OUT까지 세어 프로시저를 찾는다 — 개수가 어긋나면 "
        "`procedure ... does not exist`로 그 경로 **전량**이 실패한다. 자리표시자는 "
        "이름이 없어 읽어서는 어느 자리가 남는지 보이지 않으므로, 사이드카나 "
        "head 오라클의 시그니처를 열어 세어 맞춰라."
    )
