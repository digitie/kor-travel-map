"""POI/cache target 기준 주변 feature 조회 통합 테스트."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text

from krtour.map.infra import feature_repo
from krtour.map.infra.poi_cache_target_repo import (
    list_active_target_coords,
    upsert_poi_cache_target,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration

_KST = timezone(timedelta(hours=9))
_FETCHED = datetime(2026, 6, 3, 12, 0, tzinfo=_KST)


async def _insert_feature(
    session: AsyncSession,
    *,
    feature_id: str,
    name: str,
    lon: float,
    lat: float,
    category: str = "06020000",
    status: str = "active",
    provider: str = "python-opinet-api",
    dataset_key: str = "opinet_stations",
    updated_at: datetime = _FETCHED,
) -> None:
    source_record_key = f"src:{feature_id}"
    await session.execute(
        text(
            """
            INSERT INTO feature.features (
                feature_id, kind, name, category, coord, status, updated_at
            )
            VALUES (
                :feature_id, 'place', :name, :category,
                x_extension.ST_SetSRID(
                    x_extension.ST_MakePoint(
                        CAST(:lon AS double precision),
                        CAST(:lat AS double precision)
                    ),
                    4326
                ),
                :status, :updated_at
            )
            """
        ),
        {
            "feature_id": feature_id,
            "name": name,
            "category": category,
            "lon": lon,
            "lat": lat,
            "status": status,
            "updated_at": updated_at,
        },
    )
    await session.execute(
        text(
            """
            INSERT INTO provider_sync.source_records (
                source_record_key, provider, dataset_key, source_entity_type,
                source_entity_id, raw_payload_hash, fetched_at
            )
            VALUES (
                :source_record_key, :provider, :dataset_key, 'place',
                :feature_id, :raw_payload_hash, :fetched_at
            )
            """
        ),
        {
            "source_record_key": source_record_key,
            "provider": provider,
            "dataset_key": dataset_key,
            "feature_id": feature_id,
            "raw_payload_hash": f"hash:{feature_id}",
            "fetched_at": _FETCHED,
        },
    )
    await session.execute(
        text(
            """
            INSERT INTO provider_sync.source_links (
                feature_id, source_record_key, source_role,
                match_method, confidence, is_primary_source
            )
            VALUES (
                :feature_id, :source_record_key, 'primary',
                'natural_key', 100, true
            )
            """
        ),
        {"feature_id": feature_id, "source_record_key": source_record_key},
    )
    await session.flush()


async def test_features_nearby_target_filters_and_sorts_by_distance(
    migrated_session: AsyncSession,
) -> None:
    target = await upsert_poi_cache_target(
        migrated_session,
        external_system="tripmate",
        target_key="nearby-1",
        lon=126.978,
        lat=37.5665,
        radius_km=1.0,
    )
    await _insert_feature(
        migrated_session,
        feature_id="feature:nearby:in",
        name="가까운 장소",
        lon=126.9782,
        lat=37.5667,
    )
    await _insert_feature(
        migrated_session,
        feature_id="feature:nearby:inactive",
        name="비활성 장소",
        lon=126.9783,
        lat=37.5666,
        status="inactive",
    )
    await _insert_feature(
        migrated_session,
        feature_id="feature:nearby:far",
        name="먼 장소",
        lon=127.12,
        lat=37.66,
    )

    page = await feature_repo.features_nearby_poi_cache_target(
        migrated_session,
        target_id=target.target_id,
        providers=("python-opinet-api",),
        categories=("06020000",),
        limit=10,
    )

    assert [item.feature_id for item in page.items] == ["feature:nearby:in"]
    assert page.items[0].distance_m < 50
    assert page.items[0].primary_provider == "python-opinet-api"
    assert page.next_cursor is None

    # T-219a — KMA weather 대상 조회 2종.
    # 활성 target 좌표: 위에서 만든 target 1건.
    coords = await list_active_target_coords(migrated_session)
    assert (126.978, 37.5665) in coords
    # active place 좌표 전량: deleted_at IS NULL 기준(soft-deleted만 제외 —
    # status='inactive'여도 미삭제면 날씨를 붙일 수 있다, D-12 read 정합).
    place_coords = await feature_repo.list_active_place_coords(migrated_session)
    by_id = {feature_id: (lon, lat) for feature_id, lon, lat in place_coords}
    assert by_id["feature:nearby:in"] == (126.9782, 37.5667)
    assert "feature:nearby:inactive" in by_id
    await migrated_session.execute(
        text(
            "UPDATE feature.features SET deleted_at = now() "
            "WHERE feature_id = 'feature:nearby:far'"
        )
    )
    after = await feature_repo.list_active_place_coords(migrated_session)
    assert all(feature_id != "feature:nearby:far" for feature_id, _, _ in after)


async def test_features_nearby_target_cursor_pages_distance_order(
    migrated_session: AsyncSession,
) -> None:
    target = await upsert_poi_cache_target(
        migrated_session,
        external_system="tripmate",
        target_key="nearby-cursor",
        lon=126.978,
        lat=37.5665,
        radius_km=3.0,
    )
    await _insert_feature(
        migrated_session,
        feature_id="feature:nearby:first",
        name="첫 번째",
        lon=126.9781,
        lat=37.5666,
    )
    await _insert_feature(
        migrated_session,
        feature_id="feature:nearby:second",
        name="두 번째",
        lon=126.985,
        lat=37.568,
    )

    first_page = await feature_repo.features_nearby_poi_cache_target(
        migrated_session,
        target_id=target.target_id,
        limit=1,
    )
    assert first_page.next_cursor is not None
    assert [item.feature_id for item in first_page.items] == ["feature:nearby:first"]

    second_page = await feature_repo.features_nearby_poi_cache_target(
        migrated_session,
        target_id=target.target_id,
        limit=1,
        cursor=first_page.next_cursor,
    )
    assert [item.feature_id for item in second_page.items] == [
        "feature:nearby:second"
    ]
    assert second_page.next_cursor is None


async def test_features_nearby_target_name_sort_and_invalid_cursor(
    migrated_session: AsyncSession,
) -> None:
    target = await upsert_poi_cache_target(
        migrated_session,
        external_system="tripmate",
        target_key="nearby-name",
        lon=126.978,
        lat=37.5665,
        radius_km=3.0,
    )
    await _insert_feature(
        migrated_session,
        feature_id="feature:nearby:name-b",
        name="B second",
        lon=126.9781,
        lat=37.5666,
    )
    await _insert_feature(
        migrated_session,
        feature_id="feature:nearby:name-a",
        name="A first",
        lon=126.9782,
        lat=37.5667,
    )

    page = await feature_repo.features_nearby_poi_cache_target(
        migrated_session,
        target_id=target.target_id,
        sort="name",
        limit=10,
    )
    assert [item.feature_id for item in page.items] == [
        "feature:nearby:name-a",
        "feature:nearby:name-b",
    ]

    with pytest.raises(ValueError, match="invalid nearby cursor"):
        await feature_repo.features_nearby_poi_cache_target(
            migrated_session,
            target_id=target.target_id,
            sort="name",
            cursor="not-base64",
        )
