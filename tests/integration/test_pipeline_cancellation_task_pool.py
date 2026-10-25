"""실제 API coordinator K→P 대기 task 취소와 pool1의 다음 요청을 검증한다.

SQL timeout/EX lease 시험과 구분한다. handler·repo·SD는 정본이며 lab engine과
외부 HTTP transport만 결박한다. commit 응답 유실·provider SUCCESS 복구 증거는 아니다.
"""

from __future__ import annotations

import asyncio
import sys
from uuid import uuid4

import httpx
import pytest
from kortravelmap.api import dagster_http
from kortravelmap.api import db as api_db
from kortravelmap.api import pipeline_cancellation_service as service
from kortravelmap.api.app import create_app
from kortravelmap.api.settings import ApiSettings
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.infra.db import assert_runtime_db_privilege_boundary, make_async_engine
from kortravelmap.infra.jobs_repo import enqueue_unpaired_import_job
from tests.integration.test_provider_field_scalar_projection import (
    scalar_container as scalar_container,
)
from tests.integration.test_provider_field_scalar_projection import scalar_engines as scalar_engines
from tests.integration.test_state_lifecycle_protocol_entry import (
    owned_scalar_resource_bounds as owned_scalar_resource_bounds,
)

pytestmark = [pytest.mark.integration, pytest.mark.timeout(35)]
_PROTOCOL_CLASS = 1369104691
_PROTOCOL_OBJECT = 115


async def _state(admin, job_id):
    async with admin.begin() as observer:
        await observer.execute(text("SET TRANSACTION READ ONLY"))
        await observer.execute(text("SET LOCAL statement_timeout='1s'"))
        await observer.execute(text("SET LOCAL lock_timeout='250ms'"))
        row = (
            await observer.execute(
                text("""SELECT status,cancellation_id,cancellation_requested_at,
                cancellation_requested_by,cancellation_reason
                FROM ops.import_jobs WHERE job_id=CAST(:id AS uuid)"""),
                {"id": job_id},
            )
        ).one()
        count = await observer.scalar(
            text("""SELECT count(*) FROM ops.pipeline_cancellations
            WHERE root_kind='import_job' AND root_id=CAST(:id AS uuid)"""),
            {"id": job_id},
        )
        return tuple(row), int(count)


async def _pool_pid(runtime):
    async with runtime.connect() as connection:
        return int(await connection.scalar(text("SELECT pg_backend_pid()")))


async def _no_advisory_locks(admin, pids):
    async with admin.begin() as observer:
        await observer.execute(text("SET TRANSACTION READ ONLY"))
        await observer.execute(text("SET LOCAL statement_timeout='1s'"))
        await observer.execute(text("SET LOCAL lock_timeout='250ms'"))
        rows = (
            await observer.execute(
                text("""SELECT pid,count(*) FROM pg_locks
                WHERE locktype='advisory' AND pid=ANY(CAST(:pids AS integer[]))
                GROUP BY pid"""),
                {"pids": sorted(pids)},
            )
        ).all()
        assert rows == []


async def _wait_for_real_p_block(admin, holder_pid, lease_key, task):
    # bigint advisory K는 PG의 classid/objid 두 unsigned32 부분과 objsubid=1이다.
    high, low = (lease_key >> 32) & 0xFFFFFFFF, lease_key & 0xFFFFFFFF
    async with admin.connect() as observer, observer.begin():
        await observer.execute(text("SET TRANSACTION READ ONLY"))
        await observer.execute(text("SET LOCAL statement_timeout='1s'"))
        await observer.execute(text("SET LOCAL lock_timeout='250ms'"))
        async with asyncio.timeout(1.5):
            while True:
                assert not task.done(), "request ended before its actual P wait was observed"
                pids = (
                    (
                        await observer.execute(
                            text("""SELECT pid FROM pg_locks WHERE locktype='advisory'
                        AND database=(SELECT oid FROM pg_database WHERE datname=current_database())
                        AND classid=CAST(:high AS oid) AND objid=CAST(:low AS oid)
                        AND objsubid=1 AND mode='ExclusiveLock' AND granted"""),
                            {"high": high, "low": low},
                        )
                    )
                    .scalars()
                    .all()
                )
                assert len(pids) <= 1
                if pids:
                    pid = int(pids[0])
                    blocked = await observer.scalar(
                        text("SELECT :holder=ANY(pg_blocking_pids(:pid))"),
                        {"holder": holder_pid, "pid": pid},
                    )
                    waiting = await observer.scalar(
                        text("""SELECT count(*) FROM pg_locks WHERE pid=:pid
                        AND locktype='advisory' AND classid=:class AND objid=:object
                        AND objsubid=2 AND mode='ExclusiveLock' AND NOT granted"""),
                        {"pid": pid, "class": _PROTOCOL_CLASS, "object": _PROTOCOL_OBJECT},
                    )
                    if blocked and waiting == 1:
                        granted = await observer.scalar(
                            text("""SELECT count(*) FROM pg_locks WHERE pid=:pid
                            AND locktype='advisory' AND granted"""),
                            {"pid": pid},
                        )
                        assert granted == 1, "K only must be held before P, not L/data locks"
                        assert pid != holder_pid
                        return pid
                await asyncio.sleep(0.01)


