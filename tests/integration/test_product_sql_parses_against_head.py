"""제품 코드의 SQL 상수를 **실제 head 스키마에** Parse시켜 본다.

## 왜 이 파일이 있는가

T-VN-39 재키가 오래 걸린 이유는 하나로 모인다 — **범위를 프록시에서 유도했다.**
본문 토큰, 파이썬 선언 리터럴, 인자 이름, 별칭 붙은 읽기. 네 번 유도했고 네 번
틀렸다. 그때마다 남은 결함은 통합 테스트를 한 번 다 돌려야 드러났고, 한 번 도는 데
수십 분이 든다. 게다가 실패 하나가 픽스처를 죽이면 그 뒤의 전부가 가려진다.

그런데 이 부류의 결함은 **실행이 필요 없다.** `operator does not exist: uuid = text`
(42883), `inconsistent types deduced for parameter $1`(42P08), `column "x" does not
exist`(42703), `is of type uuid but expression is of type text`(42804),
`could not determine data type of parameter $1`(42P18) — 전부 PostgreSQL이 **Parse
단계**에서 내는 오류다. 행이 하나도 없어도, 픽스처를 하나도 세우지 않아도 난다.

그래서 여기서는 제품 SQL을 전부 모아 head 스키마에 Parse만 시킨다. 오라클은 head
자신이다. 프록시가 아니다.

## 무엇을 모으는가

이 저장소는 SQL 상수를 `_..._SQL` 이름으로 모듈 최상단에 두는 규약을 지킨다.
그래서 모듈을 **import해서** 그 이름들을 읽는다 — AST로 리터럴을 긁으면 f-string
합성과 `+` 연결을 놓치고, 그것이 또 하나의 프록시가 된다.

조각(컬럼 목록, CTE 본문)은 문장이 아니므로 건너뛴다. 판단 기준은 "SQL 동사로
시작하는가" 하나다.

## 무엇을 하지 않는가

실행하지 않는다. 따라서 런타임 롤의 권한, 행 수준 결과, 트랜잭션 의미는 보지
않는다. 그것은 각자의 통합 테스트가 본다. 여기서 잡히는 것은 **문장이 스키마와
말이 되는가** 하나뿐이고, 그 하나가 재키에서 가장 비쌌다.
"""

from __future__ import annotations

import importlib
import pkgutil
import re
from typing import Any, Final

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

#: 훑을 패키지. 제품 SQL이 사는 곳 전부.
_PACKAGES: Final[tuple[str, ...]] = (
    "kortravelmap",
    "kor_travel_map_api",
    "kortravelmap.dagster",
)

#: 문장으로 볼 시작 토큰. 조각(컬럼 목록·CTE 본문·술어)은 여기 걸리지 않는다.
_VERBS: Final[tuple[str, ...]] = (
    "SELECT",
    "INSERT",
    "UPDATE",
    "DELETE",
    "CALL",
    "WITH",
    "VALUES",
)

#: 앞머리의 SQL 주석과 공백. `--` 줄과 `/* */` 블록.
_LEADING_NOISE = re.compile(r"\A(?:\s|--[^\n]*\n|/\*.*?\*/)+", re.DOTALL)

#: Parse가 아니라 **실행 문맥**을 요구하는 문장. 이유를 같이 적는다 — 목록이 느는
#: 것 자체가 리뷰 신호다.
_NOT_PARSEABLE_WITHOUT_CONTEXT: Final[dict[str, str]] = {}


def _statement(value: object) -> str | None:
    """SQL 문장이면 그것을, 조각이거나 SQL이 아니면 ``None``."""
    if not isinstance(value, str):
        return None
    body = _LEADING_NOISE.sub("", value).lstrip()
    if not body:
        return None
    head = body.split(None, 1)[0].upper().rstrip("(")
    return value if head in _VERBS else None


def _collect() -> dict[str, str]:
    """``<모듈>.<이름>`` → SQL 문장."""
    found: dict[str, str] = {}
    for package_name in _PACKAGES:
        try:
            package = importlib.import_module(package_name)
        except ImportError:
            continue
        modules = [package]
        for info in pkgutil.walk_packages(
            getattr(package, "__path__", []), prefix=package_name + "."
        ):
            try:
                modules.append(importlib.import_module(info.name))
            except Exception:  # noqa: BLE001 — import 못 하는 모듈은 이 검사 밖이다.
                continue
        for module in modules:
            for name, value in vars(module).items():
                if not name.endswith("_SQL"):
                    continue
                statement = _statement(value)
                if statement is not None:
                    found[f"{module.__name__}.{name}"] = statement
    return found


async def test_every_product_sql_statement_parses_against_the_head_schema(
    migrated_engine: AsyncEngine,
) -> None:
    statements = _collect()
    assert len(statements) >= 150, (
        f"SQL 문장을 {len(statements)}개만 모았다 — `_..._SQL` 명명 규약이 바뀌었거나 "
        "import가 조용히 실패했다. 이 검사가 대상을 잃었다."
    )

    failures: list[str] = []
    dialect = migrated_engine.dialect
    raw = await migrated_engine.raw_connection()
    try:
        driver: Any = raw.driver_connection
        for qualified_name, sql in sorted(statements.items()):
            if qualified_name in _NOT_PARSEABLE_WITHOUT_CONTEXT:
                continue
            compiled = str(text(sql).compile(dialect=dialect))
            try:
                await driver.prepare(compiled)
            except Exception as exc:  # noqa: BLE001 — 어떤 Parse 오류든 결함이다.
                code = getattr(exc, "sqlstate", None) or type(exc).__name__
                detail = str(exc).strip().splitlines()[0]
                position = getattr(exc, "position", None)
                where = f" @{position}" if position else ""
                failures.append(f"{qualified_name}: [{code}]{where} {detail}")
    finally:
        raw.close()

    assert not failures, (
        f"제품 SQL {len(failures)}개가 head 스키마에서 Parse되지 않는다:\n  "
        + "\n  ".join(failures)
        + "\n\n이 오류는 전부 PostgreSQL의 **Parse 단계** 산물이라 행 하나 없이도 난다. "
        "통합 테스트를 다 돌려서 발견할 부류가 아니었다는 뜻이다.\n"
        "정말로 실행 문맥이 있어야만 Parse되는 문장이라면 "
        "`_NOT_PARSEABLE_WITHOUT_CONTEXT`에 이유와 함께 적어라."
    )
