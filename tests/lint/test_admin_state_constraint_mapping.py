"""admin state 경로의 23514가 조용히 catch-all 500이 되지 못하게 한다.

## 왜 이 게이트가 필요한가

`_raise_admin_state_procedure_error`는 매핑에 없는 23514를 raw로 다시 던진다. 그 자체는
옳은 기본값이다 — 진짜 불변식 위반(=버그)을 도메인 오류로 바꾸면 버그가 정상 응답처럼
보인다. **문제는 "분류를 잊은 것"과 "버그다"가 그 기본값에서 구별되지 않는다는 것이다.**

2026-08-12에 `ck_features_state_tuple`이 정확히 그렇게 새어 catch-all 500이 됐다. 그
사고 뒤 코드 주석이 근거로 인용한 fail-close 테스트
`test_admin_state_error_mapping_names_exist_in_ddl`은 **저장소에 없었다**(2026-09-08
실측 — docstring이 있지도 않은 안전망을 가리키고 있었다). 그 상태에서 이 게이트를
만들자 **raise되는데 어디에도 분류되지 않은 제약이 넷** 더 나왔다.

## 무엇을 어떻게 유도하는가

이름 목록을 여기 박지 않는다 — 박으면 그것이 세 번째 정본이 되고, 갱신 안 된 쪽을 읽은
사람이 틀린 작업을 한다(AGENTS.md DO NOT 15). 대신 baseline schema에서 **폐포를 계산**한다.

1. 라우터가 부르는 두 진입 프로시저에서 시작해 `CALL`/`PERFORM`/`SELECT feature.*`를
   따라가며 도달하는 routine을 모은다.
2. 그 본문이 `USING ... CONSTRAINT = '...'`로 **직접 raise하는** 이름을 모은다.
3. 그 본문이 **쓰는** relation의 CHECK 제약 이름을 모은다 — 테이블 CHECK는 프로시저가
   raise하지 않고 DML에서 터지므로 2번만으로는 놓친다. `ck_features_state_tuple`이
   정확히 그 종류였다.

셋의 합집합이 이 경로에서 도달 가능한 후보다. 각각은 conflict / validation / unexpected
중 **정확히 하나**에 있어야 한다.
"""

from __future__ import annotations

import pathlib
import re
from typing import Final

import pytest

from kortravelmap.infra.admin_feature_repo import (
    _ADMIN_STATE_CONFLICT_CONSTRAINTS,
    _ADMIN_STATE_UNEXPECTED_CONSTRAINTS,
    _ADMIN_STATE_VALIDATION_CONSTRAINTS,
)

_SCHEMA: Final[pathlib.Path] = (
    pathlib.Path(__file__).resolve().parents[2] / "alembic" / "baseline" / "schema.sql"
)

#: 라우터가 실제로 부르는 진입점. `admin_feature_repo.py`의 `CALL` 문과 같아야 한다.
_ENTRY_ROUTINES: Final[tuple[str, ...]] = (
    "transition_admin_feature_state",
    "reactivate_admin_feature_state",
)

_ROUTINE_HEAD = re.compile(
    r"^CREATE (?:PROCEDURE|FUNCTION) (?:feature|ops)\.([a-z0-9_]+)\(",
    re.MULTILINE,
)
_CALLS = re.compile(r"\b(?:CALL|PERFORM|SELECT)\s+(?:feature|ops)\.([a-z0-9_]+)\s*\(")
_RAISED_CONSTRAINT = re.compile(r"CONSTRAINT = '([a-z0-9_]+)'")
_WRITES = re.compile(
    r"\b(?:INSERT INTO|UPDATE)\s+((?:feature|ops|provider_sync)\.[a-z0-9_]+)"
)
_TABLE = re.compile(
    r"^CREATE TABLE ((?:feature|ops|provider_sync)\.[a-z0-9_]+) \((.*?)^\);",
    re.MULTILINE | re.DOTALL,
)
_TABLE_CHECK = re.compile(r"CONSTRAINT (ck_[a-z0-9_]+) CHECK")


def _schema_text() -> str:
    return _SCHEMA.read_text(encoding="utf-8")


def _routine_bodies(schema: str) -> dict[str, str]:
    """이름 → 본문. 같은 이름의 overload는 이어 붙인다(둘 다 도달 가능하므로)."""

    bodies: dict[str, str] = {}
    heads = list(_ROUTINE_HEAD.finditer(schema))
    for index, head in enumerate(heads):
        end = heads[index + 1].start() if index + 1 < len(heads) else len(schema)
        bodies[head.group(1)] = bodies.get(head.group(1), "") + schema[head.start() : end]
    return bodies


