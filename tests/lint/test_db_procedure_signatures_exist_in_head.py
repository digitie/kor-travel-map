"""루틴 시그니처 선언이 실재하는 스키마 상태에 묶여 있는지 검사한다.

## 왜

`src/kortravelmap/infra/db.py`는 startup preflight에서 "이 루틴들이 SECURITY DEFINER로
있어야 하고 그 밖의 것은 없어야 한다"를 **missing·unexpected 양방향**으로 대조한다.
그 목록이 **인자 타입까지 박힌 문자열 리터럴**이라, 시그니처가 바뀌면 목록이 조용히
낡는다. 낡은 목록의 증상은 배포 시점의 기동 실패이고, 그 진단은 "unexpected SECURITY
DEFINER function"이라 **어느 시그니처가 어긋났는지 말하지 않는다.**

`db.py:113-118`이 같은 사고를 이미 기록해 뒀다 — "이 등록이 없으면 함수가 배포되는
순간 모든 Dagster 프로세스가 기동 preflight에서 죽는다".

## 이 검사가 실제로 잡은 것

2026-09-09, T-VN-39 재키 준비 중 이 대조를 손으로 한 번 돌렸더니 **재작성 세트에서
누락된 루틴 12개**가 나왔다(`author_feature_field_overrides` 497줄,
`transition_feature_state` 등). 본문에 `feature_uuid`가 0건이라 "본문 참조" 눈금에
안 걸렸고, text `feature_id` **인자**만 든 루틴들이었다. 유도로 대조하지 않았으면
재키 후 첫 호출에서 42883으로 드러났을 것이다.

## 두 개의 선언, 두 개의 규율

`db.py`는 **head 전용**이다. API/Dagster가 head에 붙어 도는 preflight이므로 head
시그니처 리터럴이 옳고, 이 파일은 그것을 head 오라클과 정확히 대조한다.

`runtime_privileges.py`는 다르다. 같은 ACL 인벤토리가 **두 시점**에서 돈다 —
`0236 → 300` handoff는 baseline root(`300`)로 stamp한 직후, finalize·API entrypoint는
head에서. T-VN-39 재키가 두 시점의 시그니처를 갈라놓았으므로(42개 이름 중 11개) 그
파일은 시그니처 리터럴을 **버리고** 이름만 들고 있다. 인자 목록은 적용 시점에
`pg_proc`에서 읽는다.

그래서 이 파일의 검사도 둘로 갈린다. `db.py`는 **타입까지** 대조하고,
`runtime_privileges.py`는 **이름을 두 오라클에 묶는다** — head에는 42개가 다 있어야
하고, `300`에는 `_OPTIONAL_ROUTINES`로 선언된 것만 없어야 한다. 런타임의 "없으면
건너뛴다"가 정당한 판정인지를 여기서 정적으로 증인한다(배포가 아니라 머지를 막는
쪽이 더 이르다).

## 탐지기가 눈을 감는 형태

가장 그럴듯한 실패는 "아무것도 안 잡는데 초록"이다. 실제로 종전 판이 그랬다: 줄 단위
정규식이라 여러 줄로 쪼개진 문자열 리터럴을 못 봐서 `runtime_privileges.py`의 42개
이름 중 **19개만** 잡았고, `transition_feature_state`는 `db.py`를 통해서만 잡혔다.
그래서 이 파일은 대상 개수와 정규식 자체를 명시적으로 재고, 인벤토리 이름은 소스
정규식이 아니라 모듈이 스스로 유도한 `_DECLARED_ROUTINES`에서 가져온다 — 프록시는
언제나 진짜 집합보다 작다.

## 한계 (정직하게)

오라클은 커밋된 아티팩트라 head보다 낡을 수 있다. 그 낡음은
`tests/integration/test_alembic_metadata_consistency.py::test_head_schema_artifact_matches_head`가
막는다 — 두 게이트가 짝이다.
"""

from __future__ import annotations

import pathlib
import re

from kortravelmap.infra.runtime_privileges import (
    _DECLARED_ROUTINES,
    _OPTIONAL_ROUTINES,
    _ROUTINE_REFERENCE,
)