async def test_task_cancel_during_actual_k_then_p_wait_releases_pool_and_replays(
    scalar_engines, monkeypatch, request
):
    admin, fixture_runtime = scalar_engines
    runtime = make_async_engine(
        fixture_runtime.url.render_as_string(hide_password=False),
        pool_size=1,
        max_overflow=0,
        server_settings={
            "lock_timeout": "3s",
            "statement_timeout": "5s",
            "idle_in_transaction_session_timeout": "5s",
        },
    )
    task = None
    outbound_calls = []
    observed_pids = set()

    async def reject_network(call):
        outbound_calls.append(call.method)
        raise AssertionError("queued cancellation must not make external HTTP requests")

    try:
        await assert_runtime_db_privilege_boundary(runtime, expected_login="ktm_feature_service")
        async with AsyncSession(runtime) as session, session.begin():
            queued = await enqueue_unpaired_import_job(
                session, kind="provider_load", payload={"isolated_task_cancel_probe": True}
            )
        job_id = queued.job_id
        before = await _state(admin, job_id)
        assert before[0][0] == "queued"
        assert before[1] == 0
        observed_pids.add(await _pool_pid(runtime))
        credential = uuid4().hex + uuid4().hex
        app = create_app(
            ApiSettings(
                admin_proxy_secret=credential, public_api_key_required=False, vworld_api_key=None
            )
        )
        monkeypatch.setattr(api_db, "_get_engine", lambda: runtime)
        headers = {
            "X-Kor-Travel-Map-Admin-Proxy-Secret": credential,
            "X-Kor-Travel-Map-Actor": "admin:task-cancel-lab-" + uuid4().hex,
        }
        path = f"/v1/ops/pipeline/executions/import_job/{job_id}/cancel"
        lease_key = service._coordinator_lease_key(root_kind="import_job", root_id=job_id)
        async with httpx.AsyncClient(transport=httpx.MockTransport(reject_network)) as outbound:
            monkeypatch.setattr(
                dagster_http, "http_client_from_request", lambda request, settings: outbound
            )
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app, raise_app_exceptions=False),
                base_url="http://test",
            ) as client:
                async with AsyncSession(fixture_runtime) as holder, holder.begin():
                    holder_pid = int(await holder.scalar(text("SELECT pg_backend_pid()")))
                    await holder.execute(
                        text("SELECT ops.lock_scoped_feature_write_protocol(false)")
                    )
                    try:
                        task = asyncio.create_task(
                            client.post(
                                path, headers=headers, json={"reason": "isolated_task_cancel"}
                            ),
                            name="owned-api-task-cancel-p-wait",
                        )
                        waiting_pid = await _wait_for_real_p_block(
                            admin, holder_pid, lease_key, task
                        )
                        observed_pids.add(waiting_pid)
                        assert await _state(admin, job_id) == before
                        task.cancel("owned-api-p-wait")
                        with pytest.raises(asyncio.CancelledError):
                            await asyncio.wait_for(task, 3)
                        assert task.cancelled()
                        assert runtime.pool.checkedout() == 0
                        observed_pids.add(await _pool_pid(runtime))
                        await _no_advisory_locks(admin, observed_pids)
                        assert runtime.pool.checkedout() == 0
                        assert await _state(admin, job_id) == before
                    finally:
                        primary = sys.exc_info()[1]
                        try:
                            async with asyncio.timeout(2):
                                if task is not None and not task.done():
                                    task.cancel()
                                if task is not None:
                                    await asyncio.gather(task, return_exceptions=True)
                        except BaseException as cleanup_error:
                            if primary is None:
                                raise
                            primary.add_note(
                                f"request task cleanup also failed: {type(cleanup_error).__name__}"
                            )
                # 별도 새 HTTP/TX로만 복구한다. 취소된 요청 내부 retry/결과 추정은 없다.
                response = await client.post(
                    path, headers=headers, json={"reason": "isolated_task_cancel"}
                )
                assert response.status_code == 200, response.text
                detail = response.json()["data"]
                assert detail["status"] == "completed"
                assert detail["root"] == {"kind": "import_job", "id": job_id}
                assert detail["unresolved_member_count"] == 0
                assert len(detail["members"]) == 1
                assert detail["members"][0]["result"] == "cancelled"
                assert detail["dagster_runs"] == []
                after = await _state(admin, job_id)
                assert after[0][0] == "cancelled"
                assert after[1] == 1
                replay = await client.post(
                    path, headers=headers, json={"reason": "isolated_task_cancel"}
                )
                assert replay.status_code == 200
                assert replay.json()["data"] == detail
                assert await _state(admin, job_id) == after
                assert runtime.pool.checkedout() == 0
                observed_pids.add(await _pool_pid(runtime))
                await _no_advisory_locks(admin, observed_pids)
                assert runtime.pool.checkedout() == 0
        assert outbound_calls == []
        request.node.user_properties.extend(
            [
                ("observed_runtime_pids", ",".join(map(str, sorted(observed_pids)))),
                ("cancellation_attempts_after_replay", "1"),
                ("outbound_http_calls", "0"),
            ]
        )
    finally:
        primary = sys.exc_info()[1]
        try:
            async with asyncio.timeout(3):
                if task is not None and not task.done():
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
                await runtime.dispose()
        except BaseException as cleanup_error:
            if primary is None:
                raise
            primary.add_note(f"test cleanup also failed: {type(cleanup_error).__name__}")
