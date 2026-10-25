"""원 bytes/시각으로 예약 재개. DB/SDK는 대역이며 actual430 수용은 아니다."""

import asyncio
import hashlib
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from dagster import Failure
from kortravelmap.infra.provider_snapshot_artifact import decode_provider_snapshot_artifact
from kortravelmap.infra.provider_snapshot_recovery_repo import (
    RecoveredProviderSnapshot,
    SnapshotExecutorLease,
    SnapshotExecutorToken,
    SnapshotRegistration,
)
from test_airport_snapshot_observation import _AT, _PINS
from test_airport_snapshot_postprocess import _input

from kortravelmap.dagster import airport_snapshot_runner as target
from kortravelmap.dagster import assets
from kortravelmap.dagster.airport_snapshot_postprocess import prepare_airport_snapshot_postprocess
from kortravelmap.dagster.airport_snapshot_runtime import AirportSnapshotRuntime
from kortravelmap.dagster.feature_operation_tracking import FeatureOperationExecutionGuard


async def _case(monkeypatch, *, status="applied", geo=False):
    args, load, stats = await _input(count=1, geo=geo)
    intent = prepare_airport_snapshot_postprocess(**args)
    member = args["member"]
    sid = uuid4()
    observed = RecoveredProviderSnapshot(
        sid,
        decode_provider_snapshot_artifact(args["artifact_bytes"], expected_pins=_PINS),
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
        "running",
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
        run_id="root",
        retry_number=9,
        resources=SimpleNamespace(
            kor_travel_map_client=client,
            feature_operation_guard=guard,
            airport_snapshot_runtime=AirportSnapshotRuntime(_PINS),
            strict_address="strict",
        ),
    )
    stubs = {}
    for name, value in (
        ("read_airport_snapshot", observed),
        ("claim_airport_snapshot", SnapshotExecutorLease(token, _AT, status)),
        ("plan_airport_snapshot", object()),
        ("apply_airport_snapshot", object()),
        ("reset_airport_snapshot_plan", "reset"),
        ("collect_expired_airport_snapshots", 0),
        ("register_airport_snapshot", SnapshotRegistration(sid, True, token)),
        ("seal_airport_snapshot", object()),
    ):
        stub = AsyncMock(return_value=value)
        monkeypatch.setattr(target.io, name, stub)
        stubs[name] = stub
    backend = SimpleNamespace(
        complete_provider_snapshot_postprocess=AsyncMock(return_value=intent.receipt_candidate)
    )
    factory = Mock(return_value=backend)
    monkeypatch.setattr(target, "AirportSnapshotBackend", factory)
    collect = AsyncMock(side_effect=AssertionError("SDK/refetch forbidden"))
    monkeypatch.setattr(target, "_collect_or_legacy", collect)
    clock = AsyncMock(side_effect=AssertionError("new clock forbidden"))
    monkeypatch.setattr(assets, "_fetched_at", clock)
    return context, observed, token, intent, load, stats, stubs, backend, factory, collect, clock


@pytest.mark.parametrize("geo", [False, True])
async def test_registered_worker_restart_reuses_every_original_value_without_sdk_clock(
    monkeypatch, geo
):
    context, observed, token, intent, load, stats, stubs, backend, _, collect, clock = await _case(
        monkeypatch, geo=geo
    )
    result = await target.run_airport_snapshot_if_supported(context)
    assert result.load == load
    original = backend.complete_provider_snapshot_postprocess.await_args.args[0]
    assert original.artifact_bytes == observed.artifact_payload
    assert original.context_bytes == observed.observation_context
    assert original.result_bytes == observed.applied_result_bytes
    assert original.observation.observation_generation == "root::retry:2"
    assert original.observation.fetched_at == _AT
    assert original.observation.geo_stats == stats
    collect.assert_not_awaited()
    clock.assert_not_awaited()
    stubs["plan_airport_snapshot"].assert_not_awaited()
    stubs["apply_airport_snapshot"].assert_not_awaited()
    seal = stubs["seal_airport_snapshot"].await_args
    assert seal.args[1] == token
    assert seal.kwargs["postprocess_sha256"] == hashlib.sha256(intent.receipt_candidate).hexdigest()


