"""T-READ-10 후속 — 좁은 집계 표는 쓰기와 같은 transaction에서 맞는다(동기식).

반영 시점 계약: 동기식(지연 0). ``features`` INSERT/관련 열 UPDATE/DELETE와 route/area geometry
INSERT/``geom`` UPDATE/DELETE 뒤, commit 전 같은 transaction 안에서 이미 집계가 종전 SQL(공개 view와
subtype을 직접 읽는 사본)과 같다. 각 쓰기 뒤에 두 가지를 확인한다.

1. 표 전체가 원천 표에서 새로 유도한 값과 같다(양방향 EXCEPT — 남는 행·빠진 행·틀린 열이 없다).
2. 집계 결과(3단위 × bbox 3 × kind 필터 5)가 종전 SQL과 같다(개수 정확히, 평균 좌표 1e-9도).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text

from tests.integration.test_cluster_rollup_equivalence import _assert_same, _seed

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration

#: 원천 표에서 새로 유도한 좁은 표 — migration 455의 backfill 문장 그 자체(SELECT 부분)다.
#: trigger가 맞춘 표가 backfill이 처음부터 만든 표와 같아야 한다.
_MIGRATION_PATH = (
    Path(__file__).resolve().parents[2] / "alembic" / "versions" / "455_feature_cluster_points.py"
)
_SPEC = importlib.util.spec_from_file_location("migration_455", _MIGRATION_PATH)
assert _SPEC is not None
assert _SPEC.loader is not None
_MIGRATION = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MIGRATION)
_BACKFILL_SELECT = "SELECT" + _MIGRATION._BACKFILL_SQL.split("\nSELECT", 1)[1]
_DERIVED_SQL = f"""
SELECT
    feature_id, kind, category, sido_code, sigungu_code, legal_dong_code,
    x_extension.ST_AsEWKB(coord) AS coord, public,
    x_extension.ST_AsEWKB(marker_point) AS marker_point,
    geom_xmin, geom_xmax, geom_ymin, geom_ymax
FROM ({_BACKFILL_SELECT}) AS derived(
    feature_id, kind, category, sido_code, sigungu_code, legal_dong_code, coord, public,
    marker_point, geom_xmin, geom_xmax, geom_ymin, geom_ymax
)
"""

_STORED_SQL = """
SELECT
    feature_id, kind, category, sido_code, sigungu_code, legal_dong_code,
    x_extension.ST_AsEWKB(coord) AS coord, public,
    x_extension.ST_AsEWKB(marker_point) AS marker_point,
    geom_xmin, geom_xmax, geom_ymin, geom_ymax
