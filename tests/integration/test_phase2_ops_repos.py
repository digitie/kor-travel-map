"""ADR-045 T-205c Phase 2 ops repository 통합 테스트."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import md5
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text

from kortravelmap.core.ids import make_integrity_finding_key
from kortravelmap.infra.integrity_violation_repo import (
    DataIntegrityViolationStateConflict,
    create_data_integrity_violation,
    get_data_integrity_violation,
    list_data_integrity_violations,
    set_data_integrity_violation_status,
    sync_integrity_findings,
)
from kortravelmap.infra.models import (
    SourceEntityHeadRow,
    SourceEntityRow,
    SourceRecordRow,
)
from kortravelmap.infra.poi_cache_target_repo import (
    PoiCacheTargetConflict,
    PoiCacheTargetFeatureLinkCandidate,
    deactivate_poi_cache_target_feature_links,
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

_MOIS_PROVIDER = "python-mois-api"
_MOIS_DATASET = "mois_license_features_bulk"
_KMA_PROVIDER = "python-kma-api"
_KMA_DATASET = "kma_weather_alerts"

# T-VN-39 재키(309) 뒤 ``feature.features.feature_id``는 uuid다 — 이 파일이 심는
# seed identity도 그 형태여야 한다. 종전의 ``feature:poi:1`` 류 문자열은 legacy
# ``f_*``조차 아닌 테스트 전용 리터럴이었고, 재키 후에는 uuid 컬럼에 text를 넣는
# 자리가 된다. 값 자체는 opaque(ADR-068 결정 3)이므로 무엇을 가리키는지는 상수
# 이름이 지고, 마지막 마디만 파일 안에서 유일하게 둔다.
#
# ``ops.poi_cache_target_feature_links.feature_id`` ·
# ``ops.data_integrity_violations.feature_id``도 309가 함께 uuid로 옮겼으므로
# repository 인자로 넘어가는 값도 같은 상수다.
_FEATURE_POI = "39020001-0000-4000-8000-000000000001"
_FEATURE_POI_MANUAL = "39020001-0000-4000-8000-000000000002"
_FEATURE_POI_RESOLVER = "39020001-0000-4000-8000-000000000003"
_FEATURE_POI_RESOLVER_NEXT = "39020001-0000-4000-8000-000000000004"
_FEATURE_VIOLATION = "39020001-0000-4000-8000-000000000005"
_FEATURE_VIOLATION_BY_SUFFIX = {
    "old": "39020001-0000-4000-8000-000000000006",
    "new": "39020001-0000-4000-8000-000000000007",
}


async def _dataset_id(
    session: AsyncSession, *, provider: str, dataset_key: str
) -> int:
    """catalog에서 canonical ``provider_dataset_id``를 얻는다.

    T-VN-33 이후 ops/provider_sync 저장소는 자연키 사본을 갖지 않는다 —
    identity는 ``provider_dataset_id``다. 0089가 seed한 pair면 그대로 읽고,
    아니면 fixture 전용 행을 만든다.
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


async def _insert_feature(session: AsyncSession, feature_id: str, *, name: str) -> None:
    """FK 대상 Feature 하나를 심는다.

    ``feature_id``와 ``name``은 재키 뒤 **다른 타입의 열**이다(uuid / text).
    종전에는 같은 바인드 하나를 두 열에 꽂았는데, 그러면 파라미터 하나에
    uuid와 text가 동시에 유도되어 문장이 파스 단계에서 죽는다. 열마다 제 바인드를
    주고 정본 키 쪽만 uuid로 캐스팅한다.
    """
    await session.execute(
        text(
            """
            INSERT INTO feature.features (feature_id, kind, name, category)
            VALUES (CAST(:feature_id AS uuid), 'place', :name, 'test')
            """
        ),
        {"feature_id": feature_id, "name": name},
    )


async def _insert_source_record(session: AsyncSession, source_record_key: str) -> None:
    source_entity_key = f"se:{source_record_key}"
    provider_dataset_id = await _dataset_id(
        session, provider=_MOIS_PROVIDER, dataset_key=_MOIS_DATASET
    )
    session.add(
        SourceEntityRow(
            source_entity_key=source_entity_key,
            provider_dataset_id=provider_dataset_id,
            source_entity_type="license",
            source_entity_id=source_record_key,
            first_seen_at=_FETCHED,
            last_seen_at=_FETCHED,
        )
    )
    await session.flush()
    session.add(
        SourceRecordRow(
            source_record_key=source_record_key,
            source_entity_key=source_entity_key,
            raw_data={},
            # ck_source_records_payload_hash_canonical = ^[0-9a-f]{1,64}$
            raw_payload_hash=md5(
                source_record_key.encode("utf-8"), usedforsecurity=False
            ).hexdigest(),
            fetched_at=_FETCHED,
        )
    )
    await session.flush()
    # 현재 record 포인터는 head가 소유한다(lineage_key는 트리거가 채운다).
    session.add(
        SourceEntityHeadRow(
            source_entity_key=source_entity_key,
            current_source_record_key=source_record_key,
            observed_at=_FETCHED,
        )
    )
    await session.flush()


