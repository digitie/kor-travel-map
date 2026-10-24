"""예외 주입과 분리한 실제 SIGKILL: 미커밋 native 전체 DML과 완료 receipt의 복구.

자체 scalar PostGIS와 spawn한 worker 한 개만 사용한다. 외부 DSN/원천/운영 입력은 없다.
"""

from __future__ import annotations

import asyncio
import ctypes
import hashlib
import json
import multiprocessing
import os
import resource
import signal
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, cast
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from kortravelmap.dto import FeatureBundle
from kortravelmap.infra import scoped_provider_refresh as native
from kortravelmap.infra.db import make_async_engine
from tests.integration.test_scoped_native_scalar_refresh import (
    _bundle as _legacy_bundle,
)
from tests.integration.test_scoped_native_scalar_refresh import (
    _plan as _legacy_plan,
)
from tests.integration.test_scoped_native_scalar_refresh import (
    _read as _legacy_read,
)
from tests.integration.test_scoped_native_scalar_refresh import (
    _seed as _legacy_seed,
)
from tests.integration.test_scoped_native_scalar_refresh import (
    scalar_container as scalar_container,
)
from tests.integration.test_scoped_native_scalar_refresh import scalar_engines as scalar_engines

pytestmark = [pytest.mark.integration, pytest.mark.timeout(45)]

# 기존 fixture helper의 본체/동작은 재사용하며 untyped 경계만 명시한다.
_seed = cast(Callable[[AsyncEngine], Awaitable[tuple[UUID, int, str, str]]], _legacy_seed)
_bundle = cast(Callable[[str, str], FeatureBundle], _legacy_bundle)
_plan = cast(
    Callable[[AsyncEngine, UUID, int, FeatureBundle], Awaitable[dict[str, Any]]], _legacy_plan
)
_read = cast(Callable[[AsyncEngine, UUID, str], Awaitable[tuple[Any, ...]]], _legacy_read)


def _process_identity(pid: int) -> tuple[int, int]:
    # comm에는 공백/괄호가 있을 수 있다. Linux stat의 마지막 ')' 뒤에서 번호를 센다.
    fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
    return int(fields[1]), int(fields[19])  # ppid, starttime (field 22)


def _pidfd_open(pid: int) -> int:
    # 일부 standalone Python은 Linux pidfd wrapper를 빌드하지 않는다.
    # 같은 커널 API의 libc 정본을 쓰며 PID 기반 kill로 약화하지 않는다.
    library = ctypes.CDLL(None, use_errno=True)
    function = library.pidfd_open
    function.argtypes = [ctypes.c_int, ctypes.c_uint]
    function.restype = ctypes.c_int
    result = int(function(pid, 0))
    if result < 0:
        raise OSError(ctypes.get_errno(), "owned pidfd_open failed")
    return result


def _pidfd_kill(pidfd: int) -> None:
    library = ctypes.CDLL(None, use_errno=True)
    function = library.pidfd_send_signal
    function.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_void_p, ctypes.c_uint]
    function.restype = ctypes.c_int
    if function(pidfd, signal.SIGKILL, None, 0) < 0:
        raise OSError(ctypes.get_errno(), "owned pidfd_send_signal failed")


