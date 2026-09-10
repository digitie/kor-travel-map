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
from datetime import UTC, datetime
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


def _admin_feature_sort_arguments(module: Any, _builder: Any) -> list[dict[str, Any]]:
    """정렬 축은 모듈이 들고 있는 도메인에서 뽑는다 — 축이 늘면 검사도 는다."""
    return [
        {"sort": sort, "order": order}
        for sort in sorted(module._ADMIN_FEATURE_SORT_COLUMNS)
        for order in ("asc", "desc")
    ]


def _subtype_upsert_arguments(module: Any, _builder: Any) -> list[dict[str, Any]]:
    return [{"kind": kind} for kind in sorted(module.SUBTYPE_TABLES)]


def _dedup_review_count_arguments(_module: Any, _builder: Any) -> list[dict[str, Any]]:
    keys = ("providers", "dataset_keys", "kinds", "categories", "q_like")
    empty: dict[str, Any] = dict.fromkeys(keys)
    return [{"params": empty}, {"params": {**empty, "q_like": "%x%"}}]


def _enrichment_filter_arguments(module: Any, _builder: Any) -> list[dict[str, Any]]:
    """필터 조각은 모듈이 들고 있는 상수를 **호출부가 짝지은 그대로** 쓴다.

    첫 판은 그럴듯한 조각을 지어냈고, head 오라클이 곧바로
    `missing FROM-clause entry for table "review"`로 빨개졌다. 지어낸 조각이 없는
    별칭을 참조한 것이다 — 이 파일이 스스로 적어 둔 규칙("값을 추측하지 말고
    호출부가 실제로 넘기는 것을 보라")을 검사기 자신이 어겼다.

    쌍을 교차곱으로 만들지 않는 것도 같은 이유다. scalar 조각과 optional 조각은
    서로 다른 질의 모양을 전제하므로, 호출부가 만들지 않는 조합은 만들지 않는다.
    """
    optional = (
        module._ENRICHMENT_REVIEW_OPTIONAL_STATUS_FILTER,
        module._ENRICHMENT_REVIEW_OPTIONAL_PROVIDER_FILTER,
    )
    required = (
        module._ENRICHMENT_REVIEW_REQUIRED_STATUS_FILTER,
        module._ENRICHMENT_REVIEW_REQUIRED_PROVIDER_FILTER,
    )
    scalar = (
        module._ENRICHMENT_REVIEW_SCALAR_STATUS_FILTER,
        module._ENRICHMENT_REVIEW_SCALAR_PROVIDER_FILTER,
    )
    pairs = (
        (optional[0], optional[1]),
        (required[0], optional[1]),
        (optional[0], required[1]),
        (required[0], required[1]),
        (scalar[0], scalar[1]),
    )
    return [
        {"status_filter": status, "provider_filter": provider}
        for status, provider in pairs
    ]


def _refresh_view_arguments(_module: Any, _builder: Any) -> list[dict[str, Any]]:
    return [
        {"view_name": "feature.mv_feature_search", "strategy": strategy}
        for strategy in ("refresh", "concurrently")
    ]


def _grant_arguments(_module: Any, _builder: Any) -> list[dict[str, Any]]:
    return [{"schema": "feature", "relation": "features", "privileges": ("SELECT",)}]


def _sequence_grant_arguments(_module: Any, _builder: Any) -> list[dict[str, Any]]:
    return [{"schema": "feature", "relation": "features_row_revision_seq"}]


def _cluster_code_column_arguments(module: Any, builder: Any) -> list[dict[str, Any]]:
    """군집 코드 열은 모듈이 들고 있는 표에서 뽑는다 — 단위가 늘면 검사도 는다."""
    columns = getattr(module, "_CLUSTER_CODE_COL", None)
    if columns is None:
        columns = module._ADMIN_CLUSTER_CODE_COLUMNS
    name = next(iter(inspect.signature(builder).parameters))
    return [{name: column} for column in sorted(set(columns.values()))]


def _nearest_anchor_arguments(module: Any, _builder: Any) -> list[dict[str, Any]]:
    """anchor 술어는 호출부가 쓰는 세 가지 그대로다 — 빈 것과 두 술어."""
    return [
        {"exists_predicate": ""},
        {"exists_predicate": f"AND {module._KMA_FORECAST_PREDICATE}"},
        {"exists_predicate": f"AND {module._OBSERVED_TEMP_PREDICATE}"},
    ]


