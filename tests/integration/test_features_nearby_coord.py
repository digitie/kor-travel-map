"""좌표 기준 주변 feature 조회(``features_nearby``) 통합 테스트 (T-213b).

ADR-012: 입력 좌표를 CTE에서 1회만 5179로 변환하고, 술어는 STORED ``coord_5179``의
부분 GiST 인덱스(``idx_features_coord_5179_gist``)를 쓴다. cursor/정렬/응답 shape는
``features_nearby_poi_cache_target``과 공유하므로(같은 candidates CTE) 본 파일은 좌표
경로 고유부(반경/거리 정렬/cursor/인덱스 사용)에 집중한다.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text

from kortravelmap.infra import feature_repo
from kortravelmap.infra.feature_repo import (  # noqa: PLC2701 - EXPLAIN 대상 raw SQL
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
    lifecycle_state: str = "active",
    publication_state: str = "published",
    quality_state: str = "valid",
) -> None:
    """좌표만 다른 place feature 1건을 심는다 (기본값 = 공개 표면에 보이는 상태).

    T-VN-34(0097)가 ``status``를 물리 삭제했으므로 상태는 3축으로 심는다. 이 파일이
    상태에 거는 요구는 "``feature.public_features``에 뜨는가" 하나뿐이고, 그 조건이
    곧 ``lifecycle='active' AND publication='published' AND quality='valid'``다 —
    옛 ``status='active'``와 같은 뜻이라 기본값을 그렇게 뒀다.
    """
    await session.execute(
        text(
            """
            INSERT INTO feature.features (
                feature_id, kind, name, category, coord,
                lifecycle_state, publication_state, quality_state, updated_at
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
                :lifecycle_state, :publication_state, :quality_state, :updated_at
            )
            """
        ),
        {
            "feature_id": feature_id,
            "name": name,
            "lon": lon,
            "lat": lat,
            "lifecycle_state": lifecycle_state,
            "publication_state": publication_state,
            "quality_state": quality_state,
            "updated_at": _FETCHED,
        },
    )
    await session.flush()


async def _public_ids(session: AsyncSession) -> set[str]:
    """현재 공개 표면(``feature.public_features``)에 실재하는 feature_id 집합."""

    rows = await session.execute(
        text("SELECT feature_id FROM feature.public_features")
    )
    return {str(row[0]) for row in rows}


async def test_features_nearby_filters_active_within_radius(
    migrated_session: AsyncSession,
) -> None:
    await _insert_feature(
        migrated_session, feature_id="near:in", name="가까운 장소",
        lon=126.9782, lat=37.5667,
    )
    # 옛 ``status='inactive'``에 해당하는 자리. 0095 backfill이 그 세대의
    # inactive/deleted/soft-delete를 모두 lifecycle ``retired``로 접었고,
    # ``ck_features_state_tuple``이 retired면 publication을 ``suppressed``로
    # 강제하므로 "더는 공개되지 않는 feature"의 현행 표현은 이 tuple 하나다.
    await _insert_feature(
        migrated_session, feature_id="near:retired", name="비활성",
        lon=126.9783, lat=37.5666,
        lifecycle_state="retired", publication_state="suppressed",
    )
    await _insert_feature(
        migrated_session, feature_id="near:far", name="먼 장소",
        lon=127.12, lat=37.66,
    )

    # 반경 밖 제외와 상태 제외를 구분해 둔다 — retired 건이 빠지는 이유가
    # 거리가 아니라 **공개 표면 부재**임을 먼저 못박는다.
    public_ids = await _public_ids(migrated_session)
    assert "near:in" in public_ids
    assert "near:far" in public_ids
    assert "near:retired" not in public_ids

    page = await feature_repo.features_nearby(
        migrated_session, lon=_LON, lat=_LAT, radius_m=300.0, limit=10
    )

    # 공개 표면 ∩ 반경 안만 (retired 제외, far 제외).
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
    # 반경 술어가 STORED coord_5179를 대상으로 한다.
    assert re.search(r"st_dwithin\(\w+\.coord_5179", plan)
    # feature 좌표를 5179로 **매 행** 변환하는 패턴이 없어야 한다(ADR-012).
    #
    # 여기서 alias를 글자로 박지 않고 ``\w+``로 받는 이유: 이 SQL은 이제
    # ``feature.public_features``를 읽고, planner가 그 view를 펼치면 EXPLAIN에는
    # view 밖의 alias(``f``)가 아니라 view 안쪽 alias(``core``)가 찍힌다. 옛
    # ``st_transform(f.coord`` 단언은 그래서 무엇을 넣어도 통과하는 빈 단언이 됐다 —
    # 지키려던 성질(feature 좌표 per-row 변환 부재)은 alias와 무관하므로 그 성질
    # 자체를 본다.
    assert not re.search(r"st_transform\(\w+\.coord", plan)
