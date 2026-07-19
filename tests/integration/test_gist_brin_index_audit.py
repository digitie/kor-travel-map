"""T-VN-18 — 자동 full GiST 제거 + partial 유지 + write-cost 실측 (F-8 / D-12-3).

- head(0061)에서 자동 full GiST 3개는 사라지고 공개 술어 partial GiST 3개만 남는다.
- 공개 bbox/nearest-weather 조회의 planner가 partial GiST를 선택한다(EXPLAIN 회귀).
- weather source-record 지원 index(T-VN-17 이월)가 존재한다.
- write-cost 실측(§8.3 필수): full 포함(6 GiST) vs partial만(3 GiST) INSERT 처리량.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import make_url

from alembic import command
from kortravelmap.infra.db import make_async_engine, normalize_async_dsn

pytestmark = pytest.mark.integration

# 서울 근처 bbox — 공개 조회 EXPLAIN용.
_BBOX = (126.9, 37.5, 127.1, 37.7)

_FULL_GIST = ("idx_features_coord", "idx_features_coord_5179", "idx_features_geom")
_PARTIAL_GIST = (
    "idx_features_coord_gist",
    "idx_features_coord_5179_gist",
    "idx_features_geom_gist",
)


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
    """head(0061): partial GiST 3개 유지, 자동 full GiST 3개 제거."""
    names = await _index_names(migrated_session, "features")
    for partial in _PARTIAL_GIST:
        assert partial in names, f"partial GiST {partial} must remain"
    for full in _FULL_GIST:
        assert full not in names, f"auto full GiST {full} must be dropped"


async def test_weather_source_record_support_index_exists(
    migrated_session: Any,
) -> None:
    """T-VN-17 이월: weather source-record FK 지원 index가 존재한다(price 미러)."""
    names = await _index_names(migrated_session, "feature_weather_values")
    assert "idx_weather_values_source_record" in names


async def _seed_public_points(session: Any, count: int, prefix: str) -> None:
    # 전국(124.5~131.5 lon, 33.5~39.5 lat)에 고르게 뿌려 Seoul bbox/50km 반경이
    # 선택적(few match)이 되게 한다 → GiST bbox/KNN 스캔이 명확히 최적.
    await session.execute(
        text(
            """
            INSERT INTO feature.features (
                feature_id, kind, name, category, coord, status, updated_at
            )
            SELECT
                :prefix || g, 'place', 'p', '06020000',
                x_extension.ST_SetSRID(
                    x_extension.ST_MakePoint(
                        124.5 + (g % 700) * 0.01, 33.5 + ((g / 700) % 600) * 0.01
                    ),
                    4326
                ),
                'active', now()
            FROM generate_series(1, :count) AS g
            """
        ),
        {"prefix": prefix, "count": count},
    )
    await session.flush()
    # planner가 GiST 선택도를 알도록 통계 갱신.
    await session.execute(text("ANALYZE feature.features"))


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


# ── write-cost 실측 (§8.3 필수) — 전용 DB에서 6 GiST vs 3 partial 비교 ──


def _run_alembic(dsn: str, revision: str) -> None:
    root = Path(__file__).resolve().parents[2]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    config.set_main_option("sqlalchemy.url", dsn)
    command.upgrade(config, revision)


_INSERT_BATCH_SQL = """
INSERT INTO feature.features (
    feature_id, kind, name, category, coord, status, updated_at
)
SELECT
    :prefix || g, 'place', 'p', '06020000',
    x_extension.ST_SetSRID(
        x_extension.ST_MakePoint(
            124.5 + (g % 7000) * 0.001, 33.5 + (g % 5000) * 0.001
        ),
        4326
    ),
    'active', now()
FROM generate_series(1, :count) AS g
"""


async def _time_insert(engine: Any, prefix: str, count: int) -> float:
    async with engine.begin() as conn:
        start = time.perf_counter()
        await conn.execute(
            text(_INSERT_BATCH_SQL), {"prefix": prefix, "count": count}
        )
        return time.perf_counter() - start


async def test_dropping_full_gist_reduces_write_cost(pg_container: Any) -> None:
    """§8.3 필수 실측: 자동 full GiST 3개 제거가 geometry INSERT write-cost를 낮춘다.

    head(0061)는 이미 full을 제거했으므로, 실측을 위해 full 3개를 재생성해
    before(6 GiST)를 만들고, drop해 after(3 partial)를 만들어 같은 batch INSERT
    처리 시간을 비교한다. point insert는 coord/coord_5179 축을 색인한다.
    """
    admin_dsn = normalize_async_dsn(pg_container.get_connection_url())
    database = f"gist_writecost_{uuid4().hex}"
    target_dsn = make_url(admin_dsn).set(database=database).render_as_string(
        hide_password=False
    )
    admin_engine = make_async_engine(admin_dsn)
    async with admin_engine.connect() as connection:
        autocommit = await connection.execution_options(isolation_level="AUTOCOMMIT")
        await autocommit.execute(text(f'CREATE DATABASE "{database}"'))

    engine = None
    try:
        await asyncio.to_thread(_run_alembic, target_dsn, "head")
        engine = make_async_engine(target_dsn)

        # 기준 데이터(색인에 내용을 채운다).
        await _time_insert(engine, "base:", 20_000)

        # before-state: 자동 full GiST 3개 재생성 → 6 GiST.
        async with engine.begin() as conn:
            for name, col in (
                ("idx_features_coord", "coord"),
                ("idx_features_coord_5179", "coord_5179"),
                ("idx_features_geom", "geom"),
            ):
                await conn.execute(
                    text(
                        f"CREATE INDEX {name} ON feature.features "
                        f"USING GIST ({col})"
                    )
                )
        # warm-up 후 측정(캐시 편차 완화).
        await _time_insert(engine, "warm6:", 5_000)
        six_gist = await _time_insert(engine, "six:", 40_000)

        # after-state: 자동 full 3개 제거 → 3 partial.
        async with engine.begin() as conn:
            for name in _FULL_GIST:
                await conn.execute(text(f"DROP INDEX feature.{name}"))
        await _time_insert(engine, "warm3:", 5_000)
        three_gist = await _time_insert(engine, "three:", 40_000)

        ratio = six_gist / three_gist if three_gist else float("inf")
        print(
            f"\n[T-VN-18 write-cost] 40k INSERT: "
            f"6-GiST={six_gist:.3f}s  3-partial-GiST={three_gist:.3f}s  "
            f"ratio(6/3)={ratio:.2f}x"
        )
        # 색인 3개를 덜 유지하므로 partial-only가 더 빠르다(약간의 노이즈 허용).
        assert three_gist < six_gist * 1.02, (
            f"3-partial INSERT ({three_gist:.3f}s) should not exceed "
            f"6-GiST ({six_gist:.3f}s)"
        )
    finally:
        if engine is not None:
            await engine.dispose()
        async with admin_engine.connect() as connection:
            autocommit = await connection.execution_options(isolation_level="AUTOCOMMIT")
            await autocommit.execute(
                text(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)')
            )
        await admin_engine.dispose()