#: 켜짐/꺼짐으로 SQL 모양을 가르는 필터 인자의 "켜짐" 대역값. 값 자체는
#: 모양에만 쓰이므로(`is not None` 분기) 진위가 아니라 **타입**만 맞으면 된다.
_FILTER_STAND_INS: Final[dict[str, Any]] = {
    "job_id": "01a08a42-22ee-72bc-86d5-8c6d67deba82",
    "level": "error",
    "provider_dataset_id": 1,
    "sync_scope": "full",
    "operation_key": "sync",
    "cursor_occurred_at": datetime(2026, 1, 1, tzinfo=UTC),
}


def _optional_filter_arguments(_module: Any, builder: Any) -> list[dict[str, Any]]:
    """`X | None` 필터 인자의 켜짐/꺼짐 **모든 조합**을 만든다.

    이 조립기들은 인자마다 `is not None` 하나로 절을 붙이거나 뗀다. 조합마다
    다른 문장이 나오고, 재키가 바꾼 축(`CAST(:job_id AS uuid)`)은 그중 일부
    조합에만 나타난다. 하나만 불러서는 볼 수 없다.
    """
    names = [
        parameter.name
        for parameter in inspect.signature(builder).parameters.values()
        if parameter.default is inspect.Parameter.empty
    ]
    assert set(names) <= set(_FILTER_STAND_INS), (
        f"대역값 없는 필터 인자: {sorted(set(names) - set(_FILTER_STAND_INS))}"
    )
    return [
        {
            name: (_FILTER_STAND_INS[name] if flag else None)
            for name, flag in zip(names, combination, strict=True)
        }
        for combination in itertools.product((False, True), repeat=len(names))
    ]


#: bool이 아닌 필수 인자를 가진 조립기에 넣을 값. 도메인이 모듈에 있으면
#: 리터럴을 박지 말고 거기서 뽑는다 — 도메인이 늘 때 검사도 같이 늘어야 한다.
_BUILDER_ARGUMENTS: Final[dict[str, Any]] = {
    "kortravelmap.infra.admin_feature_repo._admin_features_sql": (
        _admin_feature_sort_arguments
    ),
    "kortravelmap.infra.admin_feature_repo._dedup_review_count_sql": (
        _dedup_review_count_arguments
    ),
    "kortravelmap.infra.admin_feature_repo._enrichment_review_sql": (
        _enrichment_filter_arguments
    ),
    "kortravelmap.infra.admin_feature_repo._enrichment_review_count_sql": (
        _enrichment_filter_arguments
    ),
    "kortravelmap.infra.feature_subtype.subtype_upsert_sql": _subtype_upsert_arguments,
    "kortravelmap.infra.batch_dag._refresh_materialized_view_sql": (
        _refresh_view_arguments
    ),
    "kortravelmap.infra.runtime_privileges._grant_sql": _grant_arguments,
    "kortravelmap.infra.runtime_privileges._sequence_grant_sql": (
        _sequence_grant_arguments
    ),
    "kortravelmap.infra.ops_repo._list_import_job_events_sql": (
        _optional_filter_arguments
    ),
    "kortravelmap.infra.ops_repo._scoped_import_job_events_sql": (
        _optional_filter_arguments
    ),
    "kortravelmap.infra.feature_repo._cluster_bbox_sql": (
        _cluster_code_column_arguments
    ),
    "kortravelmap.infra.admin_feature_repo._admin_cluster_bbox_sql": (
        _cluster_code_column_arguments
    ),
    "kortravelmap.infra.weather_repo._nearest_anchor_sql": _nearest_anchor_arguments,
    "kortravelmap.infra.weather_repo._historical_nearest_anchor_sql": (
        _nearest_anchor_arguments
    ),
    "kortravelmap.infra.weather_repo._admin_nearest_anchor_sql": (
        _nearest_anchor_arguments
    ),
}

#: 조립기 수집 하한. 숫자가 목적이 아니라 **수집이 살아 있음**이 목적이다.
_MINIMUM_SQL_BUILDERS: Final[int] = 40
_MINIMUM_CALLED_BUILDERS: Final[int] = 40

#: 이름이 `_sql`로 끝나지만 조립기가 아닌 것. 이유를 적는다.
_NOT_A_SQL_BUILDER: Final[dict[str, str]] = {
    "kortravelmap.infra.scope_repo._provider_datasets_from_sql": (
        "SQL을 **받아서 실행**하는 async 함수다 — 조립기가 아니라 소비자다"
    ),
    "kortravelmap.infra.scope_repo._sigungu_codes_from_sql": (
        "SQL을 **받아서 실행**하는 async 함수다 — 조립기가 아니라 소비자다"
    ),
}


