"""Airport1/Rest2의 실제 spawn worker와 미commit source overlap을 검증한다.

기존 정본 등록/claim/원자 적용/별도seal을 재사용하며 SDK·Geo·운영 profile은 켜지 않는다.
"""

from __future__ import annotations

import asyncio
import json
import multiprocessing
import os
import pickle
import resource
import time
from dataclasses import replace
from pathlib import Path

import pytest
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.client import AsyncKorTravelMapClient
from kortravelmap.client import _snapshot_atomic as snapshot_atomic
from kortravelmap.infra.db import make_async_engine
from tests.integration.test_rest_snapshot_two_writers import (
    _assert_postprocessed_and_seal,
    _cancel_ready,
    _prepare_airport_case,
    _prepare_rest_case,
    _run_case,
    _topics,
)
from tests.integration.test_rest_snapshot_two_writers import (
    pair_baselines as pair_baselines,
)
from tests.integration.test_rest_snapshot_two_writers import (
    scalar_container as scalar_container,
)
from tests.integration.test_rest_snapshot_two_writers import (
    scalar_engines as scalar_engines,
)
from tests.integration.test_scoped_native_worker_crash import (
    _pidfd_kill,
    _pidfd_open,
    _process_identity,
)
from tests.integration.test_state_lifecycle_protocol_entry import (
    owned_scalar_resource_bounds as owned_scalar_resource_bounds,
)

pytestmark = [pytest.mark.integration, pytest.mark.timeout(40)]
_MESSAGE_LIMIT = 256 * 1024


def _send(pipe, message):
    encoded = pickle.dumps(message, protocol=5)
    if len(encoded) > _MESSAGE_LIMIT:
        raise ValueError("owned worker message exceeds the fixed bound")
    pipe.send_bytes(encoded)


def _recv(pipe):
    # 양쪽 끝은 부모가 만든 own Pipe뿐이다. DSN은 argv/env/출력에 보내지 않는다.
    return pickle.loads(pipe.recv_bytes(_MESSAGE_LIMIT))


async def _receive(pipe, stage, profile, *, poll_seconds=5):
    if not await asyncio.to_thread(pipe.poll, poll_seconds):
        raise TimeoutError("owned snapshot worker stage deadline")
    message = _recv(pipe)
    assert isinstance(message, dict)
    assert message.get("profile") == profile
    if message.get("stage") == "error":
        raise AssertionError("owned snapshot worker failed: " + message["error_class"])
    assert message.get("stage") == stage
    return message


async def _apply(pipe, profile, request):
    engine = make_async_engine(
        request["dsn"],
        pool_size=1,
        max_overflow=0,
        server_settings={"application_name": "ktm-snapshot-pair-" + profile},
    )
    case = replace(request["case"], client=AsyncKorTravelMapClient(engine))
    measures = {}

    def before_sql(connection, cursor, statement, parameters, context, executemany):
        if "ops.begin_provider_snapshot_postprocess(" in statement:
            measures["topic_begin_ns"] = time.perf_counter_ns()
            _send(pipe, {"stage": "topic_begin", "profile": profile})

    event.listen(engine.sync_engine, "before_cursor_execute", before_sql)

    async def before_apply(session, identity):
        xid = await session.scalar(text("SELECT txid_current()"))
        _send(
            pipe,
            {
                "stage": "backend",
                "profile": profile,
                "backend": identity,
                "xid": xid,
                "before_apply_ns": time.perf_counter_ns(),
            },
        )

    async def after_apply(session, identity, result):
        assert result.load.bundles_total == (1 if profile == "airport" else 2)
        _send(
            pipe,
            {"stage": "source", "profile": profile, "source_return_ns": time.perf_counter_ns()},
        )

    async def hold_after_work(bound, fresh):
        _send(pipe, {"stage": "held", "profile": profile, "held_ns": time.perf_counter_ns()})
        await _receive(pipe, "release", profile)
        measures["released_ns"] = time.perf_counter_ns()

    try:
        completion = await _run_case(
            case,
            before_apply=before_apply,
            after_apply=after_apply,
            after_work=hold_after_work if request["leader"] else None,
        )
        _send(
            pipe,
            {
                "stage": "committed",
                "profile": profile,
                "completion": completion,
                "commit_ack_ns": time.perf_counter_ns(),
                "measures": measures,
            },
        )
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", before_sql)
        async with asyncio.timeout(5):
            await engine.dispose()


