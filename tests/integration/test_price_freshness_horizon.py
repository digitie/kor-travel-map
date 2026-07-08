"""price 신선도 지평선 통합 테스트 (PostGIS).

OpiNet 시군 윈도 로테이션(≈4일 1주기) 밖으로 밀린 관측이 현재가처럼 보이지 않도록,
``KOR_TRAVEL_MAP_PRICE_STALE_HIDE_DAYS``(기본 4일)보다 오래된 price 관측은

- 지도 bbox의 ``price_summary``(마커 라벨)와
- ``build_price_card``의 ``current``

에서 제외된다(이력·값은 보존). ``asof`` 과거 시점 질의와 ``None``(지평선 off)은
기존 동작을 유지한다.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest

from kortravelmap.dto._enums import FeatureKind, PriceDomain
from kortravelmap.dto.price import PriceValue
from kortravelmap.infra import feature_repo, price_repo
from kortravelmap.providers.krex import rest_areas_to_bundles

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration

_KST = timezone(timedelta(hours=9))


def _price_value(
    feature_id: str, *, product_key: str, observed_at: datetime, price: int
) -> PriceValue:
    return PriceValue(
        feature_id=feature_id,
        provider="python-opinet-api",
        price_domain=PriceDomain.OPINET_GAS_STATION,
        product_key=product_key,
        product_name=None,
        source_product_key=None,
        source_product_name=None,
        observed_at=observed_at,
        value_number=Decimal(price),
        unit="KRW/L",
        normalization_version="test-v1",
        payload={},
        collected_at=observed_at,
        source_record_key=None,
    )


class _RestArea:
    """`KrexRestAreaItem` Protocol — 좌표 보유 anchor place."""

    name = "지평선휴게소"
    route_name = "서해안고속도로"
    direction = "부산방향"
    lat = 36.10
    lon = 126.90
    phone_number = None


async def test_stale_price_hidden_from_current_but_kept_in_history(
    migrated_session: AsyncSession,
) -> None:
    now = datetime.now(tz=_KST)
    bundles = await rest_areas_to_bundles([_RestArea()], fetched_at=now)
    await feature_repo.load_bundles(migrated_session, bundles)
    feature_id = bundles[0].feature.feature_id

    fresh_at = now - timedelta(hours=1)
    stale_at = now - timedelta(days=10)
    await price_repo.load_price_values(
        migrated_session,
        [
            _price_value(
                feature_id, product_key="gasoline", observed_at=fresh_at, price=1700
            ),
            _price_value(
                feature_id, product_key="diesel", observed_at=stale_at, price=1500
            ),
        ],
    )
    await migrated_session.flush()

    # 기본 지평선(4일): current에는 fresh만, history에는 둘 다.
    card = await price_repo.build_price_card(
        migrated_session, feature_id=feature_id
    )
    assert [p.product_key for p in card.current] == ["gasoline"]
    assert {p.product_key for p in card.history} == {"gasoline", "diesel"}
    # is_stale 기본 임계는 지평선(4일)에서 파생 — 지평선 안 관측이 있으면 fresh.
    # (로테이션 주기 안에서 정상 갱신 중인 주유소가 stale로 보이지 않게.)
    assert card.is_stale is False

    # 지평선 off(None): 옛 관측도 current로 복귀.
    card_all = await price_repo.build_price_card(
        migrated_session, feature_id=feature_id, stale_hide_days=None
    )
    assert [p.product_key for p in card_all.current] == ["gasoline", "diesel"]

    # asof 과거 시점 질의에는 지평선을 적용하지 않는다.
    card_asof = await price_repo.build_price_card(
        migrated_session,
        feature_id=feature_id,
        asof=now - timedelta(days=9),
    )
    assert [p.product_key for p in card_asof.current] == ["diesel"]


async def test_stale_only_feature_is_stale_and_current_empty(
    migrated_session: AsyncSession,
) -> None:
    """지평선 밖 관측만 있으면 current가 비고 is_stale=True — 두 신호가 일치한다."""
    now = datetime.now(tz=_KST)

    class _StaleArea(_RestArea):
        name = "묵은가격휴게소"
        lat = 36.30
        lon = 127.10

    bundles = await rest_areas_to_bundles([_StaleArea()], fetched_at=now)
    await feature_repo.load_bundles(migrated_session, bundles)
    feature_id = bundles[0].feature.feature_id
    await price_repo.load_price_values(
        migrated_session,
        [
            _price_value(
                feature_id,
                product_key="gasoline",
                observed_at=now - timedelta(days=10),
                price=1650,
            )
        ],
    )
    await migrated_session.flush()

    card = await price_repo.build_price_card(migrated_session, feature_id=feature_id)
    assert card.current == []
    assert card.latest_at == now - timedelta(days=10)
    assert card.is_stale is True
    # 이력은 보존된다.
    assert [p.product_key for p in card.history] == ["gasoline"]


async def test_stale_price_excluded_from_bbox_price_summary(
    migrated_session: AsyncSession,
) -> None:
    now = datetime.now(tz=_KST)
    bundles = await rest_areas_to_bundles([_RestArea()], fetched_at=now)
    await feature_repo.load_bundles(migrated_session, bundles)
    feature = bundles[0].feature
    assert feature.coord is not None
    # bbox price_summary는 kind='price' feature에만 붙는다 — place anchor를
    # 그대로 쓰지 않고 같은 좌표의 price-kind row를 직접 upsert한다.
    price_feature = feature.model_copy(
        update={
            "feature_id": f"{feature.feature_id}_pz",
            "kind": FeatureKind.PRICE,
            "detail": None,  # price kind는 place detail을 갖지 않는다.
        }
    )
    await feature_repo.upsert_feature(migrated_session, price_feature)

    await price_repo.load_price_values(
        migrated_session,
        [
            _price_value(
                price_feature.feature_id,
                product_key="gasoline",
                observed_at=now - timedelta(hours=1),
                price=1700,
            ),
            _price_value(
                price_feature.feature_id,
                product_key="diesel",
                observed_at=now - timedelta(days=10),
                price=1500,
            ),
        ],
    )
    await migrated_session.flush()

    lon, lat = float(feature.coord.lon), float(feature.coord.lat)
    bbox = {
        "min_lon": lon - 0.05,
        "min_lat": lat - 0.05,
        "max_lon": lon + 0.05,
        "max_lat": lat + 0.05,
    }

    rows = await feature_repo.features_in_bbox(
        migrated_session, kinds=["price"], **bbox
    )
    hit = next(r for r in rows if r["feature_id"] == price_feature.feature_id)
    products = [p["product_key"] for p in (hit["price_summary"] or [])]
    assert products == ["gasoline"]  # 10일 묵은 diesel은 마커 라벨에서 제외.

    rows_all = await feature_repo.features_in_bbox(
        migrated_session, kinds=["price"], price_stale_hide_days=None, **bbox
    )
    hit_all = next(
        r for r in rows_all if r["feature_id"] == price_feature.feature_id
    )
    products_all = [p["product_key"] for p in (hit_all["price_summary"] or [])]
    assert products_all == ["gasoline", "diesel"]
