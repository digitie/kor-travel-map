"""DB 루틴 본문이 feature 식별자를 **한 축으로만** 비교하는지 검사한다.

## 왜 이 파일이 있는가

T-VN-39의 범위 누락은 다섯 번 나왔고, 다섯 번 다 **다른 프록시**를 봤기 때문이다.

| 회차 | 무엇을 봤나 | 놓친 것 |
|---|---|---|
| 1 | 본문에 `feature_uuid`가 나오는 루틴 | 시그니처만 text인 12개 |
| 2 | `db.py`/`runtime_privileges.py`의 선언 리터럴 | 둘 다 아닌 2개 |
| 3 | 표 별칭으로 한정된 `*.feature_uuid` 읽기 | `COALESCE`·`UNION`·`ILIKE` 부류 |
| 4 | `feature_id text` **인자 이름** | `p_master`/`p_loser`처럼 이름에 단서가 없는 것 |
| 5 | (인자가 아예 없다) | `claim_curation_import_plan_command` |

다섯 번째가 이 파일의 이유다. 그 프로시저는 feature 식별자를 **인자로 받지 않는다.**
시그니처에도 인자 이름에도 단서가 없고, 본문 한 줄이 `feature.features.feature_id`를
호출자가 준 text 키와 비교했다:

    AND core.feature_id = expected.resource_key

재키 뒤 42883이고, curation import plan claim 경로 전량이 거기서 선다.

**이름도 시그니처도 아닌 본문이 오라클이다.**

## 무엇을 보는가

`alembic/head-schema.sql`에서 `<무엇>.feature_id`(또는 `parent_feature_id` 등)를
**다른 이름의 식**과 `=`/`<>`/`IN (...)`으로 비교하는 자리를 센다. 상대가 또 다른
feature 식별자거나 plpgsql 변수(`v_`/`p_`/`o_`)면 축이 같으므로 넘어간다.

남는 것은 **판단이 필요한 자리**이고, 판단은 이 파일이 목록으로 들고 있다. 목록에
이름이 느는 것 자체가 리뷰 신호다 — 그것이 이 검사의 목적이다. 결론을 강요하지
않고 판단을 강요한다.

## 한계

plpgsql 본문의 타입은 정적으로 완전히 알 수 없다. 이 검사는 "비교 상대가 feature
식별자로 읽히지 않는다"까지만 말하고, 그것이 옳은지는 사람이 판정해 여기 적는다.
제품 SQL의 진짜 타입 검사는
`tests/integration/test_product_sql_parses_against_head.py`가 실제 Parse로 한다 —
그 오라클이 닿지 않는 곳이 **루틴 본문**이다(PostgreSQL은 plpgsql 본문을 생성
시점에 검사하지 않으므로, 이 부류는 마이그레이션이 초록인 채로 통과하고 첫 호출에서만
드러난다).
"""

from __future__ import annotations

import pathlib
import re
from typing import Final

_ROOT = pathlib.Path(__file__).resolve().parents[2]
_HEAD_SCHEMA = _ROOT / "alembic" / "head-schema.sql"

#: `<alias>.feature_id = <expr>` / `<> <expr>` / `IN (<expr>)`.
#:
#: `IN`은 **여는 괄호가 따라올 때만** 비교다. 그렇게 좁히지 않으면 plpgsql의
#: `SELECT ... INTO v_x`가 전부 걸린다.
_COMPARISON = re.compile(
    r"(?:([A-Za-z_]\w*)\.)?((?:[a-z_]+_)?feature_id)\s*"
    r"(?:(?:=|<>)|\bIN\b(?=\s*\())\s*"
    r"(\([^)]{0,120}\)|[^\s;()]+)"
)

#: 상대가 feature 식별자 축으로 읽히는 형태. 여기 걸리면 같은 축이다.
_SAME_AXIS = re.compile(
    r"feature_id|feature_uuid|\bANY\b|\bNULL\b|\bv_\w|\bp_\w|\bo_\w"
    r"|\bEXCLUDED\b|%L|%s|\bCAST\b|::uuid",
    re.IGNORECASE,
)

#: 재키 뒤에도 **text**로 남은 식별자 열. 이름에 `feature_id`가 들어 있어서
#: `_SAME_AXIS`의 `feature_id` 갈래가 이것들을 같은 축으로 읽었다 — 그 오인이
#: 정확히 이 검사가 막으려던 부류다. `feature.features.feature_id`(uuid)와
#: `manual_feature_purge_records.legacy_feature_id`(text)를 맞대면 42883이고,
#: 사면 때문에 검사는 초록이었다. 적대 리뷰가 집었다.
#:
#: ADR-098 뒤 legacy `f_*`가 살아 있는 자리는 셋뿐이다 —
#: `feature_aliases.alias`, `manual_feature_purge_records.legacy_feature_id`,
#: `ops.tvn36_legacy_freeze_preflight_manifest.legacy_feature_id`. 여기에
#: 큐레이션 import plan의 `resource_key`(주소를 담는 text)를 더한다.
_TEXT_AXIS = re.compile(
    r"legacy_feature_id|\bresource_key\b|\balias\b", re.IGNORECASE
)

