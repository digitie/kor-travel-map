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

import json
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

_SEED_NOTICES_SQL = """
INSERT INTO feature.feature_notices (feature_id, kind, notice_type, valid_end_time)
SELECT
    f.feature_id, 'notice', 'safety',
    CASE WHEN f.rn % 3 = 0 THEN now() - interval '1 day' ELSE now() + interval '1 day' END
FROM (
    SELECT feature_id, row_number() OVER (ORDER BY name) AS rn
    FROM feature.features
    WHERE kind = 'notice' AND name LIKE 'tread10 %'
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
    # 변을 1e-7도 넘는 route — 정확 범위로는 포함이 아니다(교차 부분 위의 점으로 간다).
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
    # 빈 route — 범위가 NULL이라 포함이 아니고, 종전처럼 교차 판정(거짓)으로 빠진다.
    ("empty", "route", "MULTILINESTRING EMPTY"),
)

_BBOXES: tuple[dict[str, float], ...] = (
    {"min_lon": 125.0, "min_lat": 33.0, "max_lon": 132.0, "max_lat": 39.0},
    {"min_lon": 126.8, "min_lat": 37.2, "max_lon": 127.2, "max_lat": 37.6},
    {"min_lon": 127.0, "min_lat": 37.4, "max_lon": 127.05, "max_lat": 37.45},
)

# ``["place"]``는 route/area가 없어 point-only SQL을 탄다(요청 경로 비교가 그 분기도 지나게).
_KIND_FILTERS: tuple[list[str] | None, ...] = (
    None,
    ["route"],
    ["area"],
    ["place", "route"],
    ["place"],
)


async def _seed(session: AsyncSession) -> None:
    await session.execute(text("SELECT setseed(0.1010)"))
    for kind, n in (("place", 600), ("route", 160), ("area", 24), ("notice", 30)):
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
    # notice 몫은 공개 view와 감산 fragment로 읽는다 — 셋 중 하나는 종료됐다(감산되어야 한다).
    await session.execute(text(_SEED_NOTICES_SQL))
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
                    # kind 필터 하나(place+route)에는 분류 필터도 건다(좁은 표 별칭의 분류 술어).
                    "categories": ["06020000"] if kinds == ["place", "route"] else None,
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
                        session,
                        **bbox,
                        cluster_unit=unit,
                        kinds=kinds,
                        categories=params["categories"],
                        limit=2000,
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


_PLANNER_SETTINGS_SQL = (
    "SELECT current_setting('enable_sort') AS enable_sort, "
    "current_setting('plan_cache_mode') AS plan_cache_mode"
)


async def test_cluster_planner_setting_is_scoped(migrated_session: AsyncSession) -> None:
    """집계가 바꾼 ``enable_sort``·``plan_cache_mode``는 그 문장 뒤 직전 값으로 돌아온다."""
    before = (await migrated_session.execute(text(_PLANNER_SETTINGS_SQL))).one()
    await feature_repo.cluster_features_in_bbox(
        migrated_session, **_BBOXES[0], cluster_unit="sido"
    )
    after = (await migrated_session.execute(text(_PLANNER_SETTINGS_SQL))).one()
    assert tuple(before) == ("on", "auto")
    assert tuple(after) == tuple(before)


async def test_cluster_planner_setting_switches_to_hash_aggregate(
    migrated_session: AsyncSession,
) -> None:
    """켜는 문장이 실제로 ``enable_sort``를 끄고, 그 상태의 집계 계획이 HashAggregate다."""
    await _seed(migrated_session)
    prior = (
        await migrated_session.execute(text(feature_repo._CLUSTER_HASH_AGGREGATE_ON_SQL))
    ).one()
    assert (prior.prior_enable_sort, prior.prior_plan_cache_mode) == ("on", "auto")
    assert tuple((await migrated_session.execute(text(_PLANNER_SETTINGS_SQL))).one()) == (
        "off",
        "force_custom_plan",
    )
    plan = (
        await migrated_session.execute(
            text("EXPLAIN (FORMAT JSON) " + feature_repo._CLUSTER_BBOX_SQL_BY_UNIT["sido"]),
            {
                **_BBOXES[0],
                "kinds": None,
                "categories": None,
                "providers": None,
                "attributes": None,
                "limit": 2000,
            },
        )
    ).scalar_one()
    assert '"Strategy": "Hashed"' in json.dumps(plan)
    await migrated_session.execute(
        text(feature_repo._CLUSTER_HASH_AGGREGATE_OFF_SQL),
        {
            "prior_enable_sort": prior.prior_enable_sort,
            "prior_plan_cache_mode": prior.prior_plan_cache_mode,
        },
    )
    assert tuple((await migrated_session.execute(text(_PLANNER_SETTINGS_SQL))).one()) == (
        "on",
        "auto",
    )


# T-READ-12 — asyncpg는 집계 SQL을 연결마다 prepared statement로 재사용한다.
# ``plan_cache_mode=auto``면 6번째 실행부터 generic plan을 고려하는데, 전국 bbox에서 generic
# plan은 bbox 선택도를 기본값으로 보고 좌표 GiST 직렬 scan을 골라 custom plan보다 4–5배
# 느렸다(prod 실측). 같은 연결에서 6번을 넘겨 돌려도 계획이 custom으로 남는지를 **계획만** 본다(시간은 재지 않는다).
_CLUSTER_PREPARED_STATS_SQL = """
SELECT name, generic_plans, custom_plans
FROM pg_prepared_statements
WHERE statement LIKE '%feature.feature_cluster_points AS cluster_point%'
  AND statement LIKE '%cluster_point.sido_code%'
  AND statement NOT LIKE '%pg_prepared_statements%'
  AND statement NOT LIKE 'EXPLAIN%'
