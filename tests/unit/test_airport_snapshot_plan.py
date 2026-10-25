"""정본 DTO/decoder를 쓰는 client 계획 경계. DB 효과·권한은 대역이며 PG 증거가 아니다."""

from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from kortravelmap.client import _airport_snapshot as target
from kortravelmap.infra.provider_snapshot_artifact import (
    decode_provider_snapshot_artifact,
    encode_provider_snapshot_artifact,
)
from kortravelmap.infra.provider_snapshot_recovery_repo import (
    RecoveredProviderSnapshot,
    SnapshotExecutorToken,
    SnapshotKernelBinding,
)
from tests.unit.test_airport_snapshot_client import _Scope, _Session
from tests.unit.test_provider_snapshot_artifact import _PINS
from tests.unit.test_transport_airport_preparation import _fixture


async def _case(monkeypatch):
    wire, bundle = await _fixture()
    payload = encode_provider_snapshot_artifact((bundle,), None, pins=_PINS)
    sid = uuid4()
    observed = RecoveredProviderSnapshot(
        sid,
        decode_provider_snapshot_artifact(payload, expected_pins=_PINS),
        payload,
        "a" * 64,
        b"context",
        "b" * 64,
        "prepared",
        None,
        None,
        None,
        datetime(2026, 10, 25, tzinfo=UTC),
        "running",
        "running",
        False,
        None,
    )
    token = SnapshotExecutorToken(sid, 1, uuid4())
    sessions = []

    def factory():
        session = _Session()
        session.scalar = AsyncMock(
            side_effect=lambda sql, args=None: wire if "snapshot_evidence" in str(sql) else "c" * 64
        )
        sessions.append(session)
        return _Scope(session, "session")

    client = SimpleNamespace(_transaction_bound=False, _session_factory=factory)
    order = []
    stubs = {}
    for name in (
        "claim_scoped_feature_write",
        "append_scoped_feature_write_manifest",
        "seal_scoped_feature_write_manifest",
        "bind_provider_snapshot_plan",
    ):

        async def call(*args, _name=name, **kwargs):
            order.append(_name)
            return "d" * 64 if _name == "seal_scoped_feature_write_manifest" else None

        stubs[name] = AsyncMock(side_effect=call)
        monkeypatch.setattr(target, name, stubs[name])
    return client, observed, token, wire, sessions, order, stubs


async def test_rr_complete_plan_then_rc_all_three_dependencies_bind_once(monkeypatch):
    client, observed, token, wire, sessions, order, stubs = await _case(monkeypatch)
    plan = await target.plan_airport_snapshot(client, observed, token, pins=_PINS, dataset_id=15)
    assert len(sessions) == 2
    assert "REPEATABLE READ, READ ONLY" in str(sessions[0].execute.await_args_list[0].args[0])
    assert "READ COMMITTED, READ WRITE" in str(sessions[1].execute.await_args_list[0].args[0])
    assert sessions[0].events[-2:] == sessions[1].events[-2:] == ["tx:ok", "session:ok"]
    assert sessions[0].execute.await_args_list[1].args[1]["statement"] == 3000
    assert sessions[1].execute.await_args_list[1].args[1]["statement"] == 30000
    assert order == list(stubs)
    claim = stubs[order[0]].await_args
    assert claim.kwargs["lease_seconds"] == 300
    assert claim.kwargs["exclusive_protocol"] is False
    assert claim.kwargs["regions"] == ()
    assert claim.kwargs["expected_members"] == 3
    assert claim.kwargs["input_digest"] == plan.input_digest
    members = stubs[order[1]].await_args.kwargs["members"]
    assert [(m.ordinal, m.dependency_kind) for m in members] == [
        (0, "feature"),
        (1, "source_head"),
        (2, "feature_membership"),
    ]
    assert members[1].expected_value == wire["items"][0]["source_head"]["current_source_record_key"]
    assert members[2].expected_value == "c" * 64
    assert stubs[order[-1]].await_args.kwargs["manifest_digest"] == "d" * 64
    assert all(stub.await_args.args[0] is sessions[1] for stub in stubs.values())


