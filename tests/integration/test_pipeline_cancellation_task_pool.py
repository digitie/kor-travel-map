"""실제 API coordinator K→L 대기 task 취소와 pool1의 다음 요청을 검증한다.

SQL timeout/EX lease 시험과 구분한다. handler·repo·SD는 정본이며 lab engine과
외부 HTTP transport만 결박한다. commit 응답 유실·provider SUCCESS 복구 증거는 아니다.
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from datetime import timedelta
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
_LINEAGE_KEY = 6832465333779826081
_LINEAGE_CLASS = (_LINEAGE_KEY >> 32) & 0xFFFFFFFF
_LINEAGE_OBJECT = _LINEAGE_KEY & 0xFFFFFFFF


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


async def _capture_failed_zero_lock_timeline(admin, pids, holder_pid, request):
    """최초 실패를 바꾸지 않고 holder 해제 전 최대 4.5초의 메타데이터만 남긴다."""
    started = time.monotonic()
    evidence = {
        "phase": "before_holder_release",
        "initial_zero_row_assertion_failed": True,
        "target_pids": sorted(pids),
        "holder_pid": holder_pid,
        "budget_seconds": 4.5,
        "samples": [],
        "target_advisory_rows_disappeared": False,
        "diagnostic_error_type": None,
    }
    try:
        async with asyncio.timeout(4.5):
            for _ in range(18):
                # 별도 TX로 activity 통계 snapshot을 갱신한다. query 본문은 읽지 않는다.
                async with admin.begin() as observer:
                    await observer.execute(text("SET TRANSACTION READ ONLY"))
                    await observer.execute(text("SET LOCAL statement_timeout='1s'"))
                    await observer.execute(text("SET LOCAL lock_timeout='250ms'"))
                    rows = (
                        (
                            await observer.execute(
                                text("""WITH requested(pid) AS (
                                SELECT unnest(CAST(:pids AS integer[]))
                            )
                            SELECT r.pid,a.backend_start,a.state,a.query_start,
                                a.wait_event_type,a.wait_event,
                                CAST(l.classid AS bigint) AS classid,
                                CAST(l.objid AS bigint) AS objid,
                                l.objsubid,l.mode,l.granted
                            FROM requested r
                            LEFT JOIN pg_catalog.pg_stat_activity a ON a.pid=r.pid
                            LEFT JOIN pg_catalog.pg_locks l
                                ON l.pid=r.pid AND l.locktype='advisory'
                            ORDER BY r.pid,l.classid,l.objid,l.objsubid,l.mode,l.granted
                            LIMIT 129"""),
                                {"pids": sorted(pids | {holder_pid})},
                            )
                        )
                        .mappings()
                        .all()
                    )
                    sample_rows = [
                        {
                            key: value.isoformat()
                            if key in {"backend_start", "query_start"} and value is not None
                            else value
                            for key, value in row.items()
                        }
                        for row in rows[:128]
                    ]
                    truncated = len(rows) > 128
                    evidence["samples"].append(
                        {
                            "elapsed_seconds": round(time.monotonic() - started, 6),
                            "rows": sample_rows,
                            "truncated": truncated,
                        }
                    )
                # holder 자신의 L 잠금은 target 판정에서 제외한다.
                if not truncated and not any(
                    row["pid"] in pids and row["mode"] is not None for row in sample_rows
                ):
                    evidence["target_advisory_rows_disappeared"] = True
                    break
                await asyncio.sleep(0.25)
    except BaseException as diagnostic_error:
        # 진단 실패/상한도 원 최초 AssertionError를 대체하지 않는다.
        evidence["diagnostic_error_type"] = type(diagnostic_error).__name__
    evidence["elapsed_seconds"] = round(time.monotonic() - started, 6)
    request.node.user_properties.append(
        ("pre_holder_release_advisory_timeline_json", json.dumps(evidence, sort_keys=True))
    )


async def _wait_for_real_l_block(admin, holder_pid, lease_key, task):
    # bigint advisory K는 PG의 classid/objid 두 unsigned32 부분과 objsubid=1이다.
    high, low = (lease_key >> 32) & 0xFFFFFFFF, lease_key & 0xFFFFFFFF
    async with admin.connect() as observer, observer.begin():
        await observer.execute(text("SET TRANSACTION READ ONLY"))
        await observer.execute(text("SET LOCAL statement_timeout='1s'"))
        await observer.execute(text("SET LOCAL lock_timeout='250ms'"))
        async with asyncio.timeout(1.5):
            while True:
                assert not task.done(), "request ended before its actual L wait was observed"
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
                        AND objsubid=1 AND mode='ExclusiveLock' AND NOT granted"""),
                        {"pid": pid, "class": _LINEAGE_CLASS, "object": _LINEAGE_OBJECT},
                    )
                    if blocked and waiting == 1:
                        granted = await observer.scalar(
                            text("""SELECT count(*) FROM pg_locks WHERE pid=:pid
                            AND locktype='advisory' AND granted"""),
                            {"pid": pid},
                        )
                        assert granted == 1, "K only must be held before L, not L/data locks"
                        assert pid != holder_pid
                        return pid
                await asyncio.sleep(0.01)


