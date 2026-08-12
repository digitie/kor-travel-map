"""POI/cache target 기준 주변 feature 조회 통합 테스트."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text

from kortravelmap.infra import feature_repo
from kortravelmap.infra.poi_cache_target_repo import (
    list_active_target_coords,
    upsert_poi_cache_target,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration

_KST = timezone(timedelta(hours=9))
_FETCHED = datetime(2026, 6, 3, 12, 0, tzinfo=_KST)


async def _dataset_id(
    session: AsyncSession, *, provider: str, dataset_key: str
) -> int:
    """catalog에 pair를 확보하고 canonical id를 돌려준다.

    T-VN-33 이후 provider/dataset_key는 ``provider_sync.provider_datasets``에만
    산다 — source entity/record는 ``provider_dataset_id``만 갖는다.
    """
    return int(
        (
            await session.execute(
                text(
                    """
                    INSERT INTO provider_sync.provider_datasets (
                        provider, dataset_key, display_name, source_kind,
                        is_active, capabilities
                    )
                    SELECT :provider, :dataset_key, :provider, 'system', true,
                           jsonb_build_object('schema_version', 1,
                                              'produces', '[]'::jsonb,
                                              'extensions', '{}'::jsonb)
                    ON CONFLICT (provider, dataset_key) DO UPDATE
                        SET display_name = EXCLUDED.display_name
                    RETURNING provider_dataset_id
                    """
                ),
                {"provider": provider, "dataset_key": dataset_key},
            )
        ).scalar_one()
    )


async def _insert_feature(
    session: AsyncSession,
    *,
    feature_id: str,
    name: str,
    lon: float,
    lat: float,
    category: str = "06020000",
    lifecycle_state: str = "active",
    publication_state: str = "published",
    quality_state: str = "valid",
    provider: str = "python-opinet-api",
    dataset_key: str = "opinet_stations",
    updated_at: datetime = _FETCHED,
) -> None:
    """provider 계보까지 붙은 place feature 1건을 심는다.

    T-VN-34(0097)가 ``status``를 물리 삭제해 상태는 3축으로 심는다. 기본값이
    ``('active', 'published', 'valid')``인 이유는 이 파일이 상태에 거는 요구가
    "``feature.public_features``에 뜨는가" 하나이고, 그 view의 술어가 정확히 이
    tuple이기 때문이다 — 옛 ``status='active'``와 같은 뜻이다.
    """
    source_record_key = f"src:{feature_id}"
    source_entity_key = f"entity:{feature_id}"
    await session.execute(
        text(
            """
            INSERT INTO feature.features (
                feature_id, kind, name, category, coord,
                lifecycle_state, publication_state, quality_state, updated_at
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
                :lifecycle_state, :publication_state, :quality_state, :updated_at
            )
            """
        ),
        {
            "feature_id": feature_id,
            "name": name,
            "category": category,
            "lon": lon,
            "lat": lat,
            "lifecycle_state": lifecycle_state,
            "publication_state": publication_state,
            "quality_state": quality_state,
            "updated_at": updated_at,
        },
    )
    provider_dataset_id = await _dataset_id(
        session, provider=provider, dataset_key=dataset_key
    )
    await session.execute(
        text(
            """
            INSERT INTO provider_sync.source_entities (
                source_entity_key, provider_dataset_id, source_entity_type,
                source_entity_id, first_seen_at, last_seen_at
            )
            VALUES (
                :source_entity_key, :provider_dataset_id, 'place',
                :feature_id, :fetched_at, :fetched_at
            )
            """
        ),
        {
            "source_entity_key": source_entity_key,
            "provider_dataset_id": provider_dataset_id,
            "feature_id": feature_id,
            "fetched_at": _FETCHED,
        },
    )
    await session.execute(
        text(
            """
            INSERT INTO provider_sync.source_records (
                source_record_key, source_entity_key, raw_data,
                raw_payload_hash, fetched_at
            )
            VALUES (
                :source_record_key, :source_entity_key, '{}'::jsonb,
                md5(:raw_payload_seed), :fetched_at
            )
            """
        ),
        {
            "source_record_key": source_record_key,
            "source_entity_key": source_entity_key,
            "raw_payload_seed": f"hash:{feature_id}",
            "fetched_at": _FETCHED,
        },
    )
    # 현재 record 포인터는 head가 소유한다(lineage_key는 BEFORE INSERT 트리거가 채운다).
    await session.execute(
        text(
            """
            INSERT INTO provider_sync.source_entity_heads (
                source_entity_key, current_source_record_key, observed_at
            )
            VALUES (:source_entity_key, :source_record_key, :fetched_at)
            """
        ),
        {
            "source_record_key": source_record_key,
            "source_entity_key": source_entity_key,
            "fetched_at": _FETCHED,
        },
    )
    await session.execute(
        text(
            """
            INSERT INTO provider_sync.source_links (
                feature_id, source_entity_key, source_role,
                match_method, confidence
            )
            VALUES (
                :feature_id, :source_entity_key, 'primary',
                'natural_key', 100
            )
            """
        ),
        {"feature_id": feature_id, "source_entity_key": source_entity_key},
    )
    await session.flush()


async def test_features_nearby_target_filters_and_sorts_by_distance(
    migrated_session: AsyncSession,
) -> None:
    target = await upsert_poi_cache_target(
        migrated_session,
        external_system="external-app",
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
    # 옛 ``status='inactive'`` 자리. 이 파일에서 그 행이 지던 역할은 **두 가지를
    # 동시에** 만족하는 것이었다 — 공개 nearby 결과에서는 빠지되(아래 첫 단언),
    # ``deleted_at IS NULL``이라 날씨 대상 좌표에는 남는다(아래 D-12 단언).
    # 3축에서 그 교집합을 만드는 축은 publication 하나다: lifecycle은 'active'라
    # 살아 있고, publication 'suppressed'라 ``feature.public_features``에서 빠진다.
    # (0095 backfill이 legacy 'inactive'를 lifecycle 'retired'로 접은 것은 그
    # 세대의 값 변환 규칙이고, 그대로 옮기면 이 행이 날씨 좌표에서도 사라져
    # 두 번째 단언이 검증하려던 read 정합 자체가 없어진다.)
    await _insert_feature(
        migrated_session,
        feature_id="feature:nearby:unpublished",
        name="비공개 장소",
        lon=126.9783,
        lat=37.5666,
        publication_state="suppressed",
    )
    await _insert_feature(
        migrated_session,
        feature_id="feature:nearby:far",
        name="먼 장소",
        lon=127.12,
        lat=37.66,
    )

    # 제외 이유를 거리와 상태로 나눠 못박는다: 비공개 건이 nearby에서 빠지는
    # 근거는 반경이 아니라 공개 표면(``feature.public_features``) 부재다.
    public_ids = {
        str(row[0])
        for row in await migrated_session.execute(
            text("SELECT feature_id FROM feature.public_features")
        )
    }
    assert "feature:nearby:in" in public_ids
    assert "feature:nearby:far" in public_ids
    assert "feature:nearby:unpublished" not in public_ids

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
    # active place 좌표 전량: 옛 기준 ``deleted_at IS NULL``이 3축에서는
    # ``lifecycle_state='active'``다(0095가 soft delete를 lifecycle 축으로 접었다).
    # 현행 repo는 여기에 quality 'valid'만 더 볼 뿐 publication 축은 보지 않으므로
    # "공개되지 않아도 살아 있으면 날씨를 붙인다"는 D-12 read 정합이 그대로다.
    place_coords = await feature_repo.list_active_place_coords(migrated_session)
    by_id = {feature_id: (lon, lat) for feature_id, lon, lat in place_coords}
    assert by_id["feature:nearby:in"] == (126.9782, 37.5667)
    assert "feature:nearby:unpublished" in by_id
    # 옛 soft delete(``deleted_at = now()``)의 현행 등가물은 lifecycle 'retired'다.
    # publication을 함께 내리는 것은 취향이 아니라 제약이다 — retired인데
    # publication이 suppressed가 아니면 ``ck_features_state_tuple``이 막는다.
    await migrated_session.execute(
        text(
            "UPDATE feature.features "
            "SET lifecycle_state = 'retired', publication_state = 'suppressed' "
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
        external_system="external-app",
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
        external_system="external-app",
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