def _worker(pipe, profile, parent_pid):
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_CPU, (20, 20))
    resource.setrlimit(resource.RLIMIT_AS, (1536 * 1024**2, 1536 * 1024**2))
    try:
        assert (
            Path(snapshot_atomic.__file__).resolve().parents[3]
            == Path(__file__).resolve().parents[2]
        )
        ppid, start = _process_identity(os.getpid())
        assert ppid == parent_pid
        _send(
            pipe,
            {
                "stage": "started",
                "profile": profile,
                "pid": os.getpid(),
                "parent_pid": ppid,
                "starttime": start,
            },
        )
        if not pipe.poll(12):
            raise TimeoutError("owned worker request deadline")
        asyncio.run(_apply(pipe, profile, _recv(pipe)))
    except BaseException as error:
        try:
            _send(pipe, {"stage": "error", "profile": profile, "error_class": type(error).__name__})
        finally:
            os._exit(1)
    finally:
        pipe.close()


async def _exact_topic_blocker(admin, blocked, holder):
    follower_pid, follower_start, follower_login = blocked["backend"]
    leader_pid, leader_start, leader_login = holder["backend"]
    assert follower_pid != leader_pid
    async with asyncio.timeout(0.8), AsyncSession(admin) as observer:
        while True:
            async with observer.begin():
                await observer.execute(text("SET TRANSACTION READ ONLY"))
                await observer.execute(text("SET LOCAL statement_timeout='300ms'"))
                row = (
                    await observer.execute(
                        text("""SELECT a.wait_event_type,a.wait_event,pg_blocking_pids(a.pid),
                        a.query LIKE 'SELECT ops.begin_provider_snapshot_postprocess%',
                        EXISTS(SELECT 1 FROM pg_locks l WHERE l.pid=a.pid
                          AND l.locktype='transactionid' AND NOT l.granted
                          AND l.transactionid::text=:xid),
                        EXISTS(SELECT 1 FROM pg_stat_activity h WHERE h.pid=:holder
                          AND h.backend_start=:holder_start AND h.usename=:holder_login
                          AND h.state='idle in transaction' AND h.backend_xid::text=:xid),
                        EXISTS(SELECT 1 FROM pg_locks l WHERE l.pid=:holder
                          AND l.relation='ops.ops_live_topic_revisions'::regclass
                          AND l.granted AND l.mode='RowExclusiveLock')
                        FROM pg_stat_activity a WHERE a.pid=:pid AND a.backend_start=:started
                          AND a.usename=:login"""),
                        {
                            "pid": follower_pid,
                            "started": follower_start,
                            "login": follower_login,
                            "holder": leader_pid,
                            "holder_start": leader_start,
                            "holder_login": leader_login,
                            "xid": str(holder["xid"]),
                        },
                    )
                ).one()
            if row[0] == "Lock":
                assert row[2] == [leader_pid]
                assert all(row[index] is True for index in (3, 4, 5, 6))
                return row[1]
            await asyncio.sleep(0.005)


async def _cleanup(workers, pipes, identities, pidfds, primary):
    # 전체 자식2 회수에 공유15초. foreign PID나 일반 process pattern은 사용하지 않는다.
    deadline = time.monotonic() + 15
    cleanup_error = primary

    def preserve(error):
        nonlocal cleanup_error
        if cleanup_error is None:
            cleanup_error = error
        else:
            cleanup_error.add_note("owned worker cleanup failed: " + type(error).__name__)

    for profile, process in workers.items():
        try:
            if process.pid is not None:
                await asyncio.to_thread(process.join, min(1, max(0, deadline - time.monotonic())))
                if process.is_alive():
                    actual = _process_identity(process.pid)
                    assert actual[0] == os.getpid()
                    if profile in identities:
                        assert actual == identities[profile]
                    else:
                        identities[profile] = actual
                    if profile not in pidfds:
                        pidfds[profile] = _pidfd_open(process.pid)
                    assert _process_identity(process.pid) == identities[profile]
                    _pidfd_kill(pidfds[profile])
                    await asyncio.to_thread(process.join, max(0, deadline - time.monotonic()))
                assert not process.is_alive()
            process.close()
        except BaseException as error:
            preserve(error)
        finally:
            for pipe in pipes[profile]:
                try:
                    pipe.close()
                except BaseException as error:
                    preserve(error)
            if profile in pidfds:
                try:
                    os.close(pidfds[profile])
                except BaseException as error:
                    preserve(error)
    return cleanup_error