async def test_task_cancel_during_actual_k_then_l_wait_releases_pool_and_replays(
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
                        text("SELECT ops.lock_provider_feature_tracking_protocol(false)")
                    )
                    try:
                        task = asyncio.create_task(
                            client.post(
                                path, headers=headers, json={"reason": "isolated_task_cancel"}
                            ),
                            name="owned-api-task-cancel-l-wait",
                        )
                        waiting_pid = await _wait_for_real_l_block(
                            admin, holder_pid, lease_key, task
                        )
                        observed_pids.add(waiting_pid)
                        assert await _state(admin, job_id) == before
                        task.cancel("owned-api-l-wait")
                        with pytest.raises(asyncio.CancelledError):
                            await asyncio.wait_for(task, 3)
                        assert task.cancelled()
                        assert runtime.pool.checkedout() == 0
                        observed_pids.add(await _pool_pid(runtime))
                        try:
                            await _no_advisory_locks(admin, observed_pids)
                        except AssertionError as initial_failure:
                            await _capture_failed_zero_lock_timeline(
                                admin, observed_pids, holder_pid, request
                            )
                            initial_failure.add_note(
                                "Initial zero-row assertion remains failed; bounded metadata "
                                "is in pre_holder_release_advisory_timeline_json XML property."
                            )
                            raise
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


