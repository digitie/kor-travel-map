"""#741 — admin 비공개 Feature 공간 조회와 weather anchor 회귀."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text

from kortravelmap.dto._enums import PriceDomain
from kortravelmap.dto.price import PriceValue
from kortravelmap.dto.weather import WeatherValue
from kortravelmap.infra import (
    admin_feature_repo,
    feature_repo,
    price_repo,
    weather_repo,
)
from tests.integration._subtype_seed import seed_feature_subtype

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration

_KST = timezone(timedelta(hours=9))
_NOW = datetime(2026, 7, 19, 21, 0, tzinfo=_KST)
_TEST_LON = 126.987654
_TEST_LAT = 37.576543
_BBOX = {
    "min_lon": _TEST_LON - 0.00001,
    "min_lat": _TEST_LAT - 0.00001,
    "max_lon": _TEST_LON + 0.00001,
    "max_lat": _TEST_LAT + 0.00001,
}


async def _insert_feature(
    session: AsyncSession,
    *,
    feature_id: str,
    status: str,
    kind: str = "place",
    lon: float | None = _TEST_LON,
    lat: float | None = _TEST_LAT,
    geom_wkt: str | None = None,
    deleted_at: datetime | None = None,
    user_deleted_at: datetime | None = None,
) -> None:
    await session.execute(
        text(
            """
            INSERT INTO feature.features (
                feature_id, kind, name, category, coord, status,
                sido_code, sigungu_code, legal_dong_code, updated_at,
                deleted_at, user_deleted_at
            ) VALUES (
                :feature_id, :kind, :feature_id, '06020000',
                CASE WHEN CAST(:lon AS double precision) IS NULL THEN NULL
                     ELSE x_extension.ST_SetSRID(
                         x_extension.ST_MakePoint(:lon, :lat), 4326
                     ) END,
                :status, '11', '11110', '1111010100', :updated_at,
                :deleted_at, :user_deleted_at
            )
            """
        ),
        {
            "feature_id": feature_id,
            "kind": kind,
            "lon": lon,
            "lat": lat,
            "status": status,
            "updated_at": _NOW,
            "deleted_at": deleted_at,
            "user_deleted_at": user_deleted_at,
        },
    )
    # T-VN-35(ADR-086): kind별 값·geometry의 정본은 subtype이다.
    await seed_feature_subtype(
        session, feature_id=feature_id, kind=kind, geom_wkt=geom_wkt
    )


async def test_admin_bbox_and_cluster_include_nonpublic_statuses(
    migrated_session: AsyncSession,
) -> None:
    for feature_status in ("draft", "active", "inactive", "hidden", "broken"):
        await _insert_feature(
            migrated_session,
            feature_id=f"admin-map-{feature_status}",
            status=feature_status,
        )
    await _insert_feature(
        migrated_session,
        feature_id="admin-map-deleted",
        status="deleted",
        deleted_at=_NOW,
    )
    await _insert_feature(
        migrated_session,
        feature_id="admin-map-user-deleted",
        status="inactive",
        user_deleted_at=_NOW,
    )
    await migrated_session.flush()

    assert await admin_feature_repo.admin_feature_card_target_exists(
        migrated_session, "admin-map-hidden"
    )
    assert not await admin_feature_repo.admin_feature_card_target_exists(
        migrated_session, "admin-map-deleted"
    )
    assert not await admin_feature_repo.admin_feature_card_target_exists(
        migrated_session, "admin-map-user-deleted"
    )
    assert not await admin_feature_repo.admin_feature_card_target_exists(
        migrated_session, "admin-map-missing"
    )

    admin_rows = await admin_feature_repo.admin_features_in_bbox(
        migrated_session,
        **_BBOX,
    )
    admin_ids = {row["feature_id"] for row in admin_rows}
    assert admin_ids == {
        "admin-map-draft",
        "admin-map-active",
        "admin-map-inactive",
        "admin-map-hidden",
        "admin-map-broken",
    }

    hidden_rows = await admin_feature_repo.admin_features_in_bbox(
        migrated_session,
        **_BBOX,
        statuses=["hidden"],
    )
    assert [row["feature_id"] for row in hidden_rows] == ["admin-map-hidden"]

    hidden_cluster = await admin_feature_repo.cluster_admin_features_in_bbox(
        migrated_session,
        **_BBOX,
        cluster_unit="sido",
        statuses=["hidden"],
    )
    assert hidden_cluster == [
        {
            "cluster_key": "11",
            "feature_count": 1,
            "lon": pytest.approx(_TEST_LON),
            "lat": pytest.approx(_TEST_LAT),
        }
    ]

    public_rows = await feature_repo.features_in_bbox(
        migrated_session,
        **_BBOX,
        price_stale_hide_days=None,
    )
    assert {row["feature_id"] for row in public_rows} == {"admin-map-active"}


async def test_admin_bbox_geometry_membership_is_serialization_only(
    migrated_session: AsyncSession,
) -> None:
    await _insert_feature(
        migrated_session,
        feature_id="admin-map-hidden-route",
        kind="route",
        status="hidden",
        lon=None,
        lat=None,
        geom_wkt=(
            f"LINESTRING({_TEST_LON - 0.001} {_TEST_LAT}, "
            f"{_TEST_LON + 0.001} {_TEST_LAT})"
        ),
    )
    # coord는 bbox 안이고 geom MBR도 bbox와 겹치지만 실제 선은 bbox 바깥이다.
    # route/area가 coord arm으로 우회하거나 MBR만 검사하면 잘못 포함된다.
    await _insert_feature(
        migrated_session,
        feature_id="admin-map-hidden-false-positive",
        kind="route",
        status="hidden",
        lon=_TEST_LON,
        lat=_TEST_LAT,
        geom_wkt=(
            f"LINESTRING({_TEST_LON - 0.001} {_BBOX['min_lat'] - 0.001}, "
            f"{_TEST_LON + 0.001} {_BBOX['min_lat'] - 0.001}, "
            f"{_TEST_LON + 0.001} {_TEST_LAT + 0.001})"
        ),
    )
    await migrated_session.flush()

    light = await admin_feature_repo.admin_features_in_bbox(
        migrated_session,
        **_BBOX,
        statuses=["hidden"],
        include_geometry=False,
    )
    geometry = await admin_feature_repo.admin_features_in_bbox(
        migrated_session,
        **_BBOX,
        statuses=["hidden"],
        include_geometry=True,
    )

    assert [row["feature_id"] for row in light] == ["admin-map-hidden-route"]
    assert [row["feature_id"] for row in geometry] == ["admin-map-hidden-route"]
    assert light[0]["geometry"] is None
    # T-VN-35: subtype 컬럼 타입이 MultiLineString이라 단일 선분도 Multi로 승격된다.
    assert geometry[0]["geometry"]["type"] in {"LineString", "MultiLineString"}
    assert _BBOX["min_lon"] <= light[0]["lon"] <= _BBOX["max_lon"]
    assert _BBOX["min_lat"] <= light[0]["lat"] <= _BBOX["max_lat"]

    clusters = await admin_feature_repo.cluster_admin_features_in_bbox(
        migrated_session,
        **_BBOX,
        cluster_unit="sido",
        statuses=["hidden"],
    )
    assert len(clusters) == 1
    assert clusters[0]["feature_count"] == 1


async def test_admin_weather_card_uses_nonpublic_target_and_anchor(
    migrated_session: AsyncSession,
) -> None:
    await _insert_feature(
        migrated_session,
        feature_id="admin-hidden-target",
        status="hidden",
    )
    await _insert_feature(
        migrated_session,
        feature_id="admin-hidden-weather-anchor",
        status="hidden",
        kind="weather",
        lon=_TEST_LON + 0.000001,
        lat=_TEST_LAT + 0.000001,
    )
    await weather_repo.load_weather_values(
        migrated_session,
        [
            WeatherValue(
                feature_id="admin-hidden-weather-anchor",
                provider="python-kma-api",
                weather_domain="kma_short_forecast",
                forecast_style="short",
                timeline_bucket="short",
                metric_key="TMP",
                metric_name="기온",
                value_number=Decimal("24.0"),
                unit="deg_c",
                issued_at=_NOW,
                valid_at=_NOW,
            )
        ],
    )
    await migrated_session.flush()

    public_card = await weather_repo.build_weather_card(
        migrated_session,
        feature_id="admin-hidden-target",
    )
    admin_card = await weather_repo.build_admin_weather_card(
        migrated_session,
        feature_id="admin-hidden-target",
    )
    map_rows = await admin_feature_repo.admin_features_in_bbox(
        migrated_session,
        **_BBOX,
        statuses=["hidden"],
        kinds=["weather"],
    )

    assert public_card.metrics == []
    assert [(metric.metric_key, metric.value_number) for metric in admin_card.metrics] == [
        ("TMP", Decimal("24"))
    ]
    assert map_rows[0]["weather_summary"]["metric_key"] == "TMP"


async def test_admin_price_card_and_map_summary_include_nonpublic_feature(
    migrated_session: AsyncSession,
) -> None:
    feature_id = "admin-hidden-price"
    await _insert_feature(
        migrated_session,
        feature_id=feature_id,
        status="hidden",
        kind="price",
    )
    await price_repo.load_price_values(
        migrated_session,
        [
            PriceValue(
                feature_id=feature_id,
                provider="python-opinet-api",
                price_domain=PriceDomain.OPINET_GAS_STATION,
                product_key="gasoline",
                product_name="휘발유",
                source_product_key="B027",
                source_product_name="휘발유",
                observed_at=_NOW,
                value_number=Decimal("1789"),
                unit="KRW/L",
                normalization_version="test-v1",
                payload={},
                collected_at=_NOW,
                source_record_key=None,
            ),
            PriceValue(
                feature_id=feature_id,
                provider="python-krex-api",
                price_domain=PriceDomain.REST_AREA_FUEL,
                product_key="gasoline",
                product_name="휘발유",
                source_product_key="B027",
                source_product_name="휘발유",
                observed_at=_NOW,
                value_number=Decimal("1799"),
                unit="KRW/L",
                normalization_version="test-v1",
                payload={},
                collected_at=_NOW,
                source_record_key=None,
            )
        ],
    )
    await migrated_session.flush()

    card = await price_repo.build_price_card(
        migrated_session,
        feature_id=feature_id,
        asof=_NOW,
    )
    map_rows = await admin_feature_repo.admin_features_in_bbox(
        migrated_session,
        **_BBOX,
        statuses=["hidden"],
        kinds=["price"],
    )

    expected = {
        ("python-krex-api", "rest_area_fuel", "gasoline", Decimal("1799")),
        (
            "python-opinet-api",
            "opinet_gas_station",
            "gasoline",
            Decimal("1789"),
        ),
    }
    assert {
        (point.provider, point.price_domain, point.product_key, point.value_number)
        for point in card.current
    } == expected
    assert {
        (
            point["provider"],
            point["price_domain"],
            point["product_key"],
            point["value_number"],
        )
        for point in map_rows[0]["price_summary"]
    } == expected