async def test_sealed_replay_uses_durable_original_receipt_without_executor_or_effects(monkeypatch):
    context, _, _, _, load, _, stubs, backend, factory, collect, _ = await _case(
        monkeypatch, status="child_sealed"
    )
    result = await target.run_airport_snapshot_if_supported(context)
    assert result.load == load
    for name, stub in stubs.items():
        if name != "read_airport_snapshot":
            stub.assert_not_awaited()
    factory.assert_not_called()
    backend.complete_provider_snapshot_postprocess.assert_not_awaited()
    collect.assert_not_awaited()


async def test_registered_missing_runtime_is_terminal_before_sdk(monkeypatch):
    context, _, _, _, _, _, _, _, _, collect, clock = await _case(monkeypatch)
    context.resources.airport_snapshot_runtime = None
    with pytest.raises(Failure) as raised:
        await target.run_airport_snapshot_if_supported(context)
    assert raised.value.allow_retries is False
    collect.assert_not_awaited()
    clock.assert_not_awaited()


async def test_default_off_still_checks_actual_absence_before_legacy(monkeypatch):
    context, _, _, _, _, _, stubs, _, _, collect, clock = await _case(monkeypatch)
    context.resources.airport_snapshot_runtime = None
    stubs["read_airport_snapshot"].return_value = None
    assert await target.run_airport_snapshot_if_supported(context) is None
    assert stubs["read_airport_snapshot"].await_args.kwargs["pins"] is None
    collect.assert_not_awaited()
    clock.assert_not_awaited()


async def test_bound_queue_is_explicit_legacy_without_any_snapshot_read(monkeypatch):
    context, _, _, _, _, _, stubs, _, _, collect, _ = await _case(monkeypatch)
    context.resources.kor_travel_map_client._transaction_bound = True
    assert await target.run_airport_snapshot_if_supported(context) is None
    for stub in stubs.values():
        stub.assert_not_awaited()
    collect.assert_not_awaited()


async def test_new_registration_token_is_first_claim_previous_and_no_second_fetch(monkeypatch):
    context, prepared, _, intent, load, _, stubs, _, _, _, clock = await _case(
        monkeypatch, status="prepared"
    )
    applied = replace(
        prepared,
        status="applied",
        applied_result=intent.apply_result,
        applied_result_bytes=intent.result_bytes,
    )
    stubs["read_airport_snapshot"].side_effect = [None, prepared, applied]
    collect = AsyncMock(
        return_value=(prepared.artifact_payload, prepared.observation_context, None)
    )
    monkeypatch.setattr(target, "_collect_or_legacy", collect)
    result = await target.run_airport_snapshot_if_supported(context)
    assert result.load == load
    collect.assert_awaited_once()
    created = stubs["register_airport_snapshot"].return_value.token
    assert stubs["claim_airport_snapshot"].await_args.kwargs["previous"] == created
    stubs["apply_airport_snapshot"].assert_awaited_once()
    clock.assert_not_awaited()


async def test_apply_unknown_commit_propagates_without_reset_ex_or_refetch(monkeypatch):
    context, _, _, _, _, _, stubs, backend, _, collect, _ = await _case(
        monkeypatch, status="prepared"
    )
    error = RuntimeError("unknown apply commit")
    stubs["apply_airport_snapshot"].side_effect = error
    with pytest.raises(RuntimeError) as raised:
        await target.run_airport_snapshot_if_supported(context)
    assert raised.value is error
    stubs["read_airport_snapshot"].assert_awaited_once()
    stubs["reset_airport_snapshot_plan"].assert_not_awaited()
    backend.complete_provider_snapshot_postprocess.assert_not_awaited()
    collect.assert_not_awaited()


