"""ADR-045 T-205c Phase 2 ops repository 통합 테스트."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text

from kortravelmap.infra.integrity_violation_repo import (
    DataIntegrityViolationStateConflict,
    create_data_integrity_violation,
    get_data_integrity_violation,
    list_data_integrity_violations,
    set_data_integrity_violation_status,
)
from kortravelmap.infra.poi_cache_target_repo import (
    PoiCacheTargetConflict,
    delete_poi_cache_target,
    get_poi_cache_target_by_key,
    list_poi_cache_target_feature_links,
    list_poi_cache_targets,
    upsert_poi_cache_target,
    upsert_poi_cache_target_feature_link,
)
from kortravelmap.infra.provider_refresh_policy_repo import (
    get_provider_refresh_policy,
    list_provider_refresh_policies,
    upsert_provider_refresh_policy,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration

_KST = timezone(timedelta(hours=9))
_FETCHED = datetime(2026, 6, 3, 12, 0, tzinfo=_KST)


async def _insert_feature(session: AsyncSession, feature_id: str) -> None:
    await session.execute(
        text(
            """
            INSERT INTO feature.features (feature_id, kind, name, category)
            VALUES (:feature_id, 'place', :feature_id, 'test')
            """
        ),
        {"feature_id": feature_id},
    )


async def _insert_source_record(session: AsyncSession, source_record_key: str) -> None:
    await session.execute(
        text(
            """
            INSERT INTO provider_sync.source_records (
                source_record_key, provider, dataset_key, source_entity_type,
                source_entity_id, raw_payload_hash, fetched_at
            )
            VALUES (
                :source_record_key, 'python-mois-api', 'mois_license_features_bulk',
                'license', :source_entity_id, :raw_payload_hash,
                :fetched_at
            )
            """
        ),
        {
            "source_record_key": source_record_key,
            "source_entity_id": source_record_key,
            "raw_payload_hash": f"hash-{source_record_key}",
            "fetched_at": _FETCHED,
        },
    )


async def test_provider_refresh_policy_upsert_get_list(
    migrated_session: AsyncSession,
) -> None:
    created = await upsert_provider_refresh_policy(
        migrated_session,
        provider="python-kma-api",
        dataset_key="kma_weather_alerts",
        source_kind="openapi",
        targeted_policy="allow_targeted",
        system_interval_seconds=600,
        optimal_interval_seconds=300,
        min_interval_seconds=300,
        max_requests_per_minute=30,
        max_concurrent=2,
        rate_limit_source={
            "provider_repo": "F:/dev/python-kma-api",
            "docs": ["docs/rate-limit.md"],
            "checked_at": "2026-06-03T12:00:00+09:00",
        },
    )

    assert created.provider == "python-kma-api"
    assert created.targeted_policy == "allow_targeted"
    assert created.max_concurrent == 2
    assert created.rate_limit_source["provider_repo"] == "F:/dev/python-kma-api"

    updated = await upsert_provider_refresh_policy(
        migrated_session,
        provider="python-kma-api",
        dataset_key="kma_weather_alerts",
        source_kind="openapi",
        targeted_policy="follow_system",
        system_interval_seconds=900,
        max_concurrent=1,
        enabled=False,
    )
    assert updated.targeted_policy == "follow_system"
    assert updated.system_interval_seconds == 900
    assert updated.enabled is False

    loaded = await get_provider_refresh_policy(
        migrated_session,
        provider="python-kma-api",
        dataset_key="kma_weather_alerts",
    )
    assert loaded == updated

    assert await list_provider_refresh_policies(
        migrated_session, provider="python-kma-api", enabled=False
    ) == (updated,)
    assert (
        await list_provider_refresh_policies(
            migrated_session, provider="python-kma-api", enabled=True
        )
        == ()
    )


async def test_poi_cache_target_upsert_move_delete_and_links(
    migrated_session: AsyncSession,
) -> None:
    await _insert_feature(migrated_session, "feature:poi:1")

    target = await upsert_poi_cache_target(
        migrated_session,
        external_system="external-app",
        target_key="poi-1",
        name="서울시청",
        lon=126.978,
        lat=37.5665,
        radius_km=3.0,
        provider_overrides={
            "python-kma-api:kma_weather_alerts": {"targeted_policy": "allow_targeted"}
        },
        metadata={"external_poi_id": "poi-1"},
    )
    assert target.coord_key == "126.978000:37.566500:p6"
    assert (
        target.provider_overrides["python-kma-api:kma_weather_alerts"]["targeted_policy"]
        == "allow_targeted"
    )

    same = await upsert_poi_cache_target(
        migrated_session,
        external_system="external-app",
        target_key="poi-1",
        name="서울시청",
        lon=126.978,
        lat=37.5665,
        radius_km=3.0,
    )
    assert same.target_id == target.target_id

    link = await upsert_poi_cache_target_feature_link(
        migrated_session,
        target_id=target.target_id,
        feature_id="feature:poi:1",
        provider="python-mois-api",
        dataset_key="mois_license_features_bulk",
        distance_m=120.5,
    )
    assert link.active is True
    assert link.distance_m == 120.5

    with pytest.raises(PoiCacheTargetConflict):
        await upsert_poi_cache_target(
            migrated_session,
            external_system="external-app",
            target_key="poi-1",
            lon=126.99,
            lat=37.57,
            radius_km=3.0,
        )

    moved = await upsert_poi_cache_target(
        migrated_session,
        external_system="external-app",
        target_key="poi-1",
        lon=126.99,
        lat=37.57,
        radius_km=4.0,
        on_conflict="move",
    )
    assert moved.target_id == target.target_id
    assert moved.coord_key == "126.990000:37.570000:p6"
    assert moved.radius_km == 4.0
    assert await list_poi_cache_target_feature_links(migrated_session, target.target_id) == ()
    assert (
        await list_poi_cache_target_feature_links(
            migrated_session, target.target_id, active_only=False
        )
    )[0].active is False

    deleted = await delete_poi_cache_target(
        migrated_session,
        external_system="external-app",
        target_key="poi-1",
    )
    assert deleted is not None
    assert deleted.deleted_at is not None
    assert deleted.update_enabled is False
    assert (
        await get_poi_cache_target_by_key(
            migrated_session,
            external_system="external-app",
            target_key="poi-1",
        )
        is None
    )
    target_page = await list_poi_cache_targets(
        migrated_session, external_system="external-app", include_deleted=True
    )
    assert target_page.items == (deleted,)
    assert target_page.next_cursor is None


async def test_data_integrity_violation_lifecycle_and_fk_behavior(
    migrated_session: AsyncSession,
) -> None:
    await _insert_feature(migrated_session, "feature:violation:1")
    await _insert_source_record(migrated_session, "src:violation:1")

    violation = await create_data_integrity_violation(
        migrated_session,
        provider="python-mois-api",
        dataset_key="mois_license_features_bulk",
        source_record_key="src:violation:1",
        feature_id="feature:violation:1",
        violation_type="provider_address_mismatch",
        severity="warning",
        message="provider 주소와 reverse geocode 주소가 다름",
        payload={
            "provider_address": "서울특별시 중구 세종대로 110",
            "kor_travel_geo_address": "서울특별시 중구 태평로1가",
            "distance_m": 120.0,
        },
    )
    assert violation.status == "open"
    assert violation.payload["distance_m"] == 120.0

    loaded = await get_data_integrity_violation(migrated_session, violation.issue_id)
    assert loaded == violation
    assert await list_data_integrity_violations(
        migrated_session,
        status="open",
        provider="python-mois-api",
        dataset_key="mois_license_features_bulk",
    ) == (violation,)

    resolved = await set_data_integrity_violation_status(
        migrated_session,
        violation.issue_id,
        status="resolved",
        resolution_payload={
            "operator": "local-admin",
            "reason": "manual address override",
        },
    )
    assert resolved is not None
    assert resolved.status == "resolved"
    assert resolved.resolved_at is not None
    assert resolved.payload["resolution"]["operator"] == "local-admin"

    same_resolved = await set_data_integrity_violation_status(
        migrated_session,
        violation.issue_id,
        status="resolved",
    )
    assert same_resolved is not None
    assert same_resolved.status == "resolved"
    assert same_resolved.resolved_at == resolved.resolved_at

    with pytest.raises(DataIntegrityViolationStateConflict) as exc_info:
        await set_data_integrity_violation_status(
            migrated_session,
            violation.issue_id,
            status="open",
        )
    assert exc_info.value.current_status == "resolved"
    still_resolved = await get_data_integrity_violation(migrated_session, violation.issue_id)
    assert still_resolved is not None
    assert still_resolved.status == "resolved"
    assert still_resolved.resolved_at == resolved.resolved_at

    await migrated_session.execute(
        text("DELETE FROM provider_sync.source_records WHERE source_record_key = 'src:violation:1'")
    )
    after_source_delete = await get_data_integrity_violation(
        migrated_session, violation.issue_id
    )
    assert after_source_delete is not None
    assert after_source_delete.source_record_key is None

    await migrated_session.execute(
        text("DELETE FROM feature.features WHERE feature_id = 'feature:violation:1'")
    )
    assert await get_data_integrity_violation(migrated_session, violation.issue_id) is None
