"""재시도에서 과거 카운트를 재계산하거나 retired를 잃지 않는 결과 경계."""

import json
from dataclasses import fields, replace

import pytest

from kortravelmap.infra.feature_repo import FeatureLoadResult
from kortravelmap.infra.provider_snapshot_result import (
    InvalidSnapshotApplyResult,
    decode_snapshot_apply_result,
    encode_snapshot_apply_result,
)


def _load():
    return FeatureLoadResult(
        bundles_total=15,
        features_inserted=1,
        features_updated=14,
        source_records_inserted=15,
        source_links_inserted=2,
        source_links_updated=13,
        curation_input_member_count=15,
        curation_input_set_hash="a" * 64,
        geo_stamps_written=14,
        geo_stale_rewritten=2,
        geo_stale_unchanged=3,
        geo_empty_guarded=1,
        geo_override_stale_findings=4,
        geo_partial_kept=5,
    )


def test_all_original_fields_and_retirement_roundtrip_without_default_loss():
    load = _load()
    raw = encode_snapshot_apply_result(load, retired=7)
    result = decode_snapshot_apply_result(raw)
    assert result.load == load
    assert result.load is not load
    assert result.retired == 7
    assert {field.name for field in fields(FeatureLoadResult)} == set(json.loads(raw)["load"])
    assert encode_snapshot_apply_result(result.load, retired=result.retired) == raw


def test_max_bigint_everywhere_fits_small_result_budget():
    values = {field.name: 2**63 - 1 for field in fields(FeatureLoadResult)}
    values["curation_input_set_hash"] = "f" * 64
    raw = encode_snapshot_apply_result(FeatureLoadResult(**values), retired=2**63 - 1)
    assert len(raw) < 1024 < 4096
    assert decode_snapshot_apply_result(raw).retired == 2**63 - 1


@pytest.mark.parametrize("bad", [True, False, -1, 2**63, 1.0, "1", None])
@pytest.mark.parametrize(
    "field", [f.name for f in fields(FeatureLoadResult) if f.name != "curation_input_set_hash"]
)
def test_each_counter_rejects_coercion_overflow_or_missing(field, bad):
    with pytest.raises(InvalidSnapshotApplyResult):
        encode_snapshot_apply_result(replace(_load(), **{field: bad}), retired=0)


@pytest.mark.parametrize("bad", [True, -1, 2**63, 1.0, "1", None])
def test_retired_is_not_invented_or_coerced(bad):
    with pytest.raises(InvalidSnapshotApplyResult):
        encode_snapshot_apply_result(_load(), retired=bad)


@pytest.mark.parametrize("bad", [None, "a" * 63, "a" * 65, "A" * 64, 1, True])
def test_full_result_requires_exact_causal_capture(bad):
    with pytest.raises(InvalidSnapshotApplyResult):
        encode_snapshot_apply_result(replace(_load(), curation_input_set_hash=bad), retired=0)


@pytest.mark.parametrize(
    "mutation",
    [
        "missing",
        "extra",
        "duplicate",
        "version",
        "float",
        "negative",
        "domain",
        "whitespace",
        "capture_null",
    ],
)
def test_decoder_rejects_partial_tampered_noncanonical_results(mutation):
    raw = encode_snapshot_apply_result(_load(), retired=7)
    value = json.loads(raw)
    if mutation == "missing":
        del value["load"]["geo_partial_kept"]
    elif mutation == "extra":
        value["load"]["new_counter"] = 1
    elif mutation == "duplicate":
        raw = b'{"version":1,' + raw[1:]
    elif mutation == "version":
        value["version"] = True
    elif mutation == "float":
        value["retired"] = 7.0
    elif mutation == "negative":
        value["retired"] = -1
    elif mutation == "domain":
        value["domain"] += "-other"
    elif mutation == "capture_null":
        value["load"]["curation_input_member_count"] = None
    if mutation not in {"duplicate", "whitespace"}:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    elif mutation == "whitespace":
        raw = json.dumps(value).encode()
    with pytest.raises(InvalidSnapshotApplyResult):
        decode_snapshot_apply_result(raw)


@pytest.mark.parametrize("raw", [b"[" * 2000, b"{" * 2000, b"x" * 4097, b"", b"\xff", b'{"x":NaN}'])
def test_invalid_bytes_are_rejected_before_unbounded_parse(raw):
    with pytest.raises(InvalidSnapshotApplyResult):
        decode_snapshot_apply_result(raw)
