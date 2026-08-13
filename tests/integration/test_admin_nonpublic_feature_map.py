"""#741 — admin 비공개 Feature 공간 조회와 weather anchor 회귀."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text

from kortravelmap.core.ids import make_payload_hash, make_source_record_key
from kortravelmap.dto import SourceRecord
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


async def _dataset_id(
    session: AsyncSession, *, provider: str, dataset_key: str
) -> int:
    value = await session.scalar(
        text(
            """
            SELECT provider_dataset_id
            FROM provider_sync.provider_datasets
            WHERE provider = :provider AND dataset_key = :dataset_key
            """
        ),
        {"provider": provider, "dataset_key": dataset_key},
    )
    assert value is not None
    return int(value)


def _response_record(
    *,
    provider: str,
    dataset_key: str,
    source_entity_type: str,
    raw_data: dict[str, object],
    fetched_at: datetime = _NOW,
) -> SourceRecord:
    payload_hash = make_payload_hash(raw_data)
    source_entity_id = f"test:{payload_hash[:20]}"
    return SourceRecord(
        provider=provider,
        dataset_key=dataset_key,
        source_entity_type=source_entity_type,
        source_entity_id=source_entity_id,
        raw_payload_hash=payload_hash,
        raw_data=raw_data,
        fetched_at=fetched_at,
        source_record_key=make_source_record_key(
            provider=provider,
            dataset_key=dataset_key,
            source_entity_type=source_entity_type,
            source_entity_id=source_entity_id,
            raw_payload_hash=payload_hash,
        ),
    )


async def _insert_feature(
    session: AsyncSession,
    *,
    feature_id: str,
    lifecycle_state: str = "active",
    publication_state: str = "published",
    quality_state: str = "valid",
    kind: str = "place",
    lon: float | None = _TEST_LON,
    lat: float | None = _TEST_LAT,
    geom_wkt: str | None = None,
) -> None:
    """seed를 3축 tuple로 직접 받는다.

    0097이 ``status``/``deleted_at``/``user_deleted_at``을 물리 삭제해 legacy 어휘를
    받아 번역하는 seed는 더 이상 성립하지 않는다 — legacy ``hidden``은 3축에서
    ``(active, suppressed, valid)``라는 tuple 자체이지, 따로 저장되는 별도 값이 아니다.
    이 테스트가 지키려는 명제("비공개 feature는 admin 표면에 보이고 공개 표면에는
    없다")는 축 tuple로 그대로 쓸 수 있으므로 번역 계층을 두지 않는다.
    """

    await session.execute(
        text(
            """
            INSERT INTO feature.features (
                feature_id, kind, name, category, coord,
                lifecycle_state, publication_state, quality_state,
                sido_code, sigungu_code, legal_dong_code, updated_at
            ) VALUES (
                :feature_id, :kind, :feature_id, '06020000',
                CASE WHEN CAST(:lon AS double precision) IS NULL THEN NULL
                     ELSE x_extension.ST_SetSRID(
                         x_extension.ST_MakePoint(:lon, :lat), 4326
                     ) END,
                :lifecycle_state, :publication_state, :quality_state,
                '11', '11110', '1111010100', :updated_at
            )
            """
        ),
        {
            "feature_id": feature_id,
            "kind": kind,
            "lon": lon,
            "lat": lat,
            "lifecycle_state": lifecycle_state,
            "publication_state": publication_state,
            "quality_state": quality_state,
            "updated_at": _NOW,
        },
    )
    # T-VN-35(ADR-086): kind별 값·geometry의 정본은 subtype이다.
    await seed_feature_subtype(
        session, feature_id=feature_id, kind=kind, geom_wkt=geom_wkt
    )


async def _current_dataset_id(
    session: AsyncSession, *, provider: str, dataset_key: str
) -> int:
    """현재 summary를 검증할 dataset에 freshness policy도 함께 부여한다."""

    dataset_id = await _dataset_id(session, provider=provider, dataset_key=dataset_key)
    await session.execute(
        text(
            """
            INSERT INTO ops.provider_refresh_policies (
                provider_dataset_id, source_kind, stale_after_minutes
            ) VALUES (:provider_dataset_id, 'system', 60)
            ON CONFLICT (provider_dataset_id) DO UPDATE
            SET enabled = true, stale_after_minutes = EXCLUDED.stale_after_minutes
            """
        ),
        {"provider_dataset_id": dataset_id},
    )
    return dataset_id


async def test_admin_bbox_and_cluster_include_nonpublic_statuses(
    migrated_session: AsyncSession,
) -> None:
    # 0095 backfill이 legacy status에서 만들어낼 수 있는 서로 다른 축 tuple 전부다.
    # draft/hidden/broken은 lifecycle을 잃지 않고 publication·quality로만 비공개가 되고,
    # inactive·deleted·user_deleted는 retire 사유(운영자 deactivate / tombstone /
    # user delete)와 무관하게 (retired, suppressed) 하나로 합쳐진다. 그래서 legacy가
    # admin 지도에서 inactive는 보이고 deleted는 감추던 3분할은 3축에 상(像)이 없다 —
    # 이제 admin 표면에서 "사라짐"은 hard purge(행 부재)뿐이다(ADR-090).
    seeded = {
        "admin-map-draft": ("active", "draft", "valid"),
        "admin-map-published": ("active", "published", "valid"),
        "admin-map-suppressed": ("active", "suppressed", "valid"),
        "admin-map-quarantined": ("active", "published", "quarantined"),
        "admin-map-retired": ("retired", "suppressed", "valid"),
    }
    for feature_id, (lifecycle, publication, quality) in seeded.items():
        await _insert_feature(
            migrated_session,
            feature_id=feature_id,
            lifecycle_state=lifecycle,
            publication_state=publication,
            quality_state=quality,
        )
    await migrated_session.flush()

    # card target은 공개 여부가 아니라 admin detail target의 실재(admin-any)를 묻는다.
    # `_ADMIN_FEATURE_DETAIL_SQL`이 축 술어 없이 feature_id로만 조회하고 retired도
    # reactivate 심사 대상이므로, 카드가 없어야 하는 것은 행이 없는 feature뿐이다.
    for feature_id in seeded:
        assert await admin_feature_repo.admin_feature_card_target_exists(
            migrated_session, feature_id
        )
    assert not await admin_feature_repo.admin_feature_card_target_exists(
        migrated_session, "admin-map-missing"
    )

    admin_rows = await admin_feature_repo.admin_features_in_bbox(
        migrated_session,
        **_BBOX,
    )
    admin_ids = {row["feature_id"] for row in admin_rows}
    # admin bbox는 공개 projection을 쓰지 않는다 — 축 filter를 주지 않으면 seed한 다섯
    # tuple이 모두 나온다. retired 제외를 여기 박으면 `lifecycle_state=retired` 필터가
    # 항상 빈 결과가 되어 admin in-bounds API의 축 filter 자체가 죽는다.
    assert admin_ids == set(seeded)

    # lifecycle을 'active'로 좁히면 같은 suppressed 안에서 retired가 떨어진다 —
    # 두 축이 독립임을 이 한 쌍이 증명한다.
    suppressed_rows = await admin_feature_repo.admin_features_in_bbox(
        migrated_session,
        **_BBOX,
        lifecycle_states=["active"],
        publication_states=["suppressed"],
    )
    assert [row["feature_id"] for row in suppressed_rows] == ["admin-map-suppressed"]

    suppressed_cluster = await admin_feature_repo.cluster_admin_features_in_bbox(
        migrated_session,
        **_BBOX,
        cluster_unit="sido",
        lifecycle_states=["active"],
        publication_states=["suppressed"],
    )
    assert suppressed_cluster == [
        {
            "cluster_key": "11",
            "feature_count": 1,
            "lon": pytest.approx(_TEST_LON),
            "lat": pytest.approx(_TEST_LAT),
        }
    ]

    # 공개 표면의 정본은 `feature.public_features`이고 그 유일한 tuple은
    # (active, published, valid)다. quarantined는 published여도 공개되지 않는다.
    public_rows = await feature_repo.features_in_bbox(
        migrated_session,
        **_BBOX,
        price_stale_hide_days=None,
    )
    assert {row["feature_id"] for row in public_rows} == {"admin-map-published"}


async def test_admin_bbox_geometry_membership_is_serialization_only(
    migrated_session: AsyncSession,
) -> None:
    await _insert_feature(
        migrated_session,
        feature_id="admin-map-hidden-route",
        kind="route",
        publication_state="suppressed",
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
        publication_state="suppressed",
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
        lifecycle_states=["active"],
        publication_states=["suppressed"],
        include_geometry=False,
    )
    geometry = await admin_feature_repo.admin_features_in_bbox(
        migrated_session,
        **_BBOX,
        lifecycle_states=["active"],
        publication_states=["suppressed"],
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
        lifecycle_states=["active"],
        publication_states=["suppressed"],
    )
    assert len(clusters) == 1
    assert clusters[0]["feature_count"] == 1


async def test_admin_weather_card_uses_nonpublic_target_and_anchor(
    migrated_session: AsyncSession,
) -> None:
    current = datetime.now(UTC)
    await _insert_feature(
        migrated_session,
        feature_id="admin-hidden-target",
        publication_state="suppressed",
    )
    await _insert_feature(
        migrated_session,
        feature_id="admin-hidden-weather-anchor",
        publication_state="suppressed",
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
                issued_at=current,
                valid_at=current,
            )
        ],
        provider_dataset_id=await _current_dataset_id(
            migrated_session,
            provider="python-kma-api",
            dataset_key="kma_short_forecast",
        ),
        source_record=_response_record(
            provider="python-kma-api",
            dataset_key="kma_short_forecast",
            source_entity_type="weather_response",
            raw_data={"metric": "TMP", "feature_id": "admin-hidden-weather-anchor"},
            fetched_at=current,
        ),
        selected_at=current,
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
        lifecycle_states=["active"],
        publication_states=["suppressed"],
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
    current = datetime.now(UTC)
    feature_id = "admin-hidden-price"
    await _insert_feature(
        migrated_session,
        feature_id=feature_id,
        publication_state="suppressed",
        kind="price",
    )
    opinet_value = PriceValue(
        feature_id=feature_id,
        provider="python-opinet-api",
        price_domain=PriceDomain.OPINET_GAS_STATION,
        product_key="gasoline",
        product_name="휘발유",
        source_product_key="B027",
        source_product_name="휘발유",
        observed_at=current,
        value_number=Decimal("1789"),
        unit="KRW/L",
        normalization_version="test-v1",
        payload={},
        collected_at=current,
        source_record_key=None,
    )
    krex_value = PriceValue(
        feature_id=feature_id,
        provider="python-krex-api",
        price_domain=PriceDomain.REST_AREA_FUEL,
        product_key="gasoline",
        product_name="휘발유",
        source_product_key="B027",
        source_product_name="휘발유",
        observed_at=current,
        value_number=Decimal("1799"),
        unit="KRW/L",
        normalization_version="test-v1",
        payload={},
        collected_at=current,
        source_record_key=None,
    )
    await price_repo.load_price_values(
        migrated_session,
        [opinet_value],
        provider_dataset_id=await _current_dataset_id(
            migrated_session,
            provider="python-opinet-api",
            dataset_key="opinet_gas_station_prices",
        ),
        source_record=_response_record(
            provider="python-opinet-api",
            dataset_key="opinet_gas_station_prices",
            source_entity_type="price_response",
            raw_data={"feature_id": feature_id, "value": "1789"},
            fetched_at=current,
        ),
    )
    await price_repo.load_price_values(
        migrated_session,
        [krex_value],
        provider_dataset_id=await _current_dataset_id(
            migrated_session,
            provider="python-krex-api",
            dataset_key="krex_rest_area_prices",
        ),
        source_record=_response_record(
            provider="python-krex-api",
            dataset_key="krex_rest_area_prices",
            source_entity_type="price_response",
            raw_data={"feature_id": feature_id, "value": "1799"},
            fetched_at=current,
        ),
    )
    await migrated_session.flush()

    card = await price_repo.build_price_card(
        migrated_session,
        feature_id=feature_id,
    )
    map_rows = await admin_feature_repo.admin_features_in_bbox(
        migrated_session,
        **_BBOX,
        lifecycle_states=["active"],
        publication_states=["suppressed"],
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
