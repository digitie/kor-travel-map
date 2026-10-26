"""Rest 재개는 SDK0/current binding/원receipt만 사용한다. PG 원자성 시험은 별도다."""

import hashlib
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from dagster import Failure
from kortravelmap.client._snapshot_atomic import SnapshotAtomicCompletion
from kortravelmap.infra.provider_snapshot_recovery_repo import (
    RecoveredProviderSnapshot,
    SnapshotExecutorLease,
    SnapshotExecutorToken,
    SnapshotKernelBinding,
)
from kortravelmap.infra.rest_area_snapshot_artifact import decode_rest_area_snapshot_artifact
from test_rest_snapshot_observation import _AT, _PINS
from test_rest_snapshot_postprocess import _input

from kortravelmap.dagster import assets
from kortravelmap.dagster import rest_snapshot_runner as target
from kortravelmap.dagster.feature_operation_tracking import FeatureOperationExecutionGuard
from kortravelmap.dagster.rest_snapshot_postprocess import prepare_rest_snapshot_postprocess
from kortravelmap.dagster.rest_snapshot_runtime import RestSnapshotRuntime


async def _case(monkeypatch, *, status="postprocessed"):
    args, load = await _input()
    intent = prepare_rest_snapshot_postprocess(**args)
    member = args["member"]
    sid = uuid4()
    observed = RecoveredProviderSnapshot(
        sid,
        decode_rest_area_snapshot_artifact(args["artifact_bytes"], expected_pins=_PINS),
        args["artifact_bytes"],
        hashlib.sha256(args["artifact_bytes"]).hexdigest(),
        args["context_bytes"],
        hashlib.sha256(args["context_bytes"]).hexdigest(),
        status,
        intent.apply_result if status != "prepared" else None,
        args["result_bytes"] if status != "prepared" else None,
        intent.receipt_candidate if status in {"postprocessed", "child_sealed"} else None,
        _AT,
        "running",
        "done" if status == "child_sealed" else "running",
        False,
        None,
    )
    token = SnapshotExecutorToken(sid, 3, uuid4())
    client = SimpleNamespace(_transaction_bound=False)
    guard = FeatureOperationExecutionGuard(
        client, object(), member.membership.operation_key, (member.membership,), "root", "schedule"
    )
    operation = SimpleNamespace(
        dagster_run_id="root",
        root_job_id=str(member.root_job_id),
        members=(
            SimpleNamespace(
                job_id=str(member.source_job_id),
                import_job_dataset_id=str(member.import_job_dataset_id),
                membership=member.membership,
            ),
        ),
    )
    monkeypatch.setattr(
        FeatureOperationExecutionGuard,
        "ensure",
        AsyncMock(return_value=SimpleNamespace(operation=operation)),
    )
    monkeypatch.setattr(
        target, "ensure_authoritative_feature_operation_guard", AsyncMock(return_value=guard)
    )
    monkeypatch.setattr(assets, "_exact_sync_membership", AsyncMock(return_value=member.membership))
    context = SimpleNamespace(
        run=SimpleNamespace(run_id="root"),
        run_id="root",
        resources=SimpleNamespace(
            kor_travel_map_client=client,
            feature_operation_guard=guard,
            rest_snapshot_runtime=RestSnapshotRuntime(_PINS),
            strict_address="strict",
        ),
    )
    stubs = {}
    for name, value in [
        ("read_rest_snapshot", observed),
        ("claim_rest_snapshot", SnapshotExecutorLease(token, _AT, status)),
        ("plan_rest_snapshot", object()),
        ("apply_rest_snapshot_in_session", intent.apply_result),
        ("reset_rest_snapshot_plan", "reset"),
        ("collect_expired_rest_snapshots", 0),
        ("seal_rest_snapshot", object()),
    ]:
        stubs[name] = AsyncMock(return_value=value)
        monkeypatch.setattr(target.io, name, stubs[name])
    collect = AsyncMock(side_effect=AssertionError("SDK/Geo/clock refetch forbidden"))
    monkeypatch.setattr(target, "_collect_rest_snapshot_input", collect)
    atomic = AsyncMock(side_effect=AssertionError("reapply forbidden"))
    monkeypatch.setattr(target, "run_snapshot_apply_postprocess", atomic)
    return context, observed, intent, stubs, collect, atomic


