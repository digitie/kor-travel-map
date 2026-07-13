"""price→place asset 의존(parent_feature_id FK) 정적 회귀 테스트.

opinet/krex 가격 asset은 부모 place asset을 dagster 상류 의존(``deps``)으로 선언한다 —
가격 feature의 ``parent_feature_id``가 place feature를 가리키므로 계보·backfill 순서를
보장하기 위함이다. 스케줄은 한도·주기 때문에 분리돼 있고(price 일/place 월), 런타임
정합성은 가격 asset의 parent place co-load(#605)/place 좌표 locator가 담당한다. 이
테스트는 ``deps`` 엣지 멤버십만 정적으로 검사한다 — live DB·materialize 없음.
"""

from __future__ import annotations

import pytest
from dagster import AssetsDefinition

from kortravelmap.dagster.assets import (
    KREX_NOTICE_SNAPSHOT_POOL,
    OPINET_API_POOL,
    feature_notice_krex_traffic_notices,
    feature_place_krex_rest_areas,
    feature_place_opinet_stations,
    feature_price_krex_rest_areas,
    feature_price_opinet_stations,
)

# (price asset, 선행 place asset) — price.parent_feature_id가 place를 가리키는 쌍.
_PRICE_PARENT_PLACE_PAIRS: list[tuple[AssetsDefinition, AssetsDefinition]] = [
    (feature_price_opinet_stations, feature_place_opinet_stations),
    (feature_price_krex_rest_areas, feature_place_krex_rest_areas),
]


@pytest.mark.parametrize(
    ("price_asset", "place_asset"),
    _PRICE_PARENT_PLACE_PAIRS,
    ids=["opinet", "krex"],
)
def test_price_asset_depends_on_parent_place(
    price_asset: AssetsDefinition, place_asset: AssetsDefinition
) -> None:
    """가격 asset은 부모 place asset을 dagster 상류 의존으로 선언한다."""
    assert place_asset.key in price_asset.dependency_keys


def test_opinet_assets_share_serial_api_pool() -> None:
    """schedule/manual 실행 방식과 무관하게 OpiNet 호출 asset은 같은 pool을 쓴다."""
    assert feature_place_opinet_stations.node_def.pool == OPINET_API_POOL
    assert feature_price_opinet_stations.node_def.pool == OPINET_API_POOL


def test_krex_notice_asset_uses_serial_snapshot_pool() -> None:
    """10분 schedule run이 겹쳐도 snapshot load/reconcile 순서가 역전되지 않는다."""
    assert feature_notice_krex_traffic_notices.node_def.pool == KREX_NOTICE_SNAPSHOT_POOL
