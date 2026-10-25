"""DB를 대신 증명하지 않고 intent/단일 coordinator 계약과 원 값 보존을 반증한다."""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import replace
from uuid import UUID

import pytest
from kortravelmap.core.feature_operation import ProviderDatasetOperationMembership
from kortravelmap.infra.feature_repo import FeatureLoadResult
from kortravelmap.infra.provider_snapshot_result import encode_snapshot_apply_result
from test_airport_snapshot_observation import _AT, _PINS, _artifact, _encode

from kortravelmap.dagster.airport_snapshot_postprocess import (
    AirportPostprocessMember,
    UnsupportedAirportPostprocess,
    complete_airport_snapshot_postprocess,
    prepare_airport_snapshot_postprocess,
)

_MEMBER = AirportPostprocessMember(
    UUID(int=1),
    UUID(int=2),
    UUID(int=3),
    ProviderDatasetOperationMembership(28, "dataset_wide", "feature_place_transport_airports_job"),
)


async def _input(count=15, *, geo=True, warning=False):
    artifact, stats, _ = await _artifact(count, geo=geo, warning=warning)
    context = _encode(artifact, stats)
    load = FeatureLoadResult(
        bundles_total=count,
        features_inserted=1,
        features_updated=count - 1,
        source_records_inserted=count,
        source_links_inserted=2,
        source_links_updated=13,
        curation_input_member_count=count,
        curation_input_set_hash="c" * 64,
        geo_stamps_written=14,
        geo_stale_rewritten=2,
        geo_stale_unchanged=3,
        geo_empty_guarded=1,
        geo_override_stale_findings=4,
        geo_partial_kept=5,
    )
    result = encode_snapshot_apply_result(load, retired=7)
    args = dict(
        member=_MEMBER,
        artifact_bytes=artifact,
        context_bytes=context,
        result_bytes=result,
        expected_pins=_PINS,
        expected_root_run_id="root",
    )
    return args, load, stats


class _AtomicCoordinator:
    """같은TX rollback/완료 캐시의 테스트 모형이다. 실제PG 효과의 증거가 아니다."""

    def __init__(self, fail=None, at="commit"):
        self.fail = fail
        self.at = at
        self.calls = []
        self.effects = []
        self.committed = {}

    def __getattr__(self, name):
        raise AssertionError("unexpected SDK/load/client method: " + name)

    async def complete_provider_snapshot_postprocess(self, intent):
        self.calls.append(intent)
        key = intent.member.import_job_dataset_id
        if key in self.committed:
            return self.committed[key]
        pending = []
        for stage in ("fence_latest", "findings", "sync", "stale_close", "mark", "commit"):
            if stage == self.at and self.fail is not None:
                raise self.fail
            pending.append(stage)
        self.effects.extend(pending)
        self.committed[key] = intent.receipt_candidate
        return intent.receipt_candidate


