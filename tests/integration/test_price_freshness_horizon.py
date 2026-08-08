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
from sqlalchemy import text

from kortravelmap.core.ids import make_payload_hash, make_source_record_key
from kortravelmap.dto import SourceRecord
from kortravelmap.dto._enums import FeatureKind, PriceDomain
from kortravelmap.dto.price import PriceValue
from kortravelmap.infra import feature_repo, price_repo
from kortravelmap.providers.krex import rest_areas_to_bundles
from tests.integration.perf_gate import assert_uses_index, explain_plan

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration

_KST = timezone(timedelta(hours=9))

_DATASET_KEYS = {
    "python-opinet-api": "opinet_gas_station_prices",
    "python-krex-api": "krex_rest_area_prices",
}


def _price_value(
    feature_id: str,
    *,
    product_key: str,
    observed_at: datetime,
    price: int,
    provider: str = "python-opinet-api",
    price_domain: PriceDomain = PriceDomain.OPINET_GAS_STATION,
) -> PriceValue:
    return PriceValue(
        feature_id=feature_id,
        provider=provider,
        price_domain=price_domain,
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


async def _append_price_response(
    session: AsyncSession,
    values: list[PriceValue],
    *,
    provider: str = "python-opinet-api",
) -> None:
    """T-VN-38의 source response lineage를 포함해 test price facts를 적재한다."""

    dataset_key = _DATASET_KEYS[provider]
    dataset_id = await session.scalar(
        text(
            """
            SELECT provider_dataset_id
            FROM provider_sync.provider_datasets
            WHERE provider = :provider AND dataset_key = :dataset_key
            """
        ),
        {"provider": provider, "dataset_key": dataset_key},
    )
    assert dataset_id is not None
    raw_data = {
        "values": [
            {
                "feature_id": value.feature_id,
                "product_key": value.product_key,
                "observed_at": value.observed_at.isoformat(),
                "value_number": str(value.value_number),
            }
            for value in values
        ]
    }
    payload_hash = make_payload_hash(raw_data)
    source_entity_id = f"test-price:{payload_hash[:20]}"
    await price_repo.load_price_values(
        session,
        values,
        provider_dataset_id=int(dataset_id),
        source_record=SourceRecord(
            provider=provider,
            dataset_key=dataset_key,
            source_entity_type="price_response",
            source_entity_id=source_entity_id,
            raw_payload_hash=payload_hash,
            raw_data=raw_data,
            fetched_at=max(value.observed_at for value in values) + timedelta(minutes=1),
            source_record_key=make_source_record_key(
                provider=provider,
                dataset_key=dataset_key,
                source_entity_type="price_response",
                source_entity_id=source_entity_id,
                raw_payload_hash=payload_hash,
            ),
        ),
    )


async def test_stale_price_hidden_from_current_but_kept_in_history(
    migrated_session: AsyncSession,
) -> None:
    now = datetime.now(tz=_KST)
    bundles = await rest_areas_to_bundles([_RestArea()], fetched_at=now)
    await feature_repo.load_bundles(migrated_session, bundles)
    feature_id = bundles[0].feature.feature_id

    fresh_at = now - timedelta(hours=1)
    stale_at = now - timedelta(days=10)
    await _append_price_response(
        migrated_session,
        [
            _price_value(
                feature_id, product_key="gasoline", observed_at=fresh_at, price=1700
            )
        ],
    )
    await _append_price_response(
        migrated_session,
        [
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

    # snapshot은 observed/known time을 모두 명시하고 current 지평선을 적용하지 않는다.
    card_asof = await price_repo.build_price_snapshot(
        migrated_session,
        feature_id=feature_id,
        observed_at=now - timedelta(days=9),
        known_at=now,
    )
    assert [p.product_key for p in card_asof.current] == ["diesel"]


async def test_price_card_series_queries_use_identity_indexes(
    migrated_session: AsyncSession,
) -> None:
    """current/history index가 각 series 정렬 access path에 적격인지 고정한다."""
    now = datetime.now(tz=_KST)
    bundles = await rest_areas_to_bundles([_RestArea()], fetched_at=now)
    await feature_repo.load_bundles(migrated_session, bundles)
    feature_id = bundles[0].feature.feature_id
    await _append_price_response(
        migrated_session,
        [
            _price_value(
                feature_id,
                product_key="gasoline",
                observed_at=now - timedelta(minutes=minute),
                price=1700 + minute,
            )
            for minute in range(1, 61)
        ],
    )
    await migrated_session.flush()
    await migrated_session.execute(
        text("ANALYZE feature.feature_price_values")
    )

    current_plan = await explain_plan(
        migrated_session,
        price_repo._CURRENT_SQL,  # noqa: SLF001
        {
            "feature_id": feature_id,
            "observed_at": None,
            "known_at": None,
            "stale_hide_days": None,
        },
        planner_default=False,
        pre_statements=("SET LOCAL enable_sort = off",),
    )
    assert_uses_index(current_plan, "uq_price_value_identity")

    history_plan = await explain_plan(
        migrated_session,
        price_repo._HISTORY_SQL,  # noqa: SLF001
        {
            "feature_id": feature_id,
            "observed_at": None,
            "known_at": None,
            "limit": 100,
        },
        planner_default=False,
    )
    assert_uses_index(
        history_plan,
        "idx_price_values_feature_observed_identity",
    )


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
    await _append_price_response(
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

    await _append_price_response(
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
    await _append_price_response(
        migrated_session,
        [
            _price_value(
                price_feature.feature_id,
                product_key="gasoline",
                observed_at=now - timedelta(minutes=30),
                price=1710,
                provider="python-krex-api",
                price_domain=PriceDomain.REST_AREA_FUEL,
            )
        ],
        provider="python-krex-api",
    )
    await migrated_session.flush()

    lon, lat = float(feature.coord.lon), float(feature.coord.lat)
    bbox = {
        "min_lon": lon - 0.05,
        "min_lat": lat - 0.05,
        "max_lon": lon + 0.05,
        "max_lat": lat + 0.05,
    }

    card = await price_repo.build_price_card(
        migrated_session, feature_id=price_feature.feature_id
    )
    expected_fresh_identities = {
        ("python-krex-api", "rest_area_fuel", "gasoline"),
        ("python-opinet-api", "opinet_gas_station", "gasoline"),
    }
    assert {
        (point.provider, point.price_domain, point.product_key)
        for point in card.current
    } == expected_fresh_identities

    for include_geometry in (False, True):
        rows = await feature_repo.features_in_bbox(
            migrated_session,
            kinds=["price"],
            include_geometry=include_geometry,
            **bbox,
        )
        hit = next(r for r in rows if r["feature_id"] == price_feature.feature_id)
        assert {
            (point["provider"], point["price_domain"], point["product_key"])
            for point in (hit["price_summary"] or [])
        } == expected_fresh_identities  # 10일 묵은 diesel은 마커 라벨에서 제외.

        rows_all = await feature_repo.features_in_bbox(
            migrated_session,
            kinds=["price"],
            include_geometry=include_geometry,
            price_stale_hide_days=None,
            **bbox,
        )
        hit_all = next(
            r for r in rows_all if r["feature_id"] == price_feature.feature_id
        )
        assert {
            (point["provider"], point["price_domain"], point["product_key"])
            for point in (hit_all["price_summary"] or [])
        } == expected_fresh_identities | {
            ("python-opinet-api", "opinet_gas_station", "diesel")
        }
