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

# T-VN-33: dataset 자연키 사본이 사라졌다 — 소유 dataset은 provider_dataset_id 하나뿐.
_INSERT_INTEGRITY_SQL = """
INSERT INTO ops.data_integrity_violations (
  issue_id, provider_dataset_id, violation_type, severity, message
)
VALUES (
  CAST(:key AS uuid), :provider_dataset_id, 'live_projection_test',
  'warning', 'ops-live projection revision 통합 테스트'
)
"""

_INSERT_REFRESH_POLICY_SQL = """
INSERT INTO ops.provider_refresh_policies (provider_dataset_id, source_kind)
VALUES (:provider_dataset_id, 'manual')
"""

_INSERT_SYNC_STATE_SQL = """
INSERT INTO provider_sync.provider_sync_state
  (provider_dataset_id, sync_scope, operation_key)
VALUES (:provider_dataset_id, :sync_scope, :operation_key)
"""

# 테스트 전용 catalog 행 — 실행 membership identity는
# ``provider_dataset_id + sync_scope + operation_key`` triple이다(ADR-088).
_PROBE_SYNC_SCOPE = "dataset_wide"
_PROBE_OPERATION_KEY = "live_projection_probe"

_SEED_DATASET_SQL = """
INSERT INTO provider_sync.provider_datasets (
  provider, dataset_key, display_name, source_kind, is_active, capabilities
)
SELECT :provider, 'dataset', :provider, 'system', true,
       jsonb_build_object('schema_version', 1, 'produces', '[]'::jsonb,
                          'extensions', '{}'::jsonb)
ON CONFLICT (provider, dataset_key) DO UPDATE SET display_name = EXCLUDED.display_name
RETURNING provider_dataset_id
"""

_SEED_OPERATION_SQL = """
INSERT INTO provider_sync.provider_dataset_operations (
  provider_dataset_id, operation_key, operation_kind, is_enabled, config
)
VALUES (:provider_dataset_id, :operation_key, 'refresh', true, '{}'::jsonb)
ON CONFLICT DO NOTHING
"""

_SEED_SCOPE_SQL = """
INSERT INTO provider_sync.provider_dataset_operation_scopes (
  provider_dataset_id, sync_scope, operation_key, operation_kind
)
VALUES (:provider_dataset_id, :sync_scope, :operation_key, 'refresh')
ON CONFLICT DO NOTHING
"""


async def _seed_operable_dataset(session: AsyncSession, *, provider: str) -> int:
    """dataset + enabled refresh operation + scope를 한 벌 심고 id를 돌려준다.

    ``provider_datasets``/``provider_dataset_operations``/``..._scopes``에는
    ops-live revision 트리거가 없다 — seed 자체는 topic revision을 올리지 않는다.
    """
    dataset_id = int(
        (
            await session.execute(text(_SEED_DATASET_SQL), {"provider": provider})
        ).scalar_one()
    )
    params = {
        "provider_dataset_id": dataset_id,
        "operation_key": _PROBE_OPERATION_KEY,
        "sync_scope": _PROBE_SYNC_SCOPE,
    }
    await session.execute(text(_SEED_OPERATION_SQL), params)
    await session.execute(text(_SEED_SCOPE_SQL), params)
    return dataset_id


async def _drop_seeded_dataset(session: AsyncSession, dataset_id: int) -> None:
    """seed한 dataset 한 벌을 FK 역순으로 지운다 (모두 ON DELETE RESTRICT)."""
    params = {"provider_dataset_id": dataset_id}
    for statement in (
        "DELETE FROM provider_sync.provider_sync_state "
        "WHERE provider_dataset_id = :provider_dataset_id",
        "DELETE FROM ops.provider_refresh_policies "
        "WHERE provider_dataset_id = :provider_dataset_id",
        "DELETE FROM provider_sync.provider_dataset_operation_scopes "
        "WHERE provider_dataset_id = :provider_dataset_id",
        "DELETE FROM provider_sync.provider_dataset_operations "
        "WHERE provider_dataset_id = :provider_dataset_id",
        "DELETE FROM provider_sync.provider_datasets "
        "WHERE provider_dataset_id = :provider_dataset_id",
    ):
        await session.execute(text(statement), params)

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
    """이 transaction의 증가까지 포함한 값(458: 원본 trigger는 표식만 남기고 commit 직전에 올린다).

    receipt 작성자(``get_dataset_projection_revision``)와 같이 표식을 먼저 적용하고 읽는다.
    """
    await session.execute(
        text("SET CONSTRAINTS ops.trg_ops_live_topic_pending_apply IMMEDIATE")
    )
    value = await session.scalar(
        text(
            "SELECT revision FROM ops.ops_live_topic_revisions "
            "WHERE topic = :topic"
        ),
        {"topic": topic},
    )
    await session.execute(
        text("SET CONSTRAINTS ops.trg_ops_live_topic_pending_apply DEFERRED")
    )
    assert value is not None
    return int(value)