async def test_known_replan_reads_then_exact_resets_and_reads_again_before_new_plan(monkeypatch):
    context, prepared, _, intent, _, _, stubs, _, _, collect, _ = await _case(
        monkeypatch, status="prepared"
    )
    applied = replace(
        prepared,
        status="applied",
        applied_result=intent.apply_result,
        applied_result_bytes=intent.result_bytes,
    )
    events = []

    async def read(*args, **kwargs):
        events.append("read")
        return applied if len(events) == 5 else prepared

    async def reset(*args):
        events.append("reset")
        assert args[1] is prepared
        return "reset"

    stubs["read_airport_snapshot"].side_effect = read
    stubs["reset_airport_snapshot_plan"].side_effect = reset
    stubs["apply_airport_snapshot"].side_effect = [
        target.io.AirportSnapshotReplanRequired("expired"),
        object(),
    ]
    await target.run_airport_snapshot_if_supported(context)
    assert events == ["read", "read", "reset", "read", "read"]
    assert stubs["apply_airport_snapshot"].await_count == 2
    collect.assert_not_awaited()


async def test_postprocess_cancellation_never_seals_or_refetches(monkeypatch):
    context, _, _, _, _, _, stubs, backend, _, collect, _ = await _case(monkeypatch)
    backend.complete_provider_snapshot_postprocess.side_effect = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await target.run_airport_snapshot_if_supported(context)
    stubs["seal_airport_snapshot"].assert_not_awaited()
    collect.assert_not_awaited()


async def _collector_case(monkeypatch, *, eligible=True, fail_eof=False):
    args, _, _ = await _input(count=3, geo=False)
    artifact = decode_provider_snapshot_artifact(args["artifact_bytes"], expected_pins=_PINS)
    originals = tuple(
        bundle.model_copy(update={"provider_field_presence": None}) for bundle in artifact.bundles
    )
    consumed = []

    async def batches(*args, **kwargs):
        for index in range(3):
            consumed.append(index)
            yield [index]
        if fail_eof:
            raise RuntimeError("upstream EOF failed")

    async def transform(context, converter, records, **kwargs):
        assert converter is target.airports_to_bundles
        assert kwargs["fetched_at"] == _AT
        return [originals[records[0]]]

    replayed = []
    legacy_result = object()

    async def load(context, *, batches, **kwargs):
        async for batch in batches:
            replayed.extend(batch)
        return legacy_result

    monkeypatch.setattr(assets, "_record_batches", batches)
    monkeypatch.setattr(assets, "_transform_reusing_geo", transform)
    monkeypatch.setattr(assets, "_fetched_at", AsyncMock(return_value=_AT))
    monkeypatch.setattr(assets, "_reverse_geocoder", Mock(return_value=None))
    from kortravelmap.dto.geo_dataset import GeoApplied

    monkeypatch.setattr(
        assets,
        "_geo_run_inputs",
        AsyncMock(
            return_value=dict(
                geo_applied=GeoApplied(reverse=True, geocode=False),
                current_dataset=None,
                geo_stats=None,
            )
        ),
    )
    monkeypatch.setattr(assets, "_load_snapshot_batches", AsyncMock(side_effect=load))
    prepare = AsyncMock(return_value=SimpleNamespace(eligible=eligible))
    monkeypatch.setattr(target.io, "prepare_airport_snapshot_input", prepare)
    context = SimpleNamespace(run_id="root", retry_number=9)
    return context, args["member"], originals, consumed, replayed, legacy_result, prepare


async def test_budget_ex_fallback_replays_consumed_prefix_and_remaining_sdk_once(monkeypatch):
    context, member, originals, consumed, replayed, legacy, prepare = await _collector_case(
        monkeypatch
    )
    monkeypatch.setattr(target, "_MAX_ITEMS", 1)
    payload, observation, result = await target._collect_or_legacy(
        context, object(), member, AirportSnapshotRuntime(_PINS)
    )
    assert (payload, observation, result) == (None, None, legacy)
    assert consumed == [0, 1, 2]
    assert replayed == list(originals)
    assert all(bundle.provider_field_presence is None for bundle in replayed)
    prepare.assert_not_awaited()


