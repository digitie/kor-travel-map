"""좌표 기준 주변 feature 조회(``features_nearby``) 통합 테스트 (T-213b).

ADR-012: 입력 좌표를 CTE에서 1회만 5179로 변환하고, 술어는 STORED ``coord_5179``의
부분 GiST 인덱스(``idx_features_coord_5179_gist``)를 쓴다. cursor/정렬/응답 shape는
``features_nearby_poi_cache_target``과 공유하므로(같은 candidates CTE) 본 파일은 좌표
경로 고유부(반경/거리 정렬/cursor/인덱스 사용)에 집중한다.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text

from krtour.map.infra import feature_repo
from krtour.map.infra.feature_repo import (  # noqa: PLC2701 - EXPLAIN 대상 raw SQL
    _NEARBY_COORD_DISTANCE_SQL,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration

_KST = timezone(timedelta(hours=9))
_FETCHED = datetime(2026, 6, 3, 12, 0, tzinfo=_KST)
# 서울시청 근처.
_LON = 126.978
_LAT = 37.5665


async def _insert_feature(
    session: AsyncSession,
    *,
    feature_id: str,
    name: str,
    lon: float,
    lat: float,
    status: str = "active",
) -> None:
    await session.execute(
        text(
            """
            INSERT INTO feature.features (
                feature_id, kind, name, category, coord, status, updated_at
            )
            VALUES (
                :feature_id, 'place', :name, '06020000',
                x_extension.ST_SetSRID(
                    x_extension.ST_MakePoint(
                        CAST(:lon AS double precision),
                        CAST(:lat AS double precision)
                    ),
                    4326
                ),
                :status, :updated_at
            )
            """
        ),
        {
            "feature_id": feature_id,
            "name": name,
            "lon": lon,
            "lat": lat,
            "status": status,
            "updated_at": _FETCHED,
        },
    )
    await session.flush()


async def test_features_nearby_filters_active_within_radius(
    migrated_session: AsyncSession,
) -> None:
    await _insert_feature(
        migrated_session, feature_id="near:in", name="가까운 장소",
        lon=126.9782, lat=37.5667,
    )
    await _insert_feature(
        migrated_session, feature_id="near:inactive", name="비활성",
        lon=126.9783, lat=37.5666, status="inactive",
    )
    await _insert_feature(
        migrated_session, feature_id="near:far", name="먼 장소",
        lon=127.12, lat=37.66,
    )

    page = await feature_repo.features_nearby(
        migrated_session, lon=_LON, lat=_LAT, radius_m=300.0, limit=10
    )

    # active + 반경 안만 (inactive 제외, far 제외).
    assert [item.feature_id for item in page.items] == ["near:in"]
    assert page.items[0].distance_m < 50
    assert page.next_cursor is None


async def test_features_nearby_cursor_pages_distance_order(
    migrated_session: AsyncSession,
) -> None:
    await _insert_feature(
        migrated_session, feature_id="p:1", name="A", lon=126.9781, lat=37.5666
    )
    await _insert_feature(
        migrated_session, feature_id="p:2", name="B", lon=126.9790, lat=37.5670
    )
    await _insert_feature(
        migrated_session, feature_id="p:3", name="C", lon=126.9800, lat=37.5680
    )

    seen: list[str] = []
    cursor: str | None = None
    for _ in range(5):
        page = await feature_repo.features_nearby(
            migrated_session, lon=_LON, lat=_LAT, radius_m=2000.0,
            limit=1, cursor=cursor,
        )
        seen.extend(item.feature_id for item in page.items)
        cursor = page.next_cursor
        if cursor is None:
            break

    # 거리 오름차순으로 3건 모두 한 번씩.
    assert seen == ["p:1", "p:2", "p:3"]
    assert cursor is None


async def test_features_nearby_invalid_inputs(
    migrated_session: AsyncSession,
) -> None:
    with pytest.raises(ValueError, match="radius_m"):
        await feature_repo.features_nearby(
            migrated_session, lon=_LON, lat=_LAT, radius_m=0
        )
    with pytest.raises(ValueError, match="sort"):
        await feature_repo.features_nearby(
            migrated_session, lon=_LON, lat=_LAT, radius_m=100, sort="bogus"
        )
    with pytest.raises(ValueError, match="invalid nearby cursor"):
        await feature_repo.features_nearby(
            migrated_session, lon=_LON, lat=_LAT, radius_m=100, cursor="not-base64",
        )


async def test_features_nearby_predicate_uses_stored_coord_5179(
    migrated_session: AsyncSession,
) -> None:
    """ADR-012: 반경 술어가 STORED ``coord_5179``를 대상으로 하고, feature 좌표를
    **매 행 변환하지 않는다**(입력 좌표만 origin CTE에서 1회 변환).

    소량 테스트 데이터에서는 planner가 GiST 인덱스 대신 seqscan을 고를 수 있어
    특정 인덱스 이름은 단언하지 않는다(by-target nearby와 동일한 candidates CTE).
    대신 술어 대상 컬럼과 per-row transform 부재를 검증한다.
    """
    await _insert_feature(
        migrated_session, feature_id="idx:1", name="X", lon=126.9782, lat=37.5667
    )
    rows = (
        await migrated_session.execute(
            text("EXPLAIN (VERBOSE) " + _NEARBY_COORD_DISTANCE_SQL),
            {
                "lon": _LON,
                "lat": _LAT,
                "radius_m": 500.0,
                "kinds": None,
                "categories": None,
                "statuses": ["active"],
                "providers": None,
                "limit_plus_one": 11,
                "cursor_distance_m": None,
                "cursor_name": None,
                "cursor_last_updated_at": None,
                "cursor_feature_id": None,
            },
        )
    ).scalars().all()
    plan = "\n".join(str(r) for r in rows).lower()
    # 술어/거리 계산이 STORED coord_5179를 대상으로 한다.
    assert "coord_5179" in plan
    # feature 좌표(f.coord)를 5179로 매 행 변환하는 패턴이 없어야 한다(ADR-012).
    assert "st_transform(f.coord" not in plan
    assert "st_transform(features.coord" not in plan