async def test_ops_live_topic_revision_rolls_back_with_source_write(
    migrated_engine: AsyncEngine,
) -> None:
    provider = f"rollback-{uuid4().hex}"
    async with AsyncSession(migrated_engine) as session:
        baseline = await _revision(session, "provider_sync")
        await session.rollback()
        dataset_id = await _seed_operable_dataset(session, provider=provider)
        await session.execute(
            text(_INSERT_REFRESH_POLICY_SQL),
            {"provider_dataset_id": dataset_id},
        )
        assert await _revision(session, "provider_sync") == baseline + 1
        await session.rollback()

    async with AsyncSession(migrated_engine) as session:
        assert await _revision(session, "provider_sync") == baseline
        count = await session.scalar(
            text(
                "SELECT COUNT(*) FROM ops.provider_refresh_policies "
                "WHERE provider_dataset_id = :provider_dataset_id"
            ),
            {"provider_dataset_id": dataset_id},
        )
        assert count == 0


async def test_dataset_projection_revision_rolls_back_with_source_write(
    migrated_engine: AsyncEngine,
) -> None:
    issue_id = str(uuid4())
    provider = f"rollback-integrity-{uuid4().hex}"
    async with AsyncSession(migrated_engine) as session:
        baseline = await _revision(session, "dataset_projection")
        await session.rollback()
        dataset_id = await _seed_operable_dataset(session, provider=provider)
        await session.execute(
            text(_INSERT_INTEGRITY_SQL),
            {"key": issue_id, "provider_dataset_id": dataset_id},
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
    # catalog seed는 revision 트리거가 없는 테이블만 건드린다 — baseline 이전에 심는다.
    state_dataset_id = await _seed_operable_dataset(
        migrated_session, provider=f"state-{suffix}"
    )
    policy_dataset_id = await _seed_operable_dataset(
        migrated_session, provider=f"policy-{suffix}"
    )
    integrity_dataset_id = await _seed_operable_dataset(
        migrated_session, provider=f"integrity-{suffix}"
    )

    provider_revision = await _revision(migrated_session, "provider_sync")
    dataset_revision = await _revision(migrated_session, "dataset_projection")
    schedule_revision = await _revision(migrated_session, "dagster_schedules")

    await migrated_session.execute(
        text(_INSERT_SYNC_STATE_SQL),
        {
            "provider_dataset_id": state_dataset_id,
            "sync_scope": _PROBE_SYNC_SCOPE,
            "operation_key": _PROBE_OPERATION_KEY,
        },
    )
    provider_revision += 1
    assert await _revision(migrated_session, "provider_sync") == provider_revision

    await migrated_session.execute(
        text(_INSERT_REFRESH_POLICY_SQL),
        {"provider_dataset_id": policy_dataset_id},
    )
    provider_revision += 1
    assert await _revision(migrated_session, "provider_sync") == provider_revision

    await migrated_session.execute(
        text(_INSERT_INTEGRITY_SQL),
        {"key": str(uuid4()), "provider_dataset_id": integrity_dataset_id},
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


async def test_provider_revision_counts_late_commit_writers_without_blocking(
    migrated_engine: AsyncEngine,
) -> None:
    suffix = uuid4().hex
    policy_provider = f"late-policy-{suffix}"
    state_provider = f"late-state-{suffix}"
    # 두 writer가 서로 다른 transaction에서 보려면 catalog seed는 먼저 commit한다.
    async with AsyncSession(migrated_engine) as setup:
        policy_dataset_id = await _seed_operable_dataset(
            setup, provider=policy_provider
        )
        state_dataset_id = await _seed_operable_dataset(setup, provider=state_provider)
        await setup.commit()

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
                    text(_INSERT_REFRESH_POLICY_SQL),
                    {"provider_dataset_id": policy_dataset_id},
                )

                async def _second_writer() -> None:
                    await second.execute(
                        text(_INSERT_SYNC_STATE_SQL),
                        {
                            "provider_dataset_id": state_dataset_id,
                            "sync_scope": _PROBE_SYNC_SCOPE,
                            "operation_key": _PROBE_OPERATION_KEY,
                        },
                    )
                    await second.commit()

                # 458: 같은 topic의 다른 writer는 이 transaction이 열려 있는 동안 기다리지
                # 않는다 — topic 행은 commit 직전에만 잡힌다.
                second_task = asyncio.create_task(_second_writer())
                await asyncio.wait_for(asyncio.shield(second_task), timeout=5)
                async with AsyncSession(migrated_engine) as observer:
                    assert await _revision(observer, "provider_sync") == baseline + 1
                # 먼저 시작해 나중에 commit해도 그 commit에서 값이 오른다(late commit 감지).
                await first.commit()
            finally:
                if second_task is not None:
                    if not second_task.done():
                        second_task.cancel()
                    await asyncio.gather(second_task, return_exceptions=True)

        async with AsyncSession(migrated_engine) as session:
            assert await _revision(session, "provider_sync") == baseline + 2
    finally:
        async with AsyncSession(migrated_engine) as cleanup:
            await _drop_seeded_dataset(cleanup, policy_dataset_id)
            await _drop_seeded_dataset(cleanup, state_dataset_id)
            await cleanup.commit()


async def test_dataset_projection_revision_counts_late_commit_writers_without_blocking(
    migrated_engine: AsyncEngine,
) -> None:
    suffix = uuid4().hex
    issue_id = str(uuid4())
    target_key = f"lock-target-{suffix}"
    integrity_provider = f"lock-integrity-{suffix}"
    async with AsyncSession(migrated_engine) as setup:
        integrity_dataset_id = await _seed_operable_dataset(
            setup, provider=integrity_provider
        )
        await setup.commit()

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
                    {"key": issue_id, "provider_dataset_id": integrity_dataset_id},
                )

                async def _second_writer() -> None:
                    await second.execute(
                        text(_INSERT_POI_SQL),
                        {"target_key": target_key},
                    )
                    await second.commit()

                # 458: 같은 topic의 다른 writer는 이 transaction이 열려 있는 동안 기다리지
                # 않는다 — topic 행은 commit 직전에만 잡힌다.
                second_task = asyncio.create_task(_second_writer())
                await asyncio.wait_for(asyncio.shield(second_task), timeout=5)
                async with AsyncSession(migrated_engine) as observer:
                    assert await _revision(observer, "dataset_projection") == baseline + 1
                # 먼저 시작해 나중에 commit해도 그 commit에서 값이 오른다(late commit 감지).
                await first.commit()
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
            await _drop_seeded_dataset(cleanup, integrity_dataset_id)
            await cleanup.commit()


