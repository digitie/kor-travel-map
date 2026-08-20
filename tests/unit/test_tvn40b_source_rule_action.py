"""T-VN-40B — source rule action 허용값이 한 곳에서만 정해지는지 본다.

이 task가 존재한 이유가 정확히 drift다. write 경로는 이미 `candidate|ignore`만 받는데
(`curated_repo._TYPED_RULE_ACTIONS`) DB CHECK는 `curated`를 계속 허용했고, prod에는 그 값이
35행 남아 있었다(2026-08-20 실측). 값이 다시 들어올 문은 닫혀 있는데 이미 들어온 값은
그대로였던 것이다.

그래서 두 정의가 어긋나면 red가 되게 한다. 한쪽만 고치는 다음 변경은 여기서 멈춘다.
"""

from __future__ import annotations

import re
from typing import Final

from kortravelmap.infra.curated_repo import _TYPED_RULE_ACTIONS
from kortravelmap.infra.models import CuratedSourceRuleRow

_ACTION_CONSTRAINT: Final[str] = "ck_curated_source_rules_action"
_RETIRED_ACTION: Final[str] = "curated"


def _action_check_sqltext() -> str:
    for constraint in CuratedSourceRuleRow.__table__.constraints:
        name = getattr(constraint, "name", None)
        if name is not None and _ACTION_CONSTRAINT in str(name):
            return str(constraint.sqltext)
    raise AssertionError(f"{_ACTION_CONSTRAINT} CHECK를 찾지 못했습니다")


def _action_values_from_check() -> frozenset[str]:
    return frozenset(re.findall(r"'([a-z_]+)'", _action_check_sqltext()))


def test_check_constraint_and_write_path_allow_exactly_the_same_actions() -> None:
    assert _action_values_from_check() == _TYPED_RULE_ACTIONS


def test_retired_curated_action_is_not_writable_anywhere() -> None:
    """`curated`는 ADR-092가 candidate 생성으로 재해석해 `candidate`와 같은 뜻이 됐다.

    같은 뜻의 값이 둘이면 읽는 사람마다 다르게 해석하므로 한쪽을 없앤다.
    """

    assert _RETIRED_ACTION not in _TYPED_RULE_ACTIONS
    assert _RETIRED_ACTION not in _action_values_from_check()


def test_action_set_is_exactly_candidate_and_ignore() -> None:
    """집합 자체를 못박는다.

    위 두 단언은 "두 정의가 같다"만 보므로 양쪽을 같이 바꾸면 통과한다. 무엇이어야
    하는지는 여기가 말한다 — 값이 늘거나 줄면 이 테스트가 먼저 묻는다.
    """

    assert frozenset({"candidate", "ignore"}) == _TYPED_RULE_ACTIONS
