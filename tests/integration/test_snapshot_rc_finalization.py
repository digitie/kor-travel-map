"""430 whole 설치 뒤 실제 P 대기와 RC finalization의 새 statement를 반증한다.

이 source는 미설치 조각을 임의 설치하거나 ACL을 우회하지 않는다. admin은 고유 fixture
seed/외부 EX writer/관측에만 쓰며 실제 finalize는 canonical service LOGIN이다.
"""

from __future__ import annotations

import asyncio
from contextlib import suppress
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.test_feature_write_gate_lock_budget import _seed_dataset, _seed_root
from tests.integration.test_provider_field_scalar_projection import (
    scalar_container as scalar_container,
)
from tests.integration.test_provider_field_scalar_projection import scalar_engines as scalar_engines
from tests.integration.test_state_lifecycle_protocol_entry import (
    owned_scalar_resource_bounds as owned_scalar_resource_bounds,
)

pytestmark = [pytest.mark.integration, pytest.mark.timeout(25)]
_P = "SELECT ops.lock_scoped_feature_write_protocol(true)"
_FINAL = "CALL feature.finalize_provider_curation_root(CAST(:root AS uuid),NULL,NULL,NULL,NULL)"


@pytest.mark.parametrize(
    "command",
    [
        "SELECT ops.lock_provider_feature_tracking_protocol(true)",
        "CALL feature.seal_provider_curation_snapshot_receipt("
        "NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL)",
        "CALL feature.finalize_provider_curation_root(NULL,NULL,NULL,NULL,NULL)",
    ],
)
async def test_direct_serializable_finalization_rejects_before_locks(scalar_engines, command):
    admin, _ = scalar_engines
    async with AsyncSession(admin) as session:
        await session.connection(execution_options={"isolation_level": "SERIALIZABLE"})
        pid = await session.scalar(text("SELECT pg_backend_pid()"))
        with pytest.raises(DBAPIError) as caught:
            await session.execute(text(command))
        assert caught.value.orig.sqlstate == "25001"
        async with admin.connect() as observer:
            assert (
                await observer.scalar(
                    text("""SELECT count(*) FROM pg_locks
                WHERE pid=:pid AND locktype='advisory' """),
                    {"pid": pid},
                )
                == 0
            )
        await session.rollback()


async def test_serializable_leaf_still_uses_original_l_prefix(scalar_engines):
    admin, _ = scalar_engines
    async with AsyncSession(admin) as session:
        await session.connection(execution_options={"isolation_level": "SERIALIZABLE"})
        await session.execute(text("SELECT ops.lock_provider_feature_tracking_protocol(false)"))
        assert (
            await session.scalar(
                text("""SELECT count(*) FROM pg_locks
            WHERE pid=pg_backend_pid() AND locktype='advisory' AND granted
            AND objsubid=1 AND classid=1590807301 AND objid=1746797985
            AND mode='ExclusiveLock' """)
            )
            == 1
        )
        await session.rollback()