def _reachable_constraints(schema: str) -> tuple[set[str], set[str], set[str]]:
    bodies = _routine_bodies(schema)
    checks_by_table = {
        match.group(1): set(_TABLE_CHECK.findall(match.group(2)))
        for match in _TABLE.finditer(schema)
    }

    visited: set[str] = set()
    raised: set[str] = set()
    written: set[str] = set()
    frontier = list(_ENTRY_ROUTINES)
    while frontier:
        name = frontier.pop()
        if name in visited or name not in bodies:
            continue
        visited.add(name)
        body = bodies[name]
        raised |= set(_RAISED_CONSTRAINT.findall(body))
        written |= set(_WRITES.findall(body))
        frontier.extend(_CALLS.findall(body))

    table_checks: set[str] = set()
    for relation in written:
        table_checks |= checks_by_table.get(relation, set())
    return visited, raised, table_checks


@pytest.fixture(scope="module")
def closure() -> tuple[set[str], set[str], set[str]]:
    return _reachable_constraints(_schema_text())


def test_the_derivation_actually_reaches_the_state_procedures(
    closure: tuple[set[str], set[str], set[str]],
) -> None:
    """폐포 계산이 비면 아래 분할 검사가 통째로 공허해진다.

    정규식이 스키마 덤프 형식 변화로 아무것도 못 잡으면 `set() <= anything`이 참이라
    모든 단언이 초록이 된다 — 이 저장소가 반복해 겪은 공허한 게이트다.
    """

    visited, raised, table_checks = closure
    assert set(_ENTRY_ROUTINES) <= visited
    # 진입점 둘은 다른 프로시저를 부른다. 폐포가 둘뿐이면 호출 추적이 죽은 것이다.
    assert len(visited) > len(_ENTRY_ROUTINES)
    assert len(raised) >= 5, sorted(raised)
    assert "ck_features_state_tuple" in table_checks, sorted(table_checks)


def test_every_reachable_constraint_is_classified(
    closure: tuple[set[str], set[str], set[str]],
) -> None:
    """분류를 **잊는 것**이 기본값이면 안 된다.

    셋 중 어디에도 없으면 raw re-raise → catch-all 500이다. 그 결과가 "이건 버그다"라는
    판단이었는지 그냥 잊은 것인지 코드가 말하지 못한다. 새 CHECK가 생기면 저자가 셋 중
    하나를 고르게 강제한다.
    """

    _visited, raised, table_checks = closure
    classified = (
        _ADMIN_STATE_CONFLICT_CONSTRAINTS
        | _ADMIN_STATE_VALIDATION_CONSTRAINTS
        | _ADMIN_STATE_UNEXPECTED_CONSTRAINTS
    )
    unclassified = sorted((raised | table_checks) - classified)
    assert not unclassified, (
        "admin state 경로에서 도달 가능한데 분류되지 않은 제약이 있다 — 지금 이대로면"
        f" catch-all 500이 된다: {unclassified}"
    )


def test_the_three_sets_do_not_overlap() -> None:
    """한 이름이 두 집합에 있으면 어느 HTTP 의미인지 코드가 말하지 못한다."""

    sets = {
        "conflict": _ADMIN_STATE_CONFLICT_CONSTRAINTS,
        "validation": _ADMIN_STATE_VALIDATION_CONSTRAINTS,
        "unexpected": _ADMIN_STATE_UNEXPECTED_CONSTRAINTS,
    }
    names = sorted(sets)
    for index, left_name in enumerate(names):
        for right_name in names[index + 1 :]:
            shared = sets[left_name] & sets[right_name]
            assert not shared, f"{left_name}/{right_name} 중복: {sorted(shared)}"


def test_no_classified_name_is_absent_from_the_schema(
    closure: tuple[set[str], set[str], set[str]],
) -> None:
    """반대 방향 — 존재하지 않는 제약을 분류해 두면 "구분되고 있다"는 오해가 남는다.

    이름이 오타이거나 migration에서 사라졌는데 집합에 남아 있으면, 그 이름에 기대는
    응답 계약이 영원히 발화하지 않는다.
    """

    schema = _schema_text()
    all_names = set(_RAISED_CONSTRAINT.findall(schema)) | {
        name for match in _TABLE.finditer(schema) for name in _TABLE_CHECK.findall(match.group(2))
    }
    classified = (
        _ADMIN_STATE_CONFLICT_CONSTRAINTS
        | _ADMIN_STATE_VALIDATION_CONSTRAINTS
        | _ADMIN_STATE_UNEXPECTED_CONSTRAINTS
    )
    missing = sorted(classified - all_names)
    assert not missing, f"분류돼 있으나 schema에 없는 제약: {missing}"
