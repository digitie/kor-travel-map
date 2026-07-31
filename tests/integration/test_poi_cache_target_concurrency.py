"""POI cache target version/lock 동시성 회귀."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.infra.feature_update_executor import _sync_cache_target_links
from kortravelmap.infra.feature_update_repo import FeatureUpdateRequest
from kortravelmap.infra.poi_cache_target_repo import (
    PoiCacheTarget,
    PoiCacheTargetConflict,
    delete_poi_cache_target,
    get_poi_cache_target_by_key,
    list_poi_cache_target_feature_links,
    upsert_poi_cache_target,
    upsert_poi_cache_target_feature_link,
)
from kortravelmap.infra.scope_repo import (
    CacheTargetFeatureMatch,
    CacheTargetScopeTarget,
    FeatureScopeRow,
    ScopeResolution,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = pytest.mark.integration


async def _revision(session: AsyncSession) -> int:
    value = await session.scalar(
        text(
            "SELECT revision FROM ops.ops_live_topic_revisions "
            "WHERE topic = 'dataset_projection'"
        )
    )
    assert value is not None
    return int(value)


async def _wait_for_lock(engine: AsyncEngine, backend_pid: int) -> None:
    async with AsyncSession(engine) as observer:
        async with asyncio.timeout(5):
            while True:
                row = (
                    await observer.execute(
                        text(
                            "SELECT wait_event_type FROM pg_stat_activity "
                            "WHERE pid = :backend_pid"
                        ),
                        {"backend_pid": backend_pid},
                    )
                ).one()
                if row.wait_event_type == "Lock":
                    return
                await asyncio.sleep(0.01)


async def _create_target(
    session: AsyncSession,
    *,
    external_system: str,
    target_key: str,
) -> PoiCacheTarget:
    return await upsert_poi_cache_target(
        session,
        external_system=external_system,
        target_key=target_key,
        lon=126.978,
        lat=37.5665,
        radius_km=5,
    )


def _link_resolution(target: PoiCacheTarget, feature_id: str) -> ScopeResolution:
    return ScopeResolution(
        scope_type="cache_target_keys",
        features=(FeatureScopeRow(feature_id=feature_id),),
        cache_targets=(
            CacheTargetScopeTarget(
                target_id=target.target_id,
                external_system=target.external_system,
                target_key=target.target_key,
                lon=target.lon,
                lat=target.lat,
                radius_km=target.radius_km,
                scope_mode=target.scope_mode,
                refresh_policy=target.refresh_policy,
                provider_overrides=target.provider_overrides,
            ),
        ),
        cache_target_matches=(
            CacheTargetFeatureMatch(
                target_id=target.target_id,
                feature_id=feature_id,
                provider=None,
                dataset_key=None,
                distance_m=0,
                relation="within_radius",
            ),
        ),
    )


def _link_request() -> FeatureUpdateRequest:
    """link 동기화 결과 event에 필요한 실제 executor request 계약을 만든다."""
    return FeatureUpdateRequest(
        request_id=str(uuid4()),
        scope_type="cache_target_keys",
        scope={"type": "cache_target_keys"},
        providers=(),
        dataset_keys=(),
        update_policy={},
        run_mode="queue",
        priority=50,
        status="running",
        matched_scope={},
        job_id=str(uuid4()),
        dagster_run_id=None,
        operator=None,
        reason=None,
        error_message=None,
        created_at=datetime.now(UTC),
        started_at=None,
        finished_at=None,
        generation=1,
    )


async def test_stale_entity_tag_after_put_is_412_and_revision_does_not_move(
    migrated_engine: AsyncEngine,
) -> None:
    suffix = uuid4().hex
    external_system = f"etag-put-{suffix}"
    target_key = f"target-{suffix}"
    try:
        async with AsyncSession(migrated_engine) as setup, setup.begin():
            stale = await _create_target(
                setup,
                external_system=external_system,
                target_key=target_key,
            )
        async with AsyncSession(migrated_engine) as writer, writer.begin():
            current = await _create_target(
                writer,
                external_system=external_system,
                target_key=target_key,
            )
        assert current.lock_version == stale.lock_version + 1

        async with AsyncSession(migrated_engine) as probe:
            baseline = await _revision(probe)
            await probe.rollback()
        async with AsyncSession(migrated_engine) as stale_writer, stale_writer.begin():
            result = await delete_poi_cache_target(
                stale_writer,
                external_system=external_system,
                target_key=target_key,
                expected_target_id=stale.target_id,
                expected_lock_version=stale.lock_version,
            )
            assert result.status == "precondition_failed"

        async with AsyncSession(migrated_engine) as probe:
            surviving = await get_poi_cache_target_by_key(
                probe,
                external_system=external_system,
                target_key=target_key,
            )
            assert surviving is not None
            assert surviving.entity_tag == current.entity_tag
            assert await _revision(probe) == baseline
    finally:
        async with AsyncSession(migrated_engine) as cleanup, cleanup.begin():
            await cleanup.execute(
                text(
                    "DELETE FROM ops.poi_cache_targets "
                    "WHERE external_system = :external_system"
                ),
                {"external_system": external_system},
            )


async def test_delete_recreate_race_maps_stale_delete_to_412(
    migrated_engine: AsyncEngine,
) -> None:
    suffix = uuid4().hex
    external_system = f"etag-recreate-{suffix}"
    target_key = f"target-{suffix}"
    try:
        async with AsyncSession(migrated_engine) as setup, setup.begin():
            stale = await _create_target(
                setup,
                external_system=external_system,
                target_key=target_key,
            )

        async with (
            AsyncSession(migrated_engine) as recreator,
            AsyncSession(migrated_engine) as stale_writer,
        ):
            await recreator.begin()
            removed = await delete_poi_cache_target(
                recreator,
                external_system=external_system,
                target_key=target_key,
                expected_target_id=stale.target_id,
                expected_lock_version=stale.lock_version,
            )
            assert removed.status == "deleted"
            recreated = await _create_target(
                recreator,
                external_system=external_system,
                target_key=target_key,
            )
            assert recreated.target_id != stale.target_id

            await stale_writer.begin()
            stale_pid = await stale_writer.scalar(text("SELECT pg_backend_pid()"))
            assert stale_pid is not None

            async def _stale_delete():
                result = await delete_poi_cache_target(
                    stale_writer,
                    external_system=external_system,
                    target_key=target_key,
                    expected_target_id=stale.target_id,
                    expected_lock_version=stale.lock_version,
                )
                await stale_writer.commit()
                return result

            stale_task = asyncio.create_task(_stale_delete())
            await _wait_for_lock(migrated_engine, int(stale_pid))
            await recreator.commit()
            stale_result = await asyncio.wait_for(stale_task, timeout=5)
            assert stale_result.status == "precondition_failed"

        async with AsyncSession(migrated_engine) as probe:
            surviving = await get_poi_cache_target_by_key(
                probe,
                external_system=external_system,
                target_key=target_key,
            )
            assert surviving is not None
            assert surviving.target_id == recreated.target_id
    finally:
        async with AsyncSession(migrated_engine) as cleanup, cleanup.begin():
            await cleanup.execute(
                text(
                    "DELETE FROM ops.poi_cache_targets "
                    "WHERE external_system = :external_system"
                ),
                {"external_system": external_system},
            )


async def test_concurrent_put_reject_race_yields_single_winner_and_conflict(
    migrated_engine: AsyncEngine,
) -> None:
    """동시 PUT(reject, 서로 다른 좌표)은 승자 1 + PoiCacheTargetConflict 1이다.

    S2-1 TOCTOU 회귀: unlocked pre-read로 moved/reject를 판정하면 패자가
    ``ON CONFLICT UPDATE``로 승자의 좌표를 조용히 덮어쓰고, 승자 좌표로 계산된
    active link가 stale 좌표의 link로 남는다. lock-first 판정에서는 패자가
    승자 commit을 기다렸다가 conflict로 거부돼야 한다.
    """
    suffix = uuid4().hex
    external_system = f"put-race-{suffix}"
    target_key = f"target-{suffix}"
    feature_id = f"feature:put-race:{suffix}"
    try:
        async with AsyncSession(migrated_engine) as setup, setup.begin():
            await setup.execute(
                text(
                    "INSERT INTO feature.features (feature_id, kind, name, category) "
                    "VALUES (:feature_id, 'place', :feature_id, 'test')"
                ),
                {"feature_id": feature_id},
            )

        async with (
            AsyncSession(migrated_engine) as winner,
            AsyncSession(migrated_engine) as loser,
        ):
            await winner.begin()
            created = await upsert_poi_cache_target(
                winner,
                external_system=external_system,
                target_key=target_key,
                lon=126.978,
                lat=37.5665,
                radius_km=5,
                on_conflict="reject",
            )
            winner_link = await upsert_poi_cache_target_feature_link(
                winner,
                target_id=created.target_id,
                feature_id=feature_id,
            )
            assert winner_link is not None

            await loser.begin()
            loser_pid = await loser.scalar(text("SELECT pg_backend_pid()"))
            assert loser_pid is not None

            async def _losing_put() -> str:
                try:
                    await upsert_poi_cache_target(
                        loser,
                        external_system=external_system,
                        target_key=target_key,
                        lon=127.001,
                        lat=37.401,
                        radius_km=5,
                        on_conflict="reject",
                    )
                except PoiCacheTargetConflict:
                    await loser.rollback()
                    return "conflict"
                await loser.commit()
                return "success"

            loser_task = asyncio.create_task(_losing_put())
            await _wait_for_lock(migrated_engine, int(loser_pid))
            await winner.commit()
            outcome = await asyncio.wait_for(loser_task, timeout=5)
            assert outcome == "conflict"

        async with AsyncSession(migrated_engine) as probe:
            surviving = await get_poi_cache_target_by_key(
                probe,
                external_system=external_system,
                target_key=target_key,
            )
            assert surviving is not None
            assert surviving.target_id == created.target_id
            assert surviving.coord_key == created.coord_key
            links = await list_poi_cache_target_feature_links(
                probe,
                created.target_id,
                active_only=False,
            )
            # 승자 좌표로 계산된 link만 active — stale 좌표로 남는 active link가 없다.
            assert [link.feature_id for link in links if link.active] == [feature_id]
    finally:
        async with AsyncSession(migrated_engine) as cleanup, cleanup.begin():
            await cleanup.execute(
                text(
                    "DELETE FROM ops.poi_cache_targets "
                    "WHERE external_system = :external_system"
                ),
                {"external_system": external_system},
            )
            await cleanup.execute(
                text("DELETE FROM feature.features WHERE feature_id = :feature_id"),
                {"feature_id": feature_id},
            )


async def test_executor_link_sync_wins_parent_lock_then_delete_leaves_no_active_link(
    migrated_engine: AsyncEngine,
) -> None:
    suffix = uuid4().hex
    external_system = f"link-delete-{suffix}"
    target_key = f"target-{suffix}"
    feature_id = f"feature:link-delete:{suffix}"
    try:
        async with AsyncSession(migrated_engine) as setup, setup.begin():
            await setup.execute(
                text(
                    "INSERT INTO feature.features (feature_id, kind, name, category) "
                    "VALUES (:feature_id, 'place', :feature_id, 'test')"
                ),
                {"feature_id": feature_id},
            )
            target = await _create_target(
                setup,
                external_system=external_system,
                target_key=target_key,
            )
            link = await upsert_poi_cache_target_feature_link(
                setup,
                target_id=target.target_id,
                feature_id=feature_id,
            )
            assert link is not None
        resolution = _link_resolution(target, feature_id)

        async with (
            AsyncSession(migrated_engine) as syncer,
            AsyncSession(migrated_engine) as deleter,
        ):
            await syncer.begin()
            await _sync_cache_target_links(
                syncer,
                resolution,
                request=_link_request(),
            )
            await deleter.begin()
            deleter_pid = await deleter.scalar(text("SELECT pg_backend_pid()"))
            assert deleter_pid is not None

            async def _delete():
                result = await delete_poi_cache_target(
                    deleter,
                    external_system=external_system,
                    target_key=target_key,
                    expected_target_id=target.target_id,
                    expected_lock_version=target.lock_version,
                )
                await deleter.commit()
                return result

            delete_task = asyncio.create_task(_delete())
            await _wait_for_lock(migrated_engine, int(deleter_pid))
            await syncer.commit()
            deleted = await asyncio.wait_for(delete_task, timeout=5)
            assert deleted.status == "deleted"

        async with AsyncSession(migrated_engine) as probe:
            links = await list_poi_cache_target_feature_links(
                probe,
                target.target_id,
                active_only=False,
            )
            assert links
            assert not any(link.active for link in links)
    finally:
        async with AsyncSession(migrated_engine) as cleanup, cleanup.begin():
            await cleanup.execute(
                text("DELETE FROM feature.features WHERE feature_id = :feature_id"),
                {"feature_id": feature_id},
            )
            await cleanup.execute(
                text(
                    "DELETE FROM ops.poi_cache_targets "
                    "WHERE external_system = :external_system"
                ),
                {"external_system": external_system},
            )


async def test_delete_wins_parent_lock_then_executor_sync_skips_inactive_parent(
    migrated_engine: AsyncEngine,
) -> None:
    suffix = uuid4().hex
    external_system = f"delete-link-{suffix}"
    target_key = f"target-{suffix}"
    feature_id = f"feature:delete-link:{suffix}"
    try:
        async with AsyncSession(migrated_engine) as setup, setup.begin():
            await setup.execute(
                text(
                    "INSERT INTO feature.features (feature_id, kind, name, category) "
                    "VALUES (:feature_id, 'place', :feature_id, 'test')"
                ),
                {"feature_id": feature_id},
            )
            target = await _create_target(
                setup,
                external_system=external_system,
                target_key=target_key,
            )
            link = await upsert_poi_cache_target_feature_link(
                setup,
                target_id=target.target_id,
                feature_id=feature_id,
            )
            assert link is not None
        resolution = _link_resolution(target, feature_id)

        async with (
            AsyncSession(migrated_engine) as deleter,
            AsyncSession(migrated_engine) as syncer,
        ):
            await deleter.begin()
            deleted = await delete_poi_cache_target(
                deleter,
                external_system=external_system,
                target_key=target_key,
                expected_target_id=target.target_id,
                expected_lock_version=target.lock_version,
            )
            assert deleted.status == "deleted"

            await syncer.begin()
            syncer_pid = await syncer.scalar(text("SELECT pg_backend_pid()"))
            assert syncer_pid is not None

            async def _sync() -> None:
                await _sync_cache_target_links(
                    syncer,
                    resolution,
                    request=_link_request(),
                )
                await syncer.commit()

            sync_task = asyncio.create_task(_sync())
            await _wait_for_lock(migrated_engine, int(syncer_pid))
            await deleter.commit()
            await asyncio.wait_for(sync_task, timeout=5)

        async with AsyncSession(migrated_engine) as probe:
            links = await list_poi_cache_target_feature_links(
                probe,
                target.target_id,
                active_only=False,
            )
            assert links
            assert not any(link.active for link in links)
    finally:
        async with AsyncSession(migrated_engine) as cleanup, cleanup.begin():
            await cleanup.execute(
                text("DELETE FROM feature.features WHERE feature_id = :feature_id"),
                {"feature_id": feature_id},
            )
            await cleanup.execute(
                text(
                    "DELETE FROM ops.poi_cache_targets "
                    "WHERE external_system = :external_system"
                ),
                {"external_system": external_system},
            )