@pytest.mark.parametrize("leader", ["airport", "rest"])
async def test_spawn_workers_overlap_source_then_serialize_topics_and_seal_separately(
    scalar_engines, pair_baselines, rest_catalog, leader, request
):
    admin, runtime = scalar_engines
    airport = await _prepare_airport_case(runtime, pair_baselines)
    rest = await _prepare_rest_case(admin, runtime, rest_catalog, count=2)
    cases = {"airport": airport, "rest": rest}
    follower = "rest" if leader == "airport" else "airport"
    before = await _topics(admin)
    context = multiprocessing.get_context("spawn")
    workers, pipes, identities, pidfds, starts, backend = {}, {}, {}, {}, {}, {}
    source, committed, primary = {}, {}, None
    try:
        for profile in cases:
            parent_pipe, child_pipe = context.Pipe()
            pipes[profile] = parent_pipe, child_pipe
            process = context.Process(target=_worker, args=(child_pipe, profile, os.getpid()))
            workers[profile] = process
            process.start()
            child_pipe.close()
            assert process.pid is not None
            identities[profile] = _process_identity(process.pid)
            assert identities[profile][0] == os.getpid()
            pidfds[profile] = _pidfd_open(process.pid)
        messages = await asyncio.gather(
            *(_receive(pipes[p][0], "started", p, poll_seconds=12) for p in cases)
        )
        for profile, started in zip(cases, messages, strict=True):
            assert (started["parent_pid"], started["starttime"]) == identities[profile]
            assert started["pid"] == workers[profile].pid
            starts[profile] = started
        assert starts["airport"]["pid"] != starts["rest"]["pid"]
        for profile in (leader, follower):
            parent_pipe = pipes[profile][0]
            _send(
                parent_pipe,
                {
                    "case": replace(cases[profile], client=None),
                    "dsn": runtime.url.render_as_string(hide_password=False),
                    "leader": profile == leader,
                },
            )
            backend[profile] = await _receive(parent_pipe, "backend", profile)
            source[profile] = await _receive(parent_pipe, "source", profile)
            await _receive(parent_pipe, "topic_begin", profile)
            if profile == leader:
                held = await _receive(parent_pipe, "held", profile)
        assert backend["airport"]["xid"] != backend["rest"]["xid"]
        assert backend["airport"]["backend"] != backend["rest"]["backend"]
        assert held["held_ns"] < source[follower]["source_return_ns"]
        wait = await _exact_topic_blocker(admin, backend[follower], backend[leader])
        _send(pipes[leader][0], {"stage": "release", "profile": leader})
        for profile in (leader, follower):
            committed[profile] = await _receive(pipes[profile][0], "committed", profile)
            assert (
                source[profile]["source_return_ns"]
                <= committed[profile]["measures"]["topic_begin_ns"]
                <= committed[profile]["commit_ack_ns"]
            )
            assert source[follower]["source_return_ns"] < committed[profile]["commit_ack_ns"]
        after = await _topics(admin)
        assert after["provider_sync"] >= before["provider_sync"] + 2
        assert after["dataset_projection"] >= before["dataset_projection"] + 2
        counts = {}
        for profile, case in cases.items():
            async with AsyncSession(admin) as observer:
                same_transaction = (
                    await observer.execute(
                        text("""SELECT attempt.apply_txid,control.postprocess_txid,control.status
                        FROM ops.provider_snapshot_controls control
                        JOIN ops.feature_write_attempts attempt USING(attempt_id)
                        WHERE control.snapshot_id=:snapshot"""),
                        {"snapshot": case.token.snapshot_id},
                    )
                ).one()
                assert tuple(same_transaction) == (
                    backend[profile]["xid"],
                    backend[profile]["xid"],
                    "postprocessed",
                )
            counts[profile] = await _assert_postprocessed_and_seal(
                case, committed[profile]["completion"]
            )
        assert counts == {"airport": 1, "rest": 0}
        request.node.user_properties.append(
            (
                "os_worker_pair",
                json.dumps(
                    {
                        "leader": leader,
                        "worker_pids": {p: value["pid"] for p, value in starts.items()},
                        "worker_starttimes": {p: value["starttime"] for p, value in starts.items()},
                        "distinct_backends_and_xids": True,
                        "source_transaction_lifetimes_overlap": True,
                        "exact_topic_blocker": wait,
                        "findings": counts,
                        "child_seal": "separate TX after both original commit ACKs",
                        "pool_per_child": 1,
                        "operating_cpu_rss": "not measured",
                    },
                    sort_keys=True,
                ),
            )
        )
    except BaseException as error:
        primary = error
        raise
    finally:
        cleanup_error = await _cleanup(workers, pipes, identities, pidfds, primary)
        for case in cases.values():
            try:
                await _cancel_ready(runtime, case)
            except BaseException as error:
                if cleanup_error is None:
                    cleanup_error = error
                else:
                    cleanup_error.add_note(
                        "owned ready-plan cleanup failed: " + type(error).__name__
                    )
        if primary is None and cleanup_error is not None:
            raise cleanup_error