async def test_root_capture_after_actual_p_wait_sees_committed_new_input(scalar_engines):
    admin, runtime = scalar_engines
    identity = uuid4().hex
    async with admin.begin() as seed:
        # 실제 owner fixture의 terminal tree/receipt 생성에도 같은 final prefix를 쓴다.
        await seed.execute(text("SELECT ops.lock_provider_feature_tracking_protocol(true)"))
        dataset = await _seed_dataset(seed, suffix=identity, feature_count=0)
        root, child = await _seed_root(
            seed,
            dataset_id=dataset,
            run_id="rc-final-" + identity,
            root_status="done",
            rows=0,
        )
        await seed.execute(
            text("""INSERT INTO ops.curation_provider_snapshot_receipts(
            source_job_id,root_job_id,provider_dataset_id,sync_scope,operation_key,
            observed_at,source_entity_count,input_member_count,last_source_modified_at,
            source_input_set_hash)
            SELECT CAST(:child AS uuid),CAST(:root AS uuid),:dataset,'dataset_wide','load',
                   clock_timestamp(),s.source_entity_count,s.input_member_count,
                   s.last_source_modified_at,s.source_input_set_hash
            FROM feature.current_provider_curation_input_set(:dataset) s"""),
            {"root": root, "child": child, "dataset": dataset},
        )
    ready = asyncio.get_running_loop().create_future()

    async def finalize():
        async with AsyncSession(runtime) as session:
            await session.connection(execution_options={"isolation_level": "READ COMMITTED"})
            await session.execute(text("SET LOCAL statement_timeout='5s'"))
            await session.execute(text("SET LOCAL lock_timeout='4s'"))
            assert await session.scalar(text("SELECT session_user")) == "ktm_feature_service"
            pid = int(await session.scalar(text("SELECT pg_backend_pid()")))
            before = int(
                await session.scalar(
                    text("""SELECT source_entity_count
                FROM feature.current_provider_curation_input_set(:dataset)"""),
                    {"dataset": dataset},
                )
            )
            assert before == 0
            ready.set_result(pid)
            try:
                result = (await session.execute(text(_FINAL), {"root": root})).mappings().one()
                # 대기 전 statement의0을 재사용하면 이 stale 분기로 들어오지 않는다.
                assert result["o_stale_input"] is True
                assert result["o_generation_count"] == 0
            finally:
                await session.rollback()

    task = None
    async with AsyncSession(admin) as holder:
        await holder.execute(text(_P))
        blocker = int(await holder.scalar(text("SELECT pg_backend_pid()")))
        try:
            task = asyncio.create_task(finalize())
            pid = await asyncio.wait_for(ready, 3)
            async with admin.connect() as observer, asyncio.timeout(2):
                observer_pid = int(await observer.scalar(text("SELECT pg_backend_pid()")))
                assert len({pid, blocker, observer_pid}) == 3
                while not await observer.scalar(  # noqa: ASYNC110
                    text("""SELECT EXISTS(
                    SELECT 1 FROM pg_locks WHERE pid=:pid AND locktype='advisory'
                    AND database=(SELECT oid FROM pg_database WHERE datname=current_database())
                    AND classid=1369104691 AND objid=115 AND objsubid=2
                    AND mode='ExclusiveLock' AND NOT granted)
                    AND :blocker=ANY(pg_blocking_pids(:pid))"""),
                    {"pid": pid, "blocker": blocker},
                ):
                    await asyncio.sleep(0.01)
            # 외부 EX writer의 실제 commit 뒤에만 finalizer의 P 대기를 해제한다.
            await holder.execute(
                text("""INSERT INTO provider_sync.source_entities(
                source_entity_key,provider_dataset_id,source_entity_type,source_entity_id,
                first_seen_at,last_seen_at)
                VALUES(:key,:dataset,'fixture',:identity,clock_timestamp(),clock_timestamp())"""),
                {"key": "se_" + identity * 2, "dataset": dataset, "identity": identity},
            )
            await holder.commit()
            await asyncio.wait_for(task, 6)
        finally:
            await holder.rollback()
            if task is not None and not task.done():
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await asyncio.wait_for(task, 2)
    async with admin.connect() as observer:
        assert (
            await observer.scalar(
                text("""SELECT count(*) FROM pg_locks
            WHERE pid=:pid AND locktype='advisory' """),
                {"pid": pid},
            )
            == 0
        )


