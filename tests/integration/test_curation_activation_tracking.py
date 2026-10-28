"""430·434 tracking prefix의 실제 parent/leaf/typed 경계(owned PG).

ADR-117(435)이 scoped kernel·정책 활성화·strict SH guard와 공유 P를 지웠다. 그 경로를 쓰던 사례
(applying kernel 옆의 leaf, 활성화 inventory rollback, kernel begin의 parent 대기, SH+L prefix)는
지웠고, leaf는 적재(P EX + fence) 옆에서 막히지 않음을 본다.
"""

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
from kortravelmap.infra.feature_repo import lock_feature_curation_write
from tests.integration._owned_pg import (
    scalar_container as scalar_container,
)
from tests.integration._owned_pg import scalar_engines as scalar_engines
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
        # 435(ADR-117): 정책 활성화와 strict SH guard 설치기는 사라졌다.
        assert await connection.scalar(
            text("""SELECT NOT EXISTS(SELECT 1 FROM pg_proc p
            JOIN pg_namespace n ON n.oid=p.pronamespace
            WHERE n.nspname='feature' AND p.proname IN
            ('activate_provider_field_policy','_install_strict_sh_data_guards'))""")
        )
    return admin, runtime


async def _dataset(admin) -> int:
    """tracking 경계만 보는 소유 dataset 하나. Feature·source는 필요 없다."""
    async with AsyncSession(admin) as session, session.begin():
        await session.execute(text("SELECT ops.lock_scoped_feature_write_protocol(true)"))
        return int(
            await session.scalar(
                text("""INSERT INTO provider_sync.provider_datasets(
                provider,dataset_key,display_name,source_kind)
                VALUES('guard430-fixture',:key,'owned tracking fixture','manual')
                RETURNING provider_dataset_id"""),
                {"key": uuid4().hex},
            )
        )


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


async def test_load_holding_protocol_ex_does_not_block_true_leaf(activation_engines):
    """적재가 P EX와 fence를 쥔 동안에도 같은 dataset의 tracking leaf(L만)는 끝난다(434 WI-1).

    434까지는 applying scoped kernel(P SH + parent SHARE + scope UPDATE)을 옆에 뒀다. ADR-117이
    kernel을 지웠으므로 남은 bulk writer 모양(P EX → feature-curation-write)으로 본다.
    """
    admin, runtime = activation_engines
    dataset = await _dataset(admin)
    run, membership, _ = await _operation(admin, runtime, dataset)
    async with AsyncSession(runtime) as holder:
        await holder.begin()
        try:
            await lock_feature_curation_write(holder)
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


@pytest.mark.parametrize("mode", ["none"])
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
    """434 WI-1: 취소 원장 쓰기는 L을 요구한다.

    434의 ``sh_l``(SH P + L) 사례는 435(ADR-117)에서 SH P 자체가 23514로 거부되므로 지웠다.
    """
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
    dataset = await _dataset(admin)
    _, _, operation = await _operation(admin, runtime, dataset)
    child = operation.members[0].job_id
    # 434 WI-1: L 없이는 어떤 provider job도 못 쓴다. root(provider_feature_load_run)의 done
    # 전이는 큐레이션 확정이라 L만으로는 거부한다(P EX 필요). 비권위 child 완료는 장부다.
    for mode, status, job in [
        ("none", "running", child),
        ("l", "done", operation.root_job_id),
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


async def test_old_provider_event_cannot_be_moved_to_generic_job(activation_engines):
    admin, runtime = activation_engines
    dataset = await _dataset(admin)
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
