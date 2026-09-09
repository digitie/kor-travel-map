"""feature 식별자를 인자로 받는 DB 루틴이 그것을 `uuid`로 받는지 검사한다.

## 왜

T-VN-39는 `feature_id`를 text에서 uuid로 옮긴다. 옮겨야 할 루틴의 목록을 세 번
다시 셌고, 세 번 다 놓친 것이 나왔다:

1. 1차 — `feature_uuid`를 본문에 쓰는 루틴 23개.
2. 2차 — 시그니처에 `feature_id text`가 있는데 본문에 `feature_uuid`가 없는 12개.
   `test_db_procedure_signatures_exist_in_head.py`가 찾았다.
3. 3차 — `db.py`에도 `runtime_privileges.py`에도 선언이 없고 본문에 `feature_uuid`도
   없는 2개(`apply_provider_feature_field_patch`, `create_curation_item_command`).
   호출부의 캐스트가 이미 uuid로 바뀐 채 프로시저만 text로 남아 있었다.

셋 다 같은 이유로 놓쳤다 — **목록을 프록시에서 유도했다.** 본문의 토큰, 파이썬
소스의 선언 리터럴. 프록시는 언제나 진짜 집합보다 작다.

진짜 집합은 head 오라클이 갖고 있다. 여기서는 그것을 직접 센다.

## 규칙

`alembic/head-schema.sql`의 루틴 중 이름이 feature 식별자로 읽히는 인자를 `text`로
받는 것은, T-VN-39 사이드카를 갖거나(즉 재키가 손대거나) 왜 text로 남는지를 파일
자신이 들고 있어야 한다.

legacy `f_*` 문자열을 다루는 루틴은 text가 **옳다** — `feature_uuid_from_legacy`가
그렇다. 그래서 이 검사는 "uuid여야 한다"가 아니라 "판단이 기록돼 있어야 한다"를
본다. 판단을 강요하지 결론을 강요하지 않는다.
"""

from __future__ import annotations

import pathlib
import re
from typing import Final

_ROOT = pathlib.Path(__file__).resolve().parents[2]
_VERSIONS = _ROOT / "alembic" / "versions"
_HEAD_SCHEMA = _ROOT / "alembic" / "head-schema.sql"

#: 재키를 담당하는 revision. 사이드카 접두가 이것이다.
_REKEY_REVISION: Final[str] = "309"

#: pg_dump가 한 줄로 뱉는 완전한 시그니처. 여러 줄 정의를 파싱하는 것보다 정확하다.
_DECLARATION = re.compile(
    r"^ALTER (?:FUNCTION|PROCEDURE) ([a-z_]+)\.([a-z_0-9]+)\((.*?)\) OWNER TO",
    re.MULTILINE | re.DOTALL,
)
#: 이름이 feature 식별자로 읽히는 인자. `..._feature_id`와 `feature_id` 둘 다.
_IDENTIFIER_ARG = re.compile(r"\b(?:[a-z_]*_)?feature_id\s+text\b")

#: legacy `f_*` 문자열을 다루는 것이 일이라 text가 옳은 루틴. 파일이 그 판단을 들고
#: 있어야 하며, 여기 이름을 적는 것 자체가 리뷰 대상이다.
_LEGACY_TEXT_BY_DESIGN: Final[frozenset[str]] = frozenset(
    {
        # legacy 문자열 → uuid 파생. 인자는 오늘의 feature_id가 아니라 `f_*`다.
        "feature.feature_uuid_from_legacy",
    }
)


def _sidecar_routines() -> set[str]:
    """재키 사이드카가 실제로 다루는 루틴 이름."""
    pattern = re.compile(
        r"(?:CREATE|DROP)\s+(?:OR REPLACE\s+)?(?:FUNCTION|PROCEDURE)\s+"
        r"([a-z_]+\.[a-z_0-9]+)\s*\(",
        re.IGNORECASE,
    )
    routines: set[str] = set()
    for path in _VERSIONS.glob(f"_{_REKEY_REVISION}_*.sql"):
        routines.update(pattern.findall(path.read_text(encoding="utf-8")))
    return routines


def test_every_text_feature_identifier_argument_is_accounted_for() -> None:
    handled = _sidecar_routines()
    unaccounted: list[str] = []

    for match in _DECLARATION.finditer(_HEAD_SCHEMA.read_text(encoding="utf-8")):
        routine = f"{match.group(1)}.{match.group(2)}"
        arguments = " ".join(match.group(3).split())
        offenders = [
            argument.strip()
            for argument in arguments.split(",")
            if _IDENTIFIER_ARG.search(argument)
        ]
        if not offenders:
            continue
        if routine in handled or routine in _LEGACY_TEXT_BY_DESIGN:
            continue
        unaccounted.append(f"{routine}: {', '.join(offenders)}")

    assert not unaccounted, (
        "feature 식별자를 text로 받는데 재키가 손대지도, text로 두는 이유도 없다:\n  "
        + "\n  ".join(unaccounted)
        + f"\n\n`alembic/versions/_{_REKEY_REVISION}_<이름>.sql` 사이드카를 쓰고 배선하라. "
        "legacy `f_*` 문자열을 다루는 것이 일이라 text가 옳다면 이 파일의 "
        "`_LEGACY_TEXT_BY_DESIGN`에 이름과 이유를 적어라 — 목록에 이름이 느는 것 자체가 "
        "리뷰 신호다.\n\n이 부류를 세 번 놓쳤다. 매번 목록을 프록시(본문 토큰, 파이썬 "
        "선언 리터럴)에서 유도했기 때문이고, 프록시는 언제나 진짜 집합보다 작다."
    )
