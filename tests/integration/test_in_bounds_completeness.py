"""T-VN-14 — in-bounds 지도 완결성 + exact 공간 술어 (testcontainers).

F-8 / ADR-073 D-9-3 검증:

1. **include_geometry는 serialization-only**: ``features_in_bbox``의 후보 집합
   (feature_id membership)이 ``include_geometry`` 값과 **무관하게 동일**하다. 플래그는
   route/area geometry를 응답 payload에 직렬화할지만 바꾼다. (이전에는 geometry
   변형만 geom 후보를 넣어 결과집합이 달라졌다 — EXPLAIN 재현 2220→2221행.)
2. **exact ST_Intersects**: route/area는 ``&&`` MBR prefilter만으로 생기는 false
   positive를 exact ``ST_Intersects``로 제거한다 — MBR은 겹치지만 실제 geometry가
   envelope와 교차하지 않는 route는 두 변형 모두에서 제외된다.

기능 회귀는 최소 seed만, planner 회귀는 geometry-only 대표 분포를 사용한다.
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


async def _ins_point(
    session: AsyncSession,
    *,
    feature_id: str,
    lon: float,
    lat: float,
    sido_code: str | None = None,
    sigungu_code: str | None = None,
    legal_dong_code: str | None = None,
) -> None:
    await session.execute(
        text(
            """
            INSERT INTO feature.features (
                feature_id, kind, name, category, coord, status, updated_at,
                sido_code, sigungu_code, legal_dong_code
            )
            VALUES (
                :fid, 'place', :fid, '06020000',
                x_extension.ST_SetSRID(
                    x_extension.ST_MakePoint(
                        CAST(:lon AS double precision), CAST(:lat AS double precision)
                    ), 4326
                ),
                'active', :ts, :sido_code, :sigungu_code, :legal_dong_code
            )
            """
        ),
        {
            "fid": feature_id,
            "lon": lon,
            "lat": lat,
            "ts": _NOW,
            "sido_code": sido_code,
            "sigungu_code": sigungu_code,
            "legal_dong_code": legal_dong_code,
        },
    )


async def _ins_geom(
    session: AsyncSession,
    *,
    feature_id: str,
    kind: str,
    wkt: str,
    coord_lon: float | None = None,
    coord_lat: float | None = None,
    sido_code: str | None = None,
    sigungu_code: str | None = None,
    legal_dong_code: str | None = None,
) -> None:
    """route/area feature — exact geom 후보와 coord 우회 방지 검증용."""
    await session.execute(
        text(
            """
            INSERT INTO feature.features (
                feature_id, kind, name, category, coord, geom, status, updated_at,
                sido_code, sigungu_code, legal_dong_code
            )
            VALUES (
                :fid, :kind, :fid, '02000000',
                CASE
                  WHEN CAST(:coord_lon AS double precision) IS NULL THEN NULL
                  ELSE x_extension.ST_SetSRID(
                    x_extension.ST_MakePoint(
                      CAST(:coord_lon AS double precision),
                      CAST(:coord_lat AS double precision)
                    ),
                    4326
                  )
                END,
                x_extension.ST_SetSRID(x_extension.ST_GeomFromText(:wkt), 4326),
                'active', :ts, :sido_code, :sigungu_code, :legal_dong_code
            )
            """
        ),
        {
            "fid": feature_id,
            "kind": kind,
            "wkt": wkt,
            "coord_lon": coord_lon,
            "coord_lat": coord_lat,
            "ts": _NOW,
            "sido_code": sido_code,
            "sigungu_code": sigungu_code,
            "legal_dong_code": legal_dong_code,
        },
    )


async def _seed(session: AsyncSession) -> set[str]:
    """7 feature를 넣고 bbox 안 기대 membership을 돌려준다."""
    # 후보 (bbox 안):
    region = {
        "sido_code": "11",
        "sigungu_code": "11110",
        "legal_dong_code": "1111010100",
    }
    await _ins_point(
        session, feature_id="ib:place-in", lon=127.05, lat=37.05, **region
    )
    # bbox를 가로지르는 route (coord 없음, geom && + ST_Intersects 모두 참).
    await _ins_geom(
        session,
        feature_id="ib:route-cross",
        kind="route",
        wkt="LINESTRING(126.9 37.05, 127.2 37.05)",
        **region,
    )
    # bbox와 겹치는 area polygon (coord 없음).
    await _ins_geom(
        session,
        feature_id="ib:area-in",
        kind="area",
        wkt="POLYGON((127.04 37.04, 127.06 37.04, 127.06 37.06, 127.04 37.06, 127.04 37.04))",
        **region,
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
        **region,
    )
    # 실제 geometry는 bbox를 둘러싼 hole 바깥에 있어 교차하지 않지만 geometric
    # centroid(coord)는 bbox 안이다. route/area가 coord arm으로 우회하면 포함되는
    # 적대 fixture다.
    await _ins_geom(
        session,
        feature_id="ib:area-centroid-fp",
        kind="area",
        wkt=(
            "POLYGON((126.8 36.8,127.3 36.8,127.3 37.3,126.8 37.3,126.8 36.8),"
            "(126.9 36.9,126.9 37.2,127.2 37.2,127.2 36.9,126.9 36.9))"
        ),
        coord_lon=127.05,
        coord_lat=37.05,
        **region,
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
    assert "ib:area-centroid-fp" not in light_ids
    assert "ib:area-centroid-fp" not in geom_ids
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


async def test_clusters_share_items_exact_spatial_universe(
    migrated_session: AsyncSession,
) -> None:
    """cluster도 coord-only가 아니라 items와 같은 exact 공간 후보를 집계한다."""
    expected = await _seed(migrated_session)

    items = await feature_repo.features_in_bbox(
        migrated_session, **_BBOX, include_geometry=False, price_stale_hide_days=None
    )
    clusters = await feature_repo.cluster_features_in_bbox(
        migrated_session, **_BBOX, cluster_unit="sido"
    )

    assert {row["feature_id"] for row in items} == expected
    assert len(clusters) == 1
    assert clusters[0]["cluster_key"] == "11"
    assert clusters[0]["feature_count"] == len(expected)
    # geometry 후보는 bbox 교차 부분 위에서 대표 좌표를 만들므로 cluster marker도
    # 요청 bbox 안에 남는다.
    assert _BBOX["min_lon"] <= clusters[0]["lon"] <= _BBOX["max_lon"]
    assert _BBOX["min_lat"] <= clusters[0]["lat"] <= _BBOX["max_lat"]


async def test_cross_boundary_geometry_uses_stored_canonical_code_once(
    migrated_session: AsyncSession,
) -> None:
    """경계를 가로지르는 geometry는 저장 canonical code 하나에만 귀속된다.

    두 feature 모두 같은 bbox를 가로지르지만 저장된 행정코드는 서로 다르다. geometry
    교차 영역을 기준으로 양쪽 cluster에 복제하지 않고, 선택 단위의 저장 코드에 정확히
    한 번씩 집계해 cluster 합계와 code 보강된 items 수를 같게 유지한다.
    """
    await _ins_geom(
        migrated_session,
        feature_id="ib:route-stored-seoul",
        kind="route",
        wkt="LINESTRING(126.9 37.03, 127.2 37.03)",
        sido_code="11",
        sigungu_code="11110",
        legal_dong_code="1111010100",
    )
    await _ins_geom(
        migrated_session,
        feature_id="ib:area-stored-busan",
        kind="area",
        wkt=(
            "POLYGON((126.95 36.95,127.15 36.95,127.15 37.15,"
            "126.95 37.15,126.95 36.95))"
        ),
        sido_code="26",
        sigungu_code="26110",
        legal_dong_code="2611010100",
    )
    await migrated_session.flush()

    items = await feature_repo.features_in_bbox(
        migrated_session,
        **_BBOX,
        include_geometry=False,
        price_stale_hide_days=None,
    )
    assert {row["feature_id"] for row in items} == {
        "ib:route-stored-seoul",
        "ib:area-stored-busan",
    }

    expected_by_unit = {
        "sido": {"11": 1, "26": 1},
        "sigungu": {"11110": 1, "26110": 1},
        "eupmyeondong": {"1111010100": 1, "2611010100": 1},
    }
    for unit, expected in expected_by_unit.items():
        clusters = await feature_repo.cluster_features_in_bbox(
            migrated_session,
            **_BBOX,
            cluster_unit=unit,
        )
        actual = {
            row["cluster_key"]: row["feature_count"] for row in clusters
        }
        assert actual == expected
        assert sum(actual.values()) == len(items)
