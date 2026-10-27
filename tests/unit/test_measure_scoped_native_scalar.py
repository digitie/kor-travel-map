"""제한 native 측정의 고정 입력/안전 계획/기존 지표 계약을 실제 PG 없이 검사한다."""

from __future__ import annotations

import json

import pytest

from scripts._scoped_write_baseline_pg import cpu_delta
from scripts.measure_scoped_native_scalar import (
    bundle,
    feature_id,
    fixture_digest,
    plan,
    summarize,
)
from scripts.scoped_write_baseline import interval_overlap


def test_fixture_identity_clock_and_presence_are_reproducible():
    first = fixture_digest()
    assert fixture_digest() == first
    assert len(first) == 64
    for writer in ("left", "right"):
        before, after = bundle(writer, measured=False), bundle(writer, measured=True)
        assert before.source_record.provider == after.source_record.provider
        assert before.source_record.source_entity_id == after.source_record.source_entity_id
        assert before.source_record.source_record_key != after.source_record.source_record_key
        assert before.source_link.created_at == after.source_link.created_at
        assert after.provider_field_presence.supplied_fields == {"core.name", "place.phones"}
        assert after.source_record.imported_at > before.source_record.imported_at
    assert feature_id("left") != feature_id("right")


def test_plan_requires_fresh_clones_and_separates_probe_from_cost():
    value = json.loads(json.dumps(plan()))
    assert value["modes"] == ["serial", "concurrent2"]
    assert value["repetitions"] == 3
    assert value["fresh_seeded_template_clone_per_trial"]
    assert value["operating_access"] is False
    assert value["external_provider_http"] is False
    assert "성능표본 제외" in value["overlap_probe"]
    assert "ARM" in value["limits"][0]


@pytest.mark.parametrize("value", ["other", "", None, True])
def test_unknown_fixture_writer_is_rejected(value):
    with pytest.raises(ValueError, match="unknown fixture writer"):
        bundle(value, measured=True)


def test_overlap_and_cpu_counters_preserve_physical_units():
    assert interval_overlap([(1.0, 3.0), (2.0, 4.0)]) == 1.0
    assert interval_overlap([(1.0, 2.0), (2.1, 4.0)]) == 0
    assert cpu_delta({"cpu_ns": 1_000_000_000}, {"cpu_ns": 2_500_000_000}) == 1.5
    with pytest.raises(RuntimeError):
        cpu_delta({"cpu_ns": 2}, {"cpu_ns": 1})


def _trials():
    return [
        {
            "mode": mode,
            "iteration": iteration,
            "barrier_probe_only": False,
            "state": {"sha256": "a" * 64},
            "elapsed_seconds": 2.0 if mode == "serial" else 1.0,
            "python_cpu_core_seconds": 0.2,
            "pg_cpu_core_seconds": 0.4,
            "python_rss_sample_peak_bytes": 100,
            "pg_memory_sample_peak_bytes": 200,
            "wal_bytes": 42,
        }
        for iteration in (1, 2, 3)
        for mode in ("serial", "concurrent2")
    ]


def test_comparison_keeps_three_samples_and_physical_ratios():
    value = summarize(_trials())
    assert value["concurrent_to_serial_median_ratio"]["elapsed_seconds"] == 0.5
    assert value["concurrent_to_serial_median_ratio"]["pg_cpu_core_seconds"] == 1.0
    assert value["small_input_only"]
    assert value["ratio_is_not_operating_arm_evidence"]


@pytest.mark.parametrize(
    "invalid", ["probe", "partial", "different-output", "duplicate-iteration", "nan", "bool"]
)
def test_comparison_rejects_incomparable_or_invalid_measurements(invalid):
    values = _trials()
    if invalid == "probe":
        values[0]["barrier_probe_only"] = True
    elif invalid == "partial":
        values.pop()
    elif invalid == "different-output":
        values[0]["state"] = {"sha256": "b" * 64}
    elif invalid == "duplicate-iteration":
        values[0]["iteration"] = 2
    else:
        values[0]["elapsed_seconds"] = float("nan") if invalid == "nan" else True
    with pytest.raises(ValueError, match="required|mismatch"):
        summarize(values)
