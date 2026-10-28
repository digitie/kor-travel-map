"""430 합성 뒤 실제 parent/leaf/typed 경계용 paired source. 실행은 별도 owned gate다."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.core.feature_operation import ProviderDatasetOperationMembership
from kortravelmap.infra.feature_operation_repo import (
    append_dagster_feature_attempt_event,
    ensure_dagster_feature_operation,
)
from kortravelmap.infra.scoped_feature_writes import begin_scoped_feature_write
from tests.integration.test_provider_field_scalar_projection import (
    scalar_container as scalar_container,
)
from tests.integration.test_provider_field_scalar_projection import scalar_engines as scalar_engines
from tests.integration.test_scoped_provider_batch import _plan, _seed
from tests.integration.test_state_lifecycle_protocol_entry import (
    owned_scalar_resource_bounds as owned_scalar_resource_bounds,
)
from tests.integration.test_tvn36_override_lineage_spine import _constraint_name

pytestmark = [pytest.mark.integration, pytest.mark.timeout(35)]
_L = 6832465333779826081


@pytest.fixture
async def activation_engines(scalar_engines):
    admin, runtime = scalar_engines
    # 공통 migration/ACL 합성 전에 이 시험을 실행해 정본 설치를 우회하지 않는다.
    async with admin.connect() as connection:
        assert await connection.scalar(
            text("SELECT to_regprocedure('ops.reject_pipeline_cancellation_prefix()') IS NOT NULL")
        )
        assert await connection.scalar(
            text("""SELECT position('_install_strict_sh_data_guards' IN p.prosrc)>0
            FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
            WHERE n.nspname='feature' AND p.proname='activate_provider_field_policy'""")
        )
    return admin, runtime


async def _operation(admin, runtime, dataset):
    operation = "guard430-" + uuid4().hex
    async with AsyncSession(admin) as session, session.begin():
        await session.execute(text("SELECT ops.lock_scoped_feature_write_protocol(true)"))
        await session.execute(
            text("""INSERT INTO provider_sync.provider_dataset_operations
            (provider_dataset_id,operation_key,operation_kind,is_enabled)
            VALUES(:dataset,:operation,'refresh',true)"""),
            {"dataset": dataset, "operation": operation},
        )
        await session.execute(
            text("""INSERT INTO provider_sync.provider_dataset_operation_scopes
            (provider_dataset_id,sync_scope,operation_key,operation_kind)
            VALUES(:dataset,'dataset_wide',:operation,'refresh')"""),
            {"dataset": dataset, "operation": operation},
        )
    membership = ProviderDatasetOperationMembership(dataset, "dataset_wide", operation)
    run = "guard430-" + uuid4().hex
    async with AsyncSession(runtime) as session, session.begin():
        await session.execute(text("SET LOCAL lock_timeout='700ms'"))
        await session.execute(text("SET LOCAL statement_timeout='2s'"))
        result = await ensure_dagster_feature_operation(
            session,
            dagster_run_id=run,
            trigger_kind="manual",
            selected_memberships=(membership,),
            operation_key=operation,
            engine_created_at=datetime(2026, 10, 25, tzinfo=UTC),
            engine_started_at=datetime(2026, 10, 25, tzinfo=UTC),
            observed_status="STARTED",
        )
    return run, membership, result.operation


async def _prefix(session, mode):
    if mode == "l":
        await session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": _L})
    elif mode == "ex_l":
        await session.execute(text("SELECT ops.lock_provider_feature_tracking_protocol(true)"))
    elif mode == "sh_l":
        await session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": _L})
        await session.execute(text("SELECT ops.lock_scoped_feature_write_protocol(false)"))


async def test_same_dataset_applying_does_not_block_true_leaf(activation_engines):
    admin, runtime = activation_engines
    dataset, items = await _seed(admin, runtime, count=1)
    run, membership, _ = await _operation(admin, runtime, dataset)
    plan, _ = await _plan(runtime, dataset, items)
    async with AsyncSession(runtime) as holder:
        await holder.begin()
        try:
            applying = await begin_scoped_feature_write(
                holder,
                attempt_id=plan["attempt_id"],
                owner=plan["owner"],
                manifest_digest=plan["manifest_digest"],
            )
            # runtime에는 내부 attempt 표의 raw SELECT 권한이 없다.
            # 실제 begin이 반환한 같은 행과 현재 TX를 대조한다.
            assert applying["status"] == "applying"
            assert applying["apply_txid"] == await holder.scalar(text("SELECT txid_current()"))
            # 실제 applying의 parent SHARE/ops scope UPDATE/P SH를 유지한 채 leaf를 쓴다.
            async with asyncio.timeout(2), AsyncSession(runtime) as leaf, leaf.begin():
                await leaf.execute(text("SET LOCAL lock_timeout='500ms'"))
                await leaf.execute(text("SET LOCAL statement_timeout='1s'"))
                repeated = await ensure_dagster_feature_operation(
                    leaf,
                    dagster_run_id=run,
                    trigger_kind="manual",
                    selected_memberships=(membership,),
                    operation_key=membership.operation_key,
                    engine_created_at=datetime(2026, 10, 25, tzinfo=UTC),
                    engine_started_at=datetime(2026, 10, 25, tzinfo=UTC),
                    observed_status="STARTED",
                )
                assert repeated.operation.dagster_run_id == run
                event = await append_dagster_feature_attempt_event(
                    leaf,
                    dagster_run_id=run,
                    membership=membership,
                    attempt_number=1,
                    outcome="retryable_failure",
                    error={"code": "owned430"},
                )
                assert event.job_id
            async with admin.connect() as observer:
                assert (
                    await observer.scalar(
                        text(
                            "SELECT status='applying' FROM ops.feature_write_attempts "
                            "WHERE attempt_id=:id"
                        ),
                        {"id": plan["attempt_id"]},
                    )
                    is False
                )  # 아직 commit하지 않은 applying은 다른 snapshot에 보이지 않는다.
        finally:
            await holder.rollback()
    async with admin.connect() as observer:
        assert (
            await observer.scalar(
                text("SELECT count(*) FROM ops.import_job_events WHERE event_id=:id"),
                {"id": event.event_id},
            )
            == 1
        )


@pytest.mark.parametrize("mode", ["none", "sh_l"])
@pytest.mark.parametrize(
    "relation",
    [
        "pipeline_cancellations",
        "pipeline_cancellation_members",
        "pipeline_cancellation_runs",
    ],
)
async def test_cancel_statement_requires_l_and_no_shared_protocol(
    activation_engines, mode, relation
):
    """434 WI-1: 취소 원장 쓰기는 L을 요구하고, P를 쥐었다면 EX여야 한다(SH 데이터 writer 금지)."""
    _, runtime = activation_engines
    async with AsyncSession(runtime) as session:
        await session.begin()
        try:
            await _prefix(session, mode)
            with pytest.raises(DBAPIError) as caught:
                await session.execute(text(f"DELETE FROM ops.{relation} WHERE false"))
            assert caught.value.orig.sqlstate == "23514"
            assert _constraint_name(caught.value) == "ck_provider_tracking_write_prefix"
        finally:
            await session.rollback()


@pytest.mark.parametrize("mode", ["ex_l", "l"])
async def test_cancel_existing_prefix_zero_row_path_is_allowed(activation_engines, mode):
    # 434 WI-1: L만 쥔 장부 transaction도 취소 원장을 쓴다(종전 424는 P EX→L을 요구했다).
    _, runtime = activation_engines
    async with AsyncSession(runtime) as session, session.begin():
        await _prefix(session, mode)
        for relation in [
            "pipeline_cancellations",
            "pipeline_cancellation_members",
            "pipeline_cancellation_runs",
        ]:
            result = await session.execute(text(f"DELETE FROM ops.{relation} WHERE false"))
            assert result.rowcount == 0


async def test_typed_owner_cannot_skip_l_or_terminal_p(activation_engines):
    admin, runtime = activation_engines
    dataset, _ = await _seed(admin, runtime, count=1)
    _, _, operation = await _operation(admin, runtime, dataset)
    child = operation.members[0].job_id
    # 434 WI-1: L 없이는 어떤 provider job도 못 쓴다. root(provider_feature_load_run)의 done
    # 전이는 큐레이션 확정이라 L만으로는 거부한다(P EX 필요). 비권위 child 완료는 장부다.
    for mode, status, job in [
        ("none", "running", child),
        ("l", "done", operation.root_job_id),
        ("sh_l", "failed", child),
    ]:
        async with AsyncSession(admin) as session:
            await session.begin()
            try:
                await _prefix(session, mode)
                await session.execute(text("SET LOCAL ROLE ktm_curation_command_owner"))
                with pytest.raises(DBAPIError) as caught:
                    await session.execute(
                        text(
                            "UPDATE ops.import_jobs SET status=:status "
                            "WHERE job_id=CAST(:id AS uuid)"
                        ),
                        {"status": status, "id": job},
                    )
                assert caught.value.orig.sqlstate == "23514"
                assert _constraint_name(caught.value) == "ck_provider_tracking_write_prefix"
            finally:
                await session.rollback()


async def test_generic_job_keeps_original_no_protocol_write_path(activation_engines):
    _, runtime = activation_engines
    async with AsyncSession(runtime) as session, session.begin():
        job = await session.scalar(
            text("INSERT INTO ops.import_jobs(kind,payload) VALUES('import','{}') RETURNING job_id")
        )
        await session.execute(
            text("UPDATE ops.import_jobs SET progress=7 WHERE job_id=:id"), {"id": job}
        )
        assert (
            await session.scalar(
                text("SELECT progress FROM ops.import_jobs WHERE job_id=:id"), {"id": job}
            )
            == 7
        )
        assert await session.scalar(
            text("""SELECT NOT EXISTS(SELECT 1 FROM pg_locks WHERE pid=pg_backend_pid()
            AND locktype='advisory' AND granted AND
            ((classid=1369104691 AND objid=115 AND objsubid=2)
            OR (classid=1590807301 AND objid=1746797985 AND objsubid=1)))""")
        )


async def test_activation_partial_inventory_rolls_back_policy_and_trigger(activation_engines):
    admin, runtime = activation_engines
    _, items = await _seed(admin, runtime, count=1)
    feature = items[0].feature_id
    async with admin.connect() as observer:
        baseline = (
            await observer.execute(
                text("""SELECT active.policy_revision,active.field_paths,
            epoch.epoch FROM feature.provider_field_active_policies active
            CROSS JOIN feature.provider_field_policy_epoch epoch
            WHERE active.feature_id=:id AND epoch.singleton"""),
                {"id": feature},
            )
        ).one()
        assert (
            await observer.scalar(
                text("""SELECT count(*) FROM pg_trigger
            WHERE NOT tgisinternal AND tgname IN
            ('trg_00_strict_sh_data_protocol','trg_00_strict_sh_data_target')""")
            )
            == 33
        )
    async with AsyncSession(admin) as session:
        await session.begin()
        try:
            await _prefix(session, "ex_l")
            await session.execute(
                text("DROP TRIGGER trg_00_strict_sh_data_protocol ON feature.features")
            )
            await session.execute(text("SET LOCAL ROLE ktm_feature_state_procedure_owner"))
            with pytest.raises(DBAPIError) as caught:
                await session.execute(
                    text("CALL feature.activate_provider_field_policy(:id,:revision,:fields)"),
                    {"id": feature, "revision": baseline[0], "fields": list(baseline[1])},
                )
            assert caught.value.orig.sqlstate == "23514"
            assert _constraint_name(caught.value) == "ck_strict_data_guard_inventory"
        finally:
            await session.rollback()
    async with admin.connect() as observer:
        after = (
            await observer.execute(
                text("""SELECT active.policy_revision,active.field_paths,
            epoch.epoch FROM feature.provider_field_active_policies active
            CROSS JOIN feature.provider_field_policy_epoch epoch
            WHERE active.feature_id=:id AND epoch.singleton"""),
                {"id": feature},
            )
        ).one()
        assert tuple(after) == tuple(baseline)
        assert (
            await observer.scalar(
                text("""SELECT count(*) FROM pg_trigger
            WHERE NOT tgisinternal AND tgname IN
            ('trg_00_strict_sh_data_protocol','trg_00_strict_sh_data_target')""")
            )
            == 33
        )


async def test_begin_waits_on_actual_parent_before_ops_scope_or_feature(activation_engines):
    admin, runtime = activation_engines
    dataset, items = await _seed(admin, runtime, count=1)
    plan, _ = await _plan(runtime, dataset, items)
    ready = asyncio.get_running_loop().create_future()
    async with AsyncSession(admin) as holder:
        await holder.begin()
        try:
            # 관리 SQL의 row probe다. 일반 writer의 임의 선행 잠금까지 attest하지 않는다.
            blocker = int(await holder.scalar(text("SELECT pg_backend_pid()")))
            await holder.execute(
                text(
                    "SELECT 1 FROM provider_sync.provider_datasets "
                    "WHERE provider_dataset_id=:id FOR UPDATE"
                ),
                {"id": dataset},
            )

            async def begin():
                async with AsyncSession(runtime) as session:
                    await session.begin()
                    try:
                        await session.execute(text("SET LOCAL lock_timeout='1s'"))
                        await session.execute(text("SET LOCAL statement_timeout='3s'"))
                        ready.set_result(int(await session.scalar(text("SELECT pg_backend_pid()"))))
                        with pytest.raises(DBAPIError) as caught:
                            await begin_scoped_feature_write(
                                session,
                                attempt_id=plan["attempt_id"],
                                owner=plan["owner"],
                                manifest_digest=plan["manifest_digest"],
                            )
                        assert caught.value.orig.sqlstate == "55P03"
                    finally:
                        await session.rollback()

            task = asyncio.create_task(begin())
            try:
                pid = await asyncio.wait_for(ready, 2)
                async with asyncio.timeout(0.8):
                    while True:
                        if task.done():
                            await task
                            raise AssertionError(
                                "begin ended before actual parent wait observation"
                            )
                        async with admin.connect() as observer:
                            blocked = await observer.scalar(
                                text("SELECT :blocker=ANY(pg_blocking_pids(:pid))"),
                                {"blocker": blocker, "pid": pid},
                            )
                        if blocked:
                            break
                        await asyncio.sleep(0.01)
                async with AsyncSession(admin) as observer, observer.begin():
                    await observer.execute(
                        text(
                            "SELECT 1 FROM ops.feature_write_dataset_scopes "
                            "WHERE provider_dataset_id=:id FOR UPDATE NOWAIT"
                        ),
                        {"id": dataset},
                    )
                    await observer.execute(
                        text(
                            "SELECT 1 FROM feature.features WHERE feature_id=:id FOR UPDATE NOWAIT"
                        ),
                        {"id": items[0].feature_id},
                    )
                await asyncio.wait_for(task, 2)
            finally:
                await holder.rollback()
                if not task.done():
                    task.cancel()
                await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), 2)
        finally:
            await holder.rollback()


async def test_old_provider_event_cannot_be_moved_to_generic_job(activation_engines):
    admin, runtime = activation_engines
    dataset, _ = await _seed(admin, runtime, count=1)
    run, membership, _ = await _operation(admin, runtime, dataset)
    async with AsyncSession(runtime) as session, session.begin():
        event = await append_dagster_feature_attempt_event(
            session,
            dagster_run_id=run,
            membership=membership,
            attempt_number=1,
            outcome="retryable_failure",
            error={"code": "owned430"},
        )
    async with AsyncSession(runtime) as session, session.begin():
        generic = await session.scalar(
            text("INSERT INTO ops.import_jobs(kind,payload) VALUES('import','{}') RETURNING job_id")
        )
    async with AsyncSession(runtime) as session:
        await session.begin()
        try:
            await _prefix(session, "ex_l")
            with pytest.raises(DBAPIError) as caught:
                await session.execute(
                    text(
                        "UPDATE ops.import_job_events SET job_id=:job "
                        "WHERE event_id=CAST(:event AS uuid)"
                    ),
                    {"job": generic, "event": event.event_id},
                )
            # ownership 불변 guard가 typed guard보다 먼저 이 공격을 거부한다.
            assert caught.value.orig.sqlstate == "23514"
            assert _constraint_name(caught.value) == "ck_import_job_event_ownership_immutable"
        finally:
            await session.rollback()
    # ownership을 유지한 내용 변조도 실제 typed command 경계에서 거부해야 한다.
    async with AsyncSession(runtime) as session:
        await session.begin()
        try:
            await _prefix(session, "ex_l")
            with pytest.raises(DBAPIError) as caught:
                await session.execute(
                    text(
                        "UPDATE ops.import_job_events SET message='raw mutation' "
                        "WHERE event_id=CAST(:event AS uuid)"
                    ),
                    {"event": event.event_id},
                )
            assert caught.value.orig.sqlstate == "42501"
            assert _constraint_name(caught.value) == "ck_tvn40_provider_event_typed_command"
        finally:
            await session.rollback()
    async with admin.connect() as observer:
        assert (
            str(
                await observer.scalar(
                    text(
                        "SELECT job_id FROM ops.import_job_events WHERE event_id=CAST(:id AS uuid)"
                    ),
                    {"id": event.event_id},
                )
            )
            == event.job_id
        )
        assert await observer.scalar(
            text("SELECT message FROM ops.import_job_events WHERE event_id=CAST(:id AS uuid)"),
            {"id": event.event_id},
        ) == event.message
