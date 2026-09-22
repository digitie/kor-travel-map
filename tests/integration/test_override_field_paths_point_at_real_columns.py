"""override field-path 레지스트리가 **실재하는 컬럼**을 가리키는지 본다.

`ops.feature_override_field_paths`는 "이 field_path가 어느 표의 어느 컬럼에
앉는가"를 선언한다. 그 선언은 DDL과 따로 살기 때문에, 컬럼이 이사하거나 사라져도
레지스트리는 아무 말 없이 옛 자리를 계속 가리킨다.

2026-09-20에 그 일이 일어났다. ADR-099 2단계가 route geometry를
`feature.feature_route_geometries`로 옮겼는데 `'route.geom'` 행은
`('feature_routes', 'geom')`을 계속 가리킨다. 이 저장소의 어떤 검사도 그것을 보지
않았고, 레지스트리에서 SQL을 유도하는 코드가 아직 없어 **조용했다**.

## 왜 아직 고쳐지지 않았는가

**종전에는 고칠 수 없었다.** seed 영수증이 이 표의 전 행을
`to_jsonb(row) - ['created_at','updated_at']`로 해시해 rev 300 시점 값으로 봉인했고,
배포 허가 사슬 세 곳이 그 해시를 게이트로 썼다. `target_relation`이 그 해시에 들어가는
컬럼이라, 행을 고치면 배포가 seed 영수증 불일치로 멎었다(2026-09-20 실측:
`fresh finalize seed receipt does not match baseline`). 봉인값을 다시 뜨려면 살아 있는
격리 0236 컨테이너가 필요했는데 그것이 막혀 있었다.

**지금은 고칠 수 있다.** `400` 스쿼시가 그 영수증 사슬을 통째로 걷어냈고 seed는 평범한
덤프가 됐다. 고치지 않고 두는 것은 그것이 seed **데이터** 결정이고 스쿼시의 범위가
아니기 때문이다 — 행 하나를 지우는 일이지만 레지스트리 내용을 바꾸는 일이다.

## 그래서 이 검사는 **알려진 간극을 못 박는다**

예외 목록을 두지 않는다. 예외는 조용히 늘어나고 검사를 갉아먹는다. 대신 이 간극을
**단언**한다 — 누가 그 행을 지우는 순간 이 검사가 빨갛게 되고, 그때 아래
`test_the_known_route_geometry_gap_is_still_exactly_one_row`를 지우고 위 일반 검사에
`route.geom`을 되돌려 넣는다.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration

#: 봉인 때문에 312가 옮기지 못했던 행. 봉인은 사라졌고 행은 남았다 — 이 집합이
#: 커지면 그것은 새 간극이고, 아래 검사가 잡는다.
_SEALED_STALE_FIELD_PATHS: frozenset[str] = frozenset({"route.geom"})


async def _registry_rows(session: AsyncSession) -> list[dict[str, object]]:
    return [
        dict(row)
        for row in (
            await session.execute(
                text(
                    """
                    SELECT path.field_path,
                           path.target_relation,
                           path.target_column,
                           column_catalog.data_type IS NOT NULL AS column_exists
                    FROM ops.feature_override_field_paths AS path
                    LEFT JOIN information_schema.columns AS column_catalog
                      ON column_catalog.table_schema
                           = CASE WHEN path.target_relation LIKE 'feature%%'
                                  THEN 'feature' ELSE 'ops' END
                     AND column_catalog.table_name = path.target_relation
                     AND column_catalog.column_name = path.target_column
                    ORDER BY path.field_path
                    """
                )
            )
        ).mappings()
    ]


async def test_every_declared_field_path_resolves_to_a_live_column(
    migrated_session: AsyncSession,
) -> None:
    """봉인 때문에 못 옮긴 한 행을 빼면, 모든 선언이 실재 컬럼을 가리켜야 한다."""

    rows = await _registry_rows(migrated_session)

    # 하한을 '본 것'에 건다 — 레지스트리가 비면 이 검사는 항진명제가 된다.
    assert len(rows) >= 20, (
        f"레지스트리 행이 {len(rows)}건뿐이다 — 이 검사가 아무것도 보지 않고 "
        "초록을 줄 수 있는 상태다."
    )

    dangling = {
        str(row["field_path"]): f"{row['target_relation']}.{row['target_column']}"
        for row in rows
        if not row["column_exists"]
    }
    unexpected = {
        field_path: target
        for field_path, target in dangling.items()
        if field_path not in _SEALED_STALE_FIELD_PATHS
    }
    assert not unexpected, (
        "레지스트리가 없는 컬럼을 가리킨다: "
        + ", ".join(f"{k} -> {v}" for k, v in sorted(unexpected.items()))
        + ". 컬럼이 이사했으면 레지스트리도 함께 옮겨야 한다."
    )


async def test_the_known_route_geometry_gap_is_still_exactly_one_row(
    migrated_session: AsyncSession,
) -> None:
    """**알려진 간극을 못 박는다** — 봉인이 풀리면 여기가 먼저 빨갛게 된다.

    `'route.geom'`은 geometry가 이사한 뒤에도 `feature_routes.geom`을 가리킨다.
    그것을 고치면 baseline seed 영수증이 어긋나 fresh 300 배포가 멎기 때문이다
    (모듈 docstring 참조).

    그 상태가 **정확히 이 한 행**임을 단언한다. baseline을 다시 봉인해 레지스트리를
    옮기면 이 검사가 실패하고, 그때 이 검사를 지우고 위 검사의 예외 집합을 비운다.
    """

    from kortravelmap.infra.feature_subtype import GEOMETRY_RELATIONS

    rows = await _registry_rows(migrated_session)
    dangling = {str(row["field_path"]) for row in rows if not row["column_exists"]}
    assert dangling == _SEALED_STALE_FIELD_PATHS, (
        f"매달린 선언이 {sorted(dangling)}이다 — 기대는 "
        f"{sorted(_SEALED_STALE_FIELD_PATHS)}. 줄었다면 baseline 봉인이 풀린 "
        "것이므로 이 검사를 지우고 레지스트리를 옮길 것. 늘었다면 새 간극이다."
    )

    row = next(row for row in rows if row["field_path"] == "route.geom")
    assert row["target_relation"] == "feature_routes", row
    assert row["target_column"] == "geom", row
    # 적재 경로가 실제로 쓰는 자리. 둘이 갈라져 있다는 사실 자체가 이 간극이다.
    assert GEOMETRY_RELATIONS["route"] == "feature_route_geometries"
