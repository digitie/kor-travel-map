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
from kortravelmap.infra.models import SourceEntityRow, SourceRecordRow
from kortravelmap.infra.poi_cache_target_repo import (
    PoiCacheTargetConflict,
    PoiCacheTargetFeatureLinkCandidate,
    delete_poi_cache_target,
    get_poi_cache_target_by_key,
    list_poi_cache_target_feature_links,
    list_poi_cache_targets,
    sync_poi_cache_target_feature_links,
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
    source_entity_key = f"se:{source_record_key}"
    entity = SourceEntityRow(
        source_entity_key=source_entity_key,
        provider="python-mois-api",
        dataset_key="mois_license_features_bulk",
        source_entity_type="license",
        source_entity_id=source_record_key,
        current_source_record_key=None,
        first_seen_at=_FETCHED,
        last_seen_at=_FETCHED,
    )
    session.add(entity)
    await session.flush()
    session.add(
        SourceRecordRow(
            source_record_key=source_record_key,
            source_entity_key=source_entity_key,
            provider="python-mois-api",
            dataset_key="mois_license_features_bulk",
            source_entity_type="license",
            source_entity_id=source_record_key,
            raw_payload_hash=f"hash-{source_record_key}",
            fetched_at=_FETCHED,
        )
    )
    await session.flush()
    entity.current_source_record_key = source_record_key
    await session.flush()


async def test_provider_refresh_policy_upsert_get_list(
    migrated_session: AsyncSession,
) -> None:
    created = await upsert_provider_refresh_policy(
        migrated_session,
        provider="python-kma-api",
        dataset_key="kma_weather_alerts",
        source_kind="openapi",
        expected_revision=None,
        targeted_policy="allow_targeted",
        system_interval_seconds=600,
        optimal_interval_seconds=300,
        min_interval_seconds=300,
        max_requests_per_minute=30,
        max_concurrent=2,
        stale_after_minutes=45,
        rate_limit_source={
            "provider_repo": "F:/dev/python-kma-api",
            "docs": ["docs/rate-limit.md"],
            "checked_at": "2026-06-03T12:00:00+09:00",
        },
    )

    assert created.provider == "python-kma-api"
    assert created.targeted_policy == "allow_targeted"
    assert created.max_concurrent == 2
    assert created.stale_after_minutes == 45
    assert created.rate_limit_source["provider_repo"] == "F:/dev/python-kma-api"

    updated = await upsert_provider_refresh_policy(
        migrated_session,
        provider="python-kma-api",
        dataset_key="kma_weather_alerts",
        source_kind="openapi",
        expected_revision=created.revision,
        targeted_policy="follow_system",
        system_interval_seconds=900,
        max_concurrent=1,
        enabled=False,
        stale_after_minutes=90,
    )
    assert updated.targeted_policy == "follow_system"
    assert updated.system_interval_seconds == 900
    assert updated.enabled is False
    assert updated.stale_after_minutes == 90
    assert updated.rate_limit_source == created.rate_limit_source

    explicitly_replaced = await upsert_provider_refresh_policy(
        migrated_session,
        provider="python-kma-api",
        dataset_key="kma_weather_alerts",
        source_kind="openapi",
        expected_revision=updated.revision,
        targeted_policy="follow_system",
        system_interval_seconds=900,
        max_concurrent=1,
        enabled=False,
        stale_after_minutes=90,
        rate_limit_source={"provider_contract": "2026-07-17"},
    )
    assert explicitly_replaced.rate_limit_source == {
        "provider_contract": "2026-07-17"
    }

    loaded = await get_provider_refresh_policy(
        migrated_session,
        provider="python-kma-api",
        dataset_key="kma_weather_alerts",
    )
    assert loaded == explicitly_replaced

    assert await list_provider_refresh_policies(
        migrated_session, provider="python-kma-api", enabled=False
    ) == (explicitly_replaced,)
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
    assert link is not None
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

    mismatch = await delete_poi_cache_target(
        migrated_session,
        external_system="external-app",
        target_key="poi-1",
        expected_target_id="22222222-2222-4222-8222-222222222222",
        expected_lock_version=moved.lock_version,
    )
    assert mismatch.status == "precondition_failed"
    assert (
        await get_poi_cache_target_by_key(
            migrated_session,
            external_system="external-app",
            target_key="poi-1",
        )
        is not None
    )

    delete_result = await delete_poi_cache_target(
        migrated_session,
        external_system="external-app",
        target_key="poi-1",
        expected_target_id=moved.target_id,
        expected_lock_version=moved.lock_version,
    )
    assert delete_result.status == "deleted"
    deleted = delete_result.target
    assert deleted is not None
    assert deleted.lock_version == moved.lock_version + 1
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


async def test_link_snapshot_sync_preserves_operator_manual_links(
    migrated_session: AsyncSession,
) -> None:
    """resolver link만 교체하는 snapshot sync가 manual link를 보존한다 (#699 패턴)."""
    await _insert_feature(migrated_session, "feature:poi:manual")
    await _insert_feature(migrated_session, "feature:poi:resolver")
    await _insert_feature(migrated_session, "feature:poi:resolver-next")

    target = await upsert_poi_cache_target(
        migrated_session,
        external_system="external-app",
        target_key="poi-manual",
        lon=126.978,
        lat=37.5665,
        radius_km=3.0,
    )
    resolver_link = await upsert_poi_cache_target_feature_link(
        migrated_session,
        target_id=target.target_id,
        feature_id="feature:poi:resolver",
    )
    assert resolver_link is not None
    manual_link = await upsert_poi_cache_target_feature_link(
        migrated_session,
        target_id=target.target_id,
        feature_id="feature:poi:manual",
        relation="manual",
    )
    assert manual_link is not None

    synced = await sync_poi_cache_target_feature_links(
        migrated_session,
        target_ids=(target.target_id,),
        candidates=(
            PoiCacheTargetFeatureLinkCandidate(
                target_id=target.target_id,
                feature_id="feature:poi:resolver-next",
            ),
        ),
    )
    assert [link.feature_id for link in synced] == ["feature:poi:resolver-next"]

    links = {
        link.feature_id: link
        for link in await list_poi_cache_target_feature_links(
            migrated_session,
            target.target_id,
            active_only=False,
        )
    }
    assert links["feature:poi:manual"].active is True
    assert links["feature:poi:manual"].relation == "manual"
    assert links["feature:poi:resolver"].active is False
    assert links["feature:poi:resolver-next"].active is True

    # resolver가 같은 (target, feature)를 재-upsert해도 manual 분류를 되돌리지
    # 못한다 — 되돌아가면 다음 snapshot sync가 manual link를 비활성화하게 된다.
    reclassified_direct = await upsert_poi_cache_target_feature_link(
        migrated_session,
        target_id=target.target_id,
        feature_id="feature:poi:manual",
        relation="within_radius",
    )
    assert reclassified_direct is not None
    assert reclassified_direct.relation == "manual"

    resynced = await sync_poi_cache_target_feature_links(
        migrated_session,
        target_ids=(target.target_id,),
        candidates=(
            PoiCacheTargetFeatureLinkCandidate(
                target_id=target.target_id,
                feature_id="feature:poi:manual",
                relation="within_radius",
            ),
        ),
    )
    assert [link.relation for link in resynced] == ["manual"]

    links = {
        link.feature_id: link
        for link in await list_poi_cache_target_feature_links(
            migrated_session,
            target.target_id,
            active_only=False,
        )
    }
    assert links["feature:poi:manual"].active is True
    assert links["feature:poi:manual"].relation == "manual"
    # manual이 아닌 resolver link는 이번 sync 후보에 없으므로 비활성화된다.
    assert links["feature:poi:resolver-next"].active is False


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
        text(
            "UPDATE provider_sync.source_entities "
            "SET current_source_record_key = NULL "
            "WHERE current_source_record_key = 'src:violation:1'"
        )
    )
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