async def test_cancel_after_real_k_commit_before_return_closes_unknown_lease(
    scalar_engines, monkeypatch, request
):
    """원 helper의 실제 K+commit 뒤 await barrier에서 caller 취소를 전달한다."""
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
    acquired = asyncio.Event()
    never_release = asyncio.Event()
    observed_pids = set()
    outbound_calls = []
    original_acquire = service._acquire_coordinator_lease
    barrier_used = False

    async def after_real_commit(session, *, lease_key):
        nonlocal barrier_used
        result = await original_acquire(session, lease_key=lease_key)
        if result and not barrier_used:
            barrier_used = True
            assert not session.in_transaction()
            backend = service._session_backend(session)
            assert backend is not None
            observed_pids.add(int(backend.driver.get_server_pid()))
            acquired.set()
            # 이 시험 await는 원 helper 완료 뒤 caller의 acquired 대입 전에만 추가한다.
            await never_release.wait()
        return result

    async def reject_network(call):
        outbound_calls.append(call.method)
        raise AssertionError("queued cancellation must not make external HTTP requests")

    try:
        await assert_runtime_db_privilege_boundary(runtime, expected_login="ktm_feature_service")
        async with AsyncSession(runtime) as session, session.begin():
            queued = await enqueue_unpaired_import_job(
                session, kind="provider_load", payload={"isolated_k_unknown_probe": True}
            )
        job_id = queued.job_id
        before = await _state(admin, job_id)
        assert before[0][0] == "queued"
        assert before[1] == 0
        credential = uuid4().hex + uuid4().hex
        app = create_app(
            ApiSettings(
                admin_proxy_secret=credential, public_api_key_required=False, vworld_api_key=None
            )
        )
        monkeypatch.setattr(api_db, "_get_engine", lambda: runtime)
        monkeypatch.setattr(service, "_acquire_coordinator_lease", after_real_commit)
        headers = {
            "X-Kor-Travel-Map-Admin-Proxy-Secret": credential,
            "X-Kor-Travel-Map-Actor": "admin:k-unknown-lab-" + uuid4().hex,
        }
        path = f"/v1/ops/pipeline/executions/import_job/{job_id}/cancel"
        async with httpx.AsyncClient(transport=httpx.MockTransport(reject_network)) as outbound:
            monkeypatch.setattr(
                dagster_http, "http_client_from_request", lambda request, settings: outbound
            )
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app, raise_app_exceptions=False),
                base_url="http://test",
            ) as client:
                task = asyncio.create_task(
                    client.post(path, headers=headers, json={"reason": "isolated_k_unknown"}),
                    name="owned-api-task-cancel-after-k-commit",
                )
                await asyncio.wait_for(acquired.wait(), 3)
                assert not task.done()
                assert await _state(admin, job_id) == before
                task.cancel("owned-api-k-commit-unknown")
                with pytest.raises(asyncio.CancelledError):
                    await asyncio.wait_for(task, 3)
                assert task.cancelled()
                assert runtime.pool.checkedout() == 0
                observed_pids.add(await _pool_pid(runtime))
                await _no_advisory_locks(admin, observed_pids)
                assert await _state(admin, job_id) == before

                fresh = await client.post(
                    path, headers=headers, json={"reason": "isolated_k_unknown"}
                )
                assert fresh.status_code == 200, fresh.text
                detail = fresh.json()["data"]
                assert detail["status"] == "completed"
                assert detail["root"] == {"kind": "import_job", "id": job_id}
                assert detail["unresolved_member_count"] == 0
                assert len(detail["members"]) == 1
                assert detail["members"][0]["result"] == "cancelled"
                after = await _state(admin, job_id)
                assert after[0][0] == "cancelled"
                assert after[1] == 1
                replay = await client.post(
                    path, headers=headers, json={"reason": "isolated_k_unknown"}
                )
                assert replay.status_code == 200
                assert replay.json()["data"] == detail
                assert await _state(admin, job_id) == after
                observed_pids.add(await _pool_pid(runtime))
                await _no_advisory_locks(admin, observed_pids)
                assert runtime.pool.checkedout() == 0
        assert outbound_calls == []
        request.node.user_properties.extend(
            [
                ("unknown_acquire_after_real_commit", "true"),
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


@pytest.mark.parametrize("mismatch", ["backend_start", "other_login"])
async def test_exact_termination_never_signals_nonmatching_backend(scalar_engines, mismatch):
    admin, runtime = scalar_engines
    target_engine = runtime if mismatch == "backend_start" else admin
    lease_key = service._coordinator_lease_key(root_kind="import_job", root_id=str(uuid4()))
    async with target_engine.connect() as target:
        backend = service._capture_backend(target, runtime)
        backend.backend_start = await target.scalar(
            text("SELECT backend_start FROM pg_catalog.pg_stat_activity WHERE pid=pg_backend_pid()")
        )
        if mismatch == "backend_start":
            backend.backend_start -= timedelta(seconds=1)
        assert (
            await target.scalar(
                text("SELECT pg_try_advisory_lock(:key)"),
                {"key": lease_key},
            )
            is True
        )
        await target.commit()
        try:
            assert not await service._confirm_backend_termination(
                backend,
                deadline=service.monotonic() + 0.6,
            )
            # 다른 starttime 또는 LOGIN의 실제 연결은 관측 후에도 같은 PID로 사용할 수 있다.
            assert not backend.driver.is_closed()
            assert int(await target.scalar(text("SELECT pg_backend_pid()"))) == backend.pid
            assert (
                await target.scalar(
                    text("SELECT pg_advisory_unlock(:key)"),
                    {"key": lease_key},
                )
                is True
            )
            await target.commit()
        finally:
            if not target.closed and not target.invalidated:
                await target.rollback()
                await target.execute(
                    text("SELECT pg_advisory_unlock(:key)"),
                    {"key": lease_key},
                )
                await target.commit()