_ROOT = pathlib.Path(__file__).resolve().parents[2]
_ORACLE = _ROOT / "alembic" / "head-schema.sql"
#: baseline root(`300`) 오라클. `runtime_privileges.py`가 stamp 직후 마주하는 상태다.
_BASELINE_ORACLE = _ROOT / "alembic" / "baseline" / "schema.sql"

_RUNTIME_PRIVILEGES = _ROOT / "src" / "kortravelmap" / "infra" / "runtime_privileges.py"

#: 시그니처 리터럴을 든 모듈. **head 전용 선언만** 여기 온다 — 두 시점에서 도는
#: 선언은 리터럴을 들 수 없다(모듈 docstring 참조).
_SOURCES = (_ROOT / "src" / "kortravelmap" / "infra" / "db.py",)

#: `feature.foo(text,bigint)` 형태. 스키마는 셋뿐이다.
_LITERAL = re.compile(r"\b((?:feature|ops|provider_sync)\.[a-z_0-9]+)\(([a-z_0-9 ,\[\]]*)\)")

_ROUTINE = re.compile(
    r"CREATE (?:OR REPLACE )?(?:FUNCTION|PROCEDURE) "
    r"((?:feature|ops|provider_sync)\.[a-z_0-9]+)\((.*?)\)\s*(?:RETURNS|\n\s*LANGUAGE)",
    re.S,
)

_ARG_TYPE = re.compile(
    r"(?:^|,)\s*(?:IN|OUT|INOUT|VARIADIC)?\s*[a-z_][a-z_0-9]*\s+"
    r"([a-z_ ]+(?:\[\])?)(?:\s+DEFAULT[^,]*)?(?=,|$)"
)


def _oracle_signatures(oracle: pathlib.Path) -> dict[str, set[str]]:
    """`{루틴 이름: {IN 인자 타입을 콤마로 이은 문자열, ...}}`.

    오버로드가 있을 수 있으므로 집합으로 둔다.
    """

    text = oracle.read_text(encoding="utf-8")
    found: dict[str, set[str]] = {}
    for match in _ROUTINE.finditer(text):
        name, args = match.group(1), " ".join(match.group(2).split())
        types: list[str] = []
        for piece in _split_args(args):
            # `db.py`의 리터럴은 `::regprocedure` 표기라 **IN 인자만** 담는다.
            if piece.lstrip().upper().startswith("OUT "):
                continue
            type_match = re.search(
                r"\b(?:IN|INOUT|VARIADIC)?\s*[a-z_][a-z_0-9]*\s+"
                r"([a-z][a-z ]*(?:\[\])?)\s*(?:DEFAULT.*)?$",
                piece.strip(),
            )
            if type_match:
                types.append(" ".join(type_match.group(1).split()))
        found.setdefault(name, set()).add(",".join(types))
    return found


def _split_args(args: str) -> list[str]:
    """괄호 깊이를 세며 콤마로 나눈다 — `numeric(10,2)` 같은 것 때문."""

    out: list[str] = []
    depth = 0
    current: list[str] = []
    for char in args:
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        if char == "," and depth == 0:
            out.append("".join(current))
            current = []
            continue
        current.append(char)
    if current:
        out.append("".join(current))
    return out


def _literals() -> dict[str, list[tuple[str, str, int]]]:
    """`{루틴 이름: [(타입 문자열, 파일, 줄), ...]}`."""

    found: dict[str, list[tuple[str, str, int]]] = {}
    for path in _SOURCES:
        if not path.is_file():
            continue
        rel = str(path.relative_to(_ROOT)).replace("\\", "/")
        for number, line in enumerate(path.read_text(encoding="utf-8").split("\n"), start=1):
            for match in _LITERAL.finditer(line):
                types = ",".join(p.strip() for p in match.group(2).split(",") if p.strip())
                found.setdefault(match.group(1), []).append((types, rel, number))
    return found


_ORACLE_SIGS = _oracle_signatures(_ORACLE)
_BASELINE_SIGS = _oracle_signatures(_BASELINE_ORACLE)
_LITERALS = _literals()


