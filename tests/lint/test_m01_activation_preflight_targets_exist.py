"""`m01_activation_preflight`가 겨누는 대상이 **실재하는지** 결박한다.

이 preflight는 role·relation·routine 이름을 상수로 갖는다. 상수가 스키마와 어긋나면
`has_*_privilege`가 오류를 내거나(존재하지 않는 관계) 검사가 조용히 다른 것을 본다.
그러면 "22/22 통과"가 근거가 되지 못한다.

그래서 이름을 `alembic/baseline/schema.sql`과 `docker/postgres-role-bootstrap.sh`에
대조한다. 한쪽이 바뀌면 여기서 깨진다(AGENTS.md DO NOT 15: 유도 → 결박 → 탐지).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[2]
_SCHEMA = _ROOT / "alembic" / "baseline" / "schema.sql"
_BOOTSTRAP = _ROOT / "docker" / "postgres-role-bootstrap.sh"
_PREFLIGHT = _ROOT / "scripts" / "m01_activation_preflight.py"


def _preflight_source() -> str:
    return _PREFLIGHT.read_text(encoding="utf-8")


def _constant(name: str) -> str:
    match = re.search(rf'^{name} = "(?P<value>[^"]+)"', _preflight_source(), re.MULTILINE)
    assert match is not None, f"{name} 상수를 찾지 못했다 — 이 게이트가 공허해졌다"
    return match.group("value")


def _tuple_constant(name: str) -> tuple[str, ...]:
    match = re.search(rf"^{name} = \((?P<body>.*?)\)$", _preflight_source(), re.MULTILINE | re.DOTALL)
    assert match is not None, f"{name} 상수를 찾지 못했다 — 이 게이트가 공허해졌다"
    return tuple(re.findall(r'"([^"]+)"', match.group("body")))


def test_the_gate_reads_the_real_constants() -> None:
    """상수를 실제로 읽었는지부터 본다 — 비면 아래 단언이 공허하다."""

    relations = _tuple_constant("PROTECTED_RELATIONS")
    assert len(relations) >= 2, f"보호 관계를 {len(relations)}개만 읽었다 — 파서를 의심하라"
    for name in ("API_LOGIN", "DAGSTER_LOGIN", "SCHEMA_OWNER", "MANUAL_PROCEDURE_OWNER"):
        assert _constant(name).startswith("ktm_"), f"{name}이 role 이름 같지 않다"


def test_every_protected_relation_exists_in_the_baseline() -> None:
    """claim/origin 관계가 baseline DDL에 실재해야 한다."""

    schema = _SCHEMA.read_text(encoding="utf-8")
    missing = [
        relation
        for relation in _tuple_constant("PROTECTED_RELATIONS")
        if f"CREATE TABLE {relation} (" not in schema
    ]
    assert missing == [], (
        f"preflight가 겨누는 관계가 baseline에 없다: {missing}. "
        "이름이 바뀌었으면 preflight 상수도 함께 옮겨라 — 그러지 않으면 검사가 "
        "존재하지 않는 대상을 보며 조용히 통과하거나 오류로 죽는다."
    )


def test_the_routine_split_targets_exist_in_the_baseline() -> None:
    """wrapper와 generic 루틴이 baseline DDL에 실재해야 한다."""

    schema = _SCHEMA.read_text(encoding="utf-8")
    missing = [
        routine
        for routine in (_constant("WRAPPER_ROUTINE"), _constant("GENERIC_ROUTINE"))
        if f"CREATE PROCEDURE feature.{routine}(" not in schema
    ]
    assert missing == [], f"preflight가 겨누는 루틴이 baseline에 없다: {missing}"


def test_every_role_the_preflight_names_is_created_by_the_bootstrap() -> None:
    """preflight가 이름 붙인 role을 bootstrap이 실제로 만들어야 한다."""

    bootstrap = _BOOTSTRAP.read_text(encoding="utf-8")
    names = [
        _constant(name)
        for name in (
            "API_LOGIN",
            "DAGSTER_LOGIN",
            "SCHEMA_OWNER",
            "MANUAL_PROCEDURE_OWNER",
            "ADMIN_EXECUTOR",
            "PROVIDER_EXECUTOR",
        )
    ]
    missing = [name for name in names if name not in bootstrap]
    assert missing == [], (
        f"preflight가 이름 붙인 role을 bootstrap이 모른다: {missing}. "
        "role 인벤토리는 `docker/postgres-role-bootstrap.sh`가 정본이다."
    )
