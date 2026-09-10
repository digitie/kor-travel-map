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
import inspect
import itertools
import pkgutil
import re
from typing import Any, Final

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

#: 훑을 패키지. 제품 SQL이 사는 곳 전부.
#:
#: `kortravelmap.api`/`kortravelmap.dagster`를 **따로 적는다.** 둘은 별도 배포
#: 패키지가 editable로 심는 하위 이름이라 `kortravelmap.__path__`에 경로가 아니라
#: finder hook 문자열로 들어간다. `pkgutil.walk_packages`는 그 hook을 열거하지
#: 못하므로 부모만 훑으면 API의 SQL이 통째로 시야 밖이다 — 첫 판이 정확히 그랬다
#: (`kortravelmap.api` 수집 0건). 아래 하한 단언이 그 침묵을 다시 못 만들게 한다.
_PACKAGES: Final[tuple[str, ...]] = (
    "kortravelmap",
    "kortravelmap.api",
    "kortravelmap.dagster",
)

#: 패키지별 수집 하한. 숫자 자체가 목적이 아니라 **0이 아님**이 목적이다.
_MINIMUM_STATEMENTS: Final[dict[str, int]] = {
    "kortravelmap.infra": 300,
    "kortravelmap.api": 10,
}

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

#: head 오라클이 판정할 수 없는 문장. 이유를 같이 적는다 — 목록이 느는 것 자체가
#: 리뷰 신호다.
_OUTSIDE_THE_HEAD_ORACLE: Final[dict[str, str]] = {
    # 런타임이 `to_regclass('feature.feature_files') IS NOT NULL`로 먼저 묻고
    # 없으면 이 SQL을 아예 실행하지 않는다(선택적 관계). head에 그 표가 없는 것이
    # 정상이므로 Parse 실패는 결함이 아니다.
    "kortravelmap.infra.admin_feature_repo._ADMIN_FEATURE_FILES_SQL": (
        "feature.feature_files는 선택적 관계 — 호출부가 to_regclass로 먼저 묻는다"
    ),
    "kortravelmap.infra.consistency._F8_FEATURE_FILE_METADATA_ROWS_SQL": (
        "feature.feature_files는 선택적 관계 — 호출부가 to_regclass로 먼저 묻는다"
    ),
}

#: **다른 스키마 세대**를 겨냥한 SQL. h35 cutover CLI가 0063~0079 고정 세대에서
#: 같은 import 경로를 돌린다(ADR-075, 역사 표면 보존). 그 세대의 오라클은 head가
#: 아니므로 여기서 판정하지 않는다.
#:
#: `curation_repo._pre_uuid_feature_id_recordset`의 docstring이 이 세대의 현재
#: 상태를 들고 있다 — 재키 뒤 그 경로는 세대 분기가 없는 공용 표면 셋 때문에 이미
#: 반쪽이고, 되살릴지 은퇴시킬지는 열린 결정이다.
_FROZEN_GENERATION_MARKERS: Final[tuple[str, ...]] = (
    "_FROZEN_H35_",
    "_PRE_UUID_",
    "_PRE_REVISION_",
)


def _statement(value: object) -> str | None:
    """SQL 문장이면 그것을, 조각이거나 SQL이 아니면 ``None``."""
    if not isinstance(value, str):
        return None
    body = _LEADING_NOISE.sub("", value).lstrip()
    if not body:
        return None
    head = body.split(None, 1)[0].upper().rstrip("(")
    return value if head in _VERBS else None


