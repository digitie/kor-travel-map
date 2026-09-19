"""override field-path 레지스트리가 **실재하는 컬럼**을 가리키는지 본다.

`ops.feature_override_field_paths`는 "이 field_path가 어느 표의 어느 컬럼에
앉는가"를 선언한다. 그 선언은 DDL과 따로 산다 — 컬럼이 이사하거나 사라져도
레지스트리는 아무 말 없이 옛 자리를 계속 가리킨다.

2026-09-20에 그 일이 일어났다. ADR-099 2단계가 route geometry를
`feature.feature_route_geometries`로 옮겼는데 `'route.geom'` 행은
`('feature_routes', 'geom')`을 계속 가리켰고, 이 저장소의 어떤 검사도 그것을
보지 않았다. 레지스트리에서 SQL을 유도하는 코드가 아직 없어 **조용했을 뿐**이다.

이 검사는 이름이 아니라 **효과**에 결박한다 — 레지스트리의 모든 행을
`information_schema.columns`와 대조한다. 어느 컬럼이 어디로 가든, 레지스트리가
따라오지 않으면 여기서 빨갛게 된다.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration


async def test_every_declared_field_path_resolves_to_a_live_column(
    migrated_session: AsyncSession,
) -> None:
    rows = (
        await migrated_session.execute(
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
    ).mappings().all()

    # 하한을 '본 것'에 건다 — 레지스트리가 비면 이 검사는 항진명제가 된다.
    assert len(rows) >= 20, (
        f"레지스트리 행이 {len(rows)}건뿐이다 — 이 검사가 아무것도 보지 않고 "
        "초록을 줄 수 있는 상태다."
    )

    dangling = [
        f"{row['field_path']} -> {row['target_relation']}.{row['target_column']}"
        for row in rows
        if not row["column_exists"]
    ]
    assert not dangling, (
        "레지스트리가 없는 컬럼을 가리킨다: "
        + ", ".join(dangling)
        + ". 컬럼이 이사했으면 레지스트리도 함께 옮겨야 한다."
    )


async def test_route_geometry_registry_points_at_the_sidecar_relation(
    migrated_session: AsyncSession,
) -> None:
    """`'route.geom'`은 이름을 유지하되 자리는 보조 relation이어야 한다.

    위 검사는 "어딘가 실재하는 컬럼"까지만 본다. `'route.geom'`이 예컨대
    `feature_routes.route_type`을 가리켜도 통과한다. 이 검사가 그 자리를 못 박는다.
    자리는 적재 경로의 모델에서 읽는다.
    """

    from kortravelmap.infra.feature_subtype import GEOMETRY_RELATIONS

    row = (
        await migrated_session.execute(
            text(
                "SELECT target_relation, target_column, geometry_type "
                "FROM ops.feature_override_field_paths "
                "WHERE field_path = 'route.geom'"
            )
        )
    ).mappings().one()

    assert row["target_relation"] == GEOMETRY_RELATIONS["route"], (
        f"route.geom이 {row['target_relation']}에 앉아 있다 — "
        f"적재 경로는 {GEOMETRY_RELATIONS['route']}에 쓴다."
    )
    assert row["target_column"] == "geom"
    assert row["geometry_type"] == "MULTILINESTRING"
