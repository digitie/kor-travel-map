"""T-VN-18 — 자동 full GiST 제거 + partial 유지 + write-cost 실측 (F-8 / D-12-3).

- head(0061)에서 자동 full GiST 3개는 사라지고 공개 술어 partial GiST 3개만 남는다.
- 공개 bbox/nearest-weather 조회의 planner가 partial GiST를 선택한다(EXPLAIN 회귀).
- weather source-record 지원 index(T-VN-17 이월)가 존재한다.
- write-cost 실측(§8.3 필수): full 포함(6 GiST) vs partial만(3 GiST) INSERT 처리량.
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.integration

# 서울 근처 bbox — 공개 조회 EXPLAIN용.
_BBOX = (126.9, 37.5, 127.1, 37.7)

# T-VN-35(alembic 0086): geometry는 core 컬럼이 아니다 — geom GiST 축은
# route/area subtype으로 이동했다(``idx_feature_routes_geom_gist`` /
# ``idx_feature_areas_geom_gist``). 따라서 core의 full/partial GiST 감사 대상은
# coord 2축만 남는다.
_FULL_GIST = ("idx_features_coord", "idx_features_coord_5179")
_PARTIAL_GIST = (
    "idx_features_coord_gist",
    "idx_features_coord_5179_gist",
)
#: geometry GiST 정본 — subtype 테이블별 1개씩.
_SUBTYPE_GEOM_GIST = {
    "feature_routes": "idx_feature_routes_geom_gist",
    "feature_areas": "idx_feature_areas_geom_gist",
}


async def _index_names(session: Any, table: str, schema: str = "feature") -> set[str]:
    rows = await session.execute(
        text(
            "SELECT indexname FROM pg_indexes "
            "WHERE schemaname = :s AND tablename = :t"
        ),
        {"s": schema, "t": table},
    )
    return {r[0] for r in rows}


async def test_head_keeps_partial_gist_and_drops_full_gist(
    migrated_session: Any,
) -> None:
    """head: core partial GiST 유지 · 자동 full GiST 제거 · geom GiST는 subtype."""
    names = await _index_names(migrated_session, "features")
    for partial in _PARTIAL_GIST:
        assert partial in names, f"partial GiST {partial} must remain"
    for full in _FULL_GIST:
        assert full not in names, f"auto full GiST {full} must be dropped"
    # T-VN-35: core geom GiST는 사라지고 subtype이 각자 갖는다.
    assert "idx_features_geom_gist" not in names
    for table, index_name in _SUBTYPE_GEOM_GIST.items():
        assert index_name in await _index_names(migrated_session, table)


async def test_weather_source_record_support_index_exists(
    migrated_session: Any,
) -> None:
    """T-VN-38 fact/current lookup index가 immutable weather schema에 존재한다."""
    names = await _index_names(migrated_session, "feature_weather_values")
    assert "idx_weather_values_feature_target_known" in names
    assert "idx_weather_values_source_record" not in names


async def _seed_public_points(session: Any, count: int, prefix: str) -> None:
    # 전국(124.5~131.5 lon, 33.5~39.5 lat)에 고르게 뿌려 Seoul bbox/50km 반경이
    # 선택적(few match)이 되게 한다 → GiST bbox/KNN 스캔이 명확히 최적.
    #
    # T-VN-34(0095~0097): 옛 seed의 ``status='active'``가 여기서 하던 일은 "이 행을
    # 공개 표면에 올려 partial GiST가 실제로 색인하게 만든다"였다. 0095 backfill이
    # 정한 대응이 정확히 ``status='active'`` → (lifecycle active, publication
    # published, quality valid)이고, 0096이 만든 partial GiST의 predicate도 같은 세
    # 축이다. 그래서 이 세 값은 컬럼 DEFAULT와 같더라도 명시한다 — 하나라도
    # 어긋나면 seed 행이 partial index에서 통째로 빠져 EXPLAIN 단언이 "index를 못
    # 골랐다"가 아니라 "고를 행이 없었다"로 조용히 무너진다.
    await session.execute(
        text(
            """
            INSERT INTO feature.features (
                feature_id, kind, name, category, coord,
                lifecycle_state, publication_state, quality_state, updated_at
            )
            SELECT
                :prefix || g, 'place', 'p', '06020000',
                x_extension.ST_SetSRID(
                    x_extension.ST_MakePoint(
                        124.5 + (g % 700) * 0.01, 33.5 + ((g / 700) % 600) * 0.01
                    ),
                    4326
                ),
                'active', 'published', 'valid', now()
            FROM generate_series(1, :count) AS g
            """
        ),
        {"prefix": prefix, "count": count},
    )
    await session.flush()
    # planner가 GiST 선택도를 알도록 통계 갱신.
    await session.execute(text("ANALYZE feature.features"))
    # 축 값을 되읽어 확인하지 않고 공개 view 실재를 확인한다. EXPLAIN 단언이 기대는
    # 전제는 "seed가 공개 표면에 있다"이지 "세 컬럼이 이 문자열이다"가 아니며,
    # ``feature.public_features``가 그 전제의 정본이다(공개 predicate가 바뀌면 여기서
    # 먼저 터진다).
    seeded = await session.execute(
        text(
            "SELECT count(*) FROM feature.public_features "
            "WHERE feature_id LIKE :prefix || '%'"
        ),
        {"prefix": prefix},
    )
    assert seeded.scalar_one() == count, "seed는 공개 표면에 전부 보여야 한다"


async def test_public_bbox_query_plans_partial_coord_gist(
    migrated_session: Any,
) -> None:
    """공개 bbox 조회가 partial coord GiST를 사용한다(full 제거 후에도)."""
    await _seed_public_points(migrated_session, 5000, "gist:bbox:")
    # index 후보를 강제 노출 — partial이 eligible하면 planner가 선택한다.
    await migrated_session.execute(text("SET LOCAL enable_seqscan = off"))
    plan_rows = await migrated_session.execute(
        text(
            """
            EXPLAIN
            SELECT f.feature_id
            FROM feature.public_features AS f
            WHERE f.coord IS NOT NULL
              AND f.coord OPERATOR(x_extension.&&) x_extension.ST_MakeEnvelope(
                    CAST(:min_lon AS double precision),
                    CAST(:min_lat AS double precision),
                    CAST(:max_lon AS double precision),
                    CAST(:max_lat AS double precision), 4326)
            """
        ),
        {
            "min_lon": _BBOX[0],
            "min_lat": _BBOX[1],
            "max_lon": _BBOX[2],
            "max_lat": _BBOX[3],
        },
    )
    plan = "\n".join(r[0] for r in plan_rows)
    assert "idx_features_coord_gist" in plan, plan
    assert "Seq Scan" not in plan, plan


async def test_nearest_weather_query_plans_partial_coord_5179_gist(
    migrated_session: Any,
) -> None:
    """nearest-weather(coord_5179 ST_DWithin)가 partial coord_5179 GiST를 사용한다."""
    await _seed_public_points(migrated_session, 5000, "gist:knn:")
    await migrated_session.execute(text("SET LOCAL enable_seqscan = off"))
    plan_rows = await migrated_session.execute(
        text(
            """
            EXPLAIN
            SELECT f.feature_id
            FROM feature.public_features AS f
            WHERE f.coord_5179 IS NOT NULL
              AND x_extension.ST_DWithin(
                    f.coord_5179,
                    x_extension.ST_Transform(
                        x_extension.ST_SetSRID(
                            x_extension.ST_MakePoint(126.978, 37.5665), 4326),
                        5179),
                    CAST(50000 AS double precision))
            """
        )
    )
    plan = "\n".join(r[0] for r in plan_rows)
    assert "idx_features_coord_5179_gist" in plan, plan
    assert "Seq Scan" not in plan, plan
