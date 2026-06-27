"""``test_krex_price_renderable`` — #547 휴게소 유가 feature 렌더 가능성 (PostGIS).

`restarea.fuel_prices` row에는 lon/lat가 없어 유가 price-kind Feature가
coord=None이면 모든 map/bbox 쿼리(``coord IS NOT NULL``)에서 누락된다. 본 통합
테스트는 end-to-end 회귀를 PostGIS testcontainer에서 검증한다:

1. 휴게소 place feature 적재(좌표 보유).
2. `list_primary_place_locator`로 자연키→(feature_id, 좌표) locator 조회.
3. 유가 record를 locator와 함께 변환 → 유가 feature가 place 좌표·
   ``parent_feature_id``를 상속.
4. 유가 bundle 적재 후 ``features_in_bbox``로 조회 → **유가 feature가 결과에
   노출**(렌더 가능) + 좌표·parent 정합.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

import pytest

from kortravelmap.infra import feature_repo
from kortravelmap.providers.krex import (
    KREX_PROVIDER_NAME,
    REST_AREA_DATASET_KEY,
    REST_AREA_SOURCE_ENTITY_TYPE,
    rest_area_fuel_price_records_to_features_and_values,
    rest_area_place_locator_from_rows,
    rest_areas_to_bundles,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration

_KST = timezone(timedelta(hours=9))
_FETCHED = datetime(2026, 6, 23, 12, 0, tzinfo=_KST)


@dataclass(frozen=True)
class _RestArea:
    """`KrexRestAreaItem` Protocol — 좌표 보유 휴게소."""

    name: str
    route_name: str | None
    direction: str | None
    lat: float | None
    lon: float | None
    phone_number: str | None


@dataclass(frozen=True)
class _FuelPriceRecord:
    """`KrexRestAreaFuelPriceRecord` Protocol — lon/lat 없이 주소만."""

    service_area_code: str
    route_name: str | None
    direction: str | None
    oil_company: str | None
    service_area_name: str | None
    phone_number: str | None
    address: str | None
    gasoline_price: int | None
    diesel_price: int | None
    lpg_price: int | None
    raw: dict[str, Any]


async def test_fuel_price_feature_inherits_place_coord_and_renders_in_bbox(
    migrated_session: AsyncSession,
) -> None:
    place = _RestArea(
        name="서산휴게소",
        route_name="서해안고속도로",
        direction="부산방향",
        lat=36.7800,
        lon=126.6500,
        phone_number="041-1234-5678",
    )
    # ① 휴게소 place 적재 (좌표 보유).
    place_bundles = await rest_areas_to_bundles([place], fetched_at=_FETCHED)
    await feature_repo.load_bundles(migrated_session, place_bundles)
    await migrated_session.flush()
    place_feature = place_bundles[0].feature
    assert place_feature.coord is not None

    # ② DB에서 자연키→(feature_id, 좌표) locator 조회 (#547 신규 repo 경로).
    rows = await feature_repo.list_primary_place_locator(
        migrated_session,
        provider=KREX_PROVIDER_NAME,
        dataset_key=REST_AREA_DATASET_KEY,
        source_entity_type=REST_AREA_SOURCE_ENTITY_TYPE,
    )
    locator = rest_area_place_locator_from_rows(rows)
    natural_key = place_bundles[0].source_record.source_entity_id
    assert natural_key in locator
    assert locator[natural_key][0] == place_feature.feature_id

    # ③ 유가 record(좌표 없음) → locator로 place 좌표·parent 상속.
    record = _FuelPriceRecord(
        service_area_code="A0001",
        route_name=place.route_name,
        direction=place.direction,
        oil_company="EX-OIL",
        service_area_name=place.name,
        phone_number=place.phone_number,
        address="충남 서산시",
        gasoline_price=1710,
        diesel_price=1599,
        lpg_price=None,
        raw={"serviceAreaCode": "A0001"},
    )
    price_bundles, price_values = (
        rest_area_fuel_price_records_to_features_and_values(
            [record], fetched_at=_FETCHED, place_locator=locator
        )
    )
    [price_bundle] = price_bundles
    price_feature = price_bundle.feature
    assert price_feature.coord is not None
    assert price_feature.parent_feature_id == place_feature.feature_id

    # ④ 유가 bundle 적재 후 bbox 조회 → price feature가 결과에 노출(렌더 가능).
    await feature_repo.load_bundles(migrated_session, price_bundles)
    await migrated_session.flush()

    lon = float(price_feature.coord.lon)
    lat = float(price_feature.coord.lat)
    rows_bbox = await feature_repo.features_in_bbox(
        migrated_session,
        min_lon=lon - 0.1,
        min_lat=lat - 0.1,
        max_lon=lon + 0.1,
        max_lat=lat + 0.1,
        kinds=["price"],
    )
    ids = {r["feature_id"] for r in rows_bbox}
    assert price_feature.feature_id in ids
    hit = next(
        r for r in rows_bbox if r["feature_id"] == price_feature.feature_id
    )
    assert abs(float(hit["lon"]) - lon) < 1e-6
    assert abs(float(hit["lat"]) - lat) < 1e-6
    assert hit["kind"] == "price"

    # price 좌표가 place 좌표와 일치(상속).
    assert abs(lon - float(place_feature.coord.lon)) < 1e-6
    assert abs(lat - float(place_feature.coord.lat)) < 1e-6


async def test_fuel_price_feature_coordless_without_locator(
    migrated_session: AsyncSession,
) -> None:
    """locator 없으면(또는 매칭 실패) 유가 feature는 coordless로 적재되고
    bbox 쿼리에서 누락된다 — 좌표는 place 적재·후속 실행으로 회복 가능."""
    record = _FuelPriceRecord(
        service_area_code="B0002",
        route_name="경부고속도로",
        direction="서울방향",
        oil_company="EX-OIL",
        service_area_name="미적재휴게소",
        phone_number=None,
        address="경기 어딘가",
        gasoline_price=1700,
        diesel_price=None,
        lpg_price=None,
        raw={},
    )
    price_bundles, _ = rest_area_fuel_price_records_to_features_and_values(
        [record], fetched_at=_FETCHED
    )
    [price_bundle] = price_bundles
    assert price_bundle.feature.coord is None
    await feature_repo.load_bundles(migrated_session, price_bundles)
    await migrated_session.flush()

    # coord=None → bbox 쿼리(coord IS NOT NULL)에서 제외.
    rows_bbox = await feature_repo.features_in_bbox(
        migrated_session,
        min_lon=126.0,
        min_lat=36.0,
        max_lon=128.0,
        max_lat=38.0,
        kinds=["price"],
    )
    assert price_bundle.feature.feature_id not in {
        r["feature_id"] for r in rows_bbox
    }
