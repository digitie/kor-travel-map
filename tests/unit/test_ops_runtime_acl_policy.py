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
    _OPS_TABLE_PRIVILEGES,
    _ORDINARY_SCHEMA_PRIVILEGES,
    _runtime_relation_grants,
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


def test_undeclared_ops_relation_is_refused_not_granted() -> None:
    """상수가 아니라 동작을 본다 — 선언 없는 ops 표는 권한 대신 이름으로 나와야 한다.

    상수만 보면(`"ops" not in _ORDINARY_SCHEMA_PRIVILEGES`) 분기가 다시 기본값으로
    떨어져도 green이 될 수 있다. inventory를 직접 통과시켜 판정한다.
    """

    grants, unknown = _runtime_relation_grants(
        [
            {
                "schema_name": _OPS_SCHEMA,
                "relation_name": "acl_probe_never_declared",
                "relation_kind": "r",
            }
        ]
    )

    assert grants == [], f"선언 없는 ops 표에 권한이 나갔습니다: {grants}"
    assert unknown == [f"{_OPS_SCHEMA}.acl_probe_never_declared"]


def test_ops_has_no_silent_schema_default() -> None:
    """위 동작 게이트가 기대는 전제 — 기본값 자체가 남아 있으면 안 된다."""

    assert _OPS_SCHEMA not in _ORDINARY_SCHEMA_PRIVILEGES


def test_provider_sync_still_uses_the_ordinary_schema_default() -> None:
    """엄격해진 것은 `ops`뿐이다 — 옆 스키마를 함께 잠그면 이 변경의 범위를 넘는다."""

    grants, unknown = _runtime_relation_grants(
        [
            {
                "schema_name": "provider_sync",
                "relation_name": "source_records",
                "relation_kind": "r",
            }
        ]
    )

    assert unknown == []
    assert len(grants) == 1
    assert "provider_sync" in grants[0]


def test_declared_privileges_are_a_subset_of_ordinary_crud() -> None:
    """선언은 좁히기 위한 것이다 — 평범한 CRUD보다 넓은 값이 들어오면 잡는다."""

    allowed = frozenset({"SELECT", "INSERT", "UPDATE", "DELETE"})
    wider = {
        name: sorted(set(privileges) - allowed)
        for name, privileges in _OPS_TABLE_PRIVILEGES.items()
        if set(privileges) - allowed
    }

    assert wider == {}, f"평범한 CRUD 밖의 권한이 선언됐습니다: {wider}"
