"""Rest pure intent/원receipt와 같은TX callback계약. 실제DB 원자성 수용은 별도다."""

from types import SimpleNamespace
from uuid import UUID

import pytest
from kortravelmap.core.feature_operation import ProviderDatasetOperationMembership
from kortravelmap.infra.feature_repo import FeatureLoadResult
from kortravelmap.infra.provider_snapshot_result import encode_snapshot_apply_result
from test_rest_snapshot_observation import _PINS, _artifact, _encode

from kortravelmap.dagster.rest_snapshot_backend import RestSnapshotBackend
from kortravelmap.dagster.rest_snapshot_postprocess import (
    RestPostprocessMember,
    UnsupportedRestPostprocess,
    complete_rest_snapshot_postprocess,
    prepare_rest_snapshot_postprocess,
)

_MEMBER = RestPostprocessMember(
    UUID(int=1),
    UUID(int=2),
    UUID(int=3),
    ProviderDatasetOperationMembership(
        29, "dataset_wide", "feature_place_transport_rest_areas_job"
    ),
)


async def _input(count=2):
    artifact, window, _ = await _artifact(count)
    load = FeatureLoadResult(
        bundles_total=count,
        features_updated=count,
        source_records_inserted=count,
        curation_input_member_count=count,
        curation_input_set_hash="d" * 64,
    )
    args = dict(
        member=_MEMBER,
        artifact_bytes=artifact,
        context_bytes=_encode(artifact, window),
        result_bytes=encode_snapshot_apply_result(load, retired=0),
        expected_pins=_PINS,
        expected_root_run_id="root",
    )
    return args, load


class _Receipt:
    def __init__(self, receipt):
        self.receipt = receipt

    async def complete_provider_snapshot_postprocess(self, intent):
        return self.receipt


class _Bound:
    def __init__(self, fail=None):
        self.calls = []
        self.fail = fail

    async def record_address_validation_findings(self, findings, **kwargs):
        self.calls.append("findings")
        n = len({x.dedupe_key for x in findings})
        return SimpleNamespace(
            observed_count=len(findings),
            unique_count=n,
            upserted_count=n if self.fail != "count" else n + 1,
        )

    async def record_sync_success_for_operation_membership(self, **kwargs):
        self.calls.append("sync")
        if self.fail == "sync":
            raise RuntimeError("fault")

    async def close_stale_address_validation_findings(self, **kwargs):
        self.calls.append("stale")
        return 0

    def __getattr__(self, name):
        raise AssertionError("independent IO/commit forbidden: " + name)


async def test_pure_intent_exact_receipt_preserves_counters_and_callback_owns_no_transaction():
    args, load = await _input()
    intent = prepare_rest_snapshot_postprocess(**args)
    observed = SimpleNamespace(
        artifact_payload=args["artifact_bytes"],
        observation_context=args["context_bytes"],
        applied_result_bytes=args["result_bytes"],
    )
    work = RestSnapshotBackend(_MEMBER, _PINS, "root").prepare(observed)
    assert work.receipt_candidate == intent.receipt_candidate
    assert len(work.receipt_candidate) <= 4096
    bound = _Bound()
    await work.work(bound)
    assert bound.calls == ["findings", "sync", "stale"]
    complete = await complete_rest_snapshot_postprocess(_Receipt(work.receipt_candidate), intent)
    assert complete.result.load == load
    assert complete.retired == 0
    assert complete.result.dataset_key == "transport_rest_areas"
    assert intent.cursor["asset_key"] == "feature_place_transport_rest_areas"


@pytest.mark.parametrize(
    ("fault", "expected"), [("count", ["findings"]), ("sync", ["findings", "sync"])]
)
async def test_partial_work_is_not_marked_complete_or_swallowed(fault, expected):
    args, _ = await _input()
    observed = SimpleNamespace(
        artifact_payload=args["artifact_bytes"],
        observation_context=args["context_bytes"],
        applied_result_bytes=args["result_bytes"],
    )
    bound = _Bound(fault)
    with pytest.raises((UnsupportedRestPostprocess, RuntimeError)):
        await RestSnapshotBackend(_MEMBER, _PINS, "root").prepare(observed).work(bound)
    assert bound.calls == expected


async def test_retirement_and_wrong_receipt_never_become_success():
    args, load = await _input()
    with pytest.raises(UnsupportedRestPostprocess):
        prepare_rest_snapshot_postprocess(
            **{**args, "result_bytes": encode_snapshot_apply_result(load, retired=1)}
        )
    intent = prepare_rest_snapshot_postprocess(**args)
    with pytest.raises(UnsupportedRestPostprocess):
        await complete_rest_snapshot_postprocess(_Receipt(b"other"), intent)