async def test_unsupported_whole_input_fallback_keeps_original_tuple_after_eof(monkeypatch):
    context, member, originals, consumed, replayed, legacy, prepare = await _collector_case(
        monkeypatch, eligible=False
    )
    assert (
        await target._collect_or_legacy(context, object(), member, AirportSnapshotRuntime(_PINS))
    )[2] is legacy
    assert consumed == [0, 1, 2]
    assert replayed == list(originals)
    prepare.assert_awaited_once()


async def test_real_canonical_bytes_require_observed_eof_and_preserve_first_generation(monkeypatch):
    context, member, originals, consumed, replayed, _, prepare = await _collector_case(monkeypatch)
    payload, observation, legacy = await target._collect_or_legacy(
        context, object(), member, AirportSnapshotRuntime(_PINS)
    )
    assert legacy is None
    assert consumed == [0, 1, 2]
    from kortravelmap.dagster.airport_snapshot_observation import decode_airport_observation_context

    restored = decode_airport_observation_context(
        observation, artifact_bytes=payload, expected_pins=_PINS, expected_root_run_id="root"
    )
    assert restored.source_observations == 3
    assert restored.observation_generation == "root::retry:9"
    assert restored.fetched_at == _AT
    assert all(bundle.provider_field_presence is not None for bundle in restored.artifact.bundles)
    assert all(bundle.provider_field_presence is None for bundle in originals)
    assert replayed == []
    prepare.assert_awaited_once()


async def test_truncated_upstream_is_not_eof_registration_or_ex_refetch(monkeypatch):
    context, member, _, consumed, replayed, _, prepare = await _collector_case(
        monkeypatch, fail_eof=True
    )
    with pytest.raises(RuntimeError, match="EOF failed"):
        await target._collect_or_legacy(context, object(), member, AirportSnapshotRuntime(_PINS))
    assert consumed == [0, 1, 2]
    assert replayed == []
    prepare.assert_not_awaited()


async def test_existing_airport_entry_returns_registered_result_before_clock_sdk(monkeypatch):
    result = object()
    hook = AsyncMock(return_value=result)
    monkeypatch.setattr(target, "run_airport_snapshot_if_supported", hook)
    clock = AsyncMock(side_effect=AssertionError("legacy clock must not run"))
    monkeypatch.setattr(assets, "_fetched_at", clock)
    context = object()
    assert await assets.run_feature_place_transport_airports(context) is result
    hook.assert_awaited_once_with(context)
    clock.assert_not_awaited()


async def test_existing_entry_keeps_legacy_converter_pipeline_when_hook_does_not_apply(monkeypatch):
    args, _, _ = await _input(count=1, geo=False)
    bundle = decode_provider_snapshot_artifact(args["artifact_bytes"], expected_pins=_PINS).bundles[
        0
    ]
    context = object()
    hook = AsyncMock(return_value=None)
    monkeypatch.setattr(target, "run_airport_snapshot_if_supported", hook)
    clock = AsyncMock(return_value=_AT)
    monkeypatch.setattr(assets, "_fetched_at", clock)
    records = [object()]

    async def batches(*args, **kwargs):
        yield records

    monkeypatch.setattr(assets, "_record_batches", batches)
    transform = AsyncMock(return_value=[bundle])
    monkeypatch.setattr(assets, "_transform_reusing_geo", transform)
    monkeypatch.setattr(assets, "_reverse_geocoder", Mock(return_value=None))
    result = object()
    seen = []

    async def load(context, *, batches, **kwargs):
        async for batch in batches:
            seen.extend(batch)
        return result

    monkeypatch.setattr(assets, "_load_snapshot_batches", load)
    assert await assets.run_feature_place_transport_airports(context) is result
    hook.assert_awaited_once_with(context)
    clock.assert_awaited_once_with(context)
    assert transform.await_args.args[2] is records
    assert transform.await_args.args[1] is target.airports_to_bundles
    assert seen == [bundle]


