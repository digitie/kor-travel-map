"""ops-live topic revision statement trigger 통합 테스트."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from kortravelmap.api.routers.ops_live import collect_live_topic_snapshots
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = pytest.mark.integration

_INSERT_INTEGRITY_SQL = """
INSERT INTO ops.data_integrity_violations (
  issue_id, dataset_key, violation_type, severity, message
)
VALUES (
  CAST(:key AS uuid), 'live-projection', 'live_projection_test',
  'warning', 'ops-live projection revision 통합 테스트'
)
"""

_INSERT_POI_SQL = """
INSERT INTO ops.poi_cache_targets (
  external_system, target_key, lon, lat, coord, coord_key, radius_km
)
VALUES (
  'live-projection', :target_key, 126.978, 37.5665,
  x_extension.ST_SetSRID(
    x_extension.ST_MakePoint(126.978, 37.5665), 4326
  ),
  '126.978000:37.566500:p6', 5.0
)
"""


async def _revision(session: AsyncSession, topic: str) -> int:
    value = await session.scalar(
        text(
            "SELECT revision FROM ops.ops_live_topic_revisions "
            "WHERE topic = :topic"
        ),
        {"topic": topic},
    )
    assert value is not None
    return int(value)


async def _wait_for_backend_lock(
    engine: AsyncEngine,
    backend_pid: int,
) -> str:
    async with AsyncSession(engine) as observer:
        async with asyncio.timeout(5):
            while True:
                row = (
                    await observer.execute(
                        text(
                            "SELECT wait_event_type, wait_event "
                            "FROM pg_stat_activity WHERE pid = :backend_pid"
                        ),
                        {"backend_pid": backend_pid},
                    )
                ).one()
                if row.wait_event_type == "Lock":
                    assert row.wait_event is not None
                    return str(row.wait_event)
                await asyncio.sleep(0.01)


async def test_ops_live_topic_revision_rolls_back_with_source_write(
    migrated_engine: AsyncEngine,
) -> None:
    provider = f"rollback-{uuid4().hex}"
    async with AsyncSession(migrated_engine) as session:
        baseline = await _revision(session, "provider_sync")
        await session.rollback()
        await session.execute(
            text(
                "INSERT INTO ops.provider_refresh_policies "
                "(provider, dataset_key, source_kind) "
                "VALUES (:provider, 'dataset', 'manual')"
            ),
            {"provider": provider},
        )
        assert await _revision(session, "provider_sync") == baseline + 1
        await session.rollback()

    async with AsyncSession(migrated_engine) as session:
        assert await _revision(session, "provider_sync") == baseline
        count = await session.scalar(
            text(
                "SELECT COUNT(*) FROM ops.provider_refresh_policies "
                "WHERE provider = :provider"
            ),
            {"provider": provider},
        )
        assert count == 0


async def test_dataset_projection_revision_rolls_back_with_source_write(
    migrated_engine: AsyncEngine,
) -> None:
    issue_id = str(uuid4())
    async with AsyncSession(migrated_engine) as session:
        baseline = await _revision(session, "dataset_projection")
        await session.rollback()
        await session.execute(
            text(_INSERT_INTEGRITY_SQL),
            {"key": issue_id},
        )
        assert await _revision(session, "dataset_projection") == baseline + 1
        await session.rollback()

    async with AsyncSession(migrated_engine) as session:
        assert await _revision(session, "dataset_projection") == baseline
        count = await session.scalar(
            text(
                "SELECT COUNT(*) FROM ops.data_integrity_violations "
                "WHERE issue_id = CAST(:key AS uuid)"
            ),
            {"key": issue_id},
        )
        assert count == 0


async def test_dataset_projection_revision_rolls_back_with_poi_target_write(
    migrated_engine: AsyncEngine,
) -> None:
    target_key = f"rollback-target-{uuid4().hex}"
    async with AsyncSession(migrated_engine) as session:
        baseline = await _revision(session, "dataset_projection")
        await session.rollback()
        await session.execute(
            text(_INSERT_POI_SQL),
            {"target_key": target_key},
        )
        assert await _revision(session, "dataset_projection") == baseline + 1
        await session.rollback()

    async with AsyncSession(migrated_engine) as session:
        assert await _revision(session, "dataset_projection") == baseline
        count = await session.scalar(
            text(
                "SELECT COUNT(*) FROM ops.poi_cache_targets "
                "WHERE external_system = 'live-projection' "
                "AND target_key = :target_key"
            ),
            {"target_key": target_key},
        )
        assert count == 0


async def test_each_ops_live_source_bumps_its_topic_once(
    migrated_session: AsyncSession,
) -> None:
    suffix = uuid4().hex
    provider_revision = await _revision(migrated_session, "provider_sync")
    dataset_revision = await _revision(migrated_session, "dataset_projection")
    schedule_revision = await _revision(migrated_session, "dagster_schedules")

    await migrated_session.execute(
        text(
            "INSERT INTO provider_sync.provider_sync_state "
            "(provider, dataset_key, sync_scope) "
            "VALUES (:provider, 'dataset', 'default')"
        ),
        {"provider": f"state-{suffix}"},
    )
    provider_revision += 1
    assert await _revision(migrated_session, "provider_sync") == provider_revision

    await migrated_session.execute(
        text(
            "INSERT INTO ops.provider_refresh_policies "
            "(provider, dataset_key, source_kind) "
            "VALUES (:provider, 'dataset', 'manual')"
        ),
        {"provider": f"policy-{suffix}"},
    )
    provider_revision += 1
    assert await _revision(migrated_session, "provider_sync") == provider_revision

    await migrated_session.execute(
        text(_INSERT_INTEGRITY_SQL),
        {"key": str(uuid4())},
    )
    dataset_revision += 1
    assert (
        await _revision(migrated_session, "dataset_projection")
        == dataset_revision
    )

    await migrated_session.execute(
        text(_INSERT_POI_SQL),
        {"target_key": f"target-{suffix}"},
    )
    dataset_revision += 1
    assert (
        await _revision(migrated_session, "dataset_projection")
        == dataset_revision
    )

    schedule_name = f"schedule-{suffix}"
    await migrated_session.execute(
        text(
            "INSERT INTO ops.dagster_schedule_overrides "
            "(schedule_name, cron_schedule, updated_by) "
            "VALUES (:schedule_name, '0 * * * *', 'integration-admin')"
        ),
        {"schedule_name": schedule_name},
    )
    schedule_revision += 1
    assert await _revision(migrated_session, "dagster_schedules") == schedule_revision

    command_id = str(uuid4())
    await migrated_session.execute(
        text(
            "INSERT INTO ops.dagster_schedule_audit_events "
            "(command_id, schedule_name, command, phase, actor, details) "
            "VALUES (CAST(:command_id AS uuid), :schedule_name, 'run', "
            "'requested', 'integration-admin', '{}'::jsonb)"
        ),
        {"command_id": command_id, "schedule_name": schedule_name},
    )
    schedule_revision += 1
    assert await _revision(migrated_session, "dagster_schedules") == schedule_revision

    await migrated_session.execute(
        text(
            "INSERT INTO ops.dagster_schedule_active_claims "
            "(command_id, schedule_name, created_at, resolvable_after) "
            "VALUES (CAST(:command_id AS uuid), :schedule_name, "
            "clock_timestamp() - interval '10 minutes', "
            "clock_timestamp() - interval '5 minutes')"
        ),
        {"command_id": command_id, "schedule_name": schedule_name},
    )
    await migrated_session.execute(
        text(
            "INSERT INTO ops.dagster_schedule_claim_resolutions "
            "(command_id, schedule_name, resolution, actor, reason, details) "
            "VALUES (CAST(:command_id AS uuid), :schedule_name, "
            "'confirmed_not_applied', 'integration-admin', "
            "'integration verification', '{}'::jsonb)"
        ),
        {"command_id": command_id, "schedule_name": schedule_name},
    )
    schedule_revision += 1
    assert await _revision(migrated_session, "dagster_schedules") == schedule_revision


async def test_provider_revision_serializes_late_commit_writers(
    migrated_engine: AsyncEngine,
) -> None:
    suffix = uuid4().hex
    policy_provider = f"late-policy-{suffix}"
    state_provider = f"late-state-{suffix}"
    async with AsyncSession(migrated_engine) as session:
        baseline = await _revision(session, "provider_sync")
        await session.rollback()

    second_task: asyncio.Task[None] | None = None
    try:
        async with (
            AsyncSession(migrated_engine) as first,
            AsyncSession(migrated_engine) as second,
        ):
            try:
                second_pid = await second.scalar(text("SELECT pg_backend_pid()"))
                assert second_pid is not None
                await first.execute(
                    text(
                        "INSERT INTO ops.provider_refresh_policies "
                        "(provider, dataset_key, source_kind) "
                        "VALUES (:provider, 'dataset', 'manual')"
                    ),
                    {"provider": policy_provider},
                )

                async def _second_writer() -> None:
                    await second.execute(
                        text(
                            "INSERT INTO provider_sync.provider_sync_state "
                            "(provider, dataset_key, sync_scope) "
                            "VALUES (:provider, 'dataset', 'default')"
                        ),
                        {"provider": state_provider},
                    )
                    await second.commit()

                second_task = asyncio.create_task(_second_writer())
                wait_event = await _wait_for_backend_lock(
                    migrated_engine,
                    int(second_pid),
                )
                assert wait_event in {"transactionid", "tuple"}
                assert not second_task.done()
                await first.commit()
                await asyncio.wait_for(second_task, timeout=5)
            finally:
                if second_task is not None:
                    if not second_task.done():
                        second_task.cancel()
                    await asyncio.gather(second_task, return_exceptions=True)

        async with AsyncSession(migrated_engine) as session:
            assert await _revision(session, "provider_sync") == baseline + 2
    finally:
        async with AsyncSession(migrated_engine) as cleanup:
            await cleanup.execute(
                text(
                    "DELETE FROM ops.provider_refresh_policies "
                    "WHERE provider = :provider"
                ),
                {"provider": policy_provider},
            )
            await cleanup.execute(
                text(
                    "DELETE FROM provider_sync.provider_sync_state "
                    "WHERE provider = :provider"
                ),
                {"provider": state_provider},
            )
            await cleanup.commit()


async def test_dataset_projection_revision_serializes_late_commit_writers(
    migrated_engine: AsyncEngine,
) -> None:
    suffix = uuid4().hex
    issue_id = str(uuid4())
    target_key = f"lock-target-{suffix}"
    async with AsyncSession(migrated_engine) as session:
        baseline = await _revision(session, "dataset_projection")
        await session.rollback()

    second_task: asyncio.Task[None] | None = None
    try:
        async with (
            AsyncSession(migrated_engine) as first,
            AsyncSession(migrated_engine) as second,
        ):
            try:
                second_pid = await second.scalar(text("SELECT pg_backend_pid()"))
                assert second_pid is not None
                await first.execute(
                    text(_INSERT_INTEGRITY_SQL),
                    {"key": issue_id},
                )

                async def _second_writer() -> None:
                    await second.execute(
                        text(_INSERT_POI_SQL),
                        {"target_key": target_key},
                    )
                    await second.commit()

                second_task = asyncio.create_task(_second_writer())
                wait_event = await _wait_for_backend_lock(
                    migrated_engine,
                    int(second_pid),
                )
                assert wait_event in {"transactionid", "tuple"}
                assert not second_task.done()
                await first.commit()
                await asyncio.wait_for(second_task, timeout=5)
            finally:
                if second_task is not None:
                    if not second_task.done():
                        second_task.cancel()
                    await asyncio.gather(second_task, return_exceptions=True)

        async with AsyncSession(migrated_engine) as session:
            assert (
                await _revision(session, "dataset_projection") == baseline + 2
            )
    finally:
        async with AsyncSession(migrated_engine) as cleanup:
            await cleanup.execute(
                text(
                    "DELETE FROM ops.data_integrity_violations "
                    "WHERE issue_id = CAST(:key AS uuid)"
                ),
                {"key": issue_id},
            )
            await cleanup.execute(
                text(
                    "DELETE FROM ops.poi_cache_targets "
                    "WHERE external_system = 'live-projection' "
                    "AND target_key = :target_key"
                ),
                {"target_key": target_key},
            )
            await cleanup.commit()


async def test_schedule_revision_lock_wait_preserves_two_increments(
    migrated_engine: AsyncEngine,
) -> None:
    suffix = uuid4().hex
    first_name = f"lock-first-{suffix}"
    second_name = f"lock-second-{suffix}"
    async with AsyncSession(migrated_engine) as session:
        baseline = await _revision(session, "dagster_schedules")
        await session.rollback()

    second_task: asyncio.Task[None] | None = None
    try:
        async with (
            AsyncSession(migrated_engine) as first,
            AsyncSession(migrated_engine) as second,
        ):
            try:
                second_pid = await second.scalar(text("SELECT pg_backend_pid()"))
                assert second_pid is not None
                await first.execute(
                    text(
                        "INSERT INTO ops.dagster_schedule_overrides "
                        "(schedule_name, cron_schedule, updated_by) "
                        "VALUES (:schedule_name, '0 * * * *', 'integration-admin')"
                    ),
                    {"schedule_name": first_name},
                )

                async def _second_writer() -> None:
                    await second.execute(
                        text(
                            "INSERT INTO ops.dagster_schedule_overrides "
                            "(schedule_name, cron_schedule, updated_by) "
                            "VALUES (:schedule_name, '5 * * * *', "
                            "'integration-admin')"
                        ),
                        {"schedule_name": second_name},
                    )
                    await second.commit()

                second_task = asyncio.create_task(_second_writer())
                wait_event = await _wait_for_backend_lock(
                    migrated_engine,
                    int(second_pid),
                )
                assert wait_event in {"transactionid", "tuple"}
                assert not second_task.done()
                await first.commit()
                await asyncio.wait_for(second_task, timeout=5)
            finally:
                if second_task is not None:
                    if not second_task.done():
                        second_task.cancel()
                    await asyncio.gather(second_task, return_exceptions=True)

        async with AsyncSession(migrated_engine) as session:
            assert await _revision(session, "dagster_schedules") == baseline + 2
    finally:
        async with AsyncSession(migrated_engine) as cleanup:
            await cleanup.execute(
                text(
                    "DELETE FROM ops.dagster_schedule_overrides "
                    "WHERE schedule_name IN (:first_name, :second_name)"
                ),
                {"first_name": first_name, "second_name": second_name},
            )
            await cleanup.commit()


async def test_ops_live_revision_trigger_mapping_and_pg_snapshots(
    migrated_engine: AsyncEngine,
) -> None:
    expected = {
        "trg_provider_sync_state_ops_live_revision": (
            "provider_sync.provider_sync_state",
            "provider_sync",
        ),
        "trg_provider_refresh_policies_ops_live_revision": (
            "ops.provider_refresh_policies",
            "provider_sync",
        ),
        "trg_data_integrity_violations_ops_live_revision": (
            "ops.data_integrity_violations",
            "dataset_projection",
        ),
        "trg_poi_cache_targets_ops_live_revision": (
            "ops.poi_cache_targets",
            "dataset_projection",
        ),
        "trg_dagster_schedule_overrides_ops_live_revision": (
            "ops.dagster_schedule_overrides",
            "dagster_schedules",
        ),
        "trg_dagster_schedule_audit_ops_live_revision": (
            "ops.dagster_schedule_audit_events",
            "dagster_schedules",
        ),
        "trg_dagster_schedule_claim_resolution_ops_live_revision": (
            "ops.dagster_schedule_claim_resolutions",
            "dagster_schedules",
        ),
    }
    async with AsyncSession(migrated_engine) as session:
        result = await session.execute(
            text(
                "SELECT trigger.tgname, namespace.nspname || '.' || relation.relname "
                "AS source_table, pg_get_triggerdef(trigger.oid) AS definition "
                "FROM pg_trigger AS trigger "
                "JOIN pg_class AS relation ON relation.oid = trigger.tgrelid "
                "JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace "
                "WHERE NOT trigger.tgisinternal "
                "AND trigger.tgname LIKE 'trg_%_ops_live_revision'"
            )
        )
        mappings = {
            row.tgname: (row.source_table, row.definition) for row in result
        }
        assert set(mappings) == set(expected)
        for trigger_name, (source_table, topic) in expected.items():
            mapped_table, definition = mappings[trigger_name]
            assert mapped_table == source_table
            assert "FOR EACH STATEMENT" in definition
            assert f"'{topic}'" in definition

        expected_revisions = {
            topic: await _revision(session, topic)
            for topic in (
                "provider_sync",
                "dataset_projection",
                "dagster_schedules",
            )
        }
        await session.rollback()

    async with AsyncSession(migrated_engine) as session:
        snapshots = await collect_live_topic_snapshots(
            session,
            {
                "provider_sync",
                "dataset_projection",
                "dagster_schedules",
                "dagster_runs",
            },
        )

    assert snapshots["provider_sync"].data["live_revision"] == (
        expected_revisions["provider_sync"]
    )
    assert snapshots["dataset_projection"].data["live_revision"] == (
        expected_revisions["dataset_projection"]
    )
    assert snapshots["dagster_schedules"].data["live_revision"] == (
        expected_revisions["dagster_schedules"]
    )
    run_ids = snapshots["dagster_runs"].data["run_ids"]
    assert len(run_ids) == len(set(run_ids))

    async with AsyncSession(migrated_engine) as session:
        repeated = await collect_live_topic_snapshots(session, {"dagster_runs"})
    assert repeated["dagster_runs"].data["run_ids"] == run_ids
