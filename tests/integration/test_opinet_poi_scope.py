"""``test_opinet_poi_scope`` — opinet POI-타깃 scope DB 조회 (T-RV-04b opinet-3).

``provider_fetchers._opinet_poi_target_bboxes``가 ``ops.poi_cache_targets``의 활성
target(중심+반경)을 실제 PostGIS에서 읽어 bbox로 변환하는지 검증한다. fetcher는
sync(psycopg)라 commit된 데이터만 본다 — async 세션으로 commit 후 조회.

회귀(#304 리뷰): ``external_system``은 provider명이 아니라 외부 호출자(tripmate 등)다.
opinet으로 필터하면 실제 등록 target을 전부 놓친다. active 정의(deleted_at 없음 +
update_enabled + refresh_policy<>'disabled')와 opinet provider_overrides 옵트아웃을 검증.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from geoalchemy2 import WKTElement
from kortravelmap.dagster.provider_fetchers import _opinet_poi_target_bboxes
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.infra.models import PoiCacheTargetRow
from kortravelmap.providers.opinet import (
    OPINET_PROVIDER_NAME,
    OPINET_STATION_DATASET_KEY,
)
from kortravelmap.settings import KorTravelMapSettings

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = pytest.mark.integration

_OPINET_KEY = f"{OPINET_PROVIDER_NAME}:{OPINET_STATION_DATASET_KEY}"
_SEED_SYSTEMS = ("tripmate", "kakao")


def _poi_target(
    target_key: str,
    lon: float,
    lat: float,
    radius_km: float,
    *,
    external_system: str = "tripmate",
) -> PoiCacheTargetRow:
    return PoiCacheTargetRow(
        external_system=external_system,
        target_key=target_key,
        name=f"{external_system} target {target_key}",
        lon=lon,
        lat=lat,
        coord=WKTElement(f"POINT({lon} {lat})", srid=4326),
        coord_key=f"{external_system}:{lon:.6f},{lat:.6f}",
        radius_km=radius_km,
        scope_mode="center_radius",
    )


async def test_opinet_poi_target_bboxes_active_targets_any_external_system(
    migrated_engine: AsyncEngine,
) -> None:
    dsn = migrated_engine.url.render_as_string(hide_password=False)
    settings = KorTravelMapSettings(pg_dsn=dsn)
    try:
        async with AsyncSession(migrated_engine) as session, session.begin():
            # 실제 등록 target은 external_system='tripmate' 등 외부 호출자다 — 포함돼야 함.
            session.add(_poi_target("seoul", 127.0, 37.5, 5.0))
            # 다른 외부 시스템도 동일하게 OpiNet enumeration 대상.
            session.add(_poi_target("busan", 129.07, 35.18, 3.0, external_system="kakao"))

            # 아래는 모두 제외돼야 한다.
            disabled_policy = _poi_target("disabled-policy", 128.0, 36.0, 4.0)
            disabled_policy.refresh_policy = "disabled"
            session.add(disabled_policy)

            update_off = _poi_target("update-off", 128.5, 36.5, 4.0)
            update_off.update_enabled = False
            session.add(update_off)

            deleted = _poi_target("deleted", 127.5, 37.0, 4.0)
            deleted.deleted_at = datetime(2026, 6, 1, tzinfo=UTC)
            session.add(deleted)

            # opinet을 targeted_policy='disabled'로 옵트아웃한 target.
            optout = _poi_target("opinet-optout", 126.5, 37.2, 4.0)
            optout.provider_overrides = {_OPINET_KEY: {"targeted_policy": "disabled"}}
            session.add(optout)

        bboxes = sorted(_opinet_poi_target_bboxes(settings))
        # tripmate seoul + kakao busan, 2건만.
        assert len(bboxes) == 2
        seoul = next(b for b in bboxes if b[0] < 127.0 < b[2])
        assert seoul[1] < 37.5 < seoul[3]
        assert abs((37.5 - seoul[1]) - 5.0 / 111.0) < 1e-6
        assert any(b[0] < 129.07 < b[2] for b in bboxes)  # kakao busan 포함.
    finally:
        async with AsyncSession(migrated_engine) as session, session.begin():
            await session.execute(
                text(
                    "DELETE FROM ops.poi_cache_targets "
                    "WHERE external_system = ANY(:systems)"
                ),
                {"systems": list(_SEED_SYSTEMS)},
            )