async def test_postprocessed_restart_is_sdk0_and_never_reapplies_or_rebuilds_findings(monkeypatch):
    context, observed, intent, stubs, collect, atomic = await _case(monkeypatch)
    result = await target.run_rest_snapshot_if_supported(context)
    assert result.load == intent.apply_result.load
    collect.assert_not_awaited()
    atomic.assert_not_awaited()
    stubs["apply_rest_snapshot_in_session"].assert_not_awaited()
    stubs["seal_rest_snapshot"].assert_awaited_once()
    assert stubs["read_rest_snapshot"].await_count == 2


@pytest.mark.parametrize(
    ("root", "blocked"),
    [("running", False), ("done", False), ("failed", True), ("cancelled", True)],
)
async def test_exact_sealed_receipt_root_completion_is_read_noop_but_failed_cancelled_reject(
    monkeypatch, root, blocked
):
    context, observed, intent, stubs, collect, atomic = await _case(
        monkeypatch, status="child_sealed"
    )
    stubs["read_rest_snapshot"].return_value = replace(observed, root_status=root)
    if blocked:
        with pytest.raises(Failure):
            await target.run_rest_snapshot_if_supported(context)
    else:
        result = await target.run_rest_snapshot_if_supported(context)
        assert result.load == intent.apply_result.load
    stubs["claim_rest_snapshot"].assert_not_awaited()
    stubs["seal_rest_snapshot"].assert_not_awaited()
    collect.assert_not_awaited()
    atomic.assert_not_awaited()


async def test_claim_always_reads_fresh_phase_before_planning_and_applies_in_shared_session(
    monkeypatch,
):
    context, observed, intent, stubs, collect, atomic = await _case(monkeypatch, status="prepared")
    fresh = replace(
        observed,
        kernel_binding=SnapshotKernelBinding(uuid4(), uuid4(), "e" * 64, "ready", "f" * 64, _AT),
    )
    post = replace(
        fresh,
        status="postprocessed",
        applied_result=intent.apply_result,
        applied_result_bytes=intent.result_bytes,
        postprocess_receipt=intent.receipt_candidate,
    )
    stubs["read_rest_snapshot"].side_effect = [observed, fresh, post]
    marker = object()

    async def run(*args, apply, prepare, **kwargs):
        result = await apply(marker)
        work = prepare(replace(post, status="applied", postprocess_receipt=None))
        assert work.receipt_candidate == intent.receipt_candidate
        return SnapshotAtomicCompletion(result, work.receipt_candidate)

    atomic.side_effect = run
    result = await target.run_rest_snapshot_if_supported(context)
    assert result.load == intent.apply_result.load
    assert stubs["plan_rest_snapshot"].await_args.args[1] is fresh
    assert stubs["apply_rest_snapshot_in_session"].await_args.args[0] is marker
    atomic.assert_awaited_once()
    collect.assert_not_awaited()


async def test_unknown_commit_is_propagated_without_auto_replay_then_sdk0_receipt_restores(
    monkeypatch,
):
    context, observed, intent, stubs, collect, atomic = await _case(monkeypatch, status="prepared")
    post = replace(
        observed,
        status="postprocessed",
        applied_result=intent.apply_result,
        applied_result_bytes=intent.result_bytes,
        postprocess_receipt=intent.receipt_candidate,
    )
    stubs["read_rest_snapshot"].side_effect = [observed, observed]
    error = OSError("commit response unknown")

    async def unknown(*args, apply, **kwargs):
        await apply(object())
        raise error

    atomic.side_effect = unknown
    with pytest.raises(OSError, match="commit response unknown") as caught:
        await target.run_rest_snapshot_if_supported(context)
    assert caught.value is error
    assert stubs["apply_rest_snapshot_in_session"].await_count == 1
    stubs["seal_rest_snapshot"].assert_not_awaited()
    stubs["read_rest_snapshot"].side_effect = None
    stubs["read_rest_snapshot"].return_value = post
    atomic.reset_mock()
    result = await target.run_rest_snapshot_if_supported(context)
    assert result.load == intent.apply_result.load
    atomic.assert_not_awaited()
    assert stubs["apply_rest_snapshot_in_session"].await_count == 1
    collect.assert_not_awaited()


