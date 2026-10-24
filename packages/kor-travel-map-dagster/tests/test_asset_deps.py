"""transport place asset의 pool과 code location pool 이름공간 정적 회귀 테스트.

주유소·휴게소 **가격** asset과 고속도로 돌발 asset은 ADR-114 결정 7(1단계, migration 419)로
퇴역했다 — 그 현재 상태는 Valkey(`transport_state_*`)가 든다. 그래서 price→place ``deps``
엣지와 돌발 snapshot pool 검사는 대상이 사라졌다. live DB·materialize 없음.
"""

from __future__ import annotations

import pytest

from kortravelmap.dagster.assets import (
    GEO_HEAVY_POOL,
    feature_place_transport_fuel_stations,
)


def test_fuel_station_place_load_is_geo_heavy() -> None:
    """주유소 place(약 1.2만 곳 역지오코딩)는 geo pool로 직렬화한다."""
    assert feature_place_transport_fuel_stations.node_def.pool == GEO_HEAVY_POOL


def test_retired_transport_value_assets_are_gone() -> None:
    """유가·돌발 PG asset이 다시 생기지 않는다(ADR-114 결정 7)."""
    from kortravelmap.dagster import assets

    for name in (
        "feature_price_transport_fuel_stations",
        "feature_price_transport_rest_areas",
        "feature_notice_transport_highway_incidents",
        "HIGHWAY_INCIDENT_SNAPSHOT_POOL",
    ):
        assert not hasattr(assets, name), name


@pytest.mark.filterwarnings(
    "ignore:Parameter `owners` of initializer `SensorDefinition.__init__` is currently in beta"
)
def test_every_pool_in_the_code_location_is_tenant_prefixed() -> None:
    """pool 이름공간은 instance 전역이다 — 공유 plane에서 다른 프로젝트와 슬롯을 나누지 않는다.

    실제로 로드되는 정의(``defs``)의 모든 op/asset pool을 센다. 선언 자리를 소스에서
    찾으면 새 모듈의 pool을 놓친다.
    """

    from kortravelmap.dagster.assets import MAP_POOL_PREFIX
    from kortravelmap.dagster.definitions import defs

    pools: set[str] = set()
    for job in defs.resolve_all_job_defs():
        for node in job.graph.iterate_op_defs():
            if node.pool:
                pools.add(node.pool)
    # 하한: geo-heavy pool을 실제로 봤다.
    assert {GEO_HEAVY_POOL} <= pools, pools
    assert all(pool.startswith(MAP_POOL_PREFIX) for pool in pools), sorted(pools)