@pytest.mark.parametrize("status", ["prepared", "applied", "postprocessed"])
@pytest.mark.parametrize("authoritative", [False, True])
async def test_registered_member_cannot_use_legacy_finish_without_private_marker(
    scalar_engines, status, authoritative
):
    """고권한 negative fixture는 private 상태만 구성하며 등록/apply 성공을 주장하지 않는다."""
    admin, runtime = scalar_engines
    identity = uuid4().hex
    root, child, member, snapshot, attempt, owner, fence = [str(uuid4()) for _ in range(7)]
    params = dict(
        root=root,
        child=child,
        member=member,
        snapshot=snapshot,
        attempt=attempt,
        owner=owner,
        fence=fence,
        run="bypass-" + identity,
        status=status,
    )
    async with admin.begin() as seed:
        await seed.execute(text("SELECT ops.lock_provider_feature_tracking_protocol(true)"))
        dataset = await _seed_dataset(seed, suffix=identity, feature_count=0)
        params["dataset"] = dataset
        await seed.execute(
            text("""INSERT INTO ops.import_jobs(
            job_id,kind,payload,status,progress,current_stage,dagster_run_id,
            dataset_membership_mode,trigger_kind,operation_key,dagster_run_status,created_at,started_at)
            VALUES(CAST(:root AS uuid),'provider_feature_load_run','{}','running',0,'running',
                   :run,'root','schedule','load','STARTED',now(),now())"""),
            params,
        )
        await seed.execute(
            text("""INSERT INTO ops.import_jobs(
            job_id,kind,parent_job_id,payload,status,progress,current_stage,dagster_run_id,
            dataset_membership_mode,created_at,started_at)
            VALUES(CAST(:child AS uuid),'provider_feature_load',CAST(:root AS uuid),'{}',
                   'running',0,'running',:run,'single',now(),now())"""),
            params,
        )
        await seed.execute(
            text("""INSERT INTO ops.import_job_datasets(
            import_job_dataset_id,job_id,provider_dataset_id,sync_scope,operation_key)
            VALUES(CAST(:member AS uuid),CAST(:child AS uuid),:dataset,'dataset_wide','load')"""),
            params,
        )
        await seed.execute(
            text("""SELECT ops.claim_scoped_feature_write(
            CAST(:attempt AS uuid),CAST(:owner AS uuid),:dataset,'bypass',
            '[]',repeat('a',64),0,60,true)"""),
            params,
        )
        # 구조가 유효한 private 상태의 부정 시험이다. typed artifact/result 권위를 위조해
        # positive로 쓰지 않고, 기존 공개 finish가 이러한 행을 무시하지 못함만 확인한다.
        await seed.execute(
            text("""INSERT INTO ops.provider_snapshot_artifacts(
            snapshot_id,root_job_id,source_job_id,import_job_dataset_id,provider_dataset_id,
            sync_scope,operation_key,dagster_run_id,capture_profile,
            artifact_payload,native_input_digest,observation_context)
            VALUES(CAST(:snapshot AS uuid),CAST(:root AS uuid),CAST(:child AS uuid),
                   CAST(:member AS uuid),:dataset,'dataset_wide','load',:run,'bounded-place-v1',
                   convert_to('{}','UTF8'),repeat('a',64),convert_to('{}','UTF8'))"""),
            params,
        )
        await seed.execute(
            text("""INSERT INTO ops.provider_snapshot_controls(
            snapshot_id,executor_generation,executor_fence,lease_expires_at,status,
            attempt_id,attempt_owner,manifest_digest,applied_result,applied_generation,
            applied_fence,applied_at,postprocess_receipt,postprocessed_at)
            SELECT CAST(:snapshot AS uuid),1,CAST(:fence AS uuid),
                   now()+interval '60 seconds',:status,
                   CASE WHEN :status='prepared' THEN NULL ELSE CAST(:attempt AS uuid) END,
                   CASE WHEN :status='prepared' THEN NULL ELSE CAST(:owner AS uuid) END,
                   CASE WHEN :status='prepared' THEN NULL ELSE repeat('b',64) END,
                   CASE WHEN :status='prepared' THEN NULL ELSE convert_to('{}','UTF8') END,
                   CASE WHEN :status='prepared' THEN NULL ELSE 1 END,
                   CASE WHEN :status='prepared' THEN NULL ELSE CAST(:fence AS uuid) END,
                   CASE WHEN :status='prepared' THEN NULL ELSE now() END,
                   CASE WHEN :status='postprocessed' THEN convert_to('{}','UTF8') ELSE NULL END,
                   CASE WHEN :status='postprocessed' THEN now() ELSE NULL END"""),
            params,
        )
    async with AsyncSession(runtime) as session:
        with pytest.raises(DBAPIError) as caught:
            await session.execute(
                text("""CALL ops.finish_provider_feature_membership_command(
                CAST(:root AS uuid),:dataset,'dataset_wide','load',:authoritative,now(),NULL)"""),
                {"root": root, "dataset": dataset, "authoritative": authoritative},
            )
        assert caught.value.orig.sqlstate == "23514"
        assert "registered snapshot requires atomic postprocessed member seal" in str(
            caught.value.orig
        )
        await session.rollback()
    async with admin.connect() as observer:
        row = (
            await observer.execute(
                text("""SELECT child.status,child.payload,
            control.status,control.seal_txid,
            (SELECT count(*) FROM ops.curation_provider_snapshot_receipts r
             WHERE r.source_job_id=child.job_id)
            FROM ops.import_jobs child CROSS JOIN ops.provider_snapshot_controls control
            WHERE child.job_id=CAST(:child AS uuid)
              AND control.snapshot_id=CAST(:snapshot AS uuid)"""),
                params,
            )
        ).one()
        assert row[0] == "running"
        assert row[1] == {}
        assert row[2] == status
        assert row[3] is None
        assert row[4] == 0
