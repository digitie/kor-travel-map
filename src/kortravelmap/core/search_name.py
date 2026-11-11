"""``kortravelmap.core.search_name`` — 이름 끝 라틴 괄호에서 검색용 이름 변형을 뗀다.

원천이 한글 이름 뒤에 영문 이름을 괄호로 붙여 둔 경우가 있다 — MOIS 숙박
``JW 메리어트 호텔 서울 (JW Marriott Hotel Seoul)``(#1466은 이 괄호를 이름에 남긴다). 그 Feature는
한글 이름만("JW 메리어트 호텔 서울")으로도, 영문 이름만("JW Marriott Hotel Seoul")으로도 **이름이
같은** Feature로 찾혀야 한다. 지금 검색은 이름 전체만 "이름 일치"로 보므로 두 검색어 모두 "품음"에
그쳐, 이름이 조금 더 긴 다른 숙박에 밀릴 수 있었다.

변형은 저장하지 않는다 — 검색 순위 SQL이 :data:`LATIN_BRACKET_NAME_PATTERN`으로 이름에서 바로
뗀다(``infra/feature_repo.py``). 그래서 적재·마이그레이션·backfill이 없고, 이름이 바뀌면 변형도
같이 바뀌며, 행이 늘지 않는다(별칭 폭증·중복 없음). ``feature_search_aliases``(436)는 큐레이션한
통칭 → 이름 사전이고 ``feature_aliases``는 legacy 식별자 별칭이라 둘 다 이 용도가 아니다.

안전 조건(전부 패턴 안에 있다 — Python ``re``와 PostgreSQL ARE 양쪽에서 같은 뜻인 부분집합):

- 괄호는 이름 **맨 끝** 하나(``(…)`` 또는 전각 ``（…）``)이고 그 안은 라틴 글자를 하나 이상 품고
  한글·괄호가 없다 — ``(경주)``·``(강남점)``·``(現)`` 같은 한글 메모 괄호는 건드리지 않는다.
- 괄호 앞(한글 이름)은 한글을 하나 이상 품는다 — ``Cafe (Seoul)``처럼 라틴뿐인 이름은 변형이 없다.

ADR-002(core 순수 함수) — DB·provider 의존 없음.
"""

from __future__ import annotations

import re
from typing import Final

__all__ = ["LATIN_BRACKET_NAME_PATTERN", "latin_bracket_name_parts"]

LATIN_BRACKET_NAME_PATTERN: Final[str] = (
    r"^(.*[가-힣].*[^\s(（])\s*[(（]([^()（）가-힣]*[A-Za-z][^()（）가-힣]*)[)）]$"
)
"""(한글 이름, 괄호 안 라틴 이름) 두 group. 검색 SQL이 ``regexp_match``에 그대로 넣는다."""

# DOTALL: PostgreSQL ARE의 ``.``는 줄바꿈도 맞춘다 — 두 쪽이 같은 뜻이어야 한다.
_PATTERN: Final[re.Pattern[str]] = re.compile(LATIN_BRACKET_NAME_PATTERN, re.DOTALL)


def latin_bracket_name_parts(name: str) -> tuple[str, str] | None:
    """``"JW 메리어트 호텔 서울 (JW Marriott Hotel Seoul)"`` → (한글 이름, 라틴 이름).

    조건이 맞지 않으면 ``None``. 양 끝 공백은 걷고 본다(SQL은 ``btrim``).

    >>> latin_bracket_name_parts("JW 메리어트 호텔 서울 (JW Marriott Hotel Seoul)")
    ('JW 메리어트 호텔 서울', 'JW Marriott Hotel Seoul')
    >>> latin_bracket_name_parts("라한호텔(경주)") is None
    True
    """
    match = _PATTERN.match(name.strip())
    if match is None:
        return None
    return match.group(1), match.group(2).strip()