FROM feature.feature_cluster_points
"""


async def _assert_table_matches_sources(session: AsyncSession, label: str) -> None:
    for left, right, side in (
        (_DERIVED_SQL, _STORED_SQL, "missing or stale"),
        (_STORED_SQL, _DERIVED_SQL, "extra or stale"),
    ):
        diff = (
            await session.execute(text(f"SELECT count(*) FROM ({left} EXCEPT {right}) AS d"))
        ).scalar_one()
        assert diff == 0, f"{label}: feature_cluster_points {side} rows = {diff}"


async def _check(session: AsyncSession, label: str) -> None:
    await session.flush()
    await _assert_table_matches_sources(session, label)
    await _assert_same(session, label=label)


async def _one(session: AsyncSession, sql: str) -> str:
    return str((await session.execute(text(sql))).scalar_one())


async def test_cluster_points_follow_every_write_in_the_same_transaction(
    migrated_session: AsyncSession,
) -> None:
    """쓰기 종류마다 commit 전에 이미 좁은 표와 집계가 원천과 같다(지연 0)."""
    await _seed(migrated_session)
    await _check(migrated_session, "seed")

    place = await _one(
        migrated_session,
        "SELECT feature_id FROM feature.features WHERE kind = 'place' "
        "AND name LIKE 'tread10 %' AND publication_state = 'published' ORDER BY name LIMIT 1",
    )
    route = await _one(
        migrated_session,
        "SELECT feature_id FROM feature.features WHERE kind = 'route' "
        "AND name LIKE 'tread10 %' AND sido_code IS NOT NULL "
        "AND publication_state = 'published' ORDER BY name LIMIT 1",
    )
    area = await _one(
        migrated_session,
        "SELECT feature_id FROM feature.features WHERE kind = 'area' "
        "AND name LIKE 'tread10 %' AND publication_state = 'published' ORDER BY name LIMIT 1",
    )

    steps: tuple[tuple[str, str], ...] = (
        # 좌표를 좁은 bbox 안으로 옮긴다(지역 코드는 그대로 — 코드와 좌표는 독립 열이다).
        (
            "place coord moves",
            f"UPDATE feature.features SET coord = x_extension.ST_SetSRID("
            f"x_extension.ST_MakePoint(127.02, 37.42), 4326) WHERE feature_id = '{place}'",
        ),
        ("place region code changes", f"UPDATE feature.features SET sido_code = '99', "
         f"sigungu_code = '99001', legal_dong_code = '9900100001' WHERE feature_id = '{place}'"),
        ("place category changes", f"UPDATE feature.features SET category = '06020000' "
         f"WHERE feature_id = '{place}'"),
        ("place suppressed", f"UPDATE feature.features SET publication_state = 'suppressed' "
         f"WHERE feature_id = '{place}'"),
        ("place republished", f"UPDATE feature.features SET publication_state = 'published' "
         f"WHERE feature_id = '{place}'"),
        ("route state retired", f"UPDATE feature.features SET lifecycle_state = 'retired', "
         f"publication_state = 'suppressed' WHERE feature_id = '{route}'"),
        ("route state restored", f"UPDATE feature.features SET lifecycle_state = 'active', "
         f"publication_state = 'published' WHERE feature_id = '{route}'"),
        ("place quality quarantined", f"UPDATE feature.features SET quality_state = 'quarantined' "
         f"WHERE feature_id = '{place}'"),
        ("place quality valid", f"UPDATE feature.features SET quality_state = 'valid' "
         f"WHERE feature_id = '{place}'"),
        ("place coord cleared", f"UPDATE feature.features SET coord = NULL "
         f"WHERE feature_id = '{place}'"),
        ("place coord restored", f"UPDATE feature.features SET coord = x_extension.ST_SetSRID("
         f"x_extension.ST_MakePoint(127.03, 37.43), 4326) WHERE feature_id = '{place}'"),
        (
            "route geometry crosses the narrow bbox",
            "UPDATE feature.feature_route_geometries SET geom = x_extension.ST_Multi("
            "x_extension.ST_GeomFromText('LINESTRING(126.99 37.43, 127.06 37.44)', 4326)) "
            f"WHERE feature_id = '{route}'",
        ),
        (
            "area geometry moves inside the narrow bbox",
            "UPDATE feature.feature_areas SET geom = x_extension.ST_Multi(x_extension.ST_Buffer("
            "x_extension.ST_SetSRID(x_extension.ST_MakePoint(127.025, 37.425), 4326), 0.01, 8)) "
            f"WHERE feature_id = '{area}'",
        ),
        ("area geometry row deleted", f"DELETE FROM feature.feature_areas "
         f"WHERE feature_id = '{area}'"),
        (
            "area geometry row inserted again",
            "INSERT INTO feature.feature_areas (feature_id, kind, geom, area_kind) VALUES ("
            f"'{area}', 'area', x_extension.ST_Multi(x_extension.ST_Buffer("
            "x_extension.ST_SetSRID(x_extension.ST_MakePoint(127.04, 37.44), 4326), 0.02, 8)), "
            "'park')",
        ),
        ("route geometry row deleted", f"DELETE FROM feature.feature_route_geometries "
         f"WHERE feature_id = '{route}'"),
        (
            "route geometry row inserted again",
            "INSERT INTO feature.feature_route_geometries (feature_id, kind, geom) VALUES ("
            f"'{route}', 'route', x_extension.ST_Multi(x_extension.ST_GeomFromText("
            "'LINESTRING(127.01 37.41, 127.02 37.42)', 4326)))",
        ),
        ("route feature deleted (cascade)", f"DELETE FROM feature.features "
         f"WHERE feature_id = '{route}'"),
        ("unrelated column update is a no-op", f"UPDATE feature.features SET name = 'renamed' "
         f"WHERE feature_id = '{place}'"),
    )
    for label, sql in steps:
        await migrated_session.execute(text(sql))
        await _check(migrated_session, label)


async def test_unrelated_feature_update_does_not_touch_cluster_point(
    migrated_session: AsyncSession,
) -> None:
    """집계와 무관한 열만 바뀌면 좁은 표 행을 다시 쓰지 않는다(적재 쓰기 비용)."""
    await _seed(migrated_session)
    place = await _one(
        migrated_session,
        "SELECT feature_id FROM feature.features WHERE kind = 'place' "
        "AND name LIKE 'tread10 %' ORDER BY name LIMIT 1",
    )
    before = await _one(
        migrated_session,
        f"SELECT ctid::text FROM feature.feature_cluster_points WHERE feature_id = '{place}'",
    )
    await migrated_session.execute(
        text(f"UPDATE feature.features SET name = name || ' x' WHERE feature_id = '{place}'")
    )
    after = await _one(
        migrated_session,
        f"SELECT ctid::text FROM feature.feature_cluster_points WHERE feature_id = '{place}'",
    )
    assert after == before


async def test_cluster_point_trigger_fires_after_subtype_sync(
    migrated_session: AsyncSession,
) -> None:
    """잠금 순서 고정 — 상태 전이는 subtype 행(public_ready 동기화) 다음에 좁은 표 행을 잡아야 한다.

    geometry 쓰기는 subtype 행 → 좁은 표 행 순서다. 같은 시점 AFTER trigger는 이름순(C)으로
    도므로, 좁은 표 trigger가 ``trg_features_sync_subtype_public_ready``보다 뒤에 정렬돼야 두 경로의
    잠금 순서가 같다(적대 리뷰 2026-11-19 — 앞서면 deadlock).
    """
    names = list(
        (
            await migrated_session.execute(
                text(
                    "SELECT tgname FROM pg_trigger "
                    "WHERE tgrelid = 'feature.features'::regclass AND NOT tgisinternal "
                    "AND tgname IN ('trg_features_sync_subtype_public_ready', "
                    "'trg_features_zz_cluster_point') ORDER BY tgname COLLATE \"C\""
                )
            )
        ).scalars()
    )
    assert names == ["trg_features_sync_subtype_public_ready", "trg_features_zz_cluster_point"]