async def test_bind_failure_rolls_back_claim_manifest_as_one_tx(monkeypatch):
    client, observed, token, _, sessions, _, stubs = await _case(monkeypatch)
    error = RuntimeError("binding failed")
    stubs["bind_provider_snapshot_plan"].side_effect = error
    with pytest.raises(RuntimeError) as raised:
        await target.plan_airport_snapshot(client, observed, token, pins=_PINS, dataset_id=15)
    assert raised.value is error
    assert sessions[0].events[-2:] == ["tx:ok", "session:ok"]
    assert sessions[1].events[-2:] == ["tx:error", "session:error"]


async def test_nonname_change_rejects_before_any_claim(monkeypatch):
    client, observed, token, wire, sessions, _, stubs = await _case(monkeypatch)
    next(row for row in wire["items"][0]["non_name_base"] if row["field_path"] == "place.phones")[
        "value_json"
    ] = ["changed"]
    with pytest.raises(target.AirportSnapshotUnavailable, match="requires EX"):
        await target.plan_airport_snapshot(client, observed, token, pins=_PINS, dataset_id=15)
    assert len(sessions) == 1
    assert sessions[0].events[-2:] == ["tx:error", "session:error"]
    for stub in stubs.values():
        stub.assert_not_awaited()


async def test_existing_ready_binding_is_reused_without_new_claim(monkeypatch):
    client, observed, token, _, sessions, _, stubs = await _case(monkeypatch)
    first = await target.plan_airport_snapshot(client, observed, token, pins=_PINS, dataset_id=15)
    binding = SnapshotKernelBinding(
        first.attempt_id,
        first.owner,
        first.manifest_digest,
        "ready",
        first.input_digest,
        observed.lease_expires_at,
    )
    for stub in stubs.values():
        stub.reset_mock()
    sessions.clear()
    plan = await target.plan_airport_snapshot(
        client, replace(observed, kernel_binding=binding), token, pins=_PINS, dataset_id=15
    )
    assert (plan.attempt_id, plan.owner, plan.manifest_digest) == (
        binding.attempt_id,
        binding.owner,
        binding.manifest_digest,
    )
    assert len(sessions) == 1
    for stub in stubs.values():
        stub.assert_not_awaited()


@pytest.mark.parametrize(("status", "digest"), [("cancelled", "a" * 64), ("ready", "b" * 64)])
async def test_bound_mismatch_never_allocates_an_unrelated_attempt(monkeypatch, status, digest):
    client, observed, token, _, sessions, _, stubs = await _case(monkeypatch)
    binding = SnapshotKernelBinding(
        uuid4(), uuid4(), "d" * 64, status, digest, observed.lease_expires_at
    )
    with pytest.raises(target.AirportSnapshotReplanRequired):
        await target.plan_airport_snapshot(
            client, replace(observed, kernel_binding=binding), token, pins=_PINS, dataset_id=15
        )
    assert len(sessions) == 1
    for stub in stubs.values():
        stub.assert_not_awaited()


@pytest.mark.parametrize("response", ["reset", "needs_read", None, True, "completed"])
async def test_reset_forwards_exact_original_binding_and_does_not_guess(monkeypatch, response):
    client, observed, token, _, sessions, _, _ = await _case(monkeypatch)
    binding = SnapshotKernelBinding(
        uuid4(), uuid4(), "d" * 64, "ready", "e" * 64, observed.lease_expires_at
    )
    original = client._session_factory

    def factory():
        context = original()
        context.session.scalar = AsyncMock(return_value=response)
        return context

    client._session_factory = factory
    if type(response) is str and response in {"reset", "needs_read"}:
        assert (
            await target.reset_airport_snapshot_plan(
                client, replace(observed, kernel_binding=binding), token
            )
            == response
        )
        assert sessions[0].events[-2:] == ["tx:ok", "session:ok"]
    else:
        with pytest.raises(target.AirportSnapshotUnavailable, match="invalid"):
            await target.reset_airport_snapshot_plan(
                client, replace(observed, kernel_binding=binding), token
            )
        assert sessions[0].events[-2:] == ["tx:error", "session:error"]
    params = sessions[0].scalar.await_args.args[1]
    assert params == {
        "snapshot": token.snapshot_id,
        "generation": token.generation,
        "fence": token.fence,
        "attempt": binding.attempt_id,
        "owner": binding.owner,
        "manifest": binding.manifest_digest,
    }