async def test_applied_without_atomic_receipt_is_not_resumed_as_three_transactions(monkeypatch):
    context, observed, _, stubs, collect, atomic = await _case(monkeypatch, status="applied")
    with pytest.raises(Failure):
        await target.run_rest_snapshot_if_supported(context)
    atomic.assert_not_awaited()
    stubs["seal_rest_snapshot"].assert_not_awaited()
    collect.assert_not_awaited()


async def test_real_direct_invocation_context_returns_to_legacy_path_without_snapshot_io(
    monkeypatch,
):
    from dagster import build_asset_context

    context, _, _, stubs, collect, atomic = await _case(monkeypatch)
    with build_asset_context(resources=vars(context.resources)) as direct:
        assert await target.run_rest_snapshot_if_supported(direct) is None
    target.ensure_authoritative_feature_operation_guard.assert_not_awaited()
    stubs["read_rest_snapshot"].assert_not_awaited()
    collect.assert_not_awaited()
    atomic.assert_not_awaited()


async def test_current_run_identity_is_frozen_once_and_legacy_property_is_never_read(monkeypatch):
    context, _, intent, stubs, collect, atomic = await _case(monkeypatch)
    reads = []

    class ScheduledContext:
        resources = context.resources

        @property
        def run(self):
            reads.append(1)
            return SimpleNamespace(run_id="root" if len(reads) == 1 else "changed")

        @property
        def run_id(self):
            raise AssertionError("deprecated context run_id must not be accessed")

    result = await target.run_rest_snapshot_if_supported(ScheduledContext())
    assert result.load == intent.apply_result.load
    assert reads == [1]
    assert stubs["read_rest_snapshot"].await_count == 2
    collect.assert_not_awaited()
    atomic.assert_not_awaited()


async def test_current_run_identity_mismatch_cannot_be_replaced_by_matching_legacy_id(monkeypatch):
    context, _, _, stubs, collect, atomic = await _case(monkeypatch)
    context.run = SimpleNamespace(run_id="another-root")
    with pytest.raises(Failure) as raised:
        await target.run_rest_snapshot_if_supported(context)
    assert isinstance(raised.value.__cause__, target.io.RestSnapshotUnavailable)
    assert str(raised.value.__cause__) == "canonical scheduled snapshot root required"
    stubs["read_rest_snapshot"].assert_not_awaited()
    collect.assert_not_awaited()
    atomic.assert_not_awaited()


@pytest.mark.parametrize("present", [False, True])
async def test_disabled_runtime_still_reads_durable_snapshot_before_legacy_fallback(
    monkeypatch, present
):
    context, observed, _, stubs, collect, atomic = await _case(monkeypatch)
    context.run = SimpleNamespace(run_id="root")
    context.resources.rest_snapshot_runtime = None
    stubs["read_rest_snapshot"].return_value = observed if present else None
    if present:
        with pytest.raises(Failure) as raised:
            await target.run_rest_snapshot_if_supported(context)
        assert isinstance(raised.value.__cause__, target.io.RestSnapshotUnavailable)
        assert str(raised.value.__cause__) == "registered snapshot requires verified runtime"
    else:
        assert await target.run_rest_snapshot_if_supported(context) is None
    stubs["read_rest_snapshot"].assert_awaited_once()
    stubs["claim_rest_snapshot"].assert_not_awaited()
    collect.assert_not_awaited()
    atomic.assert_not_awaited()


@pytest.mark.parametrize(("attempt", "expected"), [(0, "root"), (2, "root::retry:2")])
def test_frozen_root_identity_preserves_existing_observation_attempt_framing(attempt, expected):
    class Context:
        retry_number = attempt

        @property
        def run_id(self):
            raise AssertionError("generation must reuse the already resolved root")

    assert target._dagster_run_id(Context(), resolved_run_id="root") == expected


@pytest.mark.parametrize("bad_root", ["", " ", 7])
def test_resolved_observation_root_rejects_invalid_identity_without_legacy_access(bad_root):
    class Context:
        @property
        def run_id(self):
            raise AssertionError("invalid explicit root cannot fall back to another identity")

    assert target._dagster_run_id(Context(), resolved_run_id=bad_root) is None


def test_native_root_requirement_does_not_change_existing_legacy_helper_contract():
    context = SimpleNamespace(run_id="legacy-direct")
    assert target._context_run_id(context) == "legacy-direct"
    assert target._context_run_id(context, require_native_run=True) is None
