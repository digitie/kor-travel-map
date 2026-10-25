"""새 client TX의 commit 응답/취소 경계. PostgreSQL 수용 증거는 아니다."""

import asyncio
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from kortravelmap.client import _airport_snapshot as target
from kortravelmap.infra.provider_snapshot_recovery_repo import SnapshotExecutorToken, SnapshotMember
from kortravelmap.infra.transaction_limits import transaction_deadline
from tests.unit.test_provider_snapshot_artifact import _PINS


class _Scope:
    def __init__(self, session, label):
        self.session, self.label = session, label

    async def __aenter__(self):
        self.session.events.append(self.label + ":enter")
        return self.session

    async def __aexit__(self, kind, error, trace):
        self.session.events.append(self.label + (":ok" if kind is None else ":error"))
        if self.label == "tx" and kind is None and self.session.commit_error is not None:
            raise self.session.commit_error


class _Session:
    def __init__(self):
        self.events = []
        self.execute = AsyncMock()
        self.commit_error = None

    def begin(self):
        return _Scope(self, "tx")


def _client():
    session = _Session()
    calls = []

    def factory():
        calls.append(True)
        return _Scope(session, "session")

    return SimpleNamespace(_transaction_bound=False, _session_factory=factory), session, calls


def _call(client, name):
    member = SnapshotMember(uuid4(), uuid4(), uuid4())
    token = SnapshotExecutorToken(uuid4(), 1, uuid4())
    if name == "read":
        return target.read_airport_snapshot(client, member, pins=_PINS)
    if name == "register":
        return target.register_airport_snapshot(
            client, member, payload=b"input", context=b"context", pins=_PINS
        )
    if name == "claim":
        observed = SimpleNamespace(
            snapshot_id=token.snapshot_id, artifact_sha256="a" * 64, context_sha256="b" * 64
        )
        return target.claim_airport_snapshot(client, observed)
    return target.seal_airport_snapshot(
        client,
        token,
        artifact_sha256="a" * 64,
        context_sha256="b" * 64,
        result_sha256="c" * 64,
        postprocess_sha256="d" * 64,
    )


_NAMES = {
    "read": "read_provider_snapshot_for_member",
    "register": "register_provider_snapshot_artifact",
    "claim": "claim_provider_snapshot_executor",
    "seal": "seal_provider_snapshot_member",
}


@pytest.mark.parametrize("name", _NAMES)
async def test_bound_queue_client_rejected_before_session(name):
    client, session, calls = _client()
    client._transaction_bound = True
    with pytest.raises(target.AirportSnapshotUnavailable, match="unbound client"):
        await _call(client, name)
    assert calls == []
    session.execute.assert_not_called()


@pytest.mark.parametrize("name", _NAMES)
async def test_success_exits_commit_scope_before_return_and_forwards_once(monkeypatch, name):
    client, session, calls = _client()
    value = object()
    command = AsyncMock(return_value=value)
    monkeypatch.setattr(target, _NAMES[name], command)
    assert await _call(client, name) is value
    assert calls == [True]
    assert session.events == ["session:enter", "tx:enter", "tx:ok", "session:ok"]
    command.assert_awaited_once()
    assert command.await_args.args[0] is session
    mode, limits = session.execute.await_args_list
    assert "READ COMMITTED" in str(mode.args[0])
    assert ("READ ONLY" in str(mode.args[0])) is (name == "read")
    assert limits.args[1] == {"statement": 30000, "lock": 1000}
    assert "LEAST" in str(limits.args[0])
    if name in {"claim", "register"}:
        assert command.await_args.kwargs["lease_seconds"] == 300


@pytest.mark.parametrize("name", _NAMES)
async def test_database_error_propagates_and_rolls_back_without_retry(monkeypatch, name):
    client, session, calls = _client()
    error = RuntimeError("database failure")
    command = AsyncMock(side_effect=error)
    monkeypatch.setattr(target, _NAMES[name], command)
    with pytest.raises(RuntimeError, match="database failure") as raised:
        await _call(client, name)
    assert raised.value is error
    assert session.events[-2:] == ["tx:error", "session:error"]
    command.assert_awaited_once()
    assert len(calls) == 1


async def test_unknown_commit_never_returns_candidate_or_retries(monkeypatch):
    client, session, calls = _client()
    error = RuntimeError("commit response lost")
    session.commit_error = error
    command = AsyncMock(return_value=object())
    monkeypatch.setattr(target, _NAMES["register"], command)
    with pytest.raises(RuntimeError, match="commit response lost") as raised:
        await _call(client, "register")
    assert raised.value is error
    assert len(calls) == 1
    command.assert_awaited_once()
    assert session.events[-1] == "session:error"


async def test_actual_task_cancellation_reaches_owned_transaction_cleanup(monkeypatch):
    client, session, calls = _client()
    entered = asyncio.Event()

    async def command(*args, **kwargs):
        entered.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(target, _NAMES["read"], command)
    task = asyncio.create_task(_call(client, "read"))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert task.cancelled()
    assert session.events[-2:] == ["tx:error", "session:error"]
    assert len(calls) == 1


@pytest.mark.parametrize("present", [False, True])
async def test_missing_runtime_proves_absence_or_blocks_before_sdk(monkeypatch, present):
    client, session, calls = _client()
    session.scalar = AsyncMock(return_value=present)
    read = AsyncMock()
    monkeypatch.setattr(target, "read_provider_snapshot_for_member", read)
    member = SnapshotMember(uuid4(), uuid4(), uuid4())
    if present:
        with pytest.raises(target.AirportSnapshotUnavailable, match="verified runtime pins"):
            await target.read_airport_snapshot(client, member, pins=None)
    else:
        assert await target.read_airport_snapshot(client, member, pins=None) is None
    assert len(calls) == 1
    session.scalar.assert_awaited_once()
    assert "SELECT EXISTS" in str(session.scalar.await_args.args[0])
    assert session.scalar.await_args.args[1] == {
        "root": member.root_id,
        "child": member.child_id,
        "member": member.member_id,
    }
    read.assert_not_awaited()


@pytest.mark.parametrize(("repeatable", "statement"), [(False, 30000), (True, 3000)])
async def test_transaction_uses_shared_deadline_and_existing_setting_minimum(repeatable, statement):
    client, session, _ = _client()
    with transaction_deadline(time.monotonic() + 60):
        async with target._transaction(client, readonly=True, repeatable=repeatable):
            pass
    mode, limits = session.execute.await_args_list
    assert ("REPEATABLE READ" in str(mode.args[0])) is repeatable
    assert limits.args[1] == {"statement": statement, "lock": 1000}
    assert "LEAST(COALESCE(NULLIF(setting::bigint,0),cap),cap)" in str(limits.args[0])