def _builder_results(builder: Any) -> list[tuple[str, str]]:
    """SQL을 조립해 돌려주는 모듈 최상단 함수를 **실제로 불러** 결과를 얻는다.

    상수만 모으면 함수 안에서 조립되는 문장이 통째로 시야 밖에 남는다. 실제로
    그랬다 — `_supersede_stale_notice_sql(close_missing=True)`의
    `CAST(:hidden_before AS text[])`(재키 뒤 42883)를 이 오라클의 첫 판이 놓쳤다.

    부를 수 있는 것은 인자가 전부 bool이거나 기본값을 가진 순수 조립 함수뿐이다.
    나머지는 건드리지 않는다.
    """
    try:
        signature = inspect.signature(builder)
    except (TypeError, ValueError):
        return []
    switches: list[str] = []
    for parameter in signature.parameters.values():
        if parameter.kind in {parameter.VAR_POSITIONAL, parameter.VAR_KEYWORD}:
            return []
        if parameter.annotation is bool or parameter.annotation == "bool":
            switches.append(parameter.name)
        elif parameter.default is inspect.Parameter.empty:
            return []
    if len(switches) > 3:  # 조합 폭발 방지 — 이 저장소에는 없다.
        return []
    results: list[tuple[str, str]] = []
    for combination in itertools.product((False, True), repeat=len(switches)):
        kwargs = dict(zip(switches, combination, strict=True))
        try:
            produced = builder(**kwargs)
        except Exception:  # noqa: BLE001 — 부를 수 없는 함수는 이 검사 밖이다.
            return []
        suffix = "".join(f"[{k}={v}]" for k, v in kwargs.items())
        results.append((suffix, produced if isinstance(produced, str) else ""))
    return results


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
                if name.endswith("_SQL"):
                    statement = _statement(value)
                    if statement is not None:
                        found[f"{module.__name__}.{name}"] = statement
                elif (
                    name.endswith("_sql")
                    and inspect.isfunction(value)
                    and value.__module__ == module.__name__
                ):
                    for suffix, produced in _builder_results(value):
                        statement = _statement(produced)
                        if statement is not None:
                            found[f"{module.__name__}.{name}{suffix}"] = statement
    return found


def _fragments(statements: dict[str, str]) -> set[str]:
    """다른 문장 **안에** 통째로 들어가는 것은 조각이다.

    조각(CTE 본문, INSERT 접두)은 그 자체로 Parse되지 않지만, 그것을 품는 완성
    문장이 같이 수집돼 있으므로 판정은 그쪽에서 이미 이뤄진다. 이름 규약이 아니라
    **포함 관계**로 가리는 이유는, 품는 문장이 사라지면 조각이 다시 검사 대상이
    되게 하기 위해서다.
    """
    bodies = sorted(set(statements.values()), key=len, reverse=True)
    fragment_bodies = {
        body
        for index, body in enumerate(bodies)
        if any(body in longer for longer in bodies[:index])
    }
    return {name for name, body in statements.items() if body in fragment_bodies}


async def test_every_product_sql_statement_parses_against_the_head_schema(
    migrated_engine: AsyncEngine,
) -> None:
    statements = _collect()
    assert len(statements) >= 150, (
        f"SQL 문장을 {len(statements)}개만 모았다 — `_..._SQL` 명명 규약이 바뀌었거나 "
        "import가 조용히 실패했다. 이 검사가 대상을 잃었다."
    )
    for prefix, minimum in _MINIMUM_STATEMENTS.items():
        seen = sum(1 for name in statements if name.startswith(prefix + "."))
        assert seen >= minimum, (
            f"`{prefix}`에서 SQL 문장을 {seen}개만 모았다(하한 {minimum}). "
            "editable 설치의 finder hook은 `pkgutil.walk_packages`가 열거하지 못한다 — "
            "`_PACKAGES`에 그 이름을 직접 적어야 한다."
        )
    skipped = _fragments(statements)

    failures: list[str] = []
    dialect = migrated_engine.dialect
    raw = await migrated_engine.raw_connection()
    try:
        driver: Any = raw.driver_connection
        for qualified_name, sql in sorted(statements.items()):
            if qualified_name in skipped or qualified_name in _OUTSIDE_THE_HEAD_ORACLE:
                continue
            if any(marker in qualified_name for marker in _FROZEN_GENERATION_MARKERS):
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
