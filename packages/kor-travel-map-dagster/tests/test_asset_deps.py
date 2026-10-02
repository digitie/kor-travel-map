"""price→place asset 의존(parent_feature_id FK) 정적 회귀 테스트.

주유소·휴게소 가격 asset은 부모 place asset을 dagster 상류 의존(``deps``)으로 선언한다 —
가격 feature의 ``parent_feature_id``가 place feature를 가리키므로 계보·backfill 순서를
보장하기 위함이다. 스케줄은 한도·주기 때문에 분리돼 있고(price 일/place 월), 런타임
정합성은 가격 asset의 parent place co-load(#605)/place 좌표 locator가 담당한다. 이
테스트는 ``deps`` 엣지 멤버십만 정적으로 검사한다 — live DB·materialize 없음.
"""

from __future__ import annotations

import pytest
from dagster import AssetsDefinition

from kortravelmap.dagster.assets import (
    GEO_HEAVY_POOL,
    HIGHWAY_INCIDENT_SNAPSHOT_POOL,
    feature_notice_transport_highway_incidents,
    feature_place_transport_fuel_stations,
    feature_place_transport_rest_areas,
    feature_price_transport_fuel_stations,
    feature_price_transport_rest_areas,
)

# (price asset, 선행 place asset) — price.parent_feature_id가 place를 가리키는 쌍.
_PRICE_PARENT_PLACE_PAIRS: list[tuple[AssetsDefinition, AssetsDefinition]] = [
    (feature_price_transport_fuel_stations, feature_place_transport_fuel_stations),
    (feature_price_transport_rest_areas, feature_place_transport_rest_areas),
]


@pytest.mark.parametrize(
    ("price_asset", "place_asset"),
    _PRICE_PARENT_PLACE_PAIRS,
    ids=["fuel", "rest_area"],
)
def test_price_asset_depends_on_parent_place(
    price_asset: AssetsDefinition, place_asset: AssetsDefinition
) -> None:
    """가격 asset은 부모 place asset을 dagster 상류 의존으로 선언한다."""
    assert place_asset.key in price_asset.dependency_keys


def test_fuel_station_place_load_is_geo_heavy_and_price_is_freshness_bound() -> None:
    """주유소 place(약 1.2만 곳 역지오코딩)는 geo pool로 직렬화한다.

    price는 freshness job(``max_runtime_seconds``)이라 몇 시간짜리 월간 적재 뒤에 줄 세우지
    않는다 — OpiNet 쿼터 pool은 ADR-106으로 사라졌다(transport가 상류를 진다).
    """
    assert feature_place_transport_fuel_stations.node_def.pool == GEO_HEAVY_POOL
    assert feature_price_transport_fuel_stations.node_def.pool is None


def test_highway_incident_asset_uses_serial_snapshot_pool() -> None:
    """10분 schedule run이 겹쳐도 snapshot load/reconcile 순서가 역전되지 않는다."""
    pool = feature_notice_transport_highway_incidents.node_def.pool
    assert pool == HIGHWAY_INCIDENT_SNAPSHOT_POOL


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
    # 하한: 돌발 snapshot·geo-heavy 두 pool을 실제로 봤다.
    assert {GEO_HEAVY_POOL, HIGHWAY_INCIDENT_SNAPSHOT_POOL} <= pools, pools
    assert all(pool.startswith(MAP_POOL_PREFIX) for pool in pools), sorted(pools)
