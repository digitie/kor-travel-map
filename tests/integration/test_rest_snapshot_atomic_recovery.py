"""Rest의 backend 종료·late Geo 재검증·같은 Dagster run SDK0 복구를 검증한다."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import warnings
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from dagster import DagsterEvent, DagsterInstance, job, op
from dagster._core.storage.dagster_run import DagsterRunStatus
from kortravelmap.dagster import assets
from kortravelmap.dagster import rest_snapshot_runner as runner
from kortravelmap.dagster.feature_operation_tracking import FeatureOperationExecutionGuard
from kortravelmap.dagster.rest_snapshot_postprocess import RestPostprocessMember
from kortravelmap.dagster.rest_snapshot_runtime import RestSnapshotRuntime
from sqlalchemy import event, text
from sqlalchemy.exc import DBAPIError, SAWarning
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.client import AsyncKorTravelMapClient
from kortravelmap.client import _rest_snapshot as io
from kortravelmap.infra.db import make_async_engine
from kortravelmap.infra.provider_snapshot_recovery_repo import SnapshotMember
from tests.integration.test_provider_base_update_first import _gate
from tests.integration.test_provider_field_scalar_projection import (
    scalar_container as scalar_container,
)
from tests.integration.test_provider_field_scalar_projection import scalar_engines as scalar_engines
from tests.integration.test_provider_snapshot_atomic import _state
from tests.integration.test_rest_snapshot_registration import (
    _limits,
    _Member,
    _prepare_rest_case,
    _seed_rest_baseline,
)
from tests.integration.test_rest_snapshot_registration import (
    _rest_catalog as _rest_catalog,
)
from tests.integration.test_rest_snapshot_two_writers import _cancel_ready, _run_case
from tests.integration.test_state_lifecycle_protocol_entry import (
    owned_scalar_resource_bounds as owned_scalar_resource_bounds,
)

pytestmark = [pytest.mark.integration, pytest.mark.timeout(40)]


@pytest.fixture(scope="module")
async def rest_baseline(scalar_engines, rest_catalog):
    return await _seed_rest_baseline(*scalar_engines, rest_catalog, count=2)


async def _gone_with_no_advisory(admin, identity):
    pid, started, login = identity
    async with asyncio.timeout(3), AsyncSession(admin) as observer:
        while True:
            async with observer.begin():
                await observer.execute(text("SET TRANSACTION READ ONLY"))
                await _limits(observer)
                row = (
                    await observer.execute(
                        text("""SELECT
                    (SELECT count(*) FROM pg_stat_activity WHERE pid=:pid
                     AND backend_start=:started AND usename=:login),
                    (SELECT count(*) FROM pg_locks WHERE pid=:pid AND locktype='advisory')"""),
                        dict(pid=pid, started=started, login=login),
                    )
                ).one()
            if tuple(row) == (0, 0):
                return
            await asyncio.sleep(0.01)


async def test_backend_termination_rolls_back_real_rest_effects_and_pool_one_reuses_original_input(
    scalar_engines,
    rest_catalog,
    rest_baseline,
):
    admin, runtime = scalar_engines
    case = await _prepare_rest_case(admin, runtime, rest_catalog, count=2)
    baseline = await _state(admin)
    owned_pool = make_async_engine(
        runtime.url.render_as_string(hide_password=False), pool_size=1, max_overflow=0
    )
    client = AsyncKorTravelMapClient(owned_pool)
    killed, primary = None, None

    async def terminate_after_actual_work(bound, fresh):
        nonlocal killed
        # findings/sync/stale 실제 callback이 끝났고 finish/commit 이전인 같은 연결이다.
        async with bound._session_factory() as session, session.begin():
            killed = tuple(
                (
                    await session.execute(
                        text("""SELECT pid,backend_start,usename
                FROM pg_stat_activity WHERE pid=pg_backend_pid()
                AND backend_type='client backend'""")
                    )
                ).one()
            )
            assert killed[2] == "ktm_feature_service"
            cursor = await session.scalar(
                text("""SELECT cursor FROM provider_sync.provider_sync_state
                WHERE provider_dataset_id=:dataset AND operation_key=:operation
                AND sync_scope='dataset_wide'"""),
                {
                    "dataset": rest_catalog.dataset,
                    "operation": case.typed_member.membership.operation_key,
                },
            )
            assert cursor is not None
            async with AsyncSession(admin) as observer, observer.begin():
                await _limits(observer)
                terminated = await observer.scalar(
                    text("""SELECT pg_terminate_backend(pid)
                    FROM pg_stat_activity WHERE pid=:pid AND backend_start=:started
                    AND usename=:login AND datname=current_database()
                    AND backend_type='client backend' AND pid<>pg_backend_pid()"""),
                    dict(pid=killed[0], started=killed[1], login=killed[2]),
                )
                assert terminated is True
            # 정본 finish를 가짜 오류로 바꾸지 않고 실제 죽은 연결의 다음 SQL 오류를 받는다.
            await session.scalar(text("SELECT 1"))

    try:
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore",
                message="^transaction already deassociated from connection$",
                category=SAWarning,
            )
            with pytest.raises(DBAPIError):
                await _run_case(case, client=client, after_work=terminate_after_actual_work)
        assert killed is not None
        await _gone_with_no_advisory(admin, killed)
        assert await _state(admin) == baseline
        assert owned_pool.pool.checkedout() == 0
        async with owned_pool.connect() as connection:
            assert await connection.scalar(text("SELECT 1")) == 1
            assert await connection.scalar(text("SELECT pg_backend_pid()")) != killed[0]
        assert owned_pool.pool.checkedout() == 0
        fresh = await io.read_rest_snapshot(client, case.member, pins=case.pins)
        assert fresh.status == "prepared"
        assert fresh.artifact_payload == case.observed.artifact_payload
        assert fresh.observation_context == case.observed.observation_context
        assert fresh.kernel_binding.attempt_id == case.plan.attempt_id
        completion = await _run_case(replace(case, client=client, observed=fresh))
        recovered = await io.read_rest_snapshot(client, case.member, pins=case.pins)
        assert recovered.status == "postprocessed"
        assert recovered.applied_result == completion.result
        assert recovered.postprocess_receipt == completion.receipt
        assert recovered.artifact_payload == case.observed.artifact_payload
        assert recovered.observation_context == case.observed.observation_context
        assert owned_pool.pool.checkedout() == 0
    except BaseException as error:
        primary = error
        raise
    finally:
        try:
            await _cancel_ready(runtime, case, primary)
        finally:
            await owned_pool.dispose()


async def test_late_geo_stamp_is_rechecked_after_locks_and_rejects_before_any_rest_apply_effects(
    scalar_engines,
    rest_catalog,
    rest_baseline,
):
    admin, runtime = scalar_engines
    case = await _prepare_rest_case(admin, runtime, rest_catalog, count=2)
    feature = rest_baseline[0]
    old_stamp, primary = None, None
    try:
        async with AsyncSession(admin) as session, session.begin():
            await _gate(session)
            old_stamp = await session.scalar(
                text("""SELECT stamped_at
                FROM feature.feature_geocode_stamps WHERE feature_id=:feature FOR UPDATE"""),
                {"feature": feature},
            )
            assert old_stamp is not None
            # 정본 stamp writer는 명시 owner 관리 경계만 허용한다.
            await session.execute(text("SET LOCAL ROLE ktm_feature_state_procedure_owner"))
            assert await session.scalar(text("SELECT current_user::text")) == (
                "ktm_feature_state_procedure_owner"
            )
            changed = await session.execute(
                text("""UPDATE feature.feature_geocode_stamps
                SET stamped_at=stamped_at+interval '1 second' WHERE feature_id=:feature"""),
                {"feature": feature},
            )
            assert changed.rowcount == 1
        # 의도한 관리 변경 이후를 rollback 기준으로 삼는다. 그 변경까지 취소됐다고 주장하지 않는다.
        baseline = await _state(admin)
        never_work = AsyncMock(
            side_effect=AssertionError("postprocess before fresh evidence reject")
        )
        with pytest.raises(io.RestSnapshotReplanRequired):
            await _run_case(case, before_work=never_work)
        never_work.assert_not_awaited()
        assert await _state(admin) == baseline
        fresh = await io.read_rest_snapshot(case.client, case.member, pins=case.pins)
        assert fresh.status == "prepared"
        assert fresh.applied_result is None
    except BaseException as error:
        primary = error
        raise
    finally:
        try:
            if old_stamp is not None:
                async with AsyncSession(admin) as session, session.begin():
                    await _gate(session)
                    await session.execute(text("SET LOCAL ROLE ktm_feature_state_procedure_owner"))
                    assert await session.scalar(text("SELECT current_user::text")) == (
                        "ktm_feature_state_procedure_owner"
                    )
                    restored = await session.execute(
                        text("""UPDATE feature.feature_geocode_stamps
                        SET stamped_at=:original WHERE feature_id=:feature"""),
                        {"original": old_stamp, "feature": feature},
                    )
                    assert restored.rowcount == 1
        except BaseException as cleanup_error:
            if primary is None:
                primary = cleanup_error
                raise
            primary.add_note("owned stamp restore failed: " + type(cleanup_error).__name__)
        finally:
            # stamp 복원 실패도 kernel ready lease 정리를 생략하지 않는다.
            await _cancel_ready(runtime, case, primary)


@op
def owned_rest_recovery_step():
    pass


@job
def owned_rest_recovery_job():
    owned_rest_recovery_step()


async def test_registered_postprocessed_same_dagster_run_resumes_sdk0_without_rewriting_facts(
    scalar_engines,
    rest_catalog,
    rest_baseline,
    monkeypatch,
):
    admin, runtime = scalar_engines
    client = AsyncKorTravelMapClient(runtime)
    with DagsterInstance.ephemeral() as instance:
        operation = rest_catalog.membership.operation_key
        run = instance.create_run_for_job(
            owned_rest_recovery_job,
            status=DagsterRunStatus.STARTED,
            tags={
                "kor_travel_map.operation_key": operation,
                "kor_travel_map.trigger_kind": "schedule",
            },
        )
        instance.report_dagster_event(
            DagsterEvent("PIPELINE_START", owned_rest_recovery_job.name), run.run_id
        )
        guard = FeatureOperationExecutionGuard(
            client, instance, operation, (rest_catalog.membership,), run.run_id, "schedule"
        )
        mutation = await guard.ensure()
        assert len(mutation.operation.members) == 1
        child = mutation.operation.members[0]
        identity = SnapshotMember(
            UUID(mutation.operation.root_job_id),
            UUID(child.job_id),
            UUID(child.import_job_dataset_id),
        )
        member = _Member(
            rest_catalog,
            run.run_id,
            identity,
            RestPostprocessMember(
                identity.root_id, identity.child_id, identity.member_id, rest_catalog.membership
            ),
        )
        # J helper는 caller가 실제 engine으로 확정한 member를 사용한다. 시각/DB triple 재창조0.
        case = await _prepare_rest_case(admin, runtime, rest_catalog, count=2, member=member)
        completion = await _run_case(case)
        original = await io.read_rest_snapshot(client, case.member, pins=case.pins)
        assert original.status == "postprocessed"
        async with AsyncSession(admin) as session, session.begin():
            await _gate(session)
            applied_identity = (
                await session.execute(
                    text("""SELECT applied_generation,applied_fence
                FROM ops.provider_snapshot_controls WHERE snapshot_id=:snapshot"""),
                    {"snapshot": original.snapshot_id},
                )
            ).one()
            expired = await session.execute(
                text("""UPDATE ops.provider_snapshot_controls
                SET lease_expires_at=clock_timestamp()-interval '1 second'
                WHERE snapshot_id=:snapshot AND executor_generation=:generation
                  AND executor_fence=:fence AND status='postprocessed'"""),
                {
                    "snapshot": original.snapshot_id,
                    "generation": case.token.generation,
                    "fence": case.token.fence,
                },
            )
            assert expired.rowcount == 1
        before = await _state(admin)
        forbidden = AsyncMock(side_effect=AssertionError("SDK/Geo/newclock/reapply forbidden"))
        monkeypatch.setattr(runner, "_collect_rest_snapshot_input", forbidden)
        monkeypatch.setattr(runner, "run_snapshot_apply_postprocess", forbidden)
        monkeypatch.setattr(
            assets, "_reverse_geocoder", lambda *a: pytest.fail("live Geo forbidden")
        )
        for name in [
            "record_address_validation_findings",
            "record_sync_success_for_operation_membership",
            "close_stale_address_validation_findings",
        ]:
            monkeypatch.setattr(AsyncKorTravelMapClient, name, forbidden)
        context = SimpleNamespace(
            run_id=run.run_id,
            retry_number=0,
            log=logging.getLogger("owned-rest-sdk0"),
            resources=SimpleNamespace(
                kor_travel_map_client=client,
                feature_operation_guard=guard,
                rest_snapshot_runtime=RestSnapshotRuntime(case.pins),
                rest_snapshot_input=forbidden,
                fetched_at=forbidden,
                strict_address="strict",
            ),
        )
        result = await runner.run_rest_snapshot_if_supported(context)
        forbidden.assert_not_awaited()
        assert result.load == completion.result.load
        fresh = await io.read_rest_snapshot(client, case.member, pins=case.pins)
        assert fresh.status == "child_sealed"
        assert fresh.artifact_payload == original.artifact_payload
        assert fresh.observation_context == original.observation_context
        assert fresh.applied_result_bytes == original.applied_result_bytes
        assert fresh.postprocess_receipt == original.postprocess_receipt
        async with AsyncSession(admin) as session, session.begin():
            await session.execute(text("SET TRANSACTION READ ONLY"))
            await _limits(session)
            row = (
                await session.execute(
                    text("""SELECT applied_generation,applied_fence,
                executor_generation FROM ops.provider_snapshot_controls
                WHERE snapshot_id=:snapshot"""),
                    {"snapshot": original.snapshot_id},
                )
            ).one()
            assert tuple(row[:2]) == tuple(applied_identity)
            assert row[2] == case.token.generation + 1
        after = await _state(admin)
        for table in before:
            if table not in {"ops.provider_snapshot_controls", "ops.ops_live_topic_revisions"}:
                assert after[table] == before[table]


async def _owned_backend_identity(engine):
    async with AsyncSession(engine) as session, session.begin():
        await session.execute(text("SET TRANSACTION READ ONLY"))
        await _limits(session)
        identity = tuple(
            (
                await session.execute(
                    text("""SELECT pid,backend_start,usename
            FROM pg_stat_activity WHERE pid=pg_backend_pid()
            AND backend_type='client backend'""")
                )
            ).one()
        )
        assert identity[2] == "ktm_feature_service"
        return identity


async def test_physical_seal_between_original_read_and_claim_restores_original_receipt_sdk0(
    scalar_engines,
    rest_catalog,
    rest_baseline,
    monkeypatch,
    request,
):
    admin, runtime = scalar_engines
    case = await _prepare_rest_case(admin, runtime, rest_catalog, count=2)
    completion = await _run_case(case)
    pools = [
        make_async_engine(
            runtime.url.render_as_string(hide_password=False), pool_size=1, max_overflow=0
        )
        for _ in range(2)
    ]
    reader, sealer = [AsyncKorTravelMapClient(pool) for pool in pools]
    boundary, sealed = asyncio.Event(), asyncio.Event()
    claim_errors, sql_pids = [], {"claim": [], "seal": []}
    original_claim, original_seal = io.claim_rest_snapshot, io.seal_rest_snapshot
    task, primary, baseline = None, None, None
    listeners = []

    def observe_sql(kind, needle):
        def observe(connection, cursor, statement, parameters, context, executemany):
            if needle in statement:
                sql_pids[kind].append(connection.connection.driver_connection.get_server_pid())

        return observe

    try:
        identities = [await _owned_backend_identity(pool) for pool in pools]
        assert identities[0][0] != identities[1][0]
        old = await io.read_rest_snapshot(reader, case.member, pins=case.pins)
        assert old.status == "postprocessed"
        assert old.applied_result_bytes is not None
        assert old.postprocess_receipt is not None
        for pool, kind, needle in [
            (pools[0], "claim", "ops.claim_provider_snapshot_executor("),
            (pools[1], "seal", "ops.seal_provider_snapshot_member("),
        ]:
            listener = observe_sql(kind, needle)
            event.listen(pool.sync_engine, "before_cursor_execute", listener)
            listeners.append((pool.sync_engine, listener))

        async def claim_after_other_worker_seals(client, observed, *, previous=None):
            assert client is reader
            assert observed is old
            boundary.set()
            async with asyncio.timeout(5):
                await sealed.wait()
            try:
                return await original_claim(client, observed, previous=previous)
            except DBAPIError as error:
                claim_errors.append(error)
                raise

        async def other_worker():
            nonlocal baseline
            async with asyncio.timeout(5):
                await boundary.wait()
            await original_seal(
                sealer,
                case.token,
                artifact_sha256=old.artifact_sha256,
                context_sha256=old.context_sha256,
                result_sha256=hashlib.sha256(old.applied_result_bytes).hexdigest(),
                postprocess_sha256=hashlib.sha256(old.postprocess_receipt).hexdigest(),
            )
            # baseline은 다른 worker의 정당한 seal COMMIT 후, 이전 claim을 풀기 전에 받는다.
            baseline = await _state(admin)
            sealed.set()

        forbidden = AsyncMock(side_effect=AssertionError("sealed recovery must remain SDK0/DML0"))
        monkeypatch.setattr(io, "claim_rest_snapshot", claim_after_other_worker_seals)
        for name in ("plan_rest_snapshot", "reset_rest_snapshot_plan", "seal_rest_snapshot"):
            monkeypatch.setattr(io, name, forbidden)
        monkeypatch.setattr(runner, "_collect_rest_snapshot_input", forbidden)
        monkeypatch.setattr(runner, "run_snapshot_apply_postprocess", forbidden)
        monkeypatch.setattr(assets, "_reverse_geocoder", lambda *args: pytest.fail("Geo forbidden"))
        for name in (
            "record_address_validation_findings",
            "record_sync_success_for_operation_membership",
            "close_stale_address_validation_findings",
        ):
            monkeypatch.setattr(AsyncKorTravelMapClient, name, forbidden)
        task = asyncio.create_task(other_worker())
        resume = asyncio.create_task(
            runner._resume(
                reader,
                case.member,
                case.typed_member,
                RestSnapshotRuntime(case.pins),
                case.run,
                old,
            )
        )
        # 다른 worker의 원오류를 claim wait timeout으로 가리지 않는다.
        try:
            async with asyncio.timeout(10):
                _, result = await asyncio.gather(task, resume)
        finally:
            if not resume.done():
                resume.cancel()
            await asyncio.gather(resume, return_exceptions=True)
        assert len(claim_errors) == 1
        assert runner._claim_member_inactive(claim_errors[0])
        assert sql_pids == {"claim": [identities[0][0]], "seal": [identities[1][0]]}
        assert [await _owned_backend_identity(pool) for pool in pools] == identities
        assert result.load == completion.result.load
        forbidden.assert_not_awaited()
        assert baseline is not None
        assert await _state(admin) == baseline
        fresh = await io.read_rest_snapshot(reader, case.member, pins=case.pins)
        assert fresh.status == "child_sealed"
        assert fresh.child_status == "done"
        assert fresh.root_status in {"running", "done"}
        assert not fresh.cancellation_present
        assert fresh.snapshot_id == old.snapshot_id
        assert fresh.artifact_payload == old.artifact_payload
        assert fresh.observation_context == old.observation_context
        assert fresh.applied_result_bytes == old.applied_result_bytes
        assert fresh.postprocess_receipt == old.postprocess_receipt == completion.receipt
        assert fresh.applied_result == old.applied_result
        request.node.user_properties.append(
            (
                "physical_seal_race",
                json.dumps(
                    {
                        "physical_backends": 2,
                        "original_read": "postprocessed",
                        "other_worker_commit_before_claim": True,
                        "actual_member_inactive_23514": True,
                        "fresh_read": "child_sealed",
                        "original_receipt_preserved": True,
                        "SDK_calls": 0,
                        "resume_effect_tables_unchanged": 18,
                        "negative_scope": (
                            "cancellation/quarantine rejection remains existing pure/CI coverage"
                        ),
                    },
                    sort_keys=True,
                ),
            )
        )
    except BaseException as error:
        primary = error
        raise
    finally:
        sealed.set()
        cleanup_primary = primary

        def preserve_cleanup(error, label):
            nonlocal cleanup_primary
            if cleanup_primary is None:
                cleanup_primary = error
            else:
                cleanup_primary.add_note(label + ": " + type(error).__name__)

        if task is not None and not task.done():
            task.cancel()
        try:
            if task is not None:
                async with asyncio.timeout(5):
                    await asyncio.gather(task, return_exceptions=True)
        except BaseException as cleanup:
            preserve_cleanup(cleanup, "owned seal-race actor drain failed")
        for engine, listener in listeners:
            try:
                event.remove(engine, "before_cursor_execute", listener)
            except BaseException as cleanup:
                preserve_cleanup(cleanup, "owned seal-race listener removal failed")
        for pool in pools:
            try:
                assert pool.pool.checkedout() == 0
            except BaseException as cleanup:
                preserve_cleanup(cleanup, "owned seal-race pool checkout check failed")
            try:
                async with asyncio.timeout(5):
                    await pool.dispose()
            except BaseException as cleanup:
                preserve_cleanup(cleanup, "owned seal-race pool disposal failed")
        if primary is None and cleanup_primary is not None:
            raise cleanup_primary