async def test_provider_refresh_policy_upsert_get_list(
    migrated_session: AsyncSession,
) -> None:
    provider_dataset_id = await _dataset_id(
        migrated_session, provider=_KMA_PROVIDER, dataset_key=_KMA_DATASET
    )
    created = await upsert_provider_refresh_policy(
        migrated_session,
        provider_dataset_id=provider_dataset_id,
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
        provider_dataset_id=provider_dataset_id,
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
        provider_dataset_id=provider_dataset_id,
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
        provider_dataset_id=provider_dataset_id,
    )
    assert loaded == explicitly_replaced

    assert await list_provider_refresh_policies(
        migrated_session, provider_dataset_id=provider_dataset_id, enabled=False
    ) == (explicitly_replaced,)
    assert (
        await list_provider_refresh_policies(
            migrated_session, provider_dataset_id=provider_dataset_id, enabled=True
        )
        == ()
    )


async def test_poi_cache_target_upsert_move_delete_and_links(
    migrated_session: AsyncSession,
) -> None:
    await _insert_feature(migrated_session, _FEATURE_POI, name="poi cache target 대상")

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
        feature_id=_FEATURE_POI,
        provider_dataset_id=await _dataset_id(
            migrated_session, provider=_MOIS_PROVIDER, dataset_key=_MOIS_DATASET
        ),
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
    await _insert_feature(migrated_session, _FEATURE_POI_MANUAL, name="수동 link 대상")
    await _insert_feature(migrated_session, _FEATURE_POI_RESOLVER, name="resolver link 대상")
    await _insert_feature(
        migrated_session, _FEATURE_POI_RESOLVER_NEXT, name="다음 resolver link 대상"
    )

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
        feature_id=_FEATURE_POI_RESOLVER,
    )
    assert resolver_link is not None
    manual_link = await upsert_poi_cache_target_feature_link(
        migrated_session,
        target_id=target.target_id,
        feature_id=_FEATURE_POI_MANUAL,
        relation="manual",
    )
    assert manual_link is not None

    synced = await sync_poi_cache_target_feature_links(
        migrated_session,
        target_ids=(target.target_id,),
        candidates=(
            PoiCacheTargetFeatureLinkCandidate(
                target_id=target.target_id,
                feature_id=_FEATURE_POI_RESOLVER_NEXT,
            ),
        ),
    )
    assert [link.feature_id for link in synced] == [_FEATURE_POI_RESOLVER_NEXT]

    links = {
        link.feature_id: link
        for link in await list_poi_cache_target_feature_links(
            migrated_session,
            target.target_id,
            active_only=False,
        )
    }
    assert links[_FEATURE_POI_MANUAL].active is True
    assert links[_FEATURE_POI_MANUAL].relation == "manual"
    assert links[_FEATURE_POI_RESOLVER].active is False
    assert links[_FEATURE_POI_RESOLVER_NEXT].active is True

    # resolver snapshot이 같은 (target, feature)를 재-upsert해도 활성 manual 분류를
    # 되돌리지 않는다.
    resynced = await sync_poi_cache_target_feature_links(
        migrated_session,
        target_ids=(target.target_id,),
        candidates=(
            PoiCacheTargetFeatureLinkCandidate(
                target_id=target.target_id,
                feature_id=_FEATURE_POI_MANUAL,
                relation="within_radius",
            ),
        ),
    )
    assert [link.relation for link in resynced] == ["manual"]

    # 명시적 단건 upsert의 relation은 caller가 정본이다.
    reclassified_direct = await upsert_poi_cache_target_feature_link(
        migrated_session,
        target_id=target.target_id,
        feature_id=_FEATURE_POI_MANUAL,
        relation="within_radius",
    )
    assert reclassified_direct is not None
    assert reclassified_direct.relation == "within_radius"

    restored_manual = await upsert_poi_cache_target_feature_link(
        migrated_session,
        target_id=target.target_id,
        feature_id=_FEATURE_POI_MANUAL,
        relation="manual",
    )
    assert restored_manual is not None
    assert restored_manual.relation == "manual"

    # move/delete 경로로 비활성화된 manual row는 resolver가 재분류할 수 있다.
    assert await deactivate_poi_cache_target_feature_links(
        migrated_session, target.target_id
    ) == 1

    resynced = await sync_poi_cache_target_feature_links(
        migrated_session,
        target_ids=(target.target_id,),
        candidates=(
            PoiCacheTargetFeatureLinkCandidate(
                target_id=target.target_id,
                feature_id=_FEATURE_POI_MANUAL,
                relation="within_radius",
            ),
        ),
    )
    assert [link.relation for link in resynced] == ["within_radius"]

    assert (
        await sync_poi_cache_target_feature_links(
            migrated_session,
            target_ids=(target.target_id,),
            candidates=(),
        )
        == ()
    )

    links = {
        link.feature_id: link
        for link in await list_poi_cache_target_feature_links(
            migrated_session,
            target.target_id,
            active_only=False,
        )
    }
    assert links[_FEATURE_POI_MANUAL].active is False
    assert links[_FEATURE_POI_MANUAL].relation == "within_radius"
    assert links[_FEATURE_POI_RESOLVER_NEXT].active is False


