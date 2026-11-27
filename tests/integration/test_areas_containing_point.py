"""점을 덮는 공개 area 조회(``areas_containing_point``) 통합 테스트.

``GET /v1/features/{feature_id}/containing-areas``·``GET /v1/features/containing-areas``의 SQL이다.
``contained-features``(면 → 점)의 역방향(점 → 면). ADR-012: 공간 술어는 4326 그대로
``&&`` + ``ST_Covers``이고 ``ST_Transform``이 없으며, subtype 표의 부분 GiST
(``idx_feature_areas_geom_gist``, ``WHERE public_ready``)를 탄다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

import pytest
from sqlalchemy import text

from kortravelmap.infra import feature_repo
from kortravelmap.infra.feature_repo import (  # noqa: PLC2701 - EXPLAIN 대상 raw SQL
    _AREAS_CONTAINING_POINT_SQL,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration

_KST = timezone(timedelta(hours=9))
_FETCHED = datetime(2026, 11, 27, 12, 0, tzinfo=_KST)

# 큰 면(국립공원) ⊃ 작은 면(명승). 바깥 점·경계 점·안쪽 점을 함께 본다.
_PARK = "POLYGON((126.90 37.60, 127.10 37.60, 127.10 37.80, 126.90 37.80, 126.90 37.60))"
_SCENIC = "POLYGON((126.95 37.65, 127.00 37.65, 127.00 37.70, 126.95 37.70, 126.95 37.65))"


@dataclass(frozen=True)
class _GRec:
    source_id: str
    name: str
    geom_wkt: str
    raw: dict[str, Any]


async def _load_areas(session: AsyncSession) -> dict[str, str]:
    from kortravelmap.providers.knps import knps_geometry_records_to_bundles

    records = [
        _GRec(
            "cont-10932",
            "북한산",
            _PARK,
            {"WDPA_PID": "cont-10932", "ORIG_NAME": "북한산", "DESIG_ENG": "National Park"},
        ),
        _GRec(
            "cont-scenic",
            "우이령",
            _SCENIC,
            {"WDPA_PID": "cont-scenic", "ORIG_NAME": "우이령", "DESIG_ENG": "Scenic Site",
             "MARINE": "0"},
        ),
    ]
    bundles = await knps_geometry_records_to_bundles(
        records, dataset_key="knps_protected_areas", fetched_at=_FETCHED
    )
    assert len(bundles) == 2
    for bundle in bundles:
        await feature_repo.load_bundle(session, bundle)
    await session.flush()
    rows = (
        await session.execute(
            text(
                "SELECT f.name, CAST(f.feature_id AS text) AS fid "
                "FROM feature.public_features f WHERE f.name IN "
                "('북한산 국립공원', '우이령')"
            )
        )
    ).mappings().all()
    ids = {row["name"]: row["fid"] for row in rows}
    assert set(ids) == {"북한산 국립공원", "우이령"}, "적재한 면이 공개 표면에 떠야 한다"
    return ids


async def test_point_inside_both_returns_smallest_first(migrated_session: AsyncSession) -> None:
    ids = await _load_areas(migrated_session)

    rows = await feature_repo.areas_containing_point(
        migrated_session, lon=126.97, lat=37.67
    )

    assert [row["name"] for row in rows] == ["우이령", "북한산 국립공원"]
    assert [row["area_kind"] for row in rows] == ["protected_area", "national_park"]
    assert rows[1]["category"] == "01020101"
    assert rows[0]["area_square_meters"] < rows[1]["area_square_meters"]
    assert str(rows[1]["feature_id"]) == ids["북한산 국립공원"]


async def test_kind_filter_exclusion_boundary_and_outside(migrated_session: AsyncSession) -> None:
    ids = await _load_areas(migrated_session)

    only_parks = await feature_repo.areas_containing_point(
        migrated_session, lon=126.97, lat=37.67, area_kinds=["national_park"]
    )
    assert [row["name"] for row in only_parks] == ["북한산 국립공원"]

    # 자기 자신 제외(area의 대표점으로 물을 때).
    without_park = await feature_repo.areas_containing_point(
        migrated_session, lon=126.97, lat=37.67, exclude_feature_id=ids["북한산 국립공원"]
    )
    assert [row["name"] for row in without_park] == ["우이령"]

    # 경계 위 점도 "안"이다(ST_Covers).
    on_edge = await feature_repo.areas_containing_point(
        migrated_session, lon=126.90, lat=37.70
    )
    assert [row["name"] for row in on_edge] == ["북한산 국립공원"]

    # 면 밖(은평 시가지 쪽) — 버퍼 시절엔 "북한산 안"이던 자리.
    outside = await feature_repo.areas_containing_point(
        migrated_session, lon=126.92, lat=37.59
    )
    assert outside == []

    with pytest.raises(ValueError, match="limit"):
        await feature_repo.areas_containing_point(
            migrated_session, lon=126.97, lat=37.67, limit=0
        )


async def test_retired_area_is_not_returned(migrated_session: AsyncSession) -> None:
    ids = await _load_areas(migrated_session)
    await migrated_session.execute(
        text(
            "UPDATE feature.features SET lifecycle_state = 'retired', "
            "publication_state = 'suppressed' WHERE feature_id = CAST(:fid AS uuid)"
        ),
        {"fid": ids["우이령"]},
    )

    rows = await feature_repo.areas_containing_point(
        migrated_session, lon=126.97, lat=37.67
    )

    assert [row["name"] for row in rows] == ["북한산 국립공원"]


async def test_plan_uses_area_gist_without_transform(migrated_session: AsyncSession) -> None:
    """부분 GiST(``idx_feature_areas_geom_gist``)를 타고 술어에 ``st_transform``이 없다(ADR-012)."""
    await _load_areas(migrated_session)
    await migrated_session.execute(text("SET LOCAL enable_seqscan = off"))
    plan_rows = (
        await migrated_session.execute(
            text("EXPLAIN (VERBOSE) " + _AREAS_CONTAINING_POINT_SQL),
            {
                "lon": 126.97,
                "lat": 37.67,
                "area_kinds": None,
                "exclude_feature_id": None,
                "limit": 20,
            },
        )
    ).scalars().all()
    plan = "\n".join(str(row) for row in plan_rows).lower()
    assert "idx_feature_areas_geom_gist" in plan
    assert "st_transform" not in plan
