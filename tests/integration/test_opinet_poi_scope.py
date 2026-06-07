"""``test_opinet_poi_scope`` — opinet POI-타깃 scope DB 조회 (T-RV-04b opinet-3).

``provider_fetchers._opinet_poi_target_bboxes``가 ``ops.poi_cache_targets``의
opinet 활성 target(중심+반경)을 실제 PostGIS에서 읽어 bbox로 변환하는지 검증한다.
fetcher는 sync(psycopg)라 commit된 데이터만 본다 — async 세션으로 commit 후 조회.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from geoalchemy2 import WKTElement
from krtour.map_dagster.provider_fetchers import _opinet_poi_target_bboxes
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from krtour.map.infra.models import PoiCacheTargetRow
from krtour.map.settings import KrtourMapSettings

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = pytest.mark.integration


def _opinet_target(
    target_key: str, lon: float, lat: float, radius_km: float
) -> PoiCacheTargetRow:
    return PoiCacheTargetRow(
        external_system="opinet",
        target_key=target_key,
        name=f"opinet target {target_key}",
        lon=lon,
        lat=lat,
        coord=WKTElement(f"POINT({lon} {lat})", srid=4326),
        coord_key=f"{lon:.6f},{lat:.6f}",
        radius_km=radius_km,
        scope_mode="center_radius",
    )


async def test_opinet_poi_target_bboxes_reads_active_opinet_targets(
    migrated_engine: AsyncEngine,
) -> None:
    dsn = migrated_engine.url.render_as_string(hide_password=False)
    settings = KrtourMapSettings(pg_dsn=dsn)
    try:
        async with AsyncSession(migrated_engine) as session, session.begin():
            session.add(_opinet_target("seoul", 127.0, 37.5, 5.0))
            session.add(_opinet_target("busan", 129.07, 35.18, 3.0))
            # 비활성/타 시스템/삭제는 제외돼야 한다.
            disabled = _opinet_target("disabled", 128.0, 36.0, 4.0)
            disabled.update_enabled = False
            session.add(disabled)
            other = _opinet_target("other", 126.5, 37.0, 4.0)
            other.external_system = "kakao"
            session.add(other)

        bboxes = _opinet_target_bboxes_sorted(settings)
        # opinet 활성 2건만.
        assert len(bboxes) == 2
        # seoul bbox가 127.0/37.5 중심을 감싼다.
        seoul = next(b for b in bboxes if b[0] < 127.0 < b[2])
        assert seoul[1] < 37.5 < seoul[3]
        assert abs((37.5 - seoul[1]) - 5.0 / 111.0) < 1e-6
    finally:
        async with AsyncSession(migrated_engine) as session, session.begin():
            await session.execute(
                text(
                    "DELETE FROM ops.poi_cache_targets "
                    "WHERE external_system IN ('opinet','kakao')"
                )
            )


def _opinet_target_bboxes_sorted(
    settings: KrtourMapSettings,
) -> list[tuple[float, float, float, float]]:
    return sorted(_opinet_poi_target_bboxes(settings))