async def test_data_integrity_violation_lifecycle_and_fk_behavior(
    migrated_session: AsyncSession,
) -> None:
    await _insert_feature(migrated_session, _FEATURE_VIOLATION, name="무결성 이슈 대상")
    await _insert_source_record(migrated_session, "src:violation:1")
    provider_dataset_id = await _dataset_id(
        migrated_session, provider=_MOIS_PROVIDER, dataset_key=_MOIS_DATASET
    )

    violation = await create_data_integrity_violation(
        migrated_session,
        provider_dataset_id=provider_dataset_id,
        source_record_key="src:violation:1",
        feature_id=_FEATURE_VIOLATION,
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
    assert violation.last_seen_at >= violation.detected_at

    loaded = await get_data_integrity_violation(migrated_session, violation.issue_id)
    assert loaded == violation
    assert await list_data_integrity_violations(
        migrated_session,
        status="open",
        provider_dataset_id=provider_dataset_id,
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

    # 현재 record 포인터는 head가 소유한다 — record를 지우려면 head를 먼저 뗀다.
    await migrated_session.execute(
        text(
            "DELETE FROM provider_sync.source_entity_heads "
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
        text("DELETE FROM feature.features WHERE feature_id = CAST(:feature_id AS uuid)"),
        {"feature_id": _FEATURE_VIOLATION},
    )
    after_feature_delete = await get_data_integrity_violation(
        migrated_session, violation.issue_id
    )
    assert after_feature_delete is not None
    assert after_feature_delete.feature_id is None


async def test_integrity_finding_recurrence_tracks_latest_fk_targets(
    migrated_session: AsyncSession,
) -> None:
    provider = _MOIS_PROVIDER
    dataset_key = _MOIS_DATASET
    for suffix in ("old", "new"):
        await _insert_feature(
            migrated_session,
            _FEATURE_VIOLATION_BY_SUFFIX[suffix],
            name=f"재발 추적 대상 {suffix}",
        )
        await _insert_source_record(migrated_session, f"src:violation:{suffix}")
    provider_dataset_id = await _dataset_id(
        migrated_session, provider=provider, dataset_key=dataset_key
    )

    dedupe_key = make_integrity_finding_key(
        provider=provider,
        dataset_key=dataset_key,
        source_entity_type="license",
        source_entity_id="stable-entity",
        violation_type="missing_address",
    )

    def finding(suffix: str) -> dict[str, object]:
        return {
            "provider": provider,
            "dataset_key": dataset_key,
            "source_record_key": f"src:violation:{suffix}",
            "feature_id": _FEATURE_VIOLATION_BY_SUFFIX[suffix],
            "violation_type": "missing_address",
            "severity": "warning",
            "message": suffix,
            "payload": {"dedupe_key": dedupe_key, "occurrence_count": 1},
        }

    await sync_integrity_findings(
        migrated_session,
        provider_dataset_id=provider_dataset_id,
        findings=[finding("old")],
    )
    await sync_integrity_findings(
        migrated_session,
        provider_dataset_id=provider_dataset_id,
        findings=[finding("new")],
    )

    rows = await list_data_integrity_violations(
        migrated_session,
        provider_dataset_id=provider_dataset_id,
        violation_type="missing_address",
    )
    matched = [row for row in rows if row.payload.get("dedupe_key") == dedupe_key]
    assert len(matched) == 1
    assert matched[0].source_record_key == "src:violation:new"
    assert matched[0].feature_id == _FEATURE_VIOLATION_BY_SUFFIX["new"]
