"""`ops` 스키마의 runtime ACL 선언이 실제 표 집합과 정확히 맞는지 본다.

2026-08-20까지 `ops`는 선언이 없으면 조용히 full CRUD로 떨어졌다 — 표 57개 중 48개가
그 경로였다. 같은 파일의 `feature`는 선언 없는 relation을 예외로 막고 있었으므로 이건
설계 차이가 아니라 비대칭이었다. 대칭을 맞춘 뒤, 그 대칭이 다시 무너지지 않게 한다.

양방향을 본다. 선언이 빠지면 새 표가 권한을 그냥 얻고, 선언이 남으면 없는 표를 가리켜
다음 사람이 그 표가 아직 있다고 읽는다(`0225`가 지운 `curation_*` 9개가 실제로 그랬다).
"""

from __future__ import annotations

from typing import Final

from kortravelmap.infra.models import Base
from kortravelmap.infra.runtime_privileges import (
    _ORDINARY_SCHEMA_PRIVILEGES,
    _OPS_TABLE_PRIVILEGES,
)

_OPS_SCHEMA: Final[str] = "ops"


def _ops_tables() -> frozenset[str]:
    return frozenset(
        table.name
        for table in Base.metadata.tables.values()
        if table.schema == _OPS_SCHEMA
    )


def test_every_ops_table_has_a_deliberate_acl_declaration() -> None:
    """선언하지 않으면 권한이 생기던 경로를 막는다."""

    undeclared = sorted(_ops_tables() - set(_OPS_TABLE_PRIVILEGES))

    assert undeclared == [], (
        "ops 표에 runtime ACL 선언이 없습니다. `_OPS_TABLE_PRIVILEGES`에 명시하세요 — "
        "선언을 빠뜨리면 그 표는 권한 심사 없이 지나갑니다: " + ", ".join(undeclared)
    )


def test_no_acl_declaration_points_at_a_removed_table() -> None:
    """없는 표를 가리키는 선언은 그 표가 아직 있다고 읽히게 만든다."""

    stale = sorted(set(_OPS_TABLE_PRIVILEGES) - _ops_tables())

    assert stale == [], (
        "metadata에 없는 ops 표의 ACL 선언이 남아 있습니다. 표를 지웠다면 선언도 "
        "지우세요: " + ", ".join(stale)
    )


def test_ops_has_no_silent_schema_default() -> None:
    """기본값이 남아 있으면 위 두 게이트를 우회해 다시 조용히 권한이 생긴다."""

    assert _OPS_SCHEMA not in _ORDINARY_SCHEMA_PRIVILEGES


def test_declared_privileges_are_a_subset_of_ordinary_crud() -> None:
    """선언은 좁히기 위한 것이다 — 평범한 CRUD보다 넓은 값이 들어오면 잡는다."""

    allowed = frozenset({"SELECT", "INSERT", "UPDATE", "DELETE"})
    wider = {
        name: sorted(set(privileges) - allowed)
        for name, privileges in _OPS_TABLE_PRIVILEGES.items()
        if set(privileges) - allowed
    }

    assert wider == {}, f"평범한 CRUD 밖의 권한이 선언됐습니다: {wider}"