"""
_CLUSTER_REUSE_RUNS = 8


def _execute_literal(value: object) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        raise TypeError("bool bind is not expected here")
    if isinstance(value, (int, float)):
        return repr(value)
    raise TypeError(f"unexpected bind value {value!r}")


@pytest.mark.parametrize("kinds", [None, ["place"]], ids=["all-kinds", "point-only"])
async def test_cluster_reused_prepared_statement_stays_custom_plan(
    migrated_session: AsyncSession, kinds: list[str] | None
) -> None:
    """같은 연결에서 sido 집계를 6번 넘게 돌려도 generic plan으로 넘어가지 않는다."""
    await _seed(migrated_session)
    # 시드 뒤 통계가 없으면 planner가 빈 표로 보고 판단이 흔들린다(integration hang 교훈).
    for table in (
        "feature.features",
        "feature.feature_cluster_points",
        "feature.feature_notices",
        "feature.feature_route_geometries",
        "feature.feature_areas",
    ):
        await migrated_session.execute(text(f"ANALYZE {table}"))
    sql = (
        feature_repo._CLUSTER_BBOX_SQL_BY_UNIT["sido"]
        if kinds is None
        else feature_repo._CLUSTER_BBOX_POINT_ONLY_SQL_BY_UNIT["sido"]
    )
    before = {
        row.name: (int(row.generic_plans), int(row.custom_plans))
        for row in (await migrated_session.execute(text(_CLUSTER_PREPARED_STATS_SQL))).all()
    }
    for _ in range(_CLUSTER_REUSE_RUNS):
        await feature_repo.cluster_features_in_bbox(
            migrated_session, **_BBOXES[0], cluster_unit="sido", kinds=kinds
        )
    rows = (await migrated_session.execute(text(_CLUSTER_PREPARED_STATS_SQL))).all()
    statements = {
        row.name: (int(row.generic_plans), int(row.custom_plans))
        for row in rows
    }
    # 이번에 돈 문장은 custom을 _CLUSTER_REUSE_RUNS번 늘린 것 하나다(앞 테스트가 같은 연결에 남긴
    # 문장이 있을 수 있어 차이로 본다).
    grown = {
        name: (generic - before.get(name, (0, 0))[0], custom - before.get(name, (0, 0))[1])
        for name, (generic, custom) in statements.items()
        if (generic, custom) != before.get(name, (0, 0))
    }
    assert len(grown) == 1, grown
    ((name, (generic_delta, custom_delta)),) = grown.items()
    assert generic_delta == 0, grown
    assert custom_delta == _CLUSTER_REUSE_RUNS, grown

    # 그 prepared statement를 코드가 두는 설정으로 한 번 더 EXPLAIN — 계획 모양이 custom 그대로다.
    compiled = text(sql).compile(dialect=migrated_session.get_bind().dialect)
    params: dict[str, object] = {
        **_BBOXES[0],
        "kinds": None if kinds is None else "__kinds__",
        "categories": None,
        "providers": None,
        "attributes": None,
        "limit": 2000,
    }
    order = compiled.positiontup or []
    args = ", ".join(
        "ARRAY['place']::text[]" if params[key] == "__kinds__" else _execute_literal(params[key])
        for key in order
    )
    prior = (
        await migrated_session.execute(text(feature_repo._CLUSTER_HASH_AGGREGATE_ON_SQL))
    ).one()
    plan = (
        await migrated_session.execute(
            text(f'EXPLAIN (FORMAT JSON) EXECUTE "{name}"({args})')
        )
    ).scalar_one()
    await migrated_session.execute(
        text(feature_repo._CLUSTER_HASH_AGGREGATE_OFF_SQL),
        {
            "prior_enable_sort": prior.prior_enable_sort,
            "prior_plan_cache_mode": prior.prior_plan_cache_mode,
        },
    )
    rendered = json.dumps(plan)
    assert '"Strategy": "Hashed"' in rendered
    assert "idx_feature_cluster_points_coord_gist" not in rendered, rendered
    after = {
        row.name: (int(row.generic_plans), int(row.custom_plans))
        for row in (await migrated_session.execute(text(_CLUSTER_PREPARED_STATS_SQL))).all()
    }
    assert after[name][0] == statements[name][0]