async def test_absent_enabled_runs_one_bounded_gc_before_first_fetch(monkeypatch):
    context, prepared, _, intent, _, _, stubs, _, _, _, _ = await _case(
        monkeypatch, status="prepared"
    )
    applied = replace(
        prepared,
        status="applied",
        applied_result=intent.apply_result,
        applied_result_bytes=intent.result_bytes,
    )
    stubs["read_airport_snapshot"].side_effect = [None, prepared, applied]
    events = []

    async def collect(*args):
        events.append("gc16")
        return 0

    async def fetch(*args):
        events.append("fetch")
        return prepared.artifact_payload, prepared.observation_context, None

    stubs["collect_expired_airport_snapshots"].side_effect = collect
    monkeypatch.setattr(target, "_collect_or_legacy", fetch)
    await target.run_airport_snapshot_if_supported(context)
    assert events == ["gc16", "fetch"]
    stubs["collect_expired_airport_snapshots"].assert_awaited_once()


async def test_gc_failure_propagates_before_sdk_or_registration_without_retry(monkeypatch):
    context, _, _, _, _, _, stubs, _, _, collect, _ = await _case(monkeypatch)
    stubs["read_airport_snapshot"].return_value = None
    error = RuntimeError("bounded collection unavailable")
    stubs["collect_expired_airport_snapshots"].side_effect = error
    with pytest.raises(RuntimeError) as raised:
        await target.run_airport_snapshot_if_supported(context)
    assert raised.value is error
    stubs["collect_expired_airport_snapshots"].assert_awaited_once()
    stubs["register_airport_snapshot"].assert_not_awaited()
    collect.assert_not_awaited()


async def test_replan_never_exceeds_three_exact_reset_cycles_or_refetches(monkeypatch):
    context, _, _, _, _, _, stubs, _, _, collect, _ = await _case(monkeypatch, status="prepared")
    stubs["plan_airport_snapshot"].side_effect = target.io.AirportSnapshotReplanRequired("expired")
    with pytest.raises(Failure) as raised:
        await target.run_airport_snapshot_if_supported(context)
    assert raised.value.allow_retries is False
    assert stubs["plan_airport_snapshot"].await_count == 3
    assert stubs["reset_airport_snapshot_plan"].await_count == 3
    stubs["collect_expired_airport_snapshots"].assert_not_awaited()
    collect.assert_not_awaited()


async def test_actual_geo_context_preserves_builtin_stats_set_and_codec_accepts_it():
    from kortravelmap.dto.geo_dataset import GeoApplied
    from kortravelmap.infra.provider_snapshot_artifact import encode_provider_snapshot_artifact

    from kortravelmap.dagster.airport_snapshot_observation import encode_airport_observation_context
    from kortravelmap.dagster.etl import _geo_load_context

    args, _, stats = await _input(count=1, geo=True)
    artifact = decode_provider_snapshot_artifact(args["artifact_bytes"], expected_pins=_PINS)
    assert type(stats.observed_data_tokens) is set
    geo = _geo_load_context(
        GeoApplied(reverse=True, geocode=False), artifact.geo.current_dataset, stats
    )
    assert geo.observed_data_tokens is stats.observed_data_tokens
    assert type(geo.observed_data_tokens) is set
    payload = encode_provider_snapshot_artifact(artifact.bundles, geo, pins=_PINS)
    raw = encode_airport_observation_context(
        payload,
        pins=_PINS,
        root_run_id="root",
        observation_generation="root",
        upstream_eof=True,
        geo_stats=stats,
    )
    assert type(raw) is bytes
    assert raw


def test_existing_retry_policy_has_a_finite_retry_after_full_executor_lease():
    policy = assets.FEATURE_LOAD_RETRY_POLICY
    assert policy.max_retries == 3
    delays = [policy.calculate_delay(attempt_num=attempt) for attempt in (1, 2, 3)]
    assert delays == [60, 180, 420]
    assert sum(delays) >= target.io.LEASE_SECONDS == 300
