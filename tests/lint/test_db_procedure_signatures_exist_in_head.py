"""`db.py`·`runtime_privileges.py`가 든 루틴 시그니처가 head에 실재하는지 검사한다.

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

## 무엇을 재는가

`alembic/head-schema.sql`(head 오라클)에서 루틴의 인자 타입 목록을 뽑아,
`db.py`·`runtime_privileges.py`의 리터럴과 **정확히** 대조한다. 이름만 맞고 타입이
다르면 그것이 정확히 우리가 막으려는 상태다.

## 한계 (정직하게)

오라클은 커밋된 아티팩트라 head보다 낡을 수 있다. 그 낡음은
`tests/integration/test_alembic_metadata_consistency.py::test_head_schema_artifact_matches_head`가
막는다 — 두 게이트가 짝이다.
"""

from __future__ import annotations

import pathlib
import re

_ROOT = pathlib.Path(__file__).resolve().parents[2]
_ORACLE = _ROOT / "alembic" / "head-schema.sql"

#: 시그니처 리터럴을 든 모듈. 새 모듈이 같은 규약을 쓰면 여기 더한다.
_SOURCES = (
    _ROOT / "src" / "kortravelmap" / "infra" / "db.py",
    _ROOT / "src" / "kortravelmap" / "infra" / "runtime_privileges.py",
)

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


def _oracle_signatures() -> dict[str, set[str]]:
    """`{루틴 이름: {IN 인자 타입을 콤마로 이은 문자열, ...}}`.

    오버로드가 있을 수 있으므로 집합으로 둔다.
    """

    text = _ORACLE.read_text(encoding="utf-8")
    found: dict[str, set[str]] = {}
    for match in _ROUTINE.finditer(text):
        name, args = match.group(1), " ".join(match.group(2).split())
        types: list[str] = []
        for piece in _split_args(args):
            if re.match(r"^\s*(?:OUT|INOUT)\b", piece):
                # `db.py`의 리터럴은 `::regprocedure` 표기라 IN 인자만 담는다.
                if piece.lstrip().upper().startswith("OUT"):
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


_ORACLE_SIGS = _oracle_signatures()
_LITERALS = _literals()


def test_the_oracle_and_sources_are_live() -> None:
    """유도원이 죽으면 이 검사는 조용히 0건이 된다."""

    assert _ORACLE.is_file(), f"head 오라클이 없다: {_ORACLE}"
    assert len(_ORACLE_SIGS) >= 100, (
        f"오라클에서 루틴을 {len(_ORACLE_SIGS)}개만 읽었다 — 파서가 눈을 감았다"
    )
    missing = [str(p.relative_to(_ROOT)) for p in _SOURCES if not p.is_file()]
    assert not missing, f"시그니처 리터럴 원본이 사라졌다: {missing}"
    assert len(_LITERALS) >= 20, (
        f"리터럴을 {len(_LITERALS)}개만 찾았다 — 탐지기가 형태를 못 본다"
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
