"""protocol 진입을 부르는 SECURITY DEFINER 루틴의 소유자가 그 진입의 EXECUTE를 갖는지(433 WI-3).

## 왜

418은 ``GRANT EXECUTE ON FUNCTION ops.lock_scoped_feature_write_protocol(boolean)``을 함수
소유자가 아닌 schema owner로 냈다. grant option이 없어 PostgreSQL은 경고만 내고 아무것도
주지 않았다. 그런데 승인·수동 생성 프로시저는 첫 문장에서 그 함수를 부른다. 운영에서는 런타임
권한 조정기(``runtime_privileges``)가 같은 권한을 다시 줘서 돌았을 뿐이고, 418의 상수를 다시 적던
단위 검사는 초록이었다.

그래서 상수가 아니라 **migration만으로 만든 head 오라클**(``alembic/head-schema.sql``)에서 유도한다.
SECURITY DEFINER 루틴은 소유자 권한으로 돌므로, 그 본문이 부르는 protocol 진입은 소유자가
소유하거나 EXECUTE를 받아야 한다. 조정기를 거치지 않은 DB(복원 직후·제자리 업그레이드 리허설)에서
그 규칙이 깨지면 첫 호출이 42501로 죽는다.
"""

from __future__ import annotations

import pathlib
import re
from typing import Final

_ROOT = pathlib.Path(__file__).resolve().parents[2]
_HEAD_SCHEMA = _ROOT / "alembic" / "head-schema.sql"

#: 다른 루틴이 첫 문장에서 부르는 protocol 진입(P·L·단건 regime).
_ENTRY_FUNCTIONS: Final[frozenset[str]] = frozenset(
    {
        "ops.lock_scoped_feature_write_protocol",
        "ops.lock_single_feature_writer_protocol",
        "ops.lock_provider_evidence_writer_protocol",
        "ops.lock_provider_feature_tracking_protocol",
    }
)
_HEADER = re.compile(
    r"^CREATE (?:PROCEDURE|FUNCTION) (?P<name>[a-z_]+\.[a-z_0-9]+)\(", re.MULTILINE
)
_OWNER = re.compile(
    r"^ALTER (?:PROCEDURE|FUNCTION) (?P<name>[a-z_]+\.[a-z_0-9]+)\(.*?\) "
    r"OWNER TO (?P<owner>[a-z_]+);$",
    re.MULTILINE | re.DOTALL,
)
_GRANT = re.compile(
    r"^GRANT ALL ON FUNCTION (?P<name>[a-z_]+\.[a-z_0-9]+)\(.*?\) TO (?P<role>[a-z_]+);$",
    re.MULTILINE,
)
_CALL = re.compile(r"\b(?P<name>ops\.lock_[a-z_]+_protocol)\(")


def _routines(schema: str) -> dict[str, tuple[str, bool]]:
    """이름 → (본문, SECURITY DEFINER 여부). 본문은 머리에서 그 루틴의 OWNER 문까지다."""
    routines: dict[str, tuple[str, bool]] = {}
    for match in _HEADER.finditer(schema):
        end = schema.find("\nALTER ", match.end())
        text = schema[match.end() : end if end != -1 else len(schema)]
        head = text.split(" AS ", 1)[0]
        routines[match["name"]] = (text, "SECURITY DEFINER" in head)
    return routines


def acl_violations(schema: str) -> tuple[list[str], int]:
    """(위반, 본 호출 수). 위반은 ``caller(owner) → entry`` 형태다."""
    owners = {match["name"]: match["owner"] for match in _OWNER.finditer(schema)}
    grantees: dict[str, set[str]] = {}
    for match in _GRANT.finditer(schema):
        grantees.setdefault(match["name"], set()).add(match["role"])
    violations: list[str] = []
    seen = 0
    for name, (body, security_definer) in sorted(_routines(schema).items()):
        if name in _ENTRY_FUNCTIONS or not security_definer:
            continue
        owner = owners.get(name)
        for call in sorted({match["name"] for match in _CALL.finditer(body)}):
            if call not in _ENTRY_FUNCTIONS:
                continue
            seen += 1
            if owner is None or owner == owners.get(call):
                continue
            if owner not in grantees.get(call, set()):
                violations.append(f"{name}({owner}) → {call}")
    return violations, seen


def test_every_security_definer_caller_can_execute_its_protocol_entry() -> None:
    violations, seen = acl_violations(_HEAD_SCHEMA.read_text(encoding="utf-8"))
    # 433 head에는 P·L·regime 진입을 부르는 SECURITY DEFINER 루틴이 40개를 넘는다.
    assert seen >= 30, f"protocol 진입 호출을 {seen}개만 봤다 — 추출이 낡았다"
    assert not violations, (
        "migration만으로 만든 head에서 소유자가 EXECUTE를 갖지 못한 protocol 진입 호출:\n  "
        + "\n  ".join(violations)
        + "\n\n함수 소유자 창(`SET ROLE <owner>`)에서 GRANT해야 실제로 부여된다 — schema owner의 "
        "GRANT는 grant option이 없어 경고만 내고 아무것도 주지 않는다(418)."
    )


_PLANTED = """
--
CREATE FUNCTION ops.lock_scoped_feature_write_protocol(p_exclusive boolean) RETURNS void
    LANGUAGE plpgsql SECURITY DEFINER
    AS $$ BEGIN NULL; END $$;
ALTER FUNCTION ops.lock_scoped_feature_write_protocol(p_exclusive boolean) OWNER TO owner_a;
CREATE PROCEDURE feature.granted_caller(IN p uuid)
    LANGUAGE plpgsql SECURITY DEFINER
    AS $$ BEGIN PERFORM ops.lock_scoped_feature_write_protocol(true); END $$;
ALTER PROCEDURE feature.granted_caller(IN p uuid) OWNER TO owner_b;
CREATE PROCEDURE feature.ungranted_caller(IN p uuid)
    LANGUAGE plpgsql SECURITY DEFINER
    AS $$ BEGIN PERFORM ops.lock_scoped_feature_write_protocol(true); END $$;
ALTER PROCEDURE feature.ungranted_caller(IN p uuid) OWNER TO owner_c;
CREATE PROCEDURE feature.invoker_caller(IN p uuid)
    LANGUAGE plpgsql
    AS $$ BEGIN PERFORM ops.lock_scoped_feature_write_protocol(true); END $$;
ALTER PROCEDURE feature.invoker_caller(IN p uuid) OWNER TO owner_d;
GRANT ALL ON FUNCTION ops.lock_scoped_feature_write_protocol(p_exclusive boolean) TO owner_b;
"""


def test_the_oracle_turns_red_on_a_planted_ungranted_owner() -> None:
    violations, seen = acl_violations(_PLANTED)
    assert seen == 2, seen
    assert violations == [
        "feature.ungranted_caller(owner_c) → ops.lock_scoped_feature_write_protocol"
    ], violations