@pytest.mark.parametrize(
    "message", ["airport evidence changed after locking; replan", "other rejection"]
)
async def test_apply_replans_only_known_evidence_race_without_ex_fallback(monkeypatch, message):
    client, observed, token, _, sessions, _, _ = await _case(monkeypatch)
    plan = await target.plan_airport_snapshot(client, observed, token, pins=_PINS, dataset_id=15)
    command = AsyncMock(side_effect=ValueError(message))
    monkeypatch.setattr(target, "apply_stored_airport_reobservation", command)
    kind = (
        target.AirportSnapshotReplanRequired
        if message.startswith("airport evidence")
        else ValueError
    )
    with pytest.raises(kind):
        await target.apply_airport_snapshot(client, observed, token, plan, pins=_PINS)
    command.assert_awaited_once()
    assert command.await_args.args[1] == observed.artifact_payload
    assert command.await_args.args[2] is plan.preparation
    assert command.await_args.kwargs["attempt_id"] == plan.attempt_id
    assert sessions[-1].events[-2:] == ["tx:error", "session:error"]


async def test_apply_unknown_commit_does_not_return_or_repeat_original_counters(monkeypatch):
    client, observed, token, _, sessions, _, _ = await _case(monkeypatch)
    plan = await target.plan_airport_snapshot(client, observed, token, pins=_PINS, dataset_id=15)
    command = AsyncMock(return_value=object())
    monkeypatch.setattr(target, "apply_stored_airport_reobservation", command)
    original = client._session_factory
    error = RuntimeError("apply commit response lost")

    def factory():
        context = original()
        context.session.commit_error = error
        return context

    client._session_factory = factory
    with pytest.raises(RuntimeError) as raised:
        await target.apply_airport_snapshot(client, observed, token, plan, pins=_PINS)
    assert raised.value is error
    command.assert_awaited_once()
    assert sessions[-1].events[-1] == "session:error"


async def test_queue_bound_plan_rejects_before_even_artifact_decode(monkeypatch):
    client, observed, token, _, sessions, _, _ = await _case(monkeypatch)
    client._transaction_bound = True
    with pytest.raises(target.AirportSnapshotUnavailable, match="unbound"):
        await target.plan_airport_snapshot(
            client, replace(observed, artifact_payload=b"invalid"), token, pins=_PINS, dataset_id=15
        )
    assert sessions == []


async def test_same_executor_reset_can_claim_a_new_plan_without_unique_key_collision(monkeypatch):
    client, observed, token, wire, _, _, stubs = await _case(monkeypatch)
    keys = set()

    async def unique_claim(*args, **kwargs):
        key = kwargs["idempotency_key"]
        if key in keys:
            raise ValueError("duplicate provider_dataset_id/idempotency_key")
        keys.add(key)

    stubs["claim_scoped_feature_write"].side_effect = unique_claim
    first = await target.plan_airport_snapshot(client, observed, token, pins=_PINS, dataset_id=15)
    binding = SnapshotKernelBinding(
        first.attempt_id,
        first.owner,
        first.manifest_digest,
        "ready",
        first.input_digest,
        observed.lease_expires_at,
    )
    original = client._session_factory

    def factory():
        scope = original()
        scope.session.scalar = AsyncMock(
            side_effect=lambda sql, args=None: (
                "reset"
                if "reset_expired" in str(sql)
                else (wire if "snapshot_evidence" in str(sql) else "c" * 64)
            )
        )
        return scope

    client._session_factory = factory
    assert (
        await target.reset_airport_snapshot_plan(
            client, replace(observed, kernel_binding=binding), token
        )
        == "reset"
    )
    # SDK0 read reports unbound prepared after the committed reset. generation is unchanged.
    second = await target.plan_airport_snapshot(client, observed, token, pins=_PINS, dataset_id=15)
    assert first.attempt_id != second.attempt_id
    assert len(keys) == 2
    assert all(len(key.encode()) <= 128 for key in keys)
    assert str(first.attempt_id) in next(key for key in keys if str(first.attempt_id) in key)
    assert str(second.attempt_id) in next(key for key in keys if str(second.attempt_id) in key)
