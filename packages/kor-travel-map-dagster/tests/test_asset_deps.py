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