async def test_schedule_revision_counts_late_commit_writers_without_blocking(
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

                # 458: 같은 topic의 다른 writer는 이 transaction이 열려 있는 동안 기다리지
                # 않는다 — topic 행은 commit 직전에만 잡힌다.
                second_task = asyncio.create_task(_second_writer())
                await asyncio.wait_for(asyncio.shield(second_task), timeout=5)
                async with AsyncSession(migrated_engine) as observer:
                    assert await _revision(observer, "dagster_schedules") == baseline + 1
                # 먼저 시작해 나중에 commit해도 그 commit에서 값이 오른다(late commit 감지).
                await first.commit()
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


async def _committed_revision(engine: AsyncEngine, topic: str) -> int:
    """다른 연결에 보이는(commit된) 값 — 표식을 적용하지 않는다."""

    async with AsyncSession(engine) as observer:
        value = await observer.scalar(
            text("SELECT revision FROM ops.ops_live_topic_revisions WHERE topic = :topic"),
            {"topic": topic},
        )
    assert value is not None
    return int(value)


async def _pending_rows(engine: AsyncEngine) -> int:
    async with AsyncSession(engine) as observer:
        value = await observer.scalar(text("SELECT count(*) FROM ops.ops_live_topic_pending"))
    return int(value or 0)


async def test_one_transaction_bumps_each_topic_once_at_commit_and_leaves_no_marker(
    migrated_engine: AsyncEngine,
) -> None:
    """458: 같은 transaction이 같은 topic 원본을 몇 번 써도 commit당 +1이고 표식은 남지 않는다."""

    baseline = await _committed_revision(migrated_engine, "provider_sync")
    async with AsyncSession(migrated_engine) as writer, writer.begin():
        for _ in range(3):
            await writer.execute(
                text(
                    "UPDATE provider_sync.provider_sync_state "
                    "SET updated_at = updated_at WHERE false"
                )
            )
        # commit 전에는 다른 연결에 아무 변화도 보이지 않는다.
        assert await _committed_revision(migrated_engine, "provider_sync") == baseline
    assert await _committed_revision(migrated_engine, "provider_sync") == baseline + 1
    assert await _pending_rows(migrated_engine) == 0


async def test_receipt_includes_own_bump_and_later_writers_commit_after_it(
    migrated_engine: AsyncEngine,
) -> None:
    """ADR-065: 실제 ``get_dataset_projection_revision``의 receipt 인과(458 뒤).

    receipt는 자기 mutation의 증가를 포함하고, 그 값 이상은 receipt 작성자가 commit하기 전에는
    다른 연결에 보이지 않는다 — 뒤 writer의 commit은 그 행을 기다린다.
    """

    from kortravelmap.infra.poi_cache_target_repo import (
        get_dataset_projection_revision,
        upsert_poi_cache_target,
    )

    suffix = uuid4().hex[:8]
    baseline = await _committed_revision(migrated_engine, "dataset_projection")
    later_task: asyncio.Task[None] | None = None
    try:
        async with (
            AsyncSession(migrated_engine) as first,
            AsyncSession(migrated_engine) as second,
        ):
            await first.begin()
            await upsert_poi_cache_target(
                first,
                external_system="live-projection",
                target_key=f"receipt-a-{suffix}",
                lon=126.978,
                lat=37.5665,
                radius_km=1.0,
            )
            receipt = await get_dataset_projection_revision(first)
            assert receipt == baseline + 1

            async def _later() -> None:
                await second.begin()
                await upsert_poi_cache_target(
                    second,
                    external_system="live-projection",
                    target_key=f"receipt-b-{suffix}",
                    lon=126.978,
                    lat=37.5665,
                    radius_km=1.0,
                )
                await second.commit()

            later_task = asyncio.create_task(_later())
            await asyncio.sleep(1.0)
            assert not later_task.done()
            assert await _committed_revision(migrated_engine, "dataset_projection") < receipt
            await first.commit()
            await asyncio.wait_for(later_task, timeout=10)
        assert (
            await _committed_revision(migrated_engine, "dataset_projection") == baseline + 2
        )
        assert await _pending_rows(migrated_engine) == 0
    finally:
        if later_task is not None and not later_task.done():
            later_task.cancel()
            await asyncio.gather(later_task, return_exceptions=True)
        async with AsyncSession(migrated_engine) as cleanup, cleanup.begin():
            await cleanup.execute(
                text(
                    "DELETE FROM ops.poi_cache_targets WHERE external_system = 'live-projection' "
                    "AND target_key IN (:first_key, :second_key)"
                ),
                {"first_key": f"receipt-a-{suffix}", "second_key": f"receipt-b-{suffix}"},
            )


async def test_topic_row_is_taken_after_other_deferred_checks_at_commit(
    migrated_engine: AsyncEngine,
) -> None:
    """표식이 먼저 생기고 그 뒤에 무거운 deferred 검사가 쌓여도, commit 동안 그 검사가 도는 사이
    topic 행은 잡혀 있지 않다(표식이 한 번 줄 맨 뒤로 간다). #1548 재리뷰 실측: 다시 넣지 않으면
    3초짜리 deferred 검사 내내 행이 잡혔다 — 큰 적재의 completeness 검사가 그 자리다."""

    baseline = await _committed_revision(migrated_engine, "provider_sync")
    # temp 객체는 연결에 묶인다 — 같은 물리 연결 하나로 만들고 쓴다.
    async with migrated_engine.connect() as writer, AsyncSession(migrated_engine) as prober:
        setup = await writer.begin()
        await writer.execute(text("CREATE TEMP TABLE slow_deferred_probe (id int)"))
        await writer.execute(
            text(
                "CREATE FUNCTION pg_temp.slow_deferred_probe_check() RETURNS trigger "
                "LANGUAGE plpgsql AS $$ BEGIN PERFORM pg_sleep(2); RETURN NULL; END $$"
            )
        )
        await writer.execute(
            text(
                "CREATE CONSTRAINT TRIGGER slow_deferred_probe_check "
                "AFTER INSERT ON slow_deferred_probe DEFERRABLE INITIALLY DEFERRED "
                "FOR EACH ROW EXECUTE FUNCTION pg_temp.slow_deferred_probe_check()"
            )
        )
        await setup.commit()

        work = await writer.begin()
        # 표식 먼저(topic 원본 쓰기), 무거운 deferred 사건은 그 뒤.
        await writer.execute(
            text("UPDATE provider_sync.provider_sync_state SET updated_at = updated_at WHERE false")
        )
        await writer.execute(text("INSERT INTO slow_deferred_probe VALUES (1)"))
        started = asyncio.get_running_loop().time()
        commit_task = asyncio.create_task(work.commit())
        await asyncio.sleep(0.7)
        assert not commit_task.done()
        await prober.begin()
        locked_free = (
            await prober.execute(
                text(
                    "SELECT topic FROM ops.ops_live_topic_revisions "
                    "WHERE topic = 'provider_sync' FOR UPDATE SKIP LOCKED"
                )
            )
        ).first()
        await prober.rollback()
        await asyncio.wait_for(commit_task, timeout=30)
        elapsed = asyncio.get_running_loop().time() - started
    assert elapsed >= 1.5, elapsed
    # 느린 deferred 검사가 도는 동안 topic 행은 비어 있었다.
    assert locked_free is not None
    assert await _committed_revision(migrated_engine, "provider_sync") == baseline + 1
    assert await _pending_rows(migrated_engine) == 0