def _builder_results(builder: Any, key: str, module: Any) -> list[tuple[str, str]]:
    """SQL을 조립해 돌려주는 모듈 최상단 함수를 **실제로 불러** 결과를 얻는다.

    상수만 모으면 함수 안에서 조립되는 문장이 통째로 시야 밖에 남는다. 실제로
    그랬다 — `_supersede_stale_notice_sql(close_missing=True)`의
    `CAST(:hidden_before AS text[])`(재키 뒤 42883)를 이 오라클의 첫 판이 놓쳤다.

    **처음엔 bool 스위치와 기본값만 받는 함수로 한정했다.** 그래서 45개 조립기
    중 6개만 불렸다 — 적대 리뷰가 집었다. 나머지는 alias 같은 문자열을
    요구했는데, 그 값은 추측할 것이 아니라 **적어 둘 것**이다. `sort` 축처럼
    모듈이 도메인을 들고 있으면 리터럴 대신 거기서 뽑는다.

    표에 없고 부를 수도 없는 함수는 조용히 빠지지 않는다 —
    :func:`test_every_sql_builder_is_called_or_explained`가 잡는다.
    """
    if key in _NOT_A_SQL_BUILDER:
        return []
    try:
        signature = inspect.signature(builder)
    except (TypeError, ValueError):
        return []
    switches: list[str] = []
    needs_value = False
    for parameter in signature.parameters.values():
        if parameter.kind in {parameter.VAR_POSITIONAL, parameter.VAR_KEYWORD}:
            return []
        if parameter.annotation is bool or parameter.annotation == "bool":
            switches.append(parameter.name)
        elif parameter.default is inspect.Parameter.empty:
            needs_value = True
    supplied: list[dict[str, Any]] = [{}]
    if needs_value:
        factory = _BUILDER_ARGUMENTS.get(key)
        if factory is None:
            return []
        supplied = list(factory(module, builder))
    if len(switches) > 3:  # 조합 폭발 방지 — 이 저장소에는 없다.
        return []
    results: list[tuple[str, str]] = []
    for base in supplied:
        for combination in itertools.product((False, True), repeat=len(switches)):
            kwargs = {**base, **dict(zip(switches, combination, strict=True))}
            try:
                produced = builder(**kwargs)
            except Exception:  # noqa: BLE001 — 부를 수 없는 함수는 이 검사 밖이다.
                return []
            suffix = "".join(f"[{k}={v}]" for k, v in sorted(kwargs.items()))
            results.append((suffix, produced if isinstance(produced, str) else ""))
    return results


def _stand_in_results(builder: Any) -> list[str] | None:
    """표에 없는 조립기를 **부르기만 해 보기 위한** 대역 인자로 부른다.

    대부분의 조립기는 alias 하나를 받아 술어나 JOIN 절 같은 **조각**을 낸다.
    조각은 그 자체로 Parse되지 않고, 판정은 그것을 품는 완성 문장 쪽에서 이미
    끝난다. 그러니 alias의 진위는 이 검사에 아무 영향이 없다 — 필요한 것은
    "부를 수 있는가"뿐이고, 그래서 인자 이름을 그대로 식별자로 쓴다.

    돌려준 것이 **문장**이면 이야기가 다르다. 그건 대역값으로 Parse에 넣을 수
    없는 물건이라(`AND exists_predicate` 같은 것이 그대로 박힌다) 진짜 값을
    `_BUILDER_ARGUMENTS`에 적어야 한다. 그 판정은 호출자가 한다.

    부를 수 없으면 ``None``.
    """
    try:
        signature = inspect.signature(builder)
    except (TypeError, ValueError):
        return None
    kwargs: dict[str, Any] = {}
    switches: list[str] = []
    for parameter in signature.parameters.values():
        if parameter.kind in {parameter.VAR_POSITIONAL, parameter.VAR_KEYWORD}:
            return None
        annotation = parameter.annotation
        written = (
            annotation
            if isinstance(annotation, str)
            else getattr(annotation, "__name__", "")
        )
        if annotation is bool or written == "bool":
            switches.append(parameter.name)
        elif parameter.default is not inspect.Parameter.empty:
            continue
        elif "None" in written:
            kwargs[parameter.name] = None
        elif written == "str":
            kwargs[parameter.name] = parameter.name
        else:
            return None
    produced: list[str] = []
    for combination in itertools.product((False, True), repeat=len(switches)):
        call = {**kwargs, **dict(zip(switches, combination, strict=True))}
        try:
            result = builder(**call)
        except Exception:  # noqa: BLE001 — 부를 수 없으면 그 사실이 답이다.
            return None
        if isinstance(result, str):
            produced.append(result)
    return produced


def _modules() -> list[Any]:
    """검사 대상 패키지의 import 가능한 모듈 전부."""
    modules: list[Any] = []
    for package_name in _PACKAGES:
        try:
            package = importlib.import_module(package_name)
        except ImportError:
            continue
        modules.append(package)
        for info in pkgutil.walk_packages(
            getattr(package, "__path__", []), prefix=package_name + "."
        ):
            try:
                modules.append(importlib.import_module(info.name))
            except Exception:  # noqa: BLE001 — import 못 하는 모듈은 이 검사 밖이다.
                continue
    return modules