#: 상대가 **uuid 축임을 적극적으로** 말하는 형태. `legacy_feature_id`가 여기
#: 걸리지 않도록 `feature_id` 앞에 단어 문자가 오면 제외한다 — 그 한 글자가
#: 두 축을 가른다.
_UUID_AXIS = re.compile(
    r"(?<![A-Za-z0-9_])feature_id\b|feature_uuid|::uuid|\bAS\s+uuid\b",
    re.IGNORECASE,
)

#: plpgsql의 `... INTO <변수>`는 비교가 아니라 대입이다.
_ASSIGNMENT_INTO = re.compile(r"\bINTO\b", re.IGNORECASE)

#: `= CASE ... END`은 여러 줄이라 한 줄 정규식이 안을 못 본다. 블록 안에 uuid
#: 캐스트가 있으면 같은 축으로 본다 — 없으면 판단 대상으로 남긴다.
_CASE_WINDOW: Final[int] = 12

#: 판단이 끝난 자리. **이유를 함께 적는다.**
_JUDGED: Final[dict[str, str]] = {
    # 진단 payload의 설명 문자열. 비교가 아니다.
    "'reason', 'explicit feature_id=null',": "진단 문자열 — 비교가 아니다",
}


def test_routine_bodies_never_compare_a_feature_id_across_axes() -> None:
    lines = _HEAD_SCHEMA.read_text(encoding="utf-8").splitlines()
    unjudged: list[str] = []
    comparisons = 0

    for index, line in enumerate(lines):
        stripped = line.strip()
        if _ASSIGNMENT_INTO.search(stripped):
            continue
        for match in _COMPARISON.finditer(stripped):
            comparisons += 1
            column, other = match.group(2), match.group(3)
            # 축을 **양쪽 다** 본다. 한쪽만 보면 `feature_id`가 들어간 이름이
            # 전부 한 축으로 뭉개진다. 다만 "text가 아님"은 uuid라는 뜻이 아니다 —
            # plpgsql 변수는 덤프에서 타입을 읽을 수 없으므로, 한쪽이 text 축이고
            # **다른 쪽이 uuid 축이라고 적극적으로 말할 때만** 어긋난 것으로 본다.
            text_axis = (bool(_TEXT_AXIS.search(column)), bool(_TEXT_AXIS.search(other)))
            uuid_axis = (bool(_UUID_AXIS.search(column)), bool(_UUID_AXIS.search(other)))
            if (text_axis[0] and uuid_axis[1]) or (uuid_axis[0] and text_axis[1]):
                unjudged.append(f"head-schema.sql:{index + 1}: {stripped[:120]}")
                continue
            if _SAME_AXIS.search(other):
                continue
            if other.upper().startswith("CASE"):
                window = " ".join(lines[index : index + _CASE_WINDOW])
                if "::uuid" in window or "as uuid" in window.lower():
                    continue
            if any(key in stripped for key in _JUDGED):
                continue
            unjudged.append(f"head-schema.sql:{index + 1}: {stripped[:120]}")

    # **하한은 "판단 대상"이 아니라 "비교 자체"에 건다.** 판단 대상이 0이 되는 것은
    # 정상(전부 같은 축)이지만, 비교가 0이면 정규식이 덤프의 형태를 놓친 것이다 —
    # 그 둘을 한 숫자로 재면 초록이 무엇을 뜻하는지 알 수 없다.
    assert comparisons >= 50, (
        f"feature 식별자 비교를 {comparisons}개만 봤다 — head 오라클의 형태가 바뀌어 "
        "이 검사가 대상을 잃었을 수 있다. `_COMPARISON` 패턴을 현행 덤프에 맞춰라."
    )
    assert not unjudged, (
        "루틴 본문이 feature 식별자를 다른 축과 비교한다:\n  "
        + "\n  ".join(dict.fromkeys(unjudged))
        + "\n\n재키 뒤 `feature_id`는 uuid다. 상대가 text면 42883 "
        "`operator does not exist: uuid = text`이고, 그 경로 **전량**이 선다.\n\n"
        "옳은 자리라면 이 파일의 `_JUDGED`에 줄과 이유를 적어라 — 목록이 느는 것 "
        "자체가 리뷰 신호다."
    )