@pytest.mark.parametrize("geo", [False, True])
@pytest.mark.parametrize("warning", [False, True])
async def test_actual_fifteen_original_values_and_one_backend_commit(geo, warning):
    args, load, stats = await _input(geo=geo, warning=warning)
    intent = prepare_airport_snapshot_postprocess(**args)
    assert intent.observation.fetched_at == _AT
    assert intent.observation.observation_generation == "root::retry:2"
    assert intent.observation.geo_stats == stats
    assert intent.cursor == {
        "loaded_at": _AT.isoformat(),
        "asset_key": "feature_place_transport_airports",
        "bundles_total": 15,
        "features_inserted": 1,
        "features_updated": 14,
        "source_records_inserted": 15,
        "source_links_inserted": 2,
        "source_links_updated": 13,
    }
    assert len(intent.receipt_candidate) <= 4096
    candidate = json.loads(intent.receipt_candidate)
    assert set(candidate) == {
        "version",
        "domain",
        "root_job_id",
        "source_job_id",
        "import_job_dataset_id",
        "root_run_id",
        "artifact_sha256",
        "context_sha256",
        "result_sha256",
        "provider_dataset_id",
        "sync_scope",
        "operation_key",
        "observation_generation",
        "fetched_at",
        "source_observations",
        "findings_observed",
        "findings_unique",
        "findings_set_sha256",
        "sync_recorded",
        "stale_close_completed",
    }
    assert candidate["context_sha256"] == hashlib.sha256(args["context_bytes"]).hexdigest()
    assert candidate["result_sha256"] == hashlib.sha256(args["result_bytes"]).hexdigest()
    assert candidate["findings_unique"] == len({f.dedupe_key for f in intent.findings})
    for finding in intent.findings:
        assert finding.linked is True
        assert finding.payload["dropped"] is False
    backend = _AtomicCoordinator()
    complete = await complete_airport_snapshot_postprocess(backend, intent)
    assert len(backend.calls) == 1
    assert backend.effects == ["fence_latest", "findings", "sync", "stale_close", "mark", "commit"]
    assert complete.receipt == intent.receipt_candidate
    assert complete.result.load == load
    assert complete.retired == 7
    assert complete.result.address_validation == intent.observation.validation
    assert complete.geo_stats == stats
    if stats is not None:
        assert complete.geo_stats is not stats
    else:
        assert complete.geo_stats is None
    assert complete.result.observation_receipt.permits_stale_close


async def test_retry_uses_same_receipt_and_backend_fastpath_no_second_side_effects():
    args, _, _ = await _input(warning=True)
    intent = prepare_airport_snapshot_postprocess(**args)
    backend = _AtomicCoordinator()
    first = await complete_airport_snapshot_postprocess(backend, intent)
    events = list(backend.effects)
    second = await complete_airport_snapshot_postprocess(backend, intent)
    assert first.receipt == second.receipt
    assert len(backend.calls) == 2
    assert backend.effects == events
    assert first.result == second.result
    assert first.geo_stats is not second.geo_stats


@pytest.mark.parametrize(
    "stage", ["fence_latest", "findings", "sync", "stale_close", "mark", "commit"]
)
@pytest.mark.parametrize("cancel", [False, True])
async def test_each_backend_failure_or_cancel_propagates_and_has_no_completion(stage, cancel):
    args, _, _ = await _input()
    intent = prepare_airport_snapshot_postprocess(**args)
    failure = asyncio.CancelledError("cancel") if cancel else RuntimeError("partial " + stage)
    backend = _AtomicCoordinator(failure, stage)
    with pytest.raises(type(failure)) as caught:
        await complete_airport_snapshot_postprocess(backend, intent)
    assert caught.value is failure
    assert len(backend.calls) == 1
    assert backend.effects == []
    assert backend.committed == {}


@pytest.mark.parametrize("reply", [None, b"", b"{}", "wrong"])
async def test_no_or_wrong_backend_proof_cannot_complete(reply):
    args, _, _ = await _input()
    intent = prepare_airport_snapshot_postprocess(**args)

    class Wrong:
        async def complete_provider_snapshot_postprocess(self, request):
            return reply

    with pytest.raises(UnsupportedAirportPostprocess, match="backend did not prove"):
        await complete_airport_snapshot_postprocess(Wrong(), intent)


async def test_mutated_prepared_nested_values_are_not_sent_and_completion_has_no_backend_alias():
    args, load, stats = await _input(warning=True)
    intent = prepare_airport_snapshot_postprocess(**args)
    intent.cursor["loaded_at"] = "forged"
    intent.observation.geo_stats.calls["reverse"] = 999
    intent.findings[0].payload["dropped"] = True
    backend = _AtomicCoordinator()
    complete = await complete_airport_snapshot_postprocess(backend, intent)
    actual = backend.calls[0]
    assert actual.cursor["loaded_at"] == _AT.isoformat()
    assert actual.observation.geo_stats == stats
    assert actual.findings[0].payload["dropped"] is False
    assert complete.result.load == load
    actual.observation.geo_stats.calls["reverse"] = 321
    assert complete.geo_stats == stats