def test_the_oracle_and_sources_are_live() -> None:
    """유도원이 죽으면 이 검사는 조용히 0건이 된다."""

    assert _ORACLE.is_file(), f"head 오라클이 없다: {_ORACLE}"
    assert _BASELINE_ORACLE.is_file(), f"baseline root 오라클이 없다: {_BASELINE_ORACLE}"
    assert len(_ORACLE_SIGS) >= 100, (
        f"head 오라클에서 루틴을 {len(_ORACLE_SIGS)}개만 읽었다 — 파서가 눈을 감았다"
    )
    assert len(_BASELINE_SIGS) >= 100, (
        f"baseline 오라클에서 루틴을 {len(_BASELINE_SIGS)}개만 읽었다 — 파서가 눈을 감았다"
    )
    missing = [str(p.relative_to(_ROOT)) for p in _SOURCES if not p.is_file()]
    assert not missing, f"시그니처 리터럴 원본이 사라졌다: {missing}"
    assert len(_LITERALS) >= 20, (
        f"리터럴을 {len(_LITERALS)}개만 찾았다 — 탐지기가 형태를 못 본다"
    )
    assert _RUNTIME_PRIVILEGES.is_file(), f"ACL 인벤토리가 사라졌다: {_RUNTIME_PRIVILEGES}"
    assert len(_DECLARED_ROUTINES) >= 40, (
        f"ACL 인벤토리가 루틴을 {len(_DECLARED_ROUTINES)}개만 지목한다 — 문장이 사라졌거나 "
        "`_ROUTINE_REFERENCE`가 형태를 못 본다"
    )


def test_every_declared_signature_exists_in_head() -> None:
    """이름은 있는데 **타입이 다른** 것을 잡는다 — 그것이 조용히 낡는 형태다."""

    mismatches: list[str] = []
    unknown: list[str] = []
    for name, uses in sorted(_LITERALS.items()):
        if name not in _ORACLE_SIGS:
            unknown.append(f"{name} (오라클에 없다) ← {uses[0][1]}:{uses[0][2]}")
            continue
        for types, rel, number in uses:
            if types not in _ORACLE_SIGS[name]:
                mismatches.append(
                    f"{rel}:{number} {name}({types})\n"
                    f"      오라클: {sorted(_ORACLE_SIGS[name])}"
                )
    assert unknown == [], (
        "이 루틴이 head 오라클에 없다 — 리터럴이 죽은 시그니처를 가리킨다. "
        "startup preflight는 이것을 'missing'으로 보고 기동을 막는다.\n"
        + "\n".join(unknown)
    )
    assert mismatches == [], (
        "리터럴의 인자 타입이 head와 다르다. `db.py`의 preflight는 이것을 "
        "'unexpected SECURITY DEFINER function'으로 보고하고 **어느 시그니처가 "
        "어긋났는지 말하지 않는다.**\n" + "\n".join(mismatches)
    )


def test_the_detector_sees_a_planted_type_drift() -> None:
    """AST가 아니라 정규식이라, 아무것도 안 잡는데 초록인 실패가 가장 그럴듯하다."""

    planted = 'ROUTINE = "feature.transition_feature_state(uuid,text,text,text,bigint,jsonb)"'
    hits = list(_LITERAL.finditer(planted))
    assert len(hits) == 1, hits
    assert hits[0].group(1) == "feature.transition_feature_state"
    assert hits[0].group(2) == "uuid,text,text,text,bigint,jsonb"


def test_the_inventory_detector_sees_a_planted_routine_reference() -> None:
    """인벤토리 쪽 탐지기도 같은 방식으로 눈을 감을 수 있다."""

    planted = '"REVOKE ALL ON PROCEDURE feature.transition_feature_state(...) FROM PUBLIC"'
    assert _ROUTINE_REFERENCE.findall(planted) == [("feature", "transition_feature_state")]
    # 인자를 다시 박으면 참조로 읽히지 않는다 — 아래 회귀 fence가 그것을 잡는다.
    assert _ROUTINE_REFERENCE.findall(planted.replace("...", "uuid, text")) == []


