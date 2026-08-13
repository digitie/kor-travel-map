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


# ── write-cost 실측 (§8.3 필수) — 전용 DB에서 6 GiST vs 3 partial 비교 ──


def _run_alembic(dsn: str, revision: str) -> None:
    root = Path(__file__).resolve().parents[2]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    config.set_main_option("sqlalchemy.url", dsn)
    command.upgrade(config, revision)


# T-VN-34: write-cost 측정의 전제는 "삽입되는 행이 partial GiST에도 실제로 들어간다"는
# 것이다. 0096의 partial predicate가 (lifecycle active, publication published, quality
# valid)이므로 그 조합이 아니면 partial 쪽 유지비가 0이 되어 6-GiST/3-GiST 비교가
# 자기 자신과의 비교로 퇴화한다. 옛 ``status='active'``가 뜻하던 것이 바로 이
# 조합이라(0095 backfill) 세 축을 그대로 명시한다.
_INSERT_BATCH_SQL = """
INSERT INTO feature.features (
    feature_id, kind, name, category, coord,
    lifecycle_state, publication_state, quality_state, updated_at
)
SELECT
    :prefix || g, 'place', 'p', '06020000',
    x_extension.ST_SetSRID(
        x_extension.ST_MakePoint(
            124.5 + (g % 7000) * 0.001, 33.5 + (g % 5000) * 0.001
        ),
        4326
    ),
    'active', 'published', 'valid', now()
FROM generate_series(1, :count) AS g
"""


async def _time_insert(engine: Any, prefix: str, count: int) -> float:
    async with engine.begin() as conn:
        start = time.perf_counter()
        await conn.execute(
            text(_INSERT_BATCH_SQL), {"prefix": prefix, "count": count}
        )
        return time.perf_counter() - start


async def _min_time_insert(
    engine: Any, prefix: str, count: int, *, rounds: int
) -> float:
    """같은 batch를 여러 번 재고 **최솟값**을 돌려준다.

    벽시계 측정에서 외부 부하는 시간을 늘리기만 하고 줄이지는 못한다. 그래서 최솟값이
    "간섭 없는 비용"에 가장 가까운 추정치다 — 평균과 중앙값은 스파이크를 그대로 실어
    나른다.

    앞 판은 두 상태를 각각 40k INSERT **한 번씩** 재고 2% 마진으로 비교했다. 두 측정이
    시간상 떨어져 있어 뒤쪽 측정에 부하가 겹치면 결과가 뒤집힌다. 2026-08-11 실측:
    같은 트리·같은 명령으로 부하가 높을 때 이 단언에서 red, 낮을 때 green이었고 단독
    실행 3회는 ratio 1.10x/1.04x/1.04x로 전부 통과했다. batch 크기는 40k 그대로 두고
    회차만 3회로 늘려 그 뒤집힘을 없앤다 — 20k로 줄여도 스파이크는 걸러지지만 효과
    크기가 함께 줄어(실측 ratio 1.02x) 임계에 붙는다. 색인 유지 비용 차이는 행 수에
    비례하므로 batch를 얇게 만들면 안 된다.
    """

    return min(
        [await _time_insert(engine, f"{prefix}{index}:", count) for index in range(rounds)]
    )


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

    # 0095부터 fresh DB는 배포와 같은 principal graph를 먼저 갖춰야 upgrade가 선다
    # (restricted migrator가 state/audit owner membership을 스스로 부여하지 않는지
    # 0095가 검사한다). 자기 DB를 따로 만드는 이 테스트도 conftest와 같은 공유
    # helper를 쓴다 — 여기서만 다른 경로로 올리면 측정 대상 schema가 배포와 달라진다.
    from tests.integration._tvn34_migration_bootstrap import (
        alembic_schema_owner_role,
        bootstrapped_migrator_dsn,
    )

    engine = None
    try:
        migrator_dsn = await bootstrapped_migrator_dsn(target_dsn)
        with alembic_schema_owner_role():
            await asyncio.to_thread(_run_alembic, migrator_dsn, "head")
        engine = make_async_engine(target_dsn)

        # 기준 데이터(색인에 내용을 채운다).
        await _time_insert(engine, "base:", 20_000)

        # before-state: 자동 full GiST 2개 재생성 → 4 GiST(T-VN-35 이후 core는
        # coord 2축만 색인한다 — geom 축은 subtype 소유).
        async with engine.begin() as conn:
            for name, col in (
                ("idx_features_coord", "coord"),
                ("idx_features_coord_5179", "coord_5179"),
            ):
                await conn.execute(
                    text(
                        f"CREATE INDEX {name} ON feature.features "
                        f"USING GIST ({col})"
                    )
                )
        # warm-up 후 측정(캐시 편차 완화).
        await _time_insert(engine, "warm6:", 5_000)
        six_gist = await _min_time_insert(engine, "six:", 40_000, rounds=3)

        # after-state: 자동 full 제거 → partial만 남는다.
        async with engine.begin() as conn:
            for name in _FULL_GIST:
                await conn.execute(text(f"DROP INDEX feature.{name}"))
        await _time_insert(engine, "warm3:", 5_000)
        three_gist = await _min_time_insert(engine, "three:", 40_000, rounds=3)

        ratio = six_gist / three_gist if three_gist else float("inf")
        print(
            f"\n[T-VN-18 write-cost] 40k INSERT 최소값(3회): "
            f"6-GiST={six_gist:.3f}s  3-partial-GiST={three_gist:.3f}s  "
            f"ratio(6/3)={ratio:.2f}x"
        )
        # 색인 3개를 덜 유지하므로 partial-only가 더 빠르다(약간의 노이즈 허용).
        assert three_gist < six_gist * 1.02, (
            f"partial-only INSERT ({three_gist:.3f}s) should not exceed "
            f"full+partial ({six_gist:.3f}s)"
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
