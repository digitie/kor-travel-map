"""T-VN-14 — in-bounds 지도 완결성 + exact 공간 술어 (testcontainers).

F-8 / ADR-073 D-9-3 검증:

1. **include_geometry는 serialization-only**: ``features_in_bbox``의 후보 집합
   (feature_id membership)이 ``include_geometry`` 값과 **무관하게 동일**하다. 플래그는
   route/area geometry를 응답 payload에 직렬화할지만 바꾼다. (이전에는 geometry
   변형만 geom 후보를 넣어 결과집합이 달라졌다 — EXPLAIN 재현 2220→2221행.)
2. **exact ST_Intersects**: route/area는 ``&&`` MBR prefilter만으로 생기는 false
   positive를 exact ``ST_Intersects``로 제거한다 — MBR은 겹치지만 실제 geometry가
   envelope와 교차하지 않는 route는 두 변형 모두에서 제외된다.

최소 seed(6 feature)만 사용한다(디스크 제약).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text

from kortravelmap.infra import feature_repo

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration

_KST = timezone(timedelta(hours=9))
_NOW = datetime(2026, 7, 19, 12, 0, tzinfo=_KST)

# 작은 조회 bbox (경도 127.0~127.1, 위도 37.0~37.1).
_BBOX = {"min_lon": 127.0, "min_lat": 37.0, "max_lon": 127.1, "max_lat": 37.1}


async def _ins_point(session: AsyncSession, *, feature_id: str, lon: float, lat: float) -> None:
    await session.execute(
        text(
            """
            INSERT INTO feature.features (
                feature_id, kind, name, category, coord, status, updated_at
            )
            VALUES (
                :fid, 'place', :fid, '06020000',
                x_extension.ST_SetSRID(
                    x_extension.ST_MakePoint(
                        CAST(:lon AS double precision), CAST(:lat AS double precision)
                    ), 4326
                ),
                'active', :ts
            )
            """
        ),
        {"fid": feature_id, "lon": lon, "lat": lat, "ts": _NOW},
    )


async def _ins_geom(
    session: AsyncSession, *, feature_id: str, kind: str, wkt: str
) -> None:
    """coord 없는 route/area feature (geom만) — geom 후보 경로 검증용."""
    await session.execute(
        text(
            """
            INSERT INTO feature.features (
                feature_id, kind, name, category, geom, status, updated_at
            )
            VALUES (
                :fid, :kind, :fid, '02000000',
                x_extension.ST_SetSRID(x_extension.ST_GeomFromText(:wkt), 4326),
                'active', :ts
            )
            """
        ),
        {"fid": feature_id, "kind": kind, "wkt": wkt, "ts": _NOW},
    )


async def _seed(session: AsyncSession) -> set[str]:
    """6 feature를 넣고 bbox 안 기대 membership을 돌려준다."""
    # 후보 (bbox 안):
    await _ins_point(session, feature_id="ib:place-in", lon=127.05, lat=37.05)
    # bbox를 가로지르는 route (coord 없음, geom && + ST_Intersects 모두 참).
    await _ins_geom(
        session,
        feature_id="ib:route-cross",
        kind="route",
        wkt="LINESTRING(126.9 37.05, 127.2 37.05)",
    )
    # bbox와 겹치는 area polygon (coord 없음).
    await _ins_geom(
        session,
        feature_id="ib:area-in",
        kind="area",
        wkt="POLYGON((127.04 37.04, 127.06 37.04, 127.06 37.06, 127.04 37.06, 127.04 37.04))",
    )

    # 비후보 (bbox 밖):
    await _ins_point(session, feature_id="ib:place-out", lon=128.0, lat=38.0)
    # MBR false positive: geom의 bounding box는 bbox와 겹치지만(&&=참) 실제 선분은
    # envelope 위쪽을 지나 교차하지 않는다(ST_Intersects=거짓). exact 술어가
    # 이 route를 두 변형 모두에서 제외해야 한다.
    await _ins_geom(
        session,
        feature_id="ib:route-mbr-fp",
        kind="route",
        wkt="LINESTRING(127.05 37.2, 127.2 37.05)",
    )
    # 완전히 밖에 있는 route (대조군).
    await _ins_geom(
        session,
        feature_id="ib:route-out",
        kind="route",
        wkt="LINESTRING(128.0 38.0, 128.2 38.0)",
    )
    await session.flush()
    return {"ib:place-in", "ib:route-cross", "ib:area-in"}


async def test_mbr_false_positive_is_excluded_by_exact_intersects(
    migrated_session: AsyncSession,
) -> None:
    """&& MBR만 겹치는 route는 exact ST_Intersects로 두 변형 모두에서 제외된다 (F-8)."""
    expected = await _seed(migrated_session)

    light = await feature_repo.features_in_bbox(
        migrated_session, **_BBOX, include_geometry=False, price_stale_hide_days=None
    )
    geom = await feature_repo.features_in_bbox(
        migrated_session, **_BBOX, include_geometry=True, price_stale_hide_days=None
    )

    light_ids = {r["feature_id"] for r in light}
    geom_ids = {r["feature_id"] for r in geom}

    # MBR false positive route는 어느 변형에도 없다.
    assert "ib:route-mbr-fp" not in light_ids
    assert "ib:route-mbr-fp" not in geom_ids
    assert light_ids == expected
    assert geom_ids == expected


async def test_include_geometry_is_serialization_only(
    migrated_session: AsyncSession,
) -> None:
    """include_geometry는 membership이 아니라 geometry 직렬화만 바꾼다 (F-8/ADR-073 D-9-3).

    이전 버그(2220→2221): geometry 변형만 route/area geom을 후보에 넣어 결과집합이
    커졌다. 이제 두 변형의 feature_id 집합이 **정확히 같고**, 차이는 payload(route/
    area geometry 직렬화 유무)뿐이다.
    """
    await _seed(migrated_session)

    light = await feature_repo.features_in_bbox(
        migrated_session, **_BBOX, include_geometry=False, price_stale_hide_days=None
    )
    geom = await feature_repo.features_in_bbox(
        migrated_session, **_BBOX, include_geometry=True, price_stale_hide_days=None
    )

    # (1) membership 안정: 같은 feature_id 집합.
    assert {r["feature_id"] for r in light} == {r["feature_id"] for r in geom}

    # (2) payload만 차이: 경량 변형은 geometry 컬럼을 SELECT하지 않는다.
    assert all("geometry" not in r for r in light)

    # (3) geometry 변형은 route/area에 GeoJSON을 직렬화한다.
    geom_by_id = {r["feature_id"]: r for r in geom}
    assert geom_by_id["ib:route-cross"]["geometry"] is not None
    assert geom_by_id["ib:route-cross"]["geometry"]["type"] == "LineString"
    assert geom_by_id["ib:area-in"]["geometry"] is not None
    assert geom_by_id["ib:area-in"]["geometry"]["type"] in {"Polygon", "MultiPolygon"}
    # point feature는 geometry가 없다(coord만).
    assert geom_by_id["ib:place-in"]["geometry"] is None