async def _apply_without_commit(pipe: Any, identity: str, request: dict[str, Any]) -> None:
    engine = make_async_engine(
        request["dsn"],
        pool_size=1,
        max_overflow=0,
        server_settings={
            "application_name": "ktm-native-crash-" + identity,
            "statement_timeout": "10000",
            "lock_timeout": "1000",
            "idle_in_transaction_session_timeout": "30000",
        },
    )
    try:
        async with AsyncSession(engine) as session, session.begin():
            backend = (
                (
                    await session.execute(
                        text("""SELECT pg_backend_pid() AS pid,backend_start,txid_current() AS xid
                    FROM pg_stat_activity WHERE pid=pg_backend_pid()""")
                    )
                )
                .mappings()
                .one()
            )
            receipt = await native.refresh_scoped_provider_scalars(
                session, FeatureBundle.model_validate(request["bundle"]), **request["plan"]
            )
            if receipt["status"] != "completed":
                raise RuntimeError("native did not finish inside the uncommitted transaction")
            pipe.send(
                {
                    "stage": "uncommitted",
                    "identity": identity,
                    "backend_pid": backend["pid"],
                    "backend_start": backend["backend_start"],
                    "xid": backend["xid"],
                    "result_digest": receipt["result_digest"],
                }
            )
            # 어떤 exception/rollback/finally도 실행하기 전에 부모가 pidfd SIGKILL한다.
            async with asyncio.timeout(20):
                await asyncio.Event().wait()
    finally:
        await engine.dispose()


def _worker(pipe: Any, identity: str, parent_pid: int) -> None:
    # core dump와 CPU/주소공간 폭주를 제한한다. 자격 값은 Pipe로만 받아 argv/env에 없다.
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_CPU, (20, 20))
    resource.setrlimit(resource.RLIMIT_AS, (1536 * 1024 * 1024, 1536 * 1024 * 1024))
    try:
        assert Path(native.__file__).resolve().parents[3] == Path(__file__).resolve().parents[2]
        ppid, start = _process_identity(os.getpid())
        if ppid != parent_pid:
            raise RuntimeError("unexpected worker parent")
        pipe.send(
            {
                "stage": "started",
                "identity": identity,
                "pid": os.getpid(),
                "parent_pid": ppid,
                "starttime": start,
            }
        )
        request = pipe.recv()
        asyncio.run(_apply_without_commit(pipe, identity, request))
    except BaseException as error:
        # SQLAlchemy/driver의 DSN·raw SQL·원천을 child traceback으로 노출하지 않는다.
        try:
            pipe.send({"stage": "error", "identity": identity, "error_class": type(error).__name__})
        finally:
            os._exit(1)
    finally:
        pipe.close()


async def _receive(pipe: Any, stage: str, identity: str) -> dict[str, Any]:
    if not await asyncio.to_thread(pipe.poll, 12):
        pytest.fail("owned native worker handshake timed out")
    try:
        message = pipe.recv()
    except EOFError:
        pytest.fail("owned native worker exited before handshake")
    assert isinstance(message, dict)
    assert message.get("identity") == identity
    if message.get("stage") == "error":
        pytest.fail("owned native worker failed: " + str(message.get("error_class")))
    assert message.get("stage") == stage
    return message


