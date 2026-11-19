"""T-READ-10 — 저배율 집계의 생성 컬럼 경로가 종전 SQL과 같은 결과를 내는가 (testcontainers).

alembic 454가 ``feature.feature_route_geometries``에 단 생성 컬럼(``marker_point``·``geom_xmin``…)을
집계 SQL이 쓰도록 바꿨다. 이 파일은 **바뀌기 전 SQL의 사본**(``_legacy_cluster_sql``)을 오라클로
두고, 같은 DB·같은 인자에서 두 SQL의 결과(cluster별 개수·대표점)를 비교한다.

seed는 결과를 가를 만한 모양을 일부러 넣는다 — bbox 안에 완전히 든 route(생성 컬럼 경로),
bbox를 가로지르는 route(교차 부분 위의 점), MBR만 겹치고 실제로는 비켜 가는 route(정확
``ST_Intersects``가 빼야 한다), bbox 변에 정확히 닿는 route(포함 판정 ``>=``/``<=``의 경계),
구멍 난 area, 공개되지 않은 route, 지역 코드가 없는 route. bbox는 전국·광역·좁은 화면 셋, kind
필터는 전 kind·route만·area만·place+route.

대표점 비교의 허용 오차: 개수는 정확히 같아야 한다. 평균 좌표(``avg``)는 float 합의 순서에 따라
마지막 자리가 달라질 수 있어(계획이 행을 다른 순서로 넘기면) 1e-9도로 비교한다(약 0.1 mm).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from sqlalchemy import text

from kortravelmap.infra import feature_repo

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration

_UNITS = {"sido": "sido_code", "sigungu": "sigungu_code", "eupmyeondong": "legal_dong_code"}


def _legacy_cluster_sql(code_col: str) -> str:
    """T-READ-10 전(#1455) geometry arm 포함 집계 SQL의 사본 — 비교 오라클. 고치지 않는다."""
    env = feature_repo._bbox_envelope_sql()
    attr = feature_repo._bbox_attribute_filter_sql("f")
    notice = feature_repo._PUBLIC_ACTIVE_NOTICE_FILTER_SQL
    return f"""
WITH geometry_candidates AS MATERIALIZED (
  SELECT
      f.{code_col} AS cluster_key,
      CASE
        WHEN x_extension.ST_XMin(bbox_hit.geom) >= CAST(:min_lon AS double precision)
          AND x_extension.ST_XMax(bbox_hit.geom) <= CAST(:max_lon AS double precision)
          AND x_extension.ST_YMin(bbox_hit.geom) >= CAST(:min_lat AS double precision)
          AND x_extension.ST_YMax(bbox_hit.geom) <= CAST(:max_lat AS double precision)
          THEN x_extension.ST_PointOnSurface(bbox_hit.geom)
        ELSE x_extension.ST_PointOnSurface(
          x_extension.ST_Intersection(bbox_hit.geom, {env})
        )
      END AS marker_coord
  FROM (
    SELECT bbox_hit_route.feature_id, bbox_hit_route.geom
    FROM feature.feature_route_geometries AS bbox_hit_route
    WHERE (CAST(:kinds AS text[]) IS NULL OR 'route' = ANY(CAST(:kinds AS text[])))
      AND bbox_hit_route.public_ready
      AND bbox_hit_route.geom OPERATOR(x_extension.&&) {env}
      AND x_extension.ST_Intersects(bbox_hit_route.geom, {env})
    UNION ALL
    SELECT bbox_hit_area.feature_id, bbox_hit_area.geom
    FROM feature.feature_areas AS bbox_hit_area
    WHERE (CAST(:kinds AS text[]) IS NULL OR 'area' = ANY(CAST(:kinds AS text[])))
      AND bbox_hit_area.public_ready
      AND bbox_hit_area.geom OPERATOR(x_extension.&&) {env}
      AND x_extension.ST_Intersects(bbox_hit_area.geom, {env})
  ) AS bbox_hit
  JOIN feature.public_features AS f ON f.feature_id = bbox_hit.feature_id
  WHERE f.{code_col} IS NOT NULL
{attr}
{notice}
),
bbox_candidates AS (
  SELECT
      f.{code_col} AS cluster_key,
      x_extension.ST_X(f.coord) AS lon,
      x_extension.ST_Y(f.coord) AS lat
  FROM feature.public_features AS f
  WHERE f.{code_col} IS NOT NULL
    AND f.coord IS NOT NULL
    AND f.coord OPERATOR(x_extension.&&) {env}
    AND f.kind NOT IN ('route', 'area')
{attr}
{notice}
  UNION ALL
  SELECT
      cluster_key,
      x_extension.ST_X(marker_coord) AS lon,
      x_extension.ST_Y(marker_coord) AS lat
  FROM geometry_candidates
  WHERE marker_coord IS NOT NULL
)
SELECT
    cluster_key,
    count(*) AS feature_count,
    avg(lon) AS lon,
    avg(lat) AS lat
FROM bbox_candidates
GROUP BY cluster_key
ORDER BY feature_count DESC, cluster_key
LIMIT :limit
"""


# 지역 코드: 0.5도 격자 → 시도, 0.1도 → 시군구, 0.02도 → 읍면동(합성 값).
_CODES = """
  lpad((10 + floor((LON - 126.0) / 0.5)::int * 3 + floor((LAT - 37.0) / 0.5)::int)::text, 2, '0'),
  lpad((10 + floor((LON - 126.0) / 0.5)::int * 3 + floor((LAT - 37.0) / 0.5)::int)::text, 2, '0')
    || lpad((floor((LON - 126.0) / 0.1)::int * 20 + floor((LAT - 37.0) / 0.1)::int)::text, 3, '0'),
  lpad((10 + floor((LON - 126.0) / 0.5)::int * 3 + floor((LAT - 37.0) / 0.5)::int)::text, 2, '0')
    || lpad((floor((LON - 126.0) / 0.1)::int * 20 + floor((LAT - 37.0) / 0.1)::int)::text, 3, '0')
    || lpad((floor((LON - 126.0) / 0.02)::int * 100
             + floor((LAT - 37.0) / 0.02)::int)::text, 5, '0')
"""

_SEED_FEATURES_SQL = f"""
INSERT INTO feature.features (
    feature_id, kind, name, category, coord,
    lifecycle_state, publication_state, quality_state,
    sido_code, sigungu_code, legal_dong_code
)
SELECT
    gen_random_uuid(), CAST(:kind AS text), 'tread10 ' || g,
    CASE WHEN g % 3 = 0 THEN '06020000' ELSE '02000000' END,
    x_extension.ST_SetSRID(x_extension.ST_MakePoint(lon, lat), 4326),
    'active',
    CASE WHEN g % 17 = 0 THEN 'suppressed' ELSE 'published' END,
    'valid',
    {_CODES.replace("LON", "lon").replace("LAT", "lat")}
FROM (
    SELECT g, 126.55 + random() * 0.9 AS lon, 37.05 + random() * 0.9 AS lat
    FROM generate_series(1, :n) AS g
) AS raw
"""

# route: 무작위 걸음 선. 일부는 길게 뻗어 bbox 변을 가로지르고, 일부는 지역 코드가 없다.
_SEED_ROUTES_SQL = """
INSERT INTO feature.feature_route_geometries (feature_id, kind, geom)
SELECT
    f.feature_id, 'route',
    x_extension.ST_Multi(x_extension.ST_SetSRID(x_extension.ST_MakeLine(ARRAY(
        SELECT x_extension.ST_MakePoint(
            x_extension.ST_X(f.coord) + i * CASE WHEN f.rn % 5 = 0 THEN 0.01 ELSE 0.001 END
                * cos(f.rn) + (random() - 0.5) * 0.0005,
            x_extension.ST_Y(f.coord) + i * CASE WHEN f.rn % 5 = 0 THEN 0.01 ELSE 0.001 END
                * sin(f.rn) + (random() - 0.5) * 0.0005
        )
        FROM generate_series(0, 5 + f.rn % 40) AS i
    )), 4326))
FROM (
    SELECT feature_id, coord, row_number() OVER (ORDER BY name) AS rn
    FROM feature.features
    WHERE kind = 'route' AND name LIKE 'tread10 %'
) AS f
"""

_SEED_AREAS_SQL = """
INSERT INTO feature.feature_areas (feature_id, kind, geom, area_kind)
SELECT
    f.feature_id, 'area',
    x_extension.ST_Multi(x_extension.ST_Buffer(f.coord, 0.005 + (f.rn % 7) * 0.01, 24)),
    'park'
FROM (
    SELECT feature_id, coord, row_number() OVER (ORDER BY name) AS rn
    FROM feature.features
    WHERE kind = 'area' AND name LIKE 'tread10 %'
) AS f
"""

# 손으로 만든 경계 모양: (label, kind, wkt, 지역 코드 유무).
_EDGE_SHAPES: tuple[tuple[str, str, str], ...] = (
    # 좁은 bbox(127.0~127.05, 37.4~37.45)의 변에 정확히 닿는 route — 포함(>=, <=).
    ("edge-touch", "route", "LINESTRING(127.0 37.41, 127.05 37.44)"),
    # 변을 1e-7도 넘는 route — 포함이 아니다(float4 캐시 bbox로는 포함으로 보일 수 있다).
    ("edge-over", "route", "LINESTRING(127.0 37.41, 127.0500001 37.44)"),
    # MBR만 겹치는 route — bbox 위쪽을 대각선으로 비켜 간다(정확 교차 거짓).
    ("mbr-fp", "route", "LINESTRING(127.04 37.46, 127.06 37.44)"),
    # 좁은 bbox를 가로지르는 route — 교차 부분 위의 점.
    ("cross", "route", "LINESTRING(126.99 37.425, 127.06 37.425)"),
    # bbox를 둘러싼 구멍 난 area — 정확 교차 거짓.
    (
        "area-hole",
        "area",
        "POLYGON((126.9 37.3,127.2 37.3,127.2 37.6,126.9 37.6,126.9 37.3),"
        "(126.95 37.35,126.95 37.55,127.15 37.55,127.15 37.35,126.95 37.35))",
    ),
)

_BBOXES: tuple[dict[str, float], ...] = (
    {"min_lon": 125.0, "min_lat": 33.0, "max_lon": 132.0, "max_lat": 39.0},
    {"min_lon": 126.8, "min_lat": 37.2, "max_lon": 127.2, "max_lat": 37.6},
    {"min_lon": 127.0, "min_lat": 37.4, "max_lon": 127.05, "max_lat": 37.45},
)

_KIND_FILTERS: tuple[list[str] | None, ...] = (None, ["route"], ["area"], ["place", "route"])


async def _seed(session: AsyncSession) -> None:
    await session.execute(text("SELECT setseed(0.1010)"))
    for kind, n in (("place", 600), ("route", 160), ("area", 24)):
        await session.execute(text(_SEED_FEATURES_SQL), {"kind": kind, "n": n})
    # 지역 코드 없는 route 몇 개(집계에서 빠져야 한다).
    await session.execute(
        text(
            "UPDATE feature.features SET sido_code = NULL, sigungu_code = NULL, "
            "legal_dong_code = NULL WHERE kind = 'route' AND name LIKE 'tread10 %' "
            "AND name LIKE '%7'"
        )
    )
    await session.execute(text(_SEED_ROUTES_SQL))
    await session.execute(text(_SEED_AREAS_SQL))
    for label, kind, wkt in _EDGE_SHAPES:
        feature_id = (
            await session.execute(
                text(
                    """
                    INSERT INTO feature.features (
                        feature_id, kind, name, category, coord,
                        lifecycle_state, publication_state, quality_state,
                        sido_code, sigungu_code, legal_dong_code
                    )
                    VALUES (
                        gen_random_uuid(), CAST(:kind AS text), :name, '02000000', NULL,
                        'active', 'published', 'valid', '11', '11001', '1100100001'
                    )
                    RETURNING feature_id
                    """
                ),
                {"kind": kind, "name": f"tread10 edge {label}"},
            )
        ).scalar_one()
        table = "feature_route_geometries" if kind == "route" else "feature_areas"
        extra = (", area_kind", ", 'park'") if kind == "area" else ("", "")
        await session.execute(
            text(
                f"INSERT INTO feature.{table} (feature_id, kind, geom{extra[0]}) "
                f"VALUES (:fid, CAST(:kind AS text), x_extension.ST_Multi("
                f"x_extension.ST_GeomFromText(:wkt, 4326)){extra[1]})"
            ),
            {"fid": feature_id, "kind": kind, "wkt": wkt},
        )
    await session.flush()


def _normalized(rows: list[Any]) -> dict[str, tuple[int, float, float]]:
    return {
        str(row.cluster_key): (int(row.feature_count), float(row.lon), float(row.lat))
        for row in rows
    }


async def _assert_same(session: AsyncSession, *, label: str) -> int:
    compared = 0
    for unit, code_col in _UNITS.items():
        for bbox in _BBOXES:
            for kinds in _KIND_FILTERS:
                params: dict[str, Any] = {
                    **bbox,
                    "kinds": kinds,
                    "categories": None,
                    "providers": None,
                    "attributes": None,
                    "limit": 2000,
                }
                legacy = _normalized(
                    (await session.execute(text(_legacy_cluster_sql(code_col)), params)).all()
                )
                current = _normalized(
                    (
                        await session.execute(
                            text(feature_repo._CLUSTER_BBOX_SQL_BY_UNIT[unit]), params
                        )
                    ).all()
                )
                # 요청 경로(HashAggregate 설정·point-only 분기 포함)도 같은 답을 내야 한다.
                served = {
                    str(row["cluster_key"]): (
                        int(row["feature_count"]),
                        float(row["lon"]),
                        float(row["lat"]),
                    )
                    for row in await feature_repo.cluster_features_in_bbox(
                        session, **bbox, cluster_unit=unit, kinds=kinds, limit=2000
                    )
                }
                where = f"{label} unit={unit} bbox={bbox} kinds={kinds}"
                for candidate in (current, served):
                    assert {k: v[0] for k, v in candidate.items()} == {
                        k: v[0] for k, v in legacy.items()
                    }, where
                    for key, (_, lon, lat) in legacy.items():
                        assert candidate[key][1] == pytest.approx(lon, abs=1e-9), where
                        assert candidate[key][2] == pytest.approx(lat, abs=1e-9), where
                compared += len(legacy)
    return compared


async def test_cluster_rollup_matches_legacy_sql(migrated_session: AsyncSession) -> None:
    """생성 컬럼 경로의 집계가 종전 SQL과 cluster별 개수·대표점까지 같다."""
    await _seed(migrated_session)
    compared = await _assert_same(migrated_session, label="seed")
    # 비교가 빈 집합끼리의 항진명제가 아니도록 — 전국 bbox 셋 단위만으로도 수십 cluster다.
    assert compared > 100

    # 생성 컬럼은 geom이 바뀌면 같은 문장에서 다시 계산된다 — route 몇 개를 다른 자리로 옮긴 뒤
    # (일부는 좁은 bbox를 가로지르게) 다시 비교한다.
    await migrated_session.execute(
        text(
            """
            UPDATE feature.feature_route_geometries AS g
            SET geom = x_extension.ST_Multi(x_extension.ST_SetSRID(x_extension.ST_MakeLine(
                x_extension.ST_MakePoint(126.98 + (n.rn % 10) * 0.01, 37.39),
                x_extension.ST_MakePoint(127.03 + (n.rn % 10) * 0.01, 37.46)
            ), 4326))
            FROM (
                SELECT f.feature_id, row_number() OVER (ORDER BY f.name) AS rn
                FROM feature.features AS f
                WHERE f.kind = 'route' AND f.name LIKE 'tread10 %'
            ) AS n
            WHERE g.feature_id = n.feature_id AND n.rn % 4 = 0
            """
        )
    )
    await migrated_session.flush()
    await _assert_same(migrated_session, label="after geom update")


async def test_route_marker_columns_follow_geom(migrated_session: AsyncSession) -> None:
    """생성 컬럼이 종전 요청 시 식과 같은 값이다(INSERT·UPDATE 모두)."""
    await _seed(migrated_session)
    mismatches = await migrated_session.scalar(
        text(
            """
            SELECT count(*)
            FROM feature.feature_route_geometries AS g
            WHERE NOT (
                x_extension.ST_Equals(g.marker_point, x_extension.ST_PointOnSurface(g.geom))
                AND g.geom_xmin = x_extension.ST_XMin(g.geom)
                AND g.geom_xmax = x_extension.ST_XMax(g.geom)
                AND g.geom_ymin = x_extension.ST_YMin(g.geom)
                AND g.geom_ymax = x_extension.ST_YMax(g.geom)
            ) IS NOT FALSE
            """
        )
    )
    assert mismatches == 0


async def test_cluster_planner_setting_is_scoped(migrated_session: AsyncSession) -> None:
    """집계가 끈 ``enable_sort``는 그 문장 뒤 직전 값으로 돌아온다(transaction에 새지 않는다)."""
    before = await migrated_session.scalar(text("SELECT current_setting('enable_sort')"))
    await feature_repo.cluster_features_in_bbox(
        migrated_session, **_BBOXES[0], cluster_unit="sido"
    )
    after = await migrated_session.scalar(text("SELECT current_setting('enable_sort')"))
    assert before == "on"
    assert after == before