@pytest.mark.parametrize(
    "field", ["artifact_bytes", "context_bytes", "result_bytes", "expected_root_run_id"]
)
async def test_bad_original_wire_rejected_before_any_backend(field):
    args, _, _ = await _input()
    args[field] = "other-root" if field == "expected_root_run_id" else b"{}"
    with pytest.raises(ValueError, match="invalid"):
        prepare_airport_snapshot_postprocess(**args)


async def test_original_count_mismatch_rejected_without_recounting_result():
    args, load, _ = await _input()
    args["result_bytes"] = encode_snapshot_apply_result(replace(load, bundles_total=16), retired=7)
    with pytest.raises(UnsupportedAirportPostprocess, match="bundle count"):
        prepare_airport_snapshot_postprocess(**args)


@pytest.mark.parametrize("dataset", [True, 0, 2**63])
async def test_noncanonical_member_rejected(dataset):
    args, _, _ = await _input()
    membership = ProviderDatasetOperationMembership(1, "dataset_wide", "load")
    object.__setattr__(membership, "provider_dataset_id", dataset)
    args["member"] = replace(_MEMBER, membership=membership)
    with pytest.raises(UnsupportedAirportPostprocess):
        prepare_airport_snapshot_postprocess(**args)


async def test_candidate_tamper_prevents_coordinator_call():
    args, _, _ = await _input()
    intent = replace(prepare_airport_snapshot_postprocess(**args), receipt_candidate=b"{}")
    backend = _AtomicCoordinator()
    with pytest.raises(UnsupportedAirportPostprocess, match="binding changed"):
        await complete_airport_snapshot_postprocess(backend, intent)
    assert backend.calls == []


async def test_findings_set_hash_includes_full_sorted_payload():
    from kortravelmap.dagster.airport_snapshot_postprocess import _finding_set

    args, _, _ = await _input(warning=True)
    intent = prepare_airport_snapshot_postprocess(**args)
    count, digest = _finding_set(intent.findings)
    assert count == 15
    assert _finding_set(tuple(reversed(intent.findings))) == (count, digest)
    intent.findings[0].payload["provider_address"] = "다른 주소"
    assert _finding_set(intent.findings)[1] != digest


async def test_already_decoded_aliases_do_not_change_original_source_clock_or_counters():
    args, load, _ = await _input()
    intent = prepare_airport_snapshot_postprocess(**args)
    # 원래 readonly bytes에서만 다시 복원한다. public prepare는 caller의 DTO를 받지 않는다.
    intent.observation.artifact.bundles[0].source_record.fetched_at = _AT.replace(year=2030)
    backend = _AtomicCoordinator()
    complete = await complete_airport_snapshot_postprocess(backend, intent)
    assert backend.calls[0].cursor["loaded_at"] == _AT.isoformat()
    assert complete.result.load == load
    assert complete.receipt == intent.receipt_candidate


async def test_superseded_typed_error_is_not_retried_or_reinterpreted():
    class SupersededSnapshot(RuntimeError):
        pass

    args, _, _ = await _input()
    failure = SupersededSnapshot("newer applied generation")
    backend = _AtomicCoordinator(failure, "fence_latest")
    with pytest.raises(SupersededSnapshot) as caught:
        await complete_airport_snapshot_postprocess(
            backend, prepare_airport_snapshot_postprocess(**args)
        )
    assert caught.value is failure
    assert len(backend.calls) == 1
    assert not backend.effects


async def test_real_task_cancellation_during_single_coordinator_await_propagates():
    args, _, _ = await _input()
    started = asyncio.Event()
    finished = asyncio.Event()

    class Waiting:
        calls = 0

        async def complete_provider_snapshot_postprocess(self, request):
            self.calls += 1
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                finished.set()

    backend = Waiting()
    task = asyncio.create_task(
        complete_airport_snapshot_postprocess(backend, prepare_airport_snapshot_postprocess(**args))
    )
    await asyncio.wait_for(started.wait(), 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert task.cancelled()
    assert finished.is_set()
    assert backend.calls == 1