async def _scope_state(admin: Any, feature: Any, entity: str, plan: dict[str, Any]) -> str:
    # 고정 whitelist/고유 대상만 읽는다. DB 전체 scan이나 raw 출력은 하지 않는다.
    tables = {
        "feature.features": ("feature_id", feature),
        "feature.feature_places": ("feature_id", feature),
        "feature.feature_base_field_values": ("feature_id", feature),
        "feature.provider_field_active_policies": ("feature_id", feature),
        "feature.provider_field_shadow_candidates": ("feature_id", feature),
        "provider_sync.source_entities": ("source_entity_key", entity),
        "provider_sync.source_records": ("source_entity_key", entity),
        "provider_sync.source_entity_heads": ("source_entity_key", entity),
        "provider_sync.source_links": ("source_entity_key", entity),
        "ops.feature_write_attempts": ("attempt_id", plan["attempt_id"]),
        "ops.feature_write_dataset_scopes": ("provider_dataset_id", plan["dataset_id"]),
        "ops.feature_write_manifests": ("attempt_id", plan["attempt_id"]),
    }
    state = {}
    async with AsyncSession(admin) as session:
        for table, (column, value) in tables.items():
            state[table] = list(
                (
                    await session.scalars(
                        text(
                            f"SELECT to_jsonb(row) FROM {table} row WHERE {column}=:value "
                            'ORDER BY to_jsonb(row)::text COLLATE "C"'
                        ),
                        {"value": value},
                    )
                ).all()
            )
    canonical = json.dumps(state, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


async def _assert_connection_and_locks_released(admin: Any, backend: dict[str, Any]) -> None:
    async with asyncio.timeout(5):
        while True:
            async with AsyncSession(admin) as observer:
                alive = await observer.scalar(
                    text("""SELECT count(*) FROM pg_stat_activity
                WHERE pid=:pid AND backend_start=:start"""),
                    {"pid": backend["backend_pid"], "start": backend["backend_start"]},
                )
                locks = await observer.scalar(
                    text("SELECT count(*) FROM pg_locks WHERE pid=:pid"),
                    {"pid": backend["backend_pid"]},
                )
                if not alive and not locks:
                    return
            await asyncio.sleep(0.02)


async def test_sigkill_before_commit_releases_native_transaction_and_same_artifact_recovers(
    scalar_engines: Any,
    scalar_container: Any,
    monkeypatch: Any,
) -> None:
    admin, runtime = scalar_engines
    feature, dataset, entity, identity = await _seed(admin)
    bundle = _bundle(identity, "after-real-sigkill")
    plan = await _plan(runtime, feature, dataset, bundle)
    before = await _scope_state(admin, feature, entity, plan)
    assert await _read(admin, feature, entity) != (
        bundle.feature.name,
        bundle.source_record.source_record_key,
    )
    wrapped = scalar_container.get_wrapped_container()
    wrapped.reload()
    container_id = wrapped.id
    container_identity = wrapped.labels["codex.scalar-projection"]
    assert wrapped.name == "kt-map-scalar-" + container_identity
    limits = wrapped.attrs["HostConfig"]
    assert limits["NanoCpus"] == 2_000_000_000
    assert limits["Memory"] == limits["MemorySwap"] == 1536 * 1024 * 1024
    assert limits["PidsLimit"] == 256

    context = multiprocessing.get_context("spawn")
    parent_pipe, child_pipe = context.Pipe()
    worker = context.Process(target=_worker, args=(child_pipe, identity, os.getpid()))
    pidfd = None
    start = None
    backend = None
    try:
        worker.start()
        child_pipe.close()
        assert worker.pid is not None
        start = _process_identity(worker.pid)
        assert start[0] == os.getpid()
        pidfd = _pidfd_open(worker.pid)
        started = await _receive(parent_pipe, "started", identity)
        assert (started["parent_pid"], started["starttime"]) == start
        assert started["pid"] == worker.pid
        # 실제 owned fixture에서 만든 URL만 보낸다. 프로세스 argv/env/출력에는 없다.
        parent_pipe.send(
            {
                "dsn": runtime.url.render_as_string(hide_password=False),
                "bundle": bundle,
                "plan": plan,
            }
        )
        backend = await _receive(parent_pipe, "uncommitted", identity)
        async with AsyncSession(admin) as observer:
            observed = (
                (
                    await observer.execute(
                        text("""SELECT state,backend_xid::text AS xid,
                application_name,current_database() AS database FROM pg_stat_activity
                WHERE pid=:pid AND backend_start=:start"""),
                        {"pid": backend["backend_pid"], "start": backend["backend_start"]},
                    )
                )
                .mappings()
                .one()
            )
            assert observed["state"] == "idle in transaction"
            assert int(observed["xid"]) == backend["xid"]
            assert observed["application_name"] == "ktm-native-crash-" + identity
            assert observed["database"] == runtime.url.database
            assert (
                await observer.scalar(
                    text("""SELECT count(*) FROM pg_locks
                WHERE pid=:pid AND locktype='advisory' AND granted
                AND mode='ShareLock'
                AND classid=1369104691::oid AND objid=115::oid AND objsubid=2"""),
                    {"pid": backend["backend_pid"]},
                )
                == 1
            )
        # 자식은 전체 DML/finish를 마쳤지만 commit 전이므로 외부 정본은 아직 그대로다.
        assert await _scope_state(admin, feature, entity, plan) == before
        assert _process_identity(worker.pid) == start
        _pidfd_kill(pidfd)
        await asyncio.to_thread(worker.join, 5)
        assert not worker.is_alive()
        assert worker.exitcode == -signal.SIGKILL
        await _assert_connection_and_locks_released(admin, backend)
        assert await _scope_state(admin, feature, entity, plan) == before
        async with AsyncSession(admin) as observer, observer.begin():
            assert await observer.scalar(text("SELECT pg_try_advisory_xact_lock(1369104691,115)"))
            for table, column, value in [
                ("ops.feature_write_dataset_scopes", "provider_dataset_id", dataset),
                ("provider_sync.source_entity_heads", "source_entity_key", entity),
                ("provider_sync.source_links", "source_entity_key", entity),
                ("feature.features", "feature_id", feature),
            ]:
                assert (
                    await observer.execute(
                        text(f"SELECT 1 FROM {table} WHERE {column}=:value FOR UPDATE NOWAIT"),
                        {"value": value},
                    )
                ).scalar_one() == 1
        async with AsyncSession(runtime) as session, session.begin():
            recovered = await native.refresh_scoped_provider_scalars(session, bundle, **plan)
        assert recovered["status"] == "completed"
        assert recovered["result_digest"] == backend["result_digest"]
        assert await _read(admin, feature, entity) == (
            bundle.feature.name,
            bundle.source_record.source_record_key,
        )
        async with AsyncSession(admin) as observer:
            assert (
                await observer.scalar(
                    text("""SELECT count(*) FROM provider_sync.source_records
                WHERE source_record_key=:record"""),
                    {"record": bundle.source_record.source_record_key},
                )
                == 1
            )
            assert (
                await observer.scalar(
                    text("""SELECT count(*) FROM ops.feature_write_attempts
                WHERE attempt_id=:attempt AND status='completed'"""),
                    {"attempt": plan["attempt_id"]},
                )
                == 1
            )
        committed = await _scope_state(admin, feature, entity, plan)

        async def no_dml(*args: Any, **kwargs: Any) -> None:
            pytest.fail("completed receipt replay performed source DML")

        with monkeypatch.context() as patch:
            patch.setattr(native, "_upsert_source_record_state", no_dml)
            async with AsyncSession(runtime) as session, session.begin():
                replay = await native.refresh_scoped_provider_scalars(session, bundle, **plan)
        assert replay["result_digest"] == recovered["result_digest"]
        assert await _scope_state(admin, feature, entity, plan) == committed
        print(
            json.dumps(
                {
                    "test": "actual-native-sigkill",
                    "container_id": container_id,
                    "container_identity": container_identity,
                    "worker_exitcode": worker.exitcode,
                    "backend_gone": True,
                    "backend_locks": 0,
                    "rollback_state_equal": True,
                    "same_artifact_retry": "completed",
                    "completed_replay_dml": 0,
                    "completed_attempts": 1,
                    "new_raw_record_count": 1,
                },
                sort_keys=True,
            )
        )
    finally:
        if worker.pid is not None and worker.is_alive():
            if pidfd is None:
                # request를 보내기 전이면 EOF가 child의 시작 대기를 닫는다.
                parent_pipe.close()
            else:
                assert start is not None
                try:
                    assert _process_identity(worker.pid) == start
                    _pidfd_kill(pidfd)
                except ProcessLookupError:
                    pass  # 이미 종료한 owned pidfd만 허용한다.
                except FileNotFoundError:
                    pass  # stat 읽기 직전의 자식 종료 race.
            await asyncio.to_thread(worker.join, 5)
            assert not worker.is_alive()
        if backend is not None:
            await _assert_connection_and_locks_released(admin, backend)
        if pidfd is not None:
            os.close(pidfd)
        parent_pipe.close()
        child_pipe.close()
        if worker.pid is not None:
            worker.close()