def _sql_builders() -> dict[str, tuple[Any, Any]]:
    """``<모듈>.<이름>`` → (함수, 모듈). 이름이 ``_sql``로 끝나는 모듈 최상단 함수."""
    builders: dict[str, tuple[Any, Any]] = {}
    for module in _modules():
        for name, value in vars(module).items():
            if (
                name.endswith("_sql")
                and inspect.isfunction(value)
                and value.__module__ == module.__name__
            ):
                builders[f"{module.__name__}.{name}"] = (value, module)
    return builders


def _collect() -> dict[str, str]:
    """``<모듈>.<이름>`` → SQL 문장."""
    found: dict[str, str] = {}
    for module in _modules():
        for name, value in vars(module).items():
            if not name.endswith("_SQL"):
                continue
            statement = _statement(value)
            if statement is not None:
                found[f"{module.__name__}.{name}"] = statement
    for key, (builder, module) in _sql_builders().items():
        for suffix, produced in _builder_results(builder, key, module):
            statement = _statement(produced)
            if statement is not None:
                found[f"{key}{suffix}"] = statement
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


async def test_every_sql_builder_is_called_or_explained() -> None:
    """이름이 ``_sql``로 끝나는 조립기가 **하나도 빠짐없이** 불렸는지 본다.

    DB를 쓰지 않지만 ``async``다 — 이 모듈의 `pytestmark`가 `asyncio`를 걸어 두고
    있고, 동기 함수에 그 표시가 붙으면 pytest-asyncio가 경고를 오류로 올린다.

    이 오라클의 첫 판은 "bool 아니면 기본값" 조건에 걸리지 않는 조립기를 조용히
    건너뛰었다. 45개 중 6개만 불렸고, 그 사실은 어디에도 나타나지 않았다 —
    검사는 초록이었고 커버리지 숫자도 없었다. 적대 리뷰가 집었다.

    "조용히 빠지는 길"을 없애는 것이 이 검사의 전부다. 부를 값이 필요하면
    `_BUILDER_ARGUMENTS`에 적고, 조립기가 아니면 `_NOT_A_SQL_BUILDER`에 이유를
    적는다. 둘 다 아니면 빨강이다.

    부른 결과가 문장이 아니어도 좋다 — 대부분은 조각(술어·JOIN 절)이고, 그것은
    품는 문장 쪽에서 이미 판정된다. 여기서 재는 것은 **불렀는가**다.
    """
    builders = _sql_builders()
    assert len(builders) >= _MINIMUM_SQL_BUILDERS, (
        f"SQL 조립기가 {len(builders)}개뿐입니다 (하한 {_MINIMUM_SQL_BUILDERS}) — "
        "수집이 깨졌는지 확인하세요."
    )
    uncalled: list[str] = []
    needs_real_arguments: list[str] = []
    called = 0
    for key, (builder, module) in sorted(builders.items()):
        if key in _NOT_A_SQL_BUILDER:
            continue
        if _builder_results(builder, key, module):
            called += 1
            continue
        produced = _stand_in_results(builder)
        if produced is None:
            uncalled.append(key)
            continue
        if any(_statement(body) is not None for body in produced):
            needs_real_arguments.append(key)
            continue
        called += 1
    assert not uncalled, (
        "부르지 못한 SQL 조립기가 있습니다: "
        + ", ".join(uncalled)
        + " — 조립기가 아니면 `_NOT_A_SQL_BUILDER`에 이유를 적으세요. 값을 "
        "추측해 넣지 말고 호출부가 실제로 넘기는 것을 보세요. 도메인이 모듈에 "
        "있으면 리터럴 대신 거기서 뽑습니다."
    )
    assert not needs_real_arguments, (
        "대역 인자로 **완성 문장**을 내는 조립기가 있습니다: "
        + ", ".join(needs_real_arguments)
        + " — 조각이면 대역 alias로 충분하지만 문장은 Parse 대상입니다. 대역값이 "
        "그대로 SQL에 박히면 없는 열을 참조해 거짓 실패가 납니다. 호출부가 실제로 "
        "넘기는 값을 `_BUILDER_ARGUMENTS`에 적으세요."
    )
    assert called >= _MINIMUM_CALLED_BUILDERS, (
        f"실제로 부른 조립기가 {called}개뿐입니다 "
        f"(하한 {_MINIMUM_CALLED_BUILDERS}). `_NOT_A_SQL_BUILDER`가 늘고 있는지 "
        "보세요 — 그 목록이 느는 것 자체가 리뷰 신호입니다."
    )