def test_the_acl_inventory_carries_no_signature_literal() -> None:
    """인벤토리가 시그니처를 다시 박으면 두 시점 중 하나에서 42883으로 죽는다.

    줄바꿈으로 쪼개진 리터럴을 놓치지 않도록 암묵적 문자열 연결을 먼저 잇는다 —
    종전 판이 42개 중 19개만 본 이유가 정확히 그것이었다. **같은 줄의** 연결
    (``"...(" "uuid, text)"``)도 같은 방식으로 숨을 수 있어 함께 잇는다. 심어서
    확인했다: 줄바꿈만 잇던 판은 그 형태를 통과시켰다. 탐지기가 안 보는 형태가
    곧 은신처다.
    """

    source = _RUNTIME_PRIVILEGES.read_text(encoding="utf-8")
    # 줄을 넘든 안 넘든, 두 문자열 리터럴 사이의 공백은 파이썬이 이어 붙인다.
    joined = re.sub(r'"\s*"', "", source)
    planted = sorted(
        {f"{name}({types})" for name, types in _LITERAL.findall(joined) if types.strip()}
    )
    assert planted == [], (
        "ACL 인벤토리에 시그니처 리터럴이 다시 들어왔다: "
        + ", ".join(planted)
        + ". 이 인벤토리는 `300`과 head 두 시점에서 돌고 그 둘의 시그니처가 다르다 — "
        "리터럴 한 벌은 반드시 한쪽에서 42883으로 죽는다. `feature.<이름>(...)`으로 "
        "적고 인자는 `pg_proc`에서 유도하게 두어라."
    )


def test_every_declared_routine_exists_in_head() -> None:
    """인벤토리 이름이 head에 실재해야 한다 — optional로 선언된 것까지 포함해서.

    런타임은 이름이 안 풀리면 `_OPTIONAL_ROUTINES`에 한해 문장을 건너뛴다. 그 건너뜀은
    `300`에서 정당하지만 head에서는 **지킬 대상이 사라진 것**이다. 종전의
    `to_regprocedure` DO block은 head에서도 무조건 조용했다 — 여기서 그 구멍을 닫는다.
    """

    absent = sorted(name for name in _DECLARED_ROUTINES if name not in _ORACLE_SIGS)
    assert absent == [], (
        "ACL 인벤토리가 head에 없는 루틴을 지목한다: "
        + ", ".join(absent)
        + ". 이름이 바뀌었다면 인벤토리를 고치고, 루틴이 은퇴했다면 문장을 지워라 — "
        "그대로 두면 head 배포에서 42883이 나거나(REQUIRED), 지켜야 할 ACL이 조용히 "
        "사라진다(OPTIONAL)."
    )


def test_optional_routines_are_exactly_the_ones_the_baseline_root_lacks() -> None:
    """"없어도 된다"는 판정이 실제 `300` 상태와 맞는지 본다.

    두 방향 다 위험하다. 목록이 넓으면 진짜로 없어진 루틴이 조용히 넘어가고, 좁으면
    `0236 → 300` handoff가 42883으로 죽으며 **ACL 재조정 트랜잭션 전체가 무효화된다**.
    """

    absent_at_baseline = sorted(
        name for name in _DECLARED_ROUTINES if name not in _BASELINE_SIGS
    )
    assert absent_at_baseline == sorted(_OPTIONAL_ROUTINES), (
        "`_OPTIONAL_ROUTINES`가 baseline root(`300`) 실물과 어긋난다.\n"
        f"  `300`에 없는 인벤토리 루틴: {absent_at_baseline}\n"
        f"  optional로 선언된 것:      {sorted(_OPTIONAL_ROUTINES)}\n"
        "없는데 선언이 없으면 handoff가 42883으로 죽고, 있는데 선언이 있으면 head에서 "
        "지켜야 할 ACL이 조용히 건너뛰어진다."
    )


def test_no_declared_routine_is_overloaded_in_either_state() -> None:
    """이름 해석이 두 시점 어디에서도 모호하지 않아야 한다.

    런타임은 오버로드를 만나면 부여하지 않고 실패한다(fail-closed). 그 실패는 배포를
    멈추므로, 여기서 먼저 잡는 편이 싸다.
    """

    overloaded: list[str] = []
    for label, signatures in (("head", _ORACLE_SIGS), ("300", _BASELINE_SIGS)):
        for name in sorted(_DECLARED_ROUTINES):
            found = signatures.get(name, set())
            if len(found) > 1:
                overloaded.append(f"{label}: {name} → {sorted(found)}")
    assert overloaded == [], (
        "인벤토리 루틴이 오버로드돼 있다 — 이름 해석이 어느 쪽에 ACL을 걸지 모호하다. "
        "런타임은 이 상태에서 EXECUTE를 주지 않고 실패한다.\n" + "\n".join(overloaded)
    )
