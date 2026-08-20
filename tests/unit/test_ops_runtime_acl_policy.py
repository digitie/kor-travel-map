"""`ops` 스키마 runtime ACL의 **동작** 게이트.

2026-08-20까지 `ops`는 선언이 없으면 조용히 full CRUD로 떨어졌다. 같은 파일의
`feature`는 선언 없는 relation을 예외로 막고 있었으므로 이건 설계 차이가 아니라
비대칭이었다. 대칭을 맞춘 뒤, 그 대칭이 다시 무너지지 않게 한다.

**목록이 실제와 맞는지는 여기서 보지 않는다.** 첫 판은 `Base.metadata`의 ops 표와
선언을 맞춰 봤는데, reconcile이 순회하는 것은 metadata가 아니라 DB다. 실제로 모델에
없는 ops 표가 17개 있어서 그 게이트는 green인 채로 아무 것도 보지 못했다(n150 격리
DB 리허설이 잡았다). 목록 대조는 `tests/integration/test_runtime_privileges_acl.py`가
migrate된 DB를 상대로 양방향으로 한다.
"""

from __future__ import annotations

from typing import Final

from kortravelmap.infra.runtime_privileges import (
    _OPS_TABLE_PRIVILEGES,
    _ORDINARY_SCHEMA_PRIVILEGES,
    _runtime_relation_grants,
)

_OPS_SCHEMA: Final[str] = "ops"


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
