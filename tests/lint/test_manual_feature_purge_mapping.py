"""purge 프로시저가 raise하는 제약이 전부 도메인 오류로 분류돼 있는지 본다.

admin state 경로에서 같은 부류의 누락이 **두 번** catch-all 500을 냈다 — 2026-08-12의
`ck_features_state_tuple`, 그리고 2026-09-08에 찾은 넷. 그때마다 원인은 같았다:
**분류를 잊는 것이 기본값**이었다.

여기서는 그 기본값을 처음부터 막는다. 이름을 두 벌 적지 않고 **배포되는 프로시저
본문**에서 유도한다(AGENTS.md DO NOT 15) — 본문이 정본이고 매핑이 그것을 따라간다.

유도원은 head 오라클(`alembic/head-schema.sql`)이다. 종전에는 306 migration의 원문을
읽었는데, 스쿼시로 그 파일이 사라졌고 애초에 그것은 **중간 문자열**이었다 — DB에 실제로
들어간 본문과 같다는 보장이 없었다. 덤프는 DB가 돌려준 본문 그 자체다.
"""

from __future__ import annotations

import pathlib
import re
from typing import Final

from kortravelmap.infra.manual_feature_purge_repo import (
    _PURGE_ERROR_BY_CONSTRAINT,
    PURGE_OPERATION,
)

_HEAD_SCHEMA: Final[pathlib.Path] = (
    pathlib.Path(__file__).resolve().parents[2] / "alembic" / "head-schema.sql"
)

_RAISED = re.compile(r"CONSTRAINT = '([a-z0-9_]+)'")


def _routine_body(signature_prefix: str) -> str:
    """덤프에서 루틴 하나의 본문만 잘라낸다.

    pg_dump는 각 루틴을 `CREATE {FUNCTION,PROCEDURE} <서명> ... AS $x$ ... $x$;`로 내고
    그 뒤에 빈 줄 두 개와 다음 객체의 주석 머리가 온다. 그 경계까지를 본문으로 본다.
    """

    text_body = _HEAD_SCHEMA.read_text(encoding="utf-8")
    start = text_body.index(signature_prefix)
    end = text_body.index("\n\n\n", start)
    return text_body[start:end]


def _reachable_constraints() -> set[str]:
    """purge 경로가 실제로 raise하는 제약 이름.

    append-only 가드는 여기 들어오지 않는다 — 그것은 "누가 증거를 고치려 했다"이고
    purge 프로시저가 아니라 다른 트리거가 낸다. 프로시저 본문과 hard-purge fence,
    둘만 본다.
    """

    return set(
        _RAISED.findall(_routine_body("CREATE PROCEDURE feature.purge_manual_feature("))
    ) | set(
        _RAISED.findall(
            _routine_body("CREATE FUNCTION feature.reject_manual_feature_hard_purge(")
        )
    )


def test_the_purge_path_actually_raises_named_constraints() -> None:
    """유도가 비면 아래 분류 검사가 통째로 공허해진다.

    하한은 아래 분류 검사가 **읽는 바로 그 집합**에 건다. 다른 집합에 걸면 유도가
    비어도 하한은 초록일 수 있다.
    """

    raised = _reachable_constraints()
    assert len(raised) >= 4, sorted(raised)
    assert "ck_manual_feature_purge_unauthorised" in raised


def test_every_constraint_the_purge_path_raises_is_classified() -> None:
    """분류를 잊으면 raw로 새고, 호출자는 그것을 500으로 본다."""

    reachable = _reachable_constraints()
    assert reachable, "purge 경로에서 raise되는 제약을 하나도 찾지 못했다"
    unclassified = sorted(reachable - set(_PURGE_ERROR_BY_CONSTRAINT))
    assert not unclassified, (
        "purge 경로가 raise하는데 분류되지 않은 제약이 있다 — 호출자가 500으로 본다:"
        f" {unclassified}"
    )


def test_no_classified_name_is_absent_from_the_migration() -> None:
    """반대 방향 — 없는 제약을 분류해 두면 그 응답 계약은 영원히 발화하지 않는다."""

    raised = set(_RAISED.findall(_HEAD_SCHEMA.read_text(encoding="utf-8")))
    phantom = sorted(set(_PURGE_ERROR_BY_CONSTRAINT) - raised)
    assert not phantom, f"분류돼 있으나 migration에 없는 제약: {phantom}"


def test_the_operation_name_matches_the_procedure_contract() -> None:
    """operation 문자열이 갈리면 프로시저가 모든 호출을 거부한다 — 조용히, 항상."""

    assert f"'{PURGE_OPERATION}'" in _HEAD_SCHEMA.read_text(encoding="utf-8")
